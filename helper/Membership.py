import sqlite3
from datetime import datetime
class Membership:
    def __init__(self, data: list = None):
        # default values
        self.channel_id = ""
        self.till = 0
        self.active = False
        if not data:
            return
        self.channel_id = data[0]
        self.till = datetime.fromtimestamp(data[1])
        self.active = datetime.now() < self.till
        self.days_left = (self.till - datetime.now()).days
        if self.days_left < 0:
            self.days_left = 0
    def json(self):
        return {"channel_id": self.channel_id, "till": self.till, "active": self.active, "days_left": self.days_left}