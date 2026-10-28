import os, re, time, threading
from datetime import datetime, timedelta

os.environ.setdefault("PADDLE_NLP_HOME", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "paddlenlp"))

from paddlenlp import Taskflow

# R1 设备意图域（来自 repo/doc/nlu-domains.md 逆向结果）
_R1_DOMAINS = {
    "chat":        ("cn.yunzhisheng.chat",            "cn.yunzhisheng.chat"),
    "calendar":    ("cn.yunzhisheng.chat",            "ANSWER"),
    "weather":     ("cn.yunzhisheng.weather",         "FORECAST"),
    "light":       ("cn.yunzhisheng.setting",         "SETTING_EXEC"),
    "volume":      ("cn.yunzhisheng.setting.common",  "SETTING_EXEC"),
    "bluetooth":   ("cn.yunzhisheng.setting",         "SETTING_EXEC"),
    "sleep_mode":  ("cn.yunzhisheng.setting",         "SETTING_EXEC"),
    "purifier":    ("cn.yunzhisheng.setting",         "SETTING_IOT"),
    "curtain":     ("cn.yunzhisheng.setting",         "SETTING_IOT"),
    "ac":          ("cn.yunzhisheng.setting",         "SETTING_IOT"),
    "music_play":  ("cn.yunzhisheng.music",           "SEARCH_SONG"),
    "music_ctrl":  ("cn.yunzhisheng.setting.mp",      "SETTING_EXEC_MP"),
    "alarm":       ("cn.yunzhisheng.alarm",           "ALARM_SET"),
    "countdown":   ("cn.yunzhisheng.alarm",           "ALARM_SET_TIMING"),
    "reminder":    ("cn.yunzhisheng.reminder",        "REMINDER_SET"),
    "note":        ("cn.yunzhisheng.note",            "ANSWER"),
    "wakeupword":  ("cn.yunzhisheng.setting",         "SETTING_EXEC"),
}

_NUM = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_SLU_LOCK = threading.Lock()

# 规则底座：优先命中（按顺序），ERNIE(utc) 只做开放意图兜底。
_RULES = [
    (r"新闻|热点|热搜|头条|时事|要闻|发生了什么|有哪些.{0,4}(新闻|事)", "chat"),
    (r"几点|几点钟|多少点了|时间|日期|号数|今天.{0,2}(几号|多少号|什么日子|礼拜|星期|周几)|星期几|礼拜几|周几|农历|阴历", "calendar"),
    (r"换个?唤醒词|改.{0,2}名字|以后.{0,4}叫", "wakeupword"),
    (r"闹钟|闹铃|叫早|叫醒|叫我.{0,6}(起床|吃饭|开会)|睡前.{0,2}叫", "alarm"),
    (r"倒计时|倒数", "countdown"),
    (r"提醒|到点.{0,3}(告诉|响)|外拍提醒", "reminder"),
    (r"便签|备忘|记一下|记下|记录|记着", "note"),
    (r"天气|下(雨|雪)|会不会下雨|户外温度|气温", "weather"),
    (r"暂停|停止?播|别放了|不放了|下一首|上一首|继续(播|放)|快进|快退|收藏|取消?收藏|单曲循环|随机播|切(换|歌)播放模式|换一首", "music_ctrl"),
    (r"静音|闭嘴|音量|声音(大|小|调)|大声|小声点|调?响一点|太吵", "volume"),
    (r"氛围灯|灯带|灯光|灯环|灯颜色|灯变成", "light"),
    (r"净化器|空气清洁|吸猫毛", "purifier"),
    (r"窗帘", "curtain"),
    (r"空调|制热|制冷|暖风|冷风温度", "ac"),
    (r"蓝牙", "bluetooth"),
    (r"睡眠模式|睡觉模式|晚安模式|双击.*休眠", "sleep_mode"),
    (r"来一首|来段|放一?个?.{0,8}(歌|曲|音乐)|播放.{0,8}(歌|曲|音乐)?|想听|点?(播|一首)|唱一首|放歌", "music_play"),
    (r"嗨翻|唱支歌|听音乐", "music_play"),
]


def _cn_num(s):
    s = str(s).strip().replace("%", "")
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if "十" in s:
        i = s.index("十")
        tens = _NUM.get(s[i - 1], 1) if i > 0 else 1
        ones = _NUM.get(s[i + 1], 0) if i + 1 < len(s) else 0
        return tens * 10 + ones
    total = 0
    for ch, v in _NUM.items():
        if ch in s:
            total = total * 10 + v
    return total or None


_REL = {"今天": 0, "今晚": 0, "今日": 0, "明天": 1, "明日": 1, "明早": 1, "后天": 2, "大后天": 3}
_WEEK = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
_PM_WORDS = ("下午", "晚上", "傍晚", "夜里", "今晚")


def _parse_dt(text):
    """结构化日期/时间（尽力而为）：返回 (date yyyy-MM-dd, time HH:mm)"""
    today = datetime.now()
    day = None
    for k, v in _REL.items():
        if k in text:
            day = today + timedelta(days=v)
            break
    if day is None:
        m = re.search(r"[周星]([一二三四五六日天])", text)
        if m:
            wd = _WEEK.get(m.group(1), 0)
            delta = (wd - today.weekday() - 1) % 7 + 1
            day = today + timedelta(days=delta)

    hm = re.search(r"(\d{1,2}|十|[一二两三四五六七八九]+)\s*点\s*(半|\d{1,2}|[一二两三四五六七八九]+)?", text)
    hh = mm = None
    if hm:
        hh = int(hm.group(1)) if str(hm.group(1)).isdigit() else _cn_num(hm.group(1))
        mm = 30 if hm.group(2) == "半" else (int(hm.group(2)) if hm.group(2) and hm.group(2).isdigit() else None)
        if mm is None and hm.group(2) is not None:
            mm = _cn_num(hm.group(2))
    if hh is not None and hh < 12 and any(k in text for k in _PM_WORDS):
        hh += 12
    res_date = day.strftime("%Y-%m-%d") if day else ""
    res_time = f"{hh or 0:02d}:{mm or 0:02d}" if hh is not None else ""
    return res_date, res_time


def _abs_dt(text):
    """相对时间("N分钟/半小时/N小时后")或今天明天+时点 → 绝对 datetime；解析不了返回 None。"""
    now = datetime.now()
    m = re.search(r"(\d+|十|[一二两三四五六七八九]+)\s*分(?:钟)?(?:后|之后|以后)", text)
    if m:
        return now + timedelta(minutes=_cn_num(m.group(1)) or 0)
    if re.search(r"半(?:个)?小时(?:后|之后|以后)", text):
        return now + timedelta(minutes=30)
    m = re.search(r"(\d+|十|[一二两三四五六七八九]+)\s*(?:个)?小时(?:后|之后|以后)", text)
    if m:
        return now + timedelta(hours=_cn_num(m.group(1)) or 0)
    m = re.search(r"(\d+|十|[一二两三四五六七八九]+)\s*秒(?:钟)?(?:后|之后|以后)", text)
    if m:
        return now + timedelta(seconds=_cn_num(m.group(1)) or 0)
    d, t = _parse_dt(text)
    if t:
        hh, mm = [int(x) for x in t.split(":")]
        cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if d:
            y, mo, dd = [int(x) for x in d.split("-")]
            cand = cand.replace(year=y, month=mo, day=dd)
        if cand <= now:
            cand += timedelta(days=1)
        return cand
    return None


class ErnieSLU:
    """ERNIE 系文本 SLU：意图(utc-nano 零样分类) + 槽位(uie-nano)，全 CPU。
    权重来自 bj.bcebos.com，首次运行自动下载。
    """

    def __init__(self, intent_model="utc-nano", slot_model="uie-nano", confidence=0.30):
        self.confidence = confidence
        self._labels = list(_R1_DOMAINS)
        self._rules = [(re.compile(r), d) for r, d in _RULES]
        self._intent = Taskflow("zero_shot_text_classification", model=intent_model,
                                schema=list(self._labels), pred_threshold=0.1, batch_size=16)
        self._slot = Taskflow("information_extraction", model=slot_model, schema=[])
        self._schemas = {
            "weather":    ["城市", "时间"],
            "light":      ["开关状态", "灯颜色"],
            "volume":     ["数值", "方向"],
            "music_play": ["歌名", "歌手"],
            "alarm":      ["日期", "时间", "重复规则", "备注"],
            "countdown":  ["时长", "备注"],
            "reminder":   ["时间", "内容"],
            "purifier":   ["开关状态"],
            "curtain":    ["开关状态"],
            "ac":         ["开关状态", "温度", "模式"],
            "bluetooth":  ["开关状态"],
            "sleep_mode": ["开关状态"],
            "wakeupword": ["新唤醒词"],
        }

    def _pick_intent(self, text):
        with _SLU_LOCK:
            res = self._intent([text])
        if not res:
            return "chat", 0.0, []
        out = res[0] if isinstance(res, list) else res
        preds = out.get("predictions")
        if isinstance(preds, dict):
            preds = [{"label": k, "score": v} for k, v in preds.items()]
        if preds and isinstance(preds[0], dict) and "predictions" in preds[0]:
            preds = preds[0]["predictions"]
        if not preds:
            return "chat", 0.0, []
        top = max(preds, key=lambda p: p["score"])
        return top["label"], float(top["score"]), preds

    def _pick_slots(self, text, domain):
        schema = self._schemas.get(domain)
        if not schema:
            return {}
        with _SLU_LOCK:
            self._slot.set_schema(schema)
            res = self._slot([text])
        if not res:
            return {}
        slots = {}
        for k, spans in (res[0] if res else {}).items():
            if isinstance(spans, dict):
                spans = [spans]
            best = None
            for sp in spans or []:
                if best is None or sp.get("score", 0) > best.get("score", 0):
                    best = sp
            if best:
                slots[k] = best["text"]
        return slots

    @staticmethod
    def _to_r1(domain, text, slots):
        service, code = _R1_DOMAINS.get(domain, ("cn.yunzhisheng.chat", "cn.yunzhisheng.chat"))
        semantic = {"intent": {}}
        ops = []
        has_on = any(k in text for k in ("开", "打开", "启动"))
        has_off = any(k in text for k in ("关", "关闭", "熄"))
        turn_on = has_on and not has_off

        if domain == "weather":
            wdate = next((k for k in ("今天", "明天", "后天") if k in text), "")
            semantic["intent"] = {"city": slots.get("城市", ""), "date": wdate}
        elif domain == "light":
            if slots.get("灯颜色"):
                ops.append({"operator": "ACT_SET", "operands": "ATTR_COLOR",
                            "value": "COLOR_" + slots["灯颜色"].upper()})
            else:
                ops.append({"operator": "ACT_OPEN" if turn_on else "ACT_CLOSE", "operands": "AmbientLight"})
        elif domain == "volume":
            SettingNumberMatch = re.search(r"(?:调到|调至|设为|设成|调到|跳到|开到)\s*(\d{1,3}%?)", text) or \
                re.search(r"(?:调到|调至|设为|设成|跳到|开到)\s*(十|[一二两三四五六七八九]+)\s*个?", text)
            n = None
            if SettingNumberMatch:
                n = _cn_num(SettingNumberMatch.group(1))
            if n is None:
                bare = re.search(r"(\d{1,3})%?", text.split("调到")[-1])  # "音量 50" 场景
                if bare and "音量" in text and "," not in text and bare.group(1).isdigit():
                    n = int(bare.group(1)) if int(bare.group(1)) <= 100 else None
            if n is not None:
                ops.append({"operator": "ACT_SET", "operands": "ATTR_VOLUME",
                            "value": str(min(100, max(0, n))), "datatype": "int"})
            elif "最大" in text:
                ops.append({"operator": "ACT_MAX", "operands": "ATTR_VOLUME"})
            elif "最小" in text:
                ops.append({"operator": "ACT_MIN", "operands": "ATTR_VOLUME"})
            elif "小" in text:
                ops.append({"operator": "ACT_DECREASE", "operands": "ATTR_VOLUME"})
            elif "大" in text:
                ops.append({"operator": "ACT_INCREASE", "operands": "ATTR_VOLUME"})
            elif "静音" in text or "闭嘴" in text:
                ops.append({"operator": "ACT_SET", "operands": "ATTR_MODE", "value": "MODE_MUTE"})
            else:
                ops.append({"operator": "ACT_QUERY", "operands": "ATTR_VOLUME"})
        elif domain == "bluetooth":
            ops.append({"operator": "ACT_OPEN" if turn_on else "ACT_CLOSE", "operands": "OBJ_BLUETOOTH"})
        elif domain == "sleep_mode":
            ops.append({"operator": "ACT_OPEN" if turn_on else "ACT_CLOSE", "operands": "OBJ_SLEEP_MODE"})
        elif domain in ("purifier", "curtain", "ac"):
            obj = {"purifier": "OBJ_AIR_CLEANER", "curtain": "OBJ_CURTAIN", "ac": "OBJ_AC"}[domain]
            ops.append({"operator": "ACT_OPEN" if turn_on else "ACT_CLOSE", "operands": obj})
            if domain == "ac" and slots.get("温度"):
                n = _cn_num(slots["温度"])
                if n:
                    ops.append({"operator": "ACT_SET", "operands": "ATTR_TEMPERATURE", "value": str(n)})
        elif domain == "music_play":
            semantic["intent"] = {"song": slots.get("歌名", ""), "artist": slots.get("歌手", ""), "keyword": text}
        elif domain == "music_ctrl":
            for k, v in (("暂停", "ACT_PAUSE"), ("别", "ACT_STOP"), ("停止", "ACT_STOP"),
                         ("停", "ACT_STOP"), ("上一", "ACT_PREV"), ("下一", "ACT_NEXT"),
                         ("继续", "ACT_RESUME"), ("收藏", "ACT_COLLECT"),
                         ("取消收藏", "ACT_CANCEL_COLLECT"), ("单曲循环", "ACT_SWITCH_PLAY_MODE"),
                         ("循环", "ACT_SWITCH_PLAY_MODE"), ("随机", "ACT_SWITCH_PLAY_MODE"),
                         ("换一首", "ACT_SWITCH_PLAY_MODE"), ("切歌", "ACT_SWITCH_PLAY_MODE"),
                         ("快进", "ACT_FASTB"), ("快退", "ACT_FASTF")):
                if k in text:
                    ops.append({"operator": v})
                    break
            else:
                ops.append({"operator": "ACT_PLAY"})
        elif domain == "alarm":
            d, t = _parse_dt(text)
            semantic["intent"] = {"date": d or slots.get("日期", ""), "time": t or slots.get("时间", ""),
                                  "repeatDate": "OFF", "label": slots.get("备注", "")}
        elif domain == "countdown":
            ms = 600000
            mm = re.search(r"(\d+|十|[一二两三四五六七八九]+)\s*(?:分钟|分)", text)
            ss = re.search(r"(\d+|十|[一二两三四五六七八九]+)\s*秒", text)
            if mm:
                ms = (_cn_num(mm.group(1)) or 0) * 60000
            elif ss:
                ms = (_cn_num(ss.group(1)) or 0) * 1000
            ms = max(10000, ms)
            semantic["intent"] = {"countDownTime": ms, "repeatDate": "OFF", "label": slots.get("备注", "")}
        elif domain == "reminder":
            content = str(slots.get("内容") or "").strip()
            if not content:
                cm = re.search(r"提醒(?:我|你)?(.+)$", text)
                content = cm.group(1).strip() if cm else text
            at = _abs_dt(text)
            if at:
                # 对齐真云 1223:dateTime 为绝对时间,并带 reminderTime/event 等字段
                iso = at.strftime("%Y-%m-%d %H:%M:%S")
                semantic["intent"] = {
                    "content": content, "dateTime": iso,
                    "date": at.strftime("%Y-%m-%d"),
                    "reminderDate": at.strftime("%Y-%m-%d"),
                    "time": at.strftime("%H:%M:%S"),
                    "reminderTime": at.strftime("%H:%M:%S"),
                    "uncertainIntent": "false", "repeatType": "OFF",
                    "repeatDate": "OFF", "isSubscribe": False,
                    "topic": "GENERAL", "triggerType": "TIME", "isOrigin": True,
                    "event": {"topic": "GENERAL", "content": content},
                }
            else:
                d, t = _parse_dt(text)
                dt = ((d or slots.get("日期", "")) + " " + (t or slots.get("时间", ""))).strip()
                semantic["intent"] = {"content": content, "dateTime": dt,
                                      "repeatType": "OFF"}
        elif domain == "wakeupword":
            w = slots.get("新唤醒词") or ""
            if not w:
                wm = re.search(r"叫([\u4e00-\u9fa5]{2,4})(?:我)?$", text)
                w = wm.group(1) if wm else ""
            ops.append({"operator": "ACT_SET", "operands": "ATTR_WAKEUP_WORD", "value": w})

        if ops:
            semantic["intent"] = {"operations": ops, "voiceTip": "", "musicInfo": []}

        return {
            "domain": domain,
            "service": service,
            "code": code,
            "slots": slots,
            "r1_nlu": {
                "service": service, "code": code, "rc": 0, "retTag": "nlu",
                "text": text, "asr_recongize": text, "semantic": semantic,
            },
        }

    def __call__(self, text):
        t0 = time.time()
        # 1) 规则底座（高精度）
        domain, method = "chat", "none"
        for rx, d in self._rules:
            if rx.search(text):
                domain, method = d, "rule"
                break
        if method == "rule":
            score = 1.0
        else:
            # 2) ERNIE(utc) 零样兜底
            intent, score, ranked = self._pick_intent(text)
            if score < self.confidence:
                domain, method, score = "chat", "utc-low", score
            else:
                domain, method = intent, "ernie"
        slots = {} if domain == "chat" else self._pick_slots(text, domain)
        out = self._to_r1(domain, text, slots)
        out.update(score=round(score, 4), method=method, latency_ms=int((time.time() - t0) * 1000))
        return out


slu = None


def get_slu():
    """Taskflow(utc-nano/uie-nano)懒加载;失败给手动下载提示。"""
    global slu
    if slu is None:
        try:
            slu = ErnieSLU()
        except Exception as e:
            import os
            cache = os.path.join(os.path.expanduser("~"), ".paddlenlp", "taskflow")
            print(f"[slu] Taskflow 模型加载/下载失败: {e}", flush=True)
            print(f"[slu] 手动下载: https://bj.bcebos.com/paddlenlp/taskflow/"
                  f"(zero_shot_text_classification/utc-nano, information_extraction/uie-nano)", flush=True)
            print(f"[slu] 解压存放目录: {cache}", flush=True)
            raise
    return slu
