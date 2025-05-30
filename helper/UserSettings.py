import sqlite3
from .Riot import Riot

class UserSettings:
    def __init__(self, data: list = None, riot:Riot=None):
        # default values
        self.channel_id = ""
        self.show_link = True
        self.screenshot = False
        self.delay = 0
        self.force_desc = False
        self.silent = 2
        self.private = False
        self.webhook = ""
        self.message_level = 0
        self.take_delays = False
        self.comments = False
        if not data:
            return
        # data is a array of settings
        # convert "False" to False and "True" to True
        for i in range(len(data)):
            if data[i] == "False":
                data[i] = False
            elif data[i] == "True":
                data[i] = True
        # assign values
        self.channel_id = data[0]
        self.show_link = data[1]
        self.screenshot = data[2]
        self.delay = data[3]
        self.force_desc = data[4]
        self.silent = data[5]
        self.private = data[6]
        self.webhook = data[7]
        if self.webhook == "None":
            self.webhook = None
        if self.webhook and not self.webhook.startswith(
            "https://discord.com/api/webhooks/"
        ):
            self.webhook = "https://discord.com/api/webhooks/" + self.webhook
        self.message_level = data[8]
        self.take_delays = data[9]
        self.comments = data[10]
        self.riot = riot

    """CREATE TABLE IF NOT EXISTS SETTINGS (
        channel_id VARCHAR(40) UNIQUE,
        showlink VARCHAR(40) DEFAULT 'True',
        screenshot VARCHAR(40) DEFAULT 'False',
        delay INT DEFAULT 0,
        forcedesc VARCHAR(40) DEFAULT 'False',
        silent INT DEFAULT 2,
        private VARCHAR(40) DEFAULT 'False',
        webhook VARCHAR(128) DEFAULT NULL,
        messagelevel INT DEFAULT 0,
        takedelays INT DEFAULT 'False'
        comments VARCHAR(128) DEFAULT 'False'
        )"""

    def write(self, conn: sqlite3.Connection):
        if not self.channel_id:
            return False
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                UPDATE settings SET
                showlink = ?,
                screenshot = ?,
                delay = ?,
                forcedesc = ?,
                silent = ?,
                private = ?,
                webhook = ?,
                messagelevel = ?,
                takedelays = ?,
                comments = ? 
                WHERE channel_id = ?
                """,
                (
                    str(self.show_link),
                    str(self.screenshot),
                    str(self.delay),
                    str(self.force_desc),
                    str(self.silent),
                    str(self.private),
                    str(self.webhook),
                    str(self.message_level),
                    str(self.take_delays),
                    str(self.comments),
                    str(self.channel_id),
                ),
            )
            conn.commit()
            return True
        return True
