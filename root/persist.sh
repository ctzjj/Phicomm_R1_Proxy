#!/system/bin/sh
# 可选：安装「开机自动提权 + root shell」持久化
# 需要已获得 root（先执行 onkey）
# 用法: persist.sh [包含 exp_boot/rootd/su 的目录]
#
# 原理：
#   /system/bin/rksmbd 被替换为 exp_boot（漏洞利用，成功后拉起 /system/bin/.rd）
#   /system/build.prop 追加 sys.rksmbd.start=1
#   开机时 init 的 `on property:sys.rksmbd.start=1 -> start startsamba`
#   会在 init 域（unconfined）执行它 -> 利用成功 -> SELinux Permissive + rootd
#   另外 /system/bin/rild 替换为 rootd（rild 域有 tcp_socket 权限），作为双保险
#   所有被替换文件都会生成 .r1bak 备份

D="${1:-/sdcard/r1root}"

for f in exp_boot rootd su; do
    [ -f "$D/$f" ] || { echo "[-] missing $D/$f"; exit 1; }
done

mount -o remount,rw /system || { echo "[-] remount rw failed"; exit 1; }

[ -f /system/bin/rksmbd.r1bak ]   || cp /system/bin/rksmbd   /system/bin/rksmbd.r1bak
[ -f /system/bin/rild.r1bak ]     || cp /system/bin/rild     /system/bin/rild.r1bak
[ -f /system/build.prop.r1bak ]   || cp /system/build.prop   /system/build.prop.r1bak

cp "$D/su"       /system/bin/su       && chmod 6755 /system/bin/su
cp "$D/rootd"    /system/bin/.rd      && chmod 755  /system/bin/.rd
cp "$D/exp_boot" /system/bin/rksmbd   && chmod 755  /system/bin/rksmbd

cp "$D/rootd"    /system/bin/rild     && chmod 755  /system/bin/rild
chcon u:object_r:rild_exec:s0 /system/bin/rild

grep -q '^sys.rksmbd.start=1' /system/build.prop || echo 'sys.rksmbd.start=1' >> /system/build.prop

mount -o remount,ro /system

echo "[+] persistence installed:"
echo "    /system/bin/rksmbd  = boot exploit (sys.rksmbd.start=1)"
echo "    /system/bin/rild    = rootd (rild domain)"
echo "    /system/bin/su      = setuid root"
echo "    backups: *.r1bak, /system/build.prop.r1bak"
echo "[*] reboot to verify"
