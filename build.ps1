[CmdletBinding()]
param(
    [ValidateSet("model", "evt0", "human", "dvt", "pvt", "mp")]
    [Alias("Stage")]
    [string]$VerifyStage = "model",
    [switch]$SkipBuild,
    [switch]$UseLock,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$pythonExe = if ($PythonPath) { $PythonPath } else { $venvPython }
$requirements = if ($UseLock) { "requirements-lock.txt" } else { "requirements.txt" }

function Test-WorkCorePython([string]$Python) {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        return $false
    }
    & $Python -c "import cadquery, numpy, trimesh, vtk" 2>$null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-WorkCorePython $pythonExe)) {
    if ($PythonPath) {
        throw "The supplied -PythonPath cannot import the pinned WorkCore dependencies."
    }
    if (Test-Path -LiteralPath (Join-Path $root ".venv")) {
        throw "The existing .venv is stale or incomplete. Remove it deliberately, then rerun .\build.ps1 to create a clean environment."
    }
    $bootstrap = Get-Command python -ErrorAction SilentlyContinue
    if (-not $bootstrap) {
        throw "No usable WorkCore virtual environment and no 'python' command were found. Install 64-bit CPython 3.12, then rerun .\build.ps1."
    }
    & $bootstrap.Source -m venv $venvPython.Replace("\Scripts\python.exe", "")
    if ($LASTEXITCODE -ne 0) { throw "Virtual-environment creation failed." }
    & $venvPython -m pip install --requirement (Join-Path $root $requirements)
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    $pythonExe = $venvPython
}

if (-not $SkipBuild) {
    & $pythonExe (Join-Path $root "cad\build.py")
    if ($LASTEXITCODE -ne 0) { throw "WorkCore model build failed with exit code $LASTEXITCODE." }
}

& $pythonExe (Join-Path $root "cad\verify_release.py") --stage $VerifyStage
if ($LASTEXITCODE -ne 0) {
    throw "The '$VerifyStage' gate is not released. See the structured failures above."
}
