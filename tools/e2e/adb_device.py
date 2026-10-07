"""adb and emulator-console helpers for one emulator (always addressed with -s <serial>, bounded by timeouts).

Covers what the scenarios drive on the phone: install and permissions, port forwarding to the phone's WSS server,
logcat, the SMS and contacts providers (fake numbers only), and the emulator's modem (`adb emu gsm …`, `sms send`).
"""
from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

SDK_DEFAULT = "/opt/homebrew/share/android-commandlinetools"
PACKAGE = "app.handlive.android"


def lines_since(text: str, since: float) -> list[str]:
    """The lines of `logcat -v epoch` output stamped at `since` or later; banners and unstamped lines are dropped."""
    out = []
    for line in text.splitlines():
        stamp = line.split(maxsplit=1)[0] if line.strip() else ""
        try:
            if float(stamp) >= since:
                out.append(line)
        except ValueError:
            continue
    return out


class AdbError(RuntimeError):
    pass


@dataclass
class GsmCall:
    direction: str   # inbound | outbound
    number: str
    state: str       # active | held | ringing | dialing | alerting | waiting | incoming


class Adb:
    def __init__(self, serial: str, sdk: str | None = None) -> None:
        self.serial = serial
        sdk = sdk or os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or SDK_DEFAULT
        self.adb = str(Path(sdk) / "platform-tools" / "adb")

    def run(self, *args: str, timeout: float = 60, check: bool = True, binary: bool = False):
        cmd = [self.adb, "-s", self.serial, *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"timeout after {timeout}s: adb {' '.join(args)[:120]}") from exc
        out = proc.stdout if binary else proc.stdout.decode(errors="replace")
        if check and proc.returncode != 0:
            raise AdbError(f"adb {' '.join(args)[:120]} → {proc.returncode}: {proc.stderr.decode(errors='replace')[:300]}")
        return out

    def shell(self, command: str, timeout: float = 60, check: bool = True) -> str:
        return self.run("shell", command, timeout=timeout, check=check)

    def emu(self, command: str, timeout: float = 20) -> str:
        """An emulator console command (gsm, sms, …); the console answers OK or KO."""
        out = self.run("emu", *shlex.split(command), timeout=timeout, check=False)
        if "KO" in out.split():
            raise AdbError(f"emu {command}: {out.strip()}")
        return out

    # ----- device state ----------------------------------------------------------------------------------------
    def wait_boot(self, timeout: float = 300) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.shell("getprop sys.boot_completed", timeout=15, check=False).strip() == "1":
                    return
            except AdbError:
                pass
            time.sleep(3)
        raise AdbError(f"{self.serial} did not finish booting within {timeout}s")

    def sdk_int(self) -> int:
        return int(self.shell("getprop ro.build.version.sdk").strip())

    def keep_awake(self) -> None:
        """Screen on and unlocked for the whole run, so the UI can be driven and watched."""
        self.shell("svc power stayon true", check=False)
        self.shell("input keyevent KEYCODE_WAKEUP", check=False)
        self.shell("wm dismiss-keyguard", check=False)

    def installed(self, package: str = PACKAGE) -> bool:
        return f"package:{package}" in self.shell(f"pm list packages {package}", check=False).split()

    def install(self, apk: Path, timeout: float = 240) -> None:
        self.run("install", "-r", "-t", str(apk), timeout=timeout)

    def push(self, local: Path, remote: str) -> None:
        self.run("push", str(local), remote, timeout=120)

    def uninstall(self, package: str = PACKAGE) -> None:
        self.run("uninstall", package, timeout=120, check=False)

    def grant(self, permission: str, package: str = PACKAGE) -> None:
        self.shell(f"pm grant {package} android.permission.{permission}")

    def revoke(self, permission: str, package: str = PACKAGE) -> None:
        self.shell(f"pm revoke {package} android.permission.{permission}", check=False)

    def granted(self, permission: str, package: str = PACKAGE) -> bool:
        dump = self.shell(f"dumpsys package {package}", timeout=30)
        return re.search(rf"android\.permission\.{permission}: granted=true", dump) is not None

    def start_app(self, package: str = PACKAGE) -> None:
        self.shell(f"am start -W -n {package}/.MainActivity", timeout=60)

    def force_stop(self, package: str = PACKAGE) -> None:
        self.shell(f"am force-stop {package}", check=False)

    def pid(self, package: str = PACKAGE) -> str:
        return self.shell(f"pidof {package}", check=False).strip()

    def foreground_service(self, service: str = "HandLiveService", package: str = PACKAGE) -> str:
        """The foreground service type of the app's service ("connectedDevice"), "" when not in the foreground."""
        dump = self.shell(f"dumpsys activity services {package}", timeout=30, check=False)
        record = dump.split(f"{package}/", 1)[-1] if service in dump else ""
        record = record.split("* ServiceRecord", 1)[0]
        if "isForeground=true" not in record:
            return ""
        m = re.search(r"types=0x([0-9a-fA-F]+)", record) or re.search(r"foregroundServiceType=0x([0-9a-fA-F]+)",
                                                                       record)
        if not m:
            return "foreground"             # API 29 prints no type
        return "connectedDevice" if int(m.group(1), 16) & 0x10 else f"0x{m.group(1)}"

    def notification_texts(self, package: str = PACKAGE) -> list[str]:
        """`android.text` of the app's posted notifications (the service notification among them)."""
        dump = self.shell("dumpsys notification --noredact", timeout=30, check=False)
        texts, current = [], ""
        for line in dump.splitlines():
            m = re.search(r"NotificationRecord\(.*pkg=(\S+)", line)
            if m:
                current = m.group(1)
            t = re.search(r"android\.text=\S+ \((.*)\)\s*$", line)
            if t and current == package:
                texts.append(t.group(1))
        return texts

    def battery_exempt(self, package: str = PACKAGE) -> bool:
        return package in self.shell("dumpsys deviceidle whitelist", check=False)

    # ----- network ---------------------------------------------------------------------------------------------
    def forward(self, host_port: int, device_port: int = 47800) -> None:
        self.run("forward", f"tcp:{host_port}", f"tcp:{device_port}", timeout=20)

    def forward_remove(self, host_port: int) -> None:
        self.run("forward", "--remove", f"tcp:{host_port}", timeout=20, check=False)

    def listening(self, port: int = 47800) -> bool:
        out = self.shell("cat /proc/net/tcp6 /proc/net/tcp", check=False)
        hexport = f":{port:04X}"
        return any(hexport in line.split()[1] and line.split()[3] == "0A" for line in out.splitlines()[1:]
                   if len(line.split()) > 3)

    # ----- logcat ----------------------------------------------------------------------------------------------
    def logcat_clear(self) -> None:
        """Clears the log buffers: every buffer, else the default ones (some API levels refuse `-b all`). Raises
        AdbError when the device refuses both, so a caller never reads an old line as a new one unknowingly."""
        errors = []
        for args in (("-b", "all", "-c"), ("-c",)):
            try:
                self.run("logcat", *args, timeout=20)
                return
            except AdbError as exc:
                errors.append(str(exc))
        raise AdbError("logcat could not be cleared: " + " | ".join(errors))

    def device_epoch(self) -> int:
        """The device clock in whole seconds since the epoch, the start of a window for logcat_since()."""
        return int(self.shell("date +%s", timeout=20).strip())

    def logcat_since(self, since: float, *filters: str) -> list[str]:
        """The log lines (`-v epoch`) written at `since` or later: a window that needs no cleared buffer."""
        return lines_since(self.run("logcat", "-d", "-v", "epoch", *filters, timeout=30), since)

    def logcat_follow(self, path: Path, *filters: str) -> subprocess.Popen:
        f = path.open("ab")
        return subprocess.Popen([self.adb, "-s", self.serial, "logcat", "-v", "epoch", *filters], stdout=f,
                                stderr=subprocess.DEVNULL)

    def device_time(self) -> str:
        """The device clock in logcat's -T format, to read only what happened after this moment."""
        return self.shell("date +'%m-%d %H:%M:%S.000'", timeout=20).strip()

    def crashes(self, since: str | None = None, package: str = PACKAGE) -> list[str]:
        """FATAL EXCEPTION / ANR lines of the app (crash and main buffers), since `since` when given; buffers are
        never cleared here, so other users of a shared emulator keep their logs."""
        window = ["-T", since] if since else []
        out = self.run("logcat", "-d", "-b", "crash", *window, timeout=30, check=False)
        lines = [ln for ln in out.splitlines() if package in ln or "FATAL" in ln]
        anr = self.run("logcat", "-d", "-s", "ActivityManager", *window, timeout=30, check=False)
        return lines + [ln for ln in anr.splitlines() if "ANR in" in ln and package in ln]

    # ----- telephony (emulator modem) --------------------------------------------------------------------------
    def own_number(self) -> str | None:
        """The SIM's line 1 number (the emulator loops SMS sent to it back as incoming)."""
        for code in range(10, 25):
            out = self.shell(f"service call iphonesubinfo {code}", check=False)
            chars = "".join(re.findall(r"'([^']*)'", out)).replace(".", "").strip()
            if re.fullmatch(r"\+?1?555\d{7}", chars):
                return chars if chars.startswith("+") else "+" + chars
        return None

    def console_port(self) -> str | None:
        """The emulator's console port: an SMS sent to it as a short code comes back to this emulator."""
        m = re.search(r"emulator-(\d+)", self.serial)
        return m.group(1) if m else None

    def gsm_call(self, number: str) -> None:
        self.emu(f"gsm call {number}")

    def gsm_accept(self, number: str) -> None:
        self.emu(f"gsm accept {number}")

    def gsm_cancel(self, number: str) -> None:
        self.emu(f"gsm cancel {number}")

    def console(self, command: str, timeout: float = 10) -> str:
        """A command on the emulator console over TCP (localhost:<port>, token auth), with its output lines —
        `adb emu` relays only the final OK/KO, so listings such as `gsm list` need the console itself."""
        token = (Path.home() / ".emulator_console_auth_token").read_text().strip()
        with socket.create_connection(("127.0.0.1", int(self.console_port())), timeout=timeout) as sock:
            f = sock.makefile("rwb")

            def until_ok() -> str:
                lines = []
                while True:
                    line = f.readline().decode(errors="replace")
                    if not line:
                        raise AdbError(f"console closed during {command!r}")
                    if line.startswith("OK"):
                        return "".join(lines)
                    if line.startswith("KO"):
                        raise AdbError(f"console {command!r}: {line.strip()}")
                    lines.append(line)
            until_ok()
            for cmd in (f"auth {token}", command):
                f.write((cmd + "\n").encode())
                f.flush()
                out = until_ok()
            f.write(b"quit\n")
            f.flush()
            return out

    def gsm_list(self) -> list[GsmCall]:
        calls = []
        for line in self.console("gsm list").splitlines():
            m = re.match(r"\s*(inbound|outbound)\s+(?:from|to)\s+(\S+)\s*:\s*(\w+)", line)
            if m:
                calls.append(GsmCall(m.group(1), m.group(2), m.group(3)))
        return calls

    def call_state(self) -> dict[str, int]:
        """The framework's view of the calls (dumpsys telephony.registry, first phone): mCallState 0 idle,
        1 ringing, 2 offhook; m*CallState use PreciseCallState (1 active, 2 holding, 5 incoming, 6 waiting)."""
        out = self.shell("dumpsys telephony.registry", timeout=30, check=False)
        state: dict[str, int] = {}
        for key in ("mCallState", "mRingingCallState", "mForegroundCallState", "mBackgroundCallState"):
            m = re.search(rf"{key}=(-?\d+)", out)
            if m:
                state[key] = int(m.group(1))
        return state

    def sms_to_phone(self, number: str, text: str) -> None:
        self.emu(f"sms send {number} {text}")

    # ----- providers (fake data only) --------------------------------------------------------------------------
    def allow_sms_writes(self) -> None:
        """The shell may seed and mark SMS rows (it is not the default SMS app, so WRITE_SMS is `ignore`)."""
        self.shell("appops set com.android.shell WRITE_SMS allow")

    def content(self, verb: str, uri: str, *binds: str, where: str | None = None, timeout: float = 60) -> str:
        cmd = f"content {verb} --uri {uri}"
        cmd += "".join(f" --bind {shlex.quote(b)}" for b in binds)
        if where:
            cmd += f" --where {shlex.quote(where)}"
        return self.shell(cmd, timeout=timeout)

    def query(self, uri: str, projection: str, where: str | None = None) -> list[dict]:
        cmd = f"content query --uri {uri} --projection {projection}"
        if where:
            cmd += f" --where {shlex.quote(where)}"
        rows = []
        for line in self.shell(cmd, timeout=60).splitlines():
            if line.startswith("Row: "):
                row = {}
                for part in re.split(r", (?=\w+=)", line.split(" ", 2)[2]):
                    k, _, v = part.partition("=")
                    row[k] = v
                rows.append(row)
        return rows

    def insert_contact(self, name: str, number: str) -> str:
        """A fake local contact (no account) with one mobile number; returns its raw_contact _id."""
        before = {r["_id"] for r in self.query("content://com.android.contacts/raw_contacts", "_id")}
        self.content("insert", "content://com.android.contacts/raw_contacts", "account_type:n:", "account_name:n:")
        after = {r["_id"] for r in self.query("content://com.android.contacts/raw_contacts", "_id")}
        new = sorted(after - before, key=int)
        if not new:
            raise AdbError("contact not inserted")
        raw = new[-1]
        data = "content://com.android.contacts/data"
        self.content("insert", data, f"raw_contact_id:i:{raw}", "mimetype:s:vnd.android.cursor.item/name",
                     f"data1:s:{name}")
        self.content("insert", data, f"raw_contact_id:i:{raw}", "mimetype:s:vnd.android.cursor.item/phone_v2",
                     f"data1:s:{number}", "data2:i:2")
        return raw

    def delete_contacts_named(self, name: str) -> None:
        for row in self.query("content://com.android.contacts/raw_contacts", "_id:display_name"):
            if row.get("display_name") == name:
                self.content("delete", "content://com.android.contacts/raw_contacts",
                             where=f"_id={row['_id']}")
