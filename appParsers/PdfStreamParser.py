# appParsers/PdfStreamParser.py
"""
PDF Stream Parser Module

Provides pluggable PDF content stream extraction with multiple backends:
- PurePythonPdfParser: Uses only standard library (zlib + re, default)
- PikePdfParser: Uses pikepdf library (optional, lazy import when enabled)

Configuration (via defaults.py):
    pdf_python_parser: True   -> Use pure-python parser (default, recommended)
    pdf_python_parser: False  -> Use pikepdf parser (requires pikepdf installation)

Usage:
    from appParsers.PdfStreamParser import get_pdf_parser
    
    # Get parser based on defaults.py configuration
    parser = get_pdf_parser(app.defaults)
    content = parser.extract_content_streams("file.pdf")
    
    # Or use convenience function
    from appParsers.PdfStreamParser import parse_pdf_content_streams
    content = parse_pdf_content_streams("file.pdf", app.defaults)

Why pure-python is default:
    - No external dependencies
    - Works with all Python 3.11+ installations
    - Latest pikepdf versions crash on import even with try/except
    - Lazy import of pikepdf only when explicitly enabled
    
Note: Only the first page of PDFs is extracted (existing FlatCAM behavior).
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import base64
import logging
import re
import zlib

log = logging.getLogger('base')


class PdfStreamParserBase(ABC):
    """
    Abstract base class for PDF content stream parsers.
    
    Extracts and decompresses PDF content streams into text format
    that can be parsed by ParsePDF.py
    """
    
    @abstractmethod
    def extract_content_streams(self, filename: str) -> str:
        """
        Extract and decompress content streams from a PDF file.
        
        Only extracts from the first page (existing FlatCAM behavior).
        
        Args:
            filename: Path to the PDF file
            
        Returns:
            Decompressed content stream text (PDF operators as text)
            
        Raises:
            PdfParserError: If parsing fails
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this parser backend is available (dependencies installed).
        
        Returns:
            True if parser can be used, False otherwise
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return human-readable parser name."""
        pass


class PdfParserError(Exception):
    """Exception raised when PDF parsing fails."""
    pass


class PurePythonPdfParser(PdfStreamParserBase):
    """
    PDF parser using only Python standard library.

    Resolves the first page object's /Contents references and decodes those streams
    only. Supports FlateDecode, ASCIIHexDecode and ASCII85Decode.

    This is the DEFAULT parser - no external dependencies required.

    Limitations:
    - Does not support encrypted PDFs
    - Does not support LZW or other compression filters
    - Does not support object streams
    - May fail on complex PDF structures
    """
    
    # Regex to find PDF streams
    # Pattern: <<dictionary>> stream <compressed_data> endstream
    STREAM_PATTERN = re.compile(
        rb'<<.*?>>\s*stream\s*\r?\n(.*?)\s*\r?\n?\s*endstream',
        re.DOTALL
    )
    
    # Pattern to check for FlateDecode filter
    FLATE_DECODE_PATTERN = re.compile(rb'/FlateDecode')
    
    # Pattern to find BDC/EMC layer markers (PDF 1.2+)
    LAYER_PATTERN = re.compile(rb'BDC(.*?)EMC', re.DOTALL)
    
    @property
    def name(self) -> str:
        return "pure-python"
    
    def is_available(self) -> bool:
        # Always available - uses only standard library
        return True
    
    def extract_content_streams(self, filename: str) -> str:
        """
        Extract the content streams of the first page using only the standard library.

        The page object's ``/Contents`` references are resolved in order. Unrelated
        streams (fonts, images, metadata) are not concatenated into the geometry stream.

        Args:
            filename: Path to PDF file

        Returns:
            Decompressed content stream text

        Raises:
            PdfParserError: If parsing fails or an unsupported feature is found
        """
        try:
            with open(filename, "rb") as f:
                pdf_data = f.read()

            result = self._extract_first_page_streams(pdf_data)

            if not result.strip():
                raise PdfParserError("No valid content streams found")

            return result

        except PdfParserError:
            raise
        except Exception as e:
            raise PdfParserError(f"pure-python parsing failed: {str(e)}")

    def _extract_first_page_streams(self, pdf_data: bytes) -> str:
        """Resolve the first page object and decode its /Contents streams in order."""
        if re.search(rb'/Encrypt\s+(\d+\s+\d+\s+R|<<)', pdf_data):
            raise PdfParserError(
                "Encrypted PDFs are not supported by the pure-python parser"
            )

        objects = self._parse_objects(pdf_data)
        if not objects:
            raise PdfParserError("No PDF objects found")

        if any(re.search(rb'/Encrypt\b', obj['dict']) for obj in objects.values()):
            raise PdfParserError(
                "Encrypted PDFs are not supported by the pure-python parser"
            )

        page_ref = self._first_page_ref(objects)
        if page_ref is None:
            if any(re.search(rb'/Type\s*/ObjStm\b', obj['dict']) for obj in objects.values()):
                raise PdfParserError(
                    "PDF object streams are not supported by the pure-python parser"
                )
            raise PdfParserError("Could not locate the first page")

        content_refs = self._resolve_content_refs(
            objects, self._content_refs(objects[page_ref]['dict'])
        )
        if not content_refs:
            raise PdfParserError("The first page has no content stream")

        parts = []
        for ref in content_refs:
            content_obj = objects.get(ref)
            if content_obj is None or content_obj['stream'] is None:
                raise PdfParserError(
                    f"Missing content stream object {ref[0]} {ref[1]} R"
                )
            data = self._decode_stream(content_obj['dict'], content_obj['stream'])
            parts.append(data.decode('utf-8', errors='replace'))

        return '\n'.join(parts)

    @classmethod
    def _resolve_content_refs(cls, objects: dict, refs: list) -> list:
        """Expand an indirect /Contents array object into its stream references."""
        resolved = []
        for ref in refs:
            obj = objects.get(ref)
            if obj is not None and obj['stream'] is None:
                nested = cls._content_refs(obj['dict'])
                if not nested:
                    array = re.search(rb'\[(.*?)\]', obj['dict'], re.DOTALL)
                    if array:
                        nested = [(int(number), int(generation))
                                  for number, generation in re.findall(
                                      rb'(\d+)\s+(\d+)\s+R', array.group(1))]
                if nested:
                    resolved.extend(cls._resolve_content_refs(objects, nested))
                    continue
            resolved.append(ref)
        return resolved

    @staticmethod
    def _parse_objects(pdf_data: bytes) -> Dict[tuple, Dict[str, Any]]:
        """Parse indirect objects, including their dictionaries and raw stream bytes.

        Stream data is bounded by the declared /Length (direct or indirect) instead of
        the first ``endstream`` / ``endobj`` token: both words are legal inside an
        uncompressed content stream. The token search is only a fallback for a missing
        or malformed length.
        """
        objects = {}
        header_re = re.compile(rb'(\d+)\s+(\d+)\s+obj\b')
        stream_re = re.compile(rb'>>\s*stream[ \t]*(?:\r\n|\r|\n)')
        position = 0

        while True:
            match = header_re.search(pdf_data, position)
            if not match:
                break

            number = int(match.group(1))
            generation = int(match.group(2))
            body_start = match.end()
            endobj = pdf_data.find(b'endobj', body_start)
            stream_match = stream_re.search(pdf_data, body_start)

            if stream_match is not None and (endobj < 0 or stream_match.start() < endobj):
                dictionary = pdf_data[body_start:stream_match.start() + 2]
                data_start = stream_match.end()
                length = PurePythonPdfParser._stream_length(pdf_data, dictionary)
                next_position = None
                stream_data = None

                if length is not None and 0 <= length <= len(pdf_data) - data_start:
                    candidate_end = data_start + length
                    if re.match(rb'\s*endstream\b',
                                pdf_data[candidate_end:candidate_end + 32]):
                        stream_data = pdf_data[data_start:candidate_end]
                        next_position = candidate_end

                if next_position is None:
                    endstream = pdf_data.find(b'endstream', data_start)
                    if endstream < 0:
                        endstream = endobj if endobj >= 0 else len(pdf_data)
                    stream_data = pdf_data[data_start:endstream]
                    if stream_data.endswith(b'\r\n'):
                        stream_data = stream_data[:-2]
                    elif stream_data.endswith((b'\n', b'\r')):
                        stream_data = stream_data[:-1]
                    next_position = endstream + len(b'endstream')

                end = pdf_data.find(b'endobj', next_position)
                if end < 0:
                    end = next_position
            else:
                if endobj < 0:
                    break
                dictionary = pdf_data[body_start:endobj]
                stream_data = None
                end = endobj

            objects[(number, generation)] = {'dict': dictionary, 'stream': stream_data}
            position = end + len(b'endobj')

        return objects

    @staticmethod
    def _stream_length(pdf_data: bytes, dictionary: bytes) -> Optional[int]:
        """Return the declared stream length, resolving an indirect /Length object."""
        match = re.search(rb'/Length\s+(\d+)\s+(\d+)\s+R\b', dictionary)
        if match:
            length_ref = re.search(
                rb'(?<![\d])%d\s+%d\s+obj\b\s*([+-]?\d+)' %
                (int(match.group(1)), int(match.group(2))),
                pdf_data
            )
            return int(length_ref.group(1)) if length_ref else None

        match = re.search(rb'/Length\s+([+-]?\d+)(?!\s+\d+\s+R)\b', dictionary)
        return int(match.group(1)) if match else None

    @staticmethod
    def _walk_pages(objects: dict, ref: tuple, seen: set):
        """Depth-first walk of the page tree; return the first /Page reference."""
        if ref in seen or ref not in objects:
            return None
        seen.add(ref)

        dictionary = objects[ref]['dict']
        if re.search(rb'/Type\s*/Page\b', dictionary):
            return ref
        if re.search(rb'/Type\s*/Pages\b', dictionary):
            kids = re.search(rb'/Kids\s*\[(.*?)\]', dictionary, re.DOTALL)
            if kids:
                for number, generation in re.findall(rb'(\d+)\s+(\d+)\s+R', kids.group(1)):
                    found = PurePythonPdfParser._walk_pages(
                        objects, (int(number), int(generation)), seen
                    )
                    if found:
                        return found
        return None

    @classmethod
    def _first_page_ref(cls, objects: dict):
        """Find the first page through the catalog/page tree, with a file-order fallback."""
        for ref, obj in objects.items():
            if re.search(rb'/Type\s*/Catalog\b', obj['dict']):
                pages = re.search(rb'/Pages\s+(\d+)\s+(\d+)\s+R', obj['dict'])
                if pages:
                    page = cls._walk_pages(
                        objects, (int(pages.group(1)), int(pages.group(2))), set()
                    )
                    if page:
                        return page
                break

        pages = [ref for ref, obj in objects.items()
                 if re.search(rb'/Type\s*/Page\b', obj['dict'])]
        return sorted(pages)[0] if pages else None

    @staticmethod
    def _content_refs(dictionary: bytes) -> list:
        """Return the /Contents references of a page in array order."""
        match = re.search(
            rb'/Contents\s*(\[(.*?)\]|(\d+)\s+(\d+)\s+R)', dictionary, re.DOTALL
        )
        if not match:
            return []
        if match.group(2) is not None:
            return [(int(number), int(generation))
                    for number, generation in re.findall(rb'(\d+)\s+(\d+)\s+R', match.group(2))]
        return [(int(match.group(3)), int(match.group(4)))]

    @staticmethod
    def _stream_filters(dictionary: bytes) -> list:
        match = re.search(rb'/Filter\s*(\[[^\]]*\]|/\w+)', dictionary)
        if not match:
            if re.search(rb'/Filter\b', dictionary):
                raise PdfParserError("Unsupported indirect PDF filter reference")
            return []
        return [name.decode('ascii') for name in re.findall(rb'/(\w+)', match.group(1))]

    @staticmethod
    def _decode_ascii_hex(data: bytes) -> bytes:
        data = data.split(b'>', 1)[0]
        data = re.sub(rb'\s+', b'', data)
        if len(data) % 2:
            data += b'0'
        try:
            return bytes.fromhex(data.decode('ascii'))
        except ValueError as exc:
            raise PdfParserError(f"ASCIIHexDecode failed: {exc}")

    @staticmethod
    def _decode_ascii85(data: bytes) -> bytes:
        data = data.strip()
        if data.startswith(b'<~'):
            data = data[2:]
        if data.endswith(b'~>'):
            data = data[:-2]
        try:
            return base64.a85decode(re.sub(rb'\s+', b'', data))
        except ValueError as exc:
            raise PdfParserError(f"ASCII85Decode failed: {exc}")

    def _decode_stream(self, dictionary: bytes, stream_data: bytes) -> bytes:
        """Apply the stream's declared filters. Unknown filters fail loudly."""
        if re.search(rb'/DecodeParms', dictionary):
            raise PdfParserError("Unsupported PDF stream parameter: /DecodeParms")

        data = stream_data
        for filter_name in self._stream_filters(dictionary):
            if filter_name == 'FlateDecode':
                decoded = self._decompress_stream(data)
                if decoded is None:
                    raise PdfParserError("FlateDecode decompression failed")
                data = decoded
            elif filter_name == 'ASCIIHexDecode':
                data = self._decode_ascii_hex(data)
            elif filter_name == 'ASCII85Decode':
                data = self._decode_ascii85(data)
            else:
                raise PdfParserError(f"Unsupported PDF filter: {filter_name}")

        return data

    def _extract_all_streams(self, pdf_data: bytes) -> str:
        """
        Extract and decompress all FlateDecode streams.
        
        Args:
            pdf_data: Raw PDF file data
            
        Returns:
            Concatenated decompressed stream content
        """
        output_parts = []
        
        for match in self.STREAM_PATTERN.finditer(pdf_data):
            stream_dict = pdf_data[match.start():match.start() + match.group(0).find(b'stream')]
            compressed_data = match.group(1)
            
            # Only process FlateDecode streams
            if not self.FLATE_DECODE_PATTERN.search(stream_dict):
                continue
            
            try:
                decompressed = self._decompress_stream(compressed_data)
                if decompressed:
                    try:
                        text = decompressed.decode('utf-8', errors='replace')
                    except Exception:
                        text = decompressed.decode('latin-1', errors='replace')
                    output_parts.append(text)
            except Exception as e:
                log.debug(f"Stream decompression failed: {e}")
                continue
        
        return '\n'.join(output_parts)
    
    def _decompress_if_needed(self, data: bytes) -> Optional[bytes]:
        """Try to decompress data if it's compressed."""
        # Try direct decode first
        try:
            data.decode('utf-8')
            return data  # Already decompressed
        except UnicodeDecodeError:
            pass
        
        # Try decompression
        return self._decompress_stream(data)
    
    def _decompress_stream(self, compressed_data: bytes) -> Optional[bytes]:
        """
        Decompress FlateDecode stream using zlib.
        
        Args:
            compressed_data: Raw compressed stream data
            
        Returns:
            Decompressed data or None if decompression fails
        """
        # Try different zlib decompression strategies
        # -15 = raw deflate (no zlib header) - most common for PDFs
        try:
            return zlib.decompress(compressed_data, -15)
        except zlib.error:
            pass
        
        # Try with standard zlib header
        try:
            return zlib.decompress(compressed_data)
        except zlib.error:
            pass
        
        # Try with auto-detect header (15 + 32)
        try:
            return zlib.decompress(compressed_data, 15 + 32)
        except zlib.error:
            pass
        
        # All strategies failed - data might be corrupted or use different filter
        log.debug("All zlib decompression strategies failed")
        return None


class PikePdfParser(PdfStreamParserBase):
    """
    PDF parser using pikepdf library.
    
    Provides full PDF support including:
    - Multiple compression filters
    - Object streams
    - Encrypted PDFs (with password)
    - Complex PDF structures
    
    IMPORTANT: pikepdf is imported LAZY (only when this class is instantiated).
    This avoids import crashes on systems with incompatible pikepdf versions.
    
    Note: Only extracts content from the first page (existing FlatCAM behavior).
    """
    
    def __init__(self):
        """
        Lazy import of pikepdf - only import when actually creating instance.
        
        This prevents import-time crashes from breaking the application.
        """
        self._pikepdf = None
        self._available = None
        self.unsupported_features = set()
        self._try_import()
    
    def _try_import(self) -> None:
        """
        Attempt lazy import of pikepdf.
        
        Sets self._available to True if import succeeds, False otherwise.
        """
        if self._available is not None:
            return  # Already tried
        
        try:
            # LAZY IMPORT - only happens when PikePdfParser is instantiated
            import pikepdf
            from pikepdf import Pdf, parse_content_stream
            self._pikepdf = {
                'Pdf': Pdf,
                'parse_content_stream': parse_content_stream,
            }
            self._available = True
            log.debug("pikepdf imported successfully (lazy import)")
        except Exception as e:
            log.warning(f"pikepdf lazy import failed: {e}")
            self._pikepdf = None
            self._available = False
    
    @property
    def name(self) -> str:
        return "pikepdf"
    
    def is_available(self) -> bool:
        """Check if pikepdf was successfully imported."""
        return self._available is True
    
    def extract_content_streams(self, filename: str) -> str:
        """
        Extract content streams using pikepdf.
        
        Only extracts from the first page (existing FlatCAM behavior).
        
        Args:
            filename: Path to PDF file
            
        Returns:
            Decompressed content stream text
            
        Raises:
            PdfParserError: If pikepdf is not available or parsing fails
        """
        if not self.is_available():
            raise PdfParserError(
                "pikepdf is not available. "
                "Install with: pip install pikepdf>=2.0, "
                "or set pdf_python_parser=True in defaults.py to use pure-python parser"
            )

        self.unsupported_features = set()

        try:
            Pdf = self._pikepdf['Pdf']
            parse_content_stream = self._pikepdf['parse_content_stream']
            
            with open(filename, "rb") as f:
                pdf = Pdf.open(f)
                
                # Extract FIRST PAGE ONLY (existing FlatCAM behavior)
                page = pdf.pages[0]
                decomp_file = ''
                
                for operands, command in parse_content_stream(page):
                    if str(command) == 'Do':
                        self.unsupported_features.add('XObject')
                    elif str(command) in ('W', 'W*'):
                        self.unsupported_features.add('clipping')

                    line = ''
                    for op in operands:
                        try:
                            line += str(op) + ' '
                        except Exception:
                            # Skip operands that can't be converted to string
                            pass
                    line += str(command)
                    decomp_file += line + '\n'
                
                if not decomp_file.strip():
                    raise PdfParserError("Empty content stream or parsing error")
                
                return decomp_file
                
        except Exception as e:
            raise PdfParserError(f"pikepdf parsing failed: {str(e)}")


def get_pdf_parser(app_defaults: Optional[Dict[str, Any]] = None) -> PdfStreamParserBase:
    """
    Factory function to get PDF parser based on configuration.
    
    Args:
        app_defaults: Application defaults dict (from defaults.py).
                     If None, uses pure-python parser as safe default.
    
    Returns:
        PdfStreamParserBase instance
        
    Raises:
        PdfParserError: If selected parser is not available
    """
    # Default to pure-python (safe, no dependencies)
    use_pure_python = True
    
    if app_defaults is not None:
        # Check configuration: pdf_python_parser=True means use pure-python
        use_pure_python = app_defaults.get('pdf_python_parser', True)
    
    if use_pure_python:
        log.debug("Using pure-python PDF parser (pdf_python_parser=True)")
        return PurePythonPdfParser()
    else:
        # User explicitly requested pikepdf
        log.debug("Using pikepdf PDF parser (pdf_python_parser=False)")
        parser = PikePdfParser()
        
        if not parser.is_available():
            log.warning(
                "pikepdf parser requested but not available. "
                "Falling back to pure-python parser. "
                "Set pdf_python_parser=True in defaults.py to suppress this warning."
            )
            return PurePythonPdfParser()
        
        return parser


def get_pdf_parser_by_name(name: str) -> PdfStreamParserBase:
    """
    Factory function to get PDF parser by explicit name.
    
    Args:
        name: Parser name ('pure-python' or 'pikepdf')
    
    Returns:
        PdfStreamParserBase instance
    """
    if name == 'pure-python':
        return PurePythonPdfParser()
    elif name == 'pikepdf':
        return PikePdfParser()
    else:
        raise PdfParserError(f"Unknown parser name: {name}")


def parse_pdf_content_streams(
    filename: str,
    app_defaults: Optional[Dict[str, Any]] = None
) -> str:
    """
    Extract content streams from a PDF file.
    
    Only extracts from the first page (existing FlatCAM behavior).
    
    Args:
        filename: Path to PDF file
        app_defaults: Application defaults dict
        
    Returns:
        Decompressed content stream text
        
    Raises:
        PdfParserError: If parsing fails
    """
    parser = get_pdf_parser(app_defaults)
    return parser.extract_content_streams(filename)


# Exports
__all__ = [
    'PdfStreamParserBase',
    'PdfParserError',
    'PurePythonPdfParser',
    'PikePdfParser',
    'get_pdf_parser',
    'get_pdf_parser_by_name',
    'parse_pdf_content_streams',
]
