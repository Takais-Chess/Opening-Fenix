---
name: release-version
description: Validate changes with tests and release audit in parallel with building both Private and Public installers, bump patch version (+1 to third number), and publish the public installer as a GitHub release.
---

# Release Version Skill

This skill executes the release pipeline for Opening Fenix. It bumps the patch version (`X.Y.Z -> X.Y.Z+1`), runs the quality gate while building **both Private and Public installers simultaneously in parallel**, verifies that all checks and builds succeed, commits and tags the repository, and publishes the **Public installer** to GitHub as the latest release.

## Golden Rules
- **Never discard uncommitted code**: Do not run destructive cleanup commands like `git clean -fd`. User work must be preserved and committed as part of the release.
- **Fail Fast & Abort Gate**: If either the audit/tests or the installer build fails, abort the release immediately. Do not commit or push to GitHub.
- **Single Source of Truth**: The version must be kept identical across `opening_fenix/core/version.py`, `installer/OpeningFenix_Setup.iss`, and `CHANGELOG.md`.
- **Patch Bumps Only**: Always increment the third number by +1 (e.g. `1.3.1` -> `1.3.2`).
- **Build Both Installers**: Always generate both `Private.exe` (local personal use) and `Public.exe` (clean public distribution).
- **No Test Downgrades**: Run all 900+ tests without skipping any, utilizing multi-core parallelism (`pytest-xdist`) across available CPU cores with headless Qt.

---

## Execution Workflow

All commands must be executed from the project root where `.git`, `scripts/`, and `main.py` reside (i.e. `Opening-Fenix/Opening-Fenix`).

### Step 1: Version Bumping (Patch Increment)
*First update version files so both installers package the correct new version:*

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

### Step 2: Concurrent Build (Both Installers) & Quality Gate
Launch Job 1 (building both Private + Public installers) and Job 2 (audit + all tests) simultaneously:

```powershell
# In PowerShell, run both jobs concurrently:
$buildJob = Start-Job -ScriptBlock {
    Set-Location $args[0]
    # Build BOTH Private and Public installers
    py scripts/build_installer.py
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
2. **Both Installers Artifact Validation**:
   - Confirm that `build_installer.py` finished with exit code 0.
   - Verify that **both** installer executables exist in `Output/`:
     - `Output\OpeningFenix_Setup_vX.Y.Z_Private.exe` (>10 MB)
     - `Output\OpeningFenix_Setup_vX.Y.Z_Public.exe` (>10 MB)
   - If either installer is missing or corrupt, display output and **abort immediately**.

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

### Step 5: Summary & Confirmation
Provide the user with a final summary containing:
- New released version (e.g. `v1.3.2`)
- Local paths to both generated installers:
  - Private: `Output\OpeningFenix_Setup_vX.Y.Z_Private.exe`
  - Public: `Output\OpeningFenix_Setup_vX.Y.Z_Public.exe`
- Git commit hash & tag
- Direct link to the GitHub release with the public installer
