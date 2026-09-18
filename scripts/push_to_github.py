"""Push the local codebase to GitHub via the REST Git Data API (no git CLI).

Usage (PowerShell, from repo root):
    $env:GH_TOKEN = '<token>'   # never commit this; revoke after use
    .venv\\Scripts\\python.exe scripts/push_to_github.py
    $env:GH_TOKEN = $null

The token is read ONLY from the GH_TOKEN environment variable and is never
printed or logged. Files matching the repo .gitignore secret/data rules
(.env, .venv, caches, local DBs, logs) are excluded from the push.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import httpx

OWNER = "Miskina30"
REPO = "bet-bot"
BRANCH = "main"
API = "https://api.github.com"

EXCLUDE_DIRS = {
    ".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".hypothesis", ".data", "node_modules", "test-results", "secrets",
    "raw-archive", ".mypy_cache",
}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".db", ".sqlite3", ".pem", ".key")
EXCLUDE_NAMES = {".env"}


def should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if rel == ".env":
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    if path.name.startswith(".pip-"):
        return True
    return any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts[:-1])


def collect_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.name == "push_to_github.py" and p.parent.name == "scripts":
            files.append(p)
            continue
        if should_skip(p, root):
            continue
        if p.stat().st_size > 90 * 1024 * 1024:
            print(f"SKIP (too large): {p.relative_to(root)}")
            continue
        files.append(p)
    return files


def gh(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    url = API + path
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.request(method, url, headers=headers, json=payload)
    if resp.status_code == 404:
        raise FileNotFoundError(f"GitHub 404: {method} {path}")
    if resp.status_code >= 400:
        body = resp.text[:500]
        raise RuntimeError(f"GitHub {resp.status_code} on {method} {path}: {body}")
    return resp.json() if resp.text else {}


def ensure_repo(token: str) -> None:
    try:
        gh("GET", f"/repos/{OWNER}/{REPO}", token)
        print(f"repo exists: {OWNER}/{REPO}")
    except FileNotFoundError:
        print(f"repo missing, creating private repo {OWNER}/{REPO} ...")
        gh("POST", "/user/repos", token, {"name": REPO, "private": True,
            "description": "Academic Edge - read-only football market-intelligence MVP (research only, no wagering)"})
        print("repo created.")


def main() -> int:
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print("ERROR: set GH_TOKEN env var first. Refusing to run without it.", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    files = collect_files(root)
    print(f"collected {len(files)} files (secrets/caches/venvs excluded)")
    if any(p.name == ".env" and p.parent == root for p in files):
        print("ERROR: .env would be pushed - aborting", file=sys.stderr)
        return 2

    ensure_repo(token)

    def read_branch() -> tuple[str | None, list[str]]:
        try:
            ref_obj = gh("GET", f"/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}", token)
            sha = ref_obj["object"]["sha"]
            commit_obj = gh("GET", f"/repos/{OWNER}/{REPO}/git/commits/{sha}", token)
            return commit_obj["tree"]["sha"], [sha]
        except FileNotFoundError:
            return None, []
        except RuntimeError as exc:
            if "409" in str(exc) and "empty" in str(exc).lower():
                return None, []
            raise

    base_tree, parents = read_branch()
    if base_tree is None and not parents:
        # Repo may be completely empty: bootstrap the first commit via the
        # Contents API (Git Data API cannot write into a commitless repo).
        print("bootstrapping empty repo with an initial commit ...")
        payload = base64.b64encode(b"# bet-bot bootstrap\n").decode()
        try:
            gh("PUT", f"/repos/{OWNER}/{REPO}/contents/.bootstrap", token, {
                "message": "bootstrap: initialise repository",
                "content": payload,
                "branch": BRANCH,
            })
            print("bootstrap commit created.")
        except RuntimeError as exc:
            if "422" not in str(exc):
                raise
            print("bootstrap skipped (branch already initialised).")
        base_tree, parents = read_branch()
        print(f"branch {BRANCH} now readable: parents={len(parents)}")
    else:
        print(f"branch {BRANCH} exists")

    tree_entries: list[dict] = []
    for i, path in enumerate(files, 1):
        rel = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
            blob = gh("POST", f"/repos/{OWNER}/{REPO}/git/blobs", token,
                      {"content": text, "encoding": "utf-8"})
        except UnicodeDecodeError:
            blob = gh("POST", f"/repos/{OWNER}/{REPO}/git/blobs", token,
                      {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        tree_entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if i % 25 == 0 or i == len(files):
            print(f"  blobs {i}/{len(files)}")

    tree_payload: dict = {"tree": tree_entries}
    if base_tree:
        tree_payload["base_tree"] = base_tree
    tree = gh("POST", f"/repos/{OWNER}/{REPO}/git/trees", token, tree_payload)
    print(f"tree created: {tree['sha'][:7]} ({len(tree_entries)} entries)")

    commit = gh("POST", f"/repos/{OWNER}/{REPO}/git/commits", token, {
        "message": "Academic Edge MVP: full codebase push (domain, pricing, connectors, resolver, API, worker, web, tests, docs)",
        "tree": tree["sha"],
        "parents": parents,
    })
    print(f"commit created: {commit['sha'][:7]}")

    try:
        gh("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}", token,
           {"sha": commit["sha"], "force": True})
    except FileNotFoundError:
        gh("POST", f"/repos/{OWNER}/{REPO}/git/refs", token,
           {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    print(f"branch {BRANCH} now at {commit['sha'][:7]}")

    verify = gh("GET", f"/repos/{OWNER}/{REPO}/git/trees/{tree['sha']}?recursive=1", token)
    remote_paths = sorted(t["path"] for t in verify.get("tree", []) if t.get("type") == "blob")
    local_paths = sorted(p.relative_to(root).as_posix() for p in files)
    missing = [p for p in local_paths if p not in remote_paths]
    extra = [p for p in remote_paths if p not in local_paths]
    print(f"verify: remote has {len(remote_paths)} blobs; missing={len(missing)} extra={len(extra)}")
    for p in missing[:10]:
        print(f"  MISSING: {p}")
    for p in extra[:10]:
        print(f"  EXTRA(leftover on branch): {p}")
    print(f"DONE commit={commit['sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

