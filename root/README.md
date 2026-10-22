# Phicomm R1 Root (CVE-2019-2215, ARM32)

斐讯 R1 音箱（RK3229 / Android 5.1 / 内核 3.10.0）提权工具。

利用 Android binder 驱动 CVE-2019-2215（`binder_thread` 释放后未从等待队列摘除的 UAF），
在 ARM32/3.10 上实现**任意内核地址写**，清零 `selinux_enforcing` 使 SELinux 进入
Permissive，然后通过 `setprop ctl.start` 让 init 以 root 执行我们放置的脚本，
最终得到一个 root shell（TCP 31337）与 setuid `/system/bin/su`。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `exp2224.c` | 漏洞利用源码。用法：`exp2224 <addr_hex> <value_hex>`，向内核地址写入 4 字节 |
| `exp_boot.c` | 开机持久化变体：成功后自动拉起 `/system/bin/.rd`（rootd） |
| `rootd.c` | 极简 root shell 服务（监听 31337，`exec /system/bin/sh`） |
| `su.c` | 极简 setuid-root su |
| `root.sh` | 提权后处理：remount rw、安装 su/.rd、启动 rootd |
| `persist.sh` | 可选：安装开机自动提权（替换 `/system/bin/rksmbd` + `build.prop` 触发器） |
| `onkey/` | 一键获取 root（Windows 脚本 + 设备端脚本 + 预编译 ARM 文件） |

## 原理要点

1. 打开 `/dev/binder`，向 context manager（handle 0）发一个**同步**事务：
   发送方线程的 `transaction_stack` 随即非空。
2. 读取 48 字节（只消费 `BR_NOOP + BR_TRANSACTION_COMPLETE`，抢在 SM 回复前），
   然后 `epoll_ctl(ADD)`。此时 `binder_poll()` 会把 epoll 的等待项注册到
   `&thread->wait` 而不是 `proc->wait`。
3. `BINDER_THREAD_EXIT` 释放 `binder_thread`（252 字节 → kmalloc-256），
   但 epoll 的等待项仍链在已释放的 `thread->wait` 上。
4. 阻塞的 `readv()`（32 个 iovec，正好 kmalloc-256）复用该块；子进程延迟后
   `EPOLL_CTL_DEL` 触发 `remove_wait_queue()` → `list_del` 改写我们内核态 iovec 数组。
5. 利用管道把改写后的 iovec 指向目标地址，完成任意内核写。

32 位（ARM）关键偏移：`wait = 0x2c`（spinlock 0x2c，task_list 0x30/0x34），
所以 `iovec[5].iov_len` 是自旋锁、`iovec[6]` 对应 task_list。
chunk 布局必须为 `{target, len, &test, 4, ...}`（in-place 改写后同一个 iovec 即目标）。

本机符号（无 KASLR，3.10 厂商内核，vmlinux.elf 可导出）：
`selinux_enforcing = 0xc0f7fb0c`、`commit_creds = 0xc0062e90`、
`prepare_kernel_cred = 0xc0063344`。

## 一键使用

见 [onkey/README.md](onkey/README.md)。

## 持久化（可选，需已 root）

```sh
# 设备上以 root 执行，参数为包含 exp_boot / rootd / su 的目录
sh persist.sh /sdcard/r1root
```

原理：把 `/system/bin/rksmbd` 换成 `exp_boot`；`build.prop` 追加
`sys.rksmbd.start=1`，开机时 init 的 `on property:sys.rksmbd.start=1 → start startsamba`
会在 **init 域（unconfined）** 执行它 → 利用成功 → Permissive + 拉起 rootd。
同时把 `/system/bin/rild` 换成 rootd 作为双保险（需 `chcon u:object_r:rild_exec:s0`）。
所有被替换文件均有 `.r1bak` 备份。

## 工厂 / 配网模式（救砖与初始配置）

| 模式 | SSID | 密码 | 说明 |
| --- | --- | --- | --- |
| 工厂模式 | `Phi_<MAC>` | `fei123456` | 产测热点（WPA2）。该模式下 IJetty（`:9090`）随系统自动启动，`onkey` 依赖的 uid1000 命令执行入口无需再手动拉起 |
| 工厂模式切换 | `Phi_SwitchFctyMod_GIF87A` | `fei123456` | SystemTool 的隐藏切换热点，用于进入/退出工厂模式 |
| 正常配网 | `Phicomm_R1_<后4位>` | 未提取 | 配网接口在 `:8989`（`GET /api/wifilist`、`POST /api/configwifi`） |

- 密码来源：`ProductionTest/WifiP2P.java`（`DEFAULT_SSID = "Phi_"`、`DEFAULT_PASSWORD = "fei123456"`）
  与 `SystemTool/MainService.java`（`SWITCH_WIFI_SSID = "Phi_SwitchFctyMod_GIF87A"`、`SWITCH_WIFI_PWD = "fei123456"`）。
- 进入工厂模式（uid1000 或 root）：`service call FXSystemPrivate 1 i32 1`；
  退回正常模式：`service call FXSystemPrivate 1 i32 0`。写入 `/private/factory.conf`，**重启后生效**。
- 工厂模式启动时会清理 `/cache`、`/data/local.prop`、`/data/etc`（`onkey` 每次都会重新写入，不受影响）。
- 救砖流程：若开机后没有连上家里的 WiFi，用手机/PC 连 `Phi_*`（密码 `fei123456`），
  工厂模式热点网关固定为 `192.168.43.1` → `adb connect 192.168.43.1:5555`，
  执行 `setSysMode(0)` 后重启即回到正常模式。

## 风险提示

- `rootd` 监听 `0.0.0.0:31337` 且不需要认证，**局域网内任何人都能拿到 root**。
  请仅在可信网络使用，或自行加防火墙规则。
- 利用失败时内核可能小幅 hang（系统冻结数秒~数十秒），通常可自行恢复。

## 致谢

- Jann Horn / Project Zero 原始分析与 PoC（CVE-2019-2215）
- timwr / quirckr00t 的 su98 及衍生 3.18 移植（iovec 技巧）
