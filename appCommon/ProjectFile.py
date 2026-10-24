# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# License:  MIT Licence                                    #
# ##########################################################

"""
Read and write a FlatCAM project file: plain JSON or JSON compressed with Zstandard.

A project compressed with LZMA (made by an older app version) still loads, but a save never uses LZMA.
The JSON goes to and from the disk as a stream, so the app never holds the compressed data in RAM.

Geometries: a saved file writes each distinct geometry once, in the top-level "geometry_table" list (WKT texts),
and the objects hold references {"__class__": "Shply", "__ref__": index}. "geometry_format" is the marker of
this layout. A file made by an older app version has the WKT inline, {"__class__": "Shply", "__inst__": wkt},
and still loads. An older app version cannot read a file with a geometry table.
"""

import builtins
import gettext
import io
import json
import lzma
import math
import os
from contextlib import contextmanager

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

if '_' not in builtins.__dict__:
    _ = gettext.gettext

try:
    # Python 3.14 and newer
    from compression import zstd as std_zstd
    zstandard = None
except ImportError:
    std_zstd = None
    import zstandard

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
LZMA_MAGIC = b"\xfd7zXZ\x00"

# the most bytes that a project file can have after the decompression (a defense against a decompression bomb)
MAX_DECOMPRESSED_BYTES = 4 * 1024 ** 3

READ_CHUNK_BYTES = 64 * 1024 ** 2

GEOMETRY_TABLE_KEY = "geometry_table"
GEOMETRY_FORMAT_KEY = "geometry_format"
GEOMETRY_FORMAT = 1

ZSTD_MIN_LEVEL = 1
ZSTD_MAX_LEVEL = 22


class ProjectTooLargeError(ValueError):
    pass


class _CappedStream:
    """A read-only wrapper that fails when more than MAX_DECOMPRESSED_BYTES come out of the stream."""

    def __init__(self, stream):
        self._stream = stream
        self._total = 0

    def read(self, size=-1):
        # chunks: a request for everything must not allocate the whole cap before the first byte is read
        chunks = []
        wanted = None if size is None or size < 0 else size
        while wanted is None or wanted > 0:
            step = READ_CHUNK_BYTES if wanted is None else min(wanted, READ_CHUNK_BYTES)
            chunk = self._stream.read(step)
            if not chunk:
                break
            chunks.append(chunk)
            self._total += len(chunk)
            if self._total > MAX_DECOMPRESSED_BYTES:
                raise ProjectTooLargeError(
                    _("The project file is larger than {size} bytes after the decompression.").format(
                        size=MAX_DECOMPRESSED_BYTES))
            if wanted is not None:
                wanted -= len(chunk)
        return chunks[0] if len(chunks) == 1 else b''.join(chunks)

    def __getattr__(self, name):
        return getattr(self._stream, name)


@contextmanager
def open_project_stream(filename):
    """
    Yield a binary stream with the uncompressed content of the project file.
    The magic bytes at the start of the file select Zstandard, LZMA or plain JSON.
    """
    with open(filename, 'rb') as source:
        magic = source.read(len(LZMA_MAGIC))
        source.seek(0)
        if magic.startswith(ZSTD_MAGIC):
            if std_zstd is not None:
                with std_zstd.ZstdFile(source) as stream:
                    yield _CappedStream(stream)
            else:
                with zstandard.ZstdDecompressor().stream_reader(source, closefd=False) as stream:
                    yield _CappedStream(stream)
        elif magic.startswith(LZMA_MAGIC):
            with lzma.LZMAFile(source) as stream:
                yield _CappedStream(stream)
        else:
            yield source


class _Pending:
    """A geometry that json.load() found: decoded together with all the others (see load_project_file())."""
    __slots__ = ('index', 'in_table')

    def __init__(self, index, in_table):
        self.index = index
        self.in_table = in_table


def _decode_wkt(texts):
    if not texts:
        return []
    arr = np.empty(len(texts), dtype=object)
    arr[:] = texts
    return shapely.from_wkt(arr)


def _resolve_pending(root, table_geoms, inline_geoms):
    """Replace the _Pending placeholders inside nested dicts and lists with the decoded geometries."""
    def resolve(item):
        return (table_geoms if item.in_table else inline_geoms)[item.index]

    if isinstance(root, _Pending):
        return resolve(root)
    stack = [root]
    while stack:
        container = stack.pop()
        pairs = container.items() if isinstance(container, dict) else enumerate(container)
        for key, value in list(pairs):
            if isinstance(value, _Pending):
                container[key] = resolve(value)
            elif isinstance(value, (dict, list)):
                stack.append(value)
    return root


def load_project_file(filename, object_hook=None):
    """
    Parse a project file (Zstandard, LZMA or plain JSON).

    All the geometries of the file are decoded with one vectorized shapely.from_wkt() call after the JSON is
    parsed. A geometry that the file writes once and references many times is one shared object.

    :param filename:    path to the project file
    :param object_hook: the function that json.load() calls for each decoded dict, besides the geometries and
                        aperture macros that this function decodes itself (None or camlib.dict2obj)
    :return:            the decoded JSON content
    """
    from camlib import ApertureMacro, dict2obj

    inline = []

    def hook(d):
        if '__class__' in d:
            kind = d['__class__']
            if kind == "Shply":
                if '__ref__' in d:
                    return _Pending(d['__ref__'], True)
                if '__inst__' in d:
                    inline.append(d['__inst__'])
                    return _Pending(len(inline) - 1, False)
            elif kind == "ApertureMacro" and '__inst__' in d:
                macro = ApertureMacro()
                macro.from_dict(d['__inst__'])
                return macro
        if object_hook is not None and object_hook is not dict2obj:
            return object_hook(d)
        return d

    with open_project_stream(filename) as stream:
        data = json.load(stream, object_hook=hook)

    table = []
    if isinstance(data, dict) and GEOMETRY_TABLE_KEY in data:
        table = data.pop(GEOMETRY_TABLE_KEY)
        data.pop(GEOMETRY_FORMAT_KEY, None)
    return _resolve_pending(data, _decode_wkt(table), _decode_wkt(inline))


@contextmanager
def _open_zstd_writer(target, level):
    level = max(ZSTD_MIN_LEVEL, min(ZSTD_MAX_LEVEL, int(level)))
    if std_zstd is not None:
        options = {
            std_zstd.CompressionParameter.compression_level: level,
            std_zstd.CompressionParameter.checksum_flag: 1
        }
        with std_zstd.ZstdFile(target, 'w', options=options) as stream:
            yield stream
    else:
        compressor = zstandard.ZstdCompressor(level=level, write_checksum=True)
        with compressor.stream_writer(target, closefd=False) as stream:
            yield stream


def _dump_json(stream, data, default, allow_nan, compact=False):
    text = io.TextIOWrapper(stream, encoding='utf-8', newline='\n')
    try:
        if compact:
            # no indentation and no sorted keys: less text to make and to compress
            json.dump(data, text, default=default, separators=(',', ':'), allow_nan=allow_nan)
        else:
            json.dump(data, text, default=default, indent=2, sort_keys=True, allow_nan=allow_nan)
    finally:
        # detach() flushes the text and leaves the binary stream open for its owner to close
        text.detach()


def _write_json(filename, data, default, compression_level, allow_nan):
    with open(filename, 'wb') as target:
        if compression_level is None:
            _dump_json(target, data, default, allow_nan)
        else:
            # a compressed file is not read as text, so its JSON is compact
            with _open_zstd_writer(target, compression_level) as stream:
                _dump_json(stream, data, default, allow_nan, compact=True)


def _clean_floats(obj):
    """Replace the inf and nan floats with None, because they are not valid JSON."""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
    elif isinstance(obj, dict):
        return {k: _clean_floats(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_clean_floats(x) for x in obj]
    return obj


def _with_geometry_table(data, default):
    """
    Return the data and the 'default' function of json.dump() for a save that writes each distinct geometry once.
    This needs a ``default`` made by camlib.project_json_default(): it holds the WKT of the geometries.
    Else the data is saved as it is, with the WKT of each geometry inline.
    """
    wkt_cache = getattr(default, 'wkt_cache', None)
    if not wkt_cache or not isinstance(data, dict):
        return data, default

    table = {}
    for _geom, text in wkt_cache.values():
        table.setdefault(text, len(table))

    def table_default(obj):
        if isinstance(obj, BaseGeometry):
            entry = wkt_cache.get(id(obj))
            if entry is not None and entry[0] is obj:
                return {"__class__": "Shply", "__ref__": table[entry[1]]}
        return default(obj)

    table_data = dict(data)
    table_data[GEOMETRY_TABLE_KEY] = list(table)
    table_data[GEOMETRY_FORMAT_KEY] = GEOMETRY_FORMAT
    return table_data, table_default


def save_project_file(filename, data, default=None, compression_level=None):
    """
    Write a project file as a JSON stream. It goes to a temporary file first, which replaces ``filename``
    only after a complete write, so a failed save keeps the old file.

    :param filename:            path to the project file
    :param data:                the project dict
    :param default:             the function that json.dump() calls for an object that it cannot serialize
                                (camlib.project_json_default() makes the geometry table of the file)
    :param compression_level:   None for plain JSON, else the Zstandard compression level (1 to 22).
                                A compressed file has no inf or nan values: they become null.
    """
    data, default = _with_geometry_table(data, default)
    temp_filename = filename + '.tmp'
    try:
        if compression_level is None:
            _write_json(temp_filename, data, default, None, allow_nan=True)
        else:
            try:
                _write_json(temp_filename, data, default, compression_level, allow_nan=False)
            except ValueError:
                # there are inf/nan values; write again with them replaced by None
                _write_json(temp_filename, _clean_floats(data), default, compression_level, allow_nan=False)
        os.replace(temp_filename, filename)
    except BaseException:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        raise
