"""Corrected BIRD dev gold SQL from the annotation-error study (arXiv 2601.08778), SQL fixes only.
Official gold stays the primary score; corrected gold is the sensitivity score and flags known-wrong labels."""
import json
import os
import urllib.request
from dataclasses import replace
from pathlib import Path

from evosql.bird import gold_rows

URL = ("https://raw.githubusercontent.com/uiuc-kang-lab/text_to_sql_benchmarks/main/"
       "data/arcwise_plat_sql_only_with_diff.json")
FILE = Path("corrected/arcwise_plat_sql_only_with_diff.json")  # under data_dir


def download(data_dir):
    """Download the corrected labels once, after showing the URL and size and asking for confirmation."""
    path = Path(data_dir) / FILE
    if path.exists():
        print(f"already downloaded: {path}")
        return
    size = int(urllib.request.urlopen(urllib.request.Request(URL, method="HEAD")).headers["Content-Length"])
    if input(f"Download {URL} ({size / 1e3:.0f} KB) to {path}? [y/N] ").strip().lower() != "y":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(URL, f"{path}.tmp")
    os.replace(f"{path}.tmp", path)
    print(f"saved {path}")


def corrected(data_dir, db_id):
    """{qid: corrected gold SQL} for one database."""
    path = Path(data_dir) / FILE
    if not path.exists():
        raise SystemExit(f"{path} is missing: run `python -m evosql labels` first")
    fixes = {int(x["question_id"]): x["SQL"] for x in json.loads(path.read_text()) if x["db_id"] == db_id}
    if not fixes:
        raise SystemExit(f"{path} has no labels for {db_id}: check its format")
    return fixes


def corrected_gold(db, q, fixes):
    """Result rows of the corrected gold SQL, or the official gold rows when the study has no fix for q."""
    if q.qid not in fixes:
        return gold_rows(db.path, q)
    return gold_rows(db.path, replace(q, gold_sql=fixes[q.qid]), cache_dir="cache/gold_corrected")


def known_wrong(db, q, fixes):
    """True when the corrected gold returns different results from the official gold."""
    return set(corrected_gold(db, q, fixes)) != set(gold_rows(db.path, q))
