import time
from urllib.parse import urlparse


def format_time(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


def is_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False
