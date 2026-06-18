#!/usr/bin/env bash
#
# Regression tests for scripts/backup_healthcheck.sh.
#
# The healthcheck is the *active surfacing* layer added after the 23-day silent
# backup outage (2026-06-18): the backup job had been exiting non-zero for weeks
# but the only sink was a log file nobody read. This watchdog polls the durable
# signals the hardened backup_db.sh now emits — the OK/FAILED status marker and
# the `--status` staleness WARNING — and fires a macOS notification when a
# backup is failing or stale, so the failure can't stay silent.
#
# These tests prove the *decision* logic (alert vs. stay quiet) without firing a
# real GUI notification: the script honours an ESBVAKTIN_NOTIFY_FILE seam that
# captures the would-be notification to a file instead. The DB tools are faked
# via the same PG_DUMP / PG_RESTORE / PG_ISREADY seams backup_db.sh honours, and
# the backup directory is redirected with ESBVAKTIN_BACKUP_DIR so the real
# ~/Documents/esbvaktin-backups is never touched.
#
# Run:  bash tests/test_backup_healthcheck.sh
# Exit: 0 if all assertions pass, 1 otherwise.

set -u  # NOT -e: we want every assertion to run and tally, not abort on first.

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
HC_SCRIPT="$ROOT/scripts/backup_healthcheck.sh"
# Run under the same interpreter launchd uses (system bash 3.2) so any
# bash-4-only syntax is caught here rather than in production.
BASH_BIN="/bin/bash"

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/backup_healthcheck_test.XXXXXX")"
BIN="$SANDBOX/bin"
mkdir -p "$BIN"
trap 'rm -rf "$SANDBOX"' EXIT

PASS=0
FAIL=0
ok()  { printf '    ok   %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL   %s\n' "$1"; FAIL=$((FAIL + 1)); }

# ---- Fake DB binaries (backup_db.sh --status only needs pg_restore --list) ----
# A non-empty dump file + this fake = a "valid, restorable" dump in --status eyes.

cat > "$BIN/pg_dump" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

cat > "$BIN/pg_restore" <<'EOF'
#!/usr/bin/env bash
# Mimic `pg_restore --list <file>`: print one TOC entry so dump_is_valid() in
# backup_db.sh treats any non-empty file as a restorable dump.
echo ";"
echo "; Selected TOC Entries:"
echo "215; 1259 16456 TABLE public claims esb"
exit 0
EOF

cat > "$BIN/pg_isready" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

chmod +x "$BIN/pg_dump" "$BIN/pg_restore" "$BIN/pg_isready"

# ---- Invocation + assertion helpers -----------------------------------------

OUT=""; RC=0

# invoke_hc <backup-dir> <notify-file> [EXTRA_ENV=VAL ...]
# No array expansion — an empty "${arr[@]}" trips `set -u` on bash 3.2.
invoke_hc() {
  local bk="$1" nf="$2"; shift 2
  OUT="$(env \
      HOME="$SANDBOX" \
      ESBVAKTIN_BACKUP_DIR="$bk" \
      ESBVAKTIN_NOTIFY_FILE="$nf" \
      PG_DUMP="$BIN/pg_dump" PG_RESTORE="$BIN/pg_restore" PG_ISREADY="$BIN/pg_isready" \
      "$@" \
      "$BASH_BIN" "$HC_SCRIPT" 2>&1)"
  RC=$?
}

# invoke_hc_dry <backup-dir> [EXTRA_ENV=VAL ...] — runs with --dry-run, no seam.
invoke_hc_dry() {
  local bk="$1"; shift
  OUT="$(env \
      HOME="$SANDBOX" \
      ESBVAKTIN_BACKUP_DIR="$bk" \
      PG_DUMP="$BIN/pg_dump" PG_RESTORE="$BIN/pg_restore" PG_ISREADY="$BIN/pg_isready" \
      "$@" \
      "$BASH_BIN" "$HC_SCRIPT" --dry-run 2>&1)"
  RC=$?
}

newbk()   { local d="$SANDBOX/$1"; mkdir -p "$d"; printf '%s' "$d"; }
mark_ok()     { printf '%s\tOK\tverified backup published\n'  "$(date '+%Y-%m-%d %H:%M:%S')" > "$1/last_backup_status.txt"; }
mark_failed() { printf '%s\tFAILED\texit 1\n'                 "$(date '+%Y-%m-%d %H:%M:%S')" > "$1/last_backup_status.txt"; }

assert_rc_zero()     { [ "$RC" -eq 0 ] && ok "exit 0 — $1" || bad "expected exit 0, got $RC — $1 :: $OUT"; }
assert_notified()    { [ -s "$1" ] && ok "notification fired — $2" || bad "expected a notification — $2 :: stdout=$OUT"; }
assert_not_notified(){ [ ! -s "$1" ] && ok "stayed quiet — $2" || bad "unexpected notification — $2 :: $(cat "$1" 2>/dev/null)"; }
assert_notify_has()  { grep -q -- "$2" "$1" && ok "notification mentions '$2' — $3" || bad "notification missing '$2' — $3 :: $(cat "$1" 2>/dev/null)"; }
assert_out_has()     { printf '%s' "$OUT" | grep -q -- "$2" && ok "output contains '$2' — $1" || bad "output missing '$2' — $1 :: $OUT"; }
assert_out_lacks()   { printf '%s' "$OUT" | grep -q -- "$2" && bad "output should NOT contain '$2' — $1 :: $OUT" || ok "output omits '$2' — $1"; }

echo "Testing: $HC_SCRIPT"
echo "Interpreter: $BASH_BIN ($("$BASH_BIN" -c 'echo $BASH_VERSION'))"
echo

# === 1. Healthy: fresh valid dump + OK marker -> no notification ==============
echo "[1] healthy backups -> watchdog stays quiet"
BK="$(newbk bk1)"; NF="$SANDBOX/nf1"; rm -f "$NF"
printf 'PGDMP real bytes' > "$BK/esbvaktin_20200101_000000.dump"  # valid (age irrelevant: huge threshold)
mark_ok "$BK"
invoke_hc "$BK" "$NF" ESBVAKTIN_STALE_DAYS=36500
assert_rc_zero "healthy run"
assert_not_notified "$NF" "all signals green"
assert_out_has "logs an OK line" "OK"

# === 2. FAILED marker -> notification, even if a recent good dump exists ======
echo "[2] last run FAILED -> notify (failure surfaced)"
BK="$(newbk bk2)"; NF="$SANDBOX/nf2"; rm -f "$NF"
printf 'PGDMP real bytes' > "$BK/esbvaktin_20200101_000000.dump"  # a valid dump still on disk
mark_failed "$BK"
invoke_hc "$BK" "$NF" ESBVAKTIN_STALE_DAYS=36500   # not stale -> only the FAILED marker should trigger
assert_rc_zero "failed-marker run still exits 0 (alerting is success)"
assert_notified "$NF" "FAILED marker"
assert_notify_has "$NF" "FAILED" "names the failure"

# === 3. Stale dump (no recent valid backup) -> notification ===================
echo "[3] newest valid dump is stale -> notify"
BK="$(newbk bk3)"; NF="$SANDBOX/nf3"; rm -f "$NF"
printf 'PGDMP real bytes' > "$BK/esbvaktin_20200101_000000.dump"  # ancient but valid
mark_ok "$BK"   # marker says OK, but the dump itself is old -> staleness must still fire
invoke_hc "$BK" "$NF" ESBVAKTIN_STALE_DAYS=2
assert_rc_zero "stale run"
assert_notified "$NF" "stale dump"
assert_notify_has "$NF" "stale" "names staleness"

# === 4. No valid dump at all (only 0-byte) -> notification ====================
echo "[4] every dump empty -> notify (no valid backup)"
BK="$(newbk bk4)"; NF="$SANDBOX/nf4"; rm -f "$NF"
: > "$BK/esbvaktin_20260617_030414.dump"
: > "$BK/esbvaktin_20260618_030447.dump"
invoke_hc "$BK" "$NF" ESBVAKTIN_STALE_DAYS=2
assert_rc_zero "no-valid-backup run"
assert_notified "$NF" "no valid backup"
assert_notify_has "$NF" "no valid" "names the missing-backup condition"

# === 5. FAILED marker AND stale -> a single combined notification ============
echo "[5] failed + stale -> one notification combining both reasons"
BK="$(newbk bk5)"; NF="$SANDBOX/nf5"; rm -f "$NF"
printf 'PGDMP real bytes' > "$BK/esbvaktin_20200101_000000.dump"
mark_failed "$BK"
invoke_hc "$BK" "$NF" ESBVAKTIN_STALE_DAYS=2
assert_rc_zero "combined run"
assert_notified "$NF" "failed+stale"
# exactly one notification line captured (reasons combined, not double-fired)
LINES="$(grep -c . "$NF" 2>/dev/null | tr -d ' ')"
[ "$LINES" = "1" ] && ok "single combined notification ($LINES line)" || bad "expected 1 notification line, got $LINES :: $(cat "$NF")"
assert_notify_has "$NF" "FAILED" "combined: failure"
assert_notify_has "$NF" "stale"  "combined: staleness"

# === 6. --dry-run: reports the decision, fires nothing =======================
echo "[6] --dry-run -> prints decision, never notifies"
BK="$(newbk bk6)"
printf 'PGDMP real bytes' > "$BK/esbvaktin_20200101_000000.dump"
mark_failed "$BK"
invoke_hc_dry "$BK" ESBVAKTIN_STALE_DAYS=2
assert_rc_zero "dry-run exits 0"
assert_out_has "dry-run announces it would notify" "dry-run"
assert_out_has "dry-run still names the problem" "FAILED"

# === 7. Missing backup_db.sh status (script unfindable) -> notify + non-zero ==
echo "[7] backup script missing -> watchdog still surfaces its own failure"
BK="$(newbk bk7)"; NF="$SANDBOX/nf7"; rm -f "$NF"
# Point the watchdog at a non-existent backup script via the override seam.
invoke_hc "$BK" "$NF" ESBVAKTIN_BACKUP_SCRIPT="$SANDBOX/no_such_backup_db.sh"
[ "$RC" -ne 0 ] && ok "internal failure exits non-zero ($RC)" || bad "expected non-zero exit on internal failure, got 0 :: $OUT"
assert_notified "$NF" "watchdog self-failure"

# ---- Summary ----------------------------------------------------------------
echo
echo "================================================"
printf 'Passed: %d   Failed: %d\n' "$PASS" "$FAIL"
echo "================================================"
[ "$FAIL" -eq 0 ]
