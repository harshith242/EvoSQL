"""Set up the data: 4 BIRD dev SQLite databases, Arcwise-Plat questions and corrected column descriptions, pinned in
data/arcwise/manifest.json by commit and SHA-256. A rerun reuses the pinned commit and checks the hashes instead of
overwriting. Usage: python scripts/get_v6_data.py"""
import hashlib
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

DBS = ["formula_1", "superhero", "card_games", "european_football_2"]
BIRD_URL = "https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip"
BIRD_PREFIX = "dev_20240627/"
REPO = "uiuc-kang-lab/text_to_sql_benchmarks"
QUESTIONS = "data/arcwise_plat_full_with_diff.json"
BIRD_DIR, ARCWISE_DIR = Path("data/bird_dev"), Path("data/arcwise")
MANIFEST = ARCWISE_DIR / "manifest.json"


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def fetch_json(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def download(url, path):
    """Download to <path>.part, then rename, so an interrupted download is never mistaken for a complete one."""
    part = path.with_name(path.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    urllib.request.urlretrieve(url, part)
    os.replace(part, path)


def get_bird():
    """Extract only the chosen database folders from BIRD dev; other databases already on disk are left alone."""
    if all((BIRD_DIR / db / f"{db}.sqlite").exists() for db in DBS):
        return
    outer, inner = BIRD_DIR / "dev.zip", BIRD_DIR / "dev_databases.zip"
    if not outer.exists():
        download(BIRD_URL, outer)  # ~346 MB
    with zipfile.ZipFile(outer) as z, z.open(BIRD_PREFIX + "dev_databases.zip") as src, open(inner, "wb") as dst:
        shutil.copyfileobj(src, dst)

    with zipfile.ZipFile(inner) as z:
        for name in z.namelist():
            rel = name.removeprefix("dev_databases/")
            if rel.split("/")[0] in DBS and not name.endswith("/"):
                (BIRD_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, open(BIRD_DIR / rel, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    outer.unlink()
    inner.unlink()


def get_arcwise(commit):
    """Questions and corrected descriptions at the given commit; returns the local paths."""
    tree = fetch_json(f"https://api.github.com/repos/{REPO}/git/trees/{commit}?recursive=1")["tree"]
    prefixes = [f"data/schemas/{db}/database_description/" for db in DBS]
    csvs = [t["path"] for t in tree if t["type"] == "blob" and t["path"].endswith(".csv")]
    files = [QUESTIONS] + [p for p in csvs if p.startswith(tuple(prefixes))]
    paths = []
    for f in files:
        path = ARCWISE_DIR / f.removeprefix("data/")
        if not path.exists():
            download(f"https://raw.githubusercontent.com/{REPO}/{commit}/{f}", path)
        paths.append(path)
    return paths


def main():
    get_bird()
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
        get_arcwise(manifest["arcwise_commit"])
        changed = [p for p, h in manifest["sha256"].items() if sha256(p) != h]
        if changed:
            raise SystemExit(f"files differ from the pinned manifest: {changed}")
        print(f"verified {len(manifest['sha256'])} files against pinned commit {manifest['arcwise_commit'][:12]}")
        return

    commit = fetch_json(f"https://api.github.com/repos/{REPO}/commits/main")["sha"]
    paths = get_arcwise(commit) + [BIRD_DIR / db / f"{db}.sqlite" for db in DBS]
    questions = [q for q in json.loads((ARCWISE_DIR / Path(QUESTIONS).name).read_text()) if q["db_id"] in DBS]
    manifest = {
        "arcwise_repo": REPO, "arcwise_commit": commit, "bird_url": BIRD_URL, "databases": DBS,
        "questions_per_db": {db: sum(q["db_id"] == db for q in questions) for db in DBS},
        "sha256": {str(p): sha256(p) for p in paths},
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest["questions_per_db"]), f"pinned at {commit[:12]}")


if __name__ == "__main__":
    main()
