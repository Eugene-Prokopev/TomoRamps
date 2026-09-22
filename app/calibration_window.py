from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


# ВАЖНО: это именно текущая физическая раскладка TomoRamps.
# Никакие подключения/буквы осей здесь не переопределяются.
DISPLAY_AXES = ("X", "Y", "C", "A", "B", "Z")
AXIS_TITLES = {
    "X": "X — точный (X)",
    "Y": "Y — точный (Y)",
    "C": "Z — точный (C)",
    "A": "Вращение (A)",
    "B": "Наклон (B)",
    "Z": "XX — грубый (Z)",
}
AXIS_UNITS = {"X": "мм", "Y": "мм", "C": "мм", "A": "°", "B": "°", "Z": "мм"}
# По текущему описанию концевики есть на X, Y, Z(грубый X), C(точный Z).
AXIS_HAS_HOME = {"X": True, "Y": True, "C": True, "A": False, "B": False, "Z": True}

# Marlin может печатать дополнительные оси как I/J/K.
M503_AXIS_MAP = {"I": "A", "J": "B", "K": "C"}


def parse_m503_steps(lines: list[str]) -> dict[str, float]:
    """Parse M503/M92 output from Marlin 2.x."""
    result: dict[str, float] = {}
    text = "\n".join(str(line).replace("\r", " ") for line in lines)
    chunks: list[str] = []
    for line in text.splitlines():
        match = re.search(r"\bM92\b(.*)$", line, flags=re.IGNORECASE)
        if match:
            chunks.append(match.group(1))
        elif "STEPS PER UNIT" in line.upper():
            chunks.append(line.split(":", 1)[-1])
    if not chunks and "M92" in text.upper():
        chunks.append(text)
    for tail in chunks:
        for raw_axis, raw_value in re.findall(
            r"(?<![A-Z])([XYZABCIJK])\s*[:=]?\s*(-?(?:\d+(?:\.\d*)?|\.\d+))",
            tail,
            flags=re.IGNORECASE,
        ):
            axis = M503_AXIS_MAP.get(raw_axis.upper(), raw_axis.upper())
            if axis in DISPLAY_AXES:
                result[axis] = float(raw_value)
    return result


class CalibrationWindow(QDialog):
    """Калибровка шести осей через уже открытый GCodeController.

    Окно НЕ открывает Serial-порт самостоятельно и НЕ меняет разводку моторов.
    """

    def __init__(self, stage, parent=None) -> None:
        super().__init__(parent)
        self.stage = stage
        self.worker: StageWorker | None = None
        self.steps_from_marlin: dict[str, float] = {}
        self.proposed_steps: dict[str, float] = {}
        self.applied_temporarily: dict[str, bool] = {axis: False for axis in DISPLAY_AXES}
        self.verification_ok: dict[str, bool] = {axis: False for axis in DISPLAY_AXES}
        self.last_calibration_record: CalibrationRecord | None = None
        self.repeatability_rows: list[float] = []

        self.setWindowTitle("TomoRamps — калибровка перемещений")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.setMinimumSize(650, 450)
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(980, available.width() - 40), min(760, available.height() - 80))
        else:
            self.resize(900, 650)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        warning = QLabel(
            "ВНИМАНИЕ: калибровка вызывает реальное движение механики. "
            "Перед ходом проверьте свободное пространство и доступность быстрого останова."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "background:#fff3cd; color:#664d03; padding:8px; border:1px solid #ffecb5;"
        )
        root.addWidget(warning)

        root.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_scale_tab(), "1. Масштаб")
        self.tabs.addTab(self._build_backlash_tab(), "2. Люфт")
        self.tabs.addTab(self._build_repeatability_tab(), "3. Повторяемость")
        root.addWidget(self.tabs, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(130)
        root.addWidget(self.log)

        bottom = QHBoxLayout()
        self.btn_quick_stop = QPushButton("БЫСТРЫЙ СТОП (M410)")
        self.btn_quick_stop.setStyleSheet("background:#e67e22;color:white;font-weight:bold;padding:8px")
        self.btn_quick_stop.clicked.connect(self.quick_stop)
        bottom.addWidget(self.btn_quick_stop)
        bottom.addStretch()
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self.axis_combo.currentTextChanged.connect(self._axis_changed)
        self._axis_changed(self.axis_combo.currentText())
        self.read_m503()

    # ---------- UI ----------
    def _build_header(self) -> QGroupBox:
        box = QGroupBox("Ось и параметры Marlin")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Ось:"), 0, 0)
        self.axis_combo = QComboBox()
        for axis in DISPLAY_AXES:
            self.axis_combo.addItem(AXIS_TITLES[axis], axis)
        grid.addWidget(self.axis_combo, 0, 1, 1, 2)

        self.unit_label = QLabel("—")
        grid.addWidget(QLabel("Единица:"), 1, 0)
        grid.addWidget(self.unit_label, 1, 1)

        self.home_label = QLabel("—")
        grid.addWidget(QLabel("Концевики/HOME:"), 1, 2)
        grid.addWidget(self.home_label, 1, 3)

        self.current_steps_label = QLabel("не прочитано")
        self.current_steps_label.setStyleSheet("font-weight:bold")
        grid.addWidget(QLabel("Текущее M92:"), 2, 0)
        grid.addWidget(self.current_steps_label, 2, 1)

        self.proposed_steps_label = QLabel("—")
        grid.addWidget(QLabel("Предложенное:"), 2, 2)
        grid.addWidget(self.proposed_steps_label, 2, 3)

        self.btn_read_m503 = QPushButton("Прочитать M503")
        self.btn_read_m503.clicked.connect(self.read_m503)
        grid.addWidget(self.btn_read_m503, 0, 3)

        return box

    def _build_scale_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        test_box = QGroupBox("Калибровочный ход")
        form = QFormLayout(test_box)

        self.direction_combo = QComboBox()
        self.direction_combo.addItem("Плюс (+)", +1)
        self.direction_combo.addItem("Минус (−)", -1)
        form.addRow("Направление:", self.direction_combo)

        self.commanded_spin = QDoubleSpinBox()
        self.commanded_spin.setDecimals(4)
        self.commanded_spin.setRange(0.0001, 10000.0)
        self.commanded_spin.setValue(10.0)
        form.addRow("Тестовое перемещение:", self.commanded_spin)

        self.feed_spin = QDoubleSpinBox()
        self.feed_spin.setDecimals(1)
        self.feed_spin.setRange(0.1, 100000.0)
        self.feed_spin.setValue(60.0)
        form.addRow("Подача:", self.feed_spin)

        row = QHBoxLayout()
        self.btn_zero = QPushButton("Обнулить текущую координату (G92)")
        self.btn_zero.clicked.connect(self.zero_axis)
        row.addWidget(self.btn_zero)
        self.btn_test_move = QPushButton("Выполнить тестовый ход")
        self.btn_test_move.clicked.connect(self.test_move)
        row.addWidget(self.btn_test_move)
        form.addRow(row)

        root.addWidget(test_box)

        measure_box = QGroupBox("Измерение и расчёт")
        form2 = QFormLayout(measure_box)
        self.measured_spin = QDoubleSpinBox()
        self.measured_spin.setDecimals(5)
        self.measured_spin.setRange(0.0, 10000.0)
        self.measured_spin.setValue(10.0)
        form2.addRow("Фактически измерено:", self.measured_spin)

        self.error_label = QLabel("—")
        form2.addRow("Ошибка до коррекции:", self.error_label)

        self.btn_calculate = QPushButton("Рассчитать новое steps/unit")
        self.btn_calculate.clicked.connect(self.calculate_scale)
        form2.addRow(self.btn_calculate)

        self.btn_apply_temp = QPushButton("Применить M92 временно")
        self.btn_apply_temp.setEnabled(False)
        self.btn_apply_temp.clicked.connect(self.apply_temp_m92)
        form2.addRow(self.btn_apply_temp)
        root.addWidget(measure_box)

        verify_box = QGroupBox("Проверка перед сохранением EEPROM")
        form3 = QFormLayout(verify_box)
        self.verify_measured_spin = QDoubleSpinBox()
        self.verify_measured_spin.setDecimals(5)
        self.verify_measured_spin.setRange(0.0, 10000.0)
        form3.addRow("Измерено после коррекции:", self.verify_measured_spin)

        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setDecimals(3)
        self.tolerance_spin.setRange(0.001, 10.0)
        self.tolerance_spin.setValue(0.100)
        self.tolerance_spin.setSuffix(" %")
        form3.addRow("Допуск ошибки:", self.tolerance_spin)

        self.verify_result_label = QLabel("Сначала примените M92 и выполните повторный ход")
        self.verify_result_label.setWordWrap(True)
        form3.addRow("Результат:", self.verify_result_label)

        self.btn_verify = QPushButton("Проверить результат")
        self.btn_verify.clicked.connect(self.verify_calibration)
        form3.addRow(self.btn_verify)

        self.btn_save_eeprom = QPushButton("Сохранить в EEPROM (M500)")
        self.btn_save_eeprom.setEnabled(False)
        self.btn_save_eeprom.clicked.connect(self.save_eeprom)
        form3.addRow(self.btn_save_eeprom)

        root.addWidget(verify_box)
        root.addStretch()
        return tab

    def _build_backlash_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)
        info = QLabel(
            "Люфт измеряется отдельно от steps/unit. Подведите ось к измерителю всегда с одного "
            "направления, затем смените направление и измерьте перемещение/командный ход до начала "
            "реального движения. Значение здесь только сохраняется — автоматическая компенсация не включается."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        form = QFormLayout()
        self.backlash_plus_minus = QDoubleSpinBox()
        self.backlash_plus_minus.setDecimals(5)
        self.backlash_plus_minus.setRange(0.0, 1000.0)
        form.addRow("Люфт при + → −:", self.backlash_plus_minus)
        self.backlash_minus_plus = QDoubleSpinBox()
        self.backlash_minus_plus.setDecimals(5)
        self.backlash_minus_plus.setRange(0.0, 1000.0)
        form.addRow("Люфт при − → +:", self.backlash_minus_plus)
        self.backlash_status = QLabel("—")
        form.addRow("Среднее:", self.backlash_status)
        root.addLayout(form)

        btn = QPushButton("Сохранить измеренный люфт в JSON")
        btn.clicked.connect(self.save_backlash)
        root.addWidget(btn)
        root.addStretch()
        return tab

    def _build_repeatability_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)
        info = QLabel(
            "Введите фактически измеренные положения при многократном подходе к одной и той же точке. "
            "Для точной проверки лучше использовать индикатор 0,001 мм."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        row = QHBoxLayout()
        self.repeat_value = QDoubleSpinBox()
        self.repeat_value.setDecimals(5)
        self.repeat_value.setRange(-10000.0, 10000.0)
        row.addWidget(QLabel("Измеренное положение:"))
        row.addWidget(self.repeat_value)
        add_btn = QPushButton("Добавить измерение")
        add_btn.clicked.connect(self.add_repeatability_value)
        row.addWidget(add_btn)
        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(self.clear_repeatability)
        row.addWidget(clear_btn)
        root.addLayout(row)

        self.repeat_table = QTableWidget(0, 2)
        self.repeat_table.setHorizontalHeaderLabels(["№", "Измерено"])
        root.addWidget(self.repeat_table)

        self.repeat_stats = QLabel("N=0")
        self.repeat_stats.setWordWrap(True)
        root.addWidget(self.repeat_stats)

        save_btn = QPushButton("Сохранить статистику повторяемости в JSON")
        save_btn.clicked.connect(self.save_repeatability)
        root.addWidget(save_btn)
        return tab

    # ---------- helpers ----------
    def _axis(self) -> str:
        return str(self.axis_combo.currentData())

    def _unit(self) -> str:
        return AXIS_UNITS[self._axis()]

    def _append(self, text: str) -> None:
        self.log.append(text)

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.axis_combo,
            self.btn_read_m503,
            self.btn_zero,
            self.btn_test_move,
            self.btn_calculate,
            self.btn_apply_temp,
            self.btn_verify,
            self.btn_save_eeprom,
        ):
            widget.setEnabled(not busy)
        if not busy:
            axis = self._axis()
            self.btn_apply_temp.setEnabled(axis in self.proposed_steps)
            self.btn_save_eeprom.setEnabled(self.verification_ok.get(axis, False))

    def _run(self, description: str, fn: Callable[[], object], on_done: Callable[[object], None] | None = None) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Операция выполняется", "Дождитесь завершения текущей команды.")
            return
        self._append(f"> {description}")
        self._set_busy(True)
        self.worker = StageWorker(fn)
        if on_done is not None:
            self.worker.done.connect(on_done)
        else:
            self.worker.done.connect(lambda _result: self._append("< OK"))
        self.worker.failed.connect(self._worker_failed)
        self.worker.finished.connect(lambda: self._set_busy(False))
        self.worker.start()

    def _worker_failed(self, message: str) -> None:
        self._append(f"!!! {message}")
        QMessageBox.critical(self, "Ошибка", message)

    def _axis_changed(self, _text: str) -> None:
        axis = self._axis()
        unit = AXIS_UNITS[axis]
        self.unit_label.setText(unit)
        self.home_label.setText("есть концевики" if AXIS_HAS_HOME[axis] else "без HOME-концевика")
        current = self.steps_from_marlin.get(axis)
        self.current_steps_label.setText("не прочитано" if current is None else f"{current:.8g} steps/{unit}")
        proposed = self.proposed_steps.get(axis)
        self.proposed_steps_label.setText("—" if proposed is None else f"{proposed:.8g} steps/{unit}")
        self.btn_apply_temp.setEnabled(proposed is not None)
        self.btn_save_eeprom.setEnabled(self.verification_ok.get(axis, False))

        # Разумные стартовые значения без изменения механики.
        if axis in ("A", "B"):
            self.commanded_spin.setValue(10.0 if axis == "B" else 90.0)
            self.measured_spin.setValue(self.commanded_spin.value())
            self.feed_spin.setValue(60.0)
        elif axis == "Z":
            self.commanded_spin.setValue(20.0)
            self.measured_spin.setValue(20.0)
        else:
            self.commanded_spin.setValue(10.0)
            self.measured_spin.setValue(10.0)
        self.verify_measured_spin.setValue(0.0)
        self.verify_result_label.setText("Сначала примените M92 и выполните повторный ход")

    def _fresh_endstops(self) -> dict[tuple[str, str], bool]:
        try:
            lines = self.stage.endstops(log=False)
        except TypeError:
            lines = self.stage.endstops()
        return parse_endstops(list(lines))

    def _check_direction_safe(self, axis: str, direction: int) -> None:
        states = self._fresh_endstops()
        side = "max" if direction > 0 else "min"
        if states.get((axis, side)) is True:
            raise RuntimeError(f"Движение запрещено: {axis}_{side.upper()} уже TRIGGERED")

    # ---------- Marlin ----------
    def read_m503(self) -> None:
        def fn():
            return self.stage.send("M503", timeout_seconds=20.0)

        def done(result: object) -> None:
            lines = list(result or [])
            parsed = parse_m503_steps(lines)
            if not parsed:
                self._append("< M503 получен, но строка M92 не распознана")
                QMessageBox.warning(self, "M503", "Не удалось найти steps/unit в ответе M503.")
                return
            self.steps_from_marlin.update(parsed)
            self._append("< M92: " + ", ".join(f"{a}={v:g}" for a, v in parsed.items()))
            self._axis_changed(self.axis_combo.currentText())

        self._run("M503 — прочитать текущие steps/unit", fn, done)

    def zero_axis(self) -> None:
        axis = self._axis()
        answer = QMessageBox.question(
            self,
            "Обнулить координату",
            f"Назначить текущую физическую позицию оси {axis} как 0 командой G92 {axis}0?\n"
            "Это не HOME и не движение.",
        )
        if answer != QMessageBox.Yes:
            return
        self._run(f"G92 {axis}0", lambda: self.stage.send(f"G92 {axis}0", timeout_seconds=10.0))

    def test_move(self) -> None:
        axis = self._axis()
        direction = int(self.direction_combo.currentData())
        distance = float(self.commanded_spin.value())
        feed = float(self.feed_spin.value())
        signed = distance * direction

        if distance <= 0 or feed <= 0:
            QMessageBox.warning(self, "Параметры", "Ход и подача должны быть больше нуля.")
            return

        if QMessageBox.question(
            self,
            "Реальное движение",
            f"Переместить {AXIS_TITLES[axis]} на {signed:g} {AXIS_UNITS[axis]}?",
        ) != QMessageBox.Yes:
            return

        def fn():
            self._check_direction_safe(axis, direction)
            return self.stage.move(axis, signed, feed=feed)

        self._run(f"Тестовый ход {axis} {signed:g} {AXIS_UNITS[axis]}, F={feed:g}", fn)

    # ---------- Scale calibration ----------
    def calculate_scale(self) -> None:
        axis = self._axis()
        old = self.steps_from_marlin.get(axis)
        if old is None:
            QMessageBox.warning(self, "Нет M92", "Сначала прочитайте M503.")
            return
        commanded = float(self.commanded_spin.value())
        measured = float(self.measured_spin.value())
        try:
            new = calculate_new_steps(old, commanded, measured)
            err = relative_error_percent(commanded, measured)
        except ValueError as exc:
            QMessageBox.warning(self, "Ошибка данных", str(exc))
            return

        self.proposed_steps[axis] = new
        self.verification_ok[axis] = False
        self.applied_temporarily[axis] = False
        self.proposed_steps_label.setText(f"{new:.8g} steps/{AXIS_UNITS[axis]}")
        self.error_label.setText(f"{measured-commanded:+.5f} {AXIS_UNITS[axis]} ({err:+.4f} %)")
        self.btn_apply_temp.setEnabled(True)
        self.btn_save_eeprom.setEnabled(False)
        self._append(
            f"Расчёт {axis}: old={old:.8g}, command={commanded:g}, measured={measured:g} -> new={new:.8g}"
        )

    def apply_temp_m92(self) -> None:
        axis = self._axis()
        new = self.proposed_steps.get(axis)
        if new is None:
            return
        if QMessageBox.question(
            self,
            "Временное применение",
            f"Отправить M92 {axis}{new:.8g}?\n\nEEPROM пока НЕ будет изменена.",
        ) != QMessageBox.Yes:
            return

        def done(_result: object) -> None:
            self.steps_from_marlin[axis] = new
            self.applied_temporarily[axis] = True
            self.verification_ok[axis] = False
            self.current_steps_label.setText(f"{new:.8g} steps/{AXIS_UNITS[axis]} (RAM)")
            self.verify_result_label.setText("M92 применён временно. Выполните новый тестовый ход и измерьте результат.")
            self._append("< M92 применён только в RAM Marlin")

        self._run(f"M92 {axis}{new:.8g}", lambda: self.stage.send(f"M92 {axis}{new:.8g}", timeout_seconds=10.0), done)

    def verify_calibration(self) -> None:
        axis = self._axis()
        if not self.applied_temporarily.get(axis, False):
            QMessageBox.warning(self, "Проверка", "Сначала примените рассчитанное M92 временно.")
            return
        commanded = float(self.commanded_spin.value())
        measured = float(self.verify_measured_spin.value())
        if measured <= 0:
            QMessageBox.warning(self, "Проверка", "Введите фактически измеренный проверочный ход.")
            return
        err = relative_error_percent(commanded, measured)
        ok = abs(err) <= float(self.tolerance_spin.value())
        self.verification_ok[axis] = ok
        if ok:
            self.verify_result_label.setText(
                f"PASS: ошибка {err:+.4f} %, допуск ±{self.tolerance_spin.value():.3f} %. "
                "M500 разрешён."
            )
            self.verify_result_label.setStyleSheet("color:#198754;font-weight:bold")
        else:
            self.verify_result_label.setText(
                f"НЕ ПРОШЛО: ошибка {err:+.4f} %, допуск ±{self.tolerance_spin.value():.3f} %. "
                "Повторите измерение/калибровку; EEPROM не сохраняется."
            )
            self.verify_result_label.setStyleSheet("color:#b02a37;font-weight:bold")
        self.btn_save_eeprom.setEnabled(ok)

        old = self.steps_from_marlin.get(axis, 0.0)
        proposed = self.proposed_steps.get(axis, old)
        self.last_calibration_record = CalibrationRecord(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            axis=axis,
            title=AXIS_TITLES[axis],
            unit=AXIS_UNITS[axis],
            old_steps_per_unit=old,
            proposed_steps_per_unit=proposed,
            commanded=commanded,
            measured=float(self.measured_spin.value()),
            verification_measured=measured,
            verification_error_percent=err,
            saved_to_eeprom=False,
        )

    def save_eeprom(self) -> None:
        axis = self._axis()
        if not self.verification_ok.get(axis, False):
            QMessageBox.warning(self, "EEPROM", "Проверка не пройдена. M500 заблокирован.")
            return
        if QMessageBox.question(
            self,
            "Сохранить EEPROM",
            "Проверка пройдена. Сохранить текущие параметры Marlin командой M500?",
        ) != QMessageBox.Yes:
            return

        def done(_result: object) -> None:
            self._append("< M500: настройки сохранены в EEPROM")
            if self.last_calibration_record and self.last_calibration_record.axis == axis:
                self.last_calibration_record.saved_to_eeprom = True
                self._append_history("scale_history", asdict(self.last_calibration_record))

        self._run("M500 — сохранить EEPROM", lambda: self.stage.send("M500", timeout_seconds=15.0), done)

    # ---------- Backlash ----------
    def save_backlash(self) -> None:
        axis = self._axis()
        pm = float(self.backlash_plus_minus.value())
        mp = float(self.backlash_minus_plus.value())
        avg = (pm + mp) / 2.0
        self.backlash_status.setText(f"{avg:.5f} {AXIS_UNITS[axis]}")
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "axis": axis,
            "title": AXIS_TITLES[axis],
            "unit": AXIS_UNITS[axis],
            "plus_to_minus": pm,
            "minus_to_plus": mp,
            "mean": avg,
            "compensation_applied": False,
        }
        self._append_history("backlash_history", record)
        self._append(f"Люфт {axis}: +→- {pm:g}; -→+ {mp:g}; среднее {avg:g} {AXIS_UNITS[axis]}")

    # ---------- Repeatability ----------
    def add_repeatability_value(self) -> None:
        value = float(self.repeat_value.value())
        self.repeatability_rows.append(value)
        row = self.repeat_table.rowCount()
        self.repeat_table.insertRow(row)
        self.repeat_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.repeat_table.setItem(row, 1, QTableWidgetItem(f"{value:.5f}"))
        self._update_repeatability_stats()

    def clear_repeatability(self) -> None:
        self.repeatability_rows.clear()
        self.repeat_table.setRowCount(0)
        self._update_repeatability_stats()

    def _update_repeatability_stats(self) -> None:
        values = self.repeatability_rows
        if not values:
            self.repeat_stats.setText("N=0")
            return
        avg = mean(values)
        spread = max(values) - min(values)
        sigma = pstdev(values) if len(values) > 1 else 0.0
        self.repeat_stats.setText(
            f"N={len(values)} | среднее={avg:.5f} | σ={sigma:.5f} | "
            f"min={min(values):.5f} | max={max(values):.5f} | размах={spread:.5f} {AXIS_UNITS[self._axis()]}"
        )

    def save_repeatability(self) -> None:
        if len(self.repeatability_rows) < 2:
            QMessageBox.warning(self, "Повторяемость", "Добавьте минимум два измерения.")
            return
        axis = self._axis()
        values = list(self.repeatability_rows)
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "axis": axis,
            "title": AXIS_TITLES[axis],
            "unit": AXIS_UNITS[axis],
            "values": values,
            "mean": mean(values),
            "sigma_population": pstdev(values),
            "min": min(values),
            "max": max(values),
            "range": max(values) - min(values),
        }
        self._append_history("repeatability_history", record)
        self._append(f"Статистика повторяемости {axis} сохранена")

    # ---------- JSON ----------
    def _json_path(self) -> Path:
        # При размещении файла в app/ получаем <repo>/config/calibration.json.
        here = Path(__file__).resolve()
        if here.parent.name.lower() == "app":
            root = here.parents[1]
        else:
            root = here.parent
        return root / "config" / "calibration.json"

    def _load_json(self) -> dict:
        path = self._json_path()
        if not path.exists():
            return {"schema_version": 2, "axes": {}, "scale_history": [], "backlash_history": [], "repeatability_history": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Корень JSON должен быть объектом")
            return data
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Не удалось прочитать {path}: {exc}") from exc

    def _save_json(self, data: dict) -> None:
        path = self._json_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _append_history(self, section: str, record: dict) -> None:
        try:
            data = self._load_json()
            data.setdefault("schema_version", 2)
            data.setdefault(section, [])
            data[section].append(record)
            axis = record.get("axis")
            if axis in DISPLAY_AXES:
                axes = data.setdefault("axes", {})
                axis_data = axes.setdefault(axis, {})
                axis_data.update({
                    "title": AXIS_TITLES[axis],
                    "unit": AXIS_UNITS[axis],
                    "last_updated": record.get("timestamp"),
                })
                if section == "scale_history":
                    axis_data["steps_per_unit"] = record.get("proposed_steps_per_unit")
                    axis_data["last_scale_calibration"] = record
                elif section == "backlash_history":
                    axis_data["last_backlash"] = record
                elif section == "repeatability_history":
                    axis_data["last_repeatability"] = record
            self._save_json(data)
            self._append(f"JSON: {self._json_path()}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "JSON", str(exc))

    # ---------- stop ----------
    def quick_stop(self) -> None:
        try:
            self.stage.quick_stop()
            self._append("!!! M410 отправлен")
        except Exception as exc:  # noqa: BLE001
            self._append(f"!!! M410: {type(exc).__name__}: {exc}")

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Операция выполняется", "Сначала дождитесь завершения команды или нажмите M410.")
            event.ignore()
            return
        event.accept()
