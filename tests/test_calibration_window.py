import pytest

from PySide6.QtWidgets import QApplication, QScrollArea

from calibration_window import CalibrationWindow


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    return app


class DisconnectedStage:
    connected = False


def test_calibration_window_can_be_created(qt_app):
    window = CalibrationWindow(DisconnectedStage())
    assert window.tabs.count() == 4
    assert isinstance(window.tabs.widget(0), QScrollArea)
    assert window.tabs.widget(0).verticalScrollBarPolicy()
    window.close()
