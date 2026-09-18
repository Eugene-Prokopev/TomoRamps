# Быстрая настройка Marlin для TomoRamps

Эта памятка относится к локальным исходникам Marlin в:

```text
firmware/Marlin/Marlin/
```

## 1. Что редактировать

| Что настраиваем | Файл | Основные параметры |
|---|---|---|
| Плата, драйверы, направление, шаги, пределы | `Configuration.h` | `MOTHERBOARD`, `*_DRIVER_TYPE`, `INVERT_*_DIR`, `DEFAULT_AXIS_STEPS_PER_UNIT`, `*_MIN_POS`, `*_MAX_POS`, `*_HOME_DIR` |
| Концевики, EEPROM и общие функции | `Configuration_adv.h` | `ENDSTOPS_ALWAYS_ON_DEFAULT`, расширенные функции |
| Номера физических пинов RAMPS/Mega | `src/pins/ramps/pins_RAMPS.h` | `*_STEP_PIN`, `*_DIR_PIN`, `*_ENABLE_PIN`, `*_MIN_PIN`, `*_MAX_PIN` |
| Пины конкретной другой платы | `src/pins/<семейство>/pins_*.h` | использовать только файл, который подключён вашей платой |

Не редактируйте `.pio/build/`, `firmware.hex` или `.elf` — это результаты сборки.

## 2. Текущая схема TomoRamps

| Физическое назначение | Ось Marlin | Драйвер |
|---|---|---|
| точная X | X | RAMPS X / A4988 |
| точная Y | Y | RAMPS Y / A4988 |
| грубая X | Z | RAMPS Z / A4988 |
| вращение | A | RAMPS E1 / A4988 |
| наклон | B | RAMPS E0 / A4988 |
| точная Z | C | внешний TB6600 (Marlin K) |

В GUI строки подписаны по физическому назначению, поэтому `Z — точный (C)` отправляет команды оси `C`, а `XX — грубый (Z)` — команды `Z`.

## 3. Как поменять направление оси

В `Configuration.h` найдите параметр нужного драйвера:

```cpp
#define INVERT_X_DIR false
#define INVERT_Y_DIR false
#define INVERT_Z_DIR false
#define INVERT_I_DIR false
#define INVERT_J_DIR false
#define INVERT_K_DIR false
```

Поменяйте только `true` ↔ `false` для нужной оси.

Соответствие дополнительных осей:

```text
A — внутренний I / слот E1, вращение
B — внутренний J / слот E0, наклон
C — внутренний K / внешний TB6600
```

После изменения направления нужна новая сборка и прошивка.

## 4. Как поменять пин концевика

Для штатного X/Y/Z в `pins_RAMPS.h` используются параметры:

```cpp
#define X_MIN_PIN ...
#define X_MAX_PIN ...
#define Y_MIN_PIN ...
#define Y_MAX_PIN ...
#define Z_MIN_PIN ...
#define Z_MAX_PIN ...
```

Для внешней оси C используются:

```cpp
#define K_MIN_PIN ...
#define K_MAX_PIN ...
```

В текущем проекте:

```text
точная X: X_MIN=D3, X_MAX=D2
точная Y: Y_MIN=D14, Y_MAX=D15
грубая X (Marlin Z): Z_MIN=D11, Z_MAX=D6
точная Z (Marlin C/K): K_MIN=D18, K_MAX=D19
```

После изменения обязательно проверить, что новый пин не используется:

- STEP/DIR/ENABLE другой оси;
- USB/Serial;
- SD-картой;
- дисплеем;
- термистором;
- сервоприводом;
- TB6600.

## 5. Как поменять логику NO/NC концевика

Для NO-схемы проекта:

```text
COM → GND (-)
NO  → S
+   → не подключать
```

Обычно используется:

```cpp
#define X_MIN_ENDSTOP_INVERTING true
```

Для NC может потребоваться `false`. Проверять нужно не по догадке, а командой:

```gcode
M119
```

Правильное поведение:

```text
отпущен → open
нажат   → TRIGGERED
```

Если состояние наоборот — поменяйте только параметр `*_ENDSTOP_INVERTING` соответствующего входа.

## 6. Остановка по концевикам во время обычного jog

В `Configuration_adv.h` должна быть активна строка:

```cpp
#define ENDSTOPS_ALWAYS_ON_DEFAULT
```

Без неё Marlin может использовать концевики только во время хоуминга.

Концевик блокирует движение в сторону активного конца, но обычно разрешает движение от него.

## 7. Steps per unit

В `Configuration.h` есть временные значения:

```cpp
#define DEFAULT_AXIS_STEPS_PER_UNIT { X, Y, Z, A, B, C }
```

Порядок массива зависит от версии Marlin. В нашем проекте лучше менять значения через G-code и сохранять в JSON:

```gcode
M92 X100
M92 Y100
M92 Z100
M92 C100
M92 A50
M92 B50
M500
```

Текущая проектная копия хранится в:

```text
config/calibration.json
```

Формула калибровки:

```text
новое значение = старое значение × заданное расстояние / фактическое расстояние
```

## 8. Пределы хода

В `Configuration.h` настраиваются:

```cpp
#define X_MIN_POS 0
#define X_MAX_POS 100
#define Y_MIN_POS 0
#define Y_MAX_POS 100
#define Z_MIN_POS 0
#define Z_MAX_POS 1000
#define K_MIN_POS 0
#define K_MAX_POS 200
```

Сначала измерьте реальный безопасный ход, затем задайте пределы с запасом. Не ставьте пределы вплотную к механическому упору.

## 9. Скорость и ускорение

В `Configuration.h` можно настроить:

```cpp
#define DEFAULT_MAX_FEEDRATE { ... }
#define DEFAULT_MAX_ACCELERATION { ... }
#define DEFAULT_ACCELERATION ...
#define DEFAULT_TRAVEL_ACCELERATION ...
```

Для первого запуска лучше использовать низкие значения. Если мотор пропускает шаги, сначала уменьшайте скорость и ускорение, а не увеличивайте ток бесконтрольно.

## 10. Изменения без перепрошивки

Многие параметры можно временно проверить через консоль GUI:

```gcode
M119              ; состояние концевиков
M114              ; координаты
M17               ; включить драйверы
M18               ; отключить драйверы
M92 X100          ; временно изменить steps/unit
M503              ; показать текущие настройки
M500              ; сохранить настройки в EEPROM
M502              ; сбросить EEPROM к значениям прошивки — осторожно
G92 X0            ; только обнулить текущую координату
M211 S1           ; включить программные пределы
M211 S0           ; выключить программные пределы — осторожно
```

`M92` без `M500` обычно действует до перезагрузки. `G92` не калибрует ось и не ищет физический ноль.

## 11. Полный алгоритм изменения прошивки

1. Выключить питание моторов.
2. Сохранить текущие файлы и сделать Git-коммит:

```powershell
git add -A
git commit -m "Before Marlin tuning"
```

3. Изменить один параметр.
4. Проверить, что пины не конфликтуют.
5. Собрать без заливки:

```powershell
cd firmware/Marlin
..\..\.venv\Scripts\python.exe -m platformio run -e mega2560
cd ../..
```

6. Если сборка успешна, прошить:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/flash.ps1 COM11
```

7. Проверить без движения:

```gcode
M115
M119
M114
M503
```

8. Проверить одну ось на малом шаге.
9. Если всё работает — сделать отдельный Git-коммит.

## 12. Откат

Посмотреть историю:

```powershell
git log --oneline
```

Безопасно отменить последний коммит:

```powershell
git revert HEAD
```

Вернуться к версии до эксперимента можно через Git-клиент или отдельную ветку. Не используйте `git reset --hard`, пока не сохранили нужные изменения.
