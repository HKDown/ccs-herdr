#Requires -Version 5.1
<#
.SYNOPSIS
    ccs-tool 端到端冒烟测试（Windows PowerShell 5.1 / PowerShell 7 均可运行）。

.DESCRIPTION
    按 CLI 契约依次验证：
      daemon start -> new smoke -- cmd.exe -> ls --json 含 smoke -> send -> 等 1s
      -> log 含 SMOKE_OK -> rename -> ls 含 smoke2 -> kill -> rm -> ls 无残留 -> daemon stop

    每一步打印 [PASS] / [FAIL]，最后给出汇总；全部通过 exit 0，否则 exit 1。

    状态目录（CCS_HOME）：
      * 默认使用 %USERPROFILE%\.ccs（若环境变量 CCS_HOME 已设置则用它）。
      * 若该目录不可写（例如受限沙箱、只读配置），自动回退到
        %TEMP%\ccs-smoke-<PID>，再不行回退到脚本同目录的 .ccs-smoke-<PID>，
        并在测试结束后清理；因此不会破坏你已有的 ccs 会话。
      * 也可显式指定: -CcsHome D:\some\dir

    预期报错说明（核心 ccs.py 还在并行开发时）：
      * ccs.py 尚不存在            -> 预检 FAIL，后续步骤会连环 FAIL，属于预期。
      * 守护进程 / ConPTY 未实现   -> daemon start 或 new 失败，后续连环 FAIL。
      * 本测试不依赖 claude 是否安装，用的是 cmd.exe，因此 claude 缺失不影响。
      * 若中文/输出乱码：脚本已 chcp 65001 并设置 UTF-8 输出；仍乱码多为终端字体/代码页问题。

.PARAMETER CcsPy
    ccs.py 的路径，默认取脚本同目录下的 ccs.py。

.PARAMETER CcsHome
    测试使用的状态目录；默认 %USERPROFILE%\.ccs（或已有的 CCS_HOME）。

.PARAMETER KeepDaemon
    测试结束后不执行 daemon stop（默认会停掉守护进程）。

.PARAMETER KeepState
    测试结束后不清理“自动回退”的临时状态目录（默认清理；默认状态目录永远不会被删）。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\test_smoke.ps1

.EXAMPLE
    pwsh -NoProfile -File .\test_smoke.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\test_smoke.ps1 -CcsHome D:\tmp\ccs-test
#>
[CmdletBinding()]
param(
    [string]$CcsPy,
    [string]$CcsHome,
    [switch]$KeepDaemon,
    [switch]$KeepState
)

$ErrorActionPreference = 'Continue'

# 统一 UTF-8 输出，避免中文乱码
try {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
    chcp 65001 > $null
} catch { }

if ([string]::IsNullOrWhiteSpace($CcsPy)) { $CcsPy = Join-Path $PSScriptRoot 'ccs.py' }
try { $CcsPy = [System.IO.Path]::GetFullPath($CcsPy) } catch { }

$script:Pass = 0
$script:Fail = 0
$Session = 'smoke'
$Session2 = 'smoke2'

# ---------------------------------------------------------------- 状态目录
function Test-DirWritable {
    param([string]$Path)
    try {
        New-Item -ItemType Directory -Force -Path $Path -ErrorAction Stop | Out-Null
        $probe = Join-Path $Path ('probe-' + [guid]::NewGuid().ToString('N') + '.tmp')
        [System.IO.File]::WriteAllText($probe, 'ok')
        Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

$homeMode = 'default'
$requestedHome = ''
if (-not [string]::IsNullOrWhiteSpace($CcsHome)) {
    $homeMode = 'explicit'
    $requestedHome = [System.IO.Path]::GetFullPath($CcsHome)
} elseif (-not [string]::IsNullOrWhiteSpace($env:CCS_HOME)) {
    $homeMode = 'env'
    $requestedHome = [System.IO.Path]::GetFullPath($env:CCS_HOME)
} else {
    $requestedHome = Join-Path $env:USERPROFILE '.ccs'
}

$testHome = $requestedHome
$fallbackUsed = $false
if (-not (Test-DirWritable $testHome)) {
    Write-Host ("[警告] 状态目录不可写: " + $testHome + "，尝试使用临时目录。") -ForegroundColor Yellow
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:TEMP)) {
        $candidates += (Join-Path $env:TEMP ('ccs-smoke-' + $PID))
    }
    $candidates += (Join-Path $PSScriptRoot ('.ccs-smoke-' + $PID))
    $testHome = ''
    foreach ($cand in $candidates) {
        if (Test-DirWritable $cand) { $testHome = $cand; break }
    }
    if ($testHome -eq '') {
        Write-Host "[FAIL] 找不到可写的状态目录，无法继续测试。" -ForegroundColor Red
        Write-Host ("       已尝试: " + (($candidates) -join ' ; ')) -ForegroundColor DarkGray
        exit 1
    }
    $fallbackUsed = $true
}
$env:CCS_HOME = $testHome

# ---------------------------------------------------------------- 工具函数
function Get-BriefText {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $lines = @(($Text -replace "\r", '') -split "\n" | Where-Object { $_.Trim() -ne '' })
    if ($lines.Count -eq 0) { return '' }
    $start = [Math]::Max(0, $lines.Count - 3)
    return (($lines[$start..($lines.Count - 1)]) -join ' | ')
}

function Write-Result {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $safe = Get-BriefText $Detail
    if ($safe.Length -gt 300) { $safe = $safe.Substring(0, 300) + '...' }
    if ($Ok) {
        $script:Pass++
        Write-Host ("[PASS] " + $Name) -ForegroundColor Green
    } else {
        $script:Fail++
        Write-Host ("[FAIL] " + $Name) -ForegroundColor Red
    }
    if ($safe -ne '') { Write-Host ("       " + $safe) -ForegroundColor DarkGray }
    return $Ok
}

function Invoke-Ccs {
    param([string[]]$Arguments)
    $out = & python $CcsPy @Arguments 2>&1 | Out-String
    return [pscustomobject]@{ Code = $LASTEXITCODE; Out = $out }
}

function Test-CcsStep {
    param([string]$Name, [string[]]$Arguments)
    try {
        $r = Invoke-Ccs -Arguments $Arguments
        $detail = ("exit=" + $r.Code + "  " + $r.Out)
        return (Write-Result -Name $Name -Ok ($r.Code -eq 0) -Detail $detail)
    } catch {
        return (Write-Result -Name $Name -Ok $false -Detail ("异常: " + $_.Exception.Message))
    }
}

function Get-LsJson {
    $raw = ''
    try {
        $r = Invoke-Ccs -Arguments @('ls', '--json')
        $raw = $r.Out
        if ($r.Code -ne 0) {
            return [pscustomobject]@{ Ok = $false; Names = @(); Raw = $raw; Reason = ("ls 失败 exit=" + $r.Code) }
        }
        $obj = $raw.Trim() | ConvertFrom-Json -ErrorAction Stop
        $items = @()
        if ($obj -is [System.Array]) { $items = @($obj) }
        elseif ($null -ne $obj -and $null -ne $obj.PSObject.Properties['sessions']) { $items = @($obj.sessions) }
        elseif ($null -ne $obj) { $items = @($obj) }
        $names = @()
        foreach ($it in $items) {
            if ($null -eq $it) { continue }
            if ($it -is [string]) { $names += $it; continue }
            $prop = $it.PSObject.Properties['name']
            if ($null -ne $prop) { $names += [string]$prop.Value }
        }
        return [pscustomobject]@{ Ok = $true; Names = @($names); Raw = $raw; Reason = '' }
    } catch {
        return [pscustomobject]@{ Ok = $false; Names = @(); Raw = $raw; Reason = ("JSON 解析失败: " + $_.Exception.Message) }
    }
}

# ================= 开始 =================
Write-Host "== ccs-tool 端到端冒烟测试 ==" -ForegroundColor Cyan
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
Write-Host ("ccs.py   : " + $CcsPy)
if ($null -ne $pyCmd) { Write-Host ("python   : " + $pyCmd.Source) }
else { Write-Host "python   : 未找到" -ForegroundColor Red }
Write-Host ("状态目录 : " + $testHome + "  (" + $homeMode + ")")
if ($fallbackUsed) {
    Write-Host "           原始目录不可写，已自动回退；测试结束后会清理。" -ForegroundColor Yellow
}
Write-Host ""

$ccsExists = Test-Path -LiteralPath $ccsPy
Write-Result -Name "预检：ccs.py 存在" -Ok $ccsExists -Detail $CcsPy | Out-Null
if (-not $ccsExists) {
    Write-Host ""
    Write-Host "[说明] 未找到 ccs.py，后续步骤预期全部 FAIL（它由核心实现并行交付）。" -ForegroundColor Yellow
    Write-Host "       等 ccs.py 落地后重新运行本脚本即可。" -ForegroundColor Yellow
    Write-Host ""
}

# 预清理：保证脚本可重复运行（不存在时静默忽略，不计入 PASS/FAIL）
if ($ccsExists) {
    foreach ($n in @($Session, $Session2)) {
        & python $CcsPy kill $n 2>&1 | Out-Null
        & python $CcsPy rm $n 2>&1 | Out-Null
    }
    & python $CcsPy daemon stop 2>&1 | Out-Null
}

# ---------- 1. daemon start ----------
Test-CcsStep "daemon start" @('daemon', 'start') | Out-Null

# ---------- 2. new smoke -- cmd.exe ----------
Test-CcsStep ("new {0} -- cmd.exe" -f $Session) @('new', $Session, '--', 'cmd.exe') | Out-Null

# ---------- 3. ls --json 包含 smoke ----------
$ls1 = Get-LsJson
$ok3 = ($ls1.Ok -and ($ls1.Names -contains $Session))
$detail3 = ''
if (-not $ls1.Ok) { $detail3 = $ls1.Reason + "  " + $ls1.Raw }
else { $detail3 = "sessions=" + (@($ls1.Names) -join ',') }
Write-Result -Name ("ls --json 包含 " + $Session) -Ok $ok3 -Detail $detail3 | Out-Null

# ---------- 4. send smoke echo SMOKE_OK ----------
Test-CcsStep ("send {0} echo SMOKE_OK" -f $Session) @('send', $Session, 'echo SMOKE_OK') | Out-Null

# ---------- 5. 等待 1 秒 ----------
Start-Sleep -Milliseconds 1000

# ---------- 6. log 含 SMOKE_OK（最多尝试 4 次，每次间隔 500ms） ----------
$found = $false
$logDetail = ''
for ($i = 1; $i -le 4; $i++) {
    try {
        $r = Invoke-Ccs -Arguments @('log', $Session, '--bytes', '65536')
    } catch {
        $logDetail = "异常: " + $_.Exception.Message
        break
    }
    if ($r.Out -match 'SMOKE_OK') {
        $found = $true
        $logDetail = "第 $i 次命中，exit=" + $r.Code
        break
    }
    $logDetail = "第 $i 次未命中，exit=" + $r.Code + "  输出: " + $r.Out
    if ($i -lt 4) { Start-Sleep -Milliseconds 500 }
}
Write-Result -Name ("log {0} 含 SMOKE_OK" -f $Session) -Ok $found -Detail $logDetail | Out-Null

# ---------- 7. rename smoke smoke2 ----------
Test-CcsStep ("rename {0} {1}" -f $Session, $Session2) @('rename', $Session, $Session2) | Out-Null

# ---------- 8. ls --json 包含 smoke2 ----------
$ls2 = Get-LsJson
$ok8 = ($ls2.Ok -and ($ls2.Names -contains $Session2))
$detail8 = ''
if (-not $ls2.Ok) { $detail8 = $ls2.Reason + "  " + $ls2.Raw }
else { $detail8 = "sessions=" + (@($ls2.Names) -join ',') }
Write-Result -Name ("ls --json 包含 " + $Session2) -Ok $ok8 -Detail $detail8 | Out-Null

# 记录守护进程实例，供第 11 步比对（端口/pid 变化 = 守护进程中途重启）
$daemonBefore = Invoke-Ccs -Arguments @('daemon', 'status')

# ---------- 9. kill smoke2 ----------
Test-CcsStep ("kill {0}" -f $Session2) @('kill', $Session2) | Out-Null
Start-Sleep -Milliseconds 800

# ---------- 10. rm smoke2 ----------
Test-CcsStep ("rm " + $Session2) @('rm', $Session2) | Out-Null

# ---------- 11. 守护进程在 kill/rm 后应仍存活，且没有被重启 ----------
$daemonAfter = Invoke-Ccs -Arguments @('daemon', 'status')
$alive = ($daemonAfter.Code -eq 0)
$sameInstance = $false
if ($alive -and $null -ne $daemonBefore -and $daemonBefore.Code -eq 0) {
    $sameInstance = (($daemonBefore.Out.Trim()) -eq ($daemonAfter.Out.Trim()))
}
$daemonDetail = "before=" + (Get-BriefText $daemonBefore.Out) + "  after=" + (Get-BriefText $daemonAfter.Out)
Write-Result -Name "kill/rm 后守护进程仍存活且未重启" -Ok ($alive -and $sameInstance) -Detail $daemonDetail | Out-Null

# ---------- 12. 附加：清理后 ls 不再包含 smoke2 ----------
$ls3 = Get-LsJson
$ok11 = ($ls3.Ok -and -not ($ls3.Names -contains $Session2))
$detail11 = ''
if (-not $ls3.Ok) { $detail11 = $ls3.Reason + "  " + $ls3.Raw }
else { $detail11 = "sessions=" + (@($ls3.Names) -join ',') }
Write-Result -Name ("清理：ls 中已无 " + $Session2) -Ok $ok11 -Detail $detail11 | Out-Null

# ---------- 13. daemon stop ----------
if ($KeepDaemon) {
    Write-Host "[SKIP] daemon stop（已指定 -KeepDaemon）" -ForegroundColor Yellow
} else {
    Test-CcsStep "daemon stop" @('daemon', 'stop') | Out-Null
    Start-Sleep -Milliseconds 500
}

# ---------- 14. 清理自动回退的临时状态目录 ----------
if ($fallbackUsed -and -not $KeepState) {
    $removed = $false
    for ($i = 1; $i -le 3; $i++) {
        try {
            Remove-Item -LiteralPath $testHome -Recurse -Force -ErrorAction Stop
            $removed = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if ($removed) {
        Write-Host ("[INFO] 已清理临时状态目录: " + $testHome) -ForegroundColor DarkGray
    } else {
        Write-Host ("[INFO] 临时状态目录未能删除（守护进程可能刚退出）: " + $testHome) -ForegroundColor Yellow
    }
}

# ================= 汇总 =================
$total = $script:Pass + $script:Fail
Write-Host ""
if ($script:Fail -eq 0) {
    Write-Host ("== 汇总: 共 {0} 项，全部 PASS ==" -f $total) -ForegroundColor Green
    exit 0
} else {
    Write-Host ("== 汇总: 共 {0} 项，PASS {1}，FAIL {2} ==" -f $total, $script:Pass, $script:Fail) -ForegroundColor Red
    if (-not $ccsExists) {
        Write-Host "ccs.py 尚不存在，上述失败属于预期；等核心实现交付后重跑即可。" -ForegroundColor Yellow
    }
    exit 1
}
