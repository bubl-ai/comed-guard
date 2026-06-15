# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Commands

```bash
pip install -r requirements.txt   # requests

python test_decide.py             # run all tests (no credentials needed)

# Dry run — reads live price and thermostat, logs decision, never writes
HW_API_KEY=... HW_API_SECRET=... HW_REFRESH_TOKEN=... HW_DEVICE_ID=... HW_LOCATION_ID=... DRY_RUN=true python guard.py
```

## Architecture

Two strict layers — never mix them:

**Pure logic — `decide(price, mode, status, cool, heat)`** (`guard.py:43`)
No I/O, no clock reads, no side effects. All tests in `test_decide.py` cover only this function. Do not add I/O here.

**I/O layer — everything else**
`comed_price()` → `hw_access_token()` → `hw_read()` → `decide()` → `hw_write()` → `notify()`.
Thermostat access via the official Honeywell Home API (`api.honeywell.com`), authenticated with OAuth refresh token.

## Key invariants — do not break these

- **Manual holds are sacred.** `decide()` identifies its own holds by comparing setpoints exactly to `OFF_PAIR`, `MAX_PAIR_COOL`, `MAX_PAIR_HEAT`. Any other setpoints = human hold, never touched.
- **Hysteresis.** Enters OFF at `OFF_AT_CENTS`, only releases below `RESUME_BELOW_CENTS`. The gap prevents flapping.
- **Dead-man's switch.** `hold_until()` sets a `HoldUntil` expiry `HOLD_HOURS` out. If the script stops running, the thermostat self-releases.
- **Silent re-assertion.** Re-asserting an existing hold (setpoints already match) must not trigger a notification. The `changed` flag in `main()` handles this.
- **Never log tokens or raw API bodies** — Actions logs are public.

## Tunable constants

All at the top of `guard.py` (lines 26–36): `OFF_AT_CENTS`, `RESUME_BELOW_CENTS`, `OFF_PAIR`, `MAX_PAIR_COOL`, `MAX_PAIR_HEAT`, `HOLD_HOURS`, `TIMEZONE`. Commit and done.

## CI / GitHub Actions

- `guard.yml`: installs `requirements.txt`, runs tests, then runs `guard.py` every 10 minutes.
- `keepalive.yml`: weekly commit to prevent GitHub disabling the cron after 60 days.
- Concurrency group `price-guard`, `cancel-in-progress: false`.
- Required secrets: `HW_API_KEY`, `HW_API_SECRET`, `HW_REFRESH_TOKEN`, `HW_DEVICE_ID`, `HW_LOCATION_ID`. Optional: `NTFY_TOPIC`.
