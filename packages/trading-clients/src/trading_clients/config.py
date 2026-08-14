import asyncio
import configparser
from dataclasses import dataclass
from pathlib import Path

RC_PATH = Path.home() / ".tradingrc"


@dataclass(frozen=True)
class WebullConfig:
    app_key: str
    app_secret: str
    region_id: str
    account_id: str | None = None
    token: str | None = None


@dataclass(frozen=True)
class TradierConfig:
    api_token: str
    sandbox: bool = True
    account_id: str | None = None


@dataclass(frozen=True)
class FinnhubConfig:
    api_key: str


@dataclass(frozen=True)
class FmpConfig:
    api_key: str


@dataclass(frozen=True)
class FredConfig:
    api_key: str


@dataclass(frozen=True)
class AlphaVantageConfig:
    api_key: str


@dataclass(frozen=True)
class EiaConfig:
    api_key: str


@dataclass(frozen=True)
class FinraConfig:
    """FINRA Query API credentials (free developer account).

    The credential pair alone is not sufficient: corporate and agency datasets
    stay invisible (404, not 403) until the **Fixed Income Data user agreement**
    is accepted in the FINRA developer portal, and entitlements are baked into
    the OAuth token at mint time — so a token minted before accepting keeps
    404ing until it expires.
    """

    api_client_id: str
    api_secret: str


@dataclass(frozen=True)
class TastyTradeConfig:
    client_secret: str
    refresh_token: str


@dataclass(frozen=True)
class SnapTradeConfig:
    """SnapTrade Personal API key (read-only Fidelity/others via Akoya).

    Personal keys authenticate with just client_id + consumer_key: the key
    identifies the account owner, so requests carry no userId/userSecret and
    registerUser is not used (that's the Commercial model). Brokerages are
    connected in the SnapTrade dashboard; this key then reads them.
    """

    client_id: str
    consumer_key: str


@dataclass(frozen=True)
class EdgarConfig:
    """Optional. user_agent should be 'Your Name your@email.com' per SEC fair-use policy."""

    user_agent: str | None = None


@dataclass(frozen=True)
class AppConfig:
    webull: WebullConfig
    tradier: TradierConfig | None = None
    finnhub: FinnhubConfig | None = None
    fmp: FmpConfig | None = None
    fred: FredConfig | None = None
    alphavantage: AlphaVantageConfig | None = None
    eia: EiaConfig | None = None
    finra: FinraConfig | None = None
    tastytrade: TastyTradeConfig | None = None
    snaptrade: SnapTradeConfig | None = None
    edgar: EdgarConfig | None = None


def load_config(path: Path = RC_PATH) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Create it with a [webull] section containing "
            "app_key, app_secret, and region_id."
        )
    parser = configparser.ConfigParser()
    parser.read(path)

    # Webull (required)
    section = "webull"
    if section not in parser:
        raise KeyError(f"[{section}] section missing in {path}")
    cfg = parser[section]
    required = ("app_key", "app_secret", "region_id")
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise KeyError(f"Missing keys in [{section}]: {', '.join(missing)}")
    webull = WebullConfig(
        app_key=cfg["app_key"],
        app_secret=cfg["app_secret"],
        region_id=cfg["region_id"],
        account_id=cfg.get("account_id") or None,
        token=cfg.get("token") or None,
    )

    # Tradier (optional)
    tradier = None
    if parser.has_section("tradier"):
        tradier = TradierConfig(
            api_token=parser.get("tradier", "api_token"),
            sandbox=parser.getboolean("tradier", "sandbox", fallback=True),
            account_id=parser.get("tradier", "account_id", fallback=None) or None,
        )

    # Finnhub (optional)
    finnhub = None
    if parser.has_section("finnhub"):
        finnhub = FinnhubConfig(api_key=parser.get("finnhub", "api_key"))

    # FMP (optional)
    fmp = None
    if parser.has_section("fmp"):
        fmp = FmpConfig(api_key=parser.get("fmp", "api_key"))

    # FRED (optional)
    fred = None
    if parser.has_section("fred"):
        fred = FredConfig(api_key=parser.get("fred", "api_key"))

    # Alpha Vantage (optional)
    alphavantage = None
    if parser.has_section("alphavantage"):
        alphavantage = AlphaVantageConfig(api_key=parser.get("alphavantage", "api_key"))

    # EIA (optional)
    eia = None
    if parser.has_section("eia"):
        eia = EiaConfig(api_key=parser.get("eia", "api_key"))

    # FINRA (optional)
    finra = None
    if parser.has_section("finra"):
        finra = FinraConfig(
            api_client_id=parser.get("finra", "api_client_id"),
            api_secret=parser.get("finra", "api_secret"),
        )

    # TastyTrade (optional)
    tastytrade = None
    if parser.has_section("tastytrade"):
        tastytrade = TastyTradeConfig(
            client_secret=parser.get("tastytrade", "client_secret"),
            refresh_token=parser.get("tastytrade", "refresh_token"),
        )

    # SnapTrade (optional)
    snaptrade = None
    if parser.has_section("snaptrade"):
        snaptrade = SnapTradeConfig(
            client_id=parser.get("snaptrade", "client_id"),
            consumer_key=parser.get("snaptrade", "consumer_key"),
        )

    # EDGAR (optional — defaults work for low-volume personal use)
    edgar = None
    if parser.has_section("edgar"):
        edgar = EdgarConfig(user_agent=parser.get("edgar", "user_agent", fallback=None) or None)

    return AppConfig(
        webull=webull,
        tradier=tradier,
        finnhub=finnhub,
        fmp=fmp,
        fred=fred,
        alphavantage=alphavantage,
        eia=eia,
        finra=finra,
        tastytrade=tastytrade,
        snaptrade=snaptrade,
        edgar=edgar,
    )


async def save_webull_token(token: str, path: Path = RC_PATH) -> None:
    """Save a new Webull access token to ~/.tradingrc."""

    def _sync_save() -> None:
        parser = configparser.ConfigParser()
        parser.read(path)
        if not parser.has_section("webull"):
            raise KeyError("[webull] section missing in " + str(path))
        parser.set("webull", "token", token)
        with open(path, "w", encoding="utf-8") as f:
            parser.write(f)

    await asyncio.to_thread(_sync_save)
