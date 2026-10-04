import asyncio

import httpx
import pytest

from finder.checker import check_many, check_url, is_social, normalize_url


@pytest.mark.parametrize("raw,expected", [
    ("example.gr", "https://example.gr"),
    ("  http://example.gr/a  ", "http://example.gr/a"),
    ("https://a.gr;https://b.gr", "https://a.gr"),
    ("", None),
    (None, None),
])
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://www.facebook.com/shop", True),
    ("https://m.facebook.com/shop", True),
    ("instagram.com/shop", False),  # not normalized yet; is_social expects a full URL
    ("https://instagram.com/shop", True),
    ("https://linktr.ee/shop", True),
    ("https://notfacebook.com", False),
    ("https://facebook.com.evil.gr", False),
    ("https://myshop.gr", False),
])
def test_is_social(url, expected):
    assert is_social(url) is expected


def run(handler, url, **kw):
    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as c:
            return await check_url(c, url)
    return asyncio.run(go())


def test_alive_on_200():
    r = run(lambda req: httpx.Response(200), "https://a.gr")
    assert (r.site_status, r.http_status) == ("alive", 200)


def test_redirect_to_200_is_alive():
    def handler(req):
        if req.url.path == "/":
            return httpx.Response(301, headers={"location": "/home"})
        return httpx.Response(200)
    assert run(handler, "https://a.gr").site_status == "alive"


@pytest.mark.parametrize("code", [404, 500])
def test_error_status_is_dead(code):
    r = run(lambda req: httpx.Response(code), "https://a.gr")
    assert (r.site_status, r.http_status) == ("dead", code)


def test_connection_error_is_dead_with_text():
    def handler(req):
        raise httpx.ConnectError("Name or service not known")
    r = run(handler, "https://a.gr")
    assert r.site_status == "dead" and "ConnectError" in r.error


def test_retry_once_then_success():
    calls = []
    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200)
    assert run(handler, "https://a.gr").site_status == "alive"
    assert len(calls) == 2


def test_missing_scheme_falls_back_to_http():
    def handler(req):
        if req.url.scheme == "https":
            raise httpx.ConnectError("no tls")
        return httpx.Response(200)
    assert run(handler, "a.gr").site_status == "alive"


def test_social_makes_no_request():
    def handler(req):
        raise AssertionError("should not be called")
    assert run(handler, "https://facebook.com/shop").site_status == "social_only"


def test_check_many_limits_concurrency():
    active = peak = 0

    async def handler(req):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200)

    urls = {i: f"https://s{i}.gr" for i in range(12)}
    results = asyncio.run(check_many(urls, concurrency=3, transport=httpx.MockTransport(handler)))
    assert len(results) == 12 and peak <= 3
