#!/bin/zsh
# Chay NGOAI sandbox (can mang ra ngoai): zsh handlive-shared/tools/setup-cpace-refs.sh
#
# Buoc 1: tai van ban chinh thuc (.txt) cua draft-irtf-cfrg-cpace, ban moi nhat, tu IETF datatracker,
#   luu vao tools/vectors/.refs/draft-irtf-cfrg-cpace.txt (khong commit — xem .gitignore).
# Buoc 2: voi moi file requirements*.txt duoi tools/, dung mot .venv rieng ngay canh file do
#   (tools/vectors/.venv, tools/schemas/.venv, tools/strings/.venv, tools/bench/.venv, tools/e2e/.venv,
#   tools/e2e/relay_stack/.venv...) va pip install -r vao do.
#
# In ro tung buoc thanh cong/that bai; thoat 0 chi khi CA HAI buoc deu xong.

SHARED_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DRAFT_NAME="draft-irtf-cfrg-cpace"
REFS_DIR="$SHARED_ROOT/tools/vectors/.refs"
DRAFT_OUT="$REFS_DIR/${DRAFT_NAME}.txt"

step1_ok=1
step2_ok=1

echo "== Buoc 1: tai ${DRAFT_NAME} (.txt, ban moi nhat) tu IETF datatracker =="
mkdir -p "$REFS_DIR"

REV=""
API_JSON="$(curl -fsS "https://datatracker.ietf.org/api/v1/doc/document/${DRAFT_NAME}/" 2>/dev/null)"
if [ -n "$API_JSON" ]; then
  REV="$(printf '%s' "$API_JSON" | python3 -c 'import json, sys
try:
    print(json.load(sys.stdin).get("rev", ""))
except Exception:
    pass' 2>/dev/null)"
fi

if [ -z "$REV" ]; then
  echo "  API datatracker khong tra duoc 'rev', thu doc trang tai lieu (HTML) de do phien ban moi nhat..."
  HTML="$(curl -fsS "https://datatracker.ietf.org/doc/${DRAFT_NAME}/" 2>/dev/null)"
  REV="$(printf '%s' "$HTML" | grep -o "${DRAFT_NAME}-[0-9][0-9]" | head -1 | sed 's/.*-//')"
fi

if [ -z "$REV" ]; then
  echo "  LOI buoc 1: khong xac dinh duoc phien ban moi nhat cua ${DRAFT_NAME} (API va trang HTML cua datatracker deu khong tra duoc 'rev'). Kiem lai mang ra hoac ten tai lieu."
  step1_ok=0
else
  TXT_URL="https://www.ietf.org/archive/id/${DRAFT_NAME}-${REV}.txt"
  echo "  Phien ban moi nhat: -${REV}; tai tu ${TXT_URL}"
  HTTP_CODE="$(curl -sS -w '%{http_code}' -o "${DRAFT_OUT}.tmp" "$TXT_URL")"
  CURL_EXIT=$?
  if [ "$CURL_EXIT" -ne 0 ] || [ "$HTTP_CODE" != "200" ]; then
    echo "  LOI buoc 1: tai ${TXT_URL} that bai (curl exit=${CURL_EXIT}, http=${HTTP_CODE})."
    rm -f "${DRAFT_OUT}.tmp"
    step1_ok=0
  else
    mv "${DRAFT_OUT}.tmp" "$DRAFT_OUT"
    echo "  OK: da luu ${DRAFT_OUT} ($(wc -c < "$DRAFT_OUT" | tr -d ' ') byte)."
  fi
fi

echo
echo "== Buoc 2: dung .venv rieng cho tung thu muc tools/* co requirements*.txt, pip install -r =="
REQ_FILES="$(find "$SHARED_ROOT/tools" -iname 'requirements*.txt' | sort)"
if [ -z "$REQ_FILES" ]; then
  echo "  LOI buoc 2: khong thay file requirements*.txt nao duoi $SHARED_ROOT/tools"
  step2_ok=0
else
  while IFS= read -r REQ; do
    [ -z "$REQ" ] && continue
    DIR="$(dirname "$REQ")"
    VENV="$DIR/.venv"
    REL="${DIR#"$SHARED_ROOT"/}"
    echo "  -- $REL ($(basename "$REQ")) --"
    if [ ! -x "$VENV/bin/python3" ]; then
      echo "     tao venv moi: $VENV/"
      if ! python3 -m venv "$VENV"; then
        echo "     LOI: 'python3 -m venv' that bai cho $VENV"
        step2_ok=0
        continue
      fi
    else
      echo "     venv da co san, dung lai: $VENV/"
    fi
    echo "     pip install -r $REQ"
    if ! "$VENV/bin/pip" install --quiet --upgrade-strategy only-if-needed -r "$REQ"; then
      echo "     LOI: pip install that bai cho $REQ"
      step2_ok=0
      continue
    fi
    echo "     OK"
  done <<< "$REQ_FILES"
fi

step3_ok=1

echo
echo "== Buoc 3: chay thử verify_vectors.py, check_schemas.py, check_strings.py bang .venv vua dung =="
VERIFY_SCRIPT="$SHARED_ROOT/tools/vectors/verify_vectors.py"
CHECK_SCHEMAS="$SHARED_ROOT/tools/schemas/check_schemas.py"
CHECK_STRINGS="$SHARED_ROOT/tools/strings/check_strings.py"

if [ -f "$VERIFY_SCRIPT" ] && [ -x "$SHARED_ROOT/tools/vectors/.venv/bin/python3" ]; then
  echo "  Chay verify_vectors.py..."
  if "$SHARED_ROOT/tools/vectors/.venv/bin/python3" "$VERIFY_SCRIPT"; then
    echo "  OK: verify_vectors.py xong."
  else
    echo "  LOI: verify_vectors.py loi."
    step3_ok=0
  fi
else
  echo "  SKIP: verify_vectors.py khong tim thay hoac venv khong san sang."
  step3_ok=0
fi

if [ -f "$CHECK_SCHEMAS" ] && [ -x "$SHARED_ROOT/tools/schemas/.venv/bin/python3" ]; then
  echo "  Chay check_schemas.py..."
  if "$SHARED_ROOT/tools/schemas/.venv/bin/python3" "$CHECK_SCHEMAS"; then
    echo "  OK: check_schemas.py xong."
  else
    echo "  LOI: check_schemas.py loi."
    step3_ok=0
  fi
else
  echo "  SKIP: check_schemas.py khong tim thay hoac venv khong san sang."
  step3_ok=0
fi

if [ -f "$CHECK_STRINGS" ] && [ -x "$SHARED_ROOT/tools/strings/.venv/bin/python3" ]; then
  echo "  Chay check_strings.py..."
  if "$SHARED_ROOT/tools/strings/.venv/bin/python3" "$CHECK_STRINGS"; then
    echo "  OK: check_strings.py xong."
  else
    echo "  LOI: check_strings.py loi."
    step3_ok=0
  fi
else
  echo "  SKIP: check_strings.py khong tim thay hoac venv khong san sang."
  step3_ok=0
fi

echo
if [ "$step1_ok" -eq 1 ] && [ "$step2_ok" -eq 1 ] && [ "$step3_ok" -eq 1 ]; then
  echo "XONG: ca 3 buoc thanh cong."
  exit 0
fi
if [ "$step1_ok" -eq 0 ]; then
  echo "LOI: buoc 1 (tai draft) that bai."
fi
if [ "$step2_ok" -eq 0 ]; then
  echo "LOI: buoc 2 (venv + pip install) that bai."
fi
if [ "$step3_ok" -eq 0 ]; then
  echo "LOI: buoc 3 (thuc hien verify/check) that bai hoac khong tim thay script."
fi
exit 1
