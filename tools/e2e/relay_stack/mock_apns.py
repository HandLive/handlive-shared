"""Mock APNs: HTTP/2 over cleartext with prior knowledge (h2c), the way the relay's APNs client talks to a local URL.

    tools/.venv/bin/python tools/e2e/relay_stack/mock_apns.py --port 18444 --public-key keys/apns-public.pem \
        --key-id E2EKEY0001 --team-id E2ETEAM001 --capture captures/apns.jsonl

`POST /3/device/<token>` is the production endpoint (RELAY_APNS_URL = http://127.0.0.1:<port>) and
`POST /sandbox/3/device/<token>` the sandbox one (RELAY_APNS_SANDBOX_URL = http://127.0.0.1:<port>/sandbox).
The provider token is verified as Apple would (ES256, kid, iss, age): a bad one gets 403 `InvalidProviderToken`.
A device token that starts with `dead` gets 410 `Unregistered` (CONN-04 E3); any other gets 200 with an `apns-id`.
Every request is appended to the capture file without the `authorization` header (capture_log.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import uuid
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h2.config  # noqa: E402
import h2.connection  # noqa: E402
import h2.events  # noqa: E402
import h2.exceptions  # noqa: E402
from capture_log import CaptureLog, public_headers  # noqa: E402
from jwt_verify import load_public_key, verify_apns_token  # noqa: E402

DEAD_TOKEN_PREFIX = "dead"


class ApnsMock:
    def __init__(self, public_key, key_id: str, team_id: str, capture: CaptureLog) -> None:
        self.public_key, self.key_id, self.team_id, self.capture = public_key, key_id, team_id, capture

    def answer(self, headers: dict, body: bytes) -> tuple[int, dict, dict | None]:
        """(status, response headers, JSON error body) for one request; records it."""
        path = headers.get(":path", "")
        endpoint, rest = ("sandbox", path[len("/sandbox"):]) if path.startswith("/sandbox/") else ("production", path)
        token = rest[len("/3/device/"):] if rest.startswith("/3/device/") else ""
        auth = headers.get("authorization", "")
        verdict = verify_apns_token(auth[len("bearer "):], self.public_key, self.key_id, self.team_id) \
            if auth.startswith("bearer ") else {"valid": False, "error": "no bearer provider token"}
        try:
            payload = json.loads(body) if body else None
        except ValueError:
            payload = {"unparsed_bytes": len(body)}
        if headers.get(":method") != "POST" or not token:
            status, reply = 404, {"reason": "BadPath"}
        elif not verdict["valid"]:
            status, reply = 403, {"reason": "InvalidProviderToken"}
        elif token.startswith(DEAD_TOKEN_PREFIX):
            status, reply = 410, {"reason": "Unregistered", "timestamp": 0}
        else:
            status, reply = 200, None
        apns_id = str(uuid.uuid4())
        self.capture.append({"provider": "apns", "endpoint": endpoint, "http": "HTTP/2", "method": headers.get(":method"),
                             "path": path, "device_token": token, "headers": public_headers(
                                 (k, v) for k, v in headers.items() if not k.startswith(":")),
                             "provider_token": verdict, "body": payload, "status": status,
                             "apns_id": apns_id if status == 200 else None, "reply": reply})
        return status, {"apns-id": apns_id}, reply


class H2Server(asyncio.Protocol):
    """One h2c connection; each finished stream is answered by the mock."""

    def __init__(self, mock: ApnsMock) -> None:
        self.mock = mock
        self.conn = h2.connection.H2Connection(h2.config.H2Configuration(client_side=False, header_encoding="utf-8"))
        self.streams: dict[int, tuple[dict, bytearray]] = {}
        self.transport = None

    def connection_made(self, transport) -> None:
        self.transport = transport
        self.conn.initiate_connection()
        transport.write(self.conn.data_to_send())

    def data_received(self, data: bytes) -> None:
        try:
            events = self.conn.receive_data(data)
        except h2.exceptions.ProtocolError:
            self.transport.write(self.conn.data_to_send())
            self.transport.close()
            return
        for event in events:
            if isinstance(event, h2.events.RequestReceived):
                self.streams[event.stream_id] = ({k.lower(): v for k, v in event.headers}, bytearray())
            elif isinstance(event, h2.events.DataReceived):
                self.streams.get(event.stream_id, ({}, bytearray()))[1].extend(event.data)
                self.conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
            elif isinstance(event, h2.events.StreamEnded):
                self._respond(event.stream_id)
            elif isinstance(event, h2.events.StreamReset):
                self.streams.pop(event.stream_id, None)
            elif isinstance(event, h2.events.ConnectionTerminated):
                self.transport.close()
        self.transport.write(self.conn.data_to_send())

    def _respond(self, stream_id: int) -> None:
        headers, body = self.streams.pop(stream_id, ({}, bytearray()))
        status, extra, reply = self.mock.answer(headers, bytes(body))
        if reply is None:
            self.conn.send_headers(stream_id, [(":status", str(status)), *extra.items()], end_stream=True)
            return
        data = json.dumps(reply).encode()
        self.conn.send_headers(stream_id, [(":status", str(status)), ("content-type", "application/json"),
                                           ("content-length", str(len(data))), *extra.items()])
        self.conn.send_data(stream_id, data, end_stream=True)


async def serve(host: str, port: int, mock: ApnsMock, ready: asyncio.Event | None = None) -> asyncio.AbstractServer:
    server = await asyncio.get_running_loop().create_server(lambda: H2Server(mock), host, port)
    if ready is not None:
        ready.set()
    return server


async def main_async(args) -> None:
    mock = ApnsMock(load_public_key(args.public_key), args.key_id, args.team_id, CaptureLog(Path(args.capture)))
    server = await serve(args.host, args.port, mock)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    print(f"mock APNs (h2c) on http://{args.host}:{args.port}, sandbox under /sandbox", flush=True)
    async with server:
        await stop.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock APNs (HTTP/2 prior knowledge)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--public-key", required=True, help="PEM of the provider key's public half")
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--capture", required=True, help="JSONL file the requests are appended to")
    asyncio.run(main_async(parser.parse_args(argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
