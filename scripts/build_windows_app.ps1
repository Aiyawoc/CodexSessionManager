param(
    [string]$Version = "1.1.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Windows build must run on a real Windows AMD64 host"
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use MAJOR.MINOR.PATCH"
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$VersionSource = Get-Content -LiteralPath "src\codex_session_manager\version.py" -Raw
$VersionMatch = [regex]::Match($VersionSource, '__version__ = "(?<version>\d+\.\d+\.\d+)"')
if (-not $VersionMatch.Success -or $VersionMatch.Groups["version"].Value -ne $Version) {
    throw "build version $Version does not match src/codex_session_manager/version.py"
}

$ConfiguredUvCache = [Environment]::GetEnvironmentVariable("UV_CACHE_DIR", "Process")
$env:UV_CACHE_DIR = if ($ConfiguredUvCache) { $ConfiguredUvCache } else { Join-Path $RepoRoot "build\.uv-cache" }
$env:NUITKA_CACHE_DIR = Join-Path $RepoRoot "build\.nuitka-cache"
$BuildEnvironment = Join-Path $RepoRoot "build\.venv-build"
$SpecPath = Join-Path $RepoRoot "pysidedeploy.windows.spec"
$BuildSpec = Join-Path $RepoRoot (".pysidedeploy.windows." + [Guid]::NewGuid().ToString("N") + ".spec")
$NuitkaReport = Join-Path $RepoRoot "build\nuitka-compilation-report-windows.xml"
$NuitkaCrashReport = Join-Path $RepoRoot "nuitka-crash-report.xml"
$DeployOutput = Join-Path $RepoRoot "dist\CodexSessionManager.dist"
$Bundle = Join-Path $RepoRoot "dist\CodexSessionManager-Windows-x64"
$Archive = Join-Path $RepoRoot "dist\CodexSessionManager-Windows-x64-$Version-test.zip"
$Checksum = "$Archive.sha256"
Copy-Item -LiteralPath $SpecPath -Destination $BuildSpec

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

try {
    & (Join-Path $RepoRoot "scripts\check_windows.ps1")

    $env:UV_PROJECT_ENVIRONMENT = $BuildEnvironment
    Invoke-Checked -Program "uv" -Arguments @(
        "sync", "--locked", "--no-default-groups",
        "--group", "runtime", "--group", "gui", "--group", "build", "--compile-bytecode"
    )
    & (Join-Path $RepoRoot "scripts\fetch_age_windows_amd64.ps1")

    $BuildPython = Join-Path $BuildEnvironment "Scripts\python.exe"
    Invoke-Checked -Program $BuildPython -Arguments @(
        "scripts/build_icon_windows.py", "--output", "build/CodexSessionManager.ico"
    )

    foreach ($Path in @("deployment", $DeployOutput, $Bundle, $Archive, $Checksum)) {
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Recurse -Force
        }
    }
    foreach ($Path in @($NuitkaCrashReport, $NuitkaReport)) {
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Force
        }
    }

    $Deploy = Join-Path $BuildEnvironment "Scripts\pyside6-deploy.exe"
    Invoke-Checked -Program $Deploy -Arguments @(
        "-c", $BuildSpec, "--force", "--mode", "standalone",
        "--extra-ignore-dirs=.venv,.venv-build,.uv-cache,.nuitka-cache,build,dist,deployment,vendor,artifacts"
    )
    if (Test-Path -LiteralPath $NuitkaCrashReport) {
        throw "Nuitka emitted a crash report; refusing a partial or stale bundle"
    }
    if (-not (Test-Path -LiteralPath $NuitkaReport -PathType Leaf)) {
        throw "Nuitka compilation report is missing"
    }
    [xml]$Report = Get-Content -LiteralPath $NuitkaReport -Raw
    if ($Report.DocumentElement.GetAttribute("completion") -ne "yes") {
        throw "Nuitka compilation did not complete"
    }
    if (-not (Test-Path -LiteralPath $DeployOutput -PathType Container)) {
        throw "pyside6-deploy standalone output is missing: $DeployOutput"
    }

    Move-Item -LiteralPath $DeployOutput -Destination $Bundle
    $GeneratedExecutable = Join-Path $Bundle "app_entry.exe"
    $Executable = Join-Path $Bundle "CodexSessionManager.exe"
    if (-not (Test-Path -LiteralPath $GeneratedExecutable -PathType Leaf)) {
        throw "Nuitka executable is missing: $GeneratedExecutable"
    }
    Move-Item -LiteralPath $GeneratedExecutable -Destination $Executable

    $Resources = Join-Path $Bundle "Resources"
    $ResourceBin = Join-Path $Resources "bin"
    $ResourceLicenses = Join-Path $Resources "licenses"
    $ResourceSkills = Join-Path $Resources "skills"
    New-Item -ItemType Directory -Path $ResourceBin, $ResourceLicenses, $ResourceSkills -Force | Out-Null
    Copy-Item -LiteralPath "vendor\age\age.exe" -Destination (Join-Path $ResourceBin "age.exe")
    Copy-Item -LiteralPath "vendor\age\LICENSE" -Destination (Join-Path $ResourceLicenses "age-BSD-3-Clause.txt")
    Copy-Item -LiteralPath "vendor\age\verification.json" -Destination (Join-Path $ResourceLicenses "age-verification.json")
    Copy-Item -LiteralPath "THIRD_PARTY_NOTICES.md" -Destination $ResourceLicenses
    $NuitkaLicenses = Join-Path $BuildEnvironment "Lib\site-packages\nuitka-4.0.dist-info\licenses"
    Copy-Item -LiteralPath (Join-Path $NuitkaLicenses "LICENSE.txt") `
        -Destination (Join-Path $ResourceLicenses "nuitka-GPLv3.txt")
    Copy-Item -LiteralPath (Join-Path $NuitkaLicenses "LICENSE-RUNTIME.txt") `
        -Destination (Join-Path $ResourceLicenses "nuitka-runtime-exception.txt")
    Copy-Item -LiteralPath "skills\manage-codex-sessions" `
        -Destination (Join-Path $ResourceSkills "manage-codex-sessions") -Recurse
    [IO.File]::WriteAllText((Join-Path $Resources "build-channel"), "windows-test-unsigned`n")
    Copy-Item -LiteralPath "packaging\TEST_RELEASE_NOTICE.txt" -Destination $Resources
    Copy-Item -LiteralPath "scripts\install_windows_user.ps1" `
        -Destination (Join-Path $Bundle "Install-CodexSessionManager.ps1")

    & (Join-Path $RepoRoot "scripts\accept_windows_bundle.ps1") `
        -BundlePath $Bundle -ExpectedVersion $Version
    & (Join-Path $RepoRoot "scripts\test_windows_install_workflow.ps1") `
        -BundlePath $Bundle -ExpectedVersion $Version

    Compress-Archive -LiteralPath $Bundle -DestinationPath $Archive -CompressionLevel Optimal
    $ArchiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText($Checksum, "$ArchiveHash  $([IO.Path]::GetFileName($Archive))`n")
    Write-Host $Bundle
    Write-Host $Archive
    Write-Host "SHA-256: $ArchiveHash"
}
finally {
    Remove-Item -LiteralPath $BuildSpec -Force -ErrorAction SilentlyContinue
}
