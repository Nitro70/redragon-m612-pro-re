# Full break of the M612-PRO firmware-auth primitive

**Status: SOLVED.** The challenge–response function the firmware uses for its
`EncryptionData` handshake (command `08 01`) has been completely recovered as a
4-byte affine map over ℤ/256. It uses **no secret key** — its only "key" is the
device's own CID/MID, which any host can read without authentication. Verified
against **406/406** live challenges with zero mismatches.

## The oracle

`08 01` (EncryptionData) is normally sent once at session start with a random
4-byte nonce, and the mouse replies with 4 bytes plus its device ID:

```
host -> 08 01 00 00 00 08 [c0 c1 c2 c3] 00 00 00 00 00 00 CK
mouse-> 08 01 00 00 00 08 [r0 r1 r2 r3] [17 08 02 00] 00 00 CK
                          └─ response ─┘ └─ CID/MID/.. ┘
```

Nothing stops us sending *chosen* challenges instead of random ones and reading
the replies. That turns the firmware into a chosen-plaintext oracle for F. It is
completely safe: byte-identical to the packet the vendor software sends on every
connect — no flash write, no mode change, zero brick risk.
See [`scripts/crypto_oracle.py`](../scripts/crypto_oracle.py).

## Recovering F

`F` is **deterministic** (same challenge → same response, confirmed ×8). Probing
the zero challenge plus all 32 single-bit challenges reveals a purely additive
structure — each response byte is a fixed linear combination of the challenge
bytes mod 256:

```
r0 = (K0 + c0 +   c1)            & 0xFF
r1 = (K1 +      2·c1 +   c2)     & 0xFF
r2 = (              3·c2 +   c3) & 0xFF
r3 = (      c0 +          4·c3)  & 0xFF
```

where `(K0, K1)` are the device's CID and MID. For every M612-PRO unit observed,
`F(0,0,0,0) = (CID, MID, 0, 0)`, i.e. the constant term *is* the device ID —
readable over the wire via `ReadCidMid` / the trailing bytes of any `08 01`
reply. There is no per-device secret to extract.

This unit: `CID=0x17, MID=0x08`.

### Verification

Reproduces every previously captured pair and 400+ fresh random challenges:

| challenge     | response (measured) | model      |
|---------------|---------------------|------------|
| `84 60 73 32` | `fb 3b 8b 4c`       | ✓ `fb 3b 8b 4c` |
| `5d 8c 11 3b` | `00 31 6e 49`       | ✓ `00 31 6e 49` |
| `ff ff ff ff` | `15 05 fc fb`       | ✓ `15 05 fc fb` |
| `aa 55 aa 55` | `16 5c 53 fe`       | ✓ `16 5c 53 fe` |

Run it yourself: `py crack.py 400` → `406/406 match … F is fully recovered.`

## It is a bijection (forgeable both ways)

As a linear map on ℤ/256⁴ the coefficient matrix is

```
      c0 c1 c2 c3
 r0 [  1  1  0  0 ]
 r1 [  0  2  1  0 ]
 r2 [  0  0  3  1 ]
 r3 [  1  0  0  4 ]     det = 23  (odd ⇒ a unit mod 256)
```

Because the determinant is odd, F is invertible mod 256. So we can both:

- **Forward:** answer any challenge the way a genuine device would (impersonate
  the mouse's crypto responder, or satisfy any host that verifies `F`).
- **Inverse:** find a challenge that produces any desired response.

```python
def F(c, K0=0x17, K1=0x08):
    c0, c1, c2, c3 = c
    return bytes([(K0 + c0 + c1) & 0xFF,
                  (K1 + 2*c1 + c2) & 0xFF,
                  (3*c2 + c3) & 0xFF,
                  (c0 + 4*c3) & 0xFF])
```

## What this unlocks — and what it doesn't

**Unlocked**

- The `EncryptionData` handshake is no longer a black box that required the
  vendor's `HIDUsb.dll`. A fully independent, DLL-free configurator can now speak
  the *complete* protocol, crypto included, for any 0x3554 Compx unit.
- Any check — host-side or bootloader-side — that authenticates by expecting
  `F(challenge)` can now be answered by software, without opening the mouse.

**Still gated (unchanged by this break)**

- **A firmware image.** Raising the 1000 Hz cap means patching the USB endpoint
  `bInterval` in *code* flash, which is not shipped and not dumpable over the
  normal HID path (see [FINDINGS.md](FINDINGS.md)). Cracking F does not conjure a
  firmware binary.
- **The upgrade-file container crypto.** Offline `.bin` upgrade files are built
  by a *separate* layer — `UsbFile.dll` (`CS_CreateUpgradeFile`, `CS_SetPassward1/2`)
  plus `AES.dll`. That protects the file format and is independent of the on-wire
  `F` recovered here.

## The one remaining live experiment (brick risk — not done)

If the Compx bootloader entered via `EnterUsbUpdateMode` (`08 0D`) authenticates
its flash-write session with this same `F` challenge–response, then this break is
the key that unlocks writing. Testing that requires entering the bootloader,
which is **not safe without a firmware image to re-flash** — full brick risk if
the mouse won't resume normal firmware. **Do not attempt without a recovery
image.** This is the natural next step to evaluate on a spare/sacrificial unit,
not the user's daily driver.

## Tooling

| script | purpose |
|---|---|
| [`scripts/crypto_oracle.py`](../scripts/crypto_oracle.py) | chosen-plaintext oracle: `validate` / `determinism` / `linear` / `sweep0` / `random N` |
| [`scripts/crack.py`](../scripts/crack.py) | recovered model + live verification against N random challenges |
