import asyncio
import functools
from datetime import datetime, timedelta, timezone

import pytest

from forge.scheduler import CronError, CronExpression, Schedule


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def sync(fn):
    """Exécute un test async via asyncio.run — comme le reste de la suite,
    sans plugin pytest-asyncio."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


# ------------------------------------------------------------------ cron


def test_every_minute_matches_everything():
    assert CronExpression("* * * * *").matches(utc(2026, 9, 28, 5, 17))


def test_step_matches_only_multiples():
    cron = CronExpression("*/15 * * * *")

    assert [cron.matches(utc(2026, 9, 28, 5, m)) for m in (0, 10, 15, 30, 45, 50)] == [
        True, False, True, True, True, False,
    ]


def test_list_range_and_stepped_range():
    assert CronExpression("0,30 * * * *").matches(utc(2026, 9, 28, 5, 30))
    assert not CronExpression("0,30 * * * *").matches(utc(2026, 9, 28, 5, 15))
    assert CronExpression("0 9-17 * * *").matches(utc(2026, 9, 28, 17, 0))
    assert not CronExpression("0 9-17 * * *").matches(utc(2026, 9, 28, 18, 0))
    assert CronExpression("0-30/10 * * * *").minutes == {0, 10, 20, 30}
    assert CronExpression("5/20 * * * *").minutes == {5, 25, 45}


def test_weekday_zero_and_seven_are_both_sunday():
    sunday = utc(2026, 9, 27, 0, 0)  # un dimanche

    assert CronExpression("0 0 * * 0").matches(sunday)
    assert CronExpression("0 0 * * 7").matches(sunday)
    assert not CronExpression("0 0 * * 1").matches(sunday)
    assert CronExpression("0 0 * * 1").matches(utc(2026, 9, 28, 0, 0))  # lundi


def test_day_of_month_or_weekday_when_both_restricted():
    """Comme le cron classique : l'un OU l'autre, pas les deux."""
    cron = CronExpression("0 0 1 * 1")  # le 1er OU un lundi

    assert cron.matches(utc(2026, 9, 28, 0, 0))  # lundi, pas le 1er
    assert cron.matches(utc(2026, 10, 1, 0, 0))  # jeudi 1er
    assert not cron.matches(utc(2026, 9, 29, 0, 0))  # mardi 29


def test_aliases():
    assert CronExpression("@daily").matches(utc(2026, 9, 28, 0, 0))
    assert not CronExpression("@daily").matches(utc(2026, 9, 28, 0, 1))
    assert CronExpression("@hourly").matches(utc(2026, 9, 28, 7, 0))
    assert CronExpression("@weekly").matches(utc(2026, 9, 27, 0, 0))
    assert CronExpression("@monthly").matches(utc(2026, 10, 1, 0, 0))
    assert CronExpression("@yearly").matches(utc(2027, 1, 1, 0, 0))


@pytest.mark.parametrize(
    "bad",
    ["* * * *", "* * * * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *",
     "*/0 * * * *", "a * * * *", "5-1 * * * *", "1,,2 * * * *", ""],
)
def test_invalid_expressions_rejected(bad):
    with pytest.raises(CronError):
        CronExpression(bad)


def test_next_after():
    cron = CronExpression("0 3 * * *")

    assert cron.next_after(utc(2026, 9, 28, 5, 0)) == utc(2026, 9, 29, 3, 0)
    assert cron.next_after(utc(2026, 9, 28, 2, 59, 30)) == utc(2026, 9, 28, 3, 0)
    assert cron.next_after(utc(2026, 9, 28, 3, 0)) == utc(2026, 9, 29, 3, 0)  # strictement après


def test_next_after_month_and_leap_day():
    assert CronExpression("0 0 1 1 *").next_after(utc(2026, 9, 28, 0, 0)) == utc(2027, 1, 1, 0, 0)
    assert CronExpression("0 0 29 2 *").next_after(utc(2026, 9, 28, 0, 0)) == utc(2028, 2, 29, 0, 0)


def test_next_after_impossible_date_is_none():
    assert CronExpression("0 0 31 2 *").next_after(utc(2026, 9, 28, 0, 0)) is None


# -------------------------------------------------------------- schedule


def test_duplicate_task_name_rejected():
    schedule = Schedule()
    schedule.task("a", "* * * * *", lambda: None)

    with pytest.raises(ValueError):
        schedule.task("a", "* * * * *", lambda: None)


def test_invalid_cron_rejected_at_declaration():
    """Une faute de frappe plante au démarrage, pas à 3h du matin."""
    with pytest.raises(CronError):
        Schedule().task("a", "not a cron", lambda: None)


def test_due_uses_configured_timezone():
    schedule = Schedule("Europe/Paris")
    schedule.task("nuit", "0 3 * * *", lambda: None)

    # 28/09/2026 : heure d'été (UTC+2) -> 3h à Paris = 01:00 UTC
    assert [t.name for t in schedule.due(utc(2026, 9, 28, 1, 0))] == ["nuit"]
    assert schedule.due(utc(2026, 9, 28, 3, 0)) == []
    # 15/01/2026 : heure d'hiver (UTC+1) -> 3h à Paris = 02:00 UTC
    assert [t.name for t in schedule.due(utc(2026, 1, 15, 2, 0))] == ["nuit"]


def test_due_ignores_seconds():
    schedule = Schedule()
    schedule.task("a", "30 12 * * *", lambda: None)

    assert len(schedule.due(utc(2026, 9, 28, 12, 30, 45))) == 1


@sync
async def test_run_due_runs_async_and_sync_tasks():
    calls = []

    async def async_task():
        calls.append("async")

    def sync_task():
        calls.append("sync")

    schedule = Schedule()
    schedule.task("a", "* * * * *", async_task)
    schedule.task("b", "* * * * *", sync_task)
    schedule.task("pas-due", "0 0 1 1 *", lambda: calls.append("jamais"))

    results = await schedule.run_due(utc(2026, 9, 28, 12, 0))

    assert results == {"a": "ok", "b": "ok"}
    assert sorted(calls) == ["async", "sync"]


@sync
async def test_failing_task_does_not_stop_others():
    ran = []

    async def boom():
        raise RuntimeError("kaboom")

    async def fine():
        ran.append("fine")

    schedule = Schedule()
    schedule.task("boom", "* * * * *", boom)
    schedule.task("fine", "* * * * *", fine)

    results = await schedule.run_due(utc(2026, 9, 28, 12, 0))

    assert results == {"boom": "failed", "fine": "ok"}
    assert ran == ["fine"]


@sync
async def test_overlapping_run_of_same_task_is_skipped():
    gate = asyncio.Event()
    runs = []

    async def slow():
        runs.append(1)
        await gate.wait()

    schedule = Schedule()
    schedule.task("slow", "* * * * *", slow)

    first = asyncio.create_task(schedule.run_due(utc(2026, 9, 28, 12, 0)))
    await asyncio.sleep(0.01)  # laisse la première exécution démarrer
    second = await schedule.run_due(utc(2026, 9, 28, 12, 1))

    assert second == {"slow": "skipped"}

    gate.set()
    assert await first == {"slow": "ok"}
    assert runs == [1]


@sync
async def test_running_flag_reset_after_failure():
    async def boom():
        raise RuntimeError

    schedule = Schedule()
    task = schedule.task("boom", "* * * * *", boom)

    await schedule.run_due(utc(2026, 9, 28, 12, 0))

    assert task.running is False


# ------------------------------------------------------------------ work


def _fake_clock(start, step_seconds=60):
    state = {"now": start}

    def now_fn():
        current = state["now"]
        state["now"] = current + timedelta(seconds=step_seconds)

        return current

    return now_fn


@sync
async def test_work_skips_startup_minute_then_runs_each_minute():
    runs = []
    schedule = Schedule()
    schedule.task("tick", "* * * * *", lambda: runs.append(1))
    stop = asyncio.Event()

    async def stopper():
        while len(runs) < 3:
            await asyncio.sleep(0.005)

        stop.set()

    stopper_task = asyncio.create_task(stopper())
    await asyncio.wait_for(
        schedule.work(stop, now_fn=_fake_clock(utc(2026, 9, 28, 12, 0)), max_wait=0.001), timeout=5
    )
    await stopper_task

    assert len(runs) >= 3


@sync
async def test_work_runs_a_given_minute_only_once():
    """Deux réveils dans la même minute (gigue d'horloge) ne doivent pas
    doubler l'exécution."""
    runs = []
    schedule = Schedule()
    schedule.task("tick", "* * * * *", lambda: runs.append(1))
    stop = asyncio.Event()
    # pas de 20s : 3 réveils par minute
    clock = _fake_clock(utc(2026, 9, 28, 12, 0), step_seconds=20)
    calls = {"n": 0}

    def counting_clock():
        calls["n"] += 1

        if calls["n"] > 12:  # ~4 minutes simulées
            stop.set()

        return clock()

    await asyncio.wait_for(schedule.work(stop, now_fn=counting_clock, max_wait=0.001), timeout=5)

    # 12 réveils de 20s = minutes 12:01 à 12:04 (la minute de démarrage,
    # 12:00, est sautée) : exactement 4, malgré 3 réveils par minute.
    assert len(runs) == 4


@sync
async def test_work_stop_waits_for_running_task():
    """Un arrêt (SIGTERM) pendant qu'une tâche tourne attend sa fin."""
    finished = []
    started = asyncio.Event()

    async def slow():
        started.set()
        await asyncio.sleep(0.05)
        finished.append(1)

    schedule = Schedule()
    schedule.task("slow", "* * * * *", slow)
    stop = asyncio.Event()

    async def stopper():
        await started.wait()
        stop.set()  # arrêt demandé alors que la tâche tourne encore

    stopper_task = asyncio.create_task(stopper())
    await asyncio.wait_for(
        schedule.work(stop, now_fn=_fake_clock(utc(2026, 9, 28, 12, 0)), max_wait=0.001), timeout=5
    )
    await stopper_task

    assert finished == [1]


# --------------------------------------------------------- app schedule


@sync
async def test_app_schedule_prunes_expired_reset_tokens(client):
    """La vraie tâche déclarée dans example_app/schedule.py, contre la base."""
    from sqlalchemy import select

    from example_app.schedule import schedule
    from forge.db import get_session
    from forge.security.models import PasswordResetToken, User

    async with get_session() as session:
        user = User(login="a", email="a@x.test", password_hash="x", is_active=True)
        session.add(user)
        await session.flush()
        session.add_all([
            PasswordResetToken(token_hash="old", user_id=user.id, expires_at=datetime.now(timezone.utc) - timedelta(hours=1)),
        ])
        await session.commit()

    results = await schedule.run_due(utc(2026, 9, 28, 3, 0))

    assert results == {"prune-password-reset-tokens": "ok"}

    async with get_session() as session:
        assert (await session.execute(select(PasswordResetToken))).scalars().all() == []
