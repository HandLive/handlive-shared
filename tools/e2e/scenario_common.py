"""Steps shared by the SMS and call scenarios: granting a feature's permissions like SET-01 part B would, and
seeing the phone publish the change (SET-01 API 2 logic 4: recompute on A-UI onResume or when a new session sends
capability/hello; step 14: a change goes out as capability/update)."""
from __future__ import annotations

import time

# Fictional numbers that libphonenumber still accepts (555-01xx in area code 201, the US example number range):
# the phone normalizes recipients and callers with libphonenumber, and area code 555 is not a valid NANP number.
FAKE = {"sms_in": "+12015550101", "seed": ["+12015550150", "+12015550151", "+12015550152"],
        "contact": "+12015550123", "waiting": "+12015550124", "unknown": "+12015550125"}


def grant_and_refresh(ctx, permissions: list[str], feature: str) -> dict | None:
    """Grants what is missing (`pm grant`), then checks both recompute points; returns the latest capability."""
    rec, adb = ctx.rec, ctx.adb
    s = ctx.session or ctx.connect()
    if s is None:
        return None
    missing = [p for p in permissions if p in (s.peer_capability or {}).get("permissions_missing", [])]
    for p in permissions:
        adb.grant(p)
    if not missing:
        rec.info(f"{feature} permissions were already granted", "SET-01 part B")
        return s.peer_capability
    # A new session: its capability/hello should already carry the granted permissions.
    s = ctx.connect()
    if s is None:
        return None
    still = set(missing) & set((s.peer_capability or {}).get("permissions_missing", []))
    rec.check(f"a new session's capability/hello reflects the {feature} permissions just granted",
              "SET-01 API 2 logic 4", not still, f"still missing {sorted(still)}" if still else "")
    if not still:
        return s.peer_capability
    # HandLive's screen comes back to the foreground (onResume) → recompute → capability/update.
    mark = s.mark()
    adb.shell("input keyevent KEYCODE_HOME")
    ctx.pause()
    t0 = time.monotonic()
    adb.start_app()
    upd = s.wait(lambda m: m.type == "capability" and m.op == "update"
                 and not set(missing) & set((m.data or {}).get("permissions_missing", [])), 15, after=mark)
    rec.check(f"HandLive back on screen → capability/update without the {feature} permissions",
              "SET-01 step 14, SET-02 API 1", upd is not None, "",
              latency_ms=(time.monotonic() - t0) * 1000 if upd else None)
    if upd is not None:
        s.peer_capability = upd.data
        return upd.data
    return s.peer_capability


def features(cap: dict | None, name: str) -> dict:
    return ((cap or {}).get("features") or {}).get(name) or {}
