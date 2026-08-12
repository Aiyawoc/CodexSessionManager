param(
    [string]$BundlePath = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows) {
    throw "install_windows_user.ps1 must run on Windows"
}

$Source = (Resolve-Path $BundlePath).Path
if (-not (Test-Path -LiteralPath (Join-Path $Source "CodexSessionManager.exe") -PathType Leaf)) {
    throw "CodexSessionManager.exe is missing from $Source"
}
$InstallParent = $env:LOCALAPPDATA
$Target = Join-Path $InstallParent "CodexSessionManager"
$Staging = Join-Path $InstallParent (".CodexSessionManager." + [Guid]::NewGuid().ToString("N") + ".new")
$Previous = Join-Path $InstallParent "CodexSessionManager.previous"
$Swapped = $false

Copy-Item -LiteralPath $Source -Destination $Staging -Recurse
try {
    $Launcher = Join-Path $Staging "csm.cmd"
    [IO.File]::WriteAllText(
        $Launcher,
        "@echo off`r`n`"%~dp0CodexSessionManager.exe`" cli %*`r`n",
        [Text.Encoding]::ASCII
    )
    $StagedExecutable = Join-Path $Staging "CodexSessionManager.exe"
    & $StagedExecutable cli doctor --skip-app-server
    if ($LASTEXITCODE -ne 0) {
        throw "staged application failed doctor"
    }

    if (Test-Path -LiteralPath $Previous) {
        $Timestamped = "$Previous.$(Get-Date -Format 'yyyyMMddTHHmmss')"
        Move-Item -LiteralPath $Previous -Destination $Timestamped
    }
    if (Test-Path -LiteralPath $Target) {
        Move-Item -LiteralPath $Target -Destination $Previous
    }
    Move-Item -LiteralPath $Staging -Destination $Target
    $Swapped = $true

    $SkillSource = Join-Path $Target "Resources\skills\manage-codex-sessions"
    $SkillParent = Join-Path $HOME ".agents\skills"
    $SkillTarget = Join-Path $SkillParent "manage-codex-sessions"
    New-Item -ItemType Directory -Path $SkillParent -Force | Out-Null
    if (Test-Path -LiteralPath $SkillTarget) {
        $ExistingSkill = Join-Path $SkillTarget "SKILL.md"
        if (-not (Test-Path -LiteralPath $ExistingSkill) -or
            -not (Select-String -LiteralPath $ExistingSkill -Pattern '^name: manage-codex-sessions$' -Quiet)) {
            throw "refusing to replace an unrelated Skill at $SkillTarget"
        }
        Remove-Item -LiteralPath $SkillTarget -Recurse -Force
    }
    Copy-Item -LiteralPath $SkillSource -Destination $SkillTarget -Recurse

    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $PathEntries = @($UserPath -split ";" | Where-Object { $_ })
    if ($PathEntries -notcontains $Target) {
        $UpdatedPath = (@($PathEntries) + $Target) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $UpdatedPath, "User")
    }
    & (Join-Path $Target "CodexSessionManager.exe") cli doctor --skip-app-server
    if ($LASTEXITCODE -ne 0) {
        throw "installed application failed doctor"
    }
    Write-Host "Installed CodexSessionManager to $Target"
    Write-Host "Restart Codex and open a new terminal before using csm."
}
catch {
    if ($Swapped) {
        if (Test-Path -LiteralPath $Target) {
            Remove-Item -LiteralPath $Target -Recurse -Force
        }
        if (Test-Path -LiteralPath $Previous) {
            Move-Item -LiteralPath $Previous -Destination $Target
        }
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $Staging) {
        Remove-Item -LiteralPath $Staging -Recurse -Force
    }
}
