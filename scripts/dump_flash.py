"""Call the read-side exports in the vendor's hidusb.dll to dump mouse state.

Loads `costura64.hidusb.dll` directly via ctypes, starts the UsbServer worker
against MI_01 Col05, and calls:

  - ReadVersion
  - ReadCidMid
  - ReadReportRate
  - ReadConfig
  - ReadDPILed
  - ReadLedBar
  - ReadEncryption
  - ReadAllFlashData

All results are collected via the OnUsbDataReceived callback and printed.
The flash dump, if any, is saved to `flash_dump.bin`.

Brick risk: none (all reads). The DLL might fail to load standalone if it
needs msvcp140.dll / vcruntime140.dll — pass --dll-dir pointing at a folder
containing those too.

Requires: pywinusb   (pip install pywinusb)
You must supply the path to hidusb.dll (it's not in this repo — extract it
from the Costura-embedded resources inside the vendor software's main exe).

Usage:
  py dump_flash.py --dll PATH\\TO\\costura64.hidusb.dll [--dll-dir PATH\\TO\\dir]

  # With Costura-extracted folder (has all runtime deps):
  py dump_flash.py --dll C:\\extracted\\costura64.hidusb.dll --dll-dir C:\\extracted
"""
import argparse, ctypes, os, sys, threading, time
from ctypes import c_char_p, c_wchar_p, c_int, c_ubyte, CFUNCTYPE, POINTER

import pywinusb.hid as hid

VID, PID = 0x3554, 0xF55E


def find_col05_path():
    """Return the HID device path for MI_01 Col05 (UsagePage 0xFF02, 17-byte output)."""
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


def load_dll(dll_path, dll_dir=None):
    if dll_dir and hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(dll_dir)
    elif dll_dir:
        # Older Python: prepend to PATH
        os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')
    return ctypes.CDLL(dll_path, winmode=0)  # winmode=0 = use AltSearch path


OnUsbDataReceived = CFUNCTYPE(None, POINTER(c_ubyte), c_int, POINTER(c_ubyte), c_int)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll', required=True, help='Path to costura64.hidusb.dll')
    ap.add_argument('--dll-dir', help='Directory containing the DLL + its deps (msvcp140/vcruntime140)')
    ap.add_argument('--wait', type=float, default=3.0, help='Seconds to wait for replies after each call')
    ap.add_argument('--out', default='flash_dump.bin', help='Output file for assembled flash dump')
    args = ap.parse_args()

    if not os.path.exists(args.dll):
        print(f"DLL not found: {args.dll}"); sys.exit(1)

    print(f"Loading {args.dll}...")
    dll = load_dll(args.dll, args.dll_dir or os.path.dirname(args.dll))

    # Signatures (from DriverLib.UsbServer.cs).
    # Note: C# StringBuilder in [DllImport] defaults to CharSet.Ansi on
    # .NET Framework when no CharSet is specified. So these are ANSI char*,
    # not wchar_t*.
    dll.CS_UsbServer_Start.argtypes = [c_char_p, c_char_p, OnUsbDataReceived]
    dll.CS_UsbServer_Start.restype  = None
    dll.CS_UsbServer_Exit.argtypes  = []
    dll.CS_UsbServer_Exit.restype   = None

    for name in ('CS_UsbServer_ReadEncryption',
                 'CS_UsbServer_ReadVersion',
                 'CS_UsbServer_ReadAllFlashData',
                 'CS_UsbServer_ReadConfig',
                 'CS_UsbServer_ReadReportRate',
                 'CS_UsbServer_ReadDPILed',
                 'CS_UsbServer_ReadLedBar',
                 'CS_UsbServer_ReadCidMid',
                 'CS_UsbServer_ReadCurrentDPI',
                 'CS_UsbServer_ReadBatteryLevel',
                 'CS_UsbServer_ReadOnLine'):
        fn = getattr(dll, name)
        fn.argtypes = []
        fn.restype  = None

    dll.CS_UsbServer_ReadFalshData.argtypes = [c_int, c_int]
    dll.CS_UsbServer_ReadFalshData.restype  = None

    path = find_col05_path()
    if not path:
        print("ERROR: could not locate MI_01 Col05."); sys.exit(1)
    print(f"Endpoint: {path}\n")

    # Thread-safe replies collector
    lock = threading.Lock()
    replies = []   # list of (cmd_bytes, data_bytes, phase_label)
    current_phase = ['init']

    def _cb(cmd_ptr, cmd_len, data_ptr, data_len):
        cmd  = bytes(cmd_ptr[:cmd_len])   if cmd_len  > 0 else b''
        data = bytes(data_ptr[:data_len]) if data_len > 0 else b''
        with lock:
            replies.append((current_phase[0], cmd, data))
        # Echo inline too so we can see as it streams
        tag = current_phase[0]
        cs = cmd.hex(' ') if cmd else '-'
        if len(data) <= 64:
            ds = data.hex(' ')
        else:
            ds = data[:48].hex(' ') + f" ... ({len(data)} bytes total)"
        print(f"  [{tag}] cmd={cs}  data[{len(data)}]={ds}")

    cb = OnUsbDataReceived(_cb)   # keep alive!

    print("Starting UsbServer worker...")
    path_bytes = path.encode('ascii')
    dll.CS_UsbServer_Start(path_bytes, path_bytes, cb)
    time.sleep(0.5)

    def phase(name, fn):
        print(f"\n=== {name} ===")
        current_phase[0] = name
        try:
            fn()
        except Exception as e:
            print(f"  call failed: {e}")
        time.sleep(args.wait)

    phase('ReadVersion',        dll.CS_UsbServer_ReadVersion)
    phase('ReadCidMid',         dll.CS_UsbServer_ReadCidMid)
    phase('ReadOnLine',         dll.CS_UsbServer_ReadOnLine)
    phase('ReadBatteryLevel',   dll.CS_UsbServer_ReadBatteryLevel)
    phase('ReadCurrentDPI',     dll.CS_UsbServer_ReadCurrentDPI)
    phase('ReadReportRate',     dll.CS_UsbServer_ReadReportRate)
    phase('ReadConfig',         dll.CS_UsbServer_ReadConfig)
    phase('ReadDPILed',         dll.CS_UsbServer_ReadDPILed)
    phase('ReadLedBar',         dll.CS_UsbServer_ReadLedBar)
    phase('ReadEncryption',     dll.CS_UsbServer_ReadEncryption)
    phase('ReadAllFlashData',   dll.CS_UsbServer_ReadAllFlashData)

    print("\nStopping worker...")
    dll.CS_UsbServer_Exit()
    time.sleep(0.2)

    print(f"\n=== Summary ===")
    print(f"Total replies: {len(replies)}")
    by_phase = {}
    for ph, cmd, data in replies:
        by_phase.setdefault(ph, []).append((cmd, data))
    for ph in by_phase:
        msgs = by_phase[ph]
        total_data = sum(len(d) for _, d in msgs)
        print(f"  {ph:22s}  {len(msgs):3d} replies, {total_data:6d} data bytes")

    flash = b''.join(d for ph, _, d in replies if ph == 'ReadAllFlashData')
    if flash:
        with open(args.out, 'wb') as f: f.write(flash)
        print(f"\nFlash dump saved: {args.out}  ({len(flash)} bytes)")

    # Save the full reply log too
    log_path = os.path.splitext(args.out)[0] + '_replies.txt'
    with open(log_path, 'w', encoding='utf-8') as f:
        for ph, cmd, data in replies:
            f.write(f"[{ph}] cmd={cmd.hex(' ') if cmd else '-'}  data[{len(data)}]={data.hex(' ')}\n")
    print(f"Reply log saved: {log_path}")


if __name__ == '__main__':
    main()
