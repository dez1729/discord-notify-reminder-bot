import asyncio
import roster
from datetime import datetime, timezone

async def send_to_channels(bot, channel_ids: list, message: str, roster_list: str = None, advance_roster: bool = True):
    _task_id = id(asyncio.current_task())
    print(f"[DEBUG-dupe] send_to_channels ENTER task_id={_task_id} now={datetime.now(timezone.utc).isoformat()} "
          f"channels={channel_ids} msg={message[:40]!r}")
    if message == "{advance_only}":
        if roster_list:
            roster.advance(roster_list)
        return

    if "{roster}" in message and roster_list:
        if advance_roster:
            before = roster.get_current(roster_list)
            after = roster.advance(roster_list)
            print(f"[DEBUG-dupe] roster.advance list={roster_list} task_id={_task_id} before={before} after={after}")
        name, index, total = roster.get_current(roster_list)
        if name:
            message = message.replace("{roster}", name)

    for channel_id in channel_ids:
        try:
            channel = bot.get_channel(int(channel_id))
            if channel:
                print(f"[DEBUG-dupe] channel.send BEFORE task_id={_task_id} channel={channel_id} "
                      f"now={datetime.now(timezone.utc).isoformat()}")
                sent = await channel.send(message)
                print(f"[DEBUG-dupe] channel.send AFTER task_id={_task_id} channel={channel_id} "
                      f"message_id={sent.id} now={datetime.now(timezone.utc).isoformat()}")
            else:
                print(f"Channel {channel_id} not found")
        except Exception as e:
            print(f"[DEBUG-dupe] channel.send EXCEPTION task_id={_task_id} channel={channel_id}: {e!r}")
            print(f"Failed to send to channel {channel_id}: {e}")

