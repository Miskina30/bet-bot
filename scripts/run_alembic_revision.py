import os
import sys
import traceback

repo = "C:/Users/Anania Light Laptop/projects/academic-edge"
os.chdir(repo)

from alembic.config import Config
from alembic import command

out = []

cfg = Config()
cfg.set_main_option("script_location", os.path.join(repo, "migrations"))
cfg.set_main_option("sqlalchemy.url", "sqlite+pysqlite:///./.data/academic_edge.db")
cfg.config_file_name = os.path.join(repo, "alembic.ini")

try:
    command.revision(cfg, autogenerate=True, message="initial canonical schema")
    out.append("REVISION OK")
except Exception:
    out.append("REVISION FAILED")
    out.append(traceback.format_exc())

try:
    import glob

    out.append("versions dir: " + str(glob.glob(os.path.join(repo, "migrations", "versions", "*"))))
except Exception:
    out.append(traceback.format_exc())

with open("C:/Temp/ae_alembic.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
