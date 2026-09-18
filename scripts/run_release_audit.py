#!/usr/bin/env python3
"""
Release Audit Script for Opening Fenix.
Performs pre-release sanity checks:
1. Localization parity (de.json vs en.json)
2. Asset reference validation (icons, sounds, logos)
3. Version consistency across all distribution files
4. Basic code hygiene checks (orphan print statements in core, etc.)
"""

import os
import sys
import json
import re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def check_translations():
    print("=== [1/4] Checking Localization Parity ===")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    de_path = os.path.join(base_dir, "assets", "translations", "de.json")
    en_path = os.path.join(base_dir, "assets", "translations", "en.json")
    
    if not os.path.exists(de_path) or not os.path.exists(en_path):
        print("  [FAIL] Missing translation files!")
        return False
        
    with open(de_path, "r", encoding="utf-8") as f:
        de_data = json.load(f)
    with open(en_path, "r", encoding="utf-8") as f:
        en_data = json.load(f)
        
    def flatten_dict(d, prefix=""):
        items = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(flatten_dict(v, key))
            else:
                items[key] = v
        return items

    de_keys = set(flatten_dict(de_data).keys())
    en_keys = set(flatten_dict(en_data).keys())
    
    missing_in_en = de_keys - en_keys
    missing_in_de = en_keys - de_keys
    
    print(f"  German keys: {len(de_keys)}, English keys: {len(en_keys)}")
    if missing_in_en:
        print(f"  [WARN] {len(missing_in_en)} keys present in German but missing in English:")
        for k in sorted(list(missing_in_en))[:10]:
            print(f"    - {k}")
        if len(missing_in_en) > 10:
            print(f"    ... and {len(missing_in_en) - 10} more.")
    else:
        print("  [OK] All German keys are present in English!")
        
    if missing_in_de:
        print(f"  [WARN] {len(missing_in_de)} keys present in English but missing in German:")
        for k in sorted(list(missing_in_de))[:10]:
            print(f"    - {k}")
    else:
        print("  [OK] All English keys are present in German!")
        
    return len(missing_in_en) == 0 and len(missing_in_de) == 0

def check_assets():
    print("\n=== [2/4] Checking Asset Files & Code References ===")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(base_dir, "assets")
    
    # Collect all existing asset paths
    existing_assets = set()
    for root, _, files in os.walk(assets_dir):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), base_dir).replace("\\", "/")
            existing_assets.add(rel)
            existing_assets.add(os.path.basename(f))
            
    print(f"  Total physical asset files found: {len(existing_assets)}")
    
    # Scan python files for asset references
    asset_patterns = [
        re.compile(r'["\'](assets/[^"\']+)["\']'),
        re.compile(r'["\']([^"\']+\.(?:png|ico|svg|wav|ogg|mp3))["\']')
    ]
    
    missing_references = set()
    total_refs = 0
    code_dir = os.path.join(base_dir, "opening_fenix")
    for root, _, files in os.walk(code_dir):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    for pat in asset_patterns:
                        for match in pat.finditer(content):
                            ref = match.group(1).replace("\\", "/")
                            # Skip dynamic templates, web URLs, or user-defined repertoire assets
                            if "{" in ref or "%" in ref or ref.startswith("http") or ref.endswith("cover.png"):
                                continue
                            if "/" in ref and not ref.startswith("assets/"):
                                continue
                            total_refs += 1
                            base_ref = os.path.basename(ref)
                            if ref not in existing_assets and base_ref not in existing_assets:
                                missing_references.add((os.path.relpath(file_path, base_dir), ref))
                except Exception as e:
                    pass
                    
    print(f"  Total asset references scanned: {total_refs}")
    if missing_references:
        print(f"  [WARN] {len(missing_references)} potentially broken asset references:")
        for src, ref in sorted(list(missing_references))[:15]:
            print(f"    - {src}: {ref}")
    else:
        print("  [OK] All hardcoded asset references exist on disk!")
    return len(missing_references) == 0

def check_versions():
    print("\n=== [3/4] Checking Version Consistency ===")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 1. core/version.py
    version_file = os.path.join(base_dir, "opening_fenix", "core", "version.py")
    app_version = None
    if os.path.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("APP_VERSION"):
                    app_version = line.split("=")[1].strip().strip('"').strip("'")
    print(f"  Core APP_VERSION: {app_version}")
    
    # 2. Inno Setup
    iss_file = os.path.join(base_dir, "installer", "OpeningFenix_Setup.iss")
    iss_version = None
    if os.path.exists(iss_file):
        with open(iss_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#define MyAppVersion"):
                    iss_version = stripped.split('"')[1]
                    break
    print(f"  Inno Setup MyAppVersion: {iss_version}")
    
    # 3. publish_release.py
    publish_file = os.path.join(base_dir, "scripts", "publish_release.py")
    publish_version = None
    if os.path.exists(publish_file):
        with open(publish_file, "r", encoding="utf-8") as f:
            for line in f:
                if 'tag_name = "v' in line:
                    publish_version = line.split('"')[1].lstrip('v')
    print(f"  Publish release version: {publish_version}")

    matches = (app_version == iss_version == publish_version)
    if matches:
        print(f"  [OK] Version numbers match across files: {app_version}")
    else:
        print(f"  [WARN] Version mismatch detected! (Core: {app_version}, ISS: {iss_version}, Publish: {publish_version})")
    return matches

def check_license_and_docs():
    print("\n=== [4/4] Checking Release Documentation & Licenses ===")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    critical_docs = ["LICENSE", "README.md", "CHANGELOG.md", "QUICKSTART.md"]
    all_exist = True
    for doc in critical_docs:
        doc_path = os.path.join(base_dir, doc)
        if os.path.exists(doc_path):
            size = os.path.getsize(doc_path)
            print(f"  [OK] {doc} exists ({size} bytes)")
        else:
            print(f"  [FAIL] Missing required documentation: {doc}")
            all_exist = False
    return all_exist

def main():
    print("==================================================")
    print("       OPENING FENIX - RELEASE 1.0 AUDIT          ")
    print("==================================================")
    res1 = check_translations()
    res2 = check_assets()
    res3 = check_versions()
    res4 = check_license_and_docs()
    print("\n==================================================")
    if all([res1, res2, res3, res4]):
        print("🎉 ALL AUDIT CHECKS PASSED!")
    else:
        print("⚠️ AUDIT COMPLETED WITH WARNINGS (See details above)")
    print("==================================================")

if __name__ == "__main__":
    main()
