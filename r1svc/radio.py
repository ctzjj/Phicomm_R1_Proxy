"""广播电台意图(独立分类,非音乐):service=cn.yunzhisheng.broadcast。

设备侧 DefaultMusicHandler:acceptInboundEvent0 把 BROADCAST 映射 serviceType=5,
eventReceived case 5 → dealBroadcastPlayService:data.result.rate64_ts_url 非空即
adaptBroadcast → play(true) 自动开播,TTS 播 intent.station。
本地维护可播电台表(data/radio.json,qingting 64k mp3 直链,经 /media 代理转发)。
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

_STATIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "radio.json"
_STATIONS: list | None = None

_CN_DIG = {"零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
           "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "点": "."}
_VERBS = re.compile(r"播放|我想?要?听|收听|打开|给我|来个|来一首?|放一?首?|一下|请问|帮我|换个|切换到?")
_TRIG = re.compile(r"电台|广播|调频|频率|fm", re.IGNORECASE)

_RESPONSE_ID = "e490d9576c5b438c8283a6e71cdba997"


def _stations() -> list:
    global _STATIONS
    if _STATIONS is None:
        try:
            data = json.loads(_STATIONS_PATH.read_text(encoding="utf-8"))
            _STATIONS = [s for s in (data.get("stations") or []) if s.get("url")]
        except Exception:
            _STATIONS = []
    return _STATIONS


def _norm(text: str) -> str:
    s = "".join(_CN_DIG.get(c, c) for c in (text or "").lower())
    return _VERBS.sub("", s).replace(" ", "").strip("。,,!!??、.的")


def match(text: str) -> dict | None:
    """原话识别电台:先频率(98.7/987/九八七),后台名/别名;没命中返回 None。"""
    s = _norm(text)
    if not s:
        return None
    core = _TRIG.sub("", s).strip("的")
    if not core:
        return None
    for m in re.finditer(r"\d{2,4}(?:\.\d)?", core):
        f = m.group().replace(".", "")
        for st in _stations():
            if (st.get("freq") or "").replace(".", "") == f:
                return st
    for st in _stations():
        names = [st.get("name", "")] + [a for a in (st.get("aliases") or []) if a]
        if core in names:
            return st
    # 泛称包含(如"交通广播"→福建交通)只在原话确实带电台类词时启用,
    # 避免"播放新闻"这类误中
    if len(core) >= 2 and _TRIG.search(s):
        for st in _stations():
            names = [st.get("name", "")] + [a for a in (st.get("aliases") or []) if a]
            if any(core in n or n in core for n in names):
                return st
    return None


def build_response(body: dict[str, Any], station: dict, media_base: str) -> dict:
    """按 BroadcastResult 契约组响应;url 走 /media?u=<base64url> 代理。"""
    url = station.get("url") or ""
    if url:
        enc = base64.urlsafe_b64encode(url.encode()).rstrip(b"=").decode()
        url = media_base.rstrip("/") + "/media?u=" + enc
    name = station.get("name") or ""
    asr = (body.get("text") or "") or f"播放{name}"
    try:
        qid = int(station.get("qid") or 0)
    except ValueError:
        qid = 0
    return {
        "semantic": {"intent": {"station": name, "type": "PLAY"}},
        "code": "PLAY_BROADCAST",
        "data": {"result": {
            # 注意:source/channel_id/schedule_id 在设备端是 int,
            # 类型不符会让整个 NLU 反序列化失败(设备报"网络连接失败")
            "audience_count": "0", "channel_id": qid,
            "cover_url_large": "", "cover_url_small": "",
            "dataSourceName": "蜻蜓FM", "description": name, "errorCode": 0,
            "program_name": name,
            "rate24_aac_url": "", "rate24_ts_url": "",
            "rate64_aac_url": "", "rate64_ts_url": url,
            "schedule_id": 0, "source": 0,
            "support_bitrates": "64", "title": name,
            "totalTime": 0, "update_time": "",
        }},
        "originIntent": {"nluSlotInfos": []},
        "history": "cn.yunzhisheng.broadcast",
        "source": "nlu",
        "uniCarRet": {"result": {}, "returnCode": 609, "message": "radio"},
        "asr_recongize": asr,
        "rc": 0,
        "general": {"actionAble": "true", "quitDialog": "true",
                    "text": f"正在为您播放{name}", "type": "T"},
        "returnCode": 0,
        "retTag": "nlu",
        "service": "cn.yunzhisheng.broadcast",
        "nluProcessTime": "106",
        "text": asr,
        "responseId": _RESPONSE_ID,
    }
