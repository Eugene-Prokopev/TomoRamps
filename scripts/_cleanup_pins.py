# Разовая очистка хвоста Configuration.h от дублей TomoRamps (I_MIN_PIN/J_MIN_PIN).
# Оставляет один канонический блок в конце файла.
from pathlib import Path

p = Path("firmware/Marlin/Marlin/Configuration.h")
t = p.read_text(encoding="utf-8")

marker = "// NUM_AXES"
idx = t.find(marker)
assert idx != -1, "маркер TomoRamps-хвоста не найден"
line_start = t.rfind("\n", 0, idx) + 1

tail = (
    "// === TomoRamps: доп. оси I (наклон, слот E0) и J (вращение, слот E1) ===\n"
    "// NUM_AXES не задаём вручную: Marlin выведет 5 из I_DRIVER_TYPE/J_DRIVER_TYPE\n"
    "// AXIS_RELATIVE_MODES задаётся в Configuration_adv (TomoRamps)\n"
    "// HOMING_BUMP_MM задаётся в Configuration_adv (TomoRamps)\n"
    "#define I_MIN_PIN 42   // TomoRamps: концевик I- (AUX_2); D4 зарезервирован под E-STOP\n"
    "#define J_MIN_PIN 44   // TomoRamps: концевик J- (AUX_2)\n"
)

p.write_text(t[:line_start] + tail, encoding="utf-8", newline="\n")
print("[ok] хвост Configuration.h нормализован")
