# Redragon M612-PRO (Predator) Reverse Engineering

Full HID protocol decode, Frida-based capture rig, and driver-free Python tools
for the Redragon M612-PRO wired/wireless gaming mouse (USB VID `0x3554` /
PID `0xF55E`, Compx/MosArt CX52850P MCU, PMW3104 sensor).

No drivers installed, no kernel components used. Everything here runs as
ordinary userland Python on Windows.

## What this repo gets you

- Working Python tool to **set the fire-button rapid-click interval below the
  vendor GUI's 10 ms floor** (firmware accepts down to 1 ms).
- Working Python tool to **inspect and patch exported profile .bin files**
  (debounce, DPI stages, report rate, etc.).
- A **Frida hook** that captures everything the vendor software writes to
  the mouse — reusable for reverse engineering other HID devices.
- Full [protocol reference](docs/PROTOCOL.md) — command set, packet format,
  checksum, session structure.
- [Flash-data layout](docs/FLASHDATA_LAYOUT.md) for the exported .bin profile
  format.
- [Findings](docs/FINDINGS.md) — what works, what doesn't, why the 125 Hz
  polling ceiling can't be lifted from software.

## Quick start

```powershell
pip install pywinusb frida-tools

# List all HID interfaces exposed by the mouse
py scripts/enumerate.py

# Set the fire-button rapid-click interval to 3 ms (below GUI floor)
py scripts/set_fire.py 3 4 full

# Patch an exported profile .bin: set debounce to 1 ms, leave others alone
py scripts/patch_bin.py in.bin out.bin keyDebounceTime=1

# Inspect an exported profile .bin
py scripts/analyze_bin.py profile.bin

# Frida-sniff what the vendor software sends to the mouse
py scripts/sniff.py "C:\path\to\Mouse Drive Beta.exe"
```

## What doesn't work — be honest

- The mouse's USB endpoint descriptor has `bInterval=8` baked into firmware,
  so the polling rate is hardware-locked at 125 Hz. Effective click rate
  caps at ~62 CPS regardless of what the fire-button interval is set to.
- The vendor's DLL (`HIDUsb.dll` / `UsbFile.dll`) has no firmware-read
  function — only write. You can't dump firmware from software alone.
- Compx firmware files are password-protected (`CS_SetPassward1/2`).
- No firmware images are shipped with the vendor software.

For full reasoning see [docs/FINDINGS.md](docs/FINDINGS.md).

## Hardware targeted

| Property | Value |
|---|---|
| Product | Redragon M612-PRO / M612RGB-PRO (Predator) |
| USB VID | `0x3554` (Compx / MosArt) |
| USB PID | `0xF55E` (wired), `0xF5D5` (2.4G dongle) |
| MCU | Compx **CX52850P** (8051-core) |
| Dongle MCU | Compx CX52650N |
| Wireless aux | CH32V305 (RISC-V, for 2.4G) |
| Sensor | PixArt **PMW3104** |
| USB polling | 125 Hz (bInterval=8, fixed) |
| Modes | Wired / 2.4G / Bluetooth ("3-mode mouse") |

## Scripts

| Script | Purpose | Writes to mouse? |
|---|---|---|
| `enumerate.py`  | List HID interfaces + feature reports           | No |
| `probe.py`      | Send candidate read-config commands             | No (pokes only) |
| `sniff.py`      | Frida-hook vendor software, log HID writes      | No |
| `analyze_bin.py`| Decode / diff an exported profile .bin          | No |
| `patch_bin.py`  | Edit MouseConfig fields in a profile .bin       | No |
| `set_fire.py`   | Set fire-button interval via raw WriteFile      | **Yes (persists)** |

## Layout

```
.
├── README.md
├── LICENSE
├── .gitignore
├── scripts/            Python tools (above)
└── docs/
    ├── PROTOCOL.md          HID command set and packet format
    ├── FLASHDATA_LAYOUT.md  Exported .bin structure
    └── FINDINGS.md          What's possible and what isn't
```

## Related work

- [Qehbr/m913-ctl](https://github.com/Qehbr/m913-ctl) — Redragon M913 (SINOWEALTH). Same `04 speed times cksum` style fire-button encoding.
- [dokutan/mouse_m908](https://github.com/dokutan/mouse_m908) — Redragon M908 / M711 / M612-RGB (Holtek). Partial M612 support, has bricked units.
- [libratbag/libratbag](https://github.com/libratbag/libratbag) — `driver-sinowealth.c` covers SINOWEALTH-chipset Redragons.
- [carlossless/sinowealth-kb-tool](https://github.com/carlossless/sinowealth-kb-tool) — firmware flashing for SINOWEALTH chips. Not compatible with Compx CX52850P.

The M612-PRO is Compx/MosArt, distinct from all of the above. This repo
appears to be the first public decode of that chip family's protocol.

## License

MIT. See [LICENSE](LICENSE). Vendor software was not redistributed —
only protocol facts observed on the wire are documented here.
