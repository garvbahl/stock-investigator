from typing import Literal, Optional

from pydantic import BaseModel

MAX_YEARS = 4  # how many recent annual values to keep per field


class SourceRef(BaseModel):
    document: str          # e.g. "10-K" or "10-Q"
    accession: str         # SEC accession number, uniquely identifies the filing
    period_end: str        # end date the number covers, e.g. "2023-09-30"
    fiscal_year: Optional[int] = None
    fiscal_period: Optional[str] = None
    filed: Optional[str] = None
    xbrl_concept: str = ""  # the us-gaap tag the value came from


class VerifiedField(BaseModel):
    """A number we found in a filing, tagged to exactly where it came from."""
    name: str
    value: float
    unit: str
    source: SourceRef


class FieldHistory(BaseModel):
    """Several years of one field, most recent last."""
    name: str
    values: list[VerifiedField]

    @property
    def latest(self) -> VerifiedField:
        return self.values[-1]


class DerivedMargin(BaseModel):
    """A ratio computed in code from two verified fields for the same year.

    It is not read from a filing, but every input is, so it is verifiable:
    both source references are carried so a checker can reproduce the number.
    """
    name: str
    fiscal_year: int
    value_pct: float
    numerator: str
    denominator: str
    numerator_source: SourceRef
    denominator_source: SourceRef


class DerivedChange(BaseModel):
    """Year-over-year change for one field, computed in code from two verified
    values. Both source references are carried so the number is reproducible."""
    name: str            # field name, e.g. "revenue"
    from_year: int
    to_year: int
    from_value: float
    to_value: float
    abs_change: float    # to_value - from_value
    pct_change: float    # percent change, rounded
    from_source: SourceRef
    to_source: SourceRef


class UnknownField(BaseModel):
    """A field we looked for and did not find. It stays unknown end to end."""
    name: str
    reason: str = "not reported in retrieved filings"


Tier = Literal["confident", "partial", "blocked"]


class CompanyData(BaseModel):
    ticker: str
    cik: str
    entity_name: str
    histories: list[FieldHistory]
    margins: list[DerivedMargin]
    changes: list[DerivedChange]
    unknown: list[UnknownField]
    tier: Tier

    def as_display(self) -> dict:
        return self.model_dump()


CONCEPT_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
}

# Which margins to compute, as (name, numerator_field, denominator_field).
MARGIN_SPECS: list[tuple[str, str, str]] = [
    ("gross_margin", "gross_profit", "revenue"),
    ("operating_margin", "operating_income", "revenue"),
    ("net_margin", "net_income", "revenue"),
]


def _period_year(fact: dict) -> Optional[int]:
    """The fiscal year a number COVERS, taken from its period-end date.

    A 10-K reports the current year plus prior-year comparatives, and every one
    of those facts carries the same 'fy' (the filing's year). So we must derive
    the year from 'end', not from 'fy', or comparatives get mislabeled.
    """
    end = fact.get("end", "")
    if len(end) >= 4 and end[:4].isdigit():
        return int(end[:4])
    return None


def _annual_facts(concept_block: dict) -> list[dict]:
    """Return annual (full-year 10-K) USD facts, oldest first, deduped by the
    period-end year, keeping the latest-filed value for each year."""
    usd = concept_block.get("units", {}).get("USD")
    if not usd:
        return []
    annual = [
        f for f in usd
        if f.get("form") == "10-K" and f.get("fp") == "FY" and "start" in f
    ]
    if not annual:
        annual = [f for f in usd if f.get("form") == "10-K"]
    by_year: dict = {}
    for f in annual:
        py = _period_year(f)
        if py is None:
            continue
        prev = by_year.get(py)
        if prev is None or f.get("filed", "") > prev.get("filed", ""):
            by_year[py] = f
    return [by_year[y] for y in sorted(by_year)]


def _to_verified(name: str, fact: dict, concept: str) -> VerifiedField:
    return VerifiedField(
        name=name,
        value=float(fact["val"]),
        unit="USD",
        source=SourceRef(
            document=fact.get("form", "unknown"),
            accession=fact.get("accn", "unknown"),
            period_end=fact.get("end", "unknown"),
            fiscal_year=_period_year(fact),
            fiscal_period=fact.get("fp"),
            filed=fact.get("filed"),
            xbrl_concept=concept,
        ),
    )


def extract_fields(
    facts: dict,
) -> tuple[list[FieldHistory], list[DerivedMargin], list[DerivedChange], list[UnknownField]]:
    entity_facts = facts.get("facts", {}).get("us-gaap", {})
    histories: list[FieldHistory] = []
    missing: list[UnknownField] = []
    # year -> field_name -> VerifiedField, used to compute margins per year
    by_year_field: dict[int, dict[str, VerifiedField]] = {}

    for name, concepts in CONCEPT_MAP.items():
        # A company can change which XBRL tag it uses for the same line item
        # over time (e.g. a new revenue concept in later filings). So we merge
        # facts from ALL candidate concepts, keyed by period-end year, keeping
        # the most recently filed value for each year. Each value still records
        # which concept it came from, so provenance is preserved.
        merged: dict[int, tuple[dict, str]] = {}  # year -> (fact, concept)
        for concept in concepts:
            block = entity_facts.get(concept)
            if not block:
                continue
            for fact in _annual_facts(block):
                py = _period_year(fact)
                if py is None:
                    continue
                existing = merged.get(py)
                if existing is None or fact.get("filed", "") > existing[0].get("filed", ""):
                    merged[py] = (fact, concept)
        if not merged:
            missing.append(UnknownField(name=name))
            continue

        ordered_years = sorted(merged)[-MAX_YEARS:]
        verified = [
            _to_verified(name, merged[y][0], merged[y][1]) for y in ordered_years
        ]
        histories.append(FieldHistory(name=name, values=verified))
        for vf in verified:
            fy = vf.source.fiscal_year
            if fy is not None:
                by_year_field.setdefault(fy, {})[name] = vf

    margins = _compute_margins(by_year_field)
    changes = _compute_changes(histories)
    return histories, margins, changes, missing


def _compute_changes(histories: list[FieldHistory]) -> list[DerivedChange]:
    """Year-over-year change per field, between each consecutive pair of years."""
    out: list[DerivedChange] = []
    for h in histories:
        vals = h.values  # already oldest-first
        for prev, curr in zip(vals, vals[1:]):
            if prev.value == 0:
                continue
            fy_from = prev.source.fiscal_year
            fy_to = curr.source.fiscal_year
            if fy_from is None or fy_to is None:
                continue
            out.append(
                DerivedChange(
                    name=h.name,
                    from_year=fy_from,
                    to_year=fy_to,
                    from_value=prev.value,
                    to_value=curr.value,
                    abs_change=curr.value - prev.value,
                    pct_change=round((curr.value - prev.value) / prev.value * 100, 2),
                    from_source=prev.source,
                    to_source=curr.source,
                )
            )
    return out


def _compute_margins(
    by_year_field: dict[int, dict[str, VerifiedField]],
) -> list[DerivedMargin]:
    out: list[DerivedMargin] = []
    for fy in sorted(by_year_field):
        fields = by_year_field[fy]
        for name, num_key, den_key in MARGIN_SPECS:
            num = fields.get(num_key)
            den = fields.get(den_key)
            if num is None or den is None or den.value == 0:
                continue
            out.append(
                DerivedMargin(
                    name=name,
                    fiscal_year=fy,
                    value_pct=round(num.value / den.value * 100, 2),
                    numerator=num_key,
                    denominator=den_key,
                    numerator_source=num.source,
                    denominator_source=den.source,
                )
            )
    return out


def assign_tier(
    histories: list[FieldHistory], missing: list[UnknownField]
) -> str:
    if not histories:
        return "blocked"
    if missing:
        return "partial"
    return "confident"