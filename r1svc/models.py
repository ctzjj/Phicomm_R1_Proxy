"""Model download helper: ModelScope first, fallback mirrors; manual hint on failure."""
from __future__ import annotations

import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Callable

import httpx

_TIMEOUT = httpx.Timeout(900.0, connect=30.0)


def _download_file(url: str, dst: Path, log=None) -> bool:
    try:
        tmp = dst.with_suffix(dst.suffix + ".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=_TIMEOUT) as r:
            if r.status_code != 200:
                if log:
                    log(f"[models] {url} -> HTTP {r.status_code}")
                return False
            done = 0
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if log and done % (100 << 20) < (1 << 20):
                        log(f"[models] {dst.name}: {done >> 20}MB")
        if done == 0:
            return False
        tmp.replace(dst)
        return True
    except Exception as e:
        if log:
            log(f"[models] {url} error: {e}")
        return False


def ensure_files(model_dir: Path, base_url: str, files: list[str],
                 manual_page: str, log=None) -> bool:
    """Direct per-file download: {base_url}/{name} -> model_dir/name."""
    missing = [f for f in files if not (model_dir / f).exists() or (model_dir / f).stat().st_size == 0]
    if not missing:
        return True
    if log:
        log(f"[models] missing {len(missing)}/{len(files)}: {missing}")
    model_dir.mkdir(parents=True, exist_ok=True)
    for name in missing:
        if not _download_file(f"{base_url.rstrip('/')}/{name}", model_dir / name, log):
            _manual_hint(manual_page, model_dir, missing, log)
            return False
    if log:
        log(f"[models] {model_dir.name} downloaded OK")
    return True


def _manual_hint(manual_page: str, model_dir: Path, missing: list[str], log=None):
    if log:
        log(f"[models] 自动下载失败。请手动下载: {manual_page}")
        log(f"[models] 缺失文件 {missing} 放到目录: {model_dir}")


def _from_tarbz2(url: str, model_dir: Path, need: list[str], log=None) -> bool:
    try:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td) / "m.tar.bz2"
            with httpx.stream("GET", url, follow_redirects=True, timeout=_TIMEOUT) as r:
                if r.status_code != 200:
                    if log:
                        log(f"[models] {url} -> HTTP {r.status_code}")
                    return False
                with t.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            with tarfile.open(t, "r:bz2") as tf:
                for m in tf.getmembers():
                    b = Path(m.name).name
                    if b in need:
                        with tf.extractfile(m) as src, (model_dir / b).open("wb") as dst:
                            shutil.copyfileobj(src, dst)
        return all((model_dir / f).exists() for f in need)
    except Exception as e:
        if log:
            log(f"[models] {url} error: {e}")
        return False


# ---- SenseVoice -----------------------------------------------------------
SV_MS_BASE = ("https://modelscope.cn/models/pengzhendong/"
              "sherpa-onnx-sense-voice-zh-en-ja-ko-yue/resolve/master")
SV_GITHUB = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2")
SV_FILES = ["model.int8.onnx", "tokens.txt"]


def ensure(model_dir: Path, manual_url: str, log=None) -> bool:
    """SenseVoice: ModelScope per-file first, then GitHub tar.bz2, then manual hint."""
    missing = [f for f in SV_FILES if not (model_dir / f).exists()]
    if not missing:
        return True
    if log:
        log(f"[models] sensevoice missing: {missing}")
    model_dir.mkdir(parents=True, exist_ok=True)
    if all(_download_file(f"{SV_MS_BASE}/{f}", model_dir / f, log) for f in missing):
        if log:
            log("[models] sensevoice (modelscope) downloaded OK")
        return True
    if log:
        log("[models] modelscope failed, trying github tar.bz2 ...")
    if _from_tarbz2(SV_GITHUB, model_dir, SV_FILES, log):
        if log:
            log("[models] sensevoice (github) downloaded OK")
        return True
    _manual_hint(f"{SV_MS_BASE}/  (备用 {manual_url})", model_dir, missing, log)
    return False
