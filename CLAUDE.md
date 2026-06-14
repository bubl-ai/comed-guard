# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script (`guard.py`) that runs every 10 minutes on GitHub Actions (free, no server). It fetches the ComEd hourly electricity price and controls a Resideo/Honeywell thermostat via three states: **OFF** (price spike ≥ 15¢), **MAX** (negative price, comfort boost), **SCHEDULE** (normal price, thermostat runs its own weekly schedule). Push notifications go through ntfy.sh.

## Commands

```bash
# Run tests (the only test file; plain asserts, no framework)
python test_decide.py

# Run the guard locally (requires env vars — see README for secrets setup)
python guard.py

# Dry run (logs decision, never touches the thermostat)
DRY_RUN=true python guard.py
```

Only one dependency: `requests`. Install with `pip install requests`.

## Architecture

The script is intentionally split into two layers:

**Pure logic — `decide(price, mode, status, cool, heat)`** (`guard.py:43`)  
Returns `(action, pair, reason)` with no I/O, no clock reads, no side effects. This is the entire decision brain. All tests in `test_decide.py` exercise only this function.

**I/O layer — everything else in `guard.py`**  
`comed_price()`, `hw_access_token()`, `hw_read()`, `hw_write()`, `notify()`, and `main()`. `main()` orchestrates: fetch price → auth → read thermostat → decide → write thermostat → notify.

## Key invariants

- **Manual holds are sacred**: `decide()` identifies script-owned holds by checking if setpoints exactly equal `OFF_PAIR`, `MAX_PAIR_COOL`, or `MAX_PAIR_HEAT`. Any other setpoints mean a human hold — never touched.
- **Hysteresis**: enters OFF at `OFF_AT_CENTS` (15¢), only releases below `RESUME_BELOW_CENTS` (12¢) to prevent flapping at boundary prices.
- **Dead-man's switch**: holds are `HoldUntil` with expiry `HOLD_HOURS` (3h) out. Re-asserted each run while the condition persists. If the script stops, the hold expires naturally.
- **Notifications fire only on state change** (`changed` flag in `main()`). Re-asserting an existing hold is silent.
- **Never log tokens or raw API bodies** — Actions logs are public. Secrets arrive via env vars only.

## Tunable constants

All user-facing tuning lives at the top of `guard.py` (lines 26–36): `OFF_AT_CENTS`, `RESUME_BELOW_CENTS`, `OFF_PAIR`, `MAX_PAIR_COOL`, `MAX_PAIR_HEAT`, `HOLD_HOURS`, `TIMEZONE`. Change and commit — no other files need updating.

## CI / GitHub Actions

- `guard.yml`: runs `test_decide.py` then `guard.py` every 10 minutes. `workflow_dispatch` exposes a **Dry run** checkbox (defaults to true for manual triggers).
- `keepalive.yml`: commits a timestamp file every Monday to prevent GitHub from disabling the cron schedule after 60 days of inactivity.
- Concurrency group `price-guard` with `cancel-in-progress: false` prevents overlapping runs.
- Required secrets: `HW_API_KEY`, `HW_API_SECRET`, `HW_REFRESH_TOKEN`, `HW_DEVICE_ID`, `HW_LOCATION_ID`. Optional: `NTFY_TOPIC`.
