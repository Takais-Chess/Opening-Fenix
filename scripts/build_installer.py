import os
import sys
import shutil
import subprocess
import PyInstaller.__main__


def _sync_engines(dist_dir):
    if os.path.exists('engines'):
        dst = os.path.join(dist_dir, 'engines')
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree('engines', dst)
        print(f" -> Synced engines to {dst}")


def build_private(dist_dir, iscc_exe, iss_file, app_version):
    """Compile the PRIVATE installer (all profiles & repertoires included)."""
    print("\n3a. Compiling PRIVATE Installer (with profiles & all repertoires)...")

    pub_marker = os.path.join(dist_dir, 'PUBLIC_VERSION')
    if os.path.exists(pub_marker):
        os.remove(pub_marker)

    for folder in ['profiles', 'repertoires']:
        if os.path.exists(folder):
            dst = os.path.join(dist_dir, folder)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(folder, dst)
            print(f" -> Synced {folder} to {dst}")

    res = subprocess.run(
        [iscc_exe, f'/DMyAppVersion={app_version}', '/DAppBuildType=Private', iss_file],
        capture_output=False
    )
    if res.returncode != 0:
        print("ERROR: Private Inno Setup compilation failed.")
        sys.exit(res.returncode)


def build_public(dist_dir, iscc_exe, iss_file, app_version):
    """Compile the PUBLIC installer (example repertoires only, no personal data)."""
    print("\n3b. Compiling PUBLIC Installer (clean build with example repertoires only)...")

    # Place the PUBLIC_VERSION marker so the app knows it's a public build
    pub_marker = os.path.join(dist_dir, 'PUBLIC_VERSION')
    with open(pub_marker, 'w', encoding='utf-8') as f:
        f.write('1')

    # Remove all profiles from the bundle
    for root_dir_path, dirs, _ in os.walk(dist_dir, topdown=False):
        for d in dirs:
            if d.lower() == 'profiles':
                p_dir = os.path.join(root_dir_path, d)
                shutil.rmtree(p_dir, ignore_errors=True)
                print(f" -> Removed profile directory '{p_dir}' from public bundle")

    # Sync repertoires, keeping ONLY example/sample folders
    if os.path.exists('repertoires'):
        dst_repos = os.path.join(dist_dir, 'repertoires')
        if os.path.exists(dst_repos):
            shutil.rmtree(dst_repos)
        shutil.copytree('repertoires', dst_repos)
        for item in os.listdir(dst_repos):
            item_path = os.path.join(dst_repos, item)
            item_lower = item.lower()
            if os.path.isdir(item_path) and not ("example" in item_lower or "sample" in item_lower):
                shutil.rmtree(item_path, ignore_errors=True)
                print(f" -> Removed non-example repertoire '{item}' from public bundle")
        print(" -> Synced example repertoires to public bundle")

    res = subprocess.run(
        [iscc_exe, f'/DMyAppVersion={app_version}', '/DAppBuildType=Public', iss_file],
        capture_output=False
    )
    if res.returncode != 0:
        print("ERROR: Public Inno Setup compilation failed.")
        sys.exit(res.returncode)


def main():
    print("=" * 50)
    print("      Opening Fenix - Installer Build Script")
    print("=" * 50)
    print("Usage: python scripts/build_installer.py [--public-only | --private-only]")
    print("       No flag = build both installers (default)")

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from opening_fenix.core.version import APP_VERSION

    # Parse CLI flags
    args = sys.argv[1:]
    do_private = "--public-only" not in args
    do_public  = "--private-only" not in args

    if not do_private and not do_public:
        print("ERROR: Cannot combine --public-only and --private-only.")
        sys.exit(1)

    # --------------------------------------------------------
    # Step 1: PyInstaller bundle (always needed)
    # --------------------------------------------------------
    dist_dir = os.path.join(project_root, 'dist', 'Opening Fenix')
    if os.path.exists(dist_dir):
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'stockfish-windows-x86-64-avx2.exe'], capture_output=True)
            subprocess.run(['taskkill', '/F', '/IM', 'Opening Fenix.exe'], capture_output=True)
            import time
            time.sleep(0.5)
            shutil.rmtree(dist_dir, ignore_errors=True)
        except Exception:
            pass

    print("\n1. Building PyInstaller Application Bundle...")
    PyInstaller.__main__.run(['--noconfirm', 'Opening Fenix.spec'])

    dist_dir = os.path.join(project_root, 'dist', 'Opening Fenix')
    if not os.path.exists(dist_dir):
        print("ERROR: PyInstaller build failed! dist/Opening Fenix directory not found.")
        sys.exit(1)
    print(" -> PyInstaller base bundle ready.")

    # --------------------------------------------------------
    # Step 2: Sync engines
    # --------------------------------------------------------
    _sync_engines(dist_dir)

    # --------------------------------------------------------
    # Step 3: Locate Inno Setup Compiler
    # --------------------------------------------------------
    print("\n2. Locating Inno Setup Compiler (ISCC.exe)...")
    iscc_paths = [
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe",
    ]
    iscc_exe = next((p for p in iscc_paths if p and os.path.exists(p)), None)
    iss_file = os.path.join(project_root, 'installer', 'OpeningFenix_Setup.iss')

    if not iscc_exe:
        print("\n[NOTE] Inno Setup Compiler (ISCC.exe) was not found on your system PATH.")
        print(f"The installer script is at: {iss_file}")
        sys.exit(1)
    print(f" -> Found Inno Setup Compiler: {iscc_exe}")

    # --------------------------------------------------------
    # Step 4: Build selected installer(s)
    # --------------------------------------------------------
    if do_private:
        build_private(dist_dir, iscc_exe, iss_file, APP_VERSION)

    if do_public:
        build_public(dist_dir, iscc_exe, iss_file, APP_VERSION)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------
    print("\n" + "=" * 50)
    if do_private and do_public:
        print("         BOTH INSTALLERS BUILT SUCCESSFULLY!")
        print("=" * 50)
        print(f"1. Private Installer: Output\\OpeningFenix_Setup_v{APP_VERSION}_Private.exe")
        print(f"2. Public Installer:  Output\\OpeningFenix_Setup_v{APP_VERSION}_Public.exe")
    elif do_public:
        print("         PUBLIC INSTALLER BUILT SUCCESSFULLY!")
        print("=" * 50)
        print(f"   Public Installer:  Output\\OpeningFenix_Setup_v{APP_VERSION}_Public.exe")
    else:
        print("         PRIVATE INSTALLER BUILT SUCCESSFULLY!")
        print("=" * 50)
        print(f"   Private Installer: Output\\OpeningFenix_Setup_v{APP_VERSION}_Private.exe")


if __name__ == '__main__':
    main()
