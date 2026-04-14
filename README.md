# High Seas Hero Discord Bot

This is a discord bot for a private server to support High Seas Hero (HSH) in setting up notifications and reminders. Runs locally on my machine but can be deployed to a cloud provider if needed. Used for servers 244 and 297.

## Features

- Set up recurring reminders of upcoming events
- Set up roster for people running guild freighter. Currently support servers 244 and 297. You can also advance the roster to the next person in line
- Set up every-other-day reminders for events that happen on every other day, except if it lands on a Friday, in which case it will be sent on the following Saturday instead. This is due to Friday is ambush day and we do not want the fight to overlap with the busiest time of the day

## Installation

1. Clone the repository
2. Install the dependencies
3. Set up the environment variables
4. Set up permissions on discord for the bot to access the channels you want to send messages to (you will need to be an administrator of the server)
5. Run the bot

## Usage

1. Use the `/schedule` command to set up a recurring reminder
2. Use the `/scheduleeveryotherday` command to set up a every-other-day reminder (see above)
3. Use the `/roster` command to list the roster and to see who is currently running freighter
4. Use the `/listschedules` command to list all scheduled reminders
5. Use the `/listcustomjobs` command to list all every-other-day reminders
6. Use the `/deleteschedule` command to delete a scheduled reminder
7. Use the `/deletecustomjob` command to delete a every-other-day reminder
8. Use the `/rosteradvance` command to advance the roster to the next person in line
9. Use the `/rosterset` command to set the current position in the roster
10. Use the `/scheduleadvance` command to schedule an automatic roster advance at a given time
11. Use the `/settimezone` command to set your timezone so all your schedules will be displayed and set in your preferred timezone

## Notes

- You will need to set up the two rosters manually and are named `names-244.txt` and `names-297.txt` in the data directory. The format is one name per line and you will need the discord user ID in order to ping them. For example:

```txt
<@123456789012345678> # @username is just comment for you to see who that is
```

- If you want to set up for your own server obviously change the server numbers in code
