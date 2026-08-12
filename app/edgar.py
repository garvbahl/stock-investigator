import asyncio
import time

import httpx

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
XBRL_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class EdgarError(Exception):
    pass


class TickerNotFound(EdgarError):
    pass


class RateLimiter:
    def __init__(self, min_interval: float = 0.15):
        self._min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last = time.monotonic()


class EdgarClient:
    def __init__(self, user_agent: str):
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "EDGAR requires a User-Agent with contact email, e.g. "
                "'MyProject you@example.com'"
            )
        self._headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._limiter = RateLimiter()
        self._ticker_cache: dict[str, str] | None = None

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        for attempt in range(4):
            await self._limiter.wait()
            resp = await client.get(url, headers=self._headers, timeout=30)
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code == 404:
                raise TickerNotFound(f"Not found at {url}")
            resp.raise_for_status()
            return resp
        raise EdgarError(f"Rate limited repeatedly on {url}")

    async def _load_ticker_map(self, client: httpx.AsyncClient) -> dict[str, str]:
        if self._ticker_cache is not None:
            return self._ticker_cache
        resp = await self._get(client, SEC_TICKERS_URL)
        raw = resp.json()
        mapping = {}
        for row in raw.values():
            cik = str(row["cik_str"]).zfill(10)
            mapping[row["ticker"].upper()] = cik
        self._ticker_cache = mapping
        return mapping

    async def resolve_cik(self, client: httpx.AsyncClient, ticker: str) -> str:
        mapping = await self._load_ticker_map(client)
        cik = mapping.get(ticker.upper())
        if cik is None:
            raise TickerNotFound(f"No CIK for ticker '{ticker}'")
        return cik

    async def fetch_company_facts(self, ticker: str) -> dict:
        async with httpx.AsyncClient() as client:
            cik = await self.resolve_cik(client, ticker)
            resp = await self._get(client, XBRL_FACTS_URL.format(cik=cik))
            return resp.json()