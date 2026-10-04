"""A fake Mac (or iPhone) that talks to the real Android app exactly as M-APP / I-APP does.

It owns the client identity and pair record (pair_store.py), pairs with a PIN over `/v1/pair` (mac_pairing.py) and
opens `/v1/ctl` sessions (mac_session.py) over the phone's LAN WSS — reached from the host through `adb forward` — or
over a relay channel (relay_client.py). mDNS discovery is not used: the emulator's NAT carries no multicast, so the
client dials the forwarded port the way M-APP dials `last_host` (CONN-01 step 2a).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from bench_lines import BenchLog
from mac_pairing import PinPairing
from mac_session import MacSession
from pair_store import PairRecord
from schema_check import SchemaCheck
from transport import LanTransport

CLIENT_MODELS = {"macos": "Mac15,3", "ios": "iPhone16,1"}


def capability(platform: str = "macos", *, clipboard: bool = True, sms: bool = True, call: bool = True,
               relay: bool = False, notify: bool = True) -> dict:
    """0.7.2 as the Apple app builds it (apple/…/LocalDevice.swift): clipboard, SMS, calls and the relay switch;
    iPhone and iPad add sms.notify and call.notify."""
    mobile = platform in ("ios", "ipados")
    features = {
        "clipboard": {"enabled": clipboard, "auto_send": True, "max_text_bytes": 1_048_576,
                      "max_image_bytes": 10_485_760, "mimes": ["text/plain", "text/html", "image/png", "image/jpeg"]},
        "sms": {"enabled": sms, **({"notify": notify} if mobile else {})},
        "call": {"enabled": call, **({"notify": notify} if mobile else {})},
        "relay": {"enabled": relay},
    }
    return {"protocol": 1, "app_version": "0.0.0 (e2e)", "platform": platform,
            "os_version": "18.0" if mobile else "15.0", "model": CLIENT_MODELS.get(platform, "Mac15,3"),
            "features": features}


class FakeClient:
    def __init__(self, state_file: Path, name: str, platform: str = "macos", host: str = "127.0.0.1",
                 port: int = 47800, bench_file: Path | None = None, checker: SchemaCheck | None = None,
                 log: Callable[[str], None] = print) -> None:
        self.state_file = state_file
        self.host, self.port = host, port
        self.checker = checker or SchemaCheck()
        self.log = log
        self.record = PairRecord.load(state_file) or PairRecord.new(name, platform, CLIENT_MODELS.get(platform, ""))
        self.bench = BenchLog(bench_file, self.record.device_id)
        self.relay_capable = False

    def save(self) -> None:
        self.record.save(self.state_file)

    def forget_pair(self) -> None:
        """A new pair with a fresh identity (the phone was reinstalled, so the old pair no longer exists)."""
        r = self.record
        self.record = PairRecord.new(r.name, r.platform, r.model)
        self.bench = BenchLog(self.bench.path, self.record.device_id)
        self.save()

    def lan(self, path: str, pinned: bool = True, keepalive: bool = True) -> LanTransport:
        pin = bytes.fromhex(self.record.peer_tls_sha256) if pinned and self.record.peer_tls_sha256 else None
        return LanTransport(self.host, self.port, path, pin, keepalive=keepalive)

    def pin_pairing(self) -> PinPairing:
        return PinPairing(self.record, self.checker, lambda: self.lan("/v1/pair", pinned=False, keepalive=False))

    def session(self, open_transport: Callable[[], object] | None = None, **cap) -> MacSession:
        opener = open_transport or (lambda: self.lan("/v1/ctl"))
        caps = capability(self.record.platform, relay=self.relay_capable, **cap)
        return MacSession(self.record, opener, caps, self.checker, self.bench, self.log)
