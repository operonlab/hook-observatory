"""SSRF protection — block requests to internal/private networks."""

import ipaddress
import socket
from urllib.parse import urlparse

from src.shared.errors import BadRequestError

# Private/reserved IP ranges
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Private A
    ipaddress.ip_network("172.16.0.0/12"),      # Private B
    ipaddress.ip_network("192.168.0.0/16"),     # Private C
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / AWS metadata
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 private
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]

_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def validate_url(url: str) -> str:
    """Validate URL is not targeting internal/private networks.

    Returns the validated URL. Raises BadRequestError if blocked.
    """
    parsed = urlparse(url)

    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        raise BadRequestError("URL must use http or https scheme")

    hostname = parsed.hostname
    if not hostname:
        raise BadRequestError("URL must have a valid hostname")

    # Block known internal hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise BadRequestError("URL targets a blocked hostname")

    # Resolve hostname and check IP
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _, _, _, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    raise BadRequestError("URL resolves to a private/internal network address")
    except socket.gaierror as exc:
        raise BadRequestError(f"Cannot resolve hostname: {hostname}") from exc

    return url
