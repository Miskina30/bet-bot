"""Quick inspection of failing GitHub Actions runs (public read, no token needed)."""
import httpx

REPO = "Miskina30/bet-bot"
API = "https://api.github.com"

runs = httpx.get(f"{API}/repos/{REPO}/actions/runs?per_page=5", timeout=30).json()
for w in runs.get("workflow_runs", []):
    print(f"\n=== {w['name']} | {w['status']} | {w['conclusion']} | id={w['id']}")
    jobs = httpx.get(f"{API}/repos/{REPO}/actions/runs/{w['id']}/jobs", timeout=30).json()
    for j in jobs.get("jobs", []):
        print(f"  job: {j['name']} | {j['conclusion']}")
        if j.get("conclusion") == "failure":
            for step in j.get("steps", []):
                if step.get("conclusion") == "failure":
                    print(f"    FAILED step: {step['name']}")
                    logs = httpx.get(f"{API}/repos/{REPO}/actions/jobs/{j['id']}/logs", timeout=30)
                    if logs.status_code == 200:
                        lines = logs.text.splitlines()
                        errors = [l for l in lines if "error" in l.lower() or "Error" in l or "FAILED" in l]
                        print(f"    errors ({len(errors)}):", errors[:5])
