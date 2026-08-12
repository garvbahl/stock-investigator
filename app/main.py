import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .edgar import EdgarClient, TickerNotFound, EdgarError
from .extract import CompanyData, assign_tier, extract_fields
from .summarize import summarize, SummaryError

USER_AGENT = os.environ.get("EDGAR_USER_AGENT", "")

app = FastAPI(title="Investment Research - Stage 1")
_client: EdgarClient | None = None


def get_client() -> EdgarClient:
    global _client
    if _client is None:
        _client = EdgarClient(USER_AGENT)
    return _client


async def _fetch_company_data(ticker: str) -> CompanyData:
    try:
        client = get_client()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    try:
        facts = await client.fetch_company_facts(ticker)
    except TickerNotFound:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found in EDGAR")
    except EdgarError as e:
        raise HTTPException(status_code=502, detail=f"EDGAR error: {e}")

    histories, margins, missing = extract_fields(facts)
    return CompanyData(
        ticker=ticker.upper(),
        cik=str(facts.get("cik", "unknown")),
        entity_name=facts.get("entityName", "unknown"),
        histories=histories,
        margins=margins,
        unknown=missing,
        tier=assign_tier(histories, missing),
    )


@app.get("/api/company/{ticker}")
async def company(ticker: str):
    data = await _fetch_company_data(ticker)
    return data.as_display()


@app.get("/api/summary/{ticker}")
async def summary(ticker: str):
    data = await _fetch_company_data(ticker)
    if data.tier == "blocked":
        raise HTTPException(
            status_code=422,
            detail="Blocked: no verified data to summarize for this ticker.",
        )
    try:
        result = summarize(data)
    except SummaryError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"company": data.as_display(), "result": result.model_dump()}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")