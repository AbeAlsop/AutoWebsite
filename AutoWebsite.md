# AutoWebsite Implementation Plan

## Objective

Create a self-editing website platform where:

- The first release maintains one website end to end as a proof of concept. Multi-site hosting is a later phase.
- The AutoWebsite service hosts the generated static website as well as its administration interface.
- The public website consists entirely of static HTML/CSS/JavaScript served by AutoWebsite; the administration application is available under `/admin`.
- The website source is stored in a GitHub repository.
- A Python administration application allows authenticated administrators to modify the website using natural language.
- The administrator can upload approved images that become part of the repository.
- An AI coding agent edits the repository.
- Every modification is committed to Git.
- Any previous published version can be restored.

The proof-of-concept path is intentionally linear: one administrator, one repository,
one active website, one job at a time, and one hosted public site. Do not add a site
picker, tenant provisioning, per-site credential management, or concurrent jobs until
the single-site workflow is complete and reliable.

---

# Phase 1 – Initial Repository

Initial repository contents:

```
/
    index.html
    README.md

/admin
    app.py
    requirements.txt
    config.py

/templates

/static

/repos

/uploads

/prompts

/logs
```

Initial `index.html`

```html
<!DOCTYPE html>
<html>
<head>
    <title>Hello</title>
</head>
<body>
Hello world
</body>
</html>
```

Commit:

```
Initial commit
```

---

# Phase 2 – FastAPI Server

Use:

- Python 3.12+
- FastAPI
- Uvicorn
- Jinja2
- bcrypt
- python-multipart

Endpoints:

```
GET  /
GET  /admin
POST /login
POST /logout

GET  /dashboard

POST /prompt

POST /upload

GET  /history

POST /rollback
```

---

# Phase 3 – Authentication

Passwords must never be stored.

Use bcrypt.

```
bcrypt.hashpw()

bcrypt.checkpw()
```

Store only hashes.

Sessions:

- Secure cookies
- HttpOnly
- SameSite=Lax
- HTTPS only

Session expiration:

8 hours.

Rate-limit login attempts and record failed attempts without recording passwords or
session values.

---

# Phase 4 – CSRF Protection

Every HTML form contains a random CSRF token.

Server validates:

- session cookie
- CSRF token

Both must match.

Reject all invalid requests.

---

# Phase 5 – Single-Site Repository Model

For the proof of concept, configure exactly one active website. The browser never
submits a filesystem path, repository URL, or credential. The server reads all three
from its persistent configuration.

Keep the following future-compatible record shape, but create only one record in this
phase:

```
Website

id
name
github_repo
working_directory
github_token
owner
```

`github_token` must be an opaque secret-manager reference, not a raw token persisted
in the application database. SQLite stores the server-side configuration. The existing
`website_id` relationship remains an internal implementation detail to make a later
multi-site migration possible; the proof-of-concept dashboard has no website selector.

Administrator table:

```
Admin

username
password_hash
website_id
```

The browser never specifies a filesystem path.

The server maps the active website record to its repository.

---

# Phase 6 – Single Repository, Build, and Hosting Layout

Clone the one source repository into a server-configured repository root. The default
is `repos/` within the application project; production hosts can configure an absolute
path through `AUTOWEBSITE_REPOSITORIES_ROOT`.

During local proof-of-concept setup, an empty `active-site` directory may be seeded
from the bundled starter site. Once Git transport is connected in Phase 12, provision
that same directory from the configured GitHub repository instead; do not clone or
change remotes in response to a browser request.

```
<repositories_root>/

    active-site/       # Git checkout; never served while an agent is editing it

<published_root>/

    active-site/       # last validated, immutable release served to the public
```

AutoWebsite hosts the public site from `<published_root>/active-site/` at `/` and hosts
the administration UI at `/admin`. After a validated commit, publish a new release
atomically (for example, build into a new directory and swap a symlink or configured
release pointer). Never serve directly from the mutable checkout or an agent workspace.

Do not hard-code `/srv/autowebsites`: it is a reasonable Linux deployment location,
but macOS development machines should use a writable local location such as
`/Users/<user>/Sites/autowebsites`. All path manipulation must use Python `pathlib`,
not OS-specific string splitting or shell utilities.

The configured repository and published roots are allowlisted. Resolve every path
before use, reject paths outside its permitted root, and reject symlinks that escape
the root. Use a short-lived Git worktree for each job and a single repository lock so
only one edit can run at a time. Use least-privilege Git credentials and record the
expected remote URL and default branch at setup.

---

# Phase 7 – Single-Site Admin Dashboard

Dashboard contains

- Prompt textbox
- Upload button
- Submit button
- Job status
- Commit history
- Rollback button
- Preview link
- Validation report and changed-file diff
- Job log with retry and cancel state

No WYSIWYG editor.

Everything is prompt-driven.

There is no website switcher in the proof of concept. Persist jobs so a restart does
not lose their status, and run them serially. Maintain a private staging revision that
begins as the source checkout. Approval merges a reviewed job into staging; every later
job starts from the current staging revision, and the staging preview shows their
cumulative effect. Production remains unchanged until validation and publication.
Before publishing a change, show the administrator the proposed diff, validation result,
preview, and the prompt/uploads, model version, and validation run that produced it.
Require explicit approval for destructive or unusually large changes.
Rate-limit prompt submission, escape all displayed prompt, upload, diff, and log data,
and do not render administrator- or agent-supplied HTML as trusted dashboard markup.

---

# Phase 8 – Single-Site Coding Agent

Preferred implementation:

OpenAI Codex CLI.

Default model:

`gpt-5.6-terra`

Use the configured model override only when the deployment needs a different
intelligence/cost tier. Keep the exact selected model in every job record.

Alternative:

Aider

Alternative:

OpenHands

The coding agent receives:

- the current single-site worktree
- approved job-specific uploads and metadata
- system prompt
- administrator prompt

System prompt:

You are editing a website.

Requirements:

- Preserve valid HTML.
- Preserve accessibility.
- Preserve responsive behavior.
- Never modify files outside the repository.
- Never modify admin server code unless instructed.
- Keep CSS organized.
- Use semantic HTML.

Run the agent non-interactively with a pinned version/model, bounded wall time and
token budget, and structured output that lists changed files and executed validation
commands. Delimit administrator prompts and upload-derived data as untrusted input;
the agent must not follow instructions contained inside an asset. Apply policy checks
to the final diff, including sensitive-file, dependency, and change-size limits.
Never interpolate a prompt, filename, or upload-derived value into a shell command.
The agent must summarize its plan and validation results; policy or validation failures
end the job without publication.

---

# Phase 9 – Single-Site Uploads

The administrator uploads files for the active site. Store each upload under a generated
ID such as `uploads/active-site/<upload_id>/`; retain the original filename only as
display metadata. Do not accept an upload path from the browser.

Enforce a JPEG/PNG/WebP/GIF allowlist, content sniffing, file size/count quotas,
filename normalization, and malware scanning. An upload remains quarantined until it
passes those checks.

The administrator can later instruct the coding agent:

> Create a gallery using these uploaded images.

The images should not be transmitted to the LLM unless image understanding is required.

Instead provide:

```
filename

width

height

mime type
```

Generate a versioned metadata manifest, including `gallery.json` for images, with:

```
upload ID

original filename

checksum

mime type

width and height when applicable

scan status

gallery.json when applicable
```

automatically. Treat all upload metadata and extracted text as untrusted prompt input.
Copy only approved files required for a job into its worktree; never expose the shared
upload store to the agent.

---

# Phase 10 – Single-Site Production Safety and Release Gate

Deploy the proof of concept on one Linux VM under a non-root `autowebsite` service
account. The production README must provide a tested, ordered deployment path beginning
with cloning the GitHub repository, then installing Python, Git, and the Codex CLI,
Nginx, and a malware scanner; creating a virtual environment and protected state
directories; configuring secrets; and enabling a systemd unit. Recommend a minimum of
2 vCPU, 4 GB RAM, and 25 GB SSD for the one-site deployment, with more memory if
ClamAV runs locally. Codex is an external CLI executable and uses OpenAI-hosted model
inference; it is not a local model server.

Run the application without development reload/debug mode behind Nginx and TLS. Nginx
is the only Internet-facing process: it serves the public site's atomically switched
`published/current` release for `/`, forwards `/admin`, `/static`, and `/health` to
the app on localhost or a Unix socket, redirects HTTP to HTTPS, and renews the
configured domain certificate. The public server must never serve the source checkout,
staging tree, uploads, or job workspaces. Document DNS, firewall ports, certificate
issuance, and an optional VPN/IP allowlist for the sole administrator.

Keep the Git checkout, cumulative staging tree, disposable job workspaces, application
data, logs, and published releases in separate permission-restricted directories. Only
the active published release is readable by the public server. `/admin` has exactly one
configured administrator: use HTTPS, a strong password hash, a secret session key kept
outside the repository, secure cookies, CSRF protection, and preferably a VPN or IP
allowlist. No registration, default credentials, or multi-user roles are added here.

Run each agent job as an unprivileged, resource-limited process/container with only its
own workspace writable. It must not receive service or Git credentials, host sockets,
the source/staging/published trees, or the shared upload store. Give it network access
only when required for Codex/OpenAI, and then only through a narrow egress policy. The
initial CLI integration provides a workspace-write sandbox and timeout, but does not by
itself provide OS-level credential or filesystem isolation; require a separate
container/VM runner before enabling hostile/untrusted agent workloads. A job starts
from the current staging revision; the application rechecks its output and serializes
staging updates so an old job cannot overwrite a newer one. On cancellation or timeout,
terminate the job and leave staging and production unchanged.

Before a staging revision can be published, build an immutable candidate and require:

- allowed static files only; reject executable files, service configuration, secrets,
  escaping symlinks, and unexpected paths or sizes;
- HTML/CSS/JavaScript checks plus a local smoke test for the main page, links, and
  assets;
- a visible cumulative diff and an explicit administrator publish action.

Keep the candidate's checksums, staging revision, contributing job IDs, validation
result, and redacted logs. A failed check changes neither Git nor the public site and
leaves staging available for the next corrective job. Back up application state and the
last known-good release, document restoration, and test the complete one-admin flow
before accepting production traffic.

---

# Phase 11 – Logging

For the single site, maintain a durable audit trail and logs:

```
logs/

agent.log

web.log

security.log
```

Write line-delimited JSON records with an event name, timestamp, website ID, and the
currently active release ID when available. Rotate each file at a bounded size and keep
a small fixed number of prior files. Store logs beneath a server-configured,
permission-restricted `AUTOWEBSITE_LOGS_ROOT` (for the Linux deployment,
`/srv/autowebsite/state/logs`), not in the application checkout.

Record

- login
- logout
- uploads
- prompts
- commits
- rollbacks
- failures

Include the job ID and active release ID with every agent, validation, publication,
rollback, and security event. Record the duration of each edit job that users perform.
Retain enough information to diagnose a failed release
without recording secrets or uploaded file contents in logs. Enforce this at the log
writer: reject fields whose names indicate prompts, passwords, tokens, sessions,
cookies, secrets, paths, filenames, or content. Do not log raw agent output or error
strings; use stable outcome events and safe IDs/counts instead.

---

# Phase 12 – Git History, Publication, and Rollback

After the Phase 10 checks and administrator approval, serialize this single site's Git
workflow:

```
git add .
git commit
git push
```

Use a commit message such as:

```
AI: Added portfolio gallery
```

Give the commit/push operation—not the agent—the minimally scoped Git credential. Each
commit records the original prompt, job and upload IDs, agent/model version, validation
outcome, and release ID. The dashboard presents this history with commit hash, date,
author, message, and publication status.

The administrator can select a prior commit to roll back. Create a new rollback commit
(or a configured revert), build and run the same lightweight validation on its release
candidate, then atomically switch the hosted site to that candidate. Retain the prior
published release until the post-switch health check succeeds; if it fails, restore it
and record the failed publication. Git therefore provides a reliable recovery path for
bad site changes, while Phase 10 continues to protect credentials, the VM, and release
integrity.

On the admin panel, this replaces the list of "Agent Jobs" with a list of recent changes.
When a version is committed, the changes in that revision combine into a single entry.

---

# Phase 13 – AutoWebsite Hosting and Publication

This phase adds the production hosting feature, rather than only storing a validated
release on the VM. AutoWebsite serves the active static release at the configured public
domain/route while continuing to serve administration only at `/admin`. Configure the
domain, TLS certificate renewal, HTTP-to-HTTPS redirect, and restrictive public static
file serving in the deployment environment.

Publication takes the immutable candidate produced in Phase 10, creates a new release
directory, and atomically changes the public-server target only after the Git commit
and administrator approval succeed. Keep the previous release available until a post-publication
health check passes, so a failed switch can be reversed without serving a partial site.
GitHub is the source-of-truth backup and collaboration remote, not the production host
in this phase. GitHub Pages, Cloudflare Pages, and Netlify can become optional
deployment adapters after the hosted proof of concept is stable.

---

# Phase 14 – Multi-Site Expansion

Begin this phase only after the single-site acceptance criteria have been met in a
real hosted deployment. Add a website switcher and tenant provisioning only then.

Each additional website must have its own:

- repository and immutable remote configuration
- published release root and public host/domain mapping
- uploads, job queue, logs, and retention policy
- configuration and secret-manager credential reference
- worktree lock and resource quotas

Never share working directories or credentials. Authorization must be checked for
every website ID server-side, and the browser must continue to have no path access.

---

# Phase 15 – Future Enhancements

Future improvements may include:

- visual diff
- staging environment
- preview deployment
- AI image descriptions
- theme library
- page templates
- plugin system
- scheduled backups
- automatic screenshots
- accessibility audits
- Lighthouse performance audits

---

# Acceptance Criteria

The implementation is complete when:

- Administrator can log in securely.
- Administrator can upload files.
- Administrator can submit natural-language instructions.
- AI edits the repository.
- Changes are validated.
- Changes are committed.
- GitHub receives the commit.
- Static site publishes atomically after validation and required approval.
- AutoWebsite itself hosts the currently validated static site and keeps administration separate.
- Commit history is viewable.
- Any previous version can be restored.
- Security controls prevent unauthorized repository access.
