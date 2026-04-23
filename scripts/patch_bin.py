"""Patch a field in an exported Redragon profile .bin.

Handy helper for edit-and-reimport workflows. Changes one MouseConfig field
at the documented offset and writes a new file.

Note: for the M612-PRO, the reportRate byte at 0x40 appears to be ignored by
the firmware — the USB endpoint descriptor hardcodes bInterval=8 (125 Hz) on
this hardware, capping effective click rate at ~62 CPS regardless of flash
settings. Still useful for other Compx/MosArt mice that do honor the flash
byte, and for tweaking debounce / DPI stages in any case.

Usage:
  py patch_bin.py <in.bin> <out.bin> <field>=<value> [<field>=<value> ...]

Fields (with their offset):
  reportRate           0x40   1=1000 2=500 4=250 8=125 16=2000 32=4000 Hz
  maxDPI               0x41   number of DPI stages
  currentDPI           0x42   default stage
  keyDebounceTime      0x46   ms
  allLedOffTime        0x48   s (?)
  motionSyncEnable     0x47
  linearCorrectionEnable  0x49
  rippleControlEnable  0x4A
  moveOffLedEnable     0x4B
  sensorSleepTime      0x4D
  sensorPowerSavingModeEnable  0x4E

Example:
  py patch_bin.py in.bin out.bin reportRate=1 keyDebounceTime=1
"""
import sys


FIELDS = {
    "reportRate":                  0x40,
    "maxDPI":                      0x41,
    "currentDPI":                  0x42,
    "xSpindown":                   0x43,
    "ySpindown":                   0x44,
    "silenceHeight":               0x45,
    "keyDebounceTime":             0x46,
    "motionSyncEnable":            0x47,
    "allLedOffTime":               0x48,
    "linearCorrectionEnable":      0x49,
    "rippleControlEnable":         0x4A,
    "moveOffLedEnable":            0x4B,
    "sensorCustomSleepTimeEnable": 0x4C,
    "sensorSleepTime":             0x4D,
    "sensorPowerSavingModeEnable": 0x4E,
}


def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(2)
    inp, out, *edits = sys.argv[1:]
    data = bytearray(open(inp, 'rb').read())
    print(f"source: {inp}  ({len(data)} bytes)")

    for edit in edits:
        if '=' not in edit:
            print(f"bad edit {edit!r}, expected field=value"); sys.exit(2)
        field, value_s = edit.split('=', 1)
        if field not in FIELDS:
            print(f"unknown field {field!r}. Known: {list(FIELDS)}"); sys.exit(2)
        value = int(value_s, 0)
        if not 0 <= value <= 255:
            print(f"{field} value must be 0..255"); sys.exit(2)
        offset = FIELDS[field]
        print(f"  {field} @ 0x{offset:02x}: 0x{data[offset]:02x} -> 0x{value:02x}")
        data[offset] = value

    open(out, 'wb').write(bytes(data))
    print(f"wrote: {out}")


if __name__ == '__main__':
    main()
