# MetaMotion Bricks — Setup Guide

## Prerequisites

| Tool | Minimum version | Check |
|------|----------------|-------|
| macOS | 12 Monterey | `sw_vers` |
| Python | 3.10 | `python3 --version` |
| Homebrew | any | `brew --version` |
| Bluetooth | enabled | System Settings → Bluetooth |

---

## 1  macOS Bluetooth permissions

macOS requires explicit permission for any app to use Bluetooth.

1. **System Settings → Privacy & Security → Bluetooth**
2. Add **Terminal** (or iTerm2 / VS Code, whichever you run Python from)
3. Toggle it **ON**

> Without this, `bleak` will silently find no devices.

---

## 2  Python virtual environment

```bash
# From the project directory
python3 -m venv .venv
source .venv/bin/activate

# Confirm the venv is active
which python   # should show …/Bricks/.venv/bin/python
```

---

## 3  Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### What gets installed

| Package | Purpose |
|---------|---------|
| `bleak` | Cross-platform BLE (no native lib needed) |
| `pygame` | Game engine & rendering |
| `numpy` | Signal processing (optional but useful) |
| `metawear` | Official MbientLab SDK (optional, advanced) |

> `metawear` (the official SDK) requires `libmetawear` native dylib.
> This project uses `bleak` directly so it works without it.
> Install the official SDK only if you need the full firmware pipeline.

---

## 4  Pair the MetaMotion device

### Option A — macOS System Bluetooth (recommended first step)

1. Press the button on the MetaMotion sensor until the LED blinks blue.
2. Open **System Settings → Bluetooth**.
3. Find **MetaWear** or **MetaMotion** in the device list and click **Connect**.
4. Once paired, macOS will remember the device.

> After system pairing, `bleak` can still connect — macOS forwards the BLE
> link to the app. You do **not** need to disconnect from System Bluetooth.

### Option B — Let the app scan and connect directly

Skip system pairing entirely. The sensor needs to be in advertising mode
(LED blinking). The app will scan and connect on its own.

```bash
# Verify the sensor is visible
python main.py --scan
```

Expected output:

```
Scanning for BLE devices (10s)…

MetaMotion / MetaWear devices:
  ✓  MetaMotion S               D5:4A:AA:11:22:33  rssi=-62 dBm
```

Copy the address for use in step 5 if you want to skip future scans.

---

## 5  Run the game

### Auto-scan mode (recommended)

```bash
python main.py
```

The app scans, connects, and starts streaming automatically.

### With a known device address

```bash
python main.py --address D5:4A:AA:11:22:33
```

Skips the scan — connects immediately. Use this if you have multiple BLE
devices nearby.

### Keyboard-only mode (no sensor needed)

```bash
python main.py --keyboard
```

Great for testing the game without hardware.

### Debug HUD (shows live sensor values)

```bash
python main.py --debug
```

Or press **D** in-game at any time.

---

## 6  Sensor orientation

Wear the sensor on your wrist, **face-up** (LED/button facing the ceiling
when your arm rests on a table).

```
         ┌───────────────┐
         │  MetaMotion   │  ← face up
         └───────────────┘
              wrist
```

| Gesture | Action |
|---------|--------|
| Tilt wrist LEFT | Move paddle left |
| Tilt wrist RIGHT | Move paddle right |
| Steeper tilt | Faster paddle |
| Flick wrist upward (quick snap) | Launch ball |
| Rotate wrist clockwise | Curve ball right |
| Rotate wrist counter-clockwise | Curve ball left |

---

## 7  Troubleshooting

### "No MetaMotion device found"

- Confirm the LED is blinking blue (advertising mode). Press the button to restart advertising.
- Run `python main.py --scan` to see all BLE devices nearby.
- Check Terminal has Bluetooth permission (step 1).
- If using a M1/M2/M3 Mac and seeing a `CoreBluetooth` error, try:

  ```bash
  # Run once to grant entitlement (dev builds only)
  codesign --force --deep --sign - .venv/bin/python3
  ```

### "Connection failed: [Errno 1] disconnected"

The sensor went to sleep. Press its button to wake it, then retry.

### Pygame window doesn't open

```bash
# Install SDL2 (pygame dependency)
brew install sdl2 sdl2_image sdl2_mixer sdl2_ttf
pip install --force-reinstall pygame
```

### BLE device list empty on macOS Sonoma / Sequoia

macOS 14+ has stricter BLE scanning restrictions. Make sure:
- Bluetooth is on.
- Terminal / Python has Bluetooth permission.
- The sensor is actively advertising (LED blinking).

### "libmetawear not found" error

This only appears if you installed the `metawear` SDK. This project uses
`bleak` directly and does **not** need `libmetawear`. You can safely ignore
the error, or uninstall the metawear package:

```bash
pip uninstall metawear
```

---

## 8  Official MetaWear SDK (advanced)

If you want to use the full MbientLab firmware pipeline (data processors,
loggers, sensor fusion), install the official SDK:

```bash
# macOS arm64 (M-series)
pip install metawear

# The SDK bundles libmetawear for Intel and Apple Silicon.
# If it fails, download the dylib manually from:
# https://github.com/mbientlab/MetaWear-SDK-C-and-CPP/releases
```

The official SDK's `MetaWear` class can replace `MetaMotionSensor` in
`sensor.py`. See `sensor.py` for the firmware command protocol used by
the bleak-native implementation.

---

## 9  Windows / Linux notes

`bleak` is fully cross-platform. The game works on Windows and Linux
without changes.

**Windows**: run as Administrator the first time (BLE scan may require it).
**Linux**: install `bluez` (`sudo apt install bluez python3-dbus`) and add
your user to the `bluetooth` group.

---

## Project structure

```
Bricks/
├── main.py          Entry point — arg parsing, wires sensor + game
├── sensor.py        BLE connection, IMU streaming (bleak-native)
├── gesture.py       Tilt/flick interpreter → paddle velocity + launch
├── game.py          Pygame bricks game engine
├── requirements.txt Python dependencies
└── SETUP.md         This file
```
