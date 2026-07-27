r"""Chosen-plaintext oracle against the M612-PRO firmware auth primitive.

The `08 01` (EncryptionData) command is a challenge->response function computed
in firmware:

    08 01 00 00 00 08 <c0 c1 c2 c3> 00 00 00 00 00 00 CK   (host -> mouse)
    -> mouse replies with an input report containing <r0 r1 r2 r3> + device id

The vendor software only ever sends *random* challenges. We can send *chosen*
challenges and read the replies, giving a clean chosen-plaintext oracle on
F(challenge)->response. Reversing F is the route to minting valid bootloader
auth responses ourselves.

SAFE: `08 01` is the exact session-init packet the vendor sends on every
connect. Pure request/response, no flash writes, no mode changes. Zero brick
risk.

Usage:
  py crypto_oracle.py validate        # send the known challenge, confirm response
  py crypto_oracle.py determinism     # same challenge x8, is F stateless?
  py crypto_oracle.py linear          # zero + 32 single-bit probes (affine test)
  py crypto_oracle.py random 512      # N random challenges -> corpus JSON
  py crypto_oracle.py sweep0          # sweep byte0 0..255 with others fixed 0
"""
import sys, os, ctypes, ctypes.wintypes as wt, time, json, random
import pywinusb.hid as hid

VID, PID = 0x3554, 0xF55E
HERE = os.path.dirname(os.path.abspath(__file__))

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 0x01, 0x02
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value
ERROR_IO_PENDING = 997
WAIT_TIMEOUT = 0x102
WAIT_OBJECT_0 = 0


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p),
                ("InternalHigh", ctypes.c_void_p),
                ("Offset", wt.DWORD),
                ("OffsetHigh", wt.DWORD),
                ("hEvent", wt.HANDLE)]


CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
CreateFileW.restype = wt.HANDLE
ReadFile = kernel32.ReadFile
ReadFile.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.POINTER(OVERLAPPED)]
ReadFile.restype = wt.BOOL
WriteFile = kernel32.WriteFile
WriteFile.argtypes = [wt.HANDLE, wt.LPCVOID, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.POINTER(OVERLAPPED)]
WriteFile.restype = wt.BOOL
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wt.HANDLE]; CloseHandle.restype = wt.BOOL
CancelIo = kernel32.CancelIo
CancelIo.argtypes = [wt.HANDLE]; CancelIo.restype = wt.BOOL
CreateEventW = kernel32.CreateEventW
CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
CreateEventW.restype = wt.HANDLE
WaitForSingleObject = kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]; WaitForSingleObject.restype = wt.DWORD
GetOverlappedResult = kernel32.GetOverlappedResult
GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wt.DWORD), wt.BOOL]
GetOverlappedResult.restype = wt.BOOL
ResetEvent = kernel32.ResetEvent
ResetEvent.argtypes = [wt.HANDLE]; ResetEvent.restype = wt.BOOL


def find_col05_path():
    for d in hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices():
        try:
            d.open()
            cap = d.hid_caps
            if cap and cap.usage_page == 0xFF02 and cap.output_report_byte_length == 17:
                return d.device_path
        finally:
            try: d.close()
            except: pass
    return None


def checksum(body16: bytes) -> int:
    return (0x55 - sum(body16)) & 0xFF


def build_challenge(c: bytes) -> bytes:
    assert len(c) == 4
    body = bytes([0x08, 0x01, 0, 0, 0, 0x08]) + c + bytes(6)
    assert len(body) == 16
    return body + bytes([checksum(body)])


class Pipe:
    def __init__(self, path):
        self.h = CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if self.h == INVALID_HANDLE_VALUE or not self.h:
            raise OSError(f"CreateFileW failed err={ctypes.get_last_error()}")
        self.ev_r = CreateEventW(None, True, False, None)
        self.ev_w = CreateEventW(None, True, False, None)

    def close(self):
        try: CancelIo(self.h)
        except Exception: pass
        for hh in (self.h, self.ev_r, self.ev_w):
            try: CloseHandle(hh)
            except Exception: pass

    def write(self, data: bytes, timeout_ms=200):
        ResetEvent(self.ev_w)
        ov = OVERLAPPED(); ov.hEvent = self.ev_w
        n = wt.DWORD(0)
        buf = ctypes.create_string_buffer(data, len(data))
        ok = WriteFile(self.h, buf, len(data), ctypes.byref(n), ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise OSError(f"WriteFile err={err}")
            if WaitForSingleObject(self.ev_w, timeout_ms) != WAIT_OBJECT_0:
                CancelIo(self.h); raise TimeoutError("write timeout")
            GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(n), False)
        return n.value

    def read(self, timeout_ms=150):
        ResetEvent(self.ev_r)
        ov = OVERLAPPED(); ov.hEvent = self.ev_r
        buf = ctypes.create_string_buffer(17)
        n = wt.DWORD(0)
        ok = ReadFile(self.h, buf, 17, ctypes.byref(n), ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                return None
            w = WaitForSingleObject(self.ev_r, timeout_ms)
            if w != WAIT_OBJECT_0:
                CancelIo(self.h)
                return None
            if not GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(n), False):
                return None
        return buf.raw[:n.value]


def drain(pipe, ms=30):
    """Read and discard any pending input reports."""
    t = time.perf_counter()
    while (time.perf_counter() - t) * 1000 < ms:
        r = pipe.read(timeout_ms=10)
        if r is None:
            break


def ask(pipe, challenge: bytes, tries=6):
    """Send a challenge, return the raw 17-byte reply that carries the response.

    The reply we want echoes the response in bytes; we identify the encryption
    reply as the first report whose payload differs from the constant ACK
    (08 00 01 00 ... ) and that appears after our write.
    """
    drain(pipe, ms=15)
    pipe.write(build_challenge(challenge))
    replies = []
    deadline = time.perf_counter() + 0.20
    while time.perf_counter() < deadline and len(replies) < tries:
        r = pipe.read(timeout_ms=60)
        if r is None:
            if replies:
                break
            continue
        replies.append(r)
    return replies


def extract_response(replies, challenge):
    """Return the 4 response bytes F(challenge) from the encryption reply.

    Reply format (validated against DLL capture):
        08 01 00 00 00 08 [r0 r1 r2 r3] [17 08 02 00] 00 00 CK
                          ^bytes 6..9 = response
    """
    for r in replies:
        if len(r) >= 10 and r[0] == 0x08 and r[1] == 0x01 and r[2:6] == b'\x00\x00\x00\x08':
            return r[6:10]
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    mode = sys.argv[1]

    path = find_col05_path()
    if not path:
        print("ERROR: MI_01 Col05 not found (mouse unplugged?)"); sys.exit(1)
    print(f"Col05: {path}\n")
    pipe = Pipe(path)

    try:
        if mode == 'validate':
            known = bytes([0x84, 0x60, 0x73, 0x32])
            reps = ask(pipe, known)
            print(f"challenge = {known.hex(' ')}")
            for i, r in enumerate(reps):
                print(f"  reply[{i}] ({len(r)}B): {r.hex(' ')}")
            print("\nexpected response from prior DLL capture: fb 3b 8b 4c 17 08 02 00")

        elif mode == 'determinism':
            c = bytes([0x11, 0x22, 0x33, 0x44])
            print(f"challenge (x8) = {c.hex(' ')}")
            for i in range(8):
                reps = ask(pipe, c)
                best = extract_response(reps, c)
                print(f"  {i}: {best.hex(' ') if best else 'NO REPLY'}")

        elif mode == 'linear':
            out = {}
            probes = [bytes(4)]
            for byte_i in range(4):
                for bit in range(8):
                    c = bytearray(4); c[byte_i] = 1 << bit
                    probes.append(bytes(c))
            for c in probes:
                reps = ask(pipe, c)
                best = extract_response(reps, c)
                out[c.hex()] = best.hex() if best else None
                print(f"  {c.hex(' ')} -> {best.hex(' ') if best else 'NO REPLY'}")
            p = os.path.join(HERE, 'oracle_linear.json')
            json.dump(out, open(p, 'w'), indent=2)
            print(f"\nsaved {p}")

        elif mode == 'sweep0':
            out = {}
            for v in range(256):
                c = bytes([v, 0, 0, 0])
                reps = ask(pipe, c)
                best = extract_response(reps, c)
                out[c.hex()] = best.hex() if best else None
                if v % 16 == 0:
                    print(f"  {c.hex(' ')} -> {best.hex(' ') if best else 'NO REPLY'}")
            p = os.path.join(HERE, 'oracle_sweep0.json')
            json.dump(out, open(p, 'w'), indent=2)
            print(f"saved {p}")

        elif mode == 'random':
            n = int(sys.argv[2]) if len(sys.argv) > 2 else 256
            rng = random.Random(1234)
            out = {}
            miss = 0
            for i in range(n):
                c = bytes(rng.randrange(256) for _ in range(4))
                reps = ask(pipe, c)
                best = extract_response(reps, c)
                out[c.hex()] = best.hex() if best else None
                if best is None:
                    miss += 1
                if i % 32 == 0:
                    print(f"  [{i}/{n}] {c.hex(' ')} -> {best.hex(' ') if best else 'NO REPLY'}")
            p = os.path.join(HERE, 'oracle_random.json')
            json.dump(out, open(p, 'w'), indent=2)
            print(f"\nsaved {p}  ({n} challenges, {miss} misses)")

        else:
            print(f"unknown mode {mode!r}"); sys.exit(2)
    finally:
        pipe.close()


if __name__ == '__main__':
    main()
