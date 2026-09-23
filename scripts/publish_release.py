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
    # 1. Environment variables
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token

    # 2. Windows Credential Manager
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            advapi32 = ctypes.windll.advapi32
            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                    ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                    ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                    ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)), ('Persist', wintypes.DWORD),
                    ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                    ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)
                ]
            CredReadW = advapi32.CredReadW
            CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
            CredReadW.restype = wintypes.BOOL
            CredFree = advapi32.CredFree
            CredFree.argtypes = [ctypes.c_void_p]

            targets = ['git:https://Takais-Chess@github.com', 'git:https://github.com', 'GitHub for Visual Studio - https://Takais-Chess@github.com/']
            for t in targets:
                pcred = ctypes.POINTER(CREDENTIAL)()
                if CredReadW(t, 1, 0, ctypes.byref(pcred)):
                    blob = ctypes.string_at(pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize)
                    CredFree(pcred)
                    try:
                        return blob.decode('utf-16le')
                    except Exception:
                        return blob.decode('utf-8', errors='replace')
        except Exception:
            pass

    # 3. Git Credential Manager subprocess fallback
    try:
        p = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, _ = p.communicate('protocol=https\nhost=github.com\n\n', timeout=5)
        creds = dict(line.split('=', 1) for line in out.strip().splitlines() if '=' in line)
        return creds.get('password')
    except Exception:
        return None

def main():
    token = get_github_token()
    if not token:
        print("Error: Could not retrieve GitHub token from git credential manager.")
        sys.exit(1)

    repo = "Takais-Chess/Opening-Fenix"
    tag_name = f"v{APP_VERSION}"
    release_name = f"Opening Fenix v{APP_VERSION}"
    
    # Extract release body dynamically from CHANGELOG.md for the current APP_VERSION
    changelog_path = os.path.join(project_root, "CHANGELOG.md")
    release_body = f"## 🎉 Opening Fenix v{APP_VERSION}\n\nOfficial release v{APP_VERSION}."
    if os.path.exists(changelog_path):
        try:
            with open(changelog_path, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            pattern = rf"##\s*\[{re.escape(APP_VERSION)}\][^\n]*\n([\s\S]*?)(?=\n##\s*\[|\Z)"
            m = re.search(pattern, content)
            if m:
                body = m.group(1).strip()
                release_body = f"## 🎉 Opening Fenix v{APP_VERSION}\n\n{body}"
        except Exception as e:
            print(f"Warning: could not extract notes from CHANGELOG.md: {e}")

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
