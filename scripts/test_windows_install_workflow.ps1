param(
    [Parameter(Mandatory = $true)][string]$BundlePath,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Windows install workflow must run on a real Windows AMD64 host"
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SourceBundle = (Resolve-Path $BundlePath).Path
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ("CSM 安装 验收 " + [Guid]::NewGuid().ToString("N"))
$TestHome = Join-Path $TestRoot "用户 Home"
$TestLocalAppData = Join-Path $TestRoot "本地 应用数据"
$TestCodexHome = Join-Path $TestRoot "Codex Home"
$Installer = Join-Path $RepoRoot "scripts\install_windows_user.ps1"
$PowerShell = (Get-Process -Id $PID).Path
$SavedEnvironment = @{}
$EnvironmentNames = @(
    "PATH", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
    "CSM_DATA_DIR", "CSM_CONFIG_DIR", "CSM_CACHE_DIR", "CSM_LOG_DIR",
    "CSM_CODEX_HOME", "CODEX_HOME", "CSM_APP_PATH"
)
foreach ($Name in $EnvironmentNames) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}

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

New-Item -ItemType Directory -Path @(
    $TestHome,
    $TestLocalAppData,
    $TestCodexHome,
    (Join-Path $TestRoot "data"),
    (Join-Path $TestRoot "config"),
    (Join-Path $TestRoot "cache"),
    (Join-Path $TestRoot "log")
) -Force | Out-Null

try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:HOME = $TestHome
    $env:USERPROFILE = $TestHome
    $env:LOCALAPPDATA = $TestLocalAppData
    $env:APPDATA = Join-Path $TestRoot "Roaming AppData"
    $env:CSM_DATA_DIR = Join-Path $TestRoot "data"
    $env:CSM_CONFIG_DIR = Join-Path $TestRoot "config"
    $env:CSM_CACHE_DIR = Join-Path $TestRoot "cache"
    $env:CSM_LOG_DIR = Join-Path $TestRoot "log"
    $env:CSM_CODEX_HOME = $TestCodexHome
    $env:CODEX_HOME = $TestCodexHome
    $Target = Join-Path $TestLocalAppData "CodexSessionManager"
    $env:CSM_APP_PATH = $Target

    $InstallArguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Installer,
        "-BundlePath", $SourceBundle, "-SkipUserPathUpdate"
    )
    Invoke-Checked -Program $PowerShell -Arguments $InstallArguments
    Invoke-Checked -Program $PowerShell -Arguments $InstallArguments

    $Executable = Join-Path $Target "CodexSessionManager.exe"
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "installed executable is missing: $Executable"
    }
    if (-not (Test-Path -LiteralPath "${Target}.previous" -PathType Container)) {
        throw "repeat install did not preserve the previous installation"
    }
    $Version = (& $Executable cli version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -ne $ExpectedVersion) {
        throw "unexpected installed version: $Version"
    }
    Invoke-Checked -Program $Executable -Arguments @("cli", "doctor", "--skip-app-server")

    Invoke-Checked -Program $Executable -Arguments @("cli", "hook", "install", "--yes")
    $InstalledStatus = (& $Executable cli hook status | Out-String) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or -not $InstalledStatus.ready) {
        throw "installed Hook did not report ready"
    }
    Invoke-Checked -Program $Executable -Arguments @("cli", "hook", "uninstall", "--yes")
    $RemovedStatus = (& $Executable cli hook status | Out-String) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $RemovedStatus.ready -or
        $RemovedStatus.PreCompact -or $RemovedStatus.PostCompact) {
        throw "Hook uninstall left CSM handlers behind"
    }

    Write-Host "Windows temporary install and Hook workflow passed: $Target"
}
finally {
    foreach ($Name in $EnvironmentNames) {
        [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], "Process")
    }
    if (Test-Path -LiteralPath $TestRoot) {
        $Removed = $false
        foreach ($Attempt in 1..5) {
            try {
                Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction Stop
                $Removed = $true
                break
            }
            catch {
                if ($Attempt -lt 5) {
                    Start-Sleep -Milliseconds 250
                }
            }
        }
        if (-not $Removed) {
            throw "Unable to remove disposable install root: $TestRoot"
        }
    }
}
