import time
import os
import re
from datetime import datetime
from urllib.parse import urlparse
from typing import NamedTuple

from wavelink.ext import spotify


__all__ = [
    'ROOT',
    'SUPPORTED_URL_PATTERNS',
    'format_time',
    'is_url',
    'is_playlist',
    'is_spotify_url',
    'is_youtube_url',
    'OldestLog'
]

ROOT = os.getcwd()

SUPPORTED_URL_PATTERNS = [
    "https://www.youtube.com/playlist?list=ID_DA_PLAYLIST",
    "https://www.youtube.com/watch?v=ID_DO_ViDEO",
    "https://youtu.be/ID_DO_ViDEO",
    "https://open.spotify.com/track/ID_DA_MUSICA",
    "https://open.spotify.com/playlist/ID_DA_PLAYLIST",
    "https://open.spotify.com/album/ID_DO_ALBUM"
]


class OldestLog(NamedTuple):
    """Named tuple para armazenar log mais antigo."""
    creation_date: datetime
    fullname: str


def format_time(seconds: float) -> str:
    """
    Formata segundos para data.

    :param seconds: Tempo em segundos
    :return: String formatada
    """
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


def is_url(url: str) -> bool:
    """
    Verifica se é uma URL.

    :param url: String para ser checada
    :return: True se for URL, do contrário False
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def is_supported_url(url: str) -> bool:
    """
    Verifica se é uma URL válida.

    :param url: URL como string
    :return: True se for uma URL suportada, do contrário False
    """
    if is_spotify_url(url) or is_youtube_url(url):
        return True

    return False


def is_spotify_url(url: str) -> bool:
    """
    Verifica se é uma URL do Spotify.

    :param url: URL como string
    :return: True se for Spotify, do contrário False
    """
    match = re.match(r'(^http(s)?://(www.)?open.spotify.com/(track|playlist|album)/\S+$)', url)
    return bool(match)


def is_youtube_url(url: str) -> bool:
    """
    Verifica se é uma URL do YouTube.

    :param url: URL como string
    :return: True se for YouTube, do contrário False
    """
    match = re.match(r'(^http(s)?://(www.)?(youtube\.com/(watch\?v=|playlist\?list=)|youtu\.be/)\S+$)', url)
    return bool(match)


def is_playlist(url: str, spotify_decode: dict | None) -> bool:
    """
    Verifica se é a URL é uma playlist.

    :param url: URL como string
    :param spotify_decode: Decode do Spotify caso haja
    :return: True se for playlist, do contrário False
    """
    types = [spotify.SpotifySearchType.album, spotify.SpotifySearchType.playlist]

    is_spotify_playlist = spotify_decode and spotify_decode['type'] in types
    is_youtube_playlist = bool(re.match(r'(^http(s)?://(www.)?youtube\.com/playlist\?list=\S+$)', url))

    if is_spotify_playlist or is_youtube_playlist:
        return True

    return False


if __name__ == '__main__':
    urls = [
        'https://open.spotify.com/track/76Je5Wklky23mVoxiRszcN?si=3166d36247644cbe',
        'https://open.spotify.com/playlist/37i9dQZF1DWZUozJiHy44Y?si=045ef14b52b5438e',
        'https://open.spotify.com/album/21jF5jlMtzo94wbxmJ18aa?si=cDfgzRpcTES-ad5OoTiJvg',
        'http://open.spotify.com/playlist/21jF5jlMtzo94wbxmJ18aa?si=cDfgzRpcTES-ad5OoTiJvg',
        'https://youtube.com/playlist?list=PLdv7EOMbqaGfrXTzVm5ge-p4Cbk8RWxLu',
        'https://www.youtube.com/watch?v=SbAHzNRYdAY&list=PLdv7EOMbqaGfrXTzVm5ge-p4Cbk8RWxLu&index=1&pp=gAQBiAQB8AUB',
        'https://youtu.be/SbAHzNRYdAY',
        'https://www.youtube.com/watch?v=C7OQHIpDlvA',
        'https://open.spotify.com/playlist/37i9dQZF1DXcmaoFmN75bi?si=3d1e5be6b9404288'
    ]

    for url in urls:
        print(url, is_playlist(url, None))
