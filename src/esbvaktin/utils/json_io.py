"""Write-if-changed JSON/text helpers (fresh-03 / latency-07).

The site export rewrites ~2,200 detail files every run regardless of change, bloating git
churn and forcing full GitHub Pages rebuilds. These helpers skip byte-identical writes so
unchanged files keep their bytes (and mtime). Compare the FINAL serialised bytes — including
any DB-verdict overlay — so a genuine content change still triggers a write.
"""

from __future__ import annotations

import json
from pathlib import Path


def write_text_if_changed(path: Path, text: str) -> bool:
    """Write ``text`` to ``path`` only if it differs from the current content.

    Returns True if the file was written, False if it already held identical content.
    """
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def write_json_if_changed(path: Path, data, *, indent: int = 2) -> bool:
    """Serialise ``data`` to JSON (ensure_ascii=False, default=str) and write only if changed.

    Matches the export scripts' serialisation, so swapping a json.dump call for this is
    output-identical for plain data — it just skips the write when nothing changed.
    """
    text = json.dumps(data, ensure_ascii=False, indent=indent, default=str)
    return write_text_if_changed(path, text)
