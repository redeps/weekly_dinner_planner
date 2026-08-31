# Agent Instructions — Meal Planner

Rules for any coding agent (Claude Code or otherwise) working on this repo.
Read `docs/PRODUCT_SPEC.md`, `docs/ROADMAP.md`, `docs/DATA_MODEL.md`, and
`docs/DECISIONS.md` before writing any code.

## 1. Source of truth

`docs/PRODUCT_SPEC.md` wins over code if the two disagree, unless a
`docs/DECISIONS.md` entry says otherwise. If a task conflicts with the spec,
stop and flag it rather than improvising.

## 2. One milestone at a time

Work through `docs/ROADMAP.md` in order. Do not start a later milestone's
work before the current one is complete and tested. Do not build ahead
"while you're in there" — a small unrelated addition still needs its own
milestone and its own review.

## 3. Keep the layers separate

- Universal recipe fields stay on `recipes`. Never add category-specific or
  one-off columns there.
- Ingredients are structured rows in `recipe_ingredients`, never a text
  blob parsed at read time.
- See `docs/DATA_MODEL.md` for the full schema and why each table exists.

## 4. History and cook-tracking

`cook_history` rows are created **only** by business-logic/service
functions (e.g. `finalize_plan()`, `mark_day_cooked()`) — never as a side
effect of rendering a Streamlit screen. Streamlit reruns the whole script on
every interaction; if a rendering function writes a history row, a single
user action can silently create duplicates. Put all writes behind an
explicit action (button press → service function → write), not behind
page load.

## 5. Plan generation stays a scoring heuristic

The generator in `docs/PRODUCT_SPEC.md` §9 (seasonality, rotation, busy-day
cook time, enjoyment) is a weighted scoring pass, not a constraint solver.
Do not introduce an optimization library or complex search for this — a
straightforward scored/random selection is the intended design.

## 6. AI assist stays optional and isolated

Any code touching the local model (Ollama or otherwise) lives in
`services/ai_assist.py` (or similar), is called only from the screens that
use it, and must fail gracefully if the model isn't reachable — no core
screen (recipes, plan, grocery list) may hard-depend on it. AI-suggested
content (imported recipes, categorizations, shortcuts) is always shown for
user review/confirmation, never written to the database automatically.

## 7. Simplicity over completeness

Don't create files, folders, tables, or abstractions "for completeness" if
nothing uses them yet. If a milestone doesn't need it, leave it out and add
it when the milestone that needs it arrives.

## 8. Tests

Each milestone should leave `pytest` green. New business logic (plan
generation, grocery aggregation, history writes) needs tests — UI rendering
code does not need to be exhaustively tested, but the service functions it
calls do.

## 9. Decisions

If you make a non-obvious architectural choice (e.g. picking the rotation
window length, how the weekly calendar persists), add a dated entry to
`docs/DECISIONS.md` explaining the choice. Don't silently decide and move
on — this file is what keeps future work (and future agents) from
re-litigating settled questions.

## 10. Data hygiene

Never commit anything under `data/` or `photos/` — both are gitignored on
purpose. Don't use `git add -f` on either. Don't add a paid or cloud
dependency before Milestone 11, and only then with a `DECISIONS.md` entry.

## 11. Commits

Small, milestone-scoped commits with a clear message. Don't bundle unrelated
changes. Run `pytest` before committing.
