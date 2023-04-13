import time
import os
from wavelink.ext import spotify
from urllib.parse import urlparse


__all__ = [
    'format_time',
    'is_url',
    'is_playlist',
    'ROOT'
]

ROOT = os.getcwd()


def format_time(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


def is_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def is_playlist(search: str, decode: dict | None):
    types = [spotify.SpotifySearchType.album, spotify.SpotifySearchType.playlist]
    yt_pattern = 'https://youtube.com/playlist?list='

    if (decode and decode['type'] in types) or yt_pattern in search:
        return True
