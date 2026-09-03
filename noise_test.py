#!/usr/bin/env python3
"""Is the hiss coming from the FX engine, or from the converters?

SILENCE is the test signal. Do not play.
"""
import time
from moogone.osc import OscMessage, decode
from moogone.transport import UdpTransport
from moogone.sc.tree import parse_query_tree, SynthNode

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

root = tree()
fx = [n for n in root.walk()
      if isinstance(n, SynthNode) and n.controls.get("gain") is not None
      and n.controls.get("inBus") not in (None, 0.0)]
orig = {n.node_id: (n.defname, n.controls["gain"]) for n in fx}

print("=" * 62)
print("  DO NOT PLAY.  Let it sit silent.  Turn the monitors UP.")
print("  Listen for HISS appearing and disappearing.")
print("=" * 62)
print()
for nid, (dn, g) in orig.items():
    print(f"   {nid}  {dn:18s} gain={g}")
print(flush=True)
time.sleep(4)

for i in range(4):
    send([OscMessage("/n_set", [nid, "gain", 0.0]) for nid in orig])
    print(f"  [{i+1}/4]  FX OFF   <-- is it quieter?", flush=True)
    time.sleep(9)
    send([OscMessage("/n_set", [nid, "gain", g]) for nid, (_, g) in orig.items()])
    print(f"  [{i+1}/4]  FX ON    <-- does hiss come back?", flush=True)
    time.sleep(9)

send([OscMessage("/n_set", [nid, "gain", g]) for nid, (_, g) in orig.items()])
print("\nrestored.", flush=True)
t.close()
