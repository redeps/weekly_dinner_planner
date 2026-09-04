# Development Roadmap — Meal Planner

Work proceeds **one milestone at a time**, in order. Do not start a later
milestone before the current one is complete and tested — see
`docs/AGENT_INSTRUCTIONS.md`.

Status legend: ✅ done · 🚧 in progress · ⬜ not started

## Milestone 0 — Foundation ✅ (this task)

- project structure
- Streamlit shell (`app.py` runs, shows the project is alive)
- SQLite database connection helper (`database.py`)
- configuration (`requirements.txt`, `.devcontainer/devcontainer.json`)
- `.gitignore`
- basic tests (`tests/test_foundation.py`)
- basic documentation (this `docs/` folder)

Explicitly **not** in Milestone 0: recipes, ingredients, plans, calendar
input, grocery list, history, photos. No app schema is created yet beyond
proving SQLite is reachable.

## Milestone 1 — Core Recipes ✅

- `recipes` table (name, photo, cook_time_minutes, family_enjoyment,
  seasonality, is_quick_fallback, servings, instructions, notes)
- Add/Edit Recipe form
- Recipes browsing screen: search + filter by season / quick-fallback
- Recipe Detail screen
- seed a handful of `is_quick_fallback = true` recipes (fish fingers, frozen
  pizza, takeout, etc.)

## Milestone 2 — Ingredients ✅

- `recipe_ingredients` table (name, quantity, unit, store category)
- Add/Edit Recipe form gains a repeatable ingredient-rows section
- Recipe Detail displays ingredients

## Milestone 3 — Weekly Calendar Input ✅

- 7-day calendar input screen: busy toggle + dinner-ready time per day
  (default 6:00 PM, overridable)
- persisted per week (or re-entered each time — decide and record in
  `DECISIONS.md`)

## Milestone 4 — Plan Generation ✅

- `week_plans` + `plan_days` tables
- generation algorithm: weighted by seasonality, rotation (via
  `cook_history`), busy-day cook-time preference, and enjoyment as
  tie-breaker (see `PRODUCT_SPEC.md` §9)
- Week Plan screen: 7 days, each clickable into its recipe
- decide and record the rotation "recently cooked" window (e.g. 3 weeks) in
  `DECISIONS.md`

## Milestone 5 — Editing / Swapping ✅

- swap action on any single day, replacing that day's recipe without
  touching the rest of the week
- swap respects the same weighting logic (excludes the just-swapped-out
  recipe from its own replacement candidates)

## Milestone 6 — Grocery List ✅

- aggregation logic: sum ingredient quantities across the week's recipes
  where units match
- grouped-by-store-category read-only list view
- regenerates automatically when a day is swapped

## Milestone 7 — Cook Mode ✅

- "Start Cooking" action on Recipe Detail / Day view
- large-font, step-by-step instructions view (steps derived from the
  existing `instructions` text — no new schema)
- next/back navigation with a simple progress indicator ("Step X of Y")
- ingredients visible for reference without leaving the view
- read-only — no editing from within Cook Mode

## Milestone 8 — Cook History ✅

- `cook_history` table populated by a `finalize_plan()` / `mark_day_cooked()`
  service function (never by UI rendering — see `AGENT_INSTRUCTIONS.md`)
- simple "what have we cooked lately" view
- feeds the rotation weighting from Milestone 4

Note: built before Milestone 7 (Cook Mode), which was added to the roadmap
after this work was already done — see `DECISIONS.md`.

## Milestone 9 — AI Assist (Optional, Local) ✅

- `services/ai_assist.py` — isolated module calling a local Ollama model;
  app must run fully without it
- recipe import: paste text/URL content → pre-filled Add Recipe draft
  (name, servings, cook time estimate, ingredients, instructions), always
  reviewed/confirmed by the user before saving
- ingredient categorization: suggest `store_category` when adding an
  ingredient line, overridable
- swap suggestions with intent: free-text hint narrows swap candidates on
  top of the existing weighting (Milestone 4/5 logic)
- shortcut suggestions: optional effort-saving substitution text shown
  alongside a recipe or day, not persisted as a recipe change
- graceful degradation if the local model isn't running (feature hidden or
  disabled, no errors surfaced to the core flow)

## Milestone 10 — Recipe Import (URL + Photo) + Swappable AI Backend ✅

Course-correction on Milestone 9: recipe import shouldn't depend on a
model being available at all for the common URL case, suggestion features
shouldn't go dead the moment the app is hosted, and photo-based import
from existing cookbooks is a real need. See `docs/PRODUCT_SPEC.md` §16 and
`docs/DECISIONS.md` for the reasoning.

- `services/recipe_import.py`: fetch a recipe URL, parse embedded
  `schema.org/Recipe` JSON-LD structured data into a pre-filled Add Recipe
  draft. **Standard library only — `urllib`, `html.parser`, `json`. No
  third-party scraping package** (e.g. do not add `recipe-scrapers` or
  similar; see `docs/DECISIONS.md`). No model call, works with no AI
  backend configured at all. This becomes the **primary** import path for
  URLs; the existing AI-assist text parser (Milestone 9) becomes the
  fallback for pages with no structured data or for pasted free text.
- photo import: uploading a photo of a cookbook/recipe-card page produces
  the same pre-filled draft via a vision-capable model call.
  **This path always uses the hosted Gemini backend, regardless of which
  backend §16c's text features are configured to use** — no local vision
  model. If no Gemini key is configured, photo import is simply
  unavailable; nothing else is affected.
- refactor `services/ai_assist.py` so the text-only capabilities in §16c
  (categorization, swap-intent, shortcuts, unstructured text import) select
  their backend (local Ollama vs. hosted Gemini) from
  configuration/environment, behind the same interface already in use —
  no changes needed at call sites. The photo-import function is separate
  and always calls Gemini directly.
- confirm graceful degradation holds in all states: no backend configured,
  Ollama only (photo import still unavailable without a Gemini key),
  Gemini only, both configured
- update `docs/SETUP.md` with how to obtain and set a Gemini API key (as a
  secret, never committed) — now needed for local dev too if photo import
  is wanted, not just for hosted deployment
- tests: structured-data parsing against a few real recipe pages' HTML
  fixtures, backend-selection logic for §16c, and a mocked-response test
  for the photo-import path

## Milestone 11 — Photos ✅

- upload a photo when adding/editing a recipe
- resize/compress on save
- store file under `photos/`, named by stable recipe ID
- display photo on recipe cards and detail/day/Cook Mode views
- replace / delete photo

## Milestone 12 — Polish ✅

- mobile UX pass
- empty states (no recipes yet, no plan generated yet, etc.)
- confirmation dialogs for destructive actions (deleting a recipe, etc.)
- basic accessibility pass
- expand automated test coverage
- backup/export (e.g. download the SQLite file)

## Milestone 13 — Hosted Version ⬜ (only after Milestones 0–12 are stable)

Architecture decided (Neon + Streamlit Community Cloud, matching the
sibling "home-inventory" app) — see `docs/DECISIONS.md` for the full
reasoning. Broken into five phases, worked one at a time. (Originally six,
with the connection layer and the service layer's SQL dialect as separate
phases 1 and 2 — merged into one phase once implementation showed they
can't be verified independently; see the "Phase 1/2 merge" entry in
`docs/DECISIONS.md`.)

- **Phase 1 — Local Postgres + service layer ✅ done:** added Postgres to
  `.devcontainer/` (installed via `apt`, not Neon branching — dev/test
  never touch Neon). Ported home-inventory's `SCHEMA_MIGRATIONS`/
  `schema_version`/`_apply_migrations` pattern into `database.py` for the
  five existing tables (`recipes`, `recipe_ingredients`, `week_plans`,
  `plan_days`, `cook_history`), replacing `models.py`'s per-table
  `create_*_table()` functions — `models.py` now keeps dataclasses/
  constants only. Migrated `services/recipes.py`, `services/ingredients.py`,
  `services/plan_generation.py`, `services/cook_history.py` from `sqlite3`
  to `psycopg`/`%s` placeholders in the same pass, since `get_connection()`
  switching to Postgres and those four files staying on `sqlite3` syntax
  turned out not to be independently verifiable states — see
  `docs/DECISIONS.md`. Also carried `export_database_bytes()`'s backup
  format from a SQLite file to a per-table CSV/zip (a minimal stand-in for
  Phase 5 below, forced by the same connection-layer swap) and switched
  `get_connection()` to `autocommit=True` (Streamlit pages never close
  their connection, which otherwise leaves Postgres transactions open and
  locks other connections — not a concern SQLite's file-based model had).
- **Phase 2 — Photo storage ✅ done:** Cloudflare R2 via `boto3`,
  alongside (not replacing) local filesystem storage — local storage now
  doubles as a persistent cache that R2 syncs to/through when configured,
  so every existing page's `photo_exists()`/`resolve_photo_path()` call
  keeps working unchanged. Key scheme (`photos/<recipe_id>.jpg`) matches
  `services/photos.py`'s existing `photo_relative_path()`, carried over
  unchanged as planned. Backend selection is "is `st.secrets['r2']`
  configured?", not a separate toggle — see `docs/DECISIONS.md`.
- **Phase 3 — Auth + deployment ✅ auth done:** in-app household
  passphrase gate (`services/auth.py`, implemented) instead of
  Streamlit Community Cloud's private-app mechanism, since the free
  tier allows only one private app (already used by home-inventory) —
  see `docs/DECISIONS.md`. Deploys as a **public** app from a
  **public** repo as a result. Still pending in this phase: CI, making
  the repo public, and the actual deploy against Neon's production
  branch.
- **Phase 4 — One-time data migration:** local SQLite → Neon, local
  `photos/` → R2.
- **Phase 5 — Backups:** pure-Python per-table CSV/zip export (no
  `pg_dump`) — a minimal version of this already shipped in Phase 1 as a
  forced side effect of the connection-layer swap; revisit here only if
  it needs more than that (e.g. including photos, a nicer download UX).

Do not begin this milestone, or introduce any paid service beyond the
already-approved Gemini free tier, before the local prototype is stable and
the earlier milestones are complete.

## Milestone 14 — Household-Size Scaling ✅

Scales ingredient quantities (and the grocery list built from them) to
however many people a given day is actually feeding — not every week
uniformly, and not Cook Mode's instruction text.

- `plan_days.household_size_override` (nullable integer) — set only for
  the specific day(s) a household is hosting or cooking for more than
  usual; `NULL` means "use the global default." Lives on `plan_days`, not
  `week_plans`, because the override is per-day, not per-week.
- `app_settings` — a new single-row table (`id=1`), holding the global
  default household size (`services/settings.py`), same one-row pattern
  as `schema_version`.
- Weekly Calendar Input screen: after the existing per-day busy/dinner-
  time inputs, one week-level yes/no question — "Are there any days this
  week you're hosting or cooking for more than your normal household?"
  No (the common case) shows nothing further. Yes reveals a multiselect
  of the week's days, then a household-size number input per selected
  day — deselecting a day clears its override back to `NULL`.
- Scaling applies to ingredient quantities in the grocery list only
  (`services/grocery_list.py`) — each day's ingredients are scaled by
  that day's effective household size relative to the recipe's own
  `servings`, *before* being summed across the week, then rounded to 2
  decimal places (both per-day and on the aggregated total — see
  docs/DECISIONS.md for why both). An ingredient with no quantity (e.g.
  "salt to taste") can't be scaled and is flagged in the grocery list
  rather than silently shown blank.
- Coverage, from 8 real recipes imported through the actual Add Recipe
  flow (URL import — `services/recipe_import.py`'s structured-data
  parser — against real recipe pages): **94.3% (99/105) of ingredient
  rows had a usable quantity for scaling**; the remaining 5.7% (6 rows)
  were quantity-less garnish/seasoning lines ("a handful of parsley,"
  "thumb-sized piece of ginger") that the parser correctly can't
  quantify and that the grocery list now flags instead of silently
  showing blank. See docs/DECISIONS.md for the full investigation,
  including confirmation that `build_grocery_list()`'s existing name/unit
  aggregation logic is unaffected by scaled (decimal) quantities.

## Milestone 15 — Email the Weekly Plan ✅

A manually-triggered button, not a scheduled job: sends the current week
plan to a small, household-maintained list of recipient email addresses.
Sized as a single contained pass, not a phased breakdown — appended here
rather than inserted earlier, same reasoning as Milestone 14 (this wasn't
part of the original milestone sequence and doesn't retroactively renumber
it).

- `email_recipients` — a new table (`id`, `email` `UNIQUE`, `created_at`),
  one row per address, not a JSON list on `app_settings` — see
  docs/DECISIONS.md for why.
- `services/email.py` — recipient add/remove/list, plain-text email body
  built from the same `list_plan_days()`/`get_recipe()` calls
  `pages/5_Week_Plan.py` already uses to render the page (day, date,
  recipe name, cook time — not the full instructions), and the send
  itself via stdlib `smtplib`, one message per recipient.
- Weekly Calendar screen: an "Email recipients" add/remove list below the
  household-size section (the app's one existing standing-settings
  screen).
- Week Plan screen: a "Send weekly plan by email" button below "Finalize
  Plan," hidden behind an explanatory caption when the recipient list is
  empty. Reports success/partial-failure/failure per recipient rather
  than a single pass/fail verdict for the whole send — see
  docs/DECISIONS.md for why this differs from R2 sync's and
  `PhotoBackupError`'s failure-handling.
- New `[smtp]` secrets section (`host`, `port`, `username`,
  `app_password`), presence-detected via `st.secrets.get("smtp")` like R2
  rather than a separate on/off flag — see docs/SETUP.md.
- **Known unverified risk, flagged rather than assumed away:** whether
  Streamlit Community Cloud's outbound network actually permits SMTP on
  port 587/465 could not be confirmed from this environment — evidence
  from other Streamlit Community Cloud deployments is mixed (some report
  successful Gmail SMTP sends, others report silent delivery failure once
  deployed, though not conclusively a network-level block in every case).
  Local dev and mocked tests can't surface this either way. See
  docs/DECISIONS.md — this needs an actual deployed test send to confirm
  once Milestone 13 (Hosted Version) is live.

## Roadmap catch-up — work completed between Milestones 12 and 15 without its own entry

A one-time catch-up, not a milestone itself: several rounds of real,
shipped work landed between Milestones 12 and 15 without ever getting a
roadmap entry — recorded here for the record before Milestone 16 extends
this document further, so the gap doesn't widen. See docs/DECISIONS.md
for the full reasoning behind each.

- **Busy-day preference strengthened toward quick-fallback recipes** —
  2026-09-02. Also the related non-busy-day quick-fallback penalty, same
  date.
- **Cook Mode secondary split: sentence-packing above a 180-char proxy
  threshold** — 2026-09-02.
- **Ingredient name canonicalization for grocery-list grouping** —
  2026-09-03, plus a same-day follow-up (unit normalization, noise-word
  additions).
- **Overlap-aware plan generation**, favoring shared ingredients across a
  week's recipes — 2026-09-03, plus a same-day multi-week stability
  check.
