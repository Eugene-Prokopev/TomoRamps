"""Smoke-тест реальной платы: python scripts/smoke_serial.py --port COM5 [--move]

Безопасен: двигателями не трогает без флага --move.
"""
import argparse
import sys

from tomostage.controller import GCodeController, TomoStageError


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка связи со столом")
    ap.add_argument("--port", required=True, help="например COM5 или /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=250000)
    ap.add_argument("--move", action="store_true",
                    help="осторожно: сместить X на +1 мм и обратно")
    args = ap.parse_args()

    try:
        with GCodeController(args.port, args.baud) as st:
            print("Прошивка:", st.firmware_info())
            print("Координаты:", st.get_position())
            print("--- Концевики (M119) ---")
            for line in st.endstops():
                print(" ", line)
            if args.move:
                input("ENTER = X +1 мм и назад, Ctrl+C = отмена > ")
                st.move("X", 1.0, feed=600)
                st.move("X", -1.0, feed=600)
                print("Готово:", st.get_position())
        print("OK")
        return 0
    except TomoStageError as exc:
        print("ОШИБКА:", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
