"""
Milestone 4 tests: plan generation scoring and generation
(services/plan_generation.py).
"""

import collections
import datetime as dt
import random

import pytest

import database
import models
from models import CalendarDay
from services import ingredients as ingredient_service
from services import plan_generation as plan_service
from services import recipes as recipe_service


@pytest.fixture
def conn(tmp_path):
    connection = database.get_connection(identity=tmp_path)
    yield connection
    schema = database.schema_name_for(tmp_path)
    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


def make_recipe(conn, **overrides):
    fields = dict(
        name="Test Recipe",
        cook_time_minutes=30,
        family_enjoyment=3,
        seasonality="all-season",
        servings=4,
    )
    fields.update(overrides)
    recipe_id = recipe_service.create_recipe(conn, **fields)
    return recipe_service.get_recipe(conn, recipe_id)


def default_calendar(*, busy_days=()):
    return [
        CalendarDay(
            day_of_week=day,
            is_busy=day in busy_days,
            dinner_ready_time=dt.time(18, 0),
        )
        for day in models.DAYS_OF_WEEK
    ]


# --- current_season ---


@pytest.mark.parametrize(
    "month,expected",
    [
        (12, "winter"), (1, "winter"), (2, "winter"),
        (3, "spring"), (4, "spring"), (5, "spring"),
        (6, "summer"), (7, "summer"), (8, "summer"),
        (9, "fall"), (10, "fall"), (11, "fall"),
    ],
)
def test_current_season_maps_month_to_season(month, expected):
    assert plan_service.current_season(dt.date(2026, month, 15)) == expected


# --- last_cooked_dates ---


def test_last_cooked_dates_empty_table(conn):
    assert plan_service.last_cooked_dates(conn) == {}


def test_last_cooked_dates_returns_max_per_recipe(conn):
    recipe = make_recipe(conn)
    conn.execute(
        "INSERT INTO cook_history (recipe_id, cooked_on) VALUES (%s, %s)",
        (recipe.id, "2026-08-01"),
    )
    conn.execute(
        "INSERT INTO cook_history (recipe_id, cooked_on) VALUES (%s, %s)",
        (recipe.id, "2026-08-20"),
    )
    conn.commit()
    result = plan_service.last_cooked_dates(conn)
    assert result[recipe.id] == dt.date(2026, 8, 20)


def test_last_cooked_dates_omits_recipes_never_cooked(conn):
    recipe = make_recipe(conn)
    assert recipe.id not in plan_service.last_cooked_dates(conn)


# --- score_recipe: seasonality ---


def test_score_recipe_prefers_seasonal_match_over_all_season(conn):
    today = dt.date(2026, 1, 15)
    seasonal = make_recipe(conn, seasonality="winter")
    all_season = make_recipe(conn, seasonality="all-season")
    kwargs = dict(season="winter", is_busy=False, last_cooked=None, today=today)
    assert plan_service.score_recipe(seasonal, **kwargs) > plan_service.score_recipe(
        all_season, **kwargs
    )


def test_score_recipe_prefers_all_season_over_off_season(conn):
    today = dt.date(2026, 1, 15)
    all_season = make_recipe(conn, seasonality="all-season")
    off_season = make_recipe(conn, seasonality="summer")
    kwargs = dict(season="winter", is_busy=False, last_cooked=None, today=today)
    assert plan_service.score_recipe(all_season, **kwargs) > plan_service.score_recipe(
        off_season, **kwargs
    )


# --- score_recipe: rotation ---


def test_score_recipe_penalizes_recently_cooked_within_window(conn):
    recipe = make_recipe(conn)
    today = dt.date(2026, 8, 31)
    recently_cooked = today - dt.timedelta(days=5)
    never_cooked_score = plan_service.score_recipe(
        recipe, season="all-season", is_busy=False, last_cooked=None, today=today
    )
    recent_score = plan_service.score_recipe(
        recipe, season="all-season", is_busy=False, last_cooked=recently_cooked, today=today
    )
    assert recent_score < never_cooked_score


def test_score_recipe_does_not_penalize_outside_rotation_window(conn):
    recipe = make_recipe(conn)
    today = dt.date(2026, 8, 31)
    long_ago = today - dt.timedelta(days=plan_service.ROTATION_WINDOW_DAYS + 1)
    never_cooked_score = plan_service.score_recipe(
        recipe, season="all-season", is_busy=False, last_cooked=None, today=today
    )
    old_score = plan_service.score_recipe(
        recipe, season="all-season", is_busy=False, last_cooked=long_ago, today=today
    )
    assert old_score == never_cooked_score


# --- score_recipe: busy day / cook time ---


def test_score_recipe_prefers_quick_recipe_on_busy_day(conn):
    today = dt.date(2026, 8, 31)
    quick = make_recipe(conn, cook_time_minutes=10)
    slow = make_recipe(conn, cook_time_minutes=60)
    kwargs = dict(season="all-season", last_cooked=None, today=today)
    assert plan_service.score_recipe(
        quick, is_busy=True, **kwargs
    ) > plan_service.score_recipe(slow, is_busy=True, **kwargs)


def test_score_recipe_cook_time_irrelevant_on_non_busy_day(conn):
    today = dt.date(2026, 8, 31)
    quick = make_recipe(conn, cook_time_minutes=10)
    slow = make_recipe(conn, cook_time_minutes=60)
    kwargs = dict(season="all-season", last_cooked=None, today=today, is_busy=False)
    assert plan_service.score_recipe(quick, **kwargs) == plan_service.score_recipe(
        slow, **kwargs
    )


# --- score_recipe: quick-fallback bonus on busy days ---


def test_score_recipe_boosts_quick_fallback_beyond_plain_quick_recipe_on_busy_day(conn):
    """Both recipes are already <= BUSY_DAY_QUICK_THRESHOLD_MINUTES, so
    both get BUSY_DAY_QUICK_WEIGHT — is_quick_fallback must add a further,
    stacked boost on top of that, not just match it."""
    today = dt.date(2026, 8, 31)
    quick_fallback = make_recipe(conn, cook_time_minutes=15, is_quick_fallback=True)
    plain_quick = make_recipe(conn, cook_time_minutes=15, is_quick_fallback=False)
    kwargs = dict(season="all-season", is_busy=True, last_cooked=None, today=today)
    assert plan_service.score_recipe(
        quick_fallback, **kwargs
    ) > plan_service.score_recipe(plain_quick, **kwargs)


def test_score_recipe_busy_day_bonus_does_not_leak_into_non_busy_day(conn):
    """BUSY_DAY_QUICK_FALLBACK_BONUS must not affect a non-busy day at
    all — the non-busy-day score should differ from an otherwise-identical
    plain recipe's by exactly NON_BUSY_DAY_QUICK_FALLBACK_PENALTY, not by
    some other (e.g. leaked-bonus) factor."""
    today = dt.date(2026, 8, 31)
    quick_fallback = make_recipe(conn, cook_time_minutes=15, is_quick_fallback=True)
    plain = make_recipe(conn, cook_time_minutes=15, is_quick_fallback=False)
    kwargs = dict(season="all-season", is_busy=False, last_cooked=None, today=today)
    quick_fallback_score = plan_service.score_recipe(quick_fallback, **kwargs)
    plain_score = plan_service.score_recipe(plain, **kwargs)
    assert quick_fallback_score == pytest.approx(
        plain_score * plan_service.NON_BUSY_DAY_QUICK_FALLBACK_PENALTY
    )


def test_rotation_penalty_still_measurably_affects_quick_fallback_selection(conn):
    """Confirms the new BUSY_DAY_QUICK_FALLBACK_BONUS doesn't swamp rotation
    avoidance: a quick-fallback recipe cooked recently must still be
    measurably less likely to be picked than one that wasn't, on a busy
    day, matching the real Takeout-cooked-2-days-ago finding from the
    investigation (see docs/DECISIONS.md)."""
    today = dt.date(2026, 8, 31)
    recently_cooked = make_recipe(
        conn, name="Recently Cooked Fallback", cook_time_minutes=0, is_quick_fallback=True
    )
    fresh = make_recipe(
        conn, name="Fresh Fallback", cook_time_minutes=15, is_quick_fallback=True
    )
    rng = random.Random(0)
    picks = [
        plan_service.choose_recipe(
            [recently_cooked, fresh],
            season="all-season",
            is_busy=True,
            last_cooked_by_recipe={recently_cooked.id: today - dt.timedelta(days=2)},
            today=today,
            rng=rng,
        )
        for _ in range(500)
    ]
    recently_cooked_count = sum(1 for p in picks if p.id == recently_cooked.id)
    fresh_count = sum(1 for p in picks if p.id == fresh.id)
    assert fresh_count > recently_cooked_count, (
        "rotation avoidance must still measurably favor the not-recently-"
        "cooked quick-fallback recipe, even under the new busy-day bonus"
    )


# --- score_recipe: enjoyment tie-breaker ---


def test_score_recipe_increases_monotonically_with_enjoyment(conn):
    today = dt.date(2026, 8, 31)
    scores = [
        plan_service.score_recipe(
            make_recipe(conn, family_enjoyment=stars),
            season="all-season",
            is_busy=False,
            last_cooked=None,
            today=today,
        )
        for stars in (1, 2, 3, 4, 5)
    ]
    assert scores == sorted(scores)
    assert scores[0] < scores[-1]


# --- choose_recipe ---


def test_choose_recipe_favors_higher_weighted_candidate_across_trials(conn):
    today = dt.date(2026, 1, 15)
    favored = make_recipe(conn, name="Favored", seasonality="winter", family_enjoyment=5)
    disfavored = make_recipe(
        conn, name="Disfavored", seasonality="summer", family_enjoyment=1
    )
    rng = random.Random(0)
    picks = [
        plan_service.choose_recipe(
            [favored, disfavored],
            season="winter",
            is_busy=False,
            last_cooked_by_recipe={},
            today=today,
            rng=rng,
        )
        for _ in range(200)
    ]
    favored_count = sum(1 for p in picks if p.id == favored.id)
    assert favored_count > 150  # heavily favored by weight; not a guaranteed argmax


def test_choose_recipe_returns_the_only_candidate(conn):
    only = make_recipe(conn)
    rng = random.Random(0)
    result = plan_service.choose_recipe(
        [only],
        season="all-season",
        is_busy=False,
        last_cooked_by_recipe={},
        today=dt.date(2026, 8, 31),
        rng=rng,
    )
    assert result.id == only.id


# --- generate_week_plan ---


def test_generate_week_plan_raises_with_no_recipes(conn):
    with pytest.raises(ValueError):
        plan_service.generate_week_plan(
            conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar()
        )


def test_generate_week_plan_creates_seven_days_in_order(conn):
    for i in range(3):
        make_recipe(conn, name=f"Recipe {i}")
    week_start = dt.date(2026, 8, 31)  # a Monday
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=week_start, calendar=default_calendar(), rng=random.Random(1)
    )
    days = plan_service.list_plan_days(conn, week_plan_id)
    assert len(days) == 7
    assert [d.day_of_week for d in days] == list(models.DAYS_OF_WEEK)
    assert [d.date for d in days] == [
        (week_start + dt.timedelta(days=i)).isoformat() for i in range(7)
    ]
    assert all(d.recipe_id is not None for d in days)


def test_generate_week_plan_carries_calendar_input_per_day(conn):
    make_recipe(conn)
    calendar = default_calendar(busy_days={"wednesday"})
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["wednesday"].dinner_ready_time = dt.time(17, 0)

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(2)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    assert days["wednesday"].is_busy is True
    assert days["wednesday"].dinner_ready_time == "17:00"
    assert days["monday"].is_busy is False
    assert days["monday"].dinner_ready_time == "18:00"


def test_generate_week_plan_carries_household_size_override_per_day(conn):
    make_recipe(conn)
    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["wednesday"].household_size_override = 8

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(20)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    assert days["wednesday"].household_size_override == 8
    assert days["monday"].household_size_override is None


def test_generate_week_plan_avoids_repeats_when_enough_recipes(conn):
    for i in range(7):
        make_recipe(conn, name=f"Recipe {i}")
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(3)
    )
    days = plan_service.list_plan_days(conn, week_plan_id)
    assert len({d.recipe_id for d in days}) == 7


def test_generate_week_plan_falls_back_without_repeats_when_busy_days_exceed_quick_fallback_recipes(
    conn,
):
    """More busy days (4) than distinct quick-fallback recipes (3) - the
    scenario flagged in docs/DECISIONS.md as the reason for testing this
    explicitly, not just relying on the 2,000-trial simulation from the
    investigation. The generator must still avoid repeats and fill every
    day, falling back to a non-quick-fallback recipe for the day(s) past
    the quick-fallback supply rather than forcing a repeat or leaving a
    day unfilled."""
    for i in range(3):
        make_recipe(conn, name=f"Quick Fallback {i}", cook_time_minutes=15, is_quick_fallback=True)
    for i in range(8):
        make_recipe(conn, name=f"Regular Recipe {i}", cook_time_minutes=45, is_quick_fallback=False)

    calendar = default_calendar(busy_days={"monday", "wednesday", "friday", "saturday"})
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(1)
    )
    days = plan_service.list_plan_days(conn, week_plan_id)

    assert len(days) == 7
    assert all(d.recipe_id is not None for d in days)
    assert len({d.recipe_id for d in days}) == 7, "no repeat within the week, despite 4 busy days"


def test_generate_week_plan_full_non_busy_week_never_forces_repeat_or_unfilled_day(conn):
    """Regression test for NON_BUSY_DAY_QUICK_FALLBACK_PENALTY, shaped like
    the real dev DB (8 non-quick-fallback / 3 quick-fallback recipes,
    matching the investigation's own numbers) — a full 7-day, 0-busy-day
    week must still never repeat or leave a day unfilled despite the new
    penalty pushing weight heavily away from 3 of the 11 recipes."""
    for i in range(3):
        make_recipe(conn, name=f"Quick Fallback {i}", cook_time_minutes=15, is_quick_fallback=True)
    for i in range(8):
        make_recipe(conn, name=f"Regular Recipe {i}", cook_time_minutes=30, is_quick_fallback=False)

    for seed in range(20):
        week_plan_id = plan_service.generate_week_plan(
            conn,
            week_start_date=dt.date(2026, 8, 31),
            calendar=default_calendar(),  # no busy days
            rng=random.Random(seed),
        )
        days = plan_service.list_plan_days(conn, week_plan_id)
        assert len(days) == 7
        assert all(d.recipe_id is not None for d in days)
        assert len({d.recipe_id for d in days}) == 7, f"repeat occurred at seed={seed}"


# --- generate_week_plan: special-occasion hard exclusion (Part 3) ---


def test_generate_week_plan_never_auto_selects_special_occasion_recipes(conn):
    for i in range(3):
        make_recipe(conn, name=f"Special {i}", is_special_occasion=True)
    for i in range(8):
        make_recipe(conn, name=f"Regular {i}", is_special_occasion=False)

    for seed in range(20):
        week_plan_id = plan_service.generate_week_plan(
            conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(seed)
        )
        days = plan_service.list_plan_days(conn, week_plan_id)
        assert len(days) == 7
        assert all(d.recipe_id is not None for d in days)
        assert len({d.recipe_id for d in days}) == 7
        chosen_names = {
            recipe_service.get_recipe(conn, d.recipe_id).name for d in days
        }
        assert not any(name.startswith("Special") for name in chosen_names), (
            f"a special-occasion recipe was auto-selected at seed={seed}: {chosen_names}"
        )


def test_generate_week_plan_raises_when_only_special_occasion_recipes_exist(conn):
    make_recipe(conn, name="Holiday Roast", is_special_occasion=True)
    with pytest.raises(ValueError):
        plan_service.generate_week_plan(
            conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar()
        )


def test_swap_day_recipe_can_select_a_special_occasion_recipe(conn):
    """Swap's candidate pool must NOT exclude is_special_occasion — only
    automatic generation does."""
    original = make_recipe(conn, name="Original")
    special = make_recipe(conn, name="Holiday Roast", is_special_occasion=True)
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(0)
    )
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    # Only two recipes exist total, and Monday is necessarily `original`
    # (generate_week_plan can't have auto-picked `special`) -- so the
    # special-occasion recipe is the *only* swap candidate. If swap
    # filtered it out like generate_week_plan does, this would raise
    # (empty candidate list falling back to the unfiltered list would
    # re-include `original`, which `choose_recipe` could then return
    # instead -- so a passing assertion here specifically proves the
    # special-occasion recipe was a real, reachable candidate).
    assert monday.recipe_id == original.id
    result = plan_service.swap_day_recipe(conn, monday.id, rng=random.Random(0))
    assert result.id == special.id
    assert result.is_special_occasion is True


# --- generate_week_plan: direct assignment via CalendarDay.assigned_recipe_id ---


def test_generate_week_plan_places_assigned_recipe_with_no_scoring(conn):
    for i in range(8):
        make_recipe(conn, name=f"Regular {i}")
    special = make_recipe(conn, name="Holiday Roast", is_special_occasion=True)

    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].assigned_recipe_id = special.id

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    assert days["monday"].recipe_id == special.id


def test_generate_week_plan_falls_back_when_assigned_recipe_is_missing(conn):
    make_recipe(conn, name="Regular")
    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].assigned_recipe_id = 999999  # no such recipe

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    assert days["monday"].recipe_id is not None  # fell back to normal scoring, not a crash


def test_generate_week_plan_falls_back_when_assigned_recipe_is_deactivated(conn):
    make_recipe(conn, name="Regular")
    special = make_recipe(conn, name="Holiday Roast", is_special_occasion=True)
    recipe_service.deactivate_recipe(conn, special.id)

    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].assigned_recipe_id = special.id

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    assert days["monday"].recipe_id != special.id


def test_generate_week_plan_assignment_does_not_consume_a_slot_or_force_repeat(conn):
    """A pre-assigned special-occasion recipe must not be treated as part
    of the normal pool: exactly 7 regular recipes exist (the minimum
    needed for a repeat-free week on their own) plus one special-occasion
    recipe assigned to Monday. Monday's assignment must not shrink the
    pool available to the other 6 (auto-generated) days -- if it wrongly
    did, those 6 days would still have exactly enough regular recipes (7)
    to stay repeat-free, so this wouldn't even catch a bug by itself;
    what it does confirm is the pool used for the 6 auto-generated days
    is the full, undiminished 7 regular recipes (all recipe_ids are drawn
    from `regulars`, and Monday's own id -- the special-occasion one --
    is never among them, confirming it was never added to the pool
    `used_recipe_ids` draws exclusions from)."""
    regulars = [make_recipe(conn, name=f"Regular {i}") for i in range(7)]
    special = make_recipe(conn, name="Holiday Roast", is_special_occasion=True)

    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].assigned_recipe_id = special.id

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    days = plan_service.list_plan_days(conn, week_plan_id)
    recipe_ids = [d.recipe_id for d in days]
    assert len(recipe_ids) == 7
    assert len(set(recipe_ids)) == 7, "no repeat among the 6 auto-generated days"
    monday = next(d for d in days if d.day_of_week == "monday")
    assert monday.recipe_id == special.id
    other_ids = {d.recipe_id for d in days if d.day_of_week != "monday"}
    assert len(other_ids) == 6
    assert other_ids <= {r.id for r in regulars}, "auto-generated days drew only from the regular pool"


# --- plan_day_dishes: attach_dish / detach_dish / list_dishes (Milestone 16 Phase 2) ---


def _make_plan_day(conn):
    make_recipe(conn, name="Main")
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(0)
    )
    return plan_service.list_plan_days(conn, week_plan_id)[0]


def test_attach_dish_creates_attachment(conn):
    plan_day = _make_plan_day(conn)
    side = make_recipe(conn, name="Salad", course="side")
    plan_service.attach_dish(conn, plan_day.id, side.id)
    assert [d.id for d in plan_service.list_dishes(conn, plan_day.id)] == [side.id]


def test_attach_dish_is_a_noop_when_already_attached(conn):
    """UNIQUE(plan_day_id, recipe_id) must not surface as a raised
    constraint violation -- attaching an already-attached recipe is a
    clean no-op (ON CONFLICT DO NOTHING)."""
    plan_day = _make_plan_day(conn)
    side = make_recipe(conn, name="Salad", course="side")
    plan_service.attach_dish(conn, plan_day.id, side.id)
    plan_service.attach_dish(conn, plan_day.id, side.id)  # must not raise
    assert [d.id for d in plan_service.list_dishes(conn, plan_day.id)] == [side.id]


def test_detach_dish_removes_attachment(conn):
    plan_day = _make_plan_day(conn)
    side = make_recipe(conn, name="Salad", course="side")
    plan_service.attach_dish(conn, plan_day.id, side.id)
    plan_service.detach_dish(conn, plan_day.id, side.id)
    assert plan_service.list_dishes(conn, plan_day.id) == []


def test_detach_dish_is_a_noop_when_not_attached(conn):
    plan_day = _make_plan_day(conn)
    side = make_recipe(conn, name="Salad", course="side")
    plan_service.detach_dish(conn, plan_day.id, side.id)  # must not raise
    assert plan_service.list_dishes(conn, plan_day.id) == []


def test_list_dishes_filters_by_course(conn):
    plan_day = _make_plan_day(conn)
    side = make_recipe(conn, name="Salad", course="side")
    dessert = make_recipe(conn, name="Crumble", course="dessert")
    plan_service.attach_dish(conn, plan_day.id, side.id)
    plan_service.attach_dish(conn, plan_day.id, dessert.id)

    assert [d.id for d in plan_service.list_dishes(conn, plan_day.id, course="side")] == [side.id]
    assert [d.id for d in plan_service.list_dishes(conn, plan_day.id, course="dessert")] == [dessert.id]
    assert {d.id for d in plan_service.list_dishes(conn, plan_day.id)} == {side.id, dessert.id}


def test_list_dishes_ordered_by_name(conn):
    plan_day = _make_plan_day(conn)
    z = make_recipe(conn, name="Zucchini Salad", course="side")
    a = make_recipe(conn, name="Apple Coleslaw", course="side")
    plan_service.attach_dish(conn, plan_day.id, z.id)
    plan_service.attach_dish(conn, plan_day.id, a.id)
    assert [d.name for d in plan_service.list_dishes(conn, plan_day.id)] == [
        "Apple Coleslaw", "Zucchini Salad",
    ]


def test_attaching_the_same_recipe_to_two_different_days_is_independent(conn):
    make_recipe(conn, name="Main")
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(0)
    )
    days = plan_service.list_plan_days(conn, week_plan_id)
    side = make_recipe(conn, name="Salad", course="side")
    plan_service.attach_dish(conn, days[0].id, side.id)
    assert [d.id for d in plan_service.list_dishes(conn, days[0].id)] == [side.id]
    assert plan_service.list_dishes(conn, days[1].id) == []


# --- generate_week_plan: side/dessert attachment via CalendarDay (Milestone 16 Phase 2) ---


def test_generate_week_plan_attaches_staged_sides_and_desserts(conn):
    make_recipe(conn, name="Main")
    side = make_recipe(conn, name="Salad", course="side")
    dessert = make_recipe(conn, name="Crumble", course="dessert")

    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].side_recipe_ids = [side.id]
    calendar_by_day["monday"].dessert_recipe_ids = [dessert.id]

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    monday_dishes = {d.id for d in plan_service.list_dishes(conn, days["monday"].id)}
    assert monday_dishes == {side.id, dessert.id}
    assert plan_service.list_dishes(conn, days["tuesday"].id) == []


def test_generate_week_plan_supports_multiple_sides_on_one_day(conn):
    make_recipe(conn, name="Main")
    salad = make_recipe(conn, name="Salad", course="side")
    pudding = make_recipe(conn, name="Yorkshire Pudding", course="side")

    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["sunday"].side_recipe_ids = [salad.id, pudding.id]

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    sunday_names = {d.name for d in plan_service.list_dishes(conn, days["sunday"].id)}
    assert sunday_names == {"Salad", "Yorkshire Pudding"}


def test_generate_week_plan_skips_deactivated_staged_dish_without_failing(conn):
    make_recipe(conn, name="Main")
    side = make_recipe(conn, name="Salad", course="side")
    recipe_service.deactivate_recipe(conn, side.id)

    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].side_recipe_ids = [side.id]

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    assert plan_service.list_dishes(conn, days["monday"].id) == []  # skipped, not raised


def test_generate_week_plan_skips_missing_staged_dish_without_failing(conn):
    make_recipe(conn, name="Main")
    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].side_recipe_ids = [999999]  # no such recipe

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
    assert plan_service.list_dishes(conn, days["monday"].id) == []


# --- swap_day_recipe: attachments survive a main-recipe swap ---
# (Milestone 16 Phase 2 regression -- proving the Phase 1 investigation's
# finding that swap_day_recipe() only ever updates plan_days.recipe_id,
# rather than continuing to trust that analysis without a direct test.)


def test_swap_day_recipe_leaves_plan_day_dishes_untouched(conn):
    for i in range(3):
        make_recipe(conn, name=f"Main {i}")
    side = make_recipe(conn, name="Salad", course="side")

    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].side_recipe_ids = [side.id]

    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(0)
    )
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    assert [d.id for d in plan_service.list_dishes(conn, monday.id)] == [side.id]

    original_main_id = monday.recipe_id
    result = plan_service.swap_day_recipe(conn, monday.id, rng=random.Random(1))
    assert result.id != original_main_id  # swap excludes the current recipe -- it did change

    assert [d.id for d in plan_service.list_dishes(conn, monday.id)] == [side.id], (
        "swapping a day's main recipe must not touch its plan_day_dishes attachments"
    )


def test_generate_week_plan_allows_repeats_when_recipe_pool_too_small(conn):
    make_recipe(conn, name="Only One")
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(4)
    )
    days = plan_service.list_plan_days(conn, week_plan_id)
    assert len(days) == 7
    assert all(d.recipe_id is not None for d in days)


def test_generate_week_plan_failure_partway_through_leaves_no_partial_plan(conn, monkeypatch):
    """Under autocommit=True (see docs/DECISIONS.md), each INSERT lands on
    its own by default — generate_week_plan wraps the week_plans + 7x
    plan_days sequence in `with conn.transaction():` so a failure partway
    through the week can't leave an orphan week_plans row with only some
    of its days. Forces a failure the database/app doesn't otherwise
    produce (current_season raising on the 4th day) to prove the rollback
    covers the whole sequence, not just the failing statement."""
    make_recipe(conn, name="Recipe A")
    make_recipe(conn, name="Recipe B")

    real_current_season = plan_service.current_season
    calls = {"n": 0}

    def flaky_current_season(for_date):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("simulated failure partway through the week")
        return real_current_season(for_date)

    monkeypatch.setattr(plan_service, "current_season", flaky_current_season)

    before_week_plans = conn.execute("SELECT COUNT(*) FROM week_plans").fetchone()[0]
    before_plan_days = conn.execute("SELECT COUNT(*) FROM plan_days").fetchone()[0]

    with pytest.raises(RuntimeError):
        plan_service.generate_week_plan(
            conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar()
        )

    after_week_plans = conn.execute("SELECT COUNT(*) FROM week_plans").fetchone()[0]
    after_plan_days = conn.execute("SELECT COUNT(*) FROM plan_days").fetchone()[0]
    assert after_week_plans == before_week_plans, "the orphan week_plans row must be rolled back too"
    assert after_plan_days == before_plan_days


def test_get_latest_week_plan_returns_most_recent(conn):
    make_recipe(conn)
    first_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 24), calendar=default_calendar(), rng=random.Random(5)
    )
    second_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(6)
    )
    latest = plan_service.get_latest_week_plan(conn)
    assert latest.id == second_id
    assert latest.id != first_id


def test_get_latest_week_plan_returns_none_when_no_plans(conn):
    assert plan_service.get_latest_week_plan(conn) is None


def test_get_week_plan_returns_none_for_missing_id(conn):
    assert plan_service.get_week_plan(conn, 999) is None


# --- get_plan_day ---


def test_get_plan_day_returns_none_for_missing_id(conn):
    assert plan_service.get_plan_day(conn, 999) is None


def test_get_plan_day_returns_correct_row(conn):
    make_recipe(conn)
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(7)
    )
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    fetched = plan_service.get_plan_day(conn, monday.id)
    assert fetched == monday


# --- swap_day_recipe ---


def test_swap_day_recipe_raises_for_missing_plan_day(conn):
    with pytest.raises(ValueError):
        plan_service.swap_day_recipe(conn, 999)


def test_swap_day_recipe_raises_when_no_active_recipes(conn):
    recipe = make_recipe(conn)
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(8)
    )
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    recipe_service.deactivate_recipe(conn, recipe.id)
    with pytest.raises(ValueError):
        plan_service.swap_day_recipe(conn, monday.id)


def test_swap_day_recipe_excludes_the_swapped_out_recipe(conn):
    original = make_recipe(conn, name="Original")
    replacement = make_recipe(conn, name="Replacement")
    week_plan_id = plan_service.generate_week_plan(
        conn,
        week_start_date=dt.date(2026, 8, 31),
        calendar=default_calendar(),
        rng=random.Random(0),
    )
    days = plan_service.list_plan_days(conn, week_plan_id)
    monday = next(d for d in days if d.day_of_week == "monday")
    original_recipe_id = monday.recipe_id

    new_recipe = plan_service.swap_day_recipe(conn, monday.id, rng=random.Random(9))

    assert new_recipe.id != original_recipe_id
    assert new_recipe.id in (original.id, replacement.id)
    updated = plan_service.get_plan_day(conn, monday.id)
    assert updated.recipe_id == new_recipe.id


def test_swap_day_recipe_only_changes_that_day(conn):
    for i in range(3):
        make_recipe(conn, name=f"Recipe {i}")
    week_plan_id = plan_service.generate_week_plan(
        conn,
        week_start_date=dt.date(2026, 8, 31),
        calendar=default_calendar(),
        rng=random.Random(10),
    )
    before = {d.id: d.recipe_id for d in plan_service.list_plan_days(conn, week_plan_id)}
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )

    plan_service.swap_day_recipe(conn, monday.id, rng=random.Random(11))

    after = {d.id: d.recipe_id for d in plan_service.list_plan_days(conn, week_plan_id)}
    for plan_day_id, original_recipe_id in before.items():
        if plan_day_id == monday.id:
            continue
        assert after[plan_day_id] == original_recipe_id, "swap must not touch other days"


def test_swap_day_recipe_falls_back_to_same_recipe_when_it_is_the_only_option(conn):
    only = make_recipe(conn, name="Only One")
    week_plan_id = plan_service.generate_week_plan(
        conn,
        week_start_date=dt.date(2026, 8, 31),
        calendar=default_calendar(),
        rng=random.Random(12),
    )
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    result = plan_service.swap_day_recipe(conn, monday.id, rng=random.Random(13))
    assert result.id == only.id


def test_swap_day_recipe_applies_candidate_filter(conn):
    original = make_recipe(conn, name="Original")
    make_recipe(conn, name="Not Chosen")
    preferred = make_recipe(conn, name="Preferred")
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(14)
    )
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    plan_service.swap_day_recipe(
        conn, monday.id, rng=random.Random(15),
        candidate_filter=lambda candidates: [r for r in candidates if r.id == preferred.id],
    )
    updated = plan_service.get_plan_day(conn, monday.id)
    assert updated.recipe_id == preferred.id


def test_swap_day_recipe_ignores_a_filter_that_returns_empty(conn):
    make_recipe(conn, name="A")
    make_recipe(conn, name="B")
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(16)
    )
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    # A filter returning [] must not break the swap — falls back to the
    # unfiltered candidate list.
    result = plan_service.swap_day_recipe(
        conn, monday.id, rng=random.Random(17), candidate_filter=lambda candidates: []
    )
    assert result is not None


def test_swap_day_recipe_ignores_a_filter_that_raises(conn):
    make_recipe(conn, name="A")
    make_recipe(conn, name="B")
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(18)
    )
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )

    def broken_filter(candidates):
        raise RuntimeError("simulated AI assist failure")

    result = plan_service.swap_day_recipe(
        conn, monday.id, rng=random.Random(19), candidate_filter=broken_filter
    )
    assert result is not None


# --- ingredient-overlap bonus (docs/DECISIONS.md) ---


def test_score_recipe_overlap_bonus_increases_weight(conn):
    recipe = make_recipe(conn)
    kwargs = dict(season="all-season", is_busy=False, last_cooked=None, today=dt.date(2026, 8, 31))
    no_overlap = plan_service.score_recipe(recipe, overlap_count=0, **kwargs)
    with_overlap = plan_service.score_recipe(recipe, overlap_count=2, **kwargs)
    assert with_overlap == pytest.approx(
        no_overlap * (1 + plan_service.INGREDIENT_OVERLAP_BONUS) ** 2
    )


def test_choose_recipe_favors_recipe_sharing_committed_ingredients(conn):
    overlapping = make_recipe(conn, name="Overlapping")
    plain = make_recipe(conn, name="Plain")
    canonical_ingredients_by_recipe = {
        overlapping.id: frozenset({"parmesan"}),
        plain.id: frozenset({"salt"}),
    }
    committed = frozenset({"parmesan"})
    rng = random.Random(0)
    picks = [
        plan_service.choose_recipe(
            [overlapping, plain],
            season="all-season",
            is_busy=False,
            last_cooked_by_recipe={},
            today=dt.date(2026, 8, 31),
            rng=rng,
            canonical_ingredients_by_recipe=canonical_ingredients_by_recipe,
            committed_canonical_ingredients=committed,
        )
        for _ in range(200)
    ]
    overlapping_count = sum(1 for p in picks if p.id == overlapping.id)
    plain_count = sum(1 for p in picks if p.id == plain.id)
    assert overlapping_count > plain_count


def test_choose_recipe_defaults_to_no_overlap_bonus_when_not_provided(conn):
    """Confirms swap_day_recipe's existing call shape (no
    canonical_ingredients_by_recipe / committed_canonical_ingredients
    passed) is completely unaffected -- two otherwise-identical recipes
    stay evenly matched when the new parameters are simply omitted."""
    a = make_recipe(conn, name="A")
    b = make_recipe(conn, name="B")
    rng = random.Random(0)
    picks = [
        plan_service.choose_recipe(
            [a, b],
            season="all-season",
            is_busy=False,
            last_cooked_by_recipe={},
            today=dt.date(2026, 8, 31),
            rng=rng,
        )
        for _ in range(200)
    ]
    a_count = sum(1 for p in picks if p.id == a.id)
    assert 60 < a_count < 140  # roughly even, no bonus favoring either


def test_choose_recipe_empty_ingredient_recipe_never_gets_overlap_bonus(conn):
    """A recipe with no ingredients (e.g. a quick-fallback recipe) has an
    empty canonical set, so it can never share anything with the
    committed set -- confirmed structurally, not assumed, by pitting it
    against a recipe that genuinely does overlap."""
    quick = make_recipe(conn, name="Quick")  # no ingredients ever added
    overlapping = make_recipe(conn, name="Overlapping")
    canonical_ingredients_by_recipe = {
        quick.id: frozenset(),
        overlapping.id: frozenset({"beef stock"}),
    }
    committed = frozenset({"beef stock"})
    rng = random.Random(0)
    picks = [
        plan_service.choose_recipe(
            [quick, overlapping],
            season="all-season",
            is_busy=False,
            last_cooked_by_recipe={},
            today=dt.date(2026, 8, 31),
            rng=rng,
            canonical_ingredients_by_recipe=canonical_ingredients_by_recipe,
            committed_canonical_ingredients=committed,
        )
        for _ in range(200)
    ]
    quick_count = sum(1 for p in picks if p.id == quick.id)
    overlapping_count = sum(1 for p in picks if p.id == overlapping.id)
    assert overlapping_count > quick_count


# --- _staple_canonical_ingredients (dynamic threshold) ---


def test_staple_canonical_ingredients_excludes_at_or_above_threshold():
    canonical_ingredients_by_recipe = {
        1: frozenset({"garlic", "onion", "parmesan"}),
        2: frozenset({"garlic", "onion"}),
        3: frozenset({"garlic", "beef stock"}),
        4: frozenset({"garlic", "crème fraîche"}),
    }
    # garlic: 4/4 = 100%, onion: 2/4 = 50%, others: 1/4 = 25% each
    staples = plan_service._staple_canonical_ingredients(canonical_ingredients_by_recipe)
    assert staples == frozenset({"garlic", "onion"})
    assert "parmesan" not in staples
    assert "beef stock" not in staples
    assert "crème fraîche" not in staples


def test_staple_canonical_ingredients_ignores_empty_recipes_in_denominator():
    canonical_ingredients_by_recipe = {
        1: frozenset({"garlic"}),
        2: frozenset(),  # e.g. a quick-fallback recipe -- must not dilute the denominator
        3: frozenset(),
    }
    # garlic is in 1 of the 1 non-empty recipe (100%), not 1 of 3 (33%)
    staples = plan_service._staple_canonical_ingredients(canonical_ingredients_by_recipe)
    assert staples == frozenset({"garlic"})


def test_staple_canonical_ingredients_empty_input_returns_empty():
    assert plan_service._staple_canonical_ingredients({}) == frozenset()
    assert plan_service._staple_canonical_ingredients({1: frozenset()}) == frozenset()


def test_staple_canonical_ingredients_matches_real_dev_db_staples(conn):
    """Regression test against the real staples found during
    investigation: with the real dev-DB-shaped recipe set (garlic/onion
    common, parmesan/beef stock/crème fraîche rare), the dynamic
    threshold must land on the same staple set the investigation found
    (garlic, onion) and must NOT exclude the genuinely distinctive
    overlap ingredients."""
    real_shaped = [
        ("Beef stroganoff", ["beef stock", "butter", "crème fraîche", "garlic", "onion"]),
        ("Chicken fajitas", ["cherry tomatoes", "garlic", "olive oil", "red onion"]),
        ("Creamy mushroom pasta", ["butter", "garlic", "olive oil", "onion", "parmesan"]),
        ("Easy chicken curry", ["garlic", "onion", "tomatoes"]),
        ("Easy classic lasagne", ["garlic", "olive oil", "onion", "parmesan", "tomatoes"]),
        ("Mushroom risotto", ["butter", "garlic", "olive oil", "onion", "parmesan"]),
        ("No-fuss shepherd's pie", ["beef stock", "butter", "onion"]),
        ("Thai green curry", ["garlic"]),
    ]
    canonical_ingredients_by_recipe = {}
    for name, ingredients in real_shaped:
        r = make_recipe(conn, name=name)
        ingredient_service.replace_recipe_ingredients(
            conn, r.id, [{"name": ing, "store_category": "pantry"} for ing in ingredients]
        )
        canonical_ingredients_by_recipe[r.id] = frozenset(ingredients)

    staples = plan_service._staple_canonical_ingredients(canonical_ingredients_by_recipe)
    # Matches the investigation's own hardcoded-proxy staple list exactly,
    # confirmed here as the *dynamic* threshold's real output against
    # this real-shaped 8-recipe pool (garlic 7/8, onion 6/8, olive oil
    # 4/8, butter 4/8 -- all >= the 50% threshold).
    assert staples == frozenset({"garlic", "onion", "olive oil", "butter"})
    for distinctive in ("parmesan", "beef stock", "crème fraîche", "tomatoes"):
        assert distinctive not in staples


# --- generate_week_plan: overlap-aware, integration level ---


def test_generate_week_plan_never_forces_repeat_or_unfilled_day_with_overlap_bonus_active(conn):
    """Regression test with real overlapping ingredient data (so the
    overlap bonus is genuinely active, not trivially zero) -- a full
    7-day week must still never repeat a recipe or leave a day unfilled,
    even at exactly the 7-recipe no-repeat boundary."""
    shared_groups = [
        ["parmesan"], ["parmesan"], ["parmesan"],
        ["beef stock"], ["beef stock"],
        ["unique-a"],
        ["unique-b"],
    ]
    for i, ingredients in enumerate(shared_groups):
        r = make_recipe(conn, name=f"Recipe {i}")
        ingredient_service.replace_recipe_ingredients(
            conn, r.id, [{"name": ing, "store_category": "pantry"} for ing in ingredients]
        )

    for seed in range(20):
        week_plan_id = plan_service.generate_week_plan(
            conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(seed)
        )
        days = plan_service.list_plan_days(conn, week_plan_id)
        assert len(days) == 7
        assert all(d.recipe_id is not None for d in days)
        assert len({d.recipe_id for d in days}) == 7, f"repeat occurred at seed={seed}"


def test_generate_week_plan_pre_assigned_special_occasion_day_excluded_from_overlap(conn):
    """Regression test: a pre-assigned special-occasion day's ingredients
    must never enter the overlap accumulator. Monday is pre-assigned a
    special-occasion recipe sharing "parmesan" with one of the 7
    auto-generation candidates -- if that leaked into the accumulator,
    the matching candidate would be picked noticeably more than the other
    6 on Tuesday (the first auto-generated day, with no other prior
    context). Confirmed via simulation, not a single deterministic call,
    matching this project's existing standard for weighted-random
    behavior."""
    special = make_recipe(conn, name="Special", is_special_occasion=True)
    ingredient_service.replace_recipe_ingredients(
        conn, special.id, [{"name": "parmesan", "store_category": "dairy"}]
    )

    matching = make_recipe(conn, name="Matching")
    ingredient_service.replace_recipe_ingredients(
        conn, matching.id, [{"name": "parmesan", "store_category": "dairy"}]
    )
    others = []
    for i in range(6):
        r = make_recipe(conn, name=f"Other {i}")
        ingredient_service.replace_recipe_ingredients(
            conn, r.id, [{"name": f"unique-{i}", "store_category": "pantry"}]
        )
        others.append(r)

    calendar = default_calendar()
    calendar_by_day = {d.day_of_week: d for d in calendar}
    calendar_by_day["monday"].assigned_recipe_id = special.id

    candidates = [matching.id] + [r.id for r in others]
    tuesday_picks = collections.Counter()
    n_trials = 300
    for seed in range(n_trials):
        week_plan_id = plan_service.generate_week_plan(
            conn, week_start_date=dt.date(2026, 8, 31), calendar=calendar, rng=random.Random(seed)
        )
        days = {d.day_of_week: d for d in plan_service.list_plan_days(conn, week_plan_id)}
        tuesday_picks[days["tuesday"].recipe_id] += 1

    assert set(tuesday_picks.keys()) <= set(candidates)
    counts = [tuesday_picks[cid] for cid in candidates]
    expected_even_share = n_trials / len(candidates)
    # If Monday's pre-assignment had wrongly fed the accumulator,
    # `matching` would be picked roughly 2x as often as the other 6 --
    # clearly distinguishable from the even ~1/7 share expected here.
    assert max(counts) < 2 * expected_even_share
