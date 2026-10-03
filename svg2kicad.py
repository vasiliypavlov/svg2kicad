#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
svg2kicad.py — Inkscape SVG → KiCad .kicad_pcb converter (MVP).

Слои SVG (inkscape:label):
  THT       — группы сквозных падов THT: drill (чёрный) + pad (цветной) + silk (белый)
  F.Pad     — SMD-пады F.Cu (fill) / верх via (stroke, без fill)
  B.Pad     — SMD-пады B.Cu (fill) / низ via (stroke, без fill)
  Drill     — одиночные NPTH отверстия
  F.SilkS   — шелкография сверху
  B.SilkS   — шелкография снизу
  F.Rule    — зона запрета на F.Cu
  B.Rule    — зона запрета на B.Cu
  Edge.Cuts — контур платы

Net-метки: "NetXXX" → имя цепи "XXX". Конфликт метки и цвета = ERROR.
"""

import argparse
import math
import sys
import uuid
from collections import OrderedDict

try:
    from svgelements import (
        SVG, Group, Circle as SvCircle, Rect as SvRect,
        Path as SvPath, Polyline, Polygon,
        Text as SvText,
        Line, Close, Move, Matrix,
    )
except ImportError:
    sys.stderr.write("ERROR: нужна библиотека svgelements\n")
    sys.stderr.write("  pip install svgelements\n")
    sys.exit(2)


VERSION = "1.0.0"

DRILL_TOL_MM = 0.1
RADIUS_TOL_MM = 0.001
MARGIN_MM = 10.0
DEFAULT_SILK_STROKE_MM = 0.15
CURVE_SAMPLES = 16

L_THT   = "THT"
L_FPAD  = "F.Pad"
L_BPAD  = "B.Pad"
L_DRILL = "Drill"
L_FSILK = "F.SilkS"
L_BSILK = "B.SilkS"
L_FRULE = "F.Rule"
L_BRULE = "B.Rule"
L_EDGE  = "Edge.Cuts"

KNOWN_LAYERS = {L_THT, L_FPAD, L_BPAD, L_DRILL, L_FSILK, L_BSILK,
                L_FRULE, L_BRULE, L_EDGE}

INK_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"

C_BLACK = "#000000"
C_WHITE = "#ffffff"

CSS_NAMED = {
    'black': '#000000', 'white': '#ffffff', 'red': '#ff0000',
    'green': '#008000', 'blue': '#0000ff', 'yellow': '#ffff00',
    'cyan': '#00ffff', 'magenta': '#ff00ff', 'gray': '#808080',
    'grey': '#808080', 'silver': '#c0c0c0', 'maroon': '#800000',
    'olive': '#808000', 'lime': '#00ff00', 'aqua': '#00ffff',
    'teal': '#008080', 'navy': '#000080', 'fuchsia': '#ff00ff',
    'purple': '#800080', 'orange': '#ffa500',
}


# ============================================================================
# ЛОГГЕР
# ============================================================================

class Logger:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.debug = False
        self.fp = None

    def _emit(self, line):
        print(line)
        if self.fp:
            self.fp.write(line + '\n')

    def step(self, i, total, msg):
        self._emit("")
        self._emit(f"[STEP {i}/{total}] {msg}")

    def info(self, msg):
        self._emit(f"    [i] {msg}")

    def dbg(self, msg):
        if self.debug:
            self._emit(f"    [d] {msg}")

    def warn(self, layer=None, obj=None, msg="", hint=None):
        self.warnings.append((layer, obj, msg, hint))
        loc = f' layer="{layer}"' if layer else ''
        oid = f' object="{obj}"' if obj else ''
        self._emit(f"    [WARN]{loc}{oid} {msg}")
        if hint:
            self._emit(f"           hint: {hint}")

    def error(self, layer=None, obj=None, msg="", hint=None):
        self.errors.append((layer, obj, msg, hint))
        loc = f' layer="{layer}"' if layer else ''
        oid = f' object="{obj}"' if obj else ''
        self._emit(f"    [ERROR]{loc}{oid} {msg}")
        if hint:
            self._emit(f"           hint: {hint}")

    def summary(self):
        self._emit("")
        self._emit("=" * 60)
        if not self.errors and not self.warnings:
            self._emit("[OK] Ошибок и предупреждений нет.")
        else:
            self._emit(f"[ИТОГО] errors={len(self.errors)} warnings={len(self.warnings)}")
        self._emit("=" * 60)

    def close(self):
        if self.fp:
            self.fp.close()


LOG = Logger()


# ============================================================================
# УТИЛИТЫ
# ============================================================================

def fmt(v):
    s = f"{v:.6f}"
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s if s else "0"


def dedupe(pts, eps=1e-6):
    out = []
    for p in pts:
        if not out or abs(out[-1][0]-p[0]) > eps or abs(out[-1][1]-p[1]) > eps:
            out.append(p)
    return out


def el_id(el):
    return el.values.get('id') or '?'


def el_label(el):
    return el.values.get(INK_LABEL) or el.values.get('inkscape:label')


def _own_matrix(el):
    t = getattr(el, 'transform', None)
    return t if t is not None else Matrix()


def iter_shapes(el):
    if isinstance(el, Group):
        for c in el:
            yield from iter_shapes(c)
    else:
        yield el, _own_matrix(el)


def apply_pt(m, x, y):
    p = m.point_in_matrix_space((x, y))
    return float(p[0]), float(p[1])


def matrix_scale(m):
    try:
        return (math.hypot(m.a, m.b) + math.hypot(m.c, m.d)) / 2.0
    except AttributeError:
        p0 = m.point_in_matrix_space((0, 0))
        p1 = m.point_in_matrix_space((1, 0))
        p2 = m.point_in_matrix_space((0, 1))
        sx = math.hypot(p1[0]-p0[0], p1[1]-p0[1])
        sy = math.hypot(p2[0]-p0[0], p2[1]-p0[1])
        return (sx + sy) / 2.0


def circle_radius(c):
    for attr in ('r', 'rx', 'implicit_rx', 'ry', 'implicit_ry'):
        v = getattr(c, attr, None)
        if v is not None:
            return float(v)
    return 0.0


def circle_geom(c, m):
    x, y = apply_pt(m, c.cx, c.cy)
    return x, y, circle_radius(c) * matrix_scale(m)


def rect_corners(r, m):
    x, y, w, h = r.x, r.y, r.width, r.height
    pts = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
    return [apply_pt(m, px, py) for px, py in pts]


def path_to_polygons(path, m, samples=CURVE_SAMPLES):
    """Path → список полигонов (по одному на каждый subpath)."""
    result = []
    current = []

    for seg in path:
        if isinstance(seg, Move):
            if current and len(current) >= 2:
                result.append(current)
            current = []
            try:
                current.append(apply_pt(m, seg.end.x, seg.end.y))
            except Exception:
                pass
            continue

        try:
            e = apply_pt(m, seg.end.x, seg.end.y)
        except Exception:
            continue

        if isinstance(seg, (Line, Close)):
            if not current:
                try:
                    current.append(apply_pt(m, seg.start.x, seg.start.y))
                except Exception:
                    pass
            if (not current or
                abs(current[-1][0]-e[0]) > 1e-9 or
                abs(current[-1][1]-e[1]) > 1e-9):
                current.append(e)
        else:
            if not current:
                try:
                    current.append(apply_pt(m, seg.start.x, seg.start.y))
                except Exception:
                    pass
            for i in range(1, samples + 1):
                t = i / samples
                p = seg.point(t)
                current.append(apply_pt(m, p.x, p.y))

    if current and len(current) >= 2:
        result.append(current)

    return result


def path_to_polygon(path, m, samples=CURVE_SAMPLES):
    polys = path_to_polygons(path, m, samples)
    if not polys:
        return []
    return max(polys, key=len)


def polyline_to_polygon(shape, m):
    pts = []
    try:
        for p in shape.points:
            pts.append(apply_pt(m, p[0], p[1]))
    except Exception:
        return path_to_polygon(shape, m)
    return pts


def shape_to_polygon(shape, m):
    if isinstance(shape, SvCircle):
        x, y, r = circle_geom(shape, m)
        return [(x + r*math.cos(2*math.pi*i/48),
                 y + r*math.sin(2*math.pi*i/48)) for i in range(48)]
    if isinstance(shape, SvRect):
        return rect_corners(shape, m)
    if isinstance(shape, (Polyline, Polygon)):
        return polyline_to_polygon(shape, m)
    if isinstance(shape, SvPath):
        return path_to_polygon(shape, m)
    try:
        return path_to_polygon(shape, m)
    except Exception:
        return None


def shape_to_polygons(shape, m):
    if isinstance(shape, SvCircle):
        p = shape_to_polygon(shape, m)
        return [p] if p else []
    if isinstance(shape, SvRect):
        return [rect_corners(shape, m)]
    if isinstance(shape, SvPath):
        return path_to_polygons(shape, m)
    if isinstance(shape, (Polyline, Polygon)):
        return [polyline_to_polygon(shape, m)]
    p = shape_to_polygon(shape, m)
    return [p] if p else []


def normalize_color(c):
    if not c:
        return None
    c = c.strip().lower()
    if c in CSS_NAMED:
        return CSS_NAMED[c]
    if c.startswith('#'):
        if len(c) == 4:
            return '#' + ''.join(ch*2 for ch in c[1:])
        return c
    return c


def _get_style(el, key):
    style = el.values.get('style', '') or ''
    for item in style.split(';'):
        if ':' in item:
            k, v = item.split(':', 1)
            if k.strip() == key:
                return v.strip()
    return None


def get_fill(el):
    v = _get_style(el, 'fill')
    if v is None:
        v = el.values.get('fill')
    if not v or str(v).strip().lower() in ('none', 'transparent', ''):
        return None
    return normalize_color(str(v))


def get_stroke(el):
    v = _get_style(el, 'stroke')
    if v is None:
        v = el.values.get('stroke')
    if not v or str(v).strip().lower() in ('none', 'transparent', ''):
        return None
    return normalize_color(str(v))


def get_stroke_width_mm(el, dpi):
    v = _get_style(el, 'stroke-width')
    if v is None:
        v = el.values.get('stroke-width')
    if not v:
        return DEFAULT_SILK_STROKE_MM
    try:
        w = float(str(v).replace('px', '').replace('mm', '').strip())
        if w <= 0:
            return DEFAULT_SILK_STROKE_MM
        return w * 25.4 / dpi
    except Exception:
        return DEFAULT_SILK_STROKE_MM


def find_layers(svg):
    result = {}
    for el in svg.elements():
        if isinstance(el, Group):
            v = el_label(el)
            if v in KNOWN_LAYERS and v not in result:
                result[v] = el
            elif v and v not in KNOWN_LAYERS:
                LOG.dbg(f"Группа с неизвестным label='{v}' — игнорируется")
    return result


def warn_about_text(svg):
    """Ищем элементы <text> и предупреждаем, что они не будут сконвертированы."""
    found = []
    for el in svg.elements():
        if isinstance(el, SvText):
            found.append(el_id(el))

    if not found:
        return

    sample = ", ".join(found[:5])
    if len(found) > 5:
        sample += f" ... (всего {len(found)})"

    LOG.warn(
        None, sample,
        f"найдено {len(found)} элементов <text> — они не будут сконвертированы",
        hint=("в Inkscape выделите текст и выполните Path → Object to Path\n"
              "           (Ctrl+Shift+C), затем запустите скрипт снова")
    )


# ============================================================================
# МОДЕЛЬ
# ============================================================================

class Model:
    def __init__(self):
        self.pads = []       # каждый dict содержит 'side': 'F' | 'B' | 'THT'
        self.vias = []
        self.npths = []
        self.zones = []
        self.edges = []
        self.silk_f = []
        self.silk_b = []
        self.net_by_key = OrderedDict()
        self.net_names = {0: ""}

    def add_net(self, key):
        if key in self.net_by_key:
            return self.net_by_key[key]
        n = len(self.net_by_key) + 1
        self.net_by_key[key] = n
        self.net_names[n] = key
        return n


# ============================================================================
# БАЗОВЫЙ ПАРСИНГ
# ============================================================================

def parse_edge_cuts(group, dpi):
    contours = []
    for shape, m in iter_shapes(group):
        subpolys = shape_to_polygons(shape, m)
        if not subpolys:
            LOG.warn(L_EDGE, el_id(shape),
                     f"фигура {type(shape).__name__} не распознана, пропущена")
            continue
        for sp in subpolys:
            sp = dedupe(sp)
            if len(sp) >= 3:
                if abs(sp[0][0]-sp[-1][0]) < 1e-6 and abs(sp[0][1]-sp[-1][1]) < 1e-6:
                    sp = sp[:-1]
                contours.append([(x*25.4/dpi, y*25.4/dpi) for x, y in sp])
    return contours


def parse_rules(group, dpi, layer_name):
    zones = []
    for shape, m in iter_shapes(group):
        subpolys = shape_to_polygons(shape, m)
        if not subpolys:
            LOG.warn(layer_name, el_id(shape),
                     f"фигура {type(shape).__name__} не распознана, пропущена")
            continue
        for sp in subpolys:
            sp = dedupe(sp)
            if len(sp) >= 3:
                if abs(sp[0][0]-sp[-1][0]) < 1e-6 and abs(sp[0][1]-sp[-1][1]) < 1e-6:
                    sp = sp[:-1]
                zones.append({
                    'id': el_id(shape),
                    'layer': layer_name,
                    'points': [(x*25.4/dpi, y*25.4/dpi) for x, y in sp],
                })
    return zones


def parse_silk(group, dpi, layer_name, side):
    shapes = []
    for shape, m in iter_shapes(group):
        stroke_w = get_stroke_width_mm(shape, dpi)
        fill = get_fill(shape)
        stroke = get_stroke(shape)
        if fill and not stroke:
            LOG.warn(layer_name, el_id(shape),
                     "заливка игнорируется, используется только контур",
                     hint="на шелкографии KiCad поддерживает только линии")

        layer_str = 'F.SilkS' if side == 'F' else 'B.SilkS'

        if isinstance(shape, SvCircle):
            x, y, r = circle_geom(shape, m)
            shapes.append({
                'id': el_id(shape), 'stroke_mm': stroke_w,
                'layer': layer_str, 'kind': 'circle',
                'x': x * 25.4/dpi, 'y': y * 25.4/dpi,
                'r': r * 25.4/dpi,
            })
        elif isinstance(shape, SvRect):
            cs = rect_corners(shape, m)
            xs = [c[0] for c in cs]; ys = [c[1] for c in cs]
            shapes.append({
                'id': el_id(shape), 'stroke_mm': stroke_w,
                'layer': layer_str, 'kind': 'rect',
                'x': min(xs) * 25.4/dpi,
                'y': min(ys) * 25.4/dpi,
                'w': (max(xs) - min(xs)) * 25.4/dpi,
                'h': (max(ys) - min(ys)) * 25.4/dpi,
            })
        else:
            subpolys = shape_to_polygons(shape, m)
            if not subpolys:
                LOG.warn(layer_name, el_id(shape),
                         f"фигура {type(shape).__name__} не распознана, пропущена")
                continue
            for sp in subpolys:
                sp = dedupe(sp)
                if len(sp) < 2:
                    continue
                closed = (abs(sp[0][0]-sp[-1][0]) < 1e-6 and
                          abs(sp[0][1]-sp[-1][1]) < 1e-6)
                shapes.append({
                    'id': el_id(shape), 'stroke_mm': stroke_w,
                    'layer': layer_str, 'kind': 'poly',
                    'points': [(x*25.4/dpi, y*25.4/dpi) for x, y in sp],
                    'closed': closed,
                })
    return shapes


# ============================================================================
# THT: ГЕОМЕТРИЯ И КЛАССИФИКАЦИЯ
# ============================================================================

def shape_kind(shape):
    if isinstance(shape, SvCircle):
        return 'circle'
    if isinstance(shape, SvRect):
        return 'rect'
    return 'poly'


def _to_geom(shape, m, dpi):
    if isinstance(shape, SvCircle):
        x, y, r = circle_geom(shape, m)
        return {'kind': 'circle',
                'x': x*25.4/dpi, 'y': y*25.4/dpi, 'r': r*25.4/dpi}
    if isinstance(shape, SvRect):
        cs = rect_corners(shape, m)
        xs = [c[0] for c in cs]; ys = [c[1] for c in cs]
        return {'kind': 'rect',
                'x0': min(xs)*25.4/dpi, 'y0': min(ys)*25.4/dpi,
                'x1': max(xs)*25.4/dpi, 'y1': max(ys)*25.4/dpi}
    poly = path_to_polygon(shape, m)
    if not poly:
        return None
    return {'kind': 'poly',
            'points': [(x*25.4/dpi, y*25.4/dpi) for x, y in poly]}


def _to_silk_geoms(shape, m, dpi):
    if isinstance(shape, SvCircle):
        x, y, r = circle_geom(shape, m)
        return [{'kind': 'circle',
                 'x': x*25.4/dpi, 'y': y*25.4/dpi, 'r': r*25.4/dpi}]
    if isinstance(shape, SvRect):
        cs = rect_corners(shape, m)
        xs = [c[0] for c in cs]; ys = [c[1] for c in cs]
        return [{'kind': 'rect',
                 'x0': min(xs)*25.4/dpi, 'y0': min(ys)*25.4/dpi,
                 'x1': max(xs)*25.4/dpi, 'y1': max(ys)*25.4/dpi}]

    subpolys = shape_to_polygons(shape, m)
    result = []
    for sp in subpolys:
        sp = dedupe(sp)
        if len(sp) < 2:
            continue
        result.append({
            'kind': 'poly',
            'points': [(x*25.4/dpi, y*25.4/dpi) for x, y in sp],
        })
    return result


def _geom_center(g):
    if g['kind'] == 'circle':
        return g['x'], g['y']
    if g['kind'] == 'rect':
        return (g['x0']+g['x1'])/2, (g['y0']+g['y1'])/2
    pts = g['points']
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs)+max(xs))/2, (min(ys)+max(ys))/2


def _geom_size(g):
    if g['kind'] == 'circle':
        return 2*g['r'], 2*g['r']
    if g['kind'] == 'rect':
        return g['x1']-g['x0'], g['y1']-g['y0']
    pts = g['points']
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return max(xs)-min(xs), max(ys)-min(ys)


def _classify_sandwich(shapes, group_el, dpi):
    gid = el_id(group_el)
    group_label = el_label(group_el)

    drill = None
    pad = None
    silks = []

    for shape, m in shapes:
        sid = el_id(shape)
        fill = get_fill(shape)
        stroke = get_stroke(shape)
        kind = shape_kind(shape)

        if fill is None and stroke is None:
            LOG.warn(L_THT, sid,
                     f"фигура {kind} без заливки и обводки — пропущена")
            continue

        if fill == C_BLACK:
            if kind not in ('circle', 'rect'):
                LOG.error(L_THT, sid,
                          f"чёрный {kind} — drill должен быть круг или "
                          f"прямоугольник (овальный слот)",
                          hint="в THT drill — чёрный круг, или чёрный "
                               "прямоугольник для овального слота")
                return None
            if drill is not None:
                LOG.error(L_THT, gid,
                          "больше одного чёрного элемента (drill) "
                          "в группе",
                          hint="одна группа = один drill")
                return None
            g = _to_geom(shape, m, dpi)
            if not g:
                LOG.error(L_THT, sid, "не удалось разобрать drill")
                return None
            g['fill'] = fill
            g['id'] = sid
            g['label'] = el_label(shape)
            drill = g
            continue

        if fill == C_WHITE:
            geoms = _to_silk_geoms(shape, m, dpi)
            if not geoms:
                LOG.error(L_THT, sid, "не удалось разобрать silk")
                return None
            for g in geoms:
                g['fill'] = fill
                g['id'] = sid
                g['label'] = el_label(shape)
                silks.append(g)
            continue

        if fill:
            if kind not in ('circle', 'rect'):
                LOG.error(L_THT, sid,
                          f"цветной {kind} — pad должен быть круг или "
                          f"прямоугольник (fill={fill})",
                          hint="если это текст или кривая — задайте цвет "
                               "ровно #FFFFFF, тогда он уйдёт на silk")
                return None
            if pad is not None:
                LOG.error(L_THT, gid,
                          "больше одного цветного circle/rect (pad) "
                          "в группе",
                          hint="одна группа = один pad")
                return None
            g = _to_geom(shape, m, dpi)
            if not g:
                LOG.error(L_THT, sid, "не удалось разобрать pad")
                return None
            g['fill'] = fill
            g['id'] = sid
            g['label'] = el_label(shape)
            pad = g
            continue

        if stroke:
            if stroke == C_WHITE:
                geoms = _to_silk_geoms(shape, m, dpi)
                if not geoms:
                    LOG.error(L_THT, sid, "не удалось разобрать silk")
                    return None
                for g in geoms:
                    g['fill'] = None
                    g['id'] = sid
                    g['label'] = el_label(shape)
                    silks.append(g)
                continue
            else:
                LOG.error(L_THT, sid,
                          f"обводка {stroke} без заливки — недопустимо",
                          hint="в THT либо заливка (чёрная/цветная/белая), "
                               "либо белая обводка без заливки")
                return None

    if pad is not None and drill is not None:
        px, py = _geom_center(pad)
        dx, dy = _geom_center(drill)
        d = math.hypot(dx - px, dy - py)
        if d > DRILL_TOL_MM:
            LOG.error(L_THT, gid,
                      f"центр drill ({dx:.3f},{dy:.3f}) не совпадает "
                      f"с центром pad ({px:.3f},{py:.3f}); "
                      f"расстояние {d:.3f} мм > {DRILL_TOL_MM} мм",
                      hint="совместите центры drill и pad в Inkscape")
            return None
        return {'type': 'THT', 'id': gid,
                'pad': pad, 'drill': drill, 'silks': silks,
                'net_label': pad.get('label') or group_label}

    if pad is not None and drill is None:
        return {'type': 'SMD', 'id': gid,
                'pad': pad, 'drill': None, 'silks': silks,
                'net_label': pad.get('label') or group_label}

    if pad is None and drill is not None:
        return {'type': 'NPTH', 'id': gid,
                'pad': None, 'drill': drill, 'silks': silks,
                'net_label': None}

    LOG.error(L_THT, gid,
              "в группе нет ни pad (цветного), ни drill (чёрного)",
              hint="группа THT должна содержать хотя бы одно из двух")
    return None


def _sandwich_silk_to_model(s, model):
    info = {'id': s['id'],
            'stroke_mm': DEFAULT_SILK_STROKE_MM,
            'layer': 'F.SilkS'}
    if s['kind'] == 'circle':
        info['kind'] = 'circle'
        info['x'], info['y'], info['r'] = s['x'], s['y'], s['r']
    elif s['kind'] == 'rect':
        info['kind'] = 'rect'
        info['x'], info['y'] = s['x0'], s['y0']
        info['w'], info['h'] = s['x1']-s['x0'], s['y1']-s['y0']
    elif s['kind'] == 'poly':
        info['kind'] = 'poly'
        pts = s['points']
        info['points'] = pts
        info['closed'] = (len(pts) >= 2 and
                          abs(pts[0][0]-pts[-1][0]) < 1e-6 and
                          abs(pts[0][1]-pts[-1][1]) < 1e-6)
    model.silk_f.append(info)


def find_sandwiches(el):
    children = list(el)
    groups = [c for c in children if isinstance(c, Group)]
    shapes = [c for c in children if not isinstance(c, Group)]

    if shapes:
        if groups:
            LOG.error(L_THT, el_id(el),
                      "на одном уровне смешаны группы и фигуры",
                      hint="группа только с фигурами = один THT-пад; "
                           "контейнер = группа только с вложенными группами")
            return []
        return [el]

    result = []
    for g in groups:
        result.extend(find_sandwiches(g))
    return result


# ============================================================================
# F.Pad / B.Pad — SMD-пады и via
# ============================================================================

def _parse_pad_layer(layer_group, dpi, model, side, layer_name):
    """
    Общая логика для F.Pad и B.Pad.

    side = 'F' или 'B'.
    """
    for shape, m in iter_shapes(layer_group):
        sid = el_id(shape)
        fill = get_fill(shape)
        stroke = get_stroke(shape)

        # --- С заливкой без обводки → SMD-пад ---
        if isinstance(shape, (SvCircle, SvRect)) and fill and not stroke:
            if fill == C_BLACK:
                LOG.error(layer_name, sid,
                          f"чёрный пад на {layer_name} не имеет смысла",
                          hint="чёрный маркер допустим только внутри THT-группы")
                continue
            if fill == C_WHITE:
                LOG.error(layer_name, sid,
                          f"белый пад на {layer_name} не имеет смысла",
                          hint="белый маркер допустим только внутри THT-группы")
                continue

            if isinstance(shape, SvCircle):
                x, y, r = circle_geom(shape, m)
                model.pads.append({
                    'id': sid, 'side': side, 'kind': 'circle',
                    'x': x*25.4/dpi, 'y': y*25.4/dpi,
                    'size_x': 2*r*25.4/dpi, 'size_y': 2*r*25.4/dpi,
                    'color': fill, 'label': el_label(shape),
                    'drill_dia': None, 'drill_geom': None,
                })
            else:
                cs = rect_corners(shape, m)
                xs = [c[0] for c in cs]; ys = [c[1] for c in cs]
                model.pads.append({
                    'id': sid, 'side': side, 'kind': 'rect',
                    'x': (min(xs)+max(xs))/2*25.4/dpi,
                    'y': (min(ys)+max(ys))/2*25.4/dpi,
                    'size_x': (max(xs)-min(xs))*25.4/dpi,
                    'size_y': (max(ys)-min(ys))*25.4/dpi,
                    'color': fill, 'label': el_label(shape),
                    'drill_dia': None, 'drill_geom': None,
                })
            continue

        # --- Круг со stroke без fill → via-кандидат ---
        if isinstance(shape, SvCircle) and not fill and stroke:
            x, y, r = circle_geom(shape, m)
            attr = '_via_tops' if side == 'F' else '_via_bots'
            lst = getattr(model, attr, [])
            lst.append({
                'id': sid, 'x': x*25.4/dpi, 'y': y*25.4/dpi,
                'r': r*25.4/dpi, 'color': stroke,
            })
            setattr(model, attr, lst)
            continue

        if fill and stroke:
            LOG.error(layer_name, sid,
                      f"одновременно fill={fill} и stroke={stroke}",
                      hint="уберите либо заливку (для SMD), либо обводку (для via)")
            continue

        LOG.warn(layer_name, sid,
                 f"фигура {type(shape).__name__} с fill={fill} stroke={stroke} "
                 f"не подходит ни под SMD, ни под via — пропущена")


def parse_fpad(layer_group, dpi, model):
    _parse_pad_layer(layer_group, dpi, model, side='F', layer_name=L_FPAD)


def parse_bpad(layer_group, dpi, model):
    _parse_pad_layer(layer_group, dpi, model, side='B', layer_name=L_BPAD)


def parse_drill(layer_group, dpi, model):
    for shape, m in iter_shapes(layer_group):
        sid = el_id(shape)
        if not isinstance(shape, SvCircle):
            LOG.warn(L_DRILL, sid,
                     f"на слое Drill допустимы только circle — пропущено")
            continue
        x, y, r = circle_geom(shape, m)
        model.npths.append({
            'id': sid,
            'x': x*25.4/dpi, 'y': y*25.4/dpi,
            'dia': 2*r*25.4/dpi,
            'kind': 'circle',
        })


# ============================================================================
# ЦЕПИ
# ============================================================================

def resolve_nets(model):
    entries = []
    for p in model.pads:
        entries.append(('pad', p['color'], p['label'], p['id'], p))
    for v in model.vias:
        entries.append(('via', v['color'], v.get('label'), v['id'], v))

    color_to_names = {}
    name_to_colors = {}

    for kind, color, label, oid, obj in entries:
        net_name = None
        if label and label.startswith('Net'):
            net_name = label[3:]
            if not net_name:
                LOG.error(None, oid,
                          f"метка '{label}' — пустое имя цепи",
                          hint="укажите имя после префикса Net, например NetVCC")
                continue
        if net_name is not None:
            name_to_colors.setdefault(net_name, set()).add(color)
        if color:
            color_to_names.setdefault(color, set()).add(net_name)

    for color, names in color_to_names.items():
        names_non_none = {n for n in names if n is not None}
        if len(names_non_none) > 1:
            LOG.error(None, None,
                      f"цвет {color} используется для цепей: {sorted(names_non_none)}",
                      hint="одинаковый цвет должен соответствовать одной цепи")
    for name, colors in name_to_colors.items():
        colors_non_none = {c for c in colors if c is not None}
        if len(colors_non_none) > 1:
            LOG.error(None, None,
                      f"имя цепи '{name}' используется с цветами: {sorted(colors_non_none)}",
                      hint="одинаковое имя цепи должно иметь один цвет")

    if LOG.errors:
        return

    for kind, color, label, oid, obj in entries:
        net_name = None
        if label and label.startswith('Net') and len(label) > 3:
            net_name = label[3:]
        if net_name:
            n = model.add_net(net_name)
        elif color:
            n = model.add_net(color[1:] if color.startswith('#') else color)
        else:
            n = 0
        obj['net_num'] = n
        obj['net_name'] = model.net_names[n]


def match_vias(model):
    tops = getattr(model, '_via_tops', [])
    bots = getattr(model, '_via_bots', [])

    used_bots = set()
    for t in tops:
        best_i = None
        for i, b in enumerate(bots):
            if i in used_bots:
                continue
            dx = math.hypot(t['x'] - b['x'], t['y'] - b['y'])
            if dx > DRILL_TOL_MM:
                continue
            dr = abs(t['r'] - b['r'])
            if dr > RADIUS_TOL_MM:
                LOG.error(None, t['id'],
                          f"via: радиусы F.Pad ({t['r']:.4f}) и B.Pad ({b['r']:.4f}) "
                          f"различаются на {dr:.4f} мм",
                          hint="радиусы кругов via должны совпадать")
                continue
            if t['color'] != b['color']:
                continue
            best_i = i
            break
        if best_i is None:
            LOG.error(None, t['id'],
                      f"via-верх не имеет пары на B.Pad "
                      f"(x={t['x']:.3f} y={t['y']:.3f} color={t['color']})",
                      hint="создайте симметричный круг на слое B.Pad")
            continue
        b = bots[best_i]
        used_bots.add(best_i)
        model.vias.append({
            'id': t['id'],
            'x': t['x'], 'y': t['y'],
            'pad_dia': 2*t['r'],
            'drill_dia': 2*t['r'] * 0.6,
            'color': t['color'],
            'label': None,
        })

    for i, b in enumerate(bots):
        if i not in used_bots:
            LOG.error(None, b['id'],
                      f"via-низ не имеет пары на F.Pad "
                      f"(x={b['x']:.3f} y={b['y']:.3f})",
                      hint="создайте симметричный круг на слое F.Pad")


# ============================================================================
# ПРОВЕРКА SMD-OVER-DRILL
# ============================================================================

def _bbox_pad(p):
    """Bounding box пада (x0, y0, x1, y1). Без поворотов — у нас их нет."""
    if p['kind'] == 'circle':
        r = p['size_x'] / 2
        return (p['x']-r, p['y']-r, p['x']+r, p['y']+r)
    w, h = p['size_x'], p['size_y']
    return (p['x']-w/2, p['y']-h/2, p['x']+w/2, p['y']+h/2)


def _bbox_drill_from_tht(g):
    cx, cy = _geom_center(g)
    w, h = _geom_size(g)
    return (cx-w/2, cy-h/2, cx+w/2, cy+h/2)


def _bbox_via(v):
    dr = v['drill_dia'] / 2
    return (v['x']-dr, v['y']-dr, v['x']+dr, v['y']+dr)


def _bbox_npth(n):
    if n.get('kind') == 'oval':
        w, h = n['w'], n['h']
    else:
        w = h = n['dia']
    return (n['x']-w/2, n['y']-h/2, n['x']+w/2, n['y']+h/2)


def _bbox_overlap(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _npth_size_str(n):
    if n.get('kind') == 'oval':
        return f"{n['w']:.3f}×{n['h']:.3f}"
    return f"{n['dia']:.3f}"


def _emit_smd_over_drill_error(p, d):
    side = 'F.Cu' if p.get('side') == 'F' else 'B.Cu'
    LOG.error(
        None, p['id'],
        f"SMD-пад на {side} пересекается с отверстием {d['source']} "
        f"'{d['id']}' (drill {d['drill_str']} мм)",
        hint=(
            "Почему это ошибка:\n"
            "             при оплавлении в печи припой на SMD-площадке станет\n"
            "             жидким и под действием капиллярного эффекта затянется\n"
            "             в отверстие. Это приведёт к:\n"
            "               - недостатку припоя под компонентом;\n"
            "               - закупорке отверстия, которое должно остаться\n"
            "                 открытым (для вывода компонента или для via);\n"
            "               - риску замыкания с соседними цепями.\n"
            "           Что делать:\n"
            "             - уберите SMD-пад: THT-пад уже даёт медь на этой\n"
            "               стороне, via уже соединяет слои;\n"
            "             - или перенесите SMD-пад в другое место;\n"
            "             - для via-in-pad (BGA, теплоотвод) используйте флаг\n"
            "               --allow-via-in-pad (только для via, не для THT/NPTH)."
        )
    )


def check_smd_over_drill(model, allow_via_in_pad=False):
    """ERROR если SMD-пад пересекается с drill любого отверстия.

    Источники drill:
      - THT-пады      (drill_geom внутри пада)
      - vias          (отверстие via)
      - NPTH          (монтажные/крепежные отверстия)

    Исключение: SMD поверх via разрешается флагом --allow-via-in-pad.
    """
    drills = []

    for p in model.pads:
        if p.get('drill_geom') is not None:
            drills.append({
                'source': 'THT',
                'id': p['id'],
                'bbox': _bbox_drill_from_tht(p['drill_geom']),
                'drill_str': f"{_geom_size(p['drill_geom'])[0]:.3f}",
            })

    for v in model.vias:
        drills.append({
            'source': 'via',
            'id': v['id'],
            'bbox': _bbox_via(v),
            'drill_str': f"{v['drill_dia']:.3f}",
        })

    for n in model.npths:
        drills.append({
            'source': 'NPTH',
            'id': n['id'],
            'bbox': _bbox_npth(n),
            'drill_str': _npth_size_str(n),
        })

    if not drills:
        return

    for p in model.pads:
        # THT-пады исключаем: у них нет пасты, это не SMD.
        if p.get('drill_geom') is not None:
            continue

        p_bbox = _bbox_pad(p)
        for d in drills:
            if not _bbox_overlap(p_bbox, d['bbox']):
                continue

            if d['source'] == 'via' and allow_via_in_pad:
                LOG.warn(
                    None, p['id'],
                    f"SMD-пад на "
                    f"{'F' if p.get('side') == 'F' else 'B'}.Cu пересекается "
                    f"с via '{d['id']}' (drill {d['drill_str']} мм) — via-in-pad",
                    hint=("разрешено --allow-via-in-pad. Убедитесь, что фабрика\n"
                          "           сделает via fill (plugged / filled), иначе\n"
                          "           припой затечёт в отверстие. Для THT и NPTH\n"
                          "           это разрешение не действует.")
                )
                break

            _emit_smd_over_drill_error(p, d)
            break


# ============================================================================
# СМЕЩЕНИЕ
# ============================================================================

def apply_offset(model, off_x, off_y):
    def sh(o):
        if 'x' in o: o['x'] += off_x
        if 'y' in o: o['y'] += off_y
        if 'x0' in o: o['x0'] += off_x; o['y0'] += off_y
        if 'x1' in o: o['x1'] += off_x; o['y1'] += off_y

    for p in model.pads: sh(p)
    for v in model.vias: sh(v)
    for n in model.npths: sh(n)
    for z in model.zones:
        z['points'] = [(x+off_x, y+off_y) for x, y in z['points']]
    model.edges = [[(x+off_x, y+off_y) for x, y in c] for c in model.edges]
    for s in model.silk_f + model.silk_b:
        sh(s)
        if s.get('kind') == 'poly':
            s['points'] = [(x+off_x, y+off_y) for x, y in s['points']]


# ============================================================================
# ЗАПИСЬ .kicad_pcb
# ============================================================================

def _write_pad(w, p, name):
    drill_geom = p.get('drill_geom')
    side = p.get('side', 'F')

    if drill_geom is None:
        # SMD: layers зависят от стороны
        ptype = 'smd'
        drill_str = ''
        if side == 'B':
            layers_str = '(layers "B.Cu" "B.Paste" "B.Mask")'
        else:
            layers_str = '(layers "F.Cu" "F.Paste" "F.Mask")'
    else:
        ptype = 'thru_hole'
        dw, dh = _geom_size(drill_geom)
        if drill_geom['kind'] == 'circle':
            drill_str = f'(drill {fmt(dw)})'
        else:
            drill_str = f'(drill oval {fmt(dw)} {fmt(dh)})'
        layers_str = '(layers "*.Cu" "*.Mask")'

    shape = 'circle' if p['kind'] == 'circle' else 'rect'
    parts = [
        f'\t\t(pad "{name}" {ptype} {shape}',
        f'(at {fmt(p["x"])} {fmt(p["y"])})',
        f'(size {fmt(p["size_x"])} {fmt(p["size_y"])})',
    ]
    if drill_str:
        parts.append(drill_str)
    parts.append(layers_str)
    parts.append(f'(net {p["net_num"]} "{p["net_name"]}")')
    parts.append(f'(uuid "{uuid.uuid4()}"))')
    w(' '.join(parts))


def _write_footprint_header(w, name, layer, ref):
    w(f'\t(footprint "{name}"')
    w(f'\t\t(layer "{layer}")')
    w(f'\t\t(uuid "{uuid.uuid4()}")')
    w('\t\t(at 0 0)')
    w(f'\t\t(property "Reference" "{ref}" (at 0 0 0) (layer "F.SilkS") '
      f'(uuid "{uuid.uuid4()}") (effects (font (size 1 1) (thickness 0.15)) hide))')
    w(f'\t\t(property "Value" "{name}" (at 0 0 0) (layer "F.Fab") '
      f'(uuid "{uuid.uuid4()}") (effects (font (size 1 1) (thickness 0.15))))')


def write_kicad_pcb(model, path, gnd_pour_pts=None):
    out = []
    w = out.append

    w('(kicad_pcb')
    w('\t(version 20231120)')
    w('\t(generator "svg2kicad")')
    w(f'\t(generator_version "{VERSION}")')
    w('\t(general')
    w('\t\t(thickness 1.6)')
    w('\t\t(legacy_teardrops no)')
    w('\t)')
    w('\t(paper "A4")')
    w('\t(layers')
    LAYERS = [
        (0,  'F.Cu',       'signal', None),
        (31, 'B.Cu',       'power',  None),
        (32, 'B.Adhes',    'user',   'B.Adhesive'),
        (33, 'F.Adhes',    'user',   'F.Adhesive'),
        (34, 'B.Paste',    'user',   None),
        (35, 'F.Paste',    'user',   None),
        (36, 'B.SilkS',    'user',   'B.Silkscreen'),
        (37, 'F.SilkS',    'user',   'F.Silkscreen'),
        (38, 'B.Mask',     'user',   None),
        (39, 'F.Mask',     'user',   None),
        (40, 'Dwgs.User',  'user',   'User.Drawings'),
        (41, 'Cmts.User',  'user',   'User.Comments'),
        (42, 'Eco1.User',  'user',   'User.Eco1'),
        (43, 'Eco2.User',  'user',   'User.Eco2'),
        (44, 'Edge.Cuts',  'user',   None),
        (45, 'Margin',     'user',   None),
        (46, 'B.CrtYd',    'user',   'B.Courtyard'),
        (47, 'F.CrtYd',    'user',   'F.Courtyard'),
        (48, 'B.Fab',      'user',   None),
        (49, 'F.Fab',      'user',   None),
    ]
    for lid, lname, lkind, luser in LAYERS:
        if luser:
            w(f'\t\t({lid} "{lname}" {lkind} "{luser}")')
        else:
            w(f'\t\t({lid} "{lname}" {lkind})')
    w('\t)')
    w('\t(setup')
    w('\t\t(pad_to_mask_clearance 0)')
    w('\t)')

    w('\t(net 0 "")')
    for n in sorted(model.net_names):
        if n == 0:
            continue
        w(f'\t(net {n} "{model.net_names[n]}")')

    # Разделение падов: F+THT → один footprint, B → другой footprint.
    pads_f = [p for p in model.pads if p.get('side') in ('F', 'THT')]
    pads_b = [p for p in model.pads if p.get('side') == 'B']

    # --- Footprint F (включая все THT) ---
    if pads_f:
        _write_footprint_header(w, "svg:converted-F", "F.Cu", "#PWR01")
        for i, p in enumerate(pads_f):
            _write_pad(w, p, str(i + 1))
        w('\t)')

    # --- Footprint B (только SMD B.Cu) ---
    if pads_b:
        _write_footprint_header(w, "svg:converted-B", "B.Cu", "#PWR02")
        for i, p in enumerate(pads_b):
            _write_pad(w, p, str(i + 1))
        w('\t)')

    # --- NPTH ---
    if model.npths:
        ref_idx = 3 if pads_b else 2
        _write_footprint_header(w, "svg:holes", "F.Cu", f"#PWR{ref_idx:02d}")
        for n in model.npths:
            if n.get('kind') == 'oval':
                ww, hh = n['w'], n['h']
                w(f'\t\t(pad "" np_thru_hole oval (at {fmt(n["x"])} {fmt(n["y"])}) '
                  f'(size {fmt(ww)} {fmt(hh)}) '
                  f'(drill oval {fmt(ww)} {fmt(hh)}) '
                  f'(layers "*.Cu" "*.Mask") (uuid "{uuid.uuid4()}"))')
            else:
                d = n['dia']
                w(f'\t\t(pad "" np_thru_hole circle (at {fmt(n["x"])} {fmt(n["y"])}) '
                  f'(size {fmt(d)} {fmt(d)}) (drill {fmt(d)}) '
                  f'(layers "*.Cu" "*.Mask") (uuid "{uuid.uuid4()}"))')
        w('\t)')

    # --- Vias ---
    for v in model.vias:
        w(f'\t(via (at {fmt(v["x"])} {fmt(v["y"])}) '
          f'(size {fmt(v["pad_dia"])}) (drill {fmt(v["drill_dia"])}) '
          f'(layers "F.Cu" "B.Cu") '
          f'(net {v.get("net_num", 0)}) '
          f'(uuid "{uuid.uuid4()}"))')

    # --- Rule Area ---
    for z in model.zones:
        w('\t(zone')
        w('\t\t(net 0)')
        w('\t\t(net_name "")')
        w(f'\t\t(layers "{z["layer"]}")')
        w(f'\t\t(uuid "{uuid.uuid4()}")')
        w('\t\t(name "")')
        w('\t\t(hatch edge 0.5)')
        w('\t\t(connect_pads (clearance 0))')
        w('\t\t(min_thickness 0.25)')
        w('\t\t(filled_areas_thickness no)')
        w('\t\t(keepout')
        w('\t\t\t(copperpour not_allowed)')
        w('\t\t\t(vias not_allowed)')
        w('\t\t\t(tracks not_allowed)')
        w('\t\t\t(pads not_allowed)')
        w('\t\t\t(footprints not_allowed)')
        w('\t\t)')
        w('\t\t(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3))')
        w('\t\t(polygon')
        w('\t\t\t(pts')
        for x, y in z['points']:
            w(f'\t\t\t\t(xy {fmt(x)} {fmt(y)})')
        w('\t\t\t)')
        w('\t\t)')
        w('\t)')

    # --- GND pour на B.Cu ---
    if gnd_pour_pts:
        w('\t(zone')
        w('\t\t(net 0)')
        w('\t\t(net_name "")')
        w('\t\t(layer "B.Cu")')
        w(f'\t\t(uuid "{uuid.uuid4()}")')
        w('\t\t(name "")')
        w('\t\t(hatch edge 0.5)')
        w('\t\t(connect_pads (clearance 0.5))')
        w('\t\t(min_thickness 0.25)')
        w('\t\t(filled_areas_thickness no)')
        w('\t\t(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3))')
        w('\t\t(polygon')
        w('\t\t\t(pts')
        for x, y in gnd_pour_pts:
            w(f'\t\t\t\t(xy {fmt(x)} {fmt(y)})')
        w('\t\t\t)')
        w('\t\t)')
        w('\t)')

    # --- Silk ---
    for s in model.silk_f:
        _write_silk(w, s)
    for s in model.silk_b:
        _write_silk(w, s)

    # --- Edge.Cuts ---
    for contour in model.edges:
        n = len(contour)
        for i in range(n):
            x1, y1 = contour[i]
            x2, y2 = contour[(i + 1) % n]
            w(f'\t(gr_line (start {fmt(x1)} {fmt(y1)}) (end {fmt(x2)} {fmt(y2)}) '
              f'(stroke (width 0.05) (type default)) (layer "Edge.Cuts") '
              f'(uuid "{uuid.uuid4()}"))')

    w(')')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
        f.write('\n')


def _write_silk(w, s):
    layer = s['layer']
    sw = s['stroke_mm']
    uid = uuid.uuid4()
    if s['kind'] == 'circle':
        w(f'\t(gr_circle (center {fmt(s["x"])} {fmt(s["y"])}) '
          f'(end {fmt(s["x"]+s["r"])} {fmt(s["y"])}) '
          f'(stroke (width {fmt(sw)}) (type default)) (fill none) '
          f'(layer "{layer}") (uuid "{uid}"))')
    elif s['kind'] == 'rect':
        w(f'\t(gr_rect (start {fmt(s["x"])} {fmt(s["y"])}) '
          f'(end {fmt(s["x"]+s["w"])} {fmt(s["y"]+s["h"])}) '
          f'(stroke (width {fmt(sw)}) (type default)) (fill none) '
          f'(layer "{layer}") (uuid "{uid}"))')
    elif s['kind'] == 'poly':
        pts = s['points']
        if s.get('closed'):
            w(f'\t(gr_poly')
            w(f'\t\t(pts')
            for x, y in pts:
                w(f'\t\t\t(xy {fmt(x)} {fmt(y)})')
            w(f'\t\t)')
            w(f'\t\t(stroke (width {fmt(sw)}) (type default)) (fill none)')
            w(f'\t\t(layer "{layer}") (uuid "{uid}"))')
        else:
            for i in range(len(pts)-1):
                x1, y1 = pts[i]; x2, y2 = pts[i+1]
                w(f'\t(gr_line (start {fmt(x1)} {fmt(y1)}) (end {fmt(x2)} {fmt(y2)}) '
                  f'(stroke (width {fmt(sw)}) (type default)) (layer "{layer}") '
                  f'(uuid "{uuid.uuid4()}"))')


# ============================================================================
# HELP
# ============================================================================

HELP_RU = """\
svg2kicad — конвертер Inkscape SVG в KiCad .kicad_pcb.

ИСПОЛЬЗОВАНИЕ:
  python svg2kicad.py input.svg output.kicad_pcb [опции]

СЛОИ SVG (задаются через inkscape:label):

  THT        Группы сквозных падов (THT). Содержимое группы:
               - drill  = чёрный (#000000) круг или прямоугольник (слот);
               - pad    = цветной круг или прямоугольник;
               - silk   = белый (#FFFFFF) элемент, ИЛИ без заливки с белой обводкой.
             Одна группа = один drill + один pad + опц. silk.
             Если drill есть, а pad нет — отверстие становится NPTH.

  F.Pad      SMD-пады на F.Cu (заливка цветом) и верх via (stroke без fill).

  B.Pad      SMD-пады на B.Cu (заливка цветом) и низ via (stroke без fill).

  Drill      Одиночные неметаллизированные отверстия (NPTH).

  F.SilkS    Шелкография сверху.   F.Rule  — зона запрета на F.Cu.
  B.SilkS    Шелкография снизу.    B.Rule  — зона запрета на B.Cu.
  Edge.Cuts  Контур платы.

ЦВЕТА В THT:
  #000000  → drill (только круг или прямоугольник)
  #FFFFFF  → silk (любая фигура, включая path с буквами и кривыми)
  цветной  → pad (только круг или прямоугольник)
  без заливки + белая обводка → silk
  без заливки + цветная обводка → ERROR
  цветной path → ERROR (если это текст — задайте ровно #FFFFFF)

ИМЕНА ЦЕПЕЙ:
  Метка "NetXXX" (на паде или THT-группе) → имя цепи "XXX".
  Без метки — имя из цвета. Конфликт метки и цвета → ERROR.
  SMD-пад на B.Cu связывается с цепью на F.Cu через via того же цвета.

ТЕКСТ:
  Элементы <text> не поддерживаются. В Inkscape выделите текст и
  выполните Path → Object to Path (Ctrl+Shift+C) перед конвертацией.

ОПЦИИ:
  --dpi N         Масштаб (по умолчанию 96 = классические 96 px/inch).
                  Больше --dpi → меньше плата.
  --allow-via-in-pad
                  Разрешить наложение SMD-пада на via (via-in-pad).
                  По умолчанию такое наложение = ERROR, потому что паста
                  затечёт в отверстие при оплавлении. Для THT и NPTH
                  это разрешение не действует.
  --check-only    Только валидация, файл не пишется.
  --log FILE      Дублировать вывод в файл.
  --debug         Печатать разбор каждой фигуры.
  --version       Версия скрипта.
  --help-en       Английская справка.
"""

HELP_EN = """\
svg2kicad — Inkscape SVG to KiCad .kicad_pcb converter.

USAGE:
  python svg2kicad.py input.svg output.kicad_pcb [options]

SVG LAYERS (inkscape:label):

  THT        Through-hole pad groups. Group content:
               - drill = black (#000000) circle or rectangle (slot);
               - pad   = colored circle or rectangle;
               - silk  = white (#FFFFFF) element, OR no fill with white stroke.
             One group = one drill + one pad + opt. silk.
             If drill present and pad absent — hole becomes NPTH.

  F.Pad      SMD pads on F.Cu (colored fill) and via tops (stroke only).

  B.Pad      SMD pads on B.Cu (colored fill) and via bottoms (stroke only).

  Drill      Standalone NPTH holes.

  F.SilkS    Top silkscreen.      F.Rule  — keepout zone on F.Cu.
  B.SilkS    Bottom silkscreen.   B.Rule  — keepout zone on B.Cu.
  Edge.Cuts  Board outline.

COLORS IN THT:
  #000000  → drill (circle or rectangle only)
  #FFFFFF  → silk (any shape, including paths with letters and curves)
  colored  → pad (circle or rectangle only)
  no fill + white stroke → silk
  no fill + colored stroke → ERROR
  colored path → ERROR (if it is text, set color to exactly #FFFFFF)

NET NAMES:
  Label "NetXXX" (on a pad or THT group) → net name "XXX".
  Otherwise — derived from color. Color/label conflict → ERROR.
  SMD pads on B.Cu join the F.Cu net of the same color through a via.

TEXT:
  <text> elements are not supported. In Inkscape select the text and
  run Path → Object to Path (Ctrl+Shift+C) before conversion.

OPTIONS:
  --dpi N         Scale (default 96 = classic 96 px/inch).
                  Higher --dpi → smaller board.
  --allow-via-in-pad
                  Allow SMD pad to overlap a via (via-in-pad).
                  By default such an overlap is an ERROR: the solder paste
                  will wick into the hole during reflow. This does NOT
                  apply to THT or NPTH holes.
  --check-only    Validate only, no output file.
  --log FILE      Also write output to file.
  --debug         Verbose per-shape debug.
  --version       Script version.
  --help-en       English help.
"""


# ============================================================================
# CLI
# ============================================================================

def parse_args():
    argv = sys.argv[1:]
    if '--help-en' in argv:
        print(HELP_EN)
        sys.exit(0)
    if '--help' in argv or '-h' in argv or not argv:
        print(HELP_RU)
        sys.exit(0)
    if '--version' in argv:
        print(f"svg2kicad {VERSION}")
        sys.exit(0)

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--dpi', type=float, default=96.0)
    ap.add_argument('--check-only', action='store_true')
    ap.add_argument('--log', type=str, default=None)
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--allow-via-in-pad', action='store_true',
                    help='Разрешить наложение SMD-пада на via (для опытных)')
    return ap.parse_args(argv)


# ============================================================================
# MAIN
# ============================================================================

def main():
    args = parse_args()
    LOG.debug = args.debug
    if args.log:
        try:
            LOG.fp = open(args.log, 'w', encoding='utf-8')
        except Exception as e:
            sys.stderr.write(f"ERROR: не могу открыть лог {args.log}: {e}\n")

    print("=" * 60)
    print(f"  svg2kicad {VERSION}")
    print("=" * 60)

    total_steps = 8
    dpi = args.dpi
    px_to_mm = 25.4 / dpi

    LOG.step(1, total_steps, "Проверка аргументов")
    LOG.info(f"input      = {args.input}")
    LOG.info(f"output     = {args.output}")
    LOG.info(f"dpi        = {dpi} ({px_to_mm:.6f} мм на user unit)")
    LOG.info(f"check-only = {args.check_only}")

    LOG.step(2, total_steps, "Загрузка SVG")
    try:
        svg = SVG.parse(args.input)
    except Exception as e:
        LOG.error(None, None, f"не удалось прочитать SVG: {e}")
        LOG.summary()
        sys.exit(1)
    LOG.info("SVG успешно загружен")

    try:
        LOG.info(f"SVG width  = {svg.values.get('width')!r}")
        LOG.info(f"SVG height = {svg.values.get('height')!r}")
        LOG.info(f"SVG viewBox = {svg.values.get('viewBox')!r}")
    except Exception as e:
        LOG.warn(None, None, f"диагностика SVG не удалась: {e}")

    try:
        svg.reify()
        LOG.info("reify() выполнен — трансформации материализованы в координаты")
    except AttributeError:
        LOG.warn(None, None,
                 "svgelements не поддерживает reify() — координаты могут быть неточными",
                 hint="обновите библиотеку: pip install -U svgelements")
    except Exception as e:
        LOG.warn(None, None, f"reify() не сработал: {e}")

    # Проверка на наличие <text> (не поддерживается)
    warn_about_text(svg)

    LOG.step(3, total_steps, "Поиск слоёв")
    layers = find_layers(svg)
    for name in (L_THT, L_FPAD, L_BPAD, L_DRILL,
                 L_FSILK, L_BSILK, L_FRULE, L_BRULE, L_EDGE):
        if name in layers:
            LOG.info(f"  {name:<10} — найден")
        else:
            LOG.info(f"  {name:<10} — отсутствует")

    if not layers:
        LOG.error(None, None, "ни одного известного слоя не найдено")
        LOG.summary()
        sys.exit(1)

    LOG.step(4, total_steps, "Разбор объектов по слоям")
    model = Model()

    if L_EDGE in layers:
        model.edges = parse_edge_cuts(layers[L_EDGE], dpi)
        LOG.info(f"Edge.Cuts: {len(model.edges)} контуров")

    if L_FRULE in layers:
        model.zones += parse_rules(layers[L_FRULE], dpi, "F.Cu")
    if L_BRULE in layers:
        model.zones += parse_rules(layers[L_BRULE], dpi, "B.Cu")
    LOG.info(f"Rule Area: {len(model.zones)} зон")

    if L_THT in layers:
        sandwich_groups = find_sandwiches(layers[L_THT])
        LOG.info(f"THT: {len(sandwich_groups)} групп")

        for sg in sandwich_groups:
            shapes_with_m = list(iter_shapes(sg))
            LOG.dbg(f"  группа {el_id(sg)}: {len(shapes_with_m)} фигур")

            res = _classify_sandwich(shapes_with_m, sg, dpi)
            if not res:
                continue

            if res['type'] == 'THT':
                pad = res['pad']
                drill = res['drill']
                pad['drill_geom'] = drill
                pad['drill_dia'] = 2 * drill['r'] if drill['kind'] == 'circle' else None
                pad['color'] = pad.get('fill')
                pad['label'] = res.get('net_label')
                pad['side'] = 'THT'
                sx, sy = _geom_size(pad)
                pad['size_x'] = sx
                pad['size_y'] = sy
                px, py = _geom_center(pad)
                pad['x'] = px
                pad['y'] = py
                model.pads.append(pad)
                LOG.dbg(f"  THT {res['id']}: pad={pad['kind']} "
                        f"pos=({pad['x']:.3f},{pad['y']:.3f}) "
                        f"size={pad['size_x']:.3f}x{pad['size_y']:.3f}")

            elif res['type'] == 'SMD':
                pad = res['pad']
                pad['drill_geom'] = None
                pad['drill_dia'] = None
                pad['color'] = pad.get('fill')
                pad['label'] = res.get('net_label')
                pad['side'] = 'F'
                sx, sy = _geom_size(pad)
                pad['size_x'] = sx
                pad['size_y'] = sy
                px, py = _geom_center(pad)
                pad['x'] = px
                pad['y'] = py
                model.pads.append(pad)
                LOG.dbg(f"  SMD {res['id']}: pad={pad['kind']} "
                        f"pos=({pad['x']:.3f},{pad['y']:.3f})")

            elif res['type'] == 'NPTH':
                drill = res['drill']
                cx, cy = _geom_center(drill)
                w, h = _geom_size(drill)
                if drill['kind'] == 'circle':
                    model.npths.append({
                        'id': drill['id'],
                        'x': cx, 'y': cy,
                        'dia': w,
                        'kind': 'circle',
                    })
                else:
                    model.npths.append({
                        'id': drill['id'],
                        'x': cx, 'y': cy,
                        'w': w, 'h': h,
                        'kind': 'oval',
                    })
                LOG.info(f"  {res['id']}: техническое отверстие "
                         f"({drill['kind']}) {w:.3f}×{h:.3f} мм "
                         f"pos=({cx:.3f},{cy:.3f})")

            for silk in res['silks']:
                _sandwich_silk_to_model(silk, model)
                LOG.dbg(f"    silk {silk['id']}: {silk['kind']}")

    if L_FPAD in layers:
        n_before = len(model.pads)
        parse_fpad(layers[L_FPAD], dpi, model)
        LOG.info(f"F.Pad: +{len(model.pads) - n_before} падов, "
                 f"{len(getattr(model, '_via_tops', []))} via-верхов")

    if L_BPAD in layers:
        n_before = len(model.pads)
        parse_bpad(layers[L_BPAD], dpi, model)
        LOG.info(f"B.Pad: +{len(model.pads) - n_before} падов, "
                 f"{len(getattr(model, '_via_bots', []))} via-низов")

    if L_DRILL in layers:
        parse_drill(layers[L_DRILL], dpi, model)
        LOG.info(f"Drill: {len(model.npths)} NPTH")

    if L_FSILK in layers:
        n_before = len(model.silk_f)
        model.silk_f += parse_silk(layers[L_FSILK], dpi, L_FSILK, 'F')
        LOG.info(f"F.SilkS: {len(model.silk_f) - n_before} объектов")
    if L_BSILK in layers:
        n_before = len(model.silk_b)
        model.silk_b += parse_silk(layers[L_BSILK], dpi, L_BSILK, 'B')
        LOG.info(f"B.SilkS: {len(model.silk_b) - n_before} объектов")

    # Сводка по падам
    n_f = sum(1 for p in model.pads if p.get('side') == 'F')
    n_b = sum(1 for p in model.pads if p.get('side') == 'B')
    n_t = sum(1 for p in model.pads if p.get('side') == 'THT')
    LOG.info(f"Падов: F={n_f}, B={n_b}, THT={n_t}")

    LOG.step(5, total_steps, "Валидация и сборка")
    match_vias(model)
    LOG.info(f"Vias сопоставлено: {len(model.vias)}")
    check_smd_over_drill(model, allow_via_in_pad=args.allow_via_in_pad)
    resolve_nets(model)
    LOG.info(f"Цепей: {len(model.net_names) - 1}")

    if LOG.errors:
        LOG.summary()
        LOG.info("Обнаружены ошибки — файл не будет записан.")
        LOG.close()
        sys.exit(1)

    LOG.step(6, total_steps, "Смещение координат")
    if model.edges:
        pts = [p for c in model.edges for p in c]
        min_x = min(p[0] for p in pts)
        min_y = min(p[1] for p in pts)
        max_x = max(p[0] for p in pts)
        max_y = max(p[1] for p in pts)
        LOG.info(f"Размер контура: {(max_x-min_x):.3f} × {(max_y-min_y):.3f} мм")
    else:
        min_x = min_y = 0.0
    off_x = MARGIN_MM - min_x
    off_y = MARGIN_MM - min_y
    apply_offset(model, off_x, off_y)
    LOG.info(f"Смещение: dx={off_x:.3f} dy={off_y:.3f} мм")

    LOG.step(7, total_steps, "Заливка B.Cu")
    gnd_pour_pts = None
    if not model.pads and model.edges:
        pts = [p for c in model.edges for p in c]
        bx0, by0 = min(p[0] for p in pts) - 0.5, min(p[1] for p in pts) - 0.5
        bx1, by1 = max(p[0] for p in pts) + 0.5, max(p[1] for p in pts) + 0.5
        gnd_pour_pts = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
        LOG.info("Заливка B.Cu добавлена (падов нет)")
    else:
        LOG.info("Заливка B.Cu не требуется")

    LOG.step(8, total_steps, "Запись .kicad_pcb")
    if args.check_only:
        LOG.info("check-only: файл не пишется")
    else:
        try:
            write_kicad_pcb(model, args.output, gnd_pour_pts)
            LOG.info(f"Файл записан: {args.output}")
        except Exception as e:
            LOG.error(None, None, f"ошибка записи: {e}")
            LOG.summary()
            LOG.close()
            sys.exit(1)

    LOG.summary()
    LOG.close()
    print("[DONE] Конвертация успешно завершена.")


if __name__ == '__main__':
    main()
