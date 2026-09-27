"""Verification of the two JWTs the relay signs for its push providers (CONN-04 API 3–4), as Apple and Google would:

- the APNs provider token: ES256 over `header.claims`, header `kid` = the key id, claims `iss` = the team id and a
  recent `iat` (Apple refuses tokens older than an hour);
- the FCM OAuth assertion: RS256, `iss` = the service account, `scope` = firebase.messaging, `aud` = the token URI,
  `exp` = `iat` + 3600.
"""
from __future__ import annotations

import base64
import json
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
MAX_AGE_S = 3600


def _b64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _split(token: str) -> tuple[dict, dict, bytes, bytes]:
    head, body, sig = token.split(".")
    return json.loads(_b64u(head)), json.loads(_b64u(body)), f"{head}.{body}".encode(), _b64u(sig)


def load_public_key(path):
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def verify_apns_token(token: str, public_key, key_id: str, team_id: str, now: float | None = None) -> dict:
    """The verdict on an APNs provider token: {"valid": bool, "alg", "kid", "iss", "age_s", "error"?}."""
    now = time.time() if now is None else now
    try:
        header, claims, signed, sig = _split(token)
        if len(sig) != 64:
            raise ValueError("ES256 signature is not 64 bytes")
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        public_key.verify(der, signed, ec.ECDSA(hashes.SHA256()))
        age = int(now - int(claims["iat"]))
        verdict = {"alg": header.get("alg"), "kid": header.get("kid"), "iss": claims.get("iss"), "age_s": age}
        ok = (header.get("alg") == "ES256" and header.get("kid") == key_id and claims.get("iss") == team_id
              and -300 <= age <= MAX_AGE_S)
        return {"valid": ok, **verdict}
    except (ValueError, KeyError, TypeError, InvalidSignature) as error:
        return {"valid": False, "error": type(error).__name__}


def verify_fcm_assertion(token: str, public_key, client_email: str, token_uri: str,
                         now: float | None = None) -> dict:
    """The verdict on the OAuth2 JWT-bearer assertion: {"valid": bool, "iss", "scope", "aud", "lifetime_s"}."""
    now = time.time() if now is None else now
    try:
        header, claims, signed, sig = _split(token)
        public_key.verify(sig, signed, padding.PKCS1v15(), hashes.SHA256())
        lifetime = int(claims["exp"]) - int(claims["iat"])
        verdict = {"alg": header.get("alg"), "iss": claims.get("iss"), "scope": claims.get("scope"),
                   "aud": claims.get("aud"), "lifetime_s": lifetime}
        ok = (header.get("alg") == "RS256" and claims.get("iss") == client_email and claims.get("scope") == FCM_SCOPE
              and claims.get("aud") == token_uri and lifetime == 3600 and abs(now - int(claims["iat"])) <= 300)
        return {"valid": ok, **verdict}
    except (ValueError, KeyError, TypeError, InvalidSignature) as error:
        return {"valid": False, "error": type(error).__name__}
