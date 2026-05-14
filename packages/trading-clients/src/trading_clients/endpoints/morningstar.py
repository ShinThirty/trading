"""Morningstar endpoint definitions: earnings call transcript.

Fetched via MorningstarClient (Playwright). The transcript page lives at
kessler-prod.reta52d8.eas.morningstar.com; URLs put the MIC-style exchange
code as the first path segment (xase = NYSE American, xnys = NYSE,
xnas = Nasdaq).

Parser input is the transcript container's inner_text — visible text after
the SAL web component renders. More stable than raw HTML because the
component's class names and shadow DOM details change frequently.
"""

from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class TranscriptRequest(ParamsRequest, PathRequest):
    exchange_code: str  # 'xase', 'xnys', or 'xnas'
    symbol: str  # ticker; lowercased into the URL

    def to_path_params(self) -> dict[str, str]:
        return {
            "exchange_code": self.exchange_code,
            "symbol": self.symbol.lower(),
        }

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class TranscriptResponse:
    """Earnings call transcript text (visible body of the transcript pane).

    Container's inner_text starts with the literal "Earnings Call Transcript",
    followed by "Participants", the issuer name + ticker, then speaker turns
    ("Operator", "<Name>", ...). Date / quarter are embedded in the spoken
    script itself, not surfaced as separate metadata fields.
    """

    text: str

    @classmethod
    def from_response(cls, body_text: str) -> "TranscriptResponse":
        return cls(text=body_text.strip())

    def to_output(self) -> str:
        return self.text


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# Once Morningstar publishes a transcript, the text doesn't change. WAF also
# rate-limits us, so a long cache is friendlier. 12h covers typical
# briefing / analysis sessions without re-hitting the page.
EARNINGS_TRANSCRIPT = Endpoint(
    "/stocks/{exchange_code}/{symbol}/earnings-transcript",
    cache_ttl=43_200,
    response_model=TranscriptResponse,
    base_url="https://kessler-prod.reta52d8.eas.morningstar.com",
)
