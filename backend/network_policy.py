"""Application-level offline network policy."""

from ipaddress import ip_address
from urllib.parse import urlparse


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_local_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    if host in _LOCAL_HOSTS:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def require_local_url(url: str) -> str:
    if not is_local_url(url):
        raise ValueError("Offline mode permits local loopback URLs only")
    return url
