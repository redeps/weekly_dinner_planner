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

## 2026-08-31 — Free-first

No paid infrastructure during prototype development (Milestones 0–9).
Hosted/paid services are deferred to Milestone 10 and require a new
decision entry before adoption.

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
