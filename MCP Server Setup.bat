@echo off
setlocal enabledelayedexpansion

echo.
echo ========================================
echo   MCP-PowerBi-Finvision Dev Setup
echo ========================================
echo.

:: ----------------------------------------
:: Step 1: Check for Git + network
:: ----------------------------------------
echo [Step 1/7] Checking prerequisites (Git, network)...

git --version >nul 2>&1
if !errorlevel! neq 0 (
    echo.
    echo ERROR: Git is not installed or not in PATH.
    echo Please install Git from https://git-scm.com/downloads
    echo.
    pause
    exit /b 1
)

:: Quick network connectivity check
ping -n 1 -w 3000 dev.azure.com >nul 2>&1
if !errorlevel! neq 0 (
    ping -n 1 -w 3000 pypi.org >nul 2>&1
    if !errorlevel! neq 0 (
        echo.
        echo WARNING: No internet connection detected.
        echo Setup requires internet for cloning and installing packages.
        echo.
        set /p "continueOffline=Continue anyway? (y/N): "
        if /i not "!continueOffline!"=="y" (
            echo Exiting. Please check your internet connection and try again.
            pause
            exit /b 1
        )
    )
)

:: ----------------------------------------
:: Step 2: Find or install Python 3.12+
:: ----------------------------------------
echo [Step 2/7] Checking for Python 3.12 or higher...
set "PYTHON_CMD="

:: Try py launcher first (most reliable on Windows)
py -3.13 --version >nul 2>&1
if !errorlevel!==0 (
    set "PYTHON_CMD=py -3.13"
    goto :python_found
)

py -3.12 --version >nul 2>&1
if !errorlevel!==0 (
    set "PYTHON_CMD=py -3.12"
    goto :python_found
)

:: Try common installation paths
for %%V in (313 312) do (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        "%PROGRAMFILES%\Python%%V\python.exe"
        "C:\Python%%V\python.exe"
    ) do (
        if exist %%~P (
            set "PYTHON_CMD=%%~P"
            goto :python_found
        )
    )
)

:: Python 3.12+ not found - install automatically
echo Python 3.12+ not found. Installing Python 3.13 automatically...
echo.

:: Try winget first
winget --version >nul 2>&1
if !errorlevel! neq 0 goto :try_direct_download

echo Installing Python 3.13 via winget...
echo This may take a few minutes (you may be prompted for admin access)...
echo.
winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements --silent
if !errorlevel! neq 0 (
    echo.
    echo WARNING: winget installation may have had issues. Trying alternative...
    goto :try_direct_download
)

echo.
echo Python installed. Locating executable...
timeout /t 3 /nobreak >nul
goto :find_python_after_install

:try_direct_download
echo Downloading Python 3.13 installer...
echo.

:: Pinned fallback URL - update version number when a newer 3.13.x patch is released
set "installerUrl=https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe"
set "installerPath=%TEMP%\python-3.13.0-amd64.exe"

powershell -Command "Invoke-WebRequest -Uri '%installerUrl%' -OutFile '%installerPath%'" 2>nul

if not exist "%installerPath%" (
    echo.
    echo ERROR: Failed to download Python installer.
    echo Please install Python 3.12+ manually from:
    echo   https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo Installing Python 3.13 (this may take a minute)...
start /wait "" "%installerPath%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

del "%installerPath%" >nul 2>&1
timeout /t 3 /nobreak >nul

:find_python_after_install
:: Re-check all paths after install (outside any block so errorlevel is fresh)
py -3.13 --version >nul 2>&1
if !errorlevel!==0 (
    set "PYTHON_CMD=py -3.13"
    goto :python_found
)

py -3.12 --version >nul 2>&1
if !errorlevel!==0 (
    set "PYTHON_CMD=py -3.12"
    goto :python_found
)

for %%V in (313 312) do (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        "%USERPROFILE%\AppData\Local\Programs\Python\Python%%V\python.exe"
        "%PROGRAMFILES%\Python%%V\python.exe"
    ) do (
        if exist %%~P (
            set "PYTHON_CMD=%%~P"
            goto :python_found
        )
    )
)

echo.
echo Python was installed but cannot be located in this session.
echo Please close this window, open a NEW terminal, and run setup again.
echo.
pause
exit /b 1

:python_found
:: Resolve to full absolute path (handles both "py -3.X" and direct .exe paths)
set "PYTHON_FULL_PATH="
del "%TEMP%\_mcp_pypath.txt" >nul 2>&1
if "!PYTHON_CMD:~0,2!"=="py" (
    !PYTHON_CMD! -c "import sys; print(sys.executable)" > "%TEMP%\_mcp_pypath.txt" 2>nul
) else (
    "!PYTHON_CMD!" -c "import sys; print(sys.executable)" > "%TEMP%\_mcp_pypath.txt" 2>nul
)
if exist "%TEMP%\_mcp_pypath.txt" (
    set /p PYTHON_FULL_PATH=<"%TEMP%\_mcp_pypath.txt"
    del "%TEMP%\_mcp_pypath.txt" >nul 2>&1
)
if "!PYTHON_FULL_PATH!"=="" (
    echo WARNING: Could not resolve Python full path, using command as-is.
    set "PYTHON_FULL_PATH=!PYTHON_CMD!"
)

:: Show version using the resolved full path
"!PYTHON_FULL_PATH!" --version 2>nul
if !errorlevel! neq 0 !PYTHON_FULL_PATH! --version 2>nul
echo Using: !PYTHON_FULL_PATH!
echo.

:: ----------------------------------------
:: Step 3: Find or install uv
:: ----------------------------------------
echo [Step 3/7] Checking for uv package manager...
set "UV_CMD="

uv --version >nul 2>&1
if !errorlevel!==0 (
    set "UV_CMD=uv"
    uv --version
    echo.
    goto :uv_done
)

:: uv not found - install it
echo uv not found. Installing uv (recommended for faster installs)...
echo.
powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" 2>nul

:: Refresh PATH and check all possible install locations
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;%USERPROFILE%\.cargo\bin;%CARGO_HOME%\bin;%PATH%"

for %%P in (
    "%USERPROFILE%\.local\bin\uv.exe"
    "%LOCALAPPDATA%\uv\bin\uv.exe"
    "%USERPROFILE%\.cargo\bin\uv.exe"
) do (
    if exist %%~P (
        set "UV_CMD=%%~P"
        echo uv installed successfully.
        echo.
        goto :uv_done
    )
)

uv --version >nul 2>&1
if !errorlevel!==0 (
    set "UV_CMD=uv"
    echo uv installed successfully.
    echo.
    goto :uv_done
)

echo WARNING: Could not install uv. Will use pip as fallback.
echo.

:uv_done

:: ----------------------------------------
:: Step 4: Determine repo location
:: ----------------------------------------
:: Check if this bat file lives inside a repo (user already cloned/pulled)
set "SCRIPT_DIR=%~dp0"
if exist "!SCRIPT_DIR!requirements.txt" (
    echo Detected: Setup is running from inside the repository.
    :: Remove trailing backslash
    set "repoPath=!SCRIPT_DIR:~0,-1!"
    echo Using existing repo at: !repoPath!
    echo Skipping clone step.
    echo.
    goto :repo_ready
)

:: ----------------------------------------
:: Step 4b: Clone the repository
:: ----------------------------------------
echo [Step 4/7] Selecting clone location...
set "defaultPath=%USERPROFILE%\repos"
echo Where would you like to clone the repository?
echo.
echo Opening folder browser dialog...
echo (Default if cancelled: %defaultPath%)
echo.

:: Use PowerShell to show a folder browser dialog
for /f "usebackq delims=" %%i in (`powershell -ExecutionPolicy Bypass -Command ^
    "Add-Type -AssemblyName System.Windows.Forms;" ^
    "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;" ^
    "$dialog.Description = 'Select folder to clone MCP-PowerBi-Finvision repository';" ^
    "$dialog.RootFolder = 'MyComputer';" ^
    "$dialog.SelectedPath = '%defaultPath%';" ^
    "$dialog.ShowNewFolderButton = $true;" ^
    "if ($dialog.ShowDialog() -eq 'OK') { $dialog.SelectedPath } else { '' }"`) do set "clonePath=%%i"

if "!clonePath!"=="" (
    echo No folder selected, using default: %defaultPath%
    set "clonePath=%defaultPath%"
) else (
    echo Selected folder: !clonePath!
)

:: Create directory if it doesn't exist
if not exist "!clonePath!" (
    echo.
    echo Creating directory: !clonePath!
    mkdir "!clonePath!"
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create directory!
        pause
        exit /b 1
    )
)

set "repoPath=!clonePath!\Z02-MCP-PowerBI"

:: Check if repo already exists
if exist "!repoPath!" (
    echo.
    echo Directory already exists: !repoPath!
    echo WARNING: Choosing 'y' will PERMANENTLY DELETE this folder and all its contents.
    echo          Any uncommitted work will be lost!
    set /p "overwrite=Remove and clone fresh? (y/N): "
    if /i "!overwrite!"=="y" (
        rmdir /s /q "!repoPath!"
    ) else (
        echo Skipping clone, using existing directory.
        goto :skip_clone
    )
)

echo.
echo Cloning repository...
echo   URL: https://dev.azure.com/finticx/Finticx_SAASPlatform/_git/Z02-MCP-PowerBI
echo   To:  !repoPath!
echo.

cd /d "!clonePath!"
if !errorlevel! neq 0 (
    echo.
    echo ERROR: Cannot access directory: !clonePath!
    pause
    exit /b 1
)

git clone --branch main https://dev.azure.com/finticx/Finticx_SAASPlatform/_git/Z02-MCP-PowerBI
if !errorlevel! neq 0 (
    echo.
    echo ERROR: Failed to clone repository!
    echo Please check that the URL is accessible and you have internet.
    echo.
    pause
    exit /b 1
)

:skip_clone

:: Verify the repo directory exists
if not exist "!repoPath!" (
    echo.
    echo ERROR: Repository directory not found at: !repoPath!
    echo The clone may have failed or created a different folder name.
    echo.
    pause
    exit /b 1
)

:repo_ready
cd /d "!repoPath!"
if !errorlevel! neq 0 (
    echo.
    echo ERROR: Cannot enter directory: !repoPath!
    pause
    exit /b 1
)

if not exist "!repoPath!\requirements.txt" (
    echo.
    echo ERROR: requirements.txt not found in !repoPath!
    echo The repository may be incomplete or corrupted.
    echo.
    pause
    exit /b 1
)

echo Repository ready at: !repoPath!

:: ----------------------------------------
:: Step 5: Create venv + install dependencies
:: ----------------------------------------
set "venvDir="

if not defined UV_CMD goto :pip_install

:: ===================== UV PATH =====================
echo.
echo [Step 5/7] Setting up with uv (virtual environment + dependencies)...
echo This may take a few minutes on first run...
echo.

:: Use uv to create venv and install from requirements.txt
"!UV_CMD!" venv --python "!PYTHON_FULL_PATH!" "!repoPath!\venv"
if !errorlevel! neq 0 (
    echo.
    echo WARNING: uv venv failed. Falling back to pip...
    echo.
    if exist "!repoPath!\venv" rmdir /s /q "!repoPath!\venv" >nul 2>&1
    goto :pip_install
)

:: Install dependencies using uv pip
"!UV_CMD!" pip install -r "!repoPath!\requirements.txt" --python "!repoPath!\venv\Scripts\python.exe"
if !errorlevel! neq 0 (
    echo.
    echo WARNING: uv pip install failed. Falling back to pip...
    echo.
    rmdir /s /q "!repoPath!\venv" >nul 2>&1
    goto :pip_install
)

set "venvDir=venv"
echo.
echo uv setup completed successfully.
goto :verify_venv

:: ===================== PIP PATH =====================
:pip_install
echo.
echo [Step 5/7] Creating virtual environment with pip...
echo.

"!PYTHON_FULL_PATH!" -m venv "!repoPath!\venv"
if !errorlevel! neq 0 (
    echo First attempt failed. Retrying with --clear flag...
    "!PYTHON_FULL_PATH!" -m venv --clear "!repoPath!\venv"
)

set "venvDir=venv"

:: ----------------------------------------
:: Verify venv python.exe actually exists (retry loop)
:: ----------------------------------------
:verify_venv
echo.
echo Verifying virtual environment...

set "venvPython=!repoPath!\venv\Scripts\python.exe"

set "VENV_RETRIES=0"

:venv_check_loop
if exist "!venvPython!" goto :venv_exists

set /a VENV_RETRIES+=1
if !VENV_RETRIES! gtr 3 goto :venv_failed

echo   Attempt !VENV_RETRIES!/3: python.exe not found at !venvPython!
echo   Recreating venv...
timeout /t 2 /nobreak >nul

"!PYTHON_FULL_PATH!" -m venv --clear "!repoPath!\venv" >nul 2>&1
goto :venv_check_loop

:venv_failed
echo.
echo ========================================
echo   ERROR: Virtual environment creation failed!
echo ========================================
echo.
echo   Expected: !venvPython!
echo   This file does not exist after 3 attempts.
echo.
echo   Try running manually:
echo     cd "!repoPath!"
echo     "!PYTHON_FULL_PATH!" -m venv venv
echo.
pause
exit /b 1

:venv_exists
:: Sanity check: can the venv python actually run?
"!venvPython!" -c "print('ok')" >nul 2>&1
if !errorlevel! neq 0 (
    echo.
    echo ERROR: !venvPython! exists but cannot execute!
    echo The virtual environment may be corrupted.
    echo.
    echo Attempting to recreate...
    "!PYTHON_FULL_PATH!" -m venv --clear "!repoPath!\venv" >nul 2>&1
    "!venvPython!" -c "print('ok')" >nul 2>&1
    if !errorlevel! neq 0 (
        echo Still broken. Please delete !repoPath!\venv and run setup again.
        pause
        exit /b 1
    )
)
echo   Virtual environment OK: !venvPython!

:: ----------------------------------------
:: Install dependencies (pip path only - uv already did this)
:: ----------------------------------------
:: Check if deps were already installed via uv by testing a core import
"!venvPython!" -c "import mcp" >nul 2>&1
if !errorlevel!==0 goto :verify_deps

echo.
echo Installing dependencies from requirements.txt...
echo This may take a few minutes (some packages are large)...
echo.

:: Use the venv python directly - never rely on activate.bat
"!venvPython!" -m pip install --upgrade pip >nul 2>&1
"!venvPython!" -m pip install -r "!repoPath!\requirements.txt"
set "PIP_RESULT=!errorlevel!"

if "!PIP_RESULT!" neq "0" (
    echo.
    echo WARNING: Initial install had issues. Retrying...
    echo.
    "!venvPython!" -m pip install -r "!repoPath!\requirements.txt"
)

:: ----------------------------------------
:: Step 6: Verify critical dependencies
:: ----------------------------------------
:verify_deps
echo.
echo [Step 6/7] Verifying critical dependencies...

:: Check each package individually (outside blocks so errorlevel is always fresh)
set "DEPS_MISSING=0"

"!venvPython!" -c "import mcp" >nul 2>&1
if !errorlevel! neq 0 (
    echo   MISSING: mcp
    set "DEPS_MISSING=1"
)

"!venvPython!" -c "import clr" >nul 2>&1
if !errorlevel! neq 0 (
    echo   MISSING: pythonnet
    set "DEPS_MISSING=1"
)

"!venvPython!" -c "import psutil" >nul 2>&1
if !errorlevel! neq 0 (
    echo   MISSING: psutil
    set "DEPS_MISSING=1"
)

"!venvPython!" -c "import requests" >nul 2>&1
if !errorlevel! neq 0 (
    echo   MISSING: requests
    set "DEPS_MISSING=1"
)

"!venvPython!" -c "import polars" >nul 2>&1
if !errorlevel! neq 0 (
    echo   MISSING: polars
    set "DEPS_MISSING=1"
)

"!venvPython!" -c "import orjson" >nul 2>&1
if !errorlevel! neq 0 (
    echo   MISSING: orjson
    set "DEPS_MISSING=1"
)

"!venvPython!" -c "import networkx" >nul 2>&1
if !errorlevel! neq 0 (
    echo   MISSING: networkx
    set "DEPS_MISSING=1"
)

"!venvPython!" -c "import pbixray" >nul 2>&1
if !errorlevel! neq 0 (
    echo   MISSING: pbixray
    set "DEPS_MISSING=1"
)

if "!DEPS_MISSING!"=="0" goto :core_deps_ok

:: Core deps missing - attempt reinstall
echo.
echo   Core dependencies missing. Attempting reinstall...
echo.
"!venvPython!" -m pip install -r "!repoPath!\requirements.txt"

:: Re-verify each (outside blocks)
echo.
echo   Re-checking after reinstall...
set "DEPS_STILL_MISSING=0"

"!venvPython!" -c "import mcp" >nul 2>&1
if !errorlevel! neq 0 set "DEPS_STILL_MISSING=1"

"!venvPython!" -c "import clr" >nul 2>&1
if !errorlevel! neq 0 set "DEPS_STILL_MISSING=1"

"!venvPython!" -c "import psutil" >nul 2>&1
if !errorlevel! neq 0 set "DEPS_STILL_MISSING=1"

"!venvPython!" -c "import requests" >nul 2>&1
if !errorlevel! neq 0 set "DEPS_STILL_MISSING=1"

"!venvPython!" -c "import polars" >nul 2>&1
if !errorlevel! neq 0 set "DEPS_STILL_MISSING=1"

"!venvPython!" -c "import orjson" >nul 2>&1
if !errorlevel! neq 0 set "DEPS_STILL_MISSING=1"

"!venvPython!" -c "import networkx" >nul 2>&1
if !errorlevel! neq 0 set "DEPS_STILL_MISSING=1"

"!venvPython!" -c "import pbixray" >nul 2>&1
if !errorlevel! neq 0 set "DEPS_STILL_MISSING=1"

if "!DEPS_STILL_MISSING!"=="1" (
    echo.
    echo   ERROR: Core dependencies still missing after reinstall.
    echo   The MCP server will NOT work without these.
    echo.
    echo   Try manually:
    echo     "!venvPython!" -m pip install "mcp[cli]" pythonnet psutil requests polars orjson networkx pbixray
    echo.
    pause
    exit /b 1
)
echo   Core dependencies installed successfully on retry.

:core_deps_ok

:: Check Windows-only dependencies separately (non-blocking on other platforms)
set "WIN_DEPS_OK=1"

"!venvPython!" -c "import WMI" >nul 2>&1
if !errorlevel! neq 0 (
    echo   NOTE: WMI not available (required for Power BI Desktop connection)
    set "WIN_DEPS_OK=0"
)

"!venvPython!" -c "import win32com" >nul 2>&1
if !errorlevel! neq 0 (
    echo   NOTE: pywin32 not available (required for Power BI Desktop connection)
    set "WIN_DEPS_OK=0"
)

if "!WIN_DEPS_OK!"=="0" (
    echo.
    echo   Attempting to install Windows-specific dependencies...
    "!venvPython!" -m pip install WMI pywin32
    echo.
)

echo.
echo   All critical dependencies verified.
echo   Virtual environment Python: !venvPython!

:: ----------------------------------------
:: Step 7: Configure Claude Desktop
:: ----------------------------------------
echo.
echo ========================================
echo   Claude Desktop Configuration
echo ========================================
echo.

set "configPath=%APPDATA%\Claude\claude_desktop_config.json"
echo Detected config path: !configPath!

:: Check if config directory exists
for %%F in ("!configPath!") do set "configDir=%%~dpF"
if not exist "!configDir!" (
    echo Creating config directory: !configDir!
    mkdir "!configDir!"
)

echo.
echo [Step 7/7] Updating Claude Desktop config...

:: Write a temp PowerShell script to avoid quoting hell with inline -Command
set "PS_configPath=!configPath:'=''!"
set "PS_venvPython=!venvPython:'=''!"
set "PS_repoPath=!repoPath:'=''!"
set "PS_SCRIPT=%TEMP%\_mcp_config_setup.ps1"
(
    echo $configPath = '!PS_configPath!'
    echo $venvPython = '!PS_venvPython!'
    echo $scriptPath = '!PS_repoPath!\src\pbixray_server_enhanced.py'
    echo $serverName = 'MCP-PowerBi-Finvision-DEV'
    echo.
    echo $mcpServer = @{ 'command' = $venvPython; 'args' = @($scriptPath^) }
    echo.
    echo if (Test-Path $configPath^) {
    echo     try {
    echo         $config = Get-Content $configPath -Raw -Encoding UTF8 ^| ConvertFrom-Json
    echo         Write-Host 'Found existing config file' -ForegroundColor Green
    echo     } catch {
    echo         Write-Host 'Config file is invalid, creating new one' -ForegroundColor Yellow
    echo         $config = [PSCustomObject]@{}
    echo     }
    echo } else {
    echo     Write-Host 'Creating new config file' -ForegroundColor Yellow
    echo     $config = [PSCustomObject]@{}
    echo }
    echo.
    echo if (-not $config.PSObject.Properties['mcpServers']^) {
    echo     $config ^| Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue ([PSCustomObject]@{}^)
    echo }
    echo.
    echo if ($config.mcpServers.PSObject.Properties[$serverName]^) {
    echo     $config.mcpServers.$serverName = $mcpServer
    echo     Write-Host "Updated existing $serverName configuration" -ForegroundColor Green
    echo } else {
    echo     $config.mcpServers ^| Add-Member -NotePropertyName $serverName -NotePropertyValue $mcpServer
    echo     Write-Host "Added $serverName configuration" -ForegroundColor Green
    echo }
    echo.
    echo $json = $config ^| ConvertTo-Json -Depth 10
    echo [System.IO.File]::WriteAllText($configPath, $json, [System.Text.UTF8Encoding]::new($false^)^)
    echo.
    echo Write-Host ''
    echo Write-Host "Config saved to: $configPath" -ForegroundColor Cyan
    echo Write-Host "MCP Server: $serverName" -ForegroundColor Cyan
    echo Write-Host "  Python: $venvPython"
    echo Write-Host "  Script: $scriptPath"
) > "!PS_SCRIPT!"

powershell -ExecutionPolicy Bypass -File "!PS_SCRIPT!"
set "PS_RESULT=!errorlevel!"
del "!PS_SCRIPT!" >nul 2>&1

if "!PS_RESULT!" neq "0" (
    echo.
    echo Warning: Failed to update Claude Desktop config automatically.
    echo.
    echo You need to manually add this to mcpServers in:
    echo   !configPath!
    echo.
    echo   "MCP-PowerBi-Finvision-DEV": {
    echo     "command": "!venvPython!",
    echo     "args": ["!repoPath!\src\pbixray_server_enhanced.py"]
    echo   }
    echo.
)

:: ----------------------------------------
:: Done!
:: ----------------------------------------
echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
"!venvPython!" --version
echo.
echo Repository:          !repoPath!
echo Virtual environment: !repoPath!\venv
echo Claude config:       !configPath!
echo MCP Server:          MCP-PowerBi-Finvision-DEV
echo.
echo NOTE: Your existing MCP servers are preserved.
echo       The DEV version runs alongside production.
echo.
echo IMPORTANT: Restart Claude Desktop for changes to take effect!
echo.
echo ----------------------------------------
echo   Manual Usage
echo ----------------------------------------
echo.
echo To start the server manually (STDIO mode):
echo   1. cd "!repoPath!"
echo   2. venv\Scripts\activate.bat
echo   3. python src/pbixray_server_enhanced.py
echo.
echo ----------------------------------------
echo   VSCode / Cursor Configuration
echo ----------------------------------------
echo.
echo Add this to your VSCode settings.json (Ctrl+Shift+P ^> "MCP: Open User Configuration"):
echo.
echo   "MCP-PowerBi-Finvision-DEV": {
echo     "type": "stdio",
echo     "command": "!venvPython!",
echo     "args": ["!repoPath!\src\pbixray_server_enhanced.py"]
echo   }
echo.

endlocal
pause
