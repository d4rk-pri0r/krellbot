@echo off
rem Krellbot local installer entry point (Windows).
rem
rem Run this file from the EXTRACTED release archive (the folder that
rem contains krellbot.exe and _internal\). It copies the whole program
rem to your per-user LOCALAPPDATA\Krellbot folder and creates a Start
rem menu shortcut. No downloads, no elevation, no execution-policy
rem changes, no signing claims, no secrets are involved.
rem
rem If your PowerShell execution policy blocks the companion script,
rem this launcher prints guidance instead of changing any policy.

setlocal
set "SCRIPTDIR=%~dp0"
set "PS1=%SCRIPTDIR%Install-Krellbot.ps1"

if not exist "%PS1%" (
  echo Install-Krellbot.ps1 not found next to Install-Krellbot.cmd:
  echo   "%PS1%"
  echo Extract the FULL release archive and run the .cmd from inside it.
  exit /b 1
)

where powershell >nul 2>nul
if errorlevel 1 (
  echo Windows PowerShell is required but was not found on PATH.
  exit /b 1
)

rem -NoProfile: do not load machine/user profiles.
rem -File: run the companion script shipped in the same archive.
rem The execution policy is deliberately NOT overridden by this
rem installer. If the policy blocks the .ps1, the call below fails
rem and the guidance block prints; how (or whether) to relax the
rem policy stays the user's own decision.
powershell -NoProfile -File "%PS1%"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo Install did not complete. Nothing outside your user profile was
  echo modified, and your Krellbot data was not touched. If the message
  echo above says the script is disabled by policy, that is your own
  echo per-user PowerShell choice to make; this installer never changes
  echo any policy for you.
)

exit /b %RC%
