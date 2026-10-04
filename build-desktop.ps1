param(
    [string]$OutputPath,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$appDirectory = $PSScriptRoot
$venvDirectory = Join-Path $appDirectory '.venv'
$venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
$outputDirectory = Join-Path $appDirectory 'desktop-dist'
if ($OutputPath) { $outputDirectory = [System.IO.Path]::GetFullPath($OutputPath) }

& $Python -c "import sys; assert sys.version_info >= (3, 12), 'Python 3.12 or later is required'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or later is required.' }
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the build environment.' }
}
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $appDirectory 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install build dependencies.' }

$assetsDirectory = Join-Path $appDirectory 'assets'
$iconPng = Join-Path $assetsDirectory 'vocabulary-icon.png'
$iconIco = Join-Path $assetsDirectory 'vocabulary-icon.ico'
$fontDirectory = Join-Path $assetsDirectory 'fonts'
if (-not (Test-Path -LiteralPath (Join-Path $fontDirectory 'ChillRoundF.ttf'))) {
    throw 'Bundled font is missing.'
}

& $venvPython (Join-Path $appDirectory 'scripts\create-desktop-icon.py') $iconPng $iconIco
if ($LASTEXITCODE -ne 0) { throw 'App icon generation failed.' }

# Absolute asset paths also work when the spec file is in a separate directory.
& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --icon $iconIco `
    --add-data "$iconPng;assets" `
    --add-data "$fontDirectory;assets/fonts" `
    --name EnglishVocabularyBook `
    --distpath $outputDirectory `
    --workpath (Join-Path $appDirectory '.desktop-build') `
    --specpath (Join-Path $appDirectory '.desktop-build') `
    (Join-Path $appDirectory 'desktop_app.pyw')
if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging failed. Close the running app and retry.' }

Write-Host ('Desktop app created: ' + (Join-Path $outputDirectory 'EnglishVocabularyBook.exe'))
