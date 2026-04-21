from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from typing import Any


@dataclass
class EventOccurrence:
    """
    One concrete occurrence of an event at a specific local datetime.
    """

    event_id: str
    name: str
    event_type: str
    priority: int
    start_at: datetime
    duration_minutes: int
    registration_time_before: int
    details: dict[str, Any]
    source_event: dict[str, Any]
    source_time: str


@dataclass
class EventDisplayItem:
    """
    One computed overlay-ready event item before UI conversion.
    """

    event_id: str
    name: str
    status: str
    seconds_until_start: int
    seconds_until_end: int
    registration_in: int
    color: str
    occurrence_key: str
    source_time: str


class EventEngine:
    """
    Computes upcoming/active event rows from event definitions.

    Event times are defined in server time (GMT+3) and converted to local time.
    """

    SERVER_UTC_OFFSET = 3

    DEFAULT_COLOR = "#d4c5a1"
    REGISTRATION_COLOR = "#FFA500"
    ACTIVE_COLOR = "#33CC66"
    UPCOMING_SOON_COLOR = "#FFD966"

    def __init__(self, events: list[dict[str, Any]]):
        self.events = events or []

    # ============================================================
    # OVERLAY API
    # ============================================================

    def get_display_items(
        self, now: datetime, max_rows: int = 5
    ) -> list[EventDisplayItem]:
        items: list[EventDisplayItem] = []

        for occ in self._build_occurrences_around_now(now):
            item = self._to_display_item(occ, now)
            if item is not None:
                items.append(item)

        items.sort(
            key=lambda item: (
                self._status_sort_key(item.status),
                item.seconds_until_start,
                item.name,
            )
        )
        return items[:max_rows]

    # ============================================================
    # CALENDAR API
    # ============================================================

    def get_week_occurrences(
        self,
        center_day: datetime,
        days: int = 7,
        center_index: int = 3,
    ) -> list[list[EventOccurrence]]:
        """
        Return local occurrences grouped by day.

        Example:
        - days=7
        - center_index=3
        means the returned week is [center_day-3 ... center_day+3]
        so today appears in the middle.
        """
        if center_day.tzinfo is not None:
            local_center = center_day.astimezone().replace(tzinfo=None)
        else:
            local_center = center_day

        start_date = local_center.date() - timedelta(days=center_index)
        grouped: list[list[EventOccurrence]] = [[] for _ in range(days)]

        for offset in range(days):
            target_day = start_date + timedelta(days=offset)
            occurrences = self._build_occurrences_for_local_date(target_day)
            occurrences.sort(key=lambda occ: occ.start_at)
            grouped[offset] = occurrences

        return grouped

    # ============================================================
    # OCCURRENCE BUILDING
    # ============================================================

    def _build_occurrences_around_now(self, now: datetime) -> list[EventOccurrence]:
        """
        Build occurrences for previous / current / next week around `now`.
        Good for overlay logic.
        """
        out: list[EventOccurrence] = []

        if now.tzinfo is not None:
            local_now = now.astimezone().replace(tzinfo=None)
        else:
            local_now = now

        for event in self.events:
            normalized = self._normalize_event(event)
            if normalized is None:
                continue

            event_id = normalized["event_id"]
            name = normalized["name"]
            event_type = normalized["event_type"]
            priority = normalized["priority"]
            duration_minutes = normalized["duration_minutes"]
            registration_time_before = normalized["registration_time_before"]
            details = normalized["details"]
            source_event = normalized["source_event"]
            times = normalized["times"]
            days = normalized["days"]

            for json_day in days:
                for time_str in times:
                    base_start = self._build_occurrence_datetime(local_now, json_day, time_str)
                    if base_start is None:
                        continue

                    for week_shift in (-1, 0, 1):
                        shifted_start = base_start + timedelta(days=7 * week_shift)
                        out.append(
                            EventOccurrence(
                                event_id=event_id,
                                name=name,
                                event_type=event_type,
                                priority=priority,
                                start_at=shifted_start,
                                duration_minutes=duration_minutes,
                                registration_time_before=registration_time_before,
                                details=details,
                                source_event=source_event,
                                source_time=time_str,
                            )
                        )

        return out

    def _build_occurrences_for_local_date(self, target_date: date) -> list[EventOccurrence]:
        """
        Build all occurrences that actually happen on a specific LOCAL date.
        """
        out: list[EventOccurrence] = []

        for event in self.events:
            normalized = self._normalize_event(event)
            if normalized is None:
                continue

            event_id = normalized["event_id"]
            name = normalized["name"]
            event_type = normalized["event_type"]
            priority = normalized["priority"]
            duration_minutes = normalized["duration_minutes"]
            registration_time_before = normalized["registration_time_before"]
            details = normalized["details"]
            source_event = normalized["source_event"]
            times = normalized["times"]
            days = normalized["days"]

            for json_day in days:
                for time_str in times:
                    local_start = self._build_occurrence_datetime_for_local_date(
                        target_date,
                        json_day,
                        time_str,
                    )
                    if local_start is None:
                        continue

                    out.append(
                        EventOccurrence(
                            event_id=event_id,
                            name=name,
                            event_type=event_type,
                            priority=priority,
                            start_at=local_start,
                            duration_minutes=duration_minutes,
                            registration_time_before=registration_time_before,
                            details=details,
                            source_event=source_event,
                            source_time=time_str,
                        )
                    )

        return out

    # ============================================================
    # DISPLAY CONVERSION
    # ============================================================

    def _to_display_item(
        self, occ: EventOccurrence, now: datetime
    ) -> EventDisplayItem | None:
        if now.tzinfo is not None:
            now = now.astimezone().replace(tzinfo=None)

        start_at = occ.start_at
        end_at = start_at + timedelta(minutes=occ.duration_minutes)

        seconds_until_start = int((start_at - now).total_seconds())
        seconds_until_end = int((end_at - now).total_seconds())
        registration_in = seconds_until_start - (occ.registration_time_before * 60)

        if occ.duration_minutes > 0 and seconds_until_end <= 0:
            return None
        if occ.duration_minutes == 0 and seconds_until_start < 0:
            return None

        if occ.duration_minutes > 0 and seconds_until_start <= 0:
            status = "active"
            color = self.ACTIVE_COLOR
        elif (
            occ.registration_time_before > 0
            and registration_in <= 0
            and seconds_until_start > 0
        ):
            status = "registration"
            color = self.REGISTRATION_COLOR
        elif 0 < seconds_until_start <= 600:
            status = "upcoming_soon"
            color = self.UPCOMING_SOON_COLOR
        else:
            status = "upcoming"
            color = self.DEFAULT_COLOR

        return EventDisplayItem(
            event_id=occ.event_id,
            name=occ.name,
            status=status,
            seconds_until_start=max(seconds_until_start, 0),
            seconds_until_end=max(seconds_until_end, 0),
            registration_in=max(registration_in, 0),
            color=color,
            occurrence_key=f"{occ.event_id}|{occ.start_at.isoformat()}",
            source_time=occ.source_time,
        )

    # ============================================================
    # DATETIME BUILDING
    # ============================================================

    def _build_occurrence_datetime(
        self, now: datetime, json_weekday: int, time_str: str
    ) -> datetime | None:
        """
        Build one LOCAL datetime for an event occurrence in the current local week,
        based on JSON weekday (0=Sunday ... 6=Saturday) and server time HH:MM.
        """
        try:
            hour, minute = map(int, time_str.split(":"))
        except Exception:
            return None

        python_weekday = self._json_weekday_to_python(json_weekday)

        current_weekday = now.weekday()
        day_offset = python_weekday - current_weekday
        target_date = (now + timedelta(days=day_offset)).date()

        return self._server_date_time_to_local_datetime(target_date, hour, minute)

    def _build_occurrence_datetime_for_local_date(
        self,
        target_date: date,
        json_weekday: int,
        time_str: str,
    ) -> datetime | None:
        """
        Build one LOCAL datetime for a given local target date only if:
        - event belongs to that local date after server->local conversion
        """
        try:
            hour, minute = map(int, time_str.split(":"))
        except Exception:
            return None

        for delta_days in (-1, 0, 1):
            server_date = target_date + timedelta(days=delta_days)

            if self._server_date_json_weekday(server_date) != json_weekday:
                continue

            local_dt = self._server_date_time_to_local_datetime(server_date, hour, minute)
            if local_dt is not None and local_dt.date() == target_date:
                return local_dt

        return None

    def _server_date_time_to_local_datetime(
        self,
        server_date: date,
        hour: int,
        minute: int,
    ) -> datetime | None:
        try:
            server_dt = datetime(
                year=server_date.year,
                month=server_date.month,
                day=server_date.day,
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
                tzinfo=timezone(timedelta(hours=self.SERVER_UTC_OFFSET)),
            )
            local_dt = server_dt.astimezone()
            return local_dt.replace(tzinfo=None)
        except Exception:
            return None

    # ============================================================
    # NORMALIZATION / MAPPING
    # ============================================================

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_id = str(event.get("id", "")).strip()
        name = str(event.get("name", "")).strip()
        event_type = str(event.get("type", "Event")).strip()
        priority = int(event.get("priority", 999))
        duration_minutes = max(0, int(event.get("duration_minutes", 0)))
        registration_time_before = max(0, int(event.get("registration_time_before", 0)))
        details = event.get("details", {}) or {}

        if not event_id or not name:
            return None

        times = self._normalize_times(event.get("time"))
        days = self._normalize_days(event.get("days"))

        if not times or not days:
            return None

        return {
            "event_id": event_id,
            "name": name,
            "event_type": event_type,
            "priority": priority,
            "duration_minutes": duration_minutes,
            "registration_time_before": registration_time_before,
            "details": details,
            "source_event": event,
            "times": times,
            "days": days,
        }

    def _normalize_times(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return []

    def _normalize_days(self, value: Any) -> list[int]:
        if isinstance(value, int):
            return [value]
        if isinstance(value, list):
            out = []
            for v in value:
                try:
                    out.append(int(v))
                except Exception:
                    continue
            return out
        return []

    def _json_weekday_to_python(self, json_weekday: int) -> int:
        """
        JSON uses:
            0=Sunday, 1=Monday, ..., 6=Saturday
        Python uses:
            0=Monday, ..., 6=Sunday
        """
        return (json_weekday) % 7

    def _server_date_json_weekday(self, server_date: date) -> int:
        """
        Convert Python weekday/date into JSON weekday system.
        Python: Monday=0 ... Sunday=6
        JSON:   Sunday=0 ... Saturday=6
        """
        return (server_date.weekday()) % 7

    def _status_sort_key(self, status: str) -> int:
        order = {
            "active": 0,
            "registration": 1,
            "upcoming_soon": 2,
            "upcoming": 3,
        }
        return order.get(status, 99)