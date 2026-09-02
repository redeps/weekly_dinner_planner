# Setup — Meal Planner

Step-by-step instructions for getting this project running from nothing, and
for the day-to-day loop once it's running. Written for GitHub Codespaces.

## 1. Create the GitHub repository (private)

If you don't already have it: on GitHub, click **New repository**, name it
`meal-planner`, set visibility to **Private**, and create it without a
README (we bring our own files).

> If you already created the repo with a README/.gitignore, that's fine —
> just be ready to merge/replace when you add these project files.

## 2. Add the project files

Add all the files from this project backbone (docs/, app.py, database.py,
models.py, requirements.txt, README.md, .gitignore,
.devcontainer/devcontainer.json, components/, services/, tests/) to the
repository, either by:

- unzipping them into a local clone of the repo and pushing, or
- uploading them through the GitHub web UI, or
- committing them directly inside a Codespace (see step 3, then use the
  Codespace's terminal to add/commit/push).

Example (local clone):

```bash
git clone https://github.com/<your-username>/meal-planner.git
cd meal-planner
# copy the project files into this folder
git add .
git commit -m "Add project foundation: docs, structure, minimal app"
git push
```

## 3. Create a GitHub Codespace

On the repository page: **Code** → **Codespaces** tab → **Create codespace
on main**. GitHub will build the dev container from
`.devcontainer/devcontainer.json` automatically. This takes a minute or two
the first time.

## 4. Install dependencies

The devcontainer runs `pip install -r requirements.txt` automatically on
creation. If you need to re-run it manually (e.g. after changing
`requirements.txt`):

```bash
pip install -r requirements.txt
```

## 5. Start Streamlit

```bash
streamlit run app.py
```

## 6. Open the forwarded port

Codespaces will detect port 8501 and offer a notification/popup to open it
in the browser ("Open in Browser"). If you miss it, check the **Ports** tab
at the bottom of the Codespace window, find port 8501, and click the globe
icon to open it.

## 7. Run the tests

```bash
pytest
```

All tests should pass on a fresh checkout. If they don't, something is wrong
before you start changing code — fix that first.

## 8. Commit your changes

As you or a coding agent make changes:

```bash
git add <files you changed>
git commit -m "Short description of the change"
git push
```

Avoid `git add .` blindly — check `git status` first so you don't
accidentally stage anything under `data/` or `photos/` (they're gitignored,
but double-check if you ever see them listed as untracked).

## 9. Work through milestones one at a time

See `docs/ROADMAP.md` for the milestone list and `docs/AGENT_PROMPTS.md` for
ready-to-use prompts for each milestone. Don't skip ahead — finish and test
one milestone before starting the next. `docs/AGENT_INSTRUCTIONS.md` has the
rules any future coding agent (or you) should follow.

## 10. AI Assist (optional)

The app runs completely fine with no AI backend configured — Recipe Import
from a URL (structured data) needs none at all, and every other AI-assisted
feature (ingredient categorization, swap-intent, shortcuts, the free-text/
photo import paths) simply doesn't appear in the UI. See
`docs/PRODUCT_SPEC.md` §16 and `docs/DECISIONS.md` for the full reasoning.
Two independent backends, both optional:

**Local — Ollama** (recipe import fallback, categorization, swap-intent,
shortcuts). No API key, no cost, nothing leaves the machine.

1. Install Ollama and pull a small model, e.g. `ollama pull llama3.2`.
2. Run `ollama serve` (or let the Ollama app run in the background).
3. That's it — `AI_ASSIST_BACKEND` defaults to `ollama` and
   `OLLAMA_HOST` defaults to `http://localhost:11434`. Override either as
   environment variables if your setup differs.

**Hosted — Google Gemini free tier** (same text features as an alternative
to Ollama — set `AI_ASSIST_BACKEND=gemini` — **and required for photo
import**, which always uses Gemini regardless of that setting; see
`docs/DECISIONS.md`).

1. **Create the key.** Go to [aistudio.google.com](https://aistudio.google.com),
   sign in with a Google account, click **Get API key** in the left
   sidebar, then **Create API key**. Select an existing Google Cloud
   project or let it create one for you — no billing setup is required
   for the free tier. Copy the key immediately; it's shown only once (it
   starts with `AIza`) — if you lose it, create a new one.
2. **Restriction is automatic — just confirm it.** As of 2026, keys
   created in AI Studio are restricted to the Generative Language API by
   default at creation time — there's no manual restriction step to click
   through. On the API Keys page, check the **Key Type** column for your
   key: anything other than "Standard" is fine. If it says "Standard" (an
   older key type Google is phasing out — these stop working entirely in
   September 2026), delete it and click **Create API key** again; new
   keys default to the safer type automatically.
3. **Set it as `GEMINI_API_KEY` — as a secret, never committed:**
   - **In a Codespace** (recommended): repository → **Settings** →
     **Secrets and variables** → **Codespaces** → **New repository
     secret**. Name it exactly `GEMINI_API_KEY` — the app reads this
     specific variable (avoid also setting `GOOGLE_API_KEY`; some Google
     tooling prefers that name over an app-specific one, which could point
     a *different* tool at a key you meant only for this app — this app
     itself only ever reads `GEMINI_API_KEY`). Paste the key as the value
     and save, then **rebuild or restart the Codespace** — an
     already-running one won't pick up a newly added secret. Verify it's
     present without printing it:
     ```bash
     [ -n "$GEMINI_API_KEY" ] && echo "GEMINI_API_KEY is set" || echo "not set"
     ```
   - **Local (non-Codespace) dev**: create a `.env` file in the project
     root (already gitignored — never remove that entry) with
     `GEMINI_API_KEY=your-key-here`, and load it before running Streamlit,
     e.g. `export $(cat .env | xargs) && streamlit run app.py`.
4. Optionally set `AI_ASSIST_BACKEND=gemini` to use Gemini for the
   text-only features too (default is `ollama`); `GEMINI_MODEL` overrides
   the default model if needed.

This is relevant for local dev too now, not just a hosted deployment —
photo import (uploading a photo of a cookbook page/recipe card) has no
local-model fallback and needs a Gemini key to work at all, in the
Codespace or anywhere else.

**Never commit an API key** — not in code, not in a committed `.env`, not
pasted into a chat/AI tool prompt. If one ever ends up in a commit, treat
it as compromised: revoke it in AI Studio and issue a new one, don't just
remove it from a later commit.

## 11. Household passphrase (access gate)

The app is gated by a shared household passphrase (`services/auth.py`) —
see `docs/DECISIONS.md` for why (Streamlit Community Cloud's free tier
allows only one private app, already used by a sibling household app, so
this one will deploy as a **public** app from a **public** repo, protected
by this passphrase instead of Streamlit's private-app access control).

This reads from `st.secrets`, which is a different mechanism than the
`GEMINI_API_KEY` environment variable above — Streamlit only populates
`st.secrets` from a `.streamlit/secrets.toml` file (local) or its own
secrets manager (deployed), never from `.env` or plain environment
variables.

1. Create `.streamlit/secrets.toml` in the project root if it doesn't
   already exist (the whole `.streamlit/` folder is gitignored — never
   remove that entry). Add, at the root level (before any `[section]`
   header, same rule as any other root-level key):
   ```toml
   HOUSEHOLD_PASSWORD = "choose-a-real-passphrase-here"
   ```
2. Restart Streamlit if it's already running, so it picks up the new
   file: `st.secrets` is read once at startup.
3. **When this app is deployed to Streamlit Community Cloud**, add the
   same key via that app's **Settings → Secrets** (same TOML format) —
   nothing to do yet, noted here so it isn't forgotten. Deployment itself,
   and making the repo public, haven't happened yet; that's a deliberate
   later step, not part of this change.

Without this secret configured, every page fails closed (refuses access
and shows a configuration error) rather than silently letting anyone in.

## 12. Keep personal data and photos out of Git

`data/` (the SQLite database) and `photos/` (uploaded recipe photos) are
both listed in `.gitignore` and must stay that way. Never `git add -f` a
file under either folder. If you ever need to share the database for
debugging, export the specific rows you need rather than committing the
`.db` file.

## 13. Cloud deployment is a later milestone

Everything above runs entirely inside the Codespace with no external
services required. Hosted database, hosted photo storage, and remote
access are **Milestone 13** in `docs/ROADMAP.md`, and only happen after
the local prototype (Milestones 0–12) is stable. Auth for that milestone
is already decided and implemented (step 11 above) — the two approved
exceptions to "no paid/cloud dependency yet" are Gemini's free tier (step
10) and this passphrase gate's eventual public-repo requirement (step
11); don't add any other paid service or cloud dependency before
Milestone 13 is actually underway.

The rest of Milestone 13's architecture is decided (see
`docs/DECISIONS.md` and `docs/ROADMAP.md`'s Phase 1-5 breakdown; originally
six phases, with the connection layer and the service layer's SQL dialect
split into separate phases 1/2 — merged into one phase, see
`docs/DECISIONS.md`, once implementation showed those couldn't be verified
as independent states). Setup steps below are written ahead of time for
the phases not yet implemented.

**Local dev ✅ done (Phase 1): Postgres runs locally in the devcontainer,
not Neon.** `.devcontainer/devcontainer.json` installs Postgres via
`apt-get install postgresql` in its `postCreateCommand`, fixes
`pg_hba.conf` to allow the no-password local connection below (a fresh
`apt-get install postgresql` defaults local `host` connections to
`scram-sha-256`, which needs a password — confirmed directly and fixed by
switching those lines to `trust`; see `docs/DECISIONS.md`), and creates
the local dev/test database. Local dev and tests only ever talk to this
local instance; the deployed app is the only thing that talks to Neon.
`.streamlit/secrets.toml` needs a `[postgres]` section pointing at it:

```toml
[postgres]
dsn = "postgresql://postgres@localhost:5432/meal_planner"
```

**Photo storage ✅ done (Phase 2):** Cloudflare R2 via `boto3`, alongside
(not replacing) local filesystem storage — see docs/DECISIONS.md.
`.streamlit/secrets.toml` needs an `[r2]` section only once R2 is
actually wanted (e.g. testing the hosted path locally); with no `[r2]`
section at all, `services/photos.py` behaves exactly as it always has,
local-only — this is how local dev stays on local storage with zero
extra configuration. Key names match `boto3`'s S3 client constructor
exactly (`aws_access_key_id`/`aws_secret_access_key`, not the shorter
names an earlier draft of this doc used — confirmed against `boto3`
directly while implementing Phase 2):

```toml
[r2]
endpoint_url = "https://<account-id>.r2.cloudflarestorage.com"
aws_access_key_id = "..."
aws_secret_access_key = "..."
bucket_name = "meal-planner-photos"
```

**Hosted deployment (Phase 3, remaining part not yet implemented):** the
app deploys as a **public** app on Streamlit Community Cloud, from a
**public** GitHub repo (the free tier's one private-app slot is already
used by the sibling home-inventory app) — protected by the passphrase
gate instead of Streamlit's private-app mechanism. The repo is still
private and nothing is deployed yet; both happen only once Phase 3 is
actually underway. When it is, the deployed app's secrets (set via that
app's **Settings → Secrets**, same TOML format as above, never committed)
will need: `HOUSEHOLD_PASSWORD`, `GEMINI_API_KEY`, **`AI_ASSIST_BACKEND =
"gemini"`**, a `[postgres]` section with the **production Neon** DSN (not
the local one above), and an `[r2]` section with the real R2 credentials.

`AI_ASSIST_BACKEND` is listed as optional in step 10 above, but that's a
local-dev framing where Ollama can actually run alongside the app. A
hosted deployment has no local model server at all, and
`AI_ASSIST_BACKEND` defaults to `"ollama"` — by design, it is **never**
switched automatically just because `GEMINI_API_KEY` happens to be set
(see docs/DECISIONS.md, Milestone 10: explicit configuration, never
automatic fallback). Skip this line and every text-only AI Assist feature
(ingredient categorization, swap-intent, shortcuts) silently fails to
appear — `is_available()` returns `False` because it's still checking for
an unreachable Ollama server, not because anything is actually broken.
So for any hosted deployment, this line is effectively **required**, not
optional, for those features to work at all.

This is the one place all five secrets converge into a single box, so
the exact shape matters — the three root-level keys **must** go before
either `[section]` header, same rule as step 11:

```toml
HOUSEHOLD_PASSWORD = "choose-a-real-passphrase-here"
GEMINI_API_KEY = "AIza..."
AI_ASSIST_BACKEND = "gemini"

[postgres]
dsn = "postgresql://<user>:<password>@<neon-host>/<db>?sslmode=require"

[r2]
endpoint_url = "https://<account-id>.r2.cloudflarestorage.com"
aws_access_key_id = "..."
aws_secret_access_key = "..."
bucket_name = "meal-planner-photos"
```

Whatever platform specifics change between now and Phase 3 actually
starting, the same never-commit-a-secret rule from steps 10-11 applies to
all of these too.

## Quick reference

```bash
streamlit run app.py     # start the app
pytest                    # run tests
```
