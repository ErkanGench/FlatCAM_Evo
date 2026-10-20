# E-Cut API reference

Package: `appPlugins.Common.ecut`. License: MIT. This file describes the code as it is now.
Where this file and the code disagree, the code is correct.

Exports of `__init__.py` come from `from appPlugins.Common.ecut import ...`.
These two classes are not exported. Import them from their modules:

```python
from appPlugins.Common.ecut.ecut_gcode_engine import EcutGcodeEngine, GcodeError
from appPlugins.Common.ecut.ecut_sender_port import EcutSenderPort   # needs pyserial
```

Other public names (planner, extra packet builders, `compile_program`) are also imported from their modules.

## Hardware evidence
These facts were measured on the real board on 2026-10-20.

- `reference_axes` works with nonzero counts. It sends `a0` (`SET_POSITION`) with six int32 counts and mask `0x3f`.
- The board applies the new counts about 10-11 ms after the command. `reference_axes` waits up to 1 s for the readback.
- The board keeps its counts after a disconnect.
- Feed hold (`pause`) during a 20 mm X move at 600 mm/min braked and held. `resume` ended exactly on target.
- Spindle DAC (`B0` PWM mode, period 1000): S12000 of 24000 maximum measured about 5 V on the 0-10 V range.

Other facts come from the reports in `docs/mach3/` and are not measured again here:

- Inputs I0-I15 and outputs O0-O7 are physically mapped (`ECUT_CAPABILITY_MAP.txt`).
- The unloaded spindle DAC is verified. Loaded VFD response, step/direction spindle drive, and real RPM feedback are not verified.
- Continuous jog and finite moves passed live tests (`ECUT_CONTINUOUS_JOG.txt`).
- Home and probe cycles are not verified on a real switch. The code refuses them (see "Sensor cycles").
- MPG, expansion inputs, and the electrical cause of RX status bit 3 (E-stop) are not verified.

## Exports (`__init__.py`)
| Group | Names |
|-------|-------|
| Protocol | `EcutUsb`, `EcutUsbError`, `find_boards`, `Cmd`, `RxSubtype`, `EcutRxFrame`, `decode_rx_report`, `encode_motion_record`, `pack_motion_payload`, `build_tx_packet`, `build_motion_packet`, `ecut_crc60`, `MAX_MOTION_RECORDS_PER_PACKET` (4), `MAX_TX_PARAMS_SIZE` (63), `VID` (0x0483), `PID` (0x5750), `REPORT_SIZE` (65), `AXIS_NAMES`, `INTERPOLATION_FACTORS` |
| Config | `EcutBoardConfig`, `EcutConfigError`, `AxisConfig`, `HomingConfig`, `ProbeConfig`, `SpindleConfig`, `MPGConfig`, `SafetyConfig`, `InputSignal`, `OutputSignal`, `AxisDirection`, `SignalPolarity`, `SpindleControl`, `ProbeMode`, `HomeSequence`, `INPUT_SIGNAL_NAMES`, `OUTPUT_SIGNAL_NAMES` |
| Controller | `EcutAPI`, `State`, `EcutError`, `encode_config` |

Exception tree: `EcutError` is the base. `EcutUsbError` and `EcutConfigError` derive from it.
`EcutConfigError` also derives from `ValueError`. `GcodeError` derives from `EcutError` and has a `code`.

## ecut_protocol
Wire format: one HID report is 65 bytes (report ID 0 plus 64 bytes). TX has no CRC. RX has a CRC over bytes 1..60.

### Constants and enums
- `Cmd` (IntEnum): `STOP`=0xC8, `ESTOP`=0xC8 (alias), `CONFIG`=0xCA, `SET_POSITION`=0xA0, `MPG_CONFIG`=0x9B, `AXIS_ENABLE`=0x9B (alias), `AXIS_CONFIG`=0x9F, `IO_CONFIG`=0xA2, `PIN_CONFIG`=0xCD, `MODE`=0x1A, `SET_OUTPUTS`=0xAF, `END_STREAM`=0xE5, `MOTION_LIMITS`=0x4B, `SOFT_LIMITS`=0xB5, `PROBE`=0xAE, `HOME`=0xA6, `JOG_ON`=0xB4, `JOG_OFF`=0xC9, `PROBE_FINISH`=0xAC, `SPINDLE`=0xB0.
- `RxSubtype`: `POSITION`=0, `AUX_8H`=1, `SINGLE_H`=2, `HI`=3, `EXPAND_IO`=4, `IIIH`=5.
- Other module constants: `PAYLOAD_SIZE` (64), `CRC_DATA_SIZE` (60), `MOTION_RECORD_SIZE` (16).

### EcutRxFrame (frozen dataclass)
Fields: `report_id`, `axis_positions` (6 signed int32), `aux_u32`, `field_778`, `inputs_0_15`, `status`, `field_78c`, `field_790`, `subtype`, `subtype_values`, `crc_wire`, `crc_valid`.

| Property | Meaning |
|----------|---------|
| `configured` | status bit 0x0001 |
| `motion_busy` | status bit 0x0080 |
| `estop_active` | status bit 0x0008. No capture shows this bit set |
| `outputs` | output bitmap (`field_778`) |
| `fifo_free` | free FIFO units (`field_790`). 12000 means empty. It is not a count of record slots |
| `input_bits` | tuple of 16 booleans from `inputs_0_15` |

### Functions
| Name | Behavior |
|------|----------|
| `find_boards(vid, pid)` | Lists the boards (dicts from `hid.enumerate`). Opens no device. `EcutUsbError` if `hidapi` is missing |
| `decode_rx_report(report)` | 65 bytes to `EcutRxFrame`. `ValueError` for another length. `crc_valid` shows the CRC result |
| `ecut_crc60(payload)` | RX CRC over exactly 60 bytes. `ValueError` for another length |
| `encode_motion_record(trajectory_id, axes)` | 16 bytes: `0x69`, 24-bit ID, 6 x int16 big-endian. `ValueError` on bad ID or axis range |
| `pack_motion_payload(records)` | Up to 4 records, zero padded to 64 bytes. `ValueError` on bad records |
| `build_motion_packet(records)` | `[0]` plus payload. 1 to 4 records. No command byte. `ValueError` otherwise |
| `build_tx_packet(cmd, params=b'')` | `[0][cmd][params]`, zero padded to 65 bytes. `ValueError` if params exceed 63 bytes |

Other builders in the module (not in `__all__`): `build_spindle_pwm_packet(period_counts, duty_counts)` (`B0` PWM/DAC, period 1..0xFFFF, duty 0..period),
`build_axis_config_packet` (`9F`), `build_pin_config_packet` (`CD`), `build_input_config_packet` (`A2`, 32 logical inputs),
`build_motion_limits_packet` (`4B`), `build_soft_limits_packet` (`B5`), `build_target_packet` (`AE`, `A6`, `B4`; signed 64-bit Q16 targets).
All raise `ValueError` for bad values. None clips.

### EcutUsb(vid=VID, pid=PID)
Minimal HID transport. It has no thread and no reconnect. The caller owns threading. Needs `hidapi`.

| Member | Behavior |
|--------|----------|
| `open()` | Opens the one HID interface with number 0 or -1. `EcutUsbError`: no `hidapi`, already open, not exactly one match, or OS error |
| `close()` | Closes the device |
| `is_open` | True while the device is open |
| `send(report)` | Writes 65 bytes. `EcutUsbError` if not open, or on a failed or short write. `ValueError` for a wrong size |
| `recv(timeout_ms=100)` | Returns a valid `EcutRxFrame`, or `None` if no data. After a bad read it retries up to 3 times in 50 ms. `EcutUsbError` if the device is gone, or if the report ID or CRC stays invalid |
| `poll()` | `recv(timeout_ms=0)` |
| `cmd(opcode, params=b'')` | `send(build_tx_packet(...))` |
| `send_motion(records)` | `send(build_motion_packet(records))` |
| `stop()`, `estop()` | Send `Cmd.STOP` (0xC8) |
| `reset()`, `home()`, `jog_on()`, `jog_off()`, `probe()`, `dwell()` | Always raise `EcutError`. Use `EcutAPI` |
| `read_errors`, `read_recoveries` | Counters of bad reads and recoveries |

## ecut_config
### Enums
`SignalPolarity` (`ACTIVE_LOW`=0, `ACTIVE_HIGH`=1), `AxisDirection` (`FORWARD`=1, `REVERSE`=-1),
`HomeSequence` (`FIRST`, `SECOND`, `THIRD`), `ProbeMode` (`TOWARD_WORKPIECE`, `AWAY_FROM_WORKPIECE`),
`SpindleControl` (`NONE`=0, `PWM`=1, `STEP_DIR`=2, `ANALOG`=3).

### Dataclasses
`AxisConfig`, `HomingConfig`, `ProbeConfig`, `SpindleConfig`, `MPGConfig`, `SafetyConfig`, `InputSignal`, `OutputSignal`.
Each has `to_dict()` and `from_dict(d)`. Missing keys take the default.
Notable defaults: `AxisConfig` 800 steps/mm, 50 mm/s, 200 mm/s2, soft limits 0..300 mm and off;
`deceleration_mm_s2` None follows acceleration (`effective_deceleration_mm_s2`).
`HomingConfig` 10 and 2 mm/s, `max_travel_mm` 300, `retract_mm` 2. `ProbeConfig` 5 and 0.5 mm/s, `max_travel_mm` 50, `retract_mm` 1.
`SpindleConfig` `NONE`, `pwm_frequency_hz` 1000, `pwm_period_counts` 1000, RPM 0..24000.
`SafetyConfig` override 0..200 percent, `restore_outputs_after_m0` True. `InputSignal` `debounce_ms` 20, `port` 1.

### EcutBoardConfig
Fields and defaults:

- `vid` 0x0483, `pid` 0x5750, `units_mm` True.
- `interpolation_index` 5 (int 0-9, index into `INTERPOLATION_FACTORS`; factor 64). `EcutConfigError` otherwise, also at load.
- `motion_period_s` 0.001. It is the only accepted value (not `None`).
- `junction_deviation_mm` 0.01. `soft_limit_tolerance_mm` 0.05 (maximum `SOFT_LIMIT_TOLERANCE_MAX_MM` = 1.0).
- `input_labels` (16 names, I0..I15) and `output_labels` (8 names, O0..O7). Empty string = no name. `LABEL_MAX_LENGTH` = 32.
- `step_functions`, `dir_functions`, `spindle_axis_io`, `homing_mode` (2), `homing_count` (2), `homing_ratio_pct` (50).
- `axes` (6), `homing` (6), `inputs`, `outputs` (dicts by signal name), `probe`, `spindle`, `mpg`, `safety`.

Methods and properties: `to_dict()`, `from_dict(d)`, `validate()`, `save(path)`, `load(path)`, `interpolation_factor`, `summary()`.

- `save` validates first, then writes JSON through a temporary file and a replace.
- `load` reads JSON, builds the config, then validates. Unknown keys are ignored.
- `validate()` raises `EcutConfigError` for: not six axes and six homing entries; `motion_period_s` other than 0.001;
  bad `junction_deviation_mm` (not finite, or negative); `soft_limit_tolerance_mm` outside 0..1.0;
  labels that are not 16 and 8 printable names of at most 32 characters;
  an axis with non-integer `steps_per_mm`, `steps_per_mm` outside 1..0x7FFFFFFF, or bad direction, velocity, acceleration, deceleration or offset;
  enabled soft limits with negative limit not below positive limit; any backlash (not verified);
  an input pin outside 0..31, port not 0 or 1, bad polarity, or debounce outside 0..10000;
  an output pin outside 0..15, or two enabled outputs on one pin with different polarity;
  a bad spindle RPM range, dwell, `pwm_period_counts` (1..0xFFFF) or `pulses_per_revolution`;
  a `PWM` spindle with `pwm_frequency_hz` other than 1000, or with `SPINDLE_CW`/`SPINDLE_CCW` sharing a pin with another enabled output;
  a bad `restore_outputs_after_m0`, estop pin or polarity, or an override range outside 0 <= min <= max <= 250.

## ecut_controller
### State
`State`: `DISCONNECTED`, `IDLE`, `RUNNING`, `PAUSED`, `ESTOP`, `ERROR`.

### encode_config(config)
Returns seven 65-byte reports (455 bytes) in this order: `CONFIG`, `SET_POSITION`, `MPG_CONFIG`, `AXIS_CONFIG`, `IO_CONFIG`, `PIN_CONFIG`, `MODE`.
It calls `config.validate()` and sends nothing. `EcutError` if `mpg.enabled`, if the spindle is `STEP_DIR`, or if the E-stop input assignments conflict.

### compile_program(lines, modal=None, *, checkpoint=None)
Validates a whole program and returns a list of `(line number, action)`. It sends nothing. It raises `EcutError` with the line number and the word. It is not exported.

### EcutAPI
#### Configuration (no board access)
| Member | Behavior |
|--------|----------|
| `config` | The `EcutBoardConfig` |
| `load_config(path)` | `EcutError` if connected. `EcutConfigError` if the file is invalid |
| `save_config(path)` | Validates and saves |
| `configure_axis(axis, *, steps_per_mm, direction, enabled, max_velocity, acceleration, deceleration, soft_limit_pos, soft_limit_neg, backlash)` | `ValueError` for axis outside 0-5 or bad deceleration. `deceleration=0` follows acceleration. It does not validate the other values |
| `configure_input(name, *, enabled, pin, polarity, debounce_ms)` | `ValueError` for unknown name, pin outside 0..31, or bad debounce |
| `configure_output(name, *, enabled, pin, inverted)` | `ValueError` for unknown name or pin outside 0..15 |
| `configure_homing(axis, ...)`, `configure_probe(...)`, `configure_spindle(control, ...)` | Set config fields |
| `set_interpolation(index)` | `ValueError` outside 0-9 |
| `encode_config()`, `config_summary()` | Wrappers of `encode_config(config)` and `config.summary()` |

A change of the config after `push_config()` blocks motion, spindle and outputs until `push_config()` runs again.

#### Connection and initialization
| Member | Behavior |
|--------|----------|
| `connect()` | Opens the device. Returns True and sets `IDLE`. Returns False and sets `ERROR` on `EcutUsbError`. `EcutError` if already connected. It sends nothing to the board |
| `disconnect()` | Sends stop, spindle zero and outputs inactive, then closes. State `DISCONNECTED`. The board keeps its counts |
| `restart()` | `disconnect()`, `connect()`, `push_config()`. `EcutUsbError('Reconnect failed')` if connect fails |
| `push_config()` | Initializes the board (see below). `EcutError('Not connected')`; `EcutConfigError` or `EcutError` from `encode_config`; `EcutError` on timeout, on a changed readback, or if an input interlock is active. On failure the state is `ERROR` (or stays `ESTOP`) |
| `reset()` | Same as `push_config()` |
| `save_config_to_board()` | Always `EcutError` (persistent writes not verified) |
| `state`, `connected` | Properties |
| `on_state_change(cb)`, `on_rx_frame(cb)` | Set the callbacks (one each) |

`push_config()` sequence: stop; set outputs to their inactive level; set spindle duty 0 (PWM mode); wait for an idle board;
send the seven reports with `SET_POSITION` carrying the measured counts; set outputs; wait for idle; check that the board is configured and the counts did not change.
It preserves the raw counts and clears all outputs. Axes in `homed_axes` stay referenced when their steps/mm, direction and interpolation did not change.
After success, `_initialized` is set and `fault_reason` is cleared.

#### Motion refusals
These calls need motion permission: `run_gcode`, `jog_start`, `jog_step`, `reference_axes`, and native moves.
They raise `EcutError` when any of these is true:

- state is `ESTOP` or `ERROR` ("reset() first");
- not connected;
- `motion_period_s` is not 0.001;
- `push_config()` has not run since `connect()` ("Motion requires initialization via push_config()");
- the config differs from the one sent by `push_config()`;
- `encode_config()` fails.

#### Stop, pause, tool change
| Member | Behavior |
|--------|----------|
| `stop()` | Needs a connection. Sends stop, spindle zero, outputs inactive. Waits for an idle board and reads the counts. State `IDLE` (not changed from `ESTOP` or `ERROR`). A failure sets `ERROR`, clears the initialized flag, and re-raises |
| `estop()` | Sets `ESTOP` first, then sends the stop. Motion stays refused until `reset()` |
| `pause()` | In `RUNNING`: state `PAUSED`. A program or jog then brakes along its path at the axis deceleration and holds. During a native sensor move it sets `ERROR` instead |
| `resume()` | `EcutError` if a tool change waits (use `confirm_tool_change`), or if the FEED_HOLD input (or DOOR input with `feed_hold_on_door_open`) is active. Does nothing if not `PAUSED`. After M0 it needs fresh status and restores spindle and coolant (`restore_outputs_after_m0`) |
| `confirm_tool_change(tool)` | `EcutError` unless a pending M6 has this exact tool number. It also needs state `PAUSED`, motion permission, inactive hold inputs, and fresh status. It starts no motion, offset or spindle |
| `selected_tool`, `current_tool`, `pending_tool_change`, `pause_reason` (`'M0'`, `'M6'` or `None`) | Properties |

#### Reference (manual home)
`reference_axes(axes)`: the current position of each axis becomes its home position. No switch is used.
The home position is `homing[axis].home_offset_mm` times the axis scale (0 gives an automatic zero).

- `ValueError` if `axes` is empty or an axis is outside 0..5 or not an int.
- `EcutError`: axis disabled; state not `IDLE`; no motion permission; board not initialized or a jog active; home position outside int32.
- `EcutError('The board did not confirm the new home counts; axes stay unreferenced')` if the readback does not match within 1 s.

On success the axes are added to `homed_axes`. `homed_axes` is a sorted tuple. A stop during motion, or a status without the configured bit, clears it.

#### Sensor cycles (homing and probing)
`home_all()`, `home_axis(axis)`, `home_axes(axes)`, `probe(axis=2, distance=None)`, `probe_grid(points, safe_z_mm)`, and G-code `G31`, `G38.2`, `G28` are implemented behind a gate.
The gate is off because no physical sensor cycle is verified. These calls raise `EcutError('Probing/homing refused: a verified Mach3 physical-input cycle capture is required')` and send nothing.
Checks before the gate:

- `home_axes`: `EcutError('No homing axes configured')` for an empty list; `ValueError` for an axis outside 0..5.
- `probe`: `ValueError` for an axis outside 0..5; `EcutError` for axis 3 or higher ("Probing outside XYZ is not verified").
- `probe_grid`: `EcutError` for a non-finite coordinate. An empty point list returns `[]`.
- `run_gcode`: a `G28` word is refused at compile time. A program with `G31` or `G38.2` is refused when it starts.

`last_probe_result` is a dict or `None`. `probe_grid` returns `(x, y, z)` samples.

#### Jogging
| Member | Behavior |
|--------|----------|
| `jog_start(axis, direction=0, feed_mm_min=None, *, should_continue=None)` | Continuous jog. Direction 0 is positive, 1 is negative. It blocks the calling thread and streams 1 ms records until the soft limit (or int32 bound), a release, or an error. Release plans a braking tail. `EcutError`: state not `IDLE`, no motion permission, jog already active, disabled axis, bad feed, stream underrun, stale or backed-up status. `ValueError`: bad axis or direction. A stream error sets `ERROR` and stops |
| `jog_stop()` | Thread-safe release request. The thread that called `jog_start` sends the braking tail |
| `jogging` | True while a continuous jog runs |
| `jog_step(axis, distance_mm)` | One finite rapid move of one axis. `ValueError` for a bad axis. Errors set `ERROR` |

The caller must service the release (`jog_stop` or a `should_continue` that returns False). The jog stops at the soft limit, or at the int32 bound when soft limits are off.

#### G-code
`run_gcode(lines)` needs state `IDLE` (`EcutError` otherwise). `run_gcode_file(path)` reads a file and calls it.
Step 1: it compiles every line (`EcutError` with the line number, and nothing is sent). Step 2: it plans all linear moves of the program (soft limits, ranges). Step 3: it runs.
An error while running sets `ERROR`, clears the initialized flag, and sends a stop. A stop or E-stop during the run is kept.

Start state: units from `config.units_mm`, G90, no motion mode, no feed.

| Word | Behavior |
|------|----------|
| `G0`, `G1` | Rapid and linear move. Axis words `X Y Z A B C`. Duplicate axis word is an error. An axis word without a motion mode is an error. `G1` without `F` is an error |
| `G20`, `G21`, `G90`, `G91`, `G94` | Units, distance mode, feed per minute. Two words of one group on a line are an error |
| `G4 P<s>` | Dwell. Needs `P`, and no axis or motion word |
| `F` | Feed in units per minute. Must be above 0 |
| `S`, `M3`, `M4`, `M5` | Spindle speed and direction (see "Spindle") |
| `T<n>` | Selects a tool. Integer 0..0x7FFFFFFF |
| `M6` | Waits for `confirm_tool_change`. Needs a selected `T`, and no axis word |
| `M0` | Waits for `resume()`. Cannot share a line with M2, M30, G4, M3 or M4 |
| `M2`, `M30` | Calls `stop()` |
| `G31`, `G38.2`, `G28` | Refused by the sensor gate |

Comments (`;` and `(...)`) and blank lines are skipped. Any other word raises `EcutError` ("unsupported word").
`M7`, `M8`, `M9` are not `run_gcode` words. Use `flood_on`, `mist_on` or `set_output`.

#### Spindle and outputs
The spindle works only in `SpindleControl.PWM` mode. Duty is `round(pwm_period_counts * rpm / speed_rpm_max)`.

| Member | Behavior |
|--------|----------|
| `spindle_on_cw(rpm=0.0)`, `spindle_on_ccw(rpm=0.0)` | Sets duty, then turns on `SPINDLE_CW` or `SPINDLE_CCW`. Honors `dwell_on_seconds` and `dwell_off_seconds` |
| `spindle_off()` | Duty 0 and outputs off |
| `spindle_speed(rpm)` | With a running direction it changes the duty. Without one it stores the RPM |
| `flood_on()`, `flood_off()`, `mist_on()`, `mist_off()` | `set_output('FLOOD'/'MIST', ...)` |
| `set_output(name, on)` | Writes the full output bitmap and checks the readback for 1 s |
| `read_output(name)` | Logical level from a fresh status (inversion applied). Waits up to 0.5 s |

Spindle `EcutError` conditions: control is not `PWM`; board not initialized with the current config; RPM below 0, above `speed_rpm_max`, or between 0 and `speed_rpm_min`; direction output not enabled; state `ESTOP`, `ERROR` or `PAUSED`; no fresh status; FEED_HOLD or door interlock; stop during the command.
A failure in a spindle command sets `ERROR`, stops, and re-raises.

`set_output` and `read_output` raise `EcutError` when the name is unknown, not enabled, or starts with `STEP_` or `DIR_`.
`set_output` also raises when the board is not initialized with the current config, when `on` is True in state `ESTOP` or `ERROR`, or when the readback times out (state `ERROR`, then stop).
`read_output` also raises when it is not connected or gets no status.

#### Position, input, status
| Member | Behavior |
|--------|----------|
| `position_mm`, `position_steps` | Host-tracked position. It follows the measured counts after `stop()` and `push_config()` |
| `set_position(axis, mm)`, `zero_all()` | Only while disconnected. `EcutError` when connected. `ValueError` for a bad axis |
| `get_dro(index)`, `set_dro(index, value)` | Always `EcutError` |
| `read_inputs()` | Dict of debounced logical inputs. Polls up to 0.5 s. `EcutError` if not connected |
| `limits_triggered` | Active `*_LIMIT_*` input names |
| `feed_override` | Float. The setter clamps to `safety.min/max_feedrate_override_pct / 100`. `ValueError` if not finite |
| `telemetry` | Dict. Keys `counters`, `spindle_period`, `identity` appear when the matching RX subtype arrives |
| `last_rx_frame`, `estop_active`, `fault_reason` | Last frame; True in `ESTOP` or with the RX E-stop bit; text of the last interlock fault |
| `poll()` | Reads one frame (or `None`). Invalid CRC raises `EcutUsbError` and sets `ERROR`. See interlocks |

Interlocks run on each frame: the RX E-stop bit, an active ESTOP input, or an active limit input calls `estop()` and sets `fault_reason`.
An active FEED_HOLD input (and DOOR input with `feed_hold_on_door_open`) calls `pause()`.
Fault inputs act at once. Release and other changes follow `debounce_ms`.

## ecut_planner
Pure functions. They access no device. Import from `appPlugins.Common.ecut.ecut_planner`.

| Name | Behavior |
|------|----------|
| `LinearMove(target_mm, rapid=False, feed_mm_min=None)` | One move. `None` in `target_mm` keeps the axis count |
| `plan_linear_path(config, start_steps, moves, *, feed_override=1.0, junction_deviation_mm=0.01, period_s=0.001, checkpoint=None)` | Validates the whole path and returns `PlannedBlock` list. First entry and last exit are stopped. Junction speed follows junction deviation (0 means a stop at each block) |
| `iter_path_segments(blocks, *, junction_deviation_mm, checkpoint=None)` | Lazy sequence of 1 ms records on one shared timebase. `len()` gives the record count |
| `iter_jog_segments(config, start_steps, axis, direction, feed_mm_min, should_continue)` | Generator of single-axis records with a releasable braking tail |
| `soft_limit_violation(axis, position, tolerance)` | Distance outside the window widened by the tolerance. 0 if inside, disabled, or no limits |
| `check_soft_limit_move(axis, start, target, tolerance, name)` | See below |

Soft limits: the window is `[negative - tolerance, positive + tolerance]`. A move may end outside it only when it ends closer to the window than it started.
So an axis left outside can always move back in. Otherwise `EcutError('Target exceeds the <axis> soft limit')`.

`plan_linear_path` raises `EcutError` for: `period_s` other than 0.001; `feed_override` outside the safety range; bad `junction_deviation_mm`;
start counts that are not six int32; a target on a disabled axis; a non-finite target; a target outside int32; a non-rapid move without feed; non-finite profiles.
`iter_path_segments` raises `EcutError` for blocks not made by the planner, with different calibration, or not contiguous.
`iter_jog_segments` raises `ValueError` for a bad axis or direction, and `EcutError` for a disabled axis, a bad feed, or a record above 32767 counts. It yields nothing when the axis is already at the limit.

## ecut_gcode_engine
`GcodeError(code, message)` has `.code` (an integer error code of the sender protocol). `prepare_program` also sets `.source_index` (0-based line).

| Code | Cause |
|------|-------|
| 1 | Line is not valid UTF-8 (sender port) |
| 2 | Expected a letter and a finite number |
| 3 | Bad setting, system command, selector, or motion settings value |
| 4 | Negative `F`, `N`, `P`, `T` or `S` |
| 7 | Host settings file invalid, or PC storage failed |
| 8 | Wrong state: not idle, check mode, stale program, no measured counts, fresh status missing |
| 9 | `$X` refused (alarm, limit, or no fresh status) |
| 14 | Arc needs more than 100000 segments |
| 15 | Soft limit, or target outside int32 counts |
| 16 | Bad `$J=` jog |
| 20 | Unsupported or unverified feature. Also any other `EcutError` raised while planning |
| 21 | Two words of one modal group |
| 22 | Motion without a positive `F` |
| 23 | `N` or `T` not an integer in range |
| 24, 25, 26 | Conflicting axis commands; repeated word; `G92` without axis |
| 28, 30, 31 | `G4`/`G10` parameters; `G53` motion mode; unused axis words |
| 33, 34, 35, 36, 37 | Arc end radius, radius, offsets; unused value words (or `R` with `IJK`); `G43.1` |

### EcutGcodeEngine(api, settings_path=None)
Persistent modal parser in front of an `EcutAPI`. Positions are in X, Y and Z. A line is fully planned before the board gets any command.
With `settings_path` it loads and saves the host settings, work offsets, startup blocks and machine profile as JSON (`GcodeError` 7 if the file is invalid).

| Member | Behavior |
|--------|----------|
| `execute_line(line)` | Runs one line or `$` command. Returns the reply lines (`['ok']` for G-code). Errors raise `GcodeError` |
| `prepare_program(lines)` | Preflights a whole file without USB access or state change. Returns a prepared program. Lines must be ASCII (comments can hold other text) and must not hold control characters or `? ~ ! $` (code 20). Code 8 if not idle or no measured counts, or if the state changes during preparation |
| `execute_program(prepared)` | Runs the prepared batches. Code 8 if the program is stale, running, or interrupted |
| `status_report(state=None)` | Returns the status line (see below) |
| `realtime(code)` | Handles one real-time byte. Returns reply lines |
| `reset()` | Resets the board state and parser. Returns the banner list |
| `run_startup()` | Runs the `$N0` and `$N1` blocks. Returns `['>line:ok', ...]` |
| `settings` | Dict of setting number to value |
| `get_motion_settings()` | Snapshot with a `revision` hash, axes X-A, motors, hardware config |
| `save_motion_settings(payload)` | Needs the current `revision`, idle, check mode off, and all outputs and the spindle off. Applies it with `push_config()` and saves the file. Code 3 for bad fields, 8 for wrong state, 7 for a storage failure |
| `reference_axes(axes)` | Axes 0..3 (code 3 otherwise). Code 8 if not idle or in check mode. Calls `EcutAPI.reference_axes`. Returns `{'homed_axes': [...]}` |
| `calibration_move(axis, distance_mm, feed_mm_min, revision)` | One relative move on axis 0..3. Distance 0 < abs <= 10 mm. Feed within the axis rate. Duration at most 30 s. Code 3 for bad values or an old revision, 8 for wrong state |
| `pending_tool_change`, `pause_reason`, `confirm_tool_change(tool)` | Pass through to the API |
| `check_mode` | True after `$C`. Parses and validates only. Sends nothing to the board |

### Supported G-code
- Motion: `G0 G1 G2 G3 G80`. Arcs use `I J K` or `R`, in planes `G17 G18 G19`. Arcs become short linear moves; `$12` sets the tolerance.
- Modes: `G20 G21 G90 G91 G91.1 G93 G94 G40 G43.1 G49 G61 G54-G59`.
- Non-modal: `G4 G10 G28 G30 G28.1 G30.1 G53 G92 G92.1`. Here `G28` and `G30` move to a stored position. They do not home.
- Not supported (code 20): `G38.2`-`G38.5`, and any other G word.
- M words: `M0 M1 M2 M3 M4 M5 M6 M7 M8 M9 M30`.
- Other words: `F I J K L N P R S T X Y Z`. `A`, `B` and `C` are not G-code words here.
- Spindle speed is scaled by the spindle override and clamped to `$31`..`$30`.

### System commands (`execute_line`)
| Command | Behavior |
|---------|----------|
| `$` | Help lines |
| `$$` | All settings |
| `$I` | Version line |
| `$G` | Parser state |
| `$#` | Work offsets, stored positions, G92, TLO |
| `$C` | Toggle check mode |
| `$X` | Unlock. Code 9 without fresh status or with an alarm, E-stop or limit |
| `$H`, `$SLP` | Refused (code 20) |
| `$J=<block>` | Jog block. Needs `F`, axes, and only `G20 G21 G90 G91 G53`. Code 16 otherwise |
| `$N`, `$N0=`, `$N1=` | Read or store startup blocks. M0 and M6 are refused (code 20) |
| `$RST=$`, `$RST=#`, `$RST=*` | Restore PC settings. Not allowed when native settings were stored (code 20) |
| `$<n>=<value>` | Set a setting (below) |

Settings need an idle controller, check mode off, and no pending tool change (code 8).

| Setting | Meaning |
|---------|---------|
| `$10` | 1 = report `MPos`, 0 = `WPos` (default 1) |
| `$11` | Junction deviation, mm |
| `$12` | Arc tolerance, mm. Range above 0 up to `ARC_TOLERANCE_MAX_MM` (0.1). Default 0.002 |
| `$13` | 1 = report inches |
| `$30`, `$31` | Spindle maximum and minimum RPM |
| `$32` | Must be 0 |
| `$100`-`$103` | Steps per mm (positive integer), axes X-A |
| `$110`-`$113` | Maximum rate, mm/min |
| `$120`-`$123` | Acceleration, mm/s2 |
| `$140`-`$143` | Deceleration, mm/s2. 0 follows acceleration |
| `$150`-`$153`, `$160`-`$163`, `$170`-`$173` | Soft limit negative, positive, enable |

Any other number raises code 20. A change of `$30`, `$31`, `$100`-`$123`, `$150`-`$173` runs `push_config()` and resets the spindle and coolant modal state. `$11` and `$140`-`$143` do not.

### Status report
Format: `<State|MPos:x,y,z|FS:0,<rpm>|WCO:x,y,z|Ov:<feed>,<rapid>,<spindle>[|A:S]>`

- State: `Idle`, `Run`, `Hold:0`, `Alarm`, `Check`. `WPos` replaces `MPos` when `$10` is 0.
- `FS` has feed 0 (the board reports no velocity) and the commanded spindle RPM.
- The accessory field comes after `Ov`: `|A:S` while the spindle runs clockwise, `|A:C` while it runs counterclockwise. No field when the spindle is off.

### Real-time codes (`realtime`)
| Code | Action |
|------|--------|
| `?` | Status report |
| 0x18 | Reset. Returns the banner |
| `!`, `~` | Feed hold, resume. `~` is refused during a pending M6 (code 20) |
| 0x85 | Stop (calls `stop()`) |
| 0x84 | Feed hold, then code 20 (door parking not verified) |
| 0x90-0x94 | Feed override: 100%, +10%, -10%, +1%, -1% (limits 10%-200%) |
| 0x95-0x97 | Rapid override: 100%, 50%, 25% |
| 0x99-0x9D | Spindle override: 100%, +10%, -10%, +1%, -1% (limits 10%-200%) |
| 0xA0, 0xA1 | Toggle flood, toggle mist |

Overrides are refused during a prepared program (code 20). Physical actions are refused in check mode (code 8). Any other code raises code 20.

## ecut_sender_port
`EcutSenderPort(api=None, settings_path=None, timeout=0.1, write_timeout=1.0, *, engine=None)` is a serial-port-like adapter for the G-code Sender.
It needs `pyserial` (`serial.SerialException` is its error type).

Caution: the constructor starts a worker thread. The thread connects to the board, runs `push_config()`, and queues the banner.
`serial.SerialException` if the board does not answer or the start fails.
With `api=None` it builds an `EcutAPI` with axes X-A enabled, B and C disabled, a `PWM` spindle (24000 RPM maximum, period 1000), and `SPINDLE_CW` and `SPINDLE_CCW` disabled.
One worker thread owns all board access.

Banner: `E-Cut host adapter 1.0 ['$' for help]`. The first empty line after the sender clears its buffer also gets the banner.

### Serial-like members
| Member | Behavior |
|--------|----------|
| `write(data)` | Returns the byte count. Splits real-time bytes from line text. Lines end with CR or LF. Line limit 4096 bytes. Queue limit 65536 bytes. `serial.SerialTimeoutException` when the queue stays full for `write_timeout`. `serial.SerialException` if closed, if a line is too long, or while a program is preparing, running or failed |
| `read(size=1)`, `readline(size=-1)`, `readlines()` | Read reply bytes. They wait up to `timeout` |
| `in_waiting` | Number of reply bytes ready |
| `reset_input_buffer()` | Drops the unread replies |
| `is_open` | True until `close()` or a fatal error |
| `close()` | Stops the board and disconnects on the worker. `serial.SerialException` if the worker does not stop in 5 s, or the shutdown failed |
| `dtr`, `timeout`, `write_timeout` | Attributes |

Real-time bytes: `?`, `!`, `~`, 0x18, 0x84, 0x85, 0x90-0x9E, 0xA0, 0xA1. They run at once and skip the line queue.
A byte inside a UTF-8 character (for example in a comment) is text. 0x18 and 0x85 clear the queued lines.
During a jog, `!` and 0x85 stop the jog, and `~` does not restart it. During a motion request only 0x18 resets. `!`, 0x84 and 0x85 stop the machine. Other real-time bytes get a refusal message.

### Replies
- A line that runs gives `ok`.
- A refused line gives `[MSG:E-Cut: <reason>]`, then `error:N`. `N` is the `GcodeError` code.
- Another `EcutError` gives `error:9` if the API state is `ESTOP` or `ERROR` (clear it with reset), else `error:20`.
- A line that is not UTF-8 gives `error:1`.
- An `EcutUsbError` or an unexpected exception is fatal. The adapter sends `ALARM:1` and `[MSG:E-Cut error: ...]`, then stops the board and closes.
- After 0x18 the adapter resets the engine, sends the banner, and runs the startup blocks again.

### Status line
`?` returns the engine report with a state override. `Jog` while a jog lease is active. `Hold:0` when held and the board is stationary with a status younger than 0.5 s, else `Hold:1`. `Run` while it processes work.

### Tool change
When a program reaches M6, the adapter emits `[ECUT:TOOL:<n>]` and calls `tool_change_callback(tool)` if set.
`confirm_tool_change(tool, token=None)` queues the confirmation. `tool` must be an int >= 0 (`ValueError` otherwise), else `serial.SerialException` if closed.
It uses `tool_change_token` by default. A wrong token or tool gives `error:3`. Properties: `pending_tool_change`, `pause_reason`, `tool_change_token`.

### Jog
`start_jog(axis, direction=0, feed_mm_min=...)` leases a continuous jog to the worker. `feed_mm_min` is required.
`ValueError` for a bad axis (0..5), direction (0 or 1), or feed. `serial.SerialException` when busy, in check mode, or not idle.
The caller must call `refresh_jog()` before `JOG_LEASE_SECONDS` (0.25 s) ends. `refresh_jog()` returns False when the jog ended.
`stop_jog()` releases the jog. `jogging` is True while the lease exists.

### Program upload
`prepare_program(lines)` preflights a program on the worker (timeout 30 s). The sender must then send exactly the same lines. The program runs after the last line.

- `ValueError`: an empty program; a line that is not a nonempty string without CR or LF; non-UTF-8 text; a line over 4096 bytes; a real-time byte; more than 32 MiB or 1000000 lines.
- `serial.SerialException`: busy, called from the worker, check mode, or any `GcodeError` of the preflight.
- A line that differs from the prepared source gives `error:3` and `[MSG:E-Cut program upload mismatch; reset required]`.
- A program that fails while running sends `ALARM:1` and `[MSG:E-Cut program stopped: ...]`. A reset is then required.

### Motion settings, reference, manual output
These calls run on the worker. They raise `serial.SerialException` when the adapter is busy, in check mode, not idle, closed, or the request times out (40 s; 35 s for a calibration).
An engine error returns as `serial.SerialException` with the same text.

| Member | Behavior |
|--------|----------|
| `get_motion_settings()` | Cached snapshot (deep copy). `serial.SerialException` if not ready |
| `save_motion_settings(payload)` | `EcutGcodeEngine.save_motion_settings` |
| `calibration_move(axis, distance_mm, feed_mm_min, revision)` | `EcutGcodeEngine.calibration_move` |
| `reference_axes(axes)` | `EcutGcodeEngine.reference_axes`. Axes 0..3 |
| `set_manual_output(pin, active, revision)` | Sets output `O<pin>` (0..7) directly. `ValueError` for a bad pin or a non-boolean level. It needs the current revision, a fresh configured idle status, and an initialized board. It refuses activation with FEED_HOLD or door active. It checks the readback for 1 s |
| `get_io_state()` | Dict: `connected`, `fresh`, `age_s`, `configured`, `inputs` (16 bits), `outputs` (8 bits), `busy`, `homed_axes`. Reads cached data only |
