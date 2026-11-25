"""One-way, strictly read-only sync of repertoires from the Google Drive cloud_sync folder
into the local workspace `repertoires/` directory.

Behavior:
- Reads `*.fenixsync.zip` archives from the cloud `cloud_sync/repertoires` directory
  in read-only mode (`'r'`). NEVER writes, modifies, renames, or deletes anything inside
  the cloud folder.
- For each cloud repertoire:
  - If it does not exist locally -> extracts it into `repertoires/<Name>/`.
  - If it already exists locally -> atomically replaces `repertoires/<Name>/` with the
    fresh cloud version (extracts to a temp folder first, then swaps).
- Local-only repertoires (folders not present in `cloud_sync/repertoires`) are left
  completely untouched.

Exit codes:
- 0: Sync completed successfully.
- 2: Warning (cloud folder missing/offline, empty, or one or more archives failed).
     Callers like `/release-version` should continue the release using local repertoires
     and alert the user in the final summary.
- 1: Safety guard triggered (e.g. target overlaps source).
"""

import argparse
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_CLOUD_SOURCE = (
    r"C:\Users\Felix\Meine Ablage (felix.brunner12@gmail.com)"
    r"\Schach\Programme\Opening Fenix\cloud_sync\repertoires"
)
ARCHIVE_SUFFIX = ".fenixsync.zip"


def _safe_rmtree(path: Path) -> None:
    """Remove a directory tree, clearing read-only flags on Windows if needed."""
    if not path.exists():
        return

    def _on_readonly(func, p, _excinfo):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_on_readonly)
    else:
        shutil.rmtree(path, onerror=_on_readonly)


def _assert_disjoint_paths(source: Path, target: Path) -> None:
    """Hard safety guard: refuse if target is the same as or overlaps the cloud source."""
    src_resolved = source.resolve()
    dst_resolved = target.resolve()

    if src_resolved == dst_resolved:
        raise ValueError(f"SAFETY ABORT: target equals cloud source ({src_resolved})")

    try:
        dst_resolved.relative_to(src_resolved)
        raise ValueError(
            f"SAFETY ABORT: target ({dst_resolved}) is inside cloud source ({src_resolved})"
        )
    except ValueError as exc:
        if "SAFETY ABORT" in str(exc):
            raise

    try:
        src_resolved.relative_to(dst_resolved)
        raise ValueError(
            f"SAFETY ABORT: cloud source ({src_resolved}) is inside target ({dst_resolved})"
        )
    except ValueError as exc:
        if "SAFETY ABORT" in str(exc):
            raise


def _extract_zip_safely(zip_path: Path, dest_dir: Path) -> None:
    """Extract a zip archive in read-only mode with Zip-Slip path validation."""
    dest_resolved = dest_dir.resolve()
    with zipfile.ZipFile(zip_path, mode="r") as zf:
        for member in zf.infolist():
            member_path = (dest_resolved / member.filename).resolve()
            try:
                member_path.relative_to(dest_resolved)
            except ValueError as exc:
                raise ValueError(
                    f"Unsafe zip entry '{member.filename}' in '{zip_path.name}'"
                ) from exc
        zf.extractall(dest_resolved)


def _sync_single_archive(
    zip_path: Path, target_dir: Path, dry_run: bool = False
) -> str:
    """Sync one `<Name>.fenixsync.zip` into `target_dir/<Name>`.

    Returns 'added' or 'updated'.
    """
    filename = zip_path.name
    if not filename.lower().endswith(ARCHIVE_SUFFIX):
        raise ValueError(f"Unexpected archive name: {filename}")

    repo_name = filename[: -len(ARCHIVE_SUFFIX)].strip()
    if not repo_name or repo_name in (".", "..") or any(sep in repo_name for sep in ("/", "\\")):
        raise ValueError(f"Invalid repertoire name derived from '{filename}'")

    dest_repo_dir = target_dir / repo_name
    existed = dest_repo_dir.exists()
    action = "updated" if existed else "added"

    if dry_run:
        return action

    staging_dir = Path(tempfile.mkdtemp(prefix=".fenix_sync_stage_", dir=str(target_dir)))
    backup_dir: Path | None = None
    try:
        _extract_zip_safely(zip_path, staging_dir)

        if existed:
            backup_dir = Path(
                tempfile.mkdtemp(prefix=".fenix_sync_old_", dir=str(target_dir))
            )
            # Remove the empty temp dir so rename can use that exact path
            backup_dir.rmdir()
            os.replace(dest_repo_dir, backup_dir)

        try:
            os.replace(staging_dir, dest_repo_dir)
        except Exception:
            # Roll back previous local repertoire if swap fails
            if backup_dir is not None and backup_dir.exists() and not dest_repo_dir.exists():
                os.replace(backup_dir, dest_repo_dir)
            raise

        if backup_dir is not None and backup_dir.exists():
            _safe_rmtree(backup_dir)
    finally:
        if staging_dir.exists():
            _safe_rmtree(staging_dir)

    return action


def sync_cloud_repertoires(
    source_dir: Path, target_dir: Path, dry_run: bool = False
) -> int:
    """Run one-way additive sync from `source_dir` (read-only) into `target_dir`."""
    print("=" * 60)
    print("  Opening Fenix - Cloud Repertoires One-Way Sync (Read-Only)")
    print("=" * 60)
    print(f"  Cloud source (read-only): {source_dir}")
    print(f"  Local target:             {target_dir}")
    if dry_run:
        print("  Mode:                     DRY RUN (no files will be modified)")

    try:
        _assert_disjoint_paths(source_dir, target_dir)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    if not source_dir.exists() or not source_dir.is_dir():
        print(
            "[CLOUD_SYNC_WARNING] Cloud sync directory is not accessible or does not exist. "
            "Skipping cloud repertoire sync and keeping existing local repertoires."
        )
        return 2

    archives = sorted(
        p
        for p in source_dir.iterdir()
        if p.is_file() and p.name.lower().endswith(ARCHIVE_SUFFIX)
    )
    if not archives:
        print(
            "[CLOUD_SYNC_WARNING] No '*.fenixsync.zip' archives found in cloud sync directory. "
            "Skipping cloud repertoire sync and keeping existing local repertoires."
        )
        return 2

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    added: list[str] = []
    updated: list[str] = []
    failed: list[tuple[str, str]] = []

    for zip_path in archives:
        repo_name = zip_path.name[: -len(ARCHIVE_SUFFIX)]
        try:
            action = _sync_single_archive(zip_path, target_dir, dry_run=dry_run)
            if action == "added":
                added.append(repo_name)
                print(f"  [+ ADDED]   {repo_name}")
            else:
                updated.append(repo_name)
                print(f"  [~ UPDATED] {repo_name}")
        except Exception as exc:
            failed.append((repo_name, str(exc)))
            print(f"  [! FAILED]  {repo_name}: {exc}")

    print("-" * 60)
    print(
        f"  Summary: {len(added)} added, {len(updated)} updated, "
        f"{len(failed)} failed (local-only repertoires untouched)."
    )

    if failed:
        print(
            "[CLOUD_SYNC_WARNING] One or more cloud repertoires failed to sync. "
            "Please review the warnings above."
        )
        return 2

    return 0


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    default_source = os.environ.get("FENIX_CLOUD_REPERTOIRES_DIR", DEFAULT_CLOUD_SOURCE)
    default_target = project_root / "repertoires"

    parser = argparse.ArgumentParser(
        description="One-way read-only sync of *.fenixsync.zip repertoires from Cloud to local."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(default_source),
        help="Read-only cloud_sync/repertoires directory.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=default_target,
        help="Local repertoires directory (default: <project_root>/repertoires).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be added/updated without modifying any files.",
    )
    args = parser.parse_args()
    return sync_cloud_repertoires(args.source, args.target, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
