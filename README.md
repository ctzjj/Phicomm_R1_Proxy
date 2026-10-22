# Phicomm_R1_Proxy

斐讯 R1 音箱工具集（Go 实现）：语音识别中间人、绑定、配网、提权。

- 语音劫持：把 `asrv3.hivoice.cn` 解析到运行本程序的服务器 IP，程序转发语音解析请求，
  命中「点歌」意图时替换为网易云搜索结果，其它请求原样透传。
- 配网：直接调用音箱配网页面（`:8989`）的接口扫描 WiFi 并写入配置。
- 提权：CVE-2019-2215（ARM32 / 内核 3.10），一键 root + 开机持久化，见 `root/`。

## 快速开始

```sh
cd go
go build -o r1tool ./cmd/r1tool
```

| 命令 | 作用 |
| --- | --- |
| `r1tool asr -addr :80 -upstream 47.102.50.144:80` | 语音劫持代理（`:80`，按 Content-Length 分帧转发） |
| `r1tool bind -addr 0.0.0.0:19999` | 音箱绑定接口（`/getUserInfo` → `{"status":"0"}`） |
| `r1tool home -addr 0.0.0.0:8883` | 回显服务器（调试用） |
| `r1tool wifi -gw 192.168.43.1` | 扫描音箱可见 WiFi（自动触发扫描并轮询结果） |
| `r1tool provision -gw 192.168.43.1 -ssid "SSID" -pass "PASSWORD"` | 一键配网 |

详细参数与实现说明见 [go/README.md](go/README.md)。

## 目录

| 路径 | 说明 |
| --- | --- |
| `go/` | Go 实现（唯一实现，原 PHP 版本已移除） |
| `root/` | R1 提权（CVE-2019-2215）+ 一键 root + 开机持久化，见 [root/README.md](root/README.md) |
| `doc/返回数据格式` | 语音服务返回样例（GBK 编码，历史文档） |

## 备注

- 点歌类语句（`我想听…的歌` / `我想听…的…` / `播放…的…`）会被改写为音乐播放应答；
  「小讯小讯，氛围灯」这类指令直接透传。
- 配网模式热点与工厂模式密码见 [root/README.md](root/README.md) 的「工厂 / 配网模式」一节。
