# Prompt: Sensor Integration (`shared/sensor.py`)

## Task
Implement a BLE sensor driver that connects to a MbientLab MetaMotion wrist sensor, streams raw IMU data, and feeds it into a thread-safe queue consumed by the gesture interpreter.

## Requirements

### Connection
- Use **bleak** (async BLE library) — no MbientLab native SDK
- Support two connection modes:
  1. **Auto-scan**: scan for any device whose name contains "MetaWear", "MetaMotion", "MWC", or "MMS"
  2. **Direct address**: skip scan if `--address D5:4A:AA:11:22:33` is given
- Scan timeout: 12 seconds (configurable)
- On connection failure: raise `RuntimeError` so `main.py` can fall back to keyboard mode

### IMU Streaming
- Configure **BMI160** accelerometer: ±4g range, 100Hz ODR
- Configure **BMI160** gyroscope: ±500°/s range, 100Hz ODR
- Subscribe to both characteristics; fuse into a single `IMUSample` dataclass per timestamp

### IMUSample dataclass
```python
@dataclass
class IMUSample:
    ax: float   # accelerometer x (g)
    ay: float   # accelerometer y (g)
    az: float   # accelerometer z (g)
    gx: float   # gyroscope x (°/s)
    gy: float   # gyroscope y (°/s)
    gz: float   # gyroscope z (°/s)
    ts: float   # time.monotonic() at receipt
```

### Threading model
- BLE event loop runs in a **daemon background thread** via `asyncio.run()` in a `threading.Thread`
- Parsed `IMUSample` objects are pushed onto a `queue.Queue` (unbounded) — the gesture thread drains it
- The game (pygame) thread never touches the BLE thread directly

### Public API
```python
class MetaMotionSensor:
    data_queue: queue.Queue   # IMUSample stream

    def start_background(self, address: Optional[str] = None) -> None:
        """Connect and start streaming. Blocks until connected or raises RuntimeError."""

    def stop_background(self) -> None:
        """Gracefully disconnect and stop the BLE thread."""
```

## Implementation Notes
- Accelerometer and gyroscope notifications may arrive separately — buffer one until the other arrives, then emit a fused `IMUSample`
- Use `struct.unpack` to parse raw BLE notification bytes (little-endian int16, scaled by range/32768)
- Queue should be bounded or the gesture thread should drain with `get_nowait` to avoid unbounded growth
- Print connection status to stdout (BLE address, RSSI if available)
- On disconnect (sensor goes to sleep): attempt one reconnect, then raise/exit gracefully

## Sensor BLE Protocol (bleak-native, no SDK)
| Register | UUID suffix | Purpose |
|----------|-------------|---------|
| Accel stream | `0x001a` | Raw accel xyz |
| Gyro stream | `0x001c` | Raw gyro xyz |
| Command write | `0x0019` | Enable/disable modules |

Enabling accel 100Hz:
```python
ENABLE_ACCEL = bytes([0x03, 0x03, 0x28, 0x00])   # module 3, cmd 3, ODR=100Hz, range=±4g
```
Gyro is similar on module 5.

## Edge Cases
- Sensor advertises but rejects connection → retry once with 2s delay
- Sensor disconnects mid-game → `data_queue` goes empty; `GestureInterpreter` decays velocity to 0
- Multiple MetaMotion sensors nearby → pick the one with highest RSSI (or accept `--address` to pin)
