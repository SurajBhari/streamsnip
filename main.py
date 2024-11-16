from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    send_file,
    session,
    jsonify,
    send_from_directory
)
import yagmail
import random
from requests import get as GET
from flask_cors import CORS
import dns.resolver, dns.reversename
from bs4 import BeautifulSoup
import subprocess
import os
import yt_dlp
from json import load, dump, loads, dumps
import time
from bs4 import BeautifulSoup
from requests import get
from flask import request
from discord_webhook import DiscordWebhook, DiscordEmbed
import sqlite3
from typing import Optional, Tuple, List
from flask_sitemap import Sitemap

from urllib import parse
from urllib.parse import parse_qs
import scrapetube
from chat_downloader.sites import YouTubeChatDownloader
from chat_downloader import ChatDownloader
import logging
from datetime import datetime, timedelta, timezone
import cronitor

from string import ascii_letters, digits
from helper.util import *
from helper.Clip import Clip, time_since 
from helper.UserSettings import UserSettings

# we are in /var/www/streamsnip
import os

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
except FileNotFoundError:
    print("Config file not found")
    exit(1)

try:
    cronitor.api_key = config["cronitor_api_key"]
except FileNotFoundError:
    cronitor.api_key = None
    

if not local:
    monitor = cronitor.Monitor.put(key="Streamsnip-Clips-Performance", type="job")
else:
    monitor = None


app = Flask(__name__)
app.secret_key = os.environ.get("WSGISecretKey", "supersecretkey") # if we are running on apache we have a WSGISecretKey, its not really secret.
CORS(app)
ext = Sitemap(app=app)

global download_lock
download_lock = True
global DEFAULT_SETTINGS
DEFAULT_SETTINGS = UserSettings()
conn = sqlite3.connect("queries.db", check_same_thread=False)
# cur = db.cursor() # this is not thread safe. we will create a new cursor for each thread
owner_icon = "👑"
mod_icon = "🔧"
regular_icon = "🧑‍🌾"
subscriber_icon = "⭐"
allowed_ip = [
    "127.0.0.1",
    "52.15.46.178",
]  # store the nightbot ips here. or your own ip for testing purpose
show_fake_error = False # for blacklisted channel show fake error message or not 
requested_myself = (
    False  # on startup we request ourself so that apache build the cache.
)
base_domain = (
    "https://streamsnip.com"  # just for the sake of it. store the base domain here
)
chat_id_video = {}  # store chat_id: vid. to optimize clip command
downloader_base_url = "https://azure-internal-verse.glitch.me"
project_name = "StreamSnip"
project_logo = base_domain + "/static/logo.png"
project_repo_link = "https://github.com/SurajBhari/streamsnip"
project_logo_discord = "https://raw.githubusercontent.com/SurajBhari/streamsnip/main/static/256_discord_ss.png" # link to logo that is used in discord 

if "cookies.txt" in os.listdir("./helper"):
    cookies = "./helper/cookies.txt"
else:
    cookies = None

if "youtubeemoji.json" in os.listdir("./helper"):
    with open("./helper/youtubeemoji.json", "r", encoding="utf-8") as f:
        emoji_lookup_table = load(f)
else:
    emoji_lookup_table = {}

def is_it_expired(t:int): # we add some randomness so that not all of the cache get invalidated and added back at same time. 
    if local:
        return False # we don't need to expire the cache we have for testing purposes
    three_days_ago = int(time.time()) - 3 * 24 * 60 * 60
    last_time = three_days_ago + random.randint(0, 48) * 60 * 60
    if t < last_time:
        return True
    return False

def get_creds():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            jcreds = load(f)
            creds = jcreds['creds']
            creds['password'] = jcreds['password']  
    except (FileNotFoundError, KeyError):
        creds = {}
    return creds

def write_creds(new_creds:dict):
    if not new_creds:
        return
    # load the config as whole and then update the creds
    with open("config.json", "r", encoding="utf-8") as f:
        config = load(f)
    config['creds'] = new_creds
    with open("config.json", "w", encoding="utf-8") as f:
        dump(config, f, indent=4)
    return True

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
    cur.execute("""
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
        )""")
    conn.commit()

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
    return UserSettings(list(data))

# if there is no folder named clips then make one
if not os.path.exists("clips"):
    os.makedirs("clips")
    print("Created clips folder")

try:
    creds = config['creds']
except KeyError:
    creds = {}
    config['creds'] = creds

def is_blacklisted(channel_id):
    try:
        with open("blacklisted.json", "r", encoding="utf-8") as f:
            data = load(f)
    except FileNotFoundError:
        data = []
    return channel_id in data

def get_clip(clip_id, channel=None) -> Optional[Clip]:
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
    if not data:
        return None
    x = Clip(data[0])
    return x

def get_video_clips(video_id) ->  List[Optional[Clip]]:
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM QUERIES WHERE stream_link like ?", (f"%{video_id}%",)
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
            cur.execute(f"select * from QUERIES where channel_id=?", (channel_id,))
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


def get_channel_name_image(channel_id: str) -> Tuple[str, str]:
    if channel_id in channel_info:
        if "last_updated" not in channel_info[channel_id]:
            channel_info[channel_id]["last_updated"] = 0 # forcing to outdate the value so that it gets updated
        if "sub_count" not in channel_info[channel_id]:
            channel_info[channel_id]["last_updated"] = 0 # forcing to outdate the value so that it gets updated
        if is_it_expired(channel_info[channel_id]["last_updated"]):
            del channel_info[channel_id]
            return get_channel_name_image(channel_id)
        try:
            return channel_info[channel_id]["name"], channel_info[channel_id]["image"]
        except Exception as e:
            logging.log(logging.ERROR, e)
    
    channel_link = f"https://youtube.com/channel/{channel_id}"
    response = get(channel_link)
    if response.status_code != 200:
        # don't store anything. just for this instance return the default values. can be youtube side issue too
        return "<deleted channel>", "https://yt3.googleusercontent.com/a/default-user=s100-c-k-c0x00ffffff-no-rj"
        
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
            sub_count = yt_initial_data['header']['pageHeaderRenderer']['content']['pageHeaderViewModel']['metadata']['contentMetadataViewModel']['metadataRows'][1]['metadataParts'][0]['text']['content']
            sub_count = convert_sub_count(sub_count)
        except:
            sub_count = 0
        try:
            channel_username = yt_initial_data['metadata']['channelMetadataRenderer']['vanityChannelUrl'].split("/")[-1]
        except KeyError:
            return channel_name, channel_image # stop caring abot channel username and putting it to cache 
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
        "sub_count": sub_count
    }
    # write channel_info to channel_cache.json
    write_channel_cache(channel_info)
    
    return channel_name, channel_image

def convert_sub_count(sub_count:str) -> int:
    sub_count = sub_count.split(" ")[0]
    sub_count = sub_count.upper()
    if "K" in sub_count:
        sub_count = sub_count.replace("K", "")
        sub_count = float(sub_count) * 1000
    elif "M" in sub_count:
        sub_count = sub_count.replace("M", "")
        sub_count = float(sub_count) * 1000000
    elif "B" in sub_count: # lmao like this is ever gonna happen xd 
        sub_count = sub_count.replace("B", "")
        sub_count = float(sub_count) * 1000000000 
    else:
        sub_count = int(sub_count)
    return int(sub_count)


def take_screenshot(video_url: str, seconds: int) -> str:
    # Get the video URL using yt-dlp
    params = {
        'forceurl': True,
        'format':   'bestvideo',
        'noprogress': True,
        'quiet': True,
        'simulate': True,
    }
    if cookies:
        params['cookiesfile'] = cookies

    with yt_dlp.YoutubeDL(params) as ydl:
        video_info = ydl.extract_info(video_url, download=False)
    
    # Remove leading/trailing whitespace and newline characters from the video URL
    video_url = video_info['url']
    file_name = "ss.jpg"
    r = GET(video_url, cookies=cookies)
    if r.status_code != 200:
        return None
    index = 'index.m3u8'
    with open(index, "wb") as f:
        f.write(r.content)
        
    # Think Think 
    # FFmpeg command
    ffmpeg_command = [
        "ffmpeg",
        "-protocol_whitelist",
        "file,http,https,tcp,tls,crypto",  # Protocol whitelist
        "-y",  # say yes to prompts
        "-ss",
        str(seconds),  # Start time
        "-i",
        index,  # Input video URL
        "-vframes",
        "1",  # Number of frames to extract (1)
        "-q:v",
        "2",  # Video quality (2)
        "-hide_banner",  # Hide banner
        "-loglevel",
        "error",  # Hide logs
        file_name,  # Output image file
    ]

    try:
        subprocess.run(ffmpeg_command, check=True)
    except subprocess.CalledProcessError as e:
        print("Error:", e)
        exit(1)

    return file_name


def get_clip_with_desc(clip_desc: str, channel_id: str) -> Optional[Clip]:
    clips = get_channel_clips(channel_id)
    for clip in clips:
        if clip_desc.lower() in clip.desc.lower():
            return clip
    return None


def download_and_store(clip_id, format:str = None) -> str:
    with conn:
        cur = conn.cursor()
        data = cur.execute(
            "SELECT * FROM QUERIES WHERE  message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
            (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
        )
        data = cur.fetchall()
    if not data:
        return None
    clip = Clip(data[0])
    video_url = clip.stream_link
    timestamp = clip.time_in_seconds
    output_filename = f"./clips/{clip_id}"
    # if there is a file that start with that clip in current directory then don't download it
    for file in os.listdir("./clips"):
        if format:
            if file.startswith(clip_id) and file.endswith(format):
                return file
        else:
            if file.startswith(clip_id):
                return file
    # real thing happened at 50. but we stored timestamp with delay. take back that delay
    delay = clip.delay
    timestamp += -1 * delay
    if not delay:
        delay = -60
    l = [timestamp, timestamp + delay]
    start_time = min(l)
    end_time = max(l)
    params = {
        "cookiefile": cookies,
        "download_ranges": yt_dlp.utils.download_range_func(
            [], [[start_time, end_time]]
        ),
        "match_filter": yt_dlp.utils.match_filter_func(
            "!is_live & live_status!=is_upcoming & availability=public"
        ),
        "no_warnings": True,
        "noprogress": True,
        "outtmpl": {"default": output_filename},
        "overwrites": True,
        "silent": True,
    }
    if format:
        params["final_ext"] = format
        params['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]
    with yt_dlp.YoutubeDL(params) as ydl:
        try:
            ydl.download([video_url])
        except yt_dlp.utils.DownloadError as e:
            print(e)
            return  # this video is still live. we can't download it
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
        todays_clips = cur.execute("SELECT * FROM QUERIES WHERE time >= ? AND private is not '1'", (today,))
        todays_clips = todays_clips.fetchall()
        today_count = len(todays_clips)
        last_clip = None
        if today_count:
            last_clip = Clip(todays_clips[-1]).json()
    return dict(today_count=today_count, last_clip=last_clip)



@app.before_request
def before_request():
    # if request is for /clip or /delete or /edit then check if its from real
    if "/clip" in request.path or "/delete" in request.path or "/edit" in request.path:
        if "/extension/" in request.path: # make an exception for all the /extension routes
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
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, ValueError, dns.resolver.LifetimeTimeout, dns.resolver.NoNameservers):
            return f"You are not Nightbot. are you ?, your ip {ip}"
        else:
            # print(f"Request from {ip} is allowed")
            allowed_ip.append(ip)
    else:
        pass

@app.route("/cache")
def cache():
    return dumps(channel_info, indent=4)

@app.route("/mini_stats")
def mini_stats_r():
    if request.args.get("home") == "true":
        ms = mini_stats()
        ms['data'] = generate_home_data()
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
        cur.execute(f"SELECT *, COUNT(*) AS channel_count, MIN(time) AS first_clip_time FROM QUERIES WHERE private is not '1' GROUP BY channel_id ORDER BY MAX(time) DESC;")
        data = cur.fetchall()
    returning = []
    for clip in data:
        ch = {} 
        channel_name, channel_image = get_channel_name_image(clip[0])
        ch["image"] = channel_image
        ch["name"] = channel_name
        try:
            ch['sub_count'] = channel_info[clip[0]]['sub_count']
        except KeyError:
            ch['sub_count'] = 0
        ch["id"] = clip[0]
        ch["image"] = channel_image.replace(
            "s900-c-k-c0x00ffffff-no-rj", "s300-c-k-c0x00ffffff-no-rj"
        )
        ch["last_clip"] = Clip(clip).json()
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        ch["link"] = f"{htt}{request.host}{url_for('exports', channel_id=get_channel_at(clip[0]))}"
        ch['clip_count'] = clip[-2]
        ch['first_clip_time'] = clip[-1]
        ch['first_clip_timesince'] = time_since(datetime.fromtimestamp(clip[-1], tz=timezone.utc))
        ch['deleted'] = True if "deleted channel" in channel_name else False
        if ch['deleted']:
            ch['link'] = f"{htt}{request.host}{url_for('exports', channel_id=get_channel_id_any(clip[0]))}" # we can't get channel @ as its a deleted channel
        #ch["last_clip"] = get_channel_clips(ch_id[0])[0].json()
        returning.append(ch)
    return returning

@app.route("/channels")
def channels():
    returning = generate_home_data()
    return render_template("channels.html", data=returning)
@app.route("/")
def slash():
    returning = generate_home_data()
    return render_template("home.html", data=returning)

@app.route("/")
@app.route("/data")
def data():
    return "Disabled"
    clips = get_channel_clips()
    clips = [x.json() for x in clips]
    return clips

@app.route("/session", methods=["GET"])
def session_data():
    if session:
        return dumps(session, indent=4)
    else:
        return "No session data"
    
@app.route("/login", methods=["POST", "GET"])
def login():
    if request.method == "POST":
        # set cookies to this password
        creds = get_creds()
        for cred in creds:
            if creds[cred] == request.form["password"]:
                session["password"] = request.form["password"]
                if cred == "password":
                    session["admin"] = True
                    session["username"] = "admin"
                    session["image"] = "https://images.freeimages.com/fic/images/icons/2526/bloggers/256/admin.png?fmt=webp&h=350"
                    session['id'] = "admin"
                else:
                    username, image = get_channel_name_image(cred)
                    session["username"] = username
                    session["image"] = image
                    session["id"] = cred
                session['logged_in'] = True
                return redirect(url_for("slash"))
        return render_template("login.html", msg="INVALID PASSWORD")
    return render_template("login.html", msg="Password is the webhook URL that you are using for your channel.")

@app.route("/logout", methods=["POST", "GET"]) 
def logout():
    session.clear()
    return redirect(url_for("slash"))

@app.route("/webedit", methods=["POST"])
def webedit():
    try:
        new_message = request.json["message"]
        clip_id = request.json["clip_id"]
    except KeyError:
        return "Invalid request", 400
    if not session.get("logged_in"):
        return "Not logged in", 401
    clip = get_clip(clip_id=clip_id)
    
    if not clip:
        return "Clip not found", 404
    # compare the password of the session against the creds to verify legitmacy of the request
    creds = get_creds()

    try:
        if creds["password"] == session["password"]: # for admin
            pass
        elif creds[clip.channel] == session["password"]:
            pass
        else:
            return "Invalid password" , 401
    except KeyError:
        return "Invalid Key" , 401
        

    clip.edit(new_message, conn)
    
    return clip.desc, 200


@app.route("/webdelete", methods=["POST"])
def webdelete():
    try:
        clip_id = request.json["clip_id"]
    except KeyError:
        return "Invalid request", 400
    if not session.get("logged_in"):
        return "Not logged in", 401
    clip = get_clip(clip_id=clip_id)
    if not clip:
        return "Clip not found", 404
    # compare the password of the session against the creds to verify legitmacy of the request
    creds = get_creds()

    try:
        if creds["password"] == session["password"]: # for admin
            pass
        elif creds[clip.channel] == session["password"]:
            pass
        else:
            return "Invalid password" , 401
    except KeyError:
        return "Invalid Key" , 401

    clip.delete(conn)
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

@app.route("/settings/default", methods=["POST"])
def default_settings():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if not session.get("id"):
        return redirect(url_for("login"))
    settings = UserSettings()
    settings.channel_id = session["id"]
    if not settings.write(conn):
        return "Failed to write settings", 500
    return "OK", 200

@app.route("/settings" , methods=["POST", "GET"])
def settings():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if not session.get("id"):
        return redirect(url_for("login"))
    settings = get_channel_settings(session["id"])
    if request.method == "POST":
        settings.show_link = request.json.get("show_link")
        settings.screenshot = request.json.get("screenshot")
        settings.delay = request.json.get("delay")
        settings.force_desc = request.json.get("force_desc")
        settings.silent = request.json.get("silent")
        settings.private = request.json.get("private")
        settings.webhook = request.json.get("webhook")
        settings.message_level = request.json.get("message_level")
        settings.take_delays = request.json.get("take_delays")
        
        if not settings.write(conn):
            return "Failed to write settings", 500
        return "OK", 200
    return render_template("settings.html", session=session, settings=settings)
    

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
def clips():
    data = get_channel_clips()
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
                clip['discord_url'] = f"{prefix_webhook[clip['channel']]}/{clip['discord']['webhook']}"""
        clip['discord_url'] = "#a" # we don't want to do it for all clips. cuz its slowwwww
    return render_template(
        "export.html",
        data=data,
        clips_string=create_simplified(data),
        channel_name="All channels",
        channel_image="https://streamsnip.com/static/logo-grey.png",
        owner_icon=owner_icon,
        mod_icon=mod_icon,
        regular_icon=regular_icon,
        subscriber_icon=subscriber_icon,
        channel_id="all",
        emoji_lookup_table=emoji_lookup_table
    )

def get_channel_id_any(hint): # returns the UC id of the channel 
    if hint.startswith("UC"):
        return hint # already a channel id
    if hint.startswith("@"):
        available = [x for x in channel_info if channel_info[x].get("username") == hint]
        if available:
            return available[0]
    available = [x for x in channel_info if channel_info[x].get("name") == hint]
    if available:
        return available[0]
    available = [x for x in channel_info if hint.lower() in channel_info[x].get("name").lower()]
    if available:
        return available[0]
    return None
    
    

def get_channel_at(channel_id): # returns the @username of the channel
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
    get_channel_name_image(channel_id) # this will just come back if there is already a channel_id. 
    channel = channel_info.get(channel_id)
    if not channel:
        return channel_id
    return channel["username"]

        
# this is for specific channel
@app.route("/exports/<channel_id>")
@app.route("/e/<channel_id>")
def exports(channel_id=None):
    channel_id = get_channel_id_any(channel_id)
    if not channel_id:
        return redirect(url_for("slash")) # not found
    try:
        channel_name, channel_image = get_channel_name_image(channel_id)
    except Exception as e:
        print(e)
        return redirect(url_for("slash"))
    data = get_channel_clips(channel_id)
    data = [x.json() for x in data if not x.private]
    for clip in data:
        if clip['discord']['webhook']:
            if clip['channel'] in prefix_webhook and prefix_webhook.get(clip['channel']) is not None:
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
                clip['discord_url'] = f"{prefix_webhook[clip['channel']]}/{clip['discord']['webhook']}"
        else:
            clip['discord_url'] = "#"
    return render_template(
        "export.html",
        data=data,
        clips_string=create_simplified(data),
        channel_name=channel_name,
        channel_image=channel_image,
        owner_icon=owner_icon,
        mod_icon=mod_icon,
        regular_icon=regular_icon,
        subscriber_icon=subscriber_icon,
        channel_id=get_channel_at(channel_id),
        emoji_lookup_table=emoji_lookup_table
    )


@app.route("/channelstats/<channel_id>")
@app.route("/cs/<channel_id>")
@app.route("/channelstats")
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
    most_clipped_streams = {} # stream_link: count
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
        search_route="/searchchannel",
        search_for = "channel",
    )

@app.route("/timestats/<start>/<end>")
@app.route("/ts/<start>/<end>")
@app.route("/timestats/<start>/")
@app.route("/ts/<start>/")
@app.route("/timestats/")
@app.route("/ts/")
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
        cur.execute("SELECT * FROM QUERIES WHERE private is not '1' AND time >= ? AND time < ?", (start.timestamp(), end.timestamp(),))
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
    user_clips["Others"] = sum(list(_user_clips.values())[max_count-1:])
    if user_clips["Others"] == 0:
        user_clips.pop("Others")
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    notes = {
        k:  v
        for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
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
            if temp_start.strftime("%Y-%m-%d %H") not in streamer_trend_data[channel_id]:
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
    
    #streamers_trend_days.sort()
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
    new_dict['Others'] = {}
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
        (start.timestamp(), end.timestamp(),),
    )
    mcs = cur.fetchall()
    most_clipped_streams = {} # stream_link: count
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
        channel_image="https://streamsnip.com/static/logo-grey.png",
        most_clipped_streams=most_clipped_streams,
        best_days={},
        search_route=None,
        search_for = None,
    )

@app.route("/userstats/<channel_id>")
@app.route("/us/<channel_id>")
@app.route("/userstats")
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
        (channel_id,)
    )
    mcs = cur.fetchall()
    most_clipped_streams = {} # stream_link: count
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
        search_route = "/searchuser",
        search_for = "user",
    )


@app.route("/stats")
def stats():
    # get clips
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM QUERIES WHERE private is not '1'")
        data = cur.fetchall()
    clips = []
    today = datetime.today()
    today = today.replace(hour=0, minute=0, second=0, microsecond=0)
    three_months_ago = (today - timedelta(days=28)).timestamp()
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
    user_clips["Others"] = sum(list(_user_clips.values())[max_count-1:])
    if user_clips["Others"] == 0:
        user_clips.pop("Others")
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    notes = {
        k:  v
        for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
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
            continue # we don't need to show old data
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
    new_dict['Others'] = {}
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
    most_clipped_streams = {} # stream_link: count
    for x in mcs:
        most_clipped_streams[get_video_id(x[0])] = x[1]
    message = f"{user_count} users clipped\n{clip_count} clips on \n{channel_count} channels till now. \nand counting."
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
        channel_name="All channels",
        channel_image="https://streamsnip.com/static/logo-grey.png",
        most_clipped_streams=most_clipped_streams,
        best_days=best_days,
        search_route = "/searchchannel",
        search_for = "channel",
    )


@app.route("/admin")
def admin():
    clips = get_channel_clips()
    t = time.time()
    clip_ids = [x.id for x in clips]
    t = time.time()
    creds = get_creds()
    channel_info_admin = {}
    for key, value in creds.items():
        get_channel_name_image(key)
        try:
            channel_info_admin[key] = channel_info[key]
        except KeyError:
            continue
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        channel_info_admin[key][
            "link"
        ] = f"{htt}{request.host}{url_for('exports', channel_id=key)}"
    return render_template("admin.html", ids=clip_ids, channel_info=channel_info_admin)

def get_channel_id(path):
    html_data = get(path).text
    soup = BeautifulSoup(html_data, "html.parser")
    identifier = soup.find('meta', itemprop="identifier")
    if not identifier:
        return None
    channel_id = identifier['content']
    return channel_id

@app.route("/autoapprove")
def autoapprove():
    # verify if the entry is eligible to be autoapproved i.e there have been no previous creds. 
    key = request.args.get("key")
    value = request.args.get("value")
    if not any([key, value]):
        return "Key or Value not found"
    channel_id = get_channel_id(key)
    email = request.args.get("email")

    if "youtube.com" not in key:
        return f"Key isn't of youtube {key}"
    if "discord.com/api/webhooks" not in value:
        return f"Value isn't of discord webhook {value}"
    if not channel_id:
        return "Channel id not found"
    
    creds = get_creds()
    if channel_id in creds:
        return "Channel already has a webhook, can't auto-approve"
    password = config['password']
    request.args = {"pass": password, "key": key, "value": value, "email": email}
    return approve()



@app.route("/approve")
def approve():
    # this is in format of https://streamsnip.com/approve?pass=somepassword&key=https://www.youtube.com/channel/UC5IRLz3Q-SADL71-sW-Z16Q&value=https://discord.com/api/webhooks/51313123122515125/sadfasdasd12rasfafase-VOkUSVo4clrbXSh6Mpa
    password = request.args.get("pass")
    key = request.args.get("key")
    value = request.args.get("value")
    applier_email = request.args.get("email")
    
    value = value.replace("discordapp.com", "discord.com")

    if password != config['password']:
        return "Wrong password"
    if "youtube.com" not in key:
        return f"Key isn't of youtube {key}"
    if "discord.com/api/webhooks" not in value:
        return f"Value isn't of discord webhook {value}"

    channel_id = get_channel_id(key)
    if not channel_id:
        return "Channel id not found"

    creds = get_creds()
    creds[channel_id] = value
    write_creds(creds)

    channel_name, channel_image = get_channel_name_image(channel_id)
    webhook = DiscordWebhook(url=value, username=project_name, avatar_url=project_logo_discord)
    embed = DiscordEmbed(
        title=f"Welcome to {project_name}!", 
        description=f"I will send clips for {channel_name} here",
        )
    embed.add_embed_field(name="Add Nightbot command", value=f"If you haven't already. add Nightbot commands from [github]({project_repo_link}) .")
    embed.set_thumbnail(url=project_logo_discord)
    embed.set_color(0xebf0f7)
    webhook.add_embed(embed)
    response = webhook.execute()
    if response.status_code != 200:
        return response.text

    if "update_webhook" in config:
        webhook = DiscordWebhook(url=config["update_webhook"], username=project_name, avatar_url=project_logo_discord)
        embed = DiscordEmbed(
            title=f"New webhook added",
            description=f"New webhook added for {channel_name}",
        )
        embed.set_thumbnail(url=channel_image)
        embed.set_color(0xebf0f7)
        webhook.add_embed(embed)
        webhook.execute()
    email = config.get("smtp", None)
    if email and applier_email:
        send_email(applier_email, f"Welcome to {project_name}! I will send clips for {channel_name} on your discord channel. If you haven't already, add Nightbot commands from [github]({project_repo_link}?tab=readme-ov-file#nightbot-command) .\n\n\n\nBest Of Luck\n{project_name}")
    return "Done"

def send_email(email=None, message="New webhook added"):
    try:
        user = config['smtp']['auth']['user']
        if not user:
            raise KeyError
    except KeyError:
        return "Email not configured"
    smtp = config['smtp']
    host = smtp['host']
    port = smtp['port']
    password = smtp['auth']['pass']
    if not all([host, port, password]):
        return "Email not configured"
    try:
        yag = yagmail.SMTP(user=user, password=password, host=host, port=port)
        yag.send(to=email, subject=f"Welcome to {project_name}!", contents=message)
    except Exception as e:
        return str(e)
    return "Email sent"

    
@app.route("/ed", methods=["POST"])
def edit_delete():
    actual_password = config['password']
    if not actual_password:
        return "Password not set"
    password = request.form.get("password")
    if password != actual_password:
        return "Invalid password"
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
        clip.edit(new_name, conn)
        return "Edited"

    elif request.form.get("delete") == "Delete":
        if not request.form.get("clip", None):
            return "No Clip selected"
        # delete the clip
        clip = get_clip(clip_id)
        if not clip:
            return "Clip not found"
        clip.delete(conn)
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
        write_creds(creds)

        channel_name, channel_image = get_channel_name_image(key)
        if value.startswith("https://discord"):
            webhook = DiscordWebhook(url=value, username=project_name, avatar_url=project_logo_discord)
            embed = DiscordEmbed(
                title=f"Welcome to {project_name}!", 
                description=f"I will send clips for {channel_name} here",
                )
            embed.add_embed_field(name="Add Nightbot command", value=f"If you haven't already. add Nightbot commands from [github]({project_repo_link}?tab=readme-ov-file#nightbot-command) .")
            embed.set_thumbnail(url=project_logo_discord)
            embed.set_color(0xebf0f7)
            webhook.add_embed(embed)
            webhook.execute()
        if "update_webhook" in config:
            webhook = DiscordWebhook(url=config["update_webhook"], username=project_name, avatar_url=project_logo_discord)
            embed = DiscordEmbed(
                title=f"New webhook added",
                description=f"New webhook added for {channel_name}",
            )
            embed.set_thumbnail(url=channel_image)
            embed.set_color(0xebf0f7)
            webhook.add_embed(embed)
            webhook.execute()
        return jsonify(creds)
    elif request.form.get("show") == "show":
        return jsonify(get_creds())
    elif request.form.get("refresh") == "refresh cache":
        global channel_info
        channel_info = {} # set channel_info to empty
        write_channel_cache(channel_info)
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
def add():
    if request.method == "GET":
        return render_template(
            "add.html", link="enter link", desc="!clip", password="password"
        )
    else:
        data = request.form
        if data.get("new") == "Submit":
            link = data.get("link", None)
            desc = data.get("command", None)
            if not desc:
                desc = "!clip"
            password = data.get("password", None)
            if not link or not password:
                return "Link/command/password not found"
            vid_id = get_video_id(link)
            if not vid_id:
                return "Invalid link"
            vid = YouTubeChatDownloader(cookies=cookies).get_video_data(video_id=vid_id)
            streamer_id = vid["author_id"]
            if not password == get_webhook_url(streamer_id):
                return "Invalid password"
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
                for chat in ChatDownloader().get_chat(vid_id):
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
            return render_template(
                "add.html", link=link, desc=desc, password=password, chats=right_chats
            )
        else:
            # second time
            link = data.get("link", None)
            vid_id = get_video_id(link)
            delay = data.get("delay")
            if not delay:
                delay = 0
            vid = YouTubeChatDownloader(cookies=cookies).get_video_data(video_id=vid_id)
            password = data.get("password", None)
            streamer_id = vid["author_id"]
            if not password == get_webhook_url(streamer_id):
                return "Invalid password"
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
        return string[:256] # youtube limits to 256 characters. who are we to disobey
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
            break # this is cause the clips are sorted by time. so if we find a clip that is not of this stream. we can break and save time
    
    percentage = (user_clip_count / total_clips) * 100 
    percentage = round(percentage, 2)
    today_count_string = f" ({this_stream_count} today)" if this_stream_count != 0 else f""
    return f"{total_clips} clips have been made {today_count_string} by total {total_users} users, out of which {user_clip_count} clips ({percentage}%) have been made by you."

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
    user_id = user.get("providerId")[0]
    user_name = user.get("displayName")[0]

    arguments = {k.replace("?", ""): request.args[k] for k in request.args}


    channel_settings = get_channel_settings(channel_id)
    show_link = arguments.get("showlink", channel_settings.show_link)
    screenshot = arguments.get("screenshot", channel_settings.screenshot)
    silent = arguments.get("silent", channel_settings.silent)  # silent level. if not then 2
    private = arguments.get("private", channel_settings.private)
    webhook = arguments.get("webhook", channel_settings.webhook)
    if webhook and not webhook.startswith("https://discord.com/api/webhooks/"):
        webhook = f"https://discord.com/api/webhooks/{webhook}"
    webhook_url = get_webhook_url(channel_id) if not webhook else webhook

    take_delays = arguments.get("take_delays", channel_settings.take_delays)
    force_desc = arguments.get("force_desc", channel_settings.force_desc)
    delay = arguments.get("delay", channel_settings.delay)
    message_level = arguments.get(
        "message_level", channel_settings.message_level
    )  # 0 is normal. 1 is to persist the defautl webhook name. 2 is for no record on discord message. 3 is for service badging
    try:
        message_level = int(message_level)
    except ValueError:
        message_level = DEFAULT_SETTINGS.message_level
    logging.log(
        level=logging.INFO,
        msg=f"A request for clip with arguments {arguments} and headers {request.headers}",
    )
    if webhook and not webhook.startswith("https://discord.com/api/webhooks/"):
        webhook = f"https://discord.com/api/webhooks/{webhook}"
    try:
        silent = int(silent)
    except ValueError:
        silent = DEFAULT_SETTINGS.silent
    
    show_link = False if show_link == "false" else show_link
    screenshot = True if screenshot == "true" else screenshot
    private = True if private == "true" else private
    take_delays = True if take_delays == "true" else take_delays
    force_desc = True if force_desc == "true" else force_desc
    
    if type(show_link) != bool:
        try:
            show_link = int(show_link)
        except ValueError:
            show_link = DEFAULT_SETTINGS.show_link
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
        return "No message id provided, You have configured it wrong. please contact AG at https://discord.gg/2XVBWK99Vy"
    
    
    
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

    if len(clip_desc) > 30:
        t_clip_desc = clip_desc[:30] + "..."
    else:
        t_clip_desc = clip_desc
    if t_clip_desc != "None":
        message_to_return = f"Clip {clip_id} by {user_name} -> '{t_clip_desc}' "
    else:
        message_to_return = f"Clip {clip_id} by {user_name} "
    if delay:
        message_to_return += f" Delayed by {delay} seconds."
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
            return "Error in sending message to discord. Perhaps the webhook is invalid. Please contant AG at https://discord.gg/2XVBWK99Vy"
        webhook_id = webhook.id  
        if show_link == 1: # we don't need to get webhook details if its not needed (optimization)
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
    except:
        ss_id = None
        ss_link = None
        message_to_return += " Couldn't take screenshot."
    

    if show_link is True:
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        show_link_message = f" See all clips at {htt}{request.host}{url_for('exports', channel_id=get_channel_at(channel_id))}"

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
        return message_to_return
    elif silent == 1:
        return clip_id
    else:
        return " "


@app.route("/delete/<clip_id>")
def delete(clip_id=None):
    if not clip_id:
        return "No Clip ID provided"
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
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
        if clip.delete(conn):
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


@app.route("/edit/<xxx>")
def edit(xxx=None):
    if not xxx:
        return "No Clip ID provided"
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    if len(xxx.split(" ")) < 2:
        return "Please provide clip id and new description"
    arguments = {k.replace("?", ""): request.args[k] for k in request.args}
    silent = arguments.get("silent", 2)  # silent level. if not then 2
    clip_id = xxx.split(" ")[0]
    new_desc = " ".join(xxx.split(" ")[1:])
    try:
        silent = int(silent)
    except ValueError:
        return "Silent level should be an integer"
    channel_id = channel.get("providerId")[0]
    clip = get_clip(clip_id, channel_id)
    old_desc = clip.desc
    if not clip:
        return "Clip ID not found"
    edited = clip.edit(new_desc, conn)
    if not edited:
        return "Couldn't edit the clip"
    if silent == 0:
        return " "
    elif silent == 1:
        return clip_id
    else:
        return (
            f"Edited clip {clip_id} from title '"
            + old_desc
            + "' to '"
            + new_desc
            + "'."
        )


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
            continue # we don't provide who don't have any clips 
        if query.lower() in channel_info[channel]['name'].lower():
            answer.append([channel_info[channel]['name'], url_for("channel_stats", channel_id=channel)])
    return answer

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
            """
            , (f"%{query}%", f"%{query}%")
        )
        data = cur.fetchall()
    for user in data:
        answer.append([f"{user[1]} ({user[2]} clips)", url_for("user_stats", channel_id=user[0])])
    return answer


@app.route("/extension/clips/<video_id>")
def extension_clips(video_id):
    clips = get_video_clips(video_id)
    return jsonify([clip.json() for clip in clips])

@app.route("/extension/channel/clips/<stream_id>")
def extension_channel_clips(stream_id):
    with conn:
        cur = conn.cursor()
        # stream_link must contain the stream_id
        cur.execute(
            """
            SELECT * FROM QUERIES WHERE stream_link LIKE ?;
            """,
            (f"%{stream_id}%",),
        )
        data = cur.fetchall()
    return ([Clip(x).json() for x in data])

@app.route("/extension/clip/<clip_id>")
def extension_clip(clip_id):
    clip = get_clip(clip_id)
    return clip.json()

@app.route("/extension/channel/<channel_id>")
def extension_channel(channel_id):
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
        return ll['title']

@app.route("/globals")
def globals_():
    given_pass = request.args.get("password")
    if (not given_pass) or given_pass != config['password']:
        return "Wrong password or no password"
    else:
        return dumps(globals(), indent=4, sort_keys=True, default=str)

@app.route("/video/<clip_id>")
def video(clip_id):
    if not clip_id:
        return redirect(url_for("slash"))
    creds = get_creds()
    clip = get_clip(clip_id)
    format = request.args.get("format", None)
    try:
        if creds["password"] == session["password"]: # for admin
            pass
        elif creds[clip.channel] == session["password"]:
            pass
        else:
            return redirect("/login")
    except KeyError:
        return redirect("/login")

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
    # Not needed if you set SITEMAP_INCLUDE_RULES_WITHOUT_PARAMS=True\
    yield "slash", {}
    with conn:
        cur = conn.cursor()
        cur.execute(f"SELECT channel_id FROM QUERIES ORDER BY time DESC")
        data = cur.fetchall()
    for channel in set([x[0] for x in data]):
        yield "channel_stats", {"channel_id": channel}
        yield "exports", {"channel_id": channel}

    yield "clips", {}
    yield "stats", {}


channel_info = {}
if 'channel_cache.json' in os.listdir('./helper'):
    try:
        with open("helper/channel_cache.json","r", encoding="utf-8") as f:
            channel_info = load(f)
    except Exception as e:
        print(e)
        # delete the file just in case this doesn't happen again
        with open("helper/channel_cache.json","w", encoding="utf-8") as f:
            dump({}, f, indent=4)
else:
    with open("helper/channel_cache.json","w", encoding="utf-8") as f:
        dump({}, f, indent=4) 

        
def write_channel_cache(channel_info=channel_info):
    with open("helper/channel_cache.json","w", encoding="utf-8") as f:
        dump(channel_info, f, indent=4)
    return True

    
with conn:
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT channel_id FROM QUERIES ORDER BY time DESC")
    data = [d[0] for d in cur.fetchall()]

for ch_id in data:
    get_channel_name_image(ch_id)


# add default settings to everyone who is not in the settings table
def add_default_settings(channel_id:str):
    with conn:
        cur = conn.cursor()
        cur.execute(f"INSERT INTO settings(channel_id) VALUES(?)", (channel_id,))
        conn.commit()
    return True 

with conn:
    cur = conn.cursor()
    cur.execute(f"SELECT * from settings")
    channels_in_settings = [x[0] for x in cur.fetchall()]
    for ch_id in data:
        if ch_id not in channels_in_settings:
            #add_default_settings(ch_id)
            pass


write_channel_cache(channel_info)
prefix_webhook = {}

if __name__ == "__main__":
    print(take_screenshot('3JYldCxLBWM', 1120))
    #app.run(debug=True, host="0.0.0.0", port=80)