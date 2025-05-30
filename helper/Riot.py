import sqlite3
class Riot:
    def __init__(self, data=None):
        self.channel_id = ''
        self.id = ''
        self.tag = ''
        self.region = ''
        self.three_kills = False
        self.four_kills = False
        self.ace = False
        self.clutch = False
        self.enabled = False
        self.combined_username = None
        self.last_match_id  = ''
        self.in_db = False

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
            self.in_db = True

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
            rr = Riot()
            rr.channel_id = channel_id
            
            return rr # Return an empty Riot object if not found
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
    
    def write(self, conn: sqlite3.Connection):
        with conn:
            cur = conn.cursor()
            print(self.in_db)
            if self.in_db:
                # then get the last_match_id anre delete previous data
                cur.execute(
                    """
                    UPDATE RIOT SET
                    id = ?,
                    tag = ?,
                    region = ?,
                    three_kills = ?,
                    four_kills = ?,
                    ace = ?,
                    clutch = ?,
                    enabled = ?,
                    last_match_id = ?
                    WHERE channel_id = ?
                    """,
                    (
                        self.id,
                        self.tag,
                        self.region,
                        str(self.three_kills),
                        str(self.four_kills),
                        str(self.ace),
                        str(self.clutch),
                        str(self.enabled),
                        self.last_match_id,
                        self.channel_id
                    )
                )
            else:
                cur.execute(
                    """
                    INSERT INTO RIOT (
                        channel_id, id, tag, region,
                        three_kills, four_kills, ace, clutch,
                        enabled, last_match_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.channel_id,
                        self.id,
                        self.tag,
                        self.region,
                        str(self.three_kills),
                        str(self.four_kills),
                        str(self.ace),
                        str(self.clutch),
                        str(self.enabled),
                        self.last_match_id
                    )
                )
            self.in_db = True
            conn.commit()
        return True