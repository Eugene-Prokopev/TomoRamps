import pytest

from calibration_window import parse_m503_motion


def test_parse_motion_settings_from_real_m503():
    values = parse_m503_motion([
        "echo:  M203 X200.00 Y200.00 Z120.00 A90.00 B90.00 C60.00",
        "echo:  M201 X1500.00 Y1500.00 Z800.00 A500 B500 C300.00",
        "echo:  M204 P800.00 R3000.00 T800.00",
        "echo:  M205 B20000.00 S0.00 T0.00 J0.01",
    ])
    assert values["max_feedrate"] == pytest.approx(
        {"X": 200.0, "Y": 200.0, "Z": 120.0, "A": 90.0, "B": 90.0, "C": 60.0}
    )
    assert values["max_acceleration"]["C"] == pytest.approx(300.0)
    assert values["acceleration"] == pytest.approx(800.0)
    assert values["travel_acceleration"] == pytest.approx(800.0)
    assert values["junction_deviation"] == pytest.approx(0.01)
