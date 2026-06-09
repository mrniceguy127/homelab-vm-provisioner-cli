#!/usr/bin/env bash

resolve_python_env() {
    local candidate site_packages

    if [[ -n "${PYTHON_BIN:-}" ]]; then
        export PYTHON_BIN
        return 0
    fi

    for candidate in \
        "$ROOT_DIR/.venv/bin/python" \
        "$ROOT_DIR/.venv/bin/python3"
    do
        if [[ -f "$candidate" ]]; then
            PYTHON_BIN="$candidate"
            export PYTHON_BIN
            return 0
        fi
    done

    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python)"
    else
        printf 'No usable Python interpreter found. Run ./setup --dev or set PYTHON_BIN.\n' >&2
        return 1
    fi

    shopt -s nullglob
    for candidate in "$ROOT_DIR"/.venv/lib/python*/site-packages; do
        if [[ -d "$candidate" ]]; then
            site_packages="$candidate"
            break
        fi
    done
    shopt -u nullglob

    if [[ -n "${site_packages:-}" ]]; then
        if [[ -n "${PYTHONPATH:-}" ]]; then
            export PYTHONPATH="$site_packages:$PYTHONPATH"
        else
            export PYTHONPATH="$site_packages"
        fi
    fi

    export PYTHON_BIN
}
