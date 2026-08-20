#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="${1:?usage: deploy-server.sh VERSION INCOMING_DIR}"
INCOMING_DIR="${2:?usage: deploy-server.sh VERSION INCOMING_DIR}"

WEB_BASE="/opt/shixing-agent-ui-standalone"
API_BASE="/opt/shixing-agent-api"
STATIC_BASE="/var/www/shixing-wanli-releases"
STATIC_LINK="/var/www/shixing-wanli"
PERSISTENT_SOURCE="/opt/shixing-wanli-source/诗行万里"
PERSISTENT_KNOWLEDGE="$PERSISTENT_SOURCE/output/assets/knowledge"
KNOWLEDGE_CANDIDATE_BASE="/opt/shixing-knowledge-candidates"
KNOWLEDGE_CANDIDATE="$KNOWLEDGE_CANDIDATE_BASE/$VERSION"
RELEASE_KNOWLEDGE="$PERSISTENT_KNOWLEDGE"
API_DROPIN_DIR="/etc/systemd/system/shixing-agent-api.service.d"
API_DROPIN="$API_DROPIN_DIR/release.conf"
WEB_DROPIN_DIR="/etc/systemd/system/shixing-agent-web.service.d"
WEB_DROPIN="$WEB_DROPIN_DIR/release.conf"
WEB_SERVICE="shixing-agent-web.service"
API_SERVICE="shixing-agent-api.service"

WEB_ARCHIVE="$INCOMING_DIR/web-release.tar.gz"
API_ARCHIVE="$INCOMING_DIR/api-release.tar.gz"
STATIC_ARCHIVE="$INCOMING_DIR/static-release.tar.gz"
CHECKSUMS="$INCOMING_DIR/SHA256SUMS"
NEW_WEB="$WEB_BASE/releases/$VERSION"
NEW_API="$API_BASE/releases/$VERSION"
NEW_STATIC="$STATIC_BASE/$VERSION"
OLD_WEB="$(readlink -f "$WEB_BASE/current" 2>/dev/null || true)"
OLD_API="$(readlink -f "$API_BASE/current" 2>/dev/null || true)"
OLD_STATIC="$(readlink -f "$STATIC_LINK" 2>/dev/null || true)"
BOOTSTRAP_STATIC=""
PRE_PID=""
SWITCHED=0
STATIC_SWITCHED=0
DROPIN_EXISTED=0
WEB_DROPIN_EXISTED=0

exec 9>/run/lock/shixing-deploy.lock
flock -n 9 || { echo "another deployment is running" >&2; exit 1; }

for file in "$WEB_ARCHIVE" "$API_ARCHIVE" "$STATIC_ARCHIVE" "$CHECKSUMS"; do
  test -s "$file" || { echo "missing release file: $file" >&2; exit 1; }
done
if [ -d "$KNOWLEDGE_CANDIDATE" ]; then
  RELEASE_KNOWLEDGE="$KNOWLEDGE_CANDIDATE"
fi
test -s "$RELEASE_KNOWLEDGE/poetry_knowledge.sqlite3"
test -s "$RELEASE_KNOWLEDGE/poetry_knowledge.manifest.json"
test -x /usr/bin/python3
/usr/bin/python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)
PY
test -x /usr/local/bin/node
systemctl cat "$API_SERVICE" >/dev/null
systemctl cat "$WEB_SERVICE" >/dev/null
test -d "$STATIC_LINK" || test -L "$STATIC_LINK"

cd "$INCOMING_DIR"
sha256sum -c SHA256SUMS

mkdir -p \
  "$WEB_BASE/releases" \
  "$API_BASE/releases" \
  "$API_BASE/cache" \
  "$API_BASE/pex-cache" \
  "$STATIC_BASE"

prepare_release() {
  local archive="$1"
  local target="$2"
  local required="$3"
  local temp="$target.tmp"

  rm -rf "$temp"
  mkdir -p "$temp"
  tar -xzf "$archive" -C "$temp"
  test -e "$temp/$required"
  if [ -d "$target" ]; then
    rm -rf "$temp"
  else
    mv "$temp" "$target"
  fi
}

prepare_release "$WEB_ARCHIVE" "$NEW_WEB" "server.js"
prepare_release "$API_ARCHIVE" "$NEW_API" "poetry-agent.pex"
prepare_release "$STATIC_ARCHIVE" "$NEW_STATIC" "29_参赛导航.html"
cmp -s "$NEW_STATIC/index.html" "$NEW_STATIC/29_参赛导航.html"

chmod 755 "$NEW_API/poetry-agent.pex"
mkdir -p "$NEW_API/output/assets" "$NEW_API/apps/agent-ui"
ln -sfn "$RELEASE_KNOWLEDGE" "$NEW_API/output/assets/knowledge"
ln -sfn "$API_BASE/cache" "$NEW_API/apps/agent-ui/.cache"

check_json() {
  local url="$1"
  local kind="$2"
  local max_time="${3:-30}"
  local payload="$INCOMING_DIR/check-$kind.json"
  curl -fsS --max-time "$max_time" "$url" -o "$payload" || return 1
  /usr/bin/python3 - "$kind" "$payload" <<'PY'
import json
import sys

kind, path = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    value = json.load(handle)

if kind == "health":
    sources = value.get("sources") or {}
    good = (
        value.get("status") in {"ok", "degraded"}
        and sources.get("missing") == []
        and (sources.get("knowledgeBase") or {}).get("available") is True
    )
elif kind == "catalog":
    good = (
        value.get("status") == "ok"
        and (value.get("payload") or {}).get("poetCount") == 88
    )
elif kind == "knowledge":
    payload = value.get("payload") or {}
    good = value.get("status") == "ok" and payload.get("available") is True
else:
    good = False
raise SystemExit(0 if good else 1)
PY
}

wait_for_api() {
  local url="$1"
  local attempts="${2:-30}"
  local attempt
  for attempt in $(seq 1 "$attempts"); do
    curl -fsS --max-time 5 "$url" >/dev/null && return 0
    sleep 4
  done
  return 1
}

cleanup_preflight() {
  if [ -n "$PRE_PID" ]; then
    kill "$PRE_PID" 2>/dev/null || true
    wait "$PRE_PID" 2>/dev/null || true
    PRE_PID=""
  fi
}
trap cleanup_preflight EXIT

# Validate the new API against persistent data before changing live services.
if ss -ltn | grep -qE '127\.0\.0\.1:18123\b'; then
  echo "preflight port 18123 is already in use" >&2
  exit 1
fi
(
  cd "$NEW_API/apps/agent-ui/agent"
  AGENT_HOST=127.0.0.1 \
  AGENT_PORT=18123 \
  PEX_ROOT="$API_BASE/pex-cache" \
    /usr/bin/python3 "$NEW_API/poetry-agent.pex"
) >"$INCOMING_DIR/api-preflight.log" 2>&1 &
PRE_PID=$!
if ! wait_for_api http://127.0.0.1:18123/openapi.json \
  || ! check_json http://127.0.0.1:18123/health health 120 \
  || ! check_json http://127.0.0.1:18123/catalog/poets catalog \
  || ! check_json http://127.0.0.1:18123/knowledge/status knowledge 120; then
  cat "$INCOMING_DIR/api-preflight.log" >&2
  cleanup_preflight
  exit 1
fi
cleanup_preflight

mkdir -p "$API_DROPIN_DIR" "$WEB_DROPIN_DIR"
if [ -f "$API_DROPIN" ]; then
  cp -a "$API_DROPIN" "$INCOMING_DIR/api-dropin.before"
  DROPIN_EXISTED=1
fi
if [ -f "$WEB_DROPIN" ]; then
  cp -a "$WEB_DROPIN" "$INCOMING_DIR/web-dropin.before"
  WEB_DROPIN_EXISTED=1
fi

rollback() {
  local exit_code=$?
  [ "$exit_code" -ne 0 ] || exit_code=1
  trap - ERR HUP INT TERM
  cleanup_preflight
  if [ "$SWITCHED" -eq 1 ]; then
    if [ -n "$OLD_WEB" ] && [ -d "$OLD_WEB" ]; then
      ln -sfn "$OLD_WEB" "$WEB_BASE/current.rollback"
      mv -Tf "$WEB_BASE/current.rollback" "$WEB_BASE/current"
    else
      rm -f "$WEB_BASE/current"
    fi

    if [ -n "$OLD_API" ] && [ -d "$OLD_API" ]; then
      ln -sfn "$OLD_API" "$API_BASE/current.rollback"
      mv -Tf "$API_BASE/current.rollback" "$API_BASE/current"
    else
      rm -f "$API_BASE/current"
    fi
  fi

  if [ "$STATIC_SWITCHED" -eq 1 ]; then
    if [ -n "$BOOTSTRAP_STATIC" ]; then
      rm -f "$STATIC_LINK"
      mv "$BOOTSTRAP_STATIC" "$STATIC_LINK"
    elif [ -n "$OLD_STATIC" ] && [ -d "$OLD_STATIC" ]; then
      ln -sfn "$OLD_STATIC" "$STATIC_LINK.rollback"
      mv -Tf "$STATIC_LINK.rollback" "$STATIC_LINK"
    fi
  fi

  if [ "$DROPIN_EXISTED" -eq 1 ]; then
    cp -a "$INCOMING_DIR/api-dropin.before" "$API_DROPIN"
  else
    rm -f "$API_DROPIN"
  fi
  if [ "$WEB_DROPIN_EXISTED" -eq 1 ]; then
    cp -a "$INCOMING_DIR/web-dropin.before" "$WEB_DROPIN"
  else
    rm -f "$WEB_DROPIN"
  fi
  systemctl daemon-reload || true
  systemctl restart "$API_SERVICE" || true
  if [ -n "$OLD_WEB" ]; then
    systemctl restart "$WEB_SERVICE" || true
  else
    systemctl stop "$WEB_SERVICE" || true
  fi
  echo "deployment failed; previous release restored" >&2
  exit "$exit_code"
}
trap rollback ERR HUP INT TERM

cat >"$API_DROPIN.next" <<EOF
[Service]
WorkingDirectory=$API_BASE/current/apps/agent-ui/agent
ExecStart=
ExecStart=/usr/bin/python3 $API_BASE/current/poetry-agent.pex
Environment=PEX_ROOT=$API_BASE/pex-cache
EOF
chmod 644 "$API_DROPIN.next"
mv -f "$API_DROPIN.next" "$API_DROPIN"

cat >"$WEB_DROPIN.next" <<EOF
[Service]
WorkingDirectory=$WEB_BASE/current
ExecStart=
ExecStart=/usr/local/bin/node $WEB_BASE/current/server.js
Environment=NODE_ENV=production
Environment=HOSTNAME=0.0.0.0
Environment=PORT=3000
Environment=POETRY_AGENT_BACKEND_URL=http://127.0.0.1:8123
EOF
chmod 644 "$WEB_DROPIN.next"
mv -f "$WEB_DROPIN.next" "$WEB_DROPIN"

SWITCHED=1
ln -sfn "$NEW_WEB" "$WEB_BASE/current.next"
mv -Tf "$WEB_BASE/current.next" "$WEB_BASE/current"
ln -sfn "$NEW_API" "$API_BASE/current.next"
mv -Tf "$API_BASE/current.next" "$API_BASE/current"

if [ -L "$STATIC_LINK" ]; then
  ln -sfn "$NEW_STATIC" "$STATIC_LINK.next"
  mv -Tf "$STATIC_LINK.next" "$STATIC_LINK"
  STATIC_SWITCHED=1
else
  BOOTSTRAP_STATIC="$STATIC_BASE/bootstrap-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$STATIC_LINK" "$BOOTSTRAP_STATIC"
  STATIC_SWITCHED=1
  ln -s "$NEW_STATIC" "$STATIC_LINK"
fi

systemctl daemon-reload
systemctl restart "$API_SERVICE"
systemctl restart "$WEB_SERVICE"

wait_for_api http://127.0.0.1:8123/openapi.json
for attempt in $(seq 1 8); do
  if check_json http://127.0.0.1:8123/health health 120 \
    && check_json http://127.0.0.1:8123/catalog/poets catalog \
    && check_json http://127.0.0.1:8123/knowledge/status knowledge 120 \
    && curl -fsS --max-time 15 http://127.0.0.1:3000/ >/dev/null \
    && curl -fsS --max-time 15 http://127.0.0.1:3000/api/backend/catalog >/dev/null \
    && curl -fsS --max-time 15 http://127.0.0.1:3000/api/backend/knowledge/status >/dev/null \
    && curl -fsS --max-time 15 http://127.0.0.1/ >/dev/null; then
    break
  fi
  if [ "$attempt" -eq 8 ]; then
    false
  fi
  sleep 4
done

trap - ERR HUP INT TERM

prune_releases() {
  local base="$1"
  local current="$2"
  local -a old_releases
  mapfile -t old_releases < <(
    find "$base" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
      | sort -nr | tail -n +4 | cut -d' ' -f2-
  )
  for path in "${old_releases[@]}"; do
    [ "$(readlink -f "$path")" = "$(readlink -f "$current")" ] || rm -rf -- "$path"
  done
}

prune_releases "$WEB_BASE/releases" "$WEB_BASE/current"
prune_releases "$API_BASE/releases" "$API_BASE/current"
prune_releases "$STATIC_BASE" "$STATIC_LINK"

cd /
rm -rf "$INCOMING_DIR"
echo "deployed $VERSION"
