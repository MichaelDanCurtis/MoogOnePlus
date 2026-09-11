# MoogOnePlus — the application

A plan, written 2026-09-10, on top of ~36,000 lines of firmware documentation and
a week of getting things wrong in public. Every architectural claim here is one
that survived adversarial verification or was checked live on the instrument;
where something is still a guess it says so.

---

## The one fact the architecture hangs on

**`203.0.113.2` is not routable.** It is a point-to-point link between the i.MX6
and the XMOS voice controller. Tested from the LAN: packets go to the default
gateway and die.

Everything else follows from that. The iPad cannot talk to the voice controller.
Nothing on the network can. **The only path is a process running on the
instrument**, which is what the USB drive is for.

So the drive is not a convenience or a delivery mechanism. It *is* the product,
and the iPad app is one of its clients.

```
   iPad  ─────HTTP/WS─────┐
   MPE controller ──MIDI──┤          ┌─ OSC ──> las-sc      127.0.0.1:9300
   mioXL (RTP-MIDI) ──────┼─> moogd ─┼─ OSC ──> scsynth     127.0.0.1:57110
   Mac / DAW ─────────────┘  (cpu0)  └─ OSC ──> XMOS vc     203.0.113.2:7770
                                                             (unreachable
                                                              from anywhere
                                                              else)
```

`moogd` runs on **cpu0**. Never cpu1 — that is the audio core, verified live:
one `scsynth` thread pinned there at `SCHED_FIFO` 99 while the other six are
confined to cpu0.

---

## What the mioXL changes

It removes a whole component from this plan. iConnectivity already built the
router — 12 DIN, 10 USB, Ethernet RTP-MIDI with 22 virtual ports, merging and
filtering in hardware, presets without a computer.

So **we do not build MIDI routing. We build MIDI *interpretation*.** The mioXL
gets bytes to the right place; MoogOnePlus decides what they mean.

It also settles the transport question that had no answer: RTP-MIDI is MIDI 1.0,
MPE rides on MIDI 1.0, and network MIDI therefore works today. Note the mioXL
does **not** do MIDI 2.0 either. Defer MIDI 2.0 indefinitely; revisit only if a
specific piece of gear forces it.

---

## The six surfaces

### 1 · The modulation matrix, as a graph

The mod matrix **is** a graph. Moog renders it as twenty rows of soft-knob
scrolling, which is the worst available presentation of a graph. This is the
single clearest ergonomic win in the instrument.

The data is settled: seven tokens per row —
`[src, src_amt, ctl, ctl_amt, transform, transform_amt, dest]` — against **126
destinations, 46 sources, 42 operators**, read from the engine's own symbol
table `vx_ee.scm`. The factory library uses 71 of the 126 destinations and 5 of
31 functions. Most of the machine has never been asked to do anything.

**How it reaches the instrument** is now known, and it is not where anyone
looked: an edited row is compiled to a flat blob and sent as one OSC message to
the XMOS at `/g/<synth>/t/e/s`, `203.0.113.2:7770`, **sixteen bytes per slot**.
The address is assembled at runtime from `(synth_index, "e/s")`, which is why it
appears nowhere as a string and why days of packet captures on port 9300 found
nothing. Port 9300 was never the matrix's business.

**Verified on the wire, 2026-09-10.** All three claims above held: one OSC
blob, that address, sixteen bytes per slot, in the documented field order. The
amounts turned out to be **little-endian float32** inside a big-endian
protocol, which no amount of reading the preset schema would have revealed.
See `docs/arch/modmatrix-wire-format.md`.

**The design decision that matters.** A direct push is invisible to
`las-frontend`, which owns the preset state and recompiles the matrix from its
own copy on any panel edit or preset load. So a live write is immediate,
audible, unsaved, and silently overwritten by the next panel touch. And `las-sc`
never replies to us, so we cannot read back to reconcile.

Therefore: **the document is the preset, not the live state.**

- edit a graph → the app owns that file
- **audition** → push to the XMOS, hear it now, understand it is ephemeral
- **save** → write a real `.m1p`

That turns the limitation into a clean model, and it is earned: the preset
encoder round-trips all 300 factory matrices byte-for-byte, so a file we
generate is indistinguishable from one Moog wrote.

**On React Flow specifically:** drag-to-connect is fiddly on touch. Use the
graph for *comprehension* — see every routing at once — and tap-to-edit for
*precision*. Set an amount with a number, not a drag.

### 2 · The OSC ↔ matrix adapter

The layer under the graph: encode/decode the 7-tuples, validate every id against
the symbol table, refuse anything it cannot name. Already written and tested —
`moogd/modmatrix.go`, with the id tables generated from `vx_ee.scm` rather than
typed in, and a test that decodes all 300 factory matrices, re-encodes them, and
demands byte-for-byte agreement.

It also has to be the thing that says **no**. Some destinations hold a voice
open — routing into the VCA or sustain area is how a note gets stuck, which
happened during this investigation and is the instrument doing exactly what it
was told. The adapter should mark those and warn before writing, not after.

### 3 · MPE

**The Moog One does not implement MPE.** Five JUCE MPE classes are linked into
`las-frontend`; there is no Moog subclass of any of them and no user-facing MPE
string anywhere. It is framework residue, like the unused TLS HTTP client, the
unused Qt5/WebKit install and the 734 idle UGens. This machine is full of
complete, loaded, never-invoked subsystems.

So the honest shape is the one already proposed: **a mapping surface, not a
passthrough.** "This MPE gesture drives that OSC target." Explicit, manual,
truthful.

And the limit has to be stated in the UI, not buried: `/p` addresses are
**per-timbre and global**. A Seaboard's slide can drive filter cutoff, and that
feels good — but for all sounding notes, not per note. MIDI terminates in the
XMOS, so per-note expression cannot be added where notes are actually allocated.

The router does not care what is downstream, though. Other OSC targets may
handle per-note properly, and the mapping tab is useful pointed anywhere.

### 4 · The Rack — resident DSP the instrument never loads

*(Working name. "UGen enabler" is accurate and unusable. Candidates: **Rack** —
extends the mental model users already have; **Engine**, matching Moog's own
name for the SuperCollider layer; **Modules**. "Rack" implies effects and some
of these are generators, so **Engine** may be the more honest word.)*

The finding: the 96 plugin `.so` files register **795 UGens**. The 104 shipping
synthdefs use **61**. The remaining **734 are resident, registered and idle** —
JPverb and Greyhole (two of the best modern algorithmic reverbs anywhere),
FreeVerb/FreeVerb2/GVerb/TALReverb, a `MoogVCF` ladder model, the complete STK
physical-modelling set, the Ambisonic Toolkit, the whole granular family, 55
machine-listening UGens.

Using them is a **SynthDef sent to `scsynth` over loopback** — no cross-compile,
nothing written to disk, gone on restart, unaffected by firmware updates. The
mechanism is already proven in this repository.

Two guards that must exist before this is safe to hand someone playing live:

- **CPU.** There are only 3–7 points between a full patch and the throttle.
  JPverb is not free. Refuse visibly rather than cause a dropout.
- **Group placement.** The rack has a real structure — `~insertGroup`,
  `~busGroup`, and the load-bearing `doneAction: 1` vs `2` invariant. A synth in
  the wrong group either does nothing or frees something it should not.

### 5 · Improvements — a live feed

The most valuable long-term surface and the one with real security work in it,
so treat it as such from the start.

An improvements feed is **a remote-code channel into a musical instrument.**
That is the same problem Moog solved with a signing key they never shipped, and
we would be building the thing they deliberately did not.

Non-negotiables:

- **Signed by us**, verified on the device. Not TLS-only — TLS authenticates a
  server, not a payload.
- **Show the diff before applying.** Never silent.
- **Everything reversible.** Runtime state and drive files only; nothing to the
  rootfs, ever.
- **Pinned versions.** An improvement records which firmware it was validated
  against; refuse or warn otherwise.

Done well this is how a discontinued instrument keeps improving after its maker
stopped. Done carelessly it is a botnet with a keyboard.

### 6 · Diagnostics

Easy, high value, and it shows things the instrument's own screen cannot. `moogd`
already reads `/proc` and `/sys` directly. Available today:

| | |
|---|---|
| per-core load | cpu0 vs cpu1, and which is the audio core |
| thread detail | every `scsynth` thread, policy, priority, affinity — the thing `taskset` hides |
| temperature | SOM **and** VX, both already polled by the firmware |
| engine | ugens, synths, groups, synthdefs, live headroom against the throttle |
| audio IRQ | `sdma` counts — 82.4M on cpu0, while `esai` has never fired once |
| storage | rootfs 149 MiB free; `/var` 3.5 GB; the update slot's **12.2 MiB** margin |
| defects | the stray `/sched_rt_runtime_us` file, recreated every boot |

That last one deserves a light on the dashboard. Moog meant to raise the
realtime throttle to 99.995%; a **missing slash** wrote `999950` into a file at
the filesystem root instead of into the sysctl, which still reads the 95%
default. Confirmed live.

**Corrected 2026-09-11.** This said the defect was harmless because throttling
had "fired zero times". That was asserted rather than checked, and it was never
true: `/var/log/messages` records three activations, the most recent six minutes
before a lockup that needed a power cycle. The panel now reads the count out of
the log instead of assuming it, and grades the defect by what it finds. Raising
the ceiling as Moog intended is no longer insurance against a hypothetical — the
engine is reaching the ceiling it has.

---

## Build order

1. **Diagnostics.** Cheapest, immediately useful, and it makes everything after
   it measurable. You cannot honestly gate the Rack on CPU headroom without it.
2. **The matrix graph**, preset-backed, with live audition. The clearest win,
   needing nothing unproven.
3. **The Rack**, once the CPU guard from (1) is trustworthy.
4. **MPE mapping**, once the mioXL is in the path.
5. **Improvements**, last — because its security model deserves design attention
   rather than being bolted onto a working app.

## Ruled out, with reasons

| | |
|---|---|
| Repackaging Moog firmware | The signing key never left Moog. `lasfwu` verifies unconditionally and `--accept-unsigned` is documented but not implemented. |
| MIDI 2.0 on the instrument | The USB-B socket is the XMOS's; the i.MX6 has no USB device port. Interop-only gain, and iPadOS does not support the network transport. |
| Anything on the rootfs | A firmware update writes the *other* A/B slot and boots it. Rootfs changes evaporate; drive files survive. |
| Reading `las-sc` state back | `las-sc` replies to the front panel, never to us. |
| ~~Reading the matrix back~~ | **Overturned 2026-09-10.** The voice controller echoes every matrix blob byte-for-byte (71 of 71, confirmed by IP-ID signature). `moogd` sits on that link. |
| Writing voice-card flash (`/fw/*`) | No software recovery, and the boards are unobtainable. Not worth any feature. |
