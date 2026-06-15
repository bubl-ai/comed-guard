#!/usr/bin/env python3
"""ComEd Price Guard — keeps a Resideo/Honeywell thermostat off ComEd price peaks.

Three states, decided fresh every run (stateless):
  OFF       price >= OFF_AT_CENTS  ->  hold at OFF_PAIR (your hard comfort limits)
  MAX       price < 0              ->  hold at MAX_PAIR_COOL or MAX_PAIR_HEAT
                                       depending on current thermostat mode
  SCHEDULE  otherwise              ->  thermostat follows its own weekly schedule

Holds are HoldUntil and self-expire HOLD_HOURS out (dead-man's switch),
re-asserted each run while the condition persists. Any hold whose setpoints
don't exactly equal OFF_PAIR, MAX_PAIR_COOL, or MAX_PAIR_HEAT is a human
hold and is never touched.

Public-repo rule: never print tokens or raw API bodies — GitHub
Actions logs here are public. Secrets come from env vars only.
"""
import datetime
import os
import sys
from zoneinfo import ZoneInfo

import requests

# ---------------- Config: edit these numbers, commit, done ----------------
OFF_AT_CENTS = 15.0          # enter OFF at/above this price (cents/kWh)
RESUME_BELOW_CENTS = 12.0    # leave OFF below this (the gap prevents on/off flapping)
OFF_PAIR = (84.0, 58.0)      # (coolF, heatF) while OFF — these ARE your hard limits

MAX_PAIR_COOL = (68.0, 65.0) # used when mode is Cool or Auto — soak up cheap cooling
MAX_PAIR_HEAT = (78.0, 74.0) # used when mode is Heat — bank cheap heat
                             # Keep heatF a few °F below coolF (Resideo Auto deadband)

HOLD_HOURS = 3               # holds self-expire this far out if the script stops running
TIMEZONE = "America/Chicago"

COMED_URL = "https://hourlypricing.comed.com/api?type=currenthouraverage"
HONEYWELL_BASE = "https://api.honeywell.com"
NTFY_BASE = "https://ntfy.sh"
# ---------------------------------------------------------------------------


def decide(price, mode, status, cool, heat):
    """The entire brain. Pure: no I/O, no clock reads.

    Returns (action, pair, reason):
      action: "hold" | "release" | "none"
      pair:   (coolF, heatF) when action == "hold", else None
    """
    if mode not in ("Cool", "Heat", "Auto"):
        return "none", None, f"mode {mode!r}; doing nothing"

    max_pair = MAX_PAIR_HEAT if mode == "Heat" else MAX_PAIR_COOL

    on_hold = status not in (None, "", "NoHold")
    current = (cool, heat)
    ours_off = on_hold and current == OFF_PAIR
    ours_max = on_hold and (current == MAX_PAIR_COOL or current == MAX_PAIR_HEAT)

    if on_hold and not (ours_off or ours_max):
        return "none", None, "manual hold present; respecting it"
    if price < 0:
        return "hold", max_pair, f"price {price:.1f}c is negative; comfort boost"
    if price >= OFF_AT_CENTS:
        return "hold", OFF_PAIR, f"price {price:.1f}c >= {OFF_AT_CENTS:.1f}c; effectively off"
    if ours_max:
        return "release", None, f"price {price:.1f}c no longer negative; back to schedule"
    if ours_off and price < RESUME_BELOW_CENTS:
        return "release", None, f"price {price:.1f}c < {RESUME_BELOW_CENTS:.1f}c; back to schedule"
    if ours_off:
        return "none", None, f"price {price:.1f}c in dead band; keeping OFF hold"
    return "none", None, f"price {price:.1f}c normal; schedule is running"


# ---------------------------- I/O layer ------------------------------------


def comed_price():
    r = requests.get(COMED_URL, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise RuntimeError("ComEd API returned no data")
    return float(data[0]["price"])


def hw_access_token(key, secret, refresh_token):
    r = requests.post(
        f"{HONEYWELL_BASE}/oauth2/token",
        auth=(key, secret),
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=20,
    )
    if r.status_code != 200:
        # Never include the response body: it may echo token material.
        raise RuntimeError(f"token endpoint HTTP {r.status_code}")
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("token response missing access_token")
    return token


def hw_device_url(key, device_id, location_id):
    return (f"{HONEYWELL_BASE}/v2/devices/thermostats/{device_id}"
            f"?apikey={key}&locationId={location_id}")


def hw_read(url, token):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(
            f"thermostat read HTTP {r.status_code} (check HW_DEVICE_ID / HW_LOCATION_ID)")
    cv = r.json().get("changeableValues")
    if not cv:
        raise RuntimeError("thermostat response missing changeableValues")
    return cv


def hw_write(url, token, cv):
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                      json=cv, timeout=20)
    if not (200 <= r.status_code < 300):
        raise RuntimeError(f"thermostat write HTTP {r.status_code}")


def notify(topic, title, message):
    """Push via ntfy. Empty topic disables notifications entirely.
    Failures are printed but never fatal: notifications must not break control."""
    if not topic:
        return
    try:
        r = requests.post(f"{NTFY_BASE}/{topic}", data=message.encode("utf-8"),
                          headers={"Title": title}, timeout=20)
        if not (200 <= r.status_code < 300):
            print(f"notify error (non-fatal): ntfy HTTP {r.status_code}")
    except requests.RequestException as e:
        print(f"notify error (non-fatal): {e}")


def hold_until():
    """Local clock time HOLD_HOURS from now — the dead-man's switch expiry."""
    t = datetime.datetime.now(ZoneInfo(TIMEZONE)) + datetime.timedelta(hours=HOLD_HOURS)
    return t.strftime("%H:%M:00")


# ------------------------------- main ---------------------------------------


def main():
    dry = os.getenv("DRY_RUN", "").lower() == "true"
    topic = os.getenv("NTFY_TOPIC", "")

    env = {k: os.getenv(k, "") for k in (
        "HW_API_KEY", "HW_API_SECRET", "HW_REFRESH_TOKEN",
        "HW_DEVICE_ID", "HW_LOCATION_ID")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        print(f"FATAL [env]: missing secrets: {', '.join(missing)}")
        sys.exit(1)
    if dry:
        print("DRY RUN: decision will be logged but nothing will be sent")

    try:
        price = comed_price()
    except Exception as e:
        print(f"FATAL [comed]: {e}")
        notify(topic, "Price Guard FAILED", "stage: comed — check Actions logs")
        sys.exit(1)
    print(f"ComEd current hour average: {price:.1f} c/kWh")

    try:
        token = hw_access_token(env["HW_API_KEY"], env["HW_API_SECRET"],
                                env["HW_REFRESH_TOKEN"])
    except Exception as e:
        print(f"FATAL [auth]: {e}")
        notify(topic, "Price Guard: AUTH FAILURE",
               "Refresh token may have expired. Redo the OAuth dance in the README "
               "and update the HW_REFRESH_TOKEN secret.")
        sys.exit(1)

    url = hw_device_url(env["HW_API_KEY"], env["HW_DEVICE_ID"], env["HW_LOCATION_ID"])
    try:
        cv = hw_read(url, token)
    except Exception as e:
        print(f"FATAL [read]: {e}")
        notify(topic, "Price Guard FAILED", "stage: thermostat read — check Actions logs")
        sys.exit(1)

    mode = cv.get("mode", "")
    status = cv.get("thermostatSetpointStatus", "NoHold")
    cool = float(cv.get("coolSetpoint", 0))
    heat = float(cv.get("heatSetpoint", 0))
    print(f"Thermostat: mode={mode} status={status} cool={cool:.0f} heat={heat:.0f}")

    action, pair, reason = decide(price, mode, status, cool, heat)
    print(f"Decision: {action.upper()} — {reason}")

    if action == "none":
        return
    if dry:
        print("DRY RUN: not touching the thermostat")
        return

    if action == "hold":
        changed = (cool, heat) != pair  # re-assertion refreshes expiry silently
        cv["coolSetpoint"], cv["heatSetpoint"] = pair
        cv["thermostatSetpointStatus"] = "HoldUntil"
        cv["nextPeriodTime"] = hold_until()
    else:  # release
        changed = True
        cv["thermostatSetpointStatus"] = "NoHold"
        cv.pop("nextPeriodTime", None)

    try:
        hw_write(url, token, cv)
    except Exception as e:
        print(f"FATAL [write]: {e}")
        notify(topic, "Price Guard FAILED", "stage: thermostat write — check Actions logs")
        sys.exit(1)
    print("Thermostat updated.")

    if changed:
        notify(topic, "ComEd Price Guard", f"{price:.1f}c/kWh — {reason}")


if __name__ == "__main__":
    main()
