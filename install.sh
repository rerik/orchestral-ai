#!/bin/sh
#
# install.sh — Install orchestral-cli
#
# Usage:
#   curl -LsSf https://raw.githubusercontent.com/rerik/orchestral-ai/main/install.sh | sh
#   ./install.sh   (from a local clone of the repo)
#
# This script installs (or upgrades) the orchestral-cli package using pip.
# It detects whether it is being run from within the repository (local mode)
# or from a remote pipe (GitHub mode), and installs accordingly.
#
# Requirements: Python 3.10+, pip.
# Supported on: Linux and macOS.

set -e

# ────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────

# Print a status message to stderr so it's visible even when stdout is piped.
say() {
    printf '\033[32m%s\033[0m\n' "$*" >&2
}

warn() {
    printf '\033[33mWARNING: %s\033[0m\n' "$*" >&2
}

error() {
    printf '\033[31mERROR: %s\033[0m\n' "$*" >&2
    exit 1
}

# ────────────────────────────────────────────────────────────
# Determine install mode (local vs. GitHub)
# ────────────────────────────────────────────────────────────
#
# Local mode:  the script is running from inside a cloned repo
#              (pyproject.toml is present next to the script or in CWD).
# GitHub mode: otherwise (default for curl | sh).

script_dir=''
mode='github'

# When the script is a real file on disk (not a piped stdin), derive its directory.
# $0 could be "./install.sh", "/full/path/install.sh", or "sh" (when piped).
case "$0" in
    *install.sh)
        script_dir="$(cd "$(dirname "$0")" && pwd -P 2>/dev/null || dirname "$0")"
        ;;
esac

# Check for pyproject.toml — first next to the script, then in the current directory.
if [ -n "$script_dir" ] && [ -f "$script_dir/pyproject.toml" ]; then
    mode='local'
elif [ -f 'pyproject.toml' ]; then
    mode='local'
fi

# ────────────────────────────────────────────────────────────
# 1. Check Python (3.10+)
# ────────────────────────────────────────────────────────────
say "Checking Python..."

# Find a suitable python command.
python_cmd=''
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        python_cmd="$candidate"
        break
    fi
done

if [ -z "$python_cmd" ]; then
    error "Python not found. Please install Python 3.10 or newer (https://python.org)."
fi

# Parse major.minor version.
raw_version=$("$python_cmd" --version 2>&1)
py_major=''
py_minor=''

case "$raw_version" in
    Python*)
        # Extract the version string (e.g. "Python 3.12.5" -> "3.12.5")
        ver="${raw_version#Python }"
        py_major="${ver%%.*}"
        rest="${ver#*.}"
        py_minor="${rest%%.*}"
        ;;
esac

if [ -z "$py_major" ] || [ -z "$py_minor" ]; then
    error "Could not parse Python version from: $raw_version"
fi

# Require 3.10 or newer.
if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 10 ]; }; then
    error "Python 3.10+ is required, but found: $raw_version"
fi

say "✓ Found $raw_version"

# ────────────────────────────────────────────────────────────
# 2. Check pip availability
# ────────────────────────────────────────────────────────────
say "Checking pip..."

if ! "$python_cmd" -m pip --version >/dev/null 2>&1; then
    error "pip is not installed for $python_cmd. Please install pip (https://pip.pypa.io/en/stable/installation/)."
fi

say "✓ pip is available"

# ────────────────────────────────────────────────────────────
# 3. Check if already installed (for upgrade detection)
# ────────────────────────────────────────────────────────────
upgrade_flag=''
if command -v orchestral-cli >/dev/null 2>&1; then
    say "✓ Existing orchestral-cli installation detected — will upgrade"
    upgrade_flag='--upgrade'
fi

# ────────────────────────────────────────────────────────────
# 4. Install
# ────────────────────────────────────────────────────────────
say "Installing orchestral-cli..."

# When piped from curl, stdin is the rest of the script pipe;
# redirect pip's stdin to /dev/null so it never tries to read
# from the pipe (which could cause hangs or confusing errors).
install_stdin=''
if [ ! -t 0 ]; then
    install_stdin='</dev/null'
fi

case "$mode" in
    local)
        # Determine the install root (where pyproject.toml lives).
        if [ -n "$script_dir" ] && [ -f "$script_dir/pyproject.toml" ]; then
            install_root="$script_dir"
        else
            install_root="$PWD"
        fi
        say "   Mode: local  (directory: $install_root)"
        # shellcheck disable=SC2086
        eval "$python_cmd -m pip install $upgrade_flag \"$install_root\" $install_stdin"
        ;;
    github)
        repo_url='https://github.com/rerik/orchestral-ai.git'
        say "   Mode: GitHub (repo: $repo_url)"
        # shellcheck disable=SC2086
        eval "$python_cmd -m pip install $upgrade_flag \"git+$repo_url\" $install_stdin"
        ;;
esac

# ────────────────────────────────────────────────────────────
# 5. Verify installation
# ────────────────────────────────────────────────────────────
say "Verifying installation..."

if command -v orchestral-cli >/dev/null 2>&1; then
    say "✓ orchestral-cli installed successfully!"
else
    # The command might be in a local bin directory not on PATH.
    # Check common locations to give a helpful hint.
    for loc in "$HOME/.local/bin" "$HOME/Library/Python/3."*/bin; do
        if [ -f "$loc/orchestral-cli" ] || [ -x "$loc/orchestral-cli" ]; then
            warn "orchestral-cli is installed at '$loc/orchestral-cli' but not on your PATH."
            say "   Add to PATH:  export PATH=\"\$PATH:$loc\""
            exit 0
        fi
    done
    warn "orchestral-cli was installed but 'orchestral-cli' command was not found on PATH."
    say "   If you installed with --user, add ~/.local/bin to your PATH."
    exit 0
fi
