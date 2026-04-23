# M612-PRO HID Protocol Reference

Observed on USB VID `0x3554` / PID `0xF55E` (wired mode).

## HID interface layout

The mouse exposes three USB interfaces. Interface `MI_01` has six HID top-level
collections (the `colNN` suffix in Windows HID paths):

| Path suffix  | UsagePage | Usage  | In / Out / Feat | Purpose |
|---|---|---|---|---|
| `mi_01&col01` | `0xFF05` | `0x0000` | 8 / 0 / 0   | Vendor HID — unused |
| `mi_01&col02` | `0xFF03` | `0x0000` | 8 / 0 / 0   | Vendor HID — unused |
| `mi_01&col03` | `0x000C` | `0x0001` | 3 / 0 / 0   | Consumer control |
| `mi_01&col04` | `0x0001` | `0x0080` | 2 / 0 / 0   | System controller |
| **`mi_01&col05`** | **`0xFF02`** | **`0x0002`** | **17 / 17 / 0** | **Config pipe (all writes below go here)** |
| `mi_01&col06` | `0xFF04` | `0x0002` | 0 / 0 / 8   | Status feature report 0x06 |

`MI_00` and `MI_02` are the standard boot-mouse interfaces (Windows HID mouse
class driver owns them exclusively — userland apps can't open them).

All configuration traffic happens as 17-byte Output Report `0x08` writes on
`mi_01&col05`. Writes must arrive via `CreateFile` + `WriteFile` (interrupt
OUT endpoint). `HidD_SetOutputReport` (control endpoint) is silently ignored
for config.

## Packet format

Every config packet is **exactly 17 bytes**:

```
 byte  0  : 0x08             Report ID (always the same)
 byte  1  : cmd              Command ID (see table below)
 bytes 2..15: command-specific payload
 byte 16  : checksum         (0x55 - sum(bytes[0..15])) & 0xFF
```

The checksum covers only bytes 0 through 15 and is placed at byte 16.

```python
def checksum(body15: bytes) -> int:
    return (0x55 - sum(body15)) & 0xFF
```

## Command IDs

Extracted from `DriverLib.UsbCommandID` in the vendor software:

| Cmd  | Name                       | Observed on wire? |
|---|---|---|
| 1    | EncryptionData             | Yes — session init with 4-byte nonce |
| 2    | PCDriverStatus             | Yes — begin profile write |
| 3    | DeviceOnLine               | Yes — status poll |
| 4    | BatteryLevel               | Yes |
| 5    | DongleEnterPair            | — |
| 6    | GetPairState               | — |
| **7**| **WriteFlashData**         | **Yes — button/DPI/etc. config** |
| **8**| **ReadFlashData**          | **Yes — paged memory read/write** |
| 9    | ClearSetting               | — |
| 10   | StatusChanged              | — |
| 11   | SetDeviceVidPid            | — |
| 12   | SetDeviceDescriptorString  | — |
| **13** | **EnterUsbUpdateMode**   | — (bootloader entry, untested) |
| 14   | GetCurrentConfig           | Yes |
| 15   | SetCurrentConfig           | — |
| 16   | ReadCIDMID                 | — |
| 17   | EnterMTKMode               | — |
| 18   | ReadVersionID              | Yes |
| 20   | Set4KDongleRGB             | — |
| 21   | Get4KDongleRGBValue        | — |
| 22   | SetLongRangeMode           | — |
| 23   | GetLongRangeMode           | — |
| 240  | WriteKBCIdMID              | — |
| 241  | ReadKBCIdMID               | — |

## Observed packet structures

### `08 01` — Session init (EncryptionData)

```
08 01 00 00 00 08 NN NN NN NN 00 00 00 00 00 00 CK
                  └── random 4-byte nonce ──┘
```

Sent as the first packet after `CreateFile`. A fresh nonce is generated per
session by the vendor software (likely not validated against anything — just
a session ID the mouse echoes back).

### `08 02` — Begin config (PCDriverStatus)

```
08 02 00 00 00 01 01 00 00 00 00 00 00 00 00 00 49
                  └─ byte 5 = 0x01: profile 1
                     byte 6 = 0x01: begin-write flag
```

Precedes a full profile rewrite. Without this, single `08 07` writes may be
silently ignored on a fresh handle.

### `08 07` — WriteFlashData

Set button behavior. Button-ID in byte 4 identifies which physical button.

**Fire / rapid-click button**:

```
08 07 00 00 74 04 CC SS 00 (0x51-SS) 00 00 00 00 00 00 CK
          │  │  │  │  │  │
          │  │  │  │  │  └ complement of SS (enforced: byte9 == 0x51 - byte7)
          │  │  │  │  └ speed: ms between clicks while held (GUI exposes 10..255)
          │  │  │  └ count:  clicks per trigger (GUI default 4)
          │  │  └ mode 0x04 = rapid fire
          │  └ button ID 0x74 = fire button
          └ subcommand (unused here)
```

Firmware accepts speed down to 1 ms, but the USB polling rate caps effective
click rate at ~62 CPS (click + release both have to be reported, each taking
one poll interval of 8 ms).

Other observed button-ID variants during an Import of a different profile:

```
08 07 00 00 A0 07 01 FF 00 FF 07 09 46 00 00 00 4A   (some button, rich payload)
08 07 00 00 A9 02 08 4D 00 00 00 00 00 00 00 00 46   (button 0xA9, mode 0x02)
08 07 00 00 AD 02 06 4F 00 00 00 00 00 00 00 00 42
08 07 00 02 00 02 00 FF ...                          (paged write, page 2 addr 0x00)
08 07 00 02 20 08 02 82 B6 00 42 B6 00 23 00 00 E7
08 07 00 02 40 08 ...
```

So `08 07` is a generic flash-write dispatcher. Byte 3 is a page selector,
byte 4 is either a button ID (page 0) or a page-local address.

### `08 08` — ReadFlashData / paged write

Despite its enum name, observed use during Apply is writing. Format:

```
08 08 00 PG AD VL 00 00 00 00 00 00 00 00 00 00 CK
         │  │  │
         │  │  └ value byte
         │  └ byte address within page
         └ page number
```

Used to write the DPI lookup table (hundreds of small writes setting
successive bytes). The page=0 addresses `0x00..0xB4` are the encoded-DPI
table for the PMW3104 sensor. Specific known addresses:

| Page | Addr | Value observed | Meaning |
|---|---|---|---|
| 0 | 0x4C | 0x08        | keyDebounceTime (ms)         |
| 0 | 0xBE | 0x02        | unknown (possibly report-rate-related, but firmware ignores) |

### `08 04` — BatteryLevel (here: ack)

```
08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49
```

Sent as an intra-session acknowledgement during Apply. Exact semantics TBD.

### `08 12` — ReadVersionID

```
08 12 00 00 00 00 00 00 00 00 00 00 00 00 00 00 3B
```

### `08 0E` — GetCurrentConfig

```
08 0E 00 00 00 00 00 00 00 00 00 00 00 00 00 00 3F
```

### Mouse reply on `mi_01&col05` input

Every write produces at least one input report back on the same collection:

```
08 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 4C
```

This ACK is **constant** — the mouse does not return the requested data in
reply to our probes, meaning there's no meaningful "read config" command
exposed over this path. If there is a read command it wasn't among
`0x01..0x12`.

## Full Apply sequence

Minimum sequence that persists a fire-button change on a fresh handle:

```
CreateFile(\\?\hid#vid_3554&pid_f55e&mi_01&col05#...)
  → WriteFile(17): 08 01 00 00 00 08 <nonce> 00 00 00 00 00 00 <chk>
  → WriteFile(17): 08 02 00 00 00 01 01 00 00 00 00 00 00 00 00 00 49
  → WriteFile(17): 08 07 00 00 74 04 04 SS 00 (0x51-SS) 00 00 00 00 00 00 <chk>
  → WriteFile(17): 08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49
  → WriteFile(17): 08 12 00 00 00 00 00 00 00 00 00 00 00 00 00 00 3B
  → WriteFile(17): 08 0E 00 00 00 00 00 00 00 00 00 00 00 00 00 00 3F
CloseHandle()
```

Reference implementation: [scripts/set_fire.py](../scripts/set_fire.py).

## Minimal sequence (preserves other settings)

If you only want to tweak one byte without re-sending the full profile:

```
→ 08 01 <nonce>    session init
→ 08 07 ...        the change
→ 08 12            read version id (seems to act as commit-ish)
```

In our testing this was sufficient for the fire-button speed to stick and
preserved the user's existing debounce value.
