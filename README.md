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

On first startup, AutoWebsite copies the bundled starter site into an empty active-site
source directory and publishes an initial immutable release. It serves that release at
`/`; the mutable source checkout and agent workspaces are never publicly served.

## Uploads

Uploads are stored outside the site repository under a generated ID, never under a
browser-provided filename or path. AutoWebsite streams each file into quarantine,
enforces the configured size/count/type limits, sniffs the content type, inspects ZIP
archives, and requires a passing malware scan before marking it approved. Configure a
scanner available on the server; the default command is `clamscan` and uploads fail
closed if it is unavailable:

```bash
export AUTOWEBSITE_UPLOADS_ROOT="/srv/autowebsites-uploads"
export AUTOWEBSITE_UPLOAD_MALWARE_SCAN_COMMAND="clamscan"
export AUTOWEBSITE_MAX_UPLOAD_BYTES="10485760"
```

Approved uploads receive a SHA-256 checksum, a versioned `manifest.json`, and, for
images, dimensions plus the site-level `gallery.json` manifest. The agent must receive
only approved job-specific copies and metadata, not this shared upload store.
The dashboard also accepts an optional attachment with a prompt; after it passes the
same checks, AutoWebsite automatically associates it with that new job.

`AUTOWEBSITE_DEFAULT_GITHUB_TOKEN_REF` must be a reference resolved by the deployment's
secret manager, not a raw GitHub token. The initial settings are used only if no admin
record exists; create additional website/admin records through an operational migration
or administration workflow once that is added.

## Agent jobs

The dashboard persists one agent job at a time. Jobs use Codex CLI by default and run
in a copied workspace under `workspaces/`, so an agent cannot modify the source checkout
or public release directly. Approval copies a reviewed workspace into the private,
cumulative `staging/` revision. New jobs start from that staging revision; production
is still unchanged until the later validation/publishing phases.

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
