"""Analyze an exported profile .bin from the Redragon vendor software.

We know from the decompiled DriverLib.FlashDataMap that the profile starts with
the MouseConfig struct (15 bytes) at offset 0x40 of the .bin:

  0x40 reportRate           (R_1000=1, R_500=2, R_250=4, R_125=8, R_2000=16, R_4000=32)
  0x41 maxDPI               (number of DPI stages)
  0x42 currentDPI
  0x43 xSpindown
  0x44 ySpindown
  0x45 silenceHeight
  0x46 keyDebounceTime      (ms)
  0x47 motionSyncEnable
  0x48 allLedOffTime
  0x49 linearCorrectionEnable
  0x4A rippleControlEnable
  0x4B moveOffLedEnable
  0x4C sensorCustomSleepTimeEnable
  0x4D sensorSleepTime
  0x4E sensorPowerSavingModeEnable

DPI table, RGB, macros, button mappings follow.

Usage:
  py analyze_bin.py <profile.bin>
  py analyze_bin.py <profile.bin> <other.bin>        # diff mode
"""
import sys, os


def hexdump(data, start=0, length=None, width=16):
    if length is None: length = len(data)
    for i in range(0, min(length, len(data) - start), width):
        off = start + i
        chunk = data[off:off+width]
        hx = ' '.join(f'{b:02x}' for b in chunk)
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f'{off:08x}  {hx:<{width*3}} {asc}')


REPORT_RATE_NAMES = {1: "1000 Hz", 2: "500 Hz", 4: "250 Hz", 8: "125 Hz",
                     16: "2000 Hz", 32: "4000 Hz"}


def decode_mouse_config(data):
    if len(data) < 0x50:
        print("file too small to contain MouseConfig"); return
    print(f"\n--- MouseConfig (offset 0x40) ---")
    fields = [
        ("reportRate",                   REPORT_RATE_NAMES.get(data[0x40], f"unknown (0x{data[0x40]:02x})")),
        ("maxDPI",                       f"{data[0x41]} stages"),
        ("currentDPI",                   f"stage {data[0x42]}"),
        ("xSpindown",                    f"0x{data[0x43]:02x}"),
        ("ySpindown",                    f"0x{data[0x44]:02x}"),
        ("silenceHeight",                f"0x{data[0x45]:02x}"),
        ("keyDebounceTime",              f"{data[0x46]} ms"),
        ("motionSyncEnable",             f"{data[0x47]}"),
        ("allLedOffTime",                f"0x{data[0x48]:02x}"),
        ("linearCorrectionEnable",       f"{data[0x49]}"),
        ("rippleControlEnable",          f"{data[0x4A]}"),
        ("moveOffLedEnable",             f"{data[0x4B]}"),
        ("sensorCustomSleepTimeEnable",  f"{data[0x4C]}"),
        ("sensorSleepTime",              f"0x{data[0x4D]:02x}"),
        ("sensorPowerSavingModeEnable",  f"{data[0x4E]}"),
    ]
    for name, val in fields:
        print(f"  {name:30s} = {val}")


def find_ascii_strings(data, min_len=4):
    out = []
    cur = bytearray()
    start = 0
    for i, b in enumerate(data):
        if 32 <= b < 127:
            if not cur: start = i
            cur.append(b)
        else:
            if len(cur) >= min_len:
                out.append((start, bytes(cur).decode('ascii')))
            cur = bytearray()
    if len(cur) >= min_len:
        out.append((start, bytes(cur).decode('ascii')))
    return out


def diff_bins(a, b):
    diffs = []
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            diffs.append(i)
    return diffs


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    main_path = sys.argv[1]
    with open(main_path, 'rb') as f: data = f.read()
    print(f"=== {main_path}  ({len(data)} bytes = 0x{len(data):X}) ===")

    print("\n--- First 256 bytes ---")
    hexdump(data, 0, 256)

    decode_mouse_config(data)

    print(f"\n--- ASCII strings (len >= 4, first 20) ---")
    for off, s in find_ascii_strings(data, 4)[:20]:
        print(f"  0x{off:04x}: {s!r}")

    if len(sys.argv) >= 3:
        other_path = sys.argv[2]
        if os.path.exists(other_path):
            with open(other_path, 'rb') as f: bdata = f.read()
            print(f"\n=== diff against {other_path}  ({len(bdata)} bytes) ===")
            if len(bdata) != len(data):
                print("size mismatch, skipping diff"); return
            diffs = diff_bins(data, bdata)
            print(f"--- {len(diffs)} byte differences ---")
            ranges = []
            if diffs:
                s = p = diffs[0]
                for x in diffs[1:]:
                    if x == p + 1: p = x
                    else:
                        ranges.append((s, p)); s = p = x
                ranges.append((s, p))
            for s, e in ranges[:30]:
                print(f"  0x{s:04x}-0x{e:04x} ({e-s+1} bytes): "
                      f"A={data[s:e+1].hex(' ')}  B={bdata[s:e+1].hex(' ')}")


if __name__ == '__main__':
    main()
