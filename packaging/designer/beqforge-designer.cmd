@echo off
rem Runs the beqforge designer for beqdesigner on Windows: `beqforge serve-designer`, with the
rem container image's defaults (README, "Running the designer on Windows"). Keep this file
rem beside the release's beqforge-windows-x86_64.exe and double-click it, or run it from a
rem prompt with any extra serve-designer options, e.g. `beqforge-designer.cmd --record-dir D:\beq\records`.
rem
rem Every BEQFORGE_* variable already set in the environment wins over the defaults below.
setlocal

rem beqdesigner's work directory, as this machine sees it, so audio arrives by reference rather
rem than inline. Uncomment and point it at the folder mounted into beqdesigner's container.
rem if not defined BEQFORGE_SHARED_ROOT set "BEQFORGE_SHARED_ROOT=D:\beq\work"

rem How many titles to design at once, if this machine can take more than one (0.2.4 on).
rem if not defined BEQFORGE_WORKERS set "BEQFORGE_WORKERS=2"

if not defined BEQFORGE_HOST set "BEQFORGE_HOST=0.0.0.0"
if not defined BEQFORGE_PORT set "BEQFORGE_PORT=8420"
if not defined BEQFORGE_CACHE_DIR set "BEQFORGE_CACHE_DIR=%LOCALAPPDATA%\beqforge\cache"

set "EXE=%~dp0beqforge-windows-x86_64.exe"
if not exist "%EXE%" set "EXE=%~dp0beqforge.exe"
if not exist "%EXE%" (
    echo beqforge-windows-x86_64.exe was not found beside %~nx0
    pause
    exit /b 1
)

"%EXE%" serve-designer %*
set "STATUS=%ERRORLEVEL%"
rem keep the window open on a startup error, so a double-click shows why
if not "%STATUS%"=="0" pause
exit /b %STATUS%
