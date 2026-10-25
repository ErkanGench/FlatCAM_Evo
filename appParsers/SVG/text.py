"""SVG text: layout of text chunks and glyph outlines through ParseFont."""
import logging
import re

from shapely.affinity import affine_transform, scale as shp_scale

from .document import parse_length

log = logging.getLogger('base')

_GENERIC = {
    'sans-serif': ['Arial', 'Segoe UI', 'DejaVu Sans', 'Liberation Sans', 'Helvetica', 'Verdana', 'Tahoma'],
    'serif': ['Times New Roman', 'DejaVu Serif', 'Liberation Serif', 'Georgia'],
    'monospace': ['Consolas', 'Courier New', 'DejaVu Sans Mono', 'Liberation Mono'],
}
_RENDER_SIZE = 100.0
_BASELINE = {'middle': 0.3, 'central': 0.35, 'hanging': 0.8, 'text-before-edge': 0.9, 'text-top': 0.9,
             'text-after-edge': -0.2, 'text-bottom': -0.2, 'mathematical': 0.35, 'ideographic': -0.1}
_SPLIT = re.compile(r'[\s,]+')
_TEXT_CHILDREN = ('tspan', 'a', 'textPath')


class _NoApp:
    """Minimal stand-in for the application object ParseFont expects."""

    class _Inform:
        @staticmethod
        def emit(*args, **kwargs):
            log.debug('SVG text: %s', args)

    inform = _Inform()


_MANAGER = None


def _font_manager(app):
    """
    :return: a ParseFont instance with the system fonts indexed or None when unavailable
    """
    global _MANAGER
    mgr = getattr(app, 'f_parse', None)
    if mgr is not None and getattr(mgr, 'regular_f', None):
        return mgr
    if _MANAGER is None:
        try:
            from appParsers.ParseFont import ParseFont
            _MANAGER = ParseFont(app if app is not None else _NoApp())
            _MANAGER.get_fonts_by_types()
        except Exception as exc:
            log.warning('SVG import: fonts are not available, text is skipped: %s', exc)
            _MANAGER = False
    return _MANAGER or None


class FontService:
    """Looks fonts up, renders runs of text as unit-em outlines and measures advances."""

    def __init__(self, app=None):
        self.app = app
        self.mgr = None
        self.ready = False
        self.found = {}
        self.cache = {}
        self.lower = {}

    def _init(self):
        if self.ready:
            return self.mgr is not None
        self.ready = True
        self.mgr = _font_manager(self.app)
        if self.mgr is not None:
            self.lower = {
                'regular': {k.lower(): k for k in self.mgr.regular_f},
                'bold': {k.lower(): k for k in self.mgr.bold_f},
                'italic': {k.lower(): k for k in self.mgr.italic_f},
                'bi': {k.lower(): k for k in self.mgr.bold_italic_f},
            }
        return self.mgr is not None

    def lookup(self, families, bold, italic):
        """
        :return: (name, type, file path) or None
        """
        key = (families, bold, italic)
        if key in self.found:
            return self.found[key]
        want = 'bi' if bold and italic else ('bold' if bold else ('italic' if italic else 'regular'))
        order = {'bi': ['bi', 'bold', 'italic', 'regular'], 'bold': ['bold', 'regular'],
                 'italic': ['italic', 'regular'], 'regular': ['regular']}[want]
        names = []
        for fam in families:
            names.extend(_GENERIC.get(fam.lower(), [fam]))
        names.extend(_GENERIC['sans-serif'])
        tables = {'regular': self.mgr.regular_f, 'bold': self.mgr.bold_f,
                  'italic': self.mgr.italic_f, 'bi': self.mgr.bold_italic_f}
        result = None
        for name in names:
            for kind in order:
                orig = self.lower[kind].get(name.lower())
                if orig:
                    result = (orig, kind, tables[kind][orig])
                    break
            if result:
                break
        if result is None and self.mgr.regular_f:
            orig = sorted(self.mgr.regular_f)[0]
            result = (orig, 'regular', self.mgr.regular_f[orig])
        self.found[key] = result
        return result

    def _advance(self, path, text):
        """Advance width in em from the same engine that rendered the run."""
        if self.mgr is None:
            return 0.5 * len(text)
        return self.mgr.text_advance(text, path, _RENDER_SIZE) / _RENDER_SIZE

    def render(self, text, families, bold, italic):
        """
        :return: (unit-em outline with y up or None, advance in em) or None when no font is usable
        """
        if not self._init():
            return None
        key = (families, bold, italic, text)
        if key in self.cache:
            return self.cache[key]
        font = self.lookup(families, bold, italic)
        result = None
        if font is not None:
            result = self._render(text, font)
        self.cache[key] = result
        return result

    def _render(self, text, font):
        from appParsers.ParseFont import ParseFont
        name, kind, path = font
        try:
            geom = self.mgr.font_to_geometry(text, name, kind, _RENDER_SIZE, 'MM', 0, 0)
            if isinstance(geom, str):
                log.warning('SVG text: %s', geom)
                geom = None
            if geom is None or geom.is_empty:
                geom = None
            else:
                u = 1.0 / (_RENDER_SIZE * 64.0 * ParseFont.SCALE_MM)
                geom = shp_scale(geom, u, u, origin=(0, 0))
            try:
                adv = self._advance(path, text)
            except Exception:
                adv = geom.bounds[2] if geom is not None else 0.5 * len(text)
            return geom, adv
        except Exception as exc:
            log.debug('SVG text: font rendering failed: %s', exc)
            return None


def _families(style):
    out = []
    for part in style['font-family'].split(','):
        part = part.strip().strip('"\'').strip()
        if part:
            out.append(part)
    return tuple(out) or ('sans-serif',)


def _is_bold(weight):
    if weight in ('bold', 'bolder'):
        return True
    try:
        return int(float(weight)) >= 600
    except ValueError:
        return False


def _number_list(text, ref, fs):
    vals = []
    for tok in _SPLIT.split(text.strip()):
        if tok:
            v = parse_length(tok, ref, fs)
            vals.append(0.0 if v is None else v)
    return vals


def _collect(text_el, style, own, resolve, vp, frame):
    """
    Walk the text tree.

    :return: (list of (char, style), dict name -> {char index: value})
    """
    chars = []
    pos = {'x': {}, 'y': {}, 'dx': {}, 'dy': {}}

    def add_text(s, st):
        preserve = st['white-space'] in ('pre', 'pre-wrap', 'break-spaces')
        for ch in (s or ''):
            if ch in '\r\n\t':
                ch = ' '
            if ch == ' ' and not preserve and (not chars or chars[-1][0] == ' '):
                continue
            chars.append((ch, st))

    def walk(el, st, el_own, fr):
        idx = len(chars)
        for name, store in pos.items():
            raw = el_own.get(name)
            if raw is None:
                raw = el.get(name)
            if raw:
                ref = vp[0] if name in ('x', 'dx') else vp[1]
                for k, v in enumerate(_number_list(raw, ref, st['font-size'])):
                    store[idx + k] = v
        add_text(el.text, st)
        for child in el:
            tag = child.tag
            if isinstance(tag, str):
                local = tag.rpartition('}')[2]
                if local in _TEXT_CHILDREN:
                    c_style, c_own, c_frame = resolve(child, local, st, fr)
                    if c_style['display'] != 'none':
                        walk(child, c_style, c_own, c_frame)
            add_text(child.tail, st)

    walk(text_el, style, own, frame)
    if chars and chars[-1][0] == ' ' and chars[-1][1]['white-space'] not in ('pre', 'pre-wrap', 'break-spaces'):
        chars.pop()
    return chars, pos


def _finalize(run, fonts):
    st = run['style']
    size = st['font-size']
    fam, bold = _families(st), _is_bold(st['font-weight'])
    italic = st['font-style'] in ('italic', 'oblique')
    rendered = fonts.render(run['text'], fam, bold, italic)
    run['geom'], adv = rendered if rendered is not None else (None, 0.5 * len(run['text']))
    run['adv'] = adv * size


def _layout(chars, pos, fonts):
    """Split the characters into chunks of runs with absolute positions."""
    px, py, pdx, pdy = pos['x'], pos['y'], pos['dx'], pos['dy']
    chunks, chunk, run, cx, cy = [], None, None, 0.0, 0.0
    for i, (ch, st) in enumerate(chars):
        absolute = i in px or i in py
        if not (absolute or i in pdx or i in pdy or run is None or run['style'] is not st):
            run['chars'].append(ch)
            continue
        if run is not None:
            run['text'] = ''.join(run.pop('chars'))
            _finalize(run, fonts)
            cx = run['x'] + run['adv']
        if absolute or chunk is None:
            cx, cy = px.get(i, cx), py.get(i, cy)
            chunk = {'runs': [], 'anchor': st['text-anchor']}
            chunks.append(chunk)
        cx, cy = cx + pdx.get(i, 0.0), cy + pdy.get(i, 0.0)
        run = {'chars': [ch], 'style': st, 'x': cx, 'y': cy}
        chunk['runs'].append(run)
    if run is not None:
        run['text'] = ''.join(run.pop('chars'))
        _finalize(run, fonts)
    return chunks


def layout_text(text_el, style, own, resolve, vp, fonts, frame=None):
    """
    :param text_el: ``<text>`` element
    :param style: computed style of the element
    :param own: specified properties of the element
    :param resolve: callable(child, local, parent_style, parent_frame) -> (style, own, frame)
    :param vp: viewport size in user units
    :param fonts: FontService
    :param frame: selector frame of the text element
    :return: list of (outline in user space, style of the run)
    """
    chars, pos = _collect(text_el, style, own, resolve, vp, frame)
    if not chars:
        return []
    out = []
    for chunk in _layout(chars, pos, fonts):
        runs = chunk['runs']
        width = runs[-1]['x'] + runs[-1]['adv'] - runs[0]['x']
        shift = {'middle': -width / 2.0, 'end': -width}.get(chunk['anchor'], 0.0)
        for run in runs:
            if run['geom'] is None:
                continue
            st = run['style']
            size = st['font-size']
            base = st['alignment-baseline'] if st['alignment-baseline'] != 'auto' else st['dominant-baseline']
            dy = _BASELINE.get(base, 0.0) * size
            out.append((affine_transform(run['geom'], [size, 0, 0, -size, run['x'] + shift, run['y'] + dy]), st))
    return out
