#!/usr/bin/env python3
"""Live A/B a scsynth control on the Moog One. Prints every write as it happens.

  uv run python3 ab.py <node> <control> <valueA> <valueB> [seconds] [cycles]
"""
import sys, time
from moogone.osc import OscMessage, decode
from moogone.transport import UdpTransport
from moogone.sc.tree import parse_query_tree, SynthNode

HOST, PORT = "192.168.1.138", 57110
node = int(sys.argv[1]); ctl = sys.argv[2]
a = float(sys.argv[3]); b = float(sys.argv[4])
secs = float(sys.argv[5]) if len(sys.argv) > 5 else 6.0
cycles = int(sys.argv[6]) if len(sys.argv) > 6 else 4

t = UdpTransport(HOST, PORT)

def tree():
    t.send(OscMessage("/g_queryTree", [0, 1]).encode())
    end = time.time() + 8
    while time.time() < end:
        d = t.recv(timeout=max(0.1, end - time.time()))
        if d is None: break
        m = decode(d)
        if m.address == "/g_queryTree.reply":
            return parse_query_tree(m.args)

def setc(v):
    t.send(OscMessage("/n_set", [node, ctl, v]).encode())
    t.send(OscMessage("/sync", [1]).encode())
    end = time.time() + 3
    while time.time() < end:
        d = t.recv(timeout=max(0.1, end - time.time()))
        if d is None: break
        if decode(d).address == "/synced": return True
    return False

def readback():
    r = tree()
    if r:
        for n in r.walk():
            if n.node_id == node and isinstance(n, SynthNode):
                return n.controls.get(ctl)

try:
    n0 = None
    r = tree()
    for n in (r.walk() if r else []):
        if n.node_id == node and isinstance(n, SynthNode): n0 = n
    if n0 is None:
        print(f"node {node} not found or is a group"); sys.exit(1)
    orig = n0.controls.get(ctl)
    print(f"node {node} = {n0.defname}    {ctl} currently {orig}")
    print(f"toggling {a}  <->  {b}   every {secs:.0f}s, {cycles} cycles")
    print("PLAY NOW\n", flush=True)
    time.sleep(2)
    for i in range(cycles):
        for v, tag in ((a, "A"), (b, "B")):
            setc(v)
            got = readback()
            mark = "ok" if got == v else f"!! readback={got}"
            print(f"  [{i+1}/{cycles}] {tag}  {ctl} = {v:<8} {mark}", flush=True)
            time.sleep(secs)
    if orig is not None:
        setc(orig)
        print(f"\nrestored {ctl} = {readback()}", flush=True)
finally:
    t.close()
