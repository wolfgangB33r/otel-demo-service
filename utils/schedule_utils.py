import json
from datetime import datetime, timedelta
from pathlib import Path

from croniter import croniter


def _load_control_data(control_file: Path) -> dict:
    if not control_file.exists():
        return {}

    try:
        with open(control_file, "r") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_rpm(control_file: Path, default: int = 10) -> int:
    control_data = _load_control_data(control_file)
    try:
        rpm = int(control_data.get("rpm", default))
    except (TypeError, ValueError):
        return default
    return max(1, min(rpm, 1000))


def get_active_patterns(control_file: Path, available_patterns: list[str]) -> dict:
    control_data = _load_control_data(control_file)

    active = {}
    for pattern in available_patterns:
        if bool(control_data.get(pattern, False)):
            active[pattern] = True

    now = datetime.now()
    schedules = control_data.get("schedules", [])
    if not isinstance(schedules, list):
        return active

    for entry in schedules:
        if not isinstance(entry, dict):
            continue

        pattern = entry.get("pattern")
        cron_expression = entry.get("cron")
        try:
            duration_minutes = int(entry.get("duration_minutes", 0))
        except (TypeError, ValueError):
            continue

        if pattern not in available_patterns or not cron_expression or duration_minutes < 1:
            continue

        if not croniter.is_valid(cron_expression):
            continue

        try:
            anchor = now.replace(second=59, microsecond=999999)
            last_trigger = croniter(cron_expression, anchor).get_prev(datetime)
        except Exception:
            continue

        end_time = last_trigger + timedelta(minutes=duration_minutes)
        if last_trigger <= now < end_time:
            active[pattern] = True

    return active
