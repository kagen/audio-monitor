# Audio Monitor (Windows 11 System Audio Pattern Matcher)

Real-time system audio monitor for Windows 11. Captures **speaker output** (not microphone) using WASAPI Loopback, compares against a reference WAV file, and triggers a notification when similarity exceeds 90%.

## Features

- **System Audio Capture**: Uses WASAPI Loopback to listen to what your PC plays (browsers, music, games, etc.)
- **Real-time Visualization**: Live waveform, reference waveform, and match score history
- **3 Match Algorithms**: Time-domain correlation, spectral similarity, MFCC (via librosa)
- **Adjustable Threshold**: 50% - 100% match sensitivity
- **RMS Volume Meter**: Visual confirmation that audio is being captured
- **Windows Toast Notifications**: Native Win10/11 toast on match

## Requirements

- Windows 10/11
- Python 3.10+

## Installation

```bash
pip install -r requirements.txt
```

**Note**: `PyAudioWPatch` is required for system audio capture. Standard `PyAudio` will NOT work.

## Usage

1. Place your target audio as `reference.wav` (or use the auto-generated test file)
2. Run the monitor:
   ```bash
   python main.py
   ```
3. Click **Scan Loopback Devices** to find your system audio device
4. Select the device and click **Start Monitor**
5. Play any audio on your PC — when it matches `reference.wav`, you get a notification

## Troubleshooting

### No audio signal (RMS stays at 0%)

1. Make sure you selected a **Loopback** device, not a microphone
2. Click **Show All Devices (Debug)** to verify WASAPI devices are available
3. In Windows Sound settings, disable **Audio Enhancements** for your output device
4. Ensure your output device is set as **Default Device** in Windows

### "No WASAPI Loopback device found"

- Install `PyAudioWPatch` (not standard `PyAudio`):
  ```bash
  pip uninstall pyaudio pyaudiowpatch
  pip install PyAudioWPatch
  ```

## License

MIT


## Build Standalone EXE

### Option 1: Local Build (Windows)

```bash
# Install PyInstaller
pip install pyinstaller

# Build
python build.py
```

Output: `dist/AudioMonitor.exe`

### Option 2: GitHub Actions (Automatic)

Every push to `main` branch automatically builds and uploads the EXE as a GitHub Release.

To trigger manually:
- Go to **Actions** tab in your GitHub repo
- Select **Build Windows EXE**
- Click **Run workflow**

### Option 3: Advanced (spec file)

```bash
pyinstaller AudioMonitor.spec
```
