r"""Verify the recovered model of the M612-PRO firmware auth primitive F.

Recovered affine model over Z/256 (constants = device CID,MID = 0x17,0x08):

    r0 = (K0 + c0 + c1)      & 0xFF
    r1 = (K1 + 2*c1 + c2)    & 0xFF
    r2 = (     3*c2 + c3)    & 0xFF
    r3 = (c0 +       4*c3)   & 0xFF

This script sends a batch of FRESH random challenges (different seed from the
calibration run), predicts each response with the model, and reports any
mismatch. 100% match => F is fully recovered.
"""
import sys, os, time, random
import crypto_oracle as O

K0, K1 = 0x17, 0x08   # this unit's CID, MID (read via ReadCidMid)


def model(c, k0=K0, k1=K1):
    c0, c1, c2, c3 = c
    r0 = (k0 + c0 + c1)      & 0xFF
    r1 = (k1 + 2 * c1 + c2)  & 0xFF
    r2 = (3 * c2 + c3)       & 0xFF
    r3 = (c0 + 4 * c3)       & 0xFF
    return bytes([r0, r1, r2, r3])


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    path = O.find_col05_path()
    if not path:
        print("ERROR: mouse not found"); sys.exit(1)
    pipe = O.Pipe(path)
    rng = random.Random(0xC0FFEE)  # different seed than crypto_oracle random
    ok = miss = bad = 0
    mismatches = []
    try:
        # include a few structured edge cases first
        fixed = [bytes([0, 0, 0, 0]), bytes([0xFF, 0xFF, 0xFF, 0xFF]),
                 bytes([0x84, 0x60, 0x73, 0x32]), bytes([0x5d, 0x8c, 0x11, 0x3b]),
                 bytes([0xAA, 0x55, 0xAA, 0x55]), bytes([0x01, 0x01, 0x01, 0x01])]
        challenges = fixed + [bytes(rng.randrange(256) for _ in range(4)) for _ in range(n)]
        for i, c in enumerate(challenges):
            reps = O.ask(pipe, c)
            got = O.extract_response(reps, c)
            if got is None:
                miss += 1
                continue
            pred = model(c)
            if got == pred:
                ok += 1
            else:
                bad += 1
                mismatches.append((c.hex(' '), got.hex(' '), pred.hex(' ')))
            if i < len(fixed) or i % 64 == 0:
                mark = 'OK' if got == pred else ('MISS' if got is None else 'BAD')
                print(f"  {c.hex(' ')} -> got {got.hex(' ') if got else '--'} "
                      f"pred {pred.hex(' ')}  [{mark}]")
    finally:
        pipe.close()

    total = ok + bad
    print(f"\n=== RESULT ===")
    print(f"verified: {ok}/{total} match   (misses/no-reply: {miss})")
    if mismatches:
        print(f"MISMATCHES ({len(mismatches)}):")
        for c, g, p in mismatches[:40]:
            print(f"  {c}: got {g}  pred {p}")
    else:
        print("PERFECT — model reproduces every response. F is fully recovered.")


if __name__ == '__main__':
    main()
