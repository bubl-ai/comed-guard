# ComEd Price Guard

Turns your Honeywell Home (Resideo) thermostat effectively off when
[ComEd Hourly Pricing](https://hourlypricing.comed.com/) spikes, boosts
comfort when the price goes negative, and otherwise stays out of the way so
your normal weekly schedule runs the house. Runs free on GitHub Actions —
no server, no Raspberry Pi. All tuning is seven constants at the top of
[`guard.py`](guard.py).

## How it behaves

Every 10 minutes it checks the ComEd price and puts your thermostat into
one of three states, then gets out of the way.

**SCHEDULE — normal price (under 15¢):** releases any hold it set and lets
your thermostat's own weekly schedule run the house as if this script
doesn't exist.

**OFF — price spike (15¢+):** sets a hold at `OFF_PAIR` (default cool 84°F
/ heat 58°F). The system doesn't literally turn off — it holds at your hard
limits, so the thermostat only kicks in if the house actually hits 84°F.
You're protected, but not actively spending money cooling.

**MAX — negative price:** sets a hold at `MAX_PAIR_COOL` (default cool
68°F / heat 65°F) when in Cool or Auto mode, or `MAX_PAIR_HEAT` (default
cool 78°F / heat 74°F) when in Heat mode. The right pair is picked
automatically so the script banks cheap cooling in summer and cheap heat
in winter — no seasonal manual edit needed.

**Why OFF_PAIR equals your hard limits — not some intermediate setpoint:**
setting the thermostat to 84/58 *is* turning it off, because the thermostat
only runs when the house reaches a setpoint. If the house never hits 84°F,
the AC never runs. When it does, the thermostat itself protects you — no
extra code needed. Your hard limits are enforced by the hardware, not the
script.

**Why there are two thresholds (15¢ to enter OFF, 12¢ to leave):** without
this gap, a price hovering right at 15¢ would flip your AC on and off every
10 minutes. The script enters OFF at 15¢ but only releases back to schedule
once the price drops below 12¢ — once it's clearly cheaper.

**Holds are re-asserted every run** while the condition persists, so the
self-expiry is a safety net, not the primary mechanism. If the script ever
stops running mid-spike, the hold expires on its own within `HOLD_HOURS`
(default 3) and your schedule resumes. The script can never permanently
strand your house.

**Manual holds are sacred.** The script identifies its own holds by
checking whether the current setpoints exactly equal `OFF_PAIR`,
`MAX_PAIR_COOL`, or `MAX_PAIR_HEAT`. The MAX pairs are included so the
script can recognize and release its own MAX holds when the price is no
longer negative. Without them, a MAX hold would look like a human hold,
the script would refuse to release it, and your house would be stuck at
the MAX setpoints until you intervened manually. Any hold whose setpoints
match none of the three pairs is assumed to be yours and is never touched —
not overridden during a spike, not released when price is cheap.

**Notifications fire only when something actually changes**, so you won't
get spammed every 10 minutes during a long spike — just one push when the
state transitions.

## Security model (public repo)

All credentials are GitHub **Actions Secrets** — never in the repo. The
script never prints tokens or raw API bodies (Actions logs here are
public). Fork PRs don't receive secrets (GitHub default); also enable
Settings → Actions → "Require approval for all outside collaborators".

## Setup (one time, ~30 minutes)

1. **Resideo developer app** — sign up free at
   https://developer.honeywellhome.com, create an app with redirect URL
   `https://localhost/callback`. Note Consumer Key (`HW_API_KEY`) and
   Consumer Secret (`HW_API_SECRET`).
2. **Refresh token** — visit
   `https://api.honeywell.com/oauth2/authorize?response_type=code&client_id=YOUR_KEY&redirect_uri=https://localhost/callback`,
   log in with your Honeywell Home account, approve; copy `code=` from the
   resulting localhost URL (valid ~10 min), then:
   ```bash
   curl -u "YOUR_KEY:YOUR_SECRET" \
     -d "grant_type=authorization_code&code=THE_CODE&redirect_uri=https://localhost/callback" \
     https://api.honeywell.com/oauth2/token
   ```
   The response's `refresh_token` is `HW_REFRESH_TOKEN`.
3. **IDs** — with an access token from
   `grant_type=refresh_token&refresh_token=...` on the same endpoint:
   ```bash
   curl -H "Authorization: Bearer ACCESS_TOKEN" \
     "https://api.honeywell.com/v2/locations?apikey=YOUR_KEY"
   ```
   Grab `locationID` (`HW_LOCATION_ID`) and your thermostat `deviceID`
   (`HW_DEVICE_ID`, like `LCC-00D02D...`).
4. **ntfy** — install the ntfy app, subscribe to an unguessable topic name
   you invent (e.g. `comed-guard-x7k2m9q4`). That name is `NTFY_TOPIC`.
   Leave the secret unset to disable notifications.
5. **Add the secrets** — repo Settings → Secrets and variables → Actions:
   `HW_API_KEY`, `HW_API_SECRET`, `HW_REFRESH_TOKEN`, `HW_DEVICE_ID`,
   `HW_LOCATION_ID`, `NTFY_TOPIC` (optional).
6. **Tune the constants** at the top of `guard.py` and push.

## Testing locally

```bash
pip install -r requirements.txt

# Run the decision logic tests (no credentials needed)
python test_decide.py

# Dry run — reads live price and thermostat, logs decision, never writes
HW_API_KEY=... HW_API_SECRET=... HW_REFRESH_TOKEN=... \
HW_DEVICE_ID=... HW_LOCATION_ID=... DRY_RUN=true python guard.py
```

## Things to know

- **The house drifts during spikes.** OFF means "hold at your hard limits",
  so on a brutal peak day the house will genuinely approach 84°F before
  the AC intervenes. Pick `OFF_PAIR` numbers you accept on the worst day.
- **Your weekly schedule must exist.** Release and hold-expiry both mean
  "resume schedule". Confirm in the Honeywell app → Thermostat → Schedule
  that weekly periods are programmed.
- **`MAX_PAIR_COOL` and `MAX_PAIR_HEAT` are independent.** Tune them
  separately for what makes sense in your climate. Keep heatF a few degrees
  below coolF in each pair if you ever use Auto mode (Resideo enforces a
  deadband between the two setpoints).
- **Refresh token longevity.** Honeywell refresh tokens are long-lived in
  practice but not officially eternal. If runs start failing at stage
  `auth`, you'll get a loud ntfy with instructions: redo setup step 2 and
  update `HW_REFRESH_TOKEN`. The keepalive workflow keeps the cron alive
  but does NOT keep the token alive.
- **Cron drift:** GitHub schedules can lag 5–15 min when busy — fine,
  since billing is on hourly averages.

## Go-live checklist

- [ ] Actions → ComEd Price Guard → Run workflow with **Dry run** checked.
      Log shows the live price, your thermostat state, and the decision.
- [ ] Temporarily set `OFF_AT_CENTS = 0.1`, run **without** dry run:
      thermostat goes to 84/58 within seconds and a push arrives. Revert.
- [ ] Run again at the normal threshold: log shows RELEASE, the schedule
      resumes, and a push arrives.
- [ ] Set a manual hold in the Honeywell app, set `OFF_AT_CENTS = 0.1`,
      run: log says "manual hold present; respecting it" and nothing
      changes. Remove the hold, revert the constant.
- [ ] Trigger the Keepalive workflow manually: commit lands in repo.
- [ ] Auth-failure path: temporarily corrupt the `HW_REFRESH_TOKEN` secret
      (add a character), dispatch: loud ntfy with redo instructions
      arrives; exit code 1. Restore the token.
- [ ] Let the cron run for a week; check Actions history after the first
      real spike (and after the first negative-price night).
