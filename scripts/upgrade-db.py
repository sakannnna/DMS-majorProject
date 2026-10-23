"""Explicit, resumable stage-two part-one upgrade. Stop the app before running."""
import argparse
import hashlib
import re
import sys
from pathlib import Path

from bson import BSON, decode_file_iter, json_util

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import connect, preflight, upgrade


def backup_database(db, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"database": db.name, "collections": {}}
    for number, name in enumerate(sorted(db.list_collection_names())):
        path = directory / f"{number:04d}.bson"
        with path.open("wb") as handle:
            for document in db[name].find({}):
                handle.write(BSON.encode(document))
        manifest["collections"][name] = {"file": path.name, "options": db[name].options(), "indexes": list(db[name].list_indexes()),
                                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (directory / "manifest.json").write_text(json_util.dumps(manifest, indent=2), encoding="utf-8")
    return directory


def restore_database(db, directory):
    """Restore into an empty alternate database; never drop the source or destination."""
    directory = Path(directory).resolve()
    manifest = json_util.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if db.list_collection_names():
        raise RuntimeError("Restore destination must be empty; no data was deleted")
    paths = {}
    for name, entry in manifest["collections"].items():
        path = (directory / entry["file"]).resolve()
        if path.parent != directory or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("Invalid backup file/hash; nothing restored")
        paths[name] = path
    for name, entry in manifest["collections"].items():
        options = {k: v for k, v in entry["options"].items() if k in ("validator", "validationLevel", "validationAction", "collation")}
        db.create_collection(name, **options)
        with paths[name].open("rb") as handle:
            for document in decode_file_iter(handle):
                db[name].insert_one(document)
        for index in entry["indexes"]:
            if index["name"] != "_id_":
                db[name].create_index(list(index["key"].items()), **{k: v for k, v in index.items() if k not in ("key", "v", "ns")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", required=True, help="New directory for BSON and metadata backup")
    parser.add_argument("--restore-into", help="Restore this backup to a NEW empty alternate DB instead of upgrading")
    parser.add_argument("--app-stopped", action="store_true", help="Confirm all app/DB writers have been stopped")
    args = parser.parse_args()
    if not args.app_stopped:
        parser.error("Stop the app and other writers, then provide --app-stopped")
    client, db = connect()
    try:
        if args.restore_into:
            if not re.fullmatch(r"[A-Za-z0-9_]+", args.restore_into):
                parser.error("Invalid restore database name")
            restore_database(client[args.restore_into], args.backup_dir)
            print(f"Restored into {args.restore_into}; original DB unchanged")
            return
        preflight(db, upgrading=True)
        destination = backup_database(db, args.backup_dir)
        print(f"Backup complete: {destination}", flush=True)
        upgrade(db)
        print(f"Upgrade complete: {db.name}; old business documents unchanged")
    finally:
        client.close()


if __name__ == "__main__":
    main()
