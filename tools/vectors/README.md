English | [Tiếng Việt](README.vi.md)

# tools/vectors — generate and check the crypto test vectors

Run from the root of `shared/` (handlive-shared), with the venv in this repository's `tools/.venv`.

Output: `shared/test-vectors/*.json` (fields described in `shared/test-vectors/README.md`).

| Script | Purpose | Run |
|--------|---------|-----|
| `generate_vectors.py` | Regenerates every vector file from fixed values; `--check` compares byte for byte with the existing files and exits 1 on a difference | `tools/.venv/bin/python tools/vectors/generate_vectors.py [--check]` — `--check` must print `0 lệch` (0 differences) |
| `verify_vectors.py` | Checks every vector (RFC ones included) and every negative vector with libraries independent of the generator; XChaCha20 is checked two ways (libsodium, and HChaCha20 + ChaCha20-Poly1305); Argon2id with argon2-cffi (the PHC reference C code) against the generator's OpenSSL Argon2id | `tools/.venv/bin/python tools/vectors/verify_vectors.py` — must print `0 lỗi` (0 errors) |

Install (from the root of `shared/`): `python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/vectors/requirements.txt -r tools/schemas/requirements.txt`.

Modules:

| File | Role |
|------|------|
| `rfc_source_values.py` | Values copied verbatim from draft-irtf-cfrg-xchacha-03, RFC 8439, 7748, 5869 and 8032 (compared with the .txt files downloaded from rfc-editor.org / ietf.org; the three RFC 8032 §7.1 signatures are also reproduced by `cryptography` and libsodium) |
| `handlive_protocol_derivations.py` | HandLive derivations on the generator side (`cryptography` + pynacl), `test_bytes(label)`, the `HLREG1`/`HLAUTH1` messages |
| `pairing_discovery_derivations.py` | PAIR-01/PAIR-02 and discovery-hint derivations on the generator side, `cryptography` only (`T_offer`, MAC inputs, attestation, `K_pa`, `K_pin` with OpenSSL Argon2id, QR URI, `pr`, `K_disc`, hints) |
| `pair_handshake_messages.py` | The `pair/*` plaintexts and envelopes of `pair-handshake.json` |
| `hchacha20_reference.py` | HChaCha20 in pure Python (the Apple path) |
| `push_sms_truncation.py` | The SMS text cut of a push (CONN-04 step 5b) on the generator side, measured on the sealed envelope, and the inputs of the five cut vectors of `push-envelope.json` |
| `build_*_vectors.py` | Build the content of each vector file (`build_signature_vectors.py`: `ed25519.json`, `relay-auth.json`; `build_pair_handshake_vectors.py` + `build_pair_handshake_negative_vectors.py`: `pair-handshake.json`; `build_discovery_hint_vectors.py`: `discovery-hint.json`; `build_push_relay_vectors.py`: `push-envelope.json`, `relay-frame.json`) |
| `verify_common.py`, `verify_*_checks.py` | The checking side: HKDF/HMAC with `hashlib`/`hmac`, X25519/Ed25519/XChaCha with libsodium; negative signature vectors are checked for their stated reason |
| `verify_pairing_common.py`, `verify_pair_handshake_checks.py`, `verify_pair_handshake_negative_checks.py`, `verify_discovery_hint_checks.py` | The pairing and discovery checks: `T_offer`, MAC inputs and attestation rebuilt from the JSON fields of the `pair` messages, Argon2id with argon2-cffi, the receiver's checks run in the spec's order so each negative vector fails exactly at its `check` for its `reason` |
| `verify_push_relay_checks.py` | `K_push` with `hashlib`/`hmac` chained to `pair-prk.json`; push envelopes decoded as the notification service extension does and decrypted two ways; `HR` frames parsed with `struct`, their inner HL frame compared with `hl-frame.json` and decrypted; the text rewrite checked with a top-level JSON scanner that keeps the raw `env`; every negative vector fails for its stated reason |
| `verify_push_truncation_checks.py` | Every `sms/new` push run through the SMS text cut again from the texts before the cut, with `env_b64` lengths computed by arithmetic instead of sealing; the cut vectors must reach every branch, the 1,000 boundary, a non-ASCII cut and an astral cut |

To change a format or add vectors: edit `build_*`, run `generate_vectors.py`, then `verify_vectors.py`. Never edit the JSON files by hand.
