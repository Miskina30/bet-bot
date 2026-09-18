"""Enable GitHub Pages (workflow build) for the repo, via the REST API.

Reads the token from GH_TOKEN only; never prints it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

OWNER = "Miskina30"
REPO = "bet-bot"
API = "https://api.github.com"
TOKEN_FILE = Path(__file__).resolve().parent / ".ghtoken.tmp"


def headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def main() -> int:
    token = os.environ.get("GH_TOKEN", "").strip() or TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        print("ERROR: no token", file=sys.stderr)
        return 2
    with httpx.Client(timeout=60.0) as client:
        status = client.get(f"{API}/repos/{OWNER}/{REPO}/pages", headers=headers(token))
        if status.status_code == 200:
            data = status.json()
            print(f"Pages already enabled: {data.get('html_url')} build_type={data.get('build_type')}")
            return 0
        if status.status_code not in (404,):
            print(f"unexpected GET pages status {status.status_code}: {status.text[:300]}")

        create = client.post(
            f"{API}/repos/{OWNER}/{REPO}/pages",
            headers=headers(token),
            json={"build_type": "workflow"},
        )
        print(f"POST /pages -> {create.status_code}")
        if create.status_code >= 400:
            print(create.text[:500])
            return 1
        data = create.json()
        print(f"Pages enabled: {data.get('html_url')} build_type={data.get('build_type')}")

        again = client.get(f"{API}/repos/{OWNER}/{REPO}/pages", headers=headers(token))
        if again.status_code == 200:
            info = again.json()
            print(f"verified: url={info.get('html_url')} status={info.get('status')} build_type={info.get('build_type')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
