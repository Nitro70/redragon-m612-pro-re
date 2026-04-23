"""Scan a flash dump for USB descriptor patterns and embedded strings.

If the firmware stores its USB descriptors in the user-flash region (rather
than code ROM), they'll show up as standard USB descriptor byte patterns.
Most interesting byte: `bInterval` in interrupt endpoint descriptors, which
controls the polling rate.

Descriptor signatures searched:
  12 01 ...        Device descriptor
  09 02 ...        Configuration descriptor
  09 04 ...        Interface descriptor
  07 05 ...        Endpoint descriptor (the one with bInterval)
  09 21 ...        HID descriptor

Also dumps UTF-16LE strings (how USB string descriptors and Windows HID
paths store their text) so we can spot product / manufacturer strings
embedded in flash.

Usage:
  py scan_flash.py <path/to/flash_dump.bin>
"""
import sys


def hexdump_range(data, start, length, width=16, label=''):
    end = min(start + length, len(data))
    print(f"  {label}  [0x{start:04x}..0x{end:04x}]")
    for i in range(start, end, width):
        chunk = data[i:min(i+width, end)]
        hx = ' '.join(f'{b:02x}' for b in chunk)
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"    {i:04x}  {hx:<{width*3}} {asc}")


def scan_endpoint_descriptors(data):
    """Find every `07 05` that looks like a valid endpoint descriptor."""
    hits = []
    for i in range(len(data) - 6):
        if data[i] == 0x07 and data[i+1] == 0x05:
            ep_addr = data[i+2]
            attr    = data[i+3]
            mps     = data[i+4] | (data[i+5] << 8)
            interval = data[i+6]
            # Sanity filters to kill most coincidental matches:
            # - attr must be 0..3 (control/iso/bulk/interrupt); real interrupt endpoints = 3
            # - maxpacket usually 1..1024 (HID typically 8..64)
            # - direction bit in ep_addr: bits 7 = IN/OUT, bits 6..4 reserved (must be 0),
            #   bits 3..0 = endpoint number (1..15)
            if attr > 3: continue
            if mps == 0 or mps > 1024: continue
            ep_num = ep_addr & 0x0F
            ep_rsv = ep_addr & 0x70
            if ep_num == 0 or ep_num > 15: continue
            if ep_rsv != 0: continue
            hits.append({
                'offset': i,
                'direction': 'IN' if (ep_addr & 0x80) else 'OUT',
                'ep_num': ep_num,
                'attr': attr,
                'attr_name': ['Control','Isochronous','Bulk','Interrupt'][attr & 3],
                'maxpacket': mps,
                'bInterval': interval,
            })
    return hits


def scan_prefix(data, prefix: bytes):
    """Find every occurrence of a byte prefix, return list of offsets."""
    out = []
    L = len(prefix)
    for i in range(len(data) - L + 1):
        if data[i:i+L] == prefix:
            out.append(i)
    return out


def extract_utf16_strings(data, min_chars=4, max_chars=64):
    """Extract UTF-16LE strings (every other byte 0x00, printable ASCII otherwise)."""
    out = []
    i = 0
    while i < len(data) - 2*min_chars:
        # Try to extend a UTF-16LE string from i
        j = i
        s = ''
        while j < len(data) - 1:
            lo, hi = data[j], data[j+1]
            if hi == 0 and 32 <= lo < 127:
                s += chr(lo)
                j += 2
            else:
                break
        if len(s) >= min_chars:
            out.append((i, s[:max_chars]))
            i = j
        else:
            i += 1
    return out


def extract_ascii_strings(data, min_chars=5, max_chars=64):
    out = []
    cur = bytearray(); start = 0
    for i, b in enumerate(data):
        if 32 <= b < 127:
            if not cur: start = i
            cur.append(b)
        else:
            if len(cur) >= min_chars:
                out.append((start, bytes(cur)[:max_chars].decode('ascii')))
            cur = bytearray()
    if len(cur) >= min_chars:
        out.append((start, bytes(cur)[:max_chars].decode('ascii')))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    path = sys.argv[1]
    data = open(path, 'rb').read()
    print(f"=== {path}  ({len(data)} bytes = 0x{len(data):X}) ===\n")

    # 1) Endpoint descriptors — the key find
    print("### Candidate Endpoint descriptors (07 05 ...)")
    eps = scan_endpoint_descriptors(data)
    if eps:
        print(f"{len(eps)} plausible endpoint descriptors found:\n")
        for ep in eps:
            print(f"  offset 0x{ep['offset']:04x}: "
                  f"EP{ep['ep_num']}-{ep['direction']}  "
                  f"{ep['attr_name']}  "
                  f"maxpacket={ep['maxpacket']}  "
                  f"bInterval={ep['bInterval']} "
                  f"({'~'+str(1000//max(1,ep['bInterval']))+' Hz' if ep['attr']==3 else ''})")
            hexdump_range(data, max(0, ep['offset']-2), 16, label='context')
            print()
    else:
        print("  (none plausible)\n")

    # 2) Other descriptor headers
    for prefix_bytes, name in [
        (b'\x12\x01', 'Device'),
        (b'\x09\x02', 'Configuration'),
        (b'\x09\x04', 'Interface'),
        (b'\x09\x21', 'HID'),
    ]:
        hits = scan_prefix(data, prefix_bytes)
        if hits:
            print(f"### {name} descriptor signature ({prefix_bytes.hex(' ')})")
            for off in hits[:5]:
                hexdump_range(data, off, 24, label=f"@0x{off:04x}")
                print()

    # 3) Printable strings
    print("### ASCII strings (length >= 5)")
    for off, s in extract_ascii_strings(data, 5)[:30]:
        print(f"  0x{off:04x}: {s!r}")
    print()

    print("### UTF-16LE strings (length >= 4)")
    for off, s in extract_utf16_strings(data, 4)[:30]:
        print(f"  0x{off:04x}: {s!r}")


if __name__ == '__main__':
    main()
