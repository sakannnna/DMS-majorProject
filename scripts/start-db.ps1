param([string]$Mongod = $env:MONGOD_EXE, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dataRoot = Join-Path $projectRoot '.local\mongo'
if (-not $CheckOnly -and (Get-NetTCPConnection -LocalPort 27019 -State Listen -ErrorAction SilentlyContinue)) {
    Write-Output '端口 27019 已有服务，请核对 MONGODB_URI，未启动第二个实例。'
    exit 0
}
# 显式路径优先；未指定时按 PATH、常见安装目录及原本机位置查找。
if (-not $Mongod) {
    $command = Get-Command mongod.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { $Mongod = $command.Source }
    if (-not $Mongod -and $env:ProgramFiles) {
        $serverRoot = Join-Path $env:ProgramFiles 'MongoDB\Server'
        $versions = Get-ChildItem -LiteralPath $serverRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object { try { [version]$_.Name } catch { [version]'0.0' } } -Descending
        foreach ($directory in $versions) {
            $candidate = Join-Path $directory.FullName 'bin\mongod.exe'
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $Mongod = $candidate; break }
        }
    }
    if (-not $Mongod -and (Test-Path -LiteralPath 'D:\MongoDB\Server\bin\mongod.exe' -PathType Leaf)) {
        $Mongod = 'D:\MongoDB\Server\bin\mongod.exe'
    }
}
if (-not $Mongod -or -not (Test-Path -LiteralPath $Mongod -PathType Leaf)) {
    throw '未找到 MongoDB Server。请安装服务端，并用 -Mongod 或环境变量 MONGOD_EXE 指定 mongod.exe 完整路径；仅安装 Compass 不够。'
}
$Mongod = (Resolve-Path -LiteralPath $Mongod).Path
if ($CheckOnly) { Write-Output $Mongod; exit 0 }
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
$logPath = Join-Path $projectRoot '.local\mongodb.log'
$process = Start-Process -FilePath $Mongod -ArgumentList @('--dbpath', ('"' + $dataRoot + '"'), '--bind_ip', '127.0.0.1', '--port', '27019', '--logpath', ('"' + $logPath + '"'), '--logappend') -WindowStyle Hidden -PassThru
Set-Content -LiteralPath (Join-Path $projectRoot '.local\mongodb.pid') -Value $process.Id
Write-Output ('MongoDB 已启动，PID=' + $process.Id + '，端口 27019；日志 ' + $logPath)
