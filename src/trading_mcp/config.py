import configparser
from dataclasses import dataclass
from pathlib import Path

RC_PATH = Path.home() / ".tradingrc"


@dataclass(frozen=True)
class WebullConfig:
    app_key: str
    app_secret: str
    account_id: str
    region_id: str


@dataclass(frozen=True)
class TradierConfig:
    api_token: str
    sandbox: bool = True


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
class AppConfig:
    webull: WebullConfig
    tradier: TradierConfig | None = None
    finnhub: FinnhubConfig | None = None
    fmp: FmpConfig | None = None
    fred: FredConfig | None = None
    alphavantage: AlphaVantageConfig | None = None


def load_config(path: Path = RC_PATH) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Create it with a [webull] section containing "
            "app_key, app_secret, account_id, and region_id."
        )
    parser = configparser.ConfigParser()
    parser.read(path)

    # Webull (required)
    section = "webull"
    if section not in parser:
        raise KeyError(f"[{section}] section missing in {path}")
    cfg = parser[section]
    required = ("app_key", "app_secret", "account_id", "region_id")
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise KeyError(f"Missing keys in [{section}]: {', '.join(missing)}")
    webull = WebullConfig(
        app_key=cfg["app_key"],
        app_secret=cfg["app_secret"],
        account_id=cfg["account_id"],
        region_id=cfg["region_id"],
    )

    # Tradier (optional)
    tradier = None
    if parser.has_section("tradier"):
        tradier = TradierConfig(
            api_token=parser.get("tradier", "api_token"),
            sandbox=parser.getboolean("tradier", "sandbox", fallback=True),
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

    return AppConfig(
        webull=webull,
        tradier=tradier,
        finnhub=finnhub,
        fmp=fmp,
        fred=fred,
        alphavantage=alphavantage,
    )
