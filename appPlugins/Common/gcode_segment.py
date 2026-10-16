# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/15/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""
Pure G-code helpers of the GRBL Sender: split long G1 moves, and make the
3D toolpath with the line index of each segment.

No Qt imports, no app imports - standard library only.
"""

import math
import re

_WORD_RE = re.compile(r'([A-Z])\s*([+\-]?(?:\d+\.?\d*|\.\d+))')
_COMMENT_RE = re.compile(r'\([^)]*\)')

# G words of a block that can be split (G1 is the split move itself)
_SPLIT_G_KEYS = ('1.0', '17.0', '90.0', '94.0')
# no effect on the position, the distance mode or the units
_NO_EFFECT_G_KEYS = ('4.0', '17.0', '18.0', '19.0', '40.0', '61.0', '64.0')
_MOTION_G_KEYS = ('0.0', '1.0', '2.0', '3.0')
# X, Y, Z are unknown after them (the one-shot and frame codes of level_gcode_line)
_LOSE_G_KEYS = ('10.0', '28.0', '30.0', '53.0', '54.0', '55.0', '56.0', '57.0', '58.0', '59.0',
                '59.1', '59.2', '59.3', '92.0', '92.1')


def _words(line):
    """:return: list of (letter, float) of the words of `line`; G numbers keep their decimals (38.2)."""
    return [(m.group(1), float(m.group(2))) for m in _WORD_RE.finditer(line.upper())]


def _fmt(value, decimals):
    text = '%.*f' % (decimals, value)
    return '0.' + '0' * decimals if text.startswith('-') and float(text) == 0.0 else text


def _g_key(g):
    """The G number as a rounded string: 38.2 -> '38.2', 1 -> '1.0'."""
    return '%.1f' % g


def split_long_moves(lines, max_len, decimals=4):
    """
    Split each absolute G1 move with X or Y that is longer than `max_len`
    into equal G1 moves, so a height map can level the cut between its ends.

    The modal state is tracked with the rules of level_gcode_line(): the
    motion mode, G90/G91, G93/G94, the units and X/Y/Z. A line is left
    unchanged if it is not a G1 move, if the distance mode after its G words
    is not a confirmed G90, if the start or the end point is not known, if
    its G words are not in {G1, G17, G90, G94} (a line with no G word is
    split when the modal motion is G1), or if it has other words than G, X,
    Y, Z, F, N. A line that makes a position unknown (probe, G53, G92,
    G10, G28, G30, a work coordinate system or tool length change, a units
    change, an unknown G code, M2, M30, a "$" line) makes it unknown: only a
    later absolute G0..G3 move makes an axis known again, axis by axis. The
    first piece starts with the non-motion G words of the block, the other
    pieces start with G1. The feed word stays on the first piece only (it is
    modal).

    :param lines:    list of str (clean lines, see SenderGen.clean_lines()).
    :param max_len:  the longest XY length of 1 piece (> 0).
    :param decimals: decimals of the new X/Y/Z words.
    :return: (new_lines, count of split moves)
    """
    if not max_len > 0:
        raise ValueError("max_len must be > 0")
    pos = {'X': None, 'Y': None, 'Z': None}
    motion = 0              # modal G0..G3 (as level_gcode_line), None: not known
    dist = 90               # 90, 91, or None: not known
    inverse = False         # G93 True, G94 False, None: not known
    units = None            # 20, 21, or None: not known
    out = []
    split_count = 0

    def lose(axes=('X', 'Y', 'Z')):
        for axis in axes:
            pos[axis] = None

    for line in lines:
        if line.strip().startswith('$'):
            # a GRBL setting or command line
            lose()
            motion = None
            out.append(line)
            continue
        masked = _COMMENT_RE.sub(' ', line)
        idx = masked.find(';')
        if idx != -1:
            masked = masked[:idx]
        if not masked.strip() or masked.strip() == '%':
            out.append(line)
            continue
        if masked.strip().startswith('/'):
            # an optional line: the controller can skip it, so every modal setting that
            # it could change is not known
            lose()
            motion = dist = inverse = units = None
            out.append(line)
            continue

        upper = masked.upper()
        words = _words(masked)
        # text that is not a word (an expression, a parameter) or lower case letters
        unparsed = (masked != upper) or bool(re.sub(r'[\s%]', '', _WORD_RE.sub('', upper)))
        g_words = [v for k, v in words if k == 'G']
        letters = {k for k, _v in words}
        axes = {k: v for k, v in words if k in 'XYZ'}
        keys = [_g_key(g) for g in g_words]
        start = dict(pos)
        # `blocked`: the block makes a position unknown
        blocked = False
        for key in keys:
            if key in _MOTION_G_KEYS:
                motion = int(float(key))
            elif key == '80.0':
                motion = None
            elif key in _NO_EFFECT_G_KEYS:
                pass
            elif key == '90.0':
                dist = 90
            elif key == '91.0':
                dist = 91
            elif key == '93.0':
                inverse = True
            elif key == '94.0':
                inverse = False
            elif key in ('20.0', '21.0'):
                value = int(float(key))
                if value != units:
                    if units is not None or any(v is not None for v in pos.values()):
                        blocked = True
                    lose()
                units = value
            elif key in ('43.1', '49.0'):
                blocked = True
                lose(['Z'])
            elif key in ('38.2', '38.3', '38.4', '38.5'):
                blocked = True
                lose()
                motion = None
            elif key in _LOSE_G_KEYS:
                blocked = True
                lose()
            else:
                # any other G code: it can be a motion, a frame or a mode change
                blocked = True
                lose()
                motion = None
        nonmotion_keys = [key for key in keys if key != '1.0']
        # M2 and M30 end the program and reset the modal state
        if any(k == 'M' and v in (2.0, 30.0) for k, v in words):
            blocked = True
            lose()
            motion = None
            dist = 90
            inverse = False
        if unparsed:
            blocked = True
            lose()
            motion = None
            if upper.count('G') > len(g_words):
                # a G word that is not read can be any G code
                dist = inverse = units = None

        # the axis words: only an absolute G0..G3 move makes an axis known
        if axes:
            if blocked or motion not in (0, 1, 2, 3):
                lose(axes.keys())
            elif dist == 90:
                pos.update(axes)
            elif dist == 91:
                for k, v in axes.items():
                    if pos[k] is not None:
                        pos[k] += v
            else:
                lose(axes.keys())

        can_split = (
            not blocked and
            motion == 1 and dist == 90 and inverse is False and
            ('X' in axes or 'Y' in axes) and
            letters <= set('GXYZFN') and all(k in _SPLIT_G_KEYS for k in keys) and
            None not in (start['X'], start['Y'], start['Z']) and
            None not in (pos['X'], pos['Y'], pos['Z'])
        )
        if not can_split:
            out.append(line)
            continue
        length = math.hypot(pos['X'] - start['X'], pos['Y'] - start['Y'])
        pieces = int(math.ceil(length / max_len - 1e-9))
        if pieces <= 1:
            out.append(line)
            continue
        feed = [v for k, v in words if k == 'F']
        prefix = ''.join('G%d ' % int(float(key)) for key in nonmotion_keys)
        for n in range(1, pieces + 1):
            t = n / pieces
            x = start['X'] + (pos['X'] - start['X']) * t
            y = start['Y'] + (pos['Y'] - start['Y']) * t
            z = start['Z'] + (pos['Z'] - start['Z']) * t
            piece = 'G1 X%s Y%s Z%s' % (_fmt(x, decimals), _fmt(y, decimals), _fmt(z, decimals))
            if n == 1:
                piece = prefix + piece
                if feed:
                    piece += ' F%s' % _fmt(feed[0], 2)
            out.append(piece)
        split_count += 1
    return out, split_count
