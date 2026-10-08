"""Reset/seed ONLY the guided replay in the recording database, never uploads."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.storage import SQLiteStorage
from backend.replay import start_replay, advance_replay

parser = argparse.ArgumentParser()
parser.add_argument("--stage", type=int, choices=range(5), default=0)
args = parser.parse_args()
with SQLiteStorage(ROOT / "data" / "recording.sqlite3").transaction() as tx:
    tx.reset_replay()
    result = start_replay(tx)
    for stage in range(args.stage):
        result = advance_replay(tx, stage)
print(f"Recording replay seeded to stage {args.stage + 1}: {result['replay']['label']}. Uploads unchanged.")
