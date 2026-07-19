# Sandboxed browser for the adaptive planning loop's structured actions
# (api/browser_client.py) — a real Chromium running under a real Xvfb
# virtual display, not a bare headless API process, so a VNC viewer can be
# bolted on later without re-architecting anything.
#
# Built on Microsoft's own Playwright image rather than a bare Ubuntu/apt
# install: Chromium's own dependency list is large and easy to get subtly
# wrong (missing codecs/sandbox libs) on a from-scratch image, and this one
# already ships a Chromium build (chromium-1228 at the time this was
# written) matched to the `playwright` pip version pinned in
# requirements.txt — confirmed for real that mismatched major versions
# aren't required to line up exactly, but keeping the image tag and pip
# version numerically aligned avoids ever having to wonder about it.
FROM mcr.microsoft.com/playwright:v1.61.0-noble

# Recent Chromium versions ignore --remote-debugging-address entirely and
# only ever bind the DevTools protocol port to loopback (127.0.0.1) —
# confirmed for real: passing --remote-debugging-address=0.0.0.0 still
# left it listening on 127.0.0.1 only (a deliberate Chromium security
# hardening change, not a bug). socat bridges that loopback-only port to
# one reachable from outside the container. This mirrors the trust
# boundary already accepted for msfrpcd's plaintext RPC and Postgres in
# docker-compose.yml: only ever reachable over the local Docker network,
# never an untrusted one.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends socat \
    && rm -rf /var/lib/apt/lists/*

COPY start.sh /start.sh
RUN chmod +x /start.sh
ENTRYPOINT ["/start.sh"]
