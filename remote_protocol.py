"""Validated, signed requests for one station and one adjustment."""
import hashlib
import hmac
import json
import math
import re
import time
import uuid

PATH = "data/control/titration-buffer.json"
TTL_MS = 120_000
PUMP_TTL_MS = 15_000
PULSE_TAGS = {"base_pulse_s", "acid_pulse_s"}
LIMITS = {"base_dose_s": (0.1, 120), "base_pause_s": (1, 120),
          "acid_dose_s": (0.1, 120), "acid_pause_s": (1, 120),
          "base_start_ph": (0, 14), "base_stop_ph": (0, 14),
          "acid_start_ph": (0, 14), "acid_stop_ph": (0, 14)}
FIELDS = {"station", "id", "issued_ms", "parameter", "value", "execution"}


def valid_station(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value) is not None


def signature(payload, key):
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
    return hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()


def issue(station, parameter, value, key):
    payload = dict(station=station, id=uuid.uuid4().hex, issued_ms=time.time_ns() // 1_000_000,
                   parameter=parameter, value=value, execution="automatic")
    if not valid_values(payload):
        raise ValueError("Недопустимый параметр или значение")
    return {**payload, "signature": signature(payload, key)}


def request_ttl_ms(parameter):
    if isinstance(parameter, str) and (parameter in PULSE_TAGS or parameter == "pump_stop"):
        return PUMP_TTL_MS
    return TTL_MS


def valid_values(payload):
    value = payload["value"]
    if payload["parameter"] == "mode":
        return valid_station(payload["station"]) and isinstance(value, str) and value in ("manual", "semi", "auto")
    parameter = payload["parameter"]
    if parameter == "pump_stop":
        return valid_station(payload["station"]) and value is True
    bounds = (1, 5) if isinstance(parameter, str) and parameter in PULSE_TAGS else (
        LIMITS.get(parameter) if isinstance(parameter, str) else None)
    return (valid_station(payload["station"]) and type(value) in (float, int)
            and bounds is not None and bounds[0] <= value <= bounds[1]
            and math.isfinite(value) and round(value, 2) == value)


def verify(message, station, key, seen=0):
    now = time.time_ns() // 1_000_000
    if not isinstance(message, dict) or message.keys() != FIELDS | {"signature"}:
        return False
    issued = message["issued_ms"]
    digest = message["signature"]
    identifier = message["id"]
    return (len(key) >= 32 and message["station"] == station and type(issued) is int
            and message["execution"] == "automatic"
            and issued > seen and -5_000 <= now - issued <= request_ttl_ms(message["parameter"])
            and isinstance(identifier, str) and re.fullmatch(r"[0-9a-f]{32}", identifier)
            and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
            and valid_values(message) and hmac.compare_digest(
                digest, signature({field: message[field] for field in FIELDS}, key)))
