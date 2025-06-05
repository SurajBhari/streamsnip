import sqlite3
from datetime import datetime, timedelta
from json import load,loads,dump,dumps


class Membership:
    def __init__(self, data: list = None):
        # default values
        self.channel_id = ""
        self.active = False
        self.type = None
        self.active = False
        self.in_db = False
        self.start = datetime.fromtimestamp(943920000) # 1 jan 2000
        self.end = self.start
        self.days_left = 0
        self.free_trial = False
        self.time_left = timedelta(0)
        self.last_state = None
        if not data:
            return
        self.channel_id = data[0]
        self.type = data[1]
        self.last_state = data[1] # if its not active type gets changed to None
        try:
            self.start = datetime.fromtimestamp(data[2])
            self.end = datetime.fromtimestamp(data[3])
        except OSError:
            # make it infinite
            pass
        
        self.active = datetime.today() <= self.end
        self.in_db = True
        self.days_left = (self.end - datetime.today()).days
        if self.days_left < 0:
            self.days_left = 0
        self.time_left = self.end - datetime.today()
        self.free_trial = self.type == "FREE" and self.active
        if not self.active:
            self.type = None

    def json(self):
        return {
            "channel_id": self.channel_id,
            "active": self.active,
            "type": self.type,
            "in_db": self.in_db,
            "start": self.start.timestamp(),
            "end": self.end.timestamp(),
            "days_left": self.days_left,
            "free_trial": self.free_trial,
            "time_left": self.time_left.total_seconds()
        }

    @staticmethod
    def get(conn: sqlite3.Connection, channel_id: str):
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM membership WHERE channel_id=?", (channel_id,))
        data = cursor.fetchone()
        if not data:
            return Membership()
        return Membership(data)
