#!/usr/bin/env bash
# Preflight: Docker CLI can talk to a running dockerd.
#
# The failure mode this catches: on macOS, Docker Desktop's Electron UI and
# the Linux VM that runs dockerd are independent. The dashboard can be open
# while the VM is paused or stopped, and `docker compose up` then fails with
# a cryptic socket error. This script distinguishes those states and tells
# the user exactly what to do. We never start/stop Docker from here — that
# kills other users' running containers.

set -u

say() { printf '%s\n' "$*"; }
err() { printf '%s\n' "$*" >&2; }

# 1. Is the docker binary even installed?
if ! command -v docker >/dev/null 2>&1; then
  err "docker CLI not found on PATH."
  err "Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
  exit 2
fi

# 2. Client + server handshake. `docker version --format '{{.Server.Version}}'`
#    prints empty + exits non-zero when the server is unreachable.
if server_version=$(docker version --format '{{.Server.Version}}' 2>/dev/null) \
   && [ -n "$server_version" ]; then
  say "Docker engine reachable (server $server_version)."
  exit 0
fi

# 3. Server unreachable — try to distinguish "UI not running" from
#    "UI running but VM paused" by probing the socket directly.
sock_candidates=(
  "${DOCKER_HOST:-}"
  "$HOME/.docker/run/docker.sock"
  "/var/run/docker.sock"
)

reachable_sock=""
for sock in "${sock_candidates[@]}"; do
  # Strip leading unix:// if present.
  path="${sock#unix://}"
  [ -z "$path" ] && continue
  [ -S "$path" ] || continue
  if curl -sS --max-time 2 --unix-socket "$path" http://localhost/_ping >/dev/null 2>&1; then
    reachable_sock="$path"
    break
  fi
done

err ""
err "Docker CLI is installed, but the engine is not responding."
if [ -n "$reachable_sock" ]; then
  err "  Socket $reachable_sock answered /_ping — the CLI should have worked."
  err "  Check DOCKER_HOST env var; may be pointing at the wrong socket."
else
  err "  No Docker socket answered /_ping. Most likely Docker Desktop's UI"
  err "  is open but the Linux VM hosting dockerd is paused or stopped."
  err ""
  err "  Fix (macOS): click the whale icon in the menu bar → Resume (or Start)."
  err "  Verify:     docker version   # Server block must be populated."
  err ""
  err "  Last resort (kills any running containers):"
  err "    osascript -e 'quit app \"Docker\"' && open -a Docker"
fi
exit 1
