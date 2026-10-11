#!/usr/bin/env bash
# Krellbot local installer (Linux, per-user).
#
# Run from the EXTRACTED release archive (the folder that contains the
# `krellbot` executable and `_internal/`). The install is per-user:
#
#   - destination is $KRELLBOT_INSTALL_DIR if set, otherwise
#     ${XDG_DATA_HOME:-$HOME/.local/share}/Krellbot — a location the
#     user owns. No sudo, no root, no writes to system directories.
#   - the full one-dir payload is copied with permissions preserved;
#     nothing is downloaded and no network access happens.
#   - an XDG application entry (~/.local/share/applications/krellbot.desktop)
#     is written so Krellbot appears in the applications menu, and a
#     clickable "Launch Krellbot" file is placed on the Desktop when a
#     Desktop directory exists.
#   - user data is preserved: KRELLBOT_HOME (~/.krellbot by default),
#     packs, journal and settings are never written or deleted here.
#     Re-running the installer replaces program files only.
#
# Exit codes: 0 installed, 1 refused (unsafe source/destination or
# missing payload), 2 usage.

set -u

fail() {
    printf 'Install refused: %s\n' "$1" >&2
    printf 'Nothing has been changed.\n' >&2
    exit 1
}

usage() {
    printf 'Usage: ./install-krellbot.sh [DESTDIR]\n' >&2
    printf 'DESTDIR defaults to ${XDG_DATA_HOME:-$HOME/.local/share}/Krellbot\n' >&2
    exit 2
}

[ $# -le 1 ] || usage

# --- locate the payload (this script's own directory) -----------------------

script_path=${BASH_SOURCE[0]:-$0}
if command -v readlink >/dev/null 2>&1; then
    resolved=$(readlink -f -- "$script_path" 2>/dev/null || printf '%s' "$script_path")
else
    resolved=$script_path
fi
SOURCE=$(cd -- "$(dirname -- "$resolved")" >/dev/null 2>&1 && pwd -P) || fail "could not determine the script directory."

[ -n "${SOURCE}" ] || fail "could not determine the script directory."
[ -f "$SOURCE/krellbot" ] || fail "'krellbot' executable not found next to the installer ($SOURCE). Extract the FULL archive and run install-krellbot.sh from inside it."
[ -x "$SOURCE/krellbot" ] || fail "'$SOURCE/krellbot' is present but not executable; re-extract the archive with permissions preserved."
[ -d "$SOURCE/_internal" ] || fail "'_internal' runtime folder not found next to the installer ($SOURCE)."

case "$(uname -s)" in
    Linux*) : ;;
    *) fail "this installer is for Linux (uname: $(uname -s)). On Windows, run Install-Krellbot.cmd from the Windows archive." ;;
esac

# --- destination -------------------------------------------------------------

data_base=${XDG_DATA_HOME:-$HOME/.local/share}
[ -n "${data_base}" ] || fail "could not resolve a per-user data location (HOME/XDG_DATA_HOME)."

if [ $# -eq 1 ]; then
    DEST=$1
else
    DEST=$data_base/Krellbot
fi

case "$DEST" in
    -h|--help) usage ;;
esac

[ -n "$DEST" ] || fail "empty destination path."
case "$DEST" in
    *$'\n'*) fail "destination contains a newline." ;;
esac
case "$SOURCE" in
    *$'\n'*) fail "source contains a newline." ;;
esac

abs_dest_parent=$(dirname -- "$DEST")
mkdir -p -- "$abs_dest_parent" || fail "could not create the destination parent directory: $abs_dest_parent"
abs_dest=$(cd -- "$abs_dest_parent" >/dev/null 2>&1 && pwd -P) || fail "destination parent directory does not exist: $abs_dest_parent"
DEST=$abs_dest/$(basename -- "$DEST")

# Refuse unsafe nesting in either direction.
if [ "$SOURCE" = "$DEST" ]; then
    fail "the install destination is the same folder as the extracted archive ($DEST)."
fi
case "$DEST/" in
    "$SOURCE"/*) fail "the destination is inside the extracted archive ($DEST inside $SOURCE)." ;;
esac
case "$SOURCE/" in
    "$DEST"/*) fail "the extracted archive is inside the destination ($SOURCE inside $DEST)." ;;
esac

# Refuse a destination that is a symlink (or a path through one) to
# somewhere else: following it would write outside the chosen prefix.
if [ -L "$DEST" ] || [ -e "$DEST" ] && [ ! -d "$DEST" ]; then
    if [ -L "$DEST" ]; then
        fail "'$DEST' is a symbolic link; refusing to install through it."
    fi
    fail "'$DEST' exists and is not a directory."
fi
if [ -d "$DEST" ]; then
    link_target=$(readlink -- "$DEST" 2>/dev/null || true)
    [ -z "$link_target" ] || fail "'$DEST' is a symbolic link; refusing to install through it."
fi

# --- install -----------------------------------------------------------------

printf 'Installing Krellbot to: %s\n' "$DEST"
mkdir -p -- "$DEST" || fail "could not create '$DEST'."

# Copy the full one-dir payload. -a preserves the executable bit on the
# launcher; the temp-directory dance makes the replacement atomic-ish so
# a failed copy cannot leave a half-replaced program behind.
tmp_dest=$DEST.updating.$$
rm -rf -- "$tmp_dest"
if ! cp -a -- "$SOURCE/." "$tmp_dest"; then
    rm -rf -- "$tmp_dest"
    fail "copying the program files failed."
fi
rm -rf -- "$DEST.old"
[ ! -d "$DEST" ] || mv -- "$DEST" "$DEST.old"
if ! mv -- "$tmp_dest" "$DEST"; then
    [ ! -d "$DEST.old" ] || mv -- "$DEST.old" "$DEST"
    rm -rf -- "$tmp_dest"
    fail "installing the program files failed."
fi
rm -rf -- "$DEST.old"

[ -x "$DEST/krellbot" ] || fail "the installed executable is missing after the copy."
[ -d "$DEST/_internal" ] || fail "the installed runtime folder is missing after the copy."

# --- XDG application entry ----------------------------------------------------

apps_dir=$data_base/applications
mkdir -p -- "$apps_dir"
desktop_file=$apps_dir/krellbot.desktop
dest_exec=$DEST/krellbot
# Desktop-entry Exec values quote arguments and escape per the spec; a
# single desktop-file escape of spaces via quoted string is the widely
# implemented form. Backslashes and quotes are rejected outright so the
# quoting cannot be subverted.
case "$dest_exec" in
    *\\*|*\"*|*\'*) fail "install path contains characters the desktop entry cannot quote safely: $dest_exec" ;;
esac
cat > "$desktop_file" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=Krellbot
GenericName=Local crypto workstation
Comment=Run the Krellbot workstation locally (loopback only)
Exec="$dest_exec"
Path=$DEST
Terminal=true
Categories=Office;Finance;
StartupWMClass=krellbot
DESKTOP
chmod 0755 -- "$desktop_file" 2>/dev/null || true
printf 'Application menu entry created: %s\n' "$desktop_file"

# Refresh the menu database when the tool exists (best-effort only).
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$apps_dir" >/dev/null 2>&1 || true
fi

# --- clickable Desktop launcher ----------------------------------------------

desktop_dir=""
user_dirs=${XDG_CONFIG_HOME:-$HOME/.config}
if [ -f "$user_dirs/user-dirs.dirs" ]; then
    # Read only the XDG_DESKTOP_DIR line; do not execute the file.
    line=$(grep -m1 '^XDG_DESKTOP_DIR=' "$user_dirs/user-dirs.dirs" 2>/dev/null || true)
    if [ -n "$line" ]; then
        raw=${line#XDG_DESKTOP_DIR=}
        raw=${raw#\"}
        raw=${raw%\"}
        case "$raw" in
            \$HOME/*) desktop_dir=$HOME/${raw#\$HOME/} ;;
            /*) desktop_dir=$raw ;;
        esac
    fi
fi
[ -n "$desktop_dir" ] || desktop_dir=$HOME/Desktop
if [ -d "$desktop_dir" ] && [ ! -L "$desktop_dir" ]; then
    launch_file=$desktop_dir/Launch-Krellbot.desktop
    cat > "$launch_file" <<LAUNCH
[Desktop Entry]
Type=Application
Version=1.0
Name=Launch Krellbot
Comment=Start the local Krellbot workstation and open it in your browser
Exec="$dest_exec"
Path=$DEST
Terminal=true
StartupWMClass=krellbot
LAUNCH
    chmod 0755 -- "$launch_file" 2>/dev/null || true
    printf 'Desktop launcher created: %s\n' "$launch_file"
else
    printf 'No Desktop directory found; launch from the applications menu or run:\n  %s\n' "$dest_exec"
fi

printf '\nInstalled.\n'
printf 'Launch Krellbot from your applications menu, the Desktop file, or run:\n  %s\n' "$dest_exec"
printf 'With no arguments it starts the local workstation (127.0.0.1 only)\nand opens it in your browser. Stop it with Ctrl+C.\n'
printf 'Your Krellbot data is untouched and continues to be used.\n'
exit 0
