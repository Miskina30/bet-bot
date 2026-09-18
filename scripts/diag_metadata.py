import os
import sys
import traceback

repo = "C:/Users/Anania Light Laptop/projects/academic-edge"
sys.path.insert(0, repo)
for p in [
    "apps/worker",
    "apps/api",
    "packages/domain",
    "packages/connectors",
    "packages/resolver",
    "packages/pricing",
    "packages/features",
    "packages/forecasting",
]:
    full = os.path.join(repo, p)
    if full not in sys.path:
        sys.path.insert(0, full)

out = []
out.append("cwd=" + os.getcwd())
try:
    import academic_edge_domain.models as m  # noqa: F401
    from academic_edge_domain.db import Base

    out.append("import OK")
    out.append("tables=" + str(len(Base.metadata.tables)))
    out.append("sorted=" + ",".join(sorted(Base.metadata.tables)))
except Exception:
    out.append("IMPORT FAILED")
    out.append(traceback.format_exc())

with open("C:/Temp/ae_diag.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
