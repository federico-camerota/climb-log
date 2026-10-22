#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Development servers (`make dev`): the backend with auto-reload on :8000 in the background and
# Vite with hot reload on :5173 in the foreground (it proxies /api to the backend).
# Ctrl-C, or either server stopping, stops both and reports it once the backend has exited.
set -u

echo "make dev: open http://127.0.0.1:5173 (API on :8000). Ctrl-C stops both."

uv run climblog serve --reload &
backend=$!

stopped=0
cleanup() {
    [ "$stopped" = 1 ] && return
    stopped=1
    echo
    echo "make dev: stopping backend and frontend..."
    kill "$backend" 2>/dev/null  # no-op if Ctrl-C already stopped it
    wait "$backend" 2>/dev/null
    echo "make dev: stopped."
}
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap cleanup EXIT

pnpm --dir frontend dev
