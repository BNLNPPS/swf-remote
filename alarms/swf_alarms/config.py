"""Config loader — TOML via stdlib tomllib (Python 3.11+).

DB connection: defaults to reading SWF_REMOTE_DB_* from swf-remote's own
.env so credentials live in exactly one place. Override with an explicit
[db] dsn / host / name / user / password block if you need to point the
engine at a different Postgres (e.g. running from another host).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus


@dataclass
class EngineConfig:
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
    db_dsn: str
    raw: dict


def _parse_dotenv(path: str) -> dict:
    """Minimal .env parser: KEY=value lines, ignoring #comments and blanks.

    Preserves values containing '=' (splits on first '=' only). Strips
    surrounding single or double quotes from values.
    """
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            out[k.strip()] = v
    return out


def _compose_dsn(db_section: dict) -> str:
    """Build a libpq DSN from a [db] section in config.toml.

    If `dsn` is set, use it verbatim. Otherwise compose from host/port/name/
    user/password — which, by default, are pulled from swf-remote's own .env
    file (SWF_REMOTE_DB_NAME etc.) so credentials don't duplicate.
    """
    if db_section.get('dsn'):
        return str(db_section['dsn'])

    env_path = os.path.expanduser(
        db_section.get('env_path', '/var/www/swf-remote/src/.env')
    )
    env = _parse_dotenv(env_path)

    def pick(key, env_key, default=None):
        if db_section.get(key) is not None:
            return db_section[key]
        if env.get(env_key) is not None:
            return env[env_key]
        if key in os.environ:
            return os.environ[key]
        return default

    host = pick('host', 'SWF_REMOTE_DB_HOST', 'localhost')
    port = pick('port', 'SWF_REMOTE_DB_PORT', '5432')
    name = pick('name', 'SWF_REMOTE_DB_NAME', 'swf_remote')
    user = pick('user', 'SWF_REMOTE_DB_USER', 'swf_remote')
    password = pick('password', 'SWF_REMOTE_DB_PASSWORD', '')

    userinfo = quote_plus(str(user))
    if password:
        userinfo += ':' + quote_plus(str(password))
    return f"postgresql://{userinfo}@{host}:{port}/{name}"


def load(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    eng = raw["engine"]
    engine = EngineConfig(
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

    db_dsn = _compose_dsn(raw.get("db", {}))

    return Config(engine=engine, email=email, checks=checks,
                  db_dsn=db_dsn, raw=raw)
