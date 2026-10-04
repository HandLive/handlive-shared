"""Self-test of the E2E harness without an emulator (CI): the fake Mac's crypto against shared/test-vectors, then the
whole client (PIN pairing, pinned TLS, session handshake, capability, requests, events, schemas) against the
in-process fake phone, the UI dump parser and the HLBENCH lines. Prints "0 failed" when green.
"""
from __future__ import annotations

import json
import sys
import tempfile
import hashlib
import os
import threading
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "bench"))
sys.path.insert(0, str(HERE / "relay_stack"))

import bench_log  # noqa: E402
import mac_crypto as C  # noqa: E402
from fake_mac import FakeClient, capability  # noqa: E402
from fake_phone import PHONE_CAPABILITY, FakePhone  # noqa: E402
from schema_check import SchemaCheck  # noqa: E402
from ui_automator import en, parse_dump  # noqa: E402

VECTORS = HERE.parents[1] / "test-vectors"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def load(name: str) -> dict:
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


def vectors_pin_pairing() -> None:
    v = next(x for x in load("pair-handshake.json")["vectors"] if x["mode"] == "pin")
    ident = C.Identity(bytes.fromhex(v["client_ik_sig_seed"]), bytes.fromhex(v["client_ik_dh_priv"]))
    check("device_id of the client identity", ident.device_id == v["client_device_id"])
    offer = json.loads(v["offer_plaintext"])["data"]
    res = C.check_pin_offer(v["pin"], ident, v["client_name"], bytes.fromhex(v["nonce_c"]), offer,
                            bytes.fromhex(v["tls_sha256"]))
    check("PIN offer accepted (K_pin, K_pa, T_offer mac)", res.ok and res.k_pin.hex() == v["k_pin"], res.reason)
    wrong = C.check_pin_offer("000000" if v["pin"] != "000000" else "111111", ident, v["client_name"],
                              bytes.fromhex(v["nonce_c"]), offer, bytes.fromhex(v["tls_sha256"]))
    check("a wrong PIN fails on the mac", not wrong.ok and wrong.reason == "mac")
    tls_other = C.check_pin_offer(v["pin"], ident, v["client_name"], bytes.fromhex(v["nonce_c"]), offer, b"\x00" * 32)
    check("another TLS certificate fails on tls_sha256", not tls_other.ok and tls_other.reason == "tls_sha256")
    s = C.build_confirm(ident, offer, res, v["pair_id"], v["created_at"])
    check("pair/confirm equals the vector", s.confirm == json.loads(v["confirm_plaintext"])["data"])
    check("PRK equals the vector", s.prk.hex() == v["prk"])
    done = json.loads(v["done_plaintext"])["data"]
    check("pair/done verifies", C.check_done(done, offer, res, s) == "")
    check("Security Code equals the vector", C.security_code(s.attestation) == v["security_code"])


def vectors_session() -> None:
    for v in load("session-handshake.json")["vectors"]:
        prk = bytes.fromhex(v["prk"])
        hello = C.session_hello(prk, v["pair_id"], v["client_device_id"], bytes.fromhex(v["client_eph_priv"]),
                                bytes.fromhex(v["client_nonce"]))
        check(f"session/hello data ({v['name']})", hello.data == json.loads(v["hello_plaintext"])["data"])
        keys = C.session_keys(prk, hello, json.loads(v["welcome_plaintext"])["data"], v["server_device_id"])
        check(f"k_c2s, k_s2c ({v['name']})", keys == (bytes.fromhex(v["k_c2s"]), bytes.fromhex(v["k_s2c"])))
        bad = dict(json.loads(v["welcome_plaintext"])["data"], device_id=v["client_device_id"])
        check(f"welcome from another device_id refused ({v['name']})",
              C.session_keys(prk, hello, bad, v["server_device_id"]) is None)


def vectors_envelopes() -> None:
    for v in load("envelope.json")["vectors"]:
        if not v["encrypted"]:
            continue
        env = json.loads(v["envelope"])
        check(f"open {v['name']}", C.open_sealed(bytes.fromhex(v["key"]), env).decode() == v["plaintext"])
        again = C.seal(bytes.fromhex(v["key"]), v["type"], v["plaintext"].encode(), v["id"], v["ts"],
                       bytes.fromhex(v["nonce"]))
        check(f"seal {v['name']}", again == env)
    for v in load("envelope.json")["invalid_vectors"]:
        try:
            C.open_sealed(bytes.fromhex(v["key"]), json.loads(v["envelope"]))
            check(f"reject {v['name']}", False)
        except (ValueError, KeyError):
            check(f"reject {v['name']}", True)
    for v in load("clipboard-chunk.json")["vectors"]:
        pt = C.chunk_plaintext(v["transfer_id"], v["index"], bytes.fromhex(v["chunk_data"]))
        check(f"chunk plaintext {v['name']}", pt.hex() == v["plaintext_hex"])
        hdr, data = C.parse_plaintext(pt)
        check(f"chunk parse {v['name']}", hdr["data"]["index"] == v["index"] and data.hex() == v["chunk_data"])
    for v in load("push-envelope.json")["vectors"]:
        if "k_push" in v and "prk" in v:
            check(f"K_push {v['name']}", C.push_key(bytes.fromhex(v["prk"])).hex() == v["k_push"])


def loopback(checker: SchemaCheck) -> None:
    """The fake Mac against the fake phone over real TLS and WebSocket: pairing, session, requests, events."""
    pin = C.new_pin()
    phone = FakePhone(pin)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(Path(tmp) / "pair.json", "E2E Test Mac", port=phone.port, checker=checker,
                                bench_file=Path(tmp) / "bench.log")
            pairing = client.pin_pairing()
            wrong = pairing.attempt("000000" if pin != "000000" else "111111", attempts_left_if_wrong=2)
            check("wrong PIN → pin_mismatch", wrong.outcome == "pin_mismatch", f"{wrong.outcome} {wrong.code}")
            ok = pairing.attempt(pin, attempts_left_if_wrong=1)
            check("right PIN → paired", ok.outcome == "paired", f"{ok.outcome} {ok.code}")
            check("pairing messages match the schemas", not (wrong.violations + ok.violations),
                  "; ".join(wrong.violations + ok.violations))
            pair = phone.pairs.get(client.record.pair_id, {})
            check("same Security Code on both sides", pair.get("security_code") == ok.security_code)
            check("TLS certificate pinned", client.record.peer_tls_sha256 == phone.tls_sha256.hex())
            client.save()
            s = client.session()
            s.open()
            check("capability/hello of the phone received", s.peer_capability == PHONE_CAPABILITY)
            ack = s.request("clipboard", "push", {"clip_id": C.uuid7(), "kind": "text", "mime": "text/plain",
                                                  "text": "self test", "sensitive": False, "origin_ts": C.now_ms(),
                                                  "source": "mac", "origin_device_id": client.record.device_id})
            check("clipboard/push acked applied", ack is not None and ack.ok and ack.data["status"] == "applied")
            # Phone → Mac (CLIP-01 API 5 receiver side, CLIP-03 API 3–4): the fake Mac writes, records and acks.
            mark = s.mark()
            clip = C.uuid7()
            env_id = phone.emit("clipboard", "push", {"clip_id": clip, "kind": "text", "mime": "text/plain",
                                                      "text": "from the phone", "sensitive": False,
                                                      "origin_ts": C.now_ms(), "source": "manual",
                                                      "origin_device_id": phone.identity.device_id})
            got = s.wait(lambda m: m.type == "clipboard" and m.op == "push" and m.data["clip_id"] == clip, 5, after=mark)
            check("phone → Mac text push: recorded applied before the waiter wakes",
                  got is not None and clip in s.applied_clips)
            ack = phone.ack_for(env_id, 5)
            check("phone → Mac text push: ack applied reached the phone",
                  ack is not None and ack.get("ok") and ack["data"]["status"] == "applied")
            blob = os.urandom(70_000)
            def image_push(clip_id: str, transfer_id: str) -> dict:
                return {"clip_id": clip_id, "kind": "image", "mime": "image/png",
                        "transfer": {"transfer_id": transfer_id, "size": len(blob),
                                     "sha256": C.b64u(hashlib.sha256(blob).digest()), "chunk_size": 65_536,
                                     "chunk_count": 2},
                        "width": 10, "height": 10, "sensitive": False, "origin_ts": C.now_ms(), "source": "manual",
                        "origin_device_id": phone.identity.device_id}
            clip2, tid2 = C.uuid7(), C.uuid7()
            env_id = phone.emit("clipboard", "push", image_push(clip2, tid2))
            phone.emit_chunk(tid2, 0, blob[:65_536])
            phone.emit_chunk(tid2, 1, blob[65_536:])
            ack = phone.ack_for(env_id, 5)
            rec = s.received_transfers.get(clip2) or {}
            check("phone → Mac 2-chunk image: SHA-256 verified, in order, ack applied",
                  ack is not None and ack.get("ok") and rec.get("status") == "applied" and rec.get("chunks") == 2
                  and rec.get("in_order") is True and rec.get("sha256") == C.b64u(hashlib.sha256(blob).digest()))
            clip3, tid3 = C.uuid7(), C.uuid7()
            env_id = phone.emit("clipboard", "push", image_push(clip3, tid3))
            phone.emit_chunk(tid3, 0, blob[:65_536])
            phone.emit_chunk(tid3, 1, bytes(len(blob) - 65_536))
            ack = phone.ack_for(env_id, 5)
            err = (ack or {}).get("error") or {}
            check("phone → Mac corrupted chunks: CLIP_CHECKSUM_MISMATCH with details.transfer_id",
                  ack is not None and not ack.get("ok") and err.get("code") == "CLIP_CHECKSUM_MISMATCH"
                  and (err.get("details") or {}).get("transfer_id") == tid3)
            ack = s.request("sms", "sync", {"thread_limit": 200, "per_thread_limit": 50})
            check("sms/sync acked with data", ack is not None and ack.ok and ack.data["has_more"] is False)
            mark = s.mark()
            state = {"call_id": C.uuid7(), "direction": "incoming", "state": "ringing", "waiting": False,
                     "number": "+15555550123", "display_name": "E2E Test Contact", "presentation": "allowed",
                     "sub_id": None, "sim_label": None, "waiting_number": None, "waiting_display_name": None,
                     "started_at": C.now_ms(), "answered_at": None, "ended_at": None, "end_reason": None,
                     "controls": {"answer": True, "reject": True, "end": False, "hold": "unavailable",
                                  "dtmf": "unavailable", "mute": "unavailable"},
                     "hfp_connected": False, "audio_on": "phone"}
            threading.Timer(0.2, phone.emit, ("call_event", "state", state)).start()
            got = s.wait(lambda m: m.type == "call_event" and m.op == "state", 5, after=mark)
            check("call_event/state event received", got is not None and got.data["call_id"] == state["call_id"])
            ack = s.request("call_event", "action", {"call_id": state["call_id"], "action": "answer", "audio": "phone"})
            check("call_event/action acked", ack is not None and ack.ok and ack.data == {})
            check("no schema violation in the session", not s.violations, "; ".join(s.violations))
            s.close()
            lines = (Path(tmp) / "bench.log").read_text().splitlines()
            problems = []
            for line in lines:
                try:
                    bench_log.parse_line(line)
                except ValueError as exc:
                    problems.append(f"{exc}: {line[:80]}")
            check("HLBENCH lines parse", bool(lines) and not problems, "; ".join(problems[:2]))
    finally:
        phone.close()


def relay_loopback(checker: SchemaCheck) -> None:
    """The same client through a relay: the fake relay of tools/bench (REST + /v1/relay, 0.4.3 wrappers)."""
    import asyncio
    from relay_client import RelayAccount, RelayLink, RelayStack
    from relay_load_fake import FakeRelay
    from stack_rest import FakeDevice
    loop = asyncio.new_event_loop()
    relay = FakeRelay()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    asyncio.run_coroutine_threadsafe(relay.start(), loop).result(10)
    stack = RelayStack(f"http://127.0.0.1:{relay.rest_port}", f"ws://127.0.0.1:{relay.ws_port}/v1/relay", None,
                       Path("/nonexistent"), Path("/nonexistent"), "app.handlive.ios")
    pin = C.new_pin()
    phone = FakePhone(pin)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(Path(tmp) / "pair.json", "E2E Test Mac", port=phone.port, checker=checker)
            mac = RelayAccount(stack, client.record, checker)
            check("the Mac registers with the relay (HLREG1, HLAUTH1)", mac.register()[0] == 200 and bool(mac.token))
            phone_dev = FakeDevice("android", phone.identity.sig_seed)
            check("the phone registers with the relay", phone_dev.register(stack.rest(), "10.0.0.2")[0] == 200)
            check("PIN pairing on the LAN", client.pin_pairing().attempt(pin, 2).outcome == "paired")
            status, _ = mac.register_pair()
            check("POST /v1/pairs with both signatures", status in (200, 201), str(status))
            phone_link = RelayLink(stack, phone_dev.token, checker)
            mac_link = RelayLink(stack, mac.token, checker)
            presence = mac_link.wait_control(lambda m: m.get("op") == "presence" and m.get("online") is True, 5)
            check("presence of the phone on /v1/relay", presence is not None)
            phone.serve_relayed(phone_link.channel(client.record.device_id))
            s = client.session(open_transport=lambda: mac_link.channel(client.record.peer_device_id))
            s.open()
            check("session handshake and capabilities through the relay", s.peer_capability == PHONE_CAPABILITY)
            ack = s.request("sms", "sync", {"thread_limit": 200, "per_thread_limit": 50})
            check("a request and its ack through the relay", ack is not None and ack.ok)
            mark = s.mark()
            threading.Timer(0.2, phone.emit, ("sms", "read_changed", {"thread_id": 1, "unread_count": 0,
                                                                      "read_up_to_ts": C.now_ms()})).start()
            got = s.wait(lambda m: m.type == "sms" and m.op == "read_changed", 5, after=mark)
            check("an event from the phone through the relay", got is not None)
            check("no schema violation in the relayed session and wrappers",
                  not s.violations and not mac_link.violations and not phone_link.violations,
                  "; ".join(s.violations + mac_link.violations + phone_link.violations))
            s.close()
            mac_link.close()
            phone_link.close()
    finally:
        phone.close()
        asyncio.run_coroutine_threadsafe(relay.stop(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)


def ui_parser() -> None:
    xml = ('<?xml version="1.0"?><hierarchy rotation="0"><node index="0" text="" resource-id="" class="android.view.View" '
           'package="app.handlive.android" content-desc="" clickable="false" bounds="[0,0][1080,2400]">'
           f'<node index="1" text="{en("pairing.enter_pin")}" resource-id="" class="android.widget.TextView" '
           'package="app.handlive.android" content-desc="" clickable="false" bounds="[100,200][500,300]"/></node>'
           '</hierarchy>UI hierchary dumped to: /dev/tty')
    nodes = parse_dump(xml)
    hit = [n for n in nodes if n.text == "Enter PIN"]
    check("uiautomator dump parsed", len(nodes) == 2 and hit and hit[0].center == (300, 250))
    check("plural catalog string", en("pairing.pin_attempts_left", count=2) == "2 attempts left")


def main() -> int:
    checker = SchemaCheck()
    check("capability of the fake Mac matches the schema", not checker.check_payload(
        "capability", "hello", {"op": "hello", "data": capability("macos")}))
    check("capability of a fake iPhone matches the schema", not checker.check_payload(
        "capability", "hello", {"op": "hello", "data": capability("ios")}))
    vectors_pin_pairing()
    vectors_session()
    vectors_envelopes()
    loopback(checker)
    relay_loopback(checker)
    ui_parser()
    print(f"{len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
