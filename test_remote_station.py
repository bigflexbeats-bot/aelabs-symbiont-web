import base64
import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import app
from remote_protocol import verify


def test_api_requires_authorization_and_writes_a_valid_signed_request():
    operator = "a" * 32
    signer = "b" * 32

    def github(request, **kwargs):
        if request.get_method() == "GET":
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        body = json.loads(request.data)
        message = json.loads(base64.b64decode(body["content"]))
        assert verify(message, "qa", signer)
        assert message["parameter"] == "base_pause_s"
        assert message["value"] == 12.5
        assert not verify(dict(message, value=13.5), "qa", signer)
        assert not verify(message, "other", signer)
        assert not verify(message, "qa", signer, message["issued_ms"])
        return io.BytesIO(b"{}")

    route = "/api/titration/request"
    secrets = dict(AE_AUTOLABS_REMOTE_OPERATOR_KEY=operator, AE_AUTOLABS_REMOTE_SIGNING_KEY=signer,
                   AE_AUTOLABS_REMOTE_GITHUB_TOKEN="dummy", AE_AUTOLABS_REMOTE_STATION="qa")
    with patch.dict("os.environ", secrets), patch.object(app.urllib.request, "urlopen", side_effect=github) as api:
        with app.app.test_client() as client:
            assert b"remote-station-form" in client.get("/").data
            assert client.post(route, json={}).status_code == 401
            auth = {"Authorization": f"Bearer {operator}"}
            assert client.post(route, json={"parameter": "start", "value": 1}, headers=auth).status_code == 400
            api.assert_not_called()
            response = client.post(route, json={"parameter": "base_pause_s", "value": 12.5}, headers=auth)
            assert response.status_code == 202, response.json
            assert response.json["state"] == "pending"



def test_modes_and_pump_parameters():
    from remote_protocol import issue

    key = "b" * 32
    for mode in ("manual", "semi", "auto"):
        assert verify(issue("qa", "mode", mode, key), "qa", key)
    assert verify(issue("qa", "base_pulse_s", 5, key), "qa", key)
    assert verify(issue("qa", "pump_stop", True, key), "qa", key)



def test_stop_replaces_pending_pulse_in_the_private_buffer():
    from remote_protocol import PATH, issue

    operator = "a" * 32
    signer = "b" * 32
    pulse = issue("qa", "base_pulse_s", 3, signer)

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
        assert verify(stop, "qa", signer)
        assert stop["parameter"] == "pump_stop" and stop["value"] is True
        return io.BytesIO(b"{}")

    secrets = dict(AE_AUTOLABS_REMOTE_OPERATOR_KEY=operator, AE_AUTOLABS_REMOTE_SIGNING_KEY=signer,
                   AE_AUTOLABS_REMOTE_GITHUB_TOKEN="dummy", AE_AUTOLABS_REMOTE_STATION="qa")
    with patch.dict("os.environ", secrets), patch.object(app.urllib.request, "urlopen", side_effect=github):
        with app.app.test_client() as client:
            response = client.post("/api/titration/request", json={"parameter": "pump_stop", "value": True},
                                   headers={"Authorization": f"Bearer {operator}"})
            assert response.status_code == 202, response.json
