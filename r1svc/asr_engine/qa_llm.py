"""小讯对话:聊天都走 LLM。默认内部模型(transformers,CPU);配置 llm_api 则走外部
llama.cpp 接口(r1svc 只调用,不集成不拉起)。开关关闭或服务异常时播报
"聊天服务异常,请稍后再试"。

- 内部模型:普通对话,无工具
- 外部接口:模型自选工具(web_search/news/history_today)
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path

MODEL_DIR = Path(__file__).parent / "MiniCPM-4.7"
MS_BASE = "https://www.modelscope.cn/models/MiniMaxAI/MiniCPM4-0.5B"
FILES = ["config.json", "model.safetensors.index.json", "generation_config.json",
         "tokenizer.json", "tokenizer_config.json", "model-00001-of-00002.safetensors",
         "model-00002-of-00002.safetensors"]
MS_PAGE = "https://www.modelscope.cn/models/MiniMaxAI/MiniCPM4-0.5B/files"

DM_TTL = 600.0
DM_MAX_TURNS = 6

CHAT_UNAVAILABLE = "聊天服务异常，请稍后再试"

_lock = threading.Lock()
_tok = None
_model = None
_load_ok = False
_api = ""          # 外部 llama.cpp OpenAI 兼容地址;空=内部模型
_enabled = False   # 对话开关(WebUI);关=聊天不出话术
_web_search = False

_hist: deque = deque(maxlen=DM_MAX_TURNS * 2)
_last_ts = 0.0


def set_api(url: str):
    """llm_api:外部 llama.cpp 地址(可带 /v1/chat/completions);空=内部模型。"""
    global _api
    _api = (url or "").strip()
    if _api:
        _release()  # 切外部接口时卸掉内置模型,省内存


def set_enabled(on: bool):
    global _enabled
    _enabled = bool(on)


def set_web_search(on: bool):
    global _web_search
    _web_search = bool(on)


def _release():
    global _model, _tok, _load_ok
    was = _model is not None
    _model = None
    _tok = None
    _load_ok = False
    if was:
        import gc
        gc.collect()
        _print("[llm] builtin model unloaded (free memory)")


def _api_url() -> str:
    if not _api:
        return ""
    if "chat/completions" in _api:
        return _api
    return _api.rstrip("/") + "/v1/chat/completions"


def _http_msg(messages, tools=None, temp: float = 0.7,
              max_tokens: int = 200) -> dict:
    import urllib.request
    payload = {"messages": messages, "max_tokens": max_tokens, "temperature": temp,
               "top_p": 0.9, "repeat_penalty": 1.1, "stream": False,
               "chat_template_kwargs": {"enable_thinking": False}}
    if tools:
        payload.update({"tools": tools, "tool_choice": "auto"})
    req = urllib.request.Request(_api_url(),
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"] or {}


def _http_chat(messages) -> str:
    return (_http_msg(messages).get("content") or "").strip()


def _load(log=None) -> bool:
    global _tok, _model, _load_ok
    if _api:
        _load_ok = True
        return True
    import r1svc.models as models
    if not models.ensure_files(MODEL_DIR, MS_BASE, FILES, MS_PAGE, log or _print):
        return False
    t0 = time.time()
    import torch
    n_thr = max(1, int((os.cpu_count() or 4) * 0.8))  # 按核数 ~80% 分配
    torch.set_num_threads(n_thr)
    from transformers import AutoModelForCausalLM, AutoTokenizer
    _tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    _model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_DIR), torch_dtype=torch.float32).cpu().eval()
    _load_ok = True
    (log or _print)(f"[llm] loaded on cpu in {time.time()-t0:.1f}s "
                    f"(threads={torch.get_num_threads()})")
    return True


def _print(msg: str):
    print(msg, flush=True)


def _clean(text: str) -> str:
    """去掉 emoji 等设备 TTS 处理不了的字符(带 emoji 会让音箱重启)。"""
    out = []
    for ch in text or "":
        o = ord(ch)
        if (0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or
                0xFE00 <= o <= 0xFE0F or 0x1F000 <= o or o == 0x200D):
            continue
        out.append(ch)
    return "".join(out).replace("\r", "").strip()


def _now_text() -> str:
    t = time.localtime()
    wd = "一二三四五六日"[t.tm_wday]
    return (time.strftime("%Y年%m月%d日 星期", t) + wd +
            time.strftime(" %H点%M分", t))


_SYSTEM = ("你是智能音箱小讯,像朋友聊天一样用中文口语回答,不超过100个字,"
           "自然接地气,不说英文,不用emoji,只用中文标点。"
           "现在是{now}。"
           "需要最新或实时信息时调用工具。特别是:问天气、新闻、价格、排名、最新消息,"
           "必须先调用web_search或news;问历史上的今天必须先调用history_today。"
           "不要凭记忆回答这类问题。闲聊、问候、常识、讲笑话直接回答。"
           "被问身份时只说你是小讯,绝对不要说任何模型名。")

_TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "搜索互联网上的最新或实时信息,自己给出中文搜索词",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "中文搜索词"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "news",
        "description": "获取今天的最新新闻头条,自带日期",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "history_today",
        "description": "查询历史上的今天发生的重大事件",
        "parameters": {"type": "object", "properties": {}}}},
]


def _run_tool(name: str, args: dict) -> str:
    from r1svc import web_search as w
    if name == "news":
        return w.format_results(w._news(8, 6.0))
    if name == "history_today":
        q = time.strftime("%m月%d日 ", time.localtime()) + "历史上的今天"
        return w.history_lines(w.search(q))
    if name == "web_search":
        return w.format_results(w.search((args or {}).get("query") or ""))
    return ""


def _generate(messages) -> str:
    ids = _tok.apply_chat_template(messages, add_generation_prompt=True,
                                   return_tensors="pt")
    out = _model.generate(ids, max_new_tokens=120, do_sample=True,
                          temperature=0.7, top_p=0.9, repetition_penalty=1.1,
                          pad_token_id=_tok.eos_token_id)
    return _tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)


def answer(text: str) -> str:
    """聊天统一入口;开关关、失败或空结果都播服务异常提示。"""
    global _last_ts
    text = (text or "").strip()
    if not text:
        return CHAT_UNAVAILABLE
    with _lock:
        if not _enabled:
            return CHAT_UNAVAILABLE
        try:
            if time.time() - _last_ts > DM_TTL:
                _hist.clear()
            messages = [{"role": "system",
                         "content": _SYSTEM.format(now=_now_text())},
                        *_hist, {"role": "user", "content": text}]
            _print(f"[llm] dm turns={len(_hist)//2} "
                   f"last_user={(next((h['content'] for h in reversed(_hist) if h['role'] == 'user'), '') or '')[:20]}")
            t0 = time.time()
            if _api:
                m = _http_msg(messages, tools=_TOOLS if _web_search else None,
                              temp=0.2)
                tcs = m.get("tool_calls") or []
                if tcs:
                    msgs = list(messages) + [{
                        "role": "assistant",
                        "content": m.get("content") or "",
                        "tool_calls": tcs}]
                    used = []
                    for tc in tcs[:2]:
                        fn = tc.get("function") or {}
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except Exception:
                            args = {}
                        try:
                            res = _run_tool(fn.get("name") or "", args)
                            used.append(fn.get("name") or "?")
                        except Exception as e:
                            _print(f"[llm] tool error: {e}")
                            res = ""
                        msgs.append({"role": "tool",
                                     "tool_call_id": tc.get("id") or "0",
                                     "content": res})
                    if used:
                        _print("[llm] tools: " + ", ".join(used))
                    m = _http_msg(msgs, temp=0.5, max_tokens=400)
                ans = _clean((m.get("content") or "").strip())
            else:
                if not _load_ok and not _load():
                    return CHAT_UNAVAILABLE
                ans = _clean(_generate(messages))
            _print(f"[llm] answer in {time.time()-t0:.1f}s: {ans[:60]}")
            if not ans:
                return CHAT_UNAVAILABLE
            _hist.append({"role": "user", "content": text})
            _hist.append({"role": "assistant", "content": ans})
            _last_ts = time.time()
            return ans
        except Exception as e:
            _print(f"[llm] error: {e}")
            return CHAT_UNAVAILABLE


def clear_history():
    with _lock:
        _hist.clear()


def warmup(log=None) -> bool:
    """开关开着就预热(外部接口 ping 一次 / 内部模型加载),失败仅记日志。"""
    if not _enabled:
        return True
    try:
        if _api:
            _http_chat([{"role": "user", "content": "你好"}])
        elif not _load(log):
            return False
    except Exception as e:
        (log or _print)(f"[llm] warmup fail: {e}")
        return False
    return True
