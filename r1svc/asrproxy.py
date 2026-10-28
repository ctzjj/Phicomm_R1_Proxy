""":8080 voice-link server: raw HTTP(TCP) proxy with cloud forwarding or
custom local NLU on final requests. Port of repo/go/internal/asr/server.go.
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import r1svc.config as cfgmod
import r1svc.media as media
import r1svc.protocol as proto
import r1svc.state as statemod


# ---------------- dial cache ----------------
_DNS_LOCK = threading.Lock()
_DNS_CACHE: dict[str, tuple[str, float]] = {}


def resolve_ipv4(host: str, dns_server: str, timeout: float = 3.0) -> str | None:
    """Minimal DNS A query (UDP, single question). Cached 5 min."""
    with _DNS_LOCK:
        hit = _DNS_CACHE.get(f"{host}@{dns_server}")
        if hit and time.time() - hit[1] < 300:
            return hit[0]
    try:
        sid = int(time.time()) & 0xFFFF
        dst, dst_port = dns_server, 53
        if dst.count(":") == 1 and dst.rsplit(":", 1)[1].isdigit():
            dst, _sep, dp = dst.rpartition(":")
            dst_port = int(dp)
        fam = socket.AF_INET6 if ":" in dst else socket.AF_INET
        qname = b"".join(
            bytes([len(p)]) + p.encode() for p in host.split(".")) + b"\x00"
        pkt = struct.pack(">HHHHHH", sid, 0x0100, 1, 0, 0, 0) + \
            qname + struct.pack(">HH", 1, 1)
        s = None
        try:
            s = socket.socket(fam, socket.SOCK_DGRAM)
            s.settimeout(timeout)
            s.sendto(pkt, (dst, dst_port))
            data, _ = s.recvfrom(4096)
        finally:
            if s:
                s.close()
        ancount = int.from_bytes(data[6:8], "big")
        off = 12 + len(qname) + 4
        for _ in range(ancount):
            while True:
                if data[off] == 0:
                    off += 1
                    break
                if data[off] & 0xC0 == 0xC0:
                    off += 2
                    break
                off += data[off] + 1
            typ = int.from_bytes(data[off:off + 2], "big")
            rdl = int.from_bytes(data[off + 8:off + 10], "big")
            off += 10
            if typ == 1 and rdl == 4:
                ip = ".".join(str(b) for b in data[off:off + 4])
                with _DNS_LOCK:
                    _DNS_CACHE[f"{host}@{dns_server}"] = (ip, time.time())
                return ip
            off += rdl
    except Exception:
        return None
    return None


_UPSTREAM_HOST = "asrv3.hivoice.cn"
_EXECUTOR = ThreadPoolExecutor(max_workers=16)


def _up_addr(rt: cfgmod.Runtime) -> tuple[str, int] | None:
    """Go 语义:upstream 显式配置优先;否则用 dns 解析 asrv3;失败返回 None(502),
    绝不回退系统解析(路由器 DNS 劫持会把流量指回本机 nginx 造成回环)。"""
    up = rt.get("upstream") or ""
    if up and ":" in up:
        h, _, p = up.rpartition(":")
        return h, int(p or 80)
    dns = rt.get("dns") or "223.5.5.5:53"
    ip = resolve_ipv4(_UPSTREAM_HOST, dns)
    if not ip:
        return None
    return ip, 80


_HDR_LEN = 1048576       # per-read chunk
_502_RAW = b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
_MAX_BODY = 32 * 1024 * 1024
_TIMEOUT = 60.0


# ---------------- header/body buffer reading ----------------
_FILTER_TE = re.compile(rb"(?i)Transfer-Encoding: *chunked")
_FILTER_CL = re.compile(rb"(?i)Content-Length: ([0-9]+)")


def _read_message(sock: socket.socket) -> tuple[bytes, bytes, bytes] | None:
    """1:1 port of asr/server.go readMessage: (raw, hdr, body) | None.

    chunked body: raw keeps the chunked frame verbatim; body is de-chunked.
    response without Content-Length reads until EOF; request without
    Content-Length has no body.
    """
    br = _SockBuf(sock)
    hdr = bytearray()
    while True:
        line = br.line()
        if not line:
            return None
        hdr += line
        if len(hdr) > _MAX_BODY:
            return None
        if hdr.endswith(b"\r\n\r\n"):
            break
    head = bytes(hdr[:-4])
    if _FILTER_TE.search(head):
        raw = bytearray(hdr)
        body = bytearray()
        while True:
            line = br.line()
            if not line:
                return None
            raw += line
            s = bytes(line).strip()
            i = s.find(b";")
            if i >= 0:
                s = s[:i]
            try:
                size = int(s, 16)
            except ValueError:
                return None
            if size == 0:
                while True:
                    tl = br.line()
                    if not tl:
                        return None
                    raw += tl
                    if bytes(tl).strip(b"\r\n") == b"":
                        return bytes(raw), head, bytes(body)
            if size > _MAX_BODY or len(raw) + size > _MAX_BODY:
                return None
            data = br.exact(size)
            if data is None:
                return None
            raw += data
            body += data
            crlf = br.exact(2)
            if crlf is None:
                return None
            raw += crlf
    m = _FILTER_CL.search(head)
    if m is None:
        if head.startswith(b"HTTP/"):
            rest = br.eof_rest(_MAX_BODY)
            return head + b"\r\n\r\n" + rest, head, rest
        return bytes(hdr), head, b""
    cl = int(m.group(1))
    if cl <= 0:
        return bytes(hdr), head, b""
    if cl > _MAX_BODY:
        return None
    data = br.exact(cl)
    if data is None:
        return None
    return head + b"\r\n\r\n" + data, head, data


class _SockBuf:
    """Minimal buffered line/exact reader over a blocking socket."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = bytearray()

    def _fill(self) -> bool:
        c = self.sock.recv(65536)
        if not c:
            return False
        self.buf += c
        return True

    def line(self) -> bytes:
        while True:
            i = self.buf.find(b"\n")
            if i >= 0:
                out = bytes(self.buf[:i + 1])
                del self.buf[:i + 1]
                return out
            if not self._fill():
                return b""

    def exact(self, n: int) -> bytes | None:
        while len(self.buf) < n:
            if not self._fill():
                return None
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def eof_rest(self, limit: int) -> bytes:
        out = bytes(self.buf)
        del self.buf[:]
        while len(out) <= limit:
            c = self.sock.recv(65536)
            if not c:
                break
            out += c
        return out


async def _read_message_async(reader):
    """1:1 port of Go readMessage: returns (raw, hdr, body) or (None,)*3."""
    hdr = bytearray()
    while True:
        line = await reader.readline()
        if not line:
            return None, None, None
        hdr += line
        if len(hdr) > _MAX_BODY:
            return None, None, None
        if hdr.endswith(b"\r\n\r\n"):
            break
    head = bytes(hdr[:-4])
    if _FILTER_TE.search(head):
        raw = bytearray(hdr)
        body = bytearray()
        while True:
            size_line = await reader.readline()
            if not size_line:
                return None, None, None
            raw += size_line
            s = size_line.strip()
            i = s.find(b";")
            if i >= 0:
                s = s[:i]
            try:
                size = int(s, 16)
            except ValueError:
                return None, None, None
            if size == 0:
                while True:
                    tl = await reader.readline()
                    if not tl:
                        return None, None, None
                    raw += tl
                    if tl.strip(b"\r\n") == b"":
                        return bytes(raw), head, bytes(body)
            if size > _MAX_BODY or len(raw) + size > _MAX_BODY:
                return None, None, None
            data = await reader.readexactly(size)
            raw += data
            body += data
            crlf = await reader.readexactly(2)
            raw += crlf
    m = _FILTER_CL.search(head)
    if m is None:
        if head.startswith(b"HTTP/"):
            rest = bytearray()
            while True:
                c = await reader.read(_HDR_LEN)
                if not c:
                    break
                rest += c
                if len(rest) > _MAX_BODY:
                    break
            return head + b"\r\n\r\n" + bytes(rest), head, bytes(rest)
        return bytes(hdr), head, b""
    cl = int(m.group(1))
    if cl <= 0:
        return bytes(hdr), head, b""
    if cl > _MAX_BODY:
        return None, None, None
    data = await reader.readexactly(cl)
    return head + b"\r\n\r\n" + data, head, data


# ---------------- response wrapper ----------------
FILTER = (b"Connection:", b"Keep-Alive:", b"Content-Length:", b"Transfer-Encoding:")


def header_value(hdr: bytes, name: str) -> str | None:
    for line in hdr.split(b"\r\n"):
        if line.lower().startswith(name.lower().encode() + b":"):
            return line.partition(b":")[2].strip().decode("latin-1")
    return None


def is_media_request(hdr: bytes) -> bool:
    first = hdr.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    return ("GET " in first or "HEAD " in first) and (" /media?" in " " + first + " ")


def client_response(raw: bytes | None, body: bytes = b"",
                    http_status: int | None = None) -> bytes:
    """Rewrite cloud response raw into device response; CL recomputed."""
    if http_status == 502 or raw is None:
        return b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"
    idx = raw.find(b"\r\n\r\n")
    head_out = []
    for line in raw[:idx].split(b"\r\n"):
        if line.startswith(FILTER[0]) or line.startswith(FILTER[1]) or \
                line.startswith(FILTER[3]):
            continue
        if re.match(b"(?i)Content-Length:", line):
            continue
        head_out.append(line)
    head_out.append(("Content-Length: %d" % len(body)).encode())
    return b"\r\n".join(head_out) + b"\r\n\r\n" + body


# ---------------- forward to cloud/original upstream ----------------
def forward_cloud(rt: cfgmod.Runtime, raw: bytes, timeout: float = 60.0) -> bytes | None:
    """Send the original request raw (chunked frame kept verbatim, 1:1 Go msg.raw),
    read one response message; return resp raw (head + body may be chunked)."""
    addr = _up_addr(rt)
    if addr is None:
        return None
    host, port = addr
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=10)
        sock.settimeout(timeout)
        sock.sendall(raw)
        resp = _read_message(sock)
        if resp is None:
            return None
        rraw, _rh, _rb = resp
        return rraw
    except Exception:
        return None
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


# ---------------- custom NLU resolution ----------------
def _custom_nlu(sid: str, ogg: bytes) -> tuple[bytes, str] | None:
    """Return (payload_bytes, sid) after local NLU; None on any failure."""
    try:
        import r1svc.nlu as nlu
        out = nlu.recognize_ogg(ogg)     # dict | str | None(约定见 nlu.py)
        if not isinstance(out, dict):
            t = str(out or "").strip()
            if not t:
                return None
            out = {"code": "ANSWER", "general": {"text": t, "type": "T"},
                   "asr_recongize": t}
        payload = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode()
        return payload, sid
    except Exception:
        import traceback
        from r1svc import state
        state.STATE.log("custom nlu: error " + "\n".join(traceback.format_exc().splitlines()[-6:]))
        return None


def handle_request(raw: bytes, hdr: bytes, body: bytes,
                   rt: cfgmod.Runtime, st: statemod.State) -> bytes:
    """Single request → response bytes (pure logic, testable)."""
    st.intercepts += 1
    dump_dir = rt.get("dump_dir")
    if dump_dir:
        n = st.next_dump_seq(dump_dir)
        sid = proto.audio_session_id(hdr) or ""
        st.dump("req", dump_dir, n, hdr, body, extra={"sid": sid})
    if is_media_request(hdr):
        return b"__MEDIA__"   # caller (serve) streams media itself

    is_final = proto.is_final_request(hdr, len(body))
    if rt.get("nlu_mode") == "custom" and is_final:
        sid = proto.audio_session_id(hdr)
        ogg = None
        if sid:
            n, ogg = st.cap_finalize(sid)
        if ogg:
            got = _custom_nlu(sid or "", ogg)
            if got is not None:
                payload, _sid = got
                try:
                    body_dict = json.loads(payload.decode("utf-8"))
                except Exception:
                    body_dict = None
                mb = _try_music_overlay(body_dict, hdr, rt, st, dump_dir)
                if mb is not None:
                    return mb                 # music 用 W510 仿真头响应
                import os as _os
                delay = float(_os.environ.get("R1_NLU_DELAY_S", "0") or 0)
                if delay > 0:                 # 测设备容忍上限用的调试旋钮
                    st.log(f"custom nlu: artificial delay {delay:.0f}s")
                    time.sleep(delay)
                out = proto.build_nlu_response(sid or "", payload)
                if dump_dir:
                    st.dump("resp", dump_dir, st.next_dump_seq(dump_dir), out, b"")
                return out
            st.log("custom nlu: failed (falling back to cloud)")
    # capture for long-utterance auto split
    st.cap_add(hdr, body)
    resp = forward_cloud(rt, raw)
    if resp is None:
        return b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"
    if dump_dir:
        st.dump("resp", dump_dir, st.next_dump_seq(dump_dir),
                resp.split(b"\r\n\r\n")[0] + b"\r\n\r\n", _body_of(resp))
    parsed = proto.Parse(resp)
    if isinstance(parsed.Body, dict):
        mb = _try_music_overlay(parsed.Body, hdr, rt, st, dump_dir)
        if mb is not None:
            return mb
    return client_response(resp, _body_of(resp))


def _body_of(raw: bytes) -> bytes:
    idx = raw.find(b"\r\n\r\n")
    return raw[idx + 4:] if idx >= 0 else b""


def _try_music_overlay(body: dict[str, Any] | None, hdr: bytes,
                       rt: cfgmod.Runtime, st: statemod.State,
                       dump_dir: str | None) -> bytes | None:
    """Go 双路径:custom NLU 响应与云响应只要 music.IsMusic 即 overlay。
    广播电台是独立分类意图:原话命中本地电台表 → 直接回 broadcast 域,
    设备侧广播 SDK 自动开播;没命中才走音乐搜索。"""
    from r1svc import music, radio
    if not isinstance(body, dict):
        return None
    try:
        station = radio.match(str(body.get("text") or ""))
    except Exception as e:
        st.log(f"[radio] match failed: {e}")
        station = None
    if station:
        try:
            evaluated = radio.build_response(body, station, rt.get("media_base"))
            raw = json.dumps(evaluated, ensure_ascii=False,
                             separators=(",", ":")).encode()
            out = proto.build_nlu_response((proto.audio_session_id(hdr) or ""), raw)
            if dump_dir:
                st.dump("resp", dump_dir, st.next_dump_seq(dump_dir), out, b"")
            st.log(f"[radio] -> {station.get('name')}")
            return out
        except Exception as e:
            st.log(f"[radio] overlay failed: {e}")
    ism, kw = music.is_music(body)
    if not (ism and kw and rt.get("music_enabled", True)):
        return None
    try:
        items = music.search_all(kw, int(rt.get("music_limit", 20)))
        probed = music.probe_all(items, media._get_client(),
                                 timeout=float(rt.get("probe_timeout_s", 3.0)))
        evaluated = music.build_music_response(body, probed, rt.get("media_base"))
        raw = json.dumps(evaluated, ensure_ascii=False,
                         separators=(",", ":")).encode()
        out = proto.build_nlu_response((proto.audio_session_id(hdr) or ""), raw)
        if dump_dir:
            st.dump("resp", dump_dir, st.next_dump_seq(dump_dir), out, b"")
        return out
    except Exception as e:
        st.log(f"[music] overlay failed: {e}")
        return None


# ---------------- asyncio entrypoint ----------------
async def serve(rt: cfgmod.Runtime, st: statemod.State, host: str, port: int) -> None:
    server = await asyncio.start_server(
        lambda r, w: _conn(r, w, rt, st), host, port)
    statemod.STATE.log(f"[asr] listening on {host}:{port} mode={rt.get('nlu_mode')}")
    async with server:
        await server.serve_forever()
    # keep upstream import alive for type hints
    _ = cfgmod


async def _conn(reader, writer, rt: cfgmod.Runtime, st: statemod.State) -> None:
    loop = asyncio.get_running_loop()
    try:
        while True:
            raw, hdr, body = await _read_message_async(reader)
            if raw is None:
                return
            out = await loop.run_in_executor(
                _EXECUTOR,
                lambda: handle_request(raw, hdr, body, rt, st))
            if out == b"__MEDIA__":
                line = hdr.decode("latin-1", "replace")
                is_head = line.startswith("HEAD ")
                t0 = time.time()

                def fetch():
                    if is_head:
                        st, hd = media.fetch_upstream_head(
                            media.media_target(line), media.upstream_headers(line))
                        if st not in (200, 206):
                            # 直播源(蜻蜓等)拒绝 HEAD:GET 探头后立即关流
                            st, hd, resp = media.fetch_upstream(
                                media.media_target(line),
                                media.upstream_headers(line))
                            resp.close()
                        return st, hd, None
                    st, hd, resp = media.fetch_upstream(
                        media.media_target(line), media.upstream_headers(line))
                    return st, hd, resp

                try:
                    mstatus, mheaders, mresp = await loop.run_in_executor(
                        _EXECUTOR, fetch)
                except Exception as e:
                    st.log(f"[media] fetch error: {type(e).__name__} {e}")
                    writer.write(_502_RAW)
                    await writer.drain()
                    continue
                if mstatus not in (200, 206):
                    if mresp is not None:
                        try:
                            mresp.close()
                        except Exception:
                            pass
                    st.log(f"[media] upstream status {mstatus} -> 502")
                    writer.write(_502_RAW)
                    await writer.drain()
                    continue
                writer.write(media.build_client_response(mstatus, mheaders))
                await writer.drain()
                if is_head:
                    st.log(f"[media] HEAD {mstatus} {time.time()-t0:.1f}s")
                    continue
                total = 0
                try:
                    it = mresp.iter_raw()
                    while True:
                        chunk = await loop.run_in_executor(
                            _EXECUTOR, lambda: next(it, None))
                        if chunk is None:
                            break
                        if chunk:
                            total += len(chunk)
                            writer.write(chunk)
                            await writer.drain()
                except Exception as e:
                    st.log(f"[media] stream aborted at {total}B: "
                           f"{type(e).__name__} {e}")
                finally:
                    try:
                        mresp.close()
                    except Exception:
                        pass
                st.log(f"[media] {mstatus} streamed {total}B "
                       f"in {time.time()-t0:.1f}s")
                continue
            writer.write(out)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass
