import pytest

from main_with_calibration import parse_user_float
from tomostage.controller import GCodeController


def test_parse_user_float_accepts_dot_and_comma():
    assert parse_user_float("0.125") == pytest.approx(0.125)
    assert parse_user_float("0,125") == pytest.approx(0.125)
    assert parse_user_float("  12,5  ") == pytest.approx(12.5)


def test_controller_keeps_fractional_distance_and_feed():
    class Serial:
        def __init__(self):
            self.rx = []
            self.written = []
        def reset_input_buffer(self): pass
        def write(self, data):
            self.written.append(data.decode().strip())
            self.rx.append("ok")
        def readline(self):
            return (self.rx.pop(0) + "\n").encode() if self.rx else b""

    serial = Serial()
    controller = GCodeController("TEST", serial_factory=lambda p, b, t: serial)
    controller.connect = lambda: None
    controller._serial = serial
    controller.move("X", 0.00001, feed=12.5)
    assert "G1 X0.00001 F12.5" in serial.written
