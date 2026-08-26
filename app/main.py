"""Тестовое приложение оператора: подключение к плате + jog 5 осей + DC-мотор.

Запуск: .venv\\Scripts\\python app\\main.py
Осторожно: кнопки двигают реальные моторы. E-STOP отправляет M112.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from tomostage.controller import AXES, GCodeController, TomoStageError

AXIS_TITLES = {
    "X": "X — точная (микровинт)",
    "Y": "Y — точная (микровинт)",
    "Z": "Z — грубая (1 м)",
    "I": "I — наклон",
    "J": "J — вращение",
}


def list_ports() -> list[str]:
    try:
        from serial.tools import list_ports as lp
        return [p.device for p in lp.comports()]
    except Exception:
        return []


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TomoRamps — пульт стола (тестовый)")
        self.stage: GCodeController | None = None

        central = QWidget()
        root = QHBoxLayout(central)
        root.addWidget(self._build_connect_box())
        root.addWidget(self._build_jog_box())
        root.addWidget(self._build_dc_box())
        self.setCentralWidget(central)
        self.statusBar().showMessage("Не подключено")

    # --- левая колонка: соединение ---------------------------------
    def _build_connect_box(self) -> QGroupBox:
        box = QGroupBox("Соединение")
        lay = QVBoxLayout(box)
        self.port_combo = QComboBox()
        self.port_combo.addItems(list_ports())
        lay.addWidget(self.port_combo)
        btn_refresh = QPushButton("Обновить порты")
        btn_refresh.clicked.connect(self.refresh_ports)
        lay.addWidget(btn_refresh)
        self.btn_connect = QPushButton("Подключить")
        self.btn_connect.clicked.connect(self.toggle_connect)
        lay.addWidget(self.btn_connect)
        btn_estop = QPushButton("АВАР. СТОП (M112)")
        btn_estop.setStyleSheet("background:#c0392b; color:white; font-weight:bold")
        btn_estop.clicked.connect(self.estop)
        lay.addWidget(btn_estop)
        lay.addStretch()
        return box

    # --- центр: джойстик --------------------------------------------
    def _build_jog_box(self) -> QGroupBox:
        box = QGroupBox("Перемещение (относительное)")
        grid = QGridLayout(box)
        self.step = QDoubleSpinBox()
        self.step.setRange(0.001, 100.0)
        self.step.setValue(1.0)
        self.step.setDecimals(3)
        self.step.setSuffix(" мм/град")
        grid.addWidget(QLabel("Шаг:"), 0, 0)
        grid.addWidget(self.step, 0, 1, 1, 5)
        self.pos_labels: dict[str, QLabel] = {}
        for row, ax in enumerate(AXES, start=1):
            grid.addWidget(QLabel(AXIS_TITLES[ax]), row, 0)
            for col, mul in enumerate((-10, -1, -0.1, 0.1, 1, 10), start=1):
                btn = QPushButton(f"{'−' if mul < 0 else '+'}{abs(mul):g}")
                btn.clicked.connect(lambda _=False, a=ax, m=mul: self.jog(a, m))
                grid.addWidget(btn, row, col)
            pos = QLabel("—")
            pos.setAlignment(Qt.AlignCenter)
            self.pos_labels[ax] = pos
            grid.addWidget(pos, row, 7)
        btn_read = QPushButton("Прочитать координаты (M114)")
        btn_read.clicked.connect(self.read_pos)
        grid.addWidget(btn_read, len(AXES) + 1, 0, 1, 8)
        return box

    # --- правая колонка: DC-мотор -----------------------------------
    def _build_dc_box(self) -> QGroupBox:
        box = QGroupBox("DC-мотор (точная Z, L298N)")
        lay = QVBoxLayout(box)
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
        lay.addWidget(self.btn_fwd)
        lay.addWidget(self.btn_back)
        self.dc_dir_state = True
        lay.addStretch()
        return box

    # --- слоты -------------------------------------------------------
    def refresh_ports(self) -> None:
        self.port_combo.clear()
        self.port_combo.addItems(list_ports())

    def toggle_connect(self) -> None:
        if self.stage and self.stage.connected:
            self.stage.close()
            self.btn_connect.setText("Подключить")
            self.statusBar().showMessage("Отключено")
            return
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Нет порта", "Выберите COM-порт")
            return
        self.stage = GCodeController(port)
        try:
            self.stage.connect()
        except TomoStageError as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))
            return
        self.btn_connect.setText("Отключить")
        self.statusBar().showMessage(f"Подключено: {port}")
        self.read_pos()

    def jog(self, axis: str, mult: float) -> None:
        if not (self.stage and self.stage.connected):
            return
        try:
            self.stage.move(axis, self.step.value() * mult, feed=600)
            self.read_pos()
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка: {exc}")

    def read_pos(self) -> None:
        if not (self.stage and self.stage.connected):
            return
        try:
            for ax, val in self.stage.get_position().items():
                self.pos_labels[ax].setText(f"{val:.2f}")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Ошибка: {exc}")

    def dc_changed(self, value: int) -> None:
        self.dc_value.setText(str(value))
        if self.stage and self.stage.connected:
            try:
                self.stage.dc_speed(value)
            except TomoStageError as exc:
                self.statusBar().showMessage(f"Ошибка: {exc}")

    def dc_dir(self, forward: bool) -> None:
        self.dc_dir_state = forward
        if self.stage and self.stage.connected:
            try:
                self.stage.dc_direction(forward)
            except TomoStageError as exc:
                self.statusBar().showMessage(f"Ошибка: {exc}")

    def estop(self) -> None:
        if self.stage and self.stage.connected:
            self.stage.emergency_stop()
        self.statusBar().showMessage("M112 отправлен!")


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
