#!/usr/bin/env bash
# Starts an image the way compose.yml runs it (read-only, no capabilities) with no GLPI behind it, and
# checks it serves: GET / is 200, /healthz is 503 (no data yet), and the log has no traceback.
# Usage: bash scripts/smoke-test.sh IMAGE [HOST_PORT]
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows would rewrite --tmpfs /tmp into a Windows path

image=${1:?usage: smoke-test.sh IMAGE [HOST_PORT]}
port=${2:-18000}
name=glpi-dashboard-smoke-$$

cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$name" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
  -e GLPI_URL=http://127.0.0.1:9 -e GLPI_APP_TOKEN=smoke -e GLPI_USER_TOKEN=smoke \
  -p "127.0.0.1:$port:8000" "$image" >/dev/null

status() { curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port$1" || true; }

for _ in $(seq 1 30); do
  [ "$(status /)" = 200 ] && break
  [ "$(docker inspect -f '{{.State.Running}}' "$name")" = true ] || break
  sleep 1
done

logs=$(docker logs "$name" 2>&1)
echo "$logs"
fail() { echo "smoke test FAILED: $1" >&2; exit 1; }
[ "$(docker inspect -f '{{.State.Running}}' "$name")" = true ] || fail "container exited"
[ "$(status /)" = 200 ] || fail "GET / did not return 200"
[ "$(status /healthz)" = 503 ] || fail "/healthz did not return 503 without GLPI"
if grep -qE "Traceback|Error loading" <<<"$logs"; then fail "error in the log"; fi
echo "smoke test passed: $image"
