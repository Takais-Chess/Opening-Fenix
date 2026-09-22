import os
import sys
import stat
import shutil
import subprocess
import PyInstaller.__main__

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def safe_rmtree(path):
    """Safely delete directory trees, clearing read-only attributes on Windows."""
    if not os.path.exists(path):
        return

    def _handle_remove_readonly(func, p, excinfo):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_handle_remove_readonly)
        else:
            shutil.rmtree(path, onerror=_handle_remove_readonly)
    except Exception:
        pass

    if os.path.exists(path):
        try:
            subprocess.run(['attrib', '-r', '-s', '-h', '/s', '/d', os.path.join(path, '*')], capture_output=True)
            subprocess.run(['cmd', '/c', 'rmdir', '/s', '/q', path], capture_output=True)
        except Exception:
            pass


def _clean_engines(dist_dir):
    """Ensure engines directory is not bundled in installer packages (private or public)."""
    for root_dir_path, dirs, _ in os.walk(dist_dir, topdown=False):
        for d in dirs:
            if d.lower() == 'engines':
                e_dir = os.path.join(root_dir_path, d)
                safe_rmtree(e_dir)
                print(f" -> Removed engines directory '{e_dir}' from bundle")


def _set_process_priority():
    """Sets the build script process to BELOW_NORMAL_PRIORITY_CLASS on Windows.
    This ensures that PyInstaller packaging and Inno Setup LZMA compression
    run in the background without causing micro-stutters or frame drops in interactive apps."""
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.SetPriorityClass.restype = wintypes.BOOL
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            if kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS):
                print(" -> Build process priority set to BelowNormal (background-friendly mode).")
        except Exception:
            pass


def _run_iscc(iscc_exe, iss_file, app_version, build_type):
    """Run Inno Setup Compiler with BelowNormal priority to keep foreground apps responsive."""
    cmd = [iscc_exe, f'/DMyAppVersion={app_version}', f'/DAppBuildType={build_type}', iss_file]
    creationflags = getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0) if sys.platform == 'win32' else 0
    return subprocess.run(cmd, capture_output=False, creationflags=creationflags)


def build_private(dist_dir, iscc_exe, iss_file, app_version):
    """Compile the PRIVATE installer (non-example repertoires, no profiles, engines excluded)."""
    print("\n3a. Compiling PRIVATE Installer (non-example repertoires only, engines excluded)...")

    _clean_engines(dist_dir)

    for marker_dir in [dist_dir, os.path.join(dist_dir, '_internal')]:
        pub_marker = os.path.join(marker_dir, 'PUBLIC_VERSION')
        if os.path.exists(pub_marker):
            os.remove(pub_marker)

    # Remove any profiles from the bundle (profiles are user-created only)
    for root_dir_path, dirs, _ in os.walk(dist_dir, topdown=False):
        for d in dirs:
            if d.lower() == 'profiles':
                p_dir = os.path.join(root_dir_path, d)
                safe_rmtree(p_dir)
                print(f" -> Removed profile directory '{p_dir}' from private bundle")

    # Sync repertoires into the bundle
    if os.path.exists('repertoires'):
        for target_base in [dist_dir, os.path.join(dist_dir, '_internal')]:
            if os.path.exists(target_base):
                dst = os.path.join(target_base, 'repertoires')
                if os.path.exists(dst):
                    safe_rmtree(dst)
                shutil.copytree('repertoires', dst, ignore=shutil.ignore_patterns('*.pgi', '*.tmp', '*.lock'))
                print(f" -> Synced repertoires to {dst}")

    # Remove example/sample repertoires (private installer only ships non-example repos)
    for root_dir_path, dirs, _ in os.walk(dist_dir, topdown=False):
        for d in dirs:
            if d.lower() == 'repertoires':
                repo_dir = os.path.join(root_dir_path, d)
                for item in os.listdir(repo_dir):
                    item_path = os.path.join(repo_dir, item)
                    item_lower = item.lower()
                    if os.path.isdir(item_path) and ("example" in item_lower or "sample" in item_lower):
                        safe_rmtree(item_path)
                        safe_item = item.encode('ascii', errors='replace').decode('ascii')
                        print(f" -> Removed example repertoire '{safe_item}' from '{repo_dir}'")

    res = _run_iscc(iscc_exe, iss_file, app_version, 'Private')
    if res.returncode != 0:
        print("ERROR: Private Inno Setup compilation failed.")
        sys.exit(res.returncode)


def build_public(dist_dir, iscc_exe, iss_file, app_version):
    """Compile the PUBLIC installer (example repertoires only, no personal data)."""
    print("\n3b. Compiling PUBLIC Installer (clean build with example repertoires only)...")

    # Place the PUBLIC_VERSION marker so the app knows it's a public build
    for marker_dir in [dist_dir, os.path.join(dist_dir, '_internal')]:
        if os.path.exists(marker_dir):
            pub_marker = os.path.join(marker_dir, 'PUBLIC_VERSION')
            with open(pub_marker, 'w', encoding='utf-8') as f:
                f.write('1')
            print(f" -> Placed PUBLIC_VERSION marker at {pub_marker}")

    # Clean repertoires across the entire bundle, keeping ONLY example/sample folders
    for root_dir_path, dirs, _ in os.walk(dist_dir, topdown=False):
        for d in dirs:
            if d.lower() == 'repertoires':
                repo_dir = os.path.join(root_dir_path, d)
                for item in os.listdir(repo_dir):
                    item_path = os.path.join(repo_dir, item)
                    item_lower = item.lower()
                    if os.path.isdir(item_path) and not ("example" in item_lower or "sample" in item_lower):
                        safe_rmtree(item_path)
                        safe_item = item.encode('ascii', errors='replace').decode('ascii')
                        print(f" -> Removed non-example repertoire '{safe_item}' from '{repo_dir}'")
    print(" -> Synced example repertoires to public bundle")

    # Remove engines from public bundle (users download Stockfish on-demand to maintain 0 GPL overhead)
    _clean_engines(dist_dir)

    res = _run_iscc(iscc_exe, iss_file, app_version, 'Public')
    if res.returncode != 0:
        print("ERROR: Public Inno Setup compilation failed.")
        sys.exit(res.returncode)


def main():
    print("=" * 50)
    print("      Opening Fenix - Installer Build Script")
    print("=" * 50)
    print("Usage: python scripts/build_installer.py [--public-only | --private-only]")
    print("       No flag = build both installers (default)")

    _set_process_priority()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from opening_fenix.core.version import APP_VERSION

    # Parse CLI flags
    args = sys.argv[1:]
    do_private = "--public-only" not in args
    do_public  = "--private-only" not in args
    skip_build = "--skip-build" in args or "--no-build" in args

    if not do_private and not do_public:
        print("ERROR: Cannot combine --public-only and --private-only.")
        sys.exit(1)

    # --------------------------------------------------------
    # Step 1: PyInstaller bundle (always needed unless --skip-build)
    # --------------------------------------------------------
    dist_dir = os.path.join(project_root, 'dist', 'Opening Fenix')
    if skip_build and os.path.exists(dist_dir):
        print("\n1. Skipping PyInstaller build (--skip-build specified and dist/ exists)...")
    else:
        if os.path.exists(dist_dir):
            # Try to cleanly remove dist_dir without touching any running processes.
            safe_rmtree(dist_dir)
            # If files inside dist_dir are locked, only terminate processes running specifically from dist_dir.
            if os.path.exists(dist_dir):
                try:
                    norm_target = os.path.normcase(os.path.abspath(dist_dir))
                    ps_script = (
                        f"$target = '{norm_target}'; "
                        "Get-Process | Where-Object { $_.Path -and ($_.Path.ToLower().StartsWith($target.ToLower())) } | "
                        "Select-Object -ExpandProperty Id"
                    )
                    res = subprocess.run(['powershell', '-NoProfile', '-Command', ps_script], capture_output=True, text=True)
                    for line in res.stdout.splitlines():
                        pid = line.strip()
                        if pid.isdigit():
                            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
                    import time
                    time.sleep(0.5)
                    safe_rmtree(dist_dir)
                except Exception:
                    pass

        print("\n1. Building PyInstaller Application Bundle...")
        PyInstaller.__main__.run([
            '--noconfirm',
            '--distpath', os.path.join(project_root, 'dist'),
            '--workpath', os.path.join(project_root, 'build'),
            os.path.join(project_root, 'Opening Fenix.spec')
        ])

    dist_dir = os.path.join(project_root, 'dist', 'Opening Fenix')
    if not os.path.exists(dist_dir):
        print("ERROR: PyInstaller build failed! dist/Opening Fenix directory not found.")
        sys.exit(1)
    print(" -> PyInstaller base bundle ready.")

    # --------------------------------------------------------
    # Step 2: Clean engines (engines excluded from bundles)
    # --------------------------------------------------------
    _clean_engines(dist_dir)

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
