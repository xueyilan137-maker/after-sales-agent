"""Manual backup command. No fixture seeding, model calls or automatic restore."""

import tarfile
from pathlib import Path

from after_sales.store import backup_store, connect, state_dir


def main():
    # Serialize preference changes while collecting the business SQLite snapshot
    # and canonical DeerMem files. Backups remain in the private Docker volume.
    with connect(write=True):
        database = Path(backup_store())
        archive = database.with_suffix(".tar.gz")
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(database, arcname="business.sqlite3")
            memory = state_dir() / "customer-memory"
            if memory.exists():
                handle.add(memory, arcname="customer-memory")
        archive.chmod(0o600)
    print(f"Private backup saved: {archive}. Identity key, accounts, API keys and DeerFlow checkpoints were not exported.")


if __name__ == "__main__":
    main()
