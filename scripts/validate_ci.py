"""Validate the remote CI workflow YAML and report structural problems."""
import base64

import httpx
import yaml

API = "https://api.github.com"
REPO = "Miskina30/bet-bot"

r = httpx.get(f"{API}/repos/{REPO}/contents/.github/workflows/ci.yml", timeout=30)
raw = base64.b64decode(r.json()["content"]).decode()
print(f"ci.yml length: {len(raw)}")
try:
    doc = yaml.safe_load(raw)
    print("YAML: parsed OK")
except yaml.YAMLError as exc:
    print(f"YAML: INVALID -> {exc}")
    raise SystemExit(1)

print(f"top-level keys: {list(doc.keys())}")
print(f"'on': {doc.get('on')}")
jobs = doc.get("jobs", {})
print(f"jobs: {list(jobs.keys())}")
for name, job in jobs.items():
    print(f"\n-- job {name}")
    print(f"   runs-on: {job.get('runs-on')}")
    if "services" in job:
        print(f"   services: {list(job['services'].keys())}")
    steps = job.get("steps", [])
    print(f"   steps: {len(steps)}")
    for s in steps:
        uses = s.get("uses")
        name_ = s.get("name")
        run = (s.get("run") or "").strip().splitlines()[:1]
        print(f"     - {name_ or uses} | run={run}")
