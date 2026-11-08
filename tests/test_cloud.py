"""Offline behavior tests, using the actual HA 2026.11 entity classes."""
import asyncio
from copy import deepcopy
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from custom_components.cosa_cloud.api import CosaAPI, CosaAuthError, CosaError, CosaPartialUpdateError
from custom_components.cosa_cloud.climate import CosaClimate
from custom_components.cosa_cloud.binary_sensor import CosaConnection, CosaHeating
from custom_components.cosa_cloud.coordinator import CosaCoordinator
from custom_components.cosa_cloud.config_flow import CosaConfigFlow

DEVICE = {"id": "test-device", "name": "Test thermostat", "device": {"isConnected": True},
          "temperature": 20.5, "humidity": 0, "mode": "manual", "option": "home",
          "homeTemperature": 21, "awayTemperature": 16, "sleepTemperature": 19,
          "customTemperature": 22, "combiState": "off"}


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


if __name__ == "__main__":
    unittest.main()
