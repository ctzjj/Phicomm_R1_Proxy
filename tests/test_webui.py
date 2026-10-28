import json

import httpx
from fastapi.testclient import TestClient

from r1svc import webui
from r1svc.config import Config, DEFAULTS
from r1svc.config import Runtime


def test_status_json():
    rt = Runtime(Config.model_validate(DEFAULTS), "unused.json")
    app = webui.build(rt)
    c = TestClient(app)
    r = c.get("/api/status")
    assert r.status_code == 200
    j = r.json()
    assert "nlu_mode" in j and "llm_api" in j
    assert j["asr_ready"] in (True, False)
    assert "uptime_s" in j


def test_get_and_post_config(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    rt = Runtime(Config.model_validate(DEFAULTS), p)
    app = webui.build(rt)
    c = TestClient(app)
    r = c.get("/api/config")
    assert r.status_code == 200
    assert r.json()["nlu_mode"] == "cloud"
    r = c.post("/api/config", json={"nlu_mode": "custom", "llm_api": "http://127.0.0.1:9",
                                    "web_search": True})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    got = json.loads(p.read_text(encoding="utf-8"))
    assert got["nlu_mode"] == "custom" and got["llm_api"] == "http://127.0.0.1:9"
    assert got["web_search"] is True
    from r1svc.asr_engine import qa_llm
    assert qa_llm._web_search is True
    qa_llm.set_api("")  # 还原全局 LLM 后端
    qa_llm.set_web_search(False)
    # 未知键 → 400
    r = c.post("/api/config", json={"bogus": True})
    assert r.status_code in (400, 422)


def test_nlu_endpoint_with_stub(monkeypatch):
    rt = Runtime(Config.model_validate(DEFAULTS), "unused.json")
    app = webui.build(rt)

    def fake_rec(data: bytes):
        return {"code": "SEARCH_CATEGORY", "text": "我想听风的歌",
                "asr_recongize": "我想听风的歌",
                "semantic": {"intent": {"artist": "风的歌",
                                        "keyword": "我想听风的歌", "song": "风的歌"}}}
    import r1svc.nlu as n
    monkeypatch.setattr(n, "recognize_ogg", fake_rec)
    monkeypatch.setattr(webui, "nlu_recognize", fake_rec, raising=False)
    c = TestClient(app)
    r = c.post("/nlu", files={"file": ("utt.ogg", b"\x01\x00abc", "audio/ogg")})
    assert r.status_code == 200
    j = r.json()
    assert j["code"] == "SEARCH_CATEGORY"
    assert j["semantic"]["intent"]["keyword"].endswith("风的歌")


def test_logs_endpoint():
    rt = Runtime(Config.model_validate(DEFAULTS), "unused.json")
    app = webui.build(rt)
    c = TestClient(app)
    r = c.get("/logs")
    assert r.status_code == 200


def test_status_page_returns_html():
    rt = Runtime(Config.model_validate(DEFAULTS), "unused.json")
    app = webui.build(rt)
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200 and "r1svc" in r.text
