param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "age bundle fetch requires Windows AMD64"
}

$AgeVersion = "1.3.1"
$ArchiveName = "age-v$AgeVersion-windows-amd64.zip"
$ProofName = "$ArchiveName.proof"
$ArchiveSha256 = "c56e8ce22f7e80cb85ad946cc82d198767b056366201d3e1a2b93d865be38154"
$ProofSha256 = "223a4bf46d6bae52b13cee6c7e384c2d3228e9055aecfe77c5d2b59413cefabc"
$BinarySha256 = "90f5cc37249c06e0b302e476a8a63bcefeecd9437c192b8af33e6ff2d69558dd"
$PolicySha256 = "666d9d0b9ab2e4019769c42eaccd7d6d502a9abac45979bb9b08b7213e4f53e3"
$BaseUrl = "https://github.com/FiloSottile/age/releases/download/v$AgeVersion"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VendorRoot = Join-Path $RepoRoot "vendor\age"
$VendorAge = Join-Path $VendorRoot "age.exe"
$Verification = Join-Path $VendorRoot "verification.json"
$Policy = Join-Path $RepoRoot "packaging\sigsum-generic-2025-1.policy"

function Assert-Hash {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    $Actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected) {
        throw "SHA-256 mismatch for ${Path}: expected $Expected, got $Actual"
    }
}

if ((Test-Path -LiteralPath $VendorAge -PathType Leaf) -and
    (Test-Path -LiteralPath $Verification -PathType Leaf)) {
    try {
        Assert-Hash -Path $VendorAge -Expected $BinarySha256
        $VersionOutput = (& $VendorAge --version | Out-String).Trim()
        $Metadata = Get-Content -LiteralPath $Verification -Raw | ConvertFrom-Json
        if ($VersionOutput -eq "v$AgeVersion" -and $Metadata.binary_sha256 -eq $BinarySha256) {
            Write-Host "Using verified cached age $AgeVersion ($BinarySha256)"
            return
        }
    }
    catch {
        Write-Host "Cached age failed verification; fetching the pinned release"
    }
}

$FetchRoot = Join-Path ([IO.Path]::GetTempPath()) ("csm-age-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $FetchRoot | Out-Null
try {
    $ArchivePath = Join-Path $FetchRoot $ArchiveName
    $ProofPath = Join-Path $FetchRoot $ProofName
    Invoke-WebRequest -Uri "$BaseUrl/$ArchiveName" -OutFile $ArchivePath
    Invoke-WebRequest -Uri "$BaseUrl/$ProofName" -OutFile $ProofPath
    Assert-Hash -Path $ArchivePath -Expected $ArchiveSha256
    Assert-Hash -Path $ProofPath -Expected $ProofSha256
    Assert-Hash -Path $Policy -Expected $PolicySha256

    $GoRoot = Join-Path $FetchRoot "go"
    $GoBin = Join-Path $FetchRoot "bin"
    $env:GOCACHE = Join-Path $FetchRoot "go-cache"
    $env:GOPATH = $GoRoot
    $env:GOBIN = $GoBin
    & go install sigsum.org/sigsum-go/cmd/sigsum-verify@v0.13.1
    if ($LASTEXITCODE -ne 0) {
        throw "failed to build sigsum-verify"
    }

    $Sigsum = Join-Path $GoBin "sigsum-verify.exe"
    $Keys = Join-Path $RepoRoot "packaging\age-sigsum-keys.pub"
    # sigsum-go v0.13.1 joins embedded policy paths with Windows separators,
    # which embed.FS cannot open. Use the tracked canonical policy as a file.
    $StartInfo = [Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $Sigsum
    $StartInfo.UseShellExecute = $false
    $StartInfo.RedirectStandardInput = $true
    foreach ($Argument in @("-k", $Keys, "-p", $Policy, $ProofPath)) {
        $StartInfo.ArgumentList.Add($Argument)
    }
    $Process = [Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    if (-not $Process.Start()) {
        throw "failed to start sigsum-verify"
    }
    $InputStream = [IO.File]::OpenRead($ArchivePath)
    try {
        $InputStream.CopyTo($Process.StandardInput.BaseStream)
    }
    finally {
        $InputStream.Dispose()
        $Process.StandardInput.Close()
    }
    $Process.WaitForExit()
    if ($Process.ExitCode -ne 0) {
        throw "Sigsum verification failed with exit code $($Process.ExitCode)"
    }

    $Extracted = Join-Path $FetchRoot "extracted"
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $Extracted
    $ExtractedAge = Join-Path $Extracted "age\age.exe"
    $ExtractedLicense = Join-Path $Extracted "age\LICENSE"
    Assert-Hash -Path $ExtractedAge -Expected $BinarySha256

    New-Item -ItemType Directory -Path $VendorRoot -Force | Out-Null
    Copy-Item -LiteralPath $ExtractedAge -Destination $VendorAge -Force
    Copy-Item -LiteralPath $ExtractedLicense -Destination (Join-Path $VendorRoot "LICENSE") -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\age-v1.3.1-windows-amd64.json") `
        -Destination $Verification -Force
    $VersionOutput = (& $VendorAge --version | Out-String).Trim()
    if ($VersionOutput -ne "v$AgeVersion") {
        throw "unexpected age version: $VersionOutput"
    }
    Write-Host $VersionOutput
}
finally {
    if (Test-Path -LiteralPath $FetchRoot) {
        Remove-Item -LiteralPath $FetchRoot -Recurse -Force
    }
}
