# AutoWebsite Implementation Plan

## Objective

Create a self-editing website platform where:

- The first release maintains one website end to end as a proof of concept. Multi-site hosting is a later phase.
- The AutoWebsite service hosts the generated static website as well as its administration interface.
- The public website consists entirely of static HTML/CSS/JavaScript served by AutoWebsite; the administration application is available under `/admin`.
- The website source is stored in a GitHub repository.
- A Python administration application allows authenticated administrators to modify the website using natural language.
- The administrator can upload approved files (such as images, PDFs, and ZIP files) that become part of the repository.
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
The agent must summarize its plan and validation results; policy or validation failures
end the job without publication.

---

# Phase 9 – Single-Site Uploads

The administrator uploads files for the active site. Store each upload under a generated
ID such as `uploads/active-site/<upload_id>/`; retain the original filename only as
display metadata. Do not accept an upload path from the browser.

Enforce file-type allowlists, content sniffing, file size/count quotas, filename
normalization, and malware scanning. An upload remains quarantined until it passes
those checks. Non-executable archives such as ZIP files require explicit inspection
and extraction limits before use.

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

# Phase 10 – Single-Site Agent Workspace

The coding agent works only inside

```
<job_workspace>/
```

Run the workspace inside an OS/container sandbox as an unprivileged user, with only
that job worktree mounted read-write. Path normalization and rejecting `..` or absolute
paths are defense in depth, not the security boundary. Resolve every write target and
verify it remains under the worktree; reject escaping symlinks.

Deny host filesystem access, shell credential helpers, and network egress by default.
Pass narrowly scoped Git credentials only for the final push. Enforce CPU, memory,
process, disk, and wall-time limits, then delete the workspace after preserving the
job's audit logs and artifacts.

---

# Phase 11 – Validation

Before committing:

Run

- HTML validation
- CSS validation
- JavaScript lint
- Unit tests (future)

Also validate that the release contains only static, allowed files and that generated
links/assets resolve within the published site. Run validation in the same isolated
environment used for the agent. Keep validation output as part of the job record.

If validation fails

Do not commit.

Return errors to administrator.

---

# Phase 12 – Git Workflow

```
git add .

git commit

git push
```

For the proof of concept, commits and pushes are serialized by the single-site job
lock. Push only after validation and administrator approval. If publishing fails after
a successful push, retain the previous release and clearly mark the job as failed;
never expose a partial release.

Commit message:

```
AI:
<summary>
```

Example:

```
AI: Added portfolio gallery
```

---

# Phase 13 – History

Display

Commit hash

Date

Author

Message

Administrator can select any commit.

For each entry, show its job ID, original prompt, upload IDs, agent/model version,
validation outcome, publication outcome, and the hosted release it produced.

---

# Phase 14 – Rollback

Rollback performs

```
git checkout <commit>

git push
```

or

```
git revert
```

depending on configuration.

Record rollback in history.

Rollback must create and validate a new published release before switching the hosted
site. It must not mutate the currently served release in place.

---

# Phase 15 – AutoWebsite Hosting and Publication

AutoWebsite is the production host for the proof-of-concept site. It serves the active
validated release at the site's public route/domain and serves administration only at
`/admin`. Configure TLS and the public domain in the service's deployment environment.

Publication occurs automatically only after validation and any required approval. Use
atomic release switching and keep the prior release available for rollback. GitHub is
the source-of-truth backup and collaboration remote, not the production host in this
phase. GitHub Pages, Cloudflare Pages, and Netlify can become optional deployment
adapters after the hosted proof of concept is stable.

---

# Phase 16 – Logging

For the single site, maintain a durable audit trail and logs:

```
logs/

agent.log

web.log

security.log
```

Record

- login
- logout
- uploads
- prompts
- commits
- rollbacks
- failures

Include the job ID and active release ID with every agent, validation, publication,
rollback, and security event. Retain enough information to diagnose a failed release
without recording secrets or uploaded file contents in logs.

---

# Phase 17 – Security

Never execute administrator prompts as shell commands.

Never expose GitHub tokens.

Never expose OpenAI API keys.

Rate limit:

- login
- prompt submission

Reject oversized uploads.

Escape all HTML output.

Sanitize filenames.

Apply these controls to the one public site and its `/admin` route before introducing
any tenant-level authorization. Enforce TLS at the hosting boundary and keep public
static-file serving separate from authenticated administration routes.

---

# Phase 18 – Multi-Site Expansion

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

# Phase 19 – Future Enhancements

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

Multi-site isolation is a Phase 18 acceptance criterion, not a requirement for the
single-site proof of concept.
