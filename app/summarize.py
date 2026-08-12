from pydantic import BaseModel

from .extract import CompanyData
from .llm import LLMError, call_json, format_data_block


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


def summarize(data: CompanyData, max_attempts: int = 3) -> SummaryResult:
    if not data.histories:
        raise SummaryError("No verified fields to summarize (tier is blocked).")
    user_prompt = format_data_block(data)
    try:
        summary, meta = call_json(
            system=SYSTEM,
            user_prompt=user_prompt,
            schema=Summary,
            max_attempts=max_attempts,
        )
    except LLMError as e:
        raise SummaryError(str(e))
    return SummaryResult(
        summary=summary,
        model=meta.model,
        input_tokens=meta.input_tokens,
        output_tokens=meta.output_tokens,
        cost_usd=meta.cost_usd,
        attempts=meta.attempts,
    )