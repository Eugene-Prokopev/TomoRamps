from PySide6.QtWidgets import QApplication

from main_english import MainWindow, parse_user_float


def test_english_app_has_no_calibration_control():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert "Calibration" not in window.windowTitle()
    assert not hasattr(window, "btn_calibration")
    assert parse_user_float("0,25") == 0.25
    window.close()
