import configparser
from dataclasses import dataclass
from pathlib import Path

RC_PATH = Path.home() / ".webullrc"


@dataclass(frozen=True)
class WebullConfig:
    app_key: str
    app_secret: str
    account_id: str
    region_id: str


def load_config(path: Path = RC_PATH) -> WebullConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Create it with [webull] section containing "
            "app_key, app_secret, account_id, and region_id."
        )
    parser = configparser.ConfigParser()
    parser.read(path)
    section = "webull"
    if section not in parser:
        raise KeyError(f"[{section}] section missing in {path}")
    cfg = parser[section]
    required = ("app_key", "app_secret", "account_id", "region_id")
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise KeyError(f"Missing keys in [{section}]: {', '.join(missing)}")
    return WebullConfig(
        app_key=cfg["app_key"],
        app_secret=cfg["app_secret"],
        account_id=cfg["account_id"],
        region_id=cfg["region_id"],
    )
