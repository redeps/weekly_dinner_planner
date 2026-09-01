"""
Milestone 4 tests: plan generation scoring and generation
(services/plan_generation.py).
"""

import datetime as dt
import random

import pytest

import database
import models
from models import CalendarDay
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


def test_generate_week_plan_avoids_repeats_when_enough_recipes(conn):
    for i in range(7):
        make_recipe(conn, name=f"Recipe {i}")
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar(), rng=random.Random(3)
    )
    days = plan_service.list_plan_days(conn, week_plan_id)
    assert len({d.recipe_id for d in days}) == 7


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
