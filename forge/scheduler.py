"""
forge.scheduler
================
Tâches planifiées déclaratives, à la `schedule:run` de Laravel : on
déclare les tâches une fois (nom, expression cron, fonction), un
runner dédié les exécute à la bonne minute.

    schedule = Schedule("Europe/Paris")
    schedule.task("purge", "0 3 * * *", password_reset.purge_expired)

Deux façons de l'exécuter (voir scripts/schedule.py) :
  - `run`  : exécute les tâches dues MAINTENANT, puis sort — pour un
             cron système ou un CronJob Kubernetes toutes les minutes.
  - `work` : boucle qui se réveille à chaque minute — pour un conteneur
             dédié (une seule instance, pas dans les workers de l'API,
             sinon chaque worker exécuterait chaque tâche).

Cron 5 champs (minute heure jour-du-mois mois jour-de-semaine), avec
`*`, listes (`1,15`), intervalles (`9-17`), pas (`*/5`, `0-30/10`) et
alias (`@hourly`, `@daily`, `@weekly`, `@monthly`, `@yearly`).
Jour-du-mois ET jour-de-semaine renseignés : l'un OU l'autre suffit,
comme le cron classique.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger("forge.scheduler")

_ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
}


class CronError(ValueError):
    """Expression cron invalide."""


def _parse_field(text: str, low: int, high: int) -> set[int]:
    values: set[int] = set()

    for part in text.split(","):
        range_part, _, step_text = part.partition("/")
        step = 1

        if step_text:
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"pas invalide : '{part}'")

            step = int(step_text)

        try:
            if range_part == "*":
                start, end = low, high
            elif "-" in range_part:
                first, _, last = range_part.partition("-")
                start, end = int(first), int(last)
            else:
                start = int(range_part)
                end = high if step_text else start
        except ValueError:
            raise CronError(f"valeur invalide : '{part}'") from None

        if not (low <= start <= high and low <= end <= high and start <= end):
            raise CronError(f"hors limites ({low}-{high}) : '{part}'")

        values.update(range(start, end + 1, step))

    return values


class CronExpression:
    def __init__(self, expression: str) -> None:
        self.expression = expression
        fields = _ALIASES.get(expression.strip(), expression).split()

        if len(fields) != 5:
            raise CronError(f"5 champs attendus, {len(fields)} reçus : '{expression}'")

        self.minutes = _parse_field(fields[0], 0, 59)
        self.hours = _parse_field(fields[1], 0, 23)
        self.days = _parse_field(fields[2], 1, 31)
        self.months = _parse_field(fields[3], 1, 12)
        # 7 = dimanche aussi, ramené à 0.
        self.weekdays = {d % 7 for d in _parse_field(fields[4], 0, 7)}
        self._days_restricted = not fields[2].startswith("*")
        self._weekdays_restricted = not fields[4].startswith("*")

    def _day_matches(self, dt: datetime) -> bool:
        day_ok = dt.day in self.days
        weekday_ok = (dt.isoweekday() % 7) in self.weekdays  # dimanche = 0

        if self._days_restricted and self._weekdays_restricted:
            return day_ok or weekday_ok

        return day_ok and weekday_ok

    def matches(self, dt: datetime) -> bool:
        return (
            dt.minute in self.minutes
            and dt.hour in self.hours
            and dt.month in self.months
            and self._day_matches(dt)
        )

    def next_after(self, dt: datetime, years: int = 5) -> datetime | None:
        """Prochaine minute correspondante strictement après `dt` (heure
        murale, comme cron). None si rien dans les `years` prochaines
        années (ex. `0 0 31 2 *`)."""
        current = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = current + timedelta(days=366 * years)

        while current < limit:
            if current.month not in self.months:
                current = (current.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            elif not self._day_matches(current):
                current = current.replace(hour=0, minute=0) + timedelta(days=1)
            elif current.hour not in self.hours:
                current = current.replace(minute=0) + timedelta(hours=1)
            elif current.minute not in self.minutes:
                current += timedelta(minutes=1)
            else:
                return current

        return None


@dataclass
class Task:
    name: str
    cron: CronExpression
    func: Callable[[], Any]
    description: str = ""
    running: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Schedule:
    def __init__(self, tz: str = "UTC") -> None:
        self.tz = ZoneInfo(tz)
        self._tasks: dict[str, Task] = {}

    def task(self, name: str, cron: str, func: Callable[[], Any], description: str = "") -> Task:
        if name in self._tasks:
            raise ValueError(f"Tâche déjà déclarée : '{name}'")

        task = Task(name, CronExpression(cron), func, description)
        self._tasks[name] = task

        return task

    def tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def due(self, now: datetime) -> list[Task]:
        local = now.astimezone(self.tz).replace(second=0, microsecond=0)

        return [t for t in self._tasks.values() if t.cron.matches(local)]

    async def _run(self, task: Task) -> str:
        if task.running:
            logger.warning("Tâche '%s' ignorée : l'exécution précédente n'est pas finie", task.name)
            return "skipped"

        task.running = True
        started = time.perf_counter()

        try:
            if inspect.iscoroutinefunction(task.func):
                await task.func()
            else:
                result = await asyncio.to_thread(task.func)

                if inspect.isawaitable(result):
                    await result

            logger.info("Tâche '%s' terminée en %.0f ms", task.name, (time.perf_counter() - started) * 1000)

            return "ok"
        except Exception:
            # Une tâche qui plante ne doit jamais empêcher les autres,
            # ni tuer le runner.
            logger.exception("Tâche '%s' en échec", task.name)

            return "failed"
        finally:
            task.running = False

    async def run_due(self, now: datetime | None = None) -> dict[str, str]:
        """Exécute les tâches dues à `now` (maintenant par défaut) et
        attend leur fin. Renvoie {nom: "ok" | "failed" | "skipped"}."""
        due = self.due(now or _utc_now())
        results = await asyncio.gather(*(self._run(t) for t in due))

        return {t.name: r for t, r in zip(due, results)}

    async def work(
        self,
        stop: asyncio.Event | None = None,
        *,
        now_fn: Callable[[], datetime] = _utc_now,
        max_wait: float | None = None,
    ) -> None:
        """Boucle : se réveille à chaque début de minute. La minute en
        cours au démarrage est volontairement sautée — un redémarrage à
        03:00:30 ne doit pas relancer les tâches de 03:00. `max_wait`
        (tests) plafonne l'attente entre deux réveils."""
        stop = stop or asyncio.Event()
        pending: set[asyncio.Task] = set()
        last_minute = now_fn().replace(second=0, microsecond=0)
        logger.info("Planificateur démarré : %d tâche(s)", len(self._tasks))

        try:
            while not stop.is_set():
                now = now_fn()
                minute = now.replace(second=0, microsecond=0)

                if minute != last_minute:
                    last_minute = minute
                    # Lancée sans attendre : une tâche longue ne retarde
                    # pas la minute suivante (le chevauchement de la même
                    # tâche est refusé dans _run).
                    running = asyncio.create_task(self.run_due(minute))
                    pending.add(running)
                    running.add_done_callback(pending.discard)

                delay = 60 - now.second - now.microsecond / 1e6 + 0.05

                if max_wait is not None:
                    delay = min(delay, max_wait)

                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
        finally:
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            logger.info("Planificateur arrêté")
