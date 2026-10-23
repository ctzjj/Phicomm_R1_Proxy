# 音箱语音接口协议（抓包实测）

> 本文是劫持 `asrv3.hivoice.cn` 后从真实流量中整理的请求/响应格式，供自建 NLU / 大模型服务时**按同样格式返回**，让音箱能正常识别和执行。
> 抓包样本：`r1tool asr -dump <dir>` 生成的 `*_req.hdr/.bin`、`*_resp.hdr/.bin`。
>
> **意图分类 / 全部 code / operator / 调用链的源码级逆向**见 [`nlu-domains.md`](nlu-domains.md)（含对本文 §3.1/§3.2 样例的字段更正）。

## 1. 上传流程（客户端 → 服务端）

```
POST http://asrv3.hivoice.cn/trafficRouter/cs
CRYP: 1
P: <混淆串>[<SID>]              ← 同一句话的所有分块 SID 相同
Content-Length: <N>

body = 连续的 [uint16 小端长度][Opus 包] ...
```

* 编码：**Opus，16 kHz，单声道，20 ms/包**（首字节恒为 `0x48` = TOC config 9 = SILK WB）
* 一句话被拆成约 17 个 POST（每个约 300 ms），**固定 5 秒窗口**（`config.mg: wakeup_duration_for_continues=5000`）
* 每个音频 POST 的响应都是**空 body**（只有头部）
* 最后一条请求 `Content-Length: 0` 且带 `TP:`/`SP:`/`CI:`/`DT:` 头 → 表示"说完了，请给结果"
  （实测：最终 JSON 也可能提前挂在最后一个音频 POST 的响应上，客户端两种都能处理）

## 2. 响应头（必须带，客户端会读）

音频分块的 ack：

```
HTTP/1.1 200
Access-Control-Allow-Credentials: true
Access-Control-Allow-Origin: *
CT: W510-8N4
RS: GeLdJ
PN: rx
SID: <与请求 P 中相同的 SID>
Content-Length: 0
```

最终结果（JSON body）：

```
HTTP/1.1 200
Access-Control-Allow-Credentials: true
Access-Control-Allow-Origin: *
CT: W510
RS: <校验串>
PN: ry
SID: <与请求 P 中相同的 SID>
Content-Length: <JSON 长度>
```

> 自建服务时：**`SID` 必须回显请求里的 SID**，`CT`/`RS`/`PN` 建议照抄（`rx`=分块 ack，`ry`=最终结果）。

## 3. 最终 JSON（核心）

通用字段：

| 字段 | 说明 |
| --- | --- |
| `code` | 意图码，决定由哪个 handler 处理（见下表） |
| `semantic.intent.operations[]` | 设备控制：`{operator, operands}` |
| `general.text` | 要播报的文本（无 `audioUrl` 时由本地 TTS 朗读） |
| `general.type` | 固定 `"T"`（另有 `actionAble`/`quitDialog`=`"true"`） |
| `audioUrl` | 云端 TTS 音频直链，音箱直接播放 |
| `asr_recongize` | 识别出的文本 |
| `service` | 所属域，如 `cn.yunzhisheng.setting` |
| `history` / `uniCarRet` / `returnCode` / `responseId` | 原样透传即可 |

### 3.1 聊天/问答 — `code = "ANSWER"`

```json
{"semantic":{"intent":{"keyword":"","language":"zh","tag":""}},"code":"ANSWER",
 "history":"cn.yunzhisheng.calendar","source":"nlu",
 "uniCarRet":{"result":[],"returnCode":609,"message":"aios-home.hivoice.cn"},
 "asr_recongize":"几点了。","rc":0,
 "general":{"style":"calendar","text":"当前时间：16点35分","type":"T"},
 "returnCode":0,"audioUrl":"http://asrv3.hivoice.cn/trafficRouter/r/aImp3k",
 "retTag":"nlu","service":"cn.yunzhisheng.chat","nluProcessTime":"87","responseId":"..."}
```

### 3.2 设备控制 — `code = "SETTING_EXEC"`

```json
{"code":"SETTING_EXEC",
 "semantic":{"intent":{"operations":[{"operator":"ACT_OPEN","operands":"OBJ_BLUETOOTH"}]}},
 "service":"cn.yunzhisheng.setting",
 "general":{"text":"好的，正在为您打开蓝牙","type":"T"},
 "asr_recongize":"打开蓝牙。",
 "audioUrl":"http://asrv3.hivoice.cn/trafficRouter/r/xxxx"}
```

常用 `operator` / `operands`（来自 `assets/nlu/unidrive_main_nlu_offline.conf`）：

| 功能 | operator | operands |
| --- | --- | --- |
| 打开/关闭蓝牙 | `ACT_OPEN` / `ACT_CLOSE` | `OBJ_BLUETOOTH` |
| 音量 +/-/最大/最小 | `ACT_INCREASE` / `ACT_DECREASE` / `ACT_MAX` / `ACT_MIN` | `ATTR_VOLUME` |
| 播放/暂停/停止/上一首/下一首 | `ACT_PLAY` / `ACT_PAUSE` / `ACT_STOP` / `ACT_PREV` / `ACT_NEXT` | `OBJ_MEDIA_PLAYER` / `OBJ_MUSIC` |
| 睡眠模式 | `ACT_OPEN` / `ACT_CLOSE` | `OBJ_SLEEP_MODE` |
| 斐讯定制（版本/OTA/反馈/在线检查） | `ACT_QUESTION_VERSION` / `ACT_PHICOMM_OTA` / `ACT_PHICOMM_BACKUP` / `ACT_PHICOMM_CHECK_ONLINE_STATE` | — |
| 氛围灯/音效/智能家居 | `ACT_PHICOMM_OPEN/CLOSE_AMBIENTLIGHT`、`ACT_PHICOMM_OPEN/CLOSE_SOUNDEFFECT`、`ACT_PHICOMM_SMART_HOME` | — |

### 3.3 点歌 — `code = "SEARCH_ARTIST"` / `"SEARCH_CATEGORY"`

```json
{"semantic":{"intent":{"keyword":"陈绮贞","language":"zh","tag":""}},
 "code":"SEARCH_CATEGORY",
 "data":{"result":{"count":10,"musicinfo":[
   {"id":4420196,"errorCode":0,"duration":6313081,"lyric":"",
    "album":"华丽的冒险","artist":"陈绮贞",
    "hdImgUrl":"http://p1.music.126.net/...jpg","isCollected":false,
    "title":"旅行的意义","url":"http://m10.music.126.net/....mp3"}]}},
 "general":{"text":"为您播放陈绮贞","type":"T"},
 "asr_recongize":"我想听陈绮贞的歌。"}
```

必要字段：`data.result.musicinfo[].url`（可播放直链）、`title`、`artist`；`count` 与实际条数一致。

> **实测坑（重要）**：R1 的 MediaPlayer 对部分对象存储 CDN 的响应不兼容——
> `Server: openresty` + `Content-Disposition` / `x-nos-*` 头的链接会让播放器停在
> `MEDIA_PREPARING`（`total_time=0`，随后判为失败切下一首）。
> 优先使用 `Server: nginx`、`Content-Type: audio/mpeg`、带 `Content-Length` 的直链；
> 自建服务建议自己用 200/206 + `Accept-Ranges: bytes` 代理音频，避免这些头。
> `r1tool` 已内置 HEAD 探测：并发测速并优先挑选 nginx CDN 的链接（见 `music.ProbeOrder`）。

### 3.4 其它意图

| code | service | 说明 |
| --- | --- | --- |
| `CONNECT_WIFI` | `cn.yunzhisheng.connect` | 进入配网流程 |
| `WAKEUP_WORD` | `cn.yunzhisheng.wakeupword` | 修改唤醒词 |
| `USER_COMMAND` | — | 自定义命令（软件版本号 / 系统升级 / 问题反馈 / 你离线了吗） |

## 4. 最小可用返回（自建服务可直接套）

例如让音箱说一句话（不做事）：

```
HTTP/1.1 200
CT: W510
RS: GeLdJ
PN: ry
SID: <请求里的 SID>
Content-Type: application/json
Content-Length: 96

{"code":"ANSWER","general":{"text":"你好，我是你的音箱","type":"T"},"asr_recongize":"你好"}
```

执行一个动作（打开蓝牙）：

```json
{"code":"SETTING_EXEC",
 "semantic":{"intent":{"operations":[{"operator":"ACT_OPEN","operands":"OBJ_BLUETOOTH"}]}},
 "general":{"actionAble":"true","quitDialog":"true","text":"好的","type":"T"},
 "asr_recongize":"打开蓝牙"}
```

## 5. 与 r1tool 的配合

```sh
# 抓音频（每句一个 Ogg/Opus，可直接 ffmpeg 解码）
r1tool asr -addr 127.0.0.1:8080 -upstream 39.105.252.245:80 \
           -dump ./dump -audio-dir ./audio

# 把每句音频转发给自己的服务（POST audio/ogg，附 X-R1-SID/Packets/Sample-Rate/Channels）
r1tool asr ... -forward http://127.0.0.1:9000/asr

# 离线把已抓到的 dump 转成 Ogg
r1tool audiodump -dir ./dump -out ./audio
```

后续版本会把「你服务返回的 JSON」直接回给音箱（等价于本文档第 3/4 节的格式），实现完整的语音助手替换。
