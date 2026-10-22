<#
.SYNOPSIS
    通过 rootd (:31337) 在斐讯 R1 上执行命令并取回输出

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File rootshell.ps1
    powershell -ExecutionPolicy Bypass -File rootshell.ps1 -Cmd "id","mount -o remount,rw /system","ls /system/bin"
#>
param(
    [string]$Ip = "192.168.123.115",
    [int]$Port = 31337,
    [string[]]$Cmd = @("id", "getenforce"),
    [int]$WaitMs = 4000
)

$ErrorActionPreference = "Stop"
$client = New-Object System.Net.Sockets.TcpClient
try { $client.Connect($Ip, $Port) } catch { Write-Host "[-] connect $Ip`:$Port failed: $_" -ForegroundColor Red; exit 1 }
$stream = $client.GetStream()
$stream.ReadTimeout = 500

$marker = "R1_EOF_$(Get-Random)"
$sb = New-Object System.Text.StringBuilder
foreach ($c in $Cmd) { [void]$sb.AppendLine($c) }
[void]$sb.AppendLine("echo $marker")

$data = [System.Text.Encoding]::ASCII.GetBytes($sb.ToString())
$stream.Write($data, 0, $data.Length)
$stream.Flush()

$out = New-Object System.Text.StringBuilder
$buf = New-Object byte[] 8192
$deadline = (Get-Date).AddMilliseconds($WaitMs)
while ((Get-Date) -lt $deadline) {
    try {
        $n = $stream.Read($buf, 0, $buf.Length)
        if ($n -le 0) { break }
        [void]$out.Append([System.Text.Encoding]::ASCII.GetString($buf, 0, $n))
        if ($out.ToString() -match [regex]::Escape($marker)) { break }
    } catch { }
}
$client.Close()

$text = $out.ToString() -replace "\r", ""
$text = $text -replace [regex]::Escape($marker) + "[\s\S]*$", ""
Write-Output $text.Trim()
