"""Lightweight HTTP server for the entity review UI.

Serves the review app and handles JSON API requests.

Usage:
    uv run python scripts/entity_review_server.py
    uv run python scripts/entity_review_server.py --port 8477
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REVIEW_APP_PATH = (
    PROJECT_ROOT / "src" / "esbvaktin" / "entity_registry" / "review_app" / "index.html"
)
DISCUSS_FILE = PROJECT_ROOT / "data" / "entity_review_discuss.json"

DEFAULT_PORT = 8477
BIND_HOST = "127.0.0.1"


def _get_conn():
    """Create a fresh DB connection per request."""
    from esbvaktin.ground_truth.operations import get_connection

    return get_connection()


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress default access log; only log 4xx errors
        code = args[1] if len(args) > 1 else ""
        if str(code).startswith("4"):
            sys.stderr.write(f"[entity-review] {fmt % args}\n")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _json_response(self, data, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _error(self, status: int, message: str) -> None:
        self._json_response({"error": message}, status)

    def _parse_query(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        # Return first value for each key (single-value params)
        return {k: v[0] for k, v in qs.items()}

    # ------------------------------------------------------------------
    # OPTIONS
    # ------------------------------------------------------------------

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._serve_app()
            return

        if path == "/api/dashboard":
            self._handle_dashboard()
            return

        if path == "/api/entities":
            self._handle_entities_list()
            return

        if path.startswith("/api/entities/"):
            slug = path.removeprefix("/api/entities/")
            if slug:
                self._handle_entity_detail(slug)
                return

        self._error(404, "Not found")

    def _serve_app(self) -> None:
        if not REVIEW_APP_PATH.exists():
            self._error(404, "Review app not found")
            return
        body = REVIEW_APP_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_dashboard(self) -> None:
        from esbvaktin.entity_registry.operations import get_dashboard_stats

        conn = _get_conn()
        try:
            stats = get_dashboard_stats(conn)
            self._json_response(stats)
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    def _handle_entities_list(self) -> None:
        from esbvaktin.entity_registry.operations import get_filtered_entities

        params = self._parse_query()
        conn = _get_conn()
        try:
            entities = get_filtered_entities(
                conn,
                issue=params.get("issue"),
                entity_type=params.get("type"),
                status=params.get("status"),
                search=params.get("search"),
                sort=params.get("sort", "observations"),
            )
            self._json_response(entities)
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    def _handle_entity_detail(self, slug: str) -> None:
        from esbvaktin.entity_registry.operations import get_entity_detail

        conn = _get_conn()
        try:
            detail = get_entity_detail(slug, conn)
            if detail is None:
                self._error(404, f"Entity not found: {slug}")
                return
            self._json_response(detail)
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # PATCH
    # ------------------------------------------------------------------

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/entities/"):
            slug = path.removeprefix("/api/entities/")
            if slug and "/" not in slug:
                self._handle_entity_update(slug)
                return

        if path.startswith("/api/observations/"):
            obs_id_str = path.removeprefix("/api/observations/")
            if obs_id_str.isdigit():
                self._handle_observation_update(int(obs_id_str))
                return

        self._error(404, "Not found")

    def _handle_entity_update(self, slug: str) -> None:
        from esbvaktin.entity_registry.operations import (
            get_entity_by_slug,
            get_entity_detail,
            update_entity,
        )

        body = self._read_body()
        conn = _get_conn()
        try:
            entity = get_entity_by_slug(slug, conn)
            if entity is None:
                self._error(404, f"Entity not found: {slug}")
                return
            update_entity(entity.id, body, conn)
            detail = get_entity_detail(slug, conn)
            self._json_response(detail)
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    def _handle_observation_update(self, obs_id: int) -> None:
        from esbvaktin.entity_registry.operations import dismiss_observation, relink_observation

        body = self._read_body()
        conn = _get_conn()
        try:
            if "dismissed" in body and body["dismissed"]:
                ok = dismiss_observation(obs_id, conn)
            elif "entity_id" in body:
                ok = relink_observation(obs_id, body["entity_id"], conn)
            else:
                self._error(400, "Body must contain 'dismissed' or 'entity_id'")
                return
            if not ok:
                self._error(404, f"Observation not found: {obs_id}")
                return
            self._json_response({"ok": True})
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. /api/discuss
        if path == "/api/discuss":
            self._handle_discuss()
            return

        # 2. /api/entities/merge  (must be before slug-based routes)
        if path == "/api/entities/merge":
            self._handle_merge()
            return

        # Slug-based routes: extract slug from /api/entities/<slug>/<action>
        if path.startswith("/api/entities/"):
            remainder = path.removeprefix("/api/entities/")

            # 3. /api/entities/:slug/confirm
            if remainder.endswith("/confirm"):
                slug = remainder.removesuffix("/confirm")
                if slug:
                    self._handle_confirm(slug)
                    return

            # 4. /api/entities/:slug/delete
            if remainder.endswith("/delete"):
                slug = remainder.removesuffix("/delete")
                if slug:
                    self._handle_delete(slug)
                    return

            # 5. /api/entities/:slug/aliases
            if remainder.endswith("/aliases"):
                slug = remainder.removesuffix("/aliases")
                if slug:
                    self._handle_aliases(slug)
                    return

            # 6. /api/entities/:slug/roles
            if remainder.endswith("/roles"):
                slug = remainder.removesuffix("/roles")
                if slug:
                    self._handle_roles(slug)
                    return

        self._error(404, "Not found")

    def _handle_discuss(self) -> None:
        import datetime

        body = self._read_body()
        slug = body.get("slug")
        if not slug:
            self._error(400, "Body must contain 'slug'")
            return

        existing: list[dict] = []
        if DISCUSS_FILE.exists():
            try:
                existing = json.loads(DISCUSS_FILE.read_text())
            except json.JSONDecodeError:
                existing = []

        existing.append(
            {"slug": slug, "timestamp": datetime.datetime.now(datetime.UTC).isoformat()}
        )
        DISCUSS_FILE.write_text(json.dumps(existing, indent=2))
        self._json_response({"ok": True})

    def _handle_merge(self) -> None:
        from esbvaktin.entity_registry.operations import (
            get_entity_by_slug,
            get_entity_detail,
            merge_entities,
        )

        body = self._read_body()
        keep_slug = body.get("keep_slug")
        absorb_slug = body.get("absorb_slug")
        if not keep_slug or not absorb_slug:
            self._error(400, "Body must contain 'keep_slug' and 'absorb_slug'")
            return

        conn = _get_conn()
        try:
            keep = get_entity_by_slug(keep_slug, conn)
            absorb = get_entity_by_slug(absorb_slug, conn)
            if keep is None:
                self._error(404, f"Entity not found: {keep_slug}")
                return
            if absorb is None:
                self._error(404, f"Entity not found: {absorb_slug}")
                return
            merge_entities(keep.id, absorb.id, conn)
            detail = get_entity_detail(keep_slug, conn)
            self._json_response(detail)
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    def _handle_confirm(self, slug: str) -> None:
        from esbvaktin.entity_registry.operations import confirm_entity, get_entity_detail

        conn = _get_conn()
        try:
            result = confirm_entity(slug, conn)
            if result is None:
                self._error(404, f"Entity not found: {slug}")
                return
            detail = get_entity_detail(slug, conn)
            self._json_response(detail)
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    def _handle_delete(self, slug: str) -> None:
        from esbvaktin.entity_registry.operations import delete_entity

        conn = _get_conn()
        try:
            ok = delete_entity(slug, conn)
            if not ok:
                self._error(404, f"Entity not found: {slug}")
                return
            self._json_response({"ok": True})
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    def _handle_aliases(self, slug: str) -> None:
        from esbvaktin.entity_registry.operations import (
            get_entity_by_slug,
            get_entity_detail,
            update_entity,
        )

        body = self._read_body()
        conn = _get_conn()
        try:
            entity = get_entity_by_slug(slug, conn)
            if entity is None:
                self._error(404, f"Entity not found: {slug}")
                return
            aliases = list(entity.aliases)
            for name in body.get("add", []):
                if name not in aliases:
                    aliases.append(name)
            for name in body.get("remove", []):
                if name in aliases:
                    aliases.remove(name)
            update_entity(entity.id, {"aliases": aliases}, conn)
            detail = get_entity_detail(slug, conn)
            self._json_response(detail)
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()

    def _handle_roles(self, slug: str) -> None:
        from esbvaktin.entity_registry.operations import (
            get_entity_by_slug,
            get_entity_detail,
            update_entity,
        )

        body = self._read_body()
        conn = _get_conn()
        try:
            entity = get_entity_by_slug(slug, conn)
            if entity is None:
                self._error(404, f"Entity not found: {slug}")
                return
            roles = [r.model_dump() for r in entity.roles]
            if "add" in body:
                roles.append(body["add"])
            if "remove_index" in body:
                idx = body["remove_index"]
                if 0 <= idx < len(roles):
                    roles.pop(idx)
            update_entity(entity.id, {"roles": roles}, conn)
            detail = get_entity_detail(slug, conn)
            self._json_response(detail)
        except Exception as exc:
            self._error(500, str(exc))
        finally:
            conn.close()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Entity review UI server")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="Port to bind (default: 8477)"
    )
    args = parser.parse_args()

    server = HTTPServer((BIND_HOST, args.port), ReviewHandler)
    print(f"Entity review server running at http://{BIND_HOST}:{args.port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
