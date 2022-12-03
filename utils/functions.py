from datetime import datetime
import time
import logging
import os
from wavelink.ext import spotify
from urllib.parse import urlparse


__all__ = ['format_time', 'is_url', 'create_logger', 'is_playlist', 'ROOT']

ROOT = os.getcwd()


def format_time(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


def is_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def create_logger(filename: str):
    root = os.path.join(ROOT, 'logs')
    logs = os.listdir(root)

    if len(logs) > 7:
        oldest_log = (datetime.now(), None)

        for file in logs:
            fullname = os.path.join(root, file)
            creation_time = datetime.fromtimestamp(os.path.getctime(fullname))

            if creation_time < oldest_log[0]:
                oldest_log = (creation_time, fullname)

        os.remove(oldest_log[1])

    formatter = logging.Formatter('%(asctime)s | %(message)s', datefmt='%d/%m/%y %H:%M:%S')

    handler = logging.FileHandler(os.path.join(root, f'{filename}.log'), mode='a')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)

    logger = logging.getLogger(__name__)
    logger.addHandler(handler)

    return logger


def is_playlist(search: str, decode: dict | None):
    types = [spotify.SpotifySearchType.album, spotify.SpotifySearchType.playlist]
    yt_pattern = 'https://youtube.com/playlist?list='

    if (decode and decode['type'] in types) or yt_pattern in search:
        return True
