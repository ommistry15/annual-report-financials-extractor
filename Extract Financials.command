#!/bin/bash
# Double-click this file (on a Mac) to open the Annual Report Financials Extractor.
# The first run sets up a private Python environment in a ".venv" folder next to this file.
cd "$(dirname "$0")" || exit 1

VENV=".venv"

fail() {
    echo
    echo "$1"
    echo
    read -n 1 -s -r -p "Press any key to close this window."
    exit 1
}

# Python with a working, modern Tk (8.6+) gives a much better window than Apple's built-in Tk 8.5.
has_good_tk() {
    "$1" -c 'import sys, tkinter; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)' >/dev/null 2>&1
}

setup() {
    echo "First run: setting up. This takes a minute..."
    rm -rf "$VENV"

    # 1) uv (if installed) downloads its own Python that includes Tk.
    if command -v uv >/dev/null 2>&1; then
        if uv venv --quiet --python 3.12 "$VENV" && \
           uv pip install --quiet --python "$VENV/bin/python" -r requirements.txt; then
            return 0
        fi
        rm -rf "$VENV"
    fi

    # 2) A Python already on this Mac: python.org first, then Homebrew, then Apple's.
    PY=""
    for c in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 \
             /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
        [ -x "$c" ] || continue
        if has_good_tk "$c"; then PY="$c"; break; fi
        if [ -z "$FALLBACK" ] && "$c" -c 'import tkinter' >/dev/null 2>&1; then FALLBACK="$c"; fi
    done
    [ -z "$PY" ] && PY="$FALLBACK"
    if [ -z "$PY" ]; then
        fail "Python 3 is not installed.
Install it from https://www.python.org/downloads/ (the macOS installer),
then double-click this file again."
    fi

    "$PY" -m venv "$VENV" || fail "Could not create the Python environment."
    "$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1
    "$VENV/bin/python" -m pip install --quiet -r requirements.txt || \
        fail "Installation failed. Check your internet connection and try again."
}

if ! "$VENV/bin/python" -c "import tkinter, pypdf, pypdfium2" >/dev/null 2>&1; then
    setup
fi

# Start the window. This Terminal window can be closed once the app is open.
nohup "$VENV/bin/python" ar_gui.pyw >/dev/null 2>&1 &
disown
echo "The extractor window is open. You can close this Terminal window."
exit 0
