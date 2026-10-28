"""One-command entrypoint for r1svc (CPU only).

  python start.py                       # data\config.json
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import r1svc.config as cfgmod            # noqa: E402
from r1svc.state import State, STATE      # noqa: E402


def load_asr_background(rt: cfgmod.Runtime, log) -> None:
    try:
        import r1svc.asr_engine.sherpa_asr as sa
        sa.load_asr()
    except Exception as e:
        log(f"[asr] load failed: {e}")
    # torch/paddle 顺序:先 sherpa 再 torch 再 paddle(slu)
    try:
        import torch  # noqa: F401
    except Exception as _e:
        log(f"[llm] torch import failed: {_e}")
    # warm the full local NLU chain once so the first live request is fast:
    # SenseVoice real inference + utc-nano intent + uie-nano slots (first
    # ONNX run pays graph optimization, which can cost seconds on CPU).
    try:
        import time as _t
        import numpy as np
        import r1svc.nlu as nlu
        t0 = _t.time()
        text = nlu.asr_text(np.zeros(16000, dtype="float32"))  # 1s silence;asr_text 内部自持锁
        slu = nlu.get_slu()
        if slu is not None:
            slu("我想听周杰伦的歌")   # warms utc + uie (non-chat intent path)
        t_nlu = _t.time() - t0
        from r1svc.asr_engine import qa_llm
        qa_llm.set_enabled(bool(rt.get("llm_chat", True)))
        qa_llm.set_api(rt.get("llm_api") or "")  # 空=内部模型;填了=外部接口
        qa_llm.set_web_search(bool(rt.get("web_search")))
        t1 = _t.time()
        llm_ok = qa_llm.warmup(log)
        t_llm = _t.time() - t1
        if llm_ok:
            ans = qa_llm.answer("你好")
            log(f"[llm] warmup answer: {ans[:40]}")
        log(f"[nlu] warmup done in {t_nlu:.1f}s + llm {t_llm:.1f}s (asr text={text!r})")
    except Exception as e:
        log(f"[nlu] warmup failed: {e}")


def _uvicorn_thread(fastapi_app, host: str, port: int):
    import uvicorn
    conf = uvicorn.Config(fastapi_app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(conf)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server, t


def main() -> int:
    ap = argparse.ArgumentParser(description="r1svc single-process voice service")
    ap.add_argument("--config", default=str(ROOT / "data" / "config.json"))
    args = ap.parse_args()
    cfg_path = Path(args.config)
    runtime = cfgmod.Runtime(cfgmod.load(cfg_path), cfg_path)

    use_state = STATE
    import r1svc.state as statemod
    statemod.STATE = use_state

    def log(*parts):
        use_state.log(*parts)
        print(" ".join(str(p) for p in parts), flush=True)

    # models download hint / auto fetch(后台线程)
    from r1svc.nlu import ensure_models
    threading.Thread(target=lambda: ensure_models(log), daemon=True).start()

    # ASR background load
    threading.Thread(target=load_asr_background, args=(runtime, log), daemon=True).start()

    # bind :19999
    from r1svc import bindsvc
    bh, _, bp = runtime["listen_bind"].rpartition(":")
    _uvicorn_thread(bindsvc.serve(runtime.get("bind_log") or None), bh, int(bp))

    # api/webui :9000
    from r1svc import webui
    ah, _, ap_ = runtime["listen_api"].rpartition(":")
    _uvicorn_thread(webui.build(runtime), ah, int(ap_))

    # asr protocol :8080(主线程,asyncio)
    from r1svc import asrproxy
    h, _, p = runtime["listen_asr"].rpartition(":")
    log("[start] r1svc up: asr=%s api=%s bind=%s" % (
        runtime["listen_asr"], runtime["listen_api"], runtime["listen_bind"]))
    try:
        asyncio.run(asrproxy.serve(runtime, use_state, h, int(p)))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log("[start] asr proxy exited: %r" % e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
