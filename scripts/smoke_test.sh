#!/usr/bin/env bash
# End-to-end smoke test against a running ThermoMind API.
#   BASE=http://localhost:8000 SMOKE_USE_META=false ./scripts/smoke_test.sh
# Exits non-zero with a clear message on the first failure.
set -uo pipefail

BASE="${BASE:-http://localhost:8000}"
SMOKE_USE_META="${SMOKE_USE_META:-false}"
DS="ds_uci_551"
YEAR="${SMOKE_YEAR:-2014}"
START="${SMOKE_START:-1200}"
END="${SMOKE_END:-1320}"
PY="${PYTHON:-python3}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "ok   - $*"; }

# req METHOD PATH OUTFILE [JSON_BODY]  -> prints status code
req() {
  local method="$1" path="$2" out="$3" body="${4:-}"
  local code
  if [ -n "$body" ]; then
    code=$(curl -sS -o "$out" -w "%{http_code}" -X "$method" -H "Content-Type: application/json" -d "$body" "$BASE$path") || fail "curl $method $path failed (is the API running at $BASE?)"
  else
    code=$(curl -sS -o "$out" -w "%{http_code}" -X "$method" "$BASE$path") || fail "curl $method $path failed (is the API running at $BASE?)"
  fi
  echo "$code"
}

# check FILE PYCODE... : python snippet gets `d` (parsed JSON); raise AssertionError to fail
check() {
  local file="$1"; shift
  "$PY" - "$file" "$@" <<'PYEOF' || exit 1
import json, math, sys
path = sys.argv[1]
code = sys.argv[2]
extra = sys.argv[3:]
with open(path, "r", encoding="utf-8") as fh:
    d = json.load(fh)
try:
    exec(code, {"d": d, "math": math, "json": json, "extra": extra})
except AssertionError as exc:
    print(f"FAIL: {exc}", file=sys.stderr)
    sys.exit(1)
PYEOF
}

echo "ThermoMind smoke test against $BASE (use_meta=$SMOKE_USE_META, window $YEAR [$START,$END))"

# 1. health ------------------------------------------------------------------
code=$(req GET /api/health "$TMP/health.json")
[ "$code" = "200" ] || fail "GET /api/health returned $code"
check "$TMP/health.json" '
status, ready = d["status"], d["data_ready"]
assert status == "ok", "health status is %s (data_ready=%s)" % (status, ready)
assert ready is True, "data not ready"
print("     health: version=%s model_ready=%s meta_configured=%s meta_model=%s" % (d["version"], d["model_ready"], d["meta_configured"], d["meta_model"]))
'
ok "health"

# 2. datasets -------------------------------------------------------------------
code=$(req GET /api/datasets "$TMP/datasets.json")
[ "$code" = "200" ] || fail "GET /api/datasets returned $code"
check "$TMP/datasets.json" '
ds = [x for x in d if x["dataset_id"] == "ds_uci_551"]
assert ds, "ds_uci_551 not in datasets list"
cols = ds[0]["columns"]
assert len(cols) == 11, f"expected 11 measurement columns, got {len(cols)}: {cols}"
assert ds[0]["has_timestamps"] is False, "UCI dataset must not claim timestamps"
print("     ds_uci_551: rows=%s years=%s" % (ds[0]["row_count"], ds[0]["years"]))
'
ok "datasets list contains ds_uci_551 with 11 measurement columns"

# 3. model evaluation ------------------------------------------------------------
code=$(req GET /api/models/evaluation "$TMP/eval.json")
[ "$code" = "200" ] || fail "GET /api/models/evaluation returned $code (train the model first: make train)"
check "$TMP/eval.json" '
mae = d["holdout"]["mae"]
assert isinstance(mae, (int, float)) and math.isfinite(mae), "holdout MAE not finite: %r" % (mae,)
print("     model %s: holdout MAE=%.3f %s R2=%.3f n=%d" % (d["model_version"], mae, d["target_unit"], d["holdout"]["r2"], d["holdout"]["n"]))
'
ok "model evaluation has finite holdout MAE"

# 4. scenario preview S02 vs raw series -----------------------------------------------
LIMIT=$((END - START))
body=$(printf '{"dataset_id":"%s","scenario_id":"S02_INTAKE_RESTRICTION","year":%s,"start_index":%s,"end_index":%s,"measurements":["AFDP","TEY","CDP"]}' "$DS" "$YEAR" "$START" "$END")
code=$(req POST /api/scenarios/preview "$TMP/preview.json" "$body")
[ "$code" = "200" ] || fail "POST /api/scenarios/preview returned $code: $(cat "$TMP/preview.json")"
code=$(req GET "/api/datasets/$DS/series?measure=AFDP&year=$YEAR&start=$START&limit=$LIMIT" "$TMP/series.json")
[ "$code" = "200" ] || fail "GET series returned $code"
check "$TMP/preview.json" '
assert d["synthetic"] is True, "S02 preview must be synthetic=true"
assert d["scenario_label"] == "synthetic_overlay"
afdp = [s for s in d["series"] if s["measure"] == "AFDP"][0]
orig = [p["value"] for p in afdp["original"]]
over = [p["value"] for p in afdp["overlay"]]
assert orig != over, "AFDP overlay equals original; synthetic transform not applied"
with open(extra[0]) as fh:
    s = json.load(fh)
raw = [p["value"] for p in s["points"]]
assert raw == orig, "preview original differs from raw series endpoint (raw rows changed?)"
assert s["provenance_kind"] == "real_observation" and s["synthetic"] is False
print("     AFDP original mean=%.3f overlay mean=%.3f (%d pts)" % (sum(orig)/len(orig), sum(over)/len(over), len(orig)))
' "$TMP/series.json"
ok "S02 preview is synthetic, AFDP overlay differs, raw series unchanged"

# 5. investigation -------------------------------------------------------------------
body=$(printf '{"dataset_id":"%s","scenario_id":"S02_INTAKE_RESTRICTION","year":%s,"start_index":%s,"end_index":%s,"seed":42,"use_meta":%s}' "$DS" "$YEAR" "$START" "$END" "$SMOKE_USE_META")
echo "     running investigation (use_meta=$SMOKE_USE_META) ..."
code=$(req POST /api/investigations "$TMP/created.json" "$body")
[ "$code" = "200" ] || fail "POST /api/investigations returned $code: $(cat "$TMP/created.json")"
CASE_ID=$("$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["case_id"])' "$TMP/created.json")
check "$TMP/created.json" '
assert d["status"] in ("completed", "needs_review"), "investigation status is %s" % d["status"]
print("     case %s: status=%s" % (d["case_id"], d["status"]))
'
code=$(req GET "/api/investigations/$CASE_ID" "$TMP/inv.json")
[ "$code" = "200" ] || fail "GET /api/investigations/$CASE_ID returned $code"
STATUS=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$TMP/inv.json")
if [ "$STATUS" = "needs_review" ]; then
  # needs_review is a legitimate outcome (report rejected by the validator): show why, skip report checks
  check "$TMP/inv.json" '
print("     needs_review: validation_errors:")
for e in d.get("validation_errors") or []:
    print("       - %s" % e)
'
  ok "investigation $CASE_ID ended needs_review (report checks skipped)"
else
check "$TMP/inv.json" '
assert d["report"] is not None, "no report (error=%s, validation_errors=%s)" % (d.get("error"), d.get("validation_errors"))
assert d["report"]["report_status"] == "draft_requires_human_review"
assert d["scenario_label"] == "synthetic_overlay"
print("     mode=%s meta_used=%s meta_model=%s evidence=%d events=%d" % (d["mode"], d["meta_used"], d["meta_model"], len(d["evidence"]), len(d["events"])))
print("     report: %r severity=%s" % (d["report"]["title"], d["report"]["severity"]))
for h in d["report"]["hypotheses"]:
    print("       #%s %s [%s] support=%s" % (h["rank"], h["name"], h["status"], h["supporting_evidence_ids"]))
'
ok "investigation $CASE_ID completed with a draft report"

# every cited evidence id resolves
cited=$("$PY" - "$TMP/inv.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
ids = set()
r = d["report"]
for o in r["observations"]:
    ids.update(o["evidence_ids"])
for h in r["hypotheses"]:
    ids.update(h["supporting_evidence_ids"]); ids.update(h["contradicting_evidence_ids"])
print("\n".join(sorted(ids)))
PYEOF
)
[ -n "$cited" ] || fail "report cites no evidence ids"
n=0
while IFS= read -r eid; do
  [ -z "$eid" ] && continue
  code=$(req GET "/api/investigations/$CASE_ID/evidence/$eid" "$TMP/ev.json")
  [ "$code" = "200" ] || fail "cited evidence id '$eid' does not resolve (HTTP $code)"
  n=$((n + 1))
done <<< "$cited"
ok "all $n cited evidence ids resolve via /evidence/{id}"
fi

# 6. review ---------------------------------------------------------------------------
code=$(req POST "/api/investigations/$CASE_ID/review" "$TMP/review.json" '{"decision":"accepted","reviewer":"smoke-test","comment":"smoke review"}')
[ "$code" = "200" ] || fail "POST review returned $code: $(cat "$TMP/review.json")"
check "$TMP/review.json" '
assert d["review"] and d["review"]["decision"] == "accepted", "review not recorded"
assert d["review"]["reviewer"] == "smoke-test"
'
ok "review recorded"

# 7. export ------------------------------------------------------------------------------
code=$(req GET "/api/investigations/$CASE_ID/export.json" "$TMP/export.json")
[ "$code" = "200" ] || fail "export.json returned $code"
check "$TMP/export.json" 'assert d["case_id"] == extra[0], "export case id mismatch"' "$CASE_ID"
ok "export.json"

echo "SMOKE PASSED (case $CASE_ID)"
