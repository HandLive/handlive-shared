"""End-to-end test of the real Android app on an emulator against a fake Mac (see README.md).

    tools/.venv/bin/python tools/e2e/e2e.py setup clipboard sms calls --serial emulator-5556 --apk <app-foss-debug.apk>
    tools/.venv/bin/python tools/e2e/e2e.py all --serial emulator-5556 --apk <apk> --step-delay 0

Scenarios run in the order given; `all` = setup clipboard sms calls. Exit code 1 when any step failed.
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adb_device import Adb, AdbError  # noqa: E402
from fake_mac import FakeClient  # noqa: E402
from mac_session import MacSession, SessionRefused  # noqa: E402
from steps import Recorder  # noqa: E402
from transport import PinMismatch, TransportClosed  # noqa: E402
from ui_automator import Ui  # noqa: E402

SCENARIOS = ("setup", "clipboard", "sms", "calls")
CLIENT_NAME = "E2E Test Mac"


@dataclass
class Ctx:
    args: argparse.Namespace
    adb: Adb
    ui: Ui
    rec: Recorder
    client: FakeClient
    state_dir: Path
    sdk: int
    session: MacSession | None = None
    followers: list = field(default_factory=list)

    def pause(self) -> None:
        self.ui.pause()

    def connect(self, attempts: int = 3, **cap) -> MacSession | None:
        """A fresh /v1/ctl session (CONN-01 steps 4–10); None when every attempt failed (the reason is printed)."""
        self.disconnect()
        last = ""
        for i in range(attempts):
            s = self.client.session(**cap)
            try:
                s.open()
                self.session = s
                return s
            except (SessionRefused, TransportClosed, PinMismatch, OSError) as exc:
                last = f"{type(exc).__name__}: {exc}"
                try:
                    s.abort()
                except Exception:  # noqa: BLE001 — best effort after a failed open
                    pass
                time.sleep(1 + i)
        self.rec.check("open a /v1/ctl session", "CONN-01", False, last)
        return None

    def disconnect(self, bye: bool = True) -> None:
        if self.session is not None:
            self.session.close(bye=bye)
            self.session = None


def default_host_port(serial: str) -> int:
    """47800 + (console port − 5500): emulator-5556 → 47856, so runs on other emulators never share a port."""
    m = re.search(r"emulator-(\d+)", serial)
    return 47800 + (int(m.group(1)) - 5500) if m else 47899


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenarios", nargs="+", choices=SCENARIOS + ("all",))
    p.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL", "emulator-5556"))
    p.add_argument("--apk", type=Path, help="app-foss-debug.apk to (re)install in `setup`; without it setup keeps "
                                            "the installed app and only pairs")
    p.add_argument("--state-dir", type=Path, help="pair state, logs and results (never inside the repository); "
                                                  "default $HL_E2E_STATE_DIR or <tmp>/handlive-e2e/<serial>")
    p.add_argument("--host-port", type=int, help="host end of `adb forward` (default 47800 + port − 5500)")
    p.add_argument("--step-delay", type=float, default=1.0, help="seconds between visible actions (0 = fast)")
    p.add_argument("--sdk", default=None, help="Android SDK root (default $ANDROID_HOME)")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    names = list(SCENARIOS) if "all" in args.scenarios else list(dict.fromkeys(args.scenarios))
    state_dir = args.state_dir or Path(os.environ.get("HL_E2E_STATE_DIR") or
                                       Path(tempfile.gettempdir()) / "handlive-e2e" / args.serial)
    state_dir.mkdir(parents=True, exist_ok=True)
    port = args.host_port or default_host_port(args.serial)
    adb = Adb(args.serial, args.sdk)
    adb.wait_boot()
    rec = Recorder(args.serial, state_dir / "results.json")
    client = FakeClient(state_dir / "pair-macos.json", CLIENT_NAME, "macos", port=port,
                        bench_file=state_dir / "hlbench-mac.log")
    ctx = Ctx(args, adb, Ui(adb, args.step_delay), rec, client, state_dir, adb.sdk_int())
    print(f"device {args.serial} (API {ctx.sdk}), forward tcp:{port} → phone :47800, state {state_dir}")
    adb.keep_awake()
    adb.forward(port)
    ctx.followers.append(adb.logcat_follow(state_dir / "logcat-hlbench.log", "-s", "HLBENCH:I"))
    try:
        for name in names:
            rec.begin(name)
            try:
                importlib.import_module(f"scenario_{name}").run(ctx)
            except (AdbError, TransportClosed, SessionRefused, OSError, AssertionError) as exc:
                rec.check("scenario finished", name, False, f"stopped: {type(exc).__name__}: {exc}")
            crashes = adb.crashes()
            rec.check("no app crash or ANR during the scenario", "E2E", not crashes, "; ".join(crashes[:3]))
    finally:
        ctx.disconnect()
        for f in ctx.followers:
            f.terminate()
    print("\n" + rec.summary())
    print(f"results: {state_dir / 'results.json'}")
    return 1 if rec.failed() else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
