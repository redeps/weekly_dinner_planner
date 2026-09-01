# Architecture Decisions — Meal Planner

Append-only log. Add new entries at the bottom with a date. Do not rewrite
history here — if a decision is reversed, add a new entry that supersedes it
and note what it replaces.

## 2026-08-31 — Local-first prototype

Use Streamlit + SQLite initially, same as the home inventory project. No
hosted database, no hosted file storage, no authentication layer. The
application must run entirely inside a GitHub Codespace with no external
services required.

## 2026-08-31 — Seasonality is weighted, not filtered

Recipes tagged for the current season are preferred by the plan generator,
but off-season recipes remain selectable (not hard-excluded). All-season
recipes are treated as a safe default with neutral weight.

## 2026-08-31 — Rotation avoidance via cook history

The plan generator deprioritizes recipes cooked within a recent window,
derived from `cook_history.cooked_on` (see `DATA_MODEL.md`). The exact
window length (e.g. 3 weeks) is not yet fixed — to be decided and recorded
here when Milestone 4 is implemented.

## 2026-08-31 — Prepopulated quick-fallback recipes

The app seeds a small set of recipes flagged `is_quick_fallback = true`
(e.g. fish fingers, frozen pizza, takeout) with minimal or no ingredients
and very low cook time, for the generator to lean on for busy days. These
are ordinary, editable recipes — the flag is only a generator signal.

## 2026-08-31 — Grocery list is not a shopping-mode feature

The grocery list is a simple generated, read-only, grouped-by-category view.
It is transcribed by hand rather than used directly in-store, so no
check-off state, persistence-while-shopping, or mobile "shopping mode" is
built.

## 2026-08-31 — AI assist via local model (Ollama), optional

The app integrates a locally-run model (e.g. via Ollama) for a bounded set
of assistive features: recipe import from pasted text/URL, ingredient
store-category suggestions, swap suggestions with a free-text intent hint,
and effort-saving shortcut suggestions. This keeps the app free-first (no
paid API) and consistent with local-first architecture. The integration is
optional and isolated in its own service module — no core screen depends on
it being available, and imported/suggested content is always
reviewed/confirmed by the user before being saved, never written
automatically. Scheduled for Milestone 9, after the core plan/grocery flow
is working.

## 2026-08-31 — Cook Mode reuses existing instructions text

Rather than introducing a structured "steps" table, Cook Mode (large-font,
step-by-step view for use while actively cooking) derives its steps by
splitting the existing `recipes.instructions` text at render time. Keeps
the schema unchanged; can be revisited later if a real need for
individually-orderable, richer steps emerges.

## 2026-08-31 — Structured-data recipe import; swappable AI backend (supersedes the AI-assist entry above)

Two problems were bundled into "AI Assist" that shouldn't have been: import
friction and language-model-dependent suggestions. Splitting them:

**Recipe import** now has a primary path that needs no model at all:
parsing `schema.org/Recipe` JSON-LD structured data from a given URL. This
is deterministic, free, and works identically whether the app is running
locally or hosted. The AI-assist text parser from Milestone 9 becomes a
fallback, used only for pasted free text or pages without structured data.

**AI Assist's suggestion features** (categorization, swap-intent, shortcut
suggestions) still genuinely need a language model and remain optional —
but the backend is now swappable rather than Ollama-only: local Ollama for
development (no cost, no key), or Google Gemini's free tier (chosen for
model quality over Groq/others) when no local model server is reachable,
e.g. the eventual Milestone 13 hosted deployment. This knowingly relaxes
"no cloud services" for this one narrow, optional feature — deliberately,
not by accident. Gemini's free tier is a standing tier (not trial credits)
and its rate limits comfortably cover a household's occasional use. The API
key is stored as a secret and never committed.

This was flagged late — after Milestone 9 shipped, not while it was being
scoped — because the hosted-deployment implication of an Ollama-only design
wasn't surfaced at design time. Recorded here so the gap and the fix are
both visible going forward. See Milestone 10 in `docs/ROADMAP.md`.

## 2026-08-31 — Structured-data parser is stdlib-only, no scraping library

The URL import path (above) is implemented as our own small parser using
only `urllib`, `html.parser`, and `json` — deliberately not a third-party
scraping package such as `recipe-scrapers`. We only need the generic,
standardized `schema.org/Recipe` JSON-LD block, not the hundreds of
site-specific scrapers such a package bundles; those per-site scrapers are
themselves a maintenance liability (they break whenever a site redesigns,
and the package has to be kept updated to match). A minimal in-house parser
targeting a stable published standard is smaller, has nothing to break in
the same way, and better matches this project's "small, easy to maintain"
principle than adding a large third-party dependency for a narrow need.

## 2026-08-31 — Photo-based recipe import always uses Gemini

Photo import (for recipes only available on paper — existing cookbooks,
recipe cards) has no non-AI fallback, unlike URL import. It requires a
vision-capable model. Rather than supporting a local vision model via
Ollama, photo import always calls the hosted Gemini backend, regardless of
which backend is configured for the text-only AI Assist features. A local
vision-capable model is meaningfully heavier than the text models used
elsewhere and a poor fit for typical Codespace resources, while Gemini
handles images as a normal part of its existing free tier. Consequence: if
no Gemini key is configured, photo import is simply unavailable — every
other feature, including URL import, is unaffected.

## 2026-08-31 — Free-first

No paid infrastructure during prototype development. Hosted/paid services
in general are deferred to Milestone 13 (Hosted Version) and require a new
decision entry before adoption. The one exception, approved and recorded
above (2026-08-31 — Structured-data recipe import; swappable AI backend),
is Google Gemini's free tier for two narrow, optional AI Assist paths —
this doesn't reopen the door to paid infrastructure generally.

## 2026-08-31 — Recipe ingredients are replaced wholesale on save

The Add/Edit Recipe form's ingredient rows are saved via a delete-all-then-
reinsert for that `recipe_id` (`services/ingredients.replace_recipe_ingredients`),
not a row-by-row diff against what's in the database. The form always
submits its full current row list, so this keeps the save path simple and
avoids tracking per-row database ids in the UI layer. Acceptable given
recipes have realistically small ingredient counts (a handful to a couple
dozen rows).

## 2026-08-31 — Weekly calendar input is re-entered, not persisted, in Milestone 3

The 7-day calendar (busy toggle + dinner-ready time per day) lives only in
Streamlit `session_state` for now, not in a database table. `DATA_MODEL.md`
assigns `is_busy`/`dinner_ready_time` to the `plan_days` table, which
`DATA_MODEL.md` explicitly scopes to Milestone 4 (created alongside
`week_plans` when a plan is generated) — creating that table now would mean
starting Milestone 4's schema early, which `AGENT_INSTRUCTIONS.md` rules
out. The user re-enters the week's calendar each time before generating a
plan; Milestone 4 will carry these values into `plan_days` at that point.

## 2026-08-31 — Plan generation design (Milestone 4)

Several implementation choices for the scoring generator in
`services/plan_generation.py`, per `PRODUCT_SPEC.md` §9:

- **Rotation window: 3 weeks (21 days).** A recipe last cooked within 21
  days of today gets a rotation penalty; outside that window it's scored
  normally. Chosen as the roadmap's own suggested default — no usage data
  yet to tune it further; revisit if 21 days feels too short/long once the
  app sees real use.
- **`cook_history` table created now, in Milestone 4, not the Cook History
  milestone (then numbered Milestone 7, since renumbered to Milestone 8 —
  see below).** `DATA_MODEL.md` nominally scopes `cook_history` to that
  later milestone, but rotation avoidance (this milestone, requested
  explicitly) needs to read `last_cooked_at` from it. Resolution: the
  table's *schema* is created now so the scoring logic can query it (empty
  table = no recipe is rotation-penalized, a safe default); the *write
  path* (`finalize_plan()` / `mark_day_cooked()`, and the "what have we
  cooked lately" view) stays a later milestone's work, per
  `AGENT_INSTRUCTIONS.md` §4 —
  history rows still only get written by an explicit business-logic
  action, never by rendering.
- **Current season is derived from the plan's `week_start_date` month**,
  Northern-hemisphere mapping (Dec–Feb winter, Mar–May spring, Jun–Aug
  summer, Sep–Nov fall). Not configurable yet; revisit if the household
  using this is in the Southern Hemisphere.
- **Busy-day preference uses `is_busy` only, not "tight" `dinner_ready_time`.**
  `dinner_ready_time` is stored per day but nothing in the data model
  captures when cooking *starts*, so "tight" can't be computed from what we
  have. Only `is_busy` drives the busy-day cook-time preference for now.
- **No repeated recipe within the same generated week**, when enough
  distinct active recipes exist to avoid it (falls back to allowing a
  repeat only if the active recipe pool is smaller than 7). This is
  separate from the cross-week rotation window above, which is about
  avoiding recent repeats *between* weeks.

## 2026-08-31 — Roadmap renumbered to insert Cook Mode; Cook History built out of order

`docs/ROADMAP.md`, `docs/PRODUCT_SPEC.md`, `docs/DATA_MODEL.md`, and
`docs/AGENT_PROMPTS.md` were updated to add a new Cook Mode milestone
(large-font, step-by-step cooking view — see the entry above) as Milestone
7, shifting every milestone after it (old Milestone 7 Cook History onward)
up by one. These updates were uploaded to the repository root instead of
`docs/` and arrived as a separate commit that had diverged from this
branch's history; reconciling the two required merging them in rather than
a plain file overwrite, to avoid losing the ✅ progress markers and the
Milestone 2–4 decision entries above, which the uploaded snapshot predated.

Net effect: Cook History (now Milestone 8) was already implemented before
Cook Mode (Milestone 7) existed on the roadmap, so it was built out of the
now-current milestone order. This is flagged here rather than silently
resolved — the next milestone to pick up, in order, is Milestone 7 (Cook
Mode).

## 2026-08-31 — AI Assist implementation (Milestone 9)

Implementation choices for `services/ai_assist.py`, per `PRODUCT_SPEC.md`
§16:

- **Talks to Ollama's HTTP API directly via `urllib` (stdlib), not the
  `ollama` pip package.** Avoids a new dependency for a handful of simple
  POST requests, consistent with free-first/keep-it-small. Host
  (`OLLAMA_HOST`, default `http://localhost:11434`) and model
  (`AI_ASSIST_MODEL`, default `llama3.2`) are environment-variable
  overridable, since the model actually pulled varies per machine.
- **`is_available()` only confirms the Ollama server responds** (hits
  `/api/tags`), not that the configured model is specifically pulled.
  Checking the exact model would need parsing the tag list and matching
  names — a real per-call failure (missing model, bad response) is instead
  just handled the same way as "unreachable": the function returns `None`
  and the caller shows nothing, one unified failure path rather than two.
- **Recipe import fetches a pasted URL itself** (stdlib `urllib`, with a
  short timeout and a regex-based script/style/tag strip — no HTML-parsing
  library added) rather than requiring the user to paste already-fetched
  text. Low risk here: single-user, local-only household tool, not a
  multi-tenant service; the fetched content is only ever passed into the
  model prompt, never executed or rendered as HTML.
- **Swap-intent narrowing stays out of `services/plan_generation.py`
  entirely**, per `AGENT_INSTRUCTIONS.md` §6 (no core screen/service may
  depend on AI assist). `swap_day_recipe()` instead grew a generic optional
  `candidate_filter` hook — a plain callable, with no knowledge of AI
  assist — that the Week Plan screen supplies only when Ollama is
  available and an intent hint was entered. An empty/failed filter result
  is ignored and the unfiltered candidate list is used, so a bad or
  unavailable filter can never break a swap.
- **Every `ai_assist` function returns `None` (or an empty/unfiltered
  result) rather than raising**, whether the cause is an unreachable
  server, a missing model, a timeout, or a response that doesn't parse as
  expected — one graceful-degradation contract for every caller, verified
  in this environment (no Ollama installed) as real behavior, not just
  mocked.

## 2026-08-31 — Milestone 10 implementation choices

Implementation choices for `services/recipe_import.py` and the
`services/ai_assist.py` backend refactor, on top of the design already
recorded above (Structured-data recipe import; swappable AI backend, and
the two entries after it):

- **Backend is explicit configuration, never automatic fallback.**
  `AI_ASSIST_BACKEND` (`ollama` default, or `gemini`) picks the text
  backend outright; if it's `ollama` and Ollama isn't reachable, the app
  does not silently try Gemini even if a key happens to be set, and vice
  versa. Rationale: a household running locally shouldn't have its
  ingredient names or swap-intent text start going to a cloud API just
  because a key was configured for some other reason (e.g. testing) — the
  operator chooses the backend deliberately. An invalid `AI_ASSIST_BACKEND`
  value falls back to `ollama` rather than erroring.
- **Gemini reached via `urllib` (stdlib) against the public
  `generativelanguage.googleapis.com` REST API, not the `google-genai`
  SDK.** Same reasoning as Ollama's stdlib client (see the AI Assist
  implementation entry above): a handful of POST requests don't justify a
  new dependency. One low-level `_call_gemini()` backs both the text
  backend and photo import, since both are the same `generateContent`
  call with different `parts` (text-only vs. text+`inline_data`).
  `GEMINI_MODEL` defaults to `gemini-2.0-flash`, overridable — Google's
  model lineup moves faster than this file will be revisited, so this is
  expected to need bumping over time.
- **`is_available()` for the Gemini backend checks only that a key is
  configured, not a live reachability call.** Unlike Ollama's cheap local
  `/api/tags` ping, a real Gemini call costs a request against a metered
  (if free) quota; spending one just to answer "is this available" isn't
  worth it; an actual `_generate()` call still degrades gracefully if the
  key turns out to be invalid or the quota is exhausted.
- **`services/recipe_import.py` is not treated as "AI assist" for
  isolation purposes** (docs/AGENT_INSTRUCTIONS.md §6) — its primary path
  is deterministic and needs no model, so it's safe for the Add/Edit
  Recipe screen to call directly and unconditionally, unlike
  `services/ai_assist.py`. Its *fallback* path does call into
  `ai_assist.import_recipe_from_text()`, which already degrades to `None`
  on its own if no backend is configured — recipe_import.py doesn't need
  to know or care whether that happened.
- **`recipeIngredient` lines are stored whole, not split into
  name/quantity/unit.** schema.org's `recipeIngredient` is a flat list of
  free-text lines (e.g. "2 cups flour"), not structured fields — splitting
  that out reliably is exactly the kind of per-site/per-phrasing parsing
  logic a scraping library would bundle, which `docs/DECISIONS.md`
  (Structured-data parser is stdlib-only) deliberately avoids taking on.
  Each line becomes one ingredient row with the full text as its `name`;
  the user can split it manually if they want grocery-list unit
  aggregation to match. A real, honest limitation of the stdlib-only
  choice, not an oversight.
- **Verification note:** graceful degradation across all four backend
  combinations (none / Ollama only / Gemini only / both) is verified by
  mocked tests, and all core screens were re-confirmed working against
  this environment's real state (no Ollama, no Gemini key). The
  live Gemini-available code paths (text and photo) are verified only via
  mocked responses — this environment has no Gemini API key, so they
  haven't been exercised against the real API.

## 2026-08-31 — Recipe photo storage (Milestone 11)

Implementation choices for `services/photos.py`:

- **Every upload is normalized to a single `photos/<recipe_id>.jpg`**,
  regardless of the source format (JPEG or PNG, including RGBA — converted
  to RGB before saving as JPEG). This makes "replace" trivial (a new
  upload just overwrites the same fixed filename — no orphaned old-format
  file left behind) and keeps display code from needing to guess an
  extension.
- **Resize caps the longer edge at 1200px** (`Image.thumbnail`, so it only
  ever shrinks, never upscales a smaller photo) **and saves at JPEG
  quality 85.** Generous enough for anything this app displays (cards,
  detail view, a small Cook Mode thumbnail), while keeping files small for
  a household git-ignored `photos/` folder that isn't backed up elsewhere
  yet.
- **A failed photo (unreadable upload) doesn't block saving the rest of
  the recipe.** The name/ingredients/instructions are written first;
  photo processing is attempted after and, if it raises, the recipe is
  still saved and a warning is shown on the following Recipe Detail view
  rather than losing the user's typed data over an unrelated bad file. The
  live preview shown immediately after choosing a file is wrapped the same
  way — an invalid file can't crash the page before Save is even clicked
  (caught by testing before shipping: an unreadable upload originally
  crashed the whole page at preview time, not just at save time).
- **Verified with a real simulated upload**, not just the service layer in
  isolation: `AppTest`'s `file_uploader.upload()` drives the actual
  widget, through resize/save, through the DB write, through display on
  all four required screens (recipe cards, Recipe Detail, Week Plan day
  rows, Cook Mode).

## 2026-08-31 — Milestone 12 (Polish) implementation choices

- **Confirmation for Deactivate is an inline two-step confirm
  (session-state gated warning + Yes/Cancel), not `st.dialog`.**
  `st.dialog` exists and renders in this Streamlit version, but a quick
  check found its *interactions* don't reliably complete through
  `AppTest` (a click on a button inside the dialog didn't visibly take
  effect, even though the dialog's own contents rendered) — real enough
  uncertainty that shipping it without being able to verify the full
  confirm/cancel flow end-to-end didn't feel right. The inline pattern is
  simpler, has no such gap, and is exactly what's used elsewhere in this
  app already (e.g. Milestone 7's Cook Mode step navigation).
- **Backup export uses SQLite's own `Connection.backup()` API**, not a
  raw read of `DB_PATH`'s bytes, so a concurrent write in progress can't
  produce a corrupt downloaded snapshot. Photos aren't included in the
  download — the roadmap's own example ("download the SQLite file") is
  treated as the intended scope; the Home page's backup section says so
  explicitly so it isn't mistaken for a complete backup.
- **The "mobile UX pass" is a targeted restructure of Week Plan**
  (collapsing each day's buttons into a per-day `st.expander("Actions")`,
  leaving a compact always-visible summary line), not a general pass over
  every screen. Week Plan was the clear outlier — 7 rows of 4-5 always-
  visible buttons each is the app's worst case for a narrow screen; other
  screens' `st.columns` layouts already degrade reasonably via
  Streamlit's own responsive column-stacking, which this project doesn't
  need to reimplement.
- **Empty states elsewhere were mostly already in place** — Week Plan,
  Grocery List, Cook History, and the two "no recipe selected" screens
  each got a friendly empty-state message as part of the milestone that
  introduced them, rather than deferred to this one. The one real gap
  fixed here: Recipes browsing showed the same generic message whether
  the database was genuinely empty or just the active filters matched
  nothing — now distinguished, since the correct next action differs
  ("add a recipe" vs. "adjust your filters").

## 2026-08-31 — Auth: in-app passphrase, not Streamlit's private-app mechanism

Streamlit Community Cloud's free tier allows only **one** private app,
already spent on a sibling household app ("home-inventory"). meal-planner
therefore deploys as a **public** app from a **public** repo instead,
gated by a shared household passphrase built into the app itself
(`services/auth.py`), rather than relying on Streamlit's built-in
private-app access control.

`require_password()` checks `st.session_state["authenticated"]` first (no
re-prompt within a session); otherwise it renders a
`st.text_input(type="password")` and compares the entry against
`st.secrets["HOUSEHOLD_PASSWORD"]` (a root-level secret, same placement
convention as `GEMINI_API_KEY` — before any `[section]` in
`secrets.toml`) using `hmac.compare_digest`, not `==`, to avoid a trivial
timing side-channel. A missing secret fails closed — access is refused,
not silently granted.

**The critical detail this design has to handle itself, which Streamlit's
private-app mechanism handled automatically: multipage apps let a user
deep-link straight to any file under `pages/`, bypassing `app.py`
entirely.** A gate placed only in `app.py` would protect nothing.
`require_password()` is called at the top of `app.py` **and every file in
`pages/`** — immediately after `st.set_page_config(...)`, which Streamlit
requires to be the first Streamlit call in a script, so it has to come
after that, not before. Verified directly: every page, loaded on its own
without going through `app.py` first, shows the gate and nothing else
(`tests/test_auth_gate.py`), both against mocked secrets and against this
environment's real (locally configured) `HOUSEHOLD_PASSWORD`.

Consequence for the rest of Milestone 13's hosting decisions (Postgres
provider, photo storage, schema migration approach, CI/deployment
specifics): still open, to be proposed and recorded separately. This
entry covers only the auth mechanism, decided and implemented ahead of
the rest because it was a blocking constraint (the one-private-app-slot
conflict) discovered while planning deployment. The repository's
visibility has not been changed and nothing has been deployed yet —
implementing and locally verifying this gate was the explicit prerequisite
before either happens.

## 2026-08-31 — Milestone 13 hosting architecture (Neon + Streamlit Community Cloud)

The rest of Milestone 13, deferred by the entry above: settled over
several rounds of planning (not all committed to disk as they happened —
this entry is the catch-up record). Matches the stack already running a
sibling household app ("home-inventory"), reusing its proven patterns
directly rather than designing new ones from scratch, and keeping one
vendor/stack across both apps instead of two.

**Vendor/stack: Neon (Postgres) + Streamlit Community Cloud.** Supabase
and Turso (hosted SQLite) were both considered and rejected in favor of
matching home-inventory. meal-planner gets its **own separate Neon
project** — not shared with home-inventory, so schema-migration history
and connection limits stay independent between the two apps. "Same
stack" means same vendor and same code pattern, not a shared database.

**Local dev: local Postgres installed via `apt` in the devcontainer —
not a Neon development branch.** A development-branch approach was
proposed and then reversed during planning: local dev never touches
Neon at all, only the deployed Streamlit Cloud app does, so Neon's
project only needs its default/production branch. This keeps "must run
entirely inside a Codespace with no external services" true for local
dev rather than opening an exception for it. `.devcontainer/` does not
exist yet in this repository — confirmed via `git log --all` (no commit,
on any ref, has ever touched it) and `ls -la` (not present on disk) — so
Phase 1 (below) creates `.devcontainer/devcontainer.json` from scratch,
it doesn't edit an existing one.

**Reliability — two distinct things, not one:** Neon's free-tier
autosuspend wakes in ~300-800ms (compute suspends when idle; data is
never lost), which resolves the "reachable from my phone reliably"
concern. Streamlit Community Cloud's own app-sleep (~30-60s wake after
a period with no visitors) is a separate mechanism this doesn't touch —
still a real, minor friction on an infrequently-visited household app,
just not a database problem.

**Schema management: port home-inventory's exact pattern.** A
`SCHEMA_MIGRATIONS: list[tuple[int, str]]` of versioned, additive SQL
blocks, a one-row `schema_version` table, and `_apply_migrations(conn)`
called from `get_connection()` — applying anything newer than the
current recorded version. Lives in `database.py` (matching
home-inventory's file organization); this replaces meal-planner's
current per-table `create_recipes_table()`-style idempotent-DDL
functions. `models.py` keeps the dataclasses and constants only.

**Column types — match home-inventory's conventions, verified against
what meal-planner's own code already assumes (re-confirmed via `grep`
while writing this entry, since it had been a few rounds since this was
first checked):**
- Booleans (`is_quick_fallback`, `active`, `is_busy`) stay `INTEGER` 0/1,
  not native `BOOLEAN`. `services/recipes.py` and
  `services/plan_generation.py` already do
  `bool(row["is_quick_fallback"])`, `bool(row["active"])`,
  `bool(row["is_busy"])` at the row-mapping boundary — matching
  home-inventory costs zero changes to that code.
- `created_at`, `updated_at`, `plan_days.date`, `cook_history.cooked_on`,
  `week_plans.week_start_date`, and `plan_days.dinner_ready_time` all
  stay `TEXT`, not native `TIMESTAMPTZ`/`DATE`/`TIME`.
  `services/plan_generation.py` and `services/cook_history.py` already
  do `dt.date.fromisoformat(row[...])` / `.isoformat()` throughout for
  real date arithmetic (rotation window, sorting) — every date-shaped
  column in the schema gets the same treatment, not just the ones
  home-inventory happened to have.
- Primary keys: `SERIAL`, matching home-inventory (not
  `GENERATED ALWAYS AS IDENTITY` — purely stylistic, no reason to diverge).

**Secrets: DSN via `st.secrets["postgres"]["dsn"]`**, matching
home-inventory — `.streamlit/secrets.toml` locally (gitignored),
Streamlit Community Cloud's secrets manager when deployed. This now
coexists with two other, deliberately different, secret-reading
conventions already in the codebase: `HOUSEHOLD_PASSWORD` (also
`st.secrets`, but root-level, not nested — see the auth entry above) and
`GEMINI_API_KEY` (plain `os.environ`, per the AI Assist entries above).
Not being unified in this pass — three conventions in one small app is
inelegant, but each was deliberately matched to a specific existing
pattern (Postgres and the passphrase both mirror `st.secrets` usage
from elsewhere; `GEMINI_API_KEY` predates the other two and changing it
now would touch working, tested code for no functional benefit).

**Test isolation: port `schema_name_for(identity)`** — a per-test
Postgres *schema* (not a separate database, not SQLite `:memory:`),
keyed by a hash of an arbitrary identity (e.g. pytest's `tmp_path`),
created on first use. `get_connection()` defaults to the `public` schema
(real data) when no identity is given.

**Photo storage: Cloudflare R2, via `boto3`** — matching home-inventory
exactly. `boto3` client (the standard AWS SDK, speaks any S3-compatible
API including R2) against `st.secrets["r2"]` (`endpoint_url`,
credentials, bucket name), object keys shaped `photos/<recipe_id>.jpg` —
the same naming `services/photos.py` already uses locally
(`photo_relative_path()`), so the key scheme carries over unchanged.
Backblaze B2 is the documented fallback if a Cloudflare card-on-file is
ever unwanted — same `boto3` code works against either, since both
speak the S3 API. `services/photos.py` keeps its swappable local/hosted
backend design: local filesystem for the local-Postgres-backed dev
environment above, unchanged; R2 for production.

**Deliberate exception to the "avoid new SDK dependencies" precedent:**
`services/ai_assist.py` avoided the `ollama`/`google-genai` SDKs in
favor of raw `urllib` calls (see the AI Assist entries above) because
those are simple bearer-token REST calls. S3-compatible APIs require
request signing (AWS Signature V4), which is genuinely risky to
hand-roll versus reusing `boto3` — a different calculus, not an
inconsistency, and matching a proven working implementation
(home-inventory's) is further reason not to reinvent it. `requirements.txt`
will gain `boto3` when Phase 3 is implemented.

**Roadmap phases for the rest of Milestone 13** (see `docs/ROADMAP.md`
for the up-to-date checklist): Phase 1 (local Postgres in the
devcontainer + the migrations/`schema_version` pattern for
meal-planner's five tables), Phase 2 (migrate `services/recipes.py`,
`services/ingredients.py`, `services/plan_generation.py`,
`services/cook_history.py` to `psycopg`/`%s` placeholders), Phase 3
(photo storage via `boto3`/R2), Phase 4 (auth gate — **done**, see the
entry above — plus CI and deploying as a public app from a public repo,
pointed at Neon's production branch), Phase 5 (one-time data migration:
local SQLite → Neon, local `photos/` → R2), Phase 6 (backups: pure-Python
per-table CSV/zip export, no `pg_dump`). None of Phases 1, 2, 3, 5, or 6
are implemented yet — this entry is docs only, recording the settled
design so implementation can proceed phase by phase against a written
plan instead of relying on conversation history.

## 2026-09-01 — Milestone 13 Phase 1/2 merge, and implementation findings

Implementing Phase 1 (the entry above) surfaced a problem the phase split
didn't account for: `get_connection()` returning a Postgres connection —
required for `schema_name_for(identity)`'s per-test Postgres *schema*,
which has no SQLite equivalent — breaks every call site in
`services/recipes.py`, `services/ingredients.py`,
`services/plan_generation.py`, and `services/cook_history.py` immediately,
since all four use `?` placeholders and each defines its own
`_dict_cursor(conn: sqlite3.Connection)` helper. Postgres/psycopg doesn't
accept `?` placeholders at all — this isn't a degraded state the app
tolerates until Phase 2, it's a hard break (every query fails), so Phase 1
and Phase 2 could never actually be verified as separate, independently-
green states the way every other milestone in this project has been.
Corrected boundary: **Phase 1 now covers the connection layer and the
four named services' SQL dialect together** (see `docs/ROADMAP.md`,
renumbered from six phases to five). Photo storage (now Phase 2, was
Phase 3) is unaffected by this — `services/photos.py` never touched
`sqlite3` placeholders or row objects, so it remains a genuinely
independent next phase.

Implementation choices made while porting the four services, beyond the
placeholder syntax (`?` → `%s`) already anticipated by the roadmap:

- **Row access: `conn.cursor(row_factory=psycopg.rows.dict_row)` replaces
  each file's `_dict_cursor()` sqlite3.Row setup**, one-line body instead
  of three. Dict rows support the same `row["column"]` access used
  throughout, so no call-site changes were needed beyond the cursor
  construction itself. The plain `conn.execute(...)` call sites that
  relied on positional tuple access (`row[0]`) were deliberately left
  alone — psycopg3's default row factory is already `tuple_row`, matching
  sqlite3's default (`None` = tuples) exactly, so the existing mixed
  "some call sites want dicts, some want tuples" pattern carried over with
  zero changes to those call sites.
- **`cursor.lastrowid` has no psycopg equivalent** (Postgres has no
  client-side last-insert-id concept) — every insert that needed the new
  row's id (`create_recipe`, `generate_week_plan`'s `week_plans` insert,
  `mark_day_cooked`) gained a `RETURNING id` clause and reads
  `cursor.fetchone()[0]` instead.
- **`LIKE ? COLLATE NOCASE` (search) → `ILIKE %s`; `ORDER BY name COLLATE
  NOCASE` → `ORDER BY LOWER(name)`.** Postgres has no built-in `NOCASE`
  collation (that needs ICU or the `citext` extension, neither used
  elsewhere in this small app) — `ILIKE` and `LOWER()` reproduce the same
  case-insensitive behavior with no new dependency.
- **`datetime('now')` (SQLite) → `to_char(now() AT TIME ZONE 'utc',
  'YYYY-MM-DD HH24:MI:SS')`**, kept as a module-level `_NOW_EXPR`
  constant in both `database.py` (schema defaults) and `services/recipes.py`
  (explicit `updated_at` writes) rather than a shared import, since the two
  files don't otherwise depend on each other and the expression is a
  one-line literal. Produces the same UTC, second-precision, TEXT-typed
  string shape as the old SQLite default — confirmed nothing parses
  `created_at`/`updated_at` with `dt.date.fromisoformat()` (only
  `cooked_on`, `plan_days.date`, and `week_start_date` do, and those are
  always Python-supplied `.isoformat()` values, never this DB-computed
  default), so exact format compatibility wasn't a real constraint, just a
  courtesy.
- **`get_connection()` uses `autocommit=True`.** Not part of the original
  plan, but required once `streamlit run app.py` was actually tested
  end-to-end: none of `app.py` or `pages/*.py` ever call `conn.close()`
  (harmless with SQLite's file-based connections, since each Streamlit
  rerun's connection just got garbage-collected) — with Postgres, an
  unclosed connection that has run a plain `SELECT` sits `idle in
  transaction`, holding locks that blocked later connections (observed
  directly: `pytest` hung, and `pg_stat_activity` showed a page's
  `has_been_cooked()` query idle-in-transaction for minutes, blocking a
  test's `DROP SCHEMA ... CASCADE`). `autocommit=True` means each
  statement lands immediately with nothing left open between them,
  regardless of whether callers ever close the connection. Confirmed
  `conn.commit()` is a harmless no-op on an autocommit connection in
  psycopg3, so none of the four services' existing explicit `.commit()`
  calls needed to be touched. `export_database_bytes()` wraps its
  multi-table read in an explicit `with conn.transaction():` block (still
  works under `autocommit=True`) to keep its `REPEATABLE READ` snapshot
  guarantee across all five tables.
- **`export_database_bytes()` changed from a SQLite file to a zip of one
  CSV per table**, one phase earlier than planned (this was meant to be
  Phase 6/5's work). The old implementation used `sqlite3.Connection`'s
  own `.backup()` API, which has no Postgres equivalent — leaving it
  unported would have left the Home page's backup button (and three
  `test_foundation.py` tests plus one `test_polish_ui.py` test) broken
  until Phase 5, which didn't seem like an acceptable place to land this
  phase. This is a minimal stand-in, not the full Phase 5 design — no
  photos, no nicer packaging — Phase 5 remains open to revisit if more is
  needed. `app.py`'s download button label/filename/mime type were updated
  to match (`.zip`, not `.db`).
- **Local Postgres auth: apt's default `postgresql` package uses
  `scram-sha-256` for TCP (`host`) connections**, which needs a password —
  the documented no-password local DSN
  (`postgresql://postgres@localhost:5432/meal_planner`, from
  `docs/SETUP.md`, written before Phase 1 was implemented) would not have
  worked against a fresh `apt-get install postgresql` without a config
  change. Verified directly in this environment: switched `pg_hba.conf`'s
  `host ... 127.0.0.1/32` and `::1/128` lines (and the two `local` peer
  lines, for consistency) from `scram-sha-256`/`peer` to `trust`, restarted
  the cluster, and confirmed the documented DSN connects with no password.
  This fix is baked into `.devcontainer/devcontainer.json`'s
  `postCreateCommand` via `sed`, so a fresh devcontainer build reproduces
  it automatically — the DSN itself did not need to change.
- **Every test that touches the database now goes through
  `database.get_connection(identity=...)` against real local Postgres**,
  not `sqlite3.connect(":memory:")` + `models.create_*_table()` (removed
  along with the rest of `models.py`'s table-creation functions). This
  affected five previously-sqlite3-only unit test files
  (`test_recipes_service.py`, `test_ingredients_service.py`,
  `test_plan_generation_service.py`, `test_cook_history_service.py`,
  `test_grocery_list_service.py`) plus a handful of raw `?`-placeholder
  SQL statements those files wrote directly (test fixtures/helpers, not
  service code) for setting up rows the service layer doesn't expose a
  writer for. For the two AppTest-driven UI test files
  (`test_cook_history_ui.py`, `test_polish_ui.py`), which exercise the
  real page scripts calling `database.get_connection()` with no
  arguments, isolation is a monkeypatched module-level
  `database.TEST_SCHEMA_IDENTITY` (mirroring the old
  `DATA_DIR`/`DB_PATH` monkeypatch pattern) rather than the `identity=`
  parameter directly — `app.py`/`pages/*.py` were not touched to thread a
  test identity through, keeping this phase's footprint out of those
  files. Every isolated-schema fixture drops its schema
  (`DROP SCHEMA ... CASCADE`) on teardown — confirmed by running the full
  suite three times in a row with zero `test_%` schemas left behind
  afterward, to avoid repeating the exact "accumulating rows in a
  disposable local dev database" mistake fixed the round before this one.
- **`.streamlit/secrets.toml`'s `[postgres]` section now points at the
  local instance** (`postgresql://postgres@localhost:5432/meal_planner`),
  replacing a Neon production DSN that had been placed there during
  earlier planning/exploration — matches "local dev never touches Neon"
  from the entry above. That DSN was never actually connected to from
  this environment as far as can be verified: neither `psycopg` nor
  `psycopg2` was installed before this phase's work began (confirmed —
  `import psycopg` failed with `ModuleNotFoundError` at the start), and no
  local trace of it being used exists (shell/Python history, logs, and a
  repo-wide search for `neon.tech` all came up empty). This can't be
  stated as an absolute guarantee — a different environment instance
  could in principle have used it and left no trace here — but every
  check available from this environment says "present but unused."

## 2026-09-01 — Milestone 13 Phase 1: transaction atomicity under autocommit

`autocommit=True` (see the entry above) means each individual statement
lands on its own by default — anywhere multiple writes were relying on
the old `sqlite3` default (an implicit transaction held open until a
trailing `conn.commit()`) needed an explicit `with conn.transaction():`
wrap, or a failure partway through could leave a partial write instead of
rolling back cleanly. Audited `services/ingredients.py`,
`services/plan_generation.py`, and `services/cook_history.py` for this
pattern specifically (multi-statement writes across more than one
`conn.execute()` call, not just multiple rows via one query):

- **`services/ingredients.py: replace_recipe_ingredients`** — the
  delete-all-then-reinsert (`docs/DECISIONS.md`'s "Recipe ingredients are
  replaced wholesale on save" entry above). Wrapped in
  `with conn.transaction():`. Proven with a new test,
  `test_replace_recipe_ingredients_db_failure_partway_through_reinsert_leaves_original_intact`
  (`tests/test_ingredients_service.py`) — forces a NOT NULL violation
  (`name=None`) on the *second* of three new rows, after the delete and
  first insert have already run, and asserts the original single
  ingredient is still there afterward, not an empty or partial set. This
  is a different failure mode than the existing
  `test_replace_recipe_ingredients_invalid_row_leaves_existing_rows_untouched`
  test, which only exercises `_validate_store_category`'s Python-level
  check — that check runs *before* any `conn.execute()` call, so it can
  never have proven the DB-level sequence itself was atomic.
- **`services/plan_generation.py: generate_week_plan`** — the
  `week_plans` insert followed by 7 `plan_days` inserts. Under the old
  `sqlite3` code this was already one implicit transaction (no
  `conn.commit()` between the two kinds of insert); under `autocommit=True`
  it wasn't, so a failure partway through the week could leave an orphan
  `week_plans` row with only some of its days. Wrapped in
  `with conn.transaction():`. Proven with a new test,
  `test_generate_week_plan_failure_partway_through_leaves_no_partial_plan`
  (`tests/test_plan_generation_service.py`) — monkeypatches
  `current_season` to raise on the 4th call and asserts `week_plans`' and
  `plan_days`' row counts are unchanged afterward.
- **`services/cook_history.py`** — audited and found to need no change.
  `mark_day_cooked` is a single `INSERT` (the two prior checks are reads),
  so there's nothing to wrap. `finalize_plan` loops calling
  `mark_day_cooked` once per day, but `mark_day_cooked` already committed
  internally after its own `INSERT` under the *old* `sqlite3` code too —
  `finalize_plan`'s loop was never one atomic unit in either version, so
  `autocommit=True` changes nothing here. (It's also self-healing either
  way: `mark_day_cooked` is idempotent per plan day, so a `finalize_plan`
  call that fails partway through just leaves the remaining days to be
  picked up by calling it again — not a partial-write bug, unlike the two
  cases above where a partial write is actively wrong.)
- **`services/recipes.py` was not in scope for this audit** (not asked,
  and already checked while porting it): every write is a single
  statement per call, including `seed_quick_fallback_recipes`'s loop over
  `create_recipe` — which, like `finalize_plan` above, already committed
  per-recipe under the old `sqlite3` code too, so there's no behavior
  change to fix.

## 2026-09-01 — Milestone 13 Phase 3: R2 photo storage

Implementing this surfaced two things worth recording before the design
itself: the Milestone 13 architecture entry's claim that
"`services/photos.py` keeps its swappable local/hosted backend design"
was describing a design that didn't actually exist in the code yet —
`services/photos.py` was local-filesystem-only, no swappable anything.
This phase is what builds that design, not something that already existed
to be extended. Separately, `docs/SETUP.md`'s `[r2]` secrets example
(added ahead of implementation, during the Phase 1 docs round) used
`access_key_id`/`secret_access_key` — checked directly against `boto3`
while implementing this phase and confirmed wrong: `boto3.client("s3",
...)` expects `aws_access_key_id`/`aws_secret_access_key`. Fixed in both
places that example appears.

**Design: local storage becomes a persistent cache that R2 syncs
to/through, not a separate code path.** Every existing call site
(`pages/1_Recipes.py`, `3_Recipe_Detail.py`, `5_Week_Plan.py`,
`8_Cook_Mode.py`, `2_Add_Edit_Recipe.py`) does
`str(photos.resolve_photo_path(...))` and passes that straight to
`st.image()` — i.e. every caller already assumes `resolve_photo_path()`
returns a local file. An R2-only design (photos living *only* in R2, no
local copy) would have broken every one of those call sites — they'd need
a URL or bytes, not a local `Path` — directly contradicting this phase's
"nothing outside `services/photos.py`... should need to change" scope.
Resolution: `save_recipe_photo()` and `delete_recipe_photo()` always
write/remove the local file exactly as before, and — only when R2 is
configured — also sync that same write/delete to R2.
`resolve_photo_path()` and `photo_exists()` check the local cache first;
only on a cache miss, and only if R2 is configured, do they fall back to
R2 (downloading into the cache, or a `head_object` existence check,
respectively). Every function's return type and contract is unchanged,
so no page needed touching — the scope-boundary conflict resolved by
design rather than by escalating, unlike Phase 1's placeholder-syntax
conflict which genuinely couldn't be resolved without widening scope.

**Backend selection: `st.secrets["r2"]` presence, not a separate env var
like `AI_ASSIST_BACKEND`.** The task asked to follow whatever pattern
backend selection "actually works today" rather than invent a new one —
`services/photos.py` had none, so the candidates were this codebase's two
existing precedents: `AI_ASSIST_BACKEND` (an explicit `os.environ` toggle
the operator sets deliberately, chosen specifically so a stray API key
lying around doesn't silently redirect traffic to a cloud service — see
the AI Assist implementation entries above) and Gemini's `is_available()`
(auto-detects from whether a key is configured, no separate toggle at
all). R2 vs. local storage matches the second shape, not the first: this
Milestone 13 architecture entry already frames it as "local filesystem
for the local-Postgres-backed dev environment... unchanged; R2 for
production" — a fully environment-determined choice, not a deliberate
per-developer preference switch the way Ollama-vs-Gemini genuinely is.
Auto-detecting from secret presence also means zero new configuration
surface: local dev has no `[r2]` section and never touches R2 at all
(same "local dev never touches the hosted resource" shape as Phase 1's
Postgres), and the deployed app's Streamlit Cloud secrets manager having
an `[r2]` section is what turns R2 on there — no separate flag to keep in
sync with whether the credentials actually exist.

**Failure handling: every R2 call is caught and swallowed, never
raised** — confirmed necessary, not just assumed, by reading
`pages/2_Add_Edit_Recipe.py`'s actual save flow: it already wraps
`save_recipe_photo()` in `try/except Exception`, showing "Recipe saved,
but that photo couldn't be processed — try a different image." if it
raises. If an R2-only failure (upload succeeds locally, R2 sync fails)
raised through `save_recipe_photo()`, that page would show this
misleading message for a photo that *was* processed fine — and worse,
since the exception would happen after the local file write but before
the function returns its relative path, `update_recipe(...,
photo_path=relative_path)` on the next line would never run, leaving a
correctly-saved local file that the database never points to. So R2
failures are caught inside each `_upload_to_r2`/`_download_from_r2`/
`_delete_from_r2`/`_r2_object_exists` helper and logged, never
propagated — the local filesystem result is always what the function's
success/failure reflects. This is the same "must still run with
local-only photo storage if R2 isn't configured" principle from the task,
extended to "...or if R2 is configured but failing," which turned out to
be the same code path either way given the caching design above.

**Known accepted gap, not hardened against:** if `photo_exists()` reports
True via a live R2 `head_object` check (no local cache) and the
*following* `resolve_photo_path()` download then fails (a transient
network blip between the two calls), `st.image()` will be asked to
render a path that doesn't exist and will raise. Narrow — only possible
when R2 is configured (production) and only in the gap between two calls
within one page render — and not hardened against, per
`docs/AGENT_INSTRUCTIONS.md` §7 (simplicity over completeness): the
primary case ("R2 not configured or fully unreachable") is fully covered
by the caching design; this residual case would need pre-emptively
downloading on every `photo_exists()` call (extra R2 traffic on every
page render, for every photo, to close a transient-timing edge case) and
didn't seem worth it for a household app's scale.

**Testing: `moto`, with the mocked client built without a custom
`endpoint_url`.** No visibility into home-inventory's own test suite in
this environment (same limitation noted in the Phase 1 entry for its
implementation code), so this follows `moto`'s own documented usage
directly. Confirmed empirically that `moto`'s request interception
doesn't cover a custom (non-AWS) `endpoint_url` — pointing `boto3.client`
at a fake `*.r2.cloudflarestorage.com` host under `mock_aws()` still
attempted a real network connection and failed with an SSL handshake
error, rather than being intercepted. Since `endpoint_url` is boto3/
botocore's own well-tested plumbing, not app logic worth testing here,
tests swap in a `moto`-backed client via `monkeypatch.setattr(photos,
"_r2_client", ...)` built with only `region_name` set — this still
exercises the real `put_object`/`get_object`/`delete_object`/
`head_object` calls and real botocore exceptions, just without the
endpoint-override detail. Graceful-degradation tests use a second fixture
that makes `_r2_client()` raise directly, simulating unreachable/
misconfigured R2 distinctly from R2 simply not being configured at all
(which the rest of the existing 13 local-only tests already cover, since
this repo's real `.streamlit/secrets.toml` has no `[r2]` section — they
run with zero R2-related monkeypatching).
