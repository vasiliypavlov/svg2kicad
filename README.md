# Обновлённый `README.md`

Полная версия с добавлением `--via-mode`, описанием двух режимов работы via и разделом про известные проблемы с плагином FreeRouting.

# svg2kicad

**Inkscape SVG → KiCad `.kicad_pcb` converter for artists, makers, and small DIY projects.**

```bash
git clone https://github.com/vasiliypavlov/svg2kicad
cd svg2kicad
pip install -r requirements.txt
python svg2kicad.py input.svg output.kicad_pcb
```

[Русский](#русский) | [English](#english)

---

<a name="русский"></a>
# svg2kicad — Русский

Конвертер **Inkscape SVG → KiCad `.kicad_pcb`** для художников, мейкеров
и небольших проектов. Превращает векторную графику в готовую к производству
печатную плату: пады, сверла, переходные отверстия, шелкографию,
зоны запрета и контур платы.

Скрипт читает обычный Inkscape-файл, где объекты разложены по слоям с
заданными именами, и генерирует `.kicad_pcb`, который открывается в KiCad 8+
и трассируется в FreeRouting.

---

## Содержание

- [Зачем это нужно](#зачем-это-нужно)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Правила построения SVG](#правила-построения-svg)
  - [Слои](#слои)
  - [Цвета](#цвета)
  - [Имена цепей](#имена-цепей)
  - [Группа THT](#группа-tht)
  - [SMD-пады](#smd-пады)
  - [Via](#via)
  - [Контур платы](#контур-платы)
  - [Зоны запрета](#зоны-запрета)
  - [Шелкография](#шелкография)
- [Что получается на выходе](#что-получается-на-выходе)
- [Масштаб и `--dpi`](#масштаб-и---dpi)
- [Проверки и ошибки](#проверки-и-ошибки)
- [Опции командной строки](#опции-командной-строки)
- [Примеры](#примеры)
- [Ограничения](#ограничения)
- [Известные проблемы](#известные-проблемы-ru)
- [FAQ](#faq-ru)
- [Лицензия](#лицензия)
- [Благодарности](#благодарности)

---

## Зачем это нужно

Если вы рисуете в Inkscape арт-плату, светильник, декоративную карту
или просто небольшую электронную поделку — вам нужно превратить картинку
в файл, который понимает фабрика. Обычно это ручная работа в KiCad:
разместить пады, расставить сверла, нарисовать контур, добавить зоны
запрета. `svg2kicad` делает это автоматически.

Скрипт **не заменяет** KiCad. Он делает черновую работу: превращает
нарисованное в Inkscape в структурированную плату. Дальше вы открываете
`.kicad_pcb` в KiCad, проверяете DRC, при необходимости правите вручную
и запускаете FreeRouting.

---

## Установка

Требуется **Python 3.9+** и библиотека `svgelements`.

```bash
pip install svgelements
```

Скрипт — один файл `svg2kicad.py`. Скачайте его в удобную папку и
запускайте оттуда.

---

## Быстрый старт

```bash
python svg2kicad.py input.svg output.kicad_pcb
```

Готово. Откройте `output.kicad_pcb` в KiCad и проверьте DRC
(**Inspect → Design Rules Checker**).

---

## Правила построения SVG

Скрипт распознаёт объекты **по имени слоя** (`inkscape:label`).
Все правила построения нужно соблюдать — иначе объект будет
проигнорирован (WARN) или скрипт откажется генерировать файл (ERROR).

### Слои

| Имя слоя | Назначение |
|---|---|
| `THT` | Группы сквозных падов: drill + pad + опц. silk |
| `F.Pad` | SMD-пады на F.Cu и верх via |
| `B.Pad` | SMD-пады на B.Cu и низ via |
| `Drill` | Одиночные неметаллизированные отверстия (NPTH) |
| `F.SilkS` | Шелкография сверху |
| `B.SilkS` | Шелкография снизу |
| `F.Rule` | Зона запрета на F.Cu |
| `B.Rule` | Зона запрета на B.Cu |
| `Edge.Cuts` | Контур платы |

Слои создаются в Inkscape: **Layer → Add Layer…** и переименовываются
через **Layer → Rename Layer…** в точное имя из таблицы (регистр важен).

Любые другие слои скрипт игнорирует без комментариев.

### Цвета

Цвет объекта — это **семантический маркер**, а не украшение. Есть три
роли:

| Цвет | Значение |
|---|---|
| `#000000` (чёрный) | Drill — отверстие |
| `#FFFFFF` (белый) | Silk — шелкография |
| любой другой | Pad — посадочное место, цвет = цепь |

CSS-имена (`black`, `white`, `red`) распознаются и нормализуются в hex.
Цвета типа `#f9f9f9` — **не белый**, а цветной. Будьте аккуратны:
если вы копируете текст и не меняете цвет, он может стать «цветным»
и превратиться в пад, что вызовет ERROR. Всегда проверяйте точный
`#FFFFFF` для элементов шелкографии.

### Имена цепей

Имя цепи можно задать двумя способами.

**1. По цвету.** Если метка не задана, все пады одинакового цвета
попадают в одну цепь. Имя цепи = hex цвета без `#`, например `ffd42a`.

**2. По метке `Net<Имя>`.** В Inkscape: **Object → Object Properties →
Label**. Метка вида `NetVCC`, `NetAnode`, `NetGND` даст цепи с именами
`VCC`, `Anode`, `GND`. Префикс `Net` отрезается ровно один раз:
`NetNetAnode` → `NetAnode`.

**Приоритет — у метки.** Если у пада есть метка `Net<Имя>` — она
используется, а цвет становится просто визуальным маркером.
Конфликт (одинаковый цвет, разные метки, или наоборот) — **ERROR**.

Метки без префикса `Net` игнорируются, скрипт их не трогает.

### Группа THT

Сквозные пады (для выводных компонентов, разъёмов, штырьков)
описываются как **группа из двух или трёх элементов** внутри слоя `THT`.

**Правило:** в группе должны быть элементы строго по ролям, определяемым
**цветом**:

1. **Чёрный круг или прямоугольник** — drill (отверстие).
   Прямоугольник трактуется как овальный слот.
2. **Цветной круг или прямоугольник** — pad (медная площадка).
3. **Белый элемент или path без заливки с белой обводкой** — silk
   (шелкография, опционально). Может быть несколько.

**Пример группы:**

```xml
<g inkscape:label="THT" inkscape:groupmode="layer">
  <g id="my_tht_pad">
    <circle cx="25" cy="20" r="0.4" fill="#000000"/>  <!-- drill -->
    <circle cx="25" cy="20" r="1.5" fill="#ff0000"
            inkscape:label="NetVCC"/>                 <!-- pad -->
    <path d="..." fill="#ffffff"/>                    <!-- silk (опц.) -->
  </g>
</g>
```

**Правила:**

- Одна группа = один drill + один pad + опц. silk.
- Drill и pad **должны быть совмещены по центру** (допуск 0.1 мм).
- Если есть только drill без pad — получается NPTH (техническое
  отверстие) + silk.
- Если есть только pad без drill — получается SMD-пад на F.Cu.
- Если ни drill, ни pad — ERROR.

**Drill и pad не могут быть path** — только круг или прямоугольник.
Цветной path в THT вызовет ERROR с подсказкой.

### SMD-пады

Круги и прямоугольники **с заливкой** на слоях `F.Pad` и `B.Pad`:

- на `F.Pad` → SMD-пад на F.Cu;
- на `B.Pad` → SMD-пад на B.Cu.

**Правила:**

- Только `circle` или `rect`. Path в F.Pad/B.Pad не поддерживается.
- Заливка обязательна, обводки быть не должно.
- Цвет заливки = цвет цепи.

### Via

Переходное отверстие соединяет F.Cu и B.Cu. Описывается как **два круга
с одинаковым цветом обводки**: один на `F.Pad`, второй на `B.Pad`.

**Правила:**

- Оба круга — `circle` без заливки, только со stroke.
- Центры, радиусы и цвет stroke **должны совпадать** (центры — с
  допуском 0.1 мм, радиусы — с точностью 0.001 мм).
- Если пара не находится — ERROR.
- Диаметр сверла для via = 60% от диаметра круга.

**Пример:**

```xml
<g inkscape:label="F.Pad">
  <circle cx="50" cy="50" r="0.6" fill="none" stroke="#00ff00"/>
</g>
<g inkscape:label="B.Pad">
  <circle cx="50" cy="50" r="0.6" fill="none" stroke="#00ff00"/>
</g>
```

**Как via попадает в `.kicad_pcb`.** Есть два режима вывода, переключаемые
флагом `--via-mode`:

| Режим | Что пишется в файл | Совместимость |
|---|---|---|
| `pad` (по умолчанию) | via как **THT-пад** в отдельном футпринте `svg:vias` | Плагин FreeRouting (KiCad 10) |
| `via` | канонический объект `(via ...)` | Только standalone FreeRouting |

Подробности — в разделе [Известные проблемы](#известные-проблемы-ru).

### Контур платы

Слой `Edge.Cuts`. Все замкнутые фигуры (path, rect, circle) превращаются
в линии контура. Если фигур несколько — они все попадут в контур.

Скрипт автоматически сдвигает всё так, чтобы левый верхний угол контура
оказался в точке (10, 10) мм.

### Зоны запрета

Слои `F.Rule` и `B.Rule`. Все замкнутые фигуры превращаются в keepout-зоны
на соответствующем слое меди.

В KiCad такие зоны запрещают:

- дорожки (tracks);
- переходные отверстия (vias);
- посадочные места (pads);
- заливку медью (copper pour);
- футпринты (footprints).

Зоны корректно экспортируются в DSN и учитываются FreeRouting.

### Шелкография

Слои `F.SilkS` и `B.SilkS`. Принимаются `path`, `rect`, `circle`.

**Заливка игнорируется** — берётся только контур. Толщина линии
определяется атрибутом `stroke-width` в SVG (в пикселях) или равна
0.15 мм по умолчанию.

**Текст нужно предварительно конвертировать** в path:
**Path → Object to Path** (Ctrl+Shift+C). Иначе скрипт не сможет
его разобрать.

Сложные path с несколькими подконтурами (например, буква «A» с
внутренним треугольником) корректно разбиваются на отдельные контуры.

---

## Что получается на выходе

Файл `.kicad_pcb` (версия формата `20231120`, совместим с KiCad 8+).

Содержимое:

- **Один или два footprint'а** со всеми падами:
  - `svg:converted-F` — пады F.Cu и THT;
  - `svg:converted-B` — пады B.Cu (только если они есть).
- **Vias**:
  - в режиме `--via-mode pad` — как THT-пады в отдельном футпринте
    `svg:vias`;
  - в режиме `--via-mode via` — как самостоятельные объекты `(via ...)`.
- **NPTH** — как отдельный footprint `svg:holes`.
- **Зоны запрета** — на F.Cu и/или B.Cu.
- **Шелкография** — `gr_line`, `gr_rect`, `gr_circle`, `gr_poly`.
- **Контур платы** — `gr_line` по слою Edge.Cuts.
- **Цепи** — по одной на каждый уникальный цвет пада или имя метки.

Слои меди: F.Cu (signal), B.Cu (power). Пады получают корректные наборы
слоёв: SMD F.Cu → `F.Cu F.Paste F.Mask`, SMD B.Cu → `B.Cu B.Paste B.Mask`,
THT → `*.Cu *.Mask`.

---

## Масштаб и `--dpi`

По умолчанию размеры берутся «как в SVG»: 1 user unit = 1 пиксель при
96 dpi. Для SVG, у которых `width` и `viewBox` заданы в миллиметрах,
это даёт размер 1:1.

Чтобы получить **уменьшенную плату**, увеличьте `--dpi`:

| Команда | Размер платы из SVG 100×100 |
|---|---|
| `--dpi 96` (по умолчанию) | 100 мм |
| `--dpi 192` | 50 мм |
| `--dpi 384` | 25 мм |

Формула: `итоговый_размер = исходный_размер × 96 / DPI`.

---

## Проверки и ошибки

Скрипт строгий: он не пытается угадать, что имел в виду пользователь.
Если правила нарушены — генерация останавливается, файл не пишется.

**Уровни сообщений:**

- `[i]` — информация, ничего не значит.
- `[WARN]` — объект не распознан, пропускаем, но работаем дальше.
- `[ERROR]` — генерация останавливается, файл не создаётся.

**Что вызывает ERROR:**

- Некорректная группа THT (не то количество элементов, не те цвета).
- Drill и pad не совпадают по центру (> 0.1 мм).
- Via без пары или с разными радиусами.
- Пустая Net-метка (`Net` без имени).
- Конфликт «метка vs цвет» в одной цепи.
- Наложение SMD-пада на отверстие THT или NPTH (см. ниже).
- SMD-пад пересекается с via (по умолчанию; разрешается флагом
  `--allow-via-in-pad`).
- Отсутствие замкнутого контура платы.

**Что вызывает WARN:**

- Неизвестное имя слоя.
- Фигура без заливки и обводки.
- Метка без префикса `Net` (игнорируется).
- SMD-пад на via при активном `--allow-via-in-pad` (разрешено, но
  с предупреждением).

### Почему SMD-пад над отверстием — это ошибка

Если SMD-площадка перекрывает отверстие (THT-пад, via или NPTH), при
оплавлении в печи припой на площадке станет жидким и под действием
капиллярного эффекта затянется в отверстие. Это приведёт к:

- недостатку припоя под компонентом;
- закупорке отверстия;
- риску замыкания с соседними цепями.

Скрипт **не создаст файл**, пока такое перекрытие не будет устранено.
Если вам осознанно нужен **via-in-pad** (для BGA или отвода тепла),
запустите скрипт с флагом `--allow-via-in-pad`. Флаг **не действует**
для THT и NPTH — только для via.

---

## Опции командной строки

```
python svg2kicad.py input.svg output.kicad_pcb [опции]

  --dpi N
        Масштаб. По умолчанию 96 (классические 96 px/inch).
        Больше значение → меньше плата.

  --via-mode MODE
        Режим вывода переходных отверстий:
          pad (по умолчанию) — via как THT-пад в отдельном футпринте
              svg:vias. Работает с плагином FreeRouting (KiCad 10),
              у которого краш на pre-placed via. Функционально
              идентично настоящей via.
          via — канонический объект (via ...). Для standalone
              FreeRouting, который корректно обрабатывает pre-placed
              via. Плагин KiCad 10 в этом режиме падает.

  --allow-via-in-pad
        Разрешить наложение SMD-пада на via (via-in-pad).
        По умолчанию такое наложение = ERROR, потому что паста затечёт
        в отверстие при оплавлении. Для THT и NPTH это разрешение не
        действует.

  --check-only
        Только валидация, файл не пишется.
        Удобно для отладки SVG.

  --log FILE
        Дублировать вывод в указанный файл.

  --debug
        Подробный разбор каждой фигуры.

  --version
        Версия скрипта.

  --help
        Русская справка.

  --help-en
        Английская справка.
```

---

## Примеры

В репозитории есть примеры в папке `examples/`:

- `01_minimal.svg` — квадрат, три пада (THT, SMD F, SMD B), одна via.
- `02_tht_group.svg` — группа сквозного пада с drill, pad и шелкографией.
- `03_rules.svg` — контур + зоны запрета.

Скриншоты результатов — в `docs/`.

---

## Ограничения

Скрипт **не** умеет и не планирует в MVP:

- Работать с форматами кроме Inkscape SVG (Illustrator, Corel, DXF,
  HPGL и т. п.).
- Размещать компоненты с Reference Designator'ами (`R1`, `U1` и т. п.).
  Все пады попадают в виртуальные футпринты `#PWR01`, `#PWR02` и т. д.
  Реальные позиционные обозначения ставьте после импорта в KiCad.
- Поддерживать 4+ слоя меди.
- Размещать BGA, via-in-pad (кроме как через флаг), слепые/скрытые via.
- Работать со скруглениями на падах (только circle / rect).
- Импортировать текст как `<text>` — только `Path → Object to Path`.

Эти ограничения — сознательный выбор для простоты и надёжности.

---

<a name="известные-проблемы-ru"></a>
## Известные проблемы

### Плагин FreeRouting в KiCad 10 падает на pre-placed via

**Симптом:** при запуске плагина **FreeRouting** (встроенного в KiCad 10)
трассировка падает с ошибкой, если в `.kicad_pcb` есть хотя бы один объект
`(via ...)`. Размер, положение и слой via значения не имеют — падает на
любой.

**Причина:** баг плагина. KiCad 10 выгружает pre-placed via в секцию
`wiring` файла `.dsn`, и FreeRouting не может её обработать. Удаление via
из `.kicad_pcb` полностью устраняет краш.

**Решение:** скрипт по умолчанию (`--via-mode pad`) записывает via как
**THT-пад без открытия маски** в отдельном футпринте `svg:vias`.
Функционально это идентично настоящей via: медь на F.Cu и B.Cu плюс
металлизированное отверстие, соединяющее слои. Плагин видит это как
обычный pin и трассирует нормально.

**Как получить «настоящие» via:** используйте флаг
`--via-mode via` — скрипт запишет канонические объекты `(via ...)`.
Это подходит для **standalone-версии FreeRouting** (Java-приложение,
работает с `.dsn` напрямую). Плагин KiCad 10 на этом режиме упадёт.

**Как это выглядит в KiCad:** в режиме `pad` via отображается как
маленький круглый пад с номером `V1`, `V2`, и т. д. В режиме `via` —
как стандартный значок via. На производство это не влияет.

### Keepout-зоны и FreeRouting

FreeRouting корректно учитывает keepout-зону только когда она объявлена
на **обоих** медных слоях. Скрипт добавляет зону как в секцию F.Cu,
так и в B.Cu автоматически — специально ничего делать не нужно.

Если после экспорта DSN из KiCad зона не сработала — проверьте, что в
файле `.dsn` есть две строки `(keepout "" (polygon F.Cu ...))` и
`(keepout "" (polygon B.Cu ...))`.

---

<a name="faq-ru"></a>
## FAQ

**Q: Моя буква «A» отображается в KiCad как сплошной треугольник, а не буква.**
A: Проверьте, что текст конвертирован в path (**Path → Object to Path**).
Также убедитесь, что цвет ровно `#FFFFFF` — если это `#f9f9f9`, скрипт
сочтёт это цветным pad'ом.

**Q: Плата получилась слишком большой.**
A: Увеличьте `--dpi`. Например, `--dpi 384` уменьшит в 4 раза.

**Q: FreeRouting игнорирует зоны запрета.**
A: Проверьте, что в `.dsn` есть две строки `(keepout ...)` — для F.Cu
и для B.Cu. Скрипт добавляет их автоматически, но если зона была
нарисована как открытый path, она не попадёт.

**Q: Получаю ERROR «SMD-пад пересекается с отверстием».**
A: Уберите SMD-пад в этой точке. THT-пад уже даёт медь на обеих
сторонах, а via уже соединяет слои. Если это осознанный via-in-pad —
используйте `--allow-via-in-pad`.

**Q: FreeRouting plugin падает на моём файле. Что делать?**
A: Проверьте, что используете режим `--via-mode pad` (это по умолчанию).
Если запускаете без флага и всё равно падает — откройте `.kicad_pcb`
в текстовом редакторе и убедитесь, что в файле нет строк, начинающихся
с `(via `. Если есть — пересоберите через `--via-mode pad`.

**Q: Как задать имя цепи?**
A: В Inkscape: **Object → Object Properties → Label** → впишите `NetVCC`.
Скрипт создаст цепь `VCC`.

**Q: У меня пустой слой — это ошибка?**
A: Нет. Скрипт напишет «отсутствует», продолжит работу.

**Q: Как получить «настоящие» via, а не пады?**
A: Запустите с `--via-mode via`. Учтите, что встроенный плагин
FreeRouting в KiCad 10 на таких файлах падает — используйте
standalone FreeRouting.

---

## Лицензия

MIT. Используйте свободно, в том числе в коммерческих проектах.
Автор не несёт ответственности за брак платы, ошибки проектирования и
любые последствия использования. **Всегда проверяйте файл в KiCad и
заказывайте тестовую партию перед серийным производством.**

---

## Благодарности

- [svgelements](https://github.com/meerk40t/svgelements) — парсинг SVG.
- Сообществу KiCad — за прекрасный формат и открытую экосистему.
- [FreeRouting](https://github.com/freerouting/freerouting) — за
  автоматическую трассировку, которая кушает экспорт KiCad.

---

<a name="english"></a>
# svg2kicad — English

**Inkscape SVG → KiCad `.kicad_pcb`** converter for artists, makers, and
small projects. Converts vector graphics into a production-ready printed
circuit board: pads, drills, vias, silkscreen, keepout zones, and board
edge outline.

The script reads a standard Inkscape file where objects are arranged into
layers with specific names and generates a `.kicad_pcb` file that opens
in KiCad 8+ and routes cleanly in FreeRouting without manual
post-processing.

---

## Table of Contents

- [Why is this needed?](#why-is-this-needed)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [SVG Construction Rules](#svg-construction-rules)
  - [Layers](#layers)
  - [Colors](#colors)
  - [Net Names](#net-names)
  - [THT Group](#tht-group)
  - [SMD Pads](#smd-pads)
  - [Vias](#vias)
  - [Board Outline](#board-outline)
  - [Keepout Zones](#keepout-zones)
  - [Silkscreen](#silkscreen)
- [Output File Structure](#output-file-structure)
- [Scaling and `--dpi`](#scaling-and---dpi)
- [Validations and Errors](#validations-and-errors)
- [Command Line Options](#command-line-options)
- [Examples](#examples)
- [Limitations](#limitations)
- [Known Issues](#known-issues-en)
- [FAQ](#faq-en)
- [License](#license)
- [Acknowledgments](#acknowledgments)

---

## Why is this needed?

If you are drawing an artistic PCB, a lamp, a decorative map, or a small
electronic project in Inkscape, you need to convert your artwork into a
format that a PCB manufacturer can understand. Normally, this involves
tedious manual work in KiCad: placing pads, aligning drill holes, drawing
board outlines, and defining keepout zones. `svg2kicad` automates this
process entirely.

The script **does not replace** KiCad. It handles the initial drafting:
turning vector artwork into a structured board file. You then open the
`.kicad_pcb` in KiCad, run DRC checks, make manual adjustments if
necessary, and execute routing via FreeRouting.

---

## Installation

Requires **Python 3.9+** and the `svgelements` library.

```bash
pip install svgelements
```

The script is contained in a single file: `svg2kicad.py`. Download it
into your working directory and run it directly.

---

## Quick Start

```bash
python svg2kicad.py input.svg output.kicad_pcb
```

That's it! Open `output.kicad_pcb` in KiCad and verify design rules
(**Inspect → Design Rules Checker**).

---

## SVG Construction Rules

The script recognizes objects **by layer name** (`inkscape:label`). All
construction rules must be strictly followed; otherwise, objects will be
ignored (`WARN`) or file generation will fail (`ERROR`).

### Layers

| Layer Name | Purpose |
| --- | --- |
| `THT` | Through-hole pad groups: drill + pad + optional silk |
| `F.Pad` | SMD pads on F.Cu and upper via pads |
| `B.Pad` | SMD pads on B.Cu and lower via pads |
| `Drill` | Standalone non-plated through-holes (NPTH) |
| `F.SilkS` | Top silkscreen |
| `B.SilkS` | Bottom silkscreen |
| `F.Rule` | Keepout zone on F.Cu |
| `B.Rule` | Keepout zone on B.Cu |
| `Edge.Cuts` | Board outline |

Layers are created in Inkscape via **Layer → Add Layer…** and renamed via
**Layer → Rename Layer…** to match the exact layer names in the table
above (case-sensitive).

Any unlisted layers are silently ignored.

### Colors

Object colors act as **semantic markers**, not visual decorations. There
are three primary roles:

| Color | Meaning |
| --- | --- |
| `#000000` (black) | Drill hole |
| `#FFFFFF` (white) | Silk / Silkscreen |
| Any other color | Pad footprint; color value = Net ID |

CSS color names (`black`, `white`, `red`) are recognized and normalized
to hex. Colors like `#f9f9f9` are **not white** — they are treated as
colored pads. Be careful: copying text without resetting fill color
might turn it into a pad, causing an `ERROR`. Always verify pure
`#FFFFFF` for silkscreen elements.

### Net Names

Net names can be defined in two ways:

1. **By Color:** If no label is set, all pads of the exact same color
   belong to the same net. The net name equals the hex color without
   `#` (e.g., `ffd42a`).
2. **By `Net<Name>` Label:** In Inkscape, set **Object → Object
   Properties → Label**. A label formatted as `NetVCC`, `NetAnode`, or
   `NetGND` creates nets named `VCC`, `Anode`, or `GND`. The `Net`
   prefix is stripped exactly once (`NetNetAnode` → `NetAnode`).

**Label Priority:** If a pad has a `Net<Name>` label, it takes
precedence, and the fill color serves only as a visual marker. Conflicts
(e.g., same color with different net labels, or vice versa) trigger an
**ERROR**.

Labels without the `Net` prefix are ignored by the script.

### THT Group

Through-hole technology (THT) pads (for leaded components, connectors,
headers) are defined as a **group of 2 or 3 elements** inside the `THT`
layer.

**Rule:** Inside the group, elements must strictly fulfill roles
determined by **color**:

1. **Black circle or rectangle** — drill hole. A rectangle is treated as
   an oval slot.
2. **Colored circle or rectangle** — copper pad.
3. **White element or path without fill and with white stroke** — silk
   outline (optional). Multiple silkscreen paths are allowed.

**Group Example:**

```xml
<g inkscape:label="THT" inkscape:groupmode="layer">
  <g id="my_tht_pad">
    <circle cx="25" cy="20" r="0.4" fill="#000000"/>  <!-- drill -->
    <circle cx="25" cy="20" r="1.5" fill="#ff0000"
            inkscape:label="NetVCC"/>                 <!-- pad -->
    <path d="..." fill="#ffffff"/>                    <!-- silk (opt.) -->
  </g>
</g>
```

**Rules:**

* One THT group = exactly one drill + one pad + optional silk.
* Drill and pad **must share the exact same center** (tolerance: 0.1 mm).
* A drill without a copper pad results in an NPTH (mechanical hole) + silk.
* A copper pad without a drill results in an SMD pad on F.Cu.
* A group containing neither drill nor pad triggers an ERROR.
* **Drill and pad cannot be `<path>` elements** — only `circle` or
  `rect`. A colored path inside THT will trigger an ERROR.

### SMD Pads

Filled circles and rectangles on the `F.Pad` and `B.Pad` layers:

* `F.Pad` → SMD pad on F.Cu;
* `B.Pad` → SMD pad on B.Cu.

**Rules:**

* Supports `circle` or `rect` shapes only. Paths on `F.Pad`/`B.Pad` are
  not supported.
* Fill color is required; strokes must be removed.
* Fill color defines the net color.

### Vias

A via connects F.Cu and B.Cu layers. It is defined as **two circles with
identical stroke color**: one on `F.Pad` and one on `B.Pad`.

**Rules:**

* Both circles must be `circle` elements without fill (`fill="none"`),
  stroke only.
* Center coordinates, radii, and stroke colors **must match** (centers
  within 0.1 mm, radii within 0.001 mm).
* Unmatched via pairs trigger an ERROR.
* Via drill diameter is automatically set to 60% of the circle diameter.

**Example:**

```xml
<g inkscape:label="F.Pad">
  <circle cx="50" cy="50" r="0.6" fill="none" stroke="#00ff00"/>
</g>
<g inkscape:label="B.Pad">
  <circle cx="50" cy="50" r="0.6" fill="none" stroke="#00ff00"/>
</g>
```

**How vias are written to `.kicad_pcb`.** There are two output modes,
selected with `--via-mode`:

| Mode | What is written | Compatibility |
|---|---|---|
| `pad` (default) | via as a **THT pad** inside a dedicated footprint `svg:vias` | FreeRouting plugin (KiCad 10) |
| `via` | canonical `(via ...)` object | Standalone FreeRouting only |

See [Known Issues](#known-issues-en) for the background.

### Board Outline

The `Edge.Cuts` layer converts all closed shapes (`path`, `rect`,
`circle`) into board contour lines. Multiple shapes will all be included
in the outline.

The script automatically translates all geometry so that the top-left
bounding box corner rests at coordinate `(10, 10) mm`.

### Keepout Zones

Layers `F.Rule` and `B.Rule`. All closed shapes on these layers are
converted to copper keepout zones on their respective copper layers.

In KiCad, keepout zones prevent:

* Tracks
* Vias
* Pads
* Copper pour fills
* Footprints

Keepouts export properly to DSN files and are honored during FreeRouting
execution.

### Silkscreen

Layers `F.SilkS` and `B.SilkS`. Accepts `path`, `rect`, and `circle`.

**Fills are ignored** — only line contours are rendered. Line width is
derived from the SVG `stroke-width` attribute (in pixels) or defaults to
0.15 mm.

**Text must be converted to paths prior to processing:**
In Inkscape, select text and execute **Path → Object to Path**
(Ctrl+Shift+C). Otherwise, text elements will be ignored.

Complex paths with internal sub-contours (e.g., the letter "A" containing
an inner triangle) are correctly parsed into separate contours.

---

## Output File Structure

Outputs a `.kicad_pcb` file (format version `20231120`, compatible with
KiCad 8+).

Contains:

* **One or two generated footprints** holding all pads:
  * `svg:converted-F` — F.Cu and THT pads;
  * `svg:converted-B` — B.Cu pads (only if present).
* **Vias**:
  * with `--via-mode pad` — as THT pads inside a dedicated footprint
    `svg:vias`;
  * with `--via-mode via` — as standalone `(via ...)` objects.
* **NPTH** — organized into a dedicated footprint `svg:holes`.
* **Keepout Zones** — placed on F.Cu and/or B.Cu.
* **Silkscreen** — rendered as `gr_line`, `gr_rect`, `gr_circle`,
  `gr_poly`.
* **Board Outline** — `gr_line` elements on the Edge.Cuts layer.
* **Nets** — auto-assigned for each unique pad color or net label.

Copper layer setup: F.Cu (signal), B.Cu (power). Pads receive full layer
stacks: SMD F.Cu → `F.Cu F.Paste F.Mask`, SMD B.Cu → `B.Cu B.Paste B.Mask`,
THT → `*.Cu *.Mask`.

---

## Scaling and `--dpi`

By default, geometry scales according to SVG user units: 1 user unit =
1 pixel at 96 DPI. For SVG files with `width` and `viewBox` in
millimeters, this yields a 1:1 scale.

To produce a **scaled-down board**, increase `--dpi`:

| Command | Board Size (from 100×100 SVG) |
| --- | --- |
| `--dpi 96` (default) | 100 mm |
| `--dpi 192` | 50 mm |
| `--dpi 384` | 25 mm |

Formula: `final_size = original_size × 96 / DPI`.

---

## Validations and Errors

The conversion parser strictly enforces rule sets. If validation errors
occur, file generation aborts immediately without saving incomplete
output.

**Message levels:**

* `[i]` — Informational notice.
* `[WARN]` — Unrecognized or skipped object; execution continues.
* `[ERROR]` — Fatal validation failure; execution stops immediately.

**Triggers for ERROR:**

* Malformed THT group (invalid element count, incorrect colors).
* Drill and pad center misalignment exceeding 0.1 mm.
* Unpaired vias or mismatched via radii/colors.
* Empty Net label (`Net` without name suffix).
* Conflict between color net assignment and explicit net label.
* SMD pad overlapping THT or NPTH drill hole.
* SMD pad overlapping a via (by default; bypassable via
  `--allow-via-in-pad`).
* Missing or open board outline contour.

**Triggers for WARN:**

* Unrecognized layer name.
* Shape lacking both fill and stroke attributes.
* Label missing the required `Net` prefix (ignored).
* SMD pad over via when `--allow-via-in-pad` is active.

### Why SMD Pad over Hole is an Error

When an SMD pad covers a hole (THT drill, via, or NPTH), molten solder
will wick into the hole due to capillary action during reflow. This
causes:

* Solder starvation under component leads.
* Plugged holes.
* Increased risk of short circuits across adjacent copper nets.

The script **refuses to output files** until overlap issues are resolved.
If you deliberately require a **via-in-pad** (for high-density BGA or
thermal relief), pass `--allow-via-in-pad`. Note that this flag applies
**strictly to vias**, not THT or NPTH holes.

---

## Command Line Options

```
python svg2kicad.py input.svg output.kicad_pcb [options]

  --dpi N
        Scale DPI factor. Default is 96 (standard 96 px/inch).
        Higher value → smaller output board size.

  --via-mode MODE
        Vias output mode:
          pad (default) — vias as THT pads inside a dedicated footprint
              svg:vias. Works with the FreeRouting plugin (KiCad 10),
              which crashes on pre-placed vias. Functionally identical
              to a real via: copper on F.Cu and B.Cu + plated hole.
          via — canonical (via ...) object. For standalone FreeRouting,
              which handles pre-placed vias correctly. The KiCad 10
              plugin will crash in this mode.

  --allow-via-in-pad
        Permit SMD pad overlap with vias (via-in-pad design).
        By default, overlaps trigger ERROR due to reflow wicking risks.
        This flag does not apply to THT or NPTH holes.

  --check-only
        Perform validation check only without writing output PCB file.
        Useful for inspecting SVG layout errors.

  --log FILE
        Duplicate output log messages to specified file path.

  --debug
        Enable verbose parsing diagnostic messages for every shape.

  --version
        Show script version.

  --help
        Display Russian help text.

  --help-en
        Display English help text.
```

---

## Examples

Sample files are located in the `examples/` directory:

* `01_minimal.svg` — Square board, three pads (THT, SMD F, SMD B), one via.
* `02_tht_group.svg` — THT pad group featuring drill, copper pad, and
  silkscreen layer.
* `03_rules.svg` — Edge outline with keepout zones.

Rendered output screenshots are available in `docs/`.

---

## Limitations

The MVP implementation explicitly **does not** support:

* Non-Inkscape SVG formats (Adobe Illustrator, CorelDraw, DXF, HPGL,
  etc.).
* Component placement with Reference Designators (`R1`, `U1`, etc.). All
  pads map into virtual footprints `#PWR01`, `#PWR02`, etc. Assign real
  footprints inside KiCad after import.
* Multilayer stackups above 2 copper layers (4+ layers unsupported).
* BGA footprints, automatic blind/buried vias, or unflagged
  via-in-pads.
* Custom rounded-rectangle pads (only standard `circle` / `rect` shapes
  supported).
* Plain `<text>` elements — text must be converted via
  **Path → Object to Path**.

These constraints ensure parsing stability and code maintainability.

---

<a name="known-issues-en"></a>
## Known Issues

### FreeRouting plugin (KiCad 10) crashes on pre-placed vias

**Symptom:** the built-in **FreeRouting plugin** in KiCad 10 crashes
during routing whenever the `.kicad_pcb` file contains at least one
`(via ...)` object. Size, position, and layer do not matter — it crashes
on any.

**Cause:** a plugin bug. KiCad 10 exports pre-placed vias into the
`wiring` section of the `.dsn` file, and FreeRouting cannot process it.
Removing the via from `.kicad_pcb` eliminates the crash entirely.

**Solution:** by default, the script (`--via-mode pad`) writes vias as
**THT pads with no solder mask opening** inside a dedicated footprint
`svg:vias`. Functionally identical to a real via: copper on F.Cu and
B.Cu, plus a plated hole connecting the layers. The plugin sees this as
a regular pin and routes it correctly.

**To get "real" vias:** use `--via-mode via` — the script will write
canonical `(via ...)` objects. This is intended for the
**standalone FreeRouting** (Java app that reads `.dsn` directly). The
KiCad 10 plugin will crash in this mode.

**How this looks in KiCad:** in `pad` mode, vias appear as small round
pads labeled `V1`, `V2`, etc. In `via` mode — as the standard via
symbol. Manufacturing is unaffected either way.

### Keepout zones and FreeRouting

FreeRouting honors a keepout zone only when it is declared on **both**
copper layers. The script automatically adds the zone to both F.Cu and
B.Cu sections — no extra action needed.

If after exporting DSN from KiCad the zone is not honored — check that
the `.dsn` file contains both `(keepout "" (polygon F.Cu ...))` and
`(keepout "" (polygon B.Cu ...))` lines.

---

<a name="faq-en"></a>
## FAQ

**Q: My letter "A" appears in KiCad as a solid triangle instead of a
letter.**
A: Make sure the text was converted to paths (**Path → Object to Path**).
Also verify the color is exactly `#FFFFFF` — if it's `#f9f9f9`, the
script treats it as a colored pad.

**Q: The board came out too large.**
A: Increase `--dpi`. For example, `--dpi 384` will shrink it by 4×.

**Q: FreeRouting ignores my keepout zones.**
A: Check that the `.dsn` file contains two `(keepout ...)` lines — one
for F.Cu and one for B.Cu. The script adds both automatically, but if
the zone was drawn as an open path, it won't be included.

**Q: I get ERROR "SMD pad overlaps a hole".**
A: Remove the SMD pad at that location. The THT pad already provides
copper on both sides, and a via already connects the layers. If you
deliberately need via-in-pad, use `--allow-via-in-pad`.

**Q: The FreeRouting plugin crashes on my file. What to do?**
A: Make sure you are using `--via-mode pad` (this is the default). If
you run without the flag and it still crashes — open the `.kicad_pcb`
in a text editor and verify there are no lines starting with `(via `.
If there are, regenerate using `--via-mode pad`.

**Q: How do I assign a net name?**
A: In Inkscape: **Object → Object Properties → Label** → type `NetVCC`.
The script will create a net named `VCC`.

**Q: I have an empty layer — is that an error?**
A: No. The script will report it as "absent" and continue.

**Q: How do I get "real" vias instead of pads?**
A: Run with `--via-mode via`. Note that the built-in FreeRouting plugin
in KiCad 10 crashes on such files — use standalone FreeRouting instead.

---

## License

MIT License. Free for personal and commercial use. The author assumes no
liability for manufacturing defects, PCB design errors, or financial
losses. **Always run DRC checks in KiCad and order test prototypes prior
to mass production.**

---

## Acknowledgments

* [svgelements](https://github.com/meerk40t/svgelements) — SVG parsing
  engine.
* KiCad Community — for open file format standards and the toolchain
  ecosystem.
* [FreeRouting](https://github.com/freerouting/freerouting) — for
  automated PCB routing support.