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

## 2026-09-01 — Phase 3 durability fix: distinguish a failed R2 backup from a failed local save

The Phase 3 entry above swallows every R2 failure from `save_recipe_photo`
the same way it swallows read/delete failures — reasoned by analogy to
home-inventory, where local storage is presumably the durable copy and R2
sync is a pure bonus. That analogy doesn't hold for *this* app's actual
deployment: Streamlit Community Cloud's local disk does not survive a
container restart/redeploy, so once deployed, **R2 is the only durable
copy**, not a bonus. Swallowing a failed R2 sync identically to a
successful one meant a photo could show as saved, work fine for the rest
of that session, and then be silently gone forever the next time the
container restarts — with nothing telling the household it happened.
Local *read/delete* failures degrading silently is still correct (see the
entry above: those already fall back to "acts like local-only," which is
the right behavior whether R2 is unreachable or never configured) — it's
specifically the *write* path where a swallowed failure quietly loses
data instead of just degrading gracefully.

**Fix: `save_recipe_photo` now raises `services.photos.PhotoBackupError`
when the local save succeeds but the R2 sync fails**, instead of
swallowing it like every other R2 failure in this module. It's a
narrow, deliberate exception to this module's own "R2 failures never
raise" rule, made because this is the one path where silence is actively
harmful rather than merely a degraded experience. The exception carries
`.relative_path` — the local save already succeeded and is real and
usable, so the caller still needs that value to record in
`recipes.photo_path`, same as the success path. `pages/2_Add_Edit_Recipe.py`
catches it ahead of the pre-existing generic `except Exception:` and shows
a distinguishable message ("...couldn't be backed up to cloud storage —
it may not survive a restart...") instead of the Milestone-11 "...couldn't
be processed..." message, which would have been actively misleading here
(the photo *was* processed fine — only the backup failed) and would have
lost the `photo_path` update entirely, since the original code never
reached `update_recipe(..., photo_path=relative_path)` when
`save_recipe_photo` raised for any reason. A pure local processing
failure (unreadable upload) is unaffected — still any other exception,
still the original message, still non-blocking, per the explicit
instruction that this part was already correct.

**Scope: a distinguishable warning, not a retry queue.** A background
retry mechanism (keep retrying the R2 sync until it succeeds, independent
of the user's session) would close the gap more completely — right now,
if the household doesn't notice the warning or doesn't act on it before
the container restarts, the photo is still lost. Chose not to build one
this round: this app has no existing background-job/scheduler
infrastructure to hang it off (Streamlit's execution model is
request/rerun-driven, not a long-running process with a task queue), and
adding one is a meaningfully bigger lift — new infrastructure, not a
targeted fix — for a household app whose own product principles
(`docs/PRODUCT_SPEC.md` §2) call for staying small. A distinguishable,
actionable warning ("try saving it again later") gives the household a
real chance to notice and manually retry, which is a large improvement
over total silence for comparatively little code. If this turns out to
be insufficient in practice (households not noticing/acting on the
warning), a retry queue is the natural next step — revisit then, not
speculatively now.

## 2026-09-02 — Add Recipe photo-import: two bugs found, not one

Investigated a reported bug ("uploading a photo to auto-fill the form
says 'Paste a recipe URL or some recipe text first'") before changing
anything. Turned out to be two independent, unrelated bugs stacked on top
of each other — fixing only the first would have left photo import still
completely non-functional.

**Bug 1 — button routing.** `pages/2_Add_Edit_Recipe.py`'s "Import"
button only ever reads the text/URL field (`import_input`); the photo
uploader and its own "Extract from Photo" button live in a separate `if
ai_assist.is_photo_import_available():` block below, with no shared
state check between them. A user who uploads a photo and clicks "Import"
(the first, more prominent button) gets the text-only error, even though
their photo uploaded successfully and is still sitting in the widget
afterward. Reproduced exactly via `AppTest` before touching any code.
Fixed by making "Import"'s empty-text branch check
`st.session_state.get("ai_import_photo")` (the photo uploader was given
an explicit key for this) and pointing the user at "Extract from Photo"
instead, when a photo is present — confirmed empirically first that a
keyed widget's value is available in `session_state` even before that
widget's own `st.file_uploader(...)` line executes later in the same
script run (Streamlit rehydrates widget state before user code runs each
rerun). Kept as two separate buttons rather than merging them, matching
this app's existing pattern of small, single-purpose actions elsewhere.

**Bug 2 — `GEMINI_MODEL`'s default had gone stale.** Even after fixing
bug 1 and clicking the *correct* "Extract from Photo" button, every
attempt failed (silently, since `ai_assist._call_gemini()` deliberately
catches every exception and returns `None` — see the AI Assist entries
above). Traced past the generic "returns None" to the actual network
call: `GEMINI_MODEL`'s default, `"gemini-2.0-flash"`, no longer exists —
confirmed directly against the real configured key
(`generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent`
→ HTTP 404), while `gemini-flash-latest` against the same key and same
prompt succeeds. This is exactly the staleness the Milestone 10
implementation entry above already anticipated ("Google's model lineup
moves faster than this file will be revisited") — it has now happened.
Since photo import always uses Gemini regardless of `AI_ASSIST_BACKEND`
(no local-model fallback exists for vision), this was a complete, silent
failure of photo import for every user, not an edge case — text import
wasn't hitting it in this environment only because `AI_ASSIST_BACKEND`
defaults to `ollama`, which the deployed app won't have as an option.
Fixed by changing the default to `gemini-flash-latest` — a `-latest`
alias rather than pinning to a dated snapshot name, on the theory that an
alias is more resistant to this exact failure recurring (notably,
`gemini-2.5-flash` — a model the API's own `models.list` endpoint
currently reports as available — *also* 404'd against the same key,
which a pinned snapshot name would not have protected against either).
Grepped the codebase for any other hardcoded Gemini model name before
fixing: none found — both the text-generation path (`_generate`) and the
photo path (`import_recipe_from_photo`) already read the same single
`GEMINI_MODEL` module constant, so this was one fix, not two.

**UX — the two upload widgets looked identical.** The AI-import photo
uploader (analyzed once, discarded) and the recipe's own display-photo
uploader (saved, shown everywhere) had no visual distinction: same widget
chrome, same default file-size/type caption, near-identical wording, ~40
lines apart. This is very plausibly *why* the button-routing confusion
above happens in the first place — a user has no visual cue that these
are two unrelated actions. Fixed with labeling/caption changes only, not
a layout redesign: the AI-import uploader's label now states the outcome
("📋 Or upload a photo to auto-fill this form (AI)") rather than just
restating "a photo of a recipe" (which reads identically in purpose to
the other widget), plus a one-line caption under it ("Used once to
pre-fill the fields below, then discarded — not saved as the recipe's
photo."); the display-photo uploader got a matching but distinct icon
(🖼️) for contrast; and a `st.divider()` now sits between the whole
"Import a recipe" expander and the "## Photo" section, reinforcing that
everything above the line is a one-time drafting aid and everything below
it is the recipe's permanent data.

**Test coverage — `tests/test_recipe_photo_import_ui.py` (new).** Proves
both bugs stay fixed at the UI level, not just "some function returns the
right value in the abstract": (1) uploading a photo then clicking
"Import" now shows the new, correct message, and the untouched case (no
photo, no text) still shows the original message unchanged; (2) clicking
"Extract from Photo" with `urllib.request.urlopen` mocked to raise the
*exact* `HTTPError(..., 404, ...)` shape the dead model name actually
produced degrades to the existing graceful message rather than crashing
— mocking a bare `_call_gemini` return of `None` (as the pre-existing
service-level tests in `tests/test_ai_assist_service.py` already do)
would have passed even before bug 2 was ever found, since it never
exercises the real HTTP-error path at all.

## 2026-09-02 — Deterministic bilingual first pass for categorization and quantity/unit, plus the AI-categorization resilience fix

Two related changes, implemented together: a local, keyword-based first
pass that runs before any AI call (so most ingredients never need one at
all), and the fix for the AI fallback's own slowness for whatever's left
(the `gemini-flash-latest` overload/timeout/rate-limit findings from the
prior investigation — see the "3+ minutes, every row landed on other"
report this entry's fix responds to; that investigation wasn't itself
committed as a DECISIONS.md entry since it ended in "report, don't
implement yet").

**Categorization: `services/categorization.py`, a new pure module —
`suggest_category(name)`, bilingual keyword/substring lookup, no network,
no model.** Wired into `pages/2_Add_Edit_Recipe.py`'s
`_apply_import_draft()` as the first pass on every imported row (all
three import paths: URL structured data, AI text fallback, AI photo
import all flow through this one function); the existing manual "🤖
Auto-categorize ingredients" button already only touches rows still
`"other"` (see the categorization-UI entry above), so this shrinks that
button's own workload for free — no change needed there beyond the
resilience fix below. Substring matching, not whole-word: Norwegian
compounds words with no separator (`kyllingfilet`, `gulost`), so a
`\b`-bounded word match would miss most real Norwegian ingredient lines.

**Two real bugs found by testing against real sample recipes (not
assumed):**
1. **Cross-keyword collisions from substring matching itself** — `"garlic,
   minced"` matched `meat` (the keyword `"mince"` is a substring of
   `"minced"`), `"1 tsp cornstarch"` matched `produce` (`"corn"` is a
   substring of `"cornstarch"`), `"3 dl fiskekraft"` (fish stock) matched
   `meat` (`"fisk"` is a substring). Fixed by scoring every keyword match
   by length and keeping the *longest*, not the first category checked —
   `"cornstarch"` (an explicit pantry keyword) and `"fiskekraft"` (added
   explicitly to pantry) now correctly beat the shorter `"corn"`/`"fisk"`
   they contain. `"frozen"`/`"frossen"` is checked as a separate,
   unconditional override *before* that length comparison, not folded
   into it — it names a store aisle, not an ingredient type, and
   `"chicken"` (7 chars) being longer than `"frozen"` (6 chars) would
   otherwise make `"frozen chicken breast"` lose to `meat`, which is
   backwards for what this category is for.
2. **A dangerously generic keyword**: Norwegian `"and"` (duck) is also
   the English conjunction — `"salt and pepper"` matched `meat` before
   this was caught. Removed in favor of `"andebryst"` (duck breast, the
   actual common form), same fix-by-specificity as bug 1's collisions.

**Quantity/unit: `split_quantity_unit()` in `services/recipe_import.py`,
plain regex, wired into `_coerce_ingredients()`.** This **reverses** the
"Milestone 10 implementation choices" entry above ("`recipeIngredient`
lines are stored whole, not split into name/quantity/unit... exactly the
kind of per-site/per-phrasing parsing logic a scraping library would
bundle") — but narrowly: a leading `quantity[space]unit` prefix
(`"350g block firm tofu..."`, `"2 ss olivenolje"`) is a generic, regular
pattern across sites and languages, not the per-site
DOM-shape/phrasing-heuristic logic that reasoning was actually about, so
implementing it doesn't take on what that entry deliberately avoided.
Handles, in one regex: plain integers; dot decimals (`1.5`) and Norwegian
comma decimals (`1,5`); plain fractions (`1/2`) and mixed numbers (`1
1/2`); unicode fraction glyphs both bare (`½`) and glued to a leading
integer (`1½`); and a shared English+Norwegian unit list (`g`/`kg`/`ml`/
`l` are the same in both; `ss`/`ts`/`dl`/`stk`/`fedd`/`boks` are
Norwegian-specific, alongside `tbsp`/`tsp`/`cup`/`clove`/`can`/etc.). A
quantity with no recognized unit word still splits off (`"2 onions"` →
quantity `2.0`, unit `None`) rather than requiring both — strictly more
useful than leaving it as one opaque string. Anything that doesn't match
a leading quantity at all falls back to today's existing behavior
unchanged: the whole line as `name`, `quantity`/`unit` both `None`.

**Real coverage, measured against 10 sample recipes (5 English, 5
Norwegian; representative dishes — chicken curry, tomato soup, a tofu
stir-fry, pancakes, tacos; fiskesuppe, kjøttboller, kyllinggryte,
pannekaker, laks i ovn — written to be realistic, not fetched from a live
URL), 73 ingredient lines total:**
- Categorization: **73/73 (100%)** on this sample set. A separate
  stress test against less-common ingredients not tuned for in the
  keyword lists (galangal, kaffir lime leaves, star anise; valnøtter,
  sitrongress) — deliberately run to check this isn't just circular
  (the keyword lists and the test recipes were both written by the same
  pass) — came back **4/7 (57%) English, 5/6 (83%) Norwegian**, which is
  the honest, representative number for ingredients outside common
  everyday cooking. The gap is exactly what the AI fallback below exists
  to cover.
- Quantity extracted (with or without a recognized unit): **68/73
  (93.2%)** — 35/37 English, 33/36 Norwegian.
- Quantity **and** a recognized unit: **52/73 (71.2%)** — 28/37 English,
  24/36 Norwegian. The gap from the line above is mostly bare-count
  ingredients with no unit at all ("1 onion", "3 egg") — correctly
  `unit: None`, not a miss.
- **Known, accepted gap, not fixed**: canned/tinned ingredients where
  "canned"-ness is conveyed only by the *unit* (Norwegian `"boks"` =
  can) and not repeated in the remaining ingredient text —
  `"1 boks hakkede tomater"` (canned chopped tomatoes) categorizes as
  `produce` (via `"tomat"`) rather than `pantry`, because
  `suggest_category()` only ever sees the `name` field, never `unit`.
  Not worth wiring unit-awareness into the categorizer for this one case
  — a first pass is allowed to be imperfect; this is exactly what the AI
  fallback and manual override both exist for.

**AI-categorization resilience (`services/ai_assist.py`,
`pages/2_Add_Edit_Recipe.py`) — implementing the prior investigation's
proposed fix now that far fewer calls reach this path at all:**
1. `suggest_store_category()` now passes a separate, short
   `_CATEGORY_SUGGESTION_TIMEOUT = 6.0` into `_generate()`, instead of
   inheriting the full `_GENERATE_TIMEOUT = 30.0` meant for recipe
   import. This is the direct fix for the investigation's finding: 5 of 6
   real calls to `gemini-flash-latest` hung to the full 30s timeout, one
   more took 17s before a 503 "high demand" — a best-effort, skippable
   suggestion shouldn't cost that.
2. The bulk "🤖 Auto-categorize ingredients" button
   (`pages/2_Add_Edit_Recipe.py`) now runs its remaining `"other"` rows'
   suggestions through a `concurrent.futures.ThreadPoolExecutor(max_workers=4)`
   instead of one-by-one — these are independent, I/O-bound HTTP calls
   (the GIL releases during `urlopen`), so a batch's wall time becomes
   roughly the slowest single call rather than their sum. Row mutation
   only happens on the main thread, after each future resolves via
   `as_completed()` — never from inside a worker thread — so this adds no
   `session_state` thread-safety surface.
3. `GEMINI_MODEL`'s default changed to `gemini-flash-lite-latest`,
   which the investigation measured as fast (under 1s) and correct
   against the real API when `gemini-flash-latest` was hanging/
   overloaded/rate-limited. Lower priority than 1/2, since Part A already
   means far fewer calls ever reach this path — but still worth doing.
   Flagged, same as the `gemini-flash-latest` fix before it: a `-latest`
   alias is Google's current routing decision, not a permanent
   guarantee, and this can go stale the same way again.

**Verification:** `pytest` full suite, 3 consecutive runs, **269/269
passed each time** — confirmed up from a true baseline of **248/248**
(checked via `git stash -u`, which stashes untracked files too; a first
attempt without `-u` left the new, untracked
`tests/test_categorization_service.py` sitting on disk during the
"baseline" run and silently inflated it — caught and corrected before
this entry was written, not left as a wrong number). 21 net new tests: 7
in `tests/test_categorization_service.py`, 12 new `split_quantity_unit`
cases in `tests/test_recipe_import_service.py`, 2 in
`tests/test_ai_assist_service.py` for the timeout/model changes (2
existing `test_recipe_import_service.py` assertions were also updated in
place to match the new non-`None` quantity/unit output — modified, not
counted as additions). The coverage numbers above are real measured
output from a throwaway script run against `services/categorization.py`
and `services/recipe_import.py` directly, not estimates.

## 2026-09-02 — Multi-photo import (front/back of a recipe card)

Follows up the photo-import investigation above: once the real deployed
photo (a genuine Pixel 9 JPEG, committed to `tmp/` for testing) was
confirmed working end-to-end, the next real need is a card with content
on both sides. Investigated and confirmed before implementing, per this
project's practice of not assuming API/framework behavior.

**Single call with multiple `inline_data` parts, not one call per photo
— confirmed against the real API, not assumed.** Sent two distinct real
images as separate `inline_data` entries in one `contents` block: `200
OK`, valid parsed response, `7.12s`. `_call_gemini()` already takes an
arbitrary `parts: list[dict]`, so this needed zero changes there — only
`import_recipe_from_photos()`'s part-building grows the list. Rejected
two-calls-plus-merge: it would mean designing conflict resolution for
two independently-generated ingredient lists/instructions that might
disagree, for no benefit for a single-recipe multi-photo case.

**`import_recipe_from_photos(images: list[tuple[bytes, str]])` is the
real implementation; `import_recipe_from_photo()` is now a one-line
wrapper** (`import_recipe_from_photos([(image_bytes, mime_type)])`).
Chosen over changing the existing function's signature specifically to
avoid touching its 8 existing tests — confirmed they still pass
unmodified (`69 passed` across both photo-import test files together).
Empty-bytes entries are filtered out of `images` before the
availability/network-call check, so `import_recipe_from_photo(b"")`
still short-circuits to `None` with no network call through the wrapper,
matching its pre-existing contract exactly.

**UI gotcha, found by testing not assumed: `accept_multiple_files=True`
returns `[]` when nothing is uploaded, not `None`.** Confirmed directly
via `AppTest` before touching the page. Two existing `is not None`
checks in `pages/2_Add_Edit_Recipe.py` relied on the old single-file
contract and would have silently broken: the "Extract from Photo" gate
(`if photo is not None and st.button(...)`) and the cross-widget
"photo uploaded but wrong button clicked" detector reading
`st.session_state.get("ai_import_photo")`. Both changed to plain
truthy checks, which correctly treat `[]` the same as `None` (and the
not-yet-rendered case, where `.get()` returns `None`).

**Cap: 3 photos, enforced in application code — `st.file_uploader` has
no built-in max-*count* parameter** (checked its signature directly;
only `max_upload_size`, a per-file byte limit, exists). `len(photo) > 3`
after the widget returns shows an error and hides the "Extract from
Photo" button entirely, rather than truncating to the first 3 silently.
3 is deliberately small — this is for a multi-page card/recipe, not a
bulk-import feature.

**Timing at 3-photo scale — measured against the real API, not assumed
comfortable:** 3 real-sized photos (the real Pixel 9 photo plus two
larger synthetic ones from the earlier investigation — 2.61 MB + 0.68 MB
+ 5.63 MB, **8.92 MB combined**), 3 consecutive runs against
`import_recipe_from_photos()` directly: **2.59s, 3.89s, 2.82s** — 8-12×
headroom under the existing 30s photo-import timeout. **Left the timeout
unchanged** — the 3-photo cap is doing the safety-margin work here, not
a raised timeout; there was no evidence a raise was needed.

**Existing test compatibility — verified, not assumed.** The 3 existing
`test_recipe_photo_import_ui.py` tests use `AppTest`'s
`file_uploader.upload()`, which appends to a list rather than replacing
— confirmed compatible with `accept_multiple_files=True` with zero
mechanical changes needed. One of the three did fail on first run, but
for an unrelated reason: this change also reworded the generic failure
message from "Couldn't extract a recipe from that photo" to "...from
that" (dropping the now-inaccurate singular "photo," since the message
covers 1-3 photos) — the test's exact-wording assertion was updated to
match, not the multi-file mechanics.

**Verification:** `pytest` full suite, 3 consecutive runs, **278/278
passed each time** — confirmed up from a true baseline of **269/269**
(re-verified fresh via `git stash -u` immediately before this change,
not assumed carried over from the prior entry — a first draft of this
entry claimed 288/19-new before that check was actually run against the
real baseline; caught and corrected before committing, not left wrong).
9 net new tests: 6 in `tests/test_ai_assist_service.py` for
`import_recipe_from_photos()`, 3 in `tests/test_recipe_photo_import_ui.py`
for the cap and the combined-photos flow (1 existing assertion in that
file also updated for the reworded message — modified, not counted as an
addition).

## 2026-09-02 — Milestone 14: household-size scaling — data model, rounding, and real coverage

**Override lives on `plan_days`, not `week_plans`.** Cooking for extra
people is a per-day event (hosting one evening, not the whole week), so a
single week-level override would either force-scale every day or require
a second, separate per-day exception mechanism anyway. Putting
`household_size_override` directly on `plan_days` (nullable integer,
`NULL` = "use the global default") needs no second mechanism and matches
the existing per-day override precedent already on that table
(`dinner_ready_time` is "default 6pm, overridable per day" the same way).

**UI stays gated at the week level despite the override being per-day.**
The Weekly Calendar Input screen (`pages/4_Weekly_Calendar.py`) asks one
yes/no question after the existing per-day rows — "Are there any days
this week you're hosting or cooking for more than your normal
household?" — defaulting to "No," which shows nothing further. Only
"Yes" reveals a multiselect of the week's days and a size input per day
selected, reusing the same `st.columns` row layout the busy/dinner-time
loop above it already uses. Deselecting a day (or flipping back to "No")
clears its override by simply not including it when the day list is
rebuilt from scratch each render — no separate "clear" bookkeeping. This
keeps the common case (no extra guests) visually identical to before the
milestone, at the cost of one extra click to reach the override UI on the
weeks that need it.

**`app_settings` is a single-row table, not key/value.** Mirrors
`database.py`'s existing `schema_version` one-row pattern instead of
introducing a new generic-settings-table idiom. Holds only
`default_household_size` — no other settings were added speculatively
(`docs/AGENT_INSTRUCTIONS.md` §7); a future setting gets its own migration
when a milestone actually needs it. The row is lazily seeded on first
read (`services/settings.get_default_household_size()`) rather than by a
migration-time INSERT, so the migration itself (`database.py` version 6)
stays a bare `CREATE TABLE IF NOT EXISTS`, consistent with every other
migration block in that file.

**Real coverage, from real imported recipes — not fabricated, not
assumed.** Direct network access to most recipe sites from this
devcontainer is blocked (`allrecipes.com`, `simplyrecipes.com` etc. all
returned `HTTP 402` from the sandbox's egress proxy) — `bbcgoodfood.com`
worked. Imported 8 real recipes through the actual pipeline
`pages/2_Add_Edit_Recipe.py` uses on Save (`recipe_import.parse_recipe_url()`
→ per-ingredient `categorization.suggest_category()` → `create_recipe()` +
`replace_recipe_ingredients()`, run as a one-off script against the real
`public` schema, not a test schema) — chicken curry, chicken fajitas, beef
stroganoff, shepherd's pie, classic lasagne, Thai green curry, mushroom
risotto, creamy mushroom pasta. Result: **105 ingredient rows, 99 (94.3%)
with a usable quantity, 6 (5.7%) without** — all 6 genuine
quantity-less garnish/seasoning lines the parser correctly declines to
guess a number for: "thumb-sized piece of ginger grated," "small pack
coriander finely chopped," "large splash Worcestershire sauce," "large
handful basil leaves torn (optional)," "handful parsley leaves, chopped,"
and the serving suggestion "naan breads or cooked basmati rice, to
serve." These are exactly the rows the grocery list now flags as "not
scaled" instead of silently showing a blank amount.

**`build_grocery_list()`'s aggregation logic itself needed no change to
handle scaled quantities correctly — confirmed, not assumed.** Its
name/unit grouping key is identity-based (case/whitespace-normalized name
+ unit + store category), entirely independent of the quantity value, so
decimal scaled quantities sum into the right bucket exactly like the
clean integers it was already tested against. Verified directly: built a
week plan reusing four of the real imported recipes' actual "olive oil,
tbsp" lines, scaled per-day by four different household-size ratios
(6/4, 4/6, 4/4, 5/4) the way the new code does, and ran the real
`build_grocery_list()` against it — the four lines correctly merged into
one `olive oil` entry.

What *did* need fixing: without rounding, `1.0 * (4/6)` and similar
non-terminating ratios propagate their full floating-point tail into the
aggregated total — the same test produced `6.6666667 tbsp` before
rounding was added, which would read as broken to a user. Fixed by
rounding to 2 decimal places in two places, not one: once when a day's
scaled quantity is computed (`round(ingredient.quantity * scale_factor,
2)`), and again on the running aggregate after each addition
(`round(entry["quantity"] + scaled_quantity, 2)`) — belt-and-suspenders,
since summing several already-rounded 2-decimal floats can itself
reintroduce a binary-float tail (e.g. some `0.1 + 0.2`-shaped case) that
rounding only the per-day contribution wouldn't catch. With both in
place, the same four-recipe scenario above produces a clean `6.67 tbsp`.

**Verification:** `pytest` full suite, 3 consecutive runs, **298/298
passed each time** — up from a pre-milestone baseline of **278/278**
(re-verified directly via `git stash -u` immediately before this entry,
not assumed). 20 net new tests: 6 in `tests/test_settings_service.py`, 6
in `tests/test_grocery_list_service.py`, 6 in the new
`tests/test_household_scaling_ui.py`, 1 each in `test_calendar_service.py`
and `test_plan_generation_service.py`.

## 2026-09-02 — `requirements.txt` gains real version pins, after a deployed `AttributeError` that wasn't actually a git-sync problem

Follow-up to the multi-photo photo-import investigation: a real crash on
the deployed app (`AttributeError: module 'services.ai_assist' has no
attribute 'import_recipe_from_photos'`, at what the deployed app reported
as `pages/2_Add_Edit_Recipe.py:189`) looked at first like the same
git-sync staleness this project has hit repeatedly (see the "Add files
via upload" merge entries above). **Checked directly, not assumed this
time — it wasn't that.** `git fetch origin` + `git log
origin/main..main` and `git log main..origin/main` both came back empty:
local `main` and `origin/main` were already identical, both at `5da40bc`
(confirmed further via `git rev-parse main origin/main` — same hash,
`5da40bc...`), and `import_recipe_from_photos` is genuinely present in
that committed tree (`git show HEAD:services/ai_assist.py`, line 346).
**There was nothing to push.** The mismatch was between origin/main and
whatever Streamlit Cloud's running container actually has — a redeploy/
rebuild staleness on Streamlit Cloud's own side, not a local-vs-remote
git problem, and not something `git push` can fix. Only the "Manage app"
dashboard (reboot/redeploy) can resolve that half; it's outside anything
this session can do directly.

**Real, fixable gap found along the way: `requirements.txt` pinned
nothing.** `streamlit`, `pytest`, `Pillow`, `psycopg[binary]`, `boto3`,
and `moto` were all bare package names — a `pip install -r
requirements.txt` on a Streamlit Cloud rebuild could silently resolve
different versions than whatever's been tested against locally. Fixed by
pinning to what's actually confirmed working here:

```
streamlit==1.62.0
pytest
Pillow==12.3.0
psycopg[binary]==3.3.5
boto3==1.43.85
moto
```

**Not every package pinned — `pytest` and `moto` deliberately left loose,
confirmed by checking, not assumed.** `grep`ing the whole codebase for
`import pytest`/`import moto`/`from moto`/`from pytest` outside `tests/`
turned up nothing — neither is ever imported by `app.py`, any `pages/*.py`,
or any `services/*.py`. They only run during `pytest` itself, never as
part of serving the deployed app, so a version drift in either can't
reproduce the "works locally, breaks on Cloud" failure mode this fix is
for — pinning them would add version-bump maintenance burden for a risk
that doesn't apply to them. `streamlit`, `Pillow`, `psycopg[binary]`, and
`boto3` are all genuinely imported by app-facing code and run inside the
deployed app itself, so those four are pinned exactly.

**Verification:** `pip install -r requirements.txt` against the pinned
file resolved cleanly with no conflicts (`Requirement already satisfied`
for every package, at exactly the pinned versions). `pytest` full suite,
3 consecutive runs, **298/298 passed each time**.

## 2026-09-02 — Cook Mode secondary split: sentence-packing above a 180-char proxy threshold

Investigated the reported step-density problem before changing anything:
sampled the 11 real recipes in the dev DB (51 newline-derived "steps"
total) and found 57% of them were multi-sentence paragraphs (up to 471
chars / 91 words), confirming the complaint was real, not anecdotal.

**`services/cook_mode.py` now further splits a newline-derived step at
sentence boundaries when it exceeds `SPLIT_THRESHOLD_CHARS` (180),
purely at render time** — `recipes.instructions` and the newline-splitting
itself (Milestone 7, recorded above) are unchanged; this only adds a
second pass over each already-split line. Sentences are greedily packed
back together up to the 180-char limit rather than shown one-per-screen,
since individual sentences in the sampled data average only ~88 chars —
one-sentence-per-screen would have produced a lot of near-empty screens.
A step that's one long sentence with no sentence boundary at all (no
`.`/`!`/`?` followed by a capital letter or `(`) is left unsplit rather
than chopped mid-sentence.

**The 180-char threshold is an estimated proxy, not a measured value —
worth revisiting once there's real usage to check it against.** No
headless browser was available in the environment this was investigated
in to literally screenshot Cook Mode against a mobile viewport, and the
app has no custom CSS anywhere (confirmed by `grep`) — Cook Mode renders
steps via plain `st.markdown("# ...")`, so the estimate leans on
Streamlit's documented default H1 styling (~2.25rem/36px, ~1.2 line
height) rather than a value extracted from this app's actual rendered
output. At that size, a ~340px-wide mobile content area (a common phone
viewport width minus Streamlit's default padding) fits roughly 15-18
characters per line; accounting for the recipe-name caption, optional
photo thumbnail, "Step X of Y" caption, and the Back/Next button row all
sharing the same screen, an estimated 6-8 lines realistically fit above
the fold — roughly 100-170 characters. 180 was picked just above that
range, and also happens to land close to this dataset's own real
single-sentence step median (~88 chars for an individual sentence),
comfortably fitting one or two related sentences per screen. If real
usage on an actual phone shows steps still don't fit (or fit with room
to spare), this number should move — it was never derived from an actual
measurement of the rendered page.

**Sentence-boundary guard is a small hardcoded abbreviation list, not a
real sentence-boundary detector** — deliberately, matching this
project's stdlib-only, small-footprint pattern used elsewhere (e.g. the
URL-import parser). A split is undone when the token right before the
period is a known short recipe-instruction abbreviation (`tbsp`, `tsp`,
`min`, `approx`, `e.g`, `dr`, etc.), verified against synthetic cases
(`"Add 2 tbsp. Butter..."` stays one sentence; `"Dr. Smith's recipe..."`
splits after the right sentence, not after "Dr."). The real 11-recipe
corpus itself contained no abbreviation-collision risks at all (confirmed
by scanning it directly) — the guard exists for recipes imported in the
future, which this app's primary growth path (URL/photo import) will
keep adding.

## 2026-09-02 — Busy-day preference strengthened toward quick-fallback recipes

Milestone 4's busy-day scoring (recorded above) weights toward lower
`cook_time_minutes` generally, "including but not exclusive to"
`is_quick_fallback` recipes — but measured against the real dev DB (11
recipes, 3 flagged quick-fallback), a busy day landed on a quick-fallback
recipe only 65.8% of the time under that formula; the other ~34% it fell
through to a 25-60 min recipe. Requested: push this much stronger, so a
busy day "essentially always" lands on quick-fallback, while still
falling back to a non-repeating low-cook-time option when a week has more
busy days than distinct quick-fallback recipes exist to cover them.

**New constant, stacked on top of the existing cook-time weighting rather
than replacing it:** `BUSY_DAY_QUICK_FALLBACK_BONUS = 7.5`, multiplied
into `score_recipe`'s weight only when `is_busy` and
`recipe.is_quick_fallback` are both true, on top of the pre-existing
`BUSY_DAY_QUICK_WEIGHT`/`BUSY_DAY_SLOW_WEIGHT` branch. Stacking (rather
than a standalone `is_quick_fallback` branch that would replace the
cook-time check) keeps the "not exclusive to quick-fallback" behavior
intact — an unflagged recipe with a genuinely low cook time still gets a
boost on a busy day, just a smaller one.

**7.5 was chosen over the other two values tested (5.0 and 10.0),
measured against the real recipe set:**

| bonus | effective multiplier for a flagged recipe | measured P(any quick-fallback chosen on a busy day) |
|---|---|---|
| 5.0 | 10x | 90.6% |
| **7.5** | **15x** | **93.5%** |
| 10.0 | 20x | 95.1% |

10.0 measured highest, but was rejected as unnecessarily aggressive for a
first tuning pass — 7.5 (93.5%) already satisfies "essentially always"
while leaving more real headroom for the rotation-avoidance and
seasonality/enjoyment tie-breaking factors to still matter day-to-day
(confirmed directly: with 7.5, a quick-fallback recipe cooked 2 days
earlier drops from the most-favored pick to well behind the other two
still-eligible quick-fallback recipes, i.e. rotation avoidance still
functions under the new weight, not swamped by it). 10.0 remains an easy
follow-up bump if 93.5% turns out not to be "essentially always" enough
in practice.

**Confirmed with the real dev-DB recipe set (11 recipes, 3 flagged
quick-fallback) that the "not enough distinct quick-fallback recipes"
scenario degrades correctly, not into a repeat or an unfilled day:**
simulated a week with 4 busy days against only 3 quick-fallback recipes,
2,000 trials — no repeat ever occurred and every day was always filled.
On the 4th busy day (quick-fallback pool almost always already exhausted
by then), the generator correctly fell through to a non-quick-fallback
recipe.

**Deferred, not forgotten — a real gap found while testing this, not
introduced by this change:** among the non-quick-fallback fallback picks
in that same simulation, the choice was nearly uniform across cook times
25-60 min (10-12% each) — a 25-minute recipe and a 60-minute recipe were
equally likely once past the existing `BUSY_DAY_QUICK_THRESHOLD_MINUTES`
(20 min) cutoff, because `BUSY_DAY_SLOW_WEIGHT` is a single flat
multiplier for everything above that threshold, with no further gradient
by actual cook time. This pre-dates this change (it's a property of the
Milestone 4 formula) and only becomes visible in the specific scenario
this request asked about — more busy days than quick-fallback recipes.
Explicitly **not addressed in this change**: the request was to
strengthen the quick-fallback preference and confirm graceful fallback,
not to redesign the cook-time gradient above the busy-day threshold.
Revisit if households actually hit this scenario often enough for the
flat 25-vs-60-min tie to matter in practice.

## 2026-09-02 — Milestone 15: Email the Weekly Plan

A manually-triggered button (not a scheduled job) that sends the current
week plan to a small, household-maintained list of recipient email
addresses. Implementation choices, on top of the investigation this
milestone was built from:

**`email_recipients` is a new table (one row per address), not a
JSON-encoded list on `app_settings`.** Every table in this schema,
without exception, uses plain scalar columns — nothing anywhere stores a
JSON blob. `app_settings` itself is documented as a single-row table for
settings that don't fit a relational shape (currently just
`default_household_size`, a lone scalar); a recipient list is the
opposite shape — naturally one independent, addable/removable row per
item, closer to `recipe_ingredients`'s reason for being kept separate
from `recipes.instructions` than to anything `app_settings` already
holds. `UNIQUE` on the `email` column makes "already added" a DB-level
`ON CONFLICT DO NOTHING`, not app-level dedup logic.

**Sending uses stdlib `smtplib` + `email.message.EmailMessage` against an
SMTP provider (e.g. Gmail with an app password), not a mail-API SDK.**
Matches the precedent already set for Ollama and Gemini (`urllib`, no new
dependency for a handful of request/response calls) rather than R2's
`boto3` exception — SMTP auth is a plain login, not request-signing, so
there's no equivalent to AWS Signature V4's genuine hand-rolling risk
that justified pulling in `boto3` for R2. Confirmed current before
relying on it (same diligence as the earlier Gemini model-name check):
`smtp.gmail.com` on port 587 (STARTTLS) or 465 (implicit TLS); a personal
Gmail account requires an app password, which itself requires 2-Step
Verification (plain-password SMTP access was retired in 2022); free-tier
limits are 500 recipients/day and 100 per single message — a weekly send
to a handful of household addresses is trivially within this.

**One SMTP message per recipient, not one message with everyone in
`To`.** Two reasons, both real: it isolates a single bad address from
sinking the whole send (see the failure-handling entry below), and it
keeps the household's recipient list from being exposed to every other
recipient in a shared header — a small privacy consideration for what
could plausibly be a list that includes extended family or a babysitter,
not just the household's own accounts.

**`[smtp]` secrets section, presence-detected via `st.secrets.get("smtp")`
— matching R2's pattern, not `AI_ASSIST_BACKEND`'s.** Same reasoning
already recorded for R2: this is an environment-determined capability
(configured in production, typically absent in local dev) rather than a
deliberate per-developer choice between equally-valid backends the way
Ollama-vs-Gemini genuinely is, so auto-detecting from secret presence
needs no separate on/off flag to keep in sync.

**Failure handling deliberately differs from both existing precedents in
this codebase — R2 photo sync's always-swallow, and
`save_recipe_photo`'s `PhotoBackupError` raise-on-specific-failure — and
it's worth naming exactly what's different about each of the three
situations, not just noting that they differ:**

- **R2 sync (always swallowed):** a background bonus riding along on an
  operation (the local photo save) that has already fully succeeded by
  the time R2 is touched. "R2 failed" and "R2 was never configured" are
  the *same* functional outcome from the caller's perspective in that
  moment — local-only is itself a fully legitimate, everyday mode, not a
  degraded one. There's nothing to tell the user because nothing about
  their action is incomplete.
- **`PhotoBackupError` (raised for this one specific failure):** the same
  R2-sync operation, but raised instead of swallowed because the *local*
  copy silently stops being reliable in the real deployment (Streamlit
  Community Cloud's disk doesn't survive a restart) — so silence here
  would let data quietly vanish later, with no signal at the moment that
  could have mattered. It's still fundamentally a single write with one
  boolean verdict (durable or not) for one file.
- **Emailing the plan (per-address success/failure reported, nothing
  swallowed, nothing single-outcome):** this button has no legitimate
  silent/degraded-but-fine mode at all — there's no local fallback for an
  email; either it left the household's outbox for a given address or it
  didn't, and unlike R2 syncing a photo, this is the sole, explicit thing
  the user just clicked and is waiting on, not a side effect of something
  else that already succeeded. It's also not a single-item operation
  the way both R2 cases are — it's an inherent fan-out over N independent
  recipients, each with its own success or failure. Collapsing that into
  one verdict would actively mislead someone: swallowing would hide a
  failing address's problem from the one person who could fix a typo;
  raising on the first failure would hide that the other addresses
  actually went out fine. Per-address reporting is a third shape, not a
  compromise between the other two — it's the correct shape specifically
  because this operation is a fan-out where R2 sync and the photo backup
  case were both single-item.

**Known unverified risk, flagged rather than assumed away — whether
Streamlit Community Cloud's outbound network actually permits SMTP on
port 587/465 at all.** Researched rather than assumed: some cloud
platforms deliberately block outbound SMTP as an anti-spam measure, and
evidence specific to Streamlit Community Cloud is genuinely mixed — some
reports of Gmail SMTP sends working from a deployed app, others of email
silently failing to arrive once deployed despite working locally and
logging no exception, in at least one case attributed to the receiving
mail server flagging the sending host rather than a confirmed outbound
port block. Neither this environment's local dev nor the mocked
`smtplib` tests below can surface a real network-level block either way
— the only way to actually confirm this is a real deployed test send
once Milestone 13's hosted deployment is live. Not treated as blocking
this milestone (the feature is fully correct and tested for local/dev
use, and mirrors this project's other optional-hosted-dependency
features in degrading to a clear on-click error rather than breaking
anything if it turns out not to work deployed) but explicitly not
verified as working in the actual target hosted environment.

## 2026-09-02 — Non-busy-day quick-fallback penalty

Companion piece to the busy-day bonus above, implemented alongside two
other related changes (ingredient scaling extended to Recipe Detail/Cook
Mode, and special-occasion recipes — see the two entries below) since the
special-occasion scaling exemption depends on the ingredient-scaling
helper existing first; this entry covers the penalty on its own.

Investigated a reported annoyance (quick-fallback recipes appearing on
non-busy days) before changing anything: `score_recipe()` never read
`is_quick_fallback` outside the `if is_busy:` block, so on a non-busy day
a quick-fallback recipe was chosen at essentially the same rate as any
other recipe of similar rating — measured against the real dev DB (11
recipes, 3 flagged), **27.8%**, matching the 27.3% uniform baseline for
3-of-11 almost exactly.

**New constant, mirroring the busy-day bonus in reverse:**
`NON_BUSY_DAY_QUICK_FALLBACK_PENALTY = 0.1`, multiplied into `score_recipe`'s
weight when `is_quick_fallback` and *not* `is_busy`. 0.1 was the middle of
three tested values (0.2 / 0.1 / 0.05 — same selection methodology as the
busy-day bonus's 5.0/7.5/10.0), bringing a single non-busy day's P(any
quick-fallback chosen) down to 3.7% from the 27.8% baseline. Twice as
strong as the existing `ROTATION_PENALTY_WEIGHT` (0.2) already in this
file — appropriate since this is more of a nuisance to actively suppress
than what rotation-avoidance addresses — but deliberately not zero, so a
quick-fallback recipe can still occasionally win on real merit (higher
enjoyment rating, seasonal match).

**Confirmed safe by construction, not just by simulation:** 8 of the dev
DB's 11 recipes are non-quick-fallback, comfortably more than the 7 a week
needs, so the existing no-repeat-within-week guarantee can never be
threatened by this penalty regardless of its strength. Verified anyway,
against the real shipped `generate_week_plan()`, 500 runs (0 busy days,
recipe set shaped like the real dev DB — 8 regular / 3 quick-fallback):
**every day always filled, no repeat ever occurred**, and quick-fallback
recipes appeared in only 38.6% of weeks (average 0.44/week), down from a
baseline where they'd appear in nearly every week (97.4%, measured during
the investigation against the same shape).

## 2026-09-02 — Ingredient scaling extended to Recipe Detail and Cook Mode

Confirmed directly: `pages/8_Cook_Mode.py` and `pages/3_Recipe_Detail.py`
both fetched ingredients via `list_ingredients()` raw, completely
independent of `services/grocery_list.py`'s household-size scaling — a
genuine scoping gap from Milestone 14, not a deliberate exclusion
(`docs/PRODUCT_SPEC.md` §11 explicitly exempts only Cook Mode's
**instruction text** from scaling, saying nothing about its separate
ingredients list).

**Shared helper in `services/settings.py`, not three separate
implementations:** `scale_ingredient_quantity()` (pure numeric scaling,
replacing what was an inline calculation in `grocery_list.py`) and
`effective_ingredient_quantity()` (the day-and-recipe-aware wrapper —
resolves override-vs-default, then the special-occasion exemption below,
then delegates to the pure scaler). All three screens — grocery list,
Cook Mode, Recipe Detail — now call `effective_ingredient_quantity()`;
`grocery_list.py`'s refactor is behavior-preserving (all 18 of its
existing tests pass unchanged).

**Day context — a real gap, not an edge case: nothing tracked "reached
from a specific day" before this.** Grepped every
`st.session_state["selected_recipe_id"] = ...` call site (5 total) —
none set any plan-day identifier. New session-state key,
`selected_plan_day_id`, set only by Week Plan's View/Cook action
handlers (the only two places a `plan_day` is actually in scope).
Recipe Detail's "Start Cooking" button needs no new code — leaving the
key untouched means it naturally forwards into Cook Mode, so the chain
Week Plan → View → Recipe Detail (scaled) → Start Cooking → Cook Mode
(scaled, same day) works for free.

**Leak-prevention: cleared, not just left unset, at every day-unaware
entry point.** `st.session_state` persists for the whole session unless
explicitly cleared, so a stale `selected_plan_day_id` from an earlier
Week-Plan-originated visit would otherwise silently leak into a later
generic-browsing visit and incorrectly scale an unrelated recipe.
`pages/1_Recipes.py`'s "View" and `pages/2_Add_Edit_Recipe.py`'s
post-save redirect — the two entry points that are always day-unaware —
now explicitly `st.session_state.pop("selected_plan_day_id", None)`
alongside setting `selected_recipe_id`. Verified end-to-end, not just
argued: `tests/test_ingredient_scaling_ui.py` drives the actual
sequence (view a day → scaled amount shown → browse generically via the
real "View" button → confirm the key is cleared → re-open the same
recipe → confirm the original, not the stale scaled, amount shows).

**Stale/mismatched pointer guard.** A `selected_plan_day_id` is only
trusted when `get_plan_day(...).recipe_id == recipe.id` — guards against
a leftover pointer to a *different* recipe (e.g. the day's recipe was
swapped in another tab) silently scaling the wrong recipe's amounts.
Falls back to the unscaled/generic view rather than guessing.

**"Not scaled" flag replicated into Cook Mode**, matching the existing
grocery-list wording (`pages/6_Grocery_List.py`) exactly — shown when an
ingredient has no quantity on the recipe at all (e.g. "salt to taste"),
not when a special-occasion recipe is deliberately left unscaled (see
the next entry) — those are different states and only the former is
actually missing information.

**`effective_ingredient_quantity()` was built special-occasion-aware from
the start**, not extended later — `recipes.is_special_occasion` (the next
entry) landed in the same change, since the scaling exemption needed
somewhere to live in this helper regardless of which piece "came first."
The column is schema-ready here; nothing yet lets a household actually
set it to `true` as a feature — see the next entry for that.

## 2026-09-02 — Special-occasion recipes

New `is_special_occasion` boolean on `recipes` (migration 9, same
`INTEGER 0/1 DEFAULT 0` shape and Add/Edit Recipe form placement as
`is_quick_fallback`).

**Hard-excluded from automatic plan generation, not just deprioritized —
a different mechanism from the quick-fallback weighting above,
deliberately.** `generate_week_plan()` filters `is_special_occasion`
recipes out of its candidate pool entirely (`recipes = [r for r in
list_recipes(conn) if not r.is_special_occasion]`), including from the
small-pool repeat-fallback path — a weighted-random *penalty* (the
quick-fallback approach) still leaves a nonzero chance of an unwanted
autopick, which is the wrong shape here: a special-occasion recipe (a
holiday roast, an elaborate anniversary dinner) being silently auto-
assigned to an ordinary Tuesday is a correctness problem for the
household, not a mild statistical nuisance to tune down — so it needed a
hard filter, not a smaller weight. Confirmed safe against the real
shipped `generate_week_plan()`, 500 runs, recipe set shaped like the real
dev DB (8 regular / 3 special-occasion): **every day always filled, no
repeat ever occurred, a special-occasion recipe was never auto-selected
— 0/500.** An all-special-occasion active pool correctly raises
`ValueError` rather than silently ignoring the flag.

**Still fully reachable via swap — confirmed, not assumed, by reading
`swap_day_recipe()` and by test.** It calls `list_recipes(conn)`
unfiltered (only `generate_week_plan()` gained the new filter) — proven
with a test that makes a special-occasion recipe the *only* other
candidate for a day and confirms swap actually lands on it, rather than
falling back to a re-pick of the currently-assigned recipe. Visual
distinction so one is easy to find while browsing to deliberately place
it: a "🎉" badge on Recipes-page cards (mirroring `is_quick_fallback`'s
existing "⚡"), and a "🎉 special occasion" badge on Recipe Detail
alongside its other badges.

**Scaling exemption, built into `effective_ingredient_quantity()` (Part
2's shared helper) rather than duplicated per screen:** if
`is_special_occasion` and the day carries no explicit
`household_size_override`, the recipe's own quantities pass through
unscaled — a special-occasion recipe's serving count was deliberately
authored for a specific event, not for routine household size, so
silently stretching or shrinking it to the app-wide default would be
wrong more often than right. An explicit override for that specific day
still takes precedence and scales normally — someone deliberately said
how many people that day is actually for, which is a stronger, more
specific signal than the recipe's own default. Silence (no override) is
read as "trust the recipe," not as "assume the app-wide default."

**Direct assignment on the Weekly Calendar screen — the primary path,
not swap.** Relying on "generate, then keep swapping until the holiday
recipe happens to come up" is a bad primary UX for something a household
already knows in advance (it's Thursday, it's Thanksgiving). Added a
third week-gated section on `pages/4_Weekly_Calendar.py`, mirroring the
household-size override's exact shape (yes/no → multiselect of days →
per-day widget, deselecting a day clears its assignment, rebuilt from
scratch every render) — "Any holiday or special-occasion days this
week?" → which day(s) → a recipe picker per day, scoped to
`list_recipes(conn, special_occasion_only=True)` (new filter, symmetric
with the existing `quick_fallback_only`). Hidden entirely (no section,
no dead-end picker) when zero `is_special_occasion` recipes exist,
matching Milestone 12's empty-state pattern. Swap remains available as
the secondary way to change your mind about a specific day afterward —
untouched, still not filtered on the flag.

**One deliberate deviation from "mirror exactly":** the household-size
picker always has a sane numeric default (`existing_override or
default_household_size`); a recipe picker has no non-arbitrary default; the
per-day `st.selectbox` includes a `None` "— choose a recipe —" placeholder
rather than silently defaulting to whichever special-occasion recipe
sorts first. A day left on the placeholder simply falls back to normal
auto-generation for that day — no validation block on Generate.

**`CalendarDay.assigned_recipe_id`, carried into `generate_week_plan()`
the same way `household_size_override` already is** (confirmed by
reading the function, not assumed from the household-size precedent
alone: `CalendarDay` objects are read field-by-field per day when
building each `plan_days` INSERT). A day with `assigned_recipe_id` set
skips `choose_recipe()` entirely — no candidate pool, no scoring, the
recipe is placed directly. If the assigned recipe is missing or has been
deactivated by generation time (a narrow race — deleted in another tab
between picking it and clicking Generate), it falls back to normal
scoring for that day rather than raising a foreign-key violation into
the user's face — matches this app's existing graceful-degradation style
(e.g. `swap_day_recipe`'s broken-filter handling).

**No new `plan_days` column for "how was this chosen."** Nothing
downstream (scaling, display, cook history) needs to know whether a
day's recipe was auto-generated, swapped, or directly assigned — matches
the existing precedent exactly: a swapped-in recipe is already
indistinguishable from an originally-generated one, no "was swapped"
flag exists either.

**No-repeat interaction — structurally impossible to violate, traced
through rather than asserted.** `recipes` (the pool `choose_recipe`
draws from) is built once, before the day loop, already excluding every
`is_special_occasion` recipe. Every assignable recipe is, by
construction (the picker only offers `is_special_occasion=True`
recipes), never a member of `recipes` in the first place — so whether or
not an assigned recipe's id gets added to `used_recipe_ids` has zero
effect on any other day's candidate pool. Chose not to add it: pre-
assignment bypasses the scoring/pool machinery entirely and never
touches `used_recipe_ids`, which is more honest about what's actually
happening than adding a no-op entry would be. Confirmed by test with 7
regular recipes (the exact minimum for a repeat-free week on their own)
plus one assigned special-occasion recipe: all 7 days filled, no repeat,
and the 6 auto-generated days draw only from the 7-recipe regular pool —
undiminished by the assignment. One further consequence, deliberately
not blocked: a household can assign the *same* special-occasion recipe
to two different days (e.g. leftovers on both Christmas and Boxing Day)
— no artificial same-week dedup applies to direct assignments, consistent
with swap already not blocking repeated manual picks either.

**Session-state persistence bug, found and fixed alongside the picker
above rather than as a separate pass — the two turned out to share a
root cause.** Investigated a report that a household-size override, once
set for a specific day, disappeared after navigating to another page and
back. Reproduced directly via `AppTest` with real `st.switch_page()`
navigation (not a hand-copied `session_state` dict between separately-
constructed `AppTest` instances — tried that first, and it made the bug
look already-fixed, since manually copying the whole dict doesn't
reproduce Streamlit's actual widget-state lifecycle across a real
multipage session; the discrepancy was the first sign the naive
approach couldn't be trusted here).

**Root cause, found by inspecting session state at each step, not
guessed.** `cal_busy_{day}`, `cal_time_{day}`, and
`default_household_size_input` all survive navigation intact.
`hosting_extra_this_week` does not — it silently resets to `"No"`.
`household_override_days` and `cal_household_size_{day}` vanish from
session state entirely. The busy/time widgets survive because their
`value=` is computed fresh from the durable `st.session_state
["weekly_calendar"]` list on every render, so even when a widget's own
prior state doesn't carry over, the freshly-created instance self-heals
from the durable source. `hosting_extra_this_week`'s `st.radio(...)` had
no computed default at all — no `index=` — so a freshly-recreated
instance falls back to Streamlit's hardcoded index 0. Since the whole
`if hosting_this_week == "Yes":` block is then skipped, the section's
own unconditional end-of-script rebuild
(`household_size_override=household_override_by_day.get(day_name)`)
overwrites the still-correct value sitting in the durable list with
`None` — not because Streamlit lost the *data*, but because the page's
own code never re-consulted the durable list once its gate defaulted
shut. Confirmed the fix directly against the same repro before proposing
it: computing the radio's `index=` and the multiselect's `default=` from
`calendar_by_day` (whether any/which days currently have an override)
makes the override survive navigation correctly.

**Scope: one shared fix, not three.** Busy/dinner-time was never
affected (unconditionally rendered, already self-healing). Household-
size override needed the fix. The special-occasion picker above — same
yes/no → multiselect → per-day-widget shape — would have had the
identical bug if built the same way as the original household-size
code; built it with the computed `index=`/`default=` pattern from the
start instead of shipping it broken and patching later. Both gated
sections now follow the same rule stated once in the page's own module
docstring: every gate's default is derived from the durable
`weekly_calendar` list, never from the gating widget's own persisted
state alone.

## 2026-09-03 — Ingredient name canonicalization for grocery-list grouping

Investigated a reported grocery-list duplication problem (e.g. "Salt",
"Salt & Pepper", "4 ts salt" all showing as separate lines) before
implementing anything, against the real dev DB (105 ingredient rows / 90
distinct raw names, real BBC Good Food-style URL imports).

**The real data inverted the expected approach.** The reported example
suggested short, clean name variants, where a synonym/alias table
(mapping known short spellings to one canonical identity) would carry
most of the coverage. The actual dev DB doesn't look like that —
`recipeIngredient` lines are stored whole (Milestone 10), so `name` is
usually near-full prose ("garlic cloves finely chopped", "large red
onion cut into thin wedges"). Measured against the real data: a
generic, bilingual descriptive-noise-word/phrase stripper (chopped,
crushed, finely, of, clove(s), large, fresh, ...), with **zero**
ingredient-specific alias-table entries, collapsed 21/90 (23.3%) of
distinct raw names into 7 shared canonical groups (garlic, onion,
parmesan, beef stock, crème fraîche, canned tomatoes, lime leaves,
parsley). The alias table — the piece expected to carry the win — wasn't
needed for a single real merge in this corpus. It still exists, seeded
sparse, because genuinely-different-word synonyms (US/UK vocabulary
differences especially) will matter more once recipes from more sources
get imported; this particular sample of UK-vocabulary imports simply
didn't happen to surface one yet.

**Rejected reusing `services/categorization.py`'s keyword dictionary for
name identity, confirmed by testing, not assumed.** Its longest-substring
match is tuned for store-aisle breadth (a generic "tomato" hit is fine
when the only question is which aisle), but tried directly as a name
canonicalizer it wrongly collapsed "tomato purée" into the same group as
canned and fresh tomatoes — three different products a shopper buys
separately, unified only because all three contain the substring
"tomato". Name-identity grouping needs to be more conservative than
aisle grouping, so `services/ingredient_canonicalization.py` is a
separate module with its own, smaller, purpose-built dictionary — noise
words to strip, plus a sparse exact-match alias table (never a substring
match, specifically to avoid reintroducing this over-merge risk).
Confirmed the conservative approach doesn't just avoid that one case but
holds generally: "cherry tomatoes", "tomato purée", and canned "tomatoes"
all stay distinct, as do olive/sunflower/vegetable oil (genuinely
different products that happen to share a word).

**Fixed the Unicode-fraction leading-junk-stripper gap found during
investigation, in this same pass rather than deferring it.** The
original numeric-prefix regex only matched ASCII digits, so
`"/3½fl oz beef stock"` stripped to `"fl oz beef stock"` instead of
`"beef stock"` — the vulgar-fraction character `½` fell outside the
digit class, and the regex only consumed one leading quantity segment,
not the two in `"/1lb 2oz fillet steak sliced"`. Extended the digit
class to recognize common vulgar-fraction characters (½¼¾⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞)
and made the leading-segment match repeat (`+`) instead of matching once.
Re-run against the real strings: `"/3½fl oz beef stock"` now merges
correctly with plain `"beef stock"`; `"/1lb 2oz fillet steak sliced"`
now produces `"fillet steak"` instead of `"oz fillet steak"`. This
improved the measured real coverage from 19/90 (21.1%, investigation-
time number) to 21/90 (23.3%) — a real, measured gain, not a cosmetic
one; `"beef stock"` became a genuinely new correctly-merged group.

**Grocery-list grouping: canonical heading, quantities re-summed (not
just clustered) per distinct unit within the group, no-quantity lines
shown inline.** `GroceryItem` changed shape — from one row per (raw name,
unit) pair to one row per canonical name, carrying a list of
`GroceryUnitLine`s (one per distinct unit actually seen, or an unscaled
line). Quantities are only ever summed within a matching unit, never
across units (e.g. "2 tbsp" is never combined with "112 ml") — the same
"don't attempt risky cross-unit conversion" boundary this module already
respected before canonicalization existed, now also enforced *within* a
merged canonical group, not just across differently-named ingredients.
`pages/6_Grocery_List.py` renders a single-line group exactly as before
this existed (no visual change for the common case); a group with more
than one line gets a heading with its lines indented underneath, instead
of those lines being scattered elsewhere in the category section.

**Norwegian coverage: structurally ready, deliberately not reported as a
real number.** The noise-word list and alias table both include a small
set of Norwegian entries (hakket, revet, skivet, "løk" → onion,
"hvitløk" → garlic, etc.), matching `categorization.py`'s bilingual
shape — but the dev DB currently has zero Norwegian-sourced recipes to
measure real coverage against. Reporting a Norwegian percentage right
now would be a fabricated number dressed up as measured; it isn't
reported here, and shouldn't be assumed accurate until real Norwegian
imports exist to test against and the entries can be grown from that,
the same way `categorization.py`'s own dictionary grew from real
testing rather than being written speculatively.

**What this still can't solve, confirmed with real examples rather than
hypothesized:** novel phrasing with no shared surviving token ("of thai
basil" vs. "large handful basil leaves torn" — both basil, don't merge);
singular/plural ("carrot" vs. "carrots" — no stemming attempted, since a
stemmer risks wrongly collapsing unrelated short words); and compound
lines naming two ingredients in one string ("salt and pepper") — not
split, none observed in the current corpus. Scope was deliberately
grouping/normalization only — not further improving quantity/unit
extraction coverage itself (a handful of remaining ugly leading-fragment
cases are really extraction artifacts, not canonicalization failures),
and not the separate "favor recipes that share ingredients across the
week" feature, which depends on this working first and is scoped
separately once real usage of this shows how well it holds up.

## 2026-09-03 — Overlap-aware plan generation

The "favor recipes that share ingredients across the week" feature
flagged above, now built on top of ingredient canonicalization.

**Why this needed a genuinely new mechanism, not another static
per-recipe weight.** Every existing factor in `score_recipe()`
(seasonality, rotation, busy-day cook-time, quick-fallback bonus/penalty,
enjoyment) is computable from a single recipe plus static, precomputed
per-recipe context (e.g. `last_cooked`) — none of them need to know what
*other* days in the same generation run already picked. Overlap-
awareness is different in kind: whether Wednesday's candidate is worth a
bonus depends on what Monday and Tuesday's *choices* actually were,
which doesn't exist until the day loop has already run partway through.
`generate_week_plan()` now precomputes
`canonical_ingredients_by_recipe: dict[int, frozenset[str]]` once up
front (same shape and cost as the existing `last_cooked_dates()`
precompute), and maintains a running `committed_canonical_ingredients`
accumulator that grows as the day loop executes — the first genuine
sequential dependency in this file, everything else stays a pure,
order-independent per-recipe weight.

**Real baseline, from investigation, not assumed:** the raw pairwise
overlap number (47.3% of recipe pairs share *something*) was misleading
— every one of those pairs shared it via garlic/onion/olive oil/butter,
which 4-7 of the 8 non-empty active recipes all contain regardless of
pairing. Excluding those, only 9/55 pairs (16.4%) share a genuinely
distinctive ingredient (parmesan, crème fraîche, beef stock, tomatoes,
tomato purée, parsley, sunflower oil). Day-level simulation (1,000
trials): baseline "distinctive overlap by chance" is already 47.5%
(unsurprising with only 8 usable recipes filling 7 slots most weeks);
`bonus=1.0` raised this to 58.3% (+10.8pp), without visibly collapsing
variety across the 8 real recipes (9-14% pick share each, vs. a flat
12.5% each at bonus=0). Higher bonus values (2.0, 4.0) pushed the rate
further (63-66%) but started measurably favoring the mutually-
overlapping cluster (lasagne/stroganoff/shepherd's pie/pasta/risotto/
curry) over the genuinely distinctive outliers (Thai green curry,
chicken fajitas, ~7% each at bonus=4.0 vs. ~12% at bonus=1.0) — bonus=1.0
was chosen as the value with real, measured lift that didn't yet show
that skew.

**`INGREDIENT_OVERLAP_BONUS = 1.0`, applied as
`weight *= (1 + bonus) ** overlap_count`** — `overlap_count` is
precomputed by `choose_recipe()` per candidate (length of the
intersection between the candidate's own canonical ingredients and the
committed set), then passed into `score_recipe()` as a plain int, same
"caller precomputes, `score_recipe` stays a pure function of its inputs"
pattern `last_cooked` already established — `score_recipe()` itself has
no DB access and no knowledge of *why* a count is what it is.

**Staple exclusion: a dynamic frequency threshold
(`STAPLE_FREQUENCY_THRESHOLD = 0.5`), not a hardcoded word list.** Any
canonical ingredient present in >= 50% of the current active candidate
pool's *non-empty* recipes (recipes with zero ingredients, e.g.
Takeout, don't inform commonality and are excluded from the denominator,
though they remain full scoring candidates as always) is excluded from
`committed_canonical_ingredients` when it's updated — never subtracted
on the candidate side, since the accumulator itself simply never
contains a staple. `_staple_canonical_ingredients()` recomputes this
fresh from `canonical_ingredients_by_recipe` every `generate_week_plan()`
call, so it naturally tracks the real pool as more recipes get added —
a hardcoded list (as tested during investigation, garlic/onion/olive
oil/butter) would need manual upkeep and would silently go stale the
moment the roster's composition shifts. Confirmed by test that this
dynamic threshold, run against the real dev-DB-shaped 8-recipe set,
lands on exactly the same four ingredients the investigation's
hardcoded proxy list used — the dynamic version isn't a behavior change
today, only a design choice that stops it from needing one later.

**Deliberately NOT applied to `swap_day_recipe()` — a scope decision, not
an oversight.** A swap is a single, isolated day change; giving it
visibility into what the rest of the week already committed to is a
real, separate design question (does a swap's replacement still need to
"fit" the week's ingredient plan, or is a swap allowed to deliberately
break overlap in favor of something else the household wants right now?)
that wasn't taken on in this pass. `choose_recipe()`'s new parameters
both default to "no bonus for anyone," so `swap_day_recipe()`'s existing
call, unchanged, behaves identically to before this feature existed —
confirmed by the full existing swap test suite passing unmodified.

**Order-dependency (Monday always 0%, Thu/Fri peak, Sunday dip) — a
known, accepted characteristic for v1, not a bug.** Confirmed by
simulation during investigation: Monday has no prior-day context by
construction (nothing to build overlap from yet), overlap climbs through
the week as the committed set grows, then drops again on the last day or
two as the no-repeat rule narrows the remaining candidates. Accepted
as-is rather than reordering generation or adding a two-pass approach —
both are real added complexity that doesn't seem justified yet against
an 8-recipe pool where the *whole* feature's measured lift is already
modest (see below). Revisit if the recipe pool grows enough that this
lopsidedness becomes a household-visible complaint rather than a
statistical curiosity.

**Honest scale assessment, carried over from investigation:** with the
current 8-usable-recipe pool, this is a real but modest improvement
(+10.8pp over a baseline that's already fairly high by chance). The
value of this feature is expected to grow as the recipe pool grows —
more recipes means more chances for genuinely distinctive overlap to
exist and for the bonus to have real signal to work with — not
something this pass oversells at the current scale.

## 2026-09-03 — Grocery-list duplication follow-up: unit normalization, noise-word additions, and two non-bugs worth recording

Investigated a report of "extensive duplication and rendering bugs" in
the deployed grocery list, against a real pasted example from that
deployed app (a larger, separately-imported recipe set this dev
environment has no direct access to — see below). Two of the four
reported symptoms were real bugs; two were not, and are recorded here so
this exact investigation doesn't get re-run from scratch if the same-
looking symptom resurfaces.

**Staleness, ruled out by output structure, not by reaching the deployed
app.** This dev environment can't reach the deployed app or its Neon
database directly. Confirmed staleness wasn't the issue anyway: the
reported output's *shape* — bold-ish headings ("Garlic", "Cooking oil")
each followed by indented per-unit sub-lines, unscaled entries shown
inline within their group — is structurally impossible to produce from
any commit before the canonicalization/grouping work landed (pre-
canonicalization code rendered one flat line per raw name+unit, no
grouping at all). The deployed app was running current-era code.

**Not a bug — "don't merge across units" working exactly as designed.**
The reported "Garlic" followed by a bare "22" with no unit turned out to
be two genuinely different units (an unspecified count and "cloves")
correctly kept as separate lines within one canonical group — exactly
the existing, already-tested behavior
(`test_build_grocery_list_merges_real_garlic_variants_into_one_group`
already asserts this). No unit was dropped anywhere: the aggregation
code only sets a group's unit field once, from whichever row created
that specific `(canonical, unit)` bucket, and a `unit=None` bucket can
only exist if real rows genuinely have no unit value. The *only* real
issue was cosmetic — a bare number with nothing else reads as broken —
fixed below (item 3), not by touching the grouping logic.

**Not a bug — a copy-paste artifact, not name concatenation.** The
reported "4 tbsp Coconut oil Cooking oil" (framed as two ingredient names
joined into one label) was, on precise re-parsing against the actual
`st.write()` call sequence in `pages/6_Grocery_List.py`, two entirely
separate, correctly-distinct canonical groups ("Coconut oil" and "Cooking
oil" — confirmed directly that `canonicalize_ingredient_name()` does not
merge them) rendered adjacently. There is no code path anywhere that
concatenates two different canonical names into one label — a group's
`name` is set once and never touched again. A browser "select all → copy"
of the rendered page reliably drops bullet/bold markers and sometimes the
visual line break between adjacent block-level elements, which is almost
certainly what produced the appearance of concatenation in the pasted
plain text. Recorded explicitly so a superficially-similar report later
isn't re-investigated as a grouping bug before checking this first.

**Real bug — unit-string variants weren't recognized as the same unit.**
Confirmed by direct code inspection (`unit_key` was a bare
`.strip().lower()` — a literal string comparison) and reproduced locally
(two recipes calling for ginger as `"2 tbsp"` and `"2 tablespoons"`
showed as two separate lines, matching the real reported `Ginger` case
exactly). `normalize_unit()` (`services/ingredient_canonicalization.py`)
maps known equivalent spellings to one canonical abbreviation
(tablespoon(s)→tbsp, teaspoon(s)→tsp, gram(s)→g, and similar) — not a
conversion table; `tbsp` and `tsp` remain permanently distinct, same
"don't attempt cross-unit conversion" boundary the grouping logic already
had for ingredient quantities. Applied both to the grouping key and to
the displayed unit, so a merged group always shows one consistent
spelling rather than whichever row happened to be seen first.

**Noise-word/phrase additions — three real, distinct gaps found in the
real pasted list, not hypothesized:**
- **`"divided"`** — `Cornstarch` (plain) and `Cornstarch divided` didn't
  merge. Direct addition, same shape as existing noise words.
- **`"to garnish"`** — `Sesame seeds to garnish` didn't merge with a
  plain "sesame seeds" line. Direct addition, same shape as the
  already-handled `"to serve"`/`"to taste"` phrases.
- **`"and"`** — `Salt and pepper` and the literal `Salt pepper` line
  (both present in the real reported list) are now recognized as the
  same canonical identity. Confirmed by test that plain `Salt` still
  stays distinct from both — a compound "salt and pepper" is genuinely a
  different shopping item from salt alone, and stripping `"and"` doesn't
  change that; it only reconciles two different *spellings* of the same
  compound.

**Explicitly not touched — leaked-field artifacts, confirmed out of
scope, not silently ignored.** `"0.5 A green pepper"` (the article "a"
apparently landed in the `unit` field), `"450 Grams firm tofu"` (a
spelled-out unit word landed in the `name` field instead of `unit`), and
`"2 Heaped tsp coriander"`/`"2 Heaped tsp turmeric"` (same pattern) are
real, observed phrasing gaps — but they're extraction bugs (the wrong
raw field holds the wrong content), not name-phrasing variety a
canonicalizer can safely reconcile. Same scope boundary as the original
canonicalization decision ("not further improving extraction coverage
itself").

**Bare/unitless quantity display fixed with an explicit placeholder, not
a data change.** `NO_VALUE_DISPLAY = "—"` in `services/grocery_list.py`,
shown for both "no unit on this line" and "not scaled" — replacing a
bare number with nothing else, and replacing the previous italic caption
text for "not scaled" with a plain cell value, since the list is now a
table (see below) rather than a bulleted list.

**Grocery list rendered as a table, not a bulleted list.** `st.dataframe`
needed zero new dependencies — pandas is already an installed transitive
dependency of Streamlit itself, and nothing in this app's own code
imports it directly, so `requirements.txt` is untouched.
`grocery_list_table_rows()` flattens `build_grocery_list()`'s
category → GroceryItem → GroceryUnitLine structure into one row per
(category, ingredient, quantity, unit) — a multi-line group repeats its
ingredient name across rows (`st.dataframe` has no cell-merging), which
is the standard, unambiguous way any real spreadsheet/table already
represents this. Sequenced after the unit-normalization and noise-word
fixes landed, not before — building a table on top of still-duplicated
data would have just made the duplication more visible in a new format
rather than fixing it.

**CSV export, not `.xlsx` — confirmed the reasoning holds, not defaulted
to `openpyxl` for its own sake.** A plain CSV already opens correctly in
Excel with zero added dependency — same "avoid a new dependency unless
there's a concrete reason" precedent as the original SQLite-file backup
decision, and the same reasoning that made `boto3` a deliberate,
justified *exception* for R2 (real request-signing risk) rather than a
default choice. This is a flat ingredient list — no multi-sheet
structure, no cell formatting, no multiple related tables — so there's
no concrete capability gap `openpyxl`/`.xlsx` would close that CSV
doesn't already cover. `grocery_list_csv()` reuses the exact same
`grocery_list_table_rows()` output the on-page table renders — one row
shape, two presentations, so they can't drift from each other. The
downloaded file is encoded `utf-8-sig` (a UTF-8 byte-order mark) rather
than plain UTF-8, specifically because the new "—" placeholder is
non-ASCII and Excel on Windows is known to misrender a BOM-less UTF-8
CSV containing non-ASCII characters as a legacy codepage instead —
confirmed this is a real, standard gotcha worth guarding against
proactively rather than shipping mojibake the first time someone opens
the download in Excel.

## 2026-09-03 — Rotation avoidance vs. overlap: multi-week stability confirmed, but not for the assumed reason

Investigated whether overlap-aware generation compounds recipe
repetition over consecutive weeks faster than rotation avoidance can
counteract — the earlier overlap investigation's numbers were single-week
snapshots with no real cook-history feedback between trials.

**Method, not just the conclusion.** 100 independent trials of 10
consecutive simulated weeks each (7,000 real day-picks), against the
real recipe pool copied faithfully into an isolated schema, with real
`cook_history` rows written via `finalize_plan()` between each simulated
week — not independent single-week draws. Confirmed a real methodology
trap before trusting any result: `generate_week_plan()`'s rotation math
uses `dt.date.today()` (real wall-clock time), not the simulated week's
date — running "consecutive" weeks without patching `today` to advance
in lockstep with the simulated calendar would have made every recorded
cook date look like it happened in the future relative to a frozen
`today`, silently invalidating the rotation comparison for the whole
run. Patched via a `datetime.date` subclass swapped in per simulated
week, confirmed the swap doesn't disturb any other real date arithmetic
in the module.

**Result: stable, no drift, no compounding — confirmed with real
numbers.** Cluster recipes (lasagne/stroganoff/shepherd's pie/pasta/
risotto/chicken curry) averaged 12.37%/recipe pick share across the full
run; the two genuinely distinctive recipes (Thai green curry, chicken
fajitas) averaged 9.07%/recipe — close to, not collapsing away from, the
12.5% neutral baseline for 1-of-8 usable recipes. Per-week-position
breakdown (week 1 through week 10) shows no trend in either direction —
the distinctive pair never dropped below 6.9% in any single week, so no
"long drought" pattern either.

**The more important finding: a counterfactual, not just an
observation.** Re-ran the identical simulation with
`ROTATION_PENALTY_WEIGHT` patched to `1.0` (rotation avoidance fully
disabled) specifically to isolate *why* it's stable, not just confirm
that it is. The numbers came back nearly identical to the rotation-
enabled run. **The stability is not primarily coming from the 21-day
rotation window** — it's a structural consequence of the no-repeat-
within-week rule combined with the current pool being barely larger than
a week (8 usable, non-quick-fallback recipes for 7 slots): almost every
recipe *must* be used almost every week just to fill the plan, which
already bounds how far the distribution can drift regardless of rotation
history.

**No fix implemented — confirmed nothing needs fixing, but recording the
corrected mechanism, not just the outcome.** The thing actually asked
about (does overlap-driven cluster dominance compound over consecutive
real weeks) genuinely doesn't happen, confirmed with real simulation
against the real pool. But recording "rotation avoidance holds up as the
escape valve" would have written an assumption into this log as a
confirmed guarantee when the counterfactual shows the escape valve
currently doing the work is pool size, not the rotation window. Same
"value grows with pool size" caveat the overlap investigation itself
already flagged, now extended to rotation avoidance specifically:
revisit this once the recipe pool grows large enough that no-repeat-
within-week stops forcing near-universal weekly coverage on its own —
that's the point at which rotation avoidance's independent contribution
(if any) would actually become visible and worth re-measuring.

## 2026-09-04 — Moved "Generate New Plan" from Week Plan to Weekly Calendar

**Confirmed prior architecture before changing anything.** The button and
its `generate_week_plan()` call lived on `pages/5_Week_Plan.py`, not
`pages/4_Weekly_Calendar.py`. The two pages were already coupled through
`st.session_state["weekly_calendar"]` — a plain `list[CalendarDay]`, not
a service call or database row (see the calendar page's own docstring:
the calendar is intentionally not database-backed). Weekly Calendar
rebuilt that list from its widgets at the end of every script run; Week
Plan only read it, seeding a default copy via `build_default_week_calendar()`
if a user reached Week Plan first without ever visiting Weekly Calendar
in that session.

**Change:** the rebuild of `st.session_state["weekly_calendar"]` moved up
to immediately follow the special-occasion section (previously it sat at
the very end of the file, after the unrelated Email recipients section),
and the "Generate New Plan" button now sits right after it, before Email
recipients. This was required, not cosmetic: the button needs the
*current* run's rebuilt list, and the per-day locals it's built from
(`busy_and_time_by_day`, `household_override_by_day`,
`assigned_recipe_by_day`) are already fresh by that point in the script,
same as they were at the old end-of-file location. On success the page
calls `st.switch_page("pages/5_Week_Plan.py")` instead of `st.rerun()`,
so the new plan is immediately visible — same pattern as Home's
"+ Add Recipe" button.

**Week Plan goes clean — no generate/regenerate affordance kept there,
and no `weekly_calendar` session-state seeding either (nothing on that
page reads it anymore, so seeding it was dead code once the button
moved).** Considered keeping a "Regenerate" button on Week Plan too, for
a quick re-roll without navigating back. Rejected: Weekly Calendar is now
the one place all of a plan's inputs (busy days, dinner times, household
size, special-occasion assignment) are entered, and a second generate
entry point on Week Plan would let someone regenerate against a calendar
they never actually looked at this session (or a stale one from earlier),
silently reintroducing the exact ambiguity a single entry point removes.
Two copies of the same action with no distinct purpose also isn't
consistent with keeping the layers simple (`docs/AGENT_INSTRUCTIONS.md`
§7) — mirrors why special-occasion assignment lives only on Weekly
Calendar, not duplicated onto Week Plan. Week Plan's empty state was
updated to point at Weekly Calendar instead of naming a button that no
longer lives there.

## 2026-09-04 — Milestone 16 Phase 2: side/dessert attach UI, staging, and a real transaction bug caught before it shipped

**Staging mechanism, confirmed against the actual code rather than
assumed.** `household_size_override` and `assigned_recipe_id` are both
staged pre-generation on `CalendarDay`/`st.session_state["weekly_calendar"]`
and only carried into real `plan_days` rows by `generate_week_plan()` —
there's no path that edits an already-generated day's household size or
special-occasion assignment directly; the only way to change either is
to regenerate. Side/dessert attachments follow the identical pattern:
two new `CalendarDay` fields, `side_recipe_ids`/`dessert_recipe_ids`
(plural lists, not a single id like `assigned_recipe_id`), staged the
same way and written into `plan_day_dishes` via a new `attach_dish()`
right after each day's `plan_days` row is inserted inside
`generate_week_plan()`'s existing transaction. This was the only option
that made sense anyway — `plan_day_dishes.plan_day_id` can't reference a
row that doesn't exist yet, so attaching before generation was never
possible.

**Two `CalendarDay` fields, not one merged list**, even though
`plan_day_dishes` itself has no `course` column (Phase 1 decision).
`plan_day_dishes` doesn't need to know which course an attachment is
(it's derived from `recipes.course` at read time), but the *staging*
structure is UI-adjacent and matches the two distinct picker sections on
Weekly Calendar — merging them would mean re-deriving "which of these
ids are sides" from a recipe lookup every time the Side dishes section
needs its own default, for no benefit since nothing downstream needed
them merged.

**Shared UI helper confirmed practical, not forced.** The Side dishes
and Dessert sections are identical in shape to each other (yes/no ->
which day(s) -> per-day picker) and close to the household-size/special-
occasion sections' shape too, differing only in: household size uses a
number input, special-occasion uses a single-select (one recipe per
day), and side/dessert use a multi-select (several dishes per day, the
one actual behavioral difference from special-occasion's picker). That
one difference is exactly why the *existing* three sections were never
factored together — but since the two *new* sections differ from each
other only in course/labels, they factor cleanly into one
`_render_dish_attachment_section()` helper without forcing anything.

**Symmetric multi-select for both, confirmed with no counterexample
found.** Multiple desserts on one day (e.g. cake and ice cream for a
dinner party) is an ordinary case with no less justification than
multiple sides — no special-casing added.

**A real bug caught by testing rather than assumed away: `conn.commit()`
inside `conn.transaction()` raises.** `generate_week_plan()` wraps its
`week_plans` + 7× `plan_days` insert sequence in `with conn.transaction():`
specifically so a failure partway through can't leave a partial plan
(Milestone 13 Phase 1). Every other service function in this codebase
that writes data calls `conn.commit()` explicitly after its own
`execute()` — harmless under `autocommit=True` (each statement lands
immediately regardless), so nobody had reason to notice the explicit
call does anything at all. `attach_dish()`/`detach_dish()` are the first
functions ever called *from inside* an already-open `transaction()`
block (`generate_week_plan()` calls them per day, mid-transaction) — and
psycopg raises `ProgrammingError: Explicit commit() forbidden within a
Transaction context` if you do that. Confirmed directly with a throwaway
script against the real dev database before writing either function, not
assumed from memory of psycopg's docs. Fix: `attach_dish()`/
`detach_dish()` have no explicit `conn.commit()` at all, unlike every
other write function in this codebase — standalone calls are still
durable immediately via `autocommit=True`, and calls from inside
`generate_week_plan()`'s transaction no longer raise. Flagging the
inconsistency here rather than silently deviating from the codebase's own
pattern without explanation, since a future function copy-pasting the
"other" style into a similar transaction context would hit the exact
same bug.

**Confirmed, not just re-trusted: swapping a day's main leaves its
attachments alone.** The Phase 1 investigation predicted this from
reading `swap_day_recipe()` (it only ever runs
`UPDATE plan_days SET recipe_id = ...`). Added a direct regression test
this round instead of leaving that as an unverified claim —
`test_swap_day_recipe_leaves_plan_day_dishes_untouched` generates a plan
with a day carrying an attached side, swaps that day's main, and asserts
`list_dishes()` for that day is unchanged.

**Week Plan display stays read-only for this phase, confirmed as
reasonable rather than assumed.** Household size and special-occasion
assignment are only editable pre-generation (regenerating is the only
way to change them post-generation), which is *why* Week Plan has never
offered to edit them. `plan_day_dishes` doesn't share that constraint —
it's a genuinely independent table keyed by `plan_day_id`, so a detach
action on an already-generated day is technically straightforward to add
later without needing to touch the "Weekly Calendar owns all
pre-generation input" model at all. Noted for a future round if wanted;
not built now, since the request scoped this phase to read-only display.

## 2026-09-04 — Milestone 16 Phase 3: Grocery List aggregation, and a day's dishes are independent of its main

`build_grocery_list()`'s per-day loop used to `continue` (skip the day
entirely) when `plan_day.recipe_id` was `None` — a guard against a state
that, in practice, `generate_week_plan()` never produces (it always
assigns a main or raises). Adding attached-dish aggregation meant
revisiting that guard rather than leaving it: a day's attached
sides/desserts (`plan_day_dishes`) have no dependency on that day having
a main at all — they're a separate table keyed by `plan_day_id`, not by
`plan_days.recipe_id`. Restructured the loop to build a per-day list of
contributing recipes (`[main] if present, plus every attached dish`)
rather than gating the whole day on the main's presence, so a
hypothetical day with dishes but no main still contributes their
ingredients — confirmed with a direct test
(`test_build_grocery_list_includes_dish_ingredients_even_with_no_main_recipe`)
rather than left as an untested assumption.

No changes needed to canonicalization, grouping, sorting, or
`grocery_list_table_rows()`/`grocery_list_csv()` — confirmed, not
assumed, by running the existing test suite unchanged alongside the new
attached-dish tests. Scaling composes for free: `effective_ingredient_quantity()`
takes whichever recipe's own `servings` plus the day's household
size/override, with no course-awareness, so an attached dish scales
under the exact same day-level override as the main.

## 2026-09-04 — Milestone 16 Phase 4: Cook Mode multi-dish switcher, and a scaling gap the switcher would have exposed

**Session-state shape confirmed before changing it, not assumed.** The
pre-Phase-4 page tracked exactly two keys: `cook_mode_recipe_id` (the
last-seen recipe, to detect "is this a fresh visit") and a single
`cook_mode_step_index` (one recipe's progress). That single global index
can't survive a switcher — switching from the main to a dessert and back
would otherwise reset or blend their progress. Replaced with three keys:
`cook_mode_entry_recipe_id` + `cook_mode_plan_day_id` (together, "is this
a fresh visit," extending the old single-key check with the day too —
see below) and `cook_mode_step_index_by_recipe` (a dict keyed by recipe
id, so each dish keeps its own place) plus `cook_mode_active_recipe_id`
(which dish the switcher currently has selected). Switching dishes via
the switcher deliberately does not trigger the "fresh visit" reset — only
a different entry recipe or a different day does.

**Fresh-visit detection extended to also key off `plan_day_id`, not just
the recipe id.** The old check (`cook_mode_recipe_id != recipe.id`) alone
would under-reset in a case Phase 4 makes newly relevant: the same
recipe reached from two different days (e.g. a repeated main) would
share one step-progress entry across both days' visits. Once progress is
tracked per recipe id in a dict that persists across a whole Cook Mode
session, that staleness would leak into the new dict too if left
unchanged. Including `plan_day_id` in the reset key closes this — a
minor, deliberate behavior change, not a side effect.

**A real scaling gap found while wiring the switcher, not hypothesized.**
The existing day-scoping check was `plan_day.recipe_id == recipe.id` —
correct when the only recipe ever shown was the day's main, but the
switcher now lets the *entry point* remain the same while `recipe` itself
gets reassigned to whichever dish is selected. Left unchanged, viewing an
attached side/dessert through the switcher would have shown it
day-scoped as `False` — its ingredients silently unscaled, contradicting
the Phase 1/3 finding that attached dishes scale exactly like mains.
Fixed by widening the membership check to the day's main *or* any of its
`list_dishes()` results, confirmed with a direct test
(`test_attached_dish_ingredients_scale_like_the_main`) rather than left
as an assumption once the switcher existed.

**Switcher only appears when there's something to switch to** — a day
with no attached dishes renders nothing here at all, confirmed unchanged
against the full pre-existing `tests/test_ingredient_scaling_ui.py` Cook
Mode suite (all 10 cases, none touching dishes, still pass unmodified).

**Week Plan's "Cook" button needs no change, confirmed against the
current code rather than re-trusted from the Phase 2 proposal** — it
still sets `selected_recipe_id`/`selected_plan_day_id` to the day's main
and switches to Cook Mode; the switcher is discovered entirely from
there, on entry.

Milestone 16 (Side Dishes and Desserts) is now fully complete — all four
phases done.
