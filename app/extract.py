from typing import Literal, Optional

from pydantic import BaseModel


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


class UnknownField(BaseModel):
    """A field we looked for and did not find. It stays unknown end to end."""
    name: str
    reason: str = "not reported in retrieved filings"


Tier = Literal["confident", "partial", "blocked"]


class CompanyData(BaseModel):
    ticker: str
    cik: str
    entity_name: str
    fields: list[VerifiedField]
    unknown: list[UnknownField]
    tier: Tier

    def as_display(self) -> dict:
        return self.model_dump()


# Map a friendly field name to the XBRL concepts that may carry it, in
# preference order. Companies tag the "same" number under different concepts,
# so we try several and record which one actually supplied the value.
CONCEPT_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
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


def _latest_annual_fact(concept_block: dict) -> Optional[dict]:
    """Pick the most recent annual (10-K, full year) USD fact for a concept."""
    units = concept_block.get("units", {})
    usd = units.get("USD")
    if not usd:
        return None
    annual = [
        f for f in usd
        if f.get("form") == "10-K" and f.get("fp") == "FY" and "start" in f
    ]
    if not annual:
        annual = [f for f in usd if f.get("form") == "10-K"]
    if not annual:
        return None
    return max(annual, key=lambda f: f.get("end", ""))


def extract_fields(facts: dict) -> tuple[list[VerifiedField], list[UnknownField]]:
    entity_facts = facts.get("facts", {}).get("us-gaap", {})
    found: list[VerifiedField] = []
    missing: list[UnknownField] = []

    for name, concepts in CONCEPT_MAP.items():
        picked = None
        used_concept = None
        for concept in concepts:
            block = entity_facts.get(concept)
            if not block:
                continue
            fact = _latest_annual_fact(block)
            if fact is not None:
                picked = fact
                used_concept = concept
                break
        if picked is None:
            missing.append(UnknownField(name=name))
            continue
        found.append(
            VerifiedField(
                name=name,
                value=float(picked["val"]),
                unit="USD",
                source=SourceRef(
                    document=picked.get("form", "unknown"),
                    accession=picked.get("accn", "unknown"),
                    period_end=picked.get("end", "unknown"),
                    fiscal_year=picked.get("fy"),
                    fiscal_period=picked.get("fp"),
                    filed=picked.get("filed"),
                    xbrl_concept=used_concept or "",
                ),
            )
        )
    return found, missing


def assign_tier(found: list[VerifiedField], missing: list[UnknownField]) -> str:
    if not found:
        return "blocked"
    if missing:
        return "partial"
    return "confident"