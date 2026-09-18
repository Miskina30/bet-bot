import os

from sqlalchemy import create_engine, text

db = "sqlite+pysqlite:///" + os.environ["TEMP"].replace("\\", "/") + "/ae_seed_test.db"
engine = create_engine(db)
conn = engine.connect()

print("TABLE ROW COUNTS:")
queries = [
    ("event", "select count(*) from event"),
    ("market", "select count(*) from market"),
    ("quote", "select count(*) from quote"),
    ("outcome", "select count(*) from outcome"),
    ("sport", "select count(*) from sport"),
    ("participant", "select count(*) from participant"),
]
for name, q in queries:
    print("  ", name, "=", conn.execute(text(q)).scalar_one())

print("SPORT ROWS:")
for row in conn.execute(text("select code, name from sport")):
    print("  ", row[0], "|", row[1])

print("SYNTHETIC CHECK (sample quotes):")
for row in conn.execute(text("select source_id, decimal_odds, is_synthetic from quote limit 4")):
    print("  ", row[0], row[1], "synthetic=", bool(row[2]))

print("VENUES:")
for row in conn.execute(text("select name from venue")):
    print("  ", row[0])

print("SAMPLE EVENT JOIN:")
row = conn.execute(
    text(
        "select e.id, c.name, h.name, a.name, v.name, e.start_time_utc, e.is_synthetic "
        "from event e join competition c on c.id=e.competition_id "
        "join participant h on h.id=e.home_participant_id "
        "join participant a on a.id=e.away_participant_id "
        "join venue v on v.id=e.venue_id limit 2"
    )
).fetchall()
for r in row:
    print("  ", r)
