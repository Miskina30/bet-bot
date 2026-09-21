"""Final deploy orchestration: clean remote junk, push local state, trigger Pages.

Runs entirely via the GitHub REST API using the token from scripts/.ghtoken.tmp
(read at runtime, never printed).
"""
import os
import subprocess
import sys
import traceback
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = Path(__file__).resolve().parent / ".ghtoken.tmp"
LOG = ROOT / "deploy_pages_debug.log"
API = "https://api.github.com"
OWNER = "Miskina30"
REPO = "bet-bot"

# Remote files to delete (contain revoked token / broken template / debug junk)
DELETE_PATHS = [
    "scripts/.ghtoken.tmp",
    ".github/workflows/nextjs.yml",
    ".bootstrap",
]


def headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def delete_remote_file(client: httpx.Client, token: str, path: str) -> str:
    """Delete a file on the remote via the Contents API."""
    r = client.get(
        f"{API}/repos/{OWNER}/{REPO}/contents/{path}", headers=headers(token)
    )
    if r.status_code == 404:
        return f"  {path}: not present (skip)"
    if r.status_code != 200:
        return f"  {path}: GET failed {r.status_code}"
    sha = r.json()["sha"]
    d = client.request(
        "DELETE",
        f"{API}/repos/{OWNER}/{REPO}/contents/{path}",
        headers=headers(token),
        json={
            "message": f"chore: remove {path} (cleanup before redeploy)",
            "sha": sha,
            "branch": "main",
        },
    )
    return f"  {path}: {'deleted' if d.status_code == 200 else f'failed {d.status_code}'}"


def main() -> int:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        env = dict(os.environ)
        env["GH_TOKEN"] = token
        out: list[str] = []

        with httpx.Client(timeout=60.0) as client:
            out.append("== remote cleanup ==")
            for path in DELETE_PATHS:
                out.append(delete_remote_file(client, token, path))

        out.append("== push local state ==")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "push_to_github.py")],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
        )
        out.append(proc.stdout[-5000:])
        if proc.returncode != 0:
            out.append(proc.stderr[-2000:])

        out.append("== trigger Pages workflow ==")
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{API}/repos/{OWNER}/{REPO}/actions/workflows/pages.yml/dispatches",
                headers=headers(token),
                json={"ref": "main"},
            )
            out.append(f"  dispatch pages.yml: {r.status_code}")
            r2 = client.get(
                f"{API}/repos/{OWNER}/{REPO}/actions/runs?per_page=3",
                headers=headers(token),
            )
            for w in r2.json().get("workflow_runs", [])[:3]:
                out.append(
                    f"  {w['name']} | {w['status']} | {w['conclusion']} | {w['html_url']}"
                )

        LOG.write_text("\n".join(out), encoding="utf-8")
        print("\n".join(out))
        return 0
    except Exception:
        LOG.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
