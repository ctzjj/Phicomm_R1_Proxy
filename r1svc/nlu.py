"""Local NLU pipeline: ogg → wav16k → SenseVoice → LexiconFix → ERNIE SLU → r1_nlu.

对应老 app.py /nlu 完全一致:返回 dict(r1_nlu 字段 + text + asr_recongize)。
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ASR_ROOT = ROOT / "asr-slu"
MODEL_DIR = ASR_ROOT / "models" / "sensevoice"

MANUAL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
              "asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2")

CHAT_EMPTY = "对不起,我不太明白你的意思,再说一遍"

_LEX_FIXER: Any = None


class ModelMissing(RuntimeError):
    pass


def manual_download_hint() -> tuple[list[str], list[str]]:
    files = "model.int8.onnx", "tokens.txt"
    missing = [f for f in files if not (MODEL_DIR / f).exists()]
    dirs = str(MODEL_DIR)
    return ([MANUAL_URL], [dirs, "missing:", ", ".join(missing) or "(all present)"])


def ensure_models(state_log=None) -> bool:
    import r1svc.models as models
    ok = models.ensure(MODEL_DIR, MANUAL_URL, state_log)
    return ok


def _lexicon_fixer() -> Any:
    """Same semantics as app.py: LexiconFix only if LEXICON_FILE set (cached)."""
    global _LEX_FIXER
    if _LEX_FIXER is None:
        from r1svc.asr_engine import lexicon_fix
        p = os.environ.get("LEXICON_FILE", "")
        _LEX_FIXER = lexicon_fix.LexiconFix(p) if p else False
    return _LEX_FIXER


def decode_to_wav16k(data: bytes) -> "Any":
    """bytes(任意容器)→ float32 ndarray 16k mono;失败回退 ffmpeg。"""
    import soundfile as sf
    import numpy as np
    from scipy.signal import resample_poly
    try:
        pcm, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception:
        import subprocess
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        try:
            tmp.write(data)
        finally:
            tmp.close()
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp.name, "-ac", "1", "-ar", "16000",
                 "-f", "wav", "-"], capture_output=True)
            pcm, sr = sf.read(io.BytesIO(r.stdout), dtype="float32", always_2d=True)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    x = pcm.mean(axis=1)
    if sr != 16000:
        import math
        g = math.gcd(int(sr), 16000)
        x = resample_poly(x, 16000 // g, int(sr) // g).astype("float32")
    return np.ascontiguousarray(x, dtype="float32")


def asr_text(x: Any) -> str:
    """输入 float32 16k array → 文本;内部持 asr_lock(调用方无需再锁)。"""
    from r1svc.asr_engine import sherpa_asr
    import numpy as np
    a = sherpa_asr.get_asr()
    if a is None:
        raise ModelMissing("asr not ready")
    if not isinstance(x, np.ndarray):
        raise TypeError("asr_text expects float32 ndarray from decode_to_wav16k")
    with _get_lock():
        t = sherpa_asr.transcribe(np.ascontiguousarray(x, dtype="float32"))
    t = (t or "").strip()
    f = _lexicon_fixer()
    return f.fix(t) if f else t


def _get_lock():
    import r1svc.asr_engine.sherpa_asr as _sa
    return _sa.asr_lock()


def get_slu():
    from r1svc.asr_engine import slu_ernie
    return slu_ernie.get_slu()


def _strip_end(t: str) -> str:
    return t.rstrip("。.!！？? ")


def _answer_shell(match_type: str, source: str, history: str,
                  confidence: float = 0.99) -> dict:
    """照抄真云 ANSWER 响应字段(不含 audioUrl:实测设备从不拉取)。"""
    import random
    import string
    import time as _t
    return {
        "code": "ANSWER",
        "matchType": match_type,
        "originIntent": {"nluSlotInfos": []},
        "confidence": confidence,
        "modelIntentClsScore": {},
        "history": history,
        "source": source,
        "uniCarRet": {"result": {}, "returnCode": 609,
                      "message": "http post reuqest error"},
        "asr_recongize": "",
        "rc": 0,
        "general": {},
        "returnCode": 0,
        "retTag": "nlu",
        "service": "cn.yunzhisheng.chat",
        "nluProcessTime": "0",
        "text": "",
        "responseId": "".join(random.choices("0123456789abcdef", k=32)),
        "_t0": _t.time(),
    }


def _finalize_shell(r: dict, text: str) -> dict:
    import time as _t
    r["asr_recongize"] = text
    r["text"] = _strip_end(text)
    r["nluProcessTime"] = str(int((_t.time() - r.pop("_t0")) * 1000))
    return r


def _calendar_answer() -> dict:
    """calendar 域(真云 0753 同型):general{style:calendar,text,type:T}。"""
    import datetime
    now = datetime.datetime.now()
    r = _answer_shell("ONLY_NEED_WORD_STRING_TEMPLATE", "nlu",
                      "cn.yunzhisheng.calendar")
    r["general"] = {"style": "calendar",
                    "text": now.strftime("当前时间：%H点%M分"), "type": "T"}
    return r


def _chat_answer(text: str, asr: str) -> dict:
    """chat 域(真云 0734 同型):general{mood,style:HIGH_QUALITY,text},无 type。
    LLM 关闭/失败/空结果时不兜底:不带 general,设备走自己的无 answer 流程。"""
    from r1svc.asr_engine import qa_llm
    r = _answer_shell("NOT_UNDERSTAND", "krc", "cn.yunzhisheng.chat",
                      confidence=1.0)
    ans = qa_llm.answer(text)
    if ans:
        r["general"] = {"mood": "中性", "style": "HIGH_QUALITY", "text": ans}
    return _finalize_shell(r, asr or text)


def _confirm_text(resp: dict) -> str:
    """给无 general.text 的本地指令响应补一句播报(真云也都会带模板文本)。"""
    code = str(resp.get("code") or "")
    sem = (resp.get("semantic") or {}).get("intent") or {}
    if code == "REMINDER_SET":
        content = str(sem.get("content") or "").strip()
        iso = str(sem.get("dateTime") or "").strip()
        try:
            import datetime as _dt
            at = _dt.datetime.strptime(iso, "%Y-%m-%d %H:%M:%S")
            when = at.strftime("%Y年%m月%d日%H点%M分%S秒")
            return f"我会在{when}提醒您{content}。" if content else f"我会在{when}提醒您。"
        except Exception:
            return f"好的，{iso}后提醒您" if iso else "好的，提醒已设置"
    if code == "ALARM_SET":
        return "好的，闹钟已设置"
    if code == "ALARM_SET_TIMING":
        return "好的，倒计时已开始"
    if code == "SETTING_EXEC":
        ops = sem.get("operations") or []
        for op in ops:
            if isinstance(op, dict) and str(op.get("operands") or "") == "ATTR_WAKEUP_WORD":
                return ""   # 唤醒词误分类(如「讲个笑话」),交给闲聊兜底
        return "好的"
    if code in ("SETTING_EXEC_MP", "SETTING_IOT"):
        return "好的"
    if code == "ANSWER":
        return "好的，记下了"
    return ""


def _envelope(resp: dict, t0: float) -> dict:
    """补齐真云 nlu 响应公共字段(设备按这些字段路由播报)。"""
    import random
    import time as _t
    import uuid
    svc = str(resp.get("service") or "")
    resp.setdefault("rc", 0)
    resp.setdefault("retTag", "nlu")
    resp.setdefault("source", "nlu")
    resp.setdefault("matchType", "ONLY_NEED_WORD_STRING_TEMPLATE")
    resp.setdefault("originIntent", {"nluSlotInfos": []})
    resp.setdefault("confidence", 0.99)
    resp.setdefault("modelIntentClsScore", {})
    resp.setdefault("history", svc)
    resp.setdefault("sessionId", str(uuid.uuid4()))
    resp.setdefault("uniCarRet", {"result": {}, "returnCode": 609,
                                  "message": "http post reuqest error"})
    resp.setdefault("returnCode", 0)
    resp.setdefault("responseId",
                    "".join(random.choices("0123456789abcdef", k=32)))
    resp.setdefault("taskName", "query")
    resp.setdefault("nluProcessTime", str(int((_t.time() - t0) * 1000)))
    if not str(resp.get("text") or "").strip():
        resp["text"] = resp.get("asr_recongize") or ""
    return resp


def recognize_ogg(data: bytes) -> Any:
    """Full local NLU;chat 域返回设备契约(code ANSWER+general),其余 r1_nlu。"""
    if not ensure_models():
        raise ModelMissing(
            f"missing SenseVoice model files; manual download {MANUAL_URL}; dir {MODEL_DIR}")
    import time as _t
    t0 = _t.time()
    x = decode_to_wav16k(data)
    text = (asr_text(x) or "").strip()
    if not text:
        r = _answer_shell("NOT_UNDERSTAND", "krc", "cn.yunzhisheng.chat",
                          confidence=1.0)
        r["general"] = {"mood": "中性", "style": "HIGH_QUALITY", "text": CHAT_EMPTY}
        return _finalize_shell(r, "")
    try:
        out = get_slu()(text)
    except Exception:
        import paddle
        paddle.disable_static()   # 防御:paddlenlp 偶发残留 static 模式导致 Tensor.numpy() 失败
        out = get_slu()(text)
    domain = out.get("domain") if isinstance(out, dict) else None
    if domain == "calendar":
        return _finalize_shell(_calendar_answer(), text)
    if domain in (None, "chat"):
        return _chat_answer(text, text)
    from r1svc.asr_engine import qa_llm
    print(f"[nlu] dm cleared (domain={domain} text={text[:20]})", flush=True)
    qa_llm.clear_history()
    resp = (out.get("r1_nlu") or out) if isinstance(out, dict) else out
    if not isinstance(resp, dict):
        resp = {"code": "cn.yunzhisheng.chat"}
    g = resp.get("general") if isinstance(resp.get("general"), dict) else {}
    if not str(g.get("text") or "").strip():
        txt = _confirm_text(resp)
        if txt:
            resp["general"] = {"actionAble": "true", "quitDialog": "true",
                               "text": txt, "type": "T"}
        elif resp.get("code") == "SETTING_EXEC":
            # 其余 SETTING_EXEC 空文本(如「讲个笑话」误判成唤醒词指令)→ 闲聊兜底
            return _chat_answer(text, text)
    resp.setdefault("text", text or CHAT_EMPTY)
    resp.setdefault("asr_recongize", text or "")
    sem = resp.get("semantic") if isinstance(resp.get("semantic"), dict) else None
    if resp.get("code") == "REMINDER_SET" and sem is not None:
        txt = str((resp.get("general") or {}).get("text") or "")
        if txt:
            sem.setdefault("normalHeader", txt)
    return _envelope(resp, t0)


def build_nlu_response_block(sid: str, text: str) -> bytes:
    """Used by tests; mirror of asrproxy custom-nlu wrap for pure text."""
    payload = json.dumps({"code": "ANSWER", "general": {"text": text, "type": "T"},
                          "asr_recongize": text},
                         ensure_ascii=False, separators=(",", ":")).encode()
    from r1svc import protocol
    return protocol.build_nlu_response(sid, payload)
