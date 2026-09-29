#!/usr/bin/env python3
"""
scripts/schedule.py
====================
Runner des tâches planifiées déclarées dans example_app/schedule.py.

    python scripts/schedule.py list   # tâches et prochaine exécution
    python scripts/schedule.py run    # exécute les tâches dues maintenant, puis sort
    python scripts/schedule.py work   # boucle, se réveille à chaque minute

`work` = le conteneur `scheduler` du docker-compose (UNE seule instance :
deux runners exécuteraient chaque tâche deux fois). `run` = à appeler
toutes les minutes par un cron système / un CronJob Kubernetes si tu
préfères ne pas garder de processus en continu.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
from datetime import datetime, timezone

from forge.logs import setup_logging

from example_app.schedule import schedule


def _list() -> None:
    now = datetime.now(timezone.utc).astimezone(schedule.tz)
    print(f"{'TÂCHE':<34}{'CRON':<14}{'PROCHAINE EXÉCUTION (' + str(schedule.tz) + ')':<40}DESCRIPTION")

    for task in schedule.tasks():
        upcoming = task.cron.next_after(now)
        when = upcoming.strftime("%Y-%m-%d %H:%M") if upcoming else "jamais"
        print(f"{task.name:<34}{task.cron.expression:<14}{when:<40}{task.description}")


async def _run() -> None:
    results = await schedule.run_due()

    if not results:
        print("Aucune tâche due à cette minute.")

    for name, status in results.items():
        print(f"{name}: {status}")


async def _work() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)  # arrêt propre : finit les tâches en cours

    await schedule.work(stop)


def main() -> None:
    parser = argparse.ArgumentParser(description="Planificateur de tâches Forge")
    parser.add_argument("command", choices=["list", "run", "work"])
    command = parser.parse_args().command

    setup_logging()

    if command == "list":
        _list()
    elif command == "run":
        asyncio.run(_run())
    else:
        asyncio.run(_work())


if __name__ == "__main__":
    main()
