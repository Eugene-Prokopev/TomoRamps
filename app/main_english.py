"""TomoRamps jog controller for safe step-by-step axis testing.

Run from the project root:
    .venv\\Scripts\\python.exe app\\main.py
or by double-clicking gui.bat.
"""
from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QSlider, QTextEdit, QVBoxLayout, QWidget,
)

from tomostage.controller import AXES, GCodeController, TomoStageError

# Row order follows the physical table, not the Marlin letters.
DISPLAY_AXES = ("X", "Y", "C", "A", "B", "Z")
AXIS_TITLES = {
    "X": "X — precision (X)",
    "Y": "Y — precision (Y)",
    "C": "Z — precision (C)",
    "A": "Rotation (A)",
    "B": "Tilt (B)",
    "Z": "XX — coarse (Z)",
}
STEP_VALUES = ["0.01", "0.1", "1", "10", "100"]
FEED_VALUES = ["30", "60", "120", "300", "600", "1200"]


def parse_user_float(value: str) -> float:
    text = str(value).strip().replace(",", ".")
    if not text:
        raise ValueError("number cannot be empty")
    return float(text)


def list_ports() -> list[str]:
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


class ConsoleWorker(QThread):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, stage: GCodeController, command: str, timeout: float = 60.0) -> None:
        super().__init__()
        self.stage = stage
        self.command = command
        self.timeout = timeout

    def run(self) -> None:
        try:
            lines = self.stage.send(self.command, timeout_seconds=self.timeout)
            self.done.emit(lines)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class JogWorker(QThread):
    failed = Signal(str)

    def __init__(self, stage: GCodeController, axis: str, direction: int,
                 step: float, feed: float, blocked) -> None:
        super().__init__()
        self.stage = stage
        self.axis = axis
        self.direction = direction
        self.step = step
        self.feed = feed
        self.blocked = blocked
        self.stop_requested = False

    def request_stop(self) -> None:
        self.stop_requested = True

    def run(self) -> None:
        try:
            while not self.stop_requested:
                if self.blocked(self.axis, self.direction):
                    break
                self.stage.move(self.axis, self.step * self.direction, feed=self.feed)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    log_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TomoRamps — Jog Controller")
        self.resize(900, 520)
        self.stage: GCodeController | None = None
        self.console_worker: ConsoleWorker | None = None
        self.log_signal.connect(self.append_log)
        self.continuous_axis: str | None = None
        self.continuous_direction = 0
        self.jog_worker: JogWorker | None = None

        central = QWidget()
        root = QVBoxLayout(central)
        top = QHBoxLayout()
        top.addWidget(self._build_connect_box())
        top.addWidget(self._build_jog_box(), 1)
        # DC/external-axis controls are intentionally not shown as a separate block.
        root.addLayout(top)
        root.addWidget(self._build_console_box())
        self.setCentralWidget(central)
        self.statusBar().showMessage("Disconnected")
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self.poll_status)
        self.previous_endstops: tuple[str, ...] | None = None
        # None = state not received yet; True = TRIGGERED; False = open.
        self.endstop_state: dict[tuple[str, str], bool | None] = {
            (axis, side): None
            for axis in AXES
            for side in ("min", "max")
        }

    def _build_connect_box(self) -> QGroupBox:
        box = QGroupBox("Connection")
        lay = QVBoxLayout(box)
        self.port_combo = QComboBox()
        self.port_combo.addItems(list_ports())
        if "COM11" in [self.port_combo.itemText(i) for i in range(self.port_combo.count())]:
            self.port_combo.setCurrentText("COM11")
        lay.addWidget(self.port_combo)
        refresh = QPushButton("Refresh ports")
        refresh.clicked.connect(self.refresh_ports)
        lay.addWidget(refresh)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.toggle_connect)
        lay.addWidget(self.btn_connect)
        self.btn_m119 = QPushButton("Check endstops (M119)")
        self.btn_m119.clicked.connect(self.read_endstops)
        lay.addWidget(self.btn_m119)
        motor_row = QHBoxLayout()
        self.btn_m17 = QPushButton("Motors ON (M17)")
        self.btn_m18 = QPushButton("Motors OFF (M18)")
        self.btn_m17.clicked.connect(self.motors_on)
        self.btn_m18.clicked.connect(self.motors_off)
        motor_row.addWidget(self.btn_m17)
        motor_row.addWidget(self.btn_m18)
        lay.addLayout(motor_row)
        estop = QPushButton("EMERGENCY STOP (M112)")
        estop.setStyleSheet("background:#c0392b; color:white; font-weight:bold")
        estop.clicked.connect(self.estop)
        lay.addWidget(estop)
        quick = QPushButton("Quick motion stop (M410)")
        quick.setStyleSheet("background:#e67e22; color:white; font-weight:bold")
        quick.clicked.connect(self.quick_stop)
        lay.addWidget(quick)
        self.endstop_label = QLabel("Endstops: not checked")
        self.endstop_label.setWordWrap(True)
        lay.addWidget(self.endstop_label)
        lay.addStretch()
        return box

    def _build_jog_box(self) -> QGroupBox:
        box = QGroupBox("Jog movement (relative, like Candle)")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Movement step (custom value allowed):"), 0, 0)
        self.step_combo = QComboBox()
        self.step_combo.setEditable(True)
        self.step_combo.addItems(STEP_VALUES)
        self.step_combo.setCurrentText("0.1")
        grid.addWidget(self.step_combo, 0, 1)
        grid.addWidget(QLabel("mm / deg"), 0, 2)

        grid.addWidget(QLabel("Feed rate (custom value allowed):"), 1, 0)
        self.feed_combo = QComboBox()
        self.feed_combo.setEditable(True)
        self.feed_combo.addItems(FEED_VALUES)
        self.feed_combo.setCurrentText("60")
        grid.addWidget(self.feed_combo, 1, 1)
        grid.addWidget(QLabel("mm/min"), 1, 2)

        grid.addWidget(QLabel("Mode:"), 0, 3)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Single step", "Continuous while held"])
        grid.addWidget(self.mode_combo, 0, 4, 1, 2)

        self.pos_labels: dict[str, QLabel] = {}
        self.endstop_widgets: dict[str, dict[str, QLabel]] = {}
        grid.addWidget(QLabel("Axis / jog"), 2, 0)
        grid.addWidget(QLabel("MIN"), 2, 5)
        grid.addWidget(QLabel("MAX"), 2, 6)
        grid.addWidget(QLabel("Zero"), 2, 7)
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
            grid.addWidget(QLabel("Position:"), row, 3)
            grid.addWidget(pos, row, 4)
            min_led = self._make_endstop_indicator("MIN")
            max_led = self._make_endstop_indicator("MAX")
            self.endstop_widgets[axis] = {"min": min_led, "max": max_led}
            grid.addWidget(min_led, row, 5)
            grid.addWidget(max_led, row, 6)
            zero = QPushButton("Zero")
            zero.setToolTip(f"G92 {axis}0 — set current {axis} coordinate to zero")
            zero.clicked.connect(lambda _=False, a=axis: self.set_zero(a))
            grid.addWidget(zero, row, 7)

        read = QPushButton("Read coordinates (M114)")
        read.clicked.connect(self.read_pos)
        grid.addWidget(read, len(AXES) + 4, 0, 1, 5)
        return box

    def _build_external_axis_box(self) -> QGroupBox:
        box = QGroupBox("External precision Z axis")
        lay = QVBoxLayout(box)
        lay.addWidget(QLabel("C = TB6600; STEP/DIR/EN via Mega"))
        lay.addWidget(QLabel("Control: C− / C+ buttons on the left"))
        lay.addWidget(QLabel("No HOME yet: C endstop is not connected"))
        lay.addStretch()
        return box

    def _make_endstop_indicator(self, name: str) -> QLabel:
        label = QLabel(name)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumWidth(48)
        label.setToolTip("Gray = open / not triggered; red = TRIGGERED")
        self._set_endstop_indicator(label, False, "no data")
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
        box = QGroupBox("Marlin console and communication log")
        lay = QVBoxLayout(box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        self.log_view.setPlaceholderText("Board commands and responses will appear here...")
        lay.addWidget(self.log_view)
        row = QHBoxLayout()
        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText("Enter G-code, for example M114 or M119")
        self.command_edit.returnPressed.connect(self.send_console_command)
        row.addWidget(self.command_edit, 1)
        send = QPushButton("Send")
        send.clicked.connect(self.send_console_command)
        row.addWidget(send)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.log_view.clear)
        row.addWidget(clear)
        lay.addLayout(row)
        return box

    def append_log(self, text: str) -> None:
        self.log_view.append(text)
        try:
            log_path = Path(__file__).resolve().parents[1] / "logs" / "serial.log"
            log_path.parent.mkdir(exist_ok=True)
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(text + "\n")
        except OSError:
            pass

    def send_console_command(self) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Connect to the board first")
            return
        command = self.command_edit.text().strip()
        if not command:
            return
        if self.console_worker and self.console_worker.isRunning():
            self.statusBar().showMessage("The previous command is still running")
            return
        self.command_edit.clear()
        self.command_edit.setEnabled(False)
        timeout = 90.0 if command.upper().startswith("G28") else 20.0
        self.console_worker = ConsoleWorker(self.stage, command, timeout)
        self.console_worker.done.connect(self.console_command_done)
        self.console_worker.failed.connect(self.console_command_failed)
        self.console_worker.finished.connect(lambda: self.command_edit.setEnabled(True))
        self.console_worker.start()

    def console_command_done(self, lines: list[str]) -> None:
        self.statusBar().showMessage("Command completed")
        if any(line.lower().startswith("g28") for line in lines):
            self.read_pos(log=False)
            self.read_endstops(log=False)

    def console_command_failed(self, message: str) -> None:
        self.append_log(f"!!! {message}")
        self.statusBar().showMessage("Command failed; see the log for details")

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
            self.btn_connect.setText("Connect")
            self.statusBar().showMessage("Disconnected")
            return
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "No port", "Select a COM port")
            return
        self.stage = GCodeController(port, log_callback=self.log_signal.emit)
        try:
            self.stage.connect()
        except TomoStageError as exc:
            QMessageBox.critical(self, "Connection error", str(exc))
            self.stage = None
            return
        self.btn_connect.setText("Disconnect")
        self.statusBar().showMessage(f"Connected: {port}")
        self.read_pos(log=False)
        self.read_endstops(log=False)
        self.status_timer.start()

    def set_zero(self, axis: str) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Connect to the board first")
            return
        try:
            self.stage.set_zero(axis)
            self.read_pos()
            self.statusBar().showMessage(f"Axis {axis} zeroed with G92")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"Zeroing error: {exc}")

    def motors_on(self) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Connect to the board first")
            return
        try:
            self.stage.motors_on()
            self.statusBar().showMessage("M17: drivers enabled; check X holding torque")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"M17 error: {exc}")

    def motors_off(self) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Connect to the board first")
            return
        try:
            self.stage.motors_off()
            self.statusBar().showMessage("M18: drivers disabled")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"M18 error: {exc}")

    def jog(self, axis: str, direction: int) -> None:
        if self.mode_combo.currentIndex() == 1:
            return
        self._move_once(axis, direction)

    def _move_once(self, axis: str, direction: int) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Connect to the board first")
            return
        side = "max" if direction > 0 else "min"
        if self.endstop_state.get((axis, side)) is True:
            self.stop_continuous()
            self.statusBar().showMessage(f"Movement blocked: {axis}_{side} is triggered")
            return
        try:
            distance = parse_user_float(self.step_combo.currentText()) * direction
            feed = parse_user_float(self.feed_combo.currentText())
            if distance == 0 or feed <= 0:
                raise ValueError("step and feed must be greater than zero")
            self.stage.move(axis, distance, feed=feed)
            self.read_pos()
        except (TomoStageError, ValueError) as exc:
            self.statusBar().showMessage(f"Movement error: {exc}")

    def start_continuous(self, axis: str, direction: int) -> None:
        if self.mode_combo.currentIndex() != 1:
            return
        if self.jog_worker and self.jog_worker.isRunning():
            return
        if self._direction_blocked(axis, direction):
            side = "max" if direction > 0 else "min"
            self.statusBar().showMessage(f"Movement blocked: {axis}_{side} is triggered")
            return
        self.continuous_axis = axis
        self.continuous_direction = direction
        # Continuous mode always uses a short segment so releasing
        # the button does not wait for a large selected step to finish (for example 10 mm).
        continuous_step = min(abs(self._step_value()), 0.1)
        self.jog_worker = JogWorker(
            self.stage, axis, direction, continuous_step, self._feed_value(),
            self._direction_blocked,
        )
        self.jog_worker.failed.connect(lambda msg: self.append_log(f"!!! jog: {msg}"))
        self.jog_worker.start()

    def stop_continuous(self) -> None:
        if self.jog_worker and self.jog_worker.isRunning():
            self.jog_worker.request_stop()
        self.continuous_axis = None
        self.continuous_direction = 0

    def _direction_blocked(self, axis: str, direction: int) -> bool:
        side = "max" if direction > 0 else "min"
        return self.endstop_state.get((axis, side)) is True

    def _step_value(self) -> float:
        return parse_user_float(self.step_combo.currentText())

    def _feed_value(self) -> float:
        return parse_user_float(self.feed_combo.currentText())

    def read_pos(self, log: bool = True) -> None:
        if not (self.stage and self.stage.connected):
            return
        try:
            for axis, value in self.stage.get_position(log=log).items():
                self.pos_labels[axis].setText(f"{value:.3f}")
        except TomoStageError as exc:
            self.statusBar().showMessage(f"M114 error: {exc}")

    def read_endstops(self, log: bool = True) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Connect to the board first")
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
            self.endstop_label.setText("X endstops: " + (x_text or "response received"))
            for line in states:
                match = re.match(r"^([a-z]+)_(min|max):\s*(open|triggered)", line.lower())
                if not match:
                    continue
                raw_axis, side, raw_state = match.groups()
                axis = {"k": "C", "c": "C"}.get(raw_axis, raw_axis.upper())
                if axis not in AXES:
                    continue
                self.endstop_state[(axis, side)] = raw_state == "triggered"
                widget = self.endstop_widgets.get(axis, {}).get(side)
                if widget:
                    self._set_endstop_indicator(widget, raw_state == "triggered", raw_state)

            if states != self.previous_endstops:
                self.previous_endstops = states
                self.append_log("[endstops changed] " + (" | ".join(states) or "no data"))

            # If continuous jog reached an active endstop, immediately
            # stop sending further segments.
            if self.continuous_axis and self.continuous_direction:
                side = "max" if self.continuous_direction > 0 else "min"
                if self.endstop_state.get((self.continuous_axis, side)) is True:
                    self.stop_continuous()
        except TomoStageError as exc:
            self.statusBar().showMessage(f"M119 error: {exc}")

    def poll_status(self) -> None:
        """Periodically update position and endstops without extra log entries."""
        if not (self.stage and self.stage.connected):
            return
        self.read_pos(log=False)
        self.read_endstops(log=False)

    def dc_changed(self, value: int) -> None:
        self.dc_value.setText(f"{value}/255 ({value / 255 * 100:.0f}%)")

    def dc_run(self, forward: bool) -> None:
        if not (self.stage and self.stage.connected):
            self.statusBar().showMessage("Connect to the board first")
            return
        try:
            self.stage.dc_run(forward, self.dc_slider.value())
            self.statusBar().showMessage("DC: rotation " + ("forward" if forward else "reverse"))
        except TomoStageError as exc:
            self.statusBar().showMessage(f"DC error: {exc}")

    def dc_stop(self) -> None:
        if self.stage and self.stage.connected:
            try:
                self.stage.dc_stop()
                self.statusBar().showMessage("DC stopped")
            except TomoStageError as exc:
                self.statusBar().showMessage(f"Stop error: {exc}")

    def quick_stop(self) -> None:
        self.stop_continuous()
        try:
            if self.stage:
                self.stage.quick_stop()
            self.statusBar().showMessage("M410 sent: motion stopped")
        except Exception as exc:
            self.append_log(f"!!! quick stop: {type(exc).__name__}: {exc}")

    def estop(self) -> None:
        self.stop_continuous()
        try:
            if self.stage:
                self.stage.emergency_stop()
            self.statusBar().showMessage("M112 sent — Marlin restart required")
        except Exception as exc:
            self.append_log(f"!!! emergency stop: {type(exc).__name__}: {exc}")

    def closeEvent(self, event) -> None:
        self.stop_continuous()
        if self.console_worker and self.console_worker.isRunning():
            self.console_worker.wait(2000)
        if self.stage:
            self.stage.close()
        event.accept()


def _write_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    try:
        path = Path(__file__).resolve().parents[1] / "logs" / "crash.log"
        path.parent.mkdir(exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            traceback.print_exception(exc_type, exc_value, exc_tb, file=stream)
    finally:
        sys.__excepthook__(exc_type, exc_value, exc_tb)


def main() -> int:
    sys.excepthook = _write_uncaught_exception
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
