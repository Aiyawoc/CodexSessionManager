param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows) {
    throw "check_windows.ps1 must run on Windows"
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$ConfiguredUvCache = [Environment]::GetEnvironmentVariable("UV_CACHE_DIR", "Process")
$env:UV_CACHE_DIR = if ($ConfiguredUvCache) { $ConfiguredUvCache } else { Join-Path $RepoRoot "build\.uv-cache" }
$CheckRoot = Join-Path ([IO.Path]::GetTempPath()) ("csm-check-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $CheckRoot | Out-Null

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit code $LASTEXITCODE"
    }
}

function Assert-GeneratedText {
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    $ActualText = [IO.File]::ReadAllText($Actual).Replace("`r`n", "`n")
    $ExpectedText = [IO.File]::ReadAllText($Expected).Replace("`r`n", "`n")
    if ($ActualText -cne $ExpectedText) {
        throw "generated file is stale: $Expected"
    }
}

try {
    $GeneratedMain = Join-Path $CheckRoot "ui_main_window.py"
    $GeneratedPrompt = Join-Path $CheckRoot "ui_precompact_prompt.py"
    $GeneratedResources = Join-Path $CheckRoot "resources_rc.py"
    Invoke-Checked -Program "uv" -Arguments @(
        "run", "--locked", "pyside6-uic",
        "src/codex_session_manager/gui/main_window.ui", "-o", $GeneratedMain
    )
    Invoke-Checked -Program "uv" -Arguments @(
        "run", "--locked", "pyside6-uic",
        "src/codex_session_manager/gui/precompact_prompt.ui", "-o", $GeneratedPrompt
    )
    Invoke-Checked -Program "uv" -Arguments @(
        "run", "--locked", "pyside6-rcc",
        "src/codex_session_manager/gui/resources.qrc", "-o", $GeneratedResources
    )
    Assert-GeneratedText $GeneratedMain "src/codex_session_manager/gui/ui_main_window.py"
    Assert-GeneratedText $GeneratedPrompt "src/codex_session_manager/gui/ui_precompact_prompt.py"
    Assert-GeneratedText $GeneratedResources "src/codex_session_manager/gui/resources_rc.py"

    Invoke-Checked -Program "uv" -Arguments @("run", "--locked", "ruff", "format", "--check", ".")
    Invoke-Checked -Program "uv" -Arguments @("run", "--locked", "ruff", "check", ".")
    Invoke-Checked -Program "uv" -Arguments @("run", "--locked", "mypy", "src/codex_session_manager")
    $env:QT_QPA_PLATFORM = "offscreen"
    Invoke-Checked -Program "uv" -Arguments @("run", "--locked", "pytest")
    Invoke-Checked -Program "uv" -Arguments @(
        "run", "--locked", "python", "scripts/validate_skill.py",
        "skills/manage-codex-sessions"
    )
}
finally {
    if (Test-Path -LiteralPath $CheckRoot) {
        Remove-Item -LiteralPath $CheckRoot -Recurse -Force
    }
}
