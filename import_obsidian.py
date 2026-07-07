#!/usr/bin/env python3
"""
Bulk-import an Obsidian vault into Open Notebook.

Each top-level folder in the vault becomes its own notebook (Open Notebook has no
nested-folder support). Every .md file is sent as a `text` source with embeddings
enabled, so full-text + vector search work across the whole vault.

Usage:
    python3 import_obsidian.py                 # uses defaults below
    VAULT="/mnt/c/New/Obsidian/vaults/Z Vault" python3 import_obsidian.py
    API_URL=http://localhost:5055 API_PASSWORD=secret python3 import_obsidian.py --dry-run

Requires only the standard library + `requests` (pip install requests).
"""
import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

VAULT = Path(os.environ.get("VAULT", "/mnt/c/New/Obsidian/vaults/Z Vault"))
API_URL = os.environ.get("API_URL", "http://localhost:5055").rstrip("/")
API_PASSWORD = os.environ.get("API_PASSWORD")  # only needed if OPEN_NOTEBOOK_PASSWORD is set

session = requests.Session()
if API_PASSWORD:
    session.headers["Authorization"] = f"Bearer {API_PASSWORD}"


def api(method: str, path: str, **kw):
    r = session.request(method, f"{API_URL}{path}", timeout=300, **kw)
    r.raise_for_status()
    return r.json() if r.content else {}


def get_or_create_notebook(name: str, cache: dict) -> str:
    if name in cache:
        return cache[name]
    existing = api("GET", "/api/notebooks")
    items = existing.get("data", existing) if isinstance(existing, dict) else existing
    for nb in items or []:
        if nb.get("name") == name:
            cache[name] = nb["id"]
            return nb["id"]
    created = api("POST", "/api/notebooks", json={"name": name, "description": f"Imported from Obsidian: {name}"})
    nb_id = created.get("id") or created.get("data", {}).get("id")
    cache[name] = nb_id
    return nb_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="List what would be imported, change nothing")
    ap.add_argument("--no-embed", action="store_true", help="Skip vector embeddings (faster, search-by-keyword only)")
    args = ap.parse_args()

    if not VAULT.is_dir():
        sys.exit(f"Vault not found: {VAULT}")

    md_files = sorted(VAULT.rglob("*.md"))
    if not md_files:
        sys.exit(f"No .md files under {VAULT}")

    print(f"Vault:   {VAULT}")
    print(f"API:     {API_URL}")
    print(f"Files:   {len(md_files)} markdown notes")
    print(f"Embed:   {not args.no_embed}")
    print("-" * 60)

    cache: dict = {}
    ok = fail = 0
    for f in md_files:
        rel = f.relative_to(VAULT)
        # Top-level folder -> notebook name. Files in the vault root go to "Inbox".
        notebook_name = rel.parts[0] if len(rel.parts) > 1 else "Inbox"
        title = rel.as_posix()

        if args.dry_run:
            print(f"[dry] {notebook_name:<14} <- {title}")
            ok += 1
            continue

        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            if not content.strip():
                print(f"[skip empty] {title}")
                continue
            nb_id = get_or_create_notebook(notebook_name, cache)
            # API serves under /api and expects multipart/form-data Form fields
            # (notebooks is a single id string; embed is a string flag).
            api("POST", "/api/sources", data={
                "type": "text",
                "content": content,
                "title": title,
                "notebooks": json.dumps([nb_id]),
                "embed": "true" if not args.no_embed else "false",
            })
            print(f"[ok]  {notebook_name:<14} <- {title}")
            ok += 1
        except Exception as e:
            print(f"[ERR] {title}: {e}")
            fail += 1

    print("-" * 60)
    print(f"Done. {ok} imported, {fail} failed. Notebooks: {', '.join(sorted(cache)) or '(dry-run)'}")


if __name__ == "__main__":
    main()
