from datetime import datetime, timezone

try:
    from .util import *
except ImportError:
    from util import *
from discord_webhook import DiscordWebhook

import sqlite3
import typing


def time_since(time: datetime) -> str:
    current = datetime.now(timezone.utc)
    elapsed = current - time
    elapsed = elapsed.total_seconds()
    msPerMinute = 60
    msPerHour = msPerMinute * 60
    msPerDay = msPerHour * 24
    msPerMonth = msPerDay * 30
    msPerYear = msPerDay * 365
    if elapsed < msPerMinute:
        if int(elapsed) == 1:
            return f"1 second ago"
        return f"{int(elapsed)} seconds ago"
    elif elapsed < msPerHour:
        if int(elapsed / 60) == 1:
            return f"1 minute ago"
        return f"{int(elapsed / 60)} minutes ago"
    elif elapsed < msPerDay:
        if int(elapsed / 3600) == 1:
            return f"1 hour ago"
        return f"{int(elapsed / 3600)} hours ago"
    elif elapsed < msPerMonth:
        if int(elapsed / 86400) == 1:
            return f"~ 1 day ago"
        return f"~ {int(elapsed / 86400)} days ago"
    elif elapsed < msPerYear:
        if int(elapsed / 2592000) == 1:
            return f"~ 1 month ago"
        return f"~ {int(elapsed / 2592000)} months ago"
    else:
        if int(elapsed / 31536000) == 1:
            return f"~ 1 year ago"
        return f"~ {int(elapsed / 31536000)} years ago"


class Clip:
    channel = None
    id = None
    message_id = None
    desc = None
    time = None
    time_in_seconds = None
    user_id = None
    user_name = None
    stream_link = None
    webhook = None
    delay = None
    userlevel = None
    ss_id = None
    ss_link = None
    private = False

    def __init__(self, data: typing.List[str]):
        # data is a [str]
        x = {}
        level = data[10]
        if not level:
            level = "everyone"
        self.stream_link = data[7]
        self.stream_id = data[7].split("/")[-1].split("?")[0]
        self.channel = data[0]
        self.id = data[1][-3:] + str(int(data[4]))
        self.message_id = data[1]
        self.desc = data[2]
        self.time = datetime.fromtimestamp(int(data[3]), tz=timezone.utc)
        self.time_in_seconds = data[4]
        self.user_id = data[5]
        self.user_name = data[6]
        self.delay = int(data[9]) if data[9] else 0
        self.webhook = data[8]
        self.ss_id = data[11]
        self.ss_link = data[12]
        self.hms = time_to_hms(self.time_in_seconds)
        self.download_link = f"/video/{self.id}"
        self.private = str(data[13]) == "1"
        if "automated" in self.message_id.lower():
            level = "automated"
        self.userlevel = level

        try:
            self.message_level = int(data[14])
        except (ValueError, TypeError):
            self.message_level = 0
        self.timesince = time_since(self.time)

    def __str__(self):
        return self.desc

    def json(self):
        x = {}
        x["link"] = self.stream_link
        x["author"] = {
            "name": self.user_name,
            "id": self.user_id,
            "level": self.userlevel,
        }
        x["clip_time"] = self.time_in_seconds
        x["time"] = self.time  # real life time when clip was made
        x["message"] = self.desc
        x["stream_id"] = self.stream_id
        x["dt"] = self.time.strftime("%Y-%m-%d %H:%M:%S")
        x["hms"] = self.hms
        x["id"] = self.id
        x["delay"] = self.delay
        x["discord"] = {
            "webhook": self.webhook,
            "ss_id": self.ss_id,
            "ss_link": self.ss_link,
        }
        x["download_link"] = self.download_link
        x["private"] = self.private
        x["message_level"] = self.message_level
        x["timesince"] = self.timesince
        x["channel"] = self.channel
        return x

    def edit(self, new_desc: str, conn: sqlite3.Connection, webhook_url: str = None):
        with conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE QUERIES SET clip_desc=? WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
                (
                    new_desc,
                    self.channel,
                    f"%{self.id[:3]}",
                    int(self.id[3:]) - 1,
                    int(self.id[3:]) + 1,
                ),
            )
        conn.commit()
        if webhook_url and self.webhook:
            hms = self.hms
            is_privated_str = "(P) " if self.private else ""
            new_message = f"{is_privated_str}{self.id} | **{new_desc}** \n\n{hms}\n<{self.stream_link}>"
            if self.delay:
                new_message += f"\nDelayed by {self.delay} seconds."
            if self.message_level == 1:
                new_message += f"\nClipped by {self.user_name}"
            webhook = DiscordWebhook(
                url=webhook_url,
                id=self.webhook,
                allowed_mentions={"role": [], "user": [], "everyone": False},
                content=new_message,
            )
            try:
                webhook.edit()
            except Exception as e:
                print(e)
                pass
        self.desc = new_desc
        return True

    def delete(self, conn: sqlite3.Connection, webhook_url: str = None):
        with conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
                (
                    self.channel,
                    f"%{self.id[:3]}",
                    self.time_in_seconds - 1,
                    self.time_in_seconds + 1,
                ),
            )
            conn.commit()
        if webhook_url and self.webhook:
            webhook = DiscordWebhook(
                url=webhook_url,
                id=self.webhook,
                allowed_mentions={"role": [], "user": [], "everyone": False},
            )
            try:
                webhook.delete()
            except Exception as e:
                print(e)
                pass
            if self.ss_id:
                webhook = DiscordWebhook(
                    url=webhook_url,
                    id=self.ss_id,
                    allowed_mentions={"role": [], "user": [], "everyone": False},
                )
                try:
                    webhook.delete()
                except Exception as e:
                    print(e)
                    pass
        return True
