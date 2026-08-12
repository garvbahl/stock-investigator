import json

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from .config import ANTHROPIC_API_KEY, SUMMARY_MODEL, cost_usd
from .extract import CompanyData


class Summary(BaseModel):
    overview: str
    revenue_trend: str
    margin_trend: str
    risks: list[str]
    sources: list[str]


class SummaryResult(BaseModel):
    summary: Summary
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    attempts: int


class SummaryError(Exception):
    pass


SYSTEM = (
    "You are a financial data summarizer for a learning tool. You are given "
    "verified figures already extracted from a company's SEC filings, including "
    "several years of history and margins that were already computed for you.\n"
    "Rules you must follow:\n"
    "1. Use only the numbers provided. Never introduce a figure that is not in "
    "the provided data.\n"
    "2. Do NOT do any arithmetic. Do not compute ratios, percentages, growth "
    "rates, or margins yourself. Every margin you may mention is already given "
    "to you. If a figure you want is not provided, say the data was not "
    "available instead of calculating it.\n"
    "3. For trends, describe the direction across the years given (rising, "
    "falling, flat) using the provided yearly values. Do not invent values for "
    "years not provided.\n"
    "4. If a field is listed as unknown, do not mention it or guess it.\n"
    "5. Do not give investment advice or say whether to buy or sell.\n"
    "6. In 'sources', list the accession numbers of the filings the figures "
    "came from.\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences, matching "
    "exactly these keys: overview (string), revenue_trend (string), "
    "margin_trend (string), risks (array of strings), sources (array of strings)."
)


def _build_user_prompt(data: CompanyData) -> str:
    lines = [f"Company: {data.entity_name} (ticker {data.ticker}, CIK {data.cik})"]
    lines.append(f"Verification tier: {data.tier}")
    lines.append("")
    lines.append("Verified figures by fiscal year (oldest to newest):")
    for h in data.histories:
        lines.append(f"  {h.name}:")
        for vf in h.values:
            s = vf.source
            lines.append(
                f"    FY{s.fiscal_year}: {vf.value:,.0f} {vf.unit} "
                f"[{s.document}, period ending {s.period_end}, accession {s.accession}]"
            )
    if data.margins:
        lines.append("")
        lines.append("Margins already computed for you (do not recompute):")
        for m in data.margins:
            lines.append(
                f"  FY{m.fiscal_year} {m.name}: {m.value_pct}% "
                f"(= {m.numerator} / {m.denominator})"
            )
    if data.unknown:
        lines.append("")
        lines.append("Unknown (not found, do not reference):")
        for u in data.unknown:
            lines.append(f"  - {u.name}")
    return "\n".join(lines)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


def summarize(data: CompanyData, max_attempts: int = 3) -> SummaryResult:
    if not ANTHROPIC_API_KEY:
        raise SummaryError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
    if not data.histories:
        raise SummaryError("No verified fields to summarize (tier is blocked).")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    user_prompt = _build_user_prompt(data)
    messages = [{"role": "user", "content": user_prompt}]
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        resp = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=messages,
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        cleaned = _strip_fences(raw)
        try:
            parsed = json.loads(cleaned)
            summary = Summary.model_validate(parsed)
            return SummaryResult(
                summary=summary,
                model=SUMMARY_MODEL,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                cost_usd=cost_usd(
                    SUMMARY_MODEL, resp.usage.input_tokens, resp.usage.output_tokens
                ),
                attempts=attempt,
            )
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = str(e)
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"That was not valid. Error: {last_error}\n"
                        "Return ONLY the JSON object with the required keys, "
                        "nothing else."
                    ),
                }
            )

    raise SummaryError(
        f"Model did not return valid JSON after {max_attempts} attempts. "
        f"Last error: {last_error}"
    )