# Design Notes: What Makes This Project Distinctive

The thesis in one sentence: an AI system should never state a number it cannot
trace to a source, and should be honest about what it cannot know. Every design
choice serves that thesis. This file exists so the thesis stays loud, not buried
in the code.

## What is already uncommon here

- Code-first data layer: numbers are fetched and verified in code before any
  agent sees them. Agents interpret data, they never recall it from memory.
- A verification boundary: a number cannot exist in output without a source
  reference (accession). Derived figures (margins, growth) are computed in code
  and carry the sources of their inputs, so they are reproducible too.
- Escalation tiers (confident / partial / blocked): the system knows when to
  stop and refuse rather than guess.
- Multi-agent debate with a referee that maps disagreement instead of judging.
  The output is never a buy/sell verdict.
- The project has caught and fixed its own real bugs (agent arithmetic, XBRL
  fiscal-year mislabeling). Surviving contact with real data is the signal.

## Highest-leverage next steps (ordered by differentiation per unit effort)

1. Verification / adversarial test suite. Prove the thesis instead of asserting
   it. Feed agents poisoned data; check every number in every agent output
   against the source set; fail loudly on any untraceable figure. Surface the
   pass rate on the dashboard ("0 unsourced claims across the last N runs").
   This converts "I care about hallucination" into a measured number. Most
   students talk about hallucination; almost none instrument it.
2. Scorecard (Stage 5) as centerpiece. Log each run's conclusion, check it
   against reality at 3 and 6 months. Grading your own past outputs is rare
   intellectual honesty. Do not bury it.
3. Observability as a first-class feature. A full trace per run: data fetched ->
   verified -> each agent call (tokens, cost, retries) -> where the referee
   found disagreement. "Here is the complete auditable trace of how this
   conclusion was reached, and what it cost" is system-design maturity.
4. Make failure visible. Demo a company where verification fails and show the
   system correctly declining. "It knows when to give up" is a mature property
   most demos never show.

## Deliberately NOT doing (adds surface area, not thesis strength)

- More agents / more data sources for their own sake.
- Vector DB, embeddings, or fine-tuning. These would be keyword-stuffing here,
  not a real need. Depth on "verifiable, honest, auditable" beats breadth.

## Project framing: a discovery tool with a verified-analysis core

The front door is DISCOVERY: surface a real company to investigate (later, a
daily popup / lock-screen card). Tapping it opens the verified-analysis tools
(Fetch / Summarize / Debate). Discovery is how a user starts; the analysis flow
is what they learn once they do. Same project, two names.

Popup / discovery card rule: show only facts traceable to a filing (company
name, what it does, a striking verified figure like revenue growth or a margin,
last-filed date, verification tier). NEVER lead with share price: price has no
filing behind it (violates principle #2), and "ticker + price daily" reads as a
trade signal, which the project refuses to be. If live market data is ever shown,
it must be clearly labeled unverified and visually separated from filing-backed
numbers, never blended.

## Showing that this is genuinely agentic (for interviews)

The system is already agentic; the agency is just invisible because it runs
server-side. The fix is to make it LEGIBLE, not to add features. Concretely, the
project demonstrates agentic AI via:

- Distinct agent ROLES with constraints (fetcher/verifier, bull, bear, referee).
- Inter-agent COORDINATION (referee consumes bull + bear output and reasons over
  their disagreement).
- Self-correction: validation + retry loop; attempt counts prove it fires.
- Tool use grounded in real data (EDGAR fetch, code-computed facts, agents kept
  within verified data).
- Autonomous control flow: the escalation tier decides proceed / caveat / stop.

Dashboard trace view (observability) makes all of the above visible per run:
data fetched -> facts verified -> tier assigned -> each agent call (tokens,
retries) -> referee reads both -> disagreements. This is the single most
convincing interview artifact: it turns "trust me, it's agentic" into "watch
the agents work." Doubles as the observability feature. Demonstrable today.
