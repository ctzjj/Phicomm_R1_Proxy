import base64
import json

import httpx
import pytest

import r1svc.music as music


# ---------- netease helpers(mock) ----------
def _parse_form(request: httpx.Request) -> dict:
    raw = request.content.decode()
    out = {}
    for kv in raw.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            out[k] = v
    return out


def _netease_decrypt(hexs: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = bytes.fromhex(hexs)
    dec = Cipher(algorithms.AES(music._NETEASE_KEY), modes.ECB()).decryptor()
    return dec.update(raw)


def test_netease_search_shapes(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path + "|" + sorted(request.headers.keys()).__str__())
        if "forward" in request.url.path:
            body = dict(_parse_form(request))
            eparams = body["eparams"]
            assert eparams.isupper()
            pl = json.loads(_netease_decrypt(eparams).decode().rstrip("\x01\x02\x03\x04\x05" \
                            "\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"))
            if pl["url"] == "cloudsearch/pc":
                return httpx.Response(200, json=json.loads(
                    '{"code":200,"data":{"result":{"songs":[{"id":111,"name":"装了风的歌",'
                    '"duration":326414,"artists":[{"name":"周深"}],"album":{"name":"灯火"},'
                    '"privilege":{"fl":320000}}]}}}'))
            return httpx.Response(200, json={"code": 200, "data": [
                {"id": 111, "url": "http://m10.music.126.net/x.mp3", "br": 320000, "code": 200}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = music.netease_search("风的歌", 20, client)
    assert items[0]["title"] == "装了风的歌"
    assert items[0]["artist"] == "周深"
    assert items[0]["url"] == "http://m10.music.126.net/x.mp3"
    assert items[0]["duration"] == 326414
    assert items[0]["album_name"] == "灯火"
    assert items[0]["bitrate"] == 320


def test_netease_skips_no_privilege():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "forward" in request.url.path
        return httpx.Response(200, json=json.loads(
            '{"code":200,"data":{"result":{"songs":[{"id":111,"name":"x","duration":1,'
            '"artists":[{"name":"y"}],"album":{"name":"z"},"privilege":{"fl":0}}]}}}'))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = music.netease_search("kw", 20, client)
    assert items == []


# ---------- kuwo(mock) ----------
def test_kuwo_headers_and_parse(monkeypatch):
    seen_ua = []
    def handler(request: httpx.Request) -> httpx.Response:
        seen_ua.append((request.headers.get("user-agent", ""), request.headers.get("x-forwarded-for", "")))
        if "searchMusicBykeyWord" in request.url.path:
            return httpx.Response(200, json={"abslist": [
                {"MUSICRID": "MUSIC_555", "SONGNAME": "装了风的歌", "Artist": "周深",
                 "ALBUM": "灯火", "duration": "326", "formats": "", "bitSwitch": 1}]})
        return httpx.Response(200, json={"code": 200, "data": {
            "url": "http://kuwo/x.mp3", "bitrate": 320, "duration": 326}})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = music.kuwo_search("风的歌", 20, client)
    assert items and items[0]["url"] == "http://kuwo/x.mp3"
    assert items[0]["bitrate"] == 320
    assert seen_ua[0][1].startswith("114.") or seen_ua[0][1].startswith("223.") \
        or seen_ua[0][1].startswith("119.") or seen_ua[0][1].startswith("180.") \
        or seen_ua[0][1].startswith("117.")


def test_kuwo_retries_128k_on_fail():
    state = {"br": ["320kmp3", "128kmp3"]}
    def handler(request: httpx.Request) -> httpx.Response:
        if "searchMusicBykeyWord" in request.url.path:
            return httpx.Response(200, json={"abslist": [
                {"MUSICRID": "MUSIC_555", "SONGNAME": "s", "Artist": "a",
                 "ALBUM": "", "duration": "100", "bitSwitch": 1}]})
        br = state["br"].pop(0) if state["br"] else "128kmp3"
        if br == "320kmp3":
            return httpx.Response(200, json={"code": -1, "data": {}})
        return httpx.Response(200, json={"code": 200, "data": {"url": "http://kuwo/y.mp3",
                                                              "bitrate": 128, "duration": 100}})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = music.kuwo_search("kw", 20, client)
    assert items and items[0]["url"].endswith("y.mp3")   # 320 失败 → 128 重试成功


# ---------- migu(mock) ----------
def test_migu_search():
    def handler(request: httpx.Request) -> httpx.Response:
        if "search_all.do" in request.url.path:
            return httpx.Response(200, json={"code": "000000", "songResultData": {"result": [
                {"contentId": "9901", "name": "装了风的歌", "singers": [{"name": "周深"}],
                 "albums": [{"name": "灯火"}], "imgItems": [{"img": "http://m/i.jpg"}]}]}})
        return httpx.Response(200, json={"code": "000000",
                                         "data": {"url": "http://migu/z.mp3"}})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = music.migu_search("风的歌", 20, client)
    assert items[0]["url"] == "http://migu/z.mp3"
    assert items[0]["title"] == "装了风的歌"


# ---------- search_all / dedupe / probe ----------
def test_search_all_dedupe_better_rank():
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if "163.com" in host:
            return _netease_list([("同一歌", "歌手", "http://n/1.mp3", 320)])(request)
        if "kuwo.cn" in host:
            return _kuwo_list([("同一歌", "歌手", "http://k/1.mp3", 128)])(request)
        return _migu_list([("同一歌", "歌手", "http://m/1.mp3", 128)])(request)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = music.search_all("kw", 20, client_factory=lambda: client)
    assert len(items) == 1
    assert items[0]["url"] == "http://n/1.mp3"    # 多源 rank 谁高谁胜


def test_probe_filters_rank():
    good = b"ID3" + b"\x00" * 4096             # 头 + audio 骨
    def handler(request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("range", "")
        if "good" in request.url.path:
            cr = "bytes 0-2047/800000"
            return httpx.Response(206, headers={"Content-Range": cr, "Content-Length": "2048"},
                                  content=good[:2048])
        if "badsmall" in request.url.path:
            return httpx.Response(206, headers={"Content-Range": "bytes 0-2047/2000",
                                                "Content-Length": "2048"},
                                  content=b"ID3" + b"\x00" * 200)
        if "badjuke" in request.url.path:
            return httpx.Response(200, content=b"<!doctype html>" + b"\x00" * 4096,
                                  headers={"Content-Type": "text/html"})
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    items = [
        {"id": 1, "title": "good", "artist": "a", "url": "http://x/good",
         "bitrate": 320, "duration": 30000, "album_name": "", "img": "", "origin": "netease"},
        {"id": 2, "title": "badsmall", "artist": "a", "url": "http://x/badsmall",
         "bitrate": 320, "duration": 30000, "album_name": "", "img": "", "origin": "netease"},
        {"id": 3, "title": "badjuke", "artist": "a", "url": "http://x/badjuke",
         "bitrate": 320, "duration": 30000, "album_name": "", "img": "", "origin": "netease"},
    ]
    out = music.probe_all(items, client)
    assert [o["title"] for o in out] == ["good"]


def test_build_music_response_fields(monkeypatch):
    music.reset_test_state()
    body = {"semantic": {"intent": {"artist": "风的歌", "keyword": "我想听风歌入的歌",
                                    "song": "风的歌"}},
            "code": "SEARCH_CATEGORY", "text": "我想听风歌入的歌"}
    items = [{"id": 7863476, "title": "装了风的花，藏在寓言深处", "artist": "周深",
              "album_name": "灯火", "img": "http://p2/i.jpg", "url": "http://song.mp3",
              "duration": 326414, "bitrate": 320, "size": 0, "origin": "netease"}]
    resp = music.build_music_response(body, items, "http://asrv3.hivoice.cn")
    assert resp["code"] == "SEARCH_CATEGORY"
    assert resp["history"] == "cn.yunzhisheng.music"
    assert resp["service"] == "cn.yunzhisheng.music"
    assert resp["retTag"] == "nlu"
    assert resp["rc"] == 0
    assert resp["returnCode"] == 0
    assert resp["uniCarRet"] == {"result": {}, "returnCode": 609,
                                 "message": "aios-home.hivoice.cn"}
    assert resp["data"]["result"]["searchType"] == "common"
    assert resp["data"]["result"]["count"] == 1
    assert resp["data"]["result"]["pagesize"] == 20
    assert resp["data"]["result"]["page"] == "1"
    assert resp["data"]["result"]["source"] == 1
    assert resp["data"]["result"]["dataSourceName"] == "我的音乐"
    mi = resp["data"]["result"]["musicinfo"][0]
    assert mi["url"].startswith("http://asrv3.hivoice.cn/media?u=")
    enc = mi["url"].rsplit("u=", 1)[1]
    assert base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4)).decode() == "http://song.mp3"
    assert resp["general"]["text"] == "为您播放"
    assert resp["general"]["type"] == "T"
    assert resp["semantic"]["intent"] == body["semantic"]["intent"]
    assert "audioUrl" not in resp         # 全程字符串符 → 忽略
    assert resp["responseId"] == "e490d9576c5b438c8283a6e71cdba997"


def test_is_music_detection():
    for code, kw, hit, want_kw in [
        ("SEARCH_ARTIST", "风的歌", True, "风的歌"),
        ("SEARCH_CATEGORY", "", False, None),      # 无 keyword 不是音乐
        ("SEARCH_CATEGORY", "x", True, "x"),
        ("SEARCH_SONG", None, True, "风"),      # 用 text TextLikeRe 模糊提取
    ]:
        body = {"code": code,
                "semantic": {"intent": {k: v for k, v in
                                        (("keyword", kw), ("artist", kw), ("song", kw)) if v}},
                "text": "我想听风的歌"}
        is_m, kw2 = music.is_music(body)
        assert is_m is hit
        if hit:
            assert kw2 == want_kw


# helpers to fabricate per-source lists in dedupe tests
def _netease_list(triples):
    def handler(request: httpx.Request) -> httpx.Response:
        if "forward" in request.url.path:
            pl = json.loads(_netease_decrypt(_parse_form(request)["eparams"]).decode().rstrip(
                "\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"))
            if pl["url"] == "cloudsearch/pc":
                songs = [{"id": 7000 + i, "name": t, "duration": 300000 - i,
                          "artists": [{"name": a}], "album": {"name": "al"},
                          "privilege": {"fl": br}} for i, (t, a, _u, br) in enumerate(triples)]
                return httpx.Response(200, json={"code": 200, "data": {"result": {"songs": songs}}})
            return httpx.Response(200, json={"code": 200, "data": [
                {"id": 7000, "url": triples[0][2], "br": triples[0][3], "code": 200}]})
        i = 0
        return httpx.Response(200, json={"code": 200, "data": [
            {"id": 7000, "url": triples[0][2], "br": triples[0][3], "code": 200}]})
    return handler


def _kuwo_list(triples):   # same shape, kuwo host decides
    def handler(request: httpx.Request) -> httpx.Response:
        if "searchMusicBykeyWord" in request.url.path:
            return httpx.Response(200, json={"abslist": [
                {"MUSICRID": "MUSIC_%d" % (8000 + i), "SONGNAME": t, "Artist": a,
                 "ALBUM": "al", "duration": "300", "bitSwitch": 1}
                for i, (t, a, _u, _br) in enumerate(triples)]})
        return httpx.Response(200, json={"code": 200, "data": {"url": triples[0][2],
                                                               "bitrate": triples[0][3],
                                                               "duration": 300}})
    return handler


def _migu_list(triples):
    def handler(request: httpx.Request) -> httpx.Response:
        if "search_all.do" in request.url.path:
            return httpx.Response(200, json={"code": "000000", "songResultData": {"result": [
                {"contentId": str(9000 + i), "name": t, "singers": [{"name": a}],
                 "albums": [{"name": "al"}], "imgItems": [{"img": "http://migu/i.jpg"}]}
                for i, (t, a, _u, _br) in enumerate(triples)]}})
        return httpx.Response(200, json={"code": "000000", "data": {"url": triples[0][2]}})
    return handler
