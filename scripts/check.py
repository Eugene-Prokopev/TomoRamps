"""Автопроверка одной командой: python scripts/check.py

Позже сюда добавится компиляция прошивки (arduino-cli) и smoke-тест железа.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    print("=== pytest ===")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        cwd=ROOT,
    )
    # TODO: компиляция прошивки, когда появится firmware/
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
