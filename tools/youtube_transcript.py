import os
import json
import glob
import base64
import requests
import sys
import re
 
def extract_youtube_url(text: str):
    """Pull YouTube URL from user message if present."""
    pattern = r'(https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[\w\-]+)'
    match = re.search(pattern, text)
    return match.group(1) if match else None

def get_youtube_transcript(url: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        vid_id = None
        if "youtu.be/" in url:
            vid_id = url.split("youtu.be/")[1].split("?")[0]
        elif "/shorts/" in url:
            vid_id = url.split("/shorts/")[1].split("?")[0]
        elif "v=" in url:
            vid_id = url.split("v=")[1].split("&")[0]

        if not vid_id:
            return None

        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(vid_id)

        # ── Pick first available transcript (any language) ──
        transcript = None
        for t in transcript_list:
            transcript = t
            break

        if not transcript:
            return None

        original_lang = transcript.language
        print(f"[Marin] Found transcript in: {original_lang}")

        # ── Translate to English if not already English ──
        if transcript.language_code != "en":
            if transcript.is_translatable:
                transcript = transcript.translate("en")
                print(f"[Marin] Translated {original_lang} → English")
            else:
                print(f"[Marin] Translation not available — using {original_lang} as-is")

        fetched = transcript.fetch()
        full_text = " ".join([entry.text for entry in fetched])

        print(f"[Marin] Transcript ready: {len(full_text)} chars")
        return full_text

    except ImportError:
        print("[Marin] Run: pip install youtube-transcript-api")
        return None
    except Exception as e:
        print(f"[Marin] Transcript fetch failed: {e}")
        return None

if __name__=="__main__":
    text = get_youtube_transcript("whats in the link https://youtu.be/NP1aZVpNGTo?si=yBpoWTy3v8qwRAAN")
    print(text)
