"""Push codebase + enable GitHub Pages. Token from scripts/.ghtoken.tmp."""
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

        # verify token
        verify = subprocess.run(
            [sys.executable, "-c", (
                "import os,httpx;"
                "h={'Authorization':'Bearer '+os.environ['GH_TOKEN'],"
                "'Accept':'application/vnd.github+json'};"
                "r=httpx.get('https://api.github.com/user',headers=h,timeout=60);"
                "print('auth ->',r.status_code,r.json().get('login'))"
            )],
            env=env, capture_output=True, text=True,
        )
        out.append(f"token check: {verify.stdout.strip()}")

        if "200" not in out[-1]:
            LOG.write_text("\n".join(out), encoding="utf-8")
            print("\n".join(out))
            print("Token rejected. Aborting.")
            return 2

        for script in ("push_to_github.py", "enable_pages.py"):
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script)],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
            )
            out.append(f"=== {script} rc={proc.returncode} ===\n{proc.stdout[-5000:]}\n{proc.stderr[-2000:]}")

        LOG.write_text("\n".join(out), encoding="utf-8")
        print("\n".join(out[-4000:]))
        return 0
    except Exception:
        LOG.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
