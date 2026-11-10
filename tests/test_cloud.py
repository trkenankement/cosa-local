"""Offline behavior tests, using the actual HA 2026.11 entity classes."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.climate import HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from custom_components.cosa_cloud.api import CosaAPI, CosaAuthError, CosaError, CosaPartialUpdateError, number, normalize_schedule
from custom_components.cosa_cloud.climate import CosaClimate
from custom_components.cosa_cloud.calendar import CosaScheduleCalendar, schedule_events
from custom_components.cosa_cloud.binary_sensor import CosaConnection, CosaHeating
from custom_components.cosa_cloud.coordinator import CosaCoordinator
from custom_components.cosa_cloud.config_flow import CosaConfigFlow
from custom_components.cosa_cloud.services import register, unregister

DEVICE = {"id": "test-device", "name": "Test thermostat", "device": {"isConnected": True},
          "temperature": 20.5, "humidity": 0, "mode": "manual", "option": "home",
          "homeTemperature": 21, "awayTemperature": 16, "sleepTemperature": 19,
          "customTemperature": 22, "combiState": "off"}
SCHEDULE = {day: {"0": "sleep", "420": "away", "1020": "home"} for day in
            ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}


class Response:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, deepcopy(kwargs)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, Response) else Response(response)


class APIBehavior(unittest.IsolatedAsyncioTestCase):
    def client(self, *responses):
        session = Session(*responses)
        return CosaAPI(session, "test@example.invalid", "not-a-real-password"), session

    async def test_login_and_read_do_not_change_device_and_block_redirects(self):
        api, session = self.client({"ok": 1, "authToken": "fake-token"}, {"ok": 1, "endpoint": DEVICE})
        self.assertEqual(await api.device("test-device"), DEVICE)
        self.assertEqual([c[0].rsplit("/", 1)[1] for c in session.calls], ["login", "getEndpoint"])
        self.assertTrue(all(not c[1]["allow_redirects"] for c in session.calls))
        self.assertNotIn("authtoken", session.calls[0][1]["headers"])
        self.assertEqual(session.calls[1][1]["headers"]["authtoken"], "fake-token")

    async def test_expired_token_is_renewed_once_for_read(self):
        api, session = self.client(Response({}, 401), {"ok": 1, "authToken": "new"}, {"ok": 1, "endpoint": DEVICE})
        api.token = "old"
        await api.device("test-device")
        self.assertEqual([c[0].rsplit("/", 1)[1] for c in session.calls], ["getEndpoint", "login", "getEndpoint"])
        self.assertEqual(api.token, "new")

    async def test_missing_token_or_invalid_credentials_cannot_be_success(self):
        for response in ({"ok": 1}, {"ok": 0}, {"error": "anything"}):
            api, session = self.client(response)
            with self.assertRaises(CosaAuthError):
                await api.devices()
            self.assertEqual(len(session.calls), 1)

    async def test_temperature_preserves_presets_from_fresh_read(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE}, {"ok": 1}, {"ok": 1})
        api.token = "test"
        await api.set_temperature("test-device", 23.24)
        self.assertEqual(session.calls[1][1]["json"], {"endpoint": "test-device", "targetTemperatures": {
            "home": 21, "away": 16, "sleep": 19, "custom": 23.2}})
        self.assertEqual(session.calls[2][1]["json"], {"endpoint": "test-device", "mode": "manual", "option": "custom"})

    async def test_missing_presets_and_offline_devices_never_receive_writes(self):
        for changes in ({"homeTemperature": None}, {"awayTemperature": float("nan")},
                        {"device": {"isConnected": False}}, {"device": None}):
            api, session = self.client({"ok": 1, "endpoint": DEVICE | changes})
            api.token = "test"
            with self.assertRaises(CosaError):
                await api.set_temperature("test-device", 22)
            self.assertEqual(len(session.calls), 1)

    async def test_invalid_temperature_rejected_before_any_network(self):
        for value in (None, True, "22", float("nan"), float("inf"), 4.9, 32.1):
            api, session = self.client()
            with self.assertRaises(CosaError):
                await api.set_temperature("test-device", value)
            self.assertEqual(session.calls, [])

    async def test_write_timeout_never_retries_or_switches_mode(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE}, TimeoutError("private payload"))
        api.token = "test"
        with self.assertRaises(CosaError) as caught:
            await api.set_temperature("test-device", 22)
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(len(session.calls), 2)

    async def test_partial_update_is_reported_explicitly(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE}, {"ok": 1}, {"ok": 0})
        api.token = "test"
        with self.assertRaises(CosaPartialUpdateError):
            await api.set_temperature("test-device", 22)
        self.assertEqual(len(session.calls), 3)

    async def test_malformed_responses_and_wrong_device_rejected(self):
        for endpoint in (None, {}, [], DEVICE | {"id": "different"}):
            api, _ = self.client({"ok": 1, "endpoint": endpoint})
            api.token = "test"
            with self.assertRaises(CosaError):
                await api.device("test-device")

    async def test_http_redirect_is_not_treated_as_success(self):
        api, session = self.client(Response({}, 302))
        with self.assertRaises(CosaError):
            await api.devices()
        self.assertEqual(len(session.calls), 1)

    async def test_off_on_roundtrip_restores_observed_working_mode(self):
        for mode, option in (("auto", "away"), ("schedule", "sleep"),
                             ("manual", "home"), ("manual", "away"),
                             ("manual", "sleep"), ("manual", "custom")):
            with self.subTest(mode=mode, option=option):
                active = DEVICE | {"mode": mode, "option": option}
                frozen = DEVICE | {"mode": "manual", "option": "frozen"}
                api, session = self.client({"ok": 1, "endpoint": active}, {"ok": 1},
                                           {"ok": 1, "endpoint": frozen}, {"ok": 1})
                api.token = "fake"
                await api.set_enabled("test-device", False)
                await api.set_enabled("test-device", True)
                self.assertEqual(session.calls[1][1]["json"],
                    {"endpoint": "test-device", "mode": "manual", "option": "frozen"})
                expected = {"endpoint": "test-device", "mode": mode}
                if mode == "manual":
                    expected["option"] = option
                self.assertEqual(session.calls[3][1]["json"], expected)
                self.assertTrue(all(c[0].rsplit("/", 1)[1] in ("getEndpoint", "setMode")
                                    for c in session.calls))

    async def test_on_already_enabled_preserves_auto_schedule_and_manual(self):
        for mode, option in (("auto", "away"), ("schedule", "sleep"), ("manual", "custom")):
            api, session = self.client({"ok": 1, "endpoint": DEVICE | {"mode": mode, "option": option}})
            api.token = "fake"
            await api.set_enabled("test-device", True)
            self.assertEqual(len(session.calls), 1)

    async def test_repeated_off_keeps_original_schedule(self):
        frozen = DEVICE | {"mode": "manual", "option": "frozen"}
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"mode": "schedule"}}, {"ok": 1},
                                  {"ok": 1, "endpoint": frozen},
                                  {"ok": 1, "endpoint": frozen}, {"ok": 1})
        api.token = "fake"
        await api.set_enabled("test-device", False)
        await api.set_enabled("test-device", False)
        await api.set_enabled("test-device", True)
        self.assertEqual(session.calls[-1][1]["json"], {"endpoint": "test-device", "mode": "schedule"})
        self.assertEqual(len(session.calls), 5)

    async def test_starting_frozen_requires_explicit_profile_without_writes(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"option": "frozen"}})
        api.token = "fake"
        with self.assertRaisesRegex(CosaError, "select a preset explicitly"):
            await api.set_enabled("test-device", True)
        self.assertEqual(len(session.calls), 1)

    async def test_fresh_external_mode_wins_over_older_resume_intent(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"mode": "schedule"}},
            {"ok": 1, "endpoint": DEVICE | {"mode": "auto"}}, {"ok": 1},
            {"ok": 1, "endpoint": DEVICE | {"option": "frozen"}}, {"ok": 1})
        api.token = "fake"
        await api.device("test-device")
        await api.set_enabled("test-device", False)
        await api.set_enabled("test-device", True)
        self.assertEqual(session.calls[-1][1]["json"], {"endpoint": "test-device", "mode": "auto"})

    async def test_unknown_mode_cannot_restore_stale_profile(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE},
            {"ok": 1, "endpoint": DEVICE | {"mode": "turbo"}},
            {"ok": 1, "endpoint": DEVICE | {"option": "frozen"}})
        api.token = "fake"
        await api.device("test-device")
        with self.assertRaises(CosaError):
            await api.set_enabled("test-device", True)
        with self.assertRaises(CosaError):
            await api.set_enabled("test-device", True)
        self.assertEqual(len(session.calls), 3)

    async def test_resume_history_never_crosses_device_ids(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE},
            {"ok": 1, "endpoint": DEVICE | {"id": "other-device", "option": "frozen"}})
        api.token = "fake"
        await api.device("test-device")
        with self.assertRaises(CosaError):
            await api.set_enabled("other-device", True)
        self.assertEqual(len(session.calls), 2)

    async def test_offline_snapshot_cannot_replace_last_online_profile(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"mode": "schedule"}},
            {"ok": 1, "endpoint": DEVICE | {"device": {"isConnected": False}}},
            {"ok": 1, "endpoint": DEVICE | {"option": "frozen"}}, {"ok": 1})
        api.token = "fake"
        await api.device("test-device")
        await api.device("test-device")
        await api.set_enabled("test-device", True)
        self.assertEqual(session.calls[-1][1]["json"], {"endpoint": "test-device", "mode": "schedule"})

    async def test_mode_write_timeout_is_not_retried_and_resume_intent_survives(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"mode": "schedule"}},
            TimeoutError("private detail"),
            {"ok": 1, "endpoint": DEVICE | {"option": "frozen"}}, {"ok": 1})
        api.token = "fake"
        with self.assertRaises(CosaError) as caught:
            await api.set_enabled("test-device", False)
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(len(session.calls), 2)
        # A new explicit user action may resume after a timeout applied remotely.
        await api.set_enabled("test-device", True)
        self.assertEqual(session.calls[-1][1]["json"], {"endpoint": "test-device", "mode": "schedule"})

    async def test_missing_identity_and_offline_devices_block_enable_writes(self):
        for endpoint in ({k: v for k, v in DEVICE.items() if k != "id"},
                         DEVICE | {"device": {"isConnected": False}}):
            api, session = self.client({"ok": 1, "endpoint": endpoint})
            api.token = "fake"
            with self.assertRaises(CosaError):
                await api.set_enabled("test-device", False)
            self.assertEqual(len(session.calls), 1)

    async def test_invalid_enable_value_rejected_before_network(self):
        api, session = self.client()
        with self.assertRaises(CosaError):
            await api.set_enabled("test-device", "true")
        self.assertEqual(session.calls, [])

    async def test_huge_numeric_reading_stays_unknown(self):
        self.assertIsNone(number(10 ** 1000))

    async def test_schedule_is_read_on_demand(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"schedule": SCHEDULE}})
        api.token = "test"
        self.assertEqual(await api.get_schedule("test-device"), SCHEDULE)
        self.assertEqual(len(session.calls), 1)

    async def test_schedule_write_uses_live_payload_and_checks_readback(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"schedule": SCHEDULE}},
                                   {"ok": 1}, {"ok": 1, "endpoint": DEVICE | {"schedule": SCHEDULE}})
        api.token = "test"
        self.assertEqual(await api.set_schedule("test-device", SCHEDULE), SCHEDULE)
        self.assertTrue(session.calls[1][0].endswith("/api/endpoints/setSchedule"))
        self.assertEqual(session.calls[1][1]["json"], {"endpoint": "test-device", "schedule": SCHEDULE})
        self.assertEqual(len(session.calls), 3)

    async def test_schedule_write_rejects_mismatch_and_never_retries(self):
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"schedule": SCHEDULE}},
                                   {"ok": 1}, {"ok": 1, "endpoint": DEVICE | {"schedule": {}}})
        api.token = "test"
        with self.assertRaises(CosaError):
            await api.set_schedule("test-device", SCHEDULE)
        self.assertEqual(len([c for c in session.calls if c[0].endswith("setSchedule")]), 1)

    async def test_invalid_schedule_and_offline_device_never_write(self):
        invalid = [None, {}, SCHEDULE | {"monday": {}},
                   SCHEDULE | {"monday": {"420": "home"}},
                   SCHEDULE | {"monday": {"0": "turbo"}},
                   SCHEDULE | {"monday": {"0": []}},
                   SCHEDULE | {"monday": {"0": "home", "9" * 5000: "away"}},
                   SCHEDULE | {"monday": {"0": "home", "1440": "away"}}]
        for schedule in invalid:
            with self.subTest(schedule=schedule):
                api, session = self.client()
                with self.assertRaises(CosaError):
                    await api.set_schedule("test-device", schedule)
                self.assertEqual(session.calls, [])
        api, session = self.client({"ok": 1, "endpoint": DEVICE | {"device": {"isConnected": False}}})
        api.token = "test"
        with self.assertRaises(CosaError):
            await api.set_schedule("test-device", SCHEDULE)
        self.assertEqual(len(session.calls), 1)

    def test_schedule_accepts_yaml_integer_minute_keys(self):
        schedule = deepcopy(SCHEDULE)
        schedule["monday"] = {0: "sleep", 420: "away", 1020: "home"}
        self.assertEqual(normalize_schedule(schedule), SCHEDULE)


class HomeAssistantBehavior(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.temp.name)
        self.entry = ConfigEntry(version=1, minor_version=1, domain="cosa_cloud", title="Test",
            data={"email": "test@example.invalid", "password": "fake", "endpoint_id": "test-device"},
            options={}, source="user", unique_id="test-device", discovery_keys={}, subentries_data=[])
        self.coordinator = CosaCoordinator(self.hass, self.entry, Session())
        self.coordinator.data = deepcopy(DEVICE)
        self.climate = CosaClimate(self.coordinator)

    async def asyncTearDown(self):
        await self.hass.async_stop()
        self.temp.cleanup()

    async def test_readings_are_observed_not_guessed(self):
        self.assertEqual(self.climate.native_current_temperature, 20.5)
        self.assertEqual(self.climate.native_target_temperature, 21)
        self.assertEqual(self.climate.current_humidity, 0)
        self.coordinator.data.update(temperature=None, combiState=None)
        self.assertIsNone(self.climate.native_current_temperature)
        self.assertIsNone(self.climate.hvac_action)

    async def test_device_offline_disables_controls_but_connection_sensor_reports_off(self):
        connection = CosaConnection(self.coordinator)
        self.coordinator.data["device"]["isConnected"] = False
        self.assertFalse(self.climate.available)
        self.assertTrue(connection.available)
        self.assertFalse(connection.is_on)
        self.coordinator.last_update_success = False
        self.assertFalse(connection.available)

    async def test_control_failure_keeps_actual_value_and_requests_readback(self):
        self.coordinator.api.set_temperature = AsyncMock(side_effect=CosaError("Failed"))
        self.coordinator.async_request_refresh = AsyncMock()
        with self.assertRaises(HomeAssistantError):
            await self.climate.async_set_temperature(temperature=25)
        self.assertEqual(self.climate.native_target_temperature, 21)
        self.coordinator.async_request_refresh.assert_awaited_once()

    async def test_coordinator_turns_auth_failure_into_reauth(self):
        self.coordinator.api.device = AsyncMock(side_effect=CosaAuthError("Login required"))
        with self.assertRaises(ConfigEntryAuthFailed):
            await self.coordinator._async_update_data()

    async def test_hvac_heat_and_turn_on_share_preserving_api(self):
        self.coordinator.async_control = AsyncMock()
        await self.climate.async_turn_on()
        await self.climate.async_set_hvac_mode(HVACMode.HEAT)
        self.assertEqual(self.coordinator.async_control.await_count, 2)
        self.assertTrue(all(c.args == ("set_enabled", True)
                            for c in self.coordinator.async_control.await_args_list))

    async def test_turn_off_uses_suspend_api(self):
        self.coordinator.async_control = AsyncMock()
        await self.climate.async_turn_off()
        self.coordinator.async_control.assert_awaited_once_with("set_enabled", False)

    async def test_explicit_home_and_schedule_profiles_remain_available(self):
        self.coordinator.async_control = AsyncMock()
        await self.climate.async_set_preset_mode("home")
        self.coordinator.async_control.assert_awaited_with("set_mode", "manual", "home")
        await self.climate.async_set_preset_mode("schedule")
        self.coordinator.async_control.assert_awaited_with("set_mode", "schedule")

    async def test_resume_failure_keeps_observed_frozen_state_and_reads_back(self):
        self.coordinator.data["option"] = "frozen"
        self.coordinator.api.set_enabled = AsyncMock(side_effect=CosaError("Previous profile unknown"))
        self.coordinator.async_request_refresh = AsyncMock()
        with self.assertRaises(HomeAssistantError):
            await self.climate.async_turn_on()
        self.assertEqual(self.climate.hvac_mode, HVACMode.OFF)
        self.coordinator.async_request_refresh.assert_awaited_once()

    async def test_auto_and_schedule_roundtrip_through_entity_api_and_readback(self):
        class StatefulSession:
            def __init__(self, state):
                self.state = deepcopy(state)
                self.writes = []

            def post(self, url, **kwargs):
                if url.endswith("/getEndpoint"):
                    return Response({"ok": 1, "endpoint": deepcopy(self.state)})
                if url.endswith("/setMode"):
                    payload = deepcopy(kwargs["json"])
                    self.writes.append(payload)
                    self.state.update({k: v for k, v in payload.items() if k != "endpoint"})
                    return Response({"ok": 1})
                raise AssertionError("Unexpected API operation")

        async def readback():
            self.coordinator.data = await self.coordinator._async_update_data()

        for mode, preset in (("auto", "automatic"), ("schedule", "schedule")):
            with self.subTest(mode=mode):
                session = StatefulSession(DEVICE | {"mode": mode})
                self.coordinator.api = CosaAPI(session, "test@example.invalid", "fake")
                self.coordinator.api.token = "fake"
                self.coordinator.data = deepcopy(session.state)
                self.coordinator.async_request_refresh = AsyncMock(side_effect=readback)
                await self.climate.async_turn_off()
                self.assertEqual(self.climate.hvac_mode, HVACMode.OFF)
                await self.climate.async_turn_on()
                self.assertEqual(self.climate.hvac_mode, HVACMode.HEAT)
                self.assertEqual(self.climate.preset_mode, preset)
                self.assertEqual(session.writes, [
                    {"endpoint": "test-device", "mode": "manual", "option": "frozen"},
                    {"endpoint": "test-device", "mode": mode}])
                self.assertEqual(session.state["homeTemperature"], DEVICE["homeTemperature"])
                self.coordinator.async_request_refresh.assert_has_awaits([unittest.mock.call(), unittest.mock.call()])

    async def test_flow_bad_credentials_returns_form_not_entry(self):
        flow = CosaConfigFlow()
        flow.hass = self.hass
        with patch("custom_components.cosa_cloud.config_flow.async_get_clientsession", return_value=Session()), \
             patch.object(CosaAPI, "devices", AsyncMock(side_effect=CosaAuthError())):
            result = await flow.async_step_user({"email": "test@example.invalid", "password": "fake"})
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "invalid_auth"})

    async def test_flow_multiple_devices_requires_selection(self):
        flow = CosaConfigFlow()
        flow.hass = self.hass
        devices = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
        with patch("custom_components.cosa_cloud.config_flow.async_get_clientsession", return_value=Session()), \
             patch.object(CosaAPI, "devices", AsyncMock(return_value=devices)):
            result = await flow.async_step_user({"email": "test@example.invalid", "password": "fake"})
        self.assertEqual(result["step_id"], "device")

    async def test_schedule_actions_are_on_demand_and_return_verified_result(self):
        self.coordinator.async_get_schedule = AsyncMock(return_value=SCHEDULE)
        self.coordinator.async_control = AsyncMock(return_value=SCHEDULE)
        register(self.hass)
        try:
            with patch("custom_components.cosa_cloud.services._coordinator", return_value=self.coordinator):
                read = await self.hass.services.async_call(
                    "cosa_cloud", "get_schedule", {"entity_id": "climate.cosa"},
                    blocking=True, return_response=True,
                )
                written = await self.hass.services.async_call(
                    "cosa_cloud", "set_schedule",
                    {"entity_id": "climate.cosa", "schedule": SCHEDULE},
                    blocking=True, return_response=True,
                )
            self.assertEqual(read, {"schedule": SCHEDULE})
            self.assertEqual(written, {"verified": True, "schedule": SCHEDULE})
            self.coordinator.async_get_schedule.assert_awaited_once()
            self.coordinator.async_control.assert_awaited_once_with("set_schedule", SCHEDULE)
        finally:
            unregister(self.hass)

    async def test_calendar_shows_cosa_slots_without_new_api_requests(self):
        self.coordinator.data["schedule"] = SCHEDULE
        self.coordinator.data["timeZone"] = "Europe/Istanbul"
        self.coordinator.data["mode"] = "schedule"
        self.coordinator.data["schedulePresetType"] = 4
        calendar = CosaScheduleCalendar(self.coordinator)
        start = datetime(2026, 11, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)
        events = await calendar.async_get_events(self.hass, start, end)
        self.assertTrue(any(event.summary == "Dışarı · 16 °C" and
                            event.start.hour == 7 for event in events))
        self.assertTrue(any(event.summary == "Ev · 21 °C" and
                            event.start.hour == 17 for event in events))
        self.assertEqual(self.coordinator.api.session.calls, [])

    async def test_calendar_current_event_uses_local_time(self):
        self.coordinator.data["schedule"] = SCHEDULE
        self.coordinator.data["timeZone"] = "Europe/Istanbul"
        self.coordinator.data["mode"] = "schedule"
        self.coordinator.data["schedulePresetType"] = 4
        calendar = CosaScheduleCalendar(self.coordinator)
        with patch("custom_components.cosa_cloud.calendar.dt_util.now",
                   return_value=datetime(2026, 11, 9, 15, tzinfo=timezone.utc)):
            self.assertEqual(calendar.event.summary, "Ev · 21 °C")
        self.coordinator.data["mode"] = "manual"
        self.assertIsNone(calendar.event)
        events = await calendar.async_get_events(
            self.hass,
            datetime(2026, 11, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 10, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(events)
        self.assertTrue(all("etkin değil" in event.description for event in events))


if __name__ == "__main__":
    unittest.main()
