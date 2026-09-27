"""Self-test of the local relay stack's parts, without PostgreSQL, Redis, the relay or an emulator (CI).

    tools/.venv/bin/python tools/e2e/relay_stack/self_test.py

- keys: the test certificate's SANs, the OkHttp pin format;
- TLS front: X-Forwarded-For appended, Connection: close, a WebSocket carried both ways, the log lines, and a client
  that does not trust the CA logged with its TLS alert;
- mock APNs over h2c: a valid ES256 provider token → 200 with apns-id, a forged one → 403 InvalidProviderToken, a
  dead token → 410, the sandbox path, no authorization header in the capture;
- mock FCM: the RS256 JWT-bearer grant → access token → messages:send 200, a forged assertion → 400, UNREGISTERED;
  neither the assertion nor the access token in the capture;
- push envelopes: every envelope of test-vectors/push-envelope.json opens with its K_push; seal/open round trip.
"""
from __future__ import annotations

import asyncio
import base64
import json
import socket
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import h2.config  # noqa: E402
import h2.connection  # noqa: E402
import h2.events  # noqa: E402
import local_keys  # noqa: E402
import mock_apns  # noqa: E402
import mock_fcm  # noqa: E402
import push_crypto  # noqa: E402
import tls_front  # noqa: E402
from capture_log import CaptureLog, read_captures  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, padding  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature  # noqa: E402
from jwt_verify import FCM_SCOPE, load_public_key  # noqa: E402
from websockets.asyncio.server import serve as ws_serve  # noqa: E402
from websockets.sync.client import connect as ws_connect  # noqa: E402

VECTORS = HERE.parents[2] / "test-vectors" / "push-envelope.json"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(header: dict, claims: dict, sign) -> str:
    signing_input = f"{b64u(json.dumps(header).encode())}.{b64u(json.dumps(claims).encode())}"
    return f"{signing_input}.{b64u(sign(signing_input.encode()))}"


def es256(key) -> callable:
    def sign(data: bytes) -> bytes:
        r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return sign


class LoopThread:
    """An asyncio loop in a background thread for the servers under test."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro, timeout: float = 10):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------------------------------------------------

def test_keys(tmp: Path) -> local_keys.TlsFiles:
    tls = local_keys.tls_files(tmp / "tls")
    leaf = x509.load_pem_x509_certificates(tls.chain.read_bytes())[0]
    sans = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    ips = {str(ip) for ip in sans.get_values_for_type(x509.IPAddress)}
    check("server certificate SANs: 10.0.2.2, 127.0.0.1, localhost",
          ips == {"10.0.2.2", "127.0.0.1"} and sans.get_values_for_type(x509.DNSName) == ["localhost"], str(sans))
    check("pins in OkHttp format sha256/<44 base64 chars>",
          all(p.startswith("sha256/") and len(p) == 51 for p in (tls.ca_pin, tls.leaf_pin)), tls.ca_pin)
    check("key files are private (0600)", oct(tls.key.stat().st_mode & 0o777) == "0o600", oct(tls.key.stat().st_mode))
    again = local_keys.tls_files(tmp / "tls")
    check("the certificate is kept across starts (the APK's pin stays valid)", again.ca_pin == tls.ca_pin)
    return tls


async def _http_upstream(seen: list):
    async def handle(reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        seen.append(head.decode())
        body = b'{"ok":true}'
        writer.write(b"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        writer.close()
    return await asyncio.start_server(handle, "127.0.0.1", 0)


def test_tls_front(loop: LoopThread, tmp: Path, tls: local_keys.TlsFiles) -> None:
    seen: list[str] = []
    upstream = loop.run(_http_upstream(seen))
    up_port = upstream.sockets[0].getsockname()[1]
    port, log_path = free_port(), tmp / "front.log"
    loop.run(tls_front.serve(("127.0.0.1", port), ("127.0.0.1", up_port), str(tls.chain), str(tls.key),
                             tls_front.FrontLog(log_path)))
    ctx = ssl.create_default_context(cafile=str(tls.ca_cert))
    request = urllib.request.Request(f"https://127.0.0.1:{port}/v1/devices?x=1", data=b"{}", method="POST",
                                     headers={"X-Forwarded-For": "10.1.2.3", "User-Agent": "okhttp/4.12.0",
                                              "Connection": "keep-alive"})
    with urllib.request.urlopen(request, context=ctx, timeout=5) as response:
        status = response.status
    head = seen[0] if seen else ""
    check("TLS front forwards to the relay (certificate verified with the CA)", status == 201, str(status))
    check("X-Forwarded-For gets the client address appended", "X-Forwarded-For: 10.1.2.3, 127.0.0.1" in head, head)
    check("X-Forwarded-Proto https and Connection: close", "X-Forwarded-Proto: https" in head
          and "Connection: close" in head and "keep-alive" not in head, head)
    try:
        urllib.request.urlopen(f"https://127.0.0.1:{port}/v1/devices", context=ssl.create_default_context(),
                               timeout=5)
        refused = False
    except (urllib.error.URLError, ssl.SSLError):
        refused = True
    time.sleep(0.3)
    log = log_path.read_text()
    check("front log: method, path without query, status, UA", "POST /v1/devices 201 TLSv1.3 ua='okhttp/4.12.0'" in log
          and "x=1" not in log, log)
    check("a client that does not trust the CA is logged with its TLS alert",
          refused and "TLS handshake failed: TLSV1_ALERT_UNKNOWN_CA" in log, log)

    async def echo(ws):
        async for message in ws:
            await ws.send(message)

    async def start_echo():
        return await ws_serve(echo, "127.0.0.1", 0)

    ws_server = loop.run(start_echo())
    ws_port = list(ws_server.sockets)[0].getsockname()[1]
    ws_front = free_port()
    loop.run(tls_front.serve(("127.0.0.1", ws_front), ("127.0.0.1", ws_port), str(tls.chain), str(tls.key),
                             tls_front.FrontLog(log_path)))
    with ws_connect(f"wss://127.0.0.1:{ws_front}/v1/relay", ssl=ctx, open_timeout=5) as ws:
        ws.send('{"to":"x","env":{}}')
        text = ws.recv(timeout=5)
        ws.send(b"HR\x01\x01" + bytes(16) + b"HL")
        binary = ws.recv(timeout=5)
        opened = "GET /v1/relay 101 websocket" in log_path.read_text()
    time.sleep(0.3)
    check("a WebSocket is carried both ways, text and binary", text == '{"to":"x","env":{}}'
          and binary == b"HR\x01\x01" + bytes(16) + b"HL", repr(text))
    check("an open WebSocket is logged at once, and again when it closes",
          opened and "/v1/relay websocket closed after" in log_path.read_text(), log_path.read_text()[-300:])


def h2_post(port: int, path: str, headers: list, body: bytes) -> tuple[int, dict, bytes]:
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    conn = h2.connection.H2Connection(h2.config.H2Configuration(client_side=True, header_encoding="utf-8"))
    conn.initiate_connection()
    stream = conn.get_next_available_stream_id()
    conn.send_headers(stream, [(":method", "POST"), (":path", path), (":scheme", "http"),
                               (":authority", f"127.0.0.1:{port}"), *headers])
    conn.send_data(stream, body, end_stream=True)
    sock.sendall(conn.data_to_send())
    status, got, data = 0, {}, b""
    try:
        while chunk := sock.recv(65536):
            for event in conn.receive_data(chunk):
                if isinstance(event, h2.events.ResponseReceived):
                    got = dict(event.headers)
                    status = int(got[":status"])
                elif isinstance(event, h2.events.DataReceived):
                    data += event.data
                    conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                elif isinstance(event, h2.events.StreamEnded):
                    return status, got, data
            sock.sendall(conn.data_to_send())
    finally:
        sock.close()
    return status, got, data


def test_mock_apns(loop: LoopThread, tmp: Path) -> None:
    p8, pub = local_keys.apns_key(tmp / "keys")
    key = serialization.load_pem_private_key(p8.read_bytes(), None)
    capture = tmp / "apns.jsonl"
    mock = mock_apns.ApnsMock(load_public_key(pub), local_keys.APNS_KEY_ID, local_keys.APNS_TEAM_ID,
                              CaptureLog(capture))
    port = free_port()
    loop.run(mock_apns.serve("127.0.0.1", port, mock))
    good = jwt({"alg": "ES256", "kid": local_keys.APNS_KEY_ID}, {"iss": local_keys.APNS_TEAM_ID,
                                                                "iat": int(time.time())}, es256(key))
    forged = jwt({"alg": "ES256", "kid": local_keys.APNS_KEY_ID}, {"iss": local_keys.APNS_TEAM_ID,
                                                                  "iat": int(time.time())},
                 es256(ec.generate_private_key(ec.SECP256R1())))
    body = json.dumps({"aps": {"alert": {"loc-key": "push.sms_new"}}, "p": "x", "hl": "e30="}).encode()
    common = [("apns-push-type", "alert"), ("apns-topic", "app.handlive.ios"), ("apns-priority", "10")]
    ok = h2_post(port, "/3/device/ab12", [("authorization", f"bearer {good}"), *common], body)
    bad = h2_post(port, "/3/device/ab12", [("authorization", f"bearer {forged}"), *common], body)
    dead = h2_post(port, "/sandbox/3/device/dead01", [("authorization", f"bearer {good}"), *common], body)
    check("mock APNs: valid provider token → 200 with apns-id", ok[0] == 200 and "apns-id" in ok[1], str(ok[:2]))
    check("mock APNs: forged provider token → 403 InvalidProviderToken",
          bad[0] == 403 and json.loads(bad[2])["reason"] == "InvalidProviderToken", str(bad))
    check("mock APNs: dead token on the sandbox → 410 Unregistered",
          dead[0] == 410 and json.loads(dead[2])["reason"] == "Unregistered", str(dead))
    seen = read_captures(capture)
    text = capture.read_text()
    check("APNs capture: 3 requests, endpoints, verdicts, body, no authorization",
          [c["status"] for c in seen] == [200, 403, 410] and [c["endpoint"] for c in seen][2] == "sandbox"
          and seen[0]["provider_token"]["valid"] and seen[0]["body"]["p"] == "x" and "authorization" not in text
          and good not in text, text[:300])


def test_mock_fcm(tmp: Path) -> None:
    port = free_port()
    token_uri = f"http://127.0.0.1:{port}/token"
    account_path, pub = local_keys.fcm_account(tmp / "keys", token_uri)
    account = json.loads(account_path.read_text())
    key = serialization.load_pem_private_key(account["private_key"].encode(), None)
    capture = tmp / "fcm.jsonl"
    mock = mock_fcm.FcmMock(load_public_key(pub), local_keys.FCM_PROJECT, local_keys.FCM_CLIENT_EMAIL,
                            CaptureLog(capture))
    server = mock_fcm.make_server("127.0.0.1", port, mock)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()

    def rs256(data: bytes) -> bytes:
        return key.sign(data, padding.PKCS1v15(), hashes.SHA256())

    now = int(time.time())
    claims = {"iss": account["client_email"], "scope": FCM_SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600}

    def post(path: str, data: bytes, headers: dict) -> tuple[int, dict]:
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    form = {"Content-Type": "application/x-www-form-urlencoded"}
    grant = "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion="
    assertion = jwt({"alg": "RS256", "typ": "JWT"}, claims, rs256)
    status, token = post("/token", (grant + assertion).encode(), form)
    forged_key = ec.generate_private_key(ec.SECP256R1())
    forged, _ = post("/token", (grant + jwt({"alg": "RS256"}, claims, es256(forged_key))).encode(), form)
    access = token.get("access_token", "")
    message = {"message": {"token": "e2e-fcm-1", "data": {"t": "wake", "p": "x", "r": "user_open"},
                           "android": {"priority": "HIGH", "ttl": "60s", "collapse_key": "wake"}}}
    auth = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}
    sent = post(f"/v1/projects/{local_keys.FCM_PROJECT}/messages:send", json.dumps(message).encode(), auth)
    message["message"]["token"] = "unregistered-1"
    gone = post(f"/v1/projects/{local_keys.FCM_PROJECT}/messages:send", json.dumps(message).encode(), auth)
    server.shutdown()
    check("mock FCM: valid JWT-bearer assertion → access token; forged → 400",
          status == 200 and access and forged == 400, f"{status} {forged}")
    check("mock FCM: messages:send with the access token → 200, UNREGISTERED → 404",
          sent[0] == 200 and gone[0] == 404 and gone[1]["error"]["details"][0]["errorCode"] == "UNREGISTERED",
          f"{sent} {gone}")
    text = capture.read_text()
    check("FCM capture: verdicts and bodies, never the assertion or the access token",
          assertion not in text and access not in text and '"valid":true' in text and "e2e-fcm-1" in text, text[:300])


def test_push_envelopes() -> None:
    vectors = [v for v in json.loads(VECTORS.read_text())["vectors"] if v.get("kind") == "envelope"]
    opened = 0
    for v in vectors:
        head, payload = push_crypto.open_hl(bytes.fromhex(v["k_push"]), v["env_b64"])
        opened += head["type"] == v["type"] and payload == json.loads(v["plaintext"])
    check("every push-envelope.json envelope opens with its K_push", vectors and opened == len(vectors),
          f"{opened}/{len(vectors)}")
    key = push_crypto.push_key(bytes(32))
    call_id, ringing = push_crypto.fake_call_ringing()
    head, payload = push_crypto.open_hl(key, push_crypto.seal(key, "call_event", ringing))
    summary = push_crypto.summary(head, payload)
    check("seal/open round trip; the summary keeps no number",
          summary["state"] == "ringing" and summary["call_id"] == call_id and "+1555" not in json.dumps(summary),
          str(summary))
    try:
        push_crypto.open_hl(push_crypto.push_key(bytes([1]) * 32), push_crypto.seal(key, "sms", {"op": "new"}))
        check("another K_push does not open the envelope", False)
    except ValueError:
        check("another K_push does not open the envelope", True)


def main() -> int:
    loop = LoopThread()
    with tempfile.TemporaryDirectory(prefix="hl-relay-stack-") as t:
        tmp = Path(t)
        tls = test_keys(tmp)
        test_tls_front(loop, tmp, tls)
        test_mock_apns(loop, tmp)
        test_mock_fcm(tmp)
    test_push_envelopes()
    failed = [(n, d) for n, ok, d in RESULTS if not ok]
    for name, detail in failed:
        print(f"  FAIL {name}: {detail[:400]}")
    print(f"relay stack self-test: {len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
