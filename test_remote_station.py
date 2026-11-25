import base64
import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import app
from remote_protocol import PROTOCOL, issue, verify


LATEST = {"observation": {"titration_station": {"remote_execution": PROTOCOL, "remote_station": "qa"}}}


def test_api_uses_existing_git_token_without_remote_keys():
    def github(request, **kwargs):
        assert request.get_header("Authorization") == "Bearer existing-token"
        if request.get_method() == "GET":
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        body = json.loads(request.data)
        message = json.loads(base64.b64decode(body["content"]))
        assert verify(message, "qa")
        assert message["parameter"] == "base_pause_s"
        assert message["value"] == 12.5
        assert "signature" not in message
        assert not verify(message, "other")
        assert not verify(message, "qa", message["issued_ms"])
        return io.BytesIO(b"{}")

    route = "/api/titration/request"
    with (patch.object(app, "TOKEN", "existing-token"), patch.object(app, "file_json", return_value=LATEST),
          patch.object(app.urllib.request, "urlopen", side_effect=github) as api):
        with app.app.test_client() as client:
            assert b"remote-station-form" in client.get("/").data
            assert b'name="operator_key"' not in client.get("/").data
            assert client.post(route, json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 400
            assert client.post(route, json={"station": "qa", "parameter": "start", "value": 1}).status_code == 400
            assert client.post(route, json={"station": "old", "parameter": "mode", "value": "manual"}).status_code == 409
            api.assert_not_called()
            response = client.post(route, json={"station": "qa", "parameter": "base_pause_s", "value": 12.5})
            assert response.status_code == 202, response.json
            assert response.json["state"] == "pending"



def test_modes_and_pump_parameters():
    for mode in ("manual", "semi", "auto"):
        assert verify(issue("qa", "mode", mode), "qa")
    assert verify(issue("qa", "base_pulse_s", 5), "qa")
    assert verify(issue("qa", "pump_stop", True), "qa")



def test_stop_replaces_pending_pulse_in_the_private_buffer():
    from remote_protocol import PATH
    pulse = issue("qa", "base_pulse_s", 3)

    def github(request, **kwargs):
        if request.get_method() == "GET":
            return io.BytesIO(json.dumps({
                "sha": "previous",
                "content": base64.b64encode(json.dumps(pulse).encode()).decode(),
            }).encode())
        assert request.full_url.endswith(PATH)
        payload = json.loads(request.data)
        assert payload["sha"] == "previous"
        stop = json.loads(base64.b64decode(payload["content"]))
        assert verify(stop, "qa")
        assert stop["parameter"] == "pump_stop" and stop["value"] is True
        return io.BytesIO(b"{}")

    with (patch.object(app, "TOKEN", "existing-token"), patch.object(app, "file_json", return_value=LATEST),
          patch.object(app.urllib.request, "urlopen", side_effect=github)):
        with app.app.test_client() as client:
            response = client.post("/api/titration/request", json={"station": "qa", "parameter": "pump_stop", "value": True})
            assert response.status_code == 202, response.json
