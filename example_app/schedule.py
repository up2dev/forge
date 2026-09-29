"""
example_app/schedule.py
========================
Les tâches planifiées de l'app — un seul endroit, déclaratif. Exécutées
par `scripts/schedule.py` (voir forge/scheduler.py pour la syntaxe cron).
"""
from forge.config import get_settings
from forge.scheduler import Schedule
from forge.security import password_reset

schedule = Schedule(get_settings().scheduler_timezone)

schedule.task(
    "prune-password-reset-tokens",
    "0 3 * * *",
    password_reset.purge_expired,
    "Supprime les liens de reset de mot de passe expirés",
)
