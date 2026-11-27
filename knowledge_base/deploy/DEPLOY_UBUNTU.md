# Deploying the Nazria API on Ubuntu (no Docker)

The setup is **nginx** (port 80, public IP) → **gunicorn** (Unix socket) → **Django**, with **PostgreSQL** (the
existing database: knowledge base in schema `nazria`, the API's own tables in `nazria_api`).

It was tested on Ubuntu 24.04 LTS with Python 3.12. Run every command as a user with `sudo`.

> **Plain HTTP, for now:** phone numbers, passwords and symptoms cross the network unencrypted. Use it for testing
> and a closed pilot, and move to HTTPS ([section 9](#9-later-https)) before real patients use the app.

## 1. Packages and a service user

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev git nginx
sudo adduser --system --group --home /opt/nazria nazria
sudo install -d -o nazria -g nazria -m 750 /var/lib/nazria /var/lib/nazria/media
sudo install -d -o nazria -g www-data -m 750 /var/lib/nazria/static
sudo usermod -aG nazria www-data          # nginx may use gunicorn's socket
```

## 2. Code and Python environment

```bash
sudo -u nazria git clone https://github.com/idreesgis/nazria_mufrad_aza.git /opt/nazria/app
sudo -u nazria python3 -m venv /opt/nazria/venv
sudo -u nazria /opt/nazria/venv/bin/pip install --upgrade pip
sudo -u nazria /opt/nazria/venv/bin/pip install -r /opt/nazria/app/knowledge_base/requirements.txt
```

The repository is private, so the clone needs a GitHub deploy key or a token for the `nazria` user.

## 3. Configuration (secrets stay on the server)

```bash
sudo install -d -m 750 -o root -g nazria /etc/nazria
sudo install -m 640 -o root -g nazria /opt/nazria/app/knowledge_base/deploy/nazria.env.example /etc/nazria/nazria.env
sudo nano /etc/nazria/nazria.env
```

Set at least these values:

| Variable | What to put |
|---|---|
| `DJANGO_SECRET_KEY` | Output of `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_ALLOWED_HOSTS` | Your public IP, then `,localhost,127.0.0.1` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `http://<your public IP>` |
| `NAZRIA_DATABASE_URL` | The same database as the knowledge base |
| `NAZRIA_GOOGLE_CLIENT_IDS` | Optional: the Google "Web application" OAuth client ID, for Sign in with Google (see `docs/API.md`). The server must reach `www.googleapis.com` over HTTPS to fetch Google's public keys. |

The database must accept connections from this server, so add the server's IP to the database firewall or
allowlist.

## 4. Database tables, static files, keys, staff

A helper that runs `manage.py` as the `nazria` user. Django reads `/etc/nazria/nazria.env` itself, so no shell
interprets the values and characters such as `&`, `$` or `;` in the database URL or password are safe:

```bash
nz() { (cd /opt/nazria/app/knowledge_base && sudo -u nazria NAZRIA_ENV_FILE=/etc/nazria/nazria.env /opt/nazria/venv/bin/python manage.py "$@"); }
```

Then run:

```bash
nz create_api_schema                 # schema nazria_api (nothing is created in public)
nz migrate
nz createcachetable                  # shared rate-limit counters (NAZRIA_API_CACHE=db)
nz collectstatic --noinput
nz check --deploy
nz create_api_client android-app     # prints the app key ONCE: give it to the Android build
nz create_staff --phone 03XXXXXXXXX --name "Admin" --admin           # asks for a password
nz create_staff --phone 03YYYYYYYYY --name "Hakeem Sahib"            # a Hakeem
```

## 5. gunicorn as a service

```bash
sudo cp /opt/nazria/app/knowledge_base/deploy/nazria-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nazria-api
sudo systemctl status nazria-api          # "active (running)"
journalctl -u nazria-api -f               # logs
```

## 6. nginx

```bash
sudo cp /opt/nazria/app/knowledge_base/deploy/nginx-nazria.conf /etc/nginx/sites-available/nazria
sudo ln -sf /etc/nginx/sites-available/nazria /etc/nginx/sites-enabled/nazria
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
curl http://localhost/api/v1/health/      # {"status":"ok","database":"ok",...}
```

## 7. Firewall

Allow only SSH and HTTP from outside; gunicorn is reachable only through nginx's socket.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw enable
```

**From the Android app:** the base URL is `http://<public IP>/api/v1/`. Android 9 and newer blocks plain HTTP unless
the app allows that address in its `network_security_config.xml`. That is a change for the Android build, not the
server.

**Admin:** `http://<public IP>/admin/`. Log in with the phone number you gave `create_staff` (as `+92…`).

## 8. Updates, logs and backups

| Task | How |
|---|---|
| Update the code | `sudo /opt/nazria/app/knowledge_base/deploy/update.sh` (pull, install, migrate, collectstatic, restart, health check) |
| API logs | `journalctl -u nazria-api` |
| nginx logs | `/var/log/nginx/` |
| Audit log | `/admin/audit/auditevent/` or `GET /api/v1/staff/audit/`. It is append-only: the database refuses UPDATE, DELETE and TRUNCATE on it. |
| Backups | Everything is kept permanently, so back up both the database and the videos. |

For backups:
- **Database:** `pg_dump --schema=nazria --schema=nazria_api …`, daily.
- **Pulse videos:** copy `/var/lib/nazria/media` with them (for example with `rsync` to another machine).

## 9. Later: HTTPS

A browser-trusted certificate needs a domain name pointing to the server. A free subdomain works, for example from
DuckDNS. Then:

1. Point the domain to your public IP. Add it to `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`
   (`https://…`).
2. Get the certificate: `sudo apt install certbot python3-certbot-nginx`, then
   `sudo certbot --nginx -d your.domain`. certbot adds the TLS settings to the nginx site and renews automatically.
3. In `/etc/nazria/nazria.env`, set `NAZRIA_HTTPS=true` and `DJANGO_BEHIND_HTTPS_PROXY=true`. Then run
   `sudo systemctl restart nazria-api`.
4. Change the Android app's base URL to `https://your.domain/api/v1/` and remove the cleartext exception.
