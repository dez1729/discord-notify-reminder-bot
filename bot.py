import os
import discord
from discord import app_commands
from dotenv import load_dotenv
import db
import scheduler as sched
from typing import Literal
import roster
from discord.ext import tasks
from datetime import datetime
import pytz
import ast

TZ = pytz.timezone("America/Vancouver")

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
    rows = db.get_all_messages()
    for row in rows:
        row_id, channel_ids_str, message, fire_at, cron_expr, created_by, roster_list, advance_roster = row

        user_tz = get_tz_for_user(created_by)
        now_local = now_utc.astimezone(user_tz)

        if cron_expr:
            from croniter import croniter
            cron = croniter(cron_expr, now_local)
            prev = cron.get_prev(datetime)
            if prev.tzinfo is None:
                prev = user_tz.localize(prev)
            if (now_local - prev).total_seconds() <= 60:
                channel_ids = ast.literal_eval(channel_ids_str)
                await sched.send_to_channels(client, channel_ids, message, roster_list, bool(advance_roster))
        elif fire_at:
            fire_dt = datetime.fromisoformat(fire_at).astimezone(pytz.utc)
            if now_utc >= fire_dt and (now_utc - fire_dt).total_seconds() <= 60:
                channel_ids = ast.literal_eval(channel_ids_str)
                await sched.send_to_channels(client, channel_ids, message, roster_list, bool(advance_roster))

@tasks.loop(minutes=1)
async def custom_job_runner():
    now = datetime.now(TZ)
    rows = db.get_all_custom_jobs()
    for row in rows:
        job_id, channel_ids_str, message, hour, minute, saturday_hour, saturday_minute, start_date, last_run, _ = row
        channel_ids = ast.literal_eval(channel_ids_str)

        # figure out what time to expect today
        if now.weekday() == 5:  # Saturday
            expected_hour, expected_minute = saturday_hour, saturday_minute
        else:
            expected_hour, expected_minute = hour, minute

        # check if we should fire now
        if now.hour == expected_hour and now.minute == expected_minute:
            # check if this is a valid every-other-day slot
            last_run_dt = datetime.fromisoformat(last_run).astimezone(TZ) if last_run else None
            next_run = sched.get_next_every_other_day(last_run_dt, hour, minute, saturday_hour, saturday_minute, start_date if not last_run else None)

            if abs((now - next_run).total_seconds()) <= 60:
                for channel_id in channel_ids:
                    channel = client.get_channel(int(channel_id))
                    if channel:
                        await channel.send(message)
                db.update_custom_job_last_run(job_id, now.isoformat())
                print(f"Custom job {job_id} fired at {now}")

@job_runner.before_loop
async def before_job_runner():
    await client.wait_until_ready()

@custom_job_runner.before_loop
async def before_custom_job_runner():
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
    if not custom_job_runner.is_running():
        custom_job_runner.start()

@tree.command(name="schedule", description="Schedule a message to one or more channels")
@app_commands.describe(
    channels="Channel mentions e.g. #general #announcements",
    message="The message to send. Use {roster} to insert today's roster name",
    time="One-shot datetime e.g. 2026-04-20T09:00:00 — interpreted in your set timezone",
    cron="Cron expression e.g. '0 9 * * 1' for every Monday 9am — interpreted in your set timezone",
    roster_list="If using {roster} in your message, which list to use",
    advance_roster="Whether to advance the roster after sending"
)
async def schedule(
    interaction: discord.Interaction,
    channels: str,
    message: str,
    time: str = None,
    cron: str = None,
    roster_list: Literal["244", "297"] = None,
    advance_roster: bool = True
):
    if not time and not cron:
        await interaction.response.send_message("You must provide either a time or a cron expression.", ephemeral=True)
        return

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

    row_id = db.add_message(channel_ids, message, fire_at_utc, cron, str(interaction.user.id), roster_list, advance_roster)
    await interaction.response.send_message(f"Scheduled! ID: `{row_id}`", ephemeral=True)

@tree.command(name="listschedules", description="List all scheduled messages")
async def listschedules(interaction: discord.Interaction):
    rows = db.get_all_messages()
    if not rows:
        await interaction.response.send_message("No scheduled messages.", ephemeral=True)
        return

    lines = []
    for row in rows:
        row_id, channel_ids_str, message, fire_at, cron_expr, created_by, roster_list, advance_roster = row
        user_tz = get_tz_for_user(interaction.user.id)

        if cron_expr:
            from croniter import croniter
            now = datetime.now(TZ)
            cron = croniter(cron_expr, now)
            next_run = cron.get_next(datetime)
            # strip tzinfo if already set before localizing
            if next_run.tzinfo is not None:
                next_run = next_run.replace(tzinfo=None)

            next_run_str = format_dt(TZ.localize(next_run), user_tz)
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
            f"`ID {row_id}` | next run: {next_run_str}{roster_info} | {message[:100]}{'...' if len(message) > 100 else ''}"
        )

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tree.command(name="deleteschedule", description="Delete a scheduled message by ID")
@app_commands.describe(id="The schedule ID from /listschedules")
async def deleteschedule(interaction: discord.Interaction, id: int):
    deleted = db.delete_message(id)

    if deleted:
        await interaction.response.send_message(f"Deleted schedule `{id}`.", ephemeral=True)
    else:
        await interaction.response.send_message(f"No schedule found with ID `{id}`.", ephemeral=True)


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
    if not time and not cron:
        await interaction.response.send_message("You must provide either a time or a cron expression.", ephemeral=True)
        return

    # reuse the schedule infrastructure with a sentinel message
    row_id = db.add_message([], "{advance_only}", time, cron, str(interaction.user.id), list_name, True)

    timing = cron if cron else time
    await interaction.response.send_message(f"Roster {list_name} will advance on schedule: `{timing}` (ID: `{row_id}`)", ephemeral=True)

@tree.command(name="scheduleeveryotherday", description="Schedule a message every other day, moving to Saturday if it falls on Friday")
@app_commands.describe(
    channels="Channel mentions e.g. #general #announcements",
    message="The message to send",
    hour="Hour to send on regular days (24h, in your set timezone)",
    minute="Minute to send on regular days",
    saturday_hour="Hour to send if moved to Saturday (24h, in your set timezone)",
    saturday_minute="Minute to send if moved to Saturday",
    start_date="Date of the first run e.g. 2026-04-11"
)
async def scheduleeveryotherday(
    interaction: discord.Interaction,
    channels: str,
    message: str,
    hour: int,
    minute: int,
    saturday_hour: int,
    saturday_minute: int,
    start_date: str = None
):
    channel_ids = [c.strip("<>#") for c in channels.split() if c.startswith("<#")]
    if not channel_ids:
        await interaction.response.send_message("No valid channel mentions found.", ephemeral=True)
        return

    # convert hour/minute from user timezone to Vancouver time (what the runner uses)
    user_tz = get_tz_for_user(interaction.user.id)
    now = datetime.now(user_tz)

    # create a sample datetime in user tz and convert to Vancouver to get offset
    sample = user_tz.localize(now.replace(hour=hour, minute=minute, second=0, microsecond=0))
    sample_van = sample.astimezone(TZ)
    converted_hour, converted_minute = sample_van.hour, sample_van.minute

    sample_sat = user_tz.localize(now.replace(hour=saturday_hour, minute=saturday_minute, second=0, microsecond=0))
    sample_sat_van = sample_sat.astimezone(TZ)
    converted_saturday_hour, converted_saturday_minute = sample_sat_van.hour, sample_sat_van.minute

    job_id = db.add_custom_job(
        channel_ids, message,
        converted_hour, converted_minute,
        converted_saturday_hour, converted_saturday_minute,
        str(interaction.user.id), start_date
    )

    next_run = sched.get_next_every_other_day(None, converted_hour, converted_minute, converted_saturday_hour, converted_saturday_minute, start_date)

    await interaction.response.send_message(
        f"Scheduled! ID: `{job_id}`. First run: `{format_dt(next_run, user_tz)}`",
        ephemeral=True
    )

@tree.command(name="listcustomjobs", description="List all every-other-day jobs")
async def listcustomjobs(interaction: discord.Interaction):
    rows = db.get_all_custom_jobs()
    if not rows:
        await interaction.response.send_message("No custom jobs scheduled.", ephemeral=True)
        return

    lines = []
    for row in rows:
        job_id, channel_ids_str, message, hour, minute, saturday_hour, saturday_minute, start_date, last_run, _ = row

        # calculate next run time
        last_run_dt = datetime.fromisoformat(last_run).astimezone(TZ) if last_run else None
        next_run = sched.get_next_every_other_day(
            last_run_dt, hour, minute, saturday_hour, saturday_minute,
            start_date if not last_run else None
        )

        user_tz = get_tz_for_user(interaction.user.id)
        next_run_str = format_dt(next_run, user_tz)

        last = last_run if last_run else "never"
        start = start_date if start_date else "none"
        lines.append(
            f"`ID {job_id}` | every other day @ {hour:02d}:{minute:02d} "
            f"(fri->sat: {saturday_hour:02d}:{saturday_minute:02d}) "
            f"| start: {start} | last run: {last} | next run: {next_run_str} | {message[:100]}{'...' if len(message) > 100 else ''}"
        )

    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@tree.command(name="deletecustomjob", description="Delete an every-other-day job by ID")
@app_commands.describe(id="The job ID from /listcustomjobs")
async def deletecustomjob(interaction: discord.Interaction, id: int):
    deleted = db.delete_custom_job(id)

    if deleted:
        await interaction.response.send_message(f"Deleted custom job `{id}`.", ephemeral=True)
    else:
        await interaction.response.send_message(f"No custom job found with ID `{id}`.", ephemeral=True)

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