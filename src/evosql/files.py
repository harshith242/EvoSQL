"""Small file helpers shared by caches, logs and saved knowledge: atomic writes and JSONL logs."""
import json
import os
from pathlib import Path


def write_atomic(path, text):
    """Write via a temp file and rename, so a kill never leaves a truncated file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def read_jsonl(path):
    """Records of a JSONL log; a torn last line (killed mid-write) is ignored."""
    records = []
    for line in Path(path).read_text().splitlines() if Path(path).exists() else []:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


def append_jsonl(path, record):
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
