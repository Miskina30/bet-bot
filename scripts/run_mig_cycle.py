import os
import sys
import traceback

repo = "C:/Users/Anania Light Laptop/projects/academic-edge"
os.chdir(repo)
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

from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, inspect

out = []
tmpdb = "C:/Temp/ae_mig_test.db"
try:
    os.remove(tmpdb)
except OSError:
    pass

url = "sqlite+pysqlite:///" + tmpdb

cfg = Config()
cfg.set_main_option("script_location", os.path.join(repo, "migrations"))
cfg.set_main_option("sqlalchemy.url", url)
cfg.config_file_name = os.path.join(repo, "alembic.ini")

try:
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    tables = sorted(inspect(eng).get_table_names())
    out.append(f"UPGRADE OK: {len(tables)} tables")
    out.append("tables=" + ",".join(tables))
    command.downgrade(cfg, "base")
    eng2 = create_engine(url)
    tables2 = sorted(inspect(eng2).get_table_names())
    # alembic_version remains by design; user tables must be gone
    user_tables = [t for t in tables2 if t != "alembic_version"]
    out.append(f"DOWNGRADE OK: {len(user_tables)} user tables remain")
    command.upgrade(cfg, "head")
    eng3 = create_engine(url)
    tables3 = sorted(inspect(eng3).get_table_names())
    out.append(f"RE-UPGRADE OK: {len(tables3)} tables")
except Exception:
    out.append("MIGRATION CYCLE FAILED")
    out.append(traceback.format_exc())

with open("C:/Temp/ae_mig_cycle.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
