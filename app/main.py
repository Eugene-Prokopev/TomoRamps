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
    QApplication, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QSlider, QTextEdit,
    QVBoxLayout, QWidget,
)

from tomostage.controller import AXES, GCodeController, TomoStageError

AXIS_TITLES = {
    "X": "X — точная ось",
    "Y": "Y — точная ось",
    "Z": "Z — грубая ось",
    "A": "A — наклон",
    "B": "B — вращение",
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

        central = QWidget()
        root = QVBoxLayout(central)
        top = QHBoxLayout()
        top.addWidget(self._build_connect_box())
        top.addWidget(self._build_jog_box(), 1)
        top.addWidget(self._build_dc_box())
        root.addLayout(top)
        root.addWidget(self._build_console_box())
        self.setCentralWidget(central)
        self.statusBar().showMessage("Не подключено")
        self.endstop_timer = QTimer(self)
        self.endstop_timer.setInterval(500)
        self.endstop_timer.timeout.connect(self.read_endstops)

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

        grid.addWidget(QLabel("Шаг перемещения:"), 0, 0)
        self.step_combo = QComboBox()
        self.step_combo.addItems(STEP_VALUES)
        self.step_combo.setCurrentText("0.1")
        grid.addWidget(self.step_combo, 0, 1)
        grid.addWidget(QLabel("мм / град"), 0, 2)

        grid.addWidget(QLabel("Подача:"), 1, 0)
        self.feed_combo = QComboBox()
        self.feed_combo.addItems(FEED_VALUES)
        self.feed_combo.setCurrentText("60")
        grid.addWidget(self.feed_combo, 1, 1)
        grid.addWidget(QLabel("мм/мин"), 1, 2)

        self.pos_labels: dict[str, QLabel] = {}
        for row, axis in enumerate(AXES, start=3):
            grid.addWidget(QLabel(AXIS_TITLES[axis]), row, 0)
            minus = QPushButton(f"{axis} −")
            plus = QPushButton(f"{axis} +")
            minus.clicked.connect(lambda _=False, a=axis: self.jog(a, -1))
            plus.clicked.connect(lambda _=False, a=axis: self.jog(a, 1))
            grid.addWidget(minus, row, 1)
            grid.addWidget(plus, row, 2)
            pos = QLabel("—")
            pos.setMinimumWidth(100)
            pos.setAlignment(Qt.AlignCenter)
            self.pos_labels[axis] = pos
            grid.addWidget(QLabel("Позиция:"), row, 3)
            grid.addWidget(pos, row, 4)

        read = QPushButton("Прочитать координаты (M114)")
        read.clicked.connect(self.read_pos)
        grid.addWidget(read, len(AXES) + 4, 0, 1, 5)
        return box

    def _build_dc_box(self) -> QGroupBox:
        box = QGroupBox("DC-мотор (пока не использовать)")
        lay = QVBoxLayout(box)
        lay.addWidget(QLabel("L298N подключим позже."))
        self.dc_slider = QSlider(Qt.Horizontal)
        self.dc_slider.setRange(0, 255)
        self.dc_slider.setValue(0)
        self.dc_slider.valueChanged.connect(self.dc_changed)
        lay.addWidget(self.dc_slider)
        self.dc_value = QLabel("0")
        lay.addWidget(self.dc_value)
        self.btn_fwd = QPushButton("Вперёд")
        self.btn_back = QPushButton("Назад")
        self.btn_fwd.clicked.connect(lambda: self.dc_dir(True))
        self.btn_back.clicked.connect(lambda: self.dc_dir(False))
        self.btn_fwd.setEnabled(False)
        self.btn_back.setEnabled(False)
        lay.addWidget(self.btn_fwd)
        lay.addWidget(self.btn_back)
        lay.addStretch()
        return box

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
            self.endstop_timer.stop()
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
        self.read_pos()
        self.read_endstops()
        self.endstop_timer.start()

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
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Сначала подключите плату")
            return
        distance = float(self.step_combo.currentText()) * direction
        feed = int(self.feed_combo.currentText())
        try:
            self.stage.move(axis, distance, feed=feed)
            self.read_pos()
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка движения: {exc}")

    def read_pos(self) -> None:
        if not (self.stage and self.stage.connected):
            return
        try:
            for axis, value in self.stage.get_position().items():
                self.pos_labels[axis].setText(f"{value:.3f}")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка M114: {exc}")

    def read_endstops(self) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Сначала подключите плату")
            return
        try:
            lines = self.stage.endstops()
            text = " ".join(line for line in lines if "x_" in line.lower() or "xmin" in line.lower())
            self.endstop_label.setText("Концевики X: " + (text or "ответ получен; смотрите журнал"))
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка M119: {exc}")

    def dc_changed(self, value: int) -> None:
        self.dc_value.setText(str(value))
        # DC-кнопки отключены до отдельного безопасного теста L298N.

    def dc_dir(self, forward: bool) -> None:
        if self.stage and self.stage.connected:
            self.stage.dc_direction(forward)

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
