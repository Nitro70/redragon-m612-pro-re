"""Enumerate all HID interfaces + feature reports for Redragon M612-PRO.

Prints every HID collection exposed by VID 0x3554 / PID 0xF55E, their usage
page / usage, and the contents of any readable feature report.

Requires: pywinusb   (pip install pywinusb)
Read-only. Safe to run with the mouse plugged in.
"""
import pywinusb.hid as hid

VID, PID = 0x3554, 0xF55E

devices = hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices()
print(f"Found {len(devices)} HID interfaces for VID={VID:04X} PID={PID:04X}")
print("=" * 70)

for i, d in enumerate(devices):
    print(f"\n--- Interface {i}: {d.device_path}")
    print(f"    Vendor:  {d.vendor_name!r}")
    print(f"    Product: {d.product_name!r}")
    try:
        d.open()
        c = d.hid_caps
        if c:
            print(f"    UsagePage/Usage: 0x{c.usage_page:04X} / 0x{c.usage:04X}  "
                  f"inLen={c.input_report_byte_length} outLen={c.output_report_byte_length} "
                  f"featLen={c.feature_report_byte_length}")
        feats = d.find_feature_reports()
        print(f"    Feature reports: {len(feats)}")
        for r in feats:
            try:
                r.get()
                raw = bytes(r.get_raw_data())
                print(f"      ID 0x{r.report_id:02X}  len={len(raw)}  {raw.hex(' ')}")
            except Exception as e:
                print(f"      ID 0x{r.report_id:02X}  READ FAILED: {e}")
        outs = d.find_output_reports()
        print(f"    Output reports: {len(outs)}")
        for r in outs:
            print(f"      ID 0x{r.report_id:02X}  len={len(r.get_raw_data())}")
        ins = d.find_input_reports()
        print(f"    Input reports: {len(ins)}")
    except Exception as e:
        print(f"    OPEN FAILED: {e}")
    finally:
        try: d.close()
        except: pass
