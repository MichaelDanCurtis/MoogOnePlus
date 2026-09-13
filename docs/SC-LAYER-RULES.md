# Adding anything to the audio graph: the rules

The SuperCollider layer is **not a black box**. `/usr/share/las-fx` ships 195
class files and 17 `.scd` scripts, all readable, and this repository already
carries a 1,300-line reading of them in `docs/firmware/las-fx.md`.

This page exists because that was not enough. On 2026-09-13 four bugs were found
by deploying to the instrument one at a time, and the topology was rediscovered
by experiment when it was written down in a file on disk. A long derivation
nobody reads at the moment of writing code is worth less than a short list of
rules. **This is the short list.** Every line links to where it was established.

---

## The graph you are adding to

`[READ]` — verified live via `/api/tree`, 2026-09-13. 29 nodes.

```
0  RootNode
└── 1  default group
    ├── 1000  ~insertGroup      slots 0,1,2   inserts
    ├── 1001  ~busGroup         inputRouter → slots 3,4 → outputRouter
    └── 1014  ~eventideGroup    ten parked et_* reverbs
```

Anything added "to the tail of the root group" lands as a **sibling of group 1**,
after all of it. That is where `moogd` puts everything, and it is the placement
`makeup.py` proved on this instrument.

**The main pair is buses 7 and 0, and they are not adjacent.** Five modules in
this repository have read them as 0 and 1 — main-right and *sub*-right —
including the recorder and the network streamer. `tests/test_main_bus_pair.py`
exists to stop a sixth.

---

## Six rules

**1. Never free a node you did not create.** `/n_free` on a LADSPA node
terminates `scsynth`. Ten of them are permanently resident, and Moog never free
them — `~initEffect` *moves* an Eventide between groups instead, precisely
because freeing one is fatal. `docs/DANGER.md`, tier 4.

**2. Never `/n_run 1` anything in `~eventideGroup`.** A never-adopted Eventide
holds its SynthDef defaults, `inBus = 0` and `outBus = 0` — it would read
hardware output bus 0 and write it again. That is a feedback loop on the main
output. `las-fx.md` §4.1.

**3. Never send two `/fxN` messages to one slot inside ~250 ms.** It leaves a
waiter spinning at 100 Hz forever and can orphan a synth. `docs/DANGER.md`.

**4. Pace everything.** The instrument's LAN and its link to the voice
controller are two CDC-Ether functions of **one USB gadget**. An unpaced burst
wedges it below the level the host can reset and only removing power recovers
it. One millisecond between datagrams; `plugin/src/sender.h` enforces it and so
must anything else. `docs/PLUGIN.md`.

**5. `doneAction: 1` on the ten `et_*` defs is load-bearing.** Every other
synthdef uses `2`. "Tidying" that to `2` kills the audio engine on the next
release. `docs/DANGER.md`.

**6. Check the audio core before adding DSP.** The realtime throttle has fired
three times on this instrument. `/api/diag` reports the count and the headroom.

---

## Five SuperCollider behaviours that cost a night

None of these are Moog specifics. They are plain server semantics, and every one
was rediscovered the hard way while building the meter.

| behaviour | what it looks like when you forget |
|---|---|
| Nodes run in **group order** | a meter added before a synth reads the previous block — it showed −90 dB while a 440 Hz tone played |
| `/s_new` **refuses a duplicate node id** | freeing and immediately recreating with the same id silently leaves the old node where it was |
| `/d_recv` is **asynchronous** | the `/s_new` after it arrives before the def is registered and fails, intermittently |
| A control bus **holds its last value** | reading in the same breath as creating its writer returns the *previous* state — silence, which reads as a working meter on a quiet instrument |
| A reply sits in the socket | `/done` from `/d_recv` is read as the answer to the *next* question. `src/moogone/record.py` documents this and it still caught the bus scanner |

`/n_order` with addAction 1 onto the root group, incidentally, silently did not
move a node. It is not in the code and a comment marks where it would have been.

---

## Before writing the next feature

1. `docs/firmware/las-fx.md` for the engine, `docs/ARCHITECTURE.md` for the
   buses, `docs/DANGER.md` for what bricks things.
2. `/api/tree` to see the graph as it is now rather than as it was at boot.
3. `/api/diag` for the headroom.
4. For any UGen: read the input order off `sclang`'s own compiled output, the
   way `tools/build-engine-synthdefs.py` and `moogd/testdata/graph-reference`
   do. A wrong argument order is a patch that sounds wrong, not one that errors.
