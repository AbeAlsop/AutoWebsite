# AutoWebsite Implementation Plan

## Objective

Create a self-editing website platform where:

- Every website is stored in a GitHub repository.
- The public website consists entirely of static HTML/CSS/JavaScript.
- A Python administration application allows authenticated administrators to modify the website using natural language.
- The administrator can upload arbitrary files (images, PDFs, ZIP files, etc.) that become part of the repository.
- An AI coding agent edits the repository.
- Every modification is committed to Git.
- Any previous version can be restored.

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

# Phase 5 – Repository Model

Each website has:

```
Website

id
name
github_repo
working_directory
github_token
owner
```

Administrator table:

```
Admin

username
password_hash
website_id
```

The browser never specifies a filesystem path.

The server maps website_id to the repository.

---

# Phase 6 – Repository Layout

Each website is cloned into:

```
/srv/autowebsites/

    website1/

    website2/

    website3/
```

Each repository is completely isolated.

---

# Phase 7 – Uploads

Administrator uploads files.

Server stores them inside

```
uploads/
```

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

Generate

```
gallery.json
```

automatically.

---

# Phase 8 – Admin Dashboard

Dashboard contains

- Prompt textbox
- Upload button
- Submit button
- Job status
- Commit history
- Rollback button

No WYSIWYG editor.

Everything is prompt-driven.

---

# Phase 9 – Coding Agent

Preferred implementation:

OpenAI Codex CLI.

Alternative:

Aider

Alternative:

OpenHands

The coding agent receives:

- current repository
- uploaded files
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

---

# Phase 10 – Agent Workspace

The coding agent works only inside

```
workspace/
```

Never allow access outside.

Reject any path containing

```
..
```

Reject absolute paths.

Normalize every filename.

Confirm every edited file begins with

```
repository_root
```

before writing.

---

# Phase 11 – Validation

Before committing:

Run

- HTML validation
- CSS validation
- JavaScript lint
- Unit tests (future)

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

---

# Phase 15 – Deployment

Primary option:

GitHub Pages

Alternatives:

Cloudflare Pages

Netlify

Deployment occurs automatically after push.

---

# Phase 16 – Logging

Maintain

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

---

# Phase 18 – Multi-Tenant Isolation

Every website has

its own

- repository
- uploads
- logs
- configuration
- GitHub token

Never share working directories.

Never reuse credentials.

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
- Static site automatically deploys.
- Commit history is viewable.
- Any previous version can be restored.
- Multiple websites remain completely isolated.
- Security controls prevent unauthorized repository access.
