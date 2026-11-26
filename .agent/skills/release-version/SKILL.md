---
name: release-version
description: Validate changes with tests and release audit in parallel with building Private, Public, and Microsoft Store MSIX packages, bump patch version (+1 to third number), publish the public installer to GitHub Releases, and upload the Store MSIX to Microsoft Partner Center.
---

# Release Version Skill

This skill executes the release pipeline for Opening Fenix. It bumps the patch version (`X.Y.Z -> X.Y.Z+1`), runs the quality gate while building **Private (`Private.exe`), Public (`Public.exe`), and Microsoft Store (`Store.msix`) packages**, verifies that all checks and builds succeed, commits and tags the repository, publishes the **Public installer** to GitHub as the latest release, and uploads the **Store MSIX** to Microsoft Store via `msstore` CLI (or warns with manual instructions if not yet configured).

## Golden Rules
- **Never discard uncommitted code**: Do not run destructive cleanup commands like `git clean -fd`. User work must be preserved and committed as part of the release.
- **Fail Fast & Abort Gate**: If either the audit/tests or any package build (`build_installer.py` / `build_msix.py`) fails, abort the release immediately. Do not commit or push to GitHub.
- **Single Source of Truth**: The version must be kept identical across `opening_fenix/core/version.py`, `installer/OpeningFenix_Setup.iss`, and `CHANGELOG.md` (`build_msix.py` reads `APP_VERSION` automatically).
- **Patch Bumps Only**: Always increment the third number by +1 (e.g. `1.3.1` -> `1.3.2`).
- **Build All Release Packages**: Always generate `Private.exe` (local personal use), `Public.exe` (clean public distribution), and `OpeningFenixChess_vX.Y.Z_Store.msix` (Microsoft Store distribution).
- **Read-Only Cloud Repertoire Sync (Warn, Don't Abort)**: Before building installers, run a strictly one-way, read-only sync from `C:\Users\Felix\Meine Ablage (felix.brunner12@gmail.com)\Schach\Programme\Opening Fenix\cloud_sync\repertoires` into local `repertoires/`. **NEVER** write, rename, move, or delete anything inside the cloud folder. Local-only repertoires are left untouched. If the cloud folder is unavailable, empty, or partially fails, **do not abort the release** — continue with local `repertoires/` and prominently alert the user in the final summary.
- **Clean Previous Installer Builds**: Before building new packages, delete any previous `Output\OpeningFenix_Setup_*.exe` and `Output\OpeningFenixChess_v*_Store*.msix` builds (leaving other subdirectories like `display_audit` intact).
- **No Test Downgrades**: Run all 900+ tests without skipping any, utilizing multi-core parallelism (`pytest-xdist`) across available CPU cores with headless Qt.

---

## Execution Workflow

All commands must be executed from the project root where `.git`, `scripts/`, and `main.py` reside (i.e. `Opening-Fenix/Opening-Fenix`).

### Step 1: Version Bumping (Patch Increment)
*First update version files so all packages embed the correct new version:*

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

### Step 1.5: One-Way Cloud Repertoire Sync (Read-Only)
*Before building the installers, pull the latest `.fenixsync.zip` repertoires from Google Drive into local `repertoires/` so `Private.exe` includes the freshest repertoires:*

```powershell
py scripts/sync_cloud_repertoires.py
$cloudSyncExitCode = $LASTEXITCODE
```

- **Strictly read-only on Cloud**: The script only reads `*.fenixsync.zip` files from `C:\Users\Felix\Meine Ablage (felix.brunner12@gmail.com)\Schach\Programme\Opening Fenix\cloud_sync\repertoires` and never modifies the cloud folder.
- **Additive local update**: Adds new repertoires and replaces matching local folders with the latest cloud version; local-only repertoires are left untouched.
- **Warn, don't abort**: If `$cloudSyncExitCode -ne 0` (e.g. Google Drive is offline/unmounted, empty, or an archive failed), record the warning message and **continue with the release** using the existing local `repertoires/`. Make sure to highlight this warning prominently in Step 5 (Summary & Confirmation).

---

### Step 2: Concurrent Build (Installers + Store MSIX) & Quality Gate
First remove any previous installer and MSIX builds from `Output\`, then launch Job 1 (building Private + Public installers followed by the Store MSIX) and Job 2 (audit + all tests) simultaneously:

```powershell
# Remove previous installer and MSIX builds
Remove-Item -Force "Output\OpeningFenix_Setup_*.exe" -ErrorAction SilentlyContinue
Remove-Item -Force "Output\OpeningFenixChess_v*_Store*.msix" -ErrorAction SilentlyContinue

# In PowerShell, run both jobs concurrently:
$buildJob = Start-Job -ScriptBlock {
    Set-Location $args[0]
    # Build BOTH Private and Public installers
    py scripts/build_installer.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Build unsigned Microsoft Store MSIX reusing the PyInstaller bundle
    py scripts/build_msix.py --skip-build
    exit $LASTEXITCODE
} -ArgumentList (Get-Location).Path

$testJob = Start-Job -ScriptBlock {
    Set-Location $args[0]
    # Headless Qt (avoids desktop window compositor overhead and focus stealing)
    $env:QT_QPA_PLATFORM = "offscreen"
    
    # Run release audit first (translations, asset paths, hygiene)
    py scripts/run_release_audit.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    
    # Run all tests using all CPU cores with file isolation and clean console output
    py -m pytest -n auto --dist=loadfile -q --tb=short
    exit $LASTEXITCODE
} -ArgumentList (Get-Location).Path

# Wait for both background jobs to finish
Wait-Job $buildJob, $testJob | Out-Null

$buildResult = Receive-Job $buildJob
$testResult  = Receive-Job $testJob

$buildSuccess = ($buildJob.State -eq 'Completed' -and $buildJob.ChildJobs[0].ExitCode -eq 0)
$testSuccess  = ($testJob.State -eq 'Completed' -and $testJob.ChildJobs[0].ExitCode -eq 0)

Remove-Job $buildJob, $testJob
```

#### Verification & Abort Gate:
1. **Audit & Test Validation**:
   - Confirm localization parity (`de.json` vs `en.json`), valid asset paths, and zero test failures across all tests.
   - If tests or audit failed, display output and **abort immediately**.
2. **Release Artifacts Validation**:
   - Confirm that `build_installer.py` and `build_msix.py` finished with exit code 0.
   - Verify that all **three** packages exist in `Output/` and are >10 MB:
     - `Output\OpeningFenix_Setup_vX.Y.Z_Private.exe` (>10 MB)
     - `Output\OpeningFenix_Setup_vX.Y.Z_Public.exe` (>10 MB)
     - `Output\OpeningFenixChess_vX.Y.Z_Store.msix` (>10 MB)
   - If any artifact is missing or corrupt, display output and **abort immediately**.

---

### Step 3: Git Commit and Tag
Once both Job 1 and Job 2 have passed with flying colors:

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

### Step 4: Publish Public Release to GitHub
Execute the project release publisher:

```powershell
py scripts/publish_release.py
```

*This script will:*
- Read the release notes for the new version from `CHANGELOG.md`.
- Upload only the **Public installer** (`OpeningFenix_Setup_vX.Y.Z_Public.exe`) to GitHub.
- Tag and mark the release as the **Latest Release**.
- Keep your **Private installer** safe and local on your PC.

---

### Step 4.5: Publish to Microsoft Store (Warn, Don't Abort)
Execute the Microsoft Store publisher script:

```powershell
py scripts/publish_msstore.py
$msStoreExitCode = $LASTEXITCODE
```

- **Exit code `0`**: Uploaded and submitted `Output\OpeningFenixChess_vX.Y.Z_Store.msix` automatically via `msstore` CLI.
- **Exit code `2`**: `msstore` CLI is not installed or not configured/authenticated yet — **do not abort** the release. Include a clear manual upload reminder in Step 5 with the exact `.msix` path (`Output\OpeningFenixChess_vX.Y.Z_Store.msix`) and Partner Center URL (`https://partner.microsoft.com/en-us/dashboard/products/9MVN5X4QZ1KL/overview`).
- **Any other non-zero exit code**: Record a prominent warning in Step 5 with the script output so the user can inspect or upload manually (do **not** roll back the already-published GitHub release).

---

### Step 5: Summary & Confirmation
Provide the user with a final summary containing:
- New released version (e.g. `v1.3.2`)
- Local paths to all generated packages:
  - Private: `Output\OpeningFenix_Setup_vX.Y.Z_Private.exe`
  - Public: `Output\OpeningFenix_Setup_vX.Y.Z_Public.exe`
  - Microsoft Store: `Output\OpeningFenixChess_vX.Y.Z_Store.msix`
- Git commit hash & tag
- Direct link to the GitHub release with the public installer
- Microsoft Store upload status (submitted automatically via `msstore` CLI, or a manual upload reminder with the `.msix` path and `https://partner.microsoft.com/en-us/dashboard/products/9MVN5X4QZ1KL/overview`)
- Cloud repertoire sync status (count of added/updated repertoires, or a **prominent warning** if the cloud sync was skipped or had errors so the user knows `Private.exe` used local fallback repertoires)
