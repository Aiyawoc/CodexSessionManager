param(
    [Parameter(Mandatory = $true)][string]$BundlePath,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows) {
    throw "accept_windows_bundle.ps1 must run on Windows"
}

$SourceBundle = (Resolve-Path $BundlePath).Path
$AcceptRoot = Join-Path ([IO.Path]::GetTempPath()) ("CSM 验收 中文 " + [Guid]::NewGuid().ToString("N"))
$AcceptBundle = Join-Path $AcceptRoot "Codex Session Manager"
$SavedEnvironment = @{}
$EnvironmentNames = @(
    "PATH", "CSM_DATA_DIR", "CSM_CONFIG_DIR", "CSM_CACHE_DIR", "CSM_LOG_DIR",
    "CSM_CODEX_HOME", "CODEX_HOME", "CSM_GUI_SMOKE_EXIT_MS", "QT_QPA_PLATFORM"
)
foreach ($Name in $EnvironmentNames) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}

New-Item -ItemType Directory -Path $AcceptRoot | Out-Null
Copy-Item -LiteralPath $SourceBundle -Destination $AcceptBundle -Recurse
try {
    $Executable = Join-Path $AcceptBundle "CodexSessionManager.exe"
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "standalone executable is missing: $Executable"
    }
    $AgeKeygen = Join-Path $AcceptBundle "Resources\bin\age-keygen.exe"
    if (-not (Test-Path -LiteralPath $AgeKeygen -PathType Leaf)) {
        throw "standalone age-keygen is missing: $AgeKeygen"
    }
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:CSM_DATA_DIR = Join-Path $AcceptRoot "data"
    $env:CSM_CONFIG_DIR = Join-Path $AcceptRoot "config"
    $env:CSM_CACHE_DIR = Join-Path $AcceptRoot "cache"
    $env:CSM_LOG_DIR = Join-Path $AcceptRoot "log"
    $env:CSM_CODEX_HOME = Join-Path $AcceptRoot "codex-home"
    Remove-Item Env:CODEX_HOME -ErrorAction SilentlyContinue

    $Version = (& $Executable cli version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -ne $ExpectedVersion) {
        throw "unexpected packaged version: $Version"
    }
    $DoctorText = (& $Executable cli doctor --skip-app-server | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "packaged doctor failed"
    }
    $Doctor = $DoctorText | ConvertFrom-Json
    if (-not $Doctor.ok -or $Doctor.mode -ne "standalone-app") {
        throw "packaged doctor did not accept the standalone bundle"
    }
    $RequiredFailures = @($Doctor.checks | Where-Object { $_.required -and -not $_.ok })
    if ($RequiredFailures.Count -ne 0) {
        throw "packaged doctor reported required failures"
    }

    $ManagedIdentity = Join-Path $AcceptRoot "managed-backup.agekey"
    & $AgeKeygen --output $ManagedIdentity 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ManagedIdentity -PathType Leaf)) {
        throw "packaged age-keygen failed to generate an identity"
    }
    $Recipient = (& $AgeKeygen -y $ManagedIdentity | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $Recipient -notmatch '^age1[0-9a-z]+$') {
        throw "packaged age-keygen failed to derive a recipient"
    }

    $HookInput = '{"session_id":"acceptance","transcript_path":null,"cwd":"C:\\","hook_event_name":"PostCompact","model":"test","turn_id":"turn","trigger":"manual"}'
    $HookText = ($HookInput | & $Executable hook postcompact | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "packaged Hook protocol failed"
    }
    $Hook = $HookText | ConvertFrom-Json
    if ($Hook.'continue' -ne $true) {
        throw "PostCompact Hook did not fail open"
    }

    $env:CSM_GUI_SMOKE_EXIT_MS = "750"
    $env:QT_QPA_PLATFORM = "offscreen"
    & $Executable
    if ($LASTEXITCODE -ne 0) {
        throw "packaged GUI smoke test failed"
    }

    $Signature = Get-AuthenticodeSignature -LiteralPath $Executable
    Write-Host "Authenticode status: $($Signature.Status)"
    Write-Host "Windows standalone acceptance passed: $AcceptBundle"
}
finally {
    foreach ($Name in $EnvironmentNames) {
        [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], "Process")
    }
    if (Test-Path -LiteralPath $AcceptRoot) {
        # Windows may keep a just-executed .pyd mapped briefly after process
        # exit. This disposable runner-local copy must not invalidate a bundle
        # that already passed every acceptance gate above.
        $Removed = $false
        foreach ($Attempt in 1..5) {
            try {
                Remove-Item -LiteralPath $AcceptRoot -Recurse -Force -ErrorAction Stop
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
            Write-Warning "Unable to remove disposable acceptance copy: $AcceptRoot"
        }
    }
}
