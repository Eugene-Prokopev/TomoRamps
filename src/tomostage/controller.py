"""G-code контроллер предметного стола томографа.

Связь с Arduino Mega (Marlin 2.1.x) по последовательному порту.
Оси проекта: X, Y — точные (микровинты), Z — грубая (направляющая 1 м),
I — наклон, J — вращение (слоты E0/E1). DC-мотор: M106/M107 + M42.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Callable, Dict, Optional

AXES = ("X", "Y", "Z", "A", "B")
DEFAULT_BAUD = 250000


class TomoStageError(RuntimeError):
    """Ошибка связи или отказа прошивки."""


class GCodeController:
    """Мини-клиент G-code: отправка команд, парсинг ответов, перемещения."""

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUD,
                 timeout: float = 3.0,
                 serial_factory: Optional[Callable] = None,
                 log_callback: Optional[Callable[[str], None]] = None) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = None
        self._lock = threading.Lock()
        self._factory = serial_factory
        self._log_callback = log_callback

    def _log(self, text: str) -> None:
        if self._log_callback:
            self._log_callback(text)

    # --- соединение -------------------------------------------------
    def connect(self) -> None:
        if self._serial is not None:
            raise TomoStageError("Уже подключено")
        ser = self._factory(self.port, self.baudrate, self.timeout) \
            if self._factory else self._open_pyserial()
        try:
            ser.open()
        except Exception as exc:  # noqa: BLE001
            raise TomoStageError(f"Не удалось открыть {self.port}: {exc}") from exc
        self._serial = ser
        # Открытие USB-порта обычно вызывает reset Mega. Даём Marlin
        # завершить запуск и очищаем стартовый текст перед G-code.
        time.sleep(2.0)
        self._serial.reset_input_buffer()
        self.send("M110 N0")     # сброс нумерации строк
        self.send("G90")         # абсолютные координаты
        self.send("M82")         # экструдер в абсолют (для единообразия)

    def _open_pyserial(self):
        import serial  # локальный импорт: тестам pyserial не нужен
        # Создаём закрытый объект с настроенным COM-портом, затем connect()
        # вызывает open(). Serial() без port приводил к ошибке "Port must be configured".
        ser = serial.Serial(port=None, baudrate=self.baudrate,
                            timeout=self.timeout)
        ser.port = self.port
        return ser

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    @property
    def connected(self) -> bool:
        return self._serial is not None

    def __enter__(self) -> "GCodeController":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- обмен ------------------------------------------------------
    def send(self, command: str, wait_ok: bool = True) -> list[str]:
        """Отправить команду, вернуть список информационных строк ответа."""
        if self._serial is None:
            raise TomoStageError("Нет соединения")
        with self._lock:
            command = command.strip()
            self._log(f">>> {command}")
            self._serial.reset_input_buffer()
            self._serial.write((command + "\n").encode("ascii"))
            if not wait_ok:
                return []
            info: list[str] = []
            deadline = self.timeout * 4
            waited = 0.0
            step = 0.02
            while waited < deadline:
                raw = self._serial.readline()
                if not raw:
                    waited += step
                    continue
                line = raw.decode("ascii", errors="replace").strip()
                self._log(f"<<< {line}")
                waited = 0.0
                if not line or line == "ok":
                    if line == "ok":
                        return info
                    continue
                if line.startswith("Error:") or line.startswith("echo:"):
                    if line.startswith("Error:"):
                        info.append(line)
                        raise TomoStageError(f"Плата: {line}")
                    continue
                info.append(line)
            raise TomoStageError(f"Таймаут ответа на '{command}'")

    # --- команды уровня стола ---------------------------------------
    def get_position(self) -> Dict[str, float]:
        """M114 -> {'X': .., 'Y': .., 'Z': .., 'I': .., 'J': ..}."""
        resp = self.send("M114")
        text = " ".join(resp)
        out: Dict[str, float] = {}
        for ax in AXES:
            m = re.search(rf"\b{ax}:(-?\d+\.?\d*)", text)
            if m:
                out[ax] = float(m.group(1))
        if len(out) != len(AXES):
            raise TomoStageError(f"Не распарсены координаты: {text!r}")
        return out

    def move(self, axis: str, distance: float, feed: Optional[int] = None) -> None:
        """Относительное перемещение по одной оси."""
        if axis not in AXES:
            raise ValueError(f"Ось должна быть из {AXES}, получено {axis!r}")
        self.send("G91")
        cmd = f"G1 {axis}{distance:.4f}"
        if feed:
            cmd += f" F{int(feed)}"
        self.send(cmd)
        self.send("G90")  # вернулись в абсолют

    def home(self, axes: str = "XYZAB") -> None:
        bad = set(axes.upper()) - set(AXES)
        if bad:
            raise ValueError(f"Неизвестные оси: {bad}")
        self.send("G28 " + " ".join(axes.upper()))

    def motors_on(self) -> None:
        """Включить силовые выходы шаговых драйверов."""
        self.send("M17")

    def motors_off(self) -> None:
        """Отключить силовые выходы шаговых драйверов."""
        self.send("M18")

    def emergency_stop(self) -> None:
        self.send("M112", wait_ok=False)

    def dc_speed(self, value_0_255: int) -> None:
        """Скорость DC-мотора (ШИМ на D9/ENA L298N). Направление задаётся отдельно."""
        v = max(0, min(255, int(value_0_255)))
        self.send(f"M106 S{v}" if v else "M107")

    def dc_direction(self, forward: bool) -> None:
        """Направление DC-мотора: IN1=D11, IN2=D6."""
        self.send(f"M42 P11 S{1 if forward else 0}")
        self.send(f"M42 P6 S{0 if forward else 1}")

    def endstops(self) -> list[str]:
        return self.send("M119")

    def firmware_info(self) -> str:
        return " ".join(self.send("M115"))
