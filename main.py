# Standard library imports
from copy import deepcopy, copy
import os
import time
import random
import logging
import math
import subprocess
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import ascii_letters, digits
from typing import Optional, Tuple, List
from urllib import parse
from urllib.parse import parse_qs
from json import load, dump, loads, dumps
from http.cookiejar import MozillaCookieJar
from oauthlib.oauth2 import WebApplicationClient
from oauthlib.oauth2.rfc6749.errors import *
import secrets

# Third-party library imports
import yagmail
import cronitor
import yt_dlp
import dns.resolver
import dns.reversename
import scrapetube
from requests import get as GET
from requests import get
from requests import post as POST
from bs4 import BeautifulSoup
from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    send_file,
    session,
    jsonify,
    send_from_directory,
    flash,
)
from flask_cors import CORS
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    current_user,
    logout_user,
    AnonymousUserMixin,
)
from flask_sitemap import Sitemap
from discord_webhook import DiscordWebhook, DiscordEmbed
from chat_downloader.sites import YouTubeChatDownloader
from chat_downloader import ChatDownloader
from werkzeug.utils import secure_filename


# Local imports
from helper.util import *
from helper.Clip import Clip, time_since
from helper.UserSettings import UserSettings
from helper.Membership import Membership
from helper.Riot import Riot

# we are in /var/www/streamsnip
try:
    os.chdir("/var/www/streamsnip")
except FileNotFoundError:
    print("Running locally as we couldn't find the folder")
    local = True
    # we are working locally
    pass
else:
    local = False

if not local:
    logging.basicConfig(
        filename="./record.log",
        level=logging.ERROR,
        format=f"%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s",
    )

try:
    config = load(open("config.json", "r"))
    admin_password = config["password"]
except FileNotFoundError:
    print("Config file not found")
    admin_password = secrets.token_urlsafe(16)
    exit(1)

try:
    GOOGLE_CLIENT_ID = config["google"]["client_id"]
    GOOGLE_CLIENT_SECRET = config["google"]["client_secret"]
    GOOGLE_DISCOVERY_URL = config["google"]["discovery_url"]
except KeyError:
    GOOGLE_CLIENT_ID = GOOGLE_CLIENT_SECRET = GOOGLE_DISCOVERY_URL = (
        None  # we don't have google creds
    )

oauthclient = WebApplicationClient(GOOGLE_CLIENT_ID)
try:
    cronitor.api_key = config["cronitor_api_key"]
except FileNotFoundError:
    cronitor.api_key = None


if not local:
    monitor = cronitor.Monitor.put(key="Streamsnip-Clips-Performance", type="job")
else:
    monitor = None


app = Flask(__name__)
app.secret_key = os.environ.get(
    "WSGISecretKey", "supersecretkey"
)  # if we are running on apache we have a WSGISecretKey, its not really secret.
CORS(app)
ext = Sitemap(app=app)
app.jinja_options['extensions'] = ['jinja2_humanize_extension.HumanizeExtension']

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"
global download_lock
download_lock = True
global DEFAULT_SETTINGS
DEFAULT_SETTINGS = UserSettings()

global known_session_tokens
known_session_tokens = set()
conn = sqlite3.connect("queries.db", check_same_thread=False)
# cur = db.cursor() # this is not thread safe. we will create a new cursor for each thread
owner_icon = "👑"
mod_icon = "🔧"
regular_icon = "🧑‍🌾"
subscriber_icon = "⭐"
automated_icon = "🤖"
allowed_ip = [
    "127.0.0.1",
    "10.20.0.2",
    "::1"
]  # store the nightbot ips here. or your own ip for testing purpose
# add local ip just to make sure we go through if we are testing locally
allowed_ip.append(get("https://api.ipify.org/").text)
show_fake_error = False  # for blacklisted channel show fake error message or not
requested_myself = (
    False  # on startup we request ourself so that apache build the cache.
)
base_domain = (
    "https://streamsnip.com"  # just for the sake of it. store the base domain here
)
if local:
    base_domain = "http://localhost"

chat_id_video = {}  # store chat_id: vid. to optimize clip command
downloader_base_url = "https://azure-internal-verse.glitch.me"
project_name = "StreamSnip"
project_logo = base_domain + "/static/logo.png"
project_repo_link = "https://github.com/SurajBhari/streamsnip"
project_logo_discord = "https://raw.githubusercontent.com/SurajBhari/streamsnip/main/static/256_discord_ss.png"  # link to logo that is used in discord
sub_based_sort = True  # sort the channels on home page based on sub count
subscription_model = {
    "basic": {1: 99, 3: 249, 6: 499, 12: 999},
    "pro": {1: 199, 3: 498, 6: 998, 12: 1999},
    "premium": {1: 399, 3: 997, 6: 1998, 12: 3999},
}
discord_invite = "https://discord.gg/2XVBWK99Vy"

jar = None
if "cookies.txt" in os.listdir("./helper"):
    cookies = "./helper/cookies.txt"
    jar = MozillaCookieJar(Path(cookies))
else:
    cookies = None

if "youtubeemoji.json" in os.listdir("./helper"):
    with open("./helper/youtubeemoji.json", "r", encoding="utf-8") as f:
        emoji_lookup_table = load(f)
else:
    emoji_lookup_table = {}


def is_it_expired(
    t: int,
):  # we add some randomness so that not all of the cache get invalidated and added back at same time.
    if local:
        return False  # we don't need to expire the cache we have for testing purposes
    three_days_ago = int(time.time()) - 3 * 24 * 60 * 60
    last_time = three_days_ago + random.randint(0, 48) * 60 * 60
    if t < last_time:
        return True
    return False


if not project_logo_discord:
    project_logo_discord = project_logo

with conn:
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS QUERIES(channel_id VARCHAR(40), message_id VARCHAR(40), clip_desc VARCHAR(40), time int, time_in_seconds int, user_id VARCHAR(40), user_name VARCHAR(40), stream_link VARCHAR(40), webhook VARCHAR(40), delay int, userlevel VARCHAR(40), ss_id VARCHAR(40), ss_link VARCHAR(40), private VARCHAR(40), message_level int)"
    )
    conn.commit()
    cur.execute("PRAGMA table_info(QUERIES)")
    data = cur.fetchall()
    colums = [xp[1] for xp in data]
    if "webhook" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN webhook VARCHAR(40)")
        conn.commit()
        print("Added webhook column to QUERIES table")

    if "delay" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN delay INT")
        conn.commit()
        print("Added delay column to QUERIES table")

    if "userlevel" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN userlevel VARCHAR(40)")
        conn.commit()
        print("Added userlevel column to QUERIES table")

    if "ss_id" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN ss_id VARCHAR(40)")
        conn.commit()
        print("Added ss_id column to QUERIES table")

    if "ss_link" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN ss_link VARCHAR(40)")
        conn.commit()
        print("Added ss_link column to QUERIES table")

    if "private" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN private VARCHAR(40)")
        conn.commit()
        print("Added private column to QUERIES table")

    if "message_level" not in colums:
        cur.execute(
            "ALTER TABLE QUERIES ADD COLUMN message_level INT"
        )  # we store this for the sole purpose of rebuilding the message on !edit
        conn.commit()
        print("Added message_level column to QUERIES table")

with conn:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS SETTINGS (
        channel_id VARCHAR(40) UNIQUE,
        showlink VARCHAR(40) DEFAULT 'True',
        screenshot VARCHAR(40) DEFAULT 'False',
        delay INT DEFAULT 0,
        forcedesc VARCHAR(40) DEFAULT 'False',
        silent INT DEFAULT 2,
        private VARCHAR(40) DEFAULT 'False',
        webhook VARCHAR(128) DEFAULT 'None',
        messagelevel INT DEFAULT 0,
        takedelays INT DEFAULT 'False'
        )"""
    )
    conn.commit()
    cur.execute("PRAGMA table_info(SETTINGS)")
    data = cur.fetchall()
    colums = [xp[1] for xp in data]
    if "comments" not in colums:
        cur.execute(
            "ALTER TABLE SETTINGS ADD COLUMN comments VARCHAR(40) DEFAULT 'True'"
        )
        conn.commit()
        print("Added comments column to SETTINGS table")
    else:
        # comments already exists. we will change the default value to True
        try:
            cur.execute("DROP TABLE settings_old;")
        except sqlite3.OperationalError:
            pass
        cur.execute("ALTER TABLE settings RENAME TO settings_old;")
        conn.commit()
        cur.execute(
        """
        CREATE TABLE IF NOT EXISTS SETTINGS (
        channel_id VARCHAR(40) UNIQUE,
        showlink VARCHAR(40) DEFAULT 'True',
        screenshot VARCHAR(40) DEFAULT 'False',
        delay INT DEFAULT 0,
        forcedesc VARCHAR(40) DEFAULT 'False',
        silent INT DEFAULT 2,
        private VARCHAR(40) DEFAULT 'False',
        webhook VARCHAR(128) DEFAULT 'None',
        messagelevel INT DEFAULT 0,
        takedelays INT DEFAULT 'False',
        comments VARCHAR(40) DEFAULT 'True'
        )"""
        )
        cur.execute("""
            INSERT INTO settings (channel_id, showlink, screenshot, delay, forcedesc, silent, private, webhook, messagelevel, takedelays, comments)
            SELECT channel_id, showlink, screenshot, delay, forcedesc, silent, private, webhook, messagelevel, takedelays, 'True' FROM settings_old
                    
        """)
        cur.execute("DROP TABLE settings_old;")
        conn.commit()
        # give everyone the comments setting as True
        #cur.execute("UPDATE SETTINGS SET comments='True'") only 1 time had to be done. am dumb

    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS USERDATA(
            channel_id VARCHAR(40) UNIQUE, 
            email VARCHAR(40), 
            name VARCHAR(40), 
            image VARCHAR(40)
            )"""
    )

    conn.commit()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS LOGIN_RECORDS(
        channel_id VARCHAR(40),
        ip VARCHAR(40),
        session_token VARCHAR(40),
        user_agent VARCHAR(40),
        time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.commit()

    cur.execute(
        "CREATE TABLE IF NOT EXISTS MEMBERSHIP(channel_id VARCHAR(40),type VARCHAR(40), start DATETIME, end DATETIME)"
    )
    conn.commit()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS TRANSACTIONS(channel_id VARCHAR(40), amount INT, time INT, transaction_id VARCHAR(40), membership_type VARCHAR(40), description VARCHAR(40))"
    )
    conn.commit()
    cur.execute("CREATE TABLE IF NOT EXISTS ACCESS(channel_id VARCHAR(40), email VARCHAR(40), access_type VARCHAR(40), time INT, description VARCHAR(40))")
    conn.commit()
    # table riot having channel_id, id, tag, region, 3k, 4k, ace, clutch
    cur.execute(
        "CREATE TABLE IF NOT EXISTS RIOT(channel_id VARCHAR(40), id VARCHAR(40), tag VARCHAR(40), region VARCHAR(40), three_kills VARCHAR(40) DEFAULT 'False', four_kills VARCHAR(40) DEFAULT 'False', ace VARCHAR(40) DEFAULT 'False', clutch VARCHAR(40) DEFAULT 'False', enabled VARCHAR(40) DEFAULT 'False', last_match_id VARCHAR(40) DEFAULT '')"
    )
    conn.commit()
   
with conn:
    cur = conn.cursor()
    cur.execute("SELECT session_token FROM LOGIN_RECORDS")
    data = cur.fetchall()
    known_session_tokens = {x[0] for x in data}
    # this is a set of all the session tokens that are already in the database. we will use this to check if the session token is already used or not


class Transactions:
    def __init__(self, trans:List[str]):
        self.channel_id = None
        self.amount = 0
        self.time = datetime.fromtimestamp(10000)
        self.transaction_id = ""
        self.membership_type = ""
        self.description = ""
        self.in_db = False
        self.channel_name = ""
        self.channel_image = "https://yt3.googleusercontent.com/a/default-user=s100-c-k-c0x00ffffff-no-rj"
        if trans:
            self.in_db = True
            self.channel_id = trans[0]
            self.amount = float(trans[1])
            self.time = datetime.fromtimestamp(trans[2])
            self.transaction_id = trans[3]
            self.membership_type = trans[4]
            self.description = trans[5]
            self.channel_name, self.channel_image = get_channel_name_image(self.channel_id)





class AnonymousUser(AnonymousUserMixin):
    def __init__(self):
        super().__init__()
        self.admin = False
        self.logged_in = False
        self.id = "anonymous"


class User(UserMixin):
    def __init__(
        self,
        user_id,
        username,
        password,
        image=None,
        sub_count=0,
        email=None,
        name=None,
        gimage=None,
        logins=[],
    ):
        self.id = user_id
        if self.id == "admin":
            username = "Admin"
            image = "https://images.freeimages.com/fic/images/icons/2526/bloggers/256/admin.png?fmt=webp&h=350"
        self.username = username
        self.name = username
        self.password = password
        self.image = image
        self.admin = True if self.id.lower() == "admin" else False
        self.sub_count = sub_count
        self.logged_in = True
        self.email = email
        self.gname = name
        self.gimage = gimage

    @property
    def logins(self):
        with conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM LOGIN_RECORDS WHERE channel_id=? ORDER BY time DESC",
                (self.id,),
            )
            data = cur.fetchall()
        if not data:
            return []
        return data

    @property
    def membership(self):
        return Membership.get(conn, self.id)

    @property
    def transactions(self):
        return get_transactions(self.id)

    @property
    def can_avail_trial(self):
        return can_avail_free_trial(self.id)

    def get_id(self):
        return self.id

    @staticmethod
    def get(user_id):
        # load the config file
        creds = get_creds()
        password = creds.get(user_id, None)
        username, image = get_channel_name_image(user_id)
        try:
            sub_count = channel_info[user_id]["sub_count"]
        except KeyError:
            sub_count = 0
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM USERDATA WHERE channel_id=?", (user_id,))
            data = cur.fetchone()
            if data:
                email = data[1]
                name = data[2]
                gimage = data[3]
            else:
                email = None
                name = None
                gimage = None
        return User(
            user_id,
            username,
            password,
            image,
            sub_count=sub_count,
            email=email,
            name=name, 
            gimage=gimage,
        ) 

class Access:
    def __init__(self, data=None):
        self.channel_id = None
        self.email = None
        self.time = None
        self.access_type = None
        self.description = None
        self.channel_id = data[0] if data else None
        self.email = data[1] if data else None
        self.access_type = data[2] if data else None
        self.time = datetime.fromtimestamp(int(float(data[3]))) if data else None
        self.description = data[4] if data else None
    def toJSON(self):
        return {
            "channel_id": self.channel_id,
            "email": self.email,
            "access_type": self.access_type,
            "time": self.time.isoformat() if self.time else None,
            "description": self.description
        }


def get_channel_settings(user_id) -> UserSettings:
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM SETTINGS WHERE channel_id=?", (user_id,))
        data = cur.fetchone()
        if not data:
            x = UserSettings()
            x.channel_id = user_id
            add_default_settings(x.channel_id)
            return x
    riot = Riot.get_by_channel_id(user_id, conn)
    return UserSettings(list(data), riot=riot)


# if there is no folder named clips then make one
if not os.path.exists("clips"):
    os.makedirs("clips")
    print("Created clips folder")

try:
    creds = config["creds"]
except KeyError:
    creds = {}
    config["creds"] = creds


def is_blacklisted(channel_id):
    try:
        with open("blacklisted.json", "r", encoding="utf-8") as f:
            data = load(f)
    except FileNotFoundError:
        data = []
    return channel_id in data


def get_clip(clip_id, channel=None) -> Optional[Clip]:
    try:
        with conn:
            cur = conn.cursor()
            if channel:
                cur.execute(
                    "SELECT * FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
                    (
                        channel,
                        f"%{clip_id[:3]}",
                        int(clip_id[3:]) - 1,
                        int(clip_id[3:]) + 1,
                    ),
                )
            else:
                cur.execute(
                    "SELECT * FROM QUERIES WHERE message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
                    (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
                )
            data = cur.fetchall()
    except Exception as e:
        data = None
    if not data:
        return None
    x = Clip(data[0])
    return x


def get_video_clips(video_id, private=False) -> List[Optional[Clip]]:
    with conn:
        cur = conn.cursor()
        if private:
            cur.execute(
                "SELECT * FROM QUERIES WHERE stream_link like ?", (f"%{video_id}%",)
            )
        else:
            cur.execute(
                "SELECT * FROM QUERIES WHERE stream_link like ? AND private is not '1'",
                (f"%{video_id}%",),
            )
        data = cur.fetchall()
    if not data:
        return []
    l = []
    for y in data:
        x = Clip(y)
        l.append(x)
    return l


def get_channel_clips(channel_id=None) -> List[Clip]:
    with conn:
        cur = conn.cursor()
        if channel_id:
            cur.execute(f"select * from QUERIES where channel_id=? ORDER BY time ASC", (channel_id,))
        else:
            cur.execute(f"select * from QUERIES ORDER BY time ASC")
        data = cur.fetchall()
    l = []
    for y in data:
        x = Clip(y)
        l.append(x)
    l.reverse()
    return l


def create_simplified(clips: list) -> str:
    known_vid_id = []
    string = ""
    for clip in clips:
        if clip["stream_id"] not in known_vid_id:
            string += f"https://youtu.be/{clip['stream_id']}\n"
        string += f"{clip['author']['name']} -> {clip['message']} -> {clip['hms']}\n"
        string += f"Link: {clip['link']}\n\n\n"
        known_vid_id.append(clip["stream_id"])
    return string


def get_channel_name_image(channel_id: str, force_refresh=False) -> Tuple[str, str]:
    if (
        channel_id in channel_info and not force_refresh
    ):  # if its a force refresh we don't want to use the cache
        if "last_updated" not in channel_info[channel_id]:
            channel_info[channel_id][
                "last_updated"
            ] = 0  # forcing to outdate the value so that it gets updated
        if "sub_count" not in channel_info[channel_id]:
            channel_info[channel_id][
                "last_updated"
            ] = 0  # forcing to outdate the value so that it gets updated
        if is_it_expired(channel_info[channel_id]["last_updated"]):
            return get_channel_name_image(channel_id, force_refresh=True)
        try:
            return channel_info[channel_id]["name"], channel_info[channel_id]["image"]
        except Exception as e:
            logging.log(logging.ERROR, e)

    channel_link = f"https://youtube.com/channel/{channel_id}"
    response = get(channel_link)
    if response.status_code != 200:
        # don't store anything. just for this instance return the default values. can be youtube side issue too
        return (
            "<deleted channel>",
            "https://yt3.googleusercontent.com/a/default-user=s100-c-k-c0x00ffffff-no-rj",
        )

    html_data = response.text
    # with open("youtube.html", "w", encoding="utf-8") as f:
    #     f.write(html_data)
    yt_initial_data = loads(
        get_json_from_html(html_data, "var ytInitialData = ", 0, "};") + "}"
    )
    # put this in a local file for test purposes
    # with open("yt_initial_data.json", "w", encoding="utf-8") as f:
    #     dump(yt_initial_data, f, indent=4)
    soup = BeautifulSoup(html_data, "html.parser")
    try:
        channel_image = soup.find("meta", property="og:image")["content"]
        channel_name = soup.find("meta", property="og:title")["content"]
        try:
            sub_count = yt_initial_data["header"]["pageHeaderRenderer"]["content"][
                "pageHeaderViewModel"
            ]["metadata"]["contentMetadataViewModel"]["metadataRows"][1][
                "metadataParts"
            ][
                0
            ][
                "text"
            ][
                "content"
            ]
            sub_count = convert_sub_count(sub_count)
        except:
            sub_count = 0
        try:
            channel_username = yt_initial_data["metadata"]["channelMetadataRenderer"][
                "vanityChannelUrl"
            ].split("/")[-1]
        except KeyError:
            return (
                channel_name,
                channel_image,
            )  # stop caring abot channel username and putting it to cache
    except TypeError:  # in case the channel is deleted or not found
        channel_image = "https://yt3.googleusercontent.com/a/default-user=s100-c-k-c0x00ffffff-no-rj"
        channel_name = "<deleted channel>"
        channel_username = "@deleted"
        sub_count = 0
    last_updated = int(time.time())
    channel_info[channel_id] = {
        "name": channel_name,
        "image": channel_image,
        "username": channel_username,
        "last_updated": last_updated,
        "sub_count": sub_count,
    }
    # write channel_info to channel_cache.json
    write_channel_cache(channel_info)

    return channel_name, channel_image


def convert_sub_count(sub_count: str) -> int:
    sub_count = sub_count.split(" ")[0]
    sub_count = sub_count.upper()
    if "K" in sub_count:
        sub_count = sub_count.replace("K", "")
        sub_count = float(sub_count) * 1000
    elif "M" in sub_count:
        sub_count = sub_count.replace("M", "")
        sub_count = float(sub_count) * 1000000
    elif "B" in sub_count:  # lmao like this is ever gonna happen xd
        sub_count = sub_count.replace("B", "")
        sub_count = float(sub_count) * 1000000000
    else:
        sub_count = int(sub_count)
    return int(sub_count)



def take_screenshot(video_url: str, seconds: int) -> str:
    # Define yt-dlp options to get the best video-only stream URL
    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "skip_download": True,
    }

    if cookies:
        ydl_opts["cookiefile"] = cookies

    # Extract the video stream URL
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        video_info = ydl.extract_info(video_url, download=False)
        video_stream_url = video_info["url"].strip()

    # Download the HLS index file (M3U8 playlist)
    response = GET(video_stream_url, cookies=jar)
    if response.status_code != 200:
        return None

    index_file = "index.m3u8"
    with open(index_file, "wb") as f:
        f.write(response.content)

    # Build FFmpeg command to extract the screenshot
    output_file = "ss.jpg"
    ffmpeg_command = [
        "ffmpeg",
        "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
        "-y",
        "-ss", str(seconds),
        "-i", index_file,
        "-vframes", "1",
        "-q:v", "2",
        "-hide_banner",
        "-loglevel", "error",
        output_file,
    ]

    try:
        subprocess.run(ffmpeg_command, check=True)
    except subprocess.CalledProcessError as e:
        print("FFmpeg failed:", e)
        return None

    return output_file


def get_clip_with_desc(clip_desc: str, channel_id: str) -> Optional[Clip]:
    clips = get_channel_clips(channel_id)
    for clip in clips:
        if clip_desc.lower() in clip.desc.lower():
            return clip
    return None

def download_and_store(clip_id, format: str = None) -> str:
    with conn:
        cur = conn.cursor()
        data = cur.execute(
            "SELECT * FROM QUERIES WHERE message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
            (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
        )
        data = cur.fetchall()

    if not data:
        return None

    clip = Clip(data[0])
    video_url = clip.stream_link
    timestamp = clip.time_in_seconds
    output_filename = f"./clips/{clip_id}"
    
    # Check if file already exists
    for file in os.listdir("./clips"):
        if format:
            if file.startswith(clip_id) and file.endswith(format):
                return os.path.join("clips", file)
        else:
            if file.startswith(clip_id):
                return os.path.join("clips", file)

    # Adjust for delay
    delay = clip.delay or -60
    timestamp += -1 * delay
    start_time = min(timestamp, timestamp + delay)
    end_time = max(timestamp, timestamp + delay)

    params = {
        "cookiefile": cookies,
        "download_ranges": yt_dlp.utils.download_range_func([], [[start_time, end_time]]),
        "match_filter": yt_dlp.utils.match_filter_func("!is_live & live_status!=is_upcoming & availability=public"),
        "no_warnings": True,
        "noprogress": True,
        "outtmpl": {"default": output_filename},
        "overwrites": True,
        "quiet": True,
    }

    if format:
        params["postprocessors"] = [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": format
        }]
        params["final_ext"] = format

    with yt_dlp.YoutubeDL(params) as ydl:
        try:
            ydl.download([video_url])
        except yt_dlp.utils.DownloadError as e:
            print(f"Download error: {e}")
            return None  # Possibly still live or region restricted

    files = [
        os.path.join("clips", x) for x in os.listdir("./clips") if x.startswith(clip_id)
    ]
    if files:
        return files[0]


def mini_stats():
    today = datetime.strptime(
        datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d"
    ).timestamp()
    with conn:
        cur = conn.cursor()
        todays_clips = cur.execute(
            "SELECT * FROM QUERIES WHERE time >= ? AND private is not '1'", (today,)
        )
        todays_clips = todays_clips.fetchall()
        today_count = len(todays_clips)
        last_clip = None
        if today_count:
            last_clip = Clip(todays_clips[-1]).json()
    return dict(today_count=today_count, last_clip=last_clip)


@app.before_request
def before_request():
    """
    # if its a http request. redirect the same to https
    if not local:
        if not request.is_secure:
            return redirect(".", code=302)
    """
    # if request is for /clip or /delete or /edit then check if its from real
    if "/clip" in request.path or "/delete" in request.path or "/edit" in request.path:
        if (
            "/extension/" in request.path or "/clips" in request.path
        ):  # make an exception for all the /extension routes
            return
        ip = request.remote_addr
        if ip in allowed_ip:
            # print(f"Request from {ip} is allowed, known ip")
            return
        addrs = dns.reversename.from_address(ip)
        try:
            if not str(dns.resolver.resolve(addrs, "PTR")[0]).endswith(
                ".nightbot.net."
            ):
                raise ValueError("Not a nightbot request")
        except (
            dns.resolver.NoAnswer,
            dns.resolver.NXDOMAIN,
            ValueError,
            dns.resolver.LifetimeTimeout,
            dns.resolver.NoNameservers,
        ):
            return f"You are not Nightbot. are you ?, your ip {ip}"
        else:
            # print(f"Request from {ip} is allowed")
            allowed_ip.append(ip)
    else:
        if current_user.logged_in:
            token = session.get("session_token")
            if not token:
                # Create and register session token
                token = create_token()
                session["session_token"] = token
                add_login_record(
                    channel_id=current_user.id,
                    ip=request.remote_addr,
                    session_token=token,
                    user_agent=request.user_agent.string,
                )
                known_session_tokens.add(token)

            # Now validate
            if token not in known_session_tokens:
                #logout_user() 
                #return redirect(url_for("login"))
                ...



@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


login_manager.anonymous_user = AnonymousUser


@app.route("/start_free_trial")
def _start_free_trial():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if not current_user.can_avail_trial:
        return "You have already availed the free trial"
    start_free_trial(current_user.id)  # automatically starts the trial
    return redirect(url_for("slash"))


@app.route("/cache")
def cache():
    return dumps(channel_info, indent=4)


@app.route("/mini_stats")
def mini_stats_r():
    if request.args.get("home") == "true":
        ms = mini_stats()
        ms["data"] = generate_home_data()
        return dict(ms)

    return mini_stats()


# this function exists just because google chrome assumes that the favicon is at /favicon.ico
@app.route("/favicon.ico")
def favicon():
    return send_file("static/logo.svg")


@app.route("/robots.txt")
def robots():
    return send_file("static/robots.txt")


def generate_home_data():
    with conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT *, COUNT(*) AS channel_count, MIN(time) AS first_clip_time FROM QUERIES WHERE private is not '1' GROUP BY channel_id ORDER BY MAX(time) DESC;"
        )
        data = cur.fetchall()
    returning = []
    for clip in data:
        ch = {}
        channel_name, channel_image = get_channel_name_image(clip[0])
        ch["image"] = channel_image
        ch["name"] = channel_name
        try:
            ch["sub_count"] = channel_info[clip[0]]["sub_count"]
        except KeyError:
            ch["sub_count"] = 0
        ch["id"] = clip[0]
        ch["image"] = channel_image.replace(
            "s900-c-k-c0x00ffffff-no-rj", "s300-c-k-c0x00ffffff-no-rj"
        )
        ch["last_clip"] = Clip(clip).json()
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        ch["link"] = (
            f"{htt}{request.host}{url_for('exports', channel_id=get_channel_at(clip[0]))}"
        )
        ch["clip_count"] = clip[-2]
        ch["first_clip_time"] = clip[-1]
        ch["first_clip_timesince"] = time_since(
            datetime.fromtimestamp(clip[-1], tz=timezone.utc)
        )
        ch["deleted"] = True if "deleted channel" in channel_name else False
        if ch["deleted"]:
            ch["link"] = (
                f"{htt}{request.host}{url_for('exports', channel_id=get_channel_id_any(clip[0]))}"  # we can't get channel @ as its a deleted channel
            )
        # ch["last_clip"] = get_channel_clips(ch_id[0])[0].json()
        returning.append(ch)
    return returning


@app.route("/channels")
def channels():
    returning = generate_home_data()
    return render_template("channels.html", data=returning)


@app.route("/")
def slash():
    returning = generate_home_data()
    pinned = config.get("pinned_channels", [])
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT channel_id FROM MEMBERSHIP WHERE type='premium' AND end > ?",
            (int(time.time()),),
        )
        data = cur.fetchall()
    premium_members = [x[0] for x in data]
    #flash("hello world")
    return render_template(
        "home.html",
        data=returning,
        sub_based_sort=not current_user.is_authenticated,
        pinned=pinned,
        premium_members=premium_members,
    )

@app.route("/contactus")
def contactus():
    return render_template("contact.html", discord_invite=discord_invite)

@app.route("/tnc")
def tnc():
    return render_template("tnc.html")

@app.route("/privacy-policy")
def privacy():
    return render_template("privacy-policy.html")

@app.route("/aboutus")
def aboutus():
    return render_template("about.html")

@app.route("/")
@app.route("/data")
def data():
    if not current_user.admin:
        flash("Disabled", "info")
        return redirect(url_for("slash"))
    clips = get_channel_clips()
    clips = [x.json() for x in clips]
    return clips


@app.route("/session", methods=["GET"])
def session_data():
    if session:
        return dumps(session, indent=4)
    else:
        return "No session data"


@app.route("/user")
@login_required
def _user():
    return dumps(current_user.__dict__, indent=4)


def get_google_provider_cfg():
    return get(GOOGLE_DISCOVERY_URL).json()


@app.route("/login/google/callback")
def login_google_callback():
    code = request.args.get("code")
    google_provider_cfg = get_google_provider_cfg()

    # Step 1: Exchange Authorization Code for Token
    token_endpoint = google_provider_cfg["token_endpoint"]
    try:
        token_url, headers, body = oauthclient.prepare_token_request(
            token_endpoint,
            authorization_response=request.url,
            redirect_url=request.base_url,
            code=code,
        )
    except (AccessDeniedError, InvalidGrantError, MissingCodeError):
        return redirect(url_for("login_google"))
    token_response = POST(
        token_url,
        headers=headers,
        data=body,
        auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
    )

    # Parse and store access token
    oauthclient.parse_request_body_response(dumps(token_response.json()))
    access_token = token_response.json().get("access_token")

    # Step 2: Get User Info
    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = oauthclient.add_token(userinfo_endpoint)
    userinfo_response = get(uri, headers=headers, data=body)
    userinfo = userinfo_response.json()

    # Step 3: Fetch YouTube Data (Example)
    youtube_data = get_youtube_data(access_token)

    if youtube_data.get("error"):
        return redirect(
            url_for("login_google")
        )  # we do need to get the scope to validate the user

    try:
        youtube_id = youtube_data["items"][0]["id"]
    except KeyError:
        return redirect(
            url_for("login_google")
        )  # we do need to get the scope to validate the user
    if youtube_id in ["UCuhCyczWE_p06DjDRhKrJKg", "UCd__w3MzW2lVxdL7wA4nYYg"]:
        return {
            "youtube_data": youtube_data,
            "userinfo": userinfo,
        }  # return this for testing purpose
    
    email = userinfo.get("email", "")
    collect_user_data = {
        "email": userinfo.get("email", ""),
        "name": userinfo.get("name", ""),
        "image": userinfo.get("picture", ""),
    }
    add_user_data(youtube_id, collect_user_data)
    login_user(User.get(youtube_id), remember=True)
    token = create_token()
    session["session_token"] = token
    session["is_dummy"] = False  # litreally logged in with actual credentials
    session["master_channel_id"] = youtube_id
    add_login_record(
        channel_id=youtube_id,
        ip=request.remote_addr,
        session_token=session["session_token"],
        user_agent=request.user_agent.string,
    )
    session["logged_in"] = True
    next = session.pop("next_url", "/")
    if email:
        accessible_accounts = get_access_by_email(email)
        if accessible_accounts:
            # put next_url in session
            session["next_url"] = next
            return redirect("/change_account")
    return redirect(next or url_for("slash"))

@app.route("/change_account", methods=["GET"])
@login_required
def change_account():
    accessible_accounts = get_access_by_email(current_user.email)
    users = [User.get(x.channel_id) for x in accessible_accounts]
    if session.get("is_dummy", False):
        users = [User.get(session.get("master_channel_id", ""))] # only one way going up
    next = request.args.get("next", "")
    if not next:
        next = session.pop("next_url", "/")
    if not next.startswith("/"):
        next = "/"
    
    return render_template(
        "change_accounts.html",
        users=users,
        next=next
    )
    

@app.route("/change_account/<channel_id>", methods=["GET"])
@login_required
def change_account_to(channel_id):
    from_channel_id = current_user.id 
    from_master_channel_id = session.get("master_channel_id", "")
    email = current_user.email
    if not email:
        flash("You need to login with Google to change account", "warning")
        return redirect(url_for("login_google"))
    if channel_id not in [x.channel_id for x in get_access_by_email(email)] and channel_id != session.get("master_channel_id", ""): # we can go back to master id 
        flash("You don't have access to this account", "warning")
        return redirect(url_for("change_account"))
    session["id"] = channel_id
    session["logged_in"] = True
    session["session_token"] = create_token()
    add_login_record(
        channel_id=channel_id,
        ip=request.remote_addr,
        session_token=session["session_token"],
        user_agent=request.user_agent.string,
    )
    login_user(User.get(channel_id), remember=True)
    next = request.args.get("next", "/")
    if not next:
        next = session.pop("next_url", "/")
    if not next.startswith("/"):
        next = url_for("slash")
    print(f"Changing account from {from_channel_id} to {channel_id}")
    print(f"From master channel id: {from_master_channel_id} to {channel_id}")
    new_user = User.get(channel_id)

    if from_master_channel_id == channel_id:
        flash("You are now back to your master channel", "info")
        session["is_dummy"] = False
        session["master_channel_id"] = channel_id
    else:
        flash("You are now using a dummy account", "info")
        session["is_dummy"] = True
        session["master_channel_id"] = from_master_channel_id  # we can go back to master id
    login_user(new_user, remember=True)
    return redirect(next)



def create_token():
    return secrets.token_hex(16)


def add_login_record(channel_id, ip, session_token, user_agent):
    with conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO LOGIN_RECORDS (channel_id, ip, session_token, user_agent) VALUES (?, ?, ?, ?)",
            (channel_id, ip, session_token, user_agent),
        )
        conn.commit()
    known_session_tokens.add(session_token)  # add to the set of known session tokens
    return True


def add_user_data(channel_id, data):
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM USERDATA WHERE channel_id=?", (channel_id,))
        result = cur.fetchone()
        if not result:
            cur.execute(
                "INSERT INTO USERDATA (channel_id, email, name, image) VALUES (?, ?, ?, ?)",
                (channel_id, data["email"], data["name"], data["image"]),
            )
        else:
            if [data["email"], data["name"], data["image"]] == list(result[1:]):
                return  # no need to update
            # in this case we update the data   
            cur.execute(
                "UPDATE USERDATA SET email=?, name=?, image=? WHERE channel_id=?",
                (data["email"], data["name"], data["image"], channel_id),
            )
            
            # We insert so that we have old data too
        conn.commit()
    return True


def get_youtube_data(access_token):
    youtube_url = "https://www.googleapis.com/youtube/v3/channels"
    headers = {"Authorization": f"Bearer {access_token}"}

    params = {"part": "snippet,statistics", "mine": "true"}

    response = get(youtube_url, headers=headers, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        return {"error": "Failed to fetch YouTube data", "details": response.json()}


@app.route("/login/google")
def login_google():
    next = request.args.get("next")
    redirect_uri = request.base_url + "/callback"
    if next:
        session["next_url"] = next  # google doesn't allow query params in redirect_uri
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]
    request_uri = oauthclient.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=redirect_uri,
        scope=[
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/youtube.readonly"
        ],
    )
    return redirect(request_uri)


@app.route("/login", methods=["POST", "GET"])
def login():
    if request.method == "POST":
        remember = request.form.get("remember") == "remember"
        # set cookies to this password
        creds = get_creds()
        entered_password = request.form["password"]
        if entered_password.lower() in ["","none", "null"]:
            flash("You can't login with an empty password", "warning")
            return render_template("login.html")
        session_token = create_token()
        if entered_password == admin_password:
            session["id"] = "admin"
            session["logged_in"] = True
            session["session_token"] = session_token
            session["is_dummy"] = False  # admin is never a dummy account
            session["master_channel_id"] = "admin"
            add_login_record(
                channel_id="admin",
                ip=request.remote_addr,
                session_token=session["session_token"],
                user_agent=request.user_agent.string,
            )
            login_user(User.get(session["id"]), remember=remember)
            next = request.args.get("next")
            return redirect(next or url_for("slash"))

        for cred in creds:
            if creds[cred][-88:] == request.form["password"][-88:]:
                session["id"] = cred
                session["logged_in"] = True
                session["session_token"] = session_token
                session["is_dummy"] = False  # litreally logged in with actual credentials
                session["master_channel_id"] = cred
                add_login_record(
                    channel_id=cred,
                    ip=request.remote_addr,
                    session_token=session["session_token"],
                    user_agent=request.user_agent.string,
                )

                login_user(User.get(session["id"]), remember=remember)

                next = request.args.get("next")
                return redirect(next or url_for("slash"))
        flash("Invalid password", "warning")
        return render_template("login.html")
    next = request.args.get("next", "")
    if next:
        next = f"?next={next}"
    return render_template(
        "login.html",
        next=next,
    )


@app.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    # remove the token from database and also from known tokens
    with conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM LOGIN_RECORDS WHERE session_token=?",
            (session["session_token"],),
        )
        conn.commit()
    # remove the token from known session tokens
    if session["session_token"] in known_session_tokens:
        known_session_tokens.remove(session["session_token"])
    session.clear()
    logout_user()

    return redirect(url_for("slash"))


@app.route("/webhook")
def ___webhook():
    return redirect("/settings#webhook")

@app.route("/webedit", methods=["POST"])
@login_required
def webedit():
    try:
        new_message = request.json["message"]
        clip_id = request.json["clip_id"]
    except KeyError:
        return "Invalid request", 400
    if not current_user.admin:
        clip = get_clip(clip_id=clip_id, channel=current_user.id)
    else:
        clip = get_clip(clip_id=clip_id)

    if not clip:
        return "Clip not found", 404
    channel_id = clip.channel
    sub_detail = is_subscribed(channel_id)
    if not sub_detail:
        return f"You do not have any membership. Get the subscription at {base_domain}/membership"

    if not current_user.admin:
        if clip.channel != current_user.id:
            flash("You can't do this. You are not the owner of this channel", "danger")
            return redirect("/e/" + clip.channel)
    webhook_url = get_channel_settings(current_user.id).webhook
    clip.edit(new_message, conn, webhook_url=webhook_url)

    return clip.desc, 200


@app.route("/webdelete", methods=["POST"])
@login_required
def webdelete():
    try:
        clip_id = request.json["clip_id"]
    except KeyError:
        return "Invalid request", 400
    if not current_user.admin:
        clip = get_clip(clip_id=clip_id, channel=current_user.id)
    else:
        clip = get_clip(clip_id=clip_id)

    if not clip:
        return "Clip not found", 404
    channel_id = clip.channel
    # a person have rights to delete. even if he/she is not subscribed
    if not current_user.admin:
        if clip.channel != current_user.id:
            flash("You can't do this. You are not the owner of this channel", "danger")
            return redirect("/e/" + clip.channel)
    webhook_url = get_channel_settings(current_user.id).webhook
    clip.delete(conn, webhook_url=webhook_url)
    return "Deleted", 200


def get_video_id(video_link):
    x = parse.urlparse(video_link)
    to_return = ""
    if x.path == "/watch":
        to_return = x.query.replace("v=", "")
    if "/live/" in x.path:
        to_return = x.path.replace("/live/", "")
    if "youtu.be" in x.netloc:
        to_return = x.path.replace("/", "")
    return to_return.split("&")[0]


@app.route("/ip")
def get_ip():
    return request.remote_addr


@app.route("/settings/delete_login", methods=["POST"])
def delete_login():
    session_token = request.json.get("session_token")
    if session_token not in known_session_tokens:
        return "Invalid session token", 400
    with conn:
        # confirm that this channel_id is the same channel_id the session token is associated with it
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM LOGIN_RECORDS WHERE session_token=? AND channel_id=?",
            (
                session_token,
                current_user.id,
            ),
        )
        data = cur.fetchone()
        if not current_user.admin:
            if data[0] != current_user.id:
                flash("You can't do this. You are not the owner of this channel", "danger")
                return redirect("/settings")
        cur.execute("DELETE FROM LOGIN_RECORDS WHERE session_token=?", (session_token,))
        conn.commit()

    known_session_tokens.remove(session_token)
    return "OK", 200


@app.route("/settings/default", methods=["POST"])
@login_required
def default_settings():
    with conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM SETTINGS WHERE channel_id=?", (current_user.id,))
        conn.commit()
        cur.execute("DELETE FROM RIOT WHERE channel_id=?", (current_user.id,))
        conn.commit()
        
    add_default_settings(current_user.id)
    return "OK", 200

@app.route("/settings/add_access", methods=["POST"])
@login_required
def settings_add_access():
    try:
        if session["is_dummy"]:
            return "You are a moderator. you can't add another moderators. please ask the channel owner to do this operation.", 403
    except AttributeError:
        pass # this thing never existed before this so its ok 
    email = request.json.get("email")
    description = request.json.get("description")
    if not any([email, description]):
        return "Invalid data. missing description or email", 422
    
    with conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO ACCESS VALUES(?, ?, ?, ?, ?)", (current_user.id, email, 'all', datetime.now().timestamp(), description)) # we only have all for now. so give everyone all
        conn.commit()
    return "OK", 200

@app.route("/settings/revoke-access/<email_id>")
@login_required
def revoke_access(email_id=None):
    try:
        if session["is_dummy"]:
            return "You are a moderator. you can't add another moderators. please ask the channel owner to do this operation.", 403
    except AttributeError:
        pass # this thing never existed before this so its ok 
    if not email_id:
        return redirect("/settings")
    with conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM ACCESS WHERE channel_id = ? AND email = ?", (current_user.id, email_id))
    return redirect("/settings")


@app.route("/settings", methods=["POST", "GET"])
@login_required
def settings():
    settings = get_channel_settings(current_user.id)
    membership_details = Membership.get(conn, current_user.id)
    membership_details2 = is_subscribed(current_user.id, free_trial=False)
    can_edit = membership_details2 in ["pro", "premium", "FREE"]
    """
    if not can_edit:
        delay = settings.delay
        settings = DEFAULT_SETTINGS
        settings.delay = delay  # we don't want to change the delay""" # even if they can't edit the settings. get their settings.
    try:  # fuck around
        getattr(current_user, "sub_count")
    except AttributeError:  # find out
        current_user.sub_count = channel_info[current_user.id]["sub_count"]
    if request.method == "POST":
        if can_edit:
            settings.riot.enabled = request.json.get("val_clip_enabled") == "True"
            settings.riot.id = request.json.get('riot_id')
            settings.riot.tag = request.json.get("riot_tag")
            settings.riot.region = request.json.get("riot_region")
            settings.riot.three_kills = request.json.get("enable_3k") == "True"
            settings.riot.four_kills = request.json.get("enable_4k") == "True"
            settings.riot.clutch = request.json.get("enable_clutch") == "True"
            settings.riot.ace = request.json.get("enable_ace") == "True"
            settings.show_link = request.json.get("show_link")
            settings.screenshot = request.json.get("screenshot")
            settings.force_desc = request.json.get("force_desc")
            settings.silent = request.json.get("silent")
            settings.private = request.json.get("private")
            old_webhook = str(settings.webhook)
            settings.webhook = request.json.get("webhook").strip()
            if settings.webhook.lower() in ["none", 'null']:
                settings.webhook = ''
            settings.message_level = request.json.get("message_level")
            settings.take_delays = request.json.get("take_delays")
            settings.comments = request.json.get("comments")
            # test the settings.webhook if its valid then also send welcome to streamsnip thing
            if settings.webhook != old_webhook:
                webhook = DiscordWebhook(url=settings.webhook)
                embed = DiscordEmbed(
                    title=f"Welcome to {project_name}!",
                    description=f"I will send clips for {current_user.name} here",
                )
                embed.add_embed_field(
                    name="Add Nightbot command",
                    value=f"If you haven't already. add Nightbot commands from [github]({project_repo_link}) .",
                )
                embed.set_thumbnail(url=project_logo_discord)
                embed.set_color(0xEBF0F7)
                webhook.add_embed(embed)
                try:
                    response = webhook.execute()
                    if response.status_code != 200:
                        raise Exception(
                            f"Failed to send test webhook. Status code: {response.status_code}"
                        )
                    
                except Exception as e:
                    print(e)
                    return "Invalid webhook URL", 400
                
                # else welcome the channel
                if "update_webhook" in config:
                    webhook = DiscordWebhook(
                        url=config["update_webhook"],
                        username=project_name,
                        avatar_url=project_logo_discord,
                    )
                    embed = DiscordEmbed(
                        title=f"New webhook added",
                        description=f"New webhook added for {current_user.name}",
                    )
                    embed.set_thumbnail(url=current_user.image)
                    embed.set_color(0xEBF0F7)
                    webhook.add_embed(embed)
                    webhook.execute()
                

        settings.delay = request.json.get(
            "delay"
        )  # make an exception for delay as it can be still be edited
        settings.channel_id = current_user.id
        if not settings.write(conn):
            return "Failed to write settings", 500
        if not settings.riot.write(conn):
            return "Failed to write riot settings", 500
        return "OK", 200
    accesses = get_access(current_user.id)
    return render_template(
        "settings.html",
        session=session,
        settings=settings,
        membership_details=membership_details,
        can_edit=can_edit,
        can_turn_on_comments=membership_details.type == "premium",
        accesses=accesses,
    )
def get_access_by_email(email: str):
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM ACCESS WHERE email=?",
            (email,),
        )
        data = cur.fetchall()
    if not data:
        return []
    return [Access(d) for d in data]

def get_access(channel_id: str):
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM ACCESS WHERE channel_id=?",
            (channel_id,),
        )
        data = cur.fetchall()
    if not data:
        return []
    return [Access(d) for d in data]


@app.route("/pay/manual", methods=["GET", "POST"])
@login_required
def pay_manual():    
    amount = request.form.get("amount")
    if not amount:
        return "Invalid request: Amount missing.", 400
    amount = int(amount)
    mtype, month = get_membership_from_amount(amount)
    # Check if the requested membership matches the current membership
    
    transaction_note = f"{current_user.name} {mtype} for {str(month*28)} days"
    upi_link = f"upi://pay?pa=surajbhari@upi&pn={project_name}&cu=INR&tn={transaction_note}&am={amount}"
    upi_link_encoded = parse.quote(upi_link, safe="")

    return render_template(
        "intermediate.html", 
        upi_link=upi_link, 
        upi_link_encoded=upi_link_encoded,
        transaction_note=transaction_note,
        membership_type=mtype,
        membership_month=month,
        amount=amount,
        upgrade='',
        )


@app.route("/pay/manual/callback", methods=["GET", "POST"])
@login_required
def pay_manual_callback():
    if 'screenshot' not in request.files:
        return "Invalid request: Screenshot missing.", 400

    screenshot = request.files['screenshot']
    if screenshot.filename == '':
        return "No selected file.", 400

    # Save screenshot temporarily
    filename = f"{current_user.id}_{int(time.time())}_{secure_filename(screenshot.filename)}"
    filepath = os.path.join("static/", filename)
    screenshot.save(filepath)

    amount = request.form.get("amount")
    membership_type_from_request = request.form.get("membership")

    if not amount:
        return "Invalid request: Amount missing.", 400
    if not membership_type_from_request:
        return "Invalid request: Membership type missing.", 400

    amount = int(amount)
    mtype, months = get_membership_from_amount(amount)
    if mtype != membership_type_from_request:
        return "Invalid request: Membership type does not match the amount.", 400

    # Process membership update
    old_membership_details = Membership.get(conn, current_user.id)
    if old_membership_details.days_left:
        start_time = old_membership_details.start
        end_time = old_membership_details.end + timedelta(days=months * 28)
    else:
        start_time = datetime.now()
        end_time = datetime.now() + timedelta(days=months * 28)

    cur.execute("DELETE FROM MEMBERSHIP WHERE channel_id=?", (current_user.id,))
    cur.execute(
        "INSERT INTO MEMBERSHIP VALUES (?, ?, ?, ?)",
        (
            current_user.id,
            mtype,
            int(start_time.timestamp()),
            int(end_time.timestamp()),
        ),
    )

    reference_number = f"screenshot_{filename}"
    description = f"{current_user.name} {mtype} for {str(months*28)} days"
    cur.execute(
        "INSERT INTO TRANSACTIONS VALUES (?, ?, ?, ?, ?, ?)",
        (
            current_user.id,
            amount,
            int(time.time()),
            int(time.time()),
            mtype,
            description,
        ),
    )
    conn.commit()

    # Send webhook
    if "management_webhook" in config:
        webhook = DiscordWebhook(
            url=config["management_webhook"],
            username=project_name,
            avatar_url=project_logo_discord,
        )
        webhook.content = f"New payment screenshot uploaded by {current_user.name} <@408994955147870208>"
        embed = DiscordEmbed(
            title=f"Manual Payment for {membership_type_from_request} Membership",
            description=f"User: {current_user.name}\nAmount: {amount} INR\nMembership: {membership_type_from_request} ({months} month{'s' if months != 1 else ''})",
        )
        embed.set_thumbnail(url=current_user.image)
        embed.set_color(0xEBF0F7)
        with open(filepath, "rb") as f:
            file_data = f.read()

        webhook.add_file(file=file_data, filename=filename)

        webhook.add_embed(embed)
        webhook.execute()
        os.remove(filepath)
    else:
        print("management_webhook not set in config. Not sending webhook.")

    flash("Payment successful. Membership updated.", "success")
    return "ok", 200

@app.route("/upgrade/manual", methods=["POST"])
@login_required
def upgrade_manual():
    switch_to = request.form.get("type")
    if not switch_to:
        return "Invalid request", 400

    membership_details = Membership.get(conn, current_user.id)

    if membership_details.type.lower() == "free":
        return (
            "You are on free trial. No upgrade available. Only Subscribe is avaialable.",
            400,
        )

    if membership_details.type == switch_to:
        return "You are already on this membership.", 400

    if not membership_details.days_left:
        return "You can't upgrade from expired membership.", 400

    allowed_upgrades = {"basic": ["pro", "premium"], "pro": ["premium"], "premium": []}

    current_type = membership_details.type
    if switch_to not in allowed_upgrades.get(current_type, []):
        return "Upgrade not allowed from your current membership.", 400

    # Per day prices
    per_day_current = subscription_model[current_type][1] / 28
    per_day_new = subscription_model[switch_to][1] / 28

    # Calculate amount
    days_left = membership_details.days_left
    amount = (per_day_new - per_day_current) * days_left
    if amount <= 0:
        return "Invalid upgrade request.", 400
    # round off ammount to second decimal place
    amount = round(amount, 2)
    transaction_note = f"{current_user.name} upgrade {membership_details.type} to {switch_to}"

    upi_link = f"upi://pay?pa=surajbhari@upi&pn={project_name}&cu=INR&tn={transaction_note}&am={amount}"
    upi_link_encoded = parse.quote(upi_link, safe="")
    return render_template(
        "intermediate.html", 
        upi_link=upi_link, 
        upi_link_encoded=upi_link_encoded,
        transaction_note=transaction_note,
        amount=amount,
        upgrade=True,
        membership_type=switch_to,
        )


@app.route("/upgrade/callback/manual", methods=["POST"])
def callback_upgrade_manual():
    if 'screenshot' not in request.files:
        return "Invalid request: Screenshot missing.", 400

    screenshot = request.files['screenshot']
    if screenshot.filename == '':
        return "No selected file.", 400

    # Save screenshot temporarily
    filename = f"{current_user.id}_{int(time.time())}_{secure_filename(screenshot.filename)}"
    filepath = os.path.join("static/", filename)
    screenshot.save(filepath)
    new_type = request.form.get("membership")
    amount_paid = request.form.get("amount")
    if not new_type:
        return "Invalid request: Membership type missing.", 400
    if not amount_paid:
        return "Invalid request: Amount missing.", 400

    amount_paid = float(amount_paid)
    order_id = f"screenshot_{filename}"

    allowed_upgrades = {"basic": ["pro", "premium"], "pro": ["premium"], "premium": []}

    membership_details = Membership.get(conn, current_user.id)
    current_type = membership_details.type
    if new_type not in allowed_upgrades.get(current_type, []):
        return "Upgrade not allowed from your current membership.", 400

    # Per day prices
    per_day_current = subscription_model[current_type][1] / 28
    per_day_new = subscription_model[new_type][1] / 28

    days_left = membership_details.days_left
    should_be_paid_amount = (per_day_new - per_day_current) * days_left
    should_be_paid_amount = int(round(should_be_paid_amount))

    old_ids = get_transactions_all()
    old_ids = [x[3] for x in old_ids]
    if order_id in old_ids:
        return "Transaction already exists Please go to membership page. if you still think its an issue. please contact us from contact us page.", 400

    if should_be_paid_amount <= 0:
        return "Invalid upgrade request.", 400

    # if the difference is not more than 2 rs then its ok 
    if abs(should_be_paid_amount - amount_paid) > 2:
        return "Invalid amount paid. Please check the amount.", 400

    cur.execute(
        "UPDATE membership SET type = ? WHERE channel_id = ?",
        (
            new_type,
            current_user.id,
        ),
    )
    description = f"{current_user.name} upgrade {current_type} to {new_type}"
    cur.execute(
        "INSERT INTO TRANSACTIONS VALUES (?, ?, ?, ?, ?, ?)",
        (
            current_user.id,
            amount_paid,
            int(time.time()),
            int(time.time()),
            new_type,
            description,
        ),
    )
    conn.commit()

    if "management_webhook" in config:
        webhook = DiscordWebhook(
            url=config["management_webhook"],
            username=project_name,
            avatar_url=project_logo_discord,
        )
        webhook.content = f"New upgrade screenshot uploaded by {current_user.name} <@408994955147870208>"
        embed = DiscordEmbed(
            title=f"Manual Upgrade to {new_type} Membership",
            description=f"User: {current_user.name}\nAmount: {amount_paid} INR\nMembership upgraded from {current_type} to {new_type}"
        )
        embed.set_thumbnail(url=current_user.image)
        embed.set_color(0xEBF0F7)
        with open(filepath, "rb") as f:
            file_data = f.read()
        webhook.add_file(file=file_data, filename=filename)
        webhook.add_embed(embed)
        webhook.execute()
        # delete the file 
        os.remove(filepath)
    else:
        print("management_webhook not set in config. Not sending webhook.")

    flash("Payment successful. Membership updated.", "success")
    return "ok", 200
    
def get_membership_from_amount(amount:int):
    for mtype in subscription_model:
        for month in subscription_model[mtype]:
            am = subscription_model[mtype][month]
            if am == amount:
                return mtype, month
    return None, None


def terminate_current_membership(channel_id: str):
    with conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM MEMBERSHIP WHERE channel_id=?",
            (channel_id,),
        )
        conn.commit()
        
def get_transactions_all():
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM TRANSACTIONS")
        data = cur.fetchall()
    return data


def get_transactions(channel_id: str = None):
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM TRANSACTIONS WHERE channel_id=?", (channel_id,))
        data = cur.fetchall()
    return data


@app.route("/membership")
@login_required
def membership():
    transactions = get_transactions(current_user.id)
    balance = 0
    for i in range(len(transactions)):
        transactions[i] = list(transactions[i])
        balance += transactions[i][1]
        transactions[i][2] = datetime.fromtimestamp(
            transactions[i][2], tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")
        transactions[i][1] = f"{transactions[i][1]:.2f}"
    # estimate the membership end date
    # if the membership is basic then its 99 per 28 days if its pro then its 199 per 28 days if its love then its 299
    membership_details = Membership.get(conn, current_user.id)

    available = list(subscription_model.keys())
    available_upgrades = []
    available_subscribes = []
    if (not membership_details.type) or membership_details.type.lower() == "free":
        available_subscribes = ["basic", "pro", "premium"]
    else:
        available_subscribes = [membership_details.type]
    if membership_details.days_left:
        if membership_details.type.lower() == "free":
            available_upgrades = []
        if membership_details.type == "basic":
            available_upgrades = ["pro", "premium"]
        if membership_details.type == "pro":
            available_upgrades = ["premium"]
    return render_template(
        "membership.html",
        membership=membership_details,
        balance=f"{balance:.2f}",
        transactions=transactions[::-1],
        base_prices={"basic": 199, "pro": 299, "premium": 499},
        base_duration=28,
        subscription_model=subscription_model,
        available_upgrades=available_upgrades,
        available_subscribes=available_subscribes,
    )


# this is for nightbot to give back export link
@app.route("/export")
def export():
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    if request.is_secure:
        htt = "https://"
    else:
        htt = "http://"
    return f"You can see all the clips at {htt}{request.host}{url_for('exports', channel_id=get_channel_at(channel_id))}"


# this is for ALL CLIPS
@app.route("/e")
@app.route("/exports")
@app.route("/e/")
@app.route("/exports/")
def exports_all():
    data = get_channel_clips()
    if len(data) > 50000:
        if not current_user.admin:
            flash("DISABLED", "info")
            return redirect("/")
    data = [x.json() for x in data if not x.private]
    for clip in data:
        """
        if clip['discord']['webhook']:
            if clip['channel'] in prefix_webhook:
                clip['discord_url'] = f"{prefix_webhook[clip['channel']]}/{clip['discord']['webhook']}"
            else:
                webhook_url = creds.get(clip['channel'])
                if not webhook_url:
                    continue
                response = get(webhook_url)
                if response.status_code != 200:
                    prefix_webhook[clip['channel']] = None
                    continue
                j = response.json()
                prefix_webhook[clip['channel']] = f"https://discord.com/channels/{j['guild_id']}/{j['channel_id']}"
                clip['discord_url'] = f"{prefix_webhook[clip['channel']]}/{clip['discord']['webhook']}
        """
        clip["discord_url"] = (
            "#a"  # we don't want to do it for all clips. cuz its slowwwww
        )
    return render_template(
        "export.html",
        data=data,
        clips_string=create_simplified(data),
        channel_name="All channels",
        channel_image=f"{base_domain}/static/logo.png",
        owner_icon=owner_icon,
        mod_icon=mod_icon,
        regular_icon=regular_icon,
        subscriber_icon=subscriber_icon,
        automated_icon=automated_icon,
        channel_id="all",
        emoji_lookup_table=emoji_lookup_table,
    )


def get_channel_id_any(hint):  # returns the UC id of the channel
    if hint.lower().startswith("uc"):
        return hint  # already a channel id
    if hint.startswith("@"):
        available = [
            x
            for x in channel_info
            if hint.lower() in channel_info[x].get("username").lower()
        ]
        if available:
            return available[0]
    available = [
        x for x in channel_info if hint.lower() == channel_info[x].get("name").lower()
    ]  # we are first trying to find exact match.
    if available:
        return available[0]
    available = [
        x for x in channel_info if hint.lower() in channel_info[x].get("name").lower()
    ]
    if available:
        return available[0]
    return None


def get_channel_at(channel_id):  # returns the @username of the channel
    """
    channel_info = {
        "UCnSgtnvG74e9nxI9SibI-LA":{
            "name":"Pakshi",
            "image":"https://yt3.googleusercontent.com/Av-rtdhg7TzN6LWwhaMbilRgMz_cQmecp3NwgU9m_NtpzEt0VQ1KvJqYfMs-LSCeR9bIRkh9Pw=s900-c-k-c0x00ffffff-no-rj",
            "username":"@Pakshi_Udd",
            "last_updated":1731360906,
            "sub_count":836
        }
    }
    """
    if channel_id.startswith("@"):
        return channel_id
    get_channel_name_image(
        channel_id
    )  # this will just come back if there is already a channel_id.
    channel = channel_info.get(channel_id)
    if not channel:
        return channel_id
    return channel["username"]


def get_user_clips(user_id):
    with conn:
        cur = conn.cursor()
        if user_id:
            cur.execute(f"select * from QUERIES where user_id=?", (user_id,))
        else:
            cur.execute(f"select * from QUERIES ORDER BY time ASC")
        data = cur.fetchall()
    l = []
    for y in data:
        x = Clip(y)
        l.append(x)
    l.reverse()
    return l
# this is for specific channel
@app.route("/clips/<channel_id>")
@app.route("/clips/<channel_id>/")
@app.route("/c/<channel_id>/")
@app.route("/c/<channel_id>")
@app.route("/exports/<channel_id>")
@app.route("/e/<channel_id>")
def exports(channel_id=None):
    channel_id = get_channel_id_any(channel_id)
    
    if not channel_id:
        return redirect(url_for("slash"))  # not found
    
    try:
        channel_name, channel_image = get_channel_name_image(channel_id)
    except Exception as e:
        return redirect(url_for("slash"))
    
    data = get_channel_clips(channel_id)
    
    sub_detail = is_subscribed(channel_id, free_trial=False)
    
    can_edit = current_user.id == channel_id or current_user.admin
    
    if current_user.admin:  # no data should be hidden from admin
        data = [x.json() for x in data]
    else:
        data = [x.json() for x in data if not x.private]
    webhook_url = get_channel_settings(channel_id).webhook
    if not webhook_url:
        for clip in data:
            clip["discord_url"] = "#"
    else:
        for i, clip in enumerate(data):
            if clip["discord"]["webhook"]:
                if (
                    clip["channel"] in prefix_webhook
                ):
                    clip["discord_url"] = (
                        f"{prefix_webhook[clip['channel']]}/{clip['discord']['webhook']}"
                    )
                else:
                    response = get(webhook_url)
                    if response.status_code != 200: # its ok if the code is 200. we don't have history of all webhooks
                        prefix_webhook[clip["channel"]] = None
                    else:
                        j = response.json()
                        prefix_webhook[clip["channel"]] = (
                            f"https://discord.com/channels/{j['guild_id']}/{j['channel_id']}"
                        )
                        clip["discord_url"] = (
                            f"{prefix_webhook[clip['channel']]}/{clip['discord']['webhook']}"
                        )
            else:
                clip["discord_url"] = "#"


    return render_template(
        "export.html",
        data=data,
        clips_string=create_simplified(data),
        channel_name=channel_name,
        channel_image=channel_image,
        owner_icon=owner_icon,
        mod_icon=mod_icon,
        regular_icon=regular_icon,
        automated_icon=automated_icon,
        subscriber_icon=subscriber_icon,
        channel_id=get_channel_at(channel_id),
        emoji_lookup_table=emoji_lookup_table,
        can_edit=can_edit,
    )



@app.route("/channelstats")
@app.route("/channelstats/")
@app.route("/channelstats/<channel_id>")
@app.route("/channelstats/<channel_id>/")
@app.route("/cs")
@app.route("/cs/")
@app.route("/cs/<channel_id>")
@app.route("/cs/<channel_id>/")
def channel_stats(channel_id=None):
    if not channel_id:
        return redirect(url_for("slash"))
    if channel_id == "all":
        return redirect(url_for("stats"))
    channel_id = get_channel_id_any(channel_id)
    if not channel_id:
        return redirect(url_for("slash"))
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM QUERIES WHERE channel_id=? AND private is not '1'",
            (channel_id,),
        )
        data = cur.fetchall()
    if not data:
        return redirect(url_for("slash"))
    clips = []
    for x in data:
        clips.append(Clip(x))

    clip_count = len(clips)
    user_count = len(set([clip.user_id for clip in clips]))
    # "Name": no of clips
    user_clips = {}
    top_clippers = {}
    notes = {}
    for clip in clips:
        if clip.user_id not in user_clips:
            user_clips[clip.user_id] = 0
        user_clips[clip.user_id] += 1
        if clip.desc and clip.desc != "None":
            for word in clip.desc.lower().split():
                if word not in notes:
                    notes[word] = 0
                notes[word] += 1
        if clip.user_id not in top_clippers:
            top_clippers[clip.user_id] = 0
        top_clippers[clip.user_id] += 1
    # sort
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    notes = {
        k: 5 + 5 * v
        for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
    }
    notes = dict(list(notes.items())[:150])
    new_dict = {}
    # replace dict_keys with actual channel
    max_count = 0
    streamer_name, streamer_image = get_channel_name_image(channel_id)
    # sort and get k top clippers
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    for k, v in user_clips.items():
        max_count += 1
        if max_count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new_dict[channel_name] = v
    new_dict["Others"] = sum(list(user_clips.values())[max_count:])
    if new_dict["Others"] == 0:
        new_dict.pop("Others")
    user_clips = new_dict
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new.append(
            {
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k),
            }
        )
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    best_days = {}
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
        if day not in best_days:
            best_days[day] = 1
        else:
            best_days[day] += 1
    time_trend = new_dict
    day_counter = 0 
    clips_couter = 0
    average = {}
    for k, v in time_trend.items():
        day_counter += 1
        clips_couter += v
        average[k] = int(clips_couter/day_counter)
    best_days = {
        k: v
        for k, v in sorted(best_days.items(), key=lambda item: item[1], reverse=True)
    }
    best_days = dict(list(best_days.items())[:12])
    streamer_trend_data = {}
    # "clipper" : {day: no_of_clips}
    streamers_trend_days = []
    max_count = 0
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if clip.user_id not in streamer_trend_data:
            streamer_trend_data[clip.user_id] = {}
        if day not in streamer_trend_data[clip.user_id]:
            streamer_trend_data[clip.user_id][day] = 0
        streamer_trend_data[clip.user_id][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # replace channel id with channel name
    new_dict = {}
    known_k = []
    max_count = 0
    # sort
    streamer_trend_data = {
        k: v
        for k, v in sorted(
            streamer_trend_data.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )
    }
    for k, v in streamer_trend_data.items():
        max_count += 1
        if max_count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new_dict[channel_name] = v
        known_k.append(k)
    new_dict["Others"] = {}
    for k, v in streamer_trend_data.items():
        if k in known_k:
            continue
        for day, count in v.items():
            if day not in new_dict["Others"]:
                new_dict["Others"][day] = 0
            new_dict["Others"][day] += count
    if new_dict["Others"] == {}:
        new_dict.pop("Others")
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[x] = 0
    for clip in clips:
        hm = int((clip.time + timedelta(hours=5, minutes=30)).strftime("%H"))
        time_distribution[hm] += 1
    # get the top most clipped streams
    cur.execute(
        """
            SELECT stream_link, COUNT(message_id) AS occurrence_count
            FROM QUERIES
            WHERE channel_id=?
            GROUP BY message_id
            ORDER BY occurrence_count DESC
            LIMIT 12;
        """,
        (channel_id,),
    )
    mcs = cur.fetchall()
    most_clipped_streams = {}  # stream_link: count
    for x in mcs:
        most_clipped_streams[get_video_id(x[0])] = x[1]
    message = f"Channel Stats for {streamer_name}. {user_count} users clipped\n{clip_count} clips till now. \nand counting."
    return render_template(
        "stats.html",
        message=message,
        notes=notes,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count=len(user_clips),
        times=list(time_trend.keys()),
        counts=list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels=list(streamer_trend_data.keys()),
        time_distribution=time_distribution,
        channel_name=streamer_name,
        channel_image=streamer_image,
        most_clipped_streams=most_clipped_streams,
        best_days=best_days,
        first_clip_d={},
        search_route="/searchchannel",
        search_for="channel",
        average=average,
    )


@app.route("/ts")
@app.route("/ts/")
@app.route("/ts/<start>")
@app.route("/ts/<start>/")
@app.route("/ts/<start>/<end>")
@app.route("/ts/<start>/<end>/")
@app.route("/timestats")
@app.route("/timestats/")
@app.route("/timestats/<start>")
@app.route("/timestats/<start>/")
@app.route("/timestats/<start>/<end>")
@app.route("/timestats/<start>/<end>/")
def time_stats(start=None, end=None):
    if not start:
        # if there is no start then start is today. if there is no end then end is tomorrow
        start = datetime.strptime(str(datetime.now().date()), "%Y-%m-%d")
    else:
        start = datetime.strptime(start, "%Y-%m-%d")
    if not end:
        # if there is no end then choose one day after start
        end = start + timedelta(days=1)
    else:
        end = datetime.strptime(end, "%Y-%m-%d")
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM QUERIES WHERE private is not '1' AND time >= ? AND time < ?",
            (
                start.timestamp(),
                end.timestamp(),
            ),
        )
        data = cur.fetchall()
    clips = []
    for x in data:
        c = Clip(x)
        clips.append(c)
    clip_count = len(data)
    user_count = len(set([x[5] for x in data]))
    # "Name": no of clips
    user_clips = {}
    top_clippers = {}
    notes = {}
    for clip in clips:
        if clip.channel not in user_clips:
            user_clips[clip.channel] = 0
        user_clips[clip.channel] += 1
        if clip.desc and clip.desc != "None":
            for word in clip.desc.lower().split():
                if word not in notes:
                    notes[word] = 0
                notes[word] += 1
        if clip.user_id not in top_clippers:
            top_clippers[clip.user_id] = 0
        top_clippers[clip.user_id] += 1

    # sort
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    # get only top 25 and other as sum of rest
    _user_clips = user_clips
    channel_count = len(_user_clips)
    user_clips = {}
    max_count = 0
    top_25_ids = []

    for k, v in _user_clips.items():
        max_count += 1
        if max_count > 25:
            break
        top_25_ids.append(k)
        user_clips[k] = v
    user_clips["Others"] = sum(list(_user_clips.values())[max_count - 1 :])
    if user_clips["Others"] == 0:
        user_clips.pop("Others")
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    notes = {
        k: v for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
    }
    notes = dict(list(notes.items())[:150])
    # replace dict_keys with actual channel
    new_dict = {}
    for k, v in user_clips.items():
        if k != "Others":
            channel_name, image = get_channel_name_image(k)
        else:
            channel_name = "Others"
        new_dict[channel_name] = v
    user_clips = new_dict
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new.append(
            {
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k),
            }
        )
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    # for that hour that have no clips, add 0
    # get all hours from start date to end date
    temp_start = start
    while temp_start < end:
        new_dict[temp_start.strftime("%Y-%m-%d %H")] = 0
        temp_start += timedelta(hours=1)

    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H")
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1

    # sort the new_dict
    time_trend = new_dict
    day_counter = 0 
    clips_couter = 0
    average = {}
    for k, v in time_trend.items():
        day_counter += 1
        clips_couter += v
        average[k] = int(clips_couter/day_counter)

    streamer_trend_data = {}
    # streamer: {day: no_of_clips}
    streamers_trend_days = []

    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H")
        channel_id = clip.channel
        if channel_id not in top_25_ids:
            channel_id = "Others"

        if channel_id not in streamer_trend_data:
            streamer_trend_data[channel_id] = {}

        temp_start = start
        while temp_start < end:
            if (
                temp_start.strftime("%Y-%m-%d %H")
                not in streamer_trend_data[channel_id]
            ):
                streamer_trend_data[channel_id][temp_start.strftime("%Y-%m-%d %H")] = 0
                if temp_start.strftime("%Y-%m-%d %H") not in streamers_trend_days:
                    streamers_trend_days.append(temp_start.strftime("%Y-%m-%d %H"))
            temp_start += timedelta(hours=1)

        if day not in streamer_trend_data[channel_id]:
            streamer_trend_data[channel_id][day] = 0
        streamer_trend_data[channel_id][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    # for that hour that have no clips, add 0
    # get all hours from start date to end date

    # streamers_trend_days.sort()
    # only top 25 and others
    streamer_trend_data = {
        k: v
        for k, v in sorted(
            streamer_trend_data.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )
    }
    new_dict = {}
    known_k = []
    max_count = 0
    new_dict["Others"] = {}
    for k, v in streamer_trend_data.items():
        max_count += 1
        if k != "Others":
            channel_name, image = get_channel_name_image(k)
        else:
            channel_name = k
        new_dict[channel_name] = v
        known_k.append(k)
    if new_dict["Others"] == {}:
        new_dict.pop("Others")
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[x] = 0
    for clip in clips:
        hm = int((clip.time + timedelta(hours=5, minutes=30)).strftime("%H"))
        time_distribution[hm] += 1

    # get the top most clipped streams
    cur.execute(
        """
            SELECT stream_link, COUNT(message_id) AS occurrence_count
            FROM QUERIES WHERE time >= ? AND time < ?
            GROUP BY message_id
            ORDER BY occurrence_count DESC
            LIMIT 12;
        """,
        (
            start.timestamp(),
            end.timestamp(),
        ),
    )
    mcs = cur.fetchall()
    most_clipped_streams = {}  # stream_link: count
    for x in mcs:
        most_clipped_streams[get_video_id(x[0])] = x[1]
    message = f"{user_count} users clipped\n{clip_count} clips on \n{channel_count} channels on {start.strftime('%Y-%m-%d')} till {end.strftime('%Y-%m-%d')}."
    return render_template(
        "stats.html",
        message=message,
        notes=notes,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count=channel_count,
        times=list(time_trend.keys()),
        counts=list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels=list(streamer_trend_data.keys()),
        time_distribution=time_distribution,
        channel_name=start.strftime("%Y-%m-%d") + " to " + end.strftime("%Y-%m-%d"),
        channel_image=f"{base_domain}/static/logo.png",
        most_clipped_streams=most_clipped_streams,
        best_days={},
        first_clip_d={},
        search_route=None,
        search_for=None,
        average=average
    )


@app.route("/userstats")
@app.route("/userstats/")
@app.route("/userstats/<channel_id>")
@app.route("/userstats/<channel_id>/")
@app.route("/us")
@app.route("/us/")
@app.route("/us/<channel_id>")
@app.route("/us/<channel_id>/")
def user_stats(channel_id=None):
    if not channel_id:
        return redirect(url_for("slash"))
    channel_id = get_channel_id_any(channel_id)
    if not channel_id:
        return redirect(url_for("slash"))
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM QUERIES WHERE user_id=? AND private is not '1' ",
            (channel_id,),
        )
        data = cur.fetchall()
    if not data:
        return redirect(url_for("slash"))
    clips = []
    for x in data:
        clips.append(Clip(x))
    clip_count = len(clips)
    user_count = len(set([clip.channel for clip in clips]))
    # "Name": no of clips
    user_clips = {}
    top_clippers = {}
    notes = {}
    for clip in clips:
        if clip.channel not in user_clips:
            user_clips[clip.channel] = 0
        user_clips[clip.channel] += 1
        if clip.desc and clip.desc != "None":
            for word in clip.desc.lower().split():
                if word not in notes:
                    notes[word] = 0
                notes[word] += 1
        if clip.channel not in top_clippers:
            top_clippers[clip.channel] = 0
        top_clippers[clip.channel] += 1

    # sort
    notes = {
        k: 5 + 5 * v
        for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
    }
    notes = dict(list(notes.items())[:150])
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    new_dict = {}
    # replace dict_keys with actual channel
    max_count = 0
    streamer_name, streamer_image = get_channel_name_image(channel_id)

    # sort and get k top clippers
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    for k, v in user_clips.items():
        max_count += 1
        if max_count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new_dict[channel_name] = v
    new_dict["Others"] = sum(list(user_clips.values())[max_count:])
    if new_dict["Others"] == 0:
        new_dict.pop("Others")
    user_clips = new_dict
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new.append(
            {
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("channel_stats", channel_id=k),
            }
        )
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    best_days = {}

    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
        if day not in best_days:
            best_days[day] = 1
        else:
            best_days[day] += 1
    time_trend = new_dict
    day_counter = 0 
    clips_couter = 0
    average = {}
    for k, v in time_trend.items():
        day_counter += 1
        clips_couter += v
        average[k] = int(clips_couter/day_counter)
    best_days = {
        k: v
        for k, v in sorted(best_days.items(), key=lambda item: item[1], reverse=True)
    }
    best_days = dict(list(best_days.items())[:12])

    streamer_trend_data = {}
    # "clipper" : {day: no_of_clips}
    streamers_trend_days = []
    max_count = 0
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if clip.channel not in streamer_trend_data:
            streamer_trend_data[clip.channel] = {}
        if day not in streamer_trend_data[clip.channel]:
            streamer_trend_data[clip.channel][day] = 0
        streamer_trend_data[clip.channel][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # replace channel id with channel name
    new_dict = {}
    known_k = []
    max_count = 0
    # sort
    streamer_trend_data = {
        k: v
        for k, v in sorted(
            streamer_trend_data.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )
    }
    for k, v in streamer_trend_data.items():
        max_count += 1
        if max_count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new_dict[channel_name] = v
        known_k.append(k)
    new_dict["Others"] = {}
    for k, v in streamer_trend_data.items():
        if k in known_k:
            continue
        for day, count in v.items():
            if day not in new_dict["Others"]:
                new_dict["Others"][day] = 0
            new_dict["Others"][day] += count
    if new_dict["Others"] == {}:
        new_dict.pop("Others")
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[x] = 0
    for clip in clips:
        hm = int((clip.time + timedelta(hours=5, minutes=30)).strftime("%H"))
        time_distribution[hm] += 1
    # get the top most clipped streams
    cur.execute(
        """
            SELECT stream_link, COUNT(message_id) AS occurrence_count
            FROM QUERIES
            WHERE user_id = ?
            GROUP BY message_id
            ORDER BY occurrence_count DESC
            LIMIT 12;
        """,
        (channel_id,),
    )
    mcs = cur.fetchall()
    most_clipped_streams = {}  # stream_link: count
    for x in mcs:
        most_clipped_streams[get_video_id(x[0])] = x[1]
    message = f"User Stats for {streamer_name}. Clipped\n{clip_count} clips in {user_count} channels till now. and counting."
    return render_template(
        "stats.html",
        message=message,
        notes=notes,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count=len(user_clips),
        times=list(time_trend.keys()),
        counts=list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels=list(streamer_trend_data.keys()),
        time_distribution=time_distribution,
        channel_name=streamer_name,
        channel_image=streamer_image,
        most_clipped_streams=most_clipped_streams,
        best_days=best_days,
        first_clip_d={},
        search_route="/searchuser",
        search_for="user",
        average=average
    )


@app.route("/stats")
def stats():
    # get clips
    with conn:
        cur = conn.cursor()
        if current_user.admin:
            cur.execute("SELECT * FROM QUERIES")
        else:
            cur.execute("SELECT * FROM QUERIES WHERE private is not '1'")
        data = cur.fetchall()
    clips = []
    today = datetime.today()
    today = today.replace(hour=0, minute=0, second=0, microsecond=0)
    three_months_ago = (today - timedelta(days=28)).timestamp()
    if current_user.admin:
        three_months_ago = 0
    for x in data:
        c = Clip(x)
        clips.append(c)
    clip_count = len(data)
    user_count = len(set([x[5] for x in data]))
    # "Name": no of clips
    user_clips = {}
    top_clippers = {}
    notes = {}
    for clip in clips:
        if clip.channel not in user_clips:
            user_clips[clip.channel] = 0
        user_clips[clip.channel] += 1
        if clip.desc and clip.desc != "None":
            for word in clip.desc.lower().split():
                if word not in notes:
                    notes[word] = 0
                notes[word] += 1
        if clip.user_id not in top_clippers:
            top_clippers[clip.user_id] = 0
        top_clippers[clip.user_id] += 1

    # sort
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    # get only top 25 and other as sum of rest
    _user_clips = user_clips
    channel_count = len(_user_clips)
    user_clips = {}
    max_count = 0
    top_25_ids = []

    for k, v in _user_clips.items():
        max_count += 1
        if max_count > 25:
            break
        top_25_ids.append(k)
        user_clips[k] = v
    user_clips["Others"] = sum(list(_user_clips.values())[max_count - 1 :])
    if user_clips["Others"] == 0:
        user_clips.pop("Others")
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    notes = {
        k: v for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
    }
    notes = dict(list(notes.items())[:150])
    # replace dict_keys with actual channel
    new_dict = {}
    for k, v in user_clips.items():
        if k != "Others":
            channel_name, image = get_channel_name_image(k)
        else:
            channel_name = "Others"
        new_dict[channel_name] = v
    user_clips = new_dict
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new.append(
            {
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k),
            }
        )
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if clip.time.timestamp() < three_months_ago:
            continue
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
    time_trend = new_dict
    day_counter = 0 
    clips_couter = 0
    average = {}
    for k, v in time_trend.items():
        day_counter += 1
        clips_couter += v
        average[k] = int(clips_couter/day_counter)

    best_days = {}
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        try:
            best_days[day] += 1
        except KeyError:
            best_days[day] = 1
    best_days = {
        k: v
        for k, v in sorted(best_days.items(), key=lambda item: item[1], reverse=True)
    }
    best_days = dict(list(best_days.items())[:12])

    streamer_trend_data = {}
    # streamer: {day: no_of_clips}
    streamers_trend_days = []
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if clip.time.timestamp() < three_months_ago:
            continue  # we don't need to show old data
        channel_id = clip.channel
        if channel_id not in top_25_ids:
            channel_id = "Others"
        if channel_id not in streamer_trend_data:
            streamer_trend_data[channel_id] = {}
        if day not in streamer_trend_data[channel_id]:
            streamer_trend_data[channel_id][day] = 0
        streamer_trend_data[channel_id][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # only top 25 and others
    streamer_trend_data = {
        k: v
        for k, v in sorted(
            streamer_trend_data.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )
    }
    new_dict = {}
    known_k = []
    max_count = 0
    new_dict["Others"] = {}
    for k, v in streamer_trend_data.items():
        max_count += 1
        if k != "Others":
            channel_name, image = get_channel_name_image(k)
        else:
            channel_name = k
        new_dict[channel_name] = v
        known_k.append(k)
    if new_dict["Others"] == {}:
        new_dict.pop("Others")
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[x] = 0
    for clip in clips:
        hm = int((clip.time + timedelta(hours=5, minutes=30)).strftime("%H"))
        time_distribution[hm] += 1

    # get the top most clipped streams
    cur.execute(
        """
            SELECT stream_link, COUNT(message_id) AS occurrence_count
            FROM QUERIES
            GROUP BY message_id
            ORDER BY occurrence_count DESC
            LIMIT 12;
        """
    )
    mcs = cur.fetchall()
    most_clipped_streams = {}  # stream_link: count
    for x in mcs:
        most_clipped_streams[get_video_id(x[0])] = x[1]
    message = f"{user_count} users clipped\n{clip_count} clips on \n{channel_count} channels till now. \nand counting."

    first_clip_d = {}
    # now make a graph of first_clip to day
    this_month = (
        datetime.now()
        .replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        .replace(tzinfo=timezone.utc)
    )
    # if this is in first half of the month then we need to get the last month's data
    if datetime.now().day < 15:
        if this_month.month == 1:
            this_month = this_month.replace(month=12, year=this_month.year - 1)
        else:
            this_month = this_month.replace(month=this_month.month - 1)
    if current_user.admin:
        cur.execute(
            f"SELECT * FROM QUERIES WHERE time GROUP BY channel_id ORDER BY time DESC"
        )
    else:
        cur.execute(
            f"SELECT * FROM QUERIES WHERE PRIVATE IS NOT '1' AND time GROUP BY channel_id ORDER BY time DESC"
        )
    first_clip_sql = cur.fetchall()[::-1]  # reverse so earliest clip is at the end
    first_day = this_month.date()  # default starting point

    if current_user.admin:
        first_day = Clip(first_clip_sql[-1]).time.date()  # start from earliest clip

    last_day = Clip(first_clip_sql[0]).time.date()  # latest clip

    # Generate date range from first_day to last_day
    date_generated = [
        first_day + timedelta(days=x) for x in range(0, (last_day - first_day).days + 1)
    ]

    # Initialize the dictionary
    for single_date in date_generated:
        first_clip_d[single_date.strftime("%Y-%m-%d")] = 0

    # Fill the dictionary with actual clip data
    for clip in first_clip_sql:
        clip = Clip(clip)
        if not current_user.admin and clip.time < this_month:
            continue
        date = clip.time.strftime("%Y-%m-%d")
        try:
            first_clip_d[date] += 1
        except KeyError:
            first_clip_d[date] = 1
    return render_template(
        "stats.html",
        message=message,
        notes=notes,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count=channel_count,
        times=list(time_trend.keys()),
        counts=list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels=list(streamer_trend_data.keys()),
        time_distribution=time_distribution,
        first_clip_d=first_clip_d,
        channel_name="All channels",
        channel_image=f"{base_domain}/static/logo.png",
        most_clipped_streams=most_clipped_streams,
        best_days=best_days,
        search_route="/searchchannel",
        search_for="channel",
        average=average
    )


def get_members(tier: str = None):
    # returns all of membership details
    with conn:
        cur = conn.cursor()
        if tier:
            cur.execute(
                "SELECT * FROM MEMBERSHIP WHERE membership_type=? ORDER BY start DESC",
                (tier,),
            )
        else:
            cur.execute("SELECT * FROM MEMBERSHIP ORDER BY start DESC")
        data = cur.fetchall()
    members = {}
    for m in data:
        m = Membership(m)

        m.name, m.image = get_channel_name_image(m.channel_id)
        if not m.active:
            m.type = "expired"
            m.name = m.name + " ("+ m.last_state + ")"

        if m.type not in members:
            members[m.type] = []
        members[m.type].append(m)
    return members


def get_creds():
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT channel_id, webhook FROM SETTINGS")
        data = cur.fetchall()
    creds = {}
    for x in data:
        if not x[1]:
            continue  # skip if no webhook
        creds[x[0]] = x[1]
    return creds


@app.route("/admin")
@login_required
def admin():
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    users = generate_home_data()
    settings = vars(UserSettings())
    members = get_members()
    tiers = [x for x in members.keys()]
    transactions = get_transactions_all()
    transactions = [Transactions(x) for x in transactions if float(x[1]) != 0] # only get positive transactions
    total_earn = sum([x.amount for x in transactions])
    return render_template(
        "admin.html",
        transactions=transactions,
        total_earn = total_earn,
        users=users,
        settings=settings,
        members=members,
        tiers=tiers,
    )

@app.route("/del_membership", methods=["POST"])
@login_required
def delete_membership():
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    channel_id = request.json.get("channel_id")
    terminate_current_membership(channel_id)
    return "ok", 200


@app.route("/update_transaction", methods=["POST"])
@login_required
def update_transaction():
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    print(request.json)

    channel_id = request.json.get("channel_id")
    transaction_id = request.json.get("transaction_id")
    amount = request.json.get("amount")
    time = request.json.get("time")
    tier = request.json.get("tier")
    description = request.json.get("description")
    if not channel_id or not transaction_id:
        return "Invalid channel id or transaction id", 400
    if not amount or not time or not tier:
        return "Invalid amount, time, tier", 400
    if tier not in subscription_model.keys():
        return "Invalid tier", 400
    
    if not transaction_id or not channel_id:
        return "Invalid transaction id or channel id", 400
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM TRANSACTIONS WHERE transaction_id=? AND channel_id=? LIMIT 1",
            (transaction_id, channel_id),
        )
        data = cur.fetchall()
        if not data:
            return "Transaction ID is invalid", 400
        cur.execute(
            "UPDATE TRANSACTIONS SET amount=?, time=?, membership_type=?, description=? WHERE transaction_id=? AND channel_id=?",
            (amount, time, tier, description, transaction_id, channel_id),
        )
    conn.commit()
    return "ok", 200

@app.route("/del_transaction", methods=["POST"])
@login_required
def delete_transaction():
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    transaction_id = request.json.get("transaction_id")
    channel_id = request.json.get("channel_id")
    if not transaction_id or not channel_id:
        return "Invalid transaction id or channel id", 400
    with conn:
        cur = conn.cursor()
        # use the workaround DELETE FROM table WHERE rowid = (SELECT rowid FROM table WHERE condition LIMIT 1 ) 
        cur.execute("DELETE FROM TRANSACTIONS WHERE rowid = (SELECT rowid FROM TRANSACTIONS WHERE transaction_id=? AND channel_id=? LIMIT 1 )", (transaction_id, channel_id))
    conn.commit()
    return "ok", 200    

@app.route("/add_new_transaction", methods=["POST"])
@login_required
def add_new_transaction():  
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    channel_id = request.json.get("channel_id")
    transaction_id = request.json.get("transaction_id")
    if not transaction_id or not channel_id:
        return "Invalid transaction id or channel id", 400
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM TRANSACTIONS WHERE transaction_id=? AND channel_id=? LIMIT 1",
            (transaction_id, channel_id),
        )
        data = cur.fetchall()
        if data:
            return "Transaction already exists", 400
        cur.execute(
            "INSERT INTO TRANSACTIONS (transaction_id, channel_id) VALUES (?, ?)",
            (transaction_id, channel_id),
        )
    conn.commit()
    return "ok", 200

@app.route("/update_membership", methods=["POST"])
@login_required
def update_membership():

    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    channel_id = request.json.get("channel_id")
    tier = request.json.get("tier")
    start = request.json.get("start")
    end = request.json.get("end")

    if tier not in subscription_model.keys():
        flash("Invalid tier", "danger")
        return redirect(url_for("slash"))
    if not channel_id.startswith("UC"):
        flash("Invalid channel id", "danger")
        return redirect(url_for("slash"))
    if not start or not end:
        flash("Invalid dates", "danger")
        return redirect(url_for("slash"))
    start = int(start)
    end = int(end)
    with conn:
        cur = conn.cursor()
        print(channel_id)
        cur.execute(
            "SELECT * FROM MEMBERSHIP WHERE channel_id=?",
            (channel_id,),
        )
        data = cur.fetchall()
        if data:
            cur.execute(
                "UPDATE MEMBERSHIP SET start=?, end=?, type=? WHERE channel_id=?",
                (start, end, tier, channel_id,),
            )
        else:
            cur.execute(
                "INSERT INTO MEMBERSHIP (channel_id, type, start, end) VALUES (?, ?, ?, ?)",
                (channel_id, tier, start, end,),
            )
    conn.commit()
    return "ok", 200


@app.route("/get_individual_membership/<channel_id>")
@login_required
def get_individual_membership(channel_id):
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    membership_info = Membership.get(channel_id=channel_id, conn=conn)
    transactions = get_transactions(channel_id)
    if not transactions:
        transactions = []
    return jsonify({   
        "membership": membership_info.json(),
        "transactions": transactions,
        }
    )
@app.route("/update_settings", methods=["POST"])
def update_settings():
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    settings = UserSettings()
    user_ids = []
    settings = {}
    for key, value in request.form.items():
        if key == "new":
            continue
        if key.startswith("UC"):
            user_ids.append(key)
        else:
            if value.lower() == "true":
                value = "True"
            elif value.lower() == "false":
                value = "False"
            settings[key] = str(value)
    for user_id in user_ids:
        user_settings = get_channel_settings(user_id)
        for key, value in settings.items():
            setattr(user_settings, key, value)
        user_settings.write(conn=conn)
    return "ok"


def get_channel_id(path):
    html_data = get(path).text
    soup = BeautifulSoup(html_data, "html.parser")
    identifier = soup.find("meta", itemprop="identifier")
    if not identifier:
        return None
    channel_id = identifier["content"]
    return channel_id


@app.route("/autoapprove")
def autoapprove():
    # verify if the entry is eligible to be autoapproved i.e there have been no previous creds.
    flash("Disabled. ", "info")  
    return redirect("/")
    # this is in format of https://streamsnip.com/autoapprove?key=https://www.youtube.com/channel/UC5IRLz3Q-SADL71-sW-Z16Q&value=https://discord.com/api/webhooks/51313123122515125/sadfasdasd12rasfafase-VOkUSVo4clrbXSh6Mpa
    key = request.args.get("key")
    value = request.args.get("value")
    if not any([key, value]):
        return "Key or Value not found"
    channel_id = get_channel_id(key)
    email = request.args.get("email")
    proof = request.args.get("proof")

    if "studio.youtube.com" in key:
        key = key.replace("studio.youtube.com", "youtube.com")
    if "youtube.com" not in key:
        return f"Key isn't of youtube {key}"
    if "api/webhooks" not in value:
        return f"Value isn't of discord webhook"
    if not channel_id:
        return "Channel id not found"
    password = config["password"]
    request.args = {"pass": password, "key": key, "value": value, "email": email}
    creds = get_creds()
    channel_clips = get_channel_clips(channel_id)

    if channel_id in creds or channel_clips:
        if "management_webhook" in config:
            webhook = DiscordWebhook(
                url=config["management_webhook"],
                username=project_name,
                avatar_url=project_logo_discord,
            )
            embed = DiscordEmbed(
                title=f"Auto-approve request",
                description=f"Auto-approve request for {key} to [discord webhook]({value})",
            )
            approve_url = url_for("approve", _external=True, **request.args)
            embed.add_embed_field(name="Email", value=email)
            embed.add_embed_field(name="Approve", value=f"[Approve]({approve_url})")
            embed.set_thumbnail(url=project_logo_discord)
            # even if we want to directly embed the image we can't. since its on google drive and not accessible to everyone.
            if proof:
                embed.add_embed_field(name="Proof", value=proof)
            embed.set_color(0xEBF0F7)
            webhook.add_embed(embed)
            webhook.execute()
        if channel_id in creds:
            return "Channel already have a webhook. can't auto approve"
        else:
            return "Channel already have clips. can't auto approve"
    return approve()


@app.route("/approve")
def approve():
    flash("Disabled. ", "info")  
    return redirect("/")
    # this is in format of https://streamsnip.com/approve?pass=somepassword&key=https://www.youtube.com/channel/UC5IRLz3Q-SADL71-sW-Z16Q&value=https://discord.com/api/webhooks/51313123122515125/sadfasdasd12rasfafase-VOkUSVo4clrbXSh6Mpa
    password = request.args.get("pass")
    key = request.args.get("key")
    value = request.args.get("value")
    applier_email = request.args.get("email")

    value = value.replace("discordapp.com", "discord.com")

    if password != config["password"]:
        return "Wrong password"
    if "youtube.com" not in key:
        return f"Key isn't of youtube "
    if "/api/webhooks" not in value:
        return f"Value isn't of discord webhook "
    if not key.startswith("htt"):
        key = "https://" + key  # care about both http and https
    channel_id = get_channel_id(key)
    if not channel_id:
        return "Channel id not found"

    channel_name, channel_image = get_channel_name_image(channel_id)
    webhook = DiscordWebhook(
        url=value, username=project_name, avatar_url=project_logo_discord
    )
    embed = DiscordEmbed(
        title=f"Welcome to {project_name}!",
        description=f"I will send clips for {channel_name} here",
    )
    embed.add_embed_field(
        name="Add Nightbot command",
        value=f"If you haven't already. add Nightbot commands from [github]({project_repo_link}) .",
    )
    embed.set_thumbnail(url=project_logo_discord)
    embed.set_color(0xEBF0F7)
    webhook.add_embed(embed)
    response = webhook.execute()
    if response.status_code != 200:
        return response.text
    creds = get_creds()
    creds[channel_id] = value
    write_creds(creds)
    if "update_webhook" in config:
        webhook = DiscordWebhook(
            url=config["update_webhook"],
            username=project_name,
            avatar_url=project_logo_discord,
        )
        embed = DiscordEmbed(
            title=f"New webhook added",
            description=f"New webhook added for {channel_name}",
        )
        embed.set_thumbnail(url=channel_image)
        embed.set_color(0xEBF0F7)
        webhook.add_embed(embed)
        webhook.execute()
    email = config.get("smtp", None)
    if email and applier_email:
        send_email(
            applier_email,
            f"Welcome to {project_name}! \nI will send clips for {channel_name} on your discord channel. \n\nIf you haven't already, add Nightbot commands from {project_repo_link}?tab=readme-ov-file#nightbot-command .\n\n\n\nBest Of Luck\n{project_name}",
        )
    return "Done"


def send_email(email=None, message="New webhook added"):
    try:
        user = config["smtp"]["auth"]["user"]
        if not user:
            raise KeyError
    except KeyError:
        return "Email not configured"
    smtp = config["smtp"]
    host = smtp["host"]
    port = smtp["port"]
    password = smtp["auth"]["pass"]
    if not all([host, port, password]):
        return "Email not configured"
    try:
        yag = yagmail.SMTP(user=user, password=password, host=host, port=port)
        yag.send(to=email, subject=f"Welcome to {project_name}!", contents=message)
    except Exception as e:
        return str(e)
    return "Email sent"


@app.route("/ed", methods=["POST"])
@login_required
def edit_delete():
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    # get the clip id
    clip_id = request.form.get("clip")
    # get the action
    if request.form.get("rename") == "Rename":
        if not request.form.get("clip", None):
            return "No Clip selected"
        # edit the clip
        if not request.form.get("new_name", None):
            return "No new name provided"
        new_name = request.form.get("new_name").strip()
        clip = get_clip(clip_id)
        webhook_url = get_channel_settings(clip.channel).webhook
        clip.edit(new_name, conn, webhook_url=webhook_url)
        return "Edited"

    elif request.form.get("delete") == "Delete":
        if not request.form.get("clip", None):
            return "No Clip selected"
        # delete the clip
        clip = get_clip(clip_id)
        if not clip:
            return "Clip not found"
        webhook_url = get_channel_settings(clip.channel).webhook
        clip.delete(conn, webhook_url=webhook_url)
        return "Deleted"

    elif request.form.get("new") == "Submit":
        if not request.form.get("key", None):
            return "No key provided"
        if not request.form.get("value", None):
            return "No value provided"
        key = request.form.get("key").strip()
        value = request.form.get("value").strip()

        creds = get_creds()
        creds[key] = value
        channel_name, channel_image = get_channel_name_image(key)
        if value.startswith("https://discord"):
            webhook = DiscordWebhook(
                url=value, username=project_name, avatar_url=project_logo_discord
            )
            embed = DiscordEmbed(
                title=f"Welcome to {project_name}!",
                description=f"I will send clips for {channel_name} here",
            )
            embed.add_embed_field(
                name="Add Nightbot command",
                value=f"If you haven't already. add Nightbot commands from [github]({project_repo_link}?tab=readme-ov-file#nightbot-command) .",
            )
            embed.set_thumbnail(url=project_logo_discord)
            embed.set_color(0xEBF0F7)
            webhook.add_embed(embed)
            webhook.execute()
        if "update_webhook" in config:
            webhook = DiscordWebhook(
                url=config["update_webhook"],
                username=project_name,
                avatar_url=project_logo_discord,
            )
            embed = DiscordEmbed(
                title=f"New webhook added",
                description=f"New webhook added for {channel_name}",
            )
            embed.set_thumbnail(url=channel_image)
            embed.set_color(0xEBF0F7)
            webhook.add_embed(embed)
            webhook.execute()
        return jsonify(creds)
    elif request.form.get("show") == "show":
        return jsonify(get_creds())
    elif request.form.get("refresh") == "refresh cache":
        global channel_info
        channel_info = {}  # set channel_info to empty
        write_channel_cache(channel_info)
        return redirect(url_for("admin"))
    elif request.form.get("refreshdeleted") == "refresh deleted":
        lc = deepcopy(channel_info)
        for channel in lc:
            if "deleted" in channel_info[channel]["name"]:
                print(f"deleting {channel}")
                del channel_info[channel]
        del lc
        return redirect(url_for("admin"))
    else:
        return f"what ? {request.form}"


def get_latest_live(channel_id):
    vids = scrapetube.get_channel(channel_id, content_type="streams", limit=2, sleep=0)
    live_found_flag = False
    for vid in vids:
        if (
            vid["thumbnailOverlays"][0]["thumbnailOverlayTimeStatusRenderer"]["style"]
            == "LIVE"
        ):
            live_found_flag = True
            break
    if not live_found_flag:
        return None
    vid = YouTubeChatDownloader(cookies=cookies).get_video_data(video_id=vid["videoId"])
    return vid


@app.route("/add", methods=["POST", "GET"])
@login_required
def add():
    flash("Disabled. ", "info")  
    return redirect("/")
    if request.method == "GET":
        return render_template(
            "add.html", link="enter stream link", desc="!clip", first_render=True
        )
    else:
        data = request.form
        if data.get("new") == "Submit":
            link = data.get("link", None)
            # sanitize the link / remove all the arguments except the v
            if not link:
                return "Youtube Link not found"
            # reconstruct the link
            vid = get_video_id(link)
            link = f"https://www.youtube.com/watch?v={vid}"
            desc = data.get("command", "!clip")
            if not link:
                return "Youtube Link not found"
            vid_id = get_video_id(link)
            if not vid_id:
                return "Invalid link"
            vid = YouTubeChatDownloader(cookies=cookies).get_video_data(video_id=vid_id)
            streamer_id = vid["author_id"]
            if (
                not current_user.password == get_webhook_url(streamer_id)
                and not current_user.admin
            ):
                return "Provided stream is not of the current logged in user."
            right_chats = []
            channel_clips = get_channel_clips(streamer_id)
            # rasterize the chat from delay
            xx = []
            for clip in channel_clips:
                if clip.delay:
                    clip.time_in_seconds -= clip.delay
                    clip.delay = 0
                if vid_id != clip.stream_id:
                    continue
                d = {
                    "id": clip.id,
                    "desc": clip.desc,
                }
                xx.append(d)
            with conn:
                for chat in ChatDownloader(cookies=cookies).get_chat(vid_id):
                    flag = False
                    time = int(chat["time_in_seconds"])
                    for x in xx:
                        if chat["message"] == f"{desc} {x['desc']}":
                            flag = True
                            break
                    if flag:
                        continue
                    if chat["message_type"] == "text_message":
                        if chat["message"].startswith(desc):
                            right_chats.append(chat)
            return render_template("add.html", link=link, desc=desc, chats=right_chats)
        else:
            # second time
            link = data.get("link", None)
            # sanitize the link / remove all the arguments
            if not link:
                return "Youtube Link not found"
            # reconstruct the link
            vid = link.split("v=")[1].split("&")[0]
            link = f"https://www.youtube.com/watch?v={vid}"
            vid_id = get_video_id(link)
            delay = data.get("delay")
            if not delay:
                delay = 0
            vid = YouTubeChatDownloader(cookies=cookies).get_video_data(video_id=vid_id)
            streamer_id = vid["author_id"]
            if (
                not current_user.password == get_webhook_url(streamer_id)
                and not current_user.admin
            ):
                return "Provided stream is not of the current logged in user."
            right_chats = []
            for chat in ChatDownloader().get_chat(vid_id):
                if chat["message_id"] in data.keys():
                    right_chats.append(chat)
            response = ""
            for chat in right_chats:
                clip_message = " ".join(chat["message"].split(" ")[1:])
                chat_id = vid_id
                try:
                    user_level = parse_user_badges(chat["author"]["badges"])
                except KeyError:
                    user_level = "everyone"
                headers = {
                    "Nightbot-Channel": f"providerId={streamer_id}",
                    "Nightbot-User": f"providerId={chat['author']['id']}&displayName={chat['author']['name']}&userLevel={user_level}",
                    "Nightbot-Response-Url": "https://api.nightbot.tv/1/channel/send/",
                    "videoID": vid_id,
                    "timestamp": str(chat["timestamp"]),
                }
                if request.is_secure:
                    htt = "https://"
                else:
                    htt = "http://"
                link = f"{htt}{request.host}/clip/{chat_id}/{clip_message}"
                if delay:
                    delay = int(delay)
                    link += f"?delay={delay}"
                r = get(link, headers=headers)
                response += r.text + "\n"
            return "Done" + "\n" + response


def parse_user_badges(badges) -> str:
    """owner - Channel Owner
    moderator - Channel Moderator
    subscriber - Paid Channel Subscriber
    everyone"""
    badges = [x["title"].split(" ")[0].lower() for x in badges]
    if "owner" in badges:
        return "owner"
    if "moderator" in badges:
        return "moderator"
    if "member" in badges:
        return "subscriber"
    return "everyone"


@app.route("/uptime")
def uptime():
    # returns the uptime of the bot
    # takes 1 argument seconds
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    latest_live = get_latest_live(channel_id)
    if not latest_live:
        return "No live stream found"
    start_time = latest_live["start_time"] / 1000000
    current_time = time.time()
    uptime_seconds = current_time - start_time
    uptime = time_to_hms(uptime_seconds)
    level = request.args.get("level", 0)
    try:
        level = int(level)
    except ValueError:
        level = 0
    if not level:
        return f"Stream uptime is {uptime}"
    elif level == 1:
        return str(uptime)
    elif level == 2:
        # convert time to x hours y minutes z seconds
        uptime = uptime.split(":")
        string = "Stream is running from "
        if len(uptime) == 3:
            string += f"{uptime[0]} hours {uptime[1]} minutes & {uptime[2]} seconds."
        elif len(uptime) == 2:
            string += f"{uptime[0]} minutes & {uptime[1]} seconds."
        else:
            string += f"{uptime[0]} seconds."
        return str(string)
    else:
        return str(uptime_seconds)


@app.route("/stream_info")
def stream_info():
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    return get_latest_live(channel_id)


@app.route("/recent")
@app.route("/record")
def recent():
    default_value = 5
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    clips = [clip for clip in get_channel_clips(channel_id) if not clip.private]
    string = ""
    request_count = request.args.get("count", default_value)
    try:
        request_count = int(request_count)
    except ValueError:
        request_count = default_value

    for clip in clips[:request_count]:
        if len(clip.desc) > 10:
            clip.desc = clip.desc[:10] + "..."
        string += f"{clip.desc} {clip.id} | "
    if len(string) > 256:
        return string[:256]  # youtube limits to 256 characters. who are we to disobey
    return string


@app.route("/nstats")
@app.route("/nstat")
def nstats():
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Headers not found. Are you sure you are using nightbot ?"
    channel_id = channel.get("providerId")[0]
    user_id = user.get("providerId")[0]
    clips = get_channel_clips(channel_id)
    total_clips = len(clips)
    total_users = len(set([clip.user_id for clip in clips]))
    user_clip = [clip for clip in clips if clip.user_id == user_id]
    user_clip_count = len(user_clip)
    this_stream_count = 0
    try:
        this_stream_id = get_latest_live(channel_id)["original_video_id"]
    except:
        this_stream_id = None
    for clip in clips:
        if clip.stream_id == this_stream_id:
            this_stream_count += 1
        else:
            break  # this is cause the clips are sorted by time. so if we find a clip that is not of this stream. we can break and save time

    percentage = (user_clip_count / total_clips) * 100
    percentage = round(percentage, 2)
    today_count_string = (
        f" ({this_stream_count} today)" if this_stream_count != 0 else f""
    )
    return f"{total_clips} clips have been made {today_count_string} by total {total_users} users, out of which {user_clip_count} clips ({percentage}%) have been made by you."


@app.route("/clip/<guild_id>/<channel_id>/")
@app.route("/clip/<guild_id>/<channel_id>/<message>")
def discord_clip(guild_id, channel_id, message=None):
    if not guild_id:
        return "Guild id not found"
    if not channel_id:
        return "Channel id not found"
    return f"Guild id: {guild_id} Channel id: {channel_id} Message: {message} Probably not what you are looking for. use !clip on youtube only. --Admin ({base_domain})"


def get_transactions(channel_id):
    cur.execute("SELECT * FROM TRANSACTIONS WHERE channel_id=?", (channel_id,))
    return cur.fetchall()


def can_avail_free_trial(channel_id):
    membership_details = Membership.get(conn, channel_id)
    old_transactions = get_transactions(channel_id) 
    used_free_trial = True if any(["free" in x[3].lower() for x in old_transactions]) else False
    if not membership_details.in_db and not used_free_trial:
        return True
    if membership_details.type == "FREE":
        return False
    return False


def start_free_trial(channel_id):
    with conn:
        end_time = (
            int(time.time()) + 28 * 24 * 60 * 60
        )  # we give 28 to include current day too
        start_time = int(time.time())
        cur.execute(
            "INSERT INTO MEMBERSHIP VALUES (?, ?, ?, ?)",
            (channel_id, "FREE", start_time, end_time),
        )
        cur.execute(
            "INSERT INTO TRANSACTIONS VALUES (?, ?, ?, ?, ?, ?)",
            (
                channel_id,
                0,
                int(time.time()),
                "FREE TRIAL",
                "FREE",
                "Free Trial for 28 days",
            ),
        )
        conn.commit()


def is_subscribed(channel_id, free_trial=True):
    membership_detail = Membership.get(conn, channel_id)
    if not membership_detail.in_db:
        # if the channel is not in db that means its new. give 28 days of free trial that means 199 rs
        if free_trial and can_avail_free_trial(channel_id):
            start_free_trial(channel_id)
            return "FREE"
        else:
            return False
    if membership_detail.active:
        return membership_detail.type
    return ""  # no membership


# /clip/<message_id>/<clip_desc>?showlink=true&screenshot=true&dealy=-10&silent=2
@app.route("/clip/<message_id>/")
@app.route("/clip/<message_id>/<clip_desc>")
def clip(message_id, clip_desc=None):
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Headers not found. Are you sure you are using nightbot ?"
    channel_id = channel.get("providerId")[0]
    user_level = user.get("userLevel")[0]
    if "automated" in user_level.lower():
        user_level = "automated"
    user_id = user.get("providerId")[0]
    user_name = user.get("displayName")[0]
    channel___name, channel___image = get_channel_name_image(channel_id)

    arguments = {k.replace("?", ""): request.args[k] for k in request.args}

    sub_detail = is_subscribed(channel_id)
    if not sub_detail:
        return f"@{channel___name} 's free trial ended ☹. Get the subscription at {base_domain}/membership"
    free_trial = False
    mmmmembership = Membership.get(conn, channel_id)
    time_left = mmmmembership.time_left
    if sub_detail == "FREE":
        free_trial = True
        sub_detail = "pro"

    channel_settings = get_channel_settings(channel_id)
    if sub_detail != "basic":
        # in this case take the default arguments
        show_link = arguments.get("showlink", channel_settings.show_link)
        screenshot = arguments.get("screenshot", channel_settings.screenshot)
        # if taken from argument then it will be a string. either 'true' or 'false'
        silent = arguments.get(
            "silent", channel_settings.silent
        )  # silent level. if not then 2
        private = arguments.get("private", channel_settings.private)
        webhook = arguments.get("webhook", channel_settings.webhook)
        if webhook and not webhook.startswith("https://discord.com/api/webhooks/"):
            webhook = f"https://discord.com/api/webhooks/{webhook}"
        webhook_url = webhook

        take_delays = arguments.get("take_delays", channel_settings.take_delays)
        force_desc = arguments.get("force_desc", channel_settings.force_desc)
        delay = arguments.get("delay", channel_settings.delay)
        message_level = arguments.get(
            "message_level", channel_settings.message_level
        )  # 0 is normal. 1 is to persist the defautl webhook name. 2 is for no record on discord message. 3 is for service badging
        try:
            message_level = int(message_level)
        except ValueError:
            message_level = channel_settings.message_level
        logging.log(
            level=logging.INFO,
            msg=f"A request for clip with arguments {arguments} and headers {request.headers}",
        )
        if webhook and not webhook.startswith("https://discord.com/api/webhooks/"):
            webhook = f"https://discord.com/api/webhooks/{webhook}"
        try:
            silent = int(silent)
        except ValueError:
            silent = channel_settings.silent

        if (
            type(show_link) == str
        ):  # we got this from the arguments. we must convert it to boolean
            show_link = (
                False if show_link.lower() == "false" else channel_settings.show_link
            )  # we revert back to the channel settings if we can't convert it to boolean
        if type(screenshot) == str:
            screenshot = (
                True if screenshot.lower() == "true" else channel_settings.screenshot
            )
        if type(private) == str:
            private = True if private.lower() == "true" else channel_settings.private
        if type(take_delays) == str:
            take_delays = (
                True if take_delays.lower() == "true" else channel_settings.take_delays
            )
        if type(force_desc) == str:
            force_desc = (
                True if force_desc.lower() == "true" else channel_settings.force_desc
            )
        if type(delay) == str:
            try:
                delay = int(delay)
            except ValueError:
                delay = channel_settings.delay
        if type(message_level) == str:
            try:
                message_level = int(message_level)
            except ValueError:
                message_level = channel_settings.message_level
        logging.log(
            logging.INFO,
            f"""
                    Arguments {arguments} - show-link {show_link} - screenshot {screenshot} - private {private} - take_delays {take_delays} - force_desc {force_desc} - delay {delay} - message_level {message_level} - webhook {webhook_url} - silent {silent} - channel_id {channel_id} - user_id {user_id} - user_name {user_name} - message_id {message_id} - clip_desc {clip_desc}""",
        )
        show_link_message = ""
        try:
            delay = 0 if not delay else int(delay)
        except ValueError:
            return "Delay should be an integer (plus or minus)"
        if not clip_desc:
            if force_desc:
                return "Clip denied. You must give a title to the clip."
            clip_desc = "None"
        if take_delays:
            splitted = clip_desc.split()
            candidates = [splitted[0], splitted[-1]]
            for c in candidates:
                try:
                    extra_delay = int(c)
                    # if extra delay is in positive. make sure its appended with a + sign
                    # cases like `!clip 200 iq play` should not actually add 200 seconds. but `!clip +200 iq play` should
                    if extra_delay > 0:
                        if not c.startswith("+"):
                            continue
                    clip_desc = clip_desc.replace(c, "")
                    delay += extra_delay
                    break
                except ValueError:
                    pass
    else:
        webhook = DEFAULT_SETTINGS.webhook
        show_link = DEFAULT_SETTINGS.show_link
        screenshot = DEFAULT_SETTINGS.screenshot
        private = DEFAULT_SETTINGS.private
        webhook_url = None
        take_delays = DEFAULT_SETTINGS.take_delays
        force_desc = DEFAULT_SETTINGS.force_desc
        if not clip_desc:
            if force_desc:
                return "Clip denied. You must give a title to the clip."
            clip_desc = "None"
        # delay = DEFAULT_SETTINGS.delay # we don't need to set the delay. since we are not going to use it
        delay = arguments.get("delay", channel_settings.delay)
        if type(delay) == str:
            try:
                delay = int(delay)
            except ValueError:
                delay = channel_settings.delay
        message_level = DEFAULT_SETTINGS.message_level
        silent = DEFAULT_SETTINGS.silent

    request_time = time.time()
    h_request_time = request.headers.get("timestamp")
    if h_request_time:
        try:
            request_time = float(h_request_time)
        except ValueError:
            return "The value of request time in headers must be a number"
        if len(str(int(request_time))) > 10:
            request_time = request_time / 1000000
            # this is because youtube unknownigly stores chat timing with very high precision.
    if not local:
        monitor.ping(state="run")
    if not message_id:
        return f"No message id provided, You have configured it wrong. Please check your webhook at {base_domain}/settings"

    if message_id in chat_id_video:
        vid = chat_id_video[message_id]
    else:
        try:
            vid = get_latest_live(channel_id)
            chat_id_video[message_id] = vid
        except:
            vid = None
    # if there is a video id passed through headers. we may want to use it instead
    h_vid = request.headers.get("videoID")
    if is_blacklisted(channel_id):
        if show_fake_error:
            return "Remote Server Returned Code 404"
        else:
            return "You are blacklisted from using this service. for undisclosed reasons. :)"
    if h_vid:
        vid = YouTubeChatDownloader(cookies=cookies).get_video_data(video_id=h_vid)
    if not vid:
        return "No LiveStream Found. or failed to fetch the stream. Please try again later."
    clip_time = request_time - vid["start_time"] / 1000000 + 5
    clip_time += delay
    url = "https://youtu.be/" + vid["original_video_id"] + "?t=" + str(int(clip_time))
    clip_id = message_id[-3:] + str(int(clip_time))
    # if clip_time is in seconds. then hh:mm:ss format would be like
    hour_minute_second = time_to_hms(clip_time)
    is_privated_str = "(P) " if private else ""
    message_cc_webhook = f"{is_privated_str}{clip_id} | **{clip_desc}** \n\n{hour_minute_second} \n<{url}>"
    if delay:
        message_cc_webhook += f"\nDelayed by {delay} seconds."
    if message_level == 0:
        channel_name, channel_image = get_channel_name_image(user_id)
        webhook_name = user_name
    elif message_level == 1:
        channel_name, channel_image = "", ""
        webhook_name = ""
        message_cc_webhook += f"\nClipped by {user_name}"
    elif message_level == 2:
        webhook_name = ""
        channel_name, channel_image = "", ""
    else:
        webhook_name = project_name
        channel_name, channel_image = (
            project_name,
            project_logo_discord,
        )

    if message_level == 0:
        if user_level == "owner":
            webhook_name += f" {owner_icon}"
        elif user_level == "moderator":
            webhook_name += f" {mod_icon}"
        elif user_level == "regular":
            webhook_name += f" {regular_icon}"
        elif user_level == "subscriber":
            webhook_name += f" {subscriber_icon}"
        elif user_level == "automated":
            webhook_name += f" {automated_icon}"

    if clip_desc and len(clip_desc) > 26:
        t_clip_desc = clip_desc[:26] + "..."
    else:
        t_clip_desc = clip_desc
    message_to_return = ""
    if free_trial:
        if time_left.total_seconds() < 86400 * 3:  # less than 3 days
            message_to_return += (
                "Free Trial Ending Today. " if time_left.days == 0
                else f"Free Trial Ending in {time_left.days} days. "
            )
        else:
            # Only add this if not already covered by ending notice
            message_to_return += "Free Trial - "

    clip_info = f"'{t_clip_desc}' " if t_clip_desc != "None" else ""
    ending_soon = ""
    if not free_trial and time_left.days < 7:
        ending_soon = f" (subscription ending in {time_left.days} day{'s' if time_left.days > 1 else ''})"

    message_to_return += f"{project_name}{ending_soon} successfully clipped {clip_info}({clip_id}) by {user_name}"

    if delay:
        message_to_return += f" with a delay of {delay} seconds."
    if webhook_url:  # if webhook is not found then don't send the message
        message_to_return += " | sent to discord."
        webhook = DiscordWebhook(
            url=webhook_url,
            content=message_cc_webhook,
            username=webhook_name,
            avatar_url=channel_image,
            allowed_mentions={"role": [], "user": [], "everyone": False},
        )
        response = webhook.execute()
        if not response.status_code == 200:
            return f"Error in sending message to discord. Perhaps the webhook is invalid. Please contact AG1436 at {discord_invite}"
        webhook_id = webhook.id
        if (
            show_link == 1
        ):  # we don't need to get webhook details if its not needed (optimization)
            webhook_details = GET(webhook_url).json()
            # construct the link
            ll = f"https://discord.com/channels/{webhook_details['guild_id']}/{webhook_details['channel_id']}/{webhook_id}"
            show_link_message = f" See the clip message at {ll}"
    else:
        webhook_id = None

    try:
        if screenshot and webhook_url:
            webhook = DiscordWebhook(
                url=webhook_url,
                username=user_name,
                avatar_url=channel_image,
                allowed_mentions={"role": [], "user": [], "everyone": False},
            )
            file_name = take_screenshot(url, clip_time)
            with open(file_name, "rb") as f:
                webhook.add_file(file=f.read(), filename="ss.jpg")
            webhook.execute()
            ss_id = webhook.id
            ss_link = webhook.attachments[0]["url"]
        else:
            ss_id = None
            ss_link = None
    except Exception as e:
        ss_id = None
        ss_link = None
        logging.log(logging.ERROR, "Error in taking screenshot"+str(e))
        message_to_return += " Couldn't take screenshot."

    if show_link is True:
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        show_link_message = f" See at {htt}{request.host}{url_for('exports', channel_id=get_channel_at(channel_id))}"
    if len(message_to_return) + len(show_link_message) > 200:
        pass
    else:
        message_to_return += show_link_message

    # insert the entry to database
    with conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO QUERIES VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                channel_id,
                message_id,
                clip_desc,
                request_time,
                clip_time,
                user_id,
                user_name,
                url,
                webhook_id,
                delay,
                user_level,
                ss_id,
                ss_link,
                private,
                message_level,
            ),
        )
        conn.commit()
    if not local:
        monitor.ping(state="complete")
    if private:
        return "clipped 😉"
    if silent == 2:
        return message_to_return[:200]
    elif silent == 1:
        return clip_id
    else:
        return " "
@app.route("/get_other_pov", methods=["POST"])
def get_other_pov():
    clip_id = request.json.get("clip_id")
    if not clip_id:
        return "No clip id provided", 400

    # This is the OTHER streamer's ID (for POV)
    other_streamer_id = request.json.get("streamer_id")
    if not other_streamer_id:
        return "No streamer id provided", 400

    # Get the original clip and its source stream
    clip = get_clip(clip_id)  # clip should have stream_id and offset_seconds
    if not clip:
        return "Clip not found", 404

    try:
        # Get the original stream's start time
        clip_stream = YouTubeChatDownloader(cookies=cookies).get_video_data(
            video_id=clip.stream_id
        )
        clip_stream_start_time = clip_stream["start_time"] / 1_000_000
        clip_absolute_time = clip.time.timestamp()
    except Exception as e:
        print(f"Error getting clip stream data: {e}")
        return "Failed to get clip stream data", 500

    print(f"Searching POV from {other_streamer_id} for clip at {clip_absolute_time}")
    return get_other_streamer_pov(other_streamer_id, clip_absolute_time, clip.delay)
    
def get_other_streamer_pov(other_streamer_id, clip_absolute_time, clip_delay):
    try:
        vids = scrapetube.get_channel(other_streamer_id, content_type="streams", sleep=0)
        for vid in vids:
            try:
                vid_data = YouTubeChatDownloader(cookies=cookies).get_video_data(
                    video_id=vid["videoId"]
                )
                other_start = vid_data["start_time"] / 1_000_000
                duration = vid_data.get("duration", 0)
                other_end = other_start + duration
                print(
                    f"Checking video {vid['videoId']} from {other_start} to {other_end}"
                )
                if other_start < clip_absolute_time - 36 * 60 * 60:
                    break
                if other_start <= clip_absolute_time:
                    offset = int(clip_absolute_time - other_start)
                    offset += clip_delay  # adjust for delay
                    if duration and offset > duration:
                        continue
                    return jsonify({
                        "other_stream_id": vid["videoId"],
                        "offset_seconds": int(offset),
                        "streamer_id": other_streamer_id,
                        "timestamp_url": f"https://youtu.be/watch?v={vid['videoId']}&t={offset}s"
                    })                
            except Exception as inner_e:
                print(f"Failed to process video {vid['videoId']}: {inner_e}")
                continue
    except Exception as outer_e:
        print(f"Error scraping channel for {other_streamer_id}: {outer_e}")
        return "Failed to fetch streams for other streamer", 500

    return "No matching POV found", 404

@app.route("/get_other_streamers", methods=["POST"])
def get_other_streamers():
    home_data = generate_home_data()
    # sort the streamers by their name
    streamers = sorted(home_data, key=lambda x: x["name"])
    return streamers

@app.route("/delete")
@app.route("/delete/")
@app.route("/delete/<clip_id>")
def delete(clip_id=None):
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    sub_detail = is_subscribed(channel_id)
    if not sub_detail:
        return f"Your free trial ended ☹. Get the subscription at {base_domain}/membership"
    if not clip_id:
        clips = get_channel_clips(channel_id)
        if not clips:
            return "No clips made on this channel. So can't delete the clip"
        clip_id = clips[0].id
    arguments = {k.replace("?", ""): request.args[k] for k in request.args}
    silent = arguments.get("silent", 2)  # silent level. if not then 2
    try:
        silent = int(silent)
    except ValueError:
        return "Silent level should be an integer"
    returning_str = ""
    errored_str = ""
    for c in clip_id.split(" "):
        try:
            clip = get_clip(c, channel_id)
        except ValueError:
            clip = None
        if not clip:
            errored_str += f" {c}"
            continue
        webhook_url = get_channel_settings(clip.channel).webhook
        if clip.delete(conn, webhook_url=webhook_url):
            returning_str += f" {c}"
        else:
            errored_str += f" {c}"
    if returning_str:
        returning_str = "Deleted clips with id" + returning_str
    if errored_str:
        errored_str = "Couldn't delete clips with id" + errored_str
    if silent == 0:
        return " "
    elif silent == 1:
        return returning_str
    else:
        return returning_str + errored_str


@app.route("/edit/")
@app.route("/edit")
@app.route("/edit/<clip_id>")
@app.route("/edit/<clip_id>/")
def edit(clip_id=None):
    if not clip_id:
        # in this case nothing is provided. not even clip ip not even new description
        return "No Clip ID or Description provided"
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    arguments = {k.replace("?", ""): request.args[k] for k in request.args}
    silent = arguments.get("silent", 2)  # silent level. if not then 2
    new_desc = " ".join(clip_id.split(" ")[1:])
    try:
        silent = int(silent)
    except ValueError:
        return "Silent level should be an integer"
    channel_id = channel.get("providerId")[0]
    sub_detail = is_subscribed(channel_id)
    if not sub_detail:
        return f"Your free trial ended ☹. Get the subscription at {base_domain}/membership"
    clip = get_clip(clip_id.split(" ")[0], channel_id)
    if not clip:
        # we are talking about last clip that was made from this channel in this case
        clips = get_channel_clips(channel_id)
        if not clips:
            return "No clips made on this channel. So can't edit the clip"
        clip = clips[0]
        new_desc = clip_id
        clip_id = clip.id
    old_desc = clip.desc
    webhook_url = get_channel_settings(clip.channel).webhook
    edited = clip.edit(new_desc, conn, webhook_url=webhook_url)
    if not edited:
        return "Couldn't edit the clip"
    if silent == 0:
        return " "
    elif silent == 1:
        return clip_id.split(" ")[0]
    else:
        return f"Edited clip {clip_id.split(' ')[0]} from title '{old_desc}' to '{new_desc}'"


@app.route("/search/<clip_desc>")
def search(clip_desc=None):
    # returns the first clip['url'] that matches the description
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    clip = get_clip_with_desc(clip_desc, channel.get("providerId")[0])
    level = request.args.get("level", 0)
    try:
        level = int(level)
    except ValueError:
        return "level should be an integer"
    if not clip:
        return "Clip not found"
    match level:
        case 0:
            return clip.stream_link
        case 1:
            return clip.id
        case 2:
            return f"{clip.desc} - {clip.stream_link}"
        case 3:
            return f"{clip.id} {clip.user_name} | {clip.desc} - {clip.stream_link}"
        case _:
            return clip.stream_link


@app.route("/searchx")
@app.route("/searchx/")
@app.route("/searchx/<clip_desc>")
def searchx(clip_desc=None):
    # returns the first clip['url'] that matches the description
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    clip = get_clip_with_desc(clip_desc, channel.get("providerId")[0])
    if clip:
        return clip.json()
    return "{}"


@app.route("/searchchannel")
@app.route("/searchchannel/")
@app.route("/searchchannel/<query>")
def searchchannel(query=None):
    if not query:
        return []
    answer = []
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id FROM QUERIES GROUP BY channel_id"""
        )
        data = cur.fetchall()
    channel_ids = [x[0] for x in data]
    for channel in channel_info:
        if channel not in channel_ids:
            continue  # we don't provide who don't have any clips
        if query.lower() in channel_info[channel]["name"].lower():
            answer.append(
                [
                    channel_info[channel]["name"],
                    url_for("channel_stats", channel_id=channel),
                ]
            )
    return answer


@app.route("/searchuser")
@app.route("/searchuser/")
@app.route("/searchuser/<query>")
def searchuser(query=None):
    if not query:
        return []
    answer = []
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT user_id, 
            user_name, 
            COUNT(*) AS row_count 
            FROM QUERIES 
            WHERE user_name LIKE ? 
            OR user_id LIKE ? 
            GROUP BY user_id, user_name;
            """,
            (f"%{query}%", f"%{query}%"),
        )
        data = cur.fetchall()
    for user in data:
        answer.append(
            [f"{user[1]} ({user[2]} clips)", url_for("user_stats", channel_id=user[0])]
        )
    return answer


@app.route("/extension/request_comment/<video_id>")
def request_comment(video_id: str = None):
    if not video_id:
        return "No video id provided"
    # if we already have comment we don't need to give it back
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT comment FROM QUERIES WHERE video_id = ?
            """,
            (video_id,),
        )
        data = cur.fetchall()
        if data:
            return (
                "Comment already existed. if you don't see it. then it was deleted or held in review.",
                200,
            )
    clips = get_video_clips(video_id)
    if not clips:
        return "No clips found for this video", 404
    string = prepare_comment_text(clips)
    try:
        post_comment(video_id, string)
    except:
        return "Failed to post comment", 500
    with conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO COMMENTS VALUES (?, ?, ?)",
            (video_id, string, int(time.time())),
        )
        conn.commit()
    return "Comment posted, Please refresh if you don't see it.", 200


@app.route("/extension/clips")
@app.route("/extension/clips/")
@app.route("/extension/clips/<video_id>")
def extension_clips(video_id=None):
    if not video_id:
        return {}
    clips = get_video_clips(video_id)
    return jsonify([clip.json() for clip in clips])


@app.route("/extension/channel/clips")
@app.route("/extension/channel/clips/")
@app.route("/extension/channel/clips/<stream_id>")
def extension_channel_clips(stream_id=None):
    if not stream_id:
        return {}
    clips = get_video_clips(stream_id)
    return jsonify([clip.json() for clip in clips])


@app.route("/extension/clip")
@app.route("/extension/clip/")
@app.route("/extension/clip/<clip_id>")
def extension_clip(clip_id=None):
    if not clip_id:
        return {}
    clip = get_clip(clip_id)
    return clip.json()


@app.route("/extension/channel")
@app.route("/extension/channel/")
@app.route("/extension/channel/<channel_id>")
def extension_channel(channel_id=None):
    if not channel_id:
        return {}
    clips = get_channel_clips(channel_id)
    return jsonify([clip.json() for clip in clips])


@app.route("/loaderio-2d4d6795c8021a56f6052f095f181fe8.txt")
@app.route("/loaderio-2d4d6795c8021a56f6052f095f181fe8.html")
@app.route("/loaderio-2d4d6795c8021a56f6052f095f181fe8/")
def loaderio():
    return "loaderio-2d4d6795c8021a56f6052f095f181fe8"


@app.route("/test")
def test():
    # test if we can still retrieve the live streams. main part of the bot
    try:
        ll = get_latest_live("UCaWd5_7JhbQBe4dknZhsHJg")
    except:
        return 500, "Failed"
    else:
        return ll["title"]


@app.route("/globals")
@login_required
def globals_():
    if not current_user.admin:
        flash("You are not an admin", "danger")
        return redirect(url_for("slash"))
    return dumps(globals(), indent=4, sort_keys=True, default=str)


@app.route("/video")
@app.route("/video/")
@app.route("/video/<clip_id>")
@login_required
def video(clip_id):
    if not clip_id:
        return redirect(url_for("slash"))
    clip = get_clip(clip_id)
    if not clip:
        return "Clip not found"
    # check if the person is the owner of the clip
    if not current_user.admin:
        if clip.channel != current_user.id:
            flash("You are not owner of this clip.", "warning")
            return redirect(f"/e/{clip.channel}")
    format = request.args.get("format", None)
    clip = get_clip(clip_id)
    if not clip:
        return 404, "Clip not found"
    download_and_store(clip_id=clip.id, format=format)
    if f"{clip.id}" not in [x.split(".")[0] for x in os.listdir("./clips")]:
        return "Couldn't download the clip"
    for file in os.listdir("./clips"):
        if file.startswith(clip.id) and "part" not in file:
            if format:
                if format in file:
                    return send_from_directory("clips", file)
            else:
                return send_from_directory("clips", file)

    return "Couldn't find the file"


@ext.register_generator
def index():
    yield "slash", {}
    channels = channel_info.values()
    # sort by channels['sub_count']
    channels = sorted(channels, key=lambda x: x["sub_count"], reverse=True)
    for channel in channels[:26]:  # only do top 26
        if "lofi" in channel["name"].lower():
            continue  # we have no association with lofigirl so lets not show them
        yield "channel_stats", {"channel_id": channel["username"]}
        yield "exports", {"channel_id": channel["username"]}
    yield "stats", {}
    yield "export", {}


channel_info = {}
if "channel_cache.json" in os.listdir("./helper"):
    try:
        with open("helper/channel_cache.json", "r", encoding="utf-8") as f:
            channel_info = load(f)
    except Exception as e:
        print(e)
        # delete the file just in case this doesn't happen again
        with open("helper/channel_cache.json", "w", encoding="utf-8") as f:
            dump({}, f, indent=4)
else:
    with open("helper/channel_cache.json", "w", encoding="utf-8") as f:
        dump({}, f, indent=4)


def write_channel_cache(channel_info=channel_info):
    with open("helper/channel_cache.json", "w", encoding="utf-8") as f:
        dump(channel_info, f, indent=4)
    return True


with conn:
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT channel_id FROM QUERIES ORDER BY time DESC")
    data = [d[0] for d in cur.fetchall()]

for ch_id in data:
    get_channel_name_image(ch_id)


# add default settings to everyone who is not in the settings table
def add_default_settings(channel_id: str):
    with conn:
        cur = conn.cursor()
        cur.execute(f"INSERT INTO settings(channel_id, webhook) VALUES(?, '')", (channel_id,))
        conn.commit()
    return True


with conn:
    cur = conn.cursor()
    cur.execute(f"SELECT * from settings")
    channels_in_settings = [x[0] for x in cur.fetchall()]
    for ch_id in data:
        if ch_id not in channels_in_settings:
            # add_default_settings(ch_id)
            pass


write_channel_cache(channel_info)
prefix_webhook = {}

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=80)
