import json
from discord_webhook import DiscordWebhook, DiscordEmbed
import time
import requests as request
import os
import glob
import psutil
import threading
import sqlite3
from typing import Optional, List, Any
from datetime import datetime

import os
from Clip import Clip
from util import *


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

failed_ids = []
def comment_task() -> str:
    COMMENTS = ""
    with conn:
        # we only talk about streams that happened after 1735410600 Sun Dec 29 2024 00:00:00 GMT+0530 (India Standard Time)
        cur = conn.cursor()
        cur.execute("SELECT channel_id FROM MEMBERSHIP WHERE type='love' OR type='pro' ")
        members = [x[0] for x in cur.fetchall()]
        cur.execute("CREATE TABLE IF NOT EXISTS COMMENTS (video_id TEXT, comment TEXT, time INTEGER)")
        conn.commit()
        two_days_ago = int(time.time()) - 2 * 24 * 60 * 60
        cur.execute(f"SELECT * FROM queries WHERE time > {two_days_ago} GROUP BY message_id")  # grouping will make sure we get 1 clip from each streams
        clips = [Clip(x) for x in cur.fetchall()]
        previously_done = [x[0] for x in cur.execute("SELECT video_id FROM COMMENTS").fetchall()]
        comments_subscribers = [x[0] for x in cur.execute("SELECT channel_id from SETTINGS WHERE comments = 'True'").fetchall()]
        comment_count = 0   
        for clip in clips:
            if clip.channel not in comments_subscribers:
                print(f"Skipping {clip.channel} as comments are disabled")
                continue
            if clip.channel not in members:
                print(f"Skipping {clip.channel} as they are not a member")
                continue
            if clip.stream_id in previously_done:
                print(f"Skipping {clip.stream_id} as it is already commented")
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
            string = prepare_comment_text(clips_for_stream)
            comment_count += 1
            if comment_count > 15:
                COMMENTS += "\n" + "Comment Count surpassed 15"
                break
            try:
                if failed_ids.count(clip.stream_id) > 2:
                    COMMENTS += "\n" + f"Failed to comment 3 times. Skipping this stream {clip.stream_id}"
                    comment_count -= 1 # we are not commenting on this stream so we need to reduce the count
                    continue
                if is_video_live(clip.stream_id):
                    COMMENTS += "\n" + f"Stream is live. Skipping {clip.stream_id}"
                    continue
                post_comment(clip.stream_id, string)
                COMMENTS += "\n" + "Commented on " + clip.stream_id
                pass
            except Exception as e:
                COMMENTS += f"\nFailed to post comment for {clip.stream_id} {e}"
                failed_ids.append(clip.stream_id)
                print(e)
                continue # go to next stream. we will try again later
            cur.execute("INSERT INTO COMMENTS VALUES (?, ?, ?)", (clip.stream_id, string, int(time.time())))
            conn.commit()
    COMMENTS += "\n" + "Done commenting"
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
    file_list = ['file.txt', '/var/log/apache2/error.log', '/var/log/apache2/access.log', "../queries.db", "../record.log"]
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
        try:
            file_size = os.path.getsize(file)
        except FileNotFoundError:
            continue
        if file_size > 10000000:
            file_list.extend(split_file(file))
            continue
        fwebhook = DiscordWebhook(url=management_webhook_url)
        try:
            fwebhook.add_file(
                file=open(file, "rb"), filename=file.split('/')[-1]
            )
        except Exception as e:
            fwebhook.content = e
        try:
            fwebhook.execute()
        except Exception as e:
            management_webhook.content += str(e)
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
    # omg i hate this part with a passion
    cut_money = True
    with conn:
        cur = conn.cursor()
        # get last transaction which is today and have "fee for day" in it 
        today_0 = datetime.today().replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        cur.execute("SELECT * FROM TRANSACTIONS WHERE time > ? AND description LIKE '%Fee for day%' ORDER BY time DESC LIMIT 1", (today_0,))
        last_transaction = cur.fetchone()
        if not last_transaction:
            cut_money = True
        else:
            cut_money = False # we have already cut the money today
    if cut_money:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM QUERIES WHERE time > ?", (today_0,))
            todays_channels = [x[0] for x in cur.fetchall()]

            cur.execute("SELECT * FROM MEMBERSHIP WHERE type is not 'paused'")
            # what a mess
            # today_clips 
            membership_members = [x[0] for x in cur.fetchall()]
            todays_channels.extend(membership_members)
            members = list(set(todays_channels))
            print(members)
            for member in members:
                cur.execute("SELECT * FROM MEMBERSHIP WHERE channel_id = ?", (member,))
                member_type = cur.fetchone()[1]
                if member_type == "basic":
                    cost = 99/28
                elif member_type == "pro":
                    cost = 199/28
                elif member_type == "love":
                    cost = 299/28
                cost = cost*-1
                date = datetime.today().strftime("%Y-%m-%d")
                balance = 0
                cur.execute("SELECT * FROM TRANSACTIONS WHERE channel_id = ?", (member,))
                for row in cur.fetchall():
                    balance += row[1]
                if balance < cost*-1:
                    cost = balance*-1
                if cost == 0:
                    continue
                cur.execute("INSERT INTO TRANSACTIONS VALUES (?, ?, ?, ?, ?)", (member, cost, int(time.time()), f"{member}_{date.replace('-','_')}", "Fee for day - "+member_type + " "+date))
                conn.commit()
        
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



def split_file(file_path, chunk_size=9_500_000) -> List[str]:  # Keeping it under 10 MB
    new_paths = []
    with open(file_path, 'rb') as f:
        part = 1
        while chunk := f.read(chunk_size):
            new_path = f"{file_path}.part{part}"
            with open(new_path, 'wb') as chunk_file:
                chunk_file.write(chunk)
            part += 1
            new_paths.append(new_path)
    return new_paths

# Usage


def merge_files(input_file:str = "database.db.part", output_file:str="database.db"):
    parts = sorted(glob.glob(input_file+"*"))
    print(output_file)
    print(parts)
    with open(output_file, 'wb') as f:
        for part in parts:
            with open(part, 'rb') as chunk_file:
                f.write(chunk_file.read())

if __name__ == "__main__":
    task_count = 0

    while True:
        periodic_task()
        task_count += 1
        time.sleep(30*60)