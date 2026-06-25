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

CMD = [
    sys.executable, "-m", "PyInstaller",
    "--name", "AudioMonitor",
    "--onefile",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--hidden-import", "pyaudiowpatch",
    "--hidden-import", "scipy",
    "--hidden-import", "scipy.signal",
    "--hidden-import", "scipy.io.wavfile",
    "--hidden-import", "scipy.spatial.distance",
    "--hidden-import", "numpy",
    "--hidden-import", "matplotlib",
    "--hidden-import", "matplotlib.backends.backend_tkagg",
    "--add-data", "assets;assets",
    "main.py"
]

def main():
    print("Building AudioMonitor.exe...")
    print("This may take a few minutes.")

    result = subprocess.run(CMD, capture_output=False)

    if result.returncode == 0:
        print("\n[OK] Build successful!")
        print("   Output: dist/AudioMonitor.exe")

        if os.path.exists("reference.wav"):
            shutil.copy("reference.wav", "dist/reference.wav")
            print("   Copied reference.wav to dist/")
    else:
        print("\n[ERROR] Build failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
