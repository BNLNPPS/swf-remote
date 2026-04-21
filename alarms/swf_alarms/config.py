"""Config loader — TOML via stdlib tomllib (Python 3.11+)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EngineConfig:
    state_db: str
    swf_remote_base_url: str
    request_timeout: int = 20
    log_path: str | None = None


@dataclass
class EmailConfig:
    provider: str
    region: str
    from_addr: str


@dataclass
class CheckConfig:
    name: str
    kind: str
    enabled: bool
    severity: str
    recipients: list[str]
    cooldown_hours: float
    params: dict = field(default_factory=dict)


@dataclass
class Config:
    engine: EngineConfig
    email: EmailConfig
    checks: list[CheckConfig]
    raw: dict


def load(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    eng = raw["engine"]
    engine = EngineConfig(
        state_db=os.path.expanduser(eng["state_db"]),
        swf_remote_base_url=eng["swf_remote_base_url"].rstrip("/"),
        request_timeout=int(eng.get("request_timeout", 20)),
        log_path=os.path.expanduser(eng["log_path"]) if eng.get("log_path") else None,
    )

    e = raw["email"]
    email = EmailConfig(
        provider=e["provider"],
        region=e["region"],
        from_addr=e["from"],
    )

    checks = []
    for c in raw.get("checks", []):
        known = {"name", "kind", "enabled", "severity", "recipients", "cooldown_hours"}
        params = {k: v for k, v in c.items() if k not in known}
        checks.append(
            CheckConfig(
                name=c["name"],
                kind=c["kind"],
                enabled=bool(c.get("enabled", True)),
                severity=c.get("severity", "warning"),
                recipients=list(c["recipients"]),
                cooldown_hours=float(c.get("cooldown_hours", 24)),
                params=params,
            )
        )

    return Config(engine=engine, email=email, checks=checks, raw=raw)
