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
        if not data:
            return
        self.channel_id = data[0]
        self.type = data[1]
        self.active = self.type != "paused"
        self.in_db = True

    def json(self):
        return {
            "channel_id": self.channel_id,
            "active": self.active,
            "type": self.type,
            "in_db": self.in_db,
        }

    @staticmethod
    def get(conn: sqlite3.Connection, channel_id: str):
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM membership WHERE channel_id=?", (channel_id,))
        data = cursor.fetchone()
        if not data:
            return Membership()
        return Membership(data)
