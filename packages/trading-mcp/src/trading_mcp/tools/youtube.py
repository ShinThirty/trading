import asyncio
import re

from fastmcp import Context, FastMCP

mcp = FastMCP("youtube-tools")


@mcp.tool()
async def get_youtube_transcript(ctx: Context, url: str) -> str:
    """Get the transcript of a YouTube video.

    Extracts auto-generated or manual captions and returns the full text.
    Useful for analyzing financial commentary, earnings calls, or market analysis videos.

    url: YouTube video URL or video ID (e.g. 'https://www.youtube.com/watch?v=abc123'
      or just 'abc123').
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = url
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if m:
        video_id = m.group(1)

    api = YouTubeTranscriptApi()
    transcript = await asyncio.to_thread(api.fetch, video_id)
    full_text = " ".join(s.text for s in transcript.snippets)
    kind = "auto-generated" if transcript.is_generated else "manual"
    return f"**Video ID:** {video_id}\n**Language:** {transcript.language} ({kind})\n\n{full_text}"
