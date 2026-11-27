# crossfit-to-garmin-strava

Automatically puts your CrossFit box's workout of the day (WOD) into your **Garmin Connect** activity, and optionally into the same activity on **Strava** (see [Strava](#strava-optional)). It reads the WOD from **Arbox**, and if you train at a second box too, it works out which box each session belongs to and uses that box's WOD (see [Two boxes](#two-boxes)).

You record your class on your Garmin watch as a HIIT activity. Later, this tool finds that activity and sets:

- **Title:** `CrossFit WOD`
- **Description:** the full workout from Arbox, every section (warm-up, strength, metcon...), as your box published it.

Unofficial project. Not affiliated with, endorsed by, or supported by CrossFit, Arbox, Garmin or Strava. Use it with your own accounts only.
CrossFit is a registered trademark of CrossFit, LLC; Garmin and Strava are trademarks of their owners. They are named here only to describe what the tool works with.

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

(The booking check and the WOD fetch are separate Arbox calls. If only the booking check fails, it
assumes your home box rather than misrouting to the second box. If Arbox is unreachable altogether,
there's no WOD to fetch, so nothing is written that day.)

So your home box is the default, and the second box is used only on a day you had no Arbox booking.
It looks up the correct week for each day, so a session synced a day or two later — even one from
the previous week — still gets the right WOD. If you never set up a second box, none of this
applies: every day just uses Arbox.

## Strava (optional)

Strava copies each activity from Garmin, so the same workout shows up there under a default name
like "Evening HIIT". If you set up Strava, every run also writes the same title and WOD there:

1. For each training day, the WOD is worked out **once** (from the right box, as above).
2. It's written to Garmin, then to the Strava activity that **started at the same time** as the
   Garmin one.
3. Strava follows the same rules on its own: skipped if it's already synced, or if you renamed it or
   wrote a description. If Strava hasn't received the activity yet, a later run catches it.

A Strava problem never stops the Garmin sync.

**Why it uses the website.** Strava's app requires Google Play Integrity (a check that the app runs
unmodified on a real phone), so a script can't use the app's API. This tool makes the same calls the
strava.com website makes, with your browser's login. Strava's terms don't allow automating the
website, so this is at your own risk. The clean alternative is Strava's official API, but writing to
activities through it needs a paid Strava subscription.

**Logging in, about once a month.** Strava's "Remember me" login lasts 30 days and does not renew
itself:

1. Open strava.com in a private (Incognito) window and log in **with your email** (not Google),
   with **Remember me** ticked.
2. Press F12 → **Network** → reload the page → click the `training` row → **Request Headers** →
   right-click the `cookie:` value → **Copy value**.
3. Run `python -m arbox_sync strava login` and paste it (the prompt hides it). It keeps only the two
   "Remember me" cookies, saves them, and prints the date they expire.
4. Put the saved session file's contents in the `STRAVA_SESSION` secret.
5. Close the window **without logging out**: logging out would end that login.

Three days before the login expires, a run fails on purpose so GitHub emails you while Strava still
works. If you miss it, Strava is skipped until you log in again, and the next run fills in the days
you missed (within the lookback).

## Requirements

- Python 3.12 or newer
- A Garmin Connect account
- An Arbox member account with a password (the app's "Log in with password" option)
- Optional: a second box on the "Box WOD" platform, if you sometimes train somewhere
  else (see [Two boxes](#two-boxes) above)
- Optional: a Strava account connected to Garmin (see [Strava](#strava-optional) above)

## One-time setup

```bash
git clone https://github.com/aoao-tech/crossfit-to-garmin-strava.git
cd crossfit-to-garmin-strava
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Log in to both services once. You type your passwords, and only login tokens are kept, never the passwords:

```bash
python -m arbox_sync garmin login       # asks for email, password, and an MFA code if your account has one
python -m arbox_sync arbox login        # asks for email and password
python -m arbox_sync crossfitey login   # optional: only if you use a second box
python -m arbox_sync strava login       # optional: only for Strava; paste your browser's cookie (see Strava)
```

## Running it

Preview first. A dry run changes nothing:

```bash
python -m arbox_sync sync                 # last 5 days, dry run
python -m arbox_sync sync --apply         # last 5 days, writes to Garmin (and Strava if set up)
```

Options:

| Option | Meaning |
|---|---|
| `--date YYYY-MM-DD` | last day to process (default: today, Asia/Jerusalem time) |
| `--backfill N` | process N days ending at `--date` (default 5) |
| `--apply` | actually write to Garmin and Strava; without it nothing changes |

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
python -m arbox_sync strava activities --date 2026-11-22  # list your Strava activities that day
```

## Running on a schedule

The `sync` workflow runs automatically in GitHub Actions every 2 days in the evening (Israel time), processing the
last 5 days, so your computer can stay off. GitHub sometimes delays or drops a scheduled run; 5 days means even a
dropped run is caught up by the next one. You can also start it by hand from the Actions tab, with an optional date,
number of days, and a "dry run" switch.

The workflow needs these secrets:

| Secret | What it is |
|---|---|
| `GARMIN_TOKENS` | the Garmin login tokens created by `garmin login` |
| `ARBOX_TOKEN` | the Arbox login token created by `arbox login` |
| `CROSSFITEY_SESSION` | optional: the second box's session created by `crossfitey login`, only if you use one |
| `STRAVA_SESSION` | optional: the Strava "Remember me" login saved by `strava login`, only for Strava (renew monthly) |
| `SECRETS_PAT` | a fine-grained GitHub token, limited to this repository with Secrets read/write, so the workflow can save logins that get refreshed |

The included `garmin-smoke` workflow is a manual, read-only check that the Garmin tokens work from GitHub.

If a login ever expires, the run fails with a clear message. Run the matching `login` command again and update that secret.
The Strava login also warns you a few days early (see [Strava](#strava-optional)).

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
| `SYNC_LOOKBACK_DAYS` | `5` | default number of days per run |
| `SYNC_ACTIVITY_TYPES` | `hiit,indoor_cardio,cardio` | Garmin activity types that count as a class |
| `SYNC_FALLBACK_TITLE` | `CrossFit WOD` | title written to the activity |
| `ARBOX_BOXES_ID` | `23` | your home Arbox box id (used to check registration) |
| `ARBOX_LOCATIONS_BOX_ID` | `6` | your home Arbox location id |
| `CROSSFITEY_TRACK` | `CROSSFIT` | which track to read from the second box |
| `STRAVA_RENEW_WARN_DAYS` | `3` | how many days before the Strava login expires a run fails to warn you |

## How the Arbox part was built

Arbox has no public member API. The app's own requests were recorded once from an Android emulator, cleaned of all
personal data, and documented in [`api/API_NOTES.md`](api/API_NOTES.md) and [`api/arbox-openapi.yaml`](api/arbox-openapi.yaml)
(generated with [mitmproxy2swagger](https://github.com/alufers/mitmproxy2swagger)).
The Garmin part uses [python-garminconnect](https://github.com/cyberjunky/python-garminconnect).
The Strava part uses three calls of the strava.com website (activity list, the page holding the security token, and
saving an activity), recorded once from a browser and also listed in [`api/API_NOTES.md`](api/API_NOTES.md).

## Development

```bash
pytest          # all tests run offline; network access is blocked in tests
```

## License

MIT. See [LICENSE](LICENSE).
