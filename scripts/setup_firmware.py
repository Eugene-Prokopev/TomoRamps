"""Подготовка прошивки Marlin для TomoRamps.

Скачивает Marlin 2.1.2, распаковывает в firmware/Marlin и накладывает патчи:
5 осей (X Y Z + I наклон + J вращение), концевики, RAMPS, без экструдеров.

Запуск (можно с выключенным VPN, нужен интернет):
    .venv\\Scripts\\python scripts\\setup_firmware.py

Повторный запуск безопасен (идемпотентен).
"""
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW_DIR = ROOT / "firmware"
MARLIN_DIR = FW_DIR / "Marlin"
ZIP_PATH = FW_DIR / "marlin.zip"
MARLIN_REF = "2.1.2"
URL = f"https://github.com/MarlinFirmware/Marlin/archive/refs/tags/{MARLIN_REF}.zip"

# (регулярка, замена, описание). Флаг APPEND = добавить в конец, если не найдено.
PATCHES_H = [
    (r"^\s*//?\s*#define MOTHERBOARD\s+\S+",
     "#define MOTHERBOARD BOARD_RAMPS_14_EFB",
     "Плата: RAMPS 1.6 электрически = 1.4 (EFB), пины идентичны"),
    (r"^#define SERIAL_PORT\s+-?\d+",
     "#define SERIAL_PORT 0",
     "USB-порт Mega (16U2)"),
    (r"^#define BAUDRATE\s+\d+",
     "#define BAUDRATE 250000",
     "Скорость USB-Serial"),
    (r"^#define EXTRUDERS\s+\d+",
     "#define EXTRUDERS 0",
     "Экструдеров нет: разъёмы E0/E1 отдаются осям I и J"),
    (r"^//?\s*#define NUM_AXES\s+\d+",
     "#define NUM_AXES 5",
     "5 осей: X Y Z I J",
     "APPEND"),
    (r"^//?\s*#define USE_XMIN_PLUG.*", "#define USE_XMIN_PLUG", "Концевик X- (D3)"),
    (r"^//?\s*#define USE_XMAX_PLUG.*", "#define USE_XMAX_PLUG", "Концевик X+ (D2)"),
    (r"^//?\s*#define USE_YMIN_PLUG.*", "#define USE_YMIN_PLUG", "Концевик Y- (D14)"),
    (r"^//?\s*#define USE_YMAX_PLUG.*", "#define USE_YMAX_PLUG", "Концевик Y+ (D15)"),
    (r"^//?\s*#define USE_ZMIN_PLUG.*", "#define USE_ZMIN_PLUG", "Концевик Z- (D18)"),
    (r"^//?\s*#define USE_ZMAX_PLUG.*", "#define USE_ZMAX_PLUG", "Концевик Z+ (D19)"),
    (r"^//?\s*#define ENDSTOPPULLUPS", "#define ENDSTOPPULLUPS",
     "Подтяжки концевиков (нормально-разомкнутые на GND)"),
    (r"^#define DEFAULT_AXIS_STEPS_PER_UNIT\s*\{[^}]*\}",
     "#define DEFAULT_AXIS_STEPS_PER_UNIT { 80, 80, 80, 80, 80 } // TODO: откалибровать!",
     "Шаги/мм — стартовые, калибровка обязательна"),
    (r"^#define DEFAULT_MAX_FEEDRATE\s*\{[^}]*\}",
     "#define DEFAULT_MAX_FEEDRATE { 200, 200, 120, 90, 90 }",
     "Макс. скорости осей (мм/мин)"),
    (r"^#define DEFAULT_MAX_ACCELERATION\s*\{[^}]*\}",
     "#define DEFAULT_MAX_ACCELERATION { 1500, 1500, 800, 500, 500 }",
     "Макс. ускорения осей"),
    (r"^#define DEFAULT_ACCELERATION\s+\d+",
     "#define DEFAULT_ACCELERATION 800",
     "Рабочее ускорение"),
    (r"^#define DEFAULT_TRAVEL_ACCELERATION\s+\d+",
     "#define DEFAULT_TRAVEL_ACCELERATION 800",
     "Ускорение холостых ходов"),
    (r"^\s*/{0,2}\s*#define EEPROM_SETTINGS.*$",
     "#define EEPROM_SETTINGS",
     "EEPROM: M500 сохранит откалиброванные шаги/мм"),
    (r"^//?\s*#define CUSTOM_MACHINE_NAME.*",
     '#define CUSTOM_MACHINE_NAME "TomoRamps"',
     "Имя машины в M115"),
]


def download_and_unpack() -> None:
    marker = MARLIN_DIR / ".tomoramps_ref"
    if MARLIN_DIR.exists():
        if marker.read_text().strip() == MARLIN_REF:
            print(f"[ok] Marlin {MARLIN_REF} уже распакован, пропускаю загрузку")
            return
        sys.exit(f"Папка {MARLIN_DIR} существует, но без маркера {MARLIN_REF}.\n"
                 f"Удалите её вручную и запустите скрипт снова.")
    FW_DIR.mkdir(exist_ok=True)
    if not ZIP_PATH.exists():
        print(f"[..] Скачиваю {URL}")
        urllib.request.urlretrieve(URL, ZIP_PATH)
    print("[..] Распаковываю")
    tmp = FW_DIR / "_unpack"
    with zipfile.ZipFile(ZIP_PATH) as zf:
        zf.extractall(tmp)
    src = tmp / f"Marlin-{MARLIN_REF}"
    shutil.move(str(src), str(MARLIN_DIR))
    tmp.rmdir()
    marker.write_text(MARLIN_REF)
    print(f"[ok] Распаковано в {MARLIN_DIR}")


def apply_patches() -> int:
    errors, applied, skipped = [], 0, 0
    patched = {}
    for fname in ("Configuration.h",):
        path = MARLIN_DIR / "Marlin" / fname
        text = original = path.read_text(encoding="utf-8")
        for item in PATCHES_H:
            pattern, repl, desc = item[0], item[1], item[2]
            allow_append = len(item) > 3 and item[3] == "APPEND"
            new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
            if n:
                text = new
                applied += 1
                print(f"  [patch] {desc}")
                continue
            # уже применено ранее? (отступ и хвостовой комментарий не важны)
            if re.search(r"^\s*" + re.escape(repl) + r"(?:\s|$)", text, flags=re.M):
                skipped += 1
                print(f"  [skip ] {desc} (уже применено)")
                continue
            if allow_append:
                text += f"\n#define {repl.split(None, 1)[1]}  // TomoRamps: {desc}\n"
                applied += 1
                print(f"  [add  ] {desc} (добавлено в конец файла)")
                continue
            errors.append(f"{fname}: не найдено '{pattern}' ({desc})")
        patched[path] = (text, original)
    if errors:
        print("\n[ОШИБКИ] Патчи не применились (файл НЕ изменён):")
        for e in errors:
            print("  -", e)
        return 1
    for path, (text, original) in patched.items():
        if text != original:
            path.write_text(text, encoding="utf-8", newline="\n")
    print(f"\n[ok] Патчей применено/проверено: {applied + skipped}")
    return 0


def main() -> int:
    download_and_unpack()
    print("[..] Накладываю патчи TomoRamps")
    rc = apply_patches()
    if rc == 0:
        print("\nГотово! Дальше: powershell scripts\\flash.ps1  (сборка + заливка)")
        print("Если известен COM-порт: powershell scripts\\flash.ps1 COM5")
    return rc


if __name__ == "__main__":
    sys.exit(main())
