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

## Milestone 1 — Core Recipes ⬜

- `recipes` table (name, photo, cook_time_minutes, family_enjoyment,
  seasonality, is_quick_fallback, servings, instructions, notes)
- Add/Edit Recipe form
- Recipes browsing screen: search + filter by season / quick-fallback
- Recipe Detail screen
- seed a handful of `is_quick_fallback = true` recipes (fish fingers, frozen
  pizza, takeout, etc.)

## Milestone 2 — Ingredients ⬜

- `recipe_ingredients` table (name, quantity, unit, store category)
- Add/Edit Recipe form gains a repeatable ingredient-rows section
- Recipe Detail displays ingredients

## Milestone 3 — Weekly Calendar Input ⬜

- 7-day calendar input screen: busy toggle + dinner-ready time per day
  (default 6:00 PM, overridable)
- persisted per week (or re-entered each time — decide and record in
  `DECISIONS.md`)

## Milestone 4 — Plan Generation ⬜

- `week_plans` + `plan_days` tables
- generation algorithm: weighted by seasonality, rotation (via
  `cook_history`), busy-day cook-time preference, and enjoyment as
  tie-breaker (see `PRODUCT_SPEC.md` §9)
- Week Plan screen: 7 days, each clickable into its recipe
- decide and record the rotation "recently cooked" window (e.g. 3 weeks) in
  `DECISIONS.md`

## Milestone 5 — Editing / Swapping ⬜

- swap action on any single day, replacing that day's recipe without
  touching the rest of the week
- swap respects the same weighting logic (excludes the just-swapped-out
  recipe from its own replacement candidates)

## Milestone 6 — Grocery List ⬜

- aggregation logic: sum ingredient quantities across the week's recipes
  where units match
- grouped-by-store-category read-only list view
- regenerates automatically when a day is swapped

## Milestone 7 — Cook History ⬜

- `cook_history` table populated by a `finalize_plan()` / `mark_day_cooked()`
  service function (never by UI rendering — see `AGENT_INSTRUCTIONS.md`)
- simple "what have we cooked lately" view
- feeds the rotation weighting from Milestone 4

## Milestone 7 — Cook Mode ⬜

- "Start Cooking" action on Recipe Detail / Day view
- large-font, step-by-step instructions view (steps derived from the
  existing `instructions` text — no new schema)
- next/back navigation with a simple progress indicator ("Step X of Y")
- ingredients visible for reference without leaving the view
- read-only — no editing from within Cook Mode

## Milestone 8 — Cook History ⬜

- `cook_history` table populated by a `finalize_plan()` / `mark_day_cooked()`
  service function (never by UI rendering — see `AGENT_INSTRUCTIONS.md`)
- simple "what have we cooked lately" view
- feeds the rotation weighting from Milestone 4

## Milestone 9 — AI Assist (Optional, Local) ⬜

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

## Milestone 10 — Photos ⬜

- upload a photo when adding/editing a recipe
- resize/compress on save
- store file under `photos/`, named by stable recipe ID
- display photo on recipe cards and detail/day view
- replace / delete photo

## Milestone 11 — Polish ⬜

- mobile UX pass
- empty states (no recipes yet, no plan generated yet, etc.)
- confirmation dialogs for destructive actions (deleting a recipe, etc.)
- basic accessibility pass
- expand automated test coverage
- backup/export (e.g. download the SQLite file)

## Milestone 12 — Hosted Version ⬜ (only after Milestones 0–11 are stable)

- hosted database (e.g. managed Postgres)
- hosted photo storage
- authentication / access control
- remote access so the grocery list / plan is reachable away from home, if
  ever wanted
- migration path from SQLite to the hosted database
- backups
- deployment

Do not begin this milestone, or introduce any paid service, before the
local prototype is stable and the earlier milestones are complete.
