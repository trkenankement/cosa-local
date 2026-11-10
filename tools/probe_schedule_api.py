"""Compare authenticated Cosa schedule and nonexistent routes safely.

Set COSA_EMAIL and COSA_PASSWORD in the process environment. This probe never
uses a real endpoint ID and never sends a schedule, so it cannot change a
thermostat's weekly program. It prints only status and API result codes.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid


BASE = "https://kiwi-api.nuvia.com.tr"


def request(path: str, payload: dict, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "provider": "cosa"}
    if token:
        headers["authtoken"] = token
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.load(error)
        except (ValueError, UnicodeDecodeError):
            return error.code, {}


def result(label: str, status: int, data: dict) -> None:
    print(f"{label}: HTTP {status}; ok={data.get('ok')!r}; code={data.get('code')!r}")


def main() -> int:
    email = os.environ.get("COSA_EMAIL")
    password = os.environ.get("COSA_PASSWORD")
    if not email or not password:
        print("COSA_EMAIL and COSA_PASSWORD environment variables are required", file=sys.stderr)
        return 2

    try:
        status, data = request("/api/users/login", {"email": email, "password": password})
        if status != 200 or data.get("ok") not in (1, True):
            result("login", status, data)
            return 1
        token = data.get("authToken")
        if not isinstance(token, str) or not token:
            print("Login succeeded without a usable token")
            return 1

        # A valid read confirms that the token works before probing routes.
        status, data = request("/api/endpoints/getEndpoints", {}, token)
        result("known route", status, data)
        if status != 200 or data.get("ok") not in (1, True):
            return 1

        fake_id = f"codex-schedule-probe-{uuid.uuid4().hex}"
        payload = {"endpoint": fake_id}
        schedule_status, schedule_data = request("/api/endpoints/setSchedule", payload, token)
        missing_status, missing_data = request(
            "/api/endpoints/__codex_nonexistent_schedule_probe__", payload, token
        )
        result("setSchedule with nonexistent device", schedule_status, schedule_data)
        result("nonexistent route", missing_status, missing_data)
        if (schedule_status, schedule_data.get("ok"), schedule_data.get("code")) == (
            missing_status, missing_data.get("ok"), missing_data.get("code")
        ):
            print("Result: inconclusive; both routes returned the same result")
        else:
            print("Result: setSchedule route behaves differently; inspect its code before any write")
        return 0
    except (OSError, ValueError, TypeError):
        print("Probe failed before a conclusive comparison", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
