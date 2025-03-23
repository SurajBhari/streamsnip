import sqlite3
from datetime import datetime


class Membership:
    def __init__(self, data: list = None):
        # default values
        self.channel_id = ""
        self.active = False
        self.type = "basic"
        self.active = False
        self.in_db = False
        self.start = datetime.fromtimestamp(0)
        self.end = self.start
        self.days_left = 0
        if not data:
            return
        self.channel_id = data[0]
        self.type = data[1]
        self.start = data[2]
        self.end = data[3]
        self.active = datetime.today >= datetime.fromisoformat(data[2])
        self.in_db = True
        self.days_left = (self.end - datetime.today).days
        if self.days_left < 0:
            self.days_left = 0

    def json(self):
        return {
            "channel_id": self.channel_id,
            "active": self.active,
            "type": self.type,
            "in_db": self.in_db,
            "start": self.start,
            "end": self.end,
            "days_left": self.days_left,
        }

    @staticmethod
    def get(conn: sqlite3.Connection, channel_id: str):
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM membership WHERE channel_id=?", (channel_id,))
        data = cursor.fetchone()
        if not data:
            return Membership()
        return Membership(data)
