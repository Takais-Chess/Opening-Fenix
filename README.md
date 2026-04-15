# 🦅 Opening-Fenix
+ **Version 2.4.0 (Stabilized Edition)**

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/UI-PyQt6-green.svg)](https://www.riverbankcomputing.com/software/pyqt/)

Opening-Fenix is a professional chess repertoire management and training platform. Following a **comprehensive 2026 Codebase Audit**, the platform now features enhanced background thread stability, robust Lichess API handling, and a zero-latency database architecture. Designed for both competitive players and enthusiasts, it combines a **premium Glassmorphism UI** with advanced **Spaced Repetition (SRS)** training, local engine analysis, and Lichess statistical data to help you master your openings with ease.

---

## ✨ Key Features

### 🎨 Premium Aesthetics
*   **Glassmorphism Design**: A stunning, high-contrast interface featuring semi-transparent backgrounds, vibrant gradients, and native Qt animations.
*   **4K Ready**: Fully responsive resolution-relative scaling for a crisp experience on any monitor, regardless of DPI settings.
*   **Smooth Piece Movement**: Cubic easing animations and piece "lifting" effects for a natural, high-end feel.

### 🧠 Advanced Training (SRS)
*   **Spaced Repetition System**: A custom mastery-level algorithm (Levels 0-5) that intelligently schedules your move reviews.
*   **Onboarding Guided Tour**: Interactive walkthrough for new profiles to ensure a smooth introduction to all features.
*   **Freies Training (Free Practice)**: Instant, progress-free practice sessions using in-memory databases.
*   **Smart Variation Filtering**: Target specific lines or sub-variations seamlessly within the trainer.

### 🛠️ Repertoire Management (Creator)
*   **Interactive Tree Editor**: Build deep move trees with validation, hierarchical variation naming, and automated name propagation.
*   **Hole Finder 2.0**: Advanced gap detection with transposition awareness, smart level consistency rules, and popularity-based prioritization.
*   **Lichess Data Integration**: Real-time win rates and move frequencies across multiple Elo categories (Low, Mid, High, Masters).
*   **Bulk Analysis**: Automated Stockfish integration to analyze entire repertoires and automatically highlight "Good Moves".
*   **Flexible Import/Export**: Robust PGN handling with automated integrity repair and move-linking during bulk imports.

### 🌐 Integrations & Services
*   **UCI Engine Support**: Deep integration with local UCI engines (e.g., Stockfish) for live evaluation.
*   **Lichess API**: Native support for fetching explorer data and instantly opening positions on Lichess for further analysis.
*   **Robust Persistence**: Automatic detection and recovery system for malformed SQLite databases to prevent data loss.
*   **Multilingual Notation**: Support for localized chess notation (English/German) across the interface.

---

## 🚀 Quick Start

Get running in less than 2 minutes:

1.  **Clone & Enter**:
    ```powershell
    git clone https://github.com/felixbrunner12-lab/Opening-Fenix.git
    cd Opening-Fenix
    ```
2.  **Environment Setup**:
    ```powershell
    python -m venv .venv
    .\.venv\Scripts\activate
    ```
3.  **Install Dependencies**:
    ```powershell
    pip install -r requirements.txt
    ```
4.  **Launch**:
    ```powershell
    python main.py
    ```

---

## 📖 Documentation

For more detailed information, please refer to:
*   [**QUICKSTART.md**](QUICKSTART.md): Step-by-step guide on creating your first repertoire and starting your SRS training.
*   [**TECHNICAL_DEEP_DIVE.md**](TECHNICAL_DEEP_DIVE.md): Detailed explanation of Priority Scores, Level Reachability, and the internal architecture.
*   [**CHANGELOG.md**](CHANGELOG.md): History of updates and new features.

---

## 💻 Development & Deployment

### Testing
We maintain a robust test suite covering core services and UI components.
```powershell
pytest --cov=opening_fenix
```

### Building Executables
Create a standalone Windows `.exe` using the optimized build script:
```powershell
.\build_executable.bat
```

---

## 📂 Project Structure

*   `opening_fenix/`: Main package containing the core logic and GUI.
*   `assets/`: UI assets, including SVG pieces and board themes.
*   `engines/`: Recommended location for UCI engine executables.
*   `repertoires/`: Local storage for your opening databases.
*   `profiles/`: User-specific settings and SRS progress data.

---

## 🤝 Contributing

Contributions are welcome! Whether it's bug reports, feature suggestions, or pull requests, please feel free to contribute to the project.

## 📄 License

This project is licensed under the MIT License - see the `LICENSE` file for details (or TODO: Add license file).

---
*Built with ❤️ for the Chess Community*
