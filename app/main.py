import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .edgar import EdgarClient, TickerNotFound, EdgarError
from .extract import CompanyData, assign_tier, extract_fields
from .summarize import summarize, SummaryError
from .debate import run_debate, DebateError
from . import storage

USER_AGENT = os.environ.get("EDGAR_USER_AGENT", "")

app = FastAPI(title="Investment Research")
storage.init_db()
_client: EdgarClient | None = None


def get_client() -> EdgarClient:
    global _client
    if _client is None:
        _client = EdgarClient(USER_AGENT)
    return _client


async def _fetch_company_data(ticker: str, trace=None) -> CompanyData:
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

    histories, margins, changes, missing = extract_fields(facts)
    tier = assign_tier(histories, missing)
    verified_count = sum(len(h.values) for h in histories)

    if trace is not None:
        from .trace import TraceStep
        trace.add(TraceStep(
            stage="fetch", label="Fetch from EDGAR", kind="tool", status="ok",
            detail=f"Pulled XBRL company facts for {ticker.upper()} from SEC EDGAR",
        ))
        trace.add(TraceStep(
            stage="verify", label="Verify against sources", kind="verify", status="ok",
            detail=f"{verified_count} figures tagged to filings; "
                   f"{len(missing)} field(s) not found",
            facts_verified=verified_count, unknown_count=len(missing),
            reads=["fetch"],
        ))
        trace.add(TraceStep(
            stage="tier", label="Escalation decision", kind="decision",
            status="ok" if tier == "confident" else ("warn" if tier == "partial" else "stop"),
            detail={
                "confident": "All fields found; proceed.",
                "partial": "Some fields unknown; proceed and mark them.",
                "blocked": "No verified data; stop and queue for review.",
            }[tier],
            tier=tier, reads=["verify"],
        ))

    return CompanyData(
        ticker=ticker.upper(),
        cik=str(facts.get("cik", "unknown")),
        entity_name=facts.get("entityName", "unknown"),
        histories=histories,
        margins=margins,
        changes=changes,
        unknown=missing,
        tier=tier,
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
    payload = {"company": data.as_display(), "result": result.model_dump()}
    run_id = storage.save_run(
        ticker=data.ticker,
        kind="summary",
        tier=data.tier,
        cost_usd=result.cost_usd,
        total_tokens=result.input_tokens + result.output_tokens,
        payload=payload,
    )
    return {"run_id": run_id, **payload}


@app.get("/api/debate/{ticker}")
async def debate(ticker: str):
    from .trace import Trace
    trace = Trace()
    data = await _fetch_company_data(ticker, trace=trace)
    if data.tier == "blocked":
        raise HTTPException(
            status_code=422,
            detail="Blocked: no verified data to debate for this ticker.",
        )
    try:
        result = run_debate(data, trace=trace)
    except DebateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    payload = {
        "company": data.as_display(),
        "debate": result.model_dump(),
        "trace": trace.model_dump(),
    }
    run_id = storage.save_run(
        ticker=data.ticker,
        kind="debate",
        tier=data.tier,
        cost_usd=result.total_cost_usd,
        total_tokens=result.total_tokens,
        payload=payload,
    )
    return {"run_id": run_id, **payload}


@app.get("/api/runs")
async def runs(limit: int = 50):
    return {"runs": storage.list_runs(limit=limit)}


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: int):
    run = storage.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")