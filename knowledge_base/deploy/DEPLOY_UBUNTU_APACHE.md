# Deploying the Nazria API on Ubuntu (20.04, 22.04, 24.04) with Apache on port 95

```
Android app ──HTTP──▶ Apache :95 ──Unix socket──▶ gunicorn (systemd: nazria-api) ──▶ Django ──▶ PostgreSQL
                     (static files,                  /run/nazria/gunicorn.sock                schemas nazria
                      upload limit, headers)                                                   and nazria_api
```

- **Apache** listens on **port 95** of the server's public IP. Other Apache sites (port 80, 443…) keep working
  unchanged.
- **gunicorn** runs the Django API as the system user `nazria`, reachable only through a Unix socket.
- **PostgreSQL** is the existing database: the knowledge base is in schema `nazria`, and the API's own tables go
  into schema `nazria_api`. Nothing is created in `public`.

This setup was tested end to end with Apache 2.4 and Python 3.12. The tested requests:
- the health check, register and login, and the admin pages with their CSS;
- `/media/` being blocked;
- a 120 MB upload refused with `413`;
- an upload with an expired login getting the API's `401`;
- a forged `X-Forwarded-For` being ignored by the audit log.

> **Plain HTTP:** phone numbers, passwords and symptoms cross the network unencrypted. Use it for testing and a
> closed pilot, and move to HTTPS ([section 13](#13-later-https)) before real patients use the app.

Replace `203.0.113.10` everywhere below with **your server's public IP**.

## The quick way: one script

[`deploy_apache.sh`](deploy_apache.sh) does every step of this guide by itself, sections 1 to 10:
- packages and Python 3.12, the service user and folders;
- git, the venv, `requirements.txt` and the configuration file;
- the database, the app key and the first administrator;
- gunicorn, Apache on port 95, the firewall and the checks.

Its paths are set at the top: the project in `/home/python-www/nazria_mufrad_aza`, the venv in
`/home/python-www/nazria_mufrad_aza/venv`, and the site in `/etc/apache2/sites-available/nazria.conf`.

```bash
# the repository is private: copy the script to the server first (scp, or paste it into nano), then:
sudo bash deploy_apache.sh
```

**Software already on the server:**
- git, Apache and Python are used as they are: the script installs only what is missing, and upgrades nothing.
- **Python:** the project needs 3.11 or newer, and the newest installed version is used. When there is none (Ubuntu
  20.04's Python is 3.8, 22.04's is 3.10), the script gives the project its own **private Python 3.12** in
  `/opt/nazria-python`. It installs it with `uv`, at a pinned version whose download is checked against its published
  SHA-256 checksum. The system Python is not changed, so other programs that use it keep working.
- PostgreSQL is not installed or changed by the script. It only connects with the URL you give. If the database
  runs on this same server, the URL's host is `127.0.0.1` or `localhost`. The user in the URL must be allowed to
  connect in PostgreSQL's own settings (`pg_hba.conf`); the script never edits them.

**First run:**
- It asks for the server's public IP and the database URL (the URL is typed hidden, and never printed or logged).
- It generates `DJANGO_SECRET_KEY` and writes `/etc/nazria/nazria.env` (mode 640).
- It prints the Android **app key once**, and offers to create the first administrator.
- If the server cannot read the GitHub repository yet, it prints a **deploy key** to add on GitHub
  (Settings → Deploy keys) and stops. Run it again after adding the key.

**Every later run is an update:** pull, requirements, migrations, restart, checks. It asks nothing.

**It never:**
- deletes data or changes database settings;
- overwrites `/etc/nazria/nazria.env` once it exists;
- touches Apache's other sites.

If the database cannot be reached, it stops and says so. Add the server's IP to the database allowlist and run it
again.

Settings can be changed when running it, for example: `sudo PORT=8095 APP_DIR=/srv/nazria bash deploy_apache.sh`.

The sections below are the same steps by hand, with the reasons for each.

---

## 0. Before you start

| You need | Why |
|---|---|
| Ubuntu server (20.04, 22.04 or 24.04), a user with `sudo`, SSH access | Python 3.11+ is added for the project if missing (section 1) |
| Port **95/TCP** open at your hosting provider (security group or cloud firewall) and on the server (section 9) | The app connects to it |
| The PostgreSQL connection URL of the existing database | The API uses the same database as the knowledge base |
| The server's IP on the database's allowlist or firewall | Otherwise the connection times out |
| Read access to the private GitHub repository `idreesgis/nazria_mufrad_aza` | To clone the code (section 3) |

Check whether something already uses port 95:

```bash
sudo ss -ltnp | grep ':95 ' || echo "port 95 is free"
```

## 1. Packages, including Python 3.11 or newer

The project needs **Python 3.11 or newer**: Django 5.2 needs 3.10, and the Gemini library (`google-genai`) needs 3.11.
Ubuntu 20.04 comes with Python 3.8 and 22.04 with 3.10, so add Python 3.12 **next to** the system Python. Never
replace the system Python: Ubuntu's own tools depend on it.

```bash
sudo apt install -y git curl apache2          # skip what is already installed
python3 --version                             # 3.11 or newer? then use it and skip the rest of this section
```

**A private Python 3.12 for the project (any Ubuntu version).** This is what `deploy_apache.sh` does:

```bash
sudo install -d /opt/nazria-python/bin
curl -fsSL -o /tmp/uv.tar.gz https://github.com/astral-sh/uv/releases/download/0.11.32/uv-x86_64-unknown-linux-gnu.tar.gz
echo "aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967  /tmp/uv.tar.gz" | sha256sum -c -
tar -xzf /tmp/uv.tar.gz -C /tmp && sudo install -m 755 /tmp/uv-x86_64-unknown-linux-gnu/uv /opt/nazria-python/bin/uv
sudo UV_PYTHON_INSTALL_DIR=/opt/nazria-python/python /opt/nazria-python/bin/uv python install 3.12
sudo chmod -R a+rX /opt/nazria-python/python
sudo UV_PYTHON_INSTALL_DIR=/opt/nazria-python/python /opt/nazria-python/bin/uv python find --managed-python 3.12
# -> /opt/nazria-python/python/cpython-3.12-…/bin/python3.12 : use this path where the steps below say python3.12
```

On an ARM server, replace `x86_64` with `aarch64` and use the checksum
`4d4fa08d95b06642e5800df6a22bd71455f23f988269e18da2847971d8c0bf31`.

**Or, on Ubuntu 22.04 only,** use the deadsnakes PPA instead:
`sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt install -y python3.12 python3.12-venv`.

## 2. Service user and folders

```bash
sudo adduser --system --group --home /opt/nazria nazria
sudo install -d -o nazria -g nazria   -m 750 /var/lib/nazria /var/lib/nazria/media    # pulse videos (private)
sudo install -d -o nazria -g www-data -m 750 /var/lib/nazria/static                   # admin CSS/JS for Apache
sudo usermod -aG nazria www-data     # Apache (www-data) may open gunicorn's socket
```

## 3. The code

The repository is private. Give the server read-only access with a **deploy key**:

```bash
sudo -u nazria install -d -m 700 /opt/nazria/.ssh
sudo -u nazria ssh-keygen -t ed25519 -N "" -f /opt/nazria/.ssh/id_ed25519 -C "nazria-server"
sudo cat /opt/nazria/.ssh/id_ed25519.pub
```

On GitHub, open the repository → **Settings → Deploy keys → Add deploy key**. Paste the key and leave
"Allow write access" **off**. Then:

```bash
sudo -u nazria ssh -o StrictHostKeyChecking=accept-new -T git@github.com    # "successfully authenticated"
sudo -u nazria git clone git@github.com:idreesgis/nazria_mufrad_aza.git /opt/nazria/app
```

## 4. Python environment

```bash
sudo -u nazria python3.12 -m venv /opt/nazria/venv
sudo -u nazria /opt/nazria/venv/bin/pip install --upgrade pip
sudo -u nazria /opt/nazria/venv/bin/pip install -r /opt/nazria/app/knowledge_base/requirements.txt
```

This takes a few minutes; OpenCV, NumPy and SciPy are large.

## 5. Configuration (secrets stay on the server)

```bash
sudo install -d -m 750 -o root -g nazria /etc/nazria
sudo install -m 640 -o root -g nazria /opt/nazria/app/knowledge_base/deploy/nazria.env.example /etc/nazria/nazria.env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"      # copy this for DJANGO_SECRET_KEY
sudo nano /etc/nazria/nazria.env
```

Set these values. The rest of the file can stay as it is.

| Variable | Value for Apache on port 95 |
|---|---|
| `DJANGO_SECRET_KEY` | The random value printed above |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_ALLOWED_HOSTS` | `203.0.113.10,localhost,127.0.0.1` (your IP, **without** the port) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `http://203.0.113.10:95` (**with** the port: the admin login form needs it) |
| `NAZRIA_DATABASE_URL` | `postgresql://USER:PASSWORD@DB_HOST:5432/DBNAME?sslmode=require`. Special characters in the password must be URL-encoded (`@` → `%40`, `%` → `%25`, `#` → `%23`). |
| `NAZRIA_HTTPS` | `false` (until section 13) |
| `NAZRIA_TRUST_PROXY` | `true` (Apache passes the client IP for the audit log) |
| `NAZRIA_API_CACHE` | `db` (rate limits shared by all gunicorn workers) |
| `NAZRIA_ENGINE` | `questionnaire` (the AI explanation stays off until you switch it) |
| Social sign-in | Optional. See `docs/API.md`, "Provider setup". `NAZRIA_FACEBOOK_APP_SECRET` is a secret: only in this file. Sign in with Apple needs HTTPS (section 13). |

The file is read by systemd and by Django itself, never by a shell, so `&`, `$` or `;` in the password are safe.
Never commit this file or paste its values anywhere.

## 6. Database: schema, tables, keys and staff

A helper that runs `manage.py` as the `nazria` user with the configuration file (add it to your `~/.bashrc` to keep
it):

```bash
nz() { (cd /opt/nazria/app/knowledge_base && sudo -u nazria NAZRIA_ENV_FILE=/etc/nazria/nazria.env /opt/nazria/venv/bin/python manage.py "$@"); }
```

**First, check the database connection:**

```bash
nz shell --no-imports -c "from django.db import connection; connection.ensure_connection(); print('database ok')"
```

If this hangs and then fails with a timeout or "connection refused", the database does not accept this server yet.
Add the server's public IP to the database's allowlist or firewall and try again. Nothing else needs changing.

**The knowledge base (schema `nazria`)** is normally loaded already. Check it:

```bash
sudo systemd-run --quiet --pipe --wait -p User=nazria -p EnvironmentFile=/etc/nazria/nazria.env \
     -p WorkingDirectory=/opt/nazria/app/knowledge_base /opt/nazria/venv/bin/python -m nazria_kb verify
```

Only if it is empty, load it from the Urdu book CSV:
`… /opt/nazria/venv/bin/python -m nazria_kb load --csv /path/to/urdu_book.csv`. This is the same command as above,
with `load --csv …` instead of `verify`.

**The API's tables (schema `nazria_api`):**

```bash
nz create_api_schema                 # creates schema nazria_api (nothing in public)
nz migrate                           # Django, accounts, patients, allauth, audit…
nz seed_questionnaire                # adds missing questions/options; never overwrites a Hakeem's edits
nz createcachetable                  # rate-limit counters (NAZRIA_API_CACHE=db)
nz collectstatic --noinput           # admin CSS/JS into /var/lib/nazria/static
nz check --deploy                    # warnings about HTTPS are expected while on plain HTTP
```

**The app key and staff accounts:**

```bash
nz create_api_client android-app    # prints the app key ONCE: keep it for the Android build (section 11)
nz create_staff --phone 03XXXXXXXXX --name "Admin" --admin      # asks for a password
nz create_staff --phone 03YYYYYYYYY --name "Hakeem Sahib"       # a Hakeem
```

## 7. gunicorn as a service

The service file is the same one the nginx guide uses. gunicorn listens on `/run/nazria/gunicorn.sock`, and only the
`nazria` group (which `www-data`, Apache's user, now belongs to) can open it.

```bash
sudo cp /opt/nazria/app/knowledge_base/deploy/nazria-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nazria-api
sudo systemctl status nazria-api --no-pager                     # "active (running)"
sudo curl -s --unix-socket /run/nazria/gunicorn.sock http://localhost/api/v1/health/; echo
# {"status":"ok","database":"ok",...}
```

## 8. Apache on port 95

Two files from `deploy/`:
- `apache-ports-95.conf` adds `Listen 95`. Apache keeps its other ports.
- `apache-nazria.conf` is the site: a `<VirtualHost *:95>` that proxies to gunicorn's socket, serves the admin's
  static files, blocks `/media/`, limits uploads to 110 MB, sets security headers and makes sure the audit log
  records the real client IP.

```bash
sudo a2enmod proxy proxy_http headers expires rewrite
sudo cp /opt/nazria/app/knowledge_base/deploy/apache-ports-95.conf /etc/apache2/conf-available/nazria-port-95.conf
sudo cp /opt/nazria/app/knowledge_base/deploy/apache-nazria.conf   /etc/apache2/sites-available/nazria.conf
sudo a2enconf nazria-port-95
sudo a2ensite nazria
```

Show less about the server in headers and error pages. This changes Apache's global security settings, so it
affects all sites; skip it if you prefer:

```bash
sudo sed -i 's/^ServerTokens .*/ServerTokens Prod/; s/^ServerSignature .*/ServerSignature Off/' /etc/apache2/conf-available/security.conf
```

Check and apply. A restart, not a reload, is needed: Apache opens the new port, and `www-data` picks up its new
group from section 2.

```bash
sudo apache2ctl configtest              # "Syntax OK" (an AH00558 ServerName notice is harmless)
sudo systemctl restart apache2
sudo ss -ltnp | grep ':95 '              # apache2 listening on 0.0.0.0:95
curl -s http://localhost:95/api/v1/health/; echo
```

What the site does:

| Path | Handled by |
|---|---|
| `/api/v1/…` | gunicorn → Django (the app's API) |
| `/admin/` | gunicorn → Django (staff administration) |
| `/static/…` | Apache, from `/var/lib/nazria/static` (cached 7 days) |
| `/media/…` | **refused** (`403`): pulse videos are health data and are never served |
| Uploads over 110 MB | **refused** by Apache (`413`) before they are received |

## 9. Firewall

Allow SSH first, so you do not lock yourself out. Then allow port 95.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 95/tcp
sudo ufw status | grep -q "Status: active" || sudo ufw enable
sudo ufw status
```

If Apache also serves other sites, keep their ports open as well (for example `sudo ufw allow 80/tcp`). **Also open
port 95 in your hosting provider's firewall** or security group. Many providers block it by default, and the
server's own `ufw` cannot change that.

gunicorn and PostgreSQL need no open ports: gunicorn uses the Unix socket, and the database is reached outbound.

## 10. Check from outside

From your own computer (not the server):

```bash
curl http://203.0.113.10:95/api/v1/health/
# {"status":"ok","database":"ok","explanation_enabled":false,...,"api_version":1}
curl -I http://203.0.113.10:95/admin/login/        # 200, with X-Frame-Options: DENY
curl -I http://203.0.113.10:95/media/x             # 403
```

**Admin:** open `http://203.0.113.10:95/admin/` and log in with the phone number given to `create_staff`, written as
`+92…`.

## 11. The Android app

In the app's `local.properties` (or later in the app: Settings → Server):

```properties
nazria.serverUrl=http://203.0.113.10:95/
nazria.appKey=nzr_…            # from "create_api_client android-app"
nazria.allowHttp=true          # until the server has HTTPS
```

The app already allows plain HTTP on any port while `allowHttp=true`, so port 95 needs no other change. Build with
`./gradlew assembleRelease`, or `assembleDebug` for testing.

## 12. Updates, logs, backups, troubleshooting

| Task | How |
|---|---|
| Update to the latest code | `sudo /opt/nazria/app/knowledge_base/deploy/update.sh`. It pulls the code, installs requirements, runs migrations, seeds the questionnaire, collects static files, runs the deploy check, restarts and runs the health check. |
| API logs | `journalctl -u nazria-api -f` |
| Apache logs | `/var/log/apache2/nazria-access.log`, `/var/log/apache2/nazria-error.log` |
| Restart | `sudo systemctl restart nazria-api` (the API) · `sudo systemctl reload apache2` (after editing the site) |
| Audit log | `http://203.0.113.10:95/admin/audit/auditevent/`. It is append-only: the database refuses changes to it. |
| Backups | Back up the database daily: `pg_dump --schema=nazria --schema=nazria_api …`. Copy `/var/lib/nazria/media` (the pulse videos) with it, for example with `rsync`. Everything is kept permanently. |

Take a database backup before every update that changes the database.

| Symptom | Cause and fix |
|---|---|
| `503 Service Unavailable` from Apache | gunicorn is not running: `sudo systemctl status nazria-api`, `journalctl -u nazria-api -n 50`. |
| `503`, and the Apache error log says `Permission denied` on `gunicorn.sock` | `www-data` is not in group `nazria`, or Apache was not restarted afterwards: `sudo usermod -aG nazria www-data && sudo systemctl restart apache2`. |
| `400 Bad Request` for every request | The address you use is missing from `DJANGO_ALLOWED_HOSTS`. Add it without the port, then `sudo systemctl restart nazria-api`. |
| Admin login says "CSRF verification failed" | `DJANGO_CSRF_TRUSTED_ORIGINS` must be exactly `http://203.0.113.10:95`, with the port. |
| No answer at all from outside | Port 95 is closed in the hosting provider's firewall, or in `ufw`. |
| `database":"unavailable"` in the health check, or a timeout | The database does not accept this server's IP: add it to the database allowlist. |
| `413` when uploading a pulse video | The video is over 110 MB. The limit is in `apache-nazria.conf` and `NAZRIA_PULSE_MAX_MB`. |
| Admin pages without styling | Run `nz collectstatic --noinput`, and check `/var/lib/nazria/static` is group `www-data`. |

## 13. Later: HTTPS

HTTPS needs a **domain name** that points to the server's IP. A free subdomain works, for example from DuckDNS.
Certificates from Let's Encrypt are checked over port 80, so Apache must answer on port 80 for that domain.

1. Get the certificate: `sudo apt install -y certbot python3-certbot-apache`, then
   `sudo certbot certonly --apache -d api.your-domain.com`. It renews automatically.
2. Serve HTTPS on port 443 (the usual choice) or on port 95. To use port 95, change `apache-nazria.conf` to:
   ```apache
   <VirtualHost *:95>
       ServerName api.your-domain.com
       SSLEngine on
       SSLCertificateFile    /etc/letsencrypt/live/api.your-domain.com/fullchain.pem
       SSLCertificateKeyFile /etc/letsencrypt/live/api.your-domain.com/privkey.pem
       RequestHeader set X-Forwarded-Proto "https"
       # … the rest of the site unchanged …
   </VirtualHost>
   ```
   Then run `sudo a2enmod ssl && sudo systemctl restart apache2`. A port serves either HTTP or HTTPS, not both.
3. In `/etc/nazria/nazria.env`, set:
   - `NAZRIA_HTTPS=true` and `DJANGO_BEHIND_HTTPS_PROXY=true`;
   - the domain in `DJANGO_ALLOWED_HOSTS`;
   - `https://api.your-domain.com[:95]` in `DJANGO_CSRF_TRUSTED_ORIGINS`;
   - for Sign in with Apple, `NAZRIA_PUBLIC_URL=https://api.your-domain.com[:95]`.

   Then run `sudo systemctl restart nazria-api`.
4. Build the app with `nazria.serverUrl=https://api.your-domain.com[:95]/` and `nazria.allowHttp=false`.
