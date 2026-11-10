"""Read-only calendar view of the weekly program stored in Cosa."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .api import DAYS, SCHEDULE_PRESETS, number
from .entity import CosaEntity

LABELS = {"home": "Ev", "away": "Dışarı", "sleep": "Uyku"}


def _timezone(endpoint):
    name = endpoint.get("timeZone")
    try:
        return ZoneInfo(name) if isinstance(name, str) else ZoneInfo("Europe/Istanbul")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Istanbul")


def schedule_events(endpoint, start, end):
    """Expand a Cosa week into events in the device's timezone."""
    schedule = endpoint.get("schedule")
    if not isinstance(schedule, dict) or start >= end:
        return []
    tz = _timezone(endpoint)
    active = endpoint.get("mode") == "schedule" and endpoint.get("schedulePresetType") == 4
    description = "Cosa'daki manuel haftalık program" if active else "Cosa'daki kayıtlı program; şu anda etkin değil"
    day = start.astimezone(tz).date() - timedelta(days=1)
    last_day = end.astimezone(tz).date()
    events = []
    while day <= last_day:
        slots = schedule.get(DAYS[day.weekday()])
        if isinstance(slots, dict):
            parsed = []
            for minute, preset in slots.items():
                key = str(minute)
                if (key.isascii() and key.isdecimal() and len(key) <= 4
                        and 0 <= int(key) < 1440 and isinstance(preset, str)
                        and preset in SCHEDULE_PRESETS):
                    parsed.append((int(key), preset))
            parsed.sort()
            for index, (minute, preset) in enumerate(parsed):
                event_start = datetime.combine(day, time.min, tzinfo=tz) + timedelta(minutes=minute)
                event_end = (datetime.combine(day, time.min, tzinfo=tz)
                             + timedelta(minutes=parsed[index + 1][0]) if index + 1 < len(parsed)
                             else datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz))
                if event_start >= end or event_end <= start or event_start >= event_end:
                    continue
                target = number(endpoint.get(preset + "Temperature"), 5, 32)
                summary = LABELS[preset]
                if target is not None:
                    summary += f" · {target:g} °C"
                events.append(CalendarEvent(
                    start=event_start, end=event_end, summary=summary,
                    description=description, uid=f"{day.isoformat()}-{minute}",
                ))
        day += timedelta(days=1)
    return events


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CosaScheduleCalendar(entry.runtime_data)])


class CosaScheduleCalendar(CosaEntity, CalendarEntity):
    """A calendar projection; Cosa remains the only schedule store."""

    _attr_translation_key = "weekly_schedule"

    def __init__(self, coordinator):
        super().__init__(coordinator, "weekly_schedule")

    @property
    def event(self):
        if (self.coordinator.data.get("mode") != "schedule"
                or self.coordinator.data.get("schedulePresetType") != 4):
            return None
        now = dt_util.now()
        return next((event for event in schedule_events(self.coordinator.data,
                     now - timedelta(days=1), now + timedelta(days=2))
                     if event.end > now), None)

    async def async_get_events(self, hass, start_date, end_date):
        return schedule_events(self.coordinator.data, start_date, end_date)
