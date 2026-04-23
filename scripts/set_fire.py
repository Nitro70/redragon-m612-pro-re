"""Set the fire-button interval via Redragon M612-PRO's full HID session.

The vendor GUI clamps the fire-button interval to 10 ms minimum. The firmware
itself accepts down to 1 ms but the effective click rate is capped by the
mouse's 125 Hz USB polling (~62 CPS hard ceiling regardless of interval).

Packet format (17-byte HID output report 0x08 on MI_01 Col05):

  byte  0 : 0x08           report ID
  byte  1 : 0x07           command = WriteFlashData
  byte  2 : 0x00
  byte  3 : 0x00
  byte  4 : 0x74           fire button ID
  byte  5 : 0x04           mode  (rapid fire)
  byte  6 : count          clicks per trigger (vendor GUI default 4)
  byte  7 : SPEED          interval in ms
  byte  8 : 0x00
  byte  9 : 0x51 - SPEED   mirror/complement
  bytes 10..15: 0x00
  byte 16 : checksum       (0x55 - sum(bytes 0..15)) & 0xFF

This script uses raw CreateFile + WriteFile (not HidD_SetOutputReport) since
the firmware only processes config writes that arrive on the interrupt OUT
endpoint, not the control endpoint.

It also sends the complete session sequence observed from the vendor software:

  08 01 <nonce>  session init
  08 02 ...      begin (select profile)
  08 07 ...      the fire-button config itself
  08 04          ack
  08 12          read-version-id
  08 0E          get-current-config

Without that full sequence the mouse silently ignores config writes.

Usage:
  py set_fire.py <speed_ms> [count] [mode]
  py set_fire.py 3              # 3 ms interval, count 4, mode=full
  py set_fire.py 1 4 minimal    # minimal session (preserves debounce)
"""
import sys, ctypes, ctypes.wintypes as wt, time, random
import pywinusb.hid as hid

VID, PID = 0x3554, 0xF55E

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 0x01, 0x02
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value

CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
CreateFileW.restype  = wt.HANDLE
WriteFile = kernel32.WriteFile
WriteFile.argtypes = [wt.HANDLE, wt.LPCVOID, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.LPVOID]
WriteFile.restype  = wt.BOOL
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wt.HANDLE]; CloseHandle.restype  = wt.BOOL


def find_col05_path() -> str | None:
    """Find the MI_01 Col05 HID device path (UsagePage 0xFF02, 17-byte output)."""
    for d in hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices():
        try:
            d.open()
            cap = d.hid_caps
            if cap and cap.usage_page == 0xFF02 and cap.output_report_byte_length == 17:
                return d.device_path
        finally:
            try: d.close()
            except: pass
    return None


def checksum(body: bytes) -> int:
    """(0x55 - sum(body[:16])) & 0xFF — covers bytes 0..15, checksum goes at index 16."""
    return (0x55 - sum(body)) & 0xFF


def pkt(body: bytes) -> bytes:
    """Take up to 16 bytes, right-pad to 16, append checksum = 17 bytes total."""
    b = bytearray(16)
    b[:len(body)] = body
    return bytes(b) + bytes([checksum(b)])


def build_fire(speed: int, count: int = 4) -> bytes:
    if not (0 < speed < 256): raise ValueError("speed must be 1..255")
    if not (0 < count < 256): raise ValueError("count must be 1..255")
    b = bytearray(16)
    b[0], b[1], b[4], b[5], b[6], b[7] = 0x08, 0x07, 0x74, 0x04, count, speed
    b[9] = (0x51 - speed) & 0xFF
    return bytes(b) + bytes([checksum(b)])


def build_init() -> bytes:
    """08 01 00 00 00 08 <4-byte nonce> 00 00 00 00 00 00 + cksum."""
    nonce = random.randbytes(4)
    body = bytes([0x08, 0x01, 0, 0, 0, 0x08]) + nonce + bytes(6)
    return body + bytes([checksum(body)])


# Observed from vendor-software capture; these are constants for the M612-PRO
PKT_02  = pkt(bytes([0x08, 0x02, 0, 0, 0, 0x01, 0x01]))    # begin (profile 1)
PKT_04  = pkt(bytes([0x08, 0x04]))                          # ack
PKT_12  = pkt(bytes([0x08, 0x12]))                          # read version id
PKT_0E  = pkt(bytes([0x08, 0x0E]))                          # get current config


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    speed = int(sys.argv[1])
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    mode  = sys.argv[3] if len(sys.argv) > 3 else 'full'

    fire = build_fire(speed, count)
    init = build_init()
    print(f"fire: {fire.hex(' ')}  speed={speed} count={count}")

    path = find_col05_path()
    if not path:
        print("ERROR: could not locate MI_01 Col05 path.")
        print("Is the mouse plugged in via USB (not 2.4G dongle)?")
        sys.exit(1)

    seq_modes = {
        'bare':    [('fire', fire)],
        'commit':  [('fire', fire), ('12', PKT_12)],
        'minimal': [('01', init), ('fire', fire), ('12', PKT_12)],
        'full':    [('01', init), ('02', PKT_02), ('fire', fire),
                    ('04', PKT_04), ('12', PKT_12), ('0e', PKT_0E)],
    }
    if mode not in seq_modes:
        print(f"unknown mode {mode!r}; choose from {list(seq_modes)}")
        sys.exit(2)
    seq = seq_modes[mode]

    # Open ONE handle, send the whole sequence, close — matches vendor behavior.
    h = CreateFileW(path,
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None, OPEN_EXISTING, 0, None)
    if h in (INVALID_HANDLE_VALUE, 0, None):
        raise OSError(f"CreateFileW failed, GetLastError={ctypes.get_last_error()}")
    try:
        for label, data in seq:
            buf = ctypes.create_string_buffer(data, len(data))
            written = wt.DWORD(0)
            ok = WriteFile(h, buf, len(data), ctypes.byref(written), None)
            if not ok:
                err = ctypes.get_last_error()
                print(f"  [{label}] WRITEFAIL written={written.value} err={err}")
            else:
                print(f"  [{label}] ok ({written.value}/{len(data)}): {data.hex(' ')}")
            time.sleep(0.015)
    finally:
        CloseHandle(h)
    print("done.")


if __name__ == '__main__':
    main()
