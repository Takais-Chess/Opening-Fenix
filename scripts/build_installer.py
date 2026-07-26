import os
import sys
import shutil
import subprocess
import PyInstaller.__main__

def main():
    print("=" * 50)
    print("      Opening Fenix - Installer Build Script")
    print("=" * 50)

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)

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

    # 2. Sync Engines (Stockfish - needed for both Public and Private builds)
    if os.path.exists('engines'):
        dst = os.path.join(dist_dir, 'engines')
        if os.path.exists(dst): shutil.rmtree(dst)
        shutil.copytree('engines', dst)
        print(f" -> Synced engines to {dst}")

    # 3. Locate Inno Setup Compiler (ISCC.exe)
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
        print(f"The installer script has been created at: {iss_file}")
        sys.exit(1)

    print(f" -> Found Inno Setup Compiler: {iscc_exe}")

    # ----------------------------------------------------
    # BUILD 1: PRIVATE INSTALLER (Includes user data, excludes example repertoires)
    # ----------------------------------------------------
    print("\n3a. Compiling PRIVATE Installer (with profiles & personal repertoires)...")
    pub_marker = os.path.join(dist_dir, 'PUBLIC_VERSION')
    if os.path.exists(pub_marker):
        os.remove(pub_marker)

    for folder in ['profiles', 'repertoires']:
        if os.path.exists(folder):
            dst = os.path.join(dist_dir, folder)
            if os.path.exists(dst): shutil.rmtree(dst)
            shutil.copytree(folder, dst)
            if folder == 'repertoires':
                # Remove example repertoires from Private build
                for item in os.listdir(dst):
                    item_path = os.path.join(dst, item)
                    item_lower = item.lower()
                    if os.path.isdir(item_path) and ("example" in item_lower or "sample" in item_lower):
                        shutil.rmtree(item_path, ignore_errors=True)
                        print(f" -> Removed example repertoire '{item}' from private bundle")
            print(f" -> Synced {folder} to {dst}")

    res_priv = subprocess.run([iscc_exe, '/DAppBuildType=Private', iss_file], capture_output=False)
    if res_priv.returncode != 0:
        print("ERROR: Private Inno Setup compilation failed.")
        sys.exit(res_priv.returncode)

    # ----------------------------------------------------
    # BUILD 2: PUBLIC INSTALLER (With example repertoires only, no personal data)
    # ----------------------------------------------------
    print("\n3b. Compiling PUBLIC Installer (clean build with example repertoires only)...")
    with open(pub_marker, 'w', encoding='utf-8') as f:
        f.write('1')

    # Remove personal profiles
    dst_profiles = os.path.join(dist_dir, 'profiles')
    if os.path.exists(dst_profiles):
        shutil.rmtree(dst_profiles)
        print(" -> Removed personal profiles from public bundle")

    # Sync repertoires folder keeping ONLY example repertoires
    if os.path.exists('repertoires'):
        dst_repos = os.path.join(dist_dir, 'repertoires')
        if os.path.exists(dst_repos): shutil.rmtree(dst_repos)
        shutil.copytree('repertoires', dst_repos)
        for item in os.listdir(dst_repos):
            item_path = os.path.join(dst_repos, item)
            item_lower = item.lower()
            if os.path.isdir(item_path) and not ("example" in item_lower or "sample" in item_lower):
                shutil.rmtree(item_path, ignore_errors=True)
                print(f" -> Removed non-example repertoire '{item}' from public bundle")
        print(" -> Synced example repertoires to public bundle")

    res_pub = subprocess.run([iscc_exe, '/DAppBuildType=Public', iss_file], capture_output=False)
    if res_pub.returncode != 0:
        print("ERROR: Public Inno Setup compilation failed.")
        sys.exit(res_pub.returncode)

    output_dir = os.path.join(project_root, 'Output')
    print("\n" + "=" * 50)
    print("         BOTH INSTALLERS BUILT SUCCESSFUL!")
    print("=" * 50)
    print(f"1. Private Installer: Output\\OpeningFenix_Setup_v1.0.0_Private.exe")
    print(f"2. Public Installer:  Output\\OpeningFenix_Setup_v1.0.0_Public.exe")

if __name__ == '__main__':
    main()
