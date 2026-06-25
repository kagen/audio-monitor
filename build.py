#!/usr/bin/env python3
"""
Build script: Package main.py into a standalone Windows executable.
Usage:
    python build.py
Output:
    dist/AudioMonitor.exe
"""

import subprocess
import sys
import os
import shutil

# PyInstaller command
CMD = [
    sys.executable, "-m", "PyInstaller",
    "--name", "AudioMonitor",
    "--onefile",           # Single EXE file
    "--windowed",          # No console window (GUI app)
    "--noconfirm",
    "--clean",
    # Hidden imports
    "--hidden-import", "pyaudiowpatch",
    "--hidden-import", "scipy",
    "--hidden-import", "scipy.signal",
    "--hidden-import", "scipy.io.wavfile",
    "--hidden-import", "numpy",
    "--hidden-import", "matplotlib",
    "--hidden-import", "matplotlib.backends.backend_tkagg",
    # Data files
    "--add-data", "assets;assets",
    "main.py"
]

def main():
    print("Building AudioMonitor.exe...")
    print("This may take a few minutes.")

    result = subprocess.run(CMD, capture_output=False)

    if result.returncode == 0:
        print("\n✅ Build successful!")
        print(f"   Output: dist/AudioMonitor.exe")

        # Copy reference.wav to dist if it exists
        if os.path.exists("reference.wav"):
            shutil.copy("reference.wav", "dist/reference.wav")
            print("   Copied reference.wav to dist/")
    else:
        print("\n❌ Build failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
