# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# License:  MIT Licence                                    #
# ##########################################################

"""
Read and write a FlatCAM project file: plain JSON or JSON compressed with Zstandard.

A project compressed with LZMA (made by an older app version) still loads, but a save never uses LZMA.
The JSON goes to and from the disk as a stream, so the app never holds the compressed data in RAM.
"""

import io
import json
import lzma
import math
import os
from contextlib import contextmanager

try:
    # Python 3.14 and newer
    from compression import zstd as std_zstd
    zstandard = None
except ImportError:
    std_zstd = None
    import zstandard

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
LZMA_MAGIC = b"\xfd7zXZ\x00"

ZSTD_MIN_LEVEL = 1
ZSTD_MAX_LEVEL = 22


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
                    yield stream
            else:
                with zstandard.ZstdDecompressor().stream_reader(source, closefd=False) as stream:
                    yield stream
        elif magic.startswith(LZMA_MAGIC):
            with lzma.LZMAFile(source) as stream:
                yield stream
        else:
            yield source


def load_project_file(filename, object_hook=None):
    """
    Parse a project file (Zstandard, LZMA or plain JSON).

    :param filename:    path to the project file
    :param object_hook: the function that json.load() calls for each decoded dict
    :return:            the decoded JSON content
    """
    with open_project_stream(filename) as stream:
        return json.load(stream, object_hook=object_hook)


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


def save_project_file(filename, data, default=None, compression_level=None):
    """
    Write a project file as a JSON stream. It goes to a temporary file first, which replaces ``filename``
    only after a complete write, so a failed save keeps the old file.

    :param filename:            path to the project file
    :param data:                the project dict
    :param default:             the function that json.dump() calls for an object that it cannot serialize
    :param compression_level:   None for plain JSON, else the Zstandard compression level (1 to 22).
                                A compressed file has no inf or nan values: they become null.
    """
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
