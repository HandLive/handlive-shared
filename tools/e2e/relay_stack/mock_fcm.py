"""Mock FCM HTTP v1 and its OAuth2 token endpoint (HTTP/1.1, no TLS), for the relay's FCM client.

    tools/.venv/bin/python tools/e2e/relay_stack/mock_fcm.py --port 18445 --public-key keys/fcm-public.pem \
        --project handlive-e2e --client-email relay@handlive-e2e.iam.gserviceaccount.com --capture captures/fcm.jsonl

- `POST /token`: the JWT-bearer grant of the service account (RS256 assertion checked as Google would) → an access
  token valid 3,599 s; a bad assertion gets 400 `invalid_grant`.
- `POST /v1/projects/<project>/messages:send`: needs a token this mock issued; a registration token that starts with
  `unregistered` gets 404 with errorCode `UNREGISTERED` (CONN-04 E3), any other 200 with a message name.
Both are appended to the capture file; the assertion and the access token are never written, only their verdicts.
"""
from __future__ import annotations

import argparse
import json
import secrets
import signal
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_log import CaptureLog, public_headers  # noqa: E402
from jwt_verify import load_public_key, verify_fcm_assertion  # noqa: E402

JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
UNREGISTERED_PREFIX = "unregistered"


class FcmMock:
    def __init__(self, public_key, project: str, client_email: str, capture: CaptureLog) -> None:
        self.public_key, self.project, self.client_email, self.capture = public_key, project, client_email, capture
        self.issued: set[str] = set()
        self.sent = 0
        self.lock = threading.Lock()

    def token(self, form: dict, token_uri: str) -> tuple[int, dict]:
        grant = form.get("grant_type", [""])[0]
        verdict = verify_fcm_assertion(form.get("assertion", [""])[0], self.public_key, self.client_email, token_uri)
        ok = grant == JWT_BEARER_GRANT and verdict["valid"]
        self.capture.append({"provider": "fcm-oauth", "http": "HTTP/1.1", "method": "POST", "path": "/token",
                             "grant_type": grant, "assertion": verdict, "status": 200 if ok else 400})
        if not ok:
            return 400, {"error": "invalid_grant"}
        access = "e2e-access-" + secrets.token_urlsafe(24)
        with self.lock:
            self.issued.add(access)
        return 200, {"access_token": access, "expires_in": 3599, "token_type": "Bearer"}

    def send(self, path: str, headers, bearer: str, body: bytes) -> tuple[int, dict]:
        try:
            message = json.loads(body)
        except ValueError:
            message = None
        with self.lock:
            authorized = bearer in self.issued
        project_ok = path == f"/v1/projects/{self.project}/messages:send"
        token = ((message or {}).get("message") or {}).get("token", "")
        if not project_ok:
            status, reply = 404, {"error": {"code": 404, "status": "NOT_FOUND"}}
        elif not authorized:
            status, reply = 401, {"error": {"code": 401, "status": "UNAUTHENTICATED"}}
        elif message is None:
            status, reply = 400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}}
        elif token.startswith(UNREGISTERED_PREFIX):
            status, reply = 404, {"error": {"code": 404, "status": "NOT_FOUND", "details": [
                {"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": "UNREGISTERED"}]}}
        else:
            with self.lock:
                self.sent += 1
                name = f"projects/{self.project}/messages/{self.sent}"
            status, reply = 200, {"name": name}
        self.capture.append({"provider": "fcm", "http": "HTTP/1.1", "method": "POST", "path": path,
                             "headers": public_headers(headers.items()), "access_token_valid": authorized,
                             "body": message, "status": status, "reply": reply})
        return status, reply


def handler_for(mock: FcmMock):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args) -> None:  # the capture file is the log
            pass

        def do_POST(self) -> None:  # noqa: N802 (http.server naming)
            length = int(self.headers.get("content-length", "0") or 0)
            body = self.rfile.read(length) if length else b""
            path = urllib.parse.urlsplit(self.path).path
            if path == "/token":
                token_uri = f"http://{self.headers.get('host', '')}/token"
                status, reply = mock.token(urllib.parse.parse_qs(body.decode("utf-8", "replace")), token_uri)
            else:
                auth = self.headers.get("authorization", "")
                bearer = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
                status, reply = mock.send(path, self.headers, bearer, body)
            data = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def make_server(host: str, port: int, mock: FcmMock) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), handler_for(mock))
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock FCM HTTP v1 with its OAuth token endpoint")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--public-key", required=True, help="PEM of the service account key's public half")
    parser.add_argument("--project", required=True)
    parser.add_argument("--client-email", required=True)
    parser.add_argument("--capture", required=True, help="JSONL file the requests are appended to")
    args = parser.parse_args(argv)
    mock = FcmMock(load_public_key(args.public_key), args.project, args.client_email, CaptureLog(Path(args.capture)))
    server = make_server(args.host, args.port, mock)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"mock FCM on http://{args.host}:{args.port} (token URI /token)", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
