#!/usr/bin/env bash
set -euo pipefail
if [[ "${CI:-}" != "true" || -z "${GITHUB_RUN_ID:-}" || -z "${CAMPUS_M2_CONTRACT_SERVER:-}" ]]; then
  echo "Requires isolated CI and an explicitly pinned C checkout." >&2
  exit 2
fi
: "${CAMPUS_BOOTSTRAP_PASSWORD:?Synthetic password required}"
: "${CAMPUS_RESOURCES_SERVICE_TOKEN:?Synthetic service token required}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
c_backend="${CAMPUS_M2_CONTRACT_SERVER}/backend"
resource_pid=""; backend_pid=""; frontend_pid=""
cleanup() {
  result=$?
  trap - EXIT
  for child in "$frontend_pid" "$backend_pid" "$resource_pid"; do
    if [[ -n "$child" ]]; then kill "$child" 2>/dev/null || true; fi
  done
  if [[ "$result" != 0 ]]; then
    tail -n 80 "$RUNNER_TEMP/c-v1-backend.log" "$RUNNER_TEMP/c-v1-frontend.log" 2>/dev/null || true
  fi
  exit "$result"
}
trap cleanup EXIT
export CAMPUS_C_ENABLED=true
export CAMPUS_C_CONFIG_FILE="$RUNNER_TEMP/c-v1-runtime.json"
export CAMPUS_DEV_BACKEND_URL=http://127.0.0.1:18000
export CAMPUS_M2_LIVE_ORIGIN=http://127.0.0.1:5173
export CAMPUS_M2_RESOURCE_FIXTURE_ORIGIN=http://127.0.0.1:18111
python - <<'CONFIG'
import json, os
from pathlib import Path
source = Path(os.environ['CAMPUS_M2_CONTRACT_SERVER'])/'backend/app/modules/m2_approval/examples/runtime.synthetic.json'
config = json.loads(source.read_text())
config['resources']['base_url']='http://127.0.0.1:18111'
Path(os.environ['CAMPUS_C_CONFIG_FILE']).write_text(json.dumps(config))
CONFIG
python "$repo_root/infra/scripts/c-v1-resource-fixture.py" > "$RUNNER_TEMP/c-v1-resources.log" 2>&1 &
resource_pid=$!
cd "$c_backend"
python -m alembic upgrade head
for role in synthetic-student synthetic-first-reviewer synthetic-second-reviewer; do
  case "$role" in
    synthetic-student) account=m2-live-student ;;
    synthetic-first-reviewer) account=m2-live-reviewer-one ;;
    synthetic-second-reviewer) account=m2-live-reviewer-two ;;
  esac
  python -m app.common.auth.bootstrap --username "$account" --department-id synthetic-department \
    --roles-file app/modules/m2_approval/examples/roles.synthetic.json --role "$role" --room 1 \
    --password-env CAMPUS_BOOTSTRAP_PASSWORD
 done
python -m uvicorn app.main:app --host 127.0.0.1 --port 18000 > "$RUNNER_TEMP/c-v1-backend.log" 2>&1 &
backend_pid=$!
cd "$repo_root"
npm run dev --prefix frontend -- --host 127.0.0.1 > "$RUNNER_TEMP/c-v1-frontend.log" 2>&1 &
frontend_pid=$!
python - <<'WAIT'
import json, time, urllib.request, urllib.error
for port in (18000,5173):
    for _ in range(60):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready',timeout=3) as response:
                assert json.load(response)['scope']=='m2'
            break
        except (urllib.error.URLError,TimeoutError):
            time.sleep(1)
    else:
        raise SystemExit('Real C service/proxy did not become ready')
WAIT
npm run test:integration --prefix frontend
