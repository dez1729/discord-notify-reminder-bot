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

