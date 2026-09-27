"""TLS front of the local relay: terminates TLS with the stack's test certificate and forwards to the relay's plain
HTTP port, adding `X-Forwarded-For` like the reverse proxy of a real deployment (Caddy or nginx, deployment guide).

    tools/.venv/bin/python tools/e2e/relay_stack/tls_front.py --listen 127.0.0.1:18443 --upstream 127.0.0.1:18080 \
        --cert keys/tls/server-chain.pem --key keys/tls/server.key --log logs/tls-front.log

Each connection carries one request: the front appends the client address to `X-Forwarded-For`, sets
`X-Forwarded-Proto: https` and, except for a WebSocket upgrade, `Connection: close`; then it copies bytes both ways.
ALPN offers only `http/1.1`. The relay must trust the front (`RELAY_TRUSTED_PROXIES=127.0.0.1`).

The log has one line per request — client address, method, path without the query, the upstream status, the
User-Agent, bytes each way and the duration — and one line per failed TLS handshake with the TLS alert, which is
how a client that refuses the certificate shows up (CONN-03 E7). No body and no header value other than the
User-Agent is logged.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import ssl
import sys
import time
from pathlib import Path

MAX_HEAD = 64 * 1024
HEAD_TIMEOUT_S = 30


class FrontLog:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def write(self, text: str) -> None:
        now = time.time()
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now))}.{int(now * 1000) % 1000:03d}Z {text}"
        if self.path is None:
            print(line, flush=True)
            return
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def rewrite_head(head: bytes, client_ip: str) -> tuple[bytes, dict]:
    """The request head with the forwarding headers; also returns what the log needs."""
    lines = head.decode("latin-1").split("\r\n")
    method, target, version = (lines[0].split(" ", 2) + ["", ""])[:3]
    headers = [line for line in lines[1:] if line]
    names = {line.split(":", 1)[0].strip().lower(): line.split(":", 1)[1].strip() for line in headers if ":" in line}
    upgrade = names.get("upgrade", "").lower() == "websocket"
    forwarded = names.get("x-forwarded-for")
    kept = [line for line in headers
            if line.split(":", 1)[0].strip().lower() not in {"x-forwarded-for", "x-forwarded-proto"}
            and (upgrade or line.split(":", 1)[0].strip().lower() not in {"connection", "keep-alive"})]
    kept.append(f"X-Forwarded-For: {forwarded + ', ' if forwarded else ''}{client_ip}")
    kept.append("X-Forwarded-Proto: https")
    if not upgrade:
        kept.append("Connection: close")
    new_head = "\r\n".join([f"{method} {target} {version}", *kept, "", ""]).encode("latin-1")
    info = {"method": method, "path": target.split("?", 1)[0], "ua": names.get("user-agent", "-"),
            "upgrade": upgrade}
    return new_head, info


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, counter: list, first: list | None) -> None:
    try:
        while data := await reader.read(65536):
            if first is not None and not first:
                first.append(data[:64])
            counter[0] += len(data)
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError):
        pass
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
            else:
                writer.close()
        except (OSError, RuntimeError):
            pass


class Front:
    """Plain TCP accept, then TLS per connection, so a refused handshake is logged with its alert."""

    def __init__(self, upstream: tuple[str, int], ctx: ssl.SSLContext, log: FrontLog) -> None:
        self.upstream, self.ctx, self.log = upstream, ctx, log

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername") or ("?", 0)
        started = time.monotonic()
        try:
            await writer.start_tls(self.ctx, ssl_handshake_timeout=HEAD_TIMEOUT_S)
        except ssl.SSLError as error:  # the client's TLS alert, e.g. SSLV3_ALERT_CERTIFICATE_UNKNOWN
            self.log.write(f"{peer[0]} TLS handshake failed: {error.reason or error}")
            writer.close()
            return
        except (OSError, asyncio.TimeoutError):  # closed before a ClientHello (a port probe) or silent
            writer.close()
            return
        tls = writer.get_extra_info("ssl_object")
        tls_version = tls.version() if tls is not None else "?"
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT_S)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError,
                ssl.SSLError):
            writer.close()
            return
        new_head, info = rewrite_head(head, peer[0])
        try:
            up_reader, up_writer = await asyncio.open_connection(*self.upstream, limit=MAX_HEAD)
        except OSError as error:
            self.log.write(f"{peer[0]} {info['method']} {info['path']} upstream unreachable: {error.strerror}")
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        up_writer.write(new_head)
        sent, received, first = [len(new_head)], [0], []
        await asyncio.gather(_pipe(reader, up_writer, sent, None), _pipe(up_reader, writer, received, first))
        status = first[0].split(b" ", 2)[1].decode("latin-1", "replace") if first and b" " in first[0] else "-"
        kind = " websocket" if info["upgrade"] else ""
        self.log.write(f"{peer[0]} {info['method']} {info['path']} {status}{kind} {tls_version} ua={info['ua']!r} "
                       f"out={sent[0]}B in={received[0]}B {int((time.monotonic() - started) * 1000)}ms")
        for w in (writer, up_writer):
            w.close()


def tls_context(cert: str, key: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    ctx.set_alpn_protocols(["http/1.1"])
    return ctx


async def serve(listen: tuple[str, int], upstream: tuple[str, int], cert: str, key: str,
                log: FrontLog) -> asyncio.AbstractServer:
    front = Front(upstream, tls_context(cert, key), log)
    return await asyncio.start_server(front.handle, *listen, limit=MAX_HEAD)


def _addr(text: str) -> tuple[str, int]:
    host, port = text.rsplit(":", 1)
    return host, int(port)


async def main_async(args) -> None:
    log = FrontLog(Path(args.log) if args.log else None)
    server = await serve(_addr(args.listen), _addr(args.upstream), args.cert, args.key, log)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    print(f"TLS front on https://{args.listen} → http://{args.upstream}", flush=True)
    async with server:
        await stop.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TLS front of the local relay (adds X-Forwarded-For)")
    parser.add_argument("--listen", required=True, help="host:port to listen on")
    parser.add_argument("--upstream", required=True, help="host:port of the relay's plain HTTP listener")
    parser.add_argument("--cert", required=True, help="PEM chain: server certificate then CA")
    parser.add_argument("--key", required=True, help="PEM private key of the server certificate")
    parser.add_argument("--log", help="log file (stdout when omitted)")
    asyncio.run(main_async(parser.parse_args(argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
