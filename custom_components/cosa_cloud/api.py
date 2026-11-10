"""Small Cosa cloud client; no logging of credentials or device payloads."""
from __future__ import annotations

import asyncio
import math

BASE_URL = "https://kiwi-api.nuvia.com.tr"
PATHS = {
    "login": "/api/users/login",
    "devices": "/api/endpoints/getEndpoints",
    "device": "/api/endpoints/getEndpoint",
    "mode": "/api/endpoints/setMode",
    "temperature": "/api/endpoints/setTargetTemperatures",
    "schedule": "/api/endpoints/setSchedule",
}

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SCHEDULE_PRESETS = frozenset(("home", "away", "sleep"))


class CosaError(Exception):
    """A safe error message that contains no server payload."""


class CosaAuthError(CosaError):
    """Account authentication is required."""


class CosaResponseError(CosaError):
    """Server rejected a request."""


class CosaPartialUpdateError(CosaError):
    """The temperature was saved but switching mode failed."""


def number(value, minimum=None, maximum=None):
    """Missing, boolean, non-finite and out-of-range readings stay unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        finite = math.isfinite(value)
    except OverflowError:
        return None
    if not finite:
        return None
    if minimum is not None and value < minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def normalize_schedule(schedule):
    """Validate a complete Cosa week before allowing a write."""
    if not isinstance(schedule, dict) or set(schedule) != set(DAYS):
        raise CosaError("Schedule must contain all seven days")
    normalized = {}
    for day in DAYS:
        slots = schedule[day]
        if not isinstance(slots, dict) or not 1 <= len(slots) <= 48:
            raise CosaError("Each day needs 1 to 48 time slots")
        normalized_slots = {}
        for minute, preset in slots.items():
            if isinstance(minute, bool) or not isinstance(minute, (str, int)):
                raise CosaError("Schedule times must be minutes after midnight")
            minute_text = str(minute)
            if len(minute_text) > 4 or not minute_text.isascii() or not minute_text.isdecimal():
                raise CosaError("Schedule times must be minutes after midnight")
            minute_number = int(minute_text)
            if not 0 <= minute_number < 1440 or not isinstance(preset, str) or preset not in SCHEDULE_PRESETS:
                raise CosaError("Schedule contains an invalid time or preset")
            key = str(minute_number)
            if key in normalized_slots:
                raise CosaError("Schedule contains duplicate times")
            normalized_slots[key] = preset
        if "0" not in normalized_slots:
            raise CosaError("Each day must start at midnight")
        normalized[day] = dict(sorted(normalized_slots.items(), key=lambda item: int(item[0])))
    return normalized


class CosaAPI:
    def __init__(self, session, email: str, password: str):
        self.session = session
        self.email = email
        self.password = password
        self.token = None
        self._lock = asyncio.Lock()
        # Observed control intent only, scoped to a device and this API lifetime.
        # A restart while frozen requires an explicit preset selection.
        self._resume_modes = {}

    async def _request(self, operation, payload):
        headers = {"provider": "cosa", "Accept": "application/json"}
        if operation != "login" and self.token:
            headers["authtoken"] = self.token
        try:
            async with asyncio.timeout(20):
                async with self.session.post(
                    BASE_URL + PATHS[operation], json=payload, headers=headers,
                    allow_redirects=False, timeout=20,
                ) as response:
                    if response.status in (401, 403):
                        raise CosaAuthError("Cosa authentication failed")
                    if response.status != 200:
                        raise CosaError("Cosa service unavailable")
                    data = await response.json()
        except CosaError:
            raise
        except Exception:
            # Do not include exception text, URLs, headers, or response bodies.
            raise CosaError("Cannot communicate with Cosa") from None
        if not isinstance(data, dict) or data.get("ok") not in (1, True):
            if operation == "login":
                raise CosaAuthError("Cosa authentication failed")
            raise CosaResponseError("Cosa rejected the request")
        return data

    async def _login(self):
        data = await self._request("login", {"email": self.email, "password": self.password})
        token = data.get("authToken")
        if not isinstance(token, str) or not token:
            raise CosaAuthError("Cosa did not return an authentication token")
        self.token = token

    async def _read(self, operation, payload):
        if self.token is None:
            await self._login()
        try:
            return await self._request(operation, payload)
        except (CosaAuthError, CosaResponseError):
            # Renew once for read operations. Never automatically repeat writes.
            await self._login()
            return await self._request(operation, payload)

    async def devices(self):
        async with self._lock:
            data = await self._read("devices", {})
        devices = data.get("endpoints")
        if not isinstance(devices, list):
            raise CosaError("Cosa device list is malformed")
        return [d for d in devices if isinstance(d, dict) and isinstance(d.get("id"), str) and d["id"]]

    async def _device(self, endpoint_id):
        data = await self._read("device", {"endpoint": endpoint_id})
        endpoint = data.get("endpoint")
        if not isinstance(endpoint, dict) or not endpoint:
            raise CosaError("Cosa device response is empty or malformed")
        if endpoint.get("id") != endpoint_id:
            raise CosaError("Cosa returned a different device")
        if not isinstance(endpoint.get("device"), dict):
            raise CosaError("Cosa device connection data is missing")
        if endpoint["device"].get("isConnected") is not True:
            return endpoint  # Offline snapshots cannot replace resume intent.
        mode, option = endpoint.get("mode"), endpoint.get("option")
        if mode in ("auto", "schedule"):
            self._resume_modes[endpoint_id] = (mode, None)
        elif mode == "manual" and option in ("home", "away", "sleep", "custom"):
            self._resume_modes[endpoint_id] = (mode, option)
        elif (mode, option) != ("manual", "frozen"):
            # An unsupported observed mode must not revive an older intent.
            self._resume_modes.pop(endpoint_id, None)
        return endpoint

    async def device(self, endpoint_id):
        async with self._lock:
            return await self._device(endpoint_id)

    async def get_schedule(self, endpoint_id):
        async with self._lock:
            endpoint = await self._device(endpoint_id)
            schedule = endpoint.get("schedule")
            if not isinstance(schedule, dict):
                raise CosaError("Cosa did not return a weekly schedule")
            return schedule

    async def set_schedule(self, endpoint_id, schedule):
        normalized = normalize_schedule(schedule)
        async with self._lock:
            endpoint = await self._device(endpoint_id)
            self._require_connected(endpoint)
            await self._request("schedule", {"endpoint": endpoint_id, "schedule": normalized})
            confirmed = await self._device(endpoint_id)
            if confirmed.get("schedule") != normalized:
                raise CosaResponseError("Cosa did not confirm the weekly schedule")
            return normalized

    @staticmethod
    def _require_connected(endpoint):
        if endpoint.get("device", {}).get("isConnected") is not True:
            raise CosaError("Cosa device is not confirmed online")

    async def set_mode(self, endpoint_id, mode, option=None):
        if mode not in ("manual", "auto", "schedule"):
            raise CosaError("Unsupported mode")
        if mode == "manual" and option not in ("home", "away", "sleep", "custom", "frozen"):
            raise CosaError("Unsupported manual preset")
        async with self._lock:
            self._require_connected(await self._device(endpoint_id))
            payload = {"endpoint": endpoint_id, "mode": mode}
            if mode == "manual":
                payload["option"] = option
            await self._request("mode", payload)

    async def set_enabled(self, endpoint_id, enabled):
        """Suspend/resume without selecting a different working profile."""
        if not isinstance(enabled, bool):
            raise CosaError("Enabled must be a boolean")
        async with self._lock:
            endpoint = await self._device(endpoint_id)
            self._require_connected(endpoint)
            frozen = (endpoint.get("mode"), endpoint.get("option")) == ("manual", "frozen")
            if not enabled:
                if frozen:
                    return
                payload = {"endpoint": endpoint_id, "mode": "manual", "option": "frozen"}
            else:
                if not frozen:
                    if endpoint_id in self._resume_modes:
                        return  # Already enabled: preserve the current profile.
                    raise CosaError("Current Cosa mode is unknown; select a preset explicitly")
                previous = self._resume_modes.get(endpoint_id)
                if previous is None:
                    raise CosaError("Previous Cosa profile is unknown; select a preset explicitly")
                mode, option = previous
                payload = {"endpoint": endpoint_id, "mode": mode}
                if mode == "manual":
                    payload["option"] = option
            # Do not retry a write, including a timeout with an unknown outcome.
            await self._request("mode", payload)

    async def set_temperature(self, endpoint_id, temperature):
        if number(temperature, 5, 32) is None:
            raise CosaError("Temperature must be between 5 and 32 Celsius")
        async with self._lock:
            endpoint = await self._device(endpoint_id)
            self._require_connected(endpoint)
            values = {key: number(endpoint.get(key + "Temperature"), 5, 32)
                      for key in ("home", "away", "sleep")}
            if any(value is None for value in values.values()):
                raise CosaError("Existing preset temperatures could not be read; no changes sent")
            values["custom"] = round(temperature, 1)
            await self._request("temperature", {"endpoint": endpoint_id, "targetTemperatures": values})
            try:
                await self._request("mode", {"endpoint": endpoint_id, "mode": "manual", "option": "custom"})
            except CosaError:
                raise CosaPartialUpdateError("Temperature saved; switching to manual mode failed") from None
