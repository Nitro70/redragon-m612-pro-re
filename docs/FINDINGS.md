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
- The vendor DLL (`HIDUsb.dll`, `UsbFile.dll`) has no firmware-READ function.
  The `EnterUsbUpdateMode` command (`08 0D`) puts the mouse into the Compx
  bootloader, but the bootloader protocol is only exercised in one direction
  — the DLL only knows how to send a prepared, password-protected firmware
  blob.
- No firmware image is shipped with the vendor software (no
  `bin/*.bin` folder).
- Compx firmware files are **password-protected** (`CS_SetPassward1/2`,
  `CS_isPassward1/2` exports in `UsbFile.dll`). Even if one surfaced online
  we'd need the password to decode it.

### What would actually work

- **Hardware probe (SWD/JTAG)** on the Compx CX52850P MCU. This chip is
  8051-core. A $5 ST-Link or Raspberry Pi Pico configured as a debug probe
  can dump flash. Then you'd binary-patch the USB endpoint descriptor's
  `bInterval` byte from `0x08` to `0x01` and flash back. Requires opening
  the mouse, identifying debug pads (not documented), and soldering.

At $25–30 retail for this mouse vs. $30 for a mouse shipping with native
1000 Hz polling, the economics aren't compelling.

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
4. Firmware sends back a single 17-byte ack on the input report.

The ack is **always the same fixed stub** `08 00 01 00 ... 4C` regardless
of what was sent. There's no read-flash-contents reply. The only way the
software gets state back is via `GetCurrentConfig` (`0x0E`) and
`ReadVersionID` (`0x12`), which we haven't observed returning richer data
— the reply remained the stub in our captures. It's possible those replies
do vary and we missed them; a more careful capture around those specific
commands would clarify.

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
