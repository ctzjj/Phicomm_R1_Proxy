# r1tool (Go)

Phicomm R1 工具集（Go 实现）：绑定、语音劫持、回显调试，以及**配网（Wi-Fi provisioning）**。
原仓库中的 PHP PoC（`bind.php`、`asr_proxy.php`、`home_server.php` 与 `src/Provider/*`）已移除，
下表的「原 PHP 版」列仅保留对照关系。

只用 Go 标准库，无第三方依赖（原 PHP 版依赖 Swoole / Guzzle）。

## 构建

```sh
cd go
go build -o r1tool ./cmd/r1tool
# Windows: go build -o r1tool.exe ./cmd/r1tool
```

要求 Go >= 1.21。

## 命令

| 命令 | 原 PHP 版 | 说明 |
| --- | --- | --- |
| `r1tool bind` | `bind.php` | 绑定辅助：把 `aios-home.hivoice.cn` 指到本机，`/getUserInfo` 返回 `{"status":"0"}`，音箱即认为已绑定 |
| `r1tool asr` | `asr_proxy.php` | 语音劫持：把 `asrv3.hivoice.cn` 指到本机，转发到真实 ASR（默认 `47.102.50.144:80`），识别到点歌意图时用网易云搜索结果替换回复 |
| `r1tool home` | `home_server.php` | 简单 TCP 回显服务，用于观察音箱连接了什么 |
| `r1tool wifi` | 新增 | 列出音箱（配网模式）扫到的 Wi-Fi |
| `r1tool provision` | 新增 | 让音箱连接指定 Wi-Fi（一键配网） |

### 绑定

```sh
r1tool bind -addr 0.0.0.0:19999
# 把 aios-home.hivoice.cn 解析到本机 IP，然后对音箱说“小讯小讯”触发绑定查询
```

### 语音劫持

```sh
r1tool asr -addr :80 -upstream 47.102.50.144:80 -v
# 把 asrv3.hivoice.cn 解析到本机 IP（80 端口需要 root / 管理员权限）
```

实现说明：每个连接按 `Content-Length` 分帧，逐条转发；只有 JSON 且判定为点歌意图的
回复才会被替换（其余原样透传，避免改动无关响应）。点歌意图规则与 PHP 一致：

- `code == SEARCH_ARTIST` / `SEARCH_CATEGORY` → `semantic.intent.keyword`
- `^我想听(.*)的歌$`（ungreedy）→ `$1`
- `^我想听(.*?)的(.*)` → `$2 $1`
- `^播放(.*?)的(.*)` → `$2 $1`

搜索默认网易云（`music.163.com` 的 `linux/forward` 接口 + `eparams` AES-128-ECB 加密），
`music.Migo` 为咪咕实现，`music.Kugo` 与原 PHP 一样仅为占位。

### 配网（一键）

音箱进入配网模式后会开热点 `Phicomm_R1_xxxx`（网关 `192.168.43.1`），HTTP 服务在
`8989` 端口。让电脑连上该热点，然后：

```sh
# 查看音箱扫到的网络
r1tool wifi -gw 192.168.43.1

# 配置音箱连接家里的 Wi-Fi
r1tool provision -gw 192.168.43.1 -ssid Tomato -pass 'wlan@518' -secure WPA
```

可选参数：`-port`（默认 8989）、`-mac`（指定 BSSID）、`-scan`（配置前先列出网络）、
`-json`（`wifi` 输出原始 JSON）。成功后音箱切换到 STA 模式，电脑重新连回原网络即可。

接口：

- `GET /api/getwifilist`：触发扫描（扫描中可能返回 `[]`）
- `GET /api/wifilist`：返回 `[{level,mac,secure,ssid}]`
- `POST /api/configwifi`：`{"ssid","password","secure","mac"}` → 设备信息 JSON

> 提示：工厂模式热点是 `Phi_<MAC>`，密码 `fei123456`，详见 `../root/README.md`。

## 目录

```
go/
├── cmd/r1tool/          命令行入口
└── internal/
    ├── asr/             语音劫持 TCP 代理（原 asr_proxy.php）
    ├── bind/            绑定接口（原 bind.php）
    ├── home/            回显服务（原 home_server.php）
    ├── music/           点歌意图识别 + 网易云/咪咕/酷狗 + 数据模板
    ├── provision/       配网客户端（wifilist / configwifi）
    └── util/            HTTP 消息解析与 Content-Length 重建
```

## 测试

```sh
go test ./...
```

覆盖：HTTP 消息重建、点歌意图正则、AES-128-ECB（FIPS-197 向量）、配网接口解析、Ogg/Opus 封装。

## 语音音频与协议

`r1tool asr` 可以把每句话的 Opus 音频按会话聚合并落盘/转发：

```sh
# 落盘：每句一个 Ogg/Opus（16 kHz 单声道，可直接 ffmpeg 转 WAV）
r1tool asr -addr 127.0.0.1:8080 -audio-dir ./audio

# 转发：POST audio/ogg 到自己的 ASR / 大模型服务
r1tool asr -addr 127.0.0.1:8080 -audio-dir ./audio -forward http://127.0.0.1:9000/asr

# 离线转换已抓到的 dump
r1tool audiodump -dir ./dump -out ./audio
```

上传/响应的完整协议（响应头 `CT/RS/PN/SID`、`code`/`semantic.intent.operations`、
点歌 `data.result.musicinfo`、最小可用 JSON 等）见
[`../doc/nlu-protocol.md`](../doc/nlu-protocol.md)。
