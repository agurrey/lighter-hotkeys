#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .web.pid ]]; then
    echo "El panel no está ejecutándose"
    exit 0
fi

pid=$(cat .web.pid)
cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
process_dir=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
if [[ "$process_dir" == "$PWD" && "$cmdline" == *"web.py"* ]] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid"
    for _ in $(seq 1 50); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "El proceso sigue activo; no se ha forzado su cierre"
        exit 1
    fi
    echo "Panel detenido. Las posiciones y stops de Lighter no han cambiado."
else
    echo "Sesión antigua eliminada"
fi
rm -f .web.pid .web.url
