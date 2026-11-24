$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $async = $tcp.BeginConnect("127.0.0.1", 11434, $null, $null)
    if ($async.AsyncWaitHandle.WaitOne(300, $false) -and $tcp.Connected) {
        Write-Host "Ollama detected on 127.0.0.1:11434" -ForegroundColor Green
    } else {
        Write-Host "Ollama not detected on 127.0.0.1:11434 (use stub backend or start Ollama)" -ForegroundColor Yellow
    }
} finally {
    $tcp.Close()
}

Start-Process "http://127.0.0.1:8000"
& "$Root\.venv\Scripts\python.exe" -m uvicorn agentic_trading.api.app:create_app --factory --host 127.0.0.1 --port 8000
