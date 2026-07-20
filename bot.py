import os
import sys
import atexit
import asyncio
import discord
from discord import app_commands
from dotenv import load_dotenv
import db
import scheduler as sched
from typing import Literal
import roster
from discord.ext import tasks
from datetime import datetime, date as dt_date, timedelta, time as dt_time
import pytz
import ast

TZ = pytz.timezone("America/Vancouver")

PID_FILE = "bot.pid"

def _acquire_pid_file():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                os.kill(old_pid, 0)  # raises OSError if process is gone
                print(f"[startup] Another instance is already running (PID {old_pid}). Exiting.")
                sys.exit(1)
        except (OSError, ValueError):
            pass  # stale PID file from a crashed run
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(PID_FILE) and os.remove(PID_FILE))

_acquire_pid_file()

WEEKDAY_MAP = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
WEEKDAY_SHORT = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def format_dt(dt: datetime, user_tz: pytz.timezone = None) -> str:
    local_tz = user_tz or TZ
    local = dt.astimezone(local_tz)
    utc = dt.astimezone(pytz.utc)
    offset = local.strftime("%z")
    offset_str = f"UTC{offset[:3]}:{offset[3:]}"
    return (
        f"{local.strftime('%A %Y-%m-%d %I:%M %p')} ({offset_str}) / "
        f"{utc.strftime('%Y-%m-%d %I:%M %p')} UTC"
    )

@tasks.loop(minutes=1)
async def job_runner():
    now_utc = datetime.now(pytz.utc)
    _task = asyncio.current_task()
    _named = [t for t in asyncio.all_tasks() if t.get_name() == (_task.get_name() if _task else None)]
    print(f"[DEBUG-dupe] tick start now_utc={now_utc.isoformat()} task_id={id(_task)} "
          f"same_named_tasks_alive={len(_named)} total_tasks={len(asyncio.all_tasks())}")
    rows = db.get_all_messages()
    print(f"[DEBUG-dupe] fetched {len(rows)} rows task_id={id(_task)}")
    for row in rows:
        row_id, channel_ids_str, message, fire_at, cron_expr, created_by, roster_list, advance_roster, last_run, \
            interval_days, interval_time, interval_start, interval_skip_weekday = row

        user_tz = get_tz_for_user(created_by)
        now_local = now_utc.astimezone(user_tz)

        if cron_expr:
            from croniter import croniter
            cron = croniter(cron_expr, now_local)
            prev = cron.get_prev(datetime)
            if prev.tzinfo is None:
                prev = user_tz.localize(prev)
            if (now_local - prev).total_seconds() < 60:
                # skip if we already fired for this cron occurrence
                if last_run:
                    last_run_dt = datetime.fromisoformat(last_run)
                    if last_run_dt.tzinfo is None:
                        last_run_dt = user_tz.localize(last_run_dt)
                    if abs((last_run_dt - prev).total_seconds()) < 60:
                        continue
                print(f"[DEBUG-dupe] SENDING row_id={row_id} branch=cron occurrence={prev.isoformat()} "
                      f"task_id={id(_task)} now={now_utc.isoformat()}")
                # record before sending: if the process is killed mid-send (e.g. PC
                # restart), the marker is already durable so we won't resend on restart
                db.update_message_last_run(row_id, now_local.isoformat())
                channel_ids = ast.literal_eval(channel_ids_str)
                await sched.send_to_channels(client, channel_ids, message, roster_list, bool(advance_roster))
                print(f"[DEBUG-dupe] SENT row_id={row_id} task_id={id(_task)}")
        elif interval_days:
            start = dt_date.fromisoformat(interval_start)
            today = now_local.date()
            days_elapsed = (today - start).days
            if days_elapsed < 0:
                continue
            if days_elapsed % interval_days != 0:
                continue
            if interval_skip_weekday is not None and today.weekday() == interval_skip_weekday:
                continue
            fire_h, fire_m = map(int, interval_time.split(":"))
            if now_local.hour != fire_h or now_local.minute != fire_m:
                continue
            if last_run:
                last_run_dt = datetime.fromisoformat(last_run)
                if last_run_dt.tzinfo is None:
                    last_run_dt = user_tz.localize(last_run_dt)
                if last_run_dt.astimezone(user_tz).date() == today:
                    continue
            print(f"[DEBUG-dupe] SENDING row_id={row_id} branch=interval occurrence={today.isoformat()} "
                  f"task_id={id(_task)} now={now_utc.isoformat()}")
            db.update_message_last_run(row_id, now_local.isoformat())
            channel_ids = ast.literal_eval(channel_ids_str)
            await sched.send_to_channels(client, channel_ids, message, roster_list, bool(advance_roster))
            print(f"[DEBUG-dupe] SENT row_id={row_id} task_id={id(_task)}")
        elif fire_at:
            fire_dt = datetime.fromisoformat(fire_at).astimezone(pytz.utc)
            if now_utc >= fire_dt and (now_utc - fire_dt).total_seconds() <= 60:
                if last_run:
                    continue
                print(f"[DEBUG-dupe] SENDING row_id={row_id} branch=fire_at task_id={id(_task)} now={now_utc.isoformat()}")
                db.update_message_last_run(row_id, now_local.isoformat())
                channel_ids = ast.literal_eval(channel_ids_str)
                await sched.send_to_channels(client, channel_ids, message, roster_list, bool(advance_roster))
                print(f"[DEBUG-dupe] SENT row_id={row_id} task_id={id(_task)}")

@job_runner.before_loop
async def before_job_runner():
    await client.wait_until_ready()

@client.event
async def on_ready():
    db.setup()

    guild = discord.Object(id=GUILD_ID)
    tree.copy_global_to(guild=guild)
    synced = await tree.sync(guild=guild)

    print(f"Logged in as {client.user}")
    print(f"Synced {len(synced)} commands: {[c.name for c in synced]}")

    if not job_runner.is_running():
        job_runner.start()

@tree.command(name="schedule", description="Schedule a message to one or more channels")
@app_commands.describe(
    channels="Channel mentions e.g. #general #announcements",
    message="The message to send. Use {roster} to insert today's roster name",
    time="One-shot datetime e.g. 2026-04-20T09:00:00 — interpreted in your set timezone",
    cron="Cron expression e.g. '0 9 * * 1' for every Monday 9am — interpreted in your set timezone",
    roster_list="If using {roster} in your message, which list to use",
    advance_roster="Whether to advance the roster after sending",
    interval_days="Interval mode: run every X days",
    interval_time="Interval mode: time of day HH:MM e.g. 17:00 — interpreted in your set timezone",
    interval_start="Interval mode: start date YYYY-MM-DD (defaults to today)",
    interval_skip_weekday="Interval mode: skip the run if it lands on this weekday"
)
async def schedule(
    interaction: discord.Interaction,
    channels: str,
    message: str,
    time: str = None,
    cron: str = None,
    roster_list: Literal["244", "297"] = None,
    advance_roster: bool = True,
    interval_days: int = None,
    interval_time: str = None,
    interval_start: str = None,
    interval_skip_weekday: Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] = None,
):
    if not db.claim_interaction(interaction.id):
        return

    using_interval = interval_days is not None or interval_time is not None

    if not time and not cron and not using_interval:
        await interaction.response.send_message("You must provide either a time, a cron expression, or interval options.", ephemeral=True)
        return

    if using_interval:
        if interval_days is None or interval_time is None:
            await interaction.response.send_message("Interval mode requires both `interval_days` and `interval_time`.", ephemeral=True)
            return
        try:
            fire_h, fire_m = map(int, interval_time.split(":"))
            if not (0 <= fire_h <= 23 and 0 <= fire_m <= 59):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Invalid `interval_time`. Use HH:MM e.g. `17:00`.", ephemeral=True)
            return
        if interval_start:
            try:
                dt_date.fromisoformat(interval_start)
            except ValueError:
                await interaction.response.send_message("Invalid `interval_start`. Use YYYY-MM-DD e.g. `2026-06-06`.", ephemeral=True)
                return
        else:
            user_tz = get_tz_for_user(interaction.user.id)
            interval_start = datetime.now(user_tz).strftime("%Y-%m-%d")

    if "{roster}" in message and not roster_list:
        await interaction.response.send_message("You used {roster} but didn't pick a roster list.", ephemeral=True)
        return

    channel_ids = [c.strip("<>#") for c in channels.split() if c.startswith("<#")]
    if not channel_ids:
        await interaction.response.send_message("No valid channel mentions found.", ephemeral=True)
        return

    user_tz = get_tz_for_user(interaction.user.id)

    # convert one-shot time from user timezone to UTC for storage
    fire_at_utc = None
    if time:
        try:
            naive_dt = datetime.strptime(time, "%Y-%m-%dT%H:%M:%S")
            local_dt = user_tz.localize(naive_dt)
            fire_at_utc = local_dt.astimezone(pytz.utc).isoformat()
        except ValueError:
            await interaction.response.send_message("Invalid time format. Use e.g. `2026-04-20T09:00:00`", ephemeral=True)
            return

    skip_weekday_int = WEEKDAY_MAP[interval_skip_weekday] if interval_skip_weekday else None

    row_id = db.add_message(
        channel_ids, message, fire_at_utc, cron, str(interaction.user.id), roster_list, advance_roster,
        interval_days=interval_days if using_interval else None,
        interval_time=interval_time if using_interval else None,
        interval_start=interval_start if using_interval else None,
        interval_skip_weekday=skip_weekday_int,
    )
    await interaction.response.send_message(f"Scheduled! ID: `{row_id}`", ephemeral=True)

@tree.command(name="listschedules", description="List all scheduled messages")
async def listschedules(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    rows = db.get_all_messages()
    if not rows:
        await interaction.followup.send("No scheduled messages.", ephemeral=True)
        return

    user_tz = get_tz_for_user(interaction.user.id)
    lines = []
    for row in rows:
        row_id, channel_ids_str, message, fire_at, cron_expr, created_by, roster_list, advance_roster, _last_run, \
            interval_days, interval_time, interval_start, interval_skip_weekday = row
        interval_desc = ""

        if cron_expr:
            from croniter import croniter
            now = datetime.now(TZ)
            cron = croniter(cron_expr, now)
            next_run = cron.get_next(datetime)
            # strip tzinfo if already set before localizing
            if next_run.tzinfo is not None:
                next_run = next_run.replace(tzinfo=None)

            next_run_str = format_dt(TZ.localize(next_run), user_tz)
        elif interval_days:
            now_local = datetime.now(user_tz)
            today = now_local.date()
            start = dt_date.fromisoformat(interval_start)
            fire_h, fire_m = map(int, interval_time.split(":"))

            days_elapsed = (today - start).days
            if days_elapsed < 0:
                candidate = start
            else:
                remainder = days_elapsed % interval_days
                if remainder == 0:
                    fire_today = now_local.replace(hour=fire_h, minute=fire_m, second=0, microsecond=0)
                    candidate = today if now_local < fire_today else today + timedelta(days=interval_days)
                else:
                    candidate = today + timedelta(days=interval_days - remainder)

            iters = 0
            while interval_skip_weekday is not None and candidate.weekday() == interval_skip_weekday:
                candidate += timedelta(days=interval_days)
                iters += 1
                if iters > 365:
                    break

            next_run_str = format_dt(user_tz.localize(datetime.combine(candidate, dt_time(fire_h, fire_m))), user_tz)
            skip_part = f", skip {WEEKDAY_SHORT[interval_skip_weekday]}" if interval_skip_weekday is not None else ""
            interval_desc = f" | every {interval_days}d at {interval_time} from {interval_start}{skip_part}"
        elif fire_at:
            fire_dt = datetime.fromisoformat(fire_at).astimezone(TZ)
            next_run_str = format_dt(fire_dt, user_tz)
        else:
            next_run_str = "unknown"

        roster_info = ""
        if roster_list:
            state = roster.load_state(roster_list)
            names = roster.load_names(roster_list)
            total = len(names)
            current_index = state["current_index"] % total

            if advance_roster:
                next_index = (current_index + 1) % total
                next_name = names[next_index]
                roster_info = f" | next up: {next_name} ({next_index+1}/{total}) from roster {roster_list} | advances: yes"
            # else:
            #     current_name = names[current_index]
            #     roster_info = f" | next up: {current_name} ({current_index+1}/{total}) from roster {roster_list}"

        lines.append(
            f"`ID {row_id}` | next run: {next_run_str}{interval_desc}{roster_info} | {message[:100]}{'...' if len(message) > 100 else ''}"
        )

    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > 1900:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))

    await interaction.followup.send(chunks[0], ephemeral=True)
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk, ephemeral=True)


@tree.command(name="deleteschedule", description="Delete a scheduled message by ID")
@app_commands.describe(id="The schedule ID from /listschedules")
async def deleteschedule(interaction: discord.Interaction, id: int):
    existed = db.row_exists(id)
    await interaction.response.defer(ephemeral=True)
    if not db.claim_interaction(interaction.id):
        await interaction.followup.send("Already handled.", ephemeral=True)
        return
    deleted = db.delete_message(id)
    if deleted or existed:
        await interaction.followup.send(f"Deleted schedule `{id}`.", ephemeral=True)
    else:
        await interaction.followup.send(f"No schedule found with ID `{id}`.", ephemeral=True)


@tree.command(name="roster", description="Show a roster list and who is up today")
@app_commands.describe(list_name="Which roster list to show")
async def show_roster(interaction: discord.Interaction, list_name: Literal["244", "297"]):
    names = roster.load_names(list_name)
    if not names:
        await interaction.response.send_message(f"No names found in names-{list_name}.txt", ephemeral=True)
        return

    state = roster.load_state(list_name)
    current_index = state["current_index"] % len(names)

    lines = [f"**Roster {list_name}**\n"]
    for i, name in enumerate(names):
        if i == current_index:
            lines.append(f"➡️ **{i+1}. {name}**  ← today")
        else:
            lines.append(f"　 {i+1}. {name}")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tree.command(name="rosteradvance", description="Manually advance to the next person in a roster")
@app_commands.describe(list_name="Which roster list to advance")
async def roster_advance(interaction: discord.Interaction, list_name: Literal["244", "297"]):
    name, index, total = roster.advance(list_name)
    if not name:
        await interaction.response.send_message(f"names-{list_name}.txt is empty.", ephemeral=True)
        return
    await interaction.response.send_message(f"Advanced roster {list_name} to **{name}** ({index+1}/{total})", ephemeral=True)


@tree.command(name="rosterset", description="Manually set the current position in a roster")
@app_commands.describe(
    list_name="Which roster list to update",
    position="The position number to set as current (starting from 1)"
)
async def roster_set(interaction: discord.Interaction, list_name: Literal["244", "297"], position: int):
    names = roster.load_names(list_name)
    if not names:
        await interaction.response.send_message(f"names-{list_name}.txt is empty.", ephemeral=True)
        return
    if position < 1 or position > len(names):
        await interaction.response.send_message(f"Position must be between 1 and {len(names)}.", ephemeral=True)
        return
    roster.save_state(list_name, {"current_index": position - 1})
    await interaction.response.send_message(f"Roster {list_name} set to **{names[position-1]}** ({position}/{len(names)})", ephemeral=True)

@tree.command(name="scheduleadvance", description="Schedule an automatic roster advance at a given time")
@app_commands.describe(
    list_name="Which roster list to advance",
    cron="Cron expression e.g. '0 9 * * 1' for every Monday 9am",
    time="One-shot datetime e.g. 2026-04-20T09:00:00"
)
async def scheduleadvance(
    interaction: discord.Interaction,
    list_name: Literal["244", "297"],
    cron: str = None,
    time: str = None
):
    if not db.claim_interaction(interaction.id):
        return

    if not time and not cron:
        await interaction.response.send_message("You must provide either a time or a cron expression...", ephemeral=True)
        return

    # reuse the schedule infrastructure with a sentinel message
    row_id = db.add_message([], "{advance_only}", time, cron, str(interaction.user.id), list_name, True)

    timing = cron if cron else time
    await interaction.response.send_message(f"Roster {list_name} will advance on schedule: `{timing}` (ID: `{row_id}`)", ephemeral=True)

def get_tz_for_user(user_id: str) -> pytz.timezone:
    tz_str = db.get_user_timezone(str(user_id))
    try:
        return pytz.timezone(tz_str)
    except pytz.exceptions.UnknownTimeZoneError:
        return pytz.utc

async def timezone_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    all_timezones = pytz.all_timezones
    filtered = [tz for tz in all_timezones if current.lower() in tz.lower()]
    # Discord limits autocomplete to 25 choices
    return [app_commands.Choice(name=tz, value=tz) for tz in filtered[:25]]

@tree.command(name="settimezone", description="Set your timezone for displaying dates")
@app_commands.describe(timezone="Start typing to search e.g. Vancouver, London, Tokyo")
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def settimezone(interaction: discord.Interaction, timezone: str):
    try:
        pytz.timezone(timezone)
    except pytz.exceptions.UnknownTimeZoneError:
        await interaction.response.send_message(
            f"`{timezone}` is not a valid timezone.",
            ephemeral=True
        )
        return

    db.set_user_timezone(str(interaction.user.id), timezone)
    await interaction.response.send_message(f"Timezone set to `{timezone}`.", ephemeral=True)

client.run(TOKEN)