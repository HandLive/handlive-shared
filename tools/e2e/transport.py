"""Transports of the fake Mac: the phone's LAN WSS (0.4.1) and, through relay_client.RelayChannel, the relay (0.4.3).

A transport carries whole envelope texts; the session above it (mac_session.py) never knows which one it uses.
LanTransport opens TCP, wraps it in TLS 1.3, compares the SHA-256 of the leaf certificate (DER) with the pin before
the WebSocket upgrade (CONN-01 API 3), then speaks RFC 6455 with websockets' threading client: WS ping every 15 s,
10 s for the pong (WS_PING_INTERVAL / PONG_TIMEOUT, CONN-02 API 1), no permessage-deflate, no proxy.
"""
from __future__ import annotations

import hashlib
import hmac
import socket
import ssl

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

MAX_FRAME = 1 << 20  # envelopes are ≤ 256 KiB (0.5.1 rule 4); a larger frame is a phone bug, not a crash here


class TransportClosed(Exception):
    def __init__(self, code: int | None, reason: str = "") -> None:
        super().__init__(f"closed {code} {reason}".strip())
        self.code = code
        self.reason = reason


class PinMismatch(Exception):
    """TLS_PIN_MISMATCH (0.8.1): the certificate is not the pinned one; nothing was sent."""


def tls_context() -> ssl.SSLContext:
    """TLS 1.3 only; the self-signed certificate is trusted by its pin, not by a CA or a host name (0.4.1)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class LanTransport:
    label = "lan"

    def __init__(self, host: str, port: int, path: str, pin: bytes | None, open_timeout: float = 10.0,
                 keepalive: bool = True) -> None:
        raw = socket.create_connection((host, port), timeout=open_timeout)
        try:
            self._tls = tls_context().wrap_socket(raw, server_hostname=None)
        except (OSError, ssl.SSLError):
            raw.close()
            raise
        self.tls_version = self._tls.version()
        self.cert_sha256 = hashlib.sha256(self._tls.getpeercert(binary_form=True)).digest()
        if pin is not None and not hmac.compare_digest(pin, self.cert_sha256):
            self._tls.close()
            raise PinMismatch(f"{host}:{port}")
        self._tls.settimeout(None)
        self.ws = connect(f"ws://{host}:{port}{path}", sock=self._tls, compression=None, proxy=None,
                          open_timeout=open_timeout, ping_interval=15 if keepalive else None, ping_timeout=10,
                          close_timeout=5, max_size=MAX_FRAME, user_agent_header=None)

    def send(self, text: str) -> None:
        try:
            self.ws.send(text)
        except ConnectionClosed as exc:
            raise TransportClosed(self.close_code, self.close_reason) from exc

    def recv(self, timeout: float) -> str | bytes | None:
        """One frame, None after `timeout` s; TransportClosed once the connection is gone."""
        try:
            return self.ws.recv(timeout=timeout)
        except TimeoutError:
            return None
        except ConnectionClosed as exc:
            raise TransportClosed(self.close_code, self.close_reason) from exc

    @property
    def close_code(self) -> int | None:
        return self.ws.close_code

    @property
    def close_reason(self) -> str:
        return self.ws.close_reason or ""

    def close(self, code: int = 1000, reason: str = "") -> None:
        try:
            self.ws.close(code, reason)
        except (OSError, ConnectionClosed):
            pass

    def abort(self) -> None:
        """Drops the TCP connection without a close frame — the client left the network (CONN-02 E1, CONN-03)."""
        try:
            self._tls.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.ws.close_socket()
