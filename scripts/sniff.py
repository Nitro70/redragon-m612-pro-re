"""Frida hook to capture HID writes the vendor software sends to the mouse.

Spawns the vendor software under Frida instrumentation, hooks WriteFile /
DeviceIoControl / CreateFileW / HidD_SetFeature / HidD_SetOutputReport across
kernel32.dll, kernelbase.dll, and hid.dll, and logs every HID-shaped call with
the full buffer contents.

No kernel driver is installed. Pure userspace hooking via Frida.

Requires: frida-tools   (pip install frida-tools)

Usage:
  py sniff.py <path-to-vendor-exe>
  py sniff.py "C:\\path\\to\\Mouse Drive Beta.exe"

Runs headless. Log: sniff.log in the script's directory.
Create a file named STOP alongside the script (or Ctrl-C the Python process)
to stop the hook.

After capture, grep the log for HID writes on the mouse's MI_01 Col05 interface:
    grep -E "WriteFile\\s+h=0x[0-9a-f]+ len= 17" sniff.log | sort -u
"""
import sys, frida, time, os

HERE = os.path.dirname(os.path.abspath(__file__))
LOGFILE = os.path.join(HERE, "sniff.log")
STOPFILE = os.path.join(HERE, "STOP")

JS = r"""
'use strict';

function hex(ptr, len) {
    if (len <= 0 || len > 256) return null;
    try { return ptr.readByteArray(len); } catch (e) {
        try { return Memory.readByteArray(ptr, len); } catch (e2) { return null; }
    }
}

const handlePath = {};

const writeFileHandler = {
    onEnter: function(args) {
        const len = args[2].toInt32();
        if (len > 0 && len <= 128) {
            send({tag:'WriteFile', handle:args[0].toString(), len:len},
                 hex(args[1], len));
        }
    }
};

const ioctlHandler = {
    onEnter: function(args) {
        const inlen = args[3].toInt32();
        if (inlen > 0 && inlen <= 128) {
            send({tag:'IOCTL', handle:args[0].toString(),
                  ioctl:'0x'+(args[1].toInt32()>>>0).toString(16), inlen:inlen},
                 hex(args[2], inlen));
        }
    }
};

const hidSetFeatureHandler = {
    onEnter: function(args) {
        const len = args[2].toInt32();
        send({tag:'SET_FEATURE', handle:args[0].toString(), len:len},
             hex(args[1], len));
    }
};
const hidSetOutputHandler = {
    onEnter: function(args) {
        const len = args[2].toInt32();
        send({tag:'SET_OUTPUT', handle:args[0].toString(), len:len},
             hex(args[1], len));
    }
};

const createFileHandler = {
    onEnter: function(args) { try { this.path = args[0].readUtf16String(); } catch (e) { this.path = null; } },
    onLeave: function(ret) {
        if (ret.toInt32() !== -1 && this.path) {
            handlePath[ret.toString()] = this.path;
            if (/HID#|USB#|hid#|usb#|\\\\\.\\|\\\\\?\\/i.test(this.path)) {
                send({tag:'OPEN', handle:ret.toString(), path:this.path});
            }
        }
    }
};

const installed = new Set();
function attachOne(modName, fnName, handler) {
    const key = (modName+'!'+fnName).toLowerCase();
    if (installed.has(key)) return false;
    const m = Process.findModuleByName(modName);
    if (!m) { send({tag:'warn', msg:'no module ' + modName}); return false; }
    let addr;
    try { addr = m.findExportByName(fnName); } catch (e) { addr = null; }
    if (!addr) { send({tag:'warn', msg:'no export ' + modName + '!' + fnName}); return false; }
    try {
        Interceptor.attach(addr, handler);
        installed.add(key);
        send({tag:'ok', msg:'hooked ' + modName + '!' + fnName + ' @ ' + addr});
        return true;
    } catch (e) {
        send({tag:'warn', msg:'attach fail ' + modName + '!' + fnName + ': ' + e});
        return false;
    }
}

function installAll() {
    attachOne('kernel32.dll',   'WriteFile',          writeFileHandler);
    attachOne('kernelbase.dll', 'WriteFile',          writeFileHandler);
    attachOne('kernel32.dll',   'DeviceIoControl',    ioctlHandler);
    attachOne('kernelbase.dll', 'DeviceIoControl',    ioctlHandler);
    attachOne('kernel32.dll',   'CreateFileW',        createFileHandler);
    attachOne('kernelbase.dll', 'CreateFileW',        createFileHandler);
    attachOne('hid.dll', 'HidD_SetFeature',      hidSetFeatureHandler);
    attachOne('hid.dll', 'HidD_SetOutputReport', hidSetOutputHandler);
}

// Re-install when new modules (like hid.dll) load.
(function() {
    const a = Module.findExportByName('ntdll.dll', 'LdrLoadDll');
    if (a) {
        Interceptor.attach(a, { onLeave() { installAll(); } });
        send({tag:'ok', msg:'hooked ntdll.dll!LdrLoadDll'});
    }
})();

installAll();
send({tag:'ok', msg:'initial install pass done'});

rpc.exports = { reinstall: function() { installAll(); } };
"""


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    exe = sys.argv[1]

    logf = open(LOGFILE, 'w', encoding='utf-8')
    def log(s):
        try: print(s, flush=True)
        except Exception: pass
        logf.write(s + "\n"); logf.flush()

    _seen = set()
    def on_message(msg, data):
        if msg['type'] == 'error':
            log(f"[frida err] {msg.get('description')}")
            log(f"           stack: {msg.get('stack','')}")
            return
        p = msg.get('payload', {})
        tag = p.get('tag')
        if tag in ('ok', 'warn'):
            key = (tag, p.get('msg'))
            if key in _seen: return
            _seen.add(key)
            log(f"[{tag}] {p.get('msg')}"); return
        ts = time.strftime('%H:%M:%S')
        hx = data.hex(' ') if data else '<no-data>'
        if tag == 'SET_FEATURE':
            log(f"[{ts}] ** SET_FEATURE  h={p['handle']} len={p['len']:>3}  {hx}")
        elif tag == 'SET_OUTPUT':
            log(f"[{ts}] ** SET_OUTPUT   h={p['handle']} len={p['len']:>3}  {hx}")
        elif tag == 'WriteFile':
            log(f"[{ts}]  WriteFile     h={p['handle']} len={p['len']:>3}  {hx}")
        elif tag == 'IOCTL':
            log(f"[{ts}]  IOCTL         h={p['handle']} ioctl={p['ioctl']} len={p['inlen']:>3}  {hx}")
        elif tag == 'OPEN':
            log(f"[{ts}]  OPEN          h={p['handle']}  {p['path']}")
        else:
            log(f"[{ts}] {tag} {p} {hx}")

    log(f"Spawning {exe}...")
    pid = frida.spawn([exe], cwd=os.path.dirname(exe))
    log(f"  spawned pid={pid}")
    session = frida.attach(pid)
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    frida.resume(pid)
    log(f"Hooks active. Log: {LOGFILE}. Create '{STOPFILE}' to stop.\n")

    # A few staggered re-installs catch hid.dll when it loads late; after that
    # repeated re-installs can race the CLR and crash .NET apps.
    reinstall_at = [2, 5, 10]
    start = time.time()
    done = 0
    try:
        while not os.path.exists(STOPFILE):
            time.sleep(0.5)
            if done < len(reinstall_at) and (time.time() - start) >= reinstall_at[done]:
                try: script.exports_sync.reinstall()
                except Exception: pass
                done += 1
    except KeyboardInterrupt:
        pass
    finally:
        try: os.remove(STOPFILE)
        except: pass
        try: session.detach()
        except: pass
        logf.close()


if __name__ == '__main__':
    main()
