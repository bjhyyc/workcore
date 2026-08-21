param(
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$url = "http://127.0.0.1:4173/"
$entry = Join-Path $root "scripts\start-production.mjs"
$buildEntry = Join-Path $root "dist\server\index.js"

if (-not (Test-Path -LiteralPath $buildEntry)) {
  throw "未找到离线构建。请先在项目目录运行 npm run build。"
}

$node = (Get-Command node -ErrorAction Stop).Source

function Test-WorkCoreLocalPage {
  try {
    $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1
    return $response.StatusCode -eq 200 -and $response.Content -match "WorkCore E6|Loading review engine"
  } catch {
    return $false
  }
}

if (-not (Test-WorkCoreLocalPage)) {
  Start-Process `
    -FilePath $node `
    -ArgumentList @($entry, "--hostname", "127.0.0.1", "--port", "4173") `
    -WorkingDirectory $root `
    -WindowStyle Hidden

  $ready = $false
  for ($attempt = 0; $attempt -lt 40; $attempt += 1) {
    Start-Sleep -Milliseconds 250
    if (Test-WorkCoreLocalPage) {
      $ready = $true
      break
    }
  }

  if (-not $ready) {
    throw "本地 R14 页面未能在 10 秒内启动。"
  }
}

if (-not $NoBrowser) {
  Start-Process $url
}
