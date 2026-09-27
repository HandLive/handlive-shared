"""Keys and certificates of the local relay stack, generated in its state directory and never committed.

- TLS: a test CA (EC P-256) and a server certificate it signs, valid for 30 days, whose SANs are 10.0.2.2 (the host
  as the Android emulator sees it), 127.0.0.1 and localhost. The Android pin is the CA's SPKI in OkHttp's format
  `sha256/<base64>` (0.4.3 pins SPKIs of the chain); the leaf's pin is printed too.
- APNs: an ES256 provider key (PKCS#8 PEM, the `.p8` form) with a made-up key id and team id.
- FCM: a service-account JSON with an RSA-2048 key whose `token_uri` is the mock OAuth endpoint.

Private keys are written with mode 0600. They exist only to talk to the local mocks and the local TLS front.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import ipaddress
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SANS_IP = ("10.0.2.2", "127.0.0.1")
SANS_DNS = ("localhost",)
CERT_DAYS = 30
RENEW_BEFORE = datetime.timedelta(days=2)
APNS_KEY_ID = "E2EKEY0001"
APNS_TEAM_ID = "E2ETEAM001"
FCM_PROJECT = "handlive-e2e"
FCM_CLIENT_EMAIL = f"relay@{FCM_PROJECT}.iam.gserviceaccount.com"


@dataclass
class TlsFiles:
    ca_cert: Path
    chain: Path  # server certificate followed by the CA
    key: Path
    ca_pin: str
    leaf_pin: str
    not_after: str


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _pem_key(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def spki_pin(cert: x509.Certificate) -> str:
    """OkHttp CertificatePinner format: sha256/ + base64 of SHA-256(SubjectPublicKeyInfo DER)."""
    spki = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return "sha256/" + base64.b64encode(hashlib.sha256(spki).digest()).decode()


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HandLive e2e"),
                      x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _issue(tls_dir: Path) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    start, end = now - datetime.timedelta(days=1), now + datetime.timedelta(days=CERT_DAYS)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = _name("HandLive local relay test CA")
    ca_ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(start).not_valid_after(end)
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .add_extension(ca_ski, critical=False)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    sans = [x509.IPAddress(ipaddress.ip_address(ip)) for ip in SANS_IP] + [x509.DNSName(d) for d in SANS_DNS]
    leaf = (x509.CertificateBuilder().subject_name(_name("HandLive local relay")).issuer_name(ca_name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(start).not_valid_after(end)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
            .sign(ca_key, hashes.SHA256()))
    tls_dir.mkdir(parents=True, exist_ok=True)
    (tls_dir / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (tls_dir / "server-chain.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM)
                                               + ca.public_bytes(serialization.Encoding.PEM))
    _write_private(tls_dir / "server.key", _pem_key(key))  # the CA key is not kept: nothing else is ever signed


def tls_files(tls_dir: Path, renew: bool = False) -> TlsFiles:
    """The TLS material, issued on first use and again when it expires within 2 days (or when `renew`)."""
    ca_path, chain_path = tls_dir / "ca.pem", tls_dir / "server-chain.pem"
    if renew or not (ca_path.exists() and chain_path.exists() and (tls_dir / "server.key").exists()):
        _issue(tls_dir)
    ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
    leaf = x509.load_pem_x509_certificates(chain_path.read_bytes())[0]
    if leaf.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc) < RENEW_BEFORE:
        return tls_files(tls_dir, renew=True)
    return TlsFiles(ca_path, chain_path, tls_dir / "server.key", spki_pin(ca), spki_pin(leaf),
                    leaf.not_valid_after_utc.isoformat())


def apns_key(keys_dir: Path) -> tuple[Path, Path]:
    """(`AuthKey_<id>.p8` for the relay, the public key PEM for the mock), created once."""
    p8, pub = keys_dir / f"AuthKey_{APNS_KEY_ID}.p8", keys_dir / "apns-public.pem"
    if not (p8.exists() and pub.exists()):
        key = ec.generate_private_key(ec.SECP256R1())
        _write_private(p8, _pem_key(key))
        pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                      serialization.PublicFormat.SubjectPublicKeyInfo))
    return p8, pub


def fcm_account(keys_dir: Path, token_uri: str) -> tuple[Path, Path]:
    """(service-account JSON for the relay, the public key PEM for the mock); the JSON follows `token_uri`."""
    account, pub, key_path = keys_dir / "fcm-service-account.json", keys_dir / "fcm-public.pem", keys_dir / "fcm.key"
    if not key_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _write_private(key_path, _pem_key(key))
        pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                      serialization.PublicFormat.SubjectPublicKeyInfo))
    body = {"type": "service_account", "project_id": FCM_PROJECT, "private_key_id": "e2e",
            "private_key": key_path.read_text(), "client_email": FCM_CLIENT_EMAIL, "token_uri": token_uri}
    _write_private(account, json.dumps(body, indent=1).encode())
    return account, pub
