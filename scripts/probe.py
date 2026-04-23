"""Probe the vendor-defined config interfaces on the M612-PRO.

Reads every readable feature report and sends a small set of candidate
"read config" output commands on the MI_01 Col05 bidirectional pipe, logging
any replies the mouse sends.

Close the vendor software first (it holds the interfaces open exclusively
in some configurations). No writes to persistent flash are performed —
the commands here are either reads or generic unknown-command pokes that
the mouse ACKs with a fixed stub.

Requires: pywinusb   (pip install pywinusb)
"""
import sys, time, pywinusb.hid as hid

VID, PID = 0x3554, 0xF55E


def find_iface(usage_page):
    for d in hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices():
        d.open()
        cap = d.hid_caps
        if cap and cap.usage_page == usage_page:
            return d
        d.close()
    return None


# 1) Feature report on Col06 (UsagePage 0xFF04) — status blob
print("=== Feature report 0x06 (UsagePage FF04) ===")
d = find_iface(0xFF04)
if d:
    try:
        for r in d.find_feature_reports():
            r.get()
            raw = bytes(r.get_raw_data())
            print(f"  ID 0x{r.report_id:02X} ({len(raw)} bytes): {raw.hex(' ')}")
    finally:
        d.close()
else:
    print("  FF04 interface not found")

# 2) Probe Col05 (UsagePage 0xFF02) output+input
print("\n=== Probing Col05 (UsagePage FF02) output+input 0x08 ===")
d = find_iface(0xFF02)
if not d:
    print("  FF02 interface not found"); sys.exit(1)

received = []
def on_input(data):
    received.append(bytes(data))
    print(f"  <- input {len(data)}: {bytes(data).hex(' ')}")

d.set_raw_data_handler(on_input)

outs = d.find_output_reports()
out_rep = outs[0]
print(f"  Output report: ID 0x{out_rep.report_id:02X} len={len(out_rep.get_raw_data())}")

# Candidate commands. The mouse ACKs all of these with a fixed
# "08 00 01 00 ... 4c" stub on M612-PRO — i.e., it doesn't expose a
# meaningful read command. Left here so future RE on similar devices can
# spot differing replies.
probes = [
    ("all zero",                               bytes(16)),
    ("mouse_m908 read (0x04 0x11)",            bytes([0x04,0x11] + [0]*14)),
    ("sinowealth read prof1 (0x05 0x11)",      bytes([0x05,0x11] + [0]*14)),
    ("generic get-status (0x02)",              bytes([0x02] + [0]*15)),
    ("generic read all (0x01)",                bytes([0x01] + [0]*15)),
    ("sinowealth get buttons (0x05 0x12)",     bytes([0x05,0x12] + [0]*14)),
    ("0xA1 read",                              bytes([0xA1] + [0]*15)),
    ("0x80 read cfg",                          bytes([0x80] + [0]*15)),
]

for label, payload in probes:
    buf = [0x08] + list(payload)
    raw_len = len(out_rep.get_raw_data())
    while len(buf) < raw_len: buf.append(0)
    try:
        out_rep.set_raw_data(buf)
        before = len(received)
        out_rep.send()
        print(f"\n-> sent {label}: {bytes(buf[1:]).hex(' ')}")
        time.sleep(0.25)
        if len(received) == before:
            print("   (no response)")
    except Exception as e:
        print(f"   send failed: {e}")

d.close()
print("\nDone.")
