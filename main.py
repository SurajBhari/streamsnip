from flask import Flask, jsonify, request, render_template, redirect, url_for, session, flash
from bs4 import BeautifulSoup
import requests
import subprocess

from json import load, loads, dump, dumps
import time
import builtins
from bs4 import BeautifulSoup
from requests import get
from flask import request
from discord_webhook import DiscordWebhook
import sqlite3
from flask import redirect, render_template, request, send_file, session, url_for

from urllib.parse import parse_qs
import scrapetube
from chat_downloader.sites import YouTubeChatDownloader
app = Flask(__name__)

db = sqlite3.connect("queries.db", check_same_thread=False)
cur = db.cursor()
# create a table channel_id message_id clip_desc, time, time_in_seconds, user_id, user_name, stream_link
cur.execute("CREATE TABLE IF NOT EXISTS QUERIES(channel_id VARCHAR(40), message_id VARCHAR(40), clip_desc VARCHAR(40), time int, time_in_seconds int, user_id VARCHAR(40), user_name VARCHAR(40), stream_link VARCHAR(40))")
db.commit()


global last_slash_request, last_slash_data
last_slash_request = 0
last_slash_data = []

def get_channel_clips(channel_id:str):
    if not channel_id:
        return {}
    cur.execute(f"select * from QUERIES where channel_id=?", (channel_id, ))
    data = cur.fetchall()
    l = []
    for y in data:
        x = {}
        x['link'] = y[7]
        x['author'] = {
            'name': y[6],
            'id': y[5]
        }
        x['clip_time'] = y[4]  # time in stream when clip was made. if stream starts at 0 
        x['time'] = y[3] # real life time when clip was made
        x['message'] = y[2]
        x['stream_id'] = y[7].replace("https://youtu.be/", "").split("?")[0]
        x['dt'] = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.localtime(y[3]))
        x['hms'] = time_to_hms(y[4])
        x['id'] = y[1][-3:] + str(int(y[4]))

        l.append(x)
    l.reverse()
    return l

def time_to_hms(seconds:int):
    hour = int(seconds/3600)
    minute = int(seconds/60) % 60
    second = int(seconds) % 60
    if hour < 10:
        hour = f"0{hour}"
    if minute < 10:
        minute = f"0{minute}"
    if second < 10:
        second = f"0{second}"
    if int(hour):
        hour_minute_second = f"{hour}:{minute}:{second}"
    else:
        hour_minute_second = f"{minute}:{second}"
    return hour_minute_second

def create_simplified(clips:list) -> str:
    known_vid_id = []
    string = ""
    for clip in clips:
        if clip['stream_id'] not in known_vid_id:
            string += f"https://youtu.be/{clip['stream_id']}\n"
        string += f"{clip['author']['name']} -> {clip['message']} -> {clip['hms']}\n"
        string += f"Link: {clip['link']}\n\n\n"
        known_vid_id.append(clip['stream_id'])
    return string

def get_channel_name_image(channel_id:str):
    if not channel_id:
        return {}
    channel_link = f"https://youtube.com/channel/{channel_id}"
    html_data = get(channel_link).text
    soup = BeautifulSoup(html_data, 'html.parser')
    channel_image = soup.find("meta", property="og:image")["content"]
    channel_name = soup.find("meta", property="og:title")["content"]
    return channel_name, channel_image

def take_screenshot(video_url:str, seconds:int):
    # Get the video URL using yt-dlp
    try:
        video_info = subprocess.check_output(["yt-dlp", "-f", "bestvideo", "--get-url", video_url], universal_newlines=True)
    except subprocess.CalledProcessError as e:
        print("Error:", e)
        exit(1)

    # Remove leading/trailing whitespace and newline characters from the video URL
    video_url = video_info.strip()
    file_name = "ss.jpg"

    # FFmpeg command
    ffmpeg_command = [
        "ffmpeg",
        "-y",                     # say yes to prompts
        "-ss", str(seconds),      # Start time
        "-i", video_url,          # Input video URL
        "-vframes", "1",          # Number of frames to extract (1)
        "-q:v", "2",              # Video quality (2)
        "-hide_banner",           # Hide banner
        "-loglevel", "error",     # Hide logs
        file_name                 # Output image file
    ]

    try:
        subprocess.run(ffmpeg_command, check=True)
    except subprocess.CalledProcessError as e:
        print("Error:", e)
        exit(1)
    
    return file_name

@app.route('/')
def slash():
    global last_slash_request, last_slash_data
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        return f"If you can read this, then the program is running absolutely fine. See exports at -> http://{request.host}{url_for('exports', channel_id=channel.get('providerId')[0])}"
    except:
        pass
    if time.time() - last_slash_request < 28800: # 8 hours
        print("returning from cache")
        return render_template("home.html", data=last_slash_data)
    cur.execute(f"SELECT DISTINCT channel_id FROM QUERIES")
    data = cur.fetchall()
    returning = []
    for ch_id in data:
        ch = {}
        channel_name, channel_image = get_channel_name_image(ch_id[0])
        ch["image"] = channel_image
        ch["id"] = ch_id[0]
        ch["name"] = channel_name
        ch['link'] = f"http://{request.host}{url_for('exports', channel_id=ch_id[0])}"
        returning.append(ch)
    returning.reverse()
    last_slash_request = time.time()
    last_slash_data = returning
    return render_template("home.html", data=returning)    

@app.route("/export")
def export():
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    return f"You can download the export from http://{request.host}{url_for('exports', channel_id=channel_id)}"


@app.route("/exports/<channel_id>")
def exports(channel_id = None):
    if not channel_id:
        return redirect(url_for("slash"))
    
    channel_link = f"https://youtube.com/channel/{channel_id}"
    html_data = get(channel_link).text
    soup = BeautifulSoup(html_data, 'html.parser')
    channel_image = soup.find("meta", property="og:image")["content"]
    channel_name = soup.find("meta", property="og:title")["content"]
    data = get_channel_clips(channel_id)
    return render_template("export.html", 
                           data= data,
                           clips_string = create_simplified(data), 
                           channel_name = channel_name, 
                           channel_image=channel_image)


# /clip/<message_id>/<clip_desc>?showlink=true&screenshot=true&dealy=-10
@app.route("/clip/<message_id>/")
@app.route("/clip/<message_id>/<clip_desc>")
def clip(message_id, clip_desc=None):
    show_link = request.args.get("showlink", True)
    screenshot = request.args.get("screenshot", False)
    delay = request.args.get("delay", 0)
    show_link = False if show_link == "false" else True
    screenshot = True if screenshot == "true" else False
    try:
        delay = 0 if not delay else int(delay)
    except ValueError:
        return "Delay should be an integer (plus or minus)"
    request_time = time.time()
    if not message_id:
        return "No message id provided, You have configured it wrong. please contact AG at https://discord.gg/2XVBWK99Vy"
    if not clip_desc:
        clip_desc = "None"
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Not able to auth"

    with open("creds.json", "r") as f:
        creds = load(f)
    
    channel_id = channel.get("providerId")[0]
    try:
        webhook_url = creds[channel_id]
    except KeyError:
        return "We don't have info where to send the clip to. contact AG at https://discord.gg/2XVBWK99Vy"


    user_id = user.get("providerId")[0]
    user_name = user.get("displayName")[0]
    vids = scrapetube.get_channel(channel_id, content_type="streams")
    live_found_flag = False

    for vid in vids:
        if vid["thumbnailOverlays"][0]["thumbnailOverlayTimeStatusRenderer"]["style"] == "LIVE":
            live_found_flag = True
            break
    if not live_found_flag:
        return "No live stream found"
    #only get the previous chat and don't wait for new one
    vid = YouTubeChatDownloader().get_video_data(video_id=vid["videoId"])
    clip_time  = request_time - vid["start_time"]/1000000 + 5
    clip_time += delay
    url = "https://youtu.be/"+vid["original_video_id"]+"?t="+str(int(clip_time))
    clip_id = message_id[-3:] + str(int(clip_time))

    # if clip_time is in seconds. then hh:mm:ss format would be like
    hour_minute_second = time_to_hms(clip_time)
    message_cc_webhook = f"{clip_id} | **{clip_desc}** \n\n{hour_minute_second} \n<{url}>"
    if delay:
        message_cc_webhook += f"\nDelayed by {delay} seconds."
    channel_name, channel_image = get_channel_name_image(user_id)

    # insert the entry to database
    cur.execute("INSERT INTO QUERIES VALUES(?, ?, ?, ?, ?, ?, ?, ?)", (channel_id, message_id, clip_desc, request_time, clip_time, user_id, user_name, url))
    db.commit()

    webhook = DiscordWebhook(
        url=webhook_url, 
        content=message_cc_webhook, 
        username= user_name, 
        avatar_url=channel_image
    )
    
    message_to_return = f"Clip {clip_id} by {user_name} -> '{clip_desc[:32]}' Clipped at {hour_minute_second}"
    if delay:
        message_to_return += f" Delayed by {delay} seconds."
    message_to_return += " | sent to discord."
    if show_link:
        message_to_return += f" See all clips at http://{request.host}{url_for('exports', channel_id=channel_id)}"
    if screenshot:
        file_name = take_screenshot(url, clip_time)
        with open(file_name, "rb") as f:
            webhook.add_file(file=f.read(), filename="ss.jpg")
        print(f"Sent screenshot to {user_name} from {channel_id} with message -> {clip_desc} {url}")
    webhook.execute()
    return message_to_return

@app.route("/delete/<clip_id>")
def delete(clip_id = None):
    if not clip_id:
        print("No Clip ID provided")
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    try:
        tis = int(clip_id[3:])
    except ValueError:
        return "Clip ID should be in format of 3 characters + time in seconds"
    channel_id = channel.get("providerId")[0]
    # an id is last 3 characters of message_id + time_in_seconds
    # get previous description
    cur.execute("SELECT * FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?", (channel_id, f"%{clip_id[:3]}", tis-1, tis+1))
    data = cur.fetchall()
    if not data:
        return "Clip ID not found"
    cur.execute("DELETE FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?", (channel_id, f"%{clip_id[:3]}", tis-1, tis+1))
    db.commit()
    return f"Deleted clip ID {clip_id}."

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
    clip_id = xxx.split(" ")[0]
    new_desc = " ".join(xxx.split(" ")[1:])
    
    channel_id = channel.get("providerId")[0]
    # an id is last 3 characters of message_id + time_in_seconds
    # get previous description
    cur.execute("SELECT * FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?", (channel_id, f"%{clip_id[:3]}", int(clip_id[3:])-1, int(clip_id[3:])+1))
    data = cur.fetchall()
    if not data:
        return "Clip ID not found"
    old_desc = data[0][2]
    cur.execute("UPDATE QUERIES SET clip_desc=? WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?", (new_desc, channel_id, f"%{clip_id[:3]}", int(clip_id[3:])-1, int(clip_id[3:])+1))
    db.commit()
    return f"Edited clip ID {clip_id} from '{old_desc}' to '{new_desc}'."

    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)