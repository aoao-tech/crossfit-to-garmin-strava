# garmin-to-arbox

Automatically puts your CrossFit box's workout of the day (WOD) into your **Garmin Connect** activity. It reads the WOD from **Arbox**, and if you train at a second box too, it works out which box each session belongs to and uses that box's WOD (see [Two boxes](#two-boxes)).

You record your class on your Garmin watch as a HIIT activity. Later, this tool finds that activity and sets:

- **Title:** `CrossFit WOD`
- **Description:** the full workout from Arbox, every section (warm-up, strength, metcon...), as your box published it.

Unofficial project. Not affiliated with, endorsed by, or supported by Arbox or Garmin. Use it with your own accounts only.

## How it decides what to do

Garmin decides, Arbox only fills in. For each day:

| On Garmin that day | What happens |
|---|---|
| No HIIT or cardio activity | Treated as a rest day. Arbox is not contacted. |
| Exactly one HIIT/cardio activity | That day's WOD is fetched from Arbox and written into it. |
| Two or more HIIT/cardio activities | Nothing is changed, a warning is printed. |
| Activity already synced (ends with `[arbox-sync]`) | Skipped. It never edits the same activity twice. |
| You renamed it or wrote a description yourself | Skipped. Your own edits are never overwritten. |
| Training recorded but no WOD in Arbox | Nothing is changed. |

Only the title and description change. Your workout data (time, heart rate, etc.) is never touched.

## Two boxes

You might train at two different boxes, each with its own daily workout — say your home box on
Arbox and a second box on another platform. This tool handles both and figures out, on its own,
which box each session came from.

The catch: a Garmin HIIT activity saves no location, so the tool can't tell the boxes apart from
the workout data itself. What it *can* check is whether you **booked a class** that day — you book
in the box's app before every session. So for each day you recorded a HIIT on Garmin, it runs this
check:

1. **Ask Arbox: did you book a class that day?**
2. **Yes** → you were at your home box → write the **Arbox** WOD.
3. **No** → you must have been at the **second box** → write that box's WOD instead.
4. **Can't reach Arbox to check** → assume your home box (the usual case).

So your home box is the default, and the second box is used only on a day you had no Arbox booking.
It looks up the correct week for each day, so a session synced a day or two later — even one from
the previous week — still gets the right WOD. If you never set up a second box, none of this
applies: every day just uses Arbox.

## Requirements

- Python 3.12 or newer
- A Garmin Connect account
- An Arbox member account with a password (the app's "Log in with password" option)
- Optional: a second box on the "Box WOD" platform, if you sometimes train somewhere
  else (see [Two boxes](#two-boxes) below)

## One-time setup

```bash
git clone https://github.com/aoao-tech/garmin-to-arbox.git
cd garmin-to-arbox
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Log in to both services once. You type your passwords, and only login tokens are kept, never the passwords:

```bash
python -m arbox_sync garmin login       # asks for email, password, and an MFA code if your account has one
python -m arbox_sync arbox login        # asks for email and password
python -m arbox_sync crossfitey login   # optional: only if you use a second box (see below)
```

## Running it

Preview first. A dry run changes nothing:

```bash
python -m arbox_sync sync                 # last 3 days, dry run
python -m arbox_sync sync --apply         # last 3 days, writes to Garmin
```

Options:

| Option | Meaning |
|---|---|
| `--date YYYY-MM-DD` | last day to process (default: today, Asia/Jerusalem time) |
| `--backfill N` | process N days ending at `--date` (default 3) |
| `--apply` | actually write to Garmin; without it nothing changes |

### Backfill

To fill in older sessions once, for example the last 30 days:

```bash
python -m arbox_sync sync --backfill 30            # check what it would do
python -m arbox_sync sync --backfill 30 --apply    # then do it
```

### Handy commands

```bash
python -m arbox_sync arbox wod --date 2026-11-22          # show a day's WOD as JSON
python -m arbox_sync garmin activities --date 2026-11-22  # list your Garmin activities that day
python -m arbox_sync garmin check                         # quick read-only Garmin login check
```

## Running on a schedule

The `sync` workflow runs automatically in GitHub Actions every 2 days in the evening (Israel time), processing the
last 3 days, so your computer can stay off and a missed run catches up on the next one. You can also start it by hand
from the Actions tab, with an optional date, number of days, and a "dry run" switch.

The workflow needs these three secrets:

| Secret | What it is |
|---|---|
| `GARMIN_TOKENS` | the Garmin login tokens created by `garmin login` |
| `ARBOX_TOKEN` | the Arbox login token created by `arbox login` |
| `CROSSFITEY_SESSION` | optional: the second box's session created by `crossfitey login`, only if you use one |
| `SECRETS_PAT` | a fine-grained GitHub token, limited to this repository with Secrets read/write, so the workflow can save Garmin's refreshed tokens |

The included `garmin-smoke` workflow is a manual, read-only check that the Garmin tokens work from GitHub.

If a login ever expires, the run fails with a clear message. Run the matching `login` command again and update that secret.

## Privacy and safety

- Passwords are never saved. Only login tokens are kept.
- Workflow logs print counts only (for example `updated=1 no_training=2`), never names, IDs or workout text.
- Workflows run only on their schedule or when started by hand, never on pull requests, so outside code never gets your secrets.
- A pre-commit hook scans every commit for secrets and personal values.

## Customizing

Optional environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `SYNC_TIMEZONE` | `Asia/Jerusalem` | timezone used for "today" |
| `SYNC_LOOKBACK_DAYS` | `3` | default number of days per run |
| `SYNC_ACTIVITY_TYPES` | `hiit,indoor_cardio,cardio` | Garmin activity types that count as a class |
| `SYNC_FALLBACK_TITLE` | `CrossFit WOD` | title written to the activity |
| `ARBOX_BOXES_ID` | `23` | your home Arbox box id (used to check registration) |
| `ARBOX_LOCATIONS_BOX_ID` | `6` | your home Arbox location id |
| `CROSSFITEY_TRACK` | `CROSSFIT` | which track to read from the second box |

## How the Arbox part was built

Arbox has no public member API. The app's own requests were recorded once from an Android emulator, cleaned of all
personal data, and documented in [`api/API_NOTES.md`](api/API_NOTES.md) and [`api/arbox-openapi.yaml`](api/arbox-openapi.yaml)
(generated with [mitmproxy2swagger](https://github.com/alufers/mitmproxy2swagger)).
The Garmin part uses [python-garminconnect](https://github.com/cyberjunky/python-garminconnect).

## Development

```bash
pytest          # all tests run offline; network access is blocked in tests
```

## License

MIT. See [LICENSE](LICENSE).
