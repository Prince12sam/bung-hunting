#!/bin/bash
# Starts a real X virtual display, a real Chromium inside it, and a socat
# bridge so the DevTools protocol port Chromium binds to loopback-only
# (see Dockerfile comment) is reachable from outside the container.
set -e

CHROME_BIN=$(find /ms-playwright -maxdepth 3 -type f -path '*/chrome-linux64/chrome' | head -1)
if [ -z "$CHROME_BIN" ]; then
    echo "could not locate the Chromium binary under /ms-playwright" >&2
    exit 1
fi

Xvfb :99 -screen 0 1920x1080x24 &
sleep 1

DISPLAY=:99 "$CHROME_BIN" \
    --remote-debugging-port=9222 \
    --remote-debugging-address=127.0.0.1 \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --no-first-run &

sleep 2
exec socat TCP-LISTEN:9223,fork,reuseaddr TCP:127.0.0.1:9222
