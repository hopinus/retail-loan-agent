import io
import re
import struct
import zlib
from html import unescape
from urllib.parse import urljoin, urlsplit

import olefile
from pypdf import PdfReader
from market_watch import download


def hwp_lines(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as doc:
        compressed = doc.openstream('FileHeader').read()[36] & 1
        for path in doc.listdir():
            if not re.fullmatch(r'BodyText/Section\d+', '/'.join(path)):
                continue
            data = doc.openstream(path).read()
            if compressed:
                data = zlib.decompressobj(-15).decompress(data, 12_000_000)
            offset = 0
            while offset + 4 <= len(data):
                header, = struct.unpack_from('<I', data, offset)
                offset += 4
                size = header >> 20
                if size == 4095:
                    size, = struct.unpack_from('<I', data, offset)
                    offset += 4
                if header & 1023 == 67:
                    raw = data[offset:offset+size].decode('utf-16le', 'replace')
                    raw = re.sub(r'[\x01-\x09\x0b\x0c\x0e-\x17].{6}.', '', raw, flags=re.S)
                    yield re.sub(r'\s+', ' ', raw).strip()
                offset += size


def documents(row):
    page = download(row['url']).decode('utf8')
    seen = set()
    for href, body in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S|re.I):
        name = unescape(re.sub('<[^>]+>', '', body)).strip()
        url = urljoin(row['url'], unescape(href))
        if urlsplit(url).hostname != 'www.fss.or.kr' or urlsplit(url).path != '/fss/cmmn/file/fileDown.do':
            continue
        match = re.search(r'([^\n\r]+)\.(hwp|pdf)$', name.split('(파일크기')[0].strip(), re.I)
        if not match or match[1].strip() in seen:
            continue
        seen.add(match[1].strip())
        blob = download(url)
        if match[2].lower() == 'hwp':
            yield match[0].strip(), url, list(hwp_lines(blob))
        else:
            yield match[0].strip(), url, [s.strip() for p in PdfReader(io.BytesIO(blob)).pages for s in p.extract_text().splitlines()]


