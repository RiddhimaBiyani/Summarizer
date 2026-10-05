"""SSRF protection and safe HTTP client for Digestif."""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class SSRFProtectionError(ValueError):
    """Raised when a URL resolves to a forbidden private, loopback, or metadata address."""

    pass


def is_ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
        for net in BLOCKED_IP_NETWORKS:
            if ip in net:
                return True
        return False
    except ValueError:
        return True


def validate_url_safety(url: str) -> str:
    """Validates that a URL is http/https and does not resolve to private/local/metadata networks."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFProtectionError(
            f"Forbidden URL scheme '{parsed.scheme}': only http and https are allowed"
        )

    hostname = parsed.hostname
    if not hostname:
        raise SSRFProtectionError(f"Invalid URL without hostname: {url}")

    # Check if host is direct IP
    try:
        ipaddress.ip_address(hostname)
        if is_ip_blocked(hostname):
            raise SSRFProtectionError(f"Blocked access to private/internal IP address: {hostname}")
        return url
    except ValueError:
        pass

    # Resolve DNS to IPs
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFProtectionError(f"Could not resolve hostname '{hostname}': {e}") from e

    for family, _, _, _, sockaddr in addr_info:
        ip_str = str(sockaddr[0])
        if is_ip_blocked(ip_str):
            raise SSRFProtectionError(f"Hostname '{hostname}' resolves to blocked IP: {ip_str}")

    return url


async def safe_fetch(
    url: str,
    max_redirects: int = 5,
    timeout: float = 20.0,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Safely fetches a URL verifying each redirect hop against SSRF rules and enforcing size caps."""
    current_url = url
    client_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        client_headers.update(headers)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        redirect_count = 0
        while redirect_count <= max_redirects:
            validate_url_safety(current_url)

            # Stream and enforce max_bytes DURING download, not after -- a plain
            # client.get() buffers the entire body into memory first, so a huge or
            # unbounded response would exhaust memory before the size check ever ran.
            async with client.stream("GET", current_url, headers=client_headers) as response:
                if response.is_redirect:
                    redirect_count += 1
                    location = response.headers.get("Location")
                    if not location:
                        break
                    current_url = str(response.url.join(location))
                    continue

                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > max_bytes:
                        raise ValueError(
                            f"Response from {current_url} exceeded maximum permitted "
                            f"size {max_bytes} bytes"
                        )
                response._content = bytes(chunks)
                return response

        raise SSRFProtectionError(f"Exceeded max redirects ({max_redirects}) for {url}")
