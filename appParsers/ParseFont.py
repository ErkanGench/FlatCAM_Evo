# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

# ######################################################################
# ## Borrowed code from 'https://github.com/gddc/ttfquery/blob/master/ #
# ## and made it work with Python 3                                    #
# ######################################################################

import re
import os
import sys
import math
import glob
import threading
import unicodedata

from shapely import Polygon, MultiPolygon
from shapely.affinity import affine_transform, translate, scale
from shapely.geometry import LineString, Point, box
from shapely.ops import polygonize, unary_union

import freetype as ft
import freetype.raw as ft_raw
from freetype.ft_enums.ft_load_flags import FT_LOAD_FLAGS
from fontTools import ttLib
from fontTools.ttLib import TTCollection

import logging

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base2')

# font files the text tools parse; collections hold several faces in one file
COLLECTION_EXTENSIONS = ('.ttc', '.otc')
# faces without scalable outlines are rendered from their native bitmap strike
BITMAP_EXTENSIONS = ('.bdf', '.pcf', '.fon', '.fnt')
FONT_EXTENSIONS = ('.ttf', '.otf') + COLLECTION_EXTENSIONS + BITMAP_EXTENSIONS

# some fonts ship bitmaps for small sizes; geometry always needs the outlines
NO_BITMAP = FT_LOAD_FLAGS['FT_LOAD_NO_BITMAP']
LOAD_DEFAULT = FT_LOAD_FLAGS['FT_LOAD_DEFAULT']
LOAD_RENDER = FT_LOAD_FLAGS['FT_LOAD_RENDER']
LOAD_NO_HINTING = FT_LOAD_FLAGS['FT_LOAD_NO_HINTING']

# Qt font registration and family/style lookup are per process, never per glyph
_QT_FONTS = {}
_QT_REGISTERED = set()
_QT_UNLOADABLE = set()
_QT_LOCK = threading.RLock()
_SHAPING_CACHE = {}
_BITMAP_FACE_CACHE = {}

# Windows FNT/FON files carry a legacy codepage, not a Unicode cmap
_WINFNT_CHARSET_CODECS = {
    0: 'cp1252',    # ANSI_CHARSET
    1: 'cp1252',    # DEFAULT_CHARSET
    77: 'mac_roman',  # MAC_CHARSET
    128: 'cp932',   # SHIFTJIS_CHARSET
    129: 'cp949',   # HANGUL_CHARSET
    134: 'gbk',     # GB2312_CHARSET
    136: 'big5',    # CHINESEBIG5_CHARSET
    161: 'cp1253',  # GREEK_CHARSET
    162: 'cp1254',  # TURKISH_CHARSET
    163: 'cp1258',  # VIETNAMESE_CHARSET
    177: 'cp1255',  # HEBREW_CHARSET
    178: 'cp1256',  # ARABIC_CHARSET
    186: 'cp1257',  # BALTIC_CHARSET
    204: 'cp1251',  # RUSSIAN_CHARSET
    222: 'cp874',   # THAI_CHARSET
    238: 'cp1250',  # EASTEUROPE_CHARSET
    255: 'cp437',   # OEM_CHARSET
}


class _TextShapeError(Exception):
    """A text run cannot be laid out faithfully; the whole label fails."""


def _qt_app():
    """The running Qt application, or None.

    Never creates an application. QTextLayout and QRawFont are reentrant, so worker tasks may shape with an
    application that already exists; only the font registration is serialized by _QT_LOCK.
    """
    try:
        from PyQt6.QtGui import QGuiApplication
    except Exception:
        return None
    app = QGuiApplication.instance()
    return app if isinstance(app, QGuiApplication) else None


def _utf16_index_to_char(text, index):
    """Map a Qt UTF-16 code unit index to a Python character index."""
    if index <= 0:
        return 0 if text else -1
    units = 0
    for position, char in enumerate(text):
        if units >= index:
            return position
        units += 2 if ord(char) > 0xFFFF else 1
        if units > index:
            return position
    return -1


def _legacy_char_code(charset, char):
    """Byte code of a character in a Windows FNT legacy charset, or None."""
    codec = _WINFNT_CHARSET_CODECS.get(charset)
    if not codec:
        return None
    try:
        encoded = char.encode(codec)
    except (UnicodeEncodeError, LookupError):
        return None
    return encoded[0] if len(encoded) == 1 else None


def _winfnt_header(face):
    """FT_WinFNT_HeaderRec of a Windows bitmap face, or None for other formats."""
    if sys.platform != 'win32' or not hasattr(ft_raw, 'FT_Get_WinFNT_Header'):
        return None
    import ctypes

    class WinFNTHeader(ctypes.Structure):
        _fields_ = [
            ('version', ctypes.c_ushort),
            ('file_size', ctypes.c_ulong),
            ('copyright', ctypes.c_ubyte * 60),
            ('file_type', ctypes.c_ushort),
            ('nominal_point_size', ctypes.c_ushort),
            ('vertical_resolution', ctypes.c_ushort),
            ('horizontal_resolution', ctypes.c_ushort),
            ('ascent', ctypes.c_ushort),
            ('internal_leading', ctypes.c_ushort),
            ('external_leading', ctypes.c_ushort),
            ('italic', ctypes.c_ubyte),
            ('underline', ctypes.c_ubyte),
            ('strike_out', ctypes.c_ubyte),
            ('weight', ctypes.c_ushort),
            ('charset', ctypes.c_ubyte),
            ('pixel_width', ctypes.c_ushort),
            ('pixel_height', ctypes.c_ushort),
            ('pitch_and_family', ctypes.c_ubyte),
            ('avg_width', ctypes.c_ushort),
            ('max_width', ctypes.c_ushort),
            ('first_char', ctypes.c_ubyte),
            ('last_char', ctypes.c_ubyte),
            ('default_char', ctypes.c_ubyte),
            ('break_char', ctypes.c_ubyte),
            ('bytes_per_row', ctypes.c_ushort),
            ('device_offset', ctypes.c_ulong),
            ('face_name_offset', ctypes.c_ulong),
            ('bits_pointer', ctypes.c_ulong),
            ('bits_offset', ctypes.c_ulong),
            ('reserved', ctypes.c_ulong),
            ('flags', ctypes.c_ulong),
            ('A_space', ctypes.c_ushort),
            ('B_space', ctypes.c_ushort),
            ('C_space', ctypes.c_ushort),
            ('color_table_offset', ctypes.c_ushort),
            ('reserved1', ctypes.c_ulong * 4),
        ]

    header = WinFNTHeader()
    try:
        error = ft_raw.FT_Get_WinFNT_Header(face._FT_Face, ctypes.byref(header))
    except Exception:
        return None
    return header if error == 0 else None


def _glyph_index(face, char, header=None):
    """Glyph index from the Unicode cmap, or from a Windows FNT legacy charset."""
    glyph_index = face.get_char_index(char)
    if glyph_index:
        return glyph_index
    if header is None:
        return 0
    code = _legacy_char_code(header.charset, char)
    if code is None or not (header.first_char <= code <= header.last_char):
        return 0
    glyph_index = code - header.first_char + 1
    return glyph_index if 0 < glyph_index < face.num_glyphs else 0


def _needs_shaping(text):
    """True when per-character FreeType layout would lose the script's shaping or direction."""
    for char in text:
        if char in '\r\n\t ':
            continue
        if unicodedata.bidirectional(char) in ('R', 'AL', 'AN', 'RLE', 'RLO', 'RLI', 'LRE', 'LRO', 'LRI', 'FSI', 'PDI'):
            return True
        if unicodedata.category(char).startswith('M'):
            return True
        code = ord(char)
        if (0x0900 <= code <= 0x0DFF or 0x0E00 <= code <= 0x0EFF or 0x1000 <= code <= 0x109F or
                0x1100 <= code <= 0x11FF or 0x1780 <= code <= 0x17FF or 0x1800 <= code <= 0x18AF or
                0x1A00 <= code <= 0x1AAF or 0x1B00 <= code <= 0x1B7F or 0x1DC0 <= code <= 0x1DFF or
                0x200B <= code <= 0x200F or 0x20D0 <= code <= 0x20FF or 0xFE00 <= code <= 0xFE0F or
                0xFE20 <= code <= 0xFE2F):
            return True
    return False


def _ignorable(char):
    """Characters that may have no glyph without making the label invalid."""
    return char.isspace() or unicodedata.category(char) in ('Cf', 'Cc', 'Zs', 'Zl', 'Zp')


# Layout controls that change shaping or direction; other Cc/Cf characters are invisible noise
_KEEP_LAYOUT_CONTROLS = frozenset(
    [0x061C, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF] +
    list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A)))


def _layout_line(text):
    """Remove invisible controls that Qt would otherwise turn into fallback .notdef runs."""
    return ''.join(char for char in text
                   if not (unicodedata.category(char) in ('Cc', 'Cf')
                           and ord(char) not in _KEEP_LAYOUT_CONTROLS))


class FontPath(str):
    """Font file path that remembers which face of a collection it refers to."""

    face_index = 0

    def __new__(cls, path, face_index=0):
        font_path = super().__new__(cls, path)
        font_path.face_index = face_index
        return font_path


class ParseFont:

    # FreeType uses 26.6 fixed-point (units of 1/64 point) and set_char_size()
    # resolves point sizes at the default 72 dpi, so one point is 1/72 inch.
    # MM:   (1/64) * (25.4/72) — 26.6 fixed-point to millimeters
    # INCH: (1/64) * (1/72)    — 26.6 fixed-point to inches
    SCALE_MM = 25.4 / (64 * 72)
    SCALE_INCH = 1.0 / (64 * 72)

    FONT_SPECIFIER_NAME_ID = 4
    FONT_SPECIFIER_FAMILY_ID = 1

    @staticmethod
    def get_win32_font_path():
        """Get User-specific font directory on Win32"""
        try:
            import winreg
        except ImportError:
            return os.path.join(os.environ['WINDIR'], 'Fonts')
        else:
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            try:
                # should check that k is valid? How?
                return winreg.QueryValueEx(k, "Fonts")[0]
            finally:
                winreg.CloseKey(k)

    @staticmethod
    def get_linux_font_paths():
        """Get system font directories on Linux/Unix

        Uses /usr/sbin/chkfontpath to get the list
        of system-font directories, note that many
        of these will *not* be truetype font directories.

        If /usr/sbin/chkfontpath isn't available, uses
        returns a set of common Linux/Unix paths
        """
        executable = '/usr/sbin/chkfontpath'
        if os.path.isfile(executable):
            data = os.popen(executable).readlines()
            match = re.compile(r'\d+: (.+)')
            set_lst = []
            for line in data:
                result = match.match(line)
                if result:
                    set_lst.append(result.group(1))
            return set_lst
        else:
            directories = [
                # what seems to be the standard installation point
                "/usr/X11R6/lib/X11/fonts/TTF/",
                # common application, not really useful
                "/usr/lib/openoffice/share/fonts/truetype/",
                # documented as a good place to install new fonts...
                "/usr/share/fonts",
                "/usr/local/share/fonts",
                # distribution provided and per-user fonts
                "/usr/share/fonts/truetype",
                "~/.fonts",
                "~/.local/share/fonts",
            ]
            # the per-user data directory can be relocated through XDG_DATA_HOME
            if os.environ.get('XDG_DATA_HOME'):
                directories.append(os.path.join(os.environ['XDG_DATA_HOME'], 'fonts'))

            dir_set = []

            for directory in directories:
                directory = os.path.expanduser(os.path.expandvars(directory))
                try:
                    if os.path.isdir(directory):
                        for path, children, files in os.walk(directory):
                            dir_set.append(path)
                except (IOError, OSError, TypeError, ValueError):
                    pass
            return dir_set

    @staticmethod
    def get_mac_font_paths():
        """Get system font directories on MacOS
        """
        directories = [
            # okay, now the OS X variants...
            "~/Library/Fonts/",
            "/Library/Fonts/",
            "/Network/Library/Fonts/",
            "/System/Library/Fonts/",
            "System Folder:Fonts:",
        ]

        dir_set = []

        for directory in directories:
            directory = os.path.expanduser(os.path.expandvars(directory))
            try:
                if os.path.isdir(directory):
                    for path, children, files in os.walk(directory):
                        dir_set.append(path)
            except (IOError, OSError, TypeError, ValueError):
                pass
        return dir_set

    @staticmethod
    def get_win32_fonts(font_directory=None):
        """Get list of explicitly *installed* font names"""

        import winreg
        if font_directory is None:
            font_directory = ParseFont.get_win32_font_path()
        # fonts installed by the user without admin rights are copied here
        user_directory = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts')

        items = {}
        for root, key_name in (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Fonts"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        ):
            try:
                k = winreg.OpenKey(root, key_name)
            except OSError:
                continue
            try:
                for index in range(winreg.QueryInfoKey(k)[1]):
                    key, value, _ = winreg.EnumValue(k, index)
                    if not os.path.dirname(value):
                        value = os.path.join(font_directory, value)
                        if not os.path.exists(value):
                            value = os.path.join(user_directory, os.path.basename(value))
                    value = os.path.abspath(value).lower()
                    if value.endswith(FONT_EXTENSIONS):
                        items[value] = 1
            finally:
                winreg.CloseKey(k)

        if not items:
            # couldn't open any of the registry keys???
            return glob.glob(os.path.join(font_directory, '*.ttf'))

        return list(items.keys())

    @staticmethod
    def get_font_name(font_path):
        """
        Get the short name from the font's names table
        From 'https://github.com/gddc/ttfquery/blob/master/ttfquery/describe.py'
        and
        http://www.starrhorne.com/2012/01/18/
        how-to-extract-font-names-from-ttf-files-using-python-and-our-old-friend-the-command-line.html
        ported to Python 3 here: https://gist.github.com/pklaus/dce37521579513c574d0
        """
        name = ""
        family = ""
        face_index = getattr(font_path, 'face_index', 0)

        with ttLib.TTFont(font_path, fontNumber=face_index) as font:
            for record in font['name'].names:
                try:
                    name_str = record.toUnicode()
                except (UnicodeDecodeError, AttributeError):
                    continue

                if record.nameID == ParseFont.FONT_SPECIFIER_NAME_ID and not name:
                    name = name_str
                elif record.nameID == ParseFont.FONT_SPECIFIER_FAMILY_ID and not family:
                    family = name_str

                if name and family:
                    break
        return name, family

    def __init__(self, app):
        self.app = app

        # regular fonts
        self.regular_f = {}
        # bold fonts
        self.bold_f = {}
        # italic fonts
        self.italic_f = {}
        # bold and italic fonts
        self.bold_italic_f = {}

    def get_fonts(self, paths=None):
        """
        Find fonts in paths, or the system paths if not given
        """
        files = {}
        if paths is None:
            if sys.platform == 'win32':
                font_directory = ParseFont.get_win32_font_path()
                paths = [font_directory, ]

                # now get all installed fonts directly...
                for f in self.get_win32_fonts(font_directory):
                    files[os.path.normcase(os.path.abspath(f))] = 1
            elif sys.platform == 'linux':
                paths = ParseFont.get_linux_font_paths()
            else:
                paths = ParseFont.get_mac_font_paths()
        elif isinstance(paths, str):
            paths = [paths]

        for path in paths:
            for ext in FONT_EXTENSIONS:
                for file in glob.glob(os.path.join(path, '*' + ext)):
                    files[os.path.normcase(os.path.abspath(file))] = 1

        fonts = []
        for font_file in files:
            fonts.extend(ParseFont._font_faces(font_file))
        return fonts

    @staticmethod
    def _font_faces(font_path):
        """One entry per face; a font collection (.ttc/.otc) carries the face index."""
        if not font_path.lower().endswith(COLLECTION_EXTENSIONS):
            return [font_path]
        try:
            collection = TTCollection(font_path)
            try:
                count = len(collection.fonts)
            finally:
                for font in collection.fonts:
                    font.close()
        except Exception as e:
            log.error("ParseFont._font_faces() --> Could not read the font collection. %s" % str(e))
            return [font_path]
        return [FontPath(font_path, index) for index in range(count)]

    @staticmethod
    def _font_names(font_path):
        """Family and style of one face; the family is the name the UI lists."""
        face_index = getattr(font_path, 'face_index', 0)
        try:
            with ttLib.TTFont(font_path, fontNumber=face_index) as font:
                names = font['name']
                family = names.getDebugName(ParseFont.FONT_SPECIFIER_FAMILY_ID) or ""
                style = names.getDebugName(2) or ""
                typographic_family = names.getDebugName(16) or ""
                typographic_style = names.getDebugName(17) or ""
            return family, style, typographic_family, typographic_style
        except Exception:
            # bitmap formats (BDF, PCF, FON) have no name table; FreeType still knows the family
            face = ft.Face(font_path, index=face_index)
            try:
                family = face.family_name.decode('utf-8', 'replace') if face.family_name else ""
                style = face.style_name.decode('utf-8', 'replace') if face.style_name else ""
            finally:
                del face
            return family, style, "", ""

    @staticmethod
    def _font_kind(style):
        """Map a subfamily name to one of the four style dictionaries."""
        style = (style or '').lower()
        italic = 'italic' in style or 'oblique' in style
        bold = 'bold' in style or 'black' in style or 'heavy' in style or 'demi' in style
        if bold and italic:
            return 'bi'
        if bold:
            return 'bold'
        if italic:
            return 'italic'
        return 'regular'

    # style words the font UI splits off a legacy family name, as GDI does
    STYLE_SUFFIXES = (
        ('Bold Italic', 'bi'), ('Bold Oblique', 'bi'),
        ('SemiBold', 'bold'), ('DemiBold', 'bold'), ('ExtraBold', 'bold'), ('UltraBold', 'bold'),
        ('Bold', 'bold'), ('Black', 'bold'), ('Heavy', 'bold'), ('Demi', 'bold'),
        ('Italic', 'italic'), ('Oblique', 'italic'),
        ('Regular', 'regular'), ('Book', 'regular'), ('Medium', 'regular'), ('Light', 'regular'),
        ('Extended', 'regular'), ('Condensed', 'regular'), ('Narrow', 'regular'),
    )

    @staticmethod
    def _family_aliases(family, style, typographic_family, typographic_style):
        """Names the UI lists for this face besides its own family name."""
        aliases = []
        if typographic_family and typographic_family != family:
            aliases.append((typographic_family, ParseFont._font_kind(typographic_style or style)))
        for suffix, kind in ParseFont.STYLE_SUFFIXES:
            if family.endswith(' ' + suffix):
                aliases.append((family[:-len(suffix) - 1], kind))
                break
        return aliases

    def _register_font(self, font, family, kind):
        table = {'regular': self.regular_f, 'bold': self.bold_f,
                 'italic': self.italic_f, 'bi': self.bold_italic_f}[kind]
        if family and family not in table:
            table[family] = font

    def get_fonts_by_types(self, paths=None):

        system_fonts = []
        for font in self.get_fonts(paths):
            try:
                system_fonts.append((font, ParseFont._font_names(font)))
            except Exception as e:
                log.error("ParseFont.get_fonts_by_types() --> Could not get the font name. %s" % str(e))

        # split the installed fonts by type: regular, bold, italic (oblique), bold-italic and
        # store them in separate dictionaries {name: file_path/filename.ttf}
        for font, (family, style, _, _) in system_fonts:
            self._register_font(font, family, ParseFont._font_kind(style))

        # the family names the UI shows may not be the legacy family name; add them only where
        # no real family of that name exists, so aliases never replace a canonical face
        for font, names in system_fonts:
            for alias, kind in ParseFont._family_aliases(*names):
                self._register_font(font, alias, kind)
        log.debug("Font parsing is finished.")

    @staticmethod
    def _segment_distance(point, start, end):
        """Distance from point to the segment start-end."""
        x, y = point
        x1, y1 = start
        x2, y2 = end
        dx, dy = x2 - x1, y2 - y1
        length = dx * dx + dy * dy
        if length == 0:
            return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        t = min(1.0, max(0.0, ((x - x1) * dx + (y - y1) * dy) / length))
        return ((x - (x1 + t * dx)) ** 2 + (y - (y1 + t * dy)) ** 2) ** 0.5

    @staticmethod
    def _flatten_quad(result, p0, p1, p2, segments, tolerance, depth=0):
        """Append the vertices of a quadratic Bezier; the tolerance bounds the chord error."""
        if tolerance is None:
            for step in range(1, segments + 1):
                t = step / segments
                mt = 1 - t
                result.append((mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                               mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]))
            return
        if depth >= 12 or ParseFont._segment_distance(p1, p0, p2) <= tolerance:
            result.append(p2)
            return
        p01 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
        p12 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        middle = ((p01[0] + p12[0]) / 2, (p01[1] + p12[1]) / 2)
        ParseFont._flatten_quad(result, p0, p01, middle, segments, tolerance, depth + 1)
        ParseFont._flatten_quad(result, middle, p12, p2, segments, tolerance, depth + 1)

    @staticmethod
    def _flatten_cubic(result, p0, p1, p2, p3, segments, tolerance, depth=0):
        """Append the vertices of a cubic Bezier; the tolerance bounds the chord error."""
        if tolerance is None:
            for step in range(1, segments + 1):
                t = step / segments
                mt = 1 - t
                result.append((mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] +
                               3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                               mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] +
                               3 * mt * t * t * p2[1] + t ** 3 * p3[1]))
            return
        if depth >= 12 or max(ParseFont._segment_distance(p1, p0, p3),
                              ParseFont._segment_distance(p2, p0, p3)) <= tolerance:
            result.append(p3)
            return
        p01 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
        p12 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        p23 = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
        p012 = ((p01[0] + p12[0]) / 2, (p01[1] + p12[1]) / 2)
        p123 = ((p12[0] + p23[0]) / 2, (p12[1] + p23[1]) / 2)
        middle = ((p012[0] + p123[0]) / 2, (p012[1] + p123[1]) / 2)
        ParseFont._flatten_cubic(result, p0, p01, p012, middle, segments, tolerance, depth + 1)
        ParseFont._flatten_cubic(result, middle, p123, p23, p3, segments, tolerance, depth + 1)

    @staticmethod
    def _interpolate_contour(points, tags, segments=8, tolerance=None):
        """Convert a FreeType contour to a closed list of line vertices.

        FreeType tags bit 0: 1 = on-curve, 0 = off-curve conic (quadratic) control point.
        Bit 1 marks a cubic control point, used by CFF/OpenType outlines.
        TrueType rule: two consecutive off-curve points have an implied on-curve midpoint.

        Args:
            points: list of (x, y) from outline.points
            tags: list of int from outline.tags
            segments: line segments per Bezier curve when no tolerance is given
            tolerance: maximum chord deviation in outline units; adaptive when set
        Returns:
            list of (x, y) suitable for Polygon(), or empty list on failure
        """
        if len(points) < 2:
            return []

        pts = [(float(point[0]), float(point[1])) for point in points]
        n = len(pts)

        # Start on an on-curve point, or at the implied midpoint when the contour
        # begins and ends with conic control points.
        first_on = next((k for k in range(n) if tags[k] & 1), None)
        if first_on is None:
            result = [((pts[-1][0] + pts[0][0]) / 2, (pts[-1][1] + pts[0][1]) / 2)]
            index = 0
        else:
            result = [pts[first_on]]
            index = (first_on + 1) % n

        visited = 0
        while visited < n:
            tag = tags[index]
            if tag & 1:
                result.append(pts[index])
                index = (index + 1) % n
                visited += 1
                continue

            if tag & 2:
                # Cubic: two control points followed by the end point
                p1 = pts[index]
                p2 = pts[(index + 1) % n]
                p3 = pts[(index + 2) % n]
                ParseFont._flatten_cubic(result, result[-1], p1, p2, p3, segments, tolerance)
                index = (index + 3) % n
                visited += 3
                continue

            # Conic: one control point; a following off-curve point implies a midpoint
            control = pts[index]
            following = pts[(index + 1) % n]
            if tags[(index + 1) % n] & 1:
                end = following
                index = (index + 2) % n
                visited += 2
            else:
                end = ((control[0] + following[0]) / 2, (control[1] + following[1]) / 2)
                index = (index + 1) % n
                visited += 1
            ParseFont._flatten_quad(result, result[-1], control, end, segments, tolerance)

        # Close contour
        if len(result) > 1 and result[0] != result[-1]:
            result.append(result[0])

        return result

    @staticmethod
    def _contour_filled(point, contours, even_odd):
        """Is the point inside the area painted by the glyph contours?"""
        x, y = point
        crossings = 0
        winding = 0
        for contour in contours:
            for (x1, y1), (x2, y2) in zip(contour, contour[1:] + contour[:1]):
                if (y1 <= y < y2) or (y2 <= y < y1):
                    if x1 + (y - y1) * (x2 - x1) / (y2 - y1) > x:
                        crossings += 1
                        winding += 1 if y2 > y1 else -1
        return crossings % 2 == 1 if even_odd else winding != 0

    @staticmethod
    def _contours_geometry(contours, even_odd):
        """Resolve closed contours into the area their fill rule paints."""
        contours = [contour for contour in contours if len(contour) >= 4]
        if not contours:
            return MultiPolygon()

        # Noding the contour linework splits the glyph into faces; a face is painted
        # when its winding number (or crossing parity, for even-odd fonts) says so.
        # Holes, nested islands and overlapping contours are all resolved in one pass.
        faces = list(polygonize(unary_union([LineString(contour) for contour in contours])))
        if not faces:
            # self-intersecting linework: keep the plain contour union as a fallback
            return unary_union([Polygon(contour) for contour in contours])

        filled = [face for face in faces
                  if ParseFont._contour_filled(face.representative_point().coords[0], contours, even_odd)]
        return unary_union(filled) if filled else MultiPolygon()

    @staticmethod
    def _glyph_geometry(outline, tolerance):
        """Resolve one glyph's contours into the area its own fill rule paints."""
        contours = []
        start = 0
        for end in outline.contours:
            contour = ParseFont._interpolate_contour(outline.points[start:end + 1],
                                                     outline.tags[start:end + 1],
                                                     tolerance=tolerance)
            if len(contour) >= 4:  # minimum 3 unique points + closing
                contours.append(contour)
            start = end + 1

        even_odd = bool(getattr(outline, 'flags', 0) & 2)  # FT_OUTLINE_EVEN_ODD_FILL
        return ParseFont._contours_geometry(contours, even_odd)

    def _font_path(self, font_name, font_type):
        """File (and face index) of the requested style, or raise KeyError."""
        if font_type == 'bi':
            path_filename = self.bold_italic_f[font_name]
        elif font_type == 'bold':
            path_filename = self.bold_f[font_name]
        elif font_type == 'italic':
            path_filename = self.italic_f[font_name]
        elif font_type == 'regular':
            path_filename = self.regular_f.get(font_name, "")
        else:
            path_filename = ""

        if not path_filename and font_type == 'regular':
            # a family that only ships a heavier or slanted face still serves the default
            for table in (self.bold_f, self.italic_f, self.bold_italic_f):
                path_filename = table.get(font_name, "")
                if path_filename:
                    break
        if not path_filename:
            raise KeyError('%s %s' % (font_name, font_type))
        return path_filename

    def _fail(self, message):
        self.app.inform.emit('[ERROR_NOTCL] %s' % message)
        log.error("[ERROR_NOTCL] %s" % message)
        return "flatcam font parse failed: %s" % message

    def _font_face(self, path_filename, font_size):
        """Open the face; a multi-face bitmap file (.fon) uses its nearest native strike."""
        filename = os.fspath(path_filename)
        face_index = getattr(path_filename, 'face_index', 0)
        face = ft.Face(filename, index=face_index)
        if face.is_scalable or face.num_faces <= 1 or face_index:
            return face

        key = (os.path.normcase(os.path.abspath(filename)), max(1, int(round(font_size))))
        with _QT_LOCK:
            chosen = _BITMAP_FACE_CACHE.get(key)
            if chosen is None:
                chosen, best = 0, None
                for index in range(face.num_faces):
                    other = ft.Face(filename, index=index)
                    try:
                        sizes = list(other.available_sizes)
                        height = min((size.height or size.y_ppem / 64.0 for size in sizes),
                                     key=lambda value: abs(value - font_size)) if sizes else font_size
                    finally:
                        del other
                    score = abs(height - font_size)
                    if best is None or score < best:
                        chosen, best = index, score
                _BITMAP_FACE_CACHE[key] = chosen
        if chosen != face_index:
            del face
            face = ft.Face(filename, index=chosen)
        return face

    def font_to_geometry(self, char_string, font_name, font_type, font_size, units='MM', coordx=0, coordy=0,
                         bitmap_smoothing=0.5):
        try:
            path_filename = self._font_path(font_name, font_type)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Font not supported, try another one."))
            log.error("[ERROR_NOTCL] Font Loading: %s" % str(e))
            return "flatcam font parse failed"

        try:
            font_size = float(font_size)
        except (TypeError, ValueError, OverflowError):
            font_size = float('nan')
        if not math.isfinite(font_size) or font_size <= 0:
            raise ValueError(_("Font size must be a finite positive number."))

        try:
            bitmap_smoothing = float(bitmap_smoothing)
        except (TypeError, ValueError, OverflowError):
            bitmap_smoothing = float('nan')
        if not math.isfinite(bitmap_smoothing) or bitmap_smoothing < 0:
            raise ValueError(_("Bitmap smoothing must be a finite non-negative number of source pixels."))

        # Tabs are whitespace; newlines start a new line instead of loading .notdef.
        char_string = char_string.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)

        face = self._font_face(path_filename, font_size)
        try:
            if not face.is_scalable:
                try:
                    return self._bitmap_text_geometry(path_filename, face, char_string, font_size,
                                                      units, coordx, coordy, bitmap_smoothing)
                except _TextShapeError as e:
                    return self._fail(str(e))

            needs_qt = _needs_shaping(char_string)
            if not needs_qt and _qt_app() is not None:
                needs_qt = self._qt_shaping_required(path_filename, char_string, font_size)
            if needs_qt:
                if _qt_app() is None:
                    return self._fail(_("Text shaping needs a running Qt GUI application."))
                try:
                    return self._qt_text_geometry(path_filename, char_string, font_size,
                                                  units, coordx, coordy)
                except _TextShapeError as e:
                    if _needs_shaping(char_string):
                        return self._fail(str(e))
                    log.warning("ParseFont: Qt text layout failed, using FreeType outlines: %s", e)

            return self._outline_text_geometry(face, char_string, font_size, units, coordx, coordy)
        finally:
            del face

    def _outline_text_geometry(self, face, char_string, font_size, units, coordx, coordy):
        """Per-glyph FreeType outlines; the fallback for simple scripts and headless callers."""
        face.set_char_size(int(round(font_size * 64)))
        line_height = face.size.height or (face.size.ascender - face.size.descender)
        # flattening tolerance, as a fraction of the em, keeps curves smooth at any size
        tolerance = max(0.25, font_size * 64 / 2048)

        path = []
        pen_x = coordx
        pen_y = 0
        previous = None
        missing = []
        glyphs = {}

        # done as here: https://www.freetype.org/freetype2/docs/tutorial/step2.html
        for char in char_string:
            if char == '\n':
                pen_x = coordx
                pen_y -= line_height
                previous = None
                continue

            glyph_index = face.get_char_index(char)
            if glyph_index == 0:
                if not char.isspace():
                    missing.append(char)
                    continue
                # a whitespace the font does not map still takes the .notdef gap
                face.load_glyph(0, NO_BITMAP)
                pen_x += face.glyph.advance.x
                previous = None
                continue

            # the binding resolves character pairs internally, so pass characters
            if previous is not None:
                try:
                    pen_x += face.get_kerning(previous, char).x
                except Exception:
                    pass

            glyph = glyphs.get(glyph_index)
            if glyph is None:
                # outlines, never the embedded bitmap some fonts ship for small sizes
                face.load_glyph(glyph_index, NO_BITMAP)
                glyph = (ParseFont._glyph_geometry(face.glyph.outline, tolerance),
                         face.glyph.advance.x)
                glyphs[glyph_index] = glyph

            glyph_geo, advance = glyph
            if not glyph_geo.is_empty:
                path.append(translate(glyph_geo, xoff=pen_x, yoff=coordy + pen_y))

            pen_x += advance
            previous = char

        if missing:
            chars = ' '.join(sorted(set(missing)))
            self.app.inform.emit('[ERROR_NOTCL] %s' % (_("Font has no glyph for: %s") % chars))
            log.error("[ERROR_NOTCL] Font %s has no glyph for: %s" % (face.family_name, chars))
            return "flatcam font parse failed"

        return self._finish(path, units, coordx, coordy)

    def _finish(self, parts, units, coordx, coordy, unit_scale=1.0):
        if not parts:
            return MultiPolygon()
        ret_geo = parts[0] if len(parts) == 1 else unary_union(parts)

        # --- Single scale operation on final geometry ---
        # FreeType outlines are in 26.6 point units; Qt and bitmap coordinates are whole points.
        s = (ParseFont.SCALE_MM if str(units).upper() == 'MM' else ParseFont.SCALE_INCH) * unit_scale
        return scale(ret_geo, s, s, origin=(coordx, coordy))

    def _qt_shaping_required(self, path_filename, char_string, font_size):
        """True when Qt would substitute or position glyphs beyond the per-character cmap."""
        if _qt_app() is None:
            return False
        pixel_size = max(1, int(round(font_size)))
        filename = os.fspath(path_filename)
        key = (os.path.normcase(os.path.abspath(filename)), getattr(path_filename, 'face_index', 0),
               pixel_size, char_string)
        with _QT_LOCK:
            cached = _SHAPING_CACHE.get(key)
        if cached is not None:
            return cached

        result = False
        family = style = ''
        try:
            font, family, style = self._qt_font(path_filename, pixel_size)
        except _TextShapeError:
            font = None
        if font is not None:
            from PyQt6.QtGui import QTextLayout

            for raw_line in char_string.split('\n'):
                line_text = _layout_line(raw_line)
                if not line_text or result:
                    continue
                layout = QTextLayout(line_text, font)
                layout.beginLayout()
                layout.createLine()
                layout.endLayout()
                for run in layout.glyphRuns(0, -1, QTextLayout.GlyphRunRetrievalFlag.RetrieveAll):
                    try:
                        raw = self._qt_run_face(run, family, style)
                    except _TextShapeError:
                        break
                    indexes = run.stringIndexes()
                    for order, glyph_index in enumerate(run.glyphIndexes()):
                        at = _utf16_index_to_char(line_text, indexes[order]) if order < len(indexes) else -1
                        if not (0 <= at < len(line_text)):
                            continue
                        direct = raw.glyphIndexesForString(line_text[at])
                        if not direct or direct[0] != glyph_index:
                            result = True
                            break

        with _QT_LOCK:
            if len(_SHAPING_CACHE) > 1024:
                _SHAPING_CACHE.clear()
            _SHAPING_CACHE[key] = result
        return result

    def _qt_font(self, path_filename, pixel_size):
        """Register the font file once and select its exact family and style."""
        from PyQt6.QtGui import QFont, QFontDatabase

        filename = os.fspath(path_filename)
        key = (os.path.normcase(os.path.abspath(filename)), getattr(path_filename, 'face_index', 0))
        with _QT_LOCK:
            if key in _QT_UNLOADABLE:
                raise _TextShapeError(_("Qt cannot load the font file."))
            info = _QT_FONTS.get(key)
            if info is None:
                names = ParseFont._font_names(path_filename)
                family, style = names[0], names[1]
                if not family:
                    _QT_UNLOADABLE.add(key)
                    raise _TextShapeError(_("Qt cannot read the font family."))
                if getattr(path_filename, 'face_index', 0):
                    try:
                        first = ParseFont._font_names(FontPath(filename, 0))
                    except Exception:
                        _QT_UNLOADABLE.add(key)
                        raise _TextShapeError(_("Qt cannot read the first face of the font collection."))
                    if (family.casefold(), (style or '').casefold()) == \
                            ((first[0] or '').casefold(), (first[1] or '').casefold()):
                        # Qt has no face index API; same-named collection faces would silently use face 0
                        _QT_UNLOADABLE.add(key)
                        raise _TextShapeError(_("Qt cannot distinguish this font collection face."))
                if key not in _QT_REGISTERED:
                    registered = -1
                    try:
                        registered = QFontDatabase.addApplicationFont(filename)
                    except Exception:
                        pass
                    if registered < 0 and family not in QFontDatabase.families():
                        # the platform cannot load this face (bitmap-only formats on Windows); use FreeType
                        _QT_UNLOADABLE.add(key)
                        raise _TextShapeError(_("Qt cannot load the font file."))
                    _QT_REGISTERED.add(key)
                info = (family, style)
                _QT_FONTS[key] = info

            family, style = info
            font = QFont(family)
            font.setPixelSize(max(1, int(pixel_size)))
            if style:
                font.setStyleName(style)
            return font, family, style

    @staticmethod
    def _qt_expected_runs(runs, family, style, line_text):
        """Split glyph runs into the requested face and substituted fallback runs."""
        expected, fallback, used = [], [], set()
        for run in runs:
            try:
                raw = ParseFont._qt_run_face(run, family, style)
            except _TextShapeError:
                fallback.append(run)
                continue
            expected.append((run, raw))
            used.update(_utf16_index_to_char(line_text, at) for at in run.stringIndexes())
        return expected, fallback, used

    @staticmethod
    def _qt_fallback_is_ignorable(fallback, line_text, used):
        """Accept fallback runs only for invisible controls Qt could not keep in the face."""
        for run in fallback:
            count = len(run.glyphIndexes())
            remaining = [index for index in range(len(line_text)) if index not in used]
            if count > len(remaining):
                return False
            assigned = remaining[:count]
            used.update(assigned)
            if not assigned or not all(_ignorable(line_text[index]) for index in assigned):
                return False
        return True

    @staticmethod
    def _qt_run_face(run, family, style):
        """Reject font fallback and .notdef instead of silently drawing a different face."""
        raw = run.rawFont()
        if raw.familyName().casefold() != family.casefold():
            raise _TextShapeError(_("Font substitution is not allowed: %s") % raw.familyName())
        actual = (raw.styleName() or '').casefold()
        expected = (style or '').casefold()
        plain = {'', 'regular', 'normal', 'book', 'medium'}
        if actual and expected and actual != expected and not ({actual, expected} <= plain):
            raise _TextShapeError(_("Font face is not available: %s %s") % (family, style))
        return raw

    @staticmethod
    def _path_contours(path, tolerance):
        """Closed polygons of a QPainterPath, its cubics flattened adaptively."""
        from PyQt6.QtGui import QPainterPath

        point_type = QPainterPath.ElementType
        contours = []
        current = None
        index = 0
        count = path.elementCount()
        while index < count:
            element = path.elementAt(index)
            if element.type == point_type.MoveToElement:
                if current and len(current) >= 2:
                    contours.append(current)
                current = [(element.x, element.y)]
                index += 1
            elif element.type == point_type.LineToElement:
                if current is None:
                    current = [(element.x, element.y)]
                else:
                    current.append((element.x, element.y))
                index += 1
            elif element.type == point_type.CurveToElement:
                control1 = (element.x, element.y)
                control2 = path.elementAt(index + 1)
                end = path.elementAt(index + 2)
                if current is None:
                    current = [control1]
                ParseFont._flatten_cubic(current, current[-1], control1,
                                         (control2.x, control2.y), (end.x, end.y), 8, tolerance)
                index += 3
            else:
                index += 1
        if current and len(current) >= 2:
            contours.append(current)

        closed = []
        for contour in contours:
            if contour[0] != contour[-1]:
                contour.append(contour[0])
            if len(contour) >= 4:
                closed.append(contour)
        return closed

    def _qt_text_geometry(self, path_filename, char_string, font_size, units, coordx, coordy,
                          bitmap=False, strike_height=None, smoothing=0.0):
        """QTextLayout shaping: contextual forms, clusters, ligatures and bidi placement."""
        from PyQt6.QtGui import QTextLayout

        if bitmap:
            pixel_size = max(1, int(strike_height or 1))
            factor = font_size / float(pixel_size)
            line_height = font_size
        else:
            pixel_size = max(1, int(round(font_size)))
            factor = font_size / float(pixel_size)
            face = ft.Face(os.fspath(path_filename), index=getattr(path_filename, 'face_index', 0))
            try:
                face.set_char_size(int(round(font_size * 64)))
                line_height = (face.size.height or (face.size.ascender - face.size.descender)) / 64.0
            finally:
                del face

        font, family, style = self._qt_font(path_filename, pixel_size)
        parts = []
        missing = []
        pen_y = 0.0
        tolerance = max(0.004, pixel_size / 2048.0)

        for raw_line in char_string.split('\n'):
            line_text = _layout_line(raw_line)
            if line_text:
                layout = QTextLayout(line_text, font)
                layout.beginLayout()
                qline = layout.createLine()
                layout.endLayout()
                ascent = qline.ascent() if qline is not None else 0.0

                runs = layout.glyphRuns(0, -1, QTextLayout.GlyphRunRetrievalFlag.RetrieveAll)
                expected, fallback, used = self._qt_expected_runs(runs, family, style, line_text)
                if fallback and not self._qt_fallback_is_ignorable(fallback, line_text, used):
                    raise _TextShapeError(_("Font substitution is not allowed: %s")
                                          % fallback[0].rawFont().familyName())
                for run, raw in expected:
                    string_indexes = run.stringIndexes()
                    positions = run.positions()
                    for order, (glyph_index, position) in enumerate(zip(run.glyphIndexes(), positions)):
                        char = ''
                        if order < len(string_indexes):
                            at = _utf16_index_to_char(line_text, string_indexes[order])
                            if 0 <= at < len(line_text):
                                char = line_text[at]
                        if glyph_index == 0:
                            if char and _ignorable(char):
                                continue
                            missing.append(char or '?')
                            continue

                        # position.y() is the baseline plus any GPOS vertical offset (marks)
                        relative_y = (position.y() - ascent) * factor
                        if bitmap:
                            mask = ParseFont._qt_glyph_mask(raw, glyph_index)
                            if mask is None:
                                continue
                            glyph_geo = ParseFont._mask_geometry(mask, smoothing)
                            if glyph_geo.is_empty:
                                continue
                            rect = raw.boundingRect(glyph_index)
                            x_off = coordx + position.x() * factor + rect.x() * factor
                            y_off = coordy + pen_y - relative_y - rect.y() * factor
                            parts.append(affine_transform(glyph_geo,
                                                          [factor, 0, 0, -factor, x_off, y_off]))
                        else:
                            path = raw.pathForGlyph(glyph_index)
                            if not path.elementCount():
                                continue
                            contours = ParseFont._path_contours(path, tolerance)
                            placed = [[(coordx + position.x() * factor + x * factor,
                                        coordy + pen_y - relative_y - y * factor) for x, y in contour]
                                      for contour in contours]
                            even_odd = getattr(path.fillRule(), 'name', '') == 'OddEvenFill'
                            glyph_geo = ParseFont._contours_geometry(placed, even_odd)
                            if not glyph_geo.is_empty:
                                parts.append(glyph_geo)
            pen_y -= line_height

        if missing:
            chars = ' '.join(sorted(set(missing)))
            raise _TextShapeError(_("Font has no glyph for: %s") % chars)

        return self._finish(parts, units, coordx, coordy, 64.0)

    @staticmethod
    def _qt_glyph_mask(raw, glyph_index):
        """Alpha rows of one bitmap glyph, as QRawFont reports the native strike."""
        from PyQt6.QtGui import QImage, QRawFont

        image = raw.alphaMapForGlyph(glyph_index, QRawFont.AntialiasingType.PixelAntialiasing)
        if image.isNull():
            return None
        if image.format() != QImage.Format.Format_Alpha8:
            image = image.convertToFormat(QImage.Format.Format_Alpha8)
        width, height = image.width(), image.height()
        pointer = image.constBits()
        pointer.setsize(image.sizeInBytes())
        data = bytes(pointer)
        stride = image.bytesPerLine()
        return [data[y * stride:y * stride + width] for y in range(height)]

    @staticmethod
    def _mask_rows(bitmap):
        """Alpha rows of a FreeType mono or gray bitmap."""
        width, rows, pitch = bitmap.width, bitmap.rows, bitmap.pitch
        if not width or not rows:
            return []
        if bitmap.pixel_mode not in (1, 2):  # FT_PIXEL_MODE_MONO, FT_PIXEL_MODE_GRAY
            raise _TextShapeError(_("Unsupported FreeType bitmap pixel mode: %s") % bitmap.pixel_mode)
        stride = abs(pitch)
        data = bytes(bitmap.buffer)
        if len(data) < stride * rows:
            raise _TextShapeError(_("FreeType returned a truncated glyph bitmap."))
        order = range(rows - 1, -1, -1) if pitch < 0 else range(rows)
        out = []
        if bitmap.pixel_mode == 1:
            for y in order:
                row = data[y * stride:y * stride + (width + 7) // 8]
                out.append(bytes(255 if row[x // 8] & (0x80 >> (x % 8)) else 0 for x in range(width)))
        else:
            for y in order:
                out.append(data[y * stride:y * stride + width])
        return out

    @staticmethod
    def _mask_pixels(rows):
        """Connected ink components, 8-connected, as lists of (x, y)."""
        width, height = len(rows[0]), len(rows)
        seen = set()
        components = []
        for y in range(height):
            for x in range(width):
                if rows[y][x] < 128 or (x, y) in seen:
                    continue
                seen.add((x, y))
                stack = [(x, y)]
                pixels = []
                while stack:
                    px, py = stack.pop()
                    pixels.append((px, py))
                    for nx in (px - 1, px, px + 1):
                        for ny in (py - 1, py, py + 1):
                            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen \
                                    and rows[ny][nx] >= 128:
                                seen.add((nx, ny))
                                stack.append((nx, ny))
                components.append(pixels)
        return components

    @staticmethod
    def _pixel_union(pixels):
        """Exact pixel geometry: one unit square per ink pixel, merged per row."""
        rows = {}
        for x, y in pixels:
            rows.setdefault(y, []).append(x)
        boxes = []
        for y, xs in rows.items():
            xs.sort()
            start = previous = xs[0]
            for x in xs[1:]:
                if x == previous + 1:
                    previous = x
                else:
                    boxes.append(box(start, y, previous + 1, y + 1))
                    start = previous = x
            boxes.append(box(start, y, previous + 1, y + 1))
        return unary_union(boxes) if boxes else MultiPolygon()

    @staticmethod
    def _trace_mask_rows(rows, smoothing):
        """Trace one component's pixel mask and simplify it, in the mask's own pixels."""
        imports = []
        try:
            from PIL import Image
            from appCommon.imagetrace import trace_image
            from appParsers.SVG import svg_to_shapes
            imports = [Image, trace_image, svg_to_shapes]
        except ImportError as e:
            raise _TextShapeError(_("Bitmap smoothing needs the image tracing support: %s") % str(e))

        Image, trace_image, svg_to_shapes = imports
        width, height = len(rows[0]), len(rows)
        pixels = bytearray(width * height)
        for y, row in enumerate(rows):
            base = y * width
            for x, alpha in enumerate(row):
                pixels[base + x] = 255 - alpha
        image = Image.frombytes('L', (width, height), bytes(pixels))
        try:
            svg = trace_image(image, black_white=True, threshold=128,
                              options={'mode': 'spline', 'filter_speckle': 0})
        except ImportError as e:
            raise _TextShapeError(_("Bitmap smoothing needs the image tracing support: %s") % str(e))

        shapes = svg_to_shapes(svg, object_type='gerber', units='MM', flip=False,
                               include_text=False, user_units=True)
        traced = unary_union(shapes) if shapes else MultiPolygon()
        # vtracer drops single-pixel details; keep every ink pixel it did not cover
        tiny = [box(x, y, x + 1, y + 1)
                for y, row in enumerate(rows)
                for x, alpha in enumerate(row)
                if alpha >= 128 and not traced.contains(Point(x + 0.5, y + 0.5))]
        if tiny:
            traced = unary_union([traced] + tiny) if not traced.is_empty else unary_union(tiny)
        if traced.is_empty:
            return MultiPolygon()
        return traced.simplify(float(smoothing), preserve_topology=True)

    @staticmethod
    def _mask_topology(geometry):
        parts = list(geometry.geoms) if hasattr(geometry, 'geoms') else ([geometry] if not geometry.is_empty else [])
        return len(parts), sum(len(getattr(part, 'interiors', ())) for part in parts)

    @staticmethod
    def _mask_geometry(rows, smoothing):
        """Pixel mask to polygons: exact topology at 0, traced and simplified above 0."""
        if not rows:
            return MultiPolygon()
        pixels = [(x, y) for y, row in enumerate(rows) for x, alpha in enumerate(row) if alpha >= 128]
        exact = ParseFont._pixel_union(pixels)
        if smoothing <= 0 or exact.is_empty:
            return exact

        parts = []
        for component in ParseFont._mask_pixels(rows):
            x0 = min(x for x, _ in component)
            y0 = min(y for _, y in component)
            x1 = max(x for x, _ in component) + 1
            y1 = max(y for _, y in component) + 1
            # one background pixel around the component keeps the tracer off the image edge
            width, height = x1 - x0 + 2, y1 - y0 + 2
            local = [bytearray(width) for _ in range(height)]
            for x, y in component:
                local[y - y0 + 1][x - x0 + 1] = 255
            local_rows = [bytes(row) for row in local]
            local_pixels = [(x - x0 + 1, y - y0 + 1) for x, y in component]
            local_exact = ParseFont._pixel_union(local_pixels)

            traced = ParseFont._trace_mask_rows(local_rows, smoothing)
            if traced.is_empty:
                traced = local_exact
            else:
                # one-pixel counters and other holes survive the fit unchanged
                for polygon in (local_exact.geoms if hasattr(local_exact, 'geoms') else [local_exact]):
                    for interior in polygon.interiors:
                        hole = Polygon(interior)
                        if traced.contains(hole.representative_point()):
                            traced = traced.difference(hole)
            parts.append(translate(traced, xoff=x0 - 1, yoff=y0 - 1))

        smoothed = unary_union(parts) if parts else MultiPolygon()
        # a fit that merges strokes, closes a counter or loses a dot never replaces the exact mask
        if ParseFont._mask_topology(smoothed) != ParseFont._mask_topology(exact):
            return exact
        return smoothed

    def _bitmap_text_geometry(self, path_filename, face, char_string, font_size, units, coordx, coordy,
                              smoothing):
        """Text set from a font that only has bitmap strikes."""
        strikes = list(face.available_sizes)
        if strikes:
            strike_index = min(range(len(strikes)), key=lambda index: abs(strikes[index].height - font_size))
            strike_height = int(strikes[strike_index].height) or int(round(strikes[strike_index].y_ppem / 64.0)) or 1
        else:
            strike_index = 0
            strike_height = max(1, int(round(font_size)))
        if face.num_fixed_sizes:
            try:
                face.select_size(strike_index)
            except Exception:
                face.set_char_size(0, int(round(strike_height * 64)))
        else:
            face.set_char_size(0, int(round(strike_height * 64)))
        factor = font_size / float(strike_height)
        line_height = face.size.height / 64.0 * factor if face.size.height else font_size

        if _qt_app() is not None:
            try:
                return self._qt_text_geometry(path_filename, char_string, font_size, units, coordx, coordy,
                                              bitmap=True, strike_height=strike_height, smoothing=smoothing)
            except _TextShapeError as e:
                if _needs_shaping(char_string):
                    raise
                log.debug("ParseFont: Qt bitmap text layout failed, using FreeType bitmaps: %s", e)
        elif _needs_shaping(char_string):
            raise _TextShapeError(_("Text shaping needs a running Qt GUI application."))

        return self._freetype_bitmap_geometry(face, char_string, factor, line_height,
                                              units, coordx, coordy, smoothing)

    def _freetype_bitmap_geometry(self, face, char_string, factor, line_height,
                                  units, coordx, coordy, smoothing):
        """Native bitmap strikes laid out by FreeType, for headless and worker callers."""
        header = _winfnt_header(face)
        parts = []
        pen_x = coordx
        pen_y = 0.0
        previous = None
        missing = []

        for char in char_string:
            if char == '\n':
                pen_x = coordx
                pen_y -= line_height
                previous = None
                continue

            glyph_index = _glyph_index(face, char, header)
            if glyph_index == 0:
                if not char.isspace():
                    missing.append(char)
                    continue
                face.load_glyph(0, LOAD_DEFAULT)
                pen_x += face.glyph.advance.x / 64.0 * factor
                previous = None
                continue

            try:
                if previous is not None:
                    pen_x += face.get_kerning(previous, glyph_index).x / 64.0 * factor
            except Exception:
                pass

            face.load_glyph(glyph_index, LOAD_RENDER)
            rows = ParseFont._mask_rows(face.glyph.bitmap)
            if rows:
                glyph_geo = ParseFont._mask_geometry(rows, smoothing)
                if not glyph_geo.is_empty:
                    x_off = pen_x + face.glyph.bitmap_left * factor
                    y_off = coordy + pen_y + face.glyph.bitmap_top * factor
                    parts.append(affine_transform(glyph_geo, [factor, 0, 0, -factor, x_off, y_off]))

            pen_x += face.glyph.advance.x / 64.0 * factor
            previous = glyph_index

        if missing:
            chars = ' '.join(sorted(set(missing)))
            raise _TextShapeError(_("Font has no glyph for: %s") % chars)
        return self._finish(parts, units, coordx, coordy, 64.0)

    def text_advance(self, char_string, font_path, font_size):
        """Advance width of a text run in font_size units, from the same engine that renders it."""
        try:
            font_size = float(font_size)
        except (TypeError, ValueError, OverflowError):
            font_size = float('nan')
        if not math.isfinite(font_size) or font_size <= 0:
            raise ValueError(_("Font size must be a finite positive number."))

        char_string = char_string.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
        face = self._font_face(font_path, font_size)
        try:
            if not face.is_scalable:
                strikes = list(face.available_sizes)
                if strikes:
                    strike_index = min(range(len(strikes)), key=lambda index: abs(strikes[index].height - font_size))
                    strike_height = int(strikes[strike_index].height) or 1
                else:
                    strike_index = 0
                    strike_height = max(1, int(round(font_size)))
                if _qt_app() is not None:
                    try:
                        return self._qt_advance(font_path, char_string, font_size, strike_height)
                    except _TextShapeError:
                        if _needs_shaping(char_string):
                            raise
                elif _needs_shaping(char_string):
                    raise _TextShapeError(_("Text shaping needs a running Qt GUI application."))
                if face.num_fixed_sizes:
                    try:
                        face.select_size(strike_index)
                    except Exception:
                        face.set_char_size(0, int(round(strike_height * 64)))
                else:
                    face.set_char_size(0, int(round(strike_height * 64)))
                header = _winfnt_header(face)
                factor = font_size / float(strike_height)
                widths = []
                for line_text in char_string.split('\n'):
                    total, previous = 0.0, None
                    for char in line_text:
                        glyph_index = _glyph_index(face, char, header)
                        if previous is not None and glyph_index:
                            try:
                                total += face.get_kerning(previous, glyph_index).x / 64.0 * factor
                            except Exception:
                                pass
                        face.load_glyph(glyph_index, LOAD_DEFAULT)
                        total += face.glyph.advance.x / 64.0 * factor
                        previous = glyph_index if glyph_index else None
                    widths.append(total)
                return max(widths) if widths else 0.0

            needs_qt = _needs_shaping(char_string)
            if not needs_qt and _qt_app() is not None:
                needs_qt = self._qt_shaping_required(font_path, char_string, font_size)
            if needs_qt:
                if _qt_app() is None:
                    raise _TextShapeError(_("Text shaping needs a running Qt GUI application."))
                try:
                    return self._qt_advance(font_path, char_string, font_size,
                                            max(1, int(round(font_size))))
                except _TextShapeError:
                    if _needs_shaping(char_string):
                        raise

            face.set_char_size(int(round(font_size * 64)))
            widths = []
            for line_text in char_string.split('\n'):
                total, previous = 0.0, None
                for char in line_text:
                    glyph_index = face.get_char_index(char)
                    if previous is not None and glyph_index:
                        try:
                            total += face.get_kerning(previous, char).x / 64.0
                        except Exception:
                            pass
                    face.load_glyph(glyph_index, LOAD_NO_HINTING)
                    total += face.glyph.advance.x / 64.0
                    previous = char if glyph_index else None
                widths.append(total)
            return max(widths) if widths else 0.0
        finally:
            del face

    def _qt_advance(self, font_path, char_string, font_size, pixel_size):
        from PyQt6.QtGui import QTextLayout

        factor = font_size / float(pixel_size)
        font, family, style = self._qt_font(font_path, pixel_size)
        widths = []
        for raw_line in char_string.split('\n'):
            line_text = _layout_line(raw_line)
            if not line_text:
                widths.append(0.0)
                continue
            layout = QTextLayout(line_text, font)
            layout.beginLayout()
            line = layout.createLine()
            layout.endLayout()
            runs = layout.glyphRuns(0, -1, QTextLayout.GlyphRunRetrievalFlag.RetrieveAll)
            expected, fallback, used = self._qt_expected_runs(runs, family, style, line_text)
            if fallback and not self._qt_fallback_is_ignorable(fallback, line_text, used):
                raise _TextShapeError(_("Font substitution is not allowed: %s")
                                      % fallback[0].rawFont().familyName())
            for run, raw in expected:
                indexes = run.stringIndexes()
                for order, glyph_index in enumerate(run.glyphIndexes()):
                    at = _utf16_index_to_char(line_text, indexes[order]) if order < len(indexes) else -1
                    char = line_text[at] if 0 <= at < len(line_text) else ''
                    if glyph_index == 0:
                        if not (char and _ignorable(char)):
                            raise _TextShapeError(_("Font has no glyph for: %s") % (char or '?'))
                        continue
            # GPOS offsets (especially overhanging zero-width marks) aren't pen advances.
            widths.append(line.horizontalAdvance() * factor)
        return max(widths) if widths else 0.0
