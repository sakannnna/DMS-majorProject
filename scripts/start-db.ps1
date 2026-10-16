param([string]$Mongod = 'D:\MongoDB\Server\bin\mongod.exe')
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dataRoot = Join-Path $projectRoot '.local\mongo'
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
if (Get-NetTCPConnection -LocalPort 27019 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output '端口 27019 已有服务，请核对 MONGODB_URI，未启动第二个实例。'
    exit 0
}
if (-not (Test-Path -LiteralPath $Mongod)) { throw '请用 -Mongod 指定 mongod.exe 完整路径' }
$logPath = Join-Path $projectRoot '.local\mongodb.log'
$process = Start-Process -FilePath $Mongod -ArgumentList @('--dbpath', ('"' + $dataRoot + '"'), '--bind_ip', '127.0.0.1', '--port', '27019', '--logpath', ('"' + $logPath + '"'), '--logappend') -WindowStyle Hidden -PassThru
Set-Content -LiteralPath (Join-Path $projectRoot '.local\mongodb.pid') -Value $process.Id
Write-Output ('MongoDB 已启动，PID=' + $process.Id + '，端口 27019；日志 ' + $logPath)
