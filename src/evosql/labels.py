"""Corrected gold SQL: the annotation-error study's fixes (arXiv 2601.08778), overlaid with this repo's reviewed fixes
(labels/evosql_fixes.json, each with a reason). Official gold stays the primary score; corrected gold is the
sensitivity score and flags known-wrong labels."""
import hashlib
import json
import os
import urllib.request
from dataclasses import replace
from pathlib import Path

from evosql.bird import gold_rows

URL = ("https://raw.githubusercontent.com/uiuc-kang-lab/text_to_sql_benchmarks/main/"
       "data/arcwise_plat_sql_only_with_diff.json")
FILE = Path("corrected/arcwise_plat_sql_only_with_diff.json")  # under data_dir
OUR_FIXES = Path(__file__).parents[2] / "labels" / "evosql_fixes.json"


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
    """{qid: corrected gold SQL} for one database; our reviewed fixes override the study's."""
    path = Path(data_dir) / FILE
    if not path.exists():
        raise SystemExit(f"{path} is missing: run `python -m evosql labels` first")
    fixes = {int(x["question_id"]): x["SQL"] for x in json.loads(path.read_text()) if x["db_id"] == db_id}
    if not fixes:
        raise SystemExit(f"{path} has no labels for {db_id}: check its format")
    ours = json.loads(OUR_FIXES.read_text()) if OUR_FIXES.exists() else []
    return fixes | {int(x["question_id"]): x["SQL"] for x in ours if x["db_id"] == db_id}


def corrected_gold(db, q, fixes):
    """Result rows of the corrected gold SQL, or the official gold rows when there is no fix for q."""
    if q.qid not in fixes:
        return gold_rows(db.path, q)
    key = hashlib.sha256(fixes[q.qid].encode()).hexdigest()[:12]  # an edited fix never reuses stale cached rows
    return gold_rows(db.path, replace(q, gold_sql=fixes[q.qid]), cache_dir=f"cache/gold_corrected/{key}")


def known_wrong(db, q, fixes):
    """True when the corrected gold returns different results from the official gold."""
    return set(corrected_gold(db, q, fixes)) != set(gold_rows(db.path, q))
