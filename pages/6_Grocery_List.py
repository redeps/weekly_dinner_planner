"""
Grocery List screen — a generated, grouped-by-category table for the
current week plan, plus manual grocery items (Milestone 17): one-off
items for this week only, and standing recurring items included every
week. See docs/PRODUCT_SPEC.md §11 and docs/DECISIONS.md.

Nothing here is persisted beyond the manual items and category overrides
themselves: the table is recomputed from the live plan_days +
plan_day_dishes + recipe_ingredients + manual_grocery_items +
ingredient_category_overrides on every render (Milestone 16 Phase 3 —
each day's main *and* its attached sides/desserts; Milestone 17 — every
manual item and any persisted category correction), so it regenerates
automatically when a day is swapped, an attachment changes, a manual
item is added/removed, or a category is recategorized — no separate
refresh step needed.

Shopping mode (Milestone 18, both phases now complete) reverses the
original "no check-off state, no shopping-mode UI" decision — see
docs/DECISIONS.md for the formal supersession entry. "Finish Shopping"
sets `week_plans.shopping_completed_at`, and this whole table-and-export
section is gated on it being unset — a completed week's list reads as
empty (not deleted; the underlying data is all still there) until a new
week plan is generated, whose own `shopping_completed_at` starts unset
regardless of any prior week's state.

"Start Shopping" (a session-state-only toggle — no DB write, so losing
it costs nothing; see docs/DECISIONS.md) switches the same
`st.data_editor` into a filtered, checkbox-enabled view: unchecked rows
only, with a `Checked` `CheckboxColumn` alongside the existing `Category`
one. Checking a box persists a `grocery_checked_items` row (Milestone 18
Phase 2, `services.shopping_mode`) keyed on `(week_plan_id,
canonical_name, unit)` — the list's own post-aggregation display
identity, not a source `recipe_ingredients` row, since one checked line
can represent several merged rows. Checked rows drop into a collapsed
"Checked off (N)" expander with a plain "Restore" button each (reusing
`_render_manage_list()`'s own pattern, not a second data editor — restoring
only ever goes one direction). Checked state is DB-backed specifically so
it survives a closed tab or an app reboot mid-trip, not left in session
state like the mode toggle itself. Export is unaffected by checked state
throughout — the CSV/table always reflects the complete `grocery_list`,
same as before shopping mode existed.

Rendered as a table (Category / Ingredient / Quantity / Unit, one row per
canonical ingredient+unit combination) via `st.data_editor` — outside
shopping mode, only the Category cell is editable (a `SelectboxColumn`),
everything else stays disabled/read-only. Recategorizing a row persists
an `ingredient_category_overrides` entry (Milestone 17 Phase 2,
`services.category_overrides`) keyed on that row's canonical ingredient
name, applied by `build_grocery_list()` itself — not a rewrite of any
`recipe_ingredients` row — so every recipe using that ingredient regroups
correctly starting with the very next render, for every week, with
nothing retroactive to run. See docs/DECISIONS.md for why drag-and-drop
(the originally suggested interaction) isn't a fit for this stack, and
why this achieves the same outcome. The same row data (before any
in-progress, unsaved edit) backs the "Download as Excel (.csv)" button
below it (services.grocery_list.grocery_list_table_rows() /
grocery_list_csv()) — one underlying structure, two presentations.

One-off and recurring items share a single paste-in-and-review flow
(`_render_paste_in_section`), parameterized only by which `week_plan_id`
to write to (a specific week vs. `None`) — the two are the same
mechanism with one flag, not two features (see docs/DECISIONS.md). Both
live here rather than on Weekly Calendar: this is where the result is
seen, and where a one-off item's target week (the current plan) already
exists.
"""

import streamlit as st

from database import get_connection
from models import STORE_CATEGORIES
from services.auth import require_password
from services.category_overrides import detect_category_edits, set_override
from services.categorization import suggest_category
from services.grocery_items import add_item, list_manual_items, parse_leading_quantity, remove_item
from services.grocery_list import build_grocery_list, grocery_list_csv, grocery_list_table_rows
from services.plan_generation import get_latest_week_plan
from services.shopping_mode import (
    check_item,
    detect_checked_edits,
    list_checked_items,
    mark_shopping_completed,
    row_key,
    uncheck_item,
)

st.set_page_config(page_title="Grocery List — Meal Planner", page_icon="🍽️")
require_password()


def _parse_pasted_lines(text: str) -> list[dict]:
    """One row per non-blank pasted line: a leading plain number (if any)
    becomes `quantity`, the remainder becomes `name` and is run through
    the same deterministic categorization lookup Add/Edit Recipe's
    ingredient rows use. See `services.grocery_items.parse_leading_quantity`
    for why this exists — without it, a line like "6 eggs" stored whole
    as `name` would silently lose its "6" to grouping's own leading-
    number stripping (see docs/DECISIONS.md)."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        quantity, name = parse_leading_quantity(line)
        rows.append(
            {
                "name": name,
                "quantity": "" if quantity is None else f"{quantity:g}",
                "unit": "",
                "store_category": suggest_category(name) or "other",
            }
        )
    return rows


def _render_paste_in_section(conn, *, week_plan_id, key_prefix: str) -> None:
    """Paste-box -> parse -> editable review -> confirm, shared by the
    one-off and recurring sections below. `week_plan_id=None` writes
    recurring items; a specific id scopes the write to that one week."""
    draft_key = f"{key_prefix}_draft_rows"
    counter_key = f"{key_prefix}_draft_counter"
    input_key = f"{key_prefix}_paste_input"
    st.session_state.setdefault(counter_key, 0)

    st.text_area(
        "Paste items, one per line",
        key=input_key,
        placeholder="e.g.\n6 eggs\nDish soap\n2 rolls of paper towels",
        height=100,
    )
    if st.button("Parse", key=f"{key_prefix}_parse"):
        parsed = _parse_pasted_lines(st.session_state[input_key])
        rows = []
        for row in parsed:
            st.session_state[counter_key] += 1
            row["_key"] = st.session_state[counter_key]
            rows.append(row)
        st.session_state[draft_key] = rows
        if not rows:
            st.warning("Nothing to add — paste one item per line first.")
        st.rerun()

    draft_rows = st.session_state.get(draft_key, [])
    if draft_rows:
        st.caption("Review before adding — adjust name, quantity, unit, or category as needed.")
        for row in draft_rows:
            key = row["_key"]
            cols = st.columns([3, 1, 1, 1.5, 0.6])
            row["name"] = cols[0].text_input("Name", value=row["name"], key=f"{key_prefix}_name_{key}")
            row["quantity"] = cols[1].text_input("Qty", value=row["quantity"], key=f"{key_prefix}_qty_{key}")
            row["unit"] = cols[2].text_input("Unit", value=row["unit"], key=f"{key_prefix}_unit_{key}")
            row["store_category"] = cols[3].selectbox(
                "Category",
                STORE_CATEGORIES,
                index=STORE_CATEGORIES.index(row["store_category"]),
                key=f"{key_prefix}_cat_{key}",
            )
            cols[4].markdown("<br>", unsafe_allow_html=True)
            if cols[4].button("✕", key=f"{key_prefix}_remove_{key}", help="Remove this item"):
                st.session_state[draft_key] = [r for r in draft_rows if r["_key"] != key]
                st.rerun()

        confirm_col, discard_col = st.columns(2)
        if confirm_col.button("Add these items", type="primary", key=f"{key_prefix}_confirm"):
            errors = []
            to_add = []
            for row in st.session_state[draft_key]:
                name = row["name"].strip()
                if not name:
                    continue
                quantity = None
                if row["quantity"].strip():
                    try:
                        quantity = float(row["quantity"])
                    except ValueError:
                        errors.append(f"'{name}': quantity must be a number.")
                to_add.append(
                    {
                        "name": name,
                        "quantity": quantity,
                        "unit": row["unit"].strip() or None,
                        "store_category": row["store_category"],
                    }
                )
            if errors:
                for error in errors:
                    st.error(error)
            else:
                for item in to_add:
                    add_item(conn, week_plan_id=week_plan_id, **item)
                st.session_state.pop(draft_key, None)
                st.session_state.pop(input_key, None)
                st.rerun()
        if discard_col.button("Discard", key=f"{key_prefix}_discard"):
            st.session_state.pop(draft_key, None)
            st.rerun()


def _render_manage_list(conn, *, items, key_prefix: str) -> None:
    """A persistent add/remove list for already-saved manual items,
    mirroring `email_recipients`' own list-with-remove UI."""
    if not items:
        st.caption("_None added yet._")
        return
    for item in items:
        cols = st.columns([3, 1, 1, 1.5, 1])
        cols[0].write(item.name)
        cols[1].write("" if item.quantity is None else f"{item.quantity:g}")
        cols[2].write(item.unit or "")
        cols[3].write(item.store_category)
        if cols[4].button("Remove", key=f"{key_prefix}_remove_{item.id}"):
            remove_item(conn, item.id)
            st.rerun()


conn = get_connection()

st.title("Grocery List")

week_plan = get_latest_week_plan(conn)
if not week_plan:
    st.info("No week plan yet. Generate one from the Week Plan screen first.")
    st.stop()

st.caption(f"Week of {week_plan.week_start_date}")

if week_plan.shopping_completed_at is not None:
    st.success(
        "Shopping for this week is complete. Generate a new week plan "
        "from the Week Plan screen to start next week's list."
    )
else:
    grocery_list = build_grocery_list(conn, week_plan.id)

    shopping_active = st.session_state.get("shopping_mode_active", False)
    if not shopping_active:
        if st.button("Start Shopping", key="start_shopping", type="primary"):
            st.session_state["shopping_mode_active"] = True
            st.rerun()
    else:
        if st.button("Stop Shopping", key="stop_shopping"):
            st.session_state["shopping_mode_active"] = False
            st.rerun()

    if not grocery_list:
        st.write("_No ingredients needed this week._")
    else:
        rows = grocery_list_table_rows(grocery_list)
        category_options = [category.capitalize() for category in STORE_CATEGORIES]

        if not shopping_active:
            table_data = [
                {
                    "Category": row.category,
                    "Ingredient": row.ingredient,
                    "Quantity": row.quantity,
                    "Unit": row.unit,
                }
                for row in rows
            ]
            st.caption("Recategorize an ingredient by changing its Category cell below.")
            edited = st.data_editor(
                table_data,
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                disabled=["Ingredient", "Quantity", "Unit"],
                column_config={
                    "Category": st.column_config.SelectboxColumn(
                        "Category", options=category_options, required=True
                    ),
                },
                key="grocery_table_editor",
            )
            category_edits = detect_category_edits(table_data, edited)
            for canonical_name, new_category in category_edits:
                set_override(conn, canonical_name, new_category)
            if category_edits:
                st.rerun()
        else:
            checked_pairs = set(list_checked_items(conn, week_plan.id))
            active_rows = [row for row in rows if row_key(row.ingredient, row.unit) not in checked_pairs]
            checked_rows = [row for row in rows if row_key(row.ingredient, row.unit) in checked_pairs]

            if not active_rows:
                # st.data_editor([]) renders with no columns at all, not
                # a recognizable empty table -- a real, likely-to-happen
                # moment (everything eventually gets checked off), so
                # this gets its own message rather than a blank grid.
                st.success("Everything's checked off! Click Finish Shopping when you're done.")
            else:
                active_table_data = [
                    {
                        "Category": row.category,
                        "Ingredient": row.ingredient,
                        "Quantity": row.quantity,
                        "Unit": row.unit,
                        "Checked": False,
                    }
                    for row in active_rows
                ]
                st.caption("Check off items as you shop. Recategorize by changing Category.")
                edited = st.data_editor(
                    active_table_data,
                    hide_index=True,
                    use_container_width=True,
                    num_rows="fixed",
                    disabled=["Ingredient", "Quantity", "Unit"],
                    column_config={
                        "Category": st.column_config.SelectboxColumn(
                            "Category", options=category_options, required=True
                        ),
                        "Checked": st.column_config.CheckboxColumn("Checked", default=False),
                    },
                    key="grocery_table_editor_shopping",
                )
                category_edits = detect_category_edits(active_table_data, edited)
                for canonical_name, new_category in category_edits:
                    set_override(conn, canonical_name, new_category)
                checked_edits = detect_checked_edits(active_table_data, edited)
                for canonical_name, unit in checked_edits:
                    check_item(conn, week_plan.id, canonical_name, unit)
                if category_edits or checked_edits:
                    st.rerun()

            with st.expander(f"Checked off ({len(checked_rows)})"):
                if not checked_rows:
                    st.caption("_Nothing checked off yet._")
                else:
                    for row in checked_rows:
                        cols = st.columns([1.5, 2.5, 1, 1, 1])
                        cols[0].write(row.category)
                        cols[1].write(row.ingredient)
                        cols[2].write(row.quantity)
                        cols[3].write(row.unit)
                        canonical_name, unit = row_key(row.ingredient, row.unit)
                        if cols[4].button(
                            "Restore", key=f"restore_{canonical_name}_{unit}", use_container_width=True
                        ):
                            uncheck_item(conn, week_plan.id, canonical_name, unit)
                            st.rerun()

        # Export is deliberately unaffected by checked state — it always
        # reflects the full grocery_list, same as before shopping mode
        # existed, regardless of which rows happen to be checked off.
        st.download_button(
            "Download as Excel (.csv)",
            # utf-8-sig (a UTF-8 BOM) so Excel on Windows renders the "—"
            # placeholder correctly instead of mojibake — Excel's CSV import
            # otherwise assumes a legacy Windows codepage for a BOM-less file.
            data=grocery_list_csv(grocery_list).encode("utf-8-sig"),
            file_name=f"grocery-list-{week_plan.week_start_date}.csv",
            mime="text/csv",
        )

    if st.button("Finish Shopping", type="primary", key="finish_shopping"):
        mark_shopping_completed(conn, week_plan.id)
        st.rerun()

st.divider()
st.subheader("Add items to this week's list")
st.caption(
    "One-off items for this week only — they won't carry over to next "
    "week. For something you always need, add it as a recurring item "
    "below instead."
)
_render_paste_in_section(conn, week_plan_id=week_plan.id, key_prefix="one_off")

one_off_items = [item for item in list_manual_items(conn, week_plan.id) if item.week_plan_id is not None]
if one_off_items:
    st.caption("Added this week:")
    _render_manage_list(conn, items=one_off_items, key_prefix="one_off_manage")

st.divider()
st.subheader("Recurring items")
st.caption("Always included on the grocery list, every week, until removed.")
_render_paste_in_section(conn, week_plan_id=None, key_prefix="recurring")
_render_manage_list(conn, items=list_manual_items(conn), key_prefix="recurring_manage")
