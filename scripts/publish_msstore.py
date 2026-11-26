"""
Publish the unsigned Microsoft Store MSIX package ("Opening Fenix Chess") via the
Microsoft Store Developer CLI (`msstore`).

Exit codes:
    0 : Uploaded/published successfully via `msstore` CLI.
    1 : MSIX artifact missing/invalid, or `msstore publish` failed.
    2 : `msstore` CLI is not installed or not configured yet (non-fatal; manual upload required).
"""
import json
import os
import shutil
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_STORE_ID = "9MVN5X4QZ1KL"
MIN_MSIX_BYTES = 10 * 1024 * 1024  # 10 MB


def load_store_id(project_root: str) -> str:
    config_path = os.path.join(project_root, "installer", "msix_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            store_id = str(cfg.get("store_id", "")).strip()
            if store_id:
                return store_id
        except Exception as e:
            print(f"Warning: could not read store_id from {config_path}: {e}")
    return DEFAULT_STORE_ID


def print_manual_upload_notice(msix_path: str, store_id: str, reason: str) -> None:
    partner_url = f"https://partner.microsoft.com/en-us/dashboard/products/{store_id}/overview"
    print("\n" + "=" * 64)
    print("  Microsoft Store Upload — Manual Step Required")
    print("=" * 64)
    print(f"Reason: {reason}")
    print("\nTo enable automated uploads after your first Store submission is live:")
    print("  1. Install the CLI:   winget install Microsoft.StoreDeveloperCLI")
    print("  2. Authenticate once: msstore reconfigure")
    print("\nFor now, upload this unsigned MSIX package manually in Partner Center:")
    print(f"  Package:        {msix_path}")
    print(f"  Partner Center: {partner_url}")
    print("=" * 64)


def main() -> int:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from opening_fenix.core.version import APP_VERSION

    store_id = load_store_id(project_root)
    msix_path = os.path.join(project_root, "Output", f"OpeningFenixChess_v{APP_VERSION}_Store.msix")

    if not os.path.isfile(msix_path) or os.path.getsize(msix_path) <= MIN_MSIX_BYTES:
        size_info = f"{os.path.getsize(msix_path)} bytes" if os.path.exists(msix_path) else "not found"
        print(f"Error: Expected valid Store MSIX (>10 MB) at '{msix_path}' ({size_info}).", file=sys.stderr)
        return 1

    msstore = shutil.which("msstore")
    if not msstore:
        print_manual_upload_notice(
            msix_path,
            store_id,
            "`msstore` (Microsoft Store Developer CLI) is not installed.",
        )
        return 2

    # Check if msstore CLI is authenticated/configured
    try:
        info_res = subprocess.run(
            [msstore, "info"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if info_res.returncode != 0:
            detail = (info_res.stderr or info_res.stdout or "").strip()
            reason = "`msstore` CLI is not configured/authenticated yet."
            if detail:
                reason = f"{reason} ({detail.splitlines()[0]})"
            print_manual_upload_notice(msix_path, store_id, reason)
            return 2
    except Exception as e:
        print_manual_upload_notice(msix_path, store_id, f"Could not verify `msstore` CLI configuration: {e}")
        return 2

    cmd = [msstore, "publish", ".", "--inputFile", msix_path, "--appId", store_id]
    for arg in sys.argv[1:]:
        if arg in ("--noCommit", "-nc"):
            cmd.append(arg)

    print(f"Publishing {os.path.basename(msix_path)} to Microsoft Store (App ID: {store_id})...")
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print(" -> Successfully submitted package to Microsoft Store!")
    else:
        print(f"Error: `msstore publish` exited with code {res.returncode}.", file=sys.stderr)
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
