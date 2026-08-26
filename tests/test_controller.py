"""Тесты GCodeController на фейковом serial (плата не нужна)."""
import pytest

from tomostage.controller import GCodeController, TomoStageError


class FakeSerial:
    """Эмулирует ответы Marlin на записанные команды."""

    def __init__(self, *args, **kwargs):
        self.rx: list[str] = []      # что прочитает контроллер
        self.written: list[str] = []
        self.is_open = False

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        pass

    def write(self, data: bytes):
        cmd = data.decode().strip()
        self.written.append(cmd)
        self.rx.extend(self.reply_for(cmd))
        return len(data)

    def readline(self) -> bytes:
        if self.rx:
            return (self.rx.pop(0) + "\n").encode()
        return b""

    @staticmethod
    def reply_for(cmd: str) -> list[str]:
        if cmd == "":
            return ["start", "ok"]
        if cmd.startswith("M110") or cmd.split()[0] in ("G90", "G91", "M82", "M83"):
            return ["ok"]
        if cmd.startswith("M114"):
            return ["X:1.50 Y:-2.25 Z:300.00 I:12.0 J:45.5 E:0.00 Count X:600 Y:-900 Z:12000", "ok"]
        if cmd.startswith("M115"):
            return ["FIRMWARE_NAME:Marlin 2.1.2 SOURCE_CODE_URL:github.com/MarlinFirmware/Marlin "
                    "MACHINE_TYPE:TomoRamps EXTRUDER_COUNT:0", "ok"]
        if cmd.startswith("M119"):
            return ["Reporting endstop status", "x_min: TRIGGERED", "x_max: open",
                    "y_min: open", "y_max: open", "z_min: open", "z_max: open", "ok"]
        if cmd.startswith("G28"):
            return ["ok"]
        if cmd.startswith("G0"):
            return ["ok"]
        if cmd.startswith("M106") or cmd.startswith("M107") or cmd.startswith("M42"):
            return ["ok"]
        return ["Error: Unknown command: " + cmd]


def make_ctrl():
    return GCodeController("COM99", serial_factory=lambda p, b, t: FakeSerial())


def test_connect_sends_init_sequence():
    c = make_ctrl()
    c.connect()
    assert c.connected
    assert "G90" in c._serial.written
    assert "M110 N0" in c._serial.written
    c.close()


def test_position_parsing_all_five_axes():
    with make_ctrl() as c:
        pos = c.get_position()
    assert pos == {"X": 1.5, "Y": -2.25, "Z": 300.0, "I": 12.0, "J": 45.5}


def test_relative_move_returns_to_absolute_mode():
    with make_ctrl() as c:
        c.move("X", 0.1, feed=600)
        w = list(c._serial.written)
    assert "G91 G0 X0.1000 F600" in w
    assert w[w.index("G91 G0 X0.1000 F600") + 1] == "G90"


def test_move_rejects_unknown_axis():
    with make_ctrl() as c:
        with pytest.raises(ValueError):
            c.move("W", 1)


def test_home_builds_g28_line():
    with make_ctrl() as c:
        c.home("XI")
        assert "G28 X I" in c._serial.written


def test_dc_speed_and_direction_pins():
    with make_ctrl() as c:
        c.dc_direction(forward=True)
        c.dc_speed(180)
        c.dc_direction(forward=False)
        c.dc_speed(0)
        w = list(c._serial.written)
    assert "M42 P11 S1" in w and "M42 P6 S0" in w
    assert "M106 S180" in w
    assert "M42 P11 S0" in w and "M42 P6 S1" in w
    assert "M107" in w


def test_endstops_and_firmware():
    with make_ctrl() as c:
        assert any("TRIGGERED" in s for s in c.endstops())
        assert "Marlin" in c.firmware_info()


def test_error_from_board_raises():
    with make_ctrl() as c:
        with pytest.raises(TomoStageError):
            c.send("G999")


def test_send_without_connection_raises():
    with pytest.raises(TomoStageError):
        make_ctrl().send("M105")
