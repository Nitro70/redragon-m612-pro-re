# Findings

## The 125 Hz wall

The M612-PRO is hardware-capped at **~62 CPS** (clicks per second) because:

- Each click cycle needs two USB reports (press, release).
- USB polling rate = 125 Hz → one report every 8 ms → one full click cycle
  takes 16 ms → 62.5 CPS.

We verified the cap by setting fire-button interval to 1 ms via the raw HID
protocol and measuring 62 CPS (same as at 3 ms, 8 ms). The firmware happily
accepts the lower interval value; Windows just can't see the clicks faster
than the polling rate lets it.

### Why we can't fix it in software

- The `MouseConfig.reportRate` byte (offset `0x40` in the exported `.bin`) exists
  and the vendor code has UI radio buttons for 125/250/500/1000/2000/4000 Hz,
  but flashing `0x01` (= `R_1000`) via Import + replug does not change the
  USB endpoint's `bInterval`. The firmware appears to hardcode the descriptor.
- The `EnterUsbUpdateMode` command (`08 0D`) puts the mouse into the Compx
  bootloader, but the bootloader's write protocol is
  password-protected (`CS_SetPassward1/2`, `CS_isPassward1/2` exports),
  and no firmware image is shipped or publicly available.
- Changing `bInterval` requires modifying the USB descriptor inside firmware,
  which lives in the read-only code region and can't be touched from the normal
  HID protocol.

### What would actually work

- **Hardware probe (SWD/JTAG)** on the Compx CX52850P MCU. This chip is
  8051-core. A $5 ST-Link or Raspberry Pi Pico configured as a debug probe
  can dump flash. Then you'd binary-patch the USB endpoint descriptor's
  `bInterval` byte from `0x08` to `0x01` and flash back. Requires opening
  the mouse, identifying debug pads (not documented), and soldering.

At $25–30 retail for this mouse vs. $30 for a mouse shipping with native
1000 Hz polling, the economics aren't compelling.

## The hidusb.dll native export surface

The Costura-embedded `hidusb.dll` exports **180 functions**, most of which
are never called by the C# vendor app. This makes a difference: the native
library has a much richer API than the decompiled .NET code suggests.

Key exports we care about:

| Export | Called by vendor app? | What it's probably for |
|---|---|---|
| `CS_UsbServer_Start`              | Yes | Start background USB worker thread |
| `CS_UsbServer_Exit`               | Yes | Stop the thread |
| `CS_UsbServer_ReadAllFlashData`   | **Yes** (FormMain.cs:1029) | **Read the mouse's entire flash region** |
| `CS_UsbServer_ReadFalshData(addr,len)` | No | Read a byte range from flash |
| `CS_UsbServer_ReadConfig`         | Yes | Read MouseConfig struct |
| `CS_UsbServer_ReadReportRate`     | Yes | Read the current report rate byte |
| `CS_UsbServer_ReadEncryption`     | No  | **Read encryption state / possibly the key** |
| `CS_UsbServer_ReadVersion`        | Yes | Firmware version |
| `CS_UsbServer_ReadDPILed`         | Yes | RGB DPI-LED config |
| `CS_UsbServer_ReadLedBar`         | Yes | RGB main LED bar config |
| `CS_UsbServer_ReadCidMid`         | Yes | Device ID bytes |
| `CS_UsbServer_ReadCurrentDPI`     | Yes | Active DPI stage |

All of these are void-return, async. Results arrive via the
`OnUsbDataReceived(cmd_ptr, cmd_len, data_ptr, data_len)` callback
registered in `CS_UsbServer_Start`.

### What this means in practice

- The protocol **does** support reads — we just missed them because:
  1. The C# layer only documents a subset, and we hadn't dumped the native
     DLL export table until after the initial RE sweep.
  2. We never triggered a "read all" action in the vendor GUI during
     Frida capture; our captures only covered `08 07` / `08 08` writes
     from the Apply path.
- **`ReadAllFlashData` is a true flash dump** of the user-facing config
  region. It's not the firmware itself (that lives in code flash, not
  data flash), but it's enough to:
  - Verify what bytes the mouse is actually running from
  - See values that never appear in `.bin` exports
  - Catch any encrypted/hidden config not in `MouseConfig`
- **`ReadEncryption`** is the most intriguing — if it returns the
  encryption state the mouse expects for firmware validation, we might be
  able to derive or match the password without needing `UsbFile.dll`.
- To exploit these, either:
  - Load `costura64.hidusb.dll` directly via ctypes and call the
    exports (cleanest, gives us proper parsed results),
  - Or re-sniff vendor startup with Frida, which already invokes
    `ReadAllFlashData` on every launch — so the HID read commands are
    already on the wire, we just need to look for them in a fresh
    capture focused on startup.

## What does work

### Fire-button interval below the GUI floor

The vendor GUI clamps the fire-button rapid-click interval to 10 ms. The
firmware accepts anything from 1 up. [`scripts/set_fire.py`](../scripts/set_fire.py)
sets any value you want, persists it to flash.

At 125 Hz polling this doesn't raise CPS above 62, but it does let you:

- Get the absolute maximum out of the hardware (10 ms → 50 CPS, 3 ms → 62 CPS).
- Set different counts per trigger than the GUI allows.
- Program the behavior from a script instead of clicking through menus.

### Any-button rapid fire

The `08 07` command's button-ID byte (`0x74` for the dedicated fire button)
can be any of the other button IDs observed during Import captures
(`0xA0`, `0xA9`, `0xAD`, ...). This means any physical button can be made
rapid-fire — the dedicated fire button is not special, it's just the one
the GUI exposes.

### Full programmatic control over the profile

Any field of `MouseConfig` or the button/DPI/macro tables can be written
via `08 07` / `08 08`. You can bypass GUI clamps on debounce, DPI stages,
motion-sync, etc. — whatever the firmware honors, you can set.

### Scripted profile editing

`scripts/analyze_bin.py` decodes the exported `.bin`, `scripts/patch_bin.py`
edits `MouseConfig` fields non-destructively. The vendor's own Import reads
the modified file back without validation.

### Reusable HID sniff rig

`scripts/sniff.py` is a Frida hook that catches every HID write from
arbitrary vendor software on Windows, with no kernel driver installed.
Handy for reverse-engineering other mice, keyboards, or any HID device
whose vendor app you can run on your system.

## What the mouse's MCU actually does

The config pipe (`mi_01&col05`) is a synchronous 17-byte command/reply
channel. All the `08 xx` commands we see fit a simple pattern:

1. Vendor software sends a command packet.
2. Firmware parses it based on byte 1 (command ID).
3. Firmware writes to flash (for `0x07`, `0x08`, `0x02`, `0x0F`) or reads
   (for `0x0E`, `0x12`, `0x10`) or enters a mode (`0x0D` update, `0x11`
   MTK).
4. Firmware sends back one or more 17-byte reports on the input endpoint.

In our initial capture every reply was the same `08 00 01 00 ... 4C`
stub. We later found that the vendor app calls `CS_UsbServer_ReadAllFlashData`
on startup — which means real data replies *do* happen on the wire, we
just didn't capture an event that triggered them. Re-sniffing vendor
startup specifically should surface the full read protocol.

## Interesting but untested

- **`EnterUsbUpdateMode` (command `0x0D`)** puts the mouse into the Compx
  bootloader. It likely re-enumerates with a different PID. Worth a future
  look — the bootloader may accept read commands that the normal firmware
  doesn't. **Do not do this without a firmware image to re-flash**, since
  it's possible the mouse won't resume normal operation without being
  explicitly flashed back. Full brick risk if something goes wrong.
- **`EnterMTKMode` (command `0x11`)** — completely unknown, the decompiled
  source references it but not what it does. "MTK" might be MediaTek or a
  Compx-internal abbreviation.
- **`SetLongRangeMode` / `GetLongRangeMode`** — wireless range config.
  Could be interesting for 2.4G users trying to extend range past the
  vendor default.
- **Col06 feature report `0x06`** — 8 bytes, always returns a constant
  status blob (`06 00 00 00 00 00 0C 3E` in our capture). Might return
  dynamic data in some state we didn't reach.

## Protocol mapping to other Redragon chips

| Vendor chipset | VID  | Typical Redragon models | This repo applicable? |
|---|---|---|---|
| Compx / MosArt | `0x3554` | M612-PRO and sibling 3-mode mice | **Yes** |
| Holtek         | `0x04D9` | M612-RGB, M711 Cobra, some M712  | Similar *shape* but different layout (see `mouse_m908`) |
| SINOWEALTH     | `0x258A`, `0x25A7` | M913, newer M711 variants | Different protocol entirely (see libratbag) |

VID `0x3554` = MosArt Semiconductor / Compx Inc. Shows up on some MadCatz and
Cooler Master devices too, so the protocol here may transfer.
