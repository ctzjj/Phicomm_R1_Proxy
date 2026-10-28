"""Runtime singletons: log ring, capture sessions, dump writer."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


DUMP_DIR_HINT: Path | None = None   # tests may monkeypatch


def _ts() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


class _Sess:
    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.pkts: list[bytes] = []
        self.at = time.time()
        self.seq = 0


class State:
    def __init__(self, log_buf: int = 800) -> None:
        self._lock = threading.RLock()   # 重入:finalize/log 嵌套时避免自锁
        self._logs: list[dict[str, Any]] = []
        self._log_capacity = log_buf
        self._seq = 0
        self._dump_seq = 0
        self._sessions: dict[str, _Sess] = {}
        self._scount: dict[str, int] = {}   # sid → utterance round count
        self.utterances = 0
        self.intercepts = 0      # final requests handled
        self.start_monotonic = time.time()

    # ---------- logging ----------
    def log(self, *parts: Any) -> None:
        with self._lock:
            self._seq += 1
            self._logs.append({
                "seq": self._seq,
                "t": _ts(),
                "msg": " ".join(str(p) for p in parts),
            })
            if len(self._logs) > self._log_capacity:
                del self._logs[: len(self._logs) - self._log_capacity]

    def logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return self._logs[-limit:]

    def next_seq(self) -> int:
        with self._lock:
            return self._seq

    # ---------- capture protocol sessions ----------
    def cap_add(self, hdr: bytes, body: bytes, chunk_parse=None) -> None:
        """chunk_parse: callable(body)->list[bytes]; default protocol.parse_chunks."""
        h = hdr.decode("latin-1", "replace")
        if "/trafficRouter/cs" not in h:
            return
        if chunk_parse is None:
            from r1svc.protocol import parse_chunks
            chunk_parse = parse_chunks
        pkts = chunk_parse(body)
        sid = _sid_from_hdr(hdr)
        with self._lock:
            s = self._sessions.get(sid)
            if s is not None and (time.time() - s.at) > 3.0 and s.pkts and pkts:
                self._auto_finalize_locked(sid)
                s = None
            if not pkts:            # final request (empty body)
                if s is not None:
                    self._auto_finalize_locked(sid)
                return
            if s is None:
                s = _Sess(sid)
                s.seq = self._scount[sid] = self._scount.get(sid, 0) + 1
                self._sessions[sid] = s
            s.pkts.extend(pkts)
            s.at = time.time()

    def cap_finalize(self, sid: str, ogg_func=None) -> tuple[int, bytes | None]:
        """Explicit finalization (protocol final arrive). Returns (n_pkts, ogg)."""
        with self._lock:
            return self._finalize_locked(sid, ogg_func=ogg_func)

    def _auto_finalize_locked(self, sid: str) -> None:
        s = self._sessions.pop(sid, None)
        if s is None or not s.pkts:
            return
        self.utterances += 1
        self.log(f"[cap] auto finalize utterance utt{self.utterances:02d} sid={s.sid} pkts={len(s.pkts)}")

    def _finalize_locked(self, sid: str, ogg_func=None) -> tuple[int, bytes | None]:
        s = self._sessions.pop(sid, None)
        if s is None or not s.pkts:
            return (0, None)
        if ogg_func is None:
            from r1svc.protocol import ogg_opus
            ogg_func = ogg_opus
        self.utterances += 1
        return (len(s.pkts), ogg_func(tuple(s.pkts)))

    def cap_sweep(self) -> None:
        """Finalize sessions idle >3s (called by a 1s timer thread)."""
        with self._lock:
            stale = [sid for sid, s in self._sessions.items()
                     if s.pkts and (time.time() - s.at) > 3.0]
            for sid in stale:
                self._auto_finalize_locked(sid)

    def inspect(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sessions": len(self._sessions),
                "utterances": self.utterances,
                "intercepts": self.intercepts,
                "uptime_s": round(time.time() - self.start_monotonic, 1),
            }

    # ---------- dump(与 Go 抓包文件格式一致) ----------
    def dump(self, kind: str, dump_dir: Path | str, n: int, hdr: bytes,
             body: bytes, extra: dict[str, Any] | None = None) -> None:
        d = Path(dump_dir)
        d.mkdir(parents=True, exist_ok=True)
        tag = f"{n:04d}_{kind}"
        (d / (tag + ".hdr")).write_bytes(hdr)
        (d / (tag + ".bin")).write_bytes(body)
        h = hdr.decode("latin-1", "replace")
        first = h.split("\r\n", 1)[0]
        b32 = body[:32].hex() if body else ""
        extra_s = ""
        if extra:
            parts = []
            for k, v in extra.items():
                if v in (None, ""):
                    continue
                parts.append(f"{k} = {v}")
            extra_s = (" | " + " | ".join(parts)) if parts else ""
        text = (f"{_ts()} #{n:04d} {kind} {first}"
                f" | bytes={len(body)} first32={b32}{extra_s}\n")
        (d / (tag + ".txt")).write_text(text, encoding="utf-8")
        with (d / "index.log").open("a", encoding="utf-8") as f:
            f.write(text)
        self.log(f"[dump] {tag} bytes={len(body)}")

    def next_dump_seq(self, dump_dir: Path | str) -> int:
        d = Path(dump_dir)
        if DUMP_DIR_HINT is not None:
            d = DUMP_DIR_HINT
        with self._lock:
            n = 1
            if d.exists():
                import re
                mx = 0
                for p in d.glob("*_req.hdr"):
                    m = re.match(r"(\d{4})_req\.hdr", p.name)
                    if m:
                        mx = max(mx, int(m.group(1)))
                n = mx + 1
            self._dump_seq = max(self._dump_seq, n)
            return self._dump_seq


def _sid_from_hdr(hdr: bytes) -> str:
    from r1svc.protocol import audio_session_id
    return audio_session_id(hdr) or "unknown"


CAPTURE_HEADERS = (b"audio/ogg",)        # 与 Go 一致的内容头回放(文档级说明)
FAKE_HEADERS = (
    b"Content-Type: W510",
    b"RS: GeLdJ",
    b"PN: ry",
)

# 模块级:asrproxy/webui/bindsvc 直接 import 使用(不再于函数内创建分包)
STATE: State = State()
