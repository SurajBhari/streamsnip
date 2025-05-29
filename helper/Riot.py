import sqlite3
class Riot:
    def __init__(self, data=None):
        self.channel_id = None
        self.id = None
        self.tag = None
        self.region = None
        self.three_kills = False
        self.four_kills = False
        self.ace = False
        self.clutch = False
        self.enabled = False
        self.combined_username = None
        self.last_match_id  = None

        if data:
            self.channel_id = data[0]
            self.id = data[1]
            self.tag = data[2]
            self.region = data[3]
            self.three_kills = True if data[4] == "True" else False
            self.four_kills = True if data[5] == "True" else False
            self.ace = True if data[6] == "True" else False
            self.clutch = True if data[7] == "True" else False
            self.enabled = True if data[8] == "True" else False
            self.combined_username = f"{self.id}#{self.tag}"
            self.last_match_id = data[9] if len(data) > 4 else None

    def toJSON(self):
        return {
            "channel_id": self.channel_id,
            "id": self.id,
            "tag": self.tag,
            "region": self.region,
            "three_kills": self.three_kills,
            "four_kills": self.four_kills,
            "ace": self.ace,
            "clutch": self.clutch,
            "enabled": self.enabled
        }
    @staticmethod
    def get_by_channel_id(channel_id: str, conn: sqlite3.Connection):
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM RIOT WHERE channel_id=?", (channel_id,))
            data = cur.fetchone()
        if not data:
            return None
        return Riot(data)
    @staticmethod
    def get_all_enabled(conn:sqlite3.Connection):
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM RIOT WHERE enabled='True'")
            data = cur.fetchall()
        if not data:
            return []
        return [Riot(x) for x in data]
 