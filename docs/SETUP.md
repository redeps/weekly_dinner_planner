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

## 10. Keep personal data and photos out of Git

`data/` (the SQLite database) and `photos/` (uploaded recipe photos) are
both listed in `.gitignore` and must stay that way. Never `git add -f` a
file under either folder. If you ever need to share the database for
debugging, export the specific rows you need rather than committing the
`.db` file.

## 11. Cloud deployment is a later milestone

Everything above runs entirely inside the Codespace with no external
services required for the core app. Hosted database, hosted photo storage,
authentication, and remote access are **Milestone 13** in
`docs/ROADMAP.md`, and only happen after the local prototype (Milestones
0–12) is stable. Don't add a paid service or cloud dependency before then
— the one narrow exception is the optional Gemini API key below, which is
free-tier and deliberate (see `docs/DECISIONS.md`).

## 12. Set up a Gemini API key (for AI Assist and photo import)

Needed for: photo-based recipe import (always uses Gemini, no local
alternative), and optionally for the text-only AI Assist features
(categorization, swap-intent, shortcuts, unstructured text import) if
you'd rather not run Ollama locally. Skip this section entirely if you
don't want those features yet — everything else in the app works without
it.

**a. Create the key**

1. Go to [aistudio.google.com](https://aistudio.google.com) and sign in
   with a Google account.
2. Click **Get API key** in the left sidebar, then **Create API key**.
3. Select an existing Google Cloud project or let it create one for you —
   no billing setup is required to use the free tier.
4. Copy the key immediately. It's shown only once; if you lose it, you'll
   need to create a new one. It starts with `AIza`.

**b. Restrict the key (recommended)**

On the API Keys page in AI Studio, open the new key and restrict it to the
**Generative Language API** only. This limits the damage if the key is
ever leaked — a compromised unrestricted key can be used against other
Google APIs on the same project, not just Gemini.

**c. Add it to your Codespace as a secret — never commit it**

1. On GitHub, go to your repo → **Settings** → **Secrets and variables** →
   **Codespaces**.
2. Click **New repository secret**.
3. Name: `GEMINI_API_KEY` — use this exact name; the app reads this
   specific variable. (Avoid also setting `GOOGLE_API_KEY` — if both are
   set, most Google SDKs silently prefer `GOOGLE_API_KEY`, which can cause
   the app to authenticate with a key you didn't intend.)
4. Value: paste the key you copied.
5. Click **Add secret**.
6. Rebuild or restart your Codespace so the secret is injected as an
   environment variable (existing running Codespaces don't pick up new
   secrets automatically — stop and restart it, or create a new one).
7. Verify it's present without printing the key itself:
   ```bash
   [ -n "$GEMINI_API_KEY" ] && echo "GEMINI_API_KEY is set" || echo "not set"
   ```

**d. Never put the key in code, `.env` files committed to Git, or chat/AI
tool prompts.** `.gitignore` already excludes `.env` if you use one
locally instead of a Codespaces secret — check `git status` before
committing if you ever create one.

**e. Hosted deployment (Milestone 13, later)**

Whatever hosting platform is chosen then will have its own secret-storage
mechanism (e.g. environment variables in its dashboard) — the same
`GEMINI_API_KEY` name and never-commit rule applies. Nothing to do now;
noted here so it isn't forgotten later.

## Quick reference

```bash
streamlit run app.py     # start the app
pytest                    # run tests
```
