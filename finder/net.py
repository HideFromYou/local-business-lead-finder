"""Network defaults shared by the Google and OpenStreetMap clients.

Some home networks advertise IPv6 but cannot reach Google over it. Python then waits for each
IPv6 address to time out, one after the other, and a search "hangs" for minutes. We therefore
connect over IPv4 by default (set FORCE_IPV4=0 in .env to allow IPv6) and give up on a connection
that is not established within a few seconds.
"""

import os

import httpx

CONNECT_TIMEOUT = 8.0


def transport() -> httpx.HTTPTransport:
    if os.getenv("FORCE_IPV4", "1") == "0":
        return httpx.HTTPTransport()
    return httpx.HTTPTransport(local_address="0.0.0.0")  # binding an IPv4 address forces IPv4


def timeout(total: float = 30.0) -> httpx.Timeout:
    return httpx.Timeout(total, connect=CONNECT_TIMEOUT)
