# Changelog

## [1.0.0] — 2026-10-03 первая публичная версия

- Конвертация Inkscape SVG → KiCad `.kicad_pcb` (формат 20231120).
- Поддержка слоёв: THT, F.Pad, B.Pad, Drill, F.SilkS, B.SilkS, F.Rule, B.Rule, Edge.Cuts.
- SMD-пады на F.Cu и B.Cu.
- Сквозные пады (THT) и via через совпадение stroke-кругов.
- Зоны запрета, совместимые с FreeRouting.
- Net-метки `Net<Имя>` с приоритетом над цветом.
- Строгая валидация: SMD-over-drill, конфликты меток, непарные via.
- Флаги `--dpi`, `--allow-via-in-pad`, `--check-only`, `--log`, `--debug`.