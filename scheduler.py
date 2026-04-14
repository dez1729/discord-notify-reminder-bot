from datetime import datetime, timedelta
import pytz
import roster

async def send_to_channels(bot, channel_ids: list, message: str, roster_list: str = None, advance_roster: bool = True):
    if message == "{advance_only}":
        if roster_list:
            roster.advance(roster_list)
        return

    if "{roster}" in message and roster_list:
        if advance_roster:
            roster.advance(roster_list)
        name, index, total = roster.get_current(roster_list)
        if name:
            message = message.replace("{roster}", name)

    for channel_id in channel_ids:
        try:
            channel = bot.get_channel(int(channel_id))
            if channel:
                await channel.send(message)
            else:
                print(f"Channel {channel_id} not found")
        except Exception as e:
            print(f"Failed to send to channel {channel_id}: {e}")

def get_next_every_other_day(last_run: datetime, hour: int, minute: int, saturday_hour: int, saturday_minute: int, start_date: str = None) -> datetime:
    tz = pytz.timezone("America/Vancouver")
    now = datetime.now(tz)

    if start_date:
        anchor = datetime.strptime(start_date, "%Y-%m-%d").replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        anchor = tz.localize(anchor)
    elif last_run:
        anchor = last_run.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        anchor = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # walk forward from anchor in 2-day steps until we find a slot at or after now
    # compare at minute granularity — anchor has second=0 from .replace(), so using
    # <= would overshoot when now has non-zero seconds within the same minute
    now_min = now.replace(second=0, microsecond=0)
    candidate = anchor
    while candidate < now_min:
        candidate += timedelta(days=2)

    # apply the regular time (in case anchor had a different time)
    candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # if it lands on Friday, push to Saturday with saturday time
    if candidate.weekday() == 4:
        candidate = (candidate + timedelta(days=1)).replace(
            hour=saturday_hour, minute=saturday_minute, second=0, microsecond=0
        )

    return candidate
