"""Where the local relay stack lives: ports, the state directory layout and the JSON other tools read.

The state directory (`--state-dir`, else $HANDLIVE_RELAY_STACK_DIR, else $TMPDIR/handlive-relay-stack) holds the
generated keys, the PostgreSQL and Redis data, the logs, the mock captures and `relay_stack.json`. It is never inside
a repository. Ports are fixed per state directory (first `up` wins) because the Android build bakes the TLS front's
port into the APK.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[4]  # <workspace>/shared/tools/e2e/relay_stack
RELAY_DIR = WORKSPACE / "relay"
SHARED_TOOLS = WORKSPACE / "shared" / "tools"
PG_BIN = Path(os.environ.get("HANDLIVE_PG_BIN", "/opt/homebrew/opt/postgresql@18/bin"))
REDIS_SERVER = os.environ.get("HANDLIVE_REDIS_SERVER", "/opt/homebrew/bin/redis-server")
DB_USER, DB_PASSWORD, DB_NAME = "handlive", "handlive-dev", "handlive_relay"  # relay/.env.example placeholders
APNS_TOPIC = "app.handlive.ios"
EMULATOR_HOST = "10.0.2.2"  # the development machine as the Android emulator sees it


@dataclass
class Ports:
    postgres: int = 55433
    redis: int = 56380
    relay: int = 18080
    tls: int = 18443
    apns: int = 18444
    fcm: int = 18445


@dataclass
class Layout:
    root: Path
    ports: Ports = field(default_factory=Ports)

    @property
    def keys(self) -> Path:
        return self.root / "keys"

    @property
    def tls(self) -> Path:
        return self.root / "keys" / "tls"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def captures(self) -> Path:
        return self.root / "captures"

    @property
    def run(self) -> Path:
        return self.root / "run"

    @property
    def pg_data(self) -> Path:
        return self.root / "postgres"

    @property
    def redis_data(self) -> Path:
        return self.root / "redis"

    @property
    def json_path(self) -> Path:
        return self.root / "relay_stack.json"

    @property
    def ports_path(self) -> Path:
        return self.root / "ports.json"

    def dirs(self) -> None:
        for d in (self.root, self.keys, self.tls, self.logs, self.captures, self.run, self.redis_data):
            d.mkdir(parents=True, exist_ok=True)
        os.chmod(self.keys, 0o700)

    @property
    def database_url(self) -> str:
        return f"postgres://{DB_USER}:{DB_PASSWORD}@127.0.0.1:{self.ports.postgres}/{DB_NAME}"


def default_state_dir() -> Path:
    env = os.environ.get("HANDLIVE_RELAY_STACK_DIR")
    return Path(env) if env else Path(tempfile.gettempdir()) / "handlive-relay-stack"


def load_layout(state_dir: Path, overrides: dict | None = None) -> Layout:
    """The layout of `state_dir`, with the ports saved by its first `up`; `overrides` only apply before that."""
    layout = Layout(state_dir.resolve())
    if layout.ports_path.exists():
        layout.ports = Ports(**json.loads(layout.ports_path.read_text()))
    elif overrides:
        layout.ports = Ports(**{**asdict(layout.ports), **{k: v for k, v in overrides.items() if v}})
    return layout


def save_ports(layout: Layout) -> None:
    layout.ports_path.write_text(json.dumps(asdict(layout.ports), indent=1) + "\n")


def describe(layout: Layout, tls, apns_key_id: str, apns_team_id: str, fcm_project: str, pids: dict) -> dict:
    """The content of relay_stack.json: everything a client of the stack needs, no secret."""
    p = layout.ports
    emulator_host = f"{EMULATOR_HOST}:{p.tls}"
    return {
        "state_dir": str(layout.root),
        "relay": {"http": f"http://127.0.0.1:{p.relay}", "https": f"https://127.0.0.1:{p.tls}",
                  "wss": f"wss://127.0.0.1:{p.tls}/v1/relay", "emulator_https": f"https://{emulator_host}",
                  "emulator_wss": f"wss://{emulator_host}/v1/relay", "trusted_proxies": "127.0.0.1",
                  "log": str(layout.logs / "relay.log")},
        "tls": {"ca_cert": str(tls.ca_cert), "server_chain": str(tls.chain), "spki_pin": tls.ca_pin,
                "server_spki_pin": tls.leaf_pin, "sans": ["10.0.2.2", "127.0.0.1", "localhost"],
                "not_after": tls.not_after, "front_log": str(layout.logs / "tls-front.log"),
                "python_env": {"SSL_CERT_FILE": str(tls.ca_cert)}},
        "android_build": {"relay_host": emulator_host, "relay_extra_pins": tls.ca_pin,
                          "gradle_args": [f"-Phandlive.relayHost={emulator_host}",
                                          f"-Phandlive.relayExtraPins={tls.ca_pin}"]},
        "apns": {"url": f"http://127.0.0.1:{p.apns}", "sandbox_url": f"http://127.0.0.1:{p.apns}/sandbox",
                 "http": "HTTP/2 prior knowledge (h2c)", "topic": APNS_TOPIC, "key_id": apns_key_id,
                 "team_id": apns_team_id, "capture": str(layout.captures / "apns.jsonl"),
                 "dead_token_prefix": "dead"},
        "fcm": {"url": f"http://127.0.0.1:{p.fcm}", "project_id": fcm_project,
                "token_uri": f"http://127.0.0.1:{p.fcm}/token", "capture": str(layout.captures / "fcm.jsonl"),
                "unregistered_token_prefix": "unregistered"},
        "postgres": {"url": layout.database_url, "psql": str(PG_BIN / "psql"),
                     "log": str(layout.logs / "postgres.log")},
        "redis": {"url": f"redis://127.0.0.1:{p.redis}", "log": str(layout.logs / "redis.log")},
        "pids": pids,
    }
