param(
    [ValidateSet('auto','nuitka','pyinstaller')]
    [string]$Engine = 'pyinstaller',
    [string]$AppName = 'LegendsOverlay',
    [switch]$RequireAdmin,
    [switch]$Harden,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
# Native build tools often write warnings to stderr; rely on explicit exit-code checks instead.
$PSNativeCommandUseErrorActionPreference = $false
$PythonExe = if (Test-Path .\.venv\Scripts\python.exe) { ".\.venv\Scripts\python.exe" } else { "python" }

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Invoke-BuildProcess {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$StepName
    )

    $outFile = Join-Path $env:TEMP "$StepName-out.log"
    $errFile = Join-Path $env:TEMP "$StepName-err.log"

    Remove-Item -Force $outFile -ErrorAction SilentlyContinue
    Remove-Item -Force $errFile -ErrorAction SilentlyContinue

    $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -NoNewWindow -Wait -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $script:LASTEXITCODE = $proc.ExitCode
    if ($proc.ExitCode -ne 0) {
        $errTail = if (Test-Path $errFile) { (Get-Content $errFile -Tail 20) -join [Environment]::NewLine } else { "" }
        throw "$StepName failed with exit code $($proc.ExitCode). $errTail"
    }
}

function Build-WithNuitka {
    param(
        [string]$PythonExe,
        [string]$AppName,
        [bool]$RequireAdmin,
        [bool]$Harden
    )

    Invoke-BuildProcess -FilePath $PythonExe -ArgumentList @("-m", "pip", "install", "nuitka", "ordered-set", "zstandard") -StepName "install-nuitka-deps"

    $args = @(
        "-m", "nuitka", "main.py",
        "--onefile",
        "--windows-console-mode=disable",
        "--assume-yes-for-downloads",
        "--enable-plugin=pyqt6",
        "--nofollow-import-to=pytesseract",
        "--nofollow-import-to=PIL",
        "--nofollow-import-to=mss",
        "--nofollow-import-to=cv2",
        "--nofollow-import-to=numpy",
        "--nofollow-import-to=PySide6",
        "--nofollow-import-to=shiboken6",
        "--include-data-dir=assets=assets",
        "--include-data-files=icon.ico=icon.ico",
        "--include-data-files=events.json=events.json",
        "--include-data-files=settings.json=settings.json",
        "--include-data-files=uniques.json=uniques.json",
        "--include-data-files=uniques_state.json=uniques_state.json",
        "--output-filename=$AppName.exe",
        "--output-dir=dist"
    )

    if ($RequireAdmin) {
        $args += "--windows-uac-admin"
    }

    if ($Harden) {
        $args += "--lto=yes"
        $args += "--python-flag=no_site"
        $args += "--python-flag=isolated"
        $args += "--disable-console"
    }

    Invoke-BuildProcess -FilePath $PythonExe -ArgumentList $args -StepName "nuitka-build"
}

function Build-WithPyInstaller {
    param(
        [string]$PythonExe,
        [string]$AppName,
        [bool]$RequireAdmin,
        [bool]$Harden
    )

    Invoke-BuildProcess -FilePath $PythonExe -ArgumentList @("-m", "pip", "install", "pyinstaller") -StepName "install-pyinstaller"

    # Explicitly bundle VC runtime DLLs required by python313.dll.
    # Some user systems fail to load python313.dll if these are not resolved at runtime.
    $pyBasePrefix = (& $PythonExe -c "import sys; print(sys.base_prefix)").Trim()
    $runtimeDllCandidates = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    $runtimeDllArgs = @()
    $runtimeDllStageDir = Join-Path $PSScriptRoot ".build_runtime_dlls"
    New-Item -ItemType Directory -Path $runtimeDllStageDir -Force | Out-Null
    foreach ($dllName in $runtimeDllCandidates) {
        $dllPath = Join-Path $pyBasePrefix $dllName
        if (Test-Path $dllPath) {
            $stagedDllPath = Join-Path $runtimeDllStageDir $dllName
            Copy-Item -Path $dllPath -Destination $stagedDllPath -Force
            $runtimeDllArgs += @("--add-binary", ".build_runtime_dlls\\${dllName}:.")
        }
    }

    $args = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--optimize", "2",
        "--hidden-import", "pyttsx3",
        "--hidden-import", "pyttsx3.drivers",
        "--hidden-import", "pyttsx3.drivers.sapi5",
        "--hidden-import", "comtypes",
        "--collect-submodules", "pyttsx3.drivers",
        "--name", "$AppName",
        "--icon", "icon.ico",
        "--add-data", "assets;assets",
        "--add-data", "icon.ico;.",
        "--add-data", "events.json;.",
        "--add-data", "settings.json;.",
        "--add-data", "uniques.json;.",
        "--add-data", "uniques_state.json;.",
        ".\\main.py"
    )

    if ($runtimeDllArgs.Count -gt 0) {
        $args += $runtimeDllArgs
    }

    if ($RequireAdmin) {
        $args += "--uac-admin"
    }

    if ($Harden) {
        # PyInstaller hardening is limited; onefile + optimization + exclusion is best-effort.
        $args += "--noupx"
    }

    Invoke-BuildProcess -FilePath $PythonExe -ArgumentList $args -StepName "pyinstaller-build"
}

Write-Host "Building release with engine: $Engine"

if ($Clean) {
    Remove-Item -Recurse -Force .\build -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force .\release -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force .\__pycache__ -ErrorAction SilentlyContinue
}

Invoke-BuildProcess -FilePath $PythonExe -ArgumentList @("-m", "pip", "install", "--upgrade", "pip") -StepName "pip-upgrade"

$actualEngine = $Engine
if ($Engine -eq 'auto') {
    $actualEngine = 'nuitka'
    try {
        Build-WithNuitka -PythonExe $PythonExe -AppName $AppName -RequireAdmin:$RequireAdmin -Harden:$Harden
    }
    catch {
        Write-Warning "Nuitka build failed ($($_.Exception.Message)). Falling back to PyInstaller."
        $actualEngine = 'pyinstaller'
        Build-WithPyInstaller -PythonExe $PythonExe -AppName $AppName -RequireAdmin:$RequireAdmin -Harden:$Harden
    }
}
elseif ($Engine -eq 'nuitka') {
    Build-WithNuitka -PythonExe $PythonExe -AppName $AppName -RequireAdmin:$RequireAdmin -Harden:$Harden
}
else {
    Build-WithPyInstaller -PythonExe $PythonExe -AppName $AppName -RequireAdmin:$RequireAdmin -Harden:$Harden
}

New-Item -ItemType Directory -Path .\release -Force | Out-Null

if ($actualEngine -eq 'nuitka' -and (Test-Path ".\dist\main.dist\$AppName.exe")) {
    Remove-Item -Recurse -Force ".\release\$AppName" -ErrorAction SilentlyContinue
    Copy-Item ".\dist\main.dist" ".\release\$AppName" -Recurse -Force
    Write-Host "Done. Release folder: .\\release\\$AppName"
}
elseif (Test-Path ".\dist\$AppName.exe") {
    if (-not (Test-Path ".\dist\$AppName.exe")) {
        throw "PyInstaller output binary .\\dist\\$AppName.exe was not created."
    }
    Copy-Item .\dist\$AppName.exe .\release\$AppName.exe -Force
    Write-Host "Done. Release binary: .\\release\\$AppName.exe"
}
else {
    throw "No expected output binary found in .\\dist after build."
}
