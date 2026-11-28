#!/usr/bin/env bash
# One command to deploy (first time) or update (every later time) the Nazria API on Ubuntu 20.04 / 22.04 / 24.04:
#   git -> Python venv -> requirements -> configuration -> database -> gunicorn (systemd) -> Apache on port 95
#
#   sudo bash deploy_apache.sh
#
# Safe to run again: it pulls the latest code, installs new requirements, migrates and restarts. It never deletes
# data, never changes database settings, and never prints the database URL or other secrets.
# The guide behind each step: knowledge_base/deploy/DEPLOY_UBUNTU_APACHE.md
#
#   sudo bash deploy_apache.sh --set-database     asks again for the database (host, port, name, user, password),
#                                                 writes it correctly encoded into the settings, then deploys
set -Eeuo pipefail
SET_DATABASE=no
case "${1:-}" in
    --set-database) SET_DATABASE=yes ;;
    "") ;;
    *) echo "unknown option: $1  (the only option is --set-database)" >&2; exit 2 ;;
esac

# ------------------------------------------------------------------------------------------------ settings
# Change these here, or set them when running:  sudo PORT=8095 bash deploy_apache.sh
APP_DIR="${APP_DIR:-/home/python-www/nazria_mufrad_aza}"          # the git checkout
VENV="${VENV:-$APP_DIR/venv}"                                       # the Python virtual environment
APACHE_SITES="${APACHE_SITES:-/etc/apache2/sites-available}"
PORT="${PORT:-95}"
REPO_URL="${REPO_URL:-git@github.com:idreesgis/nazria_mufrad_aza.git}"
BRANCH="${BRANCH:-main}"
RUN_USER="${RUN_USER:-nazria}"                                     # system user that runs the API
ENV_FILE="${ENV_FILE:-/etc/nazria/nazria.env}"                      # settings and secrets (mode 640)
DATA_DIR="${DATA_DIR:-/var/lib/nazria}"                             # pulse videos, static files
SERVICE="${SERVICE:-nazria-api}"
SITE="${SITE:-nazria}"
SOCKET_DIR="/run/nazria"
# When the server has no Python 3.11+ (Ubuntu 20.04: 3.8, 22.04: 3.10), the project gets its own Python 3.12 here,
# installed with uv (pinned version, checksum verified). The system Python is never changed.
TOOLS_DIR="${TOOLS_DIR:-/opt/nazria-python}"
PRIVATE_PYTHON="${PRIVATE_PYTHON:-3.12}"
UV_VERSION="0.11.32"
declare -A UV_SHA256=(
    [x86_64]="aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967"
    [aarch64]="4d4fa08d95b06642e5800df6a22bd71455f23f988269e18da2847971d8c0bf31"
)
DJANGO_DIR="$APP_DIR/knowledge_base"

# ------------------------------------------------------------------------------------------------ helpers
STEP="start"
step() { STEP="$*"; printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m    ! %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mSTOPPED: %s\033[0m\n' "$*" >&2; exit 1; }
trap 'printf "\n\033[1;31mFAILED during: %s (line %s)\033[0m\n" "$STEP" "$LINENO" >&2' ERR
as_app() { sudo -u "$RUN_USER" -H "$@"; }
# manage.py as the service user; Django reads the env file itself (no shell sees the secrets)
manage() { (cd "$DJANGO_DIR" && sudo -u "$RUN_USER" -H env NAZRIA_ENV_FILE="$ENV_FILE" PYTHONDONTWRITEBYTECODE=1 \
             "$VENV/bin/python" manage.py "$@"); }
interactive() { [[ -t 0 ]]; }

[[ $EUID -eq 0 ]] || die "run it with sudo:  sudo bash $0"
command -v apt-get >/dev/null || die "this script is for Ubuntu (apt-get not found)"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "PORT must be a number"

# ------------------------------------------------------------------------------------------------ 1. packages
step "1/11 Software already on the server (git, Apache, Python 3.11+)"
export DEBIAN_FRONTEND=noninteractive
APT_UPDATED=""
apt_install() {      # installs only what is missing; nothing already installed is upgraded or changed
    [[ -n "$APT_UPDATED" ]] || { apt-get update -qq; APT_UPDATED=1; }
    info "installing: $*"
    apt-get install -y -qq --no-upgrade "$@" >/dev/null
}
MISSING=()
command -v git >/dev/null         || MISSING+=(git)
command -v curl >/dev/null        || MISSING+=(curl)
command -v ssh-keygen >/dev/null  || MISSING+=(openssh-client)
command -v apache2ctl >/dev/null  || MISSING+=(apache2)
[[ -e /etc/ssl/certs/ca-certificates.crt ]] || MISSING+=(ca-certificates)
if [[ ${#MISSING[@]} -gt 0 ]]; then apt_install "${MISSING[@]}"; fi
info "git $(git --version | awk '{print $3}') · $(apache2ctl -v 2>/dev/null | sed -n 's/^Server version: //p')"

# the project needs Python 3.11 or newer (the Gemini library, google-genai); use the newest one installed
PY=""
for p in python3.13 python3.12 python3.11 python3; do
    if command -v "$p" >/dev/null && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        PY="$(command -v "$p")"; break
    fi
done
if [[ -z "$PY" ]]; then
    # e.g. Ubuntu 20.04 (3.8) or 22.04 (3.10): a private Python for this project only
    warn "the system Python ($(python3 --version 2>&1)) is too old for the project (it needs 3.11 or newer)"
    info "installing a private Python $PRIVATE_PYTHON for this project in $TOOLS_DIR (the system Python stays as it is)"
    UV="$TOOLS_DIR/bin/uv"
    if [[ ! -x "$UV" ]] || [[ "$("$UV" --version 2>/dev/null | awk '{print $2}')" != "$UV_VERSION" ]]; then
        ARCH="$(uname -m)"
        [[ -n "${UV_SHA256[$ARCH]:-}" ]] || die "no uv build known for this processor ($ARCH)"
        TMP_UV="$(mktemp -d)"
        curl -fsSL -o "$TMP_UV/uv.tar.gz" \
            "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$ARCH-unknown-linux-gnu.tar.gz"
        echo "${UV_SHA256[$ARCH]}  $TMP_UV/uv.tar.gz" | sha256sum -c --quiet - \
            || { rm -rf "$TMP_UV"; die "the uv download does not match its published checksum; not installed"; }
        tar -xzf "$TMP_UV/uv.tar.gz" -C "$TMP_UV"
        install -d -m 755 "$TOOLS_DIR/bin"
        install -m 755 "$TMP_UV/uv-$ARCH-unknown-linux-gnu/uv" "$UV"
        rm -rf "$TMP_UV"
    fi
    export UV_PYTHON_INSTALL_DIR="$TOOLS_DIR/python" UV_CACHE_DIR="$TOOLS_DIR/cache" UV_NO_CONFIG=1
    "$UV" python install --quiet "$PRIVATE_PYTHON"
    PY="$("$UV" python find --managed-python "$PRIVATE_PYTHON")"
    chmod -R a+rX "$TOOLS_DIR/python"            # the service user runs it (read-only)
    [[ -x "$PY" ]] || die "the private Python was not installed"
fi
PYV="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
# "python -m venv" needs ensurepip, which Ubuntu ships separately (pythonX.Y-venv); the private Python has it
if ! "$PY" -c 'import ensurepip, venv' >/dev/null 2>&1; then apt_install "python${PYV}-venv"; fi
info "Python: $PY ($("$PY" --version 2>&1))"

# ------------------------------------------------------------------------------------------------ 2. user, folders
step "2/11 Service user '$RUN_USER' and folders"
if ! id "$RUN_USER" >/dev/null 2>&1; then
    adduser --system --group --home "$DATA_DIR" --shell /usr/sbin/nologin "$RUN_USER" >/dev/null
    info "created system user $RUN_USER"
fi
install -d -o "$RUN_USER" -g "$RUN_USER" -m 750 "$DATA_DIR" "$DATA_DIR/media"
install -d -o "$RUN_USER" -g www-data -m 750 "$DATA_DIR/static"
usermod -aG "$RUN_USER" www-data                       # Apache may open gunicorn's socket
[[ -d "$(dirname "$APP_DIR")" ]] || install -d -m 755 "$(dirname "$APP_DIR")"
[[ -d "$APP_DIR" ]] || install -d -o "$RUN_USER" -g "$RUN_USER" -m 755 "$APP_DIR"
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"
sudo -u "$RUN_USER" test -x "$APP_DIR" || die "user $RUN_USER cannot enter $APP_DIR: allow it, e.g. sudo chmod o+x $(dirname "$APP_DIR")"
HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"

# ------------------------------------------------------------------------------------------------ 3. code
step "3/11 Project files from git ($REPO_URL, branch $BRANCH)"
if [[ "$REPO_URL" == git@* || "$REPO_URL" == ssh://* ]]; then
    install -d -o "$RUN_USER" -g "$RUN_USER" -m 700 "$HOME_DIR/.ssh"
    if [[ ! -f "$HOME_DIR/.ssh/id_ed25519" ]]; then
        as_app ssh-keygen -q -t ed25519 -N "" -C "nazria-deploy@$(hostname)" -f "$HOME_DIR/.ssh/id_ed25519"
    fi
    as_app ssh-keyscan -t ed25519 github.com 2>/dev/null >> "$HOME_DIR/.ssh/known_hosts" || true
    sort -u -o "$HOME_DIR/.ssh/known_hosts" "$HOME_DIR/.ssh/known_hosts"; chown "$RUN_USER:" "$HOME_DIR/.ssh/known_hosts"
    if ! as_app git ls-remote --heads "$REPO_URL" >/dev/null 2>&1; then
        echo
        echo "  This server cannot read the private repository yet. Add this DEPLOY KEY on GitHub:"
        echo "  repository -> Settings -> Deploy keys -> Add deploy key  (leave 'Allow write access' OFF)"
        echo
        cat "$HOME_DIR/.ssh/id_ed25519.pub"
        echo
        die "add the key above on GitHub, then run this script again"
    fi
fi
git config --system --add safe.directory "$APP_DIR" 2>/dev/null || true
if [[ ! -d "$APP_DIR/.git" ]]; then
    # works for an empty folder and for one that already holds the venv
    as_app git -C "$APP_DIR" init -q
    as_app git -C "$APP_DIR" remote add origin "$REPO_URL"
fi
as_app git -C "$APP_DIR" remote set-url origin "$REPO_URL"
as_app git -C "$APP_DIR" fetch -q origin "$BRANCH"
if [[ -n "$(as_app git -C "$APP_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    die "files in $APP_DIR were edited on the server; save or undo those changes first (git -C $APP_DIR status)"
fi
as_app git -C "$APP_DIR" checkout -q -B "$BRANCH" "origin/$BRANCH"
grep -qx "/venv/" "$APP_DIR/.git/info/exclude" 2>/dev/null || echo "/venv/" | as_app tee -a "$APP_DIR/.git/info/exclude" >/dev/null
info "at commit $(as_app git -C "$APP_DIR" log -1 --format='%h %s')"

# ------------------------------------------------------------------------------------------------ 4. venv + requirements
step "4/11 Virtual environment ($VENV) and requirements.txt"
if [[ -x "$VENV/bin/python" ]] && ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    warn "the existing venv has Python < 3.11: making a new one"
    rm -rf "$VENV"
fi
[[ -x "$VENV/bin/python" ]] || as_app "$PY" -m venv "$VENV"
as_app "$VENV/bin/pip" install --quiet --upgrade pip wheel
as_app "$VENV/bin/pip" install --quiet -r "$DJANGO_DIR/requirements.txt"
info "installed: $("$VENV/bin/python" -c 'import django, allauth, gunicorn; print("Django", django.__version__, "· allauth", allauth.__version__, "· gunicorn", gunicorn.__version__)')"

# ------------------------------------------------------------------------------------------------ 5. configuration
step "5/11 Configuration ($ENV_FILE)"
install -d -m 750 -o root -g "$RUN_USER" "$(dirname "$ENV_FILE")"

# Asks for the database piece by piece; the URL is built (and every special character in the password encoded,
# e.g. % -> %25, @ -> %40) by Python, so nothing has to be encoded by hand.
ask_database() {
    echo "    The PostgreSQL database (the same one as the knowledge base):"
    read -r -p "      host [127.0.0.1 = this server]: " DB_HOST;   DB_HOST="${DB_HOST:-127.0.0.1}"
    read -r -p "      port [5432]: " DB_PORT;                     DB_PORT="${DB_PORT:-5432}"
    read -r -p "      database name: " DB_NAME
    read -r -p "      user: " DB_USER
    while :; do
        read -r -s -p "      password (hidden, exactly as it is, no encoding): " DB_PASS; echo
        read -r -s -p "      password again: " DB_PASS2; echo
        [[ "$DB_PASS" == "$DB_PASS2" ]] && break
        warn "the two passwords differ, again please"
    done
    unset DB_PASS2
    read -r -p "      SSL: prefer / disable / require [prefer]: " DB_SSL; DB_SSL="${DB_SSL:-prefer}"
    [[ -n "$DB_NAME" && -n "$DB_USER" ]] || die "database name and user are needed"
    [[ "$DB_PORT" =~ ^[0-9]+$ ]] || die "the port must be a number"
    [[ "$DB_SSL" =~ ^(prefer|disable|require|allow|verify-ca|verify-full)$ ]] || die "unknown SSL mode: $DB_SSL"
}

# Writes the settings file. The password goes to Python on stdin (never on a command line or in a shell variable
# of another process), and no value is ever interpreted by a shell.
write_settings() {   # $1 = new | database
    printf '%s' "$DB_PASS" | NZ_MODE="$1" NZ_HOST="${PUBLIC_HOST:-}" NZ_PORT="$PORT" NZ_DATA="$DATA_DIR" \
        NZ_OUT="$ENV_FILE" NZ_TEMPLATE="$DJANGO_DIR/deploy/nazria.env.example" \
        NZ_DB_HOST="$DB_HOST" NZ_DB_PORT="$DB_PORT" NZ_DB_NAME="$DB_NAME" NZ_DB_USER="$DB_USER" NZ_DB_SSL="$DB_SSL" \
        "$VENV/bin/python" -c '
import os, re, secrets, sys, tempfile
from urllib.parse import quote
e = os.environ
password = sys.stdin.read()
q = lambda v: quote(v, safe="")
host = e["NZ_DB_HOST"]
if ":" in host and not host.startswith("["):
    host = f"[{host}]"                                   # IPv6
user, port, name, ssl = e["NZ_DB_USER"], e["NZ_DB_PORT"], e["NZ_DB_NAME"], e["NZ_DB_SSL"]
url = f"postgresql://{q(user)}:{q(password)}@{host}:{port}/{q(name)}?sslmode={ssl}"
if e["NZ_MODE"] == "new":
    text = open(e["NZ_TEMPLATE"], encoding="utf-8").read()
    h, p = e["NZ_HOST"], e["NZ_PORT"]
    values = {
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(50), "DJANGO_DEBUG": "false",
        "DJANGO_ALLOWED_HOSTS": f"{h},localhost,127.0.0.1",
        "DJANGO_CSRF_TRUSTED_ORIGINS": f"http://{h}" + ("" if p == "80" else f":{p}"),
        "NAZRIA_HTTPS": "false", "NAZRIA_TRUST_PROXY": "true", "NAZRIA_API_CACHE": "db",
        "NAZRIA_MEDIA_ROOT": e["NZ_DATA"] + "/media", "NAZRIA_STATIC_ROOT": e["NZ_DATA"] + "/static",
        "NAZRIA_ENGINE": "questionnaire",
    }
else:
    text = open(e["NZ_OUT"], encoding="utf-8").read()
    values = {}
values["NAZRIA_DATABASE_URL"] = url
for k, v in values.items():
    text, n = re.subn(rf"(?m)^{k}=.*$", lambda m: f"{k}={v}", text)
    if not n:
        text = text.rstrip("\n") + f"\n{k}={v}\n"
d = os.path.dirname(e["NZ_OUT"])
fd, tmp = tempfile.mkstemp(dir=d, prefix=".nazria.env.")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write(text)
os.chmod(tmp, 0o640)
os.replace(tmp, e["NZ_OUT"])                              # all or nothing
'
    unset DB_PASS
    chown root:"$RUN_USER" "$ENV_FILE"; chmod 640 "$ENV_FILE"
}

if [[ ! -f "$ENV_FILE" ]]; then
    interactive || die "$ENV_FILE does not exist yet: run the script in a terminal once, so it can ask for the settings"
    DEFAULT_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    read -r -p "    Public IP (or domain) of this server [$DEFAULT_IP]: " PUBLIC_HOST
    PUBLIC_HOST="${PUBLIC_HOST:-$DEFAULT_IP}"
    [[ -n "$PUBLIC_HOST" ]] || die "the public IP is needed"
    ask_database
    write_settings new
    info "written (owner root, group $RUN_USER, mode 640). Social sign-in and the AI explanation can be added there later."
elif [[ "$SET_DATABASE" == yes ]]; then
    interactive || die "--set-database asks questions: run it in a terminal"
    cp -p "$ENV_FILE" "$ENV_FILE.bak"                  # the previous settings, just in case (mode 640)
    ask_database
    write_settings database
    info "database settings updated (the previous file is kept as $ENV_FILE.bak)"
else
    chown root:"$RUN_USER" "$ENV_FILE"; chmod 640 "$ENV_FILE"
    info "kept as it is (to enter the database again: sudo bash $0 --set-database)"
fi
grep -qE '^NAZRIA_DATABASE_URL=(postgres|postgis)' "$ENV_FILE" || die "NAZRIA_DATABASE_URL is not set in $ENV_FILE"

# ------------------------------------------------------------------------------------------------ 6. database
step "6/11 Database connection"
# connects once and explains a failure (host, port, user and the server's own message; never the password)
if ! (cd "$DJANGO_DIR" && timeout 60 sudo -u "$RUN_USER" -H env NZ_ENV="$ENV_FILE" PYTHONDONTWRITEBYTECODE=1 \
        "$VENV/bin/python" - <<'PYEOF'
import os, sys
os.environ["NAZRIA_ENV_FILE"] = os.environ["NZ_ENV"]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nazria_api.settings")
import django
django.setup()                                       # reads the URL exactly as the API will (postgis:// too)
from django.conf import settings
from django.db import connection
db = settings.DATABASES["default"]
where = (f"host {db['HOST'] or '(local socket)'}, port {db['PORT'] or 5432}, user {db['USER'] or '?'}, "
         f"database {db['NAME'] or '?'}, sslmode {db['OPTIONS'].get('sslmode', '(default: prefer)')}")
try:
    connection.ensure_connection()
except Exception as e:                               # noqa: BLE001 - explain, then stop
    msg = " ".join(str(e).split())
    if db["PASSWORD"]:
        msg = msg.replace(db["PASSWORD"], "***")
    low = msg.lower()
    hints = []
    if "does not support ssl" in low:
        hints.append("This PostgreSQL has no SSL: change ?sslmode=require to ?sslmode=disable in the URL "
                     "(fine for a database on this same server).")
    if "connection refused" in low:
        hints.append("Nothing listens at that host and port. Is PostgreSQL running (systemctl status postgresql), "
                     "or in Docker on another port (docker ps)? For a database on this server use host 127.0.0.1.")
    if "timeout" in low or "timed out" in low or "closed the connection unexpectedly" in low:
        hints.append("No answer: a firewall or IP allowlist blocks this server, or the host is wrong.")
    if "password authentication failed" in low or "no password supplied" in low:
        hints.append("Wrong user or password. Enter them again with: sudo bash deploy_apache.sh --set-database "
                     "(type the password exactly as it is; the script encodes characters like % itself).")
    import re
    from urllib.parse import urlsplit
    raw_pw = urlsplit(os.environ.get("NAZRIA_DATABASE_URL", "")).password or ""
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw_pw):
        hints.append("The password in the URL has a % that is not encoded (it must be %25). "
                     "Run: sudo bash deploy_apache.sh --set-database")
    if "no pg_hba.conf entry" in low:
        hints.append("PostgreSQL refuses this user/host in its pg_hba.conf (the database owner's setting).")
    if "does not exist" in low:
        hints.append("The database or user name in the URL does not exist on that server.")
    if "could not translate host name" in low or "name or service not known" in low:
        hints.append("The host name in the URL cannot be resolved.")
    print(f"    tried: {where}")
    print(f"    error: {msg[:500]}")
    for h in hints:
        print(f"    hint:  {h}")
    sys.exit(1)
print(f"    {where}")
PYEOF
); then
    echo
    echo "  The database cannot be reached from this server. Enter the database again with"
    echo "    sudo bash $0 --set-database"
    echo "  or fix the database's firewall/allowlist, then run this script again."
    echo "  No database setting was changed."
    die "database not reachable"
fi
info "connected"

step "7/11 Knowledge base (schema nazria) and the API's tables (schema nazria_api)"
if (cd "$DJANGO_DIR" && sudo -u "$RUN_USER" -H env NZ_ENV="$ENV_FILE" PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -c '
import os, sys
from nazria_api.envfile import load_env_file
load_env_file(os.environ["NZ_ENV"])
from nazria_kb.__main__ import main
sys.exit(main(["verify"]))' >/dev/null 2>&1); then
    info "knowledge base: verified"
else
    warn "the knowledge base (schema nazria) is missing or incomplete. Load it once from the Urdu book CSV:"
    warn "  see DEPLOY_UBUNTU_APACHE.md, section 6 (python -m nazria_kb load --csv ...)"
fi
manage create_api_schema
manage migrate --noinput | grep -E "Apply|No migrations" | sed 's/^ */    /' || true
manage seed_questionnaire
manage createcachetable
manage collectstatic --noinput --verbosity 0
# errors stop the script; the warnings about HTTPS are expected while the server uses plain HTTP
CHECK_OUT="$(manage check --deploy --fail-level ERROR 2>&1)" || { echo "$CHECK_OUT"; die "Django's deploy check failed"; }
OTHER_WARNINGS="$(echo "$CHECK_OUT" | grep -E '^\?: \(' | grep -vE 'security\.W(004|008|012|016)' || true)"
info "deploy check passed (HTTPS warnings expected until HTTPS is set up)"
[[ -z "$OTHER_WARNINGS" ]] || echo "$OTHER_WARNINGS" | sed 's/^/    /'

# the Android app's key: created once, shown once
if manage shell --no-imports -c 'from consultations.models import ApiClient; import sys; sys.exit(0 if ApiClient.objects.filter(name="android-app").exists() else 1)' >/dev/null 2>&1; then
    info "app key 'android-app': exists (create another one in the admin if it was lost)"
else
    echo
    echo "  ----------------------------------------------------------------------------------------------"
    manage create_api_client android-app | sed 's/^/  /'
    echo "  Put it into the Android build (nazria.appKey) or the app's Settings. It is NOT stored in clear."
    echo "  ----------------------------------------------------------------------------------------------"
fi
# a first administrator, if there is none yet
if ! manage shell --no-imports -c 'from django.contrib.auth import get_user_model; import sys; sys.exit(0 if get_user_model().objects.filter(is_superuser=True).exists() else 1)' >/dev/null 2>&1; then
    if interactive; then
        echo
        read -r -p "    No administrator yet. Create one now? Phone number (e.g. 03001234567, empty = later): " ADMIN_PHONE
        if [[ -n "$ADMIN_PHONE" ]]; then
            read -r -p "    Name: " ADMIN_NAME
            manage create_staff --phone "$ADMIN_PHONE" --name "${ADMIN_NAME:-Admin}" --admin </dev/tty
        fi
    else
        warn "no administrator yet: later run  manage.py create_staff --phone 03... --name Admin --admin"
    fi
fi

# ------------------------------------------------------------------------------------------------ 8. gunicorn
step "8/11 gunicorn service ($SERVICE)"
cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
# Written by deploy_apache.sh – the Nazria REST API (Django + gunicorn) behind Apache.
[Unit]
Description=Nazria Mufrad Aza REST API (gunicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$DJANGO_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONDONTWRITEBYTECODE=1
# gunicorn listens on a Unix socket that only Apache (www-data, in group $RUN_USER) can open
RuntimeDirectory=nazria
RuntimeDirectoryMode=0750
ExecStart=$VENV/bin/gunicorn nazria_api.wsgi \\
    --bind unix:$SOCKET_DIR/gunicorn.sock --umask 007 \\
    --workers 3 --timeout 180 --graceful-timeout 30 \\
    --access-logfile - --error-logfile -
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=on-failure
RestartSec=5

# hardening: the code and venv are read-only for the service; it writes only to $DATA_DIR
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$DATA_DIR
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --quiet "$SERVICE"
systemctl restart "$SERVICE"
for _ in $(seq 1 30); do [[ -S "$SOCKET_DIR/gunicorn.sock" ]] && break; sleep 1; done
[[ -S "$SOCKET_DIR/gunicorn.sock" ]] || { journalctl -u "$SERVICE" -n 30 --no-pager || true; die "gunicorn did not start"; }
info "running"

# ------------------------------------------------------------------------------------------------ 9. Apache
step "9/11 Apache site on port $PORT ($APACHE_SITES/$SITE.conf)"
a2enmod -q proxy proxy_http headers expires rewrite >/dev/null
echo "# Written by deploy_apache.sh – Apache also listens on port $PORT for the Nazria API.
Listen $PORT" > /etc/apache2/conf-available/nazria-port.conf
a2disconf -q nazria-port-95 >/dev/null 2>&1 || true            # an older name of this file
if grep -rqsE "^\s*Listen\s+(0\.0\.0\.0:)?$PORT\s*$" /etc/apache2/ports.conf; then
    a2disconf -q nazria-port >/dev/null 2>&1 || true           # ports.conf already has it
else
    a2enconf -q nazria-port >/dev/null
fi
sed -e "s|<VirtualHost \*:95>|<VirtualHost *:$PORT>|" \
    -e "s|/var/lib/nazria/static|$DATA_DIR/static|g" \
    -e "s|unix:/run/nazria/gunicorn.sock|unix:$SOCKET_DIR/gunicorn.sock|g" \
    "$DJANGO_DIR/deploy/apache-nazria.conf" > "$APACHE_SITES/$SITE.conf"
a2ensite -q "$SITE" >/dev/null
apache2ctl configtest 2>&1 | grep -v AH00558 | sed 's/^/    /'
apache2ctl -t >/dev/null 2>&1 || die "Apache's configuration test failed (see above); nothing was restarted"
# restart (not reload): a new port is opened and www-data gets its new group
systemctl restart apache2
info "Apache restarted"

# ------------------------------------------------------------------------------------------------ 10. firewall
step "10/11 Firewall"
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "$PORT/tcp" >/dev/null && info "ufw: port $PORT/tcp allowed"
else
    info "ufw is not active: nothing to change here"
fi
info "Also open port $PORT/TCP in your hosting provider's firewall / security group, if it has one."

# ------------------------------------------------------------------------------------------------ 11. checks
step "11/11 Checks"
sleep 1
H1="$(curl -fsS --max-time 20 --unix-socket "$SOCKET_DIR/gunicorn.sock" http://localhost/api/v1/health/ || true)"
H2="$(curl -fsS --max-time 20 "http://127.0.0.1:$PORT/api/v1/health/" || true)"
[[ "$H1" == *'"database":"ok"'* ]] && info "gunicorn: ok" || die "gunicorn's health check failed: $H1  (journalctl -u $SERVICE -n 50)"
[[ "$H2" == *'"database":"ok"'* ]] && info "Apache on port $PORT: ok" \
    || die "Apache on port $PORT does not answer correctly (tail /var/log/apache2/$SITE-error.log)"
HOST_SHOWN="$(sed -n 's/^DJANGO_ALLOWED_HOSTS=\([^,]*\).*/\1/p' "$ENV_FILE")"

trap - ERR
printf '\n\033[1;32mDeployed.\033[0m\n'
cat <<DONE
    API         http://$HOST_SHOWN:$PORT/api/v1/health/
    Admin       http://$HOST_SHOWN:$PORT/admin/        (log in with the phone number as +92...)
    App         server address  http://$HOST_SHOWN:$PORT/
    Logs        journalctl -u $SERVICE -f   ·   /var/log/apache2/$SITE-error.log
    Settings    sudo nano $ENV_FILE   then   sudo systemctl restart $SERVICE
    Update      run this script again:  sudo bash $DJANGO_DIR/deploy/deploy_apache.sh
DONE
