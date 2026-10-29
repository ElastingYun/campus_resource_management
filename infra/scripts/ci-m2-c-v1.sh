#!/usr/bin/env bash
set -euo pipefail
if [[ "${CI:-}" != "true" || -z "${GITHUB_RUN_ID:-}" || -z "${CAMPUS_M2_CONTRACT_SERVER:-}" ]]; then
  echo "Requires isolated CI and the pinned C+B acceptance workspace." >&2
  exit 2
fi
: "${CAMPUS_BOOTSTRAP_PASSWORD:?Synthetic password required}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
c_backend="${CAMPUS_M2_CONTRACT_SERVER}/backend"
backend_pid=""; frontend_pid=""
cleanup() {
  result=$?
  trap - EXIT
  for child in "$frontend_pid" "$backend_pid"; do
    if [[ -n "$child" ]]; then kill "$child" 2>/dev/null || true; fi
  done
  if [[ "$result" != 0 ]]; then
    tail -n 80 "$RUNNER_TEMP/c-v1-backend.log" "$RUNNER_TEMP/c-v1-frontend.log" 2>/dev/null || true
  fi
  exit "$result"
}
trap cleanup EXIT
acceptance_stage=configuration
trap 'echo "::error file=infra/scripts/ci-m2-c-v1.sh,line=${LINENO}::M2 acceptance failed during ${acceptance_stage}"' ERR
umask 077
export CAMPUS_C_ENABLED=true
export CAMPUS_C_CONFIG_FILE="$RUNNER_TEMP/c-v1-runtime.json"
export CAMPUS_RESOURCE_HOST_CONFIG="$RUNNER_TEMP/m2-resource-host.json"
export CAMPUS_DEV_BACKEND_URL=http://127.0.0.1:18000
export CAMPUS_M2_LIVE_ORIGIN=http://127.0.0.1:5173
# Used only while provisioning; replaced with a real, memory-only C service session.
export CAMPUS_RESOURCES_SERVICE_TOKEN=synthetic-provisioning-placeholder
python - <<'CONFIG'
import json, os
from pathlib import Path
source = Path(os.environ['CAMPUS_M2_CONTRACT_SERVER'])/'backend/app/modules/m2_approval/examples'
config = json.loads((source/'runtime.synthetic.json').read_text())
config['resources']['base_url']='http://127.0.0.1:18000'
config['submission']['room_access_policy']='campus_or_own_department'
config['submission']['allow_cross_department']=False
Path(os.environ['CAMPUS_C_CONFIG_FILE']).write_text(json.dumps(config))
roles = json.loads((source/'roles.synthetic.json').read_text())
roles['synthetic-resource-reader']=['synthetic.resource.read']
(Path(os.environ['RUNNER_TEMP'])/'m2-roles.json').write_text(json.dumps(roles))
host = {'permissions': {'read': 'synthetic.resource.read', 'manage': 'synthetic.resource.manage', 'create_rooms': 'synthetic.resource.create'}, 'room_options_permission': 'm2.submit'}
Path(os.environ['CAMPUS_RESOURCE_HOST_CONFIG']).write_text(json.dumps(host))
CONFIG
cd "$c_backend"
acceptance_stage=migrations
python -m alembic upgrade head
python -m alembic upgrade head
acceptance_stage=account-provisioning
for role in synthetic-student synthetic-first-reviewer synthetic-second-reviewer synthetic-resource-reader; do
  case "$role" in
    synthetic-student) account=m2-live-student ;;
    synthetic-first-reviewer) account=m2-live-reviewer-one ;;
    synthetic-second-reviewer) account=m2-live-reviewer-two ;;
    synthetic-resource-reader) account=m2-live-resource-reader ;;
  esac
  scope=(--room 9007199254740993)
  if [[ "$role" == synthetic-resource-reader ]]; then scope=(--all-rooms); fi
  python -m app.common.auth.bootstrap --username "$account" --department-id synthetic-department \
    --roles-file "$RUNNER_TEMP/m2-roles.json" --role "$role" "${scope[@]}" \
    --password-env CAMPUS_BOOTSTRAP_PASSWORD
 done
python -m app.common.auth.bootstrap --username m2-browser-student --department-id synthetic-department \
  --roles-file "$RUNNER_TEMP/m2-roles.json" --role synthetic-student --room 9007199254740993 \
  --password-env CAMPUS_BOOTSTRAP_PASSWORD
acceptance_stage=synthetic-resource-seed
PYTHONPATH="$c_backend" python "$repo_root/infra/scripts/seed-m2-room-acceptance.py"
CAMPUS_RESOURCES_SERVICE_TOKEN="$(cat "$RUNNER_TEMP/m2-resource-session")"
export CAMPUS_RESOURCES_SERVICE_TOKEN
PYTHONPATH="$repo_root/infra/runtime:$c_backend" python -m uvicorn m2_resources:create_app --factory --host 127.0.0.1 --port 18000 > "$RUNNER_TEMP/c-v1-backend.log" 2>&1 &
backend_pid=$!
cd "$repo_root"
npm run dev --prefix frontend -- --host 127.0.0.1 > "$RUNNER_TEMP/c-v1-frontend.log" 2>&1 &
frontend_pid=$!
acceptance_stage=service-readiness
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
        raise SystemExit('Real C+B service/proxy did not become ready')
WAIT
acceptance_stage=real-http-acceptance
npm run test:integration --prefix frontend
acceptance_stage=real-browser-acceptance
npm run test:e2e --prefix frontend
