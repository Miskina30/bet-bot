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
        for script in ("push_to_github.py", "enable_pages.py"):
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script)],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
            )
            out.append(f"=== {script} rc={proc.returncode} ===\n{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}")
        LOG.write_text("\n".join(out), encoding="utf-8")
        print("\n".join(out))
        return 0
    except Exception:
        LOG.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
