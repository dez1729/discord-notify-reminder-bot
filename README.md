# High Seas Hero Discord Bot

Discord bot for a private server to support High Seas Hero (HSH). Manages notifications, reminders, and guild freighter rosters for servers 244 and 297. Runs via Docker on a local machine.

## Features

- One-shot, cron, and interval-based scheduled messages
- Roster management with automatic or manual advancement
- Per-user timezone support
- Persistent schedules survive restarts via Docker volume

## Installation

1. Clone the repository
2. Create a `.env` file with your credentials (see below)
3. Create the `data/` directory and add roster files (see Notes)
4. Grant the bot permission to send messages in your target channels
5. Run with Docker Compose: `docker-compose up --build -d`

### `.env` file

```env
DISCORD_TOKEN=your-bot-token
GUILD_ID=your-guild-id
```

## Commands

### `/schedule` — Schedule a message

Supports three scheduling modes. All times are interpreted in your set timezone (see `/settimezone`).

| Parameter | Description |
| --- | --- |
| `channels` | Channel mentions e.g. `#general #announcements` |
| `message` | Message to send. Use `{roster}` to insert the current roster name |
| `time` | **One-shot**: datetime e.g. `2026-04-20T09:00:00` |
| `cron` | **Cron**: expression e.g. `0 9 * * 1` for every Monday at 9am |
| `interval_days` | **Interval**: run every X days |
| `interval_time` | **Interval**: time of day `HH:MM` e.g. `17:00` |
| `interval_start` | **Interval**: start date `YYYY-MM-DD` (defaults to today) |
| `interval_skip_weekday` | **Interval**: skip the run if it falls on this weekday |
| `roster_list` | Which roster to use with `{roster}` (`244` or `297`) |
| `advance_roster` | Whether to advance the roster after sending (default: yes) |

**Examples:**

```text
/schedule channels:#general message:Reminder! cron:0 17 * * 1-5
/schedule channels:#general message:Freighter time! interval_days:2 interval_time:17:00 interval_skip_weekday:friday
/schedule channels:#general message:One-time alert time:2026-07-01T09:00:00
```

### `/listschedules` — List all scheduled messages

Shows all active schedules with their ID, next run time, and message preview.

### `/deleteschedule` — Delete a schedule by ID

```text
/deleteschedule id:42
```

Use the ID shown by `/listschedules`.

### `/scheduleadvance` — Schedule an automatic roster advance

Advances a roster on a schedule without sending a message.

| Parameter | Description |
| --- | --- |
| `list_name` | Roster to advance (`244` or `297`) |
| `cron` | Cron expression |
| `time` | One-shot datetime |

### `/roster` — Show a roster

Displays the full roster and who is currently up.

### `/rosteradvance` — Manually advance the roster

Moves the roster to the next person and shows who is now up.

### `/rosterset` — Set the roster position

```text
/rosterset list_name:244 position:3
```

Sets the current position to a specific number (1-indexed).

### `/settimezone` — Set your timezone

```text
/settimezone timezone:America/Vancouver
```

All schedule times you create or view will use this timezone. Supports autocomplete — start typing a city name.

## Notes

### Roster files

Rosters are stored in the `data/` directory as plain text files, one entry per line. Name the files `names-244.txt` and `names-297.txt`.

```text
<@123456789012345678> # username — comment for your reference
<@987654321098765432> # another person
```

### Data persistence

The SQLite database and roster files live in `./data/`, which is mounted into the container. Schedules survive container rebuilds. To apply code changes without losing data:

```sh
docker-compose up --build -d
```

### Interval scheduling notes

- `interval_start` defaults to today if not specified
- `interval_skip_weekday` shifts the run to the next interval day, not just the next calendar day
- The bot checks schedules every minute; firings accurate to within ~1 minute
