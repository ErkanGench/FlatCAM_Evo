# ##########################################################
# FlatCAM Evo: E-Cut USB Motion Controller Module          #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/20/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""
E-Cut USB HID motion controller for FlatCAM.

This module provides a Python interface to E-Cut USB CNC motion controller boards,
allowing FlatCAM to directly control these boards without requiring Mach3.

Based on reverse-engineered protocol from e-Cut.dll.
See docs/mach3/Ecut_Recovered_Protocol/FINDINGS.md for protocol details.

Usage:
    from appPlugins.Common.ecut import EcutAPI

    api = EcutAPI()
    api.load_config('my_machine.json')
    api.connect()  # does not push the configuration to the board
    api.push_config()  # required initialization; preserves raw position, clears outputs
    api.run_gcode(['G0 X10 Y10', 'G1 X20 F500'])
    api.disconnect()
"""

from .ecut_protocol import (
    EcutUsb,
    EcutUsbError,
    find_boards,
    Cmd,
    RxSubtype,
    EcutRxFrame,
    decode_rx_report,
    encode_motion_record,
    pack_motion_payload,
    build_tx_packet,
    build_motion_packet,
    ecut_crc60,
    MAX_MOTION_RECORDS_PER_PACKET,
    MAX_TX_PARAMS_SIZE,
    VID,
    PID,
    REPORT_SIZE,
    AXIS_NAMES,
    INTERPOLATION_FACTORS,
)

from .ecut_config import (
    EcutBoardConfig,
    EcutConfigError,
    AxisConfig,
    HomingConfig,
    ProbeConfig,
    SpindleConfig,
    MPGConfig,
    SafetyConfig,
    InputSignal,
    OutputSignal,
    AxisDirection,
    SignalPolarity,
    SpindleControl,
    ProbeMode,
    HomeSequence,
    INPUT_SIGNAL_NAMES,
    OUTPUT_SIGNAL_NAMES,
)

from .ecut_controller import (
    EcutAPI,
    State,
    EcutError,
    encode_config,
)

__all__ = [
    # Protocol
    'EcutUsb',
    'EcutUsbError',
    'find_boards',
    'Cmd',
    'RxSubtype',
    'EcutRxFrame',
    'decode_rx_report',
    'encode_motion_record',
    'pack_motion_payload',
    'build_tx_packet',
    'build_motion_packet',
    'ecut_crc60',
    'MAX_MOTION_RECORDS_PER_PACKET',
    'MAX_TX_PARAMS_SIZE',
    'VID',
    'PID',
    'REPORT_SIZE',
    'AXIS_NAMES',
    'INTERPOLATION_FACTORS',
    # Config
    'EcutBoardConfig',
    'EcutConfigError',
    'AxisConfig',
    'HomingConfig',
    'ProbeConfig',
    'SpindleConfig',
    'MPGConfig',
    'SafetyConfig',
    'InputSignal',
    'OutputSignal',
    'AxisDirection',
    'SignalPolarity',
    'SpindleControl',
    'ProbeMode',
    'HomeSequence',
    'INPUT_SIGNAL_NAMES',
    'OUTPUT_SIGNAL_NAMES',
    # API
    'EcutAPI',
    'State',
    'EcutError',
    'encode_config',
]
