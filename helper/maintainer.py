import json
from discord_webhook import DiscordWebhook, DiscordEmbed
import time
import requests as request
import os
import psutil
import threading
import sqlite3

import os
from Clip import Clip
from util import *

owner_icon = "👑"
mod_icon = "🔧"
regular_icon = "🧑‍🌾"
subscriber_icon = "⭐"

management_webhook_url = None
management_webhook_url = json.load(open("../config.json", "r")).get(
    "management_webhook", None
)
if not management_webhook_url:
    exit("No management webhook found")

"""
def download_clips(ids, thread_no):
    for clip_id in ids:
        out = download_and_store(clip_id)
        if isinstance(out, str):
            if "error" not in out.lower():
                management_webhook = DiscordWebhook(
                    url=management_webhook_url,
                    content=f"#{thread_no} - Downloaded - {out}",
                )
                management_webhook.execute()
"""

DiscordWebhook(url=management_webhook_url, content="Maintainer started").execute()

conn = sqlite3.connect("../queries.db")


def comment_task() -> str:
    COMMENTS = ""
    with conn:
        # we only talk about streams that happened after 1735410600 Sun Dec 29 2024 00:00:00 GMT+0530 (India Standard Time)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS COMMENTS (video_id TEXT, comment TEXT, time INTEGER)")
        conn.commit()
        two_days_ago = int(time.time()) - 2 * 24 * 60 * 60
        cur.execute(f"SELECT * FROM queries WHERE time > {two_days_ago} GROUP BY message_id")  # grouping will make sure we get 1 clip from each streams
        clips = [Clip(x) for x in cur.fetchall()]
        previously_done = [x[0] for x in cur.execute("SELECT video_id FROM COMMENTS").fetchall()]
        comments_subscribers = [x[0] for x in cur.execute("SELECT channel_id from SETTINGS WHERE comments = 'True'").fetchall()]
        for clip in clips:
            if clip.channel not in comments_subscribers:
                continue
            if clip.stream_id in previously_done:
                continue
            cur.execute(
                """
                SELECT * FROM QUERIES WHERE stream_link LIKE ? AND private is not 1;
                """,
                (f"%{clip.stream_id}%",),
            )
            clips_for_stream = [Clip(x) for x in cur.fetchall()]
            if not clips_for_stream:
                continue
            string = "Clips For This stream:\n"
            for clip in clips_for_stream:
                if clip.userlevel == "everyone" or not clip.userlevel:
                    icon = ""
                elif clip.userlevel == "owner":
                    icon = owner_icon
                elif clip.userlevel == "moderator":
                    icon = mod_icon 
                elif clip.userlevel == "subscriber":
                    icon = subscriber_icon
                elif clip.userlevel == "regular":
                    icon = regular_icon
                else:
                    icon = ""
                string += f"{clip.hms} | {clip.id} | {clip.desc} -- {icon} {clip.user_name}\n"
            try:
                string = post_comment(clip.stream_id, string)
                COMMENTS += "\n" + "Commented on " + clip.stream_id
                pass
            except Exception as e:
                COMMENTS += f"\nFailed to post comment for {clip.stream_id} {e}"
                print(e)
                continue # go to next stream. we will try again later
            cur.execute("INSERT INTO COMMENTS VALUES (?, ?, ?)", (clip.stream_id, string, int(time.time())))
            conn.commit()
    return COMMENTS
            
def periodic_task():
    management_webhook = DiscordWebhook(url=management_webhook_url)
    management_webhook.content = f"<t:{int(time.time())}:F>"
    download_clips = os.listdir("../clips")
    deleted_clips = []
    not_deleted_clips = []
    for clip in download_clips:
        if ".part" in clip:
            not_deleted_clips.append(clip)
            continue # skip incomplete downloads
        os.remove(f"../clips/{clip}")
        deleted_clips.append(clip)
    os.system("ps auxf > file.txt")
    time.sleep(1)
    file_list = ['file.txt', '/var/log/apache2/error.log', '/var/log/apache2/access.log']
    # management_webhook.add_file(file=open("../config.json", "rb"), filename="config.json")
    # consturct a string that contains most important vitals of system
    # and send it to the webhook
    system_vitals = f"{task_count} CPU: {psutil.cpu_percent()}%\nMemory: {psutil.virtual_memory().percent}%\nDisk: {psutil.disk_usage('/').percent}%"
    management_webhook.content += system_vitals
    management_webhook.content += f"\nDeleted {(deleted_clips)} \nNot deleted {(not_deleted_clips)} clips"
    if task_count % 5 == 0:
        file_list.append("../config.json")
        comments = comment_task()
        # write the comments to a file and send it to the webhook
        with open("comments.txt", "w") as f:
            f.write(comments)
        file_list.append('comments.txt')
    for file in file_list:
        fwebhook = DiscordWebhook(url=management_webhook_url)
        management_webhook.add_file(
            file=open(file, "rb"), filename=file.split('/')[-1]
        )
        try:
            fwebhook.execute()
        except Exception as e:
            management_webhook.content += e
    try:
        management_webhook.execute()
    except request.exceptions.MissingSchema:
        exit("Invalid webhook URL")
    if psutil.virtual_memory().percent > 90:
        management_webhook = DiscordWebhook(
            url=management_webhook_url, content="Memory usage is high RESTARTING SERVER"
        )
        management_webhook.execute()
        # restart the system
        os.system("reboot")
    return  # lock it for now
    clips = get_channel_clips()[:250]
    clip_ids = [x.id for x in clips]
    already_downloaded = [x.split(".")[0] for x in os.listdir("clips")]
    need_to_download_ids = []
    # delete clips that are not in clips
    for clip in os.listdir("clips"):
        if clip.split(".")[0] not in clip_ids:
            os.remove(f"clips/{clip}")
            continue
        if clip.endswith(".part"):
            os.remove(f"clips/{clip}")
    need_to_download_ids = [x for x in clip_ids if x not in already_downloaded]
    management_webhook = DiscordWebhook(
        url=management_webhook_url,
        content=f"Need to download {len(need_to_download_ids)} clips, Already have {len(already_downloaded)} clips",
    )
    management_webhook.execute()

    # Number of threads for downloading
    num_threads = 3

    # Split `need_to_download_ids` into chunks for each thread
    chunk_size = len(need_to_download_ids) // num_threads
    chunks = [
        need_to_download_ids[i : i + chunk_size]
        for i in range(0, len(need_to_download_ids), chunk_size)
    ]

    # Create threads and start downloading
    threads = []
    thread_count = 1
    for chunk in chunks:
        thread = threading.Thread(
            target=download_clips,
            args=(
                chunk,
                thread_count,
            ),
        )
        thread_count += 1
        thread.start()
        threads.append(thread)

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Send a message to the management webhook
    management_webhook = DiscordWebhook(
        url=management_webhook_url, content="Clips downloaded"
    )
    management_webhook.execute()

if __name__ == "__main__":
    task_count = 0

    while True:
        periodic_task()
        task_count += 1
        time.sleep(30*60)