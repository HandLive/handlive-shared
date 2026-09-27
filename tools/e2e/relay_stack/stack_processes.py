"""Processes of the local relay stack: started detached (they outlive `relay_stack.py up`), recorded in pid files,
and stopped only when the pid still runs the command that was started — a reused pid is never signalled.

PostgreSQL runs through pg_ctl on 127.0.0.1 with Unix sockets off; Redis without persistence. Nothing touches the
system services on the default ports.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path

from stack_config import DB_NAME, DB_PASSWORD, DB_USER, PG_BIN, REDIS_SERVER, Layout


class StackError(RuntimeError):
    pass


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def wait_port(port: int, timeout_s: float, what: str, pid: int | None = None) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if port_open(port):
            return
        if pid is not None and not alive(pid):
            raise StackError(f"{what} exited before listening on {port}")
        time.sleep(0.2)
    raise StackError(f"{what} is not listening on 127.0.0.1:{port} after {timeout_s:.0f} s")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def command_of(pid: int) -> str:
    out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=10)
    return out.stdout.strip()


def spawn(layout: Layout, name: str, argv: list[str], marker: str, env: dict | None = None) -> int:
    """Start `argv` in its own session, output to logs/<name>.log; remember the pid and a `marker` its command line
    shows in `ps` (a port, a path) in run/<name>.pid."""
    log = (layout.logs / f"{name}.log").open("ab")
    process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               env={**os.environ, **(env or {})}, start_new_session=True, cwd=layout.root)
    log.close()
    (layout.run / f"{name}.pid").write_text(f"{process.pid}\n{marker}")
    return process.pid


def recorded(layout: Layout, name: str) -> int | None:
    """The pid of `name` if it still runs what was started (its marker is in the command line)."""
    path = layout.run / f"{name}.pid"
    if not path.exists():
        return None
    pid_text, _, marker = path.read_text().partition("\n")
    pid = int(pid_text)
    if not alive(pid):
        return None
    return pid if marker in command_of(pid) else None


def stop(layout: Layout, name: str, timeout_s: float = 10) -> str:
    pid = recorded(layout, name)
    (layout.run / f"{name}.pid").unlink(missing_ok=True)
    if pid is None:
        return f"{name}: not running"
    os.killpg(pid, signal.SIGTERM) if os.getpgid(pid) == pid else os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_s
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if alive(pid):
        os.kill(pid, signal.SIGKILL)
        return f"{name}: killed (pid {pid})"
    return f"{name}: stopped (pid {pid})"


# PostgreSQL -------------------------------------------------------------------------------------------------------

def _pg_env() -> dict:
    return {**os.environ, "PGPASSWORD": DB_PASSWORD}


def pg_init(layout: Layout) -> None:
    if (layout.pg_data / "PG_VERSION").exists():
        return
    pwfile = layout.run / "pg.pw"
    pwfile.write_text(DB_PASSWORD + "\n")
    os.chmod(pwfile, 0o600)
    try:
        subprocess.run([str(PG_BIN / "initdb"), "-D", str(layout.pg_data), "-U", DB_USER, f"--pwfile={pwfile}",
                        "-A", "scram-sha-256", "-E", "UTF8", "--locale=C", "--no-instructions"],
                       check=True, capture_output=True, text=True, timeout=120)
    except subprocess.CalledProcessError as error:
        raise StackError(f"initdb failed: {error.stderr.strip()[-400:]}") from error
    finally:
        pwfile.unlink(missing_ok=True)


def pg_start(layout: Layout) -> None:
    options = (f"-c listen_addresses=127.0.0.1 -c port={layout.ports.postgres} -c unix_socket_directories='' "
               f"-c logging_collector=off")
    result = subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(layout.pg_data), "-l", str(layout.logs / "postgres.log"),
                             "-o", options, "-w", "-t", "60", "start"], capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        raise StackError(f"PostgreSQL did not start: {(result.stdout + result.stderr).strip()[-400:]}")
    exists = psql(layout, f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}'", db="postgres")
    if exists.strip() != "1":
        subprocess.run([str(PG_BIN / "createdb"), "-h", "127.0.0.1", "-p", str(layout.ports.postgres), "-U", DB_USER,
                        DB_NAME], check=True, capture_output=True, env=_pg_env(), timeout=60)


def pg_running(layout: Layout) -> bool:
    result = subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(layout.pg_data), "status"], capture_output=True,
                            timeout=30)
    return result.returncode == 0


def pg_stop(layout: Layout) -> str:
    if not (layout.pg_data / "postmaster.pid").exists():
        return "postgres: not running"
    result = subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(layout.pg_data), "-m", "fast", "-w", "-t", "60", "stop"],
                            capture_output=True, text=True, timeout=90)
    return "postgres: stopped" if result.returncode == 0 else f"postgres: {result.stderr.strip()[-200:]}"


def psql(layout: Layout, sql: str, db: str = DB_NAME) -> str:
    """Run one query; unaligned, tuples only, `|` separated."""
    result = subprocess.run([str(PG_BIN / "psql"), "-h", "127.0.0.1", "-p", str(layout.ports.postgres), "-U", DB_USER,
                             "-d", db, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql],
                            capture_output=True, text=True, env=_pg_env(), timeout=60)
    if result.returncode != 0:
        raise StackError(f"psql: {result.stderr.strip()[-300:]}")
    return result.stdout


# Redis ------------------------------------------------------------------------------------------------------------

def redis_start(layout: Layout) -> int:
    # redis-server renames its process to "redis-server 127.0.0.1:<port>": that is the marker.
    return spawn(layout, "redis", [REDIS_SERVER, "--bind", "127.0.0.1", "--port", str(layout.ports.redis),
                                   "--save", "", "--appendonly", "no", "--dir", str(layout.redis_data),
                                   "--protected-mode", "yes", "--daemonize", "no"],
                 marker=f"127.0.0.1:{layout.ports.redis}")


def redis_command(layout: Layout, *args: str) -> str:
    """One Redis command over RESP; returns the reply as text (simple parser: enough for PING, EXISTS, KEYS)."""
    payload = f"*{len(args)}\r\n" + "".join(f"${len(a.encode())}\r\n{a}\r\n" for a in args)
    with socket.create_connection(("127.0.0.1", layout.ports.redis), timeout=5) as s:
        s.sendall(payload.encode())
        time.sleep(0.05)
        data = s.recv(65536).decode(errors="replace")
    return data.strip()
