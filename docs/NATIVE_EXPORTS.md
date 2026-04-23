# Native Exports of `hidusb.dll`

The vendor app's native library (shipped as `costura64.hidusb.dll` embedded
inside the exe, 64-bit) exports **180 functions**. The .NET side only
declares ~30 of them. The rest are either unused or only called from other
Compx-internal tools.

This page documents the functions that matter for reading mouse state, with
the signatures taken from `DriverLib.UsbServer.cs` in the decompiled source.

## Lifecycle

```c
// Start the background USB worker. The callback receives every response
// the mouse sends back on the input endpoint.
void CS_UsbServer_Start(
    const wchar_t *inputEndpoint,     // HID device path for input (17-byte input on Col05)
    const wchar_t *outputEndpoint,    // HID device path for output (same, for our M612-PRO)
    OnUsbDataReceived callback);

// Stop the worker.
void CS_UsbServer_Exit(void);

// The callback signature the DLL expects.
typedef void (*OnUsbDataReceived)(
    const uint8_t *cmd_ptr, int cmd_len,
    const uint8_t *data_ptr, int data_len);
```

The worker runs on a thread inside the DLL, dispatches reads/writes through
the normal HID endpoint, and invokes the callback when the mouse replies.

## Read-side (we never invoked these)

```c
void CS_UsbServer_ReadEncryption(void);       // CRITICAL: may return key material
void CS_UsbServer_ReadAllFlashData(void);     // Full user-flash dump
void CS_UsbServer_ReadFalshData(int startAddress, int length);   // sic "Falsh"
void CS_UsbServer_ReadConfig(void);           // MouseConfig
void CS_UsbServer_ReadReportRate(void);       // Current reportRate byte
void CS_UsbServer_ReadVersion(void);          // Firmware version
void CS_UsbServer_ReadDPILed(void);
void CS_UsbServer_ReadLedBar(void);
void CS_UsbServer_ReadCurrentDPI(void);
void CS_UsbServer_ReadCidMid(void);
void CS_UsbServer_ReadBatteryLevel(void);
void CS_UsbServer_ReadOnLine(void);
void CS_UsbServer_ReadDonglePairStatus(void);
```

All return `void` and deliver results asynchronously via the callback.

## Write-side (most invoked by vendor app during Apply)

```c
void CS_UsbServer_SetCurrentConfig(int configId);
void CS_UsbServer_SetVidPid(int vid, int pid);
void CS_UsbServer_SetDeviceDescriptorString(const wchar_t *s);
void CS_UsbServer_SetClearSetting(void);
void CS_UsbServer_SetPCDriverStatus(bool isActived);
void CS_UsbServer_Set4KDongleRGB(const DongleRGB *dongleRGB);
void CS_UsbServer_SetLongRangeMode(bool enable);
void CS_UsbServer_SetThreadSleepTime(int ms);
```

## Mode-transition (dangerous — don't call blindly)

```c
void CS_UsbServer_EnterUsbUpdateMode(void);   // !! Enters Compx bootloader
void CS_UsbServer_EnterMTKMode(void);         // ?? Unknown
void CS_UsbServer_EnterDonglePair(void);
void CS_UsbServer_EnterDonglePairWithCidMid(byte cid, byte mid);
void CS_UsbServer_EnterDonglePairOnlyCid(byte cid);
```

## Data marshalling helpers (no USB traffic)

```c
IntPtr CS_BufferToDPILed(byte *buf);
IntPtr CS_BufferToLedBar(byte *buf);
// Plus: BufferToDPIColor, BufferToKeyFunMap, BufferToMacroKey,
//       BufferToShortcutKey, MacroKeyToBuffer, ShortcutKeyToBuffer,
//       MouseConfigParser, ProtocolDataParser, ProtocolDataUpdate,
//       CS_ProtocolDataCompareUpdate, ...
```

These take a raw byte buffer (like the profile `.bin`) and convert to/from
the C# structs. Useful if you want to write a re-encoder without Python.

## How to call these from Python

The DLL is a standard cdecl Windows DLL. Load it with `ctypes.CDLL`:

```python
import ctypes
from ctypes import c_char_p, c_int, CFUNCTYPE, POINTER, c_ubyte

dll = ctypes.CDLL(r'path\to\costura64.hidusb.dll')

# Callback: void(*)(byte*, int, byte*, int)
CB = CFUNCTYPE(None, POINTER(c_ubyte), c_int, POINTER(c_ubyte), c_int)

dll.CS_UsbServer_Start.argtypes = [c_char_p, c_char_p, CB]
dll.CS_UsbServer_Start.restype  = None

dll.CS_UsbServer_ReadAllFlashData.argtypes = []
dll.CS_UsbServer_ReadAllFlashData.restype  = None

def on_data(cmd_ptr, cmd_len, data_ptr, data_len):
    cmd  = bytes((cmd_ptr[i]  for i in range(cmd_len)))  if cmd_len  > 0 else b''
    data = bytes((data_ptr[i] for i in range(data_len))) if data_len > 0 else b''
    print(f"cmd={cmd.hex()}  data[{data_len}]={data.hex()}")

cb = CB(on_data)     # keep the reference alive!

# Endpoints are the HID device paths (UTF-16 / wide). You can find them by
# enumerating VID 0x3554 PID 0xF55E and grabbing the MI_01 Col05 path.
dll.CS_UsbServer_Start(endpoint_w, endpoint_w, cb)
dll.CS_UsbServer_ReadAllFlashData()
# ... wait for callback ...
dll.CS_UsbServer_Exit()
```

Notes:
- `CS_UsbServer_Start` uses **wchar_t** endpoints on Windows. Pass
  `ctypes.c_wchar_p` or use `.argtypes = [c_wchar_p, c_wchar_p, CB]`.
- Keep the `CFUNCTYPE` wrapped callback in a Python variable — if it's
  garbage collected the DLL will call into freed memory.
- You must call `CS_UsbServer_Start` **before** any read/write function
  that uses the worker. Without it, nothing happens.

## Reality check

We documented this without actually invoking the functions yet. Brick risk
for pure read calls is near-zero (they use the same HID output path we've
already exercised), but:

- If the DLL has threading bugs (it's vendor software — cheap mouse
  tooling, not known for robustness), a bad call could hang the DLL thread
  or crash the Python host. Nothing persistent on the mouse.
- `CS_UsbServer_EnterUsbUpdateMode` on the other hand is **highly
  dangerous** — don't call it unless you've got a valid firmware image
  and the password to re-flash with.
