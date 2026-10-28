import json

from r1svc import config


MIN = {
    "listen_asr": "127.0.0.1:8080",
    "listen_api": "127.0.0.1:9000",
    "listen_bind": "0.0.0.0:19999",
    "upstream": "",
    "dns": "223.5.5.5:53",
    "media_base": "http://asrv3.hivoice.cn",
    "nlu_mode": "cloud",
}


def test_defaults_shape():
    c = config.Config.model_validate(config.DEFAULTS)
    assert c.listen_asr == "127.0.0.1:8080"
    assert c.listen_api == "127.0.0.1:9000"
    assert c.listen_bind == "0.0.0.0:19999"
    assert c.media_base == "http://asrv3.hivoice.cn"
    assert c.nlu_mode == "cloud"
    assert c.llm_api == ""
    assert c.web_search is False
    assert c.dns == "223.5.5.5:53"
    # 上游空字符串默认表示走 DNS
    assert c.upstream.endswith("asrv3.hivoice.cn") or c.upstream == ""
    assert c.dump_dir == str(config.ROOT / "dump_raw")
    assert c.audio_dir == str(config.ROOT / "dump_audio")


def test_normalize_nlu_mode():
    assert config.Config.model_validate({**MIN, "nlu_mode": "external"}).nlu_mode == "custom"
    assert config.Config.model_validate({**MIN, "nlu_mode": "default"}).nlu_mode == "cloud"


def test_load_creates_and_roundtrip(tmp_path):
    p = tmp_path / "nested" / "config.json"
    c = config.load(p)
    assert json.loads(p.read_text(encoding="utf-8"))["nlu_mode"] == "cloud"
    c2 = config.Config.model_validate({**config.DEFAULTS, "nlu_mode": "custom"})
    config.save(p, c2)
    c3 = config.load(p)
    assert c3.nlu_mode == "custom"


def test_runtime_set_get_hot(tmp_path):
    p = tmp_path / "config.json"
    config.load(p)
    view = config.Runtime(config.Config.model_validate(config.DEFAULTS), p)
    view.update({"nlu_mode": "custom", "media_base": "http://x/"})
    got = view.snapshot()
    assert got["nlu_mode"] == "custom"
    assert got["media_base"] == "http://x/"
    assert json.loads(p.read_text(encoding="utf-8"))["nlu_mode"] == "custom"
    # 未知键被忽略
    view.update({"nope": 1})
    assert "nope" not in view.snapshot()
