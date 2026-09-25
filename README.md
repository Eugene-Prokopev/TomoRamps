# TomoRamps

Позиционирующий стол томографа на базе **Arduino Mega 2560 + RAMPS 1.6 + Marlin 2.1.2**.
Управление выполняется по USB через G-code из Python/PySide6-приложений.

```text
Python GUI → USB Serial → Marlin → STEP/DIR → A4988 / TB6600 → двигатели
```

## Аппаратная конфигурация

- Arduino Mega 2560;
- RAMPS 1.6;
- 5 драйверов A4988 на RAMPS;
- внешний TB6600 для шестой оси C;
- механические NO-концевики;
- питание двигателей 12 V;
- USB Serial, обычно `COM11`.

## Актуальная карта осей

| G-code | Подпись в GUI | Физическое назначение | Драйвер |
|---|---|---|---|
| `X` | X — precision (X) | точная X, микровинт | RAMPS X / A4988 |
| `Y` | Y — precision (Y) | точная Y, микровинт | RAMPS Y / A4988 |
| `Z` | XX — coarse (Z) | грубая X, направляющая около 1 м | RAMPS Z / A4988 |
| `A` | Rotation (A) | вращение образца | RAMPS E1 / A4988 |
| `B` | Tilt (B) | наклон | RAMPS E0 / A4988 |
| `C` | Z — precision (C) | точная Z | внешний TB6600 |

Порядок строк в GUI: `X, Y, C, A, B, Z`.

### STEP / DIR / ENABLE

| Ось | STEP | DIR | ENABLE |
|---|---:|---:|---:|
| X | D54 | D55 | D38 |
| Y | D60 | D61 | D56 |
| Z / coarse X | D46 | D48 | D62 |
| B / E0 | D26 | D28 | D24 |
| A / E1 | D36 | D34 | D30 |
| C / TB6600 | D40 | D42 | D44 |

Для C:

```text
Mega D40 → TB6600 PUL/STEP
Mega D42 → TB6600 DIR
Mega D44 → TB6600 ENA
Mega GND ↔ TB6600 GND
Мотор → TB6600 A+/A-/B+/B-
```

### Концевики

Используются механические NO-концевики:

```text
COM → GND / контакт '-'
NO  → SIGNAL / контакт 'S'
'+' → не подключать
```

| Физическая ось | G-code | MIN | MAX |
|---|---|---:|---:|
| точная X | X | D3 / X_MIN | D2 / X_MAX |
| точная Y | Y | D14 / Y_MIN | D15 / Y_MAX |
| грубая X | Z | D11 | D6 |
| точная Z | C | D18 / Z_MIN | D19 / Z_MAX |
| вращение | A | нет | нет |
| наклон | B | нет | нет |

Ожидаемое состояние в `M119`:

```text
отпущен → open
нажат   → TRIGGERED
```

Не запускать `G28 A` и `G28 B`: у этих осей нет концевиков.

Подробная схема: [docs/axis_map.md](docs/axis_map.md).
Визуальный справочник: [docs/index.html](docs/index.html).

## Приложения

### Русская версия с калибровкой

```powershell
.\.venv\Scripts\python.exe app\main_with_calibration.py
```

Включает:

- jog и непрерывный jog короткими сегментами;
- дробные расстояния и скорости;
- поддержку точки и запятой (`0.25` и `0,25`);
- координаты `M114`;
- концевики `M119`;
- консоль G-code;
- serial-лог и crash-лог;
- `M17`, `M18`, `M410`, `M112`, `G92`;
- окно калибровки `steps/unit`;
- чтение `M503`, применение `M92`, сохранение `M500`;
- настройку runtime-параметров `M203/M201/M204/M205`.

### English-версия без калибровки

```powershell
.\.venv\Scripts\python.exe app\main_english.py
```

Это отдельный английский jog-контроллер без вкладки калибровки. Остальные функции
управления одинаковы с основной версией.

### Базовая русская версия

```powershell
.\.venv\Scripts\python.exe app\main.py
```

Для повседневной работы рекомендуется `main_english.py` или
`main_with_calibration.py`.

## Безопасные команды

Перед первым движением:

```gcode
M17
M119
M114
```

Движение выполняется относительной командой:

```gcode
G91
G1 X0.25 F12.5
G90
```

Остановка:

```gcode
M410  ; быстрый останов движения
M112  ; аварийный останов Marlin
```

`M112` обычно требует перезапуска или сброса Marlin.

## Homing и скорости

Скорость поиска нуля `G28` задаётся в прошивке параметром
`HOMING_FEEDRATE_MM_M` в `firmware/Marlin/Marlin/Configuration.h`.
Текущая конфигурация репозитория:

```cpp
#define HOMING_FEEDRATE_MM_M { (50), (50), (50), (50), (50), (50) }
```

Значения задаются в единицах Marlin в минуту. Для изменения скорости `G28` нужно
изменить `Configuration.h`, пересобрать и перепрошить Mega. Параметры `M203`, `M201`,
`M204`, `M205` из вкладки калибровки меняют обычное движение и ограничения planner,
но не заменяют compile-time скорость homing.

## Marlin: сборка и прошивка

Исходники находятся в:

```text
firmware/Marlin/Marlin/
```

Environment PlatformIO:

```text
mega2560
```

Сборка:

```powershell
cd C:\pythonProject\Tomo_Ramps_26.08.26
.\.venv\Scripts\python.exe -m platformio run -d firmware\Marlin -e mega2560
```

Прошивка на `COM11`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\flash.ps1 COM11
```

Для изменения только `steps/unit` перепрошивка не нужна:

```gcode
M92 X<value>
M500
M503
```

EEPROM Marlin — основное хранилище рабочих параметров. Файл
`config/calibration.json` используется как резервная копия и история калибровок.

## Установка и тесты

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

Тесты используют mock Serial и не требуют подключённой платы.

Проверка прошивки и тестов:

```powershell
python scripts/check.py
```

## Структура репозитория

```text
app/
  main.py                    базовый GUI
  main_with_calibration.py   русский GUI с калибровкой
  main_english.py            английский GUI без калибровки
  calibration_window.py      окно калибровки
src/tomostage/
  controller.py              G-code/Serial-контроллер
tests/                       pytest и mock Serial
firmware/Marlin/Marlin/     исходники и Configuration.h
docs/axis_map.md             актуальная распиновка и концевики
docs/calibration.md          workflow калибровки
config/calibration.json      резервная копия калибровок
logs/                        serial.log и crash.log
```

## Git workflow

Изменения делаются небольшими коммитами. Перед коммитом необходимо выполнить:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m py_compile app\main.py app\main_with_calibration.py app\main_english.py
```

Аппаратные изменения и новую прошивку проверять на одной оси за раз, с рукой рядом
с `M410`.
