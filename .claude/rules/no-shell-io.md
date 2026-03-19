---
description: Use dedicated tools instead of shell commands for file I/O — shell patterns with special characters trigger security prompts even when the command is allowed
globs: ["**"]
---

# Prefer Dedicated Tools Over Shell Commands

Claude Code's security scanner flags shell commands containing special characters — **regardless of whether the command is in the allowed permissions list**. These patterns trigger interactive "Do you want to proceed?" prompts that break autonomous skill execution.

## Patterns that trigger security prompts

| Shell pattern | Security check triggered |
|---|---|
| `< file` (input redirection) | "could read sensitive files" |
| `> file`, `cat > file << 'EOF'` (heredocs) | "expansion obfuscation" |
| `cmd1; echo "..."` (semicolons + quotes) | "quoted characters in flag names" |
| `cmd1 \| cmd2` (pipe chains) | Compound command check |
| `$()`, backticks in commands | Command substitution check |

## Dedicated tools never prompt

| Operation | Use this | Not this |
|---|---|---|
| Read file | **Read tool** | `cat`, `head`, `tail`, `less` |
| Write file | **Write tool** | Heredocs, `echo >`, `cat >` |
| Search content | **Grep tool** | `grep`, `rg`, `awk` |
| Find files | **Glob tool** | `find`, `ls` |
| Count/parse | **Read tool** + count in context | `wc -l < file` |
| Check existence | **Glob tool** | `[ -f file ]`, `test -f` |
| DB queries | `uv run python -c "..."` with `get_connection()` | `psql` (hardcodes credentials too) |

## Bash IS appropriate for

- `uv run python ...` — running Python scripts
- `git ...` — version control
- `mkdir -p` — creating directories
- `npm run ...` — site builds
- Simple single commands without special characters

## If the Write tool fails

Read the file first with Read tool, then retry Write. Do not fall back to shell diagnostics.
