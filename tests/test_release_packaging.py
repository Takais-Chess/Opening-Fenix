import os
import zipfile
from pathlib import Path

import pytest

from scripts import build_installer, build_msix, sync_cloud_repertoires


def _make_zip(zip_path: Path, files: dict[str, bytes]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_name, content in files.items():
            zf.writestr(rel_name, content)


def test_sync_cloud_repertoires_merges_split_assets_and_cleans_legacy_dirs(tmp_path):
    cloud_dir = tmp_path / "cloud_repertoires"
    local_dir = tmp_path / "local_repertoires"
    cloud_dir.mkdir()
    local_dir.mkdir()

    # Legacy stray `.assets` directory created by earlier sync runs
    legacy_assets = local_dir / "Tarrasch Example Course.assets"
    legacy_assets.mkdir()
    (legacy_assets / "stale.txt").write_text("stale", encoding="utf-8")

    # Local-only repertoire should stay untouched
    local_only = local_dir / "My Local Repo"
    local_only.mkdir()
    (local_only / "My Local Repo.db").write_bytes(b"local-db")

    # Split cloud v2 archives: DB zip + companion `.assets.fenixsync.zip`
    _make_zip(
        cloud_dir / "Tarrasch Example Course.fenixsync.zip",
        {"Tarrasch Example Course.db": b"sqlite-bytes"},
    )
    _make_zip(
        cloud_dir / "Tarrasch Example Course.assets.fenixsync.zip",
        {
            "cover.jpg": b"jpg-bytes",
            "README.md": b"# Tarrasch",
            "Model Games.ini": b"[Init]",
            "Tactics/Tactics.pgn": b"1. e4 e5 *",
        },
    )

    rc = sync_cloud_repertoires.sync_cloud_repertoires(cloud_dir, local_dir)
    assert rc == 0

    merged_dir = local_dir / "Tarrasch Example Course"
    assert (merged_dir / "Tarrasch Example Course.db").read_bytes() == b"sqlite-bytes"
    assert (merged_dir / "cover.jpg").read_bytes() == b"jpg-bytes"
    assert (merged_dir / "README.md").read_bytes() == b"# Tarrasch"
    assert (merged_dir / "Model Games.ini").read_bytes() == b"[Init]"
    assert (merged_dir / "Tactics" / "Tactics.pgn").read_bytes() == b"1. e4 e5 *"

    assert not legacy_assets.exists()
    assert (local_only / "My Local Repo.db").read_bytes() == b"local-db"
    # Cloud source must never be modified
    assert sorted(p.name for p in cloud_dir.iterdir()) == [
        "Tarrasch Example Course.assets.fenixsync.zip",
        "Tarrasch Example Course.fenixsync.zip",
    ]


def test_prepare_clean_public_store_bundle_stages_example_from_project_root(tmp_path):
    project_root = tmp_path / "repo_root"
    src_repertoires = project_root / "repertoires"
    src_repertoires.mkdir(parents=True)
    (src_repertoires / ".gitkeep").write_text("", encoding="utf-8")

    # Example repertoire + stray .assets + personal repertoire in project_root/repertoires
    ex_dir = src_repertoires / "Tarrasch Example Course"
    ex_dir.mkdir()
    (ex_dir / "Tarrasch Example Course.db").write_bytes(b"ex-db")
    (ex_dir / "cover.jpg").write_bytes(b"ex-cover")
    (ex_dir / "temp.lock").write_text("ignore", encoding="utf-8")

    stray_assets = src_repertoires / "Tarrasch Example Course.assets"
    stray_assets.mkdir()
    (stray_assets / "cover.jpg").write_bytes(b"stray")

    personal_dir = src_repertoires / "My Secret Prep"
    personal_dir.mkdir()
    (personal_dir / "My Secret Prep.db").write_bytes(b"secret-db")

    # Simulate dist/Opening Fenix AFTER build_private() stripped example repertoires
    dist_dir = tmp_path / "dist" / "Opening Fenix"
    internal_dir = dist_dir / "_internal"
    (dist_dir / "repertoires").mkdir(parents=True)
    (internal_dir / "repertoires" / "My Secret Prep").mkdir(parents=True)
    (internal_dir / "repertoires" / "My Secret Prep" / "My Secret Prep.db").write_bytes(b"secret")
    (internal_dir / "profiles").mkdir(parents=True)
    (internal_dir / "engines").mkdir(parents=True)

    staged = tmp_path / "staging" / "app"
    build_msix.prepare_clean_public_store_bundle(
        str(dist_dir), str(staged), project_root=str(project_root)
    )

    assert (staged / "PUBLIC_VERSION").exists()
    assert (staged / "STORE_VERSION").exists()
    assert (staged / "_internal" / "PUBLIC_VERSION").exists()
    assert (staged / "_internal" / "STORE_VERSION").exists()
    assert not (staged / "_internal" / "profiles").exists()
    assert not (staged / "_internal" / "engines").exists()

    for repo_root in (staged / "repertoires", staged / "_internal" / "repertoires"):
        assert (repo_root / "Tarrasch Example Course" / "Tarrasch Example Course.db").read_bytes() == b"ex-db"
        assert (repo_root / "Tarrasch Example Course" / "cover.jpg").read_bytes() == b"ex-cover"
        assert not (repo_root / "Tarrasch Example Course" / "temp.lock").exists()
        assert not (repo_root / "My Secret Prep").exists()
        assert not (repo_root / "Tarrasch Example Course.assets").exists()


def test_prepare_clean_public_store_bundle_fails_without_example_db(tmp_path):
    project_root = tmp_path / "repo_root"
    (project_root / "repertoires" / "Personal Only").mkdir(parents=True)
    (project_root / "repertoires" / "Personal Only" / "Personal Only.db").write_bytes(b"x")

    dist_dir = tmp_path / "dist" / "Opening Fenix"
    (dist_dir / "_internal").mkdir(parents=True)

    staged = tmp_path / "staging" / "app"
    with pytest.raises(RuntimeError, match="No example/sample repertoire .db"):
        build_msix.prepare_clean_public_store_bundle(
            str(dist_dir), str(staged), project_root=str(project_root)
        )


def test_sync_example_repertoires_helper_for_public_installer(tmp_path):
    src_repertoires = tmp_path / "repertoires"
    (src_repertoires / "Sample Opening").mkdir(parents=True)
    (src_repertoires / "Sample Opening" / "Sample Opening.db").write_bytes(b"db")
    (src_repertoires / "Sample Opening.assets").mkdir(parents=True)
    (src_repertoires / "Private Prep").mkdir(parents=True)
    (src_repertoires / "Private Prep" / "Private Prep.db").write_bytes(b"priv")

    dist_dir = tmp_path / "dist"
    internal_dir = dist_dir / "_internal"
    internal_dir.mkdir(parents=True)

    assert build_installer._sync_example_repertoires(
        str(src_repertoires), [str(dist_dir), str(internal_dir)]
    ) is True

    assert (internal_dir / "repertoires" / "Sample Opening" / "Sample Opening.db").exists()
    assert not (internal_dir / "repertoires" / "Sample Opening.assets").exists()
    assert not (internal_dir / "repertoires" / "Private Prep").exists()
