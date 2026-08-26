# TomoRamps — контроллер предметного стола томографа

Управление позиционированием образца: **Arduino Mega 2560 + RAMPS 1.6**, пять шаговых
двигателей (драйверы A4988) + один DC-мотор 12 В. Прошивка — Marlin 2.1.x (управление
G-code по USB), приложение оператора — Python (pyserial + PySide6).

## Железо

| Узел | Описание |
|---|---|
| Плата | Arduino Mega 2560 + RAMPS 1.6 (BIGTREETECH) |
| Шаговики | 5 × NEMA17 через A4988, микрошаг 1/16 (X, Y, Z + 2 поворотные оси) |
| DC-мотор | 12 В, управление через MOSFET D9 (ШИМ, команда `M106 S0–255`) |
| Концевики | частично установлены (раскладка уточняется) |
| Питание | 12 В DC |

## Документация по подключениям

- **[docs/index.html](docs/index.html)** — полный визуальный справочник в одном файле:
  официальная диаграмма подключения BTT RAMPS 1.6, принципиальные схемы, карта шёлка,
  шпаргалка пинов на русском (открывается в браузере без интернета).
- [docs/ramps16_pinmap.md](docs/ramps16_pinmap.md) — таблицы «разъём → пин Mega» и команды проверки (`M119`, `M42`, `M280`).
- `docs/pinout/` — исходные материалы:

| Файл | Что это |
|---|---|
| `btt_ramps16_wiring_diagram.jpg` | Официальная диаграмма подключения RAMPS 1.6 (BIGTREETECH) |
| `btt_schematic.pdf` / `btt_schematic_plus.pdf` | Принципиальные схемы платы |
| `btt_silkscreen_2d.pdf` | 2D-карта шёлка (надписей) платы |
| `rampswire14.svg` | Классическая схема RepRap (RAMPS 1.4 ≡ 1.6 электрически) |
| `osoyoo_schematic2.png` | Схема подключения периферии |
| `mega_connectors.png` / `ramps16_connectors.jpg` | Раскладка разъёмов Mega и RAMPS |
| `btt_motherboard.jpg` | Фото платы BTT |

> 🌐 Онлайн-версия справочника (после включения GitHub Pages):
> https://eugene-prokopev.github.io/TomoRamps/

## Структура репозитория

```
├── app/                 # GUI-приложение оператора (PySide6)
├── src/tomostage/       # библиотека контроллера стола (pyserial, G-code)
├── tests/               # pytest (serial мокается, железо не требуется)
├── scripts/check.py     # автопроверка цели: компиляция+тесты одним запуском
├── firmware/            # конфиги Marlin (Configuration.h и патчи)
├── docs/
│   ├── index.html         # визуальный справочник распиновки (GitHub Pages)
│   ├── ramps16_pinmap.md  # распиновка RAMPS 1.6 ↔ Mega
│   ├── pinout/            # схемы, диаграммы, фото платы
│   └── goals/             # GOAL-*.md и VERDICT-*.md (режим «цель → ревью»)
├── requirements.txt
└── README.md
```

## Быстрый старт (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

## Правила работы (workflow)

1. Цель формулируется в `docs/goals/GOAL-XXX.md` с измеримыми критериями приёмки.
2. Изменения — маленькими атомарными коммитами.
3. Перед завершением: `python scripts/check.py` (тесты + сборка прошивки).
4. Ревью отдельным ассистентом по diff и логам тестов → `VERDICT-XXX.md`.
5. Рабочие состояния помечаются тегами: `git tag g001-ok`.

## Статус

- [x] Каркас репозитория, документация
- [ ] Конфиг Marlin под 5 осей + концевики
- [ ] Библиотека контроллера + тесты
- [ ] GUI (jog, координаты, DC-мотор, e-stop)
- [ ] Интеграция с железом
