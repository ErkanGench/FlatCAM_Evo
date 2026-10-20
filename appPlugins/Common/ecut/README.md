# E-Cut USB motion controller (appPlugins.Common.ecut)

Python driver for the E-Cut USB HID CNC motion board, written from static analysis of `e-Cut.dll`
(see `docs/mach3/Ecut_Recovered_Protocol/FINDINGS.md`).

## Safety status

- This package has NEVER talked to a real board. No captured USB traffic exists.
- Do not use it to drive real machinery until the unverified items below are validated on hardware.
- It is not wired into the FlatCAM UI, preferences, or any plugin. It is a standalone package.

## Files

| File | Content |
|------|---------|
| `ecut_protocol.py` | HID transport (`EcutUsb`), packet builders, RX decoder, CRC |
| `ecut_config.py` | `EcutBoardConfig` and its dataclasses, JSON save/load |
| `ecut_controller.py` | `EcutAPI` (state machine, G-code subset, motion planning), `encode_config` |
| `__init__.py` | Public exports |
| `API_REFERENCE.md` | Class and method reference |
| `tests/ecut/test_ecut_protocol.py`, `tests/ecut/test_ecut_controller.py` | Offline tests, fake USB layer |
| `docs/mach3/Ecut_Recovered_Protocol/test_ecut_readonly.py` | Read-only DLL evidence checks |

Run the tests:

```
python -m pytest tests/ecut docs/mach3/Ecut_Recovered_Protocol/test_ecut_readonly.py -q
```

## Usage (offline or on a bench with the board and no machine attached)

```python
from appPlugins.Common.ecut import EcutAPI

api = EcutAPI()
api.load_config('machine.json')       # or api.configure_axis(...), api.config.motion_period_s = ...
api.connect()                         # opens the HID device; does NOT push the configuration
api.run_gcode(['G1 X10 Y10 F500'])    # refused unless config.motion_period_s is set
api.disconnect()
```

## Wire format as implemented

- HID output report, assumed 65 bytes: byte 0 is the report ID (0), then 64 payload bytes.
- Motion report: `[0][up to 4 x 16-byte records]`, zero padded. No command byte, no CRC.
- Motion record: `0x69`, 24-bit trajectory ID (big-endian), 6 x signed 16-bit axis deltas (big-endian).
- Command report: `[0][cmd][params, at most 63 bytes]`, zero padded. No CRC.
- Receive report: 65 bytes, big-endian fields, CRC-32 variant (poly 0x04C11DB7, 4 byte-steps per input byte) over bytes 1..60, stored at bytes 61..64.
- Builders raise `ValueError` for oversized or out-of-range input. They never truncate or clip.

## Verified vs unverified

Confirmed from static DLL analysis (not from hardware):

- Motion report framing: records start at payload byte 0, up to 4 records, no command byte, no CRC.
- The TX path calls no CRC routine; the CRC routine is only called when checking received reports.
- RX frame layout and the CRC algorithm (the DLL test vectors reproduce).
- Motion record layout; only the low 24 bits of the trajectory ID are sent.
- Command opcodes listed in `Cmd` (names are our labels).

Unverified (assumptions in the code):

- Output report length of 65 (taken from the RX length; the DLL derives it from the device).
- That the firmware accepts commands without a CRC. "No CRC on TX" is strongly indicated, not proven.
- Command parameter layouts: jog, dwell, SET_DRO values. Guesses.
- Configuration framing: `encode_config()` is an invented layout. It is larger than one packet (63 bytes), so `push_config()` refuses to send it.
- `motion_period_s`, the time one motion record covers. Unknown, so it defaults to `None` and G0/G1 moves are refused before any write.
- VID 0x0483 / PID 0x5750: candidate values from disassembly immediates, not checked against a device.
- E-stop hardware behavior. The software E-stop sends `Cmd.ESTOP`, but what the board does with it, and whether the RX status bit 3 means E-stop, are not confirmed.
- How the board signals motion completion or a full queue. Because of this `home_*()` and `probe()` raise `EcutError('homing/probing completion is not verified')` and send nothing.
- Spindle/coolant SET_DRO codes, `Cmd.SET_LED` / `Cmd.GET_LED` and the status-bit readback: guesses. `spindle_*`, `flood_*`, `mist_*`, `set_output`, `read_output` raise `EcutError('... not verified')`. Input banks (`read_inputs`, `limits_triggered`) are still decoded.
- The `Cmd` codes `MOTION_BATCH` (0xE5), `NOTIFY`, `PURGE`, `LIMIT_STOP`, `SAVE_CONFIG` are listed but not sent by the API.

## Behavior worth knowing

- E-stop (`estop()` or an RX E-stop bit) clears the run flag, sets state `ESTOP`, and refuses all motion until `reset()`.
- Moves are split into coordinated segments (same fraction on every axis, int16 deltas, exact endpoint) following a trapezoidal profile limited by each axis' `max_velocity_mm_s` and `acceleration_mm_s2` and by the modal feed.
- G1 needs an F value (on the line or earlier). A bare `F` line sets the modal feed.
- Supported G-code: G0/G1 (X Y Z A B C, F), G20/G21, G90/G91, M2/M30 (stop), bare F; `;` and `(...)` comments and blank lines are skipped. Anything else (arcs, S, T, M3/M4/M5/M7/M8/M9, G28, G38.2, unknown words) makes `run_gcode` raise `EcutError` naming the line and word. The whole program is validated before anything is sent. Start state: units from `config.units_mm` (G21), G90, no motion mode, no feed.
- `pause()` makes `run_gcode` stop submitting (also between the packets of one move) until `resume()`, `stop()` or an E-stop.
- `EcutUsb.send` raises `EcutUsbError` (an `EcutError`) on a failed or short HID write. `EcutUsb.open` only accepts HID interface 0 or -1 (not reported); other interfaces are not tried.
- `interpolation_index` must be an int 0-9 (`EcutConfigError` otherwise, also when loading JSON). Old JSON files with `cycle_time_ms`, `rapid_feedrate_mm_min`, `default_feedrate_mm_min` still load (the keys are ignored).

## Needed before real use

1. Capture USB traffic from Mach3 with the original plugin (USBPcap/Wireshark).
2. Confirm VID/PID, the output report length, and that commands work without a CRC.
3. Derive the real motion tick period and the configuration framing.
4. Test E-stop and limit behavior with the motor drivers disabled.
