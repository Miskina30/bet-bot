import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = Path(__file__).resolve().parent / ".ghtoken.tmp"
LOG = ROOT / "deploy_pages_debug.log"


def main() -> int:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        env = dict(os.environ)
        env["GH_TOKEN"] = token
        out: list[str] = []

        def run(script: str) -> int:
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script)],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
            )
            out.append(f"=== {script} rc={proc.returncode} ===\n{proc.stdout[-5000:]}\n{proc.stderr[-2000:]}")
            return proc.returncode

        # 1. make the repo public so Pages can serve it
        rc = subprocess.run(
            [sys.executable, "-c", (
                "import httpx,sys;"
                "h={'Authorization':'Bearer '+os.environ['GH_TOKEN'],"
                "'Accept':'application/vnd.github+json'};"
                "r=httpx.patch('https://api.github.com/repos/Miskina30/bet-bot',"
                "headers=h,json={'private':False,'description':'Academic Edge: read-only football market-intelligence MVP. Research only, no wagering. No secrets in the codebase.'},timeout=60);"
                "print('repo patch ->',r.status_code,'private=',r.json().get('private'))"
            )],
            env=env, capture_output=True, text=True,
        )
        out.append(f"=== repo visibility rc={rc} ===\n{rc.stdout[-2000:]}\n{rc.stderr[-1000:]}")

        rc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "push_to_github.py")],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
        )
        out.append(f"=== push_to_github.py rc={rc.returncode} ===\n{rc.stdout[-4000:]}\n{rc.stderr[-2000:]}")

        rc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "enable_pages.py")],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
        )
        out.append(f"=== enable_pages.py rc={rc.returncode} ===\n{rc.stdout[-2000:]}\n{rc.stderr[-1000:]}")

        LOG.write_text("\n".join(out), encoding="utf-8")
        print("\n".join(out[-4000:]))
        return 0
    except Exception:
        LOG.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
