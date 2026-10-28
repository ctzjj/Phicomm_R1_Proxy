"""Wire helpers: P header, chunk framing, is-final, Ogg muxer, HTTP text utils.

Ported 1:1 from repo/go/internal/{asr,audio,util}; byte-compatible fixture:
dump_raw/0001_req.bin etc.
"""
from __future__ import annotations

import json
import re
import struct
from typing import Any


# ---------------- P header / final ----------------
SID_RE = re.compile(rb"(?mi)^P:[^\r\n]*\[([^\]\r\n]+)\]")


def audio_session_id(hdr: bytes) -> str | None:
    m = SID_RE.search(hdr)
    if not m:
        return None
    try:
        return m.group(1).decode("utf-8", "replace")
    except Exception:
        return None


def is_final_request(hdr: bytes, content_length: int | None) -> bool:
    """Go: contentLength==0 && (strings.Contains(hdr,"\r\nTP:") || HasPrefix("TP:"))."""
    if content_length not in (0, None):
        return False
    return b"\r\nTP:" in hdr or hdr.startswith(b"TP:")


# ---------------- framing ----------------
def parse_chunks(body: bytes) -> list[bytes]:
    """[u16 LE len][pkt]... ; 0 len or overflow stops."""
    out: list[bytes] = []
    i = 0
    while i + 2 <= len(body):
        n = struct.unpack_from("<H", body, i)[0]
        i += 2
        if n == 0 or i + n > len(body):
            break
        out.append(body[i:i + n])
        i += n
    return out


# ---------------- OggOpus muxer(逐字节对齐 Go audio/ogg.go) ----------------
def _crc_table() -> list[int]:
    t = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            if r & 0x80000000:
                r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                r = (r << 1) & 0xFFFFFFFF
        t.append(r)
    return t


_CRC: list[int] = _crc_table()


def ogg_crc(data: bytes | bytearray) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC[((crc >> 24) & 0xFF) ^ b]
    return crc


_PACKET_SAMPLES_48K = 960
_PRESKIP = 312
_OGG_SERIAL = 0x52314F50  # "R1OP"


def _lacing(length: int) -> list[int]:
    segs: list[int] = []
    n = length
    while n >= 255:
        segs.append(255)
        n -= 255
    segs.append(n)
    return segs


def _page(flags: int, granule: int, seq: int, serial: int,
          segs: list[int], data: bytes) -> bytes:
    total = len(segs)
    header = bytearray(27 + total)
    header[0:4] = b"OggS"
    header[4] = 0
    header[5] = flags
    struct.pack_into("<Q", header, 6, granule)
    struct.pack_into("<I", header, 14, serial)
    struct.pack_into("<I", header, 18, seq)
    # bytes 22..25 CRC 置 0 后计算;byte 26 = seg count;27.. = lacing table
    header[26] = total
    header[27:27 + total] = bytes(segs)
    body = bytearray(header)
    body += data
    crc = ogg_crc(body)
    struct.pack_into("<I", body, 22, crc)
    return bytes(body)


def ogg_opus(packets: tuple[bytes, ...]) -> bytes:
    out = bytearray()
    seq = 0
    # page0: BOS + OpusHead
    head = bytearray(19)
    head[0:8] = b"OpusHead"
    head[8] = 1
    head[9] = 1
    struct.pack_into("<H", head, 10, _PRESKIP)
    struct.pack_into("<I", head, 12, 16000)
    struct.pack_into("<H", head, 16, 0)   # gain
    head[18] = 0                          # mapping family
    out += _page(0x02, 0, seq, _OGG_SERIAL, _lacing(len(head)), bytes(head))
    seq += 1
    # page1: OpusTags
    vendor = b"r1tool"
    body = bytearray()
    body += b"OpusTags"
    body += struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
    out += _page(0, 0, seq, _OGG_SERIAL, _lacing(len(body)), bytes(body))
    seq += 1
    # data pages: <=250 packets each
    done = 0
    i = 0
    while i < len(packets):
        chunk = packets[i:i + 250]
        i += 250
        segs: list[int] = []
        data = bytearray()
        for p in chunk:
            ls = _lacing(len(p))
            segs.extend(ls)
            data.extend(p)
        last = i >= len(packets)
        flags = 0x04 if last else 0
        done += len(chunk)
        out += _page(flags, done * _PACKET_SAMPLES_48K, seq, _OGG_SERIAL, segs, bytes(data))
        seq += 1
    return bytes(out)


# ---------------- HTTP text utils(对齐 Go util/datautil.go) ----------------
class Parse:
    """Minimal raw-HTTP message parse: headers block + body."""

    def __init__(self, raw: bytes) -> None:
        idx = raw.find(b"\r\n\r\n")
        if idx < 0:
            self.Headers_Raw = raw
            self.Body: Any = None
        else:
            self.Headers_Raw = raw[:idx]
            body = raw[idx + 4:]
            try:
                self.Body = json.loads(body.decode("utf-8"))
            except Exception:
                self.Body = body.decode("utf-8", "replace")


class Data:
    """Re-marshal + fix Content-Length (compact JSON, no HTML escaping)."""

    def __init__(self, raw_headers: bytes, body: Any) -> None:
        self.hdr = raw_headers
        self.body = body

    def Build(self) -> bytes:
        text = json.dumps(self.body, ensure_ascii=False,
                          separators=(",", ":")) if not isinstance(self.body, str) else self.body
        payload = text.encode("utf-8")
        hdr = self.hdr
        if re.search(rb"(?i)Content-Length: [0-9]+", hdr):
            hdr = re.sub(rb"(?i)Content-Length: [0-9]+",
                         ("Content-Length: %d" % len(payload)).encode(), hdr, count=1)
        else:
            hdr = hdr + ("\r\nContent-Length: %d" % len(payload)).encode()
        return hdr + b"\r\n\r\n" + payload


def fake_resp_raw(sid: bytes, body: Any) -> bytes:
    return (b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: W510\r\n"
            b"RS: GeLdJ\r\n"
            b"PN: ry\r\n"
            b"SID: " + sid + b"\r\n"
            b"Content-Type: application/json\r\n" +
            ("Content-Length: %d" % len(json.dumps(body, ensure_ascii=False,
                                                     separators=(",", ":")).encode())).encode()
            + b"\r\n\r\n" +
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())


def build_nlu_response(sid: str | bytes, payload: bytes) -> bytes:
    """Response for device after local NLU (self.postNLU replacement)."""
    s = sid.encode() if isinstance(sid, str) else sid
    return (b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: W510\r\n"
            b"RS: GeLdJ\r\n"
            b"PN: ry\r\n"
            b"SID: " + s + b"\r\n"
            b"Content-Type: application/json\r\n" +
            ("Content-Length: %d" % len(payload)).encode() + b"\r\n"
            b"Connection: keep-alive\r\n\r\n" + payload)
