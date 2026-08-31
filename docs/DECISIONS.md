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
