"""Make the remote branch mirror the local tree exactly (deletes leftovers).

GitHub's Git Data API builds a tree on top of `base_tree`, so files deleted
locally linger on the remote. This script computes the difference and deletes
remote paths that no longer exist locally.
"""
import os
import sys
import traceback
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = Path(__file__).resolve().parent / ".ghtoken.tmp"
API = "https://api.github.com"
OWNER = "Miskina30"
REPO = "bet-bot"
BRANCH = "main"

sys.path.insert(0, str(ROOT / "scripts"))
from push_to_github import collect_files  # noqa: E402


def headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def main() -> int:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        h = headers(token)
        local = {p.relative_to(ROOT).as_posix() for p in collect_files(ROOT)}

        with httpx.Client(timeout=60.0) as client:
            ref = client.get(
                f"{API}/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}", headers=h
            ).json()
            tree_sha = client.get(
                f"{API}/repos/{OWNER}/{REPO}/git/commits/{ref['object']['sha']}", headers=h
            ).json()["tree"]["sha"]
            tree = client.get(
                f"{API}/repos/{OWNER}/{REPO}/git/trees/{tree_sha}?recursive=1", headers=h
            ).json()

            remote = {
                t["path"]: t["sha"] for t in tree.get("tree", []) if t.get("type") == "blob"
            }
            extras = sorted(set(remote) - local)
            print(f"local={len(local)} remote={len(remote)} extras={len(extras)}")
            for path in extras:
                print(f"  deleting {path}")
                r = client.request(
                    "DELETE",
                    f"{API}/repos/{OWNER}/{REPO}/contents/{path}",
                    headers=h,
                    json={
                        "message": f"chore: delete stale {path} (mirror local tree)",
                        "sha": remote[path],
                        "branch": BRANCH,
                    },
                )
                print(f"    -> {r.status_code}")
        return 0
    except Exception:
        print(traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
