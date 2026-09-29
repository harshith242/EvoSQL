"""Set up v6 data: 4 BIRD dev SQLite databases, the Arcwise-Plat questions and corrected column descriptions,
and data/arcwise/manifest.json with the Arcwise commit and SHA-256 of every file used (the run's pinned inputs).
Usage: python scripts/get_v6_data.py"""
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

DBS = ["formula_1", "superhero", "card_games", "european_football_2"]
BIRD_URL = "https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip"
BIRD_PREFIX = "dev_20240627/"
REPO = "uiuc-kang-lab/text_to_sql_benchmarks"
QUESTIONS = "data/arcwise_plat_full_with_diff.json"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch_json(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def get_bird(out):
    """Extract only the chosen database folders from BIRD dev; other databases already on disk are left alone."""
    zips = out / "dev.zip", out / "dev_databases.zip"
    if all((out / db / f"{db}.sqlite").exists() for db in DBS):
        return
    if not zips[0].exists():
        print(f"downloading {BIRD_URL} (~346 MB)")
        urllib.request.urlretrieve(BIRD_URL, zips[0])
    with zipfile.ZipFile(zips[0]) as outer, outer.open(BIRD_PREFIX + "dev_databases.zip") as src, open(zips[1], "wb") as dst:
        shutil.copyfileobj(src, dst)
    with zipfile.ZipFile(zips[1]) as inner:
        for name in inner.namelist():
            db = name.removeprefix("dev_databases/").split("/")[0]
            if db in DBS and not name.endswith("/"):
                path = out / name.removeprefix("dev_databases/")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(inner.read(name))
    for z in zips:
        z.unlink()


def get_arcwise(out):
    """Questions and corrected descriptions at the repository's current commit, which becomes the pinned commit."""
    commit = fetch_json(f"https://api.github.com/repos/{REPO}/commits/main")["sha"]
    raw = f"https://raw.githubusercontent.com/{REPO}/{commit}/"
    tree = fetch_json(f"https://api.github.com/repos/{REPO}/git/trees/{commit}?recursive=1")["tree"]
    files = [QUESTIONS] + [t["path"] for t in tree if t["type"] == "blob" and t["path"].endswith(".csv")
                           and any(t["path"].startswith(f"data/schemas/{db}/database_description/") for db in DBS)]
    for f in files:
        path = out / f.removeprefix("data/")
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {raw}{f}")
        urllib.request.urlretrieve(raw + f, path)
    return commit, [out / f.removeprefix("data/") for f in files]


def main(bird=Path("data/bird_dev"), arcwise=Path("data/arcwise")):
    get_bird(bird)
    commit, files = get_arcwise(arcwise)
    questions = [q for q in json.loads((arcwise / Path(QUESTIONS).name).read_text()) if q["db_id"] in DBS]
    manifest = {
        "arcwise_repo": REPO, "arcwise_commit": commit, "bird_url": BIRD_URL, "databases": DBS,
        "questions_per_db": {db: sum(q["db_id"] == db for q in questions) for db in DBS},
        "sha256": {str(p): sha256(p) for p in files + [bird / db / f"{db}.sqlite" for db in DBS]},
    }
    (arcwise / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest["questions_per_db"]), f"pinned at {commit[:12]}")


if __name__ == "__main__":
    main()
