"""The fake client's identity and pair record (0.9.3 paired_device on the client side), kept in a local JSON file.

The file holds private keys and the PRK of a test pair: it lives in the state directory (never in the repository),
is written with mode 0600, and belongs to one emulator only — a reinstalled app means a new pair.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mac_crypto import Identity


@dataclass
class PairRecord:
    name: str
    platform: str
    model: str
    sig_seed: str
    dh_priv: str
    device_id: str
    pair_id: str = ""
    peer_device_id: str = ""
    peer_name: str = ""
    peer_model: str = ""
    peer_os: str = ""
    peer_ik_sig_pub: str = ""
    peer_ik_dh_pub: str = ""
    peer_tls_sha256: str = ""
    prk: str = ""
    attestation: str = ""
    sig_self: str = ""
    sig_peer: str = ""
    created_at: int = 0
    security_code: str = ""
    relay_registered: bool = False
    cursors: dict = field(default_factory=dict)

    @classmethod
    def new(cls, name: str, platform: str, model: str) -> "PairRecord":
        ident = Identity.generate()
        return cls(name, platform, model, ident.sig_seed.hex(), ident.dh_priv.hex(), ident.device_id)

    @property
    def identity(self) -> Identity:
        return Identity(bytes.fromhex(self.sig_seed), bytes.fromhex(self.dh_priv))

    @property
    def paired(self) -> bool:
        return bool(self.pair_id and self.prk)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=1)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> "PairRecord | None":
        if not path.is_file():
            return None
        return cls(**json.loads(path.read_text(encoding="utf-8")))
