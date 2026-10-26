# appParsers/PdfText.py
"""
PDF text to glyph outlines.

ParsePDF reads only path operators. This module replaces each text object
(BT ... ET) of a content stream with the outlines of its glyphs, taken from the
font program embedded in the PDF (TrueType /FontFile2 or OpenType /FontFile3).
The other operators inside the text object (colors, gs, ...) stay in place.

The glyphs are filled (or stroked) as the text render mode (Tr) says; mode 3
(invisible text, e.g. an OCR layer) draws nothing. Text in a font that is not
embedded, or in a font type that fontTools cannot read here (Type1, bare CFF),
is dropped and the text object stays as 'BT ET', so ParsePDF can report it.
"""

from io import BytesIO
from typing import Callable, Dict, List, Optional
import logging
import re

log = logging.getLogger('base')

_WHITESPACE = b' \t\r\n\f\x00'
_DELIMITERS = b'()<>[]{}/%'
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(m1, m2):
    """PDF matrix product m1 x m2 (row vector convention)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def cid_widths(items: list) -> Dict[int, float]:
    """Read the /W array of a CID font: 'c [w1 w2 ...]' and 'c_first c_last w' entries."""
    widths = {}
    index = 0
    while index < len(items):
        first = items[index]
        if index + 1 < len(items) and isinstance(items[index + 1], list):
            for offset, width in enumerate(items[index + 1]):
                widths[int(first) + offset] = float(width)
            index += 2
        elif index + 2 < len(items):
            for code in range(int(first), int(items[index + 1]) + 1):
                widths[code] = float(items[index + 2])
            index += 3
        else:
            break
    return widths


def parse_array(raw: bytes) -> list:
    """Read a PDF array of numbers and nested arrays (the /W and /Widths values)."""
    stack = [[]]
    for token in re.findall(rb'\[|\]|[+-]?(?:\d+\.?\d*|\.\d+)', raw):
        if token == b'[':
            stack.append([])
        elif token == b']':
            if len(stack) > 1:
                done = stack.pop()
                stack[-1].append(done)
        else:
            stack[-1].append(float(token))
    result = stack[0]
    return result[0] if len(result) == 1 and isinstance(result[0], list) else result


class PdfFont:
    """A PDF font whose embedded program can give glyph outlines."""

    def __init__(self, program: bytes, two_byte: bool, widths: Dict[int, float],
                 default_width: Optional[float] = None, cid_to_gid: Optional[bytes] = None,
                 simple_encoding: bool = False):
        from fontTools.ttLib import TTFont

        self.font = TTFont(BytesIO(program), lazy=True)
        self.units_per_em = float(self.font['head'].unitsPerEm)
        self.glyph_set = self.font.getGlyphSet()
        self.glyph_order = self.font.getGlyphOrder()
        self.two_byte = two_byte
        self.widths = widths
        self.default_width = default_width
        self.cid_to_gid = cid_to_gid
        self.simple_encoding = simple_encoding
        self._outlines = {}
        self._cmaps = None

    def codes(self, data: bytes) -> List[int]:
        if self.two_byte:
            return [int.from_bytes(data[i:i + 2], 'big') for i in range(0, len(data) - 1, 2)]
        return list(data)

    def _gid(self, code: int) -> int:
        if self.cid_to_gid is not None:
            position = 2 * code
            return int.from_bytes(self.cid_to_gid[position:position + 2], 'big') \
                if position + 2 <= len(self.cid_to_gid) else 0
        if not self.simple_encoding:
            return code
        # simple TrueType font: the code goes through the cmap of the font program
        if self._cmaps is None:
            self._cmaps = []
            if 'cmap' in self.font:
                for platform, encoding in ((3, 0), (1, 0), (3, 1)):
                    table = self.font['cmap'].getcmap(platform, encoding)
                    if table is not None:
                        self._cmaps.append((platform, encoding, table.cmap))
        for platform, encoding, mapping in self._cmaps:
            for key in ((0xF000 | code, code) if (platform, encoding) == (3, 0) else (code,)):
                name = mapping.get(key)
                if name is not None:
                    return self.font.getGlyphID(name)
        return code

    def width(self, code: int) -> float:
        """The advance of a code in text space units (1/1000 of the font size)."""
        if code in self.widths:
            return self.widths[code]
        if self.default_width is not None:
            return self.default_width
        name = self._glyph_name(code)
        if name is not None and 'hmtx' in self.font:
            return self.font['hmtx'][name][0] * 1000.0 / self.units_per_em
        return 0.0

    def _glyph_name(self, code: int) -> Optional[str]:
        gid = self._gid(code)
        return self.glyph_order[gid] if 0 <= gid < len(self.glyph_order) else None

    def outline(self, code: int) -> list:
        """The outline of a glyph: [(operator, [points])] in font units, cached."""
        if code not in self._outlines:
            from fontTools.pens.basePen import BasePen

            name = self._glyph_name(code)
            commands = []

            class Pen(BasePen):
                def _moveTo(self, point):
                    commands.append(('m', [point]))

                def _lineTo(self, point):
                    commands.append(('l', [point]))

                def _curveToOne(self, p1, p2, p3):
                    commands.append(('c', [p1, p2, p3]))

                def _qCurveToOne(self, p1, p2):
                    # quadratic to cubic: the control points are 2/3 of the way to p1
                    p0 = self._getCurrentPoint()
                    c1 = (p0[0] + 2.0 / 3.0 * (p1[0] - p0[0]), p0[1] + 2.0 / 3.0 * (p1[1] - p0[1]))
                    c2 = (p2[0] + 2.0 / 3.0 * (p1[0] - p2[0]), p2[1] + 2.0 / 3.0 * (p1[1] - p2[1]))
                    commands.append(('c', [c1, c2, p2]))

                def _closePath(self):
                    commands.append(('h', []))

            if name is not None and name in self.glyph_set:
                try:
                    self.glyph_set[name].draw(Pen(self.glyph_set))
                except Exception as e:
                    log.debug(f"PDF text: glyph {name} has no usable outline: {e}")
                    commands.clear()
            self._outlines[code] = commands
        return self._outlines[code]


class _TextState:
    __slots__ = ('font', 'size', 'char_spacing', 'word_spacing', 'scale', 'leading', 'rise', 'render')

    def __init__(self):
        self.font = None
        self.size = 0.0
        self.char_spacing = 0.0
        self.word_spacing = 0.0
        self.scale = 1.0
        self.leading = 0.0
        self.rise = 0.0
        self.render = 0

    def copy(self):
        other = _TextState()
        for name in self.__slots__:
            setattr(other, name, getattr(self, name))
        return other


def _literal_string(data: bytes, index: int):
    """Read a literal string at index; return (value, end)."""
    escapes = {ord('n'): b'\n', ord('r'): b'\r', ord('t'): b'\t', ord('b'): b'\b', ord('f'): b'\f'}
    value = bytearray()
    depth = 1
    index += 1
    while index < len(data):
        char = data[index]
        if char == 0x5C:  # backslash
            index += 1
            if index >= len(data):
                break
            char = data[index]
            if char in escapes:
                value += escapes[char]
            elif 0x30 <= char <= 0x37:
                digits = re.match(rb'[0-7]{1,3}', data[index:index + 3]).group(0)
                value.append(int(digits, 8) & 0xFF)
                index += len(digits) - 1
            elif char in (0x0D, 0x0A):
                if char == 0x0D and data[index + 1:index + 2] == b'\n':
                    index += 1
            else:
                value.append(char)
        elif char == 0x28:
            depth += 1
            value.append(char)
        elif char == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(value), index + 1
            value.append(char)
        else:
            value.append(char)
        index += 1
    return bytes(value), index


def _tokens(data: bytes):
    """Yield (kind, value, start, end) tokens of a content stream."""
    index = 0
    length = len(data)
    while index < length:
        char = data[index:index + 1]
        if char in _WHITESPACE:
            index += 1
            continue
        if char == b'%':
            newline = re.compile(rb'[\r\n]').search(data, index)
            index = newline.end() if newline else length
            continue
        start = index
        if char == b'(':
            value, index = _literal_string(data, index)
            yield 'string', value, start, index
        elif data.startswith(b'<<', index):
            depth = 0
            while index < length:
                if data.startswith(b'<<', index):
                    depth += 1
                    index += 2
                elif data.startswith(b'>>', index):
                    depth -= 1
                    index += 2
                    if depth == 0:
                        break
                elif data[index:index + 1] == b'(':
                    index = _literal_string(data, index)[1]
                else:
                    index += 1
            yield 'dict', None, start, index
        elif char == b'<':
            end = data.find(b'>', index + 1)
            end = length if end < 0 else end
            digits = re.sub(rb'[^0-9A-Fa-f]', b'', data[index + 1:end])
            if len(digits) % 2:
                digits += b'0'
            index = end + 1
            yield 'string', bytes.fromhex(digits.decode('ascii')), start, index
        elif char == b'[':
            index += 1
            yield 'open', None, start, index
        elif char == b']':
            index += 1
            yield 'close', None, start, index
        elif char in b'{}>)':
            index += 1
        elif char == b'/':
            index += 1
            while index < length and data[index:index + 1] not in _WHITESPACE + _DELIMITERS:
                index += 1
            yield 'name', data[start + 1:index], start, index
        else:
            while index < length and data[index:index + 1] not in _WHITESPACE + _DELIMITERS:
                index += 1
            token = data[start:index]
            try:
                yield 'number', float(token), start, index
            except ValueError:
                yield 'operator', token, start, index
                if token == b'BI':
                    image_end = re.compile(rb'(?<!\S)EI(?!\S)').search(data, index)
                    end = image_end.end() if image_end else length
                    yield 'image', None, index, end
                    index = end


def _number(value, default=0.0) -> float:
    return float(value) if isinstance(value, float) else default


def _format(value: float) -> bytes:
    text = ('%.4f' % value).rstrip('0').rstrip('.')
    return (text if text not in ('', '-0') else '0').encode('ascii')


def text_to_paths(content: bytes, get_font: Callable[[bytes], Optional[PdfFont]]) -> bytes:
    """Replace the text objects of a content stream with their glyph outlines.

    get_font(name) returns the PdfFont of a /Font resource name, or None.
    Content without text objects is returned unchanged.
    """
    if not re.search(rb'(?<![^\s\]\)>])BT(?![^\s\[\(</%])', content):
        return content

    output = []
    copied_to = 0
    state = _TextState()
    stack = []
    in_text = False
    text_start = 0
    text_operators = 0
    text_out = []
    matrix = line_matrix = _IDENTITY
    operands = []
    arrays = []
    instruction_start = None

    def show(data: bytes):
        nonlocal matrix
        font = get_font(state.font) if state.font is not None else None
        if font is None:
            return False
        scale = state.scale
        path = []
        for code in font.codes(data):
            if state.render not in (3, 7):
                glyph_scale = state.size / font.units_per_em
                glyph_matrix = multiply((glyph_scale * scale, 0.0, 0.0, glyph_scale, 0.0, state.rise), matrix)
                a, b, c, d, e, f = glyph_matrix
                for operator, points in font.outline(code):
                    for x, y in points:
                        path.append(_format(a * x + c * y + e) + b' ' + _format(b * x + d * y + f))
                    path.append(operator.encode('ascii'))
            spacing = state.char_spacing
            if not font.two_byte and code == 32:
                spacing += state.word_spacing
            advance = (font.width(code) / 1000.0 * state.size + spacing) * scale
            matrix = multiply((1.0, 0.0, 0.0, 1.0, advance, 0.0), matrix)
        if path:
            paint = {0: b'f', 4: b'f', 1: b'S', 5: b'S', 2: b'B', 6: b'B'}.get(state.render, b'f')
            text_out.append(b' '.join(path) + b'\n' + paint + b'\n')
        return True

    shown_all = True
    for kind, value, start, end in _tokens(content):
        if instruction_start is None:
            instruction_start = start
        if kind == 'open':
            arrays.append([])
            continue
        if kind == 'close':
            if arrays:
                done = arrays.pop()
                (arrays[-1] if arrays else operands).append(done)
            continue
        if kind != 'operator':
            if kind != 'image':
                (arrays[-1] if arrays else operands).append(value)
            if kind == 'image':
                instruction_start = None
            continue

        operator = value
        if operator == b'q':
            stack.append(state.copy())
        elif operator == b'Q':
            if stack:
                state = stack.pop()

        if operator == b'BT' and not in_text:
            in_text = True
            text_start = instruction_start
            text_out = []
            text_operators = 0
            matrix = line_matrix = _IDENTITY
            shown_all = True
        elif in_text and operator == b'ET':
            in_text = False
            output.append(content[copied_to:text_start])
            if not shown_all or not text_operators:
                # an empty 'BT ET' is the marker of dropped text (from a nested
                # conversion too): keep it, so ParsePDF reports the dropped text
                text_out.append(b'BT ET\n')
            output.append(b''.join(text_out))
            copied_to = end
        elif in_text:
            text_operators += 1
            numbers = [_number(operand) for operand in operands]
            if operator == b'Tf' and len(operands) >= 2:
                state.font = operands[-2] if isinstance(operands[-2], bytes) else None
                state.size = numbers[-1]
            elif operator == b'Tc' and operands:
                state.char_spacing = numbers[-1]
            elif operator == b'Tw' and operands:
                state.word_spacing = numbers[-1]
            elif operator == b'Tz' and operands:
                state.scale = numbers[-1] / 100.0
            elif operator == b'TL' and operands:
                state.leading = numbers[-1]
            elif operator == b'Ts' and operands:
                state.rise = numbers[-1]
            elif operator == b'Tr' and operands:
                state.render = int(numbers[-1])
            elif operator in (b'Td', b'TD') and len(operands) >= 2:
                if operator == b'TD':
                    state.leading = -numbers[-1]
                line_matrix = multiply((1.0, 0.0, 0.0, 1.0, numbers[-2], numbers[-1]), line_matrix)
                matrix = line_matrix
            elif operator == b'Tm' and len(operands) >= 6:
                matrix = line_matrix = tuple(numbers[-6:])
            elif operator in (b'T*', b"'", b'"'):
                if operator == b'"' and len(operands) >= 3:
                    state.word_spacing, state.char_spacing = numbers[-3], numbers[-2]
                line_matrix = multiply((1.0, 0.0, 0.0, 1.0, 0.0, -state.leading), line_matrix)
                matrix = line_matrix
                if operator != b'T*' and operands and isinstance(operands[-1], bytes):
                    shown_all = show(operands[-1]) and shown_all
            elif operator == b'Tj' and operands and isinstance(operands[-1], bytes):
                shown_all = show(operands[-1]) and shown_all
            elif operator == b'TJ' and operands and isinstance(operands[-1], list):
                for item in operands[-1]:
                    if isinstance(item, bytes):
                        shown_all = show(item) and shown_all
                    elif isinstance(item, float):
                        shift = -item / 1000.0 * state.size * state.scale
                        matrix = multiply((1.0, 0.0, 0.0, 1.0, shift, 0.0), matrix)
            elif operator not in (b'd0', b'd1'):
                # not a text operator (color, gs, marked content ...): keep it
                text_out.append(content[instruction_start:end] + b'\n')
        elif operator in (b'Tc', b'Tw', b'Tz', b'TL', b'Ts', b'Tr', b'Tf'):
            # text state operators are allowed outside BT ... ET too
            numbers = [_number(operand) for operand in operands]
            if operator == b'Tf' and len(operands) >= 2:
                state.font = operands[-2] if isinstance(operands[-2], bytes) else None
                state.size = numbers[-1]
            elif operands:
                attribute = {b'Tc': 'char_spacing', b'Tw': 'word_spacing', b'TL': 'leading',
                             b'Ts': 'rise', b'Tr': 'render', b'Tz': 'scale'}[operator]
                value = numbers[-1] / 100.0 if operator == b'Tz' else numbers[-1]
                setattr(state, attribute, int(value) if operator == b'Tr' else value)

        operands = []
        arrays = []
        instruction_start = None

    if in_text:
        # a text object without ET: keep the original bytes
        return content
    output.append(content[copied_to:])
    return b''.join(output)
