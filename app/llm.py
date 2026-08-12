import json
from typing import Type, TypeVar

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from .config import ANTHROPIC_API_KEY, SUMMARY_MODEL, cost_usd
from .extract import CompanyData

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMCallResult(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    attempts: int
    raw_text: str  # the final valid model output, kept for transcripts


def format_data_block(data: CompanyData) -> str:
    """The verified-data block every agent receives. Identical across agents so
    any disagreement is about interpretation, not different facts."""
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
    if data.changes:
        lines.append("")
        lines.append("Year-over-year changes already computed for you (do not recompute):")
        for c in data.changes:
            sign = "+" if c.abs_change >= 0 else ""
            lines.append(
                f"  {c.name} FY{c.from_year}->FY{c.to_year}: "
                f"{sign}{c.pct_change}% ({sign}{c.abs_change:,.0f} USD) "
                f"[accession {c.to_source.accession}]"
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
            t = t[:-3]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


def call_json(
    system: str,
    user_prompt: str,
    schema: Type[T],
    model: str = SUMMARY_MODEL,
    max_tokens: int = 1024,
    max_attempts: int = 3,
) -> tuple[T, LLMCallResult]:
    """Call the model, parse the reply into `schema`, retry on invalid output.

    Returns the validated object plus call metadata (tokens, cost, attempts,
    and the raw text so callers can store a transcript)."""
    if not ANTHROPIC_API_KEY:
        raise LLMError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_prompt}]
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        if resp.stop_reason == "max_tokens":
            raise LLMError(
                f"Response was cut off at the {max_tokens}-token limit before "
                "the JSON finished. Raise max_tokens for this agent."
            )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        cleaned = _strip_fences(raw)
        try:
            parsed = json.loads(cleaned)
            obj = schema.model_validate(parsed)
            meta = LLMCallResult(
                model=model,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                cost_usd=cost_usd(
                    model, resp.usage.input_tokens, resp.usage.output_tokens
                ),
                attempts=attempt,
                raw_text=cleaned,
            )
            return obj, meta
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

    raise LLMError(
        f"Model did not return valid JSON after {max_attempts} attempts. "
        f"Last error: {last_error}"
    )