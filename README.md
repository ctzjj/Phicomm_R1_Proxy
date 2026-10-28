# r1svc — 斐讯 R1 音箱本地语音后端

把斐讯 R1 音箱的云端语音链路整体接管到本地：一条命令（`python start.py`）起三个服务，
承接设备的 ASR 上行、本地/云端 NLU、音乐搜索与流代理、聊天大模型、广播电台意图、
以及设备绑定接口仿真。

- 设备侧零改动，靠 DNS 劫持把 `asrv3.hivoice.cn` 指到本机即可
- ASR（SenseVoice，sherpa-onnx，CPU）+ 意图分类（ERNIE utc/uie）全本地，不上传音频
- 聊天走 LLM：外部 llama.cpp（OpenAI 兼容接口，工具调用）或内置 MiniCPM4-0.5B
- 音乐：网易/酷狗/咪咕三源并发搜索，直链探测后经 `/media?u=` 反向代理给设备
- 广播电台：本地电台表匹配，返回设备原生 `cn.yunzhisheng.broadcast` 域，设备 SDK 自动开播
- WebUI（`:9000`）看状态、日志、改配置（热生效）

> 协议与设备域逆向细节见 `doc/`。

## 架构

```
                          ┌──────────────────────── r1svc (python start.py) ───────────────────────┐
R1 设备 ──POST /trafficRouter/cs──> WSL nginx :80 ──> :8080 asrproxy ── 中间帧: 200 空 ack          │
   │  (asrv3.hivoice.cn，DNS 劫持到本机)                │   末帧(CL:0+TP): 收齐 Opus → 本地 ASR      │
   │                                                    │     → SLU(规则 + utc/uie)                 │
   │                                                    │       ├─ chat  → LLM(+工具) → ANSWER     │
   │                                                    │       ├─ music → 三源搜索 → musicinfo    │
   │                                                    │       └─ radio → 广播域 broadcast        │
   │                                                    └─ 云端模式: 原样转发真实云端 + overlay      │
   │                                                                                               │
   ├──GET /media?u=<base64url>──> nginx :80 ──> :8080 media (Range/HEAD 透传，直播流回退)          │
   └──POST aios-home.hivoice.cn:19999──> bindsvc（/getUserInfo → {"status":"0"}，其余 catch-all）  │
                                                                                                   │
   r1svc ──> llama.cpp :12345 /v1/chat/completions（外部，带 tools）                                 │
        └─> 或内置 MiniCPM4-0.5B（transformers，CPU）                                              │
                          └───────────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. Python 环境

```powershell
# 已有 venv（本项目一直在用这个）：
D:\tmp\r1\asr-slu\.venv\Scripts\python.exe -X utf8 start.py

# 全新环境：
python -m venv asr-slu\.venv
asr-slu\.venv\Scripts\pip install -r asr-slu\requirements.txt httpx
```

说明：

- `asr-slu\requirements.txt` 里 torch 是 cu121 版（仅为内置聊天小模型/transformers 用）；
  纯 CPU 机器可改装 CPU 版 torch，ASR 本身走 sherpa-onnx 的 C 库、不依赖 torch
- SLU 依赖：paddlepaddle + paddlenlp==2.8.1（CPU 推理）

### 2. 模型（首次启动自动下载，失败时日志给出手动地址）

| 模型 | 位置 | 说明 |
| --- | --- | --- |
| SenseVoice ASR | `asr-slu\models\sensevoice` | 自动从 ModelScope 下载（失败回退 GitHub release） |
| sherpa-onnx 运行时 | `asr-slu\pkg\sherpa-onnx-v1.13.8-...-win-x64-cuda` | 需手动解压预编译包，缺失时启动日志提示 |
| utc-nano / uie-nano | `~\.paddlenlp` | paddlenlp taskflow 自动下载 |
| MiniCPM4-0.5B（内置聊天） | `r1svc\asr_engine\MiniCPM-4.7` | 仅 `llm_api` 为空时使用，首次从 ModelScope 下载 |

### 3. 配置

编辑 `data\config.json`（UTF-8 **无 BOM**，否则会被当作无效 JSON 回退默认值）：

```json
{
  "nlu_mode": "custom",
  "llm_chat": true,
  "llm_api": "http://127.0.0.1:12345",
  "web_search": true,
  "music_enabled": true
}
```

### 4. 启动

```powershell
# 前台（调试）
D:\tmp\r1\asr-slu\.venv\Scripts\python.exe -X utf8 D:\tmp\r1\start.py

# 后台（计划任务，不阻塞终端）
schtasks /run /tn r1svc
```

启动后日志会打印 `r1svc up: asr=127.0.0.1:8080 api=127.0.0.1:9000 bind=0.0.0.0:19999`，
随后是模型加载与预热（`[nlu] warmup done in ...`）。WebUI：<http://127.0.0.1:9000/>。

### 5. 设备侧前置（一次性）

1. 路由器/本机 DNS 劫持：`asrv3.hivoice.cn` → 本机 IP（如 192.168.123.151）
2. `:80` 转发到 `127.0.0.1:8080`：WSL（mirrored 网络）里 nginx `server_name asrv3.hivoice.cn; location / { proxy_pass http://127.0.0.1:8080; }`，
   或任何等价的 80→8080 转发（设备只会连 80 端口）
3. `aios-home.hivoice.cn` → 本机，`:19999` 由 bindsvc 应答（否则设备绑定请求空转、无法再唤醒）
4. 设备与本机同一局域网

### 6. 验证

```powershell
# 健康检查
curl http://127.0.0.1:9000/api/status
# 单元测试（当前 73 passed）
D:\tmp\r1\asr-slu\.venv\Scripts\python.exe -m pytest tests -q
```

真机验收（按顺序）：

| 说法 | 预期 |
| --- | --- |
| 今天天气怎么样 | 10 秒内语音播报天气 |
| 播放周杰伦的歌 | 搜歌并播放 |
| 播放FM98.7广播 | "正在播放私家车987" 后直接开播 |
| 讲个笑话 / 历史上的今天 | LLM 应答（工具链路） |

## 配置参数（`data/config.json`）

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `listen_asr` | `127.0.0.1:8080` | 设备语音协议 + `/media` 代理。**只绑本机**，对外由 nginx :80 转发 |
| `listen_api` | `127.0.0.1:9000` | WebUI + 调试 API |
| `listen_bind` | `0.0.0.0:19999` | `aios-home.hivoice.cn` 绑定仿真（`/getUserInfo → {"status":"0"}`） |
| `upstream` | `""` | 云端 NLU 上游。空 = 按请求 Host 用公共 DNS 解析真实云端；也可写 `host:port` 强制 |
| `dns` | `223.5.5.5:53` | 解析云端 IP 用的 DNS（绕开本机劫持） |
| `media_base` | `http://asrv3.hivoice.cn` | 设备取流 URL 前缀，音乐/广播 URL 会重写为 `<media_base>/media?u=<base64url>` |
| `nlu_mode` | `custom` | `custom`=本地 ASR+SLU；`cloud`=转发真实云端，仅做 music/radio overlay |
| `nlu_key` / `nlu_key_header` | `""` / `Authorization` | 访问自定义 NLU 服务时的鉴权头（可选） |
| `dump_dir` | `D:\tmp\r1\dump_raw` | 协议抓包目录（req/resp） |
| `audio_dir` | `D:\tmp\r1\dump_audio` | 上行 Opus/Ogg 音频落盘目录 |
| `bind_log` | `D:\tmp\r1\bind_access.log` | bindsvc 访问日志 |
| `log_buf` | `800` | 内存日志环形缓冲条数（WebUI 日志页） |
| `llm_chat` | `true` | 聊天总开关。关 = 统一播报"聊天服务异常，请稍后再试" |
| `llm_api` | `""` | 空 = 内置 MiniCPM4-0.5B；填 = 外部 llama.cpp 地址（自动补 `/v1/chat/completions`） |
| `web_search` | `false` | 允许 LLM 联网搜索（仅外部接口；建议开，会增加 1-3s） |
| `music_enabled` | `true` | 音乐 overlay 开关 |
| `music_limit` | `20` | 每源搜索候选数（1-50） |
| `probe_timeout_s` | `3.0` | 直链探测超时（只保留 200/206 + `audio/*`） |

除监听地址等启动期绑定项外，配置保存后热生效（WebUI`/settings` 或 `POST /api/config`）。

## 工作原理

### 设备语音协议（`:8080`）

- 设备把一句话切成约 17 个 Opus 分片，POST 到 `/trafficRouter/cs`（`P:` 头带 SID）
- 中间帧：返回 200 空 body；末帧：`Content-Length: 0` + `TP:` 头
- 末帧到达时：把本 SID 的 Opus 拼成 Ogg → 本地 ASR → SLU → 生成 NLU JSON → 按设备 W510 头格式回传
- `nlu_mode=cloud` 时原样转发真实云端（`upstream`），拿到云端 NLU 后仍可做 music/radio 改写

### 本地 NLU（`custom`）

```
Opus→Ogg ──> SenseVoice(sherpa-onnx, CPU) ──> 文本
                                            ├─ 规则底座（新闻/要闻→chat 等，slu_ernie._RULES）
                                            └─ utc-nano 零样本意图 + uie-nano 槽位(CPU)
                                            └─ 结构化: domain → cn.yunzhisheng.* intent/result
```

- chat 意图 → `qa_llm.answer()`：提示词约束 + 工具（`web_search` / `news` / `history_today`），
  由模型自主决定是否搜索；无正则、无人工路由
- 失败/关闭/空答案 → 统一 `"聊天服务异常，请稍后再试"`，绝不返回空文本

### 聊天 LLM（外部 llama.cpp 推荐参数）

```bat
llama-server -m Qwen3.5-4B-Q4_K_M.gguf --host 127.0.0.1 --port 12345 ^
  --flash-attn off --load-mode none -t 16 -c 4096 -np 1 -ngl 99 ^
  --batch-size 512 --ubatch-size 128
```

- 老 Pascal 卡（P104-100 等）flash-attn 会 CUDA 崩溃，必须 off
- 本项目请求里固定带 `chat_template_kwargs: {"enable_thinking": false}`
  （Qwen3 系默认思考模式会导致 content 为空、工具调用不稳定）
- 单轮工具调用超时 20s；实测端到端（含搜索）3-5s，在设备 10-12s 预算内

### 音乐 overlay

- 命中音乐意图 → 网易/酷狗/咪咕并发搜索 → 去重 → 直链探测（必须 200/206 且 `audio/*`）
- 命中后把 `musicinfo[].url` 重写为 `<media_base>/media?u=<base64url(真实URL)>`
- `/media` 反向代理透传 Range/HEAD，设备播放器只和本机打交道

### 广播电台（`cn.yunzhisheng.broadcast`，独立域）

- `data/radio.json` 维护本地可播电台（蜻蜓 64k mp3 直链，默认 22 台）
- 原话匹配：中文数字归一（九八七→987）、频率（98.7/987）、台名/别名；
  "交通广播"这类泛称优先命中本地台（表内福建台在前）
- 返回设备原生广播域：`semantic.intent.station` + `data.result.rate64_ts_url`；
  设备 `dealBroadcastPlayService` 只要该字段非空就自动 `play(true)` 并 TTS"正在播放<station>"
- 注意设备端 Gson 类型严格：`source`/`channel_id`/`schedule_id` 必须是数字，
  否则整个 NLU 反序列化失败（设备报"网络连接失败"）
- 直播流无 Content-Length；蜻蜓对 HEAD 返回 400，`/media` 已内置 GET 探头回退

## WebUI 与调试 API（`:9000`）

| 路径 | 说明 |
| --- | --- |
| `/` | 状态页（ASR/LLM/拦截计数/最近日志） |
| `/settings` | 设置页（llm_chat、llm_api、web_search、nlu_mode、music 等，保存热生效） |
| `/logs` | 日志页 |
| `/api/status` | 状态 JSON（含当前生效配置） |
| `/api/config` | GET 读取 / POST 修改配置 |
| `/health`、`/asr`、`/slu`、`/nlu` | 调试接口（文本模式 ASR / SLU / 端到端 NLU） |

## 目录结构

```
<项目根>（仓库根即部署目录）
├── start.py                  # 唯一入口：起 :8080/:9000/:19999 + 模型预热
├── r1svc\
│   ├── config.py             # 默认配置/读写/运行时视图
│   ├── state.py              # 运行时状态、内存日志、会话与抓包
│   ├── protocol.py           # SID/帧解析/TP 判定/Ogg muxer/响应构造
│   ├── asrproxy.py           # :8080 协议服务（云透传 + custom NLU + music/radio overlay）
│   ├── music.py              # 三源搜索/去重/probe/响应模板
│   ├── radio.py              # 广播电台匹配 + broadcast 域响应
│   ├── media.py              # /media?u= 流代理（Range/HEAD，直播回退）
│   ├── nlu.py                # 进程内 ASR+SLU→NLU JSON（chat 分支接 LLM）
│   ├── bindsvc.py            # :19999 绑定仿真
│   ├── webui.py              # :9000 WebUI/API
│   └── asr_engine\           # SenseVoice、SLU(utc/uie)、qa_llm（LLM+工具）
├── data\
│   ├── config.json           # 运行配置（UTF-8 无 BOM）
│   └── radio.json            # 本地电台表
├── tests\                    # pytest（73 用例）
├── dump_raw\ / dump_audio\   # 协议/音频抓包
└── asr-slu\                  # venv + ASR 模型/运行时（不入库）
```

## 常见问题

- **设备说"网络连接失败，请检查"**：先分两步排查——
  1) 看 `dump_raw\*_resp.hdr` 里 JSON 是否合法、字段类型是否符合设备（int/string 不匹配会整体反序列化失败）；
  2) 看 nginx access log 有没有随后的 `GET /media` 且 200。
     没有 `/media` 请求基本是 NLU 响应被设备丢弃；有请求但很快断开则是播放器等流/等首包。
- **音乐不播**：直链必须 200/206 + `audio/*`；HLS/.m3u8/.ts 一律不要。
- **配置被重置**：`config.json` 带 BOM 会导致读取失败回退默认值，必须 UTF-8 无 BOM。
- **启动后终端卡住**：前台运行会占终端属正常；日常用 `schtasks /run /tn r1svc` 后台跑。
- **ASR 首次响应慢**：首句会付 ONNX 图优化成本，`start.py` 启动时已做静音预热。

## 相关文档（doc/）

| 文档 | 内容 |
| --- | --- |
| `doc/nlu-protocol.md` | 设备上传/响应协议抓包实测 + 各域响应样例 |
| `doc/nlu-domains.md` | 设备 NLU 域全景（scheme/代码/handler 链路） |
| `doc/voice-assistant.md` | 设备语音链路研究（唤醒/录音/上传/劫持/播放） |

## 依赖

- Windows 10/11（PowerShell 5.1），Python 3.12
- `asr-slu\requirements.txt`（paddlepaddle、paddlenlp、sherpa 相关、transformers 等）+ `httpx` + `pytest`
- 可选：WSL + nginx（:80 转发）、llama.cpp（外部 LLM）
