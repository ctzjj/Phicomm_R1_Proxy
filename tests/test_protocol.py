import struct

from r1svc import protocol


def test_audio_session_id():
    hdr = b"POST /trafficRouter/cs HTTP/1.1\r\nHost: x\r\nP: aBc[SID-1]\r\n\r\n"
    assert protocol.audio_session_id(hdr) == "SID-1"
    # 无括号 → None
    hdr2 = b"POST /cs HTTP/1.1\r\nP: plain\r\n\r\n"
    assert protocol.audio_session_id(hdr2) is None
    hdr3 = b"GET / HTTP/1.1\r\n\r\n"
    assert protocol.audio_session_id(hdr3) is None


def test_is_final_request_case_sensitive():
    yes = b"POST /cs HTTP/1.1\r\nTP: replay\r\nContent-Length: 0\r\n"
    assert protocol.is_final_request(yes, 0) is True
    no = b"POST /cs HTTP/1.1\r\ntp: replay\r\nContent-Length: 0\r\n"
    assert protocol.is_final_request(no, 0) is False   # 区分大小写,同 Go
    # CL>0 非是 final
    part = b"POST /cs HTTP/1.1\r\nTP: x\r\nContent-Length: 12\r\n"
    assert protocol.is_final_request(part, 12) is False


def test_parse_chunks_le_u16():
    body = b"\x05\x00hello" + b"\x03\x00abc"
    assert protocol.parse_chunks(body) == [b"hello", b"abc"]
    # len 0 即 停止(空 body)
    assert protocol.parse_chunks(b"") == []
    # 截断报文
    assert protocol.parse_chunks(b"\xff\xffonly2") == []


def _parse_pages(b: bytes):
    pages = []
    i = 0
    while i + 4 <= len(b):
        assert b[i:i+4] == b"OggS", b[i:i+4]
        segs = b[i + 26]
        total = 27 + segs
        segtable = b[i + 27: i + 27 + segs]
        payload = sum(segtable)
        page = b[i: i + total + payload]
        pages.append(page)
        i += total + payload
    return pages


def test_ogg_opus_structure_and_crc():
    pkts = [bytes([0xFC]) * (280 + k) for k in range(3)]
    data = protocol.ogg_opus(pkts)
    pages = _parse_pages(data)
    assert len(pages) == 3  # head, tags, one data page (3 pkts < 250)
    p0 = pages[0]
    serial = struct.unpack("<I", p0[14:18])[0]
    assert serial == 0x52314F50            # "R1OP"
    assert p0[5] & 0x02                     # BOS
    seg0 = p0[27: 27 + p0[26]]
    off = 27 + p0[26]
    head = p0[off: off + seg0[0]]
    assert head[:8] == b"OpusHead"
    ver, ch = head[8], head[9]
    preskip, sr = head[10:12], head[12:16]
    assert ver == 1 and ch == 1
    assert struct.unpack("<H", preskip)[0] == 312
    assert struct.unpack("<I", sr)[0] == 16000
    # CRC 反算合适性
    for p in pages:
        chk = struct.unpack("<I", p[22:26])[0]
        zeros = bytearray(p)
        zeros[22:26] = b"\x00\x00\x00\x00"
        assert protocol.ogg_crc(zeros) == chk
    # 最后页 EOS
    assert pages[-1][5] & 0x04


def _ref_crc(data: bytes) -> int:
    import ctypes
    poly = 0x04C11DB7
    def crc32_ref(b):
        crc = 0
        for byte in b:
            crc ^= byte << 24
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
        return crc
    return crc32_ref(data)


def test_crc_reference_table_equivalence():
    for b in (b"", b"OggS", bytes(range(256)), b"r1tool" * 40):
        assert protocol.ogg_crc(b) == _ref_crc(b)


def test_build_nlu_response_headers():
    out = protocol.build_nlu_response(b"SID-9", b'{"code":"x"}')
    assert out.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Type: W510\r\nRS: GeLdJ\r\nPN: ry\r\nSID: SID-9\r\n" in out
    assert b"Content-Type: application/json\r\n" in out
    assert b"Content-Length: 12\r\n" in out
    assert out.endswith(b"Connection: keep-alive\r\n\r\n" + b'{"code":"x"}')


def test_fake_resp_wraps_body():
    raw = protocol.fake_resp_raw(b"S1", {"a": 1})
    assert b"Content-Type: W510\r\n" in raw
    assert raw.endswith(b'{"a":1}')


def test_parse_and_build_roundtrip_html_off():
    raw = b"HTTP/1.1 200 OK\r\nX-A: 1\r\n\r\n" + '{"t":"<>"}'.encode()
    d = protocol.Parse(raw)
    assert d.Body == {"t": "<>"}
    out = protocol.Data(d.Headers_Raw, d.Body).Build()
    # ensure_ascii=False → 不做 \u003e HTML 转义
    assert b"<\\u003e" not in out and b"<>" in out
    # Content-Length 重算
    cl = [l for l in out.split(b"\r\n") if l.lower().startswith(b"content-length")]
    assert cl == [b"Content-Length: 10"]
