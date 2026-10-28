import base64

import r1svc.media as media


def test_media_target_decode():
    url = "http://m10.music.126.net/260/x.mp3"
    enc = base64.urlsafe_b64encode(url.encode()).rstrip(b"=").decode()
    line = f"GET /media?u={enc} HTTP/1.1\r\nRange: bytes=0-2047\r\n".encode()
    assert media.media_target(line.decode("latin-1")) == url


def test_media_target_schema_check():
    enc = base64.urlsafe_b64encode(b"ftp://bad/path").rstrip(b"=").decode()
    line = f"GET /media?u={enc} HTTP/1.1\r\n".encode()
    assert media.media_target(line.decode("latin-1")) is None
    assert media.media_target("GET /media HTTP/1.1\r\n") is None
    assert media.media_target("POST /media?u=x HTTP/1.1\r\n") is None   # 只 GET/HEAD
    enc2 = base64.urlsafe_b64encode(b"http://h/x.mp3").rstrip(b"=").decode()
    assert media.media_target(f"HEAD /media?u={enc2} HTTP/1.1\r\n") is not None


def test_upstream_request_headers_inject():
    url = "http://m10.music.126.net/x.mp3"
    enc = base64.urlsafe_b64encode(url.encode()).rstrip(b"=").decode()
    line = f"GET /media?u={enc} HTTP/1.1\r\nRange: bytes=0-2047\r\n".encode()
    target = media.media_target(line.decode("latin-1"))
    h = media.upstream_headers(line.decode("latin-1"))
    assert h["Range"] == "bytes=0-2047"
    assert "Chrome/120" in h["User-Agent"]
    assert h.get("Referer") == "http://music.163.com/"


def test_build_client_response_200_and_206():
    from r1svc.media import build_client_response
    b = build_client_response(200, {"Content-Length": 1000, "Content-Type": "audio/mp4"})
    assert b.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Type: audio/mpeg\r\n" in b
    assert b"Content-Length: 1000\r\n" in b
    assert b"Accept-Ranges: bytes\r\n" in b
    assert b"Cache-Control: public, max-age=3600\r\n" in b
    assert b.endswith(b"Connection: close\r\n\r\n")
    assert b"x-nos-" not in b.lower()
    assert b"Content-Disposition" not in b
    b2 = build_client_response(206, {"Content-Range": "bytes 0-2047/800000",
                                     "Content-Length": 2048})
    assert b2.startswith(b"HTTP/1.1 206 Partial Content\r\n")
    assert b2.find(b"Content-Range: bytes 0-2047/800000") > 0


def test_serve_media_head_falls_back_to_get(monkeypatch):
    class W:
        def __init__(self):
            self.buf = b''
        def write(self, b):
            self.buf += b

    class Resp:
        closed = False
        def close(self):
            type(self).closed = True

    calls = {}

    def fake_head(target, headers, timeout=30.0):
        calls['head'] = target
        return 400, {}

    def fake_get(target, headers, timeout=30.0):
        calls['get'] = target
        return 200, {'Content-Length': '123'}, Resp()

    monkeypatch.setattr(media, 'fetch_upstream_head', fake_head)
    monkeypatch.setattr(media, 'fetch_upstream', fake_get)
    enc = base64.urlsafe_b64encode(b'https://lhttp.qingting.fm/live/1736/64k.mp3').rstrip(b'=').decode()
    line = f'HEAD /media?u={enc} HTTP/1.1' + chr(13) + chr(10)
    w = W()
    media.serve_media_head(w, line)
    assert calls.get('get')
    assert Resp.closed
    assert w.buf.startswith(b'HTTP/1.1 200 OK')
    assert b'Content-Length: 123' in w.buf
