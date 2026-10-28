# -*- coding: utf-8 -*-
import json
import pytest

import r1svc.nlu as nlu
from r1svc.asr_engine import qa_llm


def test_build_nlu_response_text_passthrough():
    out = nlu.build_nlu_response_block("SID-1", "几点了")
    assert out.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b'"code":"ANSWER"' in out
    assert b'"text":"\xe5\x87\xa0\xe7\x82\xb9\xe4\xba\x86"' in out


def test_recognize_missing_model_raises_hint(monkeypatch):
    # 固定把 ensure_models()=False 分支,避免单独触发真实加载
    monkeypatch.setattr(nlu, "ensure_models", lambda *a, **k: False)
    with pytest.raises(nlu.ModelMissing) as e:
        nlu.recognize_ogg(b"\x01\x00ab")
    assert "sherpa-onnx-sense-voice" in str(e.value)


def test_download_hint_contains_url_and_dir(capsys):
    urls, dirs = nlu.manual_download_hint()
    assert any(u.startswith("https://") for u in urls)
    assert any("sensevoice" in d.lower() for d in dirs)


# ---- chat / calendar 契约 ----

def _fake_slu(monkeypatch, domain):
    class S:
        def __call__(self, text):
            return {"domain": domain, "r1_nlu": {"service": "x", "code": "X",
                                                 "text": text, "asr_recongize": text,
                                                 "semantic": {"intent": {}}}}
    monkeypatch.setattr(nlu, "get_slu", lambda: S())
    monkeypatch.setattr(nlu, "decode_to_wav16k",
                        lambda b: __import__("numpy").zeros(16000, dtype="float32"))


def test_chat_domain_returns_answer_contract(monkeypatch):
    _fake_slu(monkeypatch, "chat")
    monkeypatch.setattr(nlu, "ensure_models", lambda *a, **k: True)
    monkeypatch.setattr(nlu, "asr_text", lambda x: "我肚子好饿啊")
    calls = []
    monkeypatch.setattr(qa_llm, "answer", lambda t: calls.append(t) or "吃点东西吧")
    out = nlu.recognize_ogg(b"\x01\x00ab")
    assert out["code"] == "ANSWER"
    assert out["general"]["text"] == "吃点东西吧"
    assert out["general"]["style"] == "HIGH_QUALITY"
    assert out["asr_recongize"] == "我肚子好饿啊"
    assert calls == ["我肚子好饿啊"]


def test_calendar_domain_local_clock_answer(monkeypatch):
    _fake_slu(monkeypatch, "calendar")
    monkeypatch.setattr(nlu, "ensure_models", lambda *a, **k: True)
    monkeypatch.setattr(nlu, "asr_text", lambda x: "几点了")
    out = nlu.recognize_ogg(b"\x01\x00ab")
    assert out["code"] == "ANSWER"
    assert out["general"]["style"] == "calendar"
    assert out["history"] == "cn.yunzhisheng.calendar"
    assert "当前时间" in out["general"]["text"]
    assert out["asr_recongize"] == "几点了"


def test_music_domain_keeps_r1_nlu_and_clears_dm(monkeypatch):
    _fake_slu(monkeypatch, "music_play")
    monkeypatch.setattr(nlu, "ensure_models", lambda *a, **k: True)
    monkeypatch.setattr(nlu, "asr_text", lambda x: "我想听周杰伦的歌")
    cleared = []
    monkeypatch.setattr(qa_llm, "clear_history", lambda: cleared.append(1))
    out = nlu.recognize_ogg(b"\x01\x00ab")
    assert out["code"] != "ANSWER" or "music" in json.dumps(out)
    assert cleared == [1]


def test_empty_asr_returns_canned_answer(monkeypatch):
    monkeypatch.setattr(nlu, "ensure_models", lambda *a, **k: True)
    monkeypatch.setattr(nlu, "decode_to_wav16k",
                        lambda b: __import__("numpy").zeros(16000, dtype="float32"))
    monkeypatch.setattr(nlu, "asr_text", lambda x: "")
    out = nlu.recognize_ogg(b"\x01\x00ab")
    assert out["code"] == "ANSWER"
    assert out["general"]["text"] == nlu.CHAT_EMPTY

# ---- qa_llm DM ----

def test_dm_clear_and_size():
    qa_llm._hist.clear()
    for i in range(10):
        qa_llm._hist.append({"role": "user", "content": f"q{i}"})
        qa_llm._hist.append({"role": "assistant", "content": f"a{i}"})
    assert len(qa_llm._hist) == qa_llm.DM_MAX_TURNS * 2
    assert qa_llm._hist[-1]["content"] == "a9"
    qa_llm.clear_history()
    assert len(qa_llm._hist) == 0


def test_reminder_gets_confirmation_text(monkeypatch):
    class S:
        def __call__(self, text):
            return {"domain": "reminder", "r1_nlu": {
                "service": "cn.yunzhisheng.reminder", "code": "REMINDER_SET",
                "text": text, "asr_recongize": text,
                "semantic": {"intent": {"content": text,
                                        "dateTime": "十分钟", "repeatType": "OFF"}}}}
    monkeypatch.setattr(nlu, "get_slu", lambda: S())
    monkeypatch.setattr(nlu, "ensure_models", lambda *a, **k: True)
    monkeypatch.setattr(nlu, "decode_to_wav16k",
                        lambda b: __import__("numpy").zeros(16000, dtype="float32"))
    monkeypatch.setattr(nlu, "asr_text", lambda x: "十分钟后提醒我去买车")
    out = nlu.recognize_ogg(b"\x01\x00ab")
    assert out["code"] == "REMINDER_SET"
    assert out["general"]["text"] == "好的，十分钟后提醒您"


def test_dm_fallback_when_load_fails(monkeypatch):
    monkeypatch.setattr(qa_llm, "_enabled", True)
    monkeypatch.setattr(qa_llm, "_api", "")
    monkeypatch.setattr(qa_llm, "_load_ok", False)
    monkeypatch.setattr(qa_llm, "_load", lambda log=None: False)
    assert qa_llm.answer("给我讲个笑话") == qa_llm.CHAT_UNAVAILABLE


def test_set_api_uses_llama_and_unloads_builtin(monkeypatch):
    qa_llm._hist.clear()
    qa_llm._model = object()
    qa_llm._tok = object()
    qa_llm._load_ok = True
    qa_llm.set_api("http://127.0.0.1:8080")
    assert qa_llm._model is None and not qa_llm._load_ok  # 内置模型已卸载
    assert qa_llm._api_url() == "http://127.0.0.1:8080/v1/chat/completions"
    seen = {}

    def fake_msg(messages, tools=None, temp=0.7, **k):
        seen["n"] = len(messages)
        seen["tools"] = tools
        return {"role": "assistant", "content": "好的呀"}

    monkeypatch.setattr(qa_llm, "_enabled", True)
    monkeypatch.setattr(qa_llm, "_http_msg", fake_msg)
    assert qa_llm.answer("给我讲个笑话") == "好的呀"
    assert seen["n"] == 2  # system + user
    qa_llm.set_api("http://h:1/v1/chat/completions")
    assert qa_llm._api_url() == "http://h:1/v1/chat/completions"
    qa_llm.set_api("")


# ---- models.ensure_files 手动提示 ----

def test_ensure_files_failure_logs_manual_hint(tmp_path, capsys):
    import r1svc.models as models
    ok = models.ensure_files(tmp_path / "m", "http://127.0.0.1:9/x",
                             ["a.json"], "https://modelscope.cn/models/X", None)
    assert not ok
    assert not (tmp_path / "m" / "a.json").exists()
