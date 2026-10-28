"""aios-home bind service: /getUserInfo → {"status":"0"};fallback JSON. Port of bind/server.go."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


def app(log_path: Path | None) -> FastAPI:
    a = FastAPI(title="r1svc-bind")
    lock = threading.Lock()

    def log(req: Request, body: bytes) -> None:
        if log_path is None or not isinstance(log_path, Path):
            return
        p = log_path
        body_snip = body[:4000].decode("utf-8", "replace") or ""
        line = (f"{datetime.now().strftime('%Y/%m/%d %H:%M:%S')} {req.method} "
                f"{req.url.path}?{req.url.query}\n{body_snip}\n\n")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with lock, p.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass
        from r1svc import state
        state.STATE.log(f"[bind] {req.method} {req.url.path}")

    @a.api_route("/getUserInfo", methods=["GET", "POST"])
    async def get_user_info(req: Request) -> JSONResponse:
        body = await req.body()
        log(req, body)
        return JSONResponse({"status": "0"})

    @a.api_route("/favicon.ico", methods=["GET"])
    async def favicon(req: Request) -> Response:
        log(req, b"")
        return Response(status_code=204)

    @a.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"])
    async def catch_all(req: Request) -> JSONResponse:
        body = await req.body()
        log(req, body)
        return JSONResponse({"status": "0", "code": 0, "message": "ok"})

    return a


def serve(log_path: Path | str | None) -> FastAPI:
    return app(Path(log_path) if log_path else None)
