#!/usr/bin/env bash
set -euo pipefail

# This script owns only an ephemeral GitHub runner project, including its volumes.
# Never use it as a developer or production cleanup command.
if [[ "${CI:-}" != "true" || -z "${GITHUB_RUN_ID:-}" ]]; then
  echo "This smoke script requires an isolated GitHub Actions runner." >&2
  exit 2
fi
: "${CAMPUS_DB_PASSWORD:?Set a synthetic CI database password}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
compose=(docker compose --project-name "campus-ci-${GITHUB_RUN_ID}" -f infra/compose.yaml)
cleanup() {
  result=$?
  trap - EXIT
  "${compose[@]}" logs --no-color --tail=100 || true
  "${compose[@]}" down --volumes --remove-orphans || true
  exit "$result"
}
trap cleanup EXIT

"${compose[@]}" config --quiet
"${compose[@]}" up --build --detach --wait --wait-timeout 180
"${compose[@]}" run --rm migrate

python3 - <<'CHECK'
import json
import re
import urllib.request

for port in (8000, 8080):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=10) as response:
        assert response.status == 200
        assert json.load(response)["database"] == "connected"
with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=10) as response:
    page = response.read().decode()
    assert "校园资源服务平台" in page
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page)
    assert assets, "Frontend must serve built assets, not an empty HTML shell"
for asset in assets:
    with urllib.request.urlopen("http://127.0.0.1:8080" + asset, timeout=10) as response:
        assert response.status == 200 and response.read()
print("PASS frontend assets, backend/proxy readiness, initial and repeated migration")
CHECK

"${compose[@]}" stop db
python3 - <<'CHECK'
import json
import urllib.error
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/health/live", timeout=10) as response:
    assert response.status == 200
for port in (8000, 8080):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=10)
    except urllib.error.HTTPError as response:
        assert response.code == 503
        assert json.load(response)["database"] == "unavailable"
    else:
        raise AssertionError("Database outage must not report ready")
print("PASS database outage produces 503 while HTTP process remains alive")
CHECK

"${compose[@]}" start db
python3 - <<'CHECK'
import json
import time
import urllib.error
import urllib.request

for attempt in range(30):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health/ready", timeout=5) as response:
            assert json.load(response)["database"] == "connected"
        print("PASS PostgreSQL recovery through frontend proxy")
        break
    except (urllib.error.URLError, TimeoutError):
        time.sleep(1)
else:
    raise AssertionError("Database did not recover within bounded retries")
CHECK
