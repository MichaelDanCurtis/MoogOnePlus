#!/usr/bin/env python3
"""Mute/unmute EVERY effect on the send bus at once, live."""
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

def send(*msgs):
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
orig = {n.node_id: (n.defname, n.controls["gain"], n.controls.get("mix")) for n in fx}

print("effects that will be muted:")
for nid, (dn, g, mx) in orig.items():
    print(f"   {nid}  {dn:18s} gain={g}  mix={mx}")
print("\nPLAY NOW — hold chords\n", flush=True)
time.sleep(3)

for i in range(3):
    send(*[OscMessage("/n_set", [nid, "gain", 0.0]) for nid in orig])
    print(f"  [{i+1}/3]  ####  ALL FX MUTED (gain=0)  ####", flush=True)
    time.sleep(7)
    send(*[OscMessage("/n_set", [nid, "gain", g]) for nid, (_, g, _) in orig.items()])
    print(f"  [{i+1}/3]  ----  FX RESTORED  ----", flush=True)
    time.sleep(7)

send(*[OscMessage("/n_set", [nid, "gain", g]) for nid, (_, g, _) in orig.items()])
print("\nrestored all original gains", flush=True)
t.close()
