# Krellbot local installer (Windows PowerShell).
#
# Invoked by Install-Krellbot.cmd from the EXTRACTED release archive.
# Per-user install only:
#   - copies the full one-dir program to "$env:LOCALAPPDATA\Krellbot"
#   - creates a Start menu shortcut pointing at the installed
#     krellbot.exe with a safe working directory
#   - never downloads anything, never elevates, never changes the
#     execution policy, never claims signing, never touches secrets
#   - preserves KRELLBOT_HOME and every piece of user state: the
#     install only writes inside LOCALAPPDATA\Krellbot and the user's
#     own Start menu folder. Existing installs are replaced in place;
#     "~/.krellbot" (KRELLBOT_HOME) is never written or deleted.
#
# Exit codes: 0 installed, 1 refused (unsafe source/destination or
# missing payload).

$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "Install refused: $Message"
    Write-Host "Nothing has been changed."
    exit 1
}

# --- locate the payload (the folder this script lives in) -------------------

$Source = $PSScriptRoot
if (-not $Source) {
    Fail "could not determine the script directory."
}

$Exe = Join-Path $Source 'krellbot.exe'
$Internal = Join-Path $Source '_internal'
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
    Fail "this does not look like the extracted Krellbot archive: 'krellbot.exe' is missing next to the installer (found: $Source). Extract the FULL archive and run Install-Krellbot.cmd from inside it."
}
if (-not (Test-Path -LiteralPath $Internal -PathType Container)) {
    Fail "this does not look like the extracted Krellbot archive: the '_internal' runtime folder is missing next to the installer."
}

if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne 'Win32NT') {
    Fail "this installer is for Windows. On Linux, run install-krellbot.sh from the Linux archive."
}

# --- destination ------------------------------------------------------------

$LocalAppData = [Environment]::GetFolderPath('LocalApplicationData')
if (-not $LocalAppData) {
    Fail "could not resolve the per-user LOCALAPPDATA location."
}
$Destination = Join-Path $LocalAppData 'Krellbot'

# Refuse nesting in either direction: copying a tree into itself (or
# installing onto the extracted archive itself) corrupts the payload.
$SourceFull = [System.IO.Path]::GetFullPath($Source).TrimEnd('\') + '\'
$DestinationFull = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
if ($SourceFull -eq $DestinationFull) {
    Fail "the install destination is the same folder as the extracted archive ($Destination). Choose a different extraction folder or move the archive out of LOCALAPPDATA\Krellbot."
}
if ($DestinationFull.StartsWith($SourceFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "the destination is inside the extracted archive ($Destination inside $Source); refusing to copy a tree into itself."
}
if ($SourceFull.StartsWith($DestinationFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "the extracted archive is inside the destination ($Source inside $Destination); refusing to install over the source."
}

# Refuse a pre-existing symlink/reparse-point destination that points
# elsewhere: following it would write outside LOCALAPPDATA.
if (Test-Path -LiteralPath $Destination) {
    $Item = Get-Item -LiteralPath $Destination -Force
    if ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Fail "'$Destination' is a link to another location; refusing to install through it."
    }
    if (-not ($Item.PSIsContainer)) {
        Fail "'$Destination' exists and is not a folder."
    }
}

# --- install ----------------------------------------------------------------

Write-Host "Installing Krellbot to: $Destination"
New-Item -ItemType Directory -Path $Destination -Force | Out-Null

# Robocopy mirrors the full one-dir payload; /E includes empty dirs,
# /NFL /NDL /NJH /NYS keep the console readable. Exit codes 0-7 are
# success for robocopy; anything else is a real failure.
& robocopy $Source $Destination /E /NFL /NDL /NJH /NYS /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
    Fail "robocopy failed with exit code $LASTEXITCODE."
}

$InstalledExe = Join-Path $Destination 'krellbot.exe'
if (-not (Test-Path -LiteralPath $InstalledExe -PathType Leaf)) {
    Fail "the installed executable is missing after the copy."
}

# --- Start menu shortcut ----------------------------------------------------

$Programs = [Environment]::GetFolderPath('Programs')
if ($Programs) {
    $ShortcutDir = $Programs
    $ShortcutPath = Join-Path $ShortcutDir 'Krellbot.lnk'
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $InstalledExe
    # A safe, always-present working directory: the install folder
    # itself. Never a network path, never the Windows directory.
    $Shortcut.WorkingDirectory = $Destination
    $Shortcut.Description = 'Krellbot local workstation'
    $Shortcut.Save()
    Write-Host "Start menu shortcut created: $ShortcutPath"
} else {
    Write-Host "Start menu folder not available; the program is still installed at:"
    Write-Host "  $InstalledExe"
}

Write-Host ""
Write-Host "Installed. Launch from the Start menu (Krellbot) or run:"
Write-Host "  `"$InstalledExe`""
Write-Host "With no arguments the program starts the local workstation and"
Write-Host "opens it in your browser. Stop it with Ctrl+C in its window."
Write-Host "Your Krellbot data is untouched and continues to be used."
exit 0
