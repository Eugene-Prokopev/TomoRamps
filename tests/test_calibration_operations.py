import pytest

from calibration_window import (
    CalibrationWindow,
    calculate_new_steps,
    parse_endstops,
    relative_error_percent,
)


def test_parse_endstops_real_marlin_response():
    lines = [
        "Reporting endstop status",
        "x_min: open",
        "x_max: open",
        "y_min: open",
        "y_max: open",
        "z_min: open",
        "z_max: TRIGGERED",
        "c_min: open",
        "c_max: open",
        "ok",
    ]
    states = parse_endstops(lines)
    assert states[("X", "min")] is False
    assert states[("X", "max")] is False
    assert states[("Z", "max")] is True
    assert states[("C", "min")] is False


def test_parse_endstops_accepts_echo_prefix():
    states = parse_endstops([
        "echo: x_min: TRIGGERED",
        "echo: c_max: open",
    ])
    assert states[("X", "min")] is True
    assert states[("C", "max")] is False


def test_calibration_module_exposes_endstop_parser():
    assert callable(parse_endstops)


def test_scale_calculation_uses_commanded_over_measured():
    assert calculate_new_steps(80.0, 100.0, 95.0) == pytest.approx(84.2105263158)
    assert relative_error_percent(100.0, 95.0) == pytest.approx(-5.0)


def test_scale_calculation_rejects_invalid_measurement():
    with pytest.raises(ValueError):
        calculate_new_steps(80.0, 100.0, 0.0)
