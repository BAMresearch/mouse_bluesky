#! /bin/bash

# run this in the "bluesky_http" screen:
set -e

refuse() {
    printf '%s\n' "HTTP server refused: $1" >&2
    exit 1
}

check_auth_environment() {
    [ "${QSERVER_HTTP_SERVER_SINGLE_USER_API_KEY+x}" != x ] ||
        refuse 'QSERVER_HTTP_SERVER_SINGLE_USER_API_KEY is set'
    [ "${QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS+x}" != x ] ||
        refuse 'QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS is set'
}

check_auth_environment
env_file=${MOUSE_HTTP_ENV_FILE:-$HOME/.config/mouse-http-server/env}
[ -f "$env_file" ] && [ -r "$env_file" ] || refuse 'environment file is missing or unreadable'
# GNU stat (Linux), then BSD stat (macOS).
env_mode=$(stat -c '%a' "$env_file" 2>/dev/null || stat -f '%Lp' "$env_file" 2>/dev/null) ||
    refuse 'cannot check environment file permissions'
(( (8#$env_mode & 044) == 0 )) || refuse 'environment file is readable by group or others'

set -a
source "$env_file" >/dev/null 2>&1 || refuse 'cannot load environment file'
set +a
check_auth_environment
[ -n "${MOUSE_HTTP_READER_PASSWORD:-}" ] || refuse 'MOUSE_HTTP_READER_PASSWORD is unset or empty'
[ -n "${MOUSE_HTTP_DATABASE_URI:-}" ] || refuse 'MOUSE_HTTP_DATABASE_URI is unset or empty'

host=${MOUSE_HTTP_HOST:-127.0.0.1}
port=${MOUSE_HTTP_PORT:-60610}
# Empty strings disable uvicorn TLS on loopback and prevent literal ${...} paths.
export MOUSE_HTTP_SSL_CERTFILE=${MOUSE_HTTP_SSL_CERTFILE:-}
export MOUSE_HTTP_SSL_KEYFILE=${MOUSE_HTTP_SSL_KEYFILE:-}
if [ "$host" != 127.0.0.1 ] && [ "$host" != localhost ] ||
    [ -n "$MOUSE_HTTP_SSL_CERTFILE" ] || [ -n "$MOUSE_HTTP_SSL_KEYFILE" ]; then
    [ -n "$MOUSE_HTTP_SSL_CERTFILE" ] && [ -f "$MOUSE_HTTP_SSL_CERTFILE" ] &&
        [ -r "$MOUSE_HTTP_SSL_CERTFILE" ] && [ -n "$MOUSE_HTTP_SSL_KEYFILE" ] &&
        [ -f "$MOUSE_HTTP_SSL_KEYFILE" ] && [ -r "$MOUSE_HTTP_SSL_KEYFILE" ] ||
        refuse 'TLS requires readable MOUSE_HTTP_SSL_CERTFILE and MOUSE_HTTP_SSL_KEYFILE'
fi

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec start-bluesky-httpserver --config_path "$repo_dir/qserver_profile/http_server/config.yml" \
    --host "$host" --port "$port"
