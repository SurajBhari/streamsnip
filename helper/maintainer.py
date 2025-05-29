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
from Riot import Riot
import scrapetube
from chat_downloader.sites import YouTubeChatDownloader


management_webhook_url = None
config = json.load(open("../config.json", "r"))
project_youtube_channel_id = config.get("project_youtube_channel_id")
if "cookies.txt" in os.listdir("."):
    cookies = "cookies.txt"
else:
    cookies = None
management_webhook_url = config.get("management_webhook")
henrik_api_key = config.get("henrik_api_key")
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

valorant_api_base = "https://api.henrikdev.xyz"
def get_player_uuid(tag: str, region: str) -> Optional[str]:
    """
    Get the player UUID from the Riot API using the player's tag and region.
    """
    name, tag = tag.split("#")
    url = f"{valorant_api_base}/valorant/v1/account/{name}/{tag}"
    headers = {
        "Authorization": henrik_api_key,
    }
    try:
        response = request.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", {}).get("puuid")
        else:
            print(f"Failed to get player UUID for {tag} in {region}: {response.status_code}")
            return None
    except request.RequestException as e:
        print(f"Error fetching player UUID for {tag} in {region}: {e}")
        return None
    
def get_match_list(name,tag,region):

    url = f"{valorant_api_base}/valorant/v3/matches/{region}/{name}/{tag}?mode=competitive"
    headers = {
        "Authorization": henrik_api_key,
    }
    try:
        response = request.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
        else:
            print(f"Failed to get match list for {name}#{tag} in {region}: {response.status_code}")
            return []
    except request.RequestException as e:
        print(f"Error fetching match list for {name}#{tag} in {region}: {e}")
        return []
    
def get_match(match_id: str) -> Optional[dict]:
    """
    Get match details from the Riot API using the match ID.
    """
    url = f"{valorant_api_base}/valorant/v2/match/{match_id}"
    headers = {
        "Authorization": henrik_api_key,
    }
    try:
        response = request.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", {})
        else:
            print(f"Failed to get match details for {match_id}: {response.status_code}")
            return None
    except request.RequestException as e:
        print(f"Error fetching match details for {match_id}: {e}")
        return None
def round_is_clutch(round_data):
    winning_team = round_data.get("winning_team")
    player_stats = round_data.get("player_stats", [])

    # Initialize players by team
    team_players = {"Red": set(), "Blue": set()}
    puuid_to_name = {}

    for player in player_stats:
        puuid = player["player_puuid"]
        team = player["player_team"]
        name = player["player_display_name"]
        team_players[team].add(puuid)
        puuid_to_name[puuid] = name

    # Initialize alive players
    alive = {
        "Red": set(team_players["Red"]),
        "Blue": set(team_players["Blue"]),
    }

    # Collect all kill events
    all_kills = []
    for player in player_stats:
        for kill in player.get("kill_events", []):
            all_kills.append(kill)

    # Sort kills by kill time
    all_kills.sort(key=lambda k: k["kill_time_in_round"])

    can_be_clutch = False
    clutcher_puuid = None

    for kill in all_kills:
        victim = kill["victim_puuid"]
        killer = kill["killer_puuid"]
        killer_team = kill["killer_team"]
        victim_team = kill["victim_team"]

        # Remove victim from alive players
        if victim in alive[victim_team]:
            alive[victim_team].remove(victim)

        # Check for clutch condition
        if (len(alive[winning_team]) == 1 and len(alive["Red" if winning_team == "Blue" else "Blue"]) > 2):
            can_be_clutch = True
            clutcher_puuid = list(alive[winning_team])[0]

    return puuid_to_name[clutcher_puuid] if can_be_clutch else False

def valorant_clip_task():
    response = ""
    if not henrik_api_key:
        print("No riot developer key found. Skipping valorant clip task")
        return

    with conn:
        cur = conn.cursor()
        riots = Riot.get_all_enabled(conn)
        cur.execute(
            f"SELECT channel_id FROM MEMBERSHIP WHERE type='pro' AND end > {int(time.time())}"
        )
        members = [x[0] for x in cur.fetchall()]

    for riot in riots:
        if riot.channel_id not in members:
            continue
        # if streamer is live skip them
        matches = get_match_list(riot.id, riot.tag, riot.region)
        for match in matches:
            if match.get("metadata", {}).get("mode_id") != "competitive":
                continue
            match_id = match.get("metadata", {}).get("matchid")
            if riot.last_match_id == match_id:
                break

            match_info = get_match(match_id)
            match_start_epoch = match_info.get("metadata", {}).get("game_start")
            print(f"Checking match {match_id} for {riot.channel_id}")

            clips_to_process = []
            for round_count, round in enumerate(match_info.get("rounds", []), start=1):
                kill_times = [
                    kill.get("kill_time_in_match")
                    for player in round.get("player_stats", [])
                    for kill in player.get("kill_events", [])
                    if kill.get("kill_time_in_match") is not None
                ]
                if kill_times:
                    round_start = match_start_epoch + int(min(kill_times)/1000) + 80 # Adding 80 seconds to account for the round start delay
                else:
                    round_start = None

                is_clutch = False
                is_3k = False
                is_4k = False
                is_ace = False

                for player_stat in round.get("player_stats", []):
                    player_name = player_stat.get("player_display_name")
                    if riot.id not in player_name or riot.tag not in player_name:
                        continue

                    clutch_result = round_is_clutch(round)
                    if clutch_result and player_name in clutch_result:
                        is_clutch = True

                    if player_stat.get("kills", 0) >= 3:
                        is_3k = True
                    if player_stat.get("kills", 0) >= 4:
                        is_4k = True
                    if player_stat.get("kills", 0) >= 5:
                        is_ace = True

                clip_message = ""
                if is_ace:
                    is_4k = False
                    is_3k = False
                    clip_message = "ACE "
                if is_4k:
                    is_3k = False
                    clip_message = "4K "
                if is_3k:
                    clip_message = "3K "
                if is_clutch:
                    clip_message += "CLUTCH "

                if is_clutch or is_3k or is_4k or is_ace:
                    clip_message += f"Round {round_count} | {match.get('metadata', {}).get('map', 'Unknown Map')}"
                    print(f"Queuing clip for {riot.channel_id} in match {match_id} Round {round_count}")
                    clips_to_process.append((round_start, clip_message))

            if not clips_to_process:
                print(f"No clips found for {riot.channel_id} in match {match_id}")
                continue
            

            vids = scrapetube.get_channel(riot.channel_id, content_type="streams", sleep=0)
            for vid_counter, vid in enumerate(vids):
                if vid_counter > 5:
                    print("Skipping further videos as we have checked 5 already")
                    break
                try:
                    vid_data = YouTubeChatDownloader(cookies=cookies).get_video_data(
                        video_id=vid["videoId"]
                    )
                    if vid_data["start_time"] is None:
                        print(f"Streamer is live. lets not process this video {vid['videoId']}")
                        with conn:
                            cur = conn.cursor()
                            # update the last match id for the riot
                            cur.execute(
                                "UPDATE RIOT SET last_match_id = ? WHERE channel_id = ?",
                                (match_id, riot.channel_id),
                            )
                            conn.commit()
                        break
                    stream_start_time = vid_data["start_time"] / 1_000_000
                    stream_end_time = vid_data.get("end_time", None)
                    if not stream_end_time:
                        print(f"Skipping video {vid['videoId']} as end time is None")
                        continue
                    stream_end_time /= 1_000_000

                    buffer = 10  # seconds buffer
                    valid_clips = [
                        clip for clip in clips_to_process
                        if (stream_start_time - buffer) < clip[0] < (stream_end_time + buffer)
                    ]

                    for clip_time, message in valid_clips:
                        print(stream_start_time, clip_time, stream_end_time, message)
                        headers = {
                            "Nightbot-Channel": f"providerId={riot.channel_id}",
                            "Nightbot-User": f"providerId={project_youtube_channel_id}&displayName=StreamSnip&userLevel=everyone",
                            "Nightbot-Response-Url": "https://api.nightbot.tv/1/channel/send/",
                            "videoID": vid['videoId'],
                            "timestamp": str(clip_time),
                        }
                        link = f"https://localhost/clip/AUTOMATED_CLIP_{vid['videoId']}/{message}"
                        r = request.get(link, headers=headers, verify=False)
                        response += r.text + "\n"
                        print(response)

                    if valid_clips:
                        break  # stop looking for more videos once valid clips are found
                except Exception as e:
                    print(f"Error processing video {vid['videoId']}: {e}")
                    continue
            break
    return response


def comment_task() -> str:
    COMMENTS = ""
    with conn:
        # we only talk about streams that happened after 1735410600 Sun Dec 29 2024 00:00:00 GMT+0530 (India Standard Time)
        cur = conn.cursor()
        cur.execute(
            f"SELECT channel_id FROM MEMBERSHIP WHERE type='premium' AND end > {int(time.time())}"
        )
        members = [x[0] for x in cur.fetchall()]
        cur.execute(
            "CREATE TABLE IF NOT EXISTS COMMENTS (video_id TEXT, comment TEXT, time INTEGER)"
        )
        conn.commit()
        two_days_ago = int(time.time()) - 10 * 24 * 60 * 60 # in reality this is 10 days
        cur.execute(
            f"SELECT * FROM queries WHERE time > {two_days_ago} GROUP BY message_id"
        )  # grouping will make sure we get 1 clip from each streams
        clips = [Clip(x) for x in cur.fetchall()]
        previously_done = [
            x[0] for x in cur.execute("SELECT video_id FROM COMMENTS").fetchall()
        ]
        comments_subscribers = [
            x[0]
            for x in cur.execute(
                "SELECT channel_id from SETTINGS WHERE comments = 'True'"
            ).fetchall()
        ]
        comment_count = 0
        for clip in clips:
            if clip.channel not in comments_subscribers:
                continue
            if clip.channel not in members:
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
            string = prepare_comment_text(clips_for_stream)
            comment_count += 1
            if comment_count > 15:
                COMMENTS += "\n" + "Comment Count surpassed 15"
                break
            try:
                if failed_ids.count(clip.stream_id) > 2:
                    COMMENTS += (
                        "\n"
                        + f"Failed to comment 3 times. Skipping this stream {clip.stream_id}"
                    )
                    comment_count -= 1  # we are not commenting on this stream so we need to reduce the count
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
                # send a message to the management webhook
                management_webhook = DiscordWebhook(
                    url=management_webhook_url,
                    content=f"Failed to post comment for {clip.stream_id} {e} <@408994955147870208>",
                )
                management_webhook.execute()
                print(f"Failed to post comment for {clip.stream_id} {e}")
                print(e)
                continue  # go to next stream. we will try again later
            cur.execute(
                "INSERT INTO COMMENTS VALUES (?, ?, ?)",
                (clip.stream_id, string, int(time.time())),
            )
            conn.commit()
    COMMENTS += "\n" + "Done commenting"
    return COMMENTS


def periodic_task():
    management_webhook = DiscordWebhook(url=management_webhook_url)
    management_webhook.content = f"<t:{int(time.time())}:F>"
    download_clips = os.listdir("../clips")
    vclip = valorant_clip_task()
    deleted_clips = []
    not_deleted_clips = []
    for clip in download_clips:
        if ".part" in clip:
            not_deleted_clips.append(clip)
            continue  # skip incomplete downloads
        os.remove(f"../clips/{clip}")
        deleted_clips.append(clip)
    os.system("ps auxf > file.txt")
    time.sleep(1)
    file_list = [
        "file.txt",
        "/var/log/apache2/error.log",
        "/var/log/apache2/access.log",
        "../queries.db",
        "../record.log",
        "channel_cache.json",
        "client_secrets.json",
    ]
    # management_webhook.add_file(file=open("../config.json", "rb"), filename="config.json")
    # consturct a string that contains most important vitals of system
    # and send it to the webhook
    system_vitals = f"{task_count} CPU: {psutil.cpu_percent()}%\nMemory: {psutil.virtual_memory().percent}%\nDisk: {psutil.disk_usage('/').percent}%"
    management_webhook.content += system_vitals
    management_webhook.content += (
        f"\nDeleted {(deleted_clips)} \nNot deleted {(not_deleted_clips)} clips"
    )
    if task_count % 5 == 0:
        file_list.append("../config.json")
        comments = comment_task()
        # write the comments to a file and send it to the webhook
        with open("comments.txt", "w") as f:
            f.write(comments)
        with open("vclip.txt", "w+") as f:
            f.write(vclip)
        file_list.append("vclip.txt")
        file_list.append("comments.txt")
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
            fwebhook.add_file(file=open(file, "rb"), filename=file.split("/")[-1])
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
    with open(file_path, "rb") as f:
        part = 1
        while chunk := f.read(chunk_size):
            new_path = f"{file_path}.part{part}"
            with open(new_path, "wb") as chunk_file:
                chunk_file.write(chunk)
            part += 1
            new_paths.append(new_path)
    return new_paths


# Usage


def merge_files(input_file: str = "database.db.part", output_file: str = "database.db"):
    parts = sorted(glob.glob(input_file + "*"))
    print(output_file)
    print(parts)
    with open(output_file, "wb") as f:
        for part in parts:
            with open(part, "rb") as chunk_file:
                f.write(chunk_file.read())


if __name__ == "__main__":
    task_count = 0
    while True:
        periodic_task()
        task_count += 1
        time.sleep(30 * 60)
