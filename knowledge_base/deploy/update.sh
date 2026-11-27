#!/usr/bin/env bash
# Update the API to the latest code on the server:  sudo /opt/nazria/app/knowledge_base/deploy/update.sh
set -euo pipefail
APP=/opt/nazria/app
VENV=/opt/nazria/venv
# the env file is read by Django itself (NAZRIA_ENV_FILE), never sourced by a shell
run() { sudo -u nazria env NAZRIA_ENV_FILE=/etc/nazria/nazria.env bash -c "cd $APP/knowledge_base && $*"; }

sudo -u nazria git -C "$APP" pull --ff-only
sudo -u nazria "$VENV/bin/pip" install --quiet -r "$APP/knowledge_base/requirements.txt"
run "$VENV/bin/python manage.py migrate --noinput"
run "$VENV/bin/python manage.py collectstatic --noinput --verbosity 0"
run "$VENV/bin/python manage.py check --deploy --fail-level ERROR"
systemctl restart nazria-api
sleep 2
curl -fsS http://localhost/api/v1/health/ && echo
