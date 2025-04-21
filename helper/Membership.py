import sqlite3
from datetime import datetime
from json import load,loads,dump,dumps


class Membership:
    def __init__(self, data: list = None):
        # default values
        self.channel_id = ""
        self.active = False
        self.type = None
        self.active = False
        self.in_db = False
        self.start = datetime.fromtimestamp(0)
        self.end = self.start
        self.days_left = 0
        self.free_trial = False
        if not data:
            return
        self.channel_id = data[0]
        self.type = data[1]
        self.start = datetime.fromtimestamp(data[2])
        self.end = datetime.fromtimestamp(data[3])
        self.active = datetime.today() <= self.end
        self.in_db = True
        self.days_left = (self.end - datetime.today()).days
        if self.days_left < 0:
            self.days_left = 0
        self.time_left = self.end - datetime.today()
        print(self.time_left.seconds)
        self.free_trial = self.type == "FREE" and self.active
        if not self.active:
            self.type = None

    def json(self):
        return dumps({
            "channel_id": self.channel_id,
            "active": self.active,
            "type": self.type,
            "in_db": self.in_db,
            "start": self.start.timestamp(),
            "end": self.end.timestamp(),
            "days_left": self.days_left,
            "free_trial": self.free_trial,
        })

    @staticmethod
    def get(conn: sqlite3.Connection, channel_id: str):
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM membership WHERE channel_id=?", (channel_id,))
        data = cursor.fetchone()
        if not data:
            return Membership()
        return Membership(data)
