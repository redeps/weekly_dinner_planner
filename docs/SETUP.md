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
2. **Restrict the key (recommended).** On the API Keys page in AI Studio,
   open the new key and restrict it to the **Generative Language API**
   only. This limits the damage if it's ever leaked — an unrestricted key
   can be used against other Google APIs on the same project, not just
   Gemini.
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

## 11. Keep personal data and photos out of Git

`data/` (the SQLite database) and `photos/` (uploaded recipe photos) are
both listed in `.gitignore` and must stay that way. Never `git add -f` a
file under either folder. If you ever need to share the database for
debugging, export the specific rows you need rather than committing the
`.db` file.

## 12. Cloud deployment is a later milestone

services required. Hosted database, hosted photo storage, authentication,
and remote access are **Milestone 13** in `docs/ROADMAP.md`, and only
happen after the local prototype (Milestones 0–12) is stable. The one
approved exception is Gemini's free tier for the two narrow AI Assist paths
in step 10 above — don't add any other paid service or cloud dependency
before Milestone 13. Whatever hosting platform is chosen then will have
its own secret-storage mechanism (e.g. environment variables in its
dashboard) — the same `GEMINI_API_KEY` name and never-commit rule applies
there too.

## Quick reference

```bash
streamlit run app.py     # start the app
pytest                    # run tests
```
