param(
    [ValidateSet("setup", "test", "once", "run")]
    [string]$Action = "test"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $PSScriptRoot

function Invoke-SystemPython {
    param([string[]]$PythonArgs)

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 @PythonArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Python command failed with exit code $LASTEXITCODE"
        }
        return
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python @PythonArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Python command failed with exit code $LASTEXITCODE"
        }
        return
    }

    throw "Python 3.12+ is required. Install Python and run setup again."
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $name, $value = $line -split "=", 2
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
}

function Ensure-LocalFiles {
    if (-not (Test-Path "config.yaml")) {
        Copy-Item (Join-Path $RepoRoot "config.example.yaml") "config.yaml"
        Write-Host "Created config.yaml from root config.example.yaml"
    }
    if (-not (Test-Path ".env")) {
        Copy-Item (Join-Path $RepoRoot ".env.example") ".env"
        Write-Host "Created .env from root .env.example"
    }
    if (-not (Test-Path "data")) {
        New-Item -ItemType Directory -Path "data" | Out-Null
    }
}

function Ensure-Venv {
    if (-not (Test-Path ".venv\\Scripts\\python.exe")) {
        Write-Host "Creating .venv ..."
        Invoke-SystemPython -PythonArgs @("-m", "venv", ".venv")
    }

    if (-not (Test-Path ".venv\\Scripts\\python.exe")) {
        throw "Virtual environment creation failed."
    }
}

function Setup {
    Ensure-LocalFiles
    Ensure-Venv
    $python = Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe"
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $python -m pip install -e "$RepoRoot[dev]"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Windows setup complete. Root source is installed editable."
}

function Prepare-Runtime {
    Ensure-LocalFiles
    if (-not (Test-Path ".venv\\Scripts\\python.exe")) {
        throw "Virtual environment not found. Run setup first."
    }
    Import-DotEnv ".env"
    $env:SALE_BOT_CONFIG = (Join-Path $PSScriptRoot "config.yaml")
    $env:SALE_BOT_DB = (Join-Path $PSScriptRoot "data\\sale_bot-win.sqlite3")
}

switch ($Action) {
    "setup" {
        Setup
    }
    "test" {
        Prepare-Runtime
        $python = Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe"
        & $python -m ruff check (Join-Path $RepoRoot "src") (Join-Path $RepoRoot "tests")
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $python -m pytest -q (Join-Path $RepoRoot "tests")
        exit $LASTEXITCODE
    }
    "once" {
        Prepare-Runtime
        $python = Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe"
        & $python -m sale_bot.main --once
        exit $LASTEXITCODE
    }
    "run" {
        Prepare-Runtime
        $python = Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe"
        & $python -m sale_bot.main
        exit $LASTEXITCODE
    }
}
