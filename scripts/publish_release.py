import os
import sys
import subprocess
import urllib.request
import urllib.parse
import json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from opening_fenix.core.version import APP_VERSION

def get_github_token():
    p = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, _ = p.communicate('protocol=https\nhost=github.com\n')
    creds = dict(line.split('=', 1) for line in out.strip().splitlines() if '=' in line)
    return creds.get('password')

def main():
    token = get_github_token()
    if not token:
        print("Error: Could not retrieve GitHub token from git credential manager.")
        sys.exit(1)

    repo = "Takais-Chess/Opening-Fenix"
    tag_name = f"v{APP_VERSION}"
    release_name = f"Opening Fenix v{APP_VERSION}"
    
    release_body = f"""## 🎉 Opening Fenix v{APP_VERSION} - Official Release

Opening Fenix 1.0 is here! A comprehensive, high-performance chess opening repertoire manager and active recall training system built with PyQt6, Stockfish, and Lichess database integration.

### 🌟 Release Highlights

#### 🖥️ High-DPI & Multi-Resolution Display Polish
- Full visual audit and layout optimization across all 12 core windows and modals on high-DPI scaling (125%, 150%, 200%).
- Full typography scaling audit: 100% of labels, dialogs, tables, and settings now scale dynamically with `scale(...)` across High-DPI and custom display resolutions.
- Polished dialog layouts including Engine Action, Course Import, Statistics Insights, Repertoire Selection, and Export dialogs to prevent clipping or scrollbar truncation.
- Dynamic responsive table columns in Creator Analysis and Transposition tabs with intelligent font scaling and smart percentage formatting.

#### 📊 Repertoire Statistics & Advanced Insights
- Dedicated Insights modal with intelligent opening scope detection (`Gegen 1.e4`, `1.d4 Repertoire`) eliminating false out-of-scope alerts.
- 3 Core Metric Badges: Real-world Lichess expected win rate (Effectiveness), Stockfish path evaluation score (Soundness), and memory load categorization (Learnability).
- Step-by-step opponent move coverage curve tracking book survival rate per move with color-coded visual indicators.
- Position sizing breakdown across Level 1 (Core), Level 2 (Expanded), and Level 3 (Deep).

#### ⚡ High-Speed 2-Move Transposition Scanner
- Tuned engine tolerance (10 cp) recognizing practical moves alongside top engine moves.
- Pure search depth evaluation without artificial cutoffs, reserving CPU cores for OS responsiveness and UI fluidity.
- Lazy SAN computation with real-time progress feedback.

#### 🧩 Course Import & Profile Synchronization
- Streamlined PGN course import service with interactive chapter preview.
- Multi-profile repertoire management with automated background backup deduplication.

#### 🌍 100% Bilingual Localization Parity
- Complete parity between German and English across all 1,166 translation keys.

#### 🛡️ Stability & Test Coverage
- Over 700 passing automated unit and integration tests verifying database integrity, UI event handling, and engine synchronization.
"""

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OpeningFenix-Release-Script"
    }

    # 1. Create or get existing release
    print(f"Creating release {tag_name} on {repo}...")
    create_url = f"https://api.github.com/repos/{repo}/releases"
    payload = {
        "tag_name": tag_name,
        "target_commitish": "main",
        "name": release_name,
        "body": release_body,
        "draft": False,
        "prerelease": False
    }

    req = urllib.request.Request(create_url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            rel_data = json.loads(resp.read().decode('utf-8'))
            print(" -> Release created successfully!")
    except urllib.error.HTTPError as e:
        err_content = e.read().decode('utf-8')
        if e.code == 422 and "already_exists" in err_content:
            print(" -> Release already exists, fetching existing release...")
            get_req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/tags/{tag_name}", headers=headers)
            with urllib.request.urlopen(get_req) as resp:
                rel_data = json.loads(resp.read().decode('utf-8'))
        else:
            print(f"HTTP Error {e.code}: {err_content}")
            sys.exit(1)

    release_id = rel_data["id"]
    upload_url_tmpl = rel_data["upload_url"] # e.g. https://uploads.github.com/repos/.../assets{?name,label}
    upload_url_base = upload_url_tmpl.split("{")[0]

    # 2. Check if asset already exists and delete if so
    asset_file_path = os.path.join("Output", f"OpeningFenix_Setup_v{APP_VERSION}_Public.exe")
    if not os.path.exists(asset_file_path):
        print(f"ERROR: Asset file not found at {asset_file_path}")
        sys.exit(1)

    asset_name = os.path.basename(asset_file_path)
    existing_assets = rel_data.get("assets", [])
    for a in existing_assets:
        if a["name"] == asset_name:
            print(f"Deleting existing asset {asset_name} (id: {a['id']})...")
            del_req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/assets/{a['id']}", headers=headers, method="DELETE")
            with urllib.request.urlopen(del_req) as resp:
                print(" -> Deleted old asset.")

    # 3. Upload asset
    print(f"Uploading {asset_file_path} ({os.path.getsize(asset_file_path):,} bytes)...")
    upload_url = f"{upload_url_base}?name={urllib.parse.quote(asset_name)}"
    
    with open(asset_file_path, "rb") as f:
        file_data = f.read()

    upload_headers = dict(headers)
    upload_headers["Content-Type"] = "application/octet-stream"
    upload_headers["Content-Length"] = str(len(file_data))

    up_req = urllib.request.Request(upload_url, data=file_data, headers=upload_headers, method="POST")
    try:
        with urllib.request.urlopen(up_req) as resp:
            up_data = json.loads(resp.read().decode('utf-8'))
            print(" -> Asset uploaded successfully!")
            print(f"Download URL: {up_data.get('browser_download_url')}")
    except urllib.error.HTTPError as e:
        print(f"Failed to upload asset: {e.code} - {e.read().decode('utf-8')}")
        sys.exit(1)

    print(f"\nRelease v{APP_VERSION} successfully published!")
    print(f"View release: https://github.com/{repo}/releases/tag/{tag_name}")

if __name__ == "__main__":
    main()
