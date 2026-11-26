"""
Build script for the Microsoft Store MSIX package ("Opening Fenix Chess").

Usage:
    py scripts/build_msix.py [--skip-build] [--allow-placeholders] [--test-sign]

Outputs:
    Output/OpeningFenixChess_vX.Y.Z_Store.msix              (unsigned, for Partner Center upload)
    Output/OpeningFenixChess_vX.Y.Z_Store_TestSigned.msix   (only with --test-sign, for local sideload testing)
"""
import glob
import json
import os
import shutil
import stat
import subprocess
import sys
from xml.sax.saxutils import escape as xml_escape

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def safe_rmtree(path):
    if not os.path.exists(path):
        return

    def _handle_readonly(func, p, excinfo):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_handle_readonly)
        else:
            shutil.rmtree(path, onerror=_handle_readonly)
    except Exception:
        pass


def find_sdk_tool(tool_name):
    """Locate a Windows 10/11 SDK tool (e.g. makeappx.exe or signtool.exe)."""
    found = shutil.which(tool_name)
    if found:
        return found

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    search_patterns = [
        os.path.join(r"C:\Program Files (x86)\Windows Kits\10\bin", "*", "x64", tool_name),
    ]
    if local_appdata:
        search_patterns.insert(
            0,
            os.path.join(local_appdata, "OpeningFenixBuildTools", "winsdk", "bin", "*", "x64", tool_name),
        )

    for pattern in search_patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]  # newest installed SDK version
    return None


def to_msix_version(app_version):
    """Convert '1.3.15' -> '1.3.15.0' (MSIX requires 4-part numeric version)."""
    parts = [p for p in str(app_version).strip().lstrip("vV").split(".") if p.isdigit()]
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts[:4])


def generate_store_assets(logo_path, assets_out_dir):
    """Generate all required Microsoft Store PNG tile/logo sizes from Logo.png using PyQt6."""
    os.makedirs(assets_out_dir, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication, QImage, QPainter

    app = QGuiApplication.instance() or QGuiApplication([])
    src = QImage(logo_path)
    if src.isNull():
        raise RuntimeError(f"Failed to load source logo: {logo_path}")

    # (filename, width, height, pad_ratio)
    specs = [
        ("StoreLogo.png", 50, 50, 0.04),
        ("Square44x44Logo.png", 44, 44, 0.04),
        ("Square44x44Logo.targetsize-44.png", 44, 44, 0.04),
        ("Square44x44Logo.targetsize-44_altform-unplated.png", 44, 44, 0.04),
        ("Square150x150Logo.png", 150, 150, 0.12),
        ("Wide310x150Logo.png", 310, 150, 0.12),
    ]

    for filename, w, h, pad in specs:
        canvas = QImage(w, h, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)

        max_w = int(round(w * (1.0 - 2 * pad)))
        max_h = int(round(h * (1.0 - 2 * pad)))
        scaled = src.scaled(
            max_w,
            max_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (w - scaled.width()) // 2
        y = (h - scaled.height()) // 2

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(x, y, scaled)
        painter.end()

        out_path = os.path.join(assets_out_dir, filename)
        if not canvas.save(out_path, "PNG"):
            raise RuntimeError(f"Failed to save Store asset: {out_path}")

    print(f" -> Generated {len(specs)} Store logo assets in {assets_out_dir}")


def prepare_clean_public_store_bundle(src_dist_dir, staged_app_dir):
    """Copy PyInstaller bundle into staging and sanitize for Public Microsoft Store distribution."""
    shutil.copytree(src_dist_dir, staged_app_dir)

    # Mark as both PUBLIC_VERSION and STORE_VERSION
    for marker_dir in [staged_app_dir, os.path.join(staged_app_dir, "_internal")]:
        if os.path.exists(marker_dir):
            for marker in ("PUBLIC_VERSION", "STORE_VERSION"):
                with open(os.path.join(marker_dir, marker), "w", encoding="utf-8") as f:
                    f.write("1")

    # Keep only example/sample repertoires; remove profiles and engines
    for root_dir, dirs, _ in os.walk(staged_app_dir, topdown=False):
        for d in dirs:
            d_lower = d.lower()
            full_path = os.path.join(root_dir, d)
            if d_lower in ("profiles", "engines"):
                safe_rmtree(full_path)
            elif d_lower == "repertoires":
                for item in os.listdir(full_path):
                    item_path = os.path.join(full_path, item)
                    item_lower = item.lower()
                    if os.path.isdir(item_path) and not ("example" in item_lower or "sample" in item_lower):
                        safe_rmtree(item_path)

    print(f" -> Staged clean Public + Store bundle at {staged_app_dir}")


def main():
    print("=" * 56)
    print("  Opening Fenix Chess - Microsoft Store MSIX Builder")
    print("=" * 56)

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from opening_fenix.core.version import APP_VERSION

    args = sys.argv[1:]
    skip_build = "--skip-build" in args or "--no-build" in args
    allow_placeholders = "--allow-placeholders" in args
    test_sign = "--test-sign" in args

    # 1. Load MSIX identity config
    config_path = os.path.join(project_root, "installer", "msix_config.json")
    template_path = os.path.join(project_root, "installer", "AppxManifest.template.xml")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    placeholders_present = any("REPLACE_WITH_" in str(v) for v in cfg.values())
    if placeholders_present and not allow_placeholders:
        print("\nERROR: installer/msix_config.json still contains placeholder values.")
        print("Fill in identity_name, publisher, and publisher_display_name from Microsoft Partner Center")
        print("(Product management -> Product Identity), or pass --allow-placeholders for a dry run.")
        sys.exit(1)

    # 2. Ensure PyInstaller bundle exists
    dist_dir = os.path.join(project_root, "dist", "Opening Fenix")
    if not (skip_build and os.path.exists(dist_dir)):
        print("\n1. Building PyInstaller bundle...")
        import PyInstaller.__main__

        safe_rmtree(dist_dir)
        PyInstaller.__main__.run([
            "--noconfirm",
            "--clean",
            "--distpath", os.path.join(project_root, "dist"),
            "--workpath", os.path.join(project_root, "build"),
            os.path.join(project_root, "Opening Fenix.spec"),
        ])
    else:
        print("\n1. Reusing existing PyInstaller bundle (--skip-build)...")

    if not os.path.exists(dist_dir):
        print("ERROR: dist/Opening Fenix not found.")
        sys.exit(1)

    # 3. Stage MSIX directory
    print("\n2. Staging MSIX package files...")
    staging_dir = os.path.join(project_root, "build", "msix_staging")
    safe_rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    prepare_clean_public_store_bundle(dist_dir, os.path.join(staging_dir, "app"))

    logo_path = os.path.join(project_root, "assets", "Logo", "Logo.png")
    generate_store_assets(logo_path, os.path.join(staging_dir, "Assets"))

    # 4. Render AppxManifest.xml
    msix_version = to_msix_version(APP_VERSION)
    with open(template_path, "r", encoding="utf-8") as f:
        manifest = f.read()

    replacements = {
        "{IDENTITY_NAME}": xml_escape(cfg["identity_name"]),
        "{PUBLISHER}": xml_escape(cfg["publisher"]),
        "{MSIX_VERSION}": xml_escape(msix_version),
        "{DISPLAY_NAME}": xml_escape(cfg.get("display_name", "Opening Fenix Chess")),
        "{PUBLISHER_DISPLAY_NAME}": xml_escape(cfg["publisher_display_name"]),
        "{DESCRIPTION}": xml_escape(cfg.get("description", "Chess opening repertoire trainer.")),
    }
    for k, v in replacements.items():
        manifest = manifest.replace(k, v)

    manifest_out = os.path.join(staging_dir, "AppxManifest.xml")
    with open(manifest_out, "w", encoding="utf-8") as f:
        f.write(manifest)
    print(f" -> Wrote {manifest_out} (Version {msix_version})")

    # 5. Locate makeappx.exe and pack
    print("\n3. Packing MSIX with makeappx.exe...")
    makeappx = find_sdk_tool("makeappx.exe")
    if not makeappx:
        print("\nERROR: Windows SDK 'makeappx.exe' not found.")
        print("Install the Windows 11 SDK by running:")
        print("  winget install Microsoft.WindowsSDK.10.0.26100")
        print("Then re-run: py scripts/build_msix.py --skip-build")
        sys.exit(1)

    output_dir = os.path.join(project_root, "Output")
    os.makedirs(output_dir, exist_ok=True)
    msix_out = os.path.join(output_dir, f"OpeningFenixChess_v{APP_VERSION}_Store.msix")

    res = subprocess.run([makeappx, "pack", "/d", staging_dir, "/p", msix_out, "/o"])
    if res.returncode != 0:
        print("ERROR: makeappx.exe failed.")
        sys.exit(res.returncode)

    print(f"\nSUCCESS! Unsigned Store MSIX ready for Partner Center upload:")
    print(f"  {msix_out}")

    # 6. Optional local test signing
    if test_sign:
        print("\n4. Creating locally signed copy for sideload testing (--test-sign)...")
        signtool = find_sdk_tool("signtool.exe")
        if not signtool:
            print("ERROR: signtool.exe not found in Windows SDK.")
            sys.exit(1)

        signed_out = os.path.join(output_dir, f"OpeningFenixChess_v{APP_VERSION}_Store_TestSigned.msix")
        shutil.copy2(msix_out, signed_out)

        cert_dir = os.path.join(project_root, "build", "msix_test_cert")
        os.makedirs(cert_dir, exist_ok=True)
        pfx_path = os.path.join(cert_dir, "OpeningFenixTestCert.pfx")
        cer_path = os.path.join(cert_dir, "OpeningFenixTestCert.cer")
        publisher = cfg["publisher"]

        ps_cert = (
            f"$trusted = @(); "
            f"foreach ($store in @('Cert:\\LocalMachine\\Root', 'Cert:\\CurrentUser\\Root')) {{ "
            f"  if (Test-Path $store) {{ $trusted += (Get-ChildItem $store | Select-Object -ExpandProperty Thumbprint) }} "
            f"}}; "
            f"$candidates = Get-ChildItem 'Cert:\\CurrentUser\\My' | Where-Object {{ "
            f"  $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) -and $_.Subject -eq '{publisher}' "
            f"}} | Sort-Object NotAfter -Descending; "
            f"$cert = $candidates | Where-Object {{ $trusted -contains $_.Thumbprint }} | Select-Object -First 1; "
            f"if (-not $cert) {{ $cert = $candidates | Select-Object -First 1 }}; "
            f"if ($cert) {{ "
            f"  Write-Output \" -> Reusing existing test certificate: $($cert.Thumbprint)\" "
            f"}} else {{ "
            f"  $cert = New-SelfSignedCertificate -Type Custom -Subject '{publisher}' "
            f"  -KeyUsage DigitalSignature -FriendlyName 'Opening Fenix Local Test Cert' "
            f"  -CertStoreLocation 'Cert:\\CurrentUser\\My' "
            f"  -TextExtension @('2.5.29.37={{text}}1.3.6.1.5.5.7.3.3', '2.5.29.19={{text}}'); "
            f"  Write-Output \" -> Generated new test certificate: $($cert.Thumbprint)\" "
            f"}}; "
            f"$pwd = ConvertTo-SecureString -String 'fenixtest' -Force -AsPlainText; "
            f"Export-PfxCertificate -Cert $cert -FilePath '{pfx_path}' -Password $pwd | Out-Null; "
            f"Export-Certificate -Cert $cert -FilePath '{cer_path}' | Out-Null"
        )
        cert_res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cert])
        if cert_res.returncode != 0:
            print("ERROR: Failed to generate local test certificate.")
            sys.exit(cert_res.returncode)

        sign_res = subprocess.run([
            signtool, "sign", "/fd", "SHA256", "/a",
            "/f", pfx_path, "/p", "fenixtest", signed_out,
        ])
        if sign_res.returncode != 0:
            print("ERROR: signtool.exe failed.")
            sys.exit(sign_res.returncode)

        print(f"\nLocally signed test MSIX ready:")
        print(f"  {signed_out}")
        print("\nTo test-install on this PC (run PowerShell as Administrator once to trust the test cert):")
        print(f"  Import-Certificate -FilePath \"{cer_path}\" -CertStoreLocation Cert:\\LocalMachine\\Root")
        print(f"  Add-AppxPackage -Path \"{signed_out}\"")


if __name__ == "__main__":
    main()
