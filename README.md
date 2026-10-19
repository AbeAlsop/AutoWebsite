# AutoWebsite
AI-powered self-editing website platform.

## Admin server

Run the FastAPI admin server from the repository root:

```bash
cd /Users/abe/Code/AutoWebsite
.venv/bin/uvicorn admin.app:app --reload
```

Phase 3 authentication expects credentials from environment variables:

```bash
export AUTOWEBSITE_ADMIN_USERNAME="admin"
export AUTOWEBSITE_ADMIN_PASSWORD_HASH="<bcrypt hash>"
export AUTOWEBSITE_SESSION_SECRET="<long random secret>"
export AUTOWEBSITE_SECURE_COOKIES="true"
```

On its first startup, the server creates a local SQLite mapping in `data/autowebsite.db`
and assigns this administrator to the default website. The database contains only
server-side website metadata; the browser submits a website ID, never a filesystem
path. Configure the initial website if the defaults are not suitable:

```bash
export AUTOWEBSITE_DEFAULT_WEBSITE_NAME="Example site"
export AUTOWEBSITE_DEFAULT_GITHUB_REPO="acme/example-site"
export AUTOWEBSITE_REPOSITORIES_ROOT="/srv/autowebsites"
export AUTOWEBSITE_DEFAULT_WEBSITE_DIRECTORY="/srv/autowebsites/example-site"
export AUTOWEBSITE_PUBLISHED_ROOT="/srv/autowebsites-published"
export AUTOWEBSITE_DEFAULT_GITHUB_TOKEN_REF="secret://github/acme-example-site"
```

Paths are configured rather than hard-coded, so the same application runs on macOS
and Linux. The default repository root is `repos/` within the project; set
`AUTOWEBSITE_REPOSITORIES_ROOT` and `AUTOWEBSITE_DEFAULT_WEBSITE_DIRECTORY` to
server-local absolute paths in deployment. Set `AUTOWEBSITE_PUBLISHED_ROOT` to a
separate location for immutable public releases. For example, a Linux host might use
`/srv/autowebsites/active-site` and `/srv/autowebsites-published`, while a macOS
development machine might use `/Users/you/Sites/active-site` and
`/Users/you/Sites/published`. Python's `pathlib` handles the host path format; the
browser never receives or submits either path.

When a Git location is configured, first startup clones that trusted server-side remote
into the active-site directory and publishes it. Approval copies a reviewed workspace
into this private Git staging checkout, commits it, and pushes it. Publish then replaces
the single public `published/current` directory. Git is the version archive; old local
releases are not retained.

## Uploads

Uploads are stored outside the site repository under a generated ID, never under a
browser-provided filename or path. AutoWebsite streams each file into quarantine,
enforces the configured size/count/type limits, accepts only JPEG, PNG, WebP, and GIF
content signatures, and requires a passing malware scan before marking it approved.
Configure a scanner available on the server; scanning is enabled by default and uploads
fail closed if it is unavailable:

```bash
export AUTOWEBSITE_UPLOADS_ROOT="/srv/autowebsites-uploads"
export AUTOWEBSITE_UPLOAD_MALWARE_SCAN_COMMAND="clamscan"
export AUTOWEBSITE_UPLOAD_MALWARE_SCAN_ENABLED="true"
export AUTOWEBSITE_MAX_UPLOAD_BYTES="10485760"
```

Approved uploads receive a SHA-256 checksum, a versioned `manifest.json`, and, for
images, dimensions plus the site-level `gallery.json` manifest. The agent must receive
only approved job-specific copies and metadata, not this shared upload store.
The dashboard also accepts an optional attachment with a prompt; after it passes the
same checks, AutoWebsite automatically associates it with that new job.

For a trusted local proof of concept only, set
`AUTOWEBSITE_UPLOAD_MALWARE_SCAN_ENABLED=false` to accept allowed image uploads without
a malware scan. Do not use that setting on an Internet-facing deployment.

`AUTOWEBSITE_DEFAULT_GITHUB_TOKEN_REF` must be a reference resolved by the deployment's
secret manager, not a raw GitHub token. The initial settings are used only if no admin
record exists; create additional website/admin records through an operational migration
or administration workflow once that is added.

## Agent jobs

The dashboard persists one agent job at a time. Jobs use Codex CLI by default and run
in a copied workspace under `workspaces/`, so an agent cannot modify the Git staging
checkout or public release directly. Approval commits and pushes the reviewed workspace;
production is still unchanged until the explicit Publish action.

Agent execution is disabled by default. Enable it only after configuring Codex CLI
authentication and a pinned model (use a deployment-approved model snapshot when one
is available):

```bash
export AUTOWEBSITE_AGENT_ENABLED="true"
export AUTOWEBSITE_AGENT_MODEL="gpt-5.6-terra"
export AUTOWEBSITE_AGENT_TIMEOUT_SECONDS="900"
```

The integration runs `codex exec` with the `workspace-write` sandbox and never passes
administrator prompts through a shell. Phase 10 adds the required OS/container isolation
and resource controls for production deployment.

Generate a bcrypt hash without storing the plaintext password:

```bash
.venv/bin/python -c "from admin.auth import hash_password; print(hash_password('your password'))"
```

For local HTTP-only testing, set `AUTOWEBSITE_SECURE_COOKIES=false`. Keep secure cookies enabled in production.

## Production deployment: one Linux VM and one domain

AutoWebsite runs privately; Nginx is the only Internet-facing service. Nginx serves the
immutable `published/current` release at the domain and proxies `/admin`, `/static`,
and `/health` to AutoWebsite on `127.0.0.1:8000`. It never serves the mutable
checkout, staging tree, uploads, or agent workspaces.

These instructions target a supported Debian or Ubuntu LTS VM. To support malware scans
on uploaded images, the VM should have at least 2 vCPU, 4 GB RAM, and 25 GB SSD storage.
1 vCPU and 1-2 GB RAM supports Uvicorn and Nginx for a small single-site installation.
The other vCPU and 2GB RAM is for ClamAV malware scans The model inference itself runs
on OpenAI infrastructure, not on the VM.

Before starting, create DNS `A`/`AAAA` records for the intended domain and allow TCP
ports 80 and 443 through the VM/provider firewall. Keep SSH access restricted to the
administrator's network.

1. **Clone the GitHub repository.** Do this first, with a deploy key or other
   read-only GitHub credential if the repository is private.

   ```bash
   sudo adduser --system --group --home /srv/autowebsite autowebsite
   sudo install -d -o autowebsite -g autowebsite -m 0750 /srv/autowebsite
   sudo -u autowebsite git clone https://github.com/AbeAlsop/AutoWebsite.git /srv/autowebsite/app
   ```

2. **Install external dependencies.**

   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv python3-pip git nginx certbot clamav-daemon curl
   curl -fsSLo /tmp/codex-install.sh https://chatgpt.com/codex/install.sh
   less /tmp/codex-install.sh
   sudo -u autowebsite -H sh /tmp/codex-install.sh
   rm /tmp/codex-install.sh
   sudo -u autowebsite -H env PATH=/srv/autowebsite/.local/bin:$PATH codex --version
   ```

   `clamscan` may be used instead of `clamdscan`, but `clamdscan` avoids loading the
   malware database for every upload. If you use `clamdscan`, ensure its daemon is
   enabled and set the scan command below accordingly. Codex CLI is a separate local
   executable: it edits the job workspace and requests inference from OpenAI; it is
   not a local model server. Follow the current [Codex CLI setup
   documentation](https://developers.openai.com/codex/) if its installation method or
   authentication flow has changed.

3. **Create the Python environment and protected state directories.**

   ```bash
   sudo -u autowebsite python3 -m venv /srv/autowebsite/app/.venv
   sudo -u autowebsite /srv/autowebsite/app/.venv/bin/pip install -r /srv/autowebsite/app/admin/requirements.txt
   sudo install -d -o autowebsite -g autowebsite -m 0750 \
     /srv/autowebsite/state/{data,repos,workspaces,published,uploads}
   ```

4. **Configure the service.** Copy the supplied example outside the repository, then
   edit it. Generate the password hash and session secret on the VM; do not put either
   value in Git or the shell history.

   ```bash
   sudo install -d -m 0700 /etc/autowebsite
   sudo cp /srv/autowebsite/app/deploy/autowebsite.env.example /etc/autowebsite/autowebsite.env
   sudo chmod 600 /etc/autowebsite/autowebsite.env
   sudo -u autowebsite /srv/autowebsite/app/.venv/bin/python -c "from admin.auth import hash_password; print(hash_password('choose a strong password'))"
   openssl rand -hex 32
   sudoedit /etc/autowebsite/autowebsite.env
   ```

   Put the generated bcrypt hash and random value in the matching environment entries.
   Before starting the service, configure Git identity and a least-privilege read/write
   deploy key (or equivalent credential) for the `autowebsite` account:

   ```bash
   sudo -u autowebsite -H git config --global user.name "AutoWebsite"
   sudo -u autowebsite -H git config --global user.email "autowebsite@your-domain.example"
   ```
   Leave `AUTOWEBSITE_AGENT_ENABLED=false` until the app itself has started cleanly,
   then authenticate Codex **as the `autowebsite` account** (for example, `sudo -u
   autowebsite -H codex login`) using the production account/API credential you intend
   to use. Do not store an OpenAI key in the repository or in a public systemd unit.
   Set `AUTOWEBSITE_AGENT_ENABLED=true` only after a controlled test. Set
   `AUTOWEBSITE_UPLOAD_MALWARE_SCAN_COMMAND=clamdscan` when using the ClamAV daemon.

5. **Install and start the private application service.**

   ```bash
   sudo cp /srv/autowebsite/app/deploy/autowebsite.service /etc/systemd/system/autowebsite.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now autowebsite
   curl --fail http://127.0.0.1:8000/health
   ```

   The service deliberately binds to localhost. Check failures with `sudo journalctl
   -u autowebsite -e` and do not expose port 8000 through the firewall. Now that the
   service has created `published/current`, grant Nginx traversal to the release path
   without making the rest of the state tree listable:

   ```bash
   sudo chmod 0711 /srv/autowebsite /srv/autowebsite/state
   sudo chmod 0755 /srv/autowebsite/state/published /srv/autowebsite/state/published/current
   ```

6. **Configure Nginx and TLS.** Replace `example.com` in the supplied configuration
   with the real domain (and remove `www` if it is not used). Obtain the certificate
   before enabling the TLS configuration:

   ```bash
   sudo systemctl stop nginx
   sudo certbot certonly --standalone -d example.com -d www.example.com
   sudo cp /srv/autowebsite/app/deploy/nginx-autowebsite.conf /etc/nginx/sites-available/autowebsite
   sudoedit /etc/nginx/sites-available/autowebsite
   sudo ln -s /etc/nginx/sites-available/autowebsite /etc/nginx/sites-enabled/autowebsite
   sudo rm -f /etc/nginx/sites-enabled/default
   sudo nginx -t
   sudo systemctl enable --now nginx
   ```

   Confirm `https://example.com/` displays the initial release and
   `https://example.com/admin` displays the login page. Certbot's systemd timer renews
   certificates on supported distributions; verify it with `sudo systemctl list-timers
   | grep certbot` and test with `sudo certbot renew --dry-run`.

7. **Lock down and verify the real workflow.** Restrict `/admin` to a VPN or stable
   admin IP by enabling the example allow/deny rules in the Nginx config. Confirm a
   rejected job changes neither staging nor production, approval changes only staging,
   and the explicit publish action changes the public release. Back up
   `/srv/autowebsite/state/data` and `/srv/autowebsite/state/published` before taking
   production traffic.

The included [systemd unit](deploy/autowebsite.service), [Nginx configuration](deploy/nginx-autowebsite.conf),
and [environment template](deploy/autowebsite.env.example) are deployment templates,
not secrets. Review them before each upgrade. Agent jobs currently use Codex CLI's
workspace-write sandbox and a timeout, but they run as the application service user;
for hostile/untrusted prompting, use a separate container/VM runner with an egress
allowlist before enabling agent execution on an Internet-facing installation.

## Operational log

AutoWebsite writes concise action records to Uvicorn's normal access/process log, which
systemd captures in the service journal. Use `sudo journalctl -u autowebsite` to view
login, upload, prompt/job, approval, publication, and rollback outcomes. Git is the
durable edit history; the operational log stores a bounded one-line prompt summary but
does not retain file copies, diffs, or agent output.

## Local tests

From the repository root, install the development dependencies and run pytest:

```bash
python3 -m venv .venv  # only needed if the virtual environment does not exist
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests use temporary repositories and databases; no production credentials or live
agent calls are required. Git must be installed for the Git workflow tests.

## Generated-content browser isolation

Draft previews and published pages carry a CSP `sandbox allow-scripts` policy.
Scripts may render the page, but its opaque origin cannot access admin pages,
cookies, storage, or service workers. Connections, forms, frames, and embedded
objects are disabled. This intentionally restricts generated sites that need
fetch, storage, forms, or embedded content; such features require a separately
hosted, cookie-isolated public origin before relaxing the policy. Apply the
updated Nginx configuration as well: it serves published files directly and now
forwards all administration endpoints. Purge any cached HTML during deployment.

The server refuses to start without a strong `AUTOWEBSITE_SESSION_SECRET`, even
when agent execution is disabled. Generate one before starting Uvicorn:

```bash
export AUTOWEBSITE_SESSION_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Persist that value in your protected deployment environment file rather than
generating a new value on every restart. Rotate any previously used default or
example secret; rotation invalidates existing session and CSRF tokens.
