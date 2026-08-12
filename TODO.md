# TODO / Future Work

Ideas and known limitations, kept here so they are tracked rather than forgotten.

## Real risk analysis (from filing narrative text)

Right now the summarizer only receives XBRL numbers, so its "risks" section
can only describe what the numbers show (a revenue dip, rising liabilities).
Actual risk factors live in the narrative text of a 10-K, in the "Item 1A.
Risk Factors" section, not in the structured data.

To do real risk analysis:

- Fetch the filing's primary document (the 10-K HTML/text), not just the
  XBRL facts. EDGAR exposes this via the submissions/filing-index endpoints.
- Extract the "Item 1A. Risk Factors" section.
- Feed that text to an agent as its own verified source, with the same rule:
  every risk cited must trace back to a span in the source document.
- Keep the source reference model (document + section) so a risk is
  verifiable the same way a number is.

Open question to resolve first: how to verify prose claims against a source
the way we verify numbers. Exact-match works for numbers; for text we likely
need span/quote matching rather than equality.

## (add future items below)
