import sqlite3
import pytest

from opening_fenix.core.db.database import (
    DatabaseCorruptedException,
    DatabaseManager,
    _is_orphaned_pages_only,
    _verified_db_keys,
)


def test_is_orphaned_pages_only():
    orphaned_msg = "*** in database main ***\nPage 300: never used\nPage 301: never used"
    assert _is_orphaned_pages_only(orphaned_msg) is True
    assert _is_orphaned_pages_only("Page 5: never used") is True
    assert _is_orphaned_pages_only("ok") is False
    assert _is_orphaned_pages_only("") is False
    assert _is_orphaned_pages_only("*** in database main ***\nPage 300: never used\nOn tree page 12 cell 0: Rowid 5 out of order") is False


def test_database_manager_auto_repairs_orphaned_pages(tmp_path):
    db_path = tmp_path / "orphaned.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO t (val) VALUES ('hello')")
    conn.commit()
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.close()

    # Append an unreferenced page and bump the SQLite header page_count (bytes 28..32)
    # so PRAGMA quick_check reports "Page N: never used".
    data = bytearray(db_path.read_bytes())
    old_count = int.from_bytes(data[28:32], "big")
    data[28:32] = (old_count + 1).to_bytes(4, "big")
    data.extend(b"\x00" * page_size)
    db_path.write_bytes(bytes(data))

    check_conn = sqlite3.connect(db_path)
    pre_check = check_conn.execute("PRAGMA quick_check").fetchone()[0]
    check_conn.close()
    assert "never used" in pre_check

    _verified_db_keys.clear()
    dm = DatabaseManager(str(db_path))
    try:
        verify_conn = sqlite3.connect(db_path)
        post_check = verify_conn.execute("PRAGMA integrity_check").fetchone()[0]
        row = verify_conn.execute("SELECT val FROM t WHERE id = 1").fetchone()
        verify_conn.close()
        assert post_check == "ok"
        assert row == ("hello",)
    finally:
        dm.close()


def test_database_manager_raises_on_real_corruption(tmp_path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a valid sqlite database" * 100)

    _verified_db_keys.clear()
    with pytest.raises(DatabaseCorruptedException):
        DatabaseManager(str(db_path))
