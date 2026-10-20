# E-Cut USB motion controller (appPlugins.Common.ecut)

> **NOT READY FOR PRODUCTION.** This driver is experimental. Do not use it to run a job on a machine that can cause
> damage or injury. Test it only on a bench: motor drivers disabled or no machine connected, with a hardware E-stop
> in reach. The software stop is not a safety device.

Python driver for the E-Cut USB HID CNC motion board (USB VID 0x0483, PID 0x5750). The protocol was recovered from
USB captures and an analysis of the original Mach3 plugin; the board is controlled directly, without Mach3.

The G-code Sender plugin (`appPlugins/ToolGrblSender`) uses this package: `EcutSenderPort` gives the Sender the same
line protocol as a serial controller.

## Status

Checked on a real board (bench, no motors or only a VFD connected):

- connect after a USB power cycle, status, reset and the software stop latch
- short moves and return moves; feed hold brakes along the path and resume ends at the exact position
- the axis reference (`reference_axes`): the board applies the counts about 11 ms after the command
- outputs and the spindle DAC voltage

Not checked on hardware, or refused by the code:

- spindle control through a VFD on a real machine
- homing and probing with the physical input cycle: refused with an error
- persistent configuration writes, B/C and index homing, probing outside XYZ, safety-door parking and driver
  disable: refused with an error
- long jobs, limit switches and the behavior of the E-stop input on a real machine

The code does only what the evidence proves. Everything else raises `EcutError` (or `GcodeError` in the G-code
engine) with the reason. Do not remove these checks to make a feature work.

The evidence (USB captures, protocol notes) is kept outside this repository. The references to `docs/mach3/` in the
docstrings point to it.

## Files

| File | Content |
|------|---------|
| `ecut_protocol.py` | HID transport (`EcutUsb`), packet builders, receive decoder, CRC |
| `ecut_config.py` | `EcutBoardConfig` and its dataclasses, JSON save and load |
| `ecut_controller.py` | `EcutAPI`: state machine, motion, reference, outputs, spindle |
| `ecut_planner.py` | motion planner: trapezoidal profiles, segments, soft limit checks |
| `ecut_gcode_engine.py` | `EcutGcodeEngine`: the G-code interpreter, settings, status reports |
| `ecut_sender_port.py` | `EcutSenderPort`: the port that the G-code Sender uses |
| `__init__.py` | public exports |
| `API_REFERENCE.md` | class and method reference |
| `requirements.txt` | `hidapi` (optional dependency of this package) |

## Tests

The tests use a fake USB layer. They do not open a real HID device:

```
python -m pytest tests/ecut -q
```

Hardware tests have `@pytest.mark.hardware` and run only with `FLATCAM_TEST_HARDWARE=1` and a connected board.

## Usage (bench only)

```python
from appPlugins.Common.ecut import EcutAPI

api = EcutAPI()
api.load_config('machine.json')       # or api.configure_axis(...)
api.connect()                         # opens the HID device; does NOT push the configuration
api.run_gcode(['G1 X10 Y10 F500'])
api.disconnect()
```

## Needed before production use

1. Spindle and VFD control on a real machine.
2. Homing and probing with the physical input cycle.
3. Limit switches and the E-stop input on a real machine.
4. Long jobs with motors connected, at the feed rates and accelerations of the machine.
