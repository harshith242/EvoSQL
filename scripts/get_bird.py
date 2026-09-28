"""Download BIRD dev once, keep only one database (+ its questions), delete everything else.
Usage: python scripts/get_bird.py [db_id]   (default: thrombosis_prediction)"""
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip"
PREFIX = "dev_20240627/"


def main(db_id, out_dir=Path("data/bird_dev")):
    out_dir.mkdir(parents=True, exist_ok=True)
    outer_zip, inner_zip = out_dir / "dev.zip", out_dir / "dev_databases.zip"
    if not outer_zip.exists():
        print(f"downloading {URL} (~346 MB)")
        urllib.request.urlretrieve(URL, outer_zip)

    with zipfile.ZipFile(outer_zip) as outer:
        dev = [q for q in json.loads(outer.read(PREFIX + "dev.json")) if q["db_id"] == db_id]
        tables = [t for t in json.loads(outer.read(PREFIX + "dev_tables.json")) if t["db_id"] == db_id]
        with outer.open(PREFIX + "dev_databases.zip") as src, open(inner_zip, "wb") as dst:
            shutil.copyfileobj(src, dst)
    (out_dir / "dev.json").write_text(json.dumps(dev, indent=1))
    (out_dir / "dev_tables.json").write_text(json.dumps(tables, indent=1))

    # Extract only the chosen database folder.
    with zipfile.ZipFile(inner_zip) as inner:
        prefix = f"dev_databases/{db_id}/"
        for name in inner.namelist():
            if name.startswith(prefix) and not name.endswith("/"):
                path = out_dir / name.removeprefix("dev_databases/")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(inner.read(name))

    outer_zip.unlink()
    inner_zip.unlink()
    print(f"kept {db_id}: {len(dev)} questions -> {out_dir / db_id}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "thrombosis_prediction")
