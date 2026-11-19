#! /bin/bash

# Event-timeline dashboard (event-timeline-tiled) on this instrument PC, under
# rootless Podman, on the host network, listening on 127.0.0.1 only.
#
# run this in the "bluesky_dashboard" screen:
#   ./start-mouse-dashboard.sh              start the stack in the foreground (Ctrl-C stops it)
# once per event-timeline-tiled release, with network access:
#   ./start-mouse-dashboard.sh --install    build the images and pull the proxy image, then exit
# once, after the first start (idempotent):
#   ./start-mouse-dashboard.sh --viewer     create or update the read-only Grafana login "mouse"
# anything else, with this stack's compose files and settings:
#   ./start-mouse-dashboard.sh --compose logs adapter
#
# See design_documentation/operations.md, "Event-timeline dashboard".
set -euo pipefail

refuse() {
    printf '%s\n' "dashboard refused: $1" >&2
    exit 1
}

ett_dir=${ETT_DIR:-$HOME/code/event_timeline_tiled}
compose=$HOME/.local/bin/docker-compose
conf=$HOME/.config/mouse-dashboard
tiled_key=$HOME/.tiled_api.key
queue_key=$HOME/.config/mouse-http-server/dashboard.key
admin_password=$conf/grafana-admin.password
viewer_password=$conf/grafana-viewer.password
socket=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/podman/podman.sock

# GNU stat (Linux), then BSD stat (macOS).
file_stat() {
    stat -c "$1" "$3" 2>/dev/null || stat -f "$2" "$3" 2>/dev/null
}

# A secret is a non-empty regular file, owned by this user, mode 600 or stricter.
check_secret() {
    local file=$1 mode owner
    [ -f "$file" ] && [ -r "$file" ] && [ -s "$file" ] || refuse "missing, unreadable or empty: $file"
    owner=$(file_stat '%u' '%u' "$file") || refuse "cannot check the owner of $file"
    [ "$owner" = "$(id -u)" ] || refuse "not owned by $(id -un): $file"
    mode=$(file_stat '%a' '%Lp' "$file") || refuse "cannot check the permissions of $file"
    (( (8#$mode & 077) == 0 )) || refuse "readable by group or others: $file (chmod 600)"
}

mode=start
case "${1:-}" in
    '') ;;
    --install) mode=install ;;
    --viewer) mode=viewer ;;
    --compose) mode=compose; shift ;;
    *) refuse "unknown option: $1" ;;
esac
[ "$mode" = compose ] || [ $# -le 1 ] || refuse "unexpected arguments after $1"

check_secret "$tiled_key"
check_secret "$queue_key"
check_secret "$admin_password"
[ "$mode" != viewer ] || check_secret "$viewer_password"
[ -x "$compose" ] || refuse "no docker-compose at $compose"
[ -S "$socket" ] || refuse "Podman's socket is not running: systemctl --user enable --now podman.socket"
[ -f "$ett_dir/deploy/compose.host.yaml" ] || refuse "no event-timeline-tiled checkout at $ett_dir"
# Every setting comes from here; a .env would add its own, such as a demo profile.
[ ! -e "$ett_dir/deploy/.env" ] || refuse "remove $ett_dir/deploy/.env; this script sets everything"
unset COMPOSE_FILE COMPOSE_PROFILES COMPOSE_ENV_FILES COMPOSE_PROJECT_NAME

export DOCKER_HOST="unix://$socket"
export ETT_TILED_URL=https://tiled.scicat65.ddnss.de
# Interim: the RE's own key, because single-user Tiled has no read-only keys.
export ETT_TILED_KEY_FILE=$tiled_key
export ETT_QUEUE_KEY_FILE=$queue_key
export ETT_QUEUES=MOUSE=http:http://127.0.0.1:60610
export ETT_CATALOG_ROOTS=
# Under rootless Podman, container root is this user, so the adapter reads the mode-600 keys.
export ETT_ADAPTER_USER=0:0
export ETT_HTTP_PORT=8080 ETT_GRAFANA_PORT=3000 ETT_ADAPTER_PORT=8000
export ETT_PUBLIC_URL=http://127.0.0.1:8080/
# Grafana uses this only when it first creates its database.
GF_ADMIN_PASSWORD=$(<"$admin_password")
export GF_ADMIN_PASSWORD

cd "$ett_dir"
files=(-f deploy/compose.yaml -f deploy/compose.host.yaml)
case "$mode" in
    start)
        exec "$compose" "${files[@]}" up --no-build --pull never
        ;;
    install)
        export DOCKER_BUILDKIT=0
        "$compose" "${files[@]}" build
        exec "$compose" "${files[@]}" pull proxy
        ;;
    viewer)
        exec python3 deploy/grafana_viewer.py --url "http://127.0.0.1:$ETT_GRAFANA_PORT" --login mouse \
            --password-file "$viewer_password" --admin-password-file "$admin_password"
        ;;
    compose)
        exec "$compose" "${files[@]}" "$@"
        ;;
esac
