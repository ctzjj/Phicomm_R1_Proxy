from r1svc import asrproxy
from r1svc.config import Runtime
from r1svc.config import DEFAULTS, Config


def _rt(**kw):
    c = Config.model_validate({**DEFAULTS, **kw})
    return Runtime(c, "unused.json")


def test_header_value_scans_raw():
    hdr = b"POST / HTTP/1.1\r\nRange: bytes=0-99\r\n\r\n"
    assert asrproxy.header_value(hdr, "Range") == "bytes=0-99"
    assert asrproxy.header_value(hdr, "Nope") is None


def test_is_media_request():
    assert asrproxy.is_media_request(b"GET /media?u=abc HTTP/1.1\r\n\r\n")
    assert asrproxy.is_media_request(b"HEAD /media?u=abc HTTP/1.1\r\n\r\n")
    assert not asrproxy.is_media_request(b"GET / HTTP/1.1\r\n\r\n")


def test_client_resp_from_cloud_headers_filter():
    raw = (b"HTTP/1.1 200 OK\r\n"
           b"Server: nginx\r\n"
           b"Connection: keep-alive\r\n"
           b"Transfer-Encoding: chunked\r\n"
           b"X-A: 1\r\n\r\n")
    out = asrproxy.client_response(raw, b"payload", http_status=None)
    assert out.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Server: nginx\r\n" in out
    assert b"X-A: 1\r\n" in out
    assert b"Connection:" not in out
    assert b"Transfer-Encoding:" not in out
    assert out.endswith(b"\r\n\r\npayload")
    assert b"Content-Length: 7\r\n" in out


def test_502():
    assert asrproxy.client_response(None, b"", http_status=502) == \
        b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"


def test_zone_split_request_line():
    hdr = b"GET /media?u=MQ HTTP/1.1\r\nRange: bytes=0-1\r\n\r\n"
    assert asrproxy.header_value(hdr, "Range") == "bytes=0-1"
    line, _ = hdr.split(b"\r\n", 1)
    assert line.startswith(b"GET ")


# ---------------- chunked 1:1 readMessage port ----------------

import asyncio
import io
import socket
import threading


class _FakeReader:
    def __init__(self, data: bytes):
        self.bio = io.BytesIO(data)

    async def read(self, n=-1):
        return self.bio.read(n)

    async def readline(self):
        return self.bio.readline()

    async def readexactly(self, n):
        d = self.bio.read(n)
        if len(d) < n:
            raise asyncio.IncompleteReadError(d, n)
        return d


def test_read_async_chunked_request():
    req = (b"POST /trafficRouter/cs HTTP/1.1\r\n"
           b"Transfer-Encoding: chunked\r\n"
           b"Content-Type: audio/ogg\r\n"
           b"P: [s1]\r\n\r\n"
           b"4\r\nab\xcd\x00\r\n"
           b"3;ext=1\r\nxyz\r\n"
           b"0\r\n\r\n")
    raw, hdr, body = asyncio.run(asrproxy._read_message_async(_FakeReader(req)))
    assert body == b"ab\xcd\x00xyz"           # de-chunked
    assert raw.endswith(b"4\r\nab\xcd\x00\r\n3;ext=1\r\nxyz\r\n0\r\n\r\n")
    assert b"Transfer-Encoding: chunked" in hdr
    assert b"P: [s1]" in hdr


def test_read_async_cl_request():
    req = b"POST /x HTTP/1.1\r\nContent-Length: 4\r\nP: [s2]\r\n\r\nABCD"
    raw, hdr, body = asyncio.run(asrproxy._read_message_async(_FakeReader(req)))
    assert body == b"ABCD"
    assert raw == req[:-4] + b"ABCD"


def test_read_async_request_without_cl_no_body():
    req = b"HEAD /media?u=1 HTTP/1.1\r\nHost: x\r\n\r\n"
    raw, hdr, body = asyncio.run(asrproxy._read_message_async(_FakeReader(req)))
    assert body == b"" and raw == req


def test_read_async_response_without_cl_reads_to_eof():
    resp = b"HTTP/1.1 200 OK\r\nServer: go\r\n\r\nstream-payload"
    raw, hdr, body = asyncio.run(asrproxy._read_message_async(_FakeReader(resp)))
    assert hdr.startswith(b"HTTP/1.1 200")
    assert body == b"stream-payload"


def test_read_sync_chunked_response():
    resp = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"5\r\nhello\r\n0\r\n\r\n")

    class _S:
        def __init__(self, data):
            self.bio = io.BytesIO(data)

        def recv(self, n):
            return self.bio.read(n)

    raw, hdr, body = asrproxy._read_message(_S(resp))
    assert body == b"hello"
    assert raw.endswith(b"5\r\nhello\r\n0\r\n\r\n")
