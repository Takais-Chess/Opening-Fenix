---
name: release-version
description: Validate changes with tests and release audit, bump patch version (+1 to third number), build public installer, and publish a new GitHub release.
---

# Release Version Skill

This skill guides the complete release process for Opening Fenix. It ensures code quality and translation integrity, increments the patch version (`X.Y.Z -> X.Y.Z+1`), builds the standalone public Windows installer, commits and tags the release, and publishes it to GitHub as the latest release.

## Golden Rules
- **Never discard uncommitted code**: Do not run destructive cleanup commands like `git clean -fd`. User work must be preserved and committed as part of the release.
- **Fail Fast**: If audit or tests fail, abort immediately so the user can fix the underlying issues before any files or commits are made.
- **Single Source of Truth**: The version must be kept identical across `opening_fenix/core/version.py`, `installer/OpeningFenix_Setup.iss`, and `CHANGELOG.md`.
- **Patch Bumps Only**: Always increment the third number by +1 (e.g. `1.3.1` -> `1.3.2`).

---

## Execution Workflow

All commands must be executed from the project root where `.git`, `scripts/`, and `main.py` reside (i.e. `Opening-Fenix/Opening-Fenix`).

### Step 1: Pre-Release Quality Gates
Run pre-release validation checks to verify application integrity:

1. **Run Release Audit**:
   ```powershell
   python scripts/run_release_audit.py
   ```
   *Verifies:*
   - Localization parity: Checks that `assets/translations/de.json` and `en.json` have identical keys.
   - Asset validation: Verifies all icons, audio, and images referenced in code exist on disk.
   - Code hygiene: Ensures no stray print statements or missing version references.
   *Action:* If this script reports errors or missing translation keys, stop and resolve them before proceeding.

2. **Run Test Suite**:
   ```powershell
   pytest
   ```
   *Action:* If any test fails, stop immediately and report the failure.

---

### Step 2: Version Bumping (Patch Increment)
1. Read the current version from `opening_fenix/core/version.py` (`APP_VERSION`).
2. Compute the next patch version by incrementing the third digit by 1:
   - Example: `1.3.1` $\to$ `1.3.2`.
3. Update the version in the following files:
   - **`opening_fenix/core/version.py`**:
     ```python
     APP_VERSION = "X.Y.Z"
     ```
   - **`installer/OpeningFenix_Setup.iss`**:
     ```iss
     #define MyAppVersion "X.Y.Z"
     ```
4. Update **`CHANGELOG.md`**:
   - Add a new section at the top (under `# Changelog`) with today's date:
     ```markdown
     ## [X.Y.Z] - YYYY-MM-DD

     ### Added & Improved
     - <Summary of features and improvements>

     ### Fixed
     - <Summary of bug fixes>
     ```
   - If the user hasn't provided a summary, prompt them or inspect recent git commit history / changes to generate concise notes.

---

### Step 3: Build the Public Installer
Run the Inno Setup build script for the public distribution:

```powershell
python scripts/build_installer.py --public-only
```

*Verification:*
- Confirm that the build process exits with code 0.
- Verify the output installer `.exe` exists in the output directory (e.g. `installer/Output/` or `dist/`) and has a valid file size (>10 MB).

---

### Step 4: Commit and Git Tag
Once the installer is built and verified:

1. Stage all pending changes, updated version files, and changelog:
   ```powershell
   git add .
   ```
2. Commit with a standardized release message:
   ```powershell
   git commit -m "Release vX.Y.Z"
   ```
3. Create an annotated Git tag:
   ```powershell
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   ```
4. Push both the commit and tag to the remote repository:
   ```powershell
   git push origin main
   git push origin vX.Y.Z
   ```

---

### Step 5: Publish Release to GitHub
Execute the project release publisher:

```powershell
python scripts/publish_release.py
```

*This script will:*
- Read the release notes for the new version from `CHANGELOG.md`.
- Upload the newly built public installer executable to the GitHub release.
- Tag and mark the release as the **Latest Release**.

---

### Step 6: Summary & Confirmation
Provide the user with a final summary containing:
- New released version (e.g. `v1.3.2`)
- Git commit hash & tag
- Path and size of the generated installer executable
- Direct link to the GitHub release
