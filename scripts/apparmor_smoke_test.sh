#!/usr/bin/env bash
# Runs the app image under its AppArmor profile with the Sonos simulation and walks
# through admin + guest requests. Fails on any AppArmor denial (plan 6, phase 5).
# Needs: Linux with AppArmor, docker, sudo (used in CI on ubuntu-latest).
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-sobo-apparmor-test}"
DATA="$(mktemp -d)"
NAME="sobo-apparmor-$$"

cleanup() {
  docker logs "$NAME" 2>&1 | tail -n 40 || true
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sudo apparmor_parser --replace sobo/apparmor.txt
docker build -q -t "$IMAGE" sobo >/dev/null
since="$(date '+%Y-%m-%d %H:%M:%S')"

docker run -d --name "$NAME" --network host \
  --security-opt apparmor=sobo \
  -v "$DATA:/data" \
  -e SOBO_FAKE_SONOS=1 -e SOBO_FAKE_SPEED=20 -e SOBO_TRUSTED_INGRESS=127.0.0.1 \
  "$IMAGE" >/dev/null

for _ in $(seq 60); do
  curl -fsS -o /dev/null http://127.0.0.1:8737/ && break
  sleep 1
done
curl -fsS http://127.0.0.1:8737/ | grep -q "<title>SoBo</title>"
profile="$(docker inspect -f '{{.AppArmorProfile}}' "$NAME")"
[[ "$profile" == "sobo" ]] || { echo "unexpected AppArmor profile: $profile" >&2; exit 1; }
sudo cat /proc/"$(docker inspect -f '{{.State.Pid}}' "$NAME")"/attr/current
# The backend must run in the child profile, not in the outer one.
backend_pid="$(pgrep -f -n 'python3 -m sobo')"
label="$(sudo cat /proc/"$backend_pid"/attr/current)"
echo "backend: $label"
[[ "$label" == "sobo//sobo_python (enforce)" ]] || { echo "backend not in sobo_python" >&2; exit 1; }

# Configure and switch on (admin API), then a guest flow through the internal API.
settings="$(curl -fsS http://127.0.0.1:8737/api/settings)"
settings="$(jq '.speaker.coordinator_uid = "RINCON_FAKE_LIVING" | .account_id = "fake-apple-1"
  | .fallback.source_id = "fake_playlist:party" | .active = true' <<<"$settings")"
curl -fsS -X PUT -H "X-SoBo-Request: 1" -H 'Content-Type: application/json' -d "$settings" http://127.0.0.1:8737/api/settings >/dev/null
curl -fsS -X POST -H "X-SoBo-Request: 1" -H "Content-Type: application/json" -d "{\"active\": true}" http://127.0.0.1:8737/api/jukebox >/dev/null

secret="$(sudo cat "$DATA/secret")"
guest() {
  curl -fsS -X POST -H "X-SoBo-Secret: $secret" -H 'Content-Type: application/json' \
    -d "$1" http://127.0.0.1:8738/internal/guest
}
session="$(guest '{"action":"join","nickname":"Smoke"}' | jq -r .session)"
result="$(guest "{\"action\":\"search\",\"session\":\"$session\",\"q\":\"comet\"}" | jq -r '.results[0].id')"
guest "{\"action\":\"suggest\",\"session\":\"$session\",\"result\":\"$result\"}" | jq -e .ok >/dev/null
guest "{\"action\":\"wait\",\"session\":\"$session\",\"since\":0,\"timeout\":5}" | jq -e .ok >/dev/null
sleep 3
curl -fsS http://127.0.0.1:8737/api/status | jq -e '.state | startswith("playing")' >/dev/null
curl -fsS 'http://127.0.0.1:8737/api/audit?limit=5' | jq -e 'length > 0' >/dev/null

# Restart: the database and secret must survive under the profile.
docker restart "$NAME" >/dev/null
for _ in $(seq 60); do
  curl -fsS -o /dev/null http://127.0.0.1:8737/api/status && break
  sleep 1
done
curl -fsS http://127.0.0.1:8737/api/settings | jq -e '.speaker.coordinator_uid == "RINCON_FAKE_LIVING"' >/dev/null

denials="$(sudo journalctl -k --since "$since" --no-pager | grep 'apparmor="DENIED"' | grep 'profile="sobo' || true)"
if [[ -n "$denials" ]]; then
  echo "AppArmor denials:" >&2
  echo "$denials" >&2
  exit 1
fi
echo "AppArmor smoke test passed"
