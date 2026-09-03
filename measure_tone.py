#!/usr/bin/env python3
"""Record FX-muted vs FX-on from the line inputs, diff the spectra, name the tone.

DO NOT PLAY. Silence is the test signal.
"""
import time
import numpy as np
import sounddevice as sd
from moogone.osc import OscMessage, decode
from moogone.transport import UdpTransport
from moogone.sc.tree import parse_query_tree, SynthNode
from moogone.analysis.wav import Audio, save_wav
from moogone.analysis.spectrum import spectrum
from moogone.analysis.noise import noise_floor_dbfs, rms_dbfs

DEV, SR, SECS, CHANS = 5, 44100, 8.0, 6
LEFT, RIGHT = 2, 3
t = UdpTransport("192.168.1.138", 57110)

def tree():
    t.send(OscMessage("/g_queryTree", [0, 1]).encode())
    end = time.time() + 8
    while time.time() < end:
        d = t.recv(timeout=max(0.1, end - time.time()))
        if d is None: break
        m = decode(d)
        if m.address == "/g_queryTree.reply": return parse_query_tree(m.args)

def send(msgs):
    for m in msgs: t.send(m.encode())
    t.send(OscMessage("/sync", [1]).encode())
    end = time.time() + 3
    while time.time() < end:
        d = t.recv(timeout=max(0.1, end - time.time()))
        if d is None: break
        if decode(d).address == "/synced": return

def rec(label):
    print(f"  recording {label} ({SECS:.0f}s)...", flush=True)
    a = sd.rec(int(SECS*SR), samplerate=SR, channels=CHANS, device=DEV, dtype="float64")
    sd.wait()
    return Audio(((a[:, LEFT] + a[:, RIGHT]) / 2.0).astype(np.float64), SR)

root = tree()
fx = [n for n in root.walk()
      if isinstance(n, SynthNode) and n.controls.get("gain") is not None
      and n.controls.get("inBus") not in (None, 0.0)]
orig = {n.node_id: (n.defname, n.controls["gain"]) for n in fx}
print("effects under test:")
for nid, (dn, g) in orig.items(): print(f"   {nid} {dn} gain={g}")
mute = [OscMessage("/n_set", [nid, "gain", 0.0]) for nid in orig]
rest = [OscMessage("/n_set", [nid, "gain", g]) for nid, (_, g) in orig.items()]

print("\nDO NOT PLAY.\n", flush=True)
time.sleep(2)
send(mute); time.sleep(2); off = rec("FX MUTED")
send(rest); time.sleep(2); on  = rec("FX ON")
send(rest); t.close()

save_wav("captures/fx_off.wav", off); save_wav("captures/fx_on.wav", on)
print(f"\n  FX off: floor {noise_floor_dbfs(off):7.2f} dBFS   rms {rms_dbfs(off):7.2f}")
print(f"  FX on : floor {noise_floor_dbfs(on):7.2f} dBFS   rms {rms_dbfs(on):7.2f}")
print(f"  --> FX add {noise_floor_dbfs(on) - noise_floor_dbfs(off):+.2f} dB to the noise floor")

f, m_off = spectrum(off); _, m_on = spectrum(on)
diff = m_on - m_off
band = (f > 20) & (f < SR/2 - 100)
fb, db_ = f[band], diff[band]
top = np.argsort(db_)[::-1][:14]

print("\n" + "="*60)
print("  WHAT THE FX ADD  (FX_on minus FX_off, by frequency)")
print("="*60)
for fr, g in sorted(zip(fb[top], db_[top])):
    if g < 3: continue
    tag = ""
    for name, ref in (("block rate 48000/128", 375.0), ("48000/64", 750.0), ("mains", 60.0)):
        for h in range(1, 60):
            if abs(fr - ref*h) < max(6, ref*h*0.01):
                tag = f"   <-- {h}x {name}"; break
        if tag: break
    print(f"  {fr:9.1f} Hz   {g:+6.1f} dB{tag}")
print("\n  wavs saved: captures/fx_off.wav  captures/fx_on.wav")
