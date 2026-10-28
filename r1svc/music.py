"""Music search sources(ne/ku/migu)+ dedupe + probe + Format template.

Ported from repo/go/internal/music/*.go (1:1 对应),shape 按统一 dict schema。
"""
from __future__ import annotations

import base64
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx


# ---------------- 数据类型:源层条目一律用 dict(字段见各 *_search 返回) ----------------
# dict 字段约定(统一 schema):
#   id,title,artist,album_name,duration(ms),url,bitrate,size,origin,img

# ---------------- netease ----------------
_NETEASE_KEY = bytes.fromhex("7246674226682325323F5E6544673A51")
_UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _netease_encrypt(payload: dict[str, Any]) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(_NETEASE_KEY), modes.ECB()).encryptor()
    return enc.update(raw).hex().upper()


def netease_search(keyword: str, limit: int, client: httpx.Client) -> list[dict[str, Any]]:
    candidates = min(limit * 4, 50)
    payload = {"method": "POST", "url": "cloudsearch/pc",
               "params": {"s": keyword, "type": 1, "offset": 0, "limit": candidates}}
    form = {"eparams": _netease_encrypt(payload)}
    try:
        r = client.post("http://music.163.com/api/linux/forward", data=form,
                        headers={"User-Agent": _UA_CHROME, "Referer": "http://music.163.com"})
    except Exception as e:
        raise RuntimeError(f"netease search: {e}") from e
    if r.status_code != 200:
        raise RuntimeError(f"netease search: status {r.status_code}")
    try:
        j = r.json()
    except Exception as e:
        raise RuntimeError(f"netease search: bad json: {e}") from e
    songs = (j.get("data") or {}).get("result") or {}
    songs = songs.get("songs") or []
    out: list[dict[str, Any]] = []
    for s in songs:
        try:
            if int((((s.get("privilege") or {}).get("fl")) or 0)) <= 0:
                continue
            song_id = s.get("id")
            sp = {"method": "POST", "url": "/api/song/enhance/player/url",
                  "params": {"ids": [song_id], "br": 320000}}
            r2 = client.post("http://music.163.com/api/linux/forward",
                             data={"eparams": _netease_encrypt(sp)},
                             headers={"User-Agent": _UA_CHROME, "Referer": "http://music.163.com"})
            url = ""
            if r2.status_code == 200:
                d2 = r2.json().get("data") or []
                if isinstance(d2, list) and d2:
                    u = d2[0].get("url") or ""
                    if isinstance(u, str) and u.startswith("http"):
                        url = u
            artists = s.get("artists") or []
            out.append({
                "id": song_id, "title": s.get("name") or "", "artist": artists[0]["name"] if artists else "",
                "album_name": (s.get("album") or {}).get("name") or "", "duration": int(s.get("duration") or 0),
                "url": url, "bitrate": 320, "size": 0, "origin": "netease", "img": "",
            })
        except Exception:  # per-song resilience
            continue
    return out


# ---------------- kuwo ----------------
_KUWO_UA = _UA_CHROME
_KUWO_TOKEN = "ABCDEFGHIJKLMNOP"
_KUWO_XFF_POOL = ["114.114.114.114", "223.5.5.5", "119.29.29.29", "180.76.76.76", "117.50.10.10"]


def _kuwo_ln() -> tuple[str, str]:
    ip = random.choice(_KUWO_XFF_POOL)
    return ip, ip


def kuwo_search(keyword: str, limit: int, client: httpx.Client) -> list[dict[str, Any]]:
    xff, xri = _kuwo_ln()
    params = {
        "vipver": "1", "client": "kt", "ft": "music", "cluster": "0", "strategy": "2012",
        "encoding": "utf8", "rformat": "json", "mobi": "1", "issubtitle": "1",
        "show_copyright_off": "1", "pn": "0", "rn": str(limit), "all": keyword,
    }
    headers = {"User-Agent": _KUWO_UA, "Cookie": f"kw_token={_KUWO_TOKEN}",
               "X-Forwarded-For": xff, "X-Real-IP": xri,
               "Referer": "http://www.kuwo.cn/"}
    url = "http://www.kuwo.cn/search/searchMusicBykeyWord"
    try:
        r = client.get(url, params=params, headers=headers)
    except Exception as e:
        raise RuntimeError(f"kuwo search: {e}") from e
    if r.status_code != 200:
        raise RuntimeError(f"kuwo search: status {r.status_code}")
    try:
        j = r.json()
    except Exception as e:
        raise RuntimeError(f"kuwo search: bad json: {e}") from e
    rows = j.get("abslist") or []
    out = []
    for raw in rows:
        if raw.get("bitSwitch") == 0:
            continue
        rid = (raw.get("MUSICRID") or "").replace("MUSIC_", "")
        name = raw.get("SONGNAME") or ""
        if not rid or not name:
            continue
        import html as _h
        title = _h.unescape(name).strip()
        dur_s = int(raw.get("duration") or 0)
        item = {"origin": "kuwo", "id": int(rid) if rid.isdigit() else rid, "title": title,
                "artist": _h.unescape(raw.get("Artist") or ""), "album_name": _h.unescape(raw.get("ALBUM") or ""),
                "duration": dur_s * 1000, "url": "", "bitrate": 0, "size": 0, "img": ""}
        for br in ("320kmp3", "128kmp3"):
            u = _kuwo_get_url(client, headers, int(rid) if rid.isdigit() else rid, br)
            if u:
                item["url"] = u
                item["bitrate"] = 320 if br == "320kmp3" else 128
                break
        if item["url"]:
            out.append(item)
    return out


def _kuwo_get_url(client: httpx.Client, headers: dict[str, str], rid: int, br: str) -> str:
    user = f"user=C_APK_guanwang_{int(time.time() * 1e9)}{random.randint(0, 999999)}"
    u = ("http://mobi.kuwo.cn/mobi.s?f=web"
         "&source=kwplayercar_ar_6.0.0.9_B_jiakong_vh.apk"
         f"&from=PC&type=convert_url_with_sign&br={br}&rid={rid}&{user}")
    try:
        r = client.get(u, headers={**headers, "Referer": "http://kuwo.cn/"})
    except Exception:
        return ""
    if r.status_code != 200:
        return ""
    try:
        j = r.json()
    except Exception:
        return ""
    if str(j.get("code")) != "200":
        return ""
    data = j.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    return data.get("url") or ""


# ---------------- migu ----------------
_MIGU_UA = "Android_migu/7.41.13 okhttp/3.12.13"


def migu_search(keyword: str, limit: int, client: httpx.Client) -> list[dict[str, Any]]:
    params = {"ua": "Android_migu", "version": "5.0.1", "text": keyword,
              "pageNo": "1", "pageSize": str(limit)}
    search_switch = '{"song":1,"lyric":0,"website":0,"mv":0,"tag":0,"album":0,"folder":0,' \
                    '"singer":0,"songList":0,"topic":0,"ringTone":0,"collectedSong":1}'
    params["searchSwitch"] = search_switch
    headers = {"User-Agent": _MIGU_UA, "Referer": "http://m.migu.cn/",
               "channel": "0146832", "version": "7.41.13"}
    try:
        r = client.get("http://pd.musicapp.migu.cn/MIGUM2.0/v1.0/content/search_all.do",
                       params=params, headers=headers)
    except Exception as e:
        raise RuntimeError(f"migu search: {e}") from e
    if r.status_code != 200:
        raise RuntimeError(f"migu search: status {r.status_code}")
    try:
        j = r.json()
    except Exception as e:
        raise RuntimeError(f"migu search: bad json: {e}") from e
    rows = ((j.get("songResultData") or {}).get("result")) or []
    out = []
    for raw in rows:
        try:
            content_id = raw.get("contentId")
            name = raw.get("name") or ""
            if not content_id or not name:
                continue
            singers = raw.get("singers") or [{}]
            albums = raw.get("albums") or [{}]
            img_items = raw.get("imgItems") or [{}]
            url = _migu_get_url(client, headers, content_id)
            if not url:
                continue
            out.append({"origin": "migu", "id": content_id,
                        "title": name, "artist": singers[0].get("name") or "",
                        "album_name": albums[0].get("name") or "",
                        "duration": 0, "url": url, "bitrate": 128, "size": 0,
                        "img": img_items[0].get("img") or ""})
        except Exception:
            continue
    return out


def _migu_get_url(client: httpx.Client, headers: dict[str, str], cid: str) -> str:
    u = ("https://c.musicapp.migu.cn/MIGUM2.0/v2.1/content/listen-url"
         f"?netType=01&resourceType=2&contentId={cid}&toneFlag=PQ")
    try:
        r = client.get(u, headers=headers)
    except Exception:
        return ""
    try:
        return r.json().get("data", {}).get("url") or ""
    except Exception:
        return ""


# ---------------- search_all + dedupe ----------------
_RANK = {"netease": 3, "kuwo": 2}

NETEASE_HOST = "music.163.com"
KUWO_HOST = "www.kuwo.cn"
MIGU_HOST = "pd.musicapp.migu.cn"


def _song_key(title: str, artist: str) -> str:
    n = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return n(title) + "|" + n(artist)


_TEST_STATE: dict[str, Any] = {"probe_logs": []}


def reset_test_state() -> None:
    _TEST_STATE["probe_logs"].clear()


def _log_probe(msg: str) -> None:
    _TEST_STATE["probe_logs"].append(msg)


def search_all(keyword: str, limit: int, client_factory=None) -> list[dict[str, Any]]:
    """多源并发(每源 8s),dedupe by key,取 rank 高者。"""
    errors: list[str] = []
    results: dict[str, list[dict[str, Any]]] = {}
    lock = threading.Lock()

    def run(origin: str) -> None:
        fn = {"netease": netease_search, "kuwo": kuwo_search, "migu": migu_search}[origin]
        timeout = httpx.Timeout(8.0, connect=5.0)
        client = (client_factory or (lambda: httpx.Client(timeout=timeout, follow_redirects=True)))()
        try:
            lst = fn(keyword, limit, client)
            with lock:
                results[origin] = lst
        except Exception as e:
            with lock:
                errors.append(f"{origin}: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass

    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(run, origin) for origin in ("netease", "kuwo", "migu")]
        for f in futs:
            f.result()

    for e in errors:
        _log_probe(f"[music] source error — {e}")
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for origin in ("netease", "kuwo", "migu"):
        for it in results.get(origin, []):
            k = _song_key(it["title"], it["artist"])
            if k in merged:
                existing = merged[k]
                old_r = _RANK.get(existing["origin"], 1)
                new_r = _RANK.get(origin, 1)
                if new_r > old_r or (new_r == old_r and it["bitrate"] > existing["bitrate"]):
                    merged[k] = it
                    _order_update(order, k)
            else:
                merged[k] = it
                order.append(k)
    items = [merged[k] for k in order]
    _log_probe(f"[music] search '{keyword}': net={len(results.get('netease', []))} "
               f"ku={len(results.get('kuwo', []))} mi={len(results.get('migu', []))} → {len(items)}")
    return items[: max(limit, 1)]


def _order_update(order: list[str], k: str) -> None:
    if k not in order:
        order.append(k)


# ---------------- probe ----------------
_PROBE_MAGIC = (b"ID3", b"OggS", b"fLaC", b"ftyp")


def _looks_like_audio(b: bytes) -> bool:
    if b[:3] == b"ID3" or b[:4] in _PROBE_MAGIC:
        return True
    if len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0:
        return True
    return False


def probe_all(items: list[dict[str, Any]], client: httpx.Client,
              timeout: float = 3.0) -> list[dict[str, Any]]:
    probed: list[tuple[dict[str, Any], float, int, int, int, int]] = []

    def iprobe(i: int, it: dict[str, Any]) -> None:
        t0 = time.time()
        try:
            r = client.get(it["url"], headers={"Range": "bytes=0-2047"},
                           timeout=timeout, follow_redirects=False)
            lat = time.time() - t0
            ok = r.status_code in (200, 206)
            ct = r.headers.get("content-type", "")
            if ok and ct and not (ct.startswith("audio/") or "octet-stream" in ct):
                ok = False
            body = r.content
            if ok and not _looks_like_audio(body):
                ok = False
            size = 0
            cr = r.headers.get("content-range", "")
            m = re.match(r"bytes \d+-\d+/(\d+)", cr)
            if m:
                size = int(m.group(1))
            elif r.status_code == 200:
                size = int(r.headers.get("content-length") or 0)
                if size <= 65536:
                    size = 0           # Go: CL>64k otherwise 0
            if size and size < 256 * 1024:
                ok = False
            brate = int(it.get("bitrate") or 0)
            duration = int(it.get("duration") or 0)
            if ok and size and duration > 0:
                if not brate:
                    brate = int(size * 8 / duration)
                    it["bitrate"] = brate
                expect = (brate if brate > 96 else 96) * (duration / 1000.0) / 8.0
                if size * 2 < expect:
                    ok = False
            score = 0
            svr = r.headers.get("server", "")
            if "nginx" in svr.lower():
                score = 2
            elif "openresty" in svr.lower():
                score = 0
            else:
                score = 1
            if ok:
                it["size"] = size
                it["bitrate"] = brate if brate else 320
                probed.append((it, lat, score, size, brate, i))
        except Exception as e:
            _log_probe(f"[probe] {it.get('origin')} {it['title']}: {e}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, it in enumerate(items):
            ex.submit(iprobe, i, it)

    out = sorted(probed, key=lambda t: (-t[2], -t[4], t[1]))[:10]
    if not out:
        return items[:10]
    return [t[0] for t in out]


# ---------------- is_music + format template ----------------
MusicCodeRe = re.compile(r"^(?:我想听|播放)(.*)的(.*)$")
TextLikeRe = re.compile(r"^我想听(.*)的歌$")


def is_music(body: dict[str, Any]) -> tuple[bool, str | None]:
    """(is_music, keyword) — Go music.New(d).IsMusic() port."""
    code = (body.get("code") or "")
    text = (body.get("text") or "") or _nest(body, "general", "text") or ""
    intent = (body.get("semantic") or {}).get("intent") or {}
    if code == "SEARCH_ARTIST":
        return True, intent.get("keyword") or None
    if code == "SEARCH_CATEGORY":
        k = (intent.get("keyword") or "").strip()
        if not k:
            return False, None
        return True, intent.get("keyword")
    m = TextLikeRe.match(text)
    if m:
        return True, m.group(1)
    m2 = MusicCodeRe.match(text)
    if m2:
        return True, m2.group(2) + " " + m2.group(1)
    return False, None


def _nest(d: dict[str, Any], *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


_FORMAT_RESPONSE_ID = "e490d9576c5b438c8283a6e71cdba997"


def build_music_response(body: dict[str, Any], items: list[dict[str, Any]],
                         media_base: str) -> dict[str, Any]:
    """Go provider.Format() port. Build dict with FIXED template."""
    ism, kw = is_music(body)
    text = kw or (body.get("text") or "")
    intent = (body.get("semantic") or {}).get("intent") or {}
    musicinfo = []
    for it in items:
        raw_url = it.get("url", "")
        if raw_url:
            enc = base64.urlsafe_b64encode(raw_url.encode()).rstrip(b"=").decode()
            raw_url = media_base.rstrip("/") + "/media?u=" + enc
        mi = {"id": it.get("id") or random.randint(1, 9999999),
              "errorCode": 0, "duration": it.get("duration") or random.randint(1, 999999),
              "lyric": "", "album": it.get("album_name") or "",
              "artist": it.get("artist") or "", "hdImgUrl": it.get("img") or "",
              "isCollected": False, "title": it.get("title") or ""}
        if raw_url:
            mi["url"] = raw_url
        musicinfo.append(mi)
    intent.setdefault("language", "zh")
    intent.setdefault("tag", "")
    intent.setdefault("keyword", "")
    return {
        "semantic": {"intent": intent},
        "code": "SEARCH_CATEGORY",
        "data": {"result": {
            "count": len(musicinfo), "musicinfo": musicinfo,
            "totalTime": 10, "pagesize": 20, "errorCode": 0, "page": "1",
            "source": 1, "dataSourceName": "我的音乐", "searchType": "common",
        }},
        "originIntent": {"nluSlotInfos": []},
        "history": "cn.yunzhisheng.music",
        "source": "nlu",
        "uniCarRet": {"result": {}, "returnCode": 609, "message": "aios-home.hivoice.cn"},
        "asr_recongize": text or "为您播放",
        "rc": 0,
        "general": {"actionAble": "true", "quitDialog": "true",
                    "text": "为您播放", "type": "T"},
        "returnCode": 0,
        "retTag": "nlu",
        "service": "cn.yunzhisheng.music",
        "nluProcessTime": "106",
        "text": text or "为您播放",
        "responseId": _FORMAT_RESPONSE_ID,
    }
