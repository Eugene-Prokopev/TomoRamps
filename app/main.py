"""TomoRamps jog-пульт для безопасной поэтапной проверки осей.

Запуск из корня проекта:
    .venv\\Scripts\\python.exe app\\main.py
или двойным щелчком по gui.bat.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QSlider, QTextEdit, QVBoxLayout, QWidget,
)

from tomostage.controller import AXES, GCodeController, TomoStageError

# Порядок строк соответствует физическому столу, а не буквам Marlin.
DISPLAY_AXES = ("X", "Y", "C", "A", "B", "Z")
AXIS_TITLES = {
    "X": "X — точный (X)",
    "Y": "Y — точный (Y)",
    "C": "Z — точный (C)",
    "A": "Вращение (A)",
    "B": "Наклон (B)",
    "Z": "XX — грубый (Z)",
}
STEP_VALUES = ["0.01", "0.1", "1", "10", "100"]
FEED_VALUES = ["30", "60", "120", "300", "600", "1200"]


def list_ports() -> list[str]:
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TomoRamps — Jog-пульт")
        self.resize(900, 520)
        self.stage: GCodeController | None = None
        self.continuous_axis: str | None = None
        self.continuous_direction = 0
        self.continuous_timer = QTimer(self)
        self.continuous_timer.setInterval(120)
        self.continuous_timer.timeout.connect(self._continuous_tick)

        central = QWidget()
        root = QVBoxLayout(central)
        top = QHBoxLayout()
        top.addWidget(self._build_connect_box())
        top.addWidget(self._build_jog_box(), 1)
        # Управление DC/внешней осью отдельным блоком больше не показываем.
        root.addLayout(top)
        root.addWidget(self._build_console_box())
        self.setCentralWidget(central)
        self.statusBar().showMessage("Не подключено")
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self.poll_status)
        self.previous_endstops: tuple[str, ...] | None = None

    def _build_connect_box(self) -> QGroupBox:
        box = QGroupBox("Соединение")
        lay = QVBoxLayout(box)
        self.port_combo = QComboBox()
        self.port_combo.addItems(list_ports())
        if "COM11" in [self.port_combo.itemText(i) for i in range(self.port_combo.count())]:
            self.port_combo.setCurrentText("COM11")
        lay.addWidget(self.port_combo)
        refresh = QPushButton("Обновить порты")
        refresh.clicked.connect(self.refresh_ports)
        lay.addWidget(refresh)
        self.btn_connect = QPushButton("Подключить")
        self.btn_connect.clicked.connect(self.toggle_connect)
        lay.addWidget(self.btn_connect)
        self.btn_m119 = QPushButton("Проверить концевики (M119)")
        self.btn_m119.clicked.connect(self.read_endstops)
        lay.addWidget(self.btn_m119)
        motor_row = QHBoxLayout()
        self.btn_m17 = QPushButton("Моторы ON (M17)")
        self.btn_m18 = QPushButton("Моторы OFF (M18)")
        self.btn_m17.clicked.connect(self.motors_on)
        self.btn_m18.clicked.connect(self.motors_off)
        motor_row.addWidget(self.btn_m17)
        motor_row.addWidget(self.btn_m18)
        lay.addLayout(motor_row)
        estop = QPushButton("АВАР. СТОП (M112)")
        estop.setStyleSheet("background:#c0392b; color:white; font-weight:bold")
        estop.clicked.connect(self.estop)
        lay.addWidget(estop)
        self.endstop_label = QLabel("Концевики: не проверены")
        self.endstop_label.setWordWrap(True)
        lay.addWidget(self.endstop_label)
        lay.addStretch()
        return box

    def _build_jog_box(self) -> QGroupBox:
        box = QGroupBox("Jog-перемещение (относительное, как в Candle)")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Шаг перемещения (свой тоже можно ввести):"), 0, 0)
        self.step_combo = QComboBox()
        self.step_combo.setEditable(True)
        self.step_combo.addItems(STEP_VALUES)
        self.step_combo.setCurrentText("0.1")
        grid.addWidget(self.step_combo, 0, 1)
        grid.addWidget(QLabel("мм / град"), 0, 2)

        grid.addWidget(QLabel("Подача (свою можно ввести):"), 1, 0)
        self.feed_combo = QComboBox()
        self.feed_combo.setEditable(True)
        self.feed_combo.addItems(FEED_VALUES)
        self.feed_combo.setCurrentText("60")
        grid.addWidget(self.feed_combo, 1, 1)
        grid.addWidget(QLabel("мм/мин"), 1, 2)

        grid.addWidget(QLabel("Режим:"), 0, 3)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Один шаг", "Непрерывно при удержании"])
        grid.addWidget(self.mode_combo, 0, 4, 1, 2)

        self.pos_labels: dict[str, QLabel] = {}
        self.endstop_widgets: dict[str, dict[str, QLabel]] = {}
        grid.addWidget(QLabel("Ось / jog"), 2, 0)
        grid.addWidget(QLabel("MIN"), 2, 5)
        grid.addWidget(QLabel("MAX"), 2, 6)
        for row, axis in enumerate(DISPLAY_AXES, start=3):
            grid.addWidget(QLabel(AXIS_TITLES[axis]), row, 0)
            minus = QPushButton(f"{axis} −")
            plus = QPushButton(f"{axis} +")
            minus.clicked.connect(lambda _=False, a=axis: self.jog(a, -1))
            plus.clicked.connect(lambda _=False, a=axis: self.jog(a, 1))
            minus.pressed.connect(lambda a=axis: self.start_continuous(a, -1))
            plus.pressed.connect(lambda a=axis: self.start_continuous(a, 1))
            minus.released.connect(self.stop_continuous)
            plus.released.connect(self.stop_continuous)
            grid.addWidget(minus, row, 1)
            grid.addWidget(plus, row, 2)
            pos = QLabel("—")
            pos.setMinimumWidth(85)
            pos.setAlignment(Qt.AlignCenter)
            self.pos_labels[axis] = pos
            grid.addWidget(QLabel("Позиция:"), row, 3)
            grid.addWidget(pos, row, 4)
            min_led = self._make_endstop_indicator("MIN")
            max_led = self._make_endstop_indicator("MAX")
            self.endstop_widgets[axis] = {"min": min_led, "max": max_led}
            grid.addWidget(min_led, row, 5)
            grid.addWidget(max_led, row, 6)

        read = QPushButton("Прочитать координаты (M114)")
        read.clicked.connect(self.read_pos)
        grid.addWidget(read, len(AXES) + 4, 0, 1, 5)
        return box

    def _build_external_axis_box(self) -> QGroupBox:
        box = QGroupBox("Внешняя точная ось Z")
        lay = QVBoxLayout(box)
        lay.addWidget(QLabel("C = TB6600; STEP/DIR/EN через Mega"))
        lay.addWidget(QLabel("Управление: кнопки C− / C+ слева"))
        lay.addWidget(QLabel("Пока без HOME: концевик C не подключён"))
        lay.addStretch()
        return box

    def _make_endstop_indicator(self, name: str) -> QLabel:
        label = QLabel(name)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumWidth(48)
        label.setToolTip("Серый = open / не сработал; красный = TRIGGERED")
        self._set_endstop_indicator(label, False, "нет данных")
        return label

    @staticmethod
    def _set_endstop_indicator(label: QLabel, triggered: bool, state: str) -> None:
        color = "#d9534f" if triggered else "#777777"
        label.setText(state.upper())
        label.setStyleSheet(
            f"background-color:{color}; color:white; padding:3px; "
            "border-radius:3px; font-weight:bold;"
        )

    def _build_console_box(self) -> QGroupBox:
        box = QGroupBox("Консоль Marlin и журнал обмена")
        lay = QVBoxLayout(box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        self.log_view.setPlaceholderText("Здесь будут команды и ответы платы...")
        lay.addWidget(self.log_view)
        row = QHBoxLayout()
        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText("Введите G-code, например M114 или M119")
        self.command_edit.returnPressed.connect(self.send_console_command)
        row.addWidget(self.command_edit, 1)
        send = QPushButton("Отправить")
        send.clicked.connect(self.send_console_command)
        row.addWidget(send)
        clear = QPushButton("Очистить")
        clear.clicked.connect(self.log_view.clear)
        row.addWidget(clear)
        lay.addLayout(row)
        return box

    def append_log(self, text: str) -> None:
        self.log_view.append(text)

    def send_console_command(self) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Сначала подключите плату")
            return
        command = self.command_edit.text().strip()
        if not command:
            return
        try:
            self.stage.send(command)
        except TomoStageError as exc:
            self.append_log(f"!!! {exc}")
        finally:
            self.command_edit.clear()

    def refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        self.port_combo.addItems(list_ports())
        if current:
            self.port_combo.setCurrentText(current)

    def toggle_connect(self) -> None:
        if self.stage and self.stage.connected:
            self.status_timer.stop()
            self.stage.close()
            self.btn_connect.setText("Подключить")
            self.statusBar().showMessage("Отключено")
            return
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Нет порта", "Выберите COM-порт")
            return
        self.stage = GCodeController(port, log_callback=self.append_log)
        try:
            self.stage.connect()
        except TomoStageError as exc:
            QMessageBox.critical(self, "Ошибка подключения", str(exc))
            self.stage = None
            return
        self.btn_connect.setText("Отключить")
        self.statusBar().showMessage(f"Подключено: {port}")
        self.read_pos(log=False)
        self.read_endstops(log=False)
        self.status_timer.start()

    def motors_on(self) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Сначала подключите плату")
            return
        try:
            self.stage.motors_on()
            self.statusBar().showMessage("M17: драйверы включены; проверьте удерживающий момент X")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка M17: {exc}")

    def motors_off(self) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Сначала подключите плату")
            return
        try:
            self.stage.motors_off()
            self.statusBar().showMessage("M18: драйверы отключены")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка M18: {exc}")

    def jog(self, axis: str, direction: int) -> None:
        if self.mode_combo.currentIndex() == 1:
            return
        self._move_once(axis, direction)

    def _move_once(self, axis: str, direction: int) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Сначала подключите плату")
            return
        try:
            distance = float(self.step_combo.currentText()) * direction
            feed = int(float(self.feed_combo.currentText()))
            if distance == 0 or feed <= 0:
                raise ValueError("шаг и подача должны быть больше нуля")
            self.stage.move(axis, distance, feed=feed)
            self.read_pos()
        except (TomoStageError, ValueError) as exc:
            self.statusBar().showMessage(f"Ошибка движения: {exc}")

    def start_continuous(self, axis: str, direction: int) -> None:
        if self.mode_combo.currentIndex() != 1:
            return
        self.continuous_axis = axis
        self.continuous_direction = direction
        self._continuous_tick()
        self.continuous_timer.start()

    def stop_continuous(self) -> None:
        self.continuous_timer.stop()
        self.continuous_axis = None
        self.continuous_direction = 0

    def _continuous_tick(self) -> None:
        if self.continuous_axis:
            self._move_once(self.continuous_axis, self.continuous_direction)

    def read_pos(self, log: bool = True) -> None:
        if not (self.stage and self.stage.connected):
            return
        try:
            for axis, value in self.stage.get_position(log=log).items():
                self.pos_labels[axis].setText(f"{value:.3f}")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка M114: {exc}")

    def read_endstops(self, log: bool = True) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Сначала подключите плату")
            return
        try:
            lines = self.stage.endstops(log=log)
            states = tuple(line.strip() for line in lines if ":" in line and any(
                name in line.lower() for name in (
                    "x_min", "x_max", "y_min", "y_max", "z_min", "z_max",
                    "a_min", "a_max", "b_min", "b_max", "c_min", "c_max",
                    "i_min", "i_max", "j_min", "j_max", "k_min", "k_max"
                )
            ))
            for line in states:
                name, value = line.split(":", 1)
                parts = name.strip().lower().split("_")
                if len(parts) != 2:
                    continue
                axis = {"i": "A", "j": "B", "k": "C"}.get(parts[0], parts[0].upper())
                side = parts[1]
                if axis in self.endstop_widgets and side in ("min", "max"):
                    triggered = "triggered" in value.lower()
                    self._set_endstop_indicator(
                        self.endstop_widgets[axis][side], triggered, value.strip()
                    )
            x_text = " ".join(line for line in states if "x_" in line.lower())
            self.endstop_label.setText("Концевики X: " + (x_text or "ответ получен"))
            if states != self.previous_endstops:
                self.previous_endstops = states
                self.append_log("[концевики изменились] " + (" | ".join(states) or "нет данных"))
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка M119: {exc}")

    def poll_status(self) -> None:
        """Периодически обновлять позицию и концевики без лишнего журнала."""
        if not (self.stage and self.stage.connected):
            return
        self.read_pos(log=False)
        self.read_endstops(log=False)

    def dc_changed(self, value: int) -> None:
        self.dc_value.setText(f"{value}/255 ({value / 255 * 100:.0f}%)")

    def dc_run(self, forward: bool) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Сначала подключите плату")
            return
        try:
            self.stage.dc_run(forward, self.dc_slider.value())
            self.statusBar().showMessage("DC: вращение " + ("вперёд" if forward else "назад"))
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка DC: {exc}")

    def dc_stop(self) -> None:
        if self.stage and self.stage.connected:
            try:
                self.stage.dc_stop()
                self.statusBar().showMessage("DC остановлен")
            except TomoStageError as exc:
                self.statusBar().showMessage(f"Ошибка остановки DC: {exc}")

    def estop(self) -> None:
        if self.stage and self.stage.connected:
            self.stage.emergency_stop()
        self.statusBar().showMessage("M112 отправлен")


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
