import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# The model used for the summarizer. Haiku is the cheapest current tier and is
# well suited to structured extraction and summarization.
SUMMARY_MODEL = "claude-haiku-4-5-20251001"

# Prices in USD per million tokens, kept here so cost tracking reads from one
# place. Update if you switch models. (input, output)
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = MODEL_PRICES.get(model, (0.0, 0.0))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000