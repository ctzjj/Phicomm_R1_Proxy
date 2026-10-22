# R1 语音助手调研记录（续接用）

> 本文记录对 `com.phicomm.speaker.device`（云知声 ANT 引擎）与 `com.phicomm.speaker.player`（echoplayer）
> 的实测结论、协议细节与已知坑，方便后续继续开发。协议字段以抓包为准。

## 1. 组件与链路

| 组件 | 包名 | 职责 |
| --- | --- | --- |
| 语音助手 | `com.phicomm.speaker.device` | 唤醒、录音、ASR/NLU 请求、执行意图、TTS |
| 播放器 | `com.phicomm.speaker.player` | 出声、音乐播放（NetPlayerService/MultiMediaPlayer）、蓝牙/AirPlay/DLNA |
| 进程间 | `msgcenter`（`MessageDispatchManager`） | 助手 ↔ 播放器 的消息通道（play/pause/状态上报） |
| 云端 | `asrv3.hivoice.cn` | ASR + NLU + TTS（Opus 上传、JSON 返回、TTS 音频） |
| 云端 | `aios-home.hivoice.cn:19999` | 绑定、日志上报、音乐内容 API |
| 云端 | `msg-pandora.hivoice.cn` | MQTT 推送 |

劫持方式（已验证）：路由器把 `asrv3.hivoice.cn`、`aios-home.hivoice.cn` 指向 PC，
WSL nginx 按 `server_name` 反代到 `r1tool asr`（127.0.0.1:8080）与绑定服务。

## 2. 唤醒与录音

- 本地唤醒引擎：`libasrfix.so` + `assets/asrfix`，关键词 **"小讯小讯"**
- 阈值：`assets/config/config.mg` → `wakeup_benchmark=-9.1`，播放音乐时 -11.3/-12.3/-13.3
- `aec_enable=true`（`libaec.so`），支持四麦（`ASR_FOURMIC`）与 DOA
- **`oneshot_enable=false`**：必须先唤醒再说命令；每次唤醒只处理一条
- 录音窗口 **固定 5 秒**（`wakeup_duration_for_continues=5000`），不是 VAD 截断
- VAD 参数：前静音 5000ms / 后静音 800ms（在线）

## 3. 上传协议（asrv3）

```
POST /trafficRouter/cs
CRYP: 1
P: <混淆串>[<SID>]        ← 同一句的 SID 相同
Content-Length: N

body = [uint16 LE 长度][Opus 包] ...   （16 kHz 单声道，20 ms/包，TOC=0x48 → SILK WB）
```

- 一句约 17 个 POST；每条音频 POST 的响应只回 ack（`CT: W510-8N4`、`RS`、`PN: rx`、`SID`、空 body）
- 最后一条 `Content-Length: 0` 且带 `TP/SP/CI/DT` 头 → "说完了，给结果"
- 最终 JSON 可能挂在最后一个音频 POST 的响应上，也可能挂在 `TP` 请求的响应上（客户端都能处理）
- **音频没有加密**（`CRYP: 1` 只混淆元数据头）；`r1tool asr -audio-dir` 已能按 SID 聚合出 Ogg/Opus
- 电平很低（峰值约 -42 dBFS），云端会归一化；本地处理建议 +30dB 左右

实测细节：
- 静音/无有效语音时云端返回 **HTTP 604 空体**，助手会念兜底话术（不是代理问题）
- 云端偶发 604/超时，代理需原样透传并保持上游可切换

## 4. 响应格式与意图判定

详见 [`nlu-protocol.md`](nlu-protocol.md)。要点：

- **不是本地规则判断**：云端 NLU 在预定义意图体系上做分类 + 槽位抽取，返回 `code`/`service`/`semantic.intent.operations`
- 本地只有离线命令词表（`assets/nlu/unidrive_main_nlu_offline.conf`、`assets/commands/user_commands_config.xml`）
- 闲聊 = 没有可执行 operations，只有 `general.text`/`audioUrl` → 只播 TTS
- 实测云端分类不稳定（"我想听陈绮贞的歌" 曾被判成闲聊），`r1tool` 已加"闲聊兜底 → 自己搜索"

## 5. 音乐链路

```
SEARCH_ARTIST / SEARCH_CATEGORY（或我们兜底）
  → 助手把 itemList 经 msgcenter 发给 echoplayer
  → MultiMediaPlayer: play() 准备 → 需 start() 才真正播放
  → 播放中每 30s 上报状态到 MQTT
```

**实测坑（重要）**

1. **CDN 兼容性**：`Server: openresty` + `Content-Disposition` / `x-nos-*` 的对象存储链接会让
   R1 的 MediaPlayer 卡在 `MEDIA_PREPARING`（`total_time=0`）→ 判失败切歌。
   `Server: nginx`、`Content-Type: audio/mpeg`、带 `Content-Length` 的直链可正常播放。
   → `r1tool` 的 `music.ProbeOrder` 会 HEAD 探测并优先 nginx CDN。
2. **TTS 与播放的时序**：助手会先播 TTS 再 start 音乐；`audioUrl` 若是失效地址会导致一直不 start。
   → 响应里不带 `audioUrl`（本地 TTS 播报）已验证可播。
3. **音乐 API 现状**：
   - 网易云：`linux/forward` + `cloudsearch/pc` + `song/enhance/player/url`（`br=320000`）可用
   - 网易云备用：`https://music.163.com/api/search/get/web?s=&type=1&offset=0&limit=`
   - 酷我：`http://search.kuwo.cn/r.s?...&rformat=json`（返回单引号伪 JSON，需容错解析）；
     播放地址 `http://antiserver.kuwo.cn/anti.s?...&rid=MUSIC_<rid>`：**目前只返回试听片段**（约 80~200KB），已用「实际大小 vs 码率×时长」校验过滤掉
   - 酷狗：`http://mobilecdn.kugou.com/api/v3/search/song` 搜索可用，但取播放地址需要登录态
     （`wwwapi.kugou.com/yy/index.php?r=play/getdata` 返回 `err_code=30020`）→ 暂不启用
   - 咪咕：`m.music.migu.cn/migu/remoting/scr_search_tag` 已下线（301 到 v5 SPA）→ 移除
   - `kugo.go` 原本只是把 Kuwo 的响应当日志打印，从未可用 → 已被真实 Kuwo 实现取代

## 6. 当前实现状态（`go/`）

| 功能 | 状态 |
| --- | --- |
| `r1tool asr` 劫持 / 改写点歌 | ✅ 可用 |
| 音频抓取（按 SID 聚合 Ogg） | ✅ 可用 |
| `-forward` 转发音频 | ✅ 可用（待接自建 NLU） |
| 点歌多源并发 + 去重 + 音质择优 | ✅ 网易云 + 酷我，探测可播后返回 |
| 自建 NLU/TTS（路线 A/B） | ⏳ 待做 |

## 7. 下一步（路线 A 优先）

1. `-nlu <url>`：把音频转发给自建服务，拿回 `code/operations/text` → 组装响应回给音箱
2. 自建 TTS（CosyVoice2 / edge-tts）替换 `audioUrl`
3. 多轮上下文（按 SID + 时间窗关联）
4. 技能补齐（闹钟/提醒/天气），槽位格式需从 `PhicommAlarmHandler/ReminderHandler` 逆出
5. 若追求"小爱级"体验（流式、打断、连续对话）→ 路线 B：自建客户端（见对话记录）

## 8. 音源可用性实测（2026-10）

| 音源 | 搜索 | 完整曲目 | 结论 |
| --- | --- | --- | --- |
| 网易云（linux/forward + cloudsearch + song/enhance） | ✅ | ✅ 320k（免费曲目） | 主力源 |
| 网易云（GD Studio `music-api.gdstudio.xyz`） | ✅ | ✅ 320k | 本机网络下 Cloudflare 连接被 RST，默认未启用 |
| 酷我（www.kuwo.cn 搜索 + mobi.s `convert_url_with_sign`） | ✅ | ✅ 320k（需随机国内 IP 头） | 主力源之一；旧的 `anti.s` 只返回试听，已弃用 |
| 酷狗（mobilecdn 搜索 + m.kugou getSongInfo） | ✅ | ❌ url 为空（需登录） | 未启用 |
| QQ 音乐（musicu.fcg） | ❌ 需登录 | ❌ vkey 405 | 未启用 |
| 咪咕（pd.musicapp 搜索 + listen-url `toneFlag=PQ`） | ✅ | ✅ 128k（HQ/SQ 需登录） | 免登录可用，已启用 |

**覆盖率取决于曲目的版权/会员状态**：免费曲目基本都能出 320k（实测「经典老歌」10 首全可播）；
冷门/会员曲目（如部分陈绮贞）在网易云拿不到 URL，其它平台又只有试听或需要登录 → 只能等有凭据的音源接入。

多源框架已就绪：实现 `music.Source`（`Name`/`Search`）后加入 `DefaultSources()` 即可自动参与
「并发搜索 → 去重选最优音质 → ranged GET 校验 → 过滤试听 → 按可播/码率/延迟排序」。