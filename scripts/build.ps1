[CmdletBinding()]
param(
    # Use a different interpreter only when the caller explicitly requests one.
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "This build produces a Windows executable and must run on Windows."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = Join-Path $repoRoot "main.py"
$buildDir = Join-Path $repoRoot "build"
$distDir = Join-Path $repoRoot "dist"

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Could not find the application entry point: $source"
}

$pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw "Python was not found. Install Python 3.10+ and ensure '$Python' is on PATH."
}

$pythonVersionText = (& $Python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to query the Python interpreter '$Python'."
}
$pythonVersion = [version]$pythonVersionText
if ($pythonVersion -lt [version]"3.10") {
    throw "Python 3.10 or newer is required (found $pythonVersionText)."
}
$pointerBits = [int]((& $Python -c "import struct; print(struct.calcsize('P') * 8)").Trim())
if ($LASTEXITCODE -ne 0 -or $pointerBits -ne 64) {
    throw "A 64-bit Python interpreter is required for the windows-x64 artifact."
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$pyinstallerCheck = & $Python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
$pyinstallerExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($pyinstallerExitCode -ne 0) {
    throw "PyInstaller is required. Install the optional build tools with: $Python -m pip install .[build]"
}

# Only these two explicitly named directories are ever removed. Resolve and
# verify them as children of the checkout before cleaning, so a changed script
# path cannot turn cleanup into a broad or accidental deletion.
$rootPrefix = ([IO.Path]::GetFullPath($repoRoot)).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
foreach ($target in @($buildDir, $distDir)) {
    $fullTarget = [IO.Path]::GetFullPath($target)
    if (-not $fullTarget.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a path outside the repository: $fullTarget"
    }
    if (Test-Path -LiteralPath $fullTarget) {
        Remove-Item -LiteralPath $fullTarget -Recurse -Force
    }
    New-Item -ItemType Directory -Path $fullTarget -Force | Out-Null
}

$version = (& $Python -c "import autoclicker; print(autoclicker.__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    throw "Could not read autoclicker.__version__."
}
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Version '$version' is not suitable for an artifact name."
}

$artifactBase = "AutoclickerIO-$version-windows-x64"
$workPath = Join-Path $buildDir "pyinstaller"
$specPath = Join-Path $buildDir "spec"
New-Item -ItemType Directory -Path $workPath, $specPath -Force | Out-Null

Write-Host "Building $artifactBase.exe with Python $pythonVersionText (PyInstaller $pyinstallerCheck)..."
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $artifactBase `
    --workpath $workPath `
    --distpath $distDir `
    --specpath $specPath `
    $source
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$artifact = Join-Path $distDir "$artifactBase.exe"
if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
    throw "PyInstaller completed without producing the expected artifact: $artifact"
}

$sizeMiB = [math]::Round((Get-Item -LiteralPath $artifact).Length / 1MB, 2)
Write-Host "Created $artifact ($sizeMiB MiB)."
Write-Output $artifact
