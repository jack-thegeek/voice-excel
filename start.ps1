# =============================================
#  voice-excel 一键启动脚本（PowerShell）
#  自动检查端口占用 -> 选择可用端口 -> 启动服务并打开浏览器
# =============================================

$ErrorActionPreference = "Stop"

# 切换到脚本所在目录
Set-Location -Path $PSScriptRoot

$Host.UI.RawUI.WindowTitle = "voice-excel 语音修改成绩表"

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  voice-excel 语音修改成绩表 启动器" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

# ---------- 1. 检查虚拟环境 ----------
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "[错误] 未找到虚拟环境: $python" -ForegroundColor Red
    Write-Host "请先运行以下命令安装依赖:" -ForegroundColor Yellow
    Write-Host "    uv venv" -ForegroundColor Yellow
    Write-Host "    uv pip install fastapi uvicorn[standard] openpyxl torch torchaudio funasr soundfile" -ForegroundColor Yellow
    Write-Host "    uv pip install sherpa-onnx     # 可选的轻量引擎" -ForegroundColor Yellow
    Read-Host "`n按回车键退出"
    exit 1
}

# ---------- 1b. 检查两个语音引擎的依赖 ----------
$engineChk = & $python -c "import engines; print('|'.join(f'{e['id']}:{int(e['available'])}' for e in engines.list_engines()))" 2>$null
if ($engineChk) {
    foreach ($part in ($engineChk -split '\|')) {
        $id, $avail = $part -split ':'
        if ($avail -eq '1') {
            Write-Host "[引擎] $id 可用" -ForegroundColor Green
        } else {
            Write-Host "[引擎] $id 不可用（缺依赖，不影响其他引擎）" -ForegroundColor Yellow
        }
    }
}

# ---------- 2. 查找可用端口（8765 起，最多探测 20 个）----------
function Test-PortFree([int]$p) {
    return -not [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

$port = 8765
for ($i = 0; $i -lt 20; $i++) {
    if (Test-PortFree $port) { break }
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $ownerName = "未知进程"
    if ($owner) {
        $proc = Get-Process -Id $owner.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) { $ownerName = $proc.ProcessName }
    }
    Write-Host "[提示] 端口 $port 正被 $ownerName 占用，尝试下一个端口..." -ForegroundColor Yellow
    $port++
}
if (-not (Test-PortFree $port)) {
    Write-Host "[错误] 8765-8784 端口均被占用，请关闭占用程序后重试。" -ForegroundColor Red
    Read-Host "`n按回车键退出"
    exit 1
}

# ---------- 3. 启动服务 ----------
Write-Host "[启动] 服务地址: http://127.0.0.1:$port/" -ForegroundColor Green
Write-Host "[提示] 浏览器将自动打开；默认引擎 sherpa-onnx 首次需准备约 237MB 模型。" -ForegroundColor Green
Write-Host "[提示] 页面「录入设置 → 语音引擎」可切换 FunASR（精度高，切过去才加载）。" -ForegroundColor Green
Write-Host "[提示] 关闭本窗口即停止服务。" -ForegroundColor Green
Write-Host ""

$env:HOST = "127.0.0.1"
$env:PORT = "$port"

& $python (Join-Path $PSScriptRoot "main.py")
$code = $LASTEXITCODE
Write-Host ""
if ($code -ne 0) {
    Write-Host "[错误] 服务异常退出，退出码: $code" -ForegroundColor Red
} else {
    Write-Host "[已停止] 服务已正常退出。" -ForegroundColor Cyan
}
Read-Host "按回车键关闭窗口"
exit $code
