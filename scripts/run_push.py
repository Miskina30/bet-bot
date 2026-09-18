import os
import subprocess
import sys
import traceback
from pathlib import Path

TOKEN_FILE = Path(__file__).resolve().parent / ".ghtoken.tmp"
LOG_FILE = Path(__file__).resolve().parent.parent / "run_push_debug.log"


def main() -> int:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        env = dict(os.environ)
        env["GH_TOKEN"] = token
        root = Path(__file__).resolve().parent.parent
        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "push_to_github.py")],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )
        LOG_FILE.write_text(
            f"returncode={proc.returncode}\n---STDOUT---\n{proc.stdout[-8000:]}"
            f"\n---STDERR---\n{proc.stderr[-4000:]}",
            encoding="utf-8",
        )
        print(f"returncode={proc.returncode}")
        print("---STDOUT TAIL---")
        print(proc.stdout[-3000:])
        print("---STDERR TAIL---")
        print(proc.stderr[-2000:])
        return 0
    except Exception:
        LOG_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
