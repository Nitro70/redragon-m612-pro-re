# Exported Profile `.bin` Layout

The vendor software's Export / Import feature writes and reads a 10 492-byte
binary file. Below is the reverse-engineered layout derived from the decompiled
`DriverLib.FlashDataMap`, `MouseConfig`, and related C# structs.

## File-level structure

```
0x0000 ..0x001F  (32 bytes)  Manufacturer header: "Compx Inc" + NUL padding
0x0020 ..0x003F  (32 bytes)  Sensor name string: "3104" + NUL padding  (PMW3104)
0x0040 ..           FlashDataMap — the actual config, layout below.
```

The FlashDataMap is a C# struct (`[StructLayout(LayoutKind.Sequential)]`)
marshaled directly:

```csharp
public struct FlashDataMap {
    public MouseConfig          mouseConfig;          // 15 bytes
    public DPIConfig[]          dpiConfig;            // 8 entries
    public DPILed               dpiLed;
    public LedBar               ledBar;
    public KeyFunMap[]          keys;                 // 16 entries
    public ShortCutKey[]        shortCutKey;          // 16 entries
    public MacroKey[]           macroKey;             // 16 entries
}
```

The tail of the file (past ~0x2a0) is mostly zero-padding up to the fixed
10 492-byte length. Any non-zero bytes there in an export file are leftover
buffer contents from the software (we've seen Photoshop XMP metadata there,
likely memcpy overruns from a resource image the vendor tool loads — harmless).

## `MouseConfig` — 15 bytes at offset `0x40`

| Offset | Field                         | Type | Notes |
|---|---|---|---|
| `0x40` | `reportRate`                  | u8 | See enum below. M612-PRO firmware ignores this. |
| `0x41` | `maxDPI`                      | u8 | Number of configured DPI stages |
| `0x42` | `currentDPI`                  | u8 | Default stage index |
| `0x43` | `xSpindown`                   | u8 | Sensor X angle-snap / spindown |
| `0x44` | `ySpindown`                   | u8 | |
| `0x45` | `silenceHeight`               | u8 | Silent-click height? |
| `0x46` | `keyDebounceTime`             | u8 | ms, 1..8 in vendor GUI |
| `0x47` | `motionSyncEnable`            | u8 | Boolean |
| `0x48` | `allLedOffTime`               | u8 | Seconds before idle LED off |
| `0x49` | `linearCorrectionEnable`      | u8 | Boolean |
| `0x4A` | `rippleControlEnable`         | u8 | Boolean |
| `0x4B` | `moveOffLedEnable`            | u8 | Boolean |
| `0x4C` | `sensorCustomSleepTimeEnable` | u8 | Boolean |
| `0x4D` | `sensorSleepTime`             | u8 | |
| `0x4E` | `sensorPowerSavingModeEnable` | u8 | Boolean |

### `REPORT_RATE` enum values

| Value | Meaning |
|---|---|
| `0x01` | 1000 Hz |
| `0x02` | 500 Hz |
| `0x04` | 250 Hz |
| `0x08` | 125 Hz |
| `0x10` | 2000 Hz |
| `0x20` | 4000 Hz |

M612-PRO firmware appears to hardcode `bInterval=8` in its USB descriptor
regardless of the flash byte. Setting this to `0x01` and re-importing does
not raise the effective polling rate.

## Remaining structs

These are referenced by `FlashDataMap` but field-level offsets were not fully
mapped in this repo. The decompiled names are documented here for future
work.

### `DPIConfig[8]` — DPI stage configuration

Holds the 8 DPI stage values. Each entry likely has sensor-encoded DPI,
X/Y multiplier, and an enabled flag.

### `DPILed`, `LedBar`

RGB configuration for the DPI indicator LED and the main LED bar.

### `KeyFunMap[16]`, `ShortCutKey[16]`, `MacroKey[16]`

Button remapping, shortcut definitions, and macros. 16 entries each means
the firmware has 16 slots regardless of how many physical buttons the mouse
has — M612-PRO uses about 6–8 of them.

## How to find specific fields

Two good techniques:

1. **Diff two exports.** Save a profile, change one UI setting, save again,
   diff the two files. `scripts/analyze_bin.py a.bin b.bin` does this and
   prints contiguous byte ranges that differ.
2. **Read the decompiled struct.** Open the vendor software's decompilation
   locally and find `DriverLib.<StructName>` — ilspycmd gives clean C#.

## Patching exports

The software's Import reads and writes exports back to the mouse *without*
range-checking the values against its own GUI clamps. This means you can
bypass GUI floors/ceilings by editing the .bin directly and importing.
See [scripts/patch_bin.py](../scripts/patch_bin.py).

Example: `patch_bin.py in.bin out.bin keyDebounceTime=1 reportRate=1`
