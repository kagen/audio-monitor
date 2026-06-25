#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 11 System Audio Monitor (WASAPI Loopback)
Captures system output (speakers/headphones), NOT microphone.
Triggers notification when system plays audio matching reference.wav

Requirements:
    pip install -r requirements.txt

Usage:
    python main.py
"""

import numpy as np
import threading
import queue
import time
import os
import sys
import logging
import ctypes
from datetime import datetime
from scipy import signal
from scipy.io import wavfile as scipy_wavfile

# GUI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib import font_manager as fm, rcParams

# ============ Font Setup (Japanese Windows 11 compatible) ============
_font_candidates = [
    "C:/Windows/Fonts/YuGothR.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "C:/Windows/Fonts/segoeui.ttf",
]
_font_ok = False
for fp in _font_candidates:
    if os.path.exists(fp):
        try:
            fm.fontManager.addfont(fp)
            prop = fm.FontProperties(fname=fp)
            rcParams['font.family'] = prop.get_name()
            rcParams['axes.unicode_minus'] = False
            _font_ok = True
            break
        except Exception:
            pass
if not _font_ok:
    rcParams['font.sans-serif'] = ['Yu Gothic UI', 'Meiryo UI', 'MS Gothic', 'Segoe UI', 'DejaVu Sans']
    rcParams['axes.unicode_minus'] = False

# ============ Config ============
CONFIG = {
    "sample_rate": 44100,
    "channels": 2,
    "block_size": 2048,
    "match_threshold": 0.90,
    "window_sec": 2.0,
    "display_sec": 3.0,
    "notification_cooldown": 5,
    "match_mode": "correlation",
}

# ============ Logging ============
class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.see(tk.END)
            self.text_widget.configure(state='disabled')
        self.text_widget.after(0, append)

# ============ Audio Capture: PyAudioWPatch WASAPI Loopback ============
class SystemAudioCapture:
    """
    Capture system audio output using PyAudioWPatch WASAPI Loopback.
    This listens to what the speakers/headphones play, NOT the microphone.
    """
    def __init__(self, config):
        self.config = config
        self.sample_rate = config["sample_rate"]
        self.channels = config["channels"]
        self.block_size = config["block_size"]
        self.p = None
        self.stream = None
        self.running = False
        self.buffer = np.zeros(int(self.sample_rate * config["display_sec"]), dtype=np.float32)
        self.lock = threading.Lock()
        self.device_name = None
        self.actual_sample_rate = config["sample_rate"]
        self.actual_channels = config["channels"]
        self.rms_level = 0.0

    def _get_pyaudio(self):
        try:
            import pyaudiowpatch as pyaudio
            return pyaudio, True
        except ImportError:
            try:
                import pyaudio
                logging.warning("PyAudioWPatch not found! System audio capture will NOT work.")
                return pyaudio, False
            except ImportError:
                return None, False

    def get_loopback_devices(self):
        pa, has_wpatch = self._get_pyaudio()
        if not has_wpatch:
            return []
        p = pa.PyAudio()
        devices = []
        try:
            for info in p.get_loopback_device_info_generator():
                devices.append({
                    'index': info['index'],
                    'name': info['name'],
                    'channels': info['maxInputChannels'],
                    'sample_rate': int(info['defaultSampleRate']),
                    'hostApi': info['hostApi']
                })
        except Exception as e:
            logging.error(f"Failed to get loopback devices: {e}")
        finally:
            p.terminate()
        return devices

    def get_default_loopback(self):
        pa, has_wpatch = self._get_pyaudio()
        if not has_wpatch:
            return None
        p = pa.PyAudio()
        try:
            info = p.get_default_wasapi_loopback()
            return {
                'index': info['index'],
                'name': info['name'],
                'channels': info['maxInputChannels'],
                'sample_rate': int(info['defaultSampleRate']),
            }
        except Exception as e:
            logging.warning(f"Cannot get default loopback: {e}")
            return None
        finally:
            p.terminate()

    def get_all_devices(self):
        pa, has_wpatch = self._get_pyaudio()
        if pa is None:
            return []
        p = pa.PyAudio()
        devices = []
        try:
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                host_api = p.get_host_api_info_by_index(info['hostApi'])['name'] if 'hostApi' in info else ''
                devices.append({
                    'index': i,
                    'name': info.get('name', ''),
                    'inch': info.get('maxInputChannels', 0),
                    'outch': info.get('maxOutputChannels', 0),
                    'sr': int(info.get('defaultSampleRate', 0)),
                    'host': host_api,
                })
        finally:
            p.terminate()
        return devices

    def start(self, device_info=None):
        pa, has_wpatch = self._get_pyaudio()
        if pa is None:
            logging.error("PyAudio not installed")
            return False
        if not has_wpatch:
            logging.error("PyAudioWPatch is REQUIRED. Install: pip install PyAudioWPatch")
            return False

        self.p = pa.PyAudio()

        if device_info is None:
            device_info = self.get_default_loopback()

        if device_info is None:
            loopbacks = self.get_loopback_devices()
            if loopbacks:
                device_info = loopbacks[0]
            else:
                logging.error("No WASAPI Loopback device found.")
                self.p.terminate()
                return False

        self.device_name = device_info['name']
        self.actual_sample_rate = device_info.get('sample_rate', self.sample_rate)
        self.actual_channels = min(device_info.get('channels', 2), self.channels)

        logging.info(f"Opening Loopback: [{device_info['index']}] {self.device_name}")
        logging.info(f"  SR: {self.actual_sample_rate} Hz, CH: {self.actual_channels}")

        try:
            self.stream = self.p.open(
                format=pa.paInt16,
                channels=self.actual_channels,
                rate=self.actual_sample_rate,
                input=True,
                input_device_index=device_info['index'],
                frames_per_buffer=self.block_size,
                stream_callback=self._callback
            )
            self.stream.start_stream()
            self.running = True
            logging.info("Capture stream started")
            return True
        except Exception as e:
            logging.error(f"Failed to open stream: {e}")
            self.p.terminate()
            return False

    def _callback(self, in_data, frame_count, time_info, status_flags):
        data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)

        if self.actual_channels > 1:
            data = data.reshape(-1, self.actual_channels)
            mono = np.mean(data, axis=1).astype(np.float32)
        else:
            mono = data

        mono = mono / 32768.0

        if len(mono) > 0:
            self.rms_level = np.sqrt(np.mean(mono ** 2))

        if self.actual_sample_rate != self.config["sample_rate"]:
            ratio = self.config["sample_rate"] / self.actual_sample_rate
            new_len = int(len(mono) * ratio)
            if new_len > 0:
                mono = signal.resample(mono, new_len)

        with self.lock:
            n = len(mono)
            self.buffer = np.roll(self.buffer, -n)
            self.buffer[-n:] = mono
        return (None, 0)

    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.p:
            self.p.terminate()
        logging.info("Capture stopped")

    def get_buffer(self):
        with self.lock:
            return self.buffer.copy()

    def get_match_window(self, window_sec):
        samples = int(self.config["sample_rate"] * window_sec)
        with self.lock:
            if len(self.buffer) >= samples:
                return self.buffer[-samples:].copy()
            return None


# ============ Waveform Matcher ============
class WaveformMatcher:
    def __init__(self, config):
        self.config = config
        self.reference = None
        self.ref_len = 0
        self.ref_fft = None
        self.ref_time = None

    def load_reference(self, filepath):
        try:
            sr, data = scipy_wavfile.read(filepath)
            if sr != self.config["sample_rate"]:
                num = int(len(data) * self.config["sample_rate"] / sr)
                data = signal.resample(data, num)
            if len(data.shape) > 1:
                data = np.mean(data, axis=1)
            data = data.astype(np.float32)
            if np.max(np.abs(data)) > 1.0:
                data = data / 32768.0
            self.reference = data
            self.ref_len = len(data)
            self.ref_fft = np.fft.rfft(data)
            self.ref_time = np.linspace(0, self.ref_len / self.config["sample_rate"], self.ref_len)
            logging.info(f"Reference loaded: {os.path.basename(filepath)} ({self.ref_len/self.config['sample_rate']:.2f}s)")
            return True
        except Exception as e:
            logging.error(f"Failed to load reference: {e}")
            return False

    def compute_similarity(self, audio_window):
        if self.reference is None or audio_window is None or len(audio_window) < self.ref_len:
            return 0.0
        mode = self.config["match_mode"]
        test = audio_window[-self.ref_len:]

        if mode == "correlation":
            test_norm = (test - np.mean(test)) / (np.std(test) + 1e-10)
            ref_norm = (self.reference - np.mean(self.reference)) / (np.std(self.reference) + 1e-10)
            corr = np.correlate(test_norm, ref_norm, mode='valid')
            if len(corr) > 0:
                score = np.max(corr) / len(ref_norm)
                return float(np.clip(score, 0, 1))

        elif mode == "spectral":
            test_fft = np.fft.rfft(test)
            ref_mag = np.abs(self.ref_fft)
            test_mag = np.abs(test_fft)
            dot = np.dot(ref_mag, test_mag)
            norm = np.linalg.norm(ref_mag) * np.linalg.norm(test_mag) + 1e-10
            return float(dot / norm)

        elif mode == "mfcc":
            try:
                import librosa
                ref_mfcc = librosa.feature.mfcc(y=self.reference, sr=self.config["sample_rate"], n_mfcc=13, hop_length=512)
                test_mfcc = librosa.feature.mfcc(y=test, sr=self.config["sample_rate"], n_mfcc=13, hop_length=512)
                min_frames = min(ref_mfcc.shape[1], test_mfcc.shape[1])
                ref_vec = ref_mfcc[:, :min_frames].flatten()
                test_vec = test_mfcc[:, :min_frames].flatten()
                from scipy.spatial.distance import cosine
                return float(1 - cosine(ref_vec, test_vec))
            except ImportError:
                logging.warning("librosa not found, falling back to correlation")
                self.config["match_mode"] = "correlation"
                return self.compute_similarity(audio_window)
        return 0.0


# ============ Notifier ============
class Notifier:
    def __init__(self, cooldown=5):
        self.cooldown = cooldown
        self.last_time = 0
        self.toaster = None
        try:
            from win10toast import ToastNotifier
            self.toaster = ToastNotifier()
        except ImportError:
            pass

    def set_cooldown(self, sec):
        self.cooldown = sec

    def notify(self, similarity):
        now = time.time()
        if now - self.last_time < self.cooldown:
            return
        self.last_time = now
        msg = f"Match: {similarity*100:.1f}%"
        try:
            if self.toaster:
                self.toaster.show_toast("Audio Pattern Matched", msg, duration=5, threaded=True)
            else:
                ctypes.windll.user32.MessageBoxW(0, msg, "Audio Monitor", 0x40)
        except Exception as e:
            logging.error(f"Notification failed: {e}")


# ============ GUI ============
class AudioMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("System Audio Monitor (Loopback)")
        self.root.geometry("1200x900")
        self.root.minsize(1000, 750)

        self.config = CONFIG.copy()
        self.capture = SystemAudioCapture(self.config)
        self.matcher = WaveformMatcher(self.config)
        self.notifier = Notifier(self.config["notification_cooldown"])

        self.is_running = False
        self.match_history = []
        self.max_history = 200
        self.selected_device = None

        self._build_ui()
        self._setup_logging()
        self._start_ui_update()

    def _build_ui(self):
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_frame = ttk.LabelFrame(main_pane, text="Control Panel", padding=10)
        main_pane.add(left_frame, weight=1)

        # Reference file
        ttk.Label(left_frame, text="Reference WAV:").pack(anchor=tk.W, pady=(0,2))
        file_frame = ttk.Frame(left_frame)
        file_frame.pack(fill=tk.X, pady=(0,10))
        self.file_var = tk.StringVar(value="Not loaded")
        ttk.Entry(file_frame, textvariable=self.file_var, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(file_frame, text="Browse...", command=self._load_file).pack(side=tk.RIGHT, padx=(5,0))

        # Loopback Device
        ttk.Label(left_frame, text="Loopback Device:", foreground='blue').pack(anchor=tk.W, pady=(5,2))
        self.device_var = tk.StringVar(value="Auto-detect")
        self.device_combo = ttk.Combobox(left_frame, textvariable=self.device_var, state="readonly", width=35)
        self.device_combo.pack(fill=tk.X, pady=(0,5))
        ttk.Button(left_frame, text="Scan Loopback Devices", command=self._refresh_loopback_devices).pack(fill=tk.X, pady=(0,5))
        ttk.Button(left_frame, text="Show All Devices (Debug)", command=self._show_all_devices).pack(fill=tk.X, pady=(0,10))

        # Volume indicator
        ttk.Label(left_frame, text="Input Level (RMS):", foreground='green').pack(anchor=tk.W, pady=(5,2))
        self.volume_bar = ttk.Progressbar(left_frame, orient=tk.HORIZONTAL, length=200, mode='determinate', maximum=100)
        self.volume_bar.pack(fill=tk.X, pady=(0,5))
        self.volume_label = ttk.Label(left_frame, text="0.0%")
        self.volume_label.pack(anchor=tk.W, pady=(0,10))

        # Match mode
        ttk.Label(left_frame, text="Match Algorithm:").pack(anchor=tk.W, pady=(5,2))
        self.mode_var = tk.StringVar(value="correlation")
        mode_combo = ttk.Combobox(left_frame, textvariable=self.mode_var, 
                                  values=["correlation", "spectral", "mfcc"], state="readonly")
        mode_combo.pack(fill=tk.X, pady=(0,10))
        mode_combo.bind("<<ComboboxSelected>>", lambda e: self.config.update({"match_mode": self.mode_var.get()}))

        # Threshold
        ttk.Label(left_frame, text="Match Threshold:").pack(anchor=tk.W, pady=(5,2))
        thresh_frame = ttk.Frame(left_frame)
        thresh_frame.pack(fill=tk.X, pady=(0,10))
        self.thresh_var = tk.DoubleVar(value=90.0)
        self.thresh_slider = ttk.Scale(thresh_frame, from_=50, to=100, orient=tk.HORIZONTAL, 
                                       variable=self.thresh_var, command=self._on_thresh_change)
        self.thresh_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.thresh_label = ttk.Label(thresh_frame, text="90.0%", width=6)
        self.thresh_label.pack(side=tk.RIGHT, padx=(5,0))

        # Cooldown
        ttk.Label(left_frame, text="Notify Cooldown (sec):").pack(anchor=tk.W, pady=(5,2))
        self.cooldown_var = tk.IntVar(value=5)
        ttk.Spinbox(left_frame, from_=1, to=60, textvariable=self.cooldown_var, 
                    command=lambda: self.notifier.set_cooldown(self.cooldown_var.get())).pack(fill=tk.X, pady=(0,10))

        # Buttons
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=15)
        self.start_btn = ttk.Button(btn_frame, text="Start Monitor", command=self._start_monitor)
        self.start_btn.pack(fill=tk.X, pady=(0,5))
        self.stop_btn = ttk.Button(btn_frame, text="Stop Monitor", command=self._stop_monitor, state='disabled')
        self.stop_btn.pack(fill=tk.X)

        # Status
        self.status_frame = ttk.LabelFrame(left_frame, text="Status", padding=5)
        self.status_frame.pack(fill=tk.X, pady=10)
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(self.status_frame, textvariable=self.status_var, font=('Segoe UI', 10, 'bold')).pack()

        # Score
        self.score_var = tk.StringVar(value="0.0%")
        self.score_label = tk.Label(left_frame, textvariable=self.score_var, font=('Arial', 36, 'bold'), 
                                    fg='gray', bg='#f0f0f0')
        self.score_label.pack(pady=15)

        # Indicator
        self.indicator = tk.Canvas(left_frame, width=60, height=60, bg='#f0f0f0', highlightthickness=0)
        self.indicator.pack()
        self.indicator.create_oval(10, 10, 50, 50, fill='gray', tags='light')

        # Right Panel
        right_frame = ttk.Frame(main_pane)
        main_pane.add(right_frame, weight=3)

        fig = Figure(figsize=(10, 9), dpi=100, facecolor='#fafafa')
        gs = fig.add_gridspec(3, 1, height_ratios=[1,1,0.8], hspace=0.35)

        self.ax_live = fig.add_subplot(gs[0])
        self.ax_live.set_title('System Live Audio (Loopback)', fontsize=12, fontweight='bold')
        self.ax_live.set_xlabel('Time (s)')
        self.ax_live.set_ylabel('Amplitude')
        self.ax_live.set_ylim(-1.2, 1.2)
        self.ax_live.grid(True, alpha=0.3)
        self.line_live, = self.ax_live.plot([], [], 'b-', lw=0.8, alpha=0.8)

        self.ax_ref = fig.add_subplot(gs[1])
        self.ax_ref.set_title('Reference Waveform', fontsize=12, fontweight='bold')
        self.ax_ref.set_xlabel('Time (s)')
        self.ax_ref.set_ylabel('Amplitude')
        self.ax_ref.set_ylim(-1.2, 1.2)
        self.ax_ref.grid(True, alpha=0.3)
        self.line_ref, = self.ax_ref.plot([], [], 'g-', lw=1.0)

        self.ax_hist = fig.add_subplot(gs[2])
        self.ax_hist.set_title('Match Score History', fontsize=12, fontweight='bold')
        self.ax_hist.set_xlabel('Frame')
        self.ax_hist.set_ylabel('Similarity')
        self.ax_hist.set_ylim(0, 1.1)
        self.ax_hist.grid(True, alpha=0.3)
        self.line_hist, = self.ax_hist.plot([], [], 'c-', lw=1.5)
        self.threshold_line = self.ax_hist.axhline(y=0.9, color='red', linestyle='--', linewidth=2)

        self.canvas = FigureCanvasTkAgg(fig, master=right_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Log
        bottom_frame = ttk.LabelFrame(self.root, text="Log", padding=5)
        bottom_frame.pack(fill=tk.BOTH, expand=False, padx=5, pady=(0,5))
        self.log_text = scrolledtext.ScrolledText(bottom_frame, height=8, state='disabled', font=('Consolas', 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self._refresh_loopback_devices()

    def _refresh_loopback_devices(self):
        devices = self.capture.get_loopback_devices()
        self._device_map = {}
        names = ["Auto-detect (Default Speakers)"]
        for dev in devices:
            display = f"[{dev['index']}] {dev['name']} ({dev['channels']}ch, {dev['sample_rate']}Hz)"
            names.append(display)
            self._device_map[display] = dev
        self.device_combo['values'] = names
        if len(devices) == 0:
            logging.warning("No Loopback devices found!")
        else:
            logging.info(f"Found {len(devices)} Loopback device(s)")
            for d in devices:
                logging.info(f"  [{d['index']}] {d['name']}")

    def _show_all_devices(self):
        devices = self.capture.get_all_devices()
        logging.info("=" * 50)
        logging.info("ALL AUDIO DEVICES:")
        for d in devices:
            marker = ""
            if d['host'] == 'Windows WASAPI':
                if 'loopback' in d['name'].lower():
                    marker = " <-- LOOPBACK!"
                else:
                    marker = " [WASAPI]"
            logging.info(f"  [{d['index']}] {d['name']} | IN:{d['inch']} OUT:{d['outch']} | {d['sr']}Hz | {d['host']}{marker}")
        logging.info("=" * 50)

    def _get_selected_device(self):
        sel = self.device_var.get()
        if sel == "Auto-detect (Default Speakers)":
            return None
        return self._device_map.get(sel, None)

    def _setup_logging(self):
        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S'))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def _on_thresh_change(self, val):
        v = float(val)
        self.thresh_label.config(text=f"{v:.1f}%")
        self.config["match_threshold"] = v / 100.0
        if hasattr(self, 'threshold_line'):
            self.threshold_line.set_ydata([v/100.0, v/100.0])
            self.canvas.draw_idle()

    def _load_file(self):
        path = filedialog.askopenfilename(
            title="Select Reference WAV",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")]
        )
        if path:
            if self.matcher.load_reference(path):
                self.file_var.set(os.path.basename(path))
                self._update_ref_plot()
            else:
                messagebox.showerror("Error", "Failed to load reference audio")

    def _update_ref_plot(self):
        if self.matcher.reference is not None and self.matcher.ref_time is not None:
            self.line_ref.set_data(self.matcher.ref_time, self.matcher.reference)
            self.ax_ref.set_xlim(0, self.matcher.ref_time[-1])
            self.ax_ref.relim()
            self.ax_ref.autoscale_view()
            self.canvas.draw_idle()

    def _start_monitor(self):
        if self.matcher.reference is None:
            messagebox.showwarning("Hint", "Please load a reference WAV file first")
            return

        device_info = self._get_selected_device()
        if not self.capture.start(device_info):
            msg = (
                "Failed to start audio capture.\n\n"
                "1. Install PyAudioWPatch: pip install PyAudioWPatch\n"
                "2. Disable audio enhancements in Sound Control Panel\n"
                "3. Click 'Show All Devices (Debug)' to check available devices"
            )
            messagebox.showerror("Audio Capture Error", msg)
            return

        self.is_running = True
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.status_var.set("MONITORING")
        self.score_label.config(fg='orange')

        self.match_thread = threading.Thread(target=self._match_loop, daemon=True)
        self.match_thread.start()
        logging.info("Monitor started")

    def _stop_monitor(self):
        self.is_running = False
        self.capture.stop()
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.status_var.set("Stopped")
        self.score_var.set("0.0%")
        self.score_label.config(fg='gray')
        self.indicator.itemconfig('light', fill='gray')
        self.volume_bar['value'] = 0
        self.volume_label.config(text="0.0%")
        logging.info("Monitor stopped")

    def _match_loop(self):
        while self.is_running and self.capture.running:
            window = self.capture.get_match_window(self.config["window_sec"])
            if window is not None:
                score = self.matcher.compute_similarity(window)
                self.match_history.append(score)
                if len(self.match_history) > self.max_history:
                    self.match_history.pop(0)
                if score >= self.config["match_threshold"]:
                    self.notifier.notify(score)
                    self.root.after(0, self._trigger_alert, score)
            time.sleep(0.05)

    def _trigger_alert(self, score):
        self.score_label.config(fg='red')
        self.indicator.itemconfig('light', fill='red')
        self.status_var.set(f"MATCH! {score*100:.1f}%")
        logging.warning(f"PATTERN MATCHED! Similarity: {score*100:.2f}%")
        self.root.after(500, lambda: self.score_label.config(fg='orange'))
        self.root.after(500, lambda: self.indicator.itemconfig('light', fill='orange'))
        self.root.after(500, lambda: self.status_var.set("MONITORING"))

    def _start_ui_update(self):
        self._update_plots()
        self.root.after(50, self._start_ui_update)

    def _update_plots(self):
        if not self.is_running:
            return
        buf = self.capture.get_buffer()
        if buf is not None and len(buf) > 0:
            t = np.linspace(0, len(buf)/self.config["sample_rate"], len(buf))
            self.line_live.set_data(t, buf)
            self.ax_live.set_xlim(0, t[-1])
        rms = self.capture.rms_level
        pct = min(rms * 100 * 3, 100)
        self.volume_bar['value'] = pct
        self.volume_label.config(text=f"{pct:.1f}% {'(NO SIGNAL!)' if pct < 1 else ''}")
        if pct < 1 and self.is_running:
            self.volume_label.config(foreground='red')
        else:
            self.volume_label.config(foreground='black')
        if self.match_history:
            current = self.match_history[-1]
            self.score_var.set(f"{current*100:.1f}%")
            color = 'red' if current >= self.config["match_threshold"] else ('orange' if current >= 0.7 else 'green')
            self.score_label.config(fg=color)
            self.indicator.itemconfig('light', fill=color)
            x = np.arange(len(self.match_history))
            self.line_hist.set_data(x, self.match_history)
            self.ax_hist.set_xlim(0, max(len(self.match_history), self.max_history))
        self.canvas.draw_idle()


# ============ Entry ============
def main():
    try:
        import scipy
    except ImportError:
        print("Missing: scipy")
        print("pip install numpy scipy matplotlib")
        sys.exit(1)

    root = tk.Tk()
    app = AudioMonitorGUI(root)

    if not os.path.exists("reference.wav"):
        logging.info("Creating test reference.wav (1kHz sine, 2s)...")
        t = np.linspace(0, 2, 88200)
        wave = 0.5 * np.sin(2 * np.pi * 1000 * t)
        wave = (wave * 32767).astype(np.int16)
        scipy_wavfile.write("reference.wav", 44100, wave)
        logging.info("Test reference.wav created. Replace with your target audio.")

    root.mainloop()

if __name__ == "__main__":
    main()
