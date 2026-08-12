from pydantic import BaseModel

from .extract import CompanyData
from .llm import LLMError, call_json, format_data_block


class Claim(BaseModel):
    point: str            # the argument being made
    plain_language: str   # the same point explained simply for a beginner
    figures: list[str]    # supporting figures, each as "field FYxxxx: value"
    accessions: list[str]  # accession numbers backing those figures


class SideCase(BaseModel):
    thesis: str           # one-sentence overall stance
    plain_summary: str    # the thesis restated in simple, jargon-free terms
    claims: list[Claim]


class Disagreement(BaseModel):
    topic: str            # what they disagree about
    plain_language: str   # what this disagreement means, in simple terms
    bull_view: str
    bear_view: str
    resolving_data: str   # what data would settle it


class RefereeReport(BaseModel):
    disagreements: list[Disagreement]
    what_cannot_be_known: list[str]  # limits of the current data


class AgentRun(BaseModel):
    role: str             # "bull" | "bear" | "referee"
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    attempts: int
    transcript: str       # the raw JSON the agent returned


class DebateResult(BaseModel):
    bull: SideCase
    bear: SideCase
    referee: RefereeReport
    runs: list[AgentRun]
    total_cost_usd: float
    total_tokens: int


class DebateError(Exception):
    pass


_SHARED_RULES = (
    "You may use ONLY the verified figures provided. Never introduce a number "
    "that is not in the data. Do NOT do ANY arithmetic yourself: do not compute "
    "growth rates, percentage changes, differences, ratios, or margins. All "
    "margins AND all year-over-year changes (both percent and dollar amounts) "
    "are already provided to you above; cite those directly and never calculate "
    "your own. If a number you want is not provided, say so instead of computing "
    "it. Do not reference any field listed as unknown. Do not give buy or sell "
    "advice. For every figure you cite, include its accession number so the "
    "claim is traceable. Make at most 4 claims, and keep each point to one or "
    "two sentences.\n"
    "This tool is for beginners who are new to investing. For every claim, also "
    "provide a 'plain_language' version that explains the same point in simple, "
    "everyday words, avoiding finance jargon (or briefly defining any term you "
    "must use). Imagine explaining it to a smart friend who has never read a "
    "financial statement."
)

BULL_SYSTEM = (
    "You are the Bull. Argue the STRONGEST honest case FOR this stock using the "
    "verified data. Be persuasive but truthful; do not exaggerate beyond what "
    "the numbers support.\n" + _SHARED_RULES + "\n"
    "Respond with ONLY a JSON object with keys: thesis (string), plain_summary "
    "(string, the thesis in simple beginner terms), claims (array of objects "
    "each with: point (string), plain_language (string), figures (array of "
    "strings), accessions (array of strings))."
)

BEAR_SYSTEM = (
    "You are the Bear. Argue the STRONGEST honest case AGAINST this stock using "
    "the verified data. Be persuasive but truthful; do not invent weaknesses the "
    "numbers do not support.\n" + _SHARED_RULES + "\n"
    "Respond with ONLY a JSON object with keys: thesis (string), plain_summary "
    "(string, the thesis in simple beginner terms), claims (array of objects "
    "each with: point (string), plain_language (string), figures (array of "
    "strings), accessions (array of strings))."
)

REFEREE_SYSTEM = (
    "You are the Referee. You do NOT pick a winner and you do NOT give advice. "
    "Both the Bull and the Bear saw the SAME verified data, so any disagreement "
    "is about interpretation, not facts. Your job: identify the specific points "
    "where they disagree, state each side's view fairly, and say what additional "
    "data would resolve each disagreement. Also list what genuinely cannot be "
    "known from the current data.\n" + _SHARED_RULES + "\n"
    "This tool is for beginners, so for each disagreement include a "
    "'plain_language' field explaining in simple terms what the two sides are "
    "really arguing about and why it matters.\n"
    "Respond with ONLY a JSON object with keys: disagreements (array of objects "
    "each with: topic (string), plain_language (string), bull_view (string), "
    "bear_view (string), resolving_data (string)), what_cannot_be_known (array "
    "of strings)."
)


def _fmt_side(label: str, case: SideCase) -> str:
    lines = [f"{label} thesis: {case.thesis}", f"{label} claims:"]
    for c in case.claims:
        lines.append(f"  - {c.point} (figures: {', '.join(c.figures) or 'none'})")
    return "\n".join(lines)


def run_debate(data: CompanyData, max_attempts: int = 3, trace=None) -> DebateResult:
    if not data.histories:
        raise DebateError("No verified data to debate (tier is blocked).")

    data_block = format_data_block(data)
    runs: list[AgentRun] = []

    try:
        bull, bull_meta = call_json(BULL_SYSTEM, data_block, SideCase,
                                    max_tokens=2048, max_attempts=max_attempts)
        runs.append(_to_run("bull", bull_meta))
        _trace_agent(trace, "bull", "Bull agent",
                     f"Argued the case FOR using {len(bull.claims)} claims", bull_meta,
                     reads=["verify"])

        bear, bear_meta = call_json(BEAR_SYSTEM, data_block, SideCase,
                                    max_tokens=2048, max_attempts=max_attempts)
        runs.append(_to_run("bear", bear_meta))
        _trace_agent(trace, "bear", "Bear agent",
                     f"Argued the case AGAINST using {len(bear.claims)} claims", bear_meta,
                     reads=["verify"])

        referee_prompt = (
            data_block
            + "\n\n--- BULL CASE ---\n" + _fmt_side("Bull", bull)
            + "\n\n--- BEAR CASE ---\n" + _fmt_side("Bear", bear)
        )
        referee, ref_meta = call_json(REFEREE_SYSTEM, referee_prompt, RefereeReport,
                                      max_tokens=2048, max_attempts=max_attempts)
        runs.append(_to_run("referee", ref_meta))
        _trace_agent(trace, "referee", "Referee agent",
                     f"Read both cases; found {len(referee.disagreements)} "
                     f"disagreement(s), no verdict", ref_meta,
                     reads=["agent:bull", "agent:bear"])
    except LLMError as e:
        raise DebateError(str(e))

    return DebateResult(
        bull=bull,
        bear=bear,
        referee=referee,
        runs=runs,
        total_cost_usd=sum(r.cost_usd for r in runs),
        total_tokens=sum(r.input_tokens + r.output_tokens for r in runs),
    )


def _trace_agent(trace, key, label, detail, meta, reads):
    if trace is None:
        return
    from .trace import TraceStep
    trace.add(TraceStep(
        stage=f"agent:{key}",
        label=label,
        kind="agent",
        status="ok" if meta.attempts == 1 else "warn",
        detail=detail + ("" if meta.attempts == 1 else f" (needed {meta.attempts} attempts)"),
        model=meta.model,
        input_tokens=meta.input_tokens,
        output_tokens=meta.output_tokens,
        cost_usd=meta.cost_usd,
        attempts=meta.attempts,
        reads=reads,
    ))


def _to_run(role: str, meta) -> AgentRun:
    return AgentRun(
        role=role,
        model=meta.model,
        input_tokens=meta.input_tokens,
        output_tokens=meta.output_tokens,
        cost_usd=meta.cost_usd,
        attempts=meta.attempts,
        transcript=meta.raw_text,
    )