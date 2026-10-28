"""Config defaults, load/save and hot runtime view."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


ROOT = Path(__file__).resolve().parents[1]

DEFAULTS: dict[str, Any] = {
    "listen_asr": "127.0.0.1:8080",
    "listen_api": "127.0.0.1:9000",
    "listen_bind": "0.0.0.0:19999",
    # 上游地址:空=本地 DNS(asrv3.hivoice.cn);或 "host:port" 强制
    "upstream": "",
    "dns": "223.5.5.5:53",
    "media_base": "http://asrv3.hivoice.cn",
    "nlu_mode": "cloud",          # cloud | custom
    "nlu_key": "",
    "nlu_key_header": "Authorization",
    "dump_dir": str(ROOT / "dump_raw"),
    "audio_dir": str(ROOT / "dump_audio"),
    "bind_log": str(ROOT / "bind_access.log"),
    "log_buf": 800,
    "llm_chat": True,             # 对话开关:关=播报"聊天服务异常,请稍后再试"
    "llm_api": "",                # 外部 llama.cpp 地址;空=内置模型,填了=外部接口
    "web_search": False,          # 允许模型联网搜索(仅外部接口,可能拖慢响应)
    "music_enabled": True,
    "music_limit": 20,
    "probe_timeout_s": 3.0,
}


class Config(BaseModel):
    listen_asr: str = DEFAULTS["listen_asr"]
    listen_api: str = DEFAULTS["listen_api"]
    listen_bind: str = DEFAULTS["listen_bind"]
    upstream: str = ""
    dns: str = DEFAULTS["dns"]
    media_base: str = DEFAULTS["media_base"]
    nlu_mode: str = "cloud"
    nlu_key: str = ""
    nlu_key_header: str = "Authorization"
    dump_dir: str = DEFAULTS["dump_dir"]
    audio_dir: str = DEFAULTS["audio_dir"]
    bind_log: str = DEFAULTS["bind_log"]
    log_buf: int = 800
    llm_chat: bool = True
    llm_api: str = ""
    web_search: bool = False
    music_enabled: bool = True
    music_limit: int = Field(default=20, ge=1, le=50)
    probe_timeout_s: float = 3.0

    @field_validator("nlu_mode", mode="before")
    @classmethod
    def _norm_mode(cls, v: Any) -> str:
        s = str(v or "cloud").strip().lower()
        if s in ("custom", "external"):
            return "custom"
        return "cloud"


EDITABLE = frozenset(Config.model_fields.keys())


def load(path: Path | str) -> Config:
    p = Path(path)
    data: dict[str, Any] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    merged = {**DEFAULTS, **{k: v for k, v in (data or {}).items() if k in EDITABLE}}
    cfg = Config.model_validate(merged)
    if not p.exists():
        save(p, cfg)
    return cfg


def save(path: Path | str, cfg: Config) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Runtime:
    """process-wide hot view of the config; persists on update()."""

    def __init__(self, cfg: Config, path: Path | str) -> None:
        self._cfg = cfg
        self._path = Path(path)
        self._lock = threading.Lock()

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return getattr(self._cfg, key)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return getattr(self._cfg, key, default)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._cfg.model_dump()

    def update(self, patch: dict[str, Any]) -> None:
        with self._lock:
            for k, v in patch.items():
                if k not in EDITABLE:
                    continue
                setattr(self._cfg, k, Config.model_validate(
                    {**self._cfg.model_dump(), k: v}).__getattribute__(k))
            save(self._path, self._cfg)
