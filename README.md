# 🦅 Opening Fenix V2

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![UI Framework](https://img.shields.io/badge/UI-PyQt6-green.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)

**Opening Fenix V2** is a modern, high-performance chess repertoire management and training platform. Designed for players of all levels, it combines **Spaced Repetition (SRS)**, **Lichess statistical integration**, **Stockfish evaluation**, and **smart gap analysis** to build an unshakeable opening repertoire.

---

## ✨ Highlights & Key Features

### 🧠 Intelligent Spaced Repetition (SRS) Training
- **Leitner 7-Box System**: Automatically schedules move reviews based on your recall performance (from 5 minutes up to 6 months).
- **Priority-Driven Learning**: Focuses first on the lines you encounter most frequently in real games.
- **Onboarding Guided Tour**: Interactive step-by-step tour for new users to quickly master all controls.
- **Freies Training (Free Practice)**: Practice any repertoire line instantly without altering your SRS progress stats.
- **Dynamic Opening Elo**: Visual estimate of your repertoire mastery progress.

### 🛠️ Repertoire Building & Hole Finder 2.0
- **Interactive Tree Creator**: Add, edit, tag, and organize variations with automatic parent-child level propagation.
- **Rep. Loch Finder (Hole Finder)**: Scans your repertoire against millions of Lichess games to highlight critical lines opponents play that you haven't covered yet.
- **Transposition Awareness**: Automatically handles transpositions so you never repeat work across different move orders.
- **PGN Import / Export**: Bulk import PGN files with automatic sequence repair and comment merging.

### 🌐 Lichess & Engine Integrations
- **Lichess Explorer Data**: View real-world win rates and move frequencies across ELO tiers (Low, Mid, High, Masters).
- **One-Click Microscope**: Instantly open any position in the browser on Lichess for deeper study.
- **Stockfish UCI Engine**: Live evaluation bar, multi-PV move suggestions, and automatic candidate move highlighting.
- **Multilingual Support**: Toggle between English (`Nf3`) and German (`Sf3`) chess notation.

---

## 🚀 Quick Start Guide

Get up and running in under 2 minutes:

```powershell
# 1. Clone the repository
git clone https://github.com/Takais-Chess/Opening-Fenix.git
cd Opening-Fenix

# 2. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# 3. Install required dependencies
pip install -r requirements.txt

# 4. Launch Opening Fenix
python main.py
```

---

## 📖 Documentation & Deep Dives

Explore our dedicated documentation guides for step-by-step tutorials and technical details:

| Guide | Description |
| :--- | :--- |
| 🚀 [**QUICKSTART.md**](QUICKSTART.md) | Step-by-step onboarding guide for creating repertoires, importing PGNs, and starting training. |
| ♟️ [**TECHNICAL_DEEP_DIVE.md**](TECHNICAL_DEEP_DIVE.md) | Algorithmic deep dive into Priority Scores (BFS), Move Selection, Level Reachability, and SRS mechanics. |
| 📋 [**FUTURE_TODO.md**](FUTURE_TODO.md) | Roadmap of upcoming features, community suggestions, and planned enhancements. |
| 📜 [**CHANGELOG.md**](CHANGELOG.md) | Detailed version release history and stability fixes. |

---

## 💻 Running Tests & Building Executables

### Automated Tests
Run the `pytest` suite to verify database integrity, UI state transitions, and core services:
```powershell
$env:PYTHONPATH="."; .\.venv\Scripts\python.exe -m pytest
```

### Standalone Executable
Build a standalone Windows executable (`.exe`):
```powershell
.\build_executable.bat
```

---

## 📂 Project Structure

```
Opening-Fenix/
├── opening_fenix/         # Core application package
│   ├── core/              # Database models, SRS, Priority & Lichess services
│   ├── creator/           # Repertoire Creator & Hole Finder UI
│   └── gui/               # PyQt6 Main Window, Trainer, and custom widgets
├── assets/                # Board textures, SVG piece sets, and sound effects
├── repertoires/           # Dedicated local folders for repertoire databases
├── profiles/              # User progress data, settings, and SRS history
└── tests/                 # Comprehensive pytest suite
```

---

## 🤝 Contributing & Support

Contributions, issue reports, and feature requests are always welcome! Feel free to submit a Pull Request or open an Issue on GitHub.

*Built with ❤️ for the Chess Community*
