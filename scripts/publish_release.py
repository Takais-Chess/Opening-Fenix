import os
import sys
import subprocess
import urllib.request
import urllib.parse
import json

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
    tag_name = "v0.9.13"
    release_name = "Opening Fenix v0.9.13"
    
    release_body = """## What's New in v0.9.13

### 📊 Repertoire Statistics & Insights
- **Dedicated Insights Modal**: Accessible directly from the Creator toolbar (right of the Resources button).
- **Opening Scope Detection**: Smart root branch detection (`Gegen 1.e4`, `1.d4 Repertoire`) that scopes coverage curves and expected win rates specifically within the course's focus, eliminating false alerts for out-of-scope openings.
- **3 Core Metric Badges**: Real-world Lichess expected win rate (Effectiveness), Stockfish path evaluation score (Soundness), and memory load categorization (Learnability).
- **1-Step Move Coverage Curve**: Dynamic step-by-step opponent coverage curve tracking book survival rate per move with colored visual indicators.
- **Clean Level Sizing Breakdown**: Non-cluttered text breakdown of unique positions across Level 1 (Core), Level 2 (Expanded), and Level 3 (Deep).

### ⚡ 2-Move Transposition Scanner Speed & Quality Overhaul
- **Fixed Depth Variable Shadowing**: Eliminated engine depth runaway bug that caused runaway engine analysis on deep lines.
- **Tuned Engine Tolerance (10 cp)**: Practical moves within 10 centipawns of the engine's #1 move are recognized as `🟡 Solide (-X cp)`.
- **Pure Depth Search**: Engine evaluation runs strictly according to the configured search depth (e.g. depth 25) without artificial timeouts.
- **Lazy SAN Computation**: Transposition discovery runs on raw UCI/FEN representations, computing expensive SAN strings only for accepted candidates.
- **Detailed Real-Time Logging**: Step-by-step evaluation feedback logged in real-time.

### 🖥️ Transposition Scan System Responsiveness
- **CPU Core Reservation**: Automatically reserves at least 1 CPU core for the operating system and UI during deep multi-move scans.
- **OS / GIL Yielding**: Yields GIL between position evaluations so Windows and the UI remain completely responsive.

### 🎨 UI Polish
- Fixed column-span clearing issue in the Transpositions tab so the "No direct transpositions" message is properly cleared when navigating to a 2-move transposition.
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
    asset_file_path = os.path.join("Output", "OpeningFenix_Setup_v0.9.13_Public.exe")
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

    print("\nRelease v0.9.13 successfully published!")
    print(f"View release: https://github.com/{repo}/releases/tag/{tag_name}")

if __name__ == "__main__":
    main()
