#!/usr/bin/env bash
set -Eeuo pipefail

repo_root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
project_name="nexo-image-smoke-$(date -u +%Y%m%d%H%M%S)-${RANDOM}${RANDOM}"
compose_file="$repo_root/tests/ops/compose-image-smoke.yml"
export POSTGRES_USER=smoke_user
export POSTGRES_DB=smoke_db
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
export NEXO_CORS_ORIGINS=

compose() {
  docker compose --project-name "$project_name" --file "$compose_file" "$@"
}

cleanup() {
  result=$?
  trap - EXIT
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

compose up -d --wait --wait-timeout 120
port=$(compose port api 8000)
port=${port##*:}
python3 - "$port" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base = f"http://127.0.0.1:{sys.argv[1]}"
request = urllib.request.Request(
    f"{base}/api/v1/health",
    headers={"Origin": "https://untrusted.example.test"},
)
with urllib.request.urlopen(request, timeout=5) as response:
    body = json.load(response)
    assert body["status"] == "ok", body
    assert body["database"] == "ok", body
    assert response.headers.get("access-control-allow-origin") is None

try:
    urllib.request.urlopen(
        urllib.request.Request(
            f"{base}/api/v1/auth/register",
            data=b"x" * 65,
            headers={"Content-Type": "application/json"},
            method="POST",
        ),
        timeout=5,
    )
except urllib.error.HTTPError as error:
    assert error.code == 413, error.code
    assert json.load(error)["error"]["code"] == "request_too_large"
else:
    raise AssertionError("the production request-body limit was not enforced")
print("Image smoke passed: migrations, health, CORS default, and HTTP body limit")
PY