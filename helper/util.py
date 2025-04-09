from typing import Optional, List
from json import load, dump

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os

owner_icon = "👑"
mod_icon = "🔧"
regular_icon = "🧑‍🌾"
subscriber_icon = "⭐"


def time_to_hms(seconds: int):
    hour = int(seconds / 3600)
    minute = int(seconds / 60) % 60
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




def get_json_from_html(html: str, key: str, num_chars: int = 2, stop: str = '"') -> str:
    pos_begin = html.find(key) + len(key) + num_chars
    pos_end = html.find(stop, pos_begin)
    return html[pos_begin:pos_end]


# Scopes for the YouTube Data API
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def authenticate_youtube():
    """Authenticate with OAuth2 and return an authorized YouTube API client."""
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secrets.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save credentials for the next run
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("youtube", "v3", credentials=creds)


def is_video_live(video_id):
    youtube = authenticate_youtube()
    request = youtube.videos().list(part="snippet,statistics", id=video_id)
    response = request.execute()
    try:
        return response["items"][0]["snippet"]["liveBroadcastContent"] == "live"
    except KeyError:
        return False


def post_comment(video_id, comment_text):
    """Post a comment on a YouTube video."""
    youtube = authenticate_youtube()
    request = youtube.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": comment_text}},
            }
        },
    )
    response = request.execute()
    print("Comment posted:", response)


def list_comments(video_id):
    youtube = authenticate_youtube()

    request = youtube.commentThreads().list(part="snippet", videoId=video_id)
    return request.execute()


def prepare_comment_text(clips: List) -> str:
    string = "Clips For This stream: (this is a BETA option. please take this with a grain of salt)\n"
    for clip in clips:
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
    string += "\nThat's all. \n\nThis is a BETA feature. Please take this with a grain of salt. If you have any feedback, please let me know."
    return string


if __name__ == "__main__":
    # Replace with your video ID and comment text
    VIDEO_ID = "mtfr0OkzTks"
    COMMENT_TEXT = "This is a test comment from a Python script!"

    post_comment(VIDEO_ID, COMMENT_TEXT)
