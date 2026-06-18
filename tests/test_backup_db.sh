#!/usr/bin/env bash
#
# Regression tests for scripts/backup_db.sh.
#
# These guard the data-safety contract that was violated by the 23-day silent
# backup outage discovered 2026-06-18: when the Postgres container is down,
# pg_dump exits non-zero but leaves a 0-byte .dump behind, and the verification
# step treated an empty custom-format dump as valid. The hardened script must
# NEVER publish a 0-byte/unrestorable dump, and --status must report the newest
# *good* (non-empty, restorable) dump and warn when it is stale.
#
# Pure stdlib bash + coreutils — no bats/shellcheck dependency. The DB tools are
# faked via the PG_DUMP / PG_RESTORE / PG_ISREADY env seams the script honours,
# and the backup directory is redirected with ESBVAKTIN_BACKUP_DIR so the real
# ~/Documents/esbvaktin-backups is never touched.
#
# Run:  bash tests/test_backup_db.sh
# Exit: 0 if all assertions pass, 1 otherwise.

set -u  # NOT -e: we want every assertion to run and tally, not abort on first.

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$(cd "$HERE/.." && pwd)/scripts/backup_db.sh"
# Run the script under the same interpreter launchd uses (system bash 3.2) so
# any bash-4-only syntax is caught here rather than in production.
BASH_BIN="/bin/bash"

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/backup_db_test.XXXXXX")"
BIN="$SANDBOX/bin"
mkdir -p "$BIN"
trap 'rm -rf "$SANDBOX"' EXIT

PASS=0
FAIL=0
ok()  { printf '    ok   %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL   %s\n' "$1"; FAIL=$((FAIL + 1)); }

# ---- Fake binaries (behaviour driven by FAKE_* env vars at call time) --------

cat > "$BIN/pg_dump" <<'EOF'
#!/usr/bin/env bash
# Honour `-f <outfile>`: create it with FAKE_PGDUMP_CONTENT (possibly empty),
# mimicking how real pg_dump opens/creates the output file before it connects.
out=""; prev=""
for a in "$@"; do
  [ "$prev" = "-f" ] && out="$a"
  prev="$a"
done
[ -n "$out" ] && printf '%s' "${FAKE_PGDUMP_CONTENT:-}" > "$out"
[ -n "${FAKE_PGDUMP_MARKER:-}" ] && echo called >> "$FAKE_PGDUMP_MARKER"
exit "${FAKE_PGDUMP_EXIT:-0}"
EOF

cat > "$BIN/pg_restore" <<'EOF'
#!/usr/bin/env bash
# Mimic `pg_restore --list <file>`. Default: exit 0 and print a TOC entry.
# FAKE_PGRESTORE_EXIT=1      -> archive unreadable / corrupt.
# FAKE_PGRESTORE_EMPTY_TOC=1 -> exit 0 but print NO entries, reproducing the
#                               real hazard where an empty custom-format dump
#                               is "valid" yet contains no data.
if [ "${FAKE_PGRESTORE_EXIT:-0}" = "0" ]; then
  if [ "${FAKE_PGRESTORE_EMPTY_TOC:-0}" = "1" ]; then
    echo ";"
    echo "; (no data)"
  else
    echo ";"
    echo "; Selected TOC Entries:"
    echo "215; 1259 16456 TABLE public claims esb"
  fi
fi
exit "${FAKE_PGRESTORE_EXIT:-0}"
EOF

cat > "$BIN/pg_isready" <<'EOF'
#!/usr/bin/env bash
exit "${FAKE_PGISREADY_EXIT:-0}"
EOF

chmod +x "$BIN/pg_dump" "$BIN/pg_restore" "$BIN/pg_isready"

# ---- Invocation + assertion helpers -----------------------------------------

OUT=""; RC=0
# invoke <backup-dir> <backup|status> [EXTRA_ENV=VAL ...]
# Note: no array expansion — an empty "${arr[@]}" trips `set -u` on bash 3.2.
invoke() {
  local bk="$1" mode="$2"; shift 2
  if [ "$mode" = "status" ]; then
    OUT="$(env \
        HOME="$SANDBOX" \
        ESBVAKTIN_BACKUP_DIR="$bk" \
        ESBVAKTIN_INBOX_DIR="$SANDBOX/no_such_inbox" \
        PG_DUMP="$BIN/pg_dump" PG_RESTORE="$BIN/pg_restore" PG_ISREADY="$BIN/pg_isready" \
        "$@" \
        "$BASH_BIN" "$SCRIPT" --status 2>&1)"
  else
    OUT="$(env \
        HOME="$SANDBOX" \
        ESBVAKTIN_BACKUP_DIR="$bk" \
        ESBVAKTIN_INBOX_DIR="$SANDBOX/no_such_inbox" \
        PG_DUMP="$BIN/pg_dump" PG_RESTORE="$BIN/pg_restore" PG_ISREADY="$BIN/pg_isready" \
        "$@" \
        "$BASH_BIN" "$SCRIPT" 2>&1)"
  fi
  RC=$?
}

n_dumps()    { find "$1" -name 'esbvaktin_*.dump' 2>/dev/null | wc -l | tr -d ' '; }
n_zero()     { find "$1" -name 'esbvaktin_*.dump' -size 0 2>/dev/null | wc -l | tr -d ' '; }
n_nonempty() { find "$1" -name 'esbvaktin_*.dump' ! -size 0 2>/dev/null | wc -l | tr -d ' '; }
n_temp()     { find "$1" -name '.esbvaktin_*' 2>/dev/null | wc -l | tr -d ' '; }

assert_rc_nonzero() { [ "$RC" -ne 0 ] && ok "exit non-zero ($RC) — $1" || bad "expected non-zero exit, got 0 — $1"; }
assert_rc_zero()    { [ "$RC" -eq 0 ] && ok "exit 0 — $1" || bad "expected exit 0, got $RC — $1 :: $OUT"; }
assert_eq()         { [ "$2" = "$3" ] && ok "$1 ($2)" || bad "$1: expected '$3', got '$2'"; }
assert_contains()   { printf '%s' "$OUT" | grep -q -- "$2" && ok "output contains '$2' — $1" || bad "output missing '$2' — $1 :: $OUT"; }
assert_absent()     { printf '%s' "$OUT" | grep -q -- "$2" && bad "output should NOT contain '$2' — $1 :: $OUT" || ok "output omits '$2' — $1"; }

newbk() { local d="$SANDBOX/$1"; mkdir -p "$d"; printf '%s' "$d"; }

echo "Testing: $SCRIPT"
echo "Interpreter: $BASH_BIN ($("$BASH_BIN" -c 'echo $BASH_VERSION'))"
echo

# === 1. DB down: pg_isready precheck aborts before any artifact is written ====
echo "[1] DB down -> precheck aborts, no artifact, pg_dump not invoked"
BK="$(newbk bk1)"; MARK="$SANDBOX/pg_dump_called_1"; rm -f "$MARK"
invoke "$BK" backup FAKE_PGISREADY_EXIT=1 FAKE_PGDUMP_EXIT=0 FAKE_PGDUMP_CONTENT=data FAKE_PGDUMP_MARKER="$MARK"
assert_rc_nonzero "DB down should fail the run"
assert_eq "no dump published" "$(n_dumps "$BK")" "0"
assert_eq "no temp left"      "$(n_temp "$BK")"  "0"
[ ! -f "$MARK" ] && ok "pg_dump not invoked when DB is down" || bad "pg_dump ran despite precheck"

# === 2. pg_dump exits non-zero (leaving a 0-byte temp) -> nothing published ===
echo "[2] pg_dump failure -> no 0-byte artifact survives"
BK="$(newbk bk2)"
invoke "$BK" backup FAKE_PGISREADY_EXIT=0 FAKE_PGDUMP_EXIT=1 FAKE_PGDUMP_CONTENT=
assert_rc_nonzero "pg_dump failure should fail the run"
assert_eq "no dump published"   "$(n_dumps "$BK")"  "0"
assert_eq "no 0-byte artifact"  "$(n_zero "$BK")"   "0"
assert_eq "no temp left"        "$(n_temp "$BK")"   "0"

# === 3. pg_dump exits 0 but writes 0 bytes -> rejected by size guard ==========
echo "[3] empty dump (exit 0, 0 bytes) -> rejected, never published"
BK="$(newbk bk3)"
invoke "$BK" backup FAKE_PGISREADY_EXIT=0 FAKE_PGDUMP_EXIT=0 FAKE_PGDUMP_CONTENT= FAKE_PGRESTORE_EXIT=0
assert_rc_nonzero "empty dump should fail the run"
assert_eq "no dump published" "$(n_dumps "$BK")" "0"
assert_eq "no temp left"      "$(n_temp "$BK")"  "0"

# === 4. Non-empty but unrestorable -> rejected by pg_restore guard ============
echo "[4] corrupt dump (pg_restore --list fails) -> rejected"
BK="$(newbk bk4)"
invoke "$BK" backup FAKE_PGISREADY_EXIT=0 FAKE_PGDUMP_EXIT=0 FAKE_PGDUMP_CONTENT="PGDMP-garbage" FAKE_PGRESTORE_EXIT=1
assert_rc_nonzero "corrupt dump should fail the run"
assert_eq "no dump published" "$(n_dumps "$BK")" "0"
assert_eq "no temp left"      "$(n_temp "$BK")"  "0"

# === 5. Non-empty, restorable, but EMPTY TOC -> rejected (the latent bug) =====
echo "[5] empty-TOC dump (valid header, no data) -> rejected"
BK="$(newbk bk5)"
invoke "$BK" backup FAKE_PGISREADY_EXIT=0 FAKE_PGDUMP_EXIT=0 FAKE_PGDUMP_CONTENT="PGDMP-header-only" FAKE_PGRESTORE_EXIT=0 FAKE_PGRESTORE_EMPTY_TOC=1
assert_rc_nonzero "empty-TOC dump should fail the run"
assert_eq "no dump published" "$(n_dumps "$BK")" "0"
assert_eq "no temp left"      "$(n_temp "$BK")"  "0"

# === 6. Happy path -> exactly one good dump published, status marker = OK =====
echo "[6] happy path -> one verified dump published"
BK="$(newbk bk6)"
invoke "$BK" backup FAKE_PGISREADY_EXIT=0 FAKE_PGDUMP_EXIT=0 FAKE_PGDUMP_CONTENT="PGDMP real archive bytes" FAKE_PGRESTORE_EXIT=0
assert_rc_zero "happy path should succeed"
assert_eq "one non-empty dump" "$(n_nonempty "$BK")" "1"
assert_eq "no 0-byte dump"     "$(n_zero "$BK")"     "0"
assert_eq "no temp left"       "$(n_temp "$BK")"     "0"
assert_contains "verification reported" "Verification: OK"
[ -f "$BK/last_backup_status.txt" ] && grep -q "OK" "$BK/last_backup_status.txt" \
  && ok "status marker records OK" || bad "status marker missing/!OK :: $(cat "$BK/last_backup_status.txt" 2>/dev/null)"

# === 7. Successful backup prunes pre-existing 0-byte dumps ====================
echo "[7] success cleans up historical 0-byte dumps"
BK="$(newbk bk7)"
: > "$BK/esbvaktin_20260101_000000.dump"   # pre-existing zero-byte dump
: > "$BK/esbvaktin_20260102_000000.dump"   # another one
invoke "$BK" backup FAKE_PGISREADY_EXIT=0 FAKE_PGDUMP_EXIT=0 FAKE_PGDUMP_CONTENT="PGDMP bytes" FAKE_PGRESTORE_EXIT=0
assert_rc_zero "happy path with stale zero-byte dumps should succeed"
assert_eq "zero-byte dumps removed" "$(n_zero "$BK")"     "0"
assert_eq "only the new dump remains" "$(n_nonempty "$BK")" "1"

# === 8. --status reports newest GOOD dump, not the newest 0-byte one ==========
echo "[8] --status ignores 0-byte dumps and reports last good"
BK="$(newbk bk8)"
printf 'PGDMP bytes' > "$BK/esbvaktin_20260526_031457.dump"  # real, older
: > "$BK/esbvaktin_20260618_030447.dump"                     # 0-byte, newest
invoke "$BK" status FAKE_PGRESTORE_EXIT=0 ESBVAKTIN_STALE_DAYS=36500
assert_rc_zero "--status should succeed"
assert_contains "last-good is the real dump" "Last good backup: esbvaktin_20260526_031457.dump"
assert_contains "0-byte dump flagged"        "EMPTY"
assert_absent "newest 0-byte not treated as good" "Last good backup: esbvaktin_20260618_030447.dump"

# === 9. --status warns loudly when the newest good dump is stale =============
echo "[9] --status warns when newest valid dump exceeds staleness threshold"
BK="$(newbk bk9)"
printf 'PGDMP bytes' > "$BK/esbvaktin_20200101_000000.dump"  # ancient but valid
invoke "$BK" status FAKE_PGRESTORE_EXIT=0 ESBVAKTIN_STALE_DAYS=2
assert_rc_zero "--status should still exit 0"
assert_contains "stale warning surfaced" "WARNING"

# === 10. --status warns when there is NO valid dump at all ===================
echo "[10] --status warns when every dump is empty"
BK="$(newbk bk10)"
: > "$BK/esbvaktin_20260617_030414.dump"
: > "$BK/esbvaktin_20260618_030447.dump"
invoke "$BK" status FAKE_PGRESTORE_EXIT=0 ESBVAKTIN_STALE_DAYS=2
assert_rc_zero "--status should still exit 0"
assert_contains "no-valid-backup warning" "NO valid"

# ---- Summary ----------------------------------------------------------------
echo
echo "================================================"
printf 'Passed: %d   Failed: %d\n' "$PASS" "$FAIL"
echo "================================================"
[ "$FAIL" -eq 0 ]
