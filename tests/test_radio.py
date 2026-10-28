# -*- coding: utf-8 -*-
import base64

from r1svc import radio


def test_match_freq_987_variants():
    st = radio.match("播放FM98.7广播")
    assert st and st["name"] == "私家车987"
    # 设备 asr 常见变体:f m 九八七广播
    st2 = radio.match("播放 f m 九八七广播")
    assert st2 and st2["qid"] == "1736"
    st3 = radio.match("我想听98.7")
    assert st3 and st3["freq"] == "98.7"


def test_match_name_and_generic_local_priority():
    st = radio.match("我想听中国之声")
    assert st and st["name"] == "中国之声"
    st2 = radio.match("播放福建交通广播")
    assert st2 and st2["qid"] == "1733"
    # 泛称"交通广播"没带城市 → 表内福建台排前,优先本地
    st3 = radio.match("来个交通广播")
    assert st3 and "交通" in st3["name"]


def test_match_no_hit_returns_none():
    assert radio.match("播放周杰伦的歌") is None
    assert radio.match("帮我放广播剧") is None
    assert radio.match("") is None
    assert radio.match("播放新闻") is None


def test_stations_file_valid():
    radio._STATIONS = None  # 强制重读
    stations = radio._stations()
    assert len(stations) >= 20
    assert all(s.get("url", "").startswith("http") for s in stations)
    assert any(s["qid"] == "1736" for s in stations)


def test_build_response_broadcast_contract():
    body = {"text": "播放FM98.7广播",
            "semantic": {"intent": {"name": "私家车987"}}}
    st = radio.match(body["text"])
    out = radio.build_response(body, st, "http://127.0.0.1:9000")
    assert out["service"] == "cn.yunzhisheng.broadcast"
    assert out["semantic"]["intent"]["station"] == "私家车987"
    res = out["data"]["result"]
    # 设备契约:rate64_ts_url 非空即自动开播
    assert res["rate64_ts_url"]
    url = res["rate64_ts_url"]
    assert url.startswith("http://127.0.0.1:9000/media?u=")
    enc = url.split("?u=", 1)[1]
    dec = base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4)).decode()
    assert dec == st["url"]
    assert res["title"] == "私家车987"
    # 设备端 Gson/fastjson 类型:source/channel_id/schedule_id 必须是 int,
    # 否则整个 NLU 反序列化失败(设备报"网络连接失败")
    assert res["source"] == 0 and isinstance(res["source"], int)
    assert res["schedule_id"] == 0 and isinstance(res["schedule_id"], int)
    assert res["channel_id"] == 1736 and isinstance(res["channel_id"], int)
    assert out["general"]["text"].startswith("正在为您播放")
    assert out["history"] == "cn.yunzhisheng.broadcast"
