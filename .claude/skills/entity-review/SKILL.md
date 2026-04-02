# Entity Review

Interactive browser-based entity review with terminal discussion bridge.

## Usage

```
/entity-review              # Start review session (launches browser UI)
/entity-review status       # Show review queue status (no server)
```

## Status Mode

Query entity registry directly. No server needed.

### Step 1: Query dashboard stats

```bash
uv run python -c "
from esbvaktin.entity_registry.operations import get_dashboard_stats
from esbvaktin.ground_truth.operations import get_connection
conn = get_connection()
stats = get_dashboard_stats(conn)
conn.close()
print(f'''Entity Registry Status
{'='*50}
  Total entities:       {stats['total_entities']}
  Total observations:   {stats['total_observations']}

  By verification status:''')
for status, count in stats.get('by_status', {}).items():
    pct = round(100 * count / max(stats['total_entities'], 1), 1)
    print(f'    {status}: {count} ({pct}%)')
print(f'''
  Review queue:
    Stance conflicts:   {stats['stance_conflicts']}
    Type mismatches:    {stats['type_mismatches']}
    Placeholders:       {stats['placeholders']}''')
"
```

### Step 2: Present results to user

Show the output. Highlight any non-zero queue items. Suggest `/entity-review` to start a review session if items need attention.

---

## Interactive Mode

### Step 1: Start the API server

```bash
uv run python scripts/entity_review_server.py &
```

Save the PID. Tell the user:

> Entity review server running at http://localhost:8477 — open this in your browser.

### Step 2: Enter interactive loop

Watch for two input sources:

**1. Discuss events** — check `data/entity_review_discuss.json` for new events. When a new slug appears:

```bash
uv run python -c "
import json
from esbvaktin.entity_registry.operations import get_entity_detail
from esbvaktin.ground_truth.operations import get_connection
slug = json.loads(open('data/entity_review_discuss.json').read())['slug']
conn = get_connection()
detail = get_entity_detail(slug, conn)
conn.close()
print(json.dumps(detail, indent=2, ensure_ascii=False, default=str))
"
```

Present the entity context conversationally:
- Entity name, type, subtype, stance (note if locked)
- Observation count and stance breakdown
- Each observation: observed_stance, article_url, attribution_types
- Current aliases and roles
- Any notes
- Flagged issues (stance conflict, type mismatch, etc.)

Ask: "What would you like to do with this entity?"

**2. Terminal commands** from the user:

| Command pattern | Action |
|---|---|
| `look up <name or slug>` | Load entity from DB, present context |
| `confirm all <type> where <condition>` | Query DB, confirm matching entities, report count |
| `set <slug> stance to <value> and lock` | PATCH entity, add to locked_fields, report |
| `show entities with no observations` | Query and present list |
| `show <issue_type>` | Query filtered entities, present list |
| Natural language requests | Interpret and execute via operations |

### Step 3: Apply decisions

Based on user response, execute via the operations module:

- **Confirm**: `confirm_entity(slug, conn)`
- **Edit stance + lock**: `update_entity(entity.id, {"stance": "mixed", "stance_score": 0.0, "locked_fields": ["stance"]}, conn)`
- **Dismiss observation**: `dismiss_observation(obs_id, conn)`
- **Delete entity**: `delete_entity(slug, conn)`
- **Merge**: `merge_entities(keep_id, absorb_id, conn)`

Always remind user: "Changes saved — refresh the browser to see updates."

### Step 4: Bulk operations

For bulk commands like "confirm all individuals where pro observations outnumber anti 3:1":

1. Query `get_filtered_entities` with appropriate filters
2. For each matching entity, check the condition against `stance_breakdown`
3. Confirm those that match
4. Report: "Confirmed N entities. Refresh the browser."

### Step 5: Exit

When user says "done", "exit", or "quit":

1. Kill the server process
2. Print session summary (how many confirmed, edited, merged, deleted)
3. Clean up `data/entity_review_discuss.json` if it exists
4. Suggest running `/entity-review status` to see updated queue
