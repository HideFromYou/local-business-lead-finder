"""Website liveness check. Only does ordinary GET requests to public sites."""

import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

TIMEOUT = 10.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# A page on one of these is not the business's own website.
SOCIAL_HOSTS = (
    "facebook.com", "fb.com", "fb.me", "instagram.com", "linktr.ee", "twitter.com", "x.com",
    "tiktok.com", "youtube.com", "youtu.be", "linkedin.com", "pinterest.com", "beacons.ai",
    "bio.link", "wa.me",
)


@dataclass
class CheckResult:
    site_status: str  # alive / dead / social_only
    http_status: int | None = None
    error: str | None = None


def normalize_url(raw: str | None) -> str | None:
    """Trim, keep the first URL if several are given, add https:// when no scheme."""
    if not raw:
        return None
    url = raw.split(";")[0].strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url.lstrip("/")
    return url


def hostname(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_social(url: str) -> bool:
    host = hostname(url)
    return any(host == d or host.endswith("." + d) for d in SOCIAL_HOSTS)


async def check_url(client: httpx.AsyncClient, raw_url: str) -> CheckResult:
    url = normalize_url(raw_url)
    if url is None:
        return CheckResult("dead", error="empty url")
    if is_social(url):
        return CheckResult("social_only")

    # Retry once. If we had to add the scheme ourselves, the retry uses http://,
    # since some small sites have no HTTPS at all.
    attempts = [url]
    attempts.append("http://" + url[len("https://"):] if "://" not in raw_url.strip() else url)

    result = CheckResult("dead")
    for attempt in attempts:
        try:
            response = await client.get(attempt)
        except httpx.InvalidURL as e:
            return CheckResult("dead", error=f"invalid url: {e}")
        except httpx.HTTPError as e:
            result = CheckResult("dead", error=f"{type(e).__name__}: {e}".strip(": "))
            continue
        if response.status_code < 400:
            return CheckResult("alive", http_status=response.status_code)
        result = CheckResult("dead", http_status=response.status_code, error=f"HTTP {response.status_code}")
    return result


async def check_many(urls: dict[int, str], concurrency: int = 5,
                     transport: httpx.AsyncBaseTransport | None = None) -> dict[int, CheckResult]:
    """Check {id: url} with at most `concurrency` requests at once."""
    semaphore = asyncio.Semaphore(concurrency)
    results: dict[int, CheckResult] = {}

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}, transport=transport
    ) as client:

        async def worker(key: int, url: str) -> None:
            async with semaphore:
                results[key] = await check_url(client, url)

        await asyncio.gather(*(worker(k, u) for k, u in urls.items()))
    return results
