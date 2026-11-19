#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077

if [[ -f .web.pid ]]; then
    pid=$(cat .web.pid)
    cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
    process_dir=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
    if [[ "$process_dir" == "$PWD" && "$cmdline" == *"web.py"* ]] && kill -0 "$pid" 2>/dev/null; then
        if grep -Eq '^http://127\.0\.0\.1:[0-9]+/#[A-Za-z0-9_-]{43}$' .web.url 2>/dev/null; then
            xdg-open "$(cat .web.url)" >/dev/null 2>&1 &
            echo "Panel ya activo: abriendo pestaña"
            exit 0
        fi
        echo "El panel está iniciando; vuelve a intentarlo en un segundo"
        exit 0
    fi
fi

rm -f .web.pid .web.url
nohup .venv/bin/python web.py --open >> .web.log 2>&1 &
pid=$!

for _ in $(seq 1 80); do
    if grep -Eq '^http://127\.0\.0\.1:[0-9]+/#[A-Za-z0-9_-]{43}$' .web.url 2>/dev/null; then
        echo "Panel iniciado. No hay terminal que mantener abierta."
        exit 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "No se pudo iniciar. Revisa $(pwd)/.web.log"
        exit 1
    fi
    sleep 0.1
done

echo "El panel tarda en responder. Revisa $(pwd)/.web.log"
exit 1
