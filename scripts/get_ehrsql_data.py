"""Set up the EHRSQL data: the MIMIC-IV demo database, validation questions and official post-processing, pinned in
data/ehrsql/manifest.json by commit and SHA-256, and the frozen 119-question stream (17 templates x 7 questions).
A rerun only verifies the hashes. Usage: python scripts/get_ehrsql_data.py"""
import hashlib
import json
import os
import random
import urllib.request
from collections import defaultdict
from pathlib import Path

from evosql.bird import execute
from evosql.ehrsql_postprocess import post_process_sql

REPO = "glee4810/ehrsql-2024"
COMMIT = "f9e1aa02160d39e3f8df52bf5c69c5cf2e472499"
DATA_DIR = Path("data/ehrsql")
FILES = {  # local path -> path in the repo
    DATA_DIR / "mimic_iv" / "mimic_iv.sqlite": "data/mimic_iv/mimic_iv.sqlite",
    DATA_DIR / "annotated.json": "data/mimic_iv/valid/annotated.json",
    DATA_DIR / "postprocessing.py": "scoring_program/postprocessing.py",
}
MANIFEST, STREAM = DATA_DIR / "manifest.json", DATA_DIR / "stream_v8.json"
TEMPLATES, PER_TEMPLATE, MAX_SECONDS = 17, 7, 5.0


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def download(url, path):
    """Download to <path>.part, then rename, so an interrupted download is never mistaken for a complete one."""
    part = path.with_name(path.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    urllib.request.urlretrieve(url, part)
    os.replace(part, path)


def build_stream():
    """The first 17 shuffled candidate templates, all 7 of their questions each, with post-processed gold SQL."""
    db = DATA_DIR / "mimic_iv" / "mimic_iv.sqlite"
    by_template = defaultdict(list)
    for item in json.loads((DATA_DIR / "annotated.json").read_text()):
        if item["query"] and item["query"] != "null":
            by_template[item["template"]].append(item)

    candidates = []
    for template, items in by_template.items():
        if len(items) != PER_TEMPLATE:
            continue
        results = [execute(db, post_process_sql(i["query"]), timeout=MAX_SECONDS) for i in items]
        if all(not error and rows not in ([], [(None,)]) for rows, error in results):
            candidates.append(template)

    candidates.sort()
    random.Random(0).shuffle(candidates)
    chosen = candidates[:TEMPLATES]
    print(f"{len(candidates)} candidate templates, chosen: {chosen}")

    stream = []
    for template in chosen:
        for item in by_template[template]:
            stream.append({"qid": len(stream) + 1, "id": item["id"], "db_id": "mimic_iv", "template": template,
                           "question": item["question"], "query": item["query"],
                           "gold_sql": post_process_sql(item["query"])})
    return stream


def main():
    for path, repo_path in FILES.items():
        if not path.exists():
            download(f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{repo_path}", path)

    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
        hashes = {**manifest["files"], manifest["stream"]["path"]: manifest["stream"]["sha256"]}
        changed = [p for p, h in hashes.items() if sha256(p) != h]
        if changed:
            raise SystemExit(f"files differ from the pinned manifest: {changed}")
        print(f"verified {len(hashes)} files against pinned commit {manifest['commit'][:12]}")
        return

    stream = build_stream()
    STREAM.write_text(json.dumps(stream, indent=1))
    manifest = {
        "repo": REPO, "commit": COMMIT, "files": {str(p): sha256(p) for p in FILES},
        "stream": {"path": str(STREAM), "sha256": sha256(STREAM), "templates": TEMPLATES, "questions": len(stream)},
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    print(f"pinned {len(stream)} questions at {COMMIT[:12]}")


if __name__ == "__main__":
    main()
