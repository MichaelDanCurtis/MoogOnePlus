#!/usr/bin/env python3
"""Is the hum the delay's feedback comb resonating? Two tests, by ear.

  A: kill feedback   -> if the tone dies, it IS the feedback loop
  B: sweep the time  -> if the PITCH tracks, it's the comb resonance
DO NOT PLAY.
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

n = next(x for x in tree().walk()
         if isinstance(x, SynthNode) and x.defname.startswith("stereoDelay"))
N, C = n.node_id, dict(n.controls)
print(f"target: node {N} {n.defname}")
print(f"  timeL={C['timeL']:.5f}s  feedbackL={C['feedbackL']}  tone={C['tone']}")
print("\nDO NOT PLAY. Monitors up.\n", flush=True)
time.sleep(3)

print("--- TEST A: does the tone need the feedback loop? ---", flush=True)
for i in range(3):
    send([OscMessage("/n_set", [N, "feedbackL", 0.0]),
          OscMessage("/n_set", [N, "feedbackR", 0.0])])
    print(f"  [{i+1}/3] feedback = 0     <-- tone GONE?", flush=True)
    time.sleep(8)
    send([OscMessage("/n_set", [N, "feedbackL", C["feedbackL"]]),
          OscMessage("/n_set", [N, "feedbackR", C["feedbackR"]])])
    print(f"  [{i+1}/3] feedback restored <-- tone BACK?", flush=True)
    time.sleep(8)

print("\n--- TEST B: does the PITCH track the delay time? ---", flush=True)
for mult, label in ((1.0, "normal"), (0.5, "HALF time -> pitch should RISE an octave"),
                    (2.0, "DOUBLE time -> pitch should FALL an octave"),
                    (0.25, "QUARTER time -> up two octaves")):
    send([OscMessage("/n_set", [N, "timeL", C["timeL"] * mult]),
          OscMessage("/n_set", [N, "timeR", C["timeR"] * mult])])
    hz = 1.0 / (C["timeL"] * mult)
    print(f"  timeL={C['timeL']*mult:.5f}s  (~{hz:,.0f} Hz fundamental)  {label}", flush=True)
    time.sleep(10)

send([OscMessage("/n_set", [N, k, v]) for k, v in
      (("timeL", C["timeL"]), ("timeR", C["timeR"]),
       ("feedbackL", C["feedbackL"]), ("feedbackR", C["feedbackR"]))])
print("\nrestored.", flush=True)
t.close()
