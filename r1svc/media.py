"""/media?u= base64url passthrough proxy(GET/HEAD,Range 支持)。"""
from __future__ import annotations

import base64
import threading
import urllib.parse
from typing import Any

import httpx


_UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def media_target(line: str) -> str | None:
    """Return upstream URL if the request is a valid local media request."""
    req = line.split("\r\n", 1)[0]
    parts = req.split(" ")
    if len(parts) < 2:
        return None
    method, target = parts[0], parts[1]
    if method not in ("GET", "HEAD"):
        return None
    if not target.startswith("/media"):
        return None
    q = urllib.parse.urlsplit("http://x" + target)
    u = urllib.parse.parse_qs(q.query).get("u", [""])[0]
    if not u:
        return None
    try:
        raw = base64.urlsafe_b64decode(u + "=" * (-len(u) % 4))
        url = raw.decode("utf-8", "strict")
    except Exception:
        return None
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    return url


def upstream_headers(line: str) -> dict[str, str]:
    headers = {"User-Agent": _UA_CHROME, "Referer": "http://music.163.com/",
               "Accept": "*/*", "Connection": "close"}
    for raw in line.split("\r\n")[1:]:
        k, _, v = raw.partition(":")
        k = k.strip()
        if k.lower() == "range" and v.strip():
            headers["Range"] = v.strip()
    return headers


def build_client_response(status: int, headers: dict[str, Any]) -> bytes:
    line = "HTTP/1.1 206 Partial Content\r\n" if status == 206 else "HTTP/1.1 200 OK\r\n"
    out = line
    out += "Accept-Ranges: bytes\r\n"
    out += "Content-Type: audio/mpeg\r\n"
    cl = headers.get("Content-Length")
    if cl:
        out += f"Content-Length: {cl}\r\n"
    cr = headers.get("Content-Range")
    if status == 206 and cr:
        out += f"Content-Range: {cr}\r\n"
    out += "Cache-Control: public, max-age=3600\r\n"
    out += "Connection: close\r\n"
    return out.encode("latin-1") + b"\r\n"


def fetch_upstream(target: str, headers: dict[str, str],
                   timeout: float = 30.0) -> tuple[int, dict[str, str], Any]:
    """Return (status, resp_headers, stream_ctx|None). stream via httpx streaming."""
    client = _get_client()
    req = client.build_request("GET", target, headers=headers)
    resp = client.send(req, stream=True)
    return resp.status_code, dict(resp.headers), resp


def fetch_upstream_head(target: str, headers: dict[str, str],
                        timeout: float = 30.0) -> tuple[int, dict[str, str]]:
    client = _get_client()
    req = client.build_request("HEAD", target, headers=headers)
    resp = client.send(req, stream=True)
    resp.close()
    return resp.status_code, dict(resp.headers)


_CL = threading.local()


def _get_client() -> httpx.Client:
    c = getattr(_CL, "client", None)
    if c is None:
        c = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0),
                         follow_redirects=True, http2=False)
        _CL.client = c
    return c


def serve_media_send(w, line: str, chunk_sink=None) -> None:
    """Full(GET) media serve. w: writer with .write/.drain."""
    target = media_target(line)
    if target is None:
        w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    try:
        status, headers, resp = fetch_upstream(target, upstream_headers(line))
    except Exception:
        w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    if status not in (200, 206):
        resp.close()
        w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    head = build_client_response(status, headers)
    w.write(head)
    for chunk in resp.iter_raw():
        if not chunk:
            continue
        if chunk_sink is not None:
            chunk_sink(chunk)
        w.write(chunk)
    resp.close()


def serve_media_head(w, line: str) -> None:
    target = media_target(line)
    if target is None:
        w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    headers = upstream_headers(line)
    status, hdrs = 0, {}
    try:
        status, hdrs = fetch_upstream_head(target, headers)
    except Exception:
        status = 0
    if status not in (200, 206):
        # 部分直播源(如蜻蜓)拒绝 HEAD:用 GET 探一次头,立即关流
        try:
            status, hdrs, resp = fetch_upstream(target, headers)
            resp.close()
        except Exception:
            status = 0
            hdrs = {}
    if status not in (200, 206):
        w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    head = build_client_response(status, hdrs)
    w.write(head)
