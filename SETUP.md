# ESBvaktin — Machine Setup Runbook

Recovery reference. Not a tutorial.

---

## Prerequisites

- Python 3.12+ (`brew install python@3.12`)
- uv (`brew install uv` or `curl -Ls https://astral.sh/uv/install.sh | sh`)
- Docker Desktop (for PostgreSQL)
- Git
- Homebrew libpq (`brew install libpq`) — needed for `pg_dump` in backup script
- R + ggplot2 (optional, for data fetching scripts)

---

## Clone + Install

```bash
git clone git@github.com:brynjolfurjonsson/esbvaktin.git ~/esbvaktin
cd ~/esbvaktin
uv sync
```

Optional extras (install what you need):

```bash
uv sync --extra dev          # pytest, ruff
uv sync --extra embeddings   # FlagEmbedding + torch (~2 GB, needs BAAI/bge-m3)
uv sync --extra icelandic    # GreynirCorrect, Icegrams, Islenska, Reynir
uv sync --extra email        # Mailgun (requests)
uv sync --extra ghost        # Ghost CMS publishing (pyjwt)
```

Note: `embeddings` requires `--extra embeddings`, not `uv pip install` — the latter won't resolve correctly.

---

## Environment Variables

Create `.env` in the project root (never committed):

```dotenv
DATABASE_URL=postgresql://esb:localdev@localhost:5432/esbvaktin

# Optional — Icelandic quality pipeline
MALSTADUR_API_KEY=...

# Optional — email pipeline
MAILGUN_API_KEY=...
MAILGUN_DOMAIN=...

# Optional — Ghost CMS
GHOST_URL=...
GHOST_ADMIN_KEY=...
```

Default `DATABASE_URL` (`postgresql://esb:localdev@localhost:5432/esbvaktin`) is the Docker dev instance. No `.env` entry needed if using defaults.

---

## Database Setup

```bash
docker compose up -d                            # Start PostgreSQL 17 + pgvector
uv run python scripts/init_db.py               # Create schema (tables, indices, triggers)
uv run python scripts/seed_evidence.py insert data/seeds/   # Seed committed evidence
```

Shortcut — schema + seed in one step:

```bash
uv run python scripts/init_db.py --seed
```

Docker container: `esbvaktin-db`, port 5432, credentials `esb/localdev`, DB `esbvaktin`. Data persisted in Docker volume `esbvaktin_data`.

---

## Alþingi Speech Database

The speeches MCP server reads from a local SQLite file (read-only, not in this repo):

```
data/althingi.db
```

Obtain from backup or the Þingfrettir pipeline. The speeches MCP server will fail to start without it. The main pipeline works without it.

---

## Site Repo

The 11ty site lives in a sibling directory:

```bash
git clone git@github.com:brynjolfurjonsson/esbvaktin-site.git ~/esbvaktin-site
```

Export scripts assume `~/esbvaktin-site` exists. Pass `--site-dir` to override.

---

## Automated Backups (launchd)

Daily DB backup at 03:00, writes to `~/Documents/esbvaktin-backups/` (synced to iCloud).

The plist is tracked in the repo — install it from the committed template rather than hand-writing it:

```bash
cp deploy/launchd/is.esbvaktin.backup-db.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/is.esbvaktin.backup-db.plist
```

Verify: `./scripts/backup_db.sh --status`

The template's PATH uses the version-agnostic libpq symlink (`/opt/homebrew/opt/libpq/bin`), so a `brew upgrade libpq` won't break the job. `PGPASSWORD=localdev` is the local Docker dev credential, not a secret.

---

## Backup Healthcheck (launchd)

Active surfacing so a backup failure can't stay silent (the 03:00 job once exited non-zero for ~23 days with no one notified — its only sink was `backup.log`). A separate watchdog runs daily at 09:00, polls the durable signals `backup_db.sh` emits, and fires a macOS notification when the last run **FAILED** or the newest valid dump is **stale / missing**:

```bash
cp deploy/launchd/is.esbvaktin.backup-healthcheck.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/is.esbvaktin.backup-healthcheck.plist
```

Verify (prints the decision, fires no notification):

```bash
./scripts/backup_healthcheck.sh --dry-run
```

- It is a **separate** LaunchAgent, not a hook inside the backup job, so it still alerts when the backup job never ran at all (unloaded, throttled off, or died early).
- It needs no database — it only reads `last_backup_status.txt` and runs `backup_db.sh --status`. It does shell out to `pg_restore` to validate dumps, so its plist PATH includes libpq.
- Notification backend: `terminal-notifier` if installed, else `osascript`. `ESBVAKTIN_STALE_DAYS` (default 2) sets the staleness threshold.
- Logs: `~/Documents/esbvaktin-backups/backup-healthcheck.log`.

---

## Link Rot Check (launchd)

Weekly URL check every Monday at 09:00.

Create `~/Library/LaunchAgents/is.esbvaktin.linkcheck.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>is.esbvaktin.linkcheck</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/brynjolfurjonsson/.local/bin/uv</string>
        <string>run</string>
        <string>python</string>
        <string>scripts/check_evidence_urls.py</string>
        <string>check</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/brynjolfurjonsson/esbvaktin</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>9</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/brynjolfurjonsson/Documents/esbvaktin-backups/linkcheck.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/brynjolfurjonsson/Documents/esbvaktin-backups/linkcheck.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/is.esbvaktin.linkcheck.plist
```

Logs: `~/Documents/esbvaktin-backups/linkcheck.log` / `.err`

Run manually: `uv run python scripts/check_evidence_urls.py check`

---

## Verify Setup

```bash
uv run --extra dev python -m pytest       # 340 tests, all should pass
uv run python scripts/seed_evidence.py status   # Evidence count
uv run python scripts/manage_inbox.py status    # Inbox state
```

---

## Notes

- Backup plists are committed templates in `deploy/launchd/` — `cp` them to `~/Library/LaunchAgents/` and `launchctl load`. The linkcheck plist content is inline above; create it manually.
- Backup dir `~/Documents/esbvaktin-backups/` is created automatically on first `backup_db.sh` run.
- `data/analyses/`, `data/reassessment/`, `data/inbox/` are gitignored — restore from backup if needed.
- Inbox (`data/inbox/inbox.json`) is backed up daily alongside the DB dump.
