# -*- coding: utf-8 -*-
import os
import json
import time
import subprocess
import tempfile
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import openai

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
YOUR_CHANNEL_ID = os.getenv("YOUR_CHANNEL_ID")

openai.api_key = OPENAI_API_KEY
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

CHANNELS_TO_MONITOR = [
    "UCpcTrCXbl4E3jKmQXV-oBgA",
    "UCCBFffCRRRkjFL9LXQQ9YDg",
    "UCNAf1k0yIjyGu3k9BwAg3lg",
]

NICHE         = "FIFA World Cup 2026"
BRAND_NAME    = "RepostAI"          # change to your channel name
BRAND_COLOR   = "0x6C47FF"          # purple — change if you want
WATERMARK_TEXT = "WC2026.Shorts"    # shown bottom-right


def get_latest_videos(channel_id, max_results=5):
    print(f"[SEARCH] Checking channel: {channel_id}")
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=max_results,
        order="date",
        type="video",
        publishedAfter=(datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if False else
            (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    response = request.execute()
    videos = []
    for item in response.get("items", []):
        videos.append({
            "id":        item["id"]["videoId"],
            "title":     item["snippet"]["title"],
            "channel":   item["snippet"]["channelTitle"],
            "url":       f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            "published": item["snippet"]["publishedAt"]
        })
    print(f"  Found {len(videos)} new videos")
    return videos


def download_video(url, output_dir):
    print(f"[DOWNLOAD] Downloading: {url}")
    output_path = os.path.join(output_dir, "original.mp4")
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] Download failed: {result.stderr}")
        return None
    print(f"  Downloaded to: {output_path}")
    return output_path


def get_transcript(video_path):
    print("[TRANSCRIBE] Transcribing with Whisper...")
    audio_path = video_path.replace(".mp4", "_audio.mp3")
    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-q:a", "0", "-map", "a",
        audio_path, "-y"
    ], capture_output=True)

    with open(audio_path, "rb") as audio_file:
        response = openai.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )
    os.remove(audio_path)
    print(f"  Transcribed {len(response.segments)} segments")
    return response.segments


def find_best_moment(segments, video_title):
    print("[AI] Analyzing best moments...")

    transcript_text = "\n".join([
        f"[{seg.start:.1f}s - {seg.end:.1f}s]: {seg.text}"
        for seg in segments
    ])

    prompt = f"""You are an expert YouTube Shorts editor specializing in {NICHE}.

Video title: "{video_title}"

Transcript with timestamps:
{transcript_text}

Find the single most exciting, viral-worthy 45-60 second clip.
Rules:
- Must be between 45 and 60 seconds long
- Must have a clear beginning and end
- Must be the most exciting/emotional/surprising moment

Respond ONLY in this exact JSON format:
{{
  "start_time": 45.2,
  "end_time": 103.7,
  "reason": "Why this moment is the best",
  "hook": "A short 6-word hook text to show on screen at the start"
}}"""

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    result = json.loads(response.choices[0].message.content)
    print(f"  Best moment: {result['start_time']}s to {result['end_time']}s")
    print(f"  Hook: {result.get('hook', '')}")
    return result


def cut_short_with_branding(video_path, start_time, end_time, output_dir, hook_text=""):
    """
    Cut the Short AND add:
    - Vertical 9:16 crop
    - Hook text at top (first 3 seconds)
    - Watermark bottom right
    - Subtle color grade (more vibrant)
    - Progress bar at bottom
    """
    print(f"[CUT] Cutting + branding Short ({start_time}s to {end_time}s)...")
    output_path = os.path.join(output_dir, "short_branded.mp4")
    duration = end_time - start_time

    # Find font — use Arial on Windows, fallback to DejaVu
    font_path = "C\\\\:/Windows/Fonts/arialbd.ttf"   # Windows bold Arial
    fallback   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    # Safe hook text (escape special chars for ffmpeg)
    safe_hook = hook_text.replace("'", "").replace(":", "").replace("\\", "")[:40]
    safe_brand = WATERMARK_TEXT.replace("'", "")

    # FFmpeg filter chain:
    # 1. Scale to 1080x1920 vertical
    # 2. Boost saturation/contrast slightly
    # 3. Add hook text top center (first 3s)
    # 4. Add watermark bottom right (full duration)
    # 5. Add thin progress bar at bottom
    vf = (
        # Step 1 — vertical crop
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
        "setsar=1,"
        # Step 2 — color grade (more vivid)
        "eq=saturation=1.3:contrast=1.05:brightness=0.02,"
        # Step 3 — hook text (shows first 3 seconds)
        f"drawtext=text='{safe_hook}'"
        f":fontsize=52"
        f":fontcolor=white"
        f":borderw=3:bordercolor=black"
        f":x=(w-text_w)/2:y=120"
        f":enable='between(t,0,3)',"
        # Step 4 — watermark bottom right (always visible)
        f"drawtext=text='{safe_brand}'"
        f":fontsize=28"
        f":fontcolor=white@0.7"
        f":borderw=2:bordercolor=black@0.5"
        f":x=w-text_w-20:y=h-60,"
        # Step 5 — progress bar at very bottom
        f"drawbox=x=0:y=h-8:w=iw*t/{duration}:h=8:color=9B59B6@0.9:t=fill"
    )

    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path, "-y"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] Branding failed, trying simple cut...")
        # Fallback — simple cut without branding
        return cut_simple(video_path, start_time, end_time, output_dir)

    print(f"  Branded Short saved: {output_path}")
    return output_path


def cut_simple(video_path, start_time, end_time, output_dir):
    """Fallback simple cut without text overlays"""
    output_path = os.path.join(output_dir, "short.mp4")
    duration = end_time - start_time
    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path, "-y"
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path


def generate_metadata(video_title, reason, hook):
    print("[META] Generating metadata...")

    prompt = f"""You are a viral YouTube Shorts expert for {NICHE} content.

Original video: "{video_title}"
Why this clip is great: "{reason}"
Hook shown on screen: "{hook}"

Generate optimized YouTube Shorts metadata.
Respond ONLY in this exact JSON format:
{{
  "title": "Catchy title under 60 chars with emoji",
  "description": "2-3 lines engaging description with relevant hashtags including #Shorts #WorldCup2026 #FIFA",
  "tags": ["FIFA", "WorldCup2026", "WorldCup", "Football", "Soccer", "Shorts", "Goals", "Highlights", "FIFA2026", "WorldCupShorts"]
}}"""

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    metadata = json.loads(response.choices[0].message.content)
    print(f"  Title: {metadata['title']}")
    return metadata


def upload_to_youtube(short_path, metadata):
    print("[UPLOAD] Uploading to YouTube...")
    from googleapiclient.discovery import build as oauth_build
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file("oauth_token.json")
    youtube_upload = oauth_build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title":       metadata["title"],
            "description": metadata["description"],
            "tags":        metadata["tags"],
            "categoryId":  "17"
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(short_path, mimetype="video/mp4", resumable=True)
    request = youtube_upload.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Uploading... {int(status.progress() * 100)}%")

    print(f"  Uploaded! https://youtube.com/watch?v={response['id']}")
    return response["id"]


def run_pipeline():
    print("=" * 50)
    print("RepostAI Pipeline Started")
    print(f"Monitoring {len(CHANNELS_TO_MONITOR)} channels")
    print("=" * 50)

    processed = set()

    while True:
        for channel_id in CHANNELS_TO_MONITOR:
            try:
                videos = get_latest_videos(channel_id)

                for video in videos:
                    if video["id"] in processed:
                        continue

                    print(f"\n{'='*50}")
                    print(f"Processing: {video['title']}")
                    print(f"{'='*50}")

                    with tempfile.TemporaryDirectory() as tmpdir:
                        video_path = download_video(video["url"], tmpdir)
                        if not video_path:
                            continue

                        segments  = get_transcript(video_path)
                        best      = find_best_moment(segments, video["title"])
                        hook      = best.get("hook", "Watch this amazing moment")

                        short_path = cut_short_with_branding(
                            video_path,
                            best["start_time"],
                            best["end_time"],
                            tmpdir,
                            hook_text=hook
                        )
                        if not short_path:
                            continue

                        metadata = generate_metadata(
                            video["title"],
                            best["reason"],
                            hook
                        )

                        upload_to_youtube(short_path, metadata)

                        # Save a local copy too
                        import shutil
                        os.makedirs("shorts", exist_ok=True)
                        shutil.copy(short_path, f"shorts/{video['id']}_short.mp4")
                        with open(f"shorts/{video['id']}_metadata.json", "w") as f:
                            json.dump(metadata, f, indent=2)

                    processed.add(video["id"])

            except Exception as e:
                print(f"[ERROR] {channel_id}: {e}")
                continue

        print(f"\nWaiting 15 minutes before next check...")
        time.sleep(900)


if __name__ == "__main__":
    run_pipeline()