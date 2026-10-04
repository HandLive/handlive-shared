"""An in-process stand-in for the phone's WSS server, used only by self_test.py (CI, no emulator).

It plays the S side just far enough to drive the harness end to end: PIN pairing on `/v1/pair` (PAIR-01 A4, API 3
and 5), the session handshake and capability on `/v1/ctl` (0.6.3, CONN-01), acks for clipboard, SMS and call requests,
and events pushed on demand. Its crypto is the vector tools' generator code; the real phone is the real test.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import ssl
import tempfile
import threading
import time
from pathlib import Path

import mac_crypto as C
import pairing_discovery_derivations as P
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from handlive_protocol_derivations import hkdf, hmac256, pair_salt_input, uuid_bytes, x25519_dh, x25519_pub
from websockets.sync.server import serve


def _self_signed(tmp: Path) -> tuple[ssl.SSLContext, bytes]:
    """ECDSA P-256, CN=HandLive (SET-01 API 1); returns the server context and the SHA-256 of the DER."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HandLive")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30)).sign(key, hashes.SHA256()))
    (tmp / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                    serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(tmp / "cert.pem", tmp / "key.pem")
    return ctx, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).digest()


class FakePhone:
    def __init__(self, pin: str) -> None:
        self.pin = pin
        self.identity = C.Identity.generate()
        self.pairs: dict[str, dict] = {}
        self.received: list[dict] = []
        self._tmp = tempfile.TemporaryDirectory()
        ctx, self.tls_sha256 = _self_signed(Path(self._tmp.name))
        self.server = serve(self._handle, "127.0.0.1", 0, ssl=ctx, compression=None)
        self.port = self.server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self._session = None

    def close(self) -> None:
        self.server.shutdown()
        self._tmp.cleanup()

    def _handle(self, ws) -> None:
        path = ws.request.path
        if path == "/v1/pair":
            self._pair(ws)
        elif path == "/v1/ctl":
            self._ctl(ws)
        else:
            ws.close(4400, "BAD_REQUEST")

    # ----- /v1/pair (PIN) --------------------------------------------------------------------------------------
    def _pair(self, ws) -> None:
        hello = C.open_plain(json.loads(ws.recv(10)))["data"]
        nonce_c, nonce_s = C.b64u_decode(hello["nonce"], 32), os.urandom(32)
        k_pin = P.pin_key(self.pin, nonce_c, nonce_s)
        k_pa = P.pair_auth_key(k_pin, nonce_c, nonce_s)
        client = {"device_id": hello["device_id"], "nonce": nonce_c, "ik_sig_pub": C.b64u_decode(hello["ik_sig_pub"]),
                  "ik_dh_pub": C.b64u_decode(hello["ik_dh_pub"]), "name": hello["name"]}
        me = self.identity
        server = {"device_id": me.device_id, "nonce": nonce_s, "ik_sig_pub": me.sig_pub, "ik_dh_pub": me.dh_pub,
                  "name": "Fake Phone"}
        t_offer = P.joined(P.offer_parts(client, server, self.tls_sha256))
        offer = {"device_id": me.device_id, "nonce": C.b64u(nonce_s), "name": "Fake Phone", "model": "Pixel 8",
                 "os_version": "15", "ik_sig_pub": C.b64u(me.sig_pub), "ik_dh_pub": C.b64u(me.dh_pub),
                 "tls_sha256": C.b64u(self.tls_sha256), "mac": C.b64u(P.hmac_sha256(k_pa, t_offer))}
        ws.send(json.dumps(C.plain_envelope("pair", "offer", offer)))
        reply = C.open_plain(json.loads(ws.recv(10)))
        if reply["op"] != "confirm":
            return
        c = reply["data"]
        sig_c = C.b64u_decode(c["sig"], 64)
        mac = P.hmac_sha256(k_pa, P.joined(P.confirm_parts(t_offer, c["pair_id"], c["created_at"], sig_c)))
        if not hmac.compare_digest(mac, C.b64u_decode(c["mac"], 32)):
            ws.send(json.dumps(C.plain_envelope("pair", "error", {"code": "AUTH_FAILED", "message": "x"})))
            return
        shared = x25519_dh(me.dh_priv, client["ik_dh_pub"])
        prk = hkdf(shared + k_pin, C.PAIR_INFO, 32, hashlib.sha256(pair_salt_input(me.device_id, client["device_id"]))
                   .digest())
        att = P.joined(P.attestation_parts(c["pair_id"], me.device_id, client["device_id"], me.sig_pub,
                                           client["ik_sig_pub"], c["created_at"]))
        assert C.ed25519_verify(client["ik_sig_pub"], att, sig_c)
        sig_s = me.sign(att)
        self.pairs[c["pair_id"]] = {"peer": client["device_id"], "prk": prk, "security_code": C.security_code(att)}
        done = {"sig": C.b64u(sig_s), "prk_check": C.b64u(P.hmac_sha256(prk, P.prk_check_input("server", c["pair_id"]))),
                "mac": C.b64u(P.hmac_sha256(k_pa, P.joined(P.done_parts(c["pair_id"], sig_s))))}
        ws.send(json.dumps(C.plain_envelope("pair", "done", done)))
        try:
            ws.recv(2)
        except Exception:  # noqa: BLE001 — the client closes after done
            pass

    # ----- /v1/ctl ---------------------------------------------------------------------------------------------
    def _ctl(self, ws) -> None:
        hello = C.open_plain(json.loads(ws.recv(5)))["data"]
        pair = self.pairs.get(hello["pair_id"])
        if pair is None:
            ws.send(json.dumps(C.plain_envelope("session", "error", {"code": "PAIR_UNKNOWN", "message": "x"})))
            ws.close(4401, "PAIR_UNKNOWN")
            return
        prk = pair["prk"]
        k_auth = hkdf(prk, C.SESSION_AUTH_INFO, 32)
        eph_c, nonce_c = C.b64u_decode(hello["eph"], 32), C.b64u_decode(hello["nonce"], 32)
        t1 = b"HL1|hello|" + uuid_bytes(hello["pair_id"]) + uuid_bytes(hello["device_id"]) + eph_c + nonce_c
        if not hmac.compare_digest(hmac256(k_auth, t1), C.b64u_decode(hello["mac"], 32)):
            ws.close(4401, "AUTH_FAILED")
            return
        eph_s, nonce_s = os.urandom(32), os.urandom(32)
        t2 = b"HL1|welcome|" + t1 + uuid_bytes(self.identity.device_id) + x25519_pub(eph_s) + nonce_s
        welcome = {"device_id": self.identity.device_id, "eph": C.b64u(x25519_pub(eph_s)), "nonce": C.b64u(nonce_s),
                   "mac": C.b64u(hmac256(k_auth, t2))}
        ws.send(json.dumps(C.plain_envelope("session", "welcome", welcome)))
        secret = hkdf(x25519_dh(eph_s, eph_c) + prk, C.SESSION_INFO, 64, hashlib.sha256(t2).digest())
        k_c2s, k_s2c = secret[:32], secret[32:]
        def send(typ: str, body: dict) -> str:
            env = C.seal(k_s2c, typ, C.compact_json(body).encode())
            ws.send(json.dumps(env))
            return env["id"]

        def send_raw(typ: str, plaintext: bytes) -> str:
            env = C.seal(k_s2c, typ, plaintext)
            ws.send(json.dumps(env))
            return env["id"]

        self._session, self._session_raw = send, send_raw
        send("capability", {"op": "hello", "data": PHONE_CAPABILITY})
        for frame in ws:
            env = json.loads(frame)
            body, binary = C.parse_plaintext(C.open_sealed(k_c2s, env))
            self.received.append({"type": env["type"], "body": body, "binary": binary})
            reply = self._answer(env["type"], body)
            if reply is not None:
                send("ack", {"re": env["id"], "ok": True, "data": reply})

    def serve_relayed(self, channel) -> threading.Thread:
        """Serves one /v1/ctl session that arrives through a relay channel (0.4.3) instead of the LAN socket."""
        th = threading.Thread(target=self._ctl, args=(_ChannelSocket(channel),), daemon=True)
        th.start()
        return th

    def emit(self, typ: str, op: str, data: dict) -> str:
        """An event or request from the phone; returns the envelope id (the `re` of a later ack)."""
        return self._session(typ, {"op": op, "data": data})

    def emit_chunk(self, transfer_id: str, index: int, data: bytes) -> str:
        """A `clipboard/chunk` of the phone (CLIP-03 API 4): binary plaintext in a sealed envelope."""
        return self._session_raw("clipboard", C.chunk_plaintext(transfer_id, index, data))

    def ack_for(self, env_id: str, timeout: float) -> dict | None:
        """The Mac's ack of the phone's envelope [env_id], or None within [timeout] seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in list(self.received):
                if m["type"] == "ack" and (m["body"] or {}).get("re") == env_id:
                    return m["body"]
            time.sleep(0.05)
        return None

    @staticmethod
    def _answer(typ: str, body: dict) -> dict | None:
        op, data = body.get("op"), body.get("data") or {}
        if typ == "clipboard" and op == "push":
            return {"clip_id": data["clip_id"], "status": "applied"}
        if typ == "sms" and op == "sync":
            return {"threads": [], "messages": [], "cursor": "eyJ2IjoxLCJpZCI6MCwidCI6MH0", "has_more": False,
                    "unread": []}
        if typ == "call_event" and op == "action":
            return {}
        return None


class _ChannelSocket:
    """The subset of a websockets connection that _ctl uses, over a relay_client.RelayChannel."""

    def __init__(self, channel) -> None:
        self.channel = channel

    def recv(self, timeout: float | None = None) -> str:
        text = self.channel.recv(timeout or 30)
        if text is None:
            raise TimeoutError
        return text

    def send(self, text: str) -> None:
        self.channel.send(text)

    def close(self, *args) -> None:
        self.channel.close()

    def __iter__(self):
        while True:
            try:
                text = self.channel.recv(1.0)
            except Exception:  # noqa: BLE001 — the relay link closed: the session is over
                return
            if text is not None:
                yield text


PHONE_CAPABILITY = {
    "protocol": 1, "app_version": "1.0.0 (1)", "platform": "android", "os_version": "15", "model": "Pixel 8",
    "features": {"clipboard": {"enabled": True, "auto_send": False, "max_text_bytes": 1048576,
                               "max_image_bytes": 10485760, "mimes": ["text/plain", "image/png", "image/jpeg"]},
                 "sms": {"enabled": True, "can_send": True, "default_sub_id": 1,
                         "sims": [{"sub_id": 1, "slot": 0, "label": "SIM 1"}]},
                 "call": {"enabled": True, "can_answer": True, "can_end": True, "caller_id": True},
                 "relay": {"enabled": False}},
    "permissions_missing": []}
