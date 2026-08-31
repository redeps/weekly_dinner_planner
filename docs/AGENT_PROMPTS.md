# Agent Prompts — Meal Planner (Cookbook)

Ready-to-use prompts for driving this build with Claude Code, one per
milestone. Use them in order — don't skip ahead. Each prompt assumes
`docs/PRODUCT_SPEC.md`, `docs/ROADMAP.md`, `docs/DATA_MODEL.md`,
`docs/DECISIONS.md`, and `docs/AGENT_INSTRUCTIONS.md` are already in the
repo (they are, as of this Foundation commit).

**How to use these:** open the repo in Claude Code (inside the Codespace),
paste the prompt for the milestone you're on, let it work, review the diff,
run `pytest`, then commit before moving to the next prompt.

---

## Milestone 0 — Foundation

Already done by this backbone. Once it's in your repo:

```
Read docs/PRODUCT_SPEC.md, docs/ROADMAP.md, docs/DATA_MODEL.md,
docs/DECISIONS.md, and docs/AGENT_INSTRUCTIONS.md. Then run `pytest` and
`streamlit run app.py` to confirm the foundation works. Report back what
you find — don't change anything yet.
```

## Milestone 1 — Core Recipes

```
Implement Milestone 1 from docs/ROADMAP.md: the `recipes` table (per
docs/DATA_MODEL.md), an Add/Edit Recipe form, a Recipes browsing screen
with search + filter by season and quick-fallback, and a Recipe Detail
screen. Seed a handful of is_quick_fallback recipes (fish fingers, frozen
pizza, takeout — no need for real ingredients on these yet). Follow
docs/AGENT_INSTRUCTIONS.md. Add tests for the recipe service functions.
Stop when Milestone 1 is done — don't start ingredients yet.
```

## Milestone 2 — Ingredients

```
Implement Milestone 2 from docs/ROADMAP.md: the `recipe_ingredients` table,
a repeatable ingredient-rows section on the Add/Edit Recipe form, and
ingredient display on Recipe Detail. Follow docs/AGENT_INSTRUCTIONS.md
(structured rows, not a text blob). Add tests.
```

## Milestone 3 — Weekly Calendar Input

```
Implement Milestone 3 from docs/ROADMAP.md: a 7-day calendar input screen
(busy toggle + dinner-ready time per day, default 6:00 PM, overridable).
Decide how it persists (per-week vs. re-entered) and record that choice in
docs/DECISIONS.md before finishing. Add tests.
```

## Milestone 4 — Plan Generation

```
Implement Milestone 4 from docs/ROADMAP.md: the `week_plans` and
`plan_days` tables, and the plan generation algorithm described in
docs/PRODUCT_SPEC.md §9 (seasonality weighting, rotation avoidance via
cook_history, busy-day cook-time preference, enjoyment as tie-breaker).
Pick a rotation window (e.g. 3 weeks) and record it in docs/DECISIONS.md.
Build the Week Plan screen: 7 days, each clickable into its recipe. Follow
docs/AGENT_INSTRUCTIONS.md §5 — this is a scoring heuristic, not a solver.
Add tests for the scoring logic specifically.
```

## Milestone 5 — Editing / Swapping

```
Implement Milestone 5 from docs/ROADMAP.md: a swap action on any single day
of the current week plan, replacing only that day's recipe. Reuse the
Milestone 4 scoring logic for candidates, excluding the recipe being
swapped out. Add tests.
```

## Milestone 6 — Grocery List

```
Implement Milestone 6 from docs/ROADMAP.md: aggregate recipe_ingredients
across the current week plan's 7 recipes (summing quantities where units
match), grouped by store_category, shown as a simple read-only list. It
should regenerate automatically when a day is swapped. Per
docs/DECISIONS.md, no check-off state or shopping-mode UI is needed. Add
tests for the aggregation logic.
```

## Milestone 7 — Cook History

```
Implement Milestone 7 from docs/ROADMAP.md: the `cook_history` table and a
finalize_plan()/mark_day_cooked() service function that writes it — per
docs/AGENT_INSTRUCTIONS.md §4, this must never happen as a side effect of
rendering. Add a simple "what have we cooked lately" view. Add tests
including a check that re-rendering the page does not create duplicate
history rows.
```

## Milestone 8 — AI Assist (Optional, Local)

```
Implement Milestone 8 from docs/ROADMAP.md: an isolated services/ai_assist.py
module calling a local Ollama model, covering recipe import (paste
text/URL → pre-filled Add Recipe draft, always reviewed before saving),
ingredient store_category suggestions, swap suggestions with a free-text
intent hint, and shortcut/substitution suggestions. Per
docs/AGENT_INSTRUCTIONS.md §6, no core screen may depend on this module
being available — confirm the app still fully works with Ollama stopped.
Add tests that mock the model call and verify graceful degradation when
it's unreachable.
```

## Milestone 9 — Photos

```
Implement Milestone 9 from docs/ROADMAP.md: photo upload on the Add/Edit
Recipe form, resize/compress on save, store under photos/ named by the
recipe's stable ID, display on recipe cards and detail/day views, and
replace/delete. Confirm photos/ stays gitignored.
```

## Milestone 10 — Polish

```
Implement Milestone 10 from docs/ROADMAP.md: mobile UX pass, empty states,
confirmation dialogs for destructive actions, a basic accessibility pass,
expanded test coverage, and a backup/export option (e.g. download the
SQLite file).
```

## Milestone 11 — Hosted Version

```
Do not run this prompt until Milestones 0–10 are stable and you've decided
to move off the local prototype. When ready: propose a hosted architecture
(managed Postgres, hosted photo storage, auth, migration path from SQLite,
backups, deployment) as a plan first, get it reviewed, record the decision
in docs/DECISIONS.md, then implement.
```
