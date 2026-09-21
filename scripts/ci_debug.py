"""Inspect the latest CI run failures (public read)."""
import httpx

API = "https://api.github.com"
REPO = "Miskina30/bet-bot"

runs = httpx.get(f"{API}/repos/{REPO}/actions/runs?per_page=6", timeout=30).json()
for w in runs.get("workflow_runs", []):
    if w["name"] != ".github/workflows/ci.yml":
        continue
    print(f"\n=== CI run {w['id']} | {w['status']} | {w['conclusion']}")
    jobs = httpx.get(f"{API}/repos/{REPO}/actions/runs/{w['id']}/jobs", timeout=30).json()
    print(f"jobs returned: {len(jobs.get('jobs', []))}")
    for j in jobs.get("jobs", []):
        print(f"  JOB: {j['name']} | {j['conclusion']}")
        for s in j.get("steps", []):
            mark = "  <-- FAILED" if s.get("conclusion") == "failure" else ""
            print(f"    {s['name']}: {s.get('conclusion')}{mark}")
    break
