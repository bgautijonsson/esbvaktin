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

Create `~/Library/LaunchAgents/is.esbvaktin.backup-db.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>is.esbvaktin.backup-db</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/brynjolfurjonsson/esbvaktin/scripts/backup_db.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/brynjolfurjonsson/Documents/esbvaktin-backups/backup.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/brynjolfurjonsson/Documents/esbvaktin-backups/backup.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/Cellar/libpq/18.2/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>PGPASSWORD</key>
        <string>localdev</string>
    </dict>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/is.esbvaktin.backup-db.plist
```

Verify: `./scripts/backup_db.sh --status`

Note: if libpq version differs from `18.2`, update the PATH in the plist (`brew info libpq` to check).

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

- Plist content is in this file — create them manually at `~/Library/LaunchAgents/` on a new machine.
- Backup dir `~/Documents/esbvaktin-backups/` is created automatically on first `backup_db.sh` run.
- `data/analyses/`, `data/reassessment/`, `data/inbox/` are gitignored — restore from backup if needed.
- Inbox (`data/inbox/inbox.json`) is backed up daily alongside the DB dump.
