# Vox — a workbench for the Moog One

**Date:** 2026-09-03
**Status:** Drafted overnight under the owner's mandate ("while I am sleeping, create an
app"). Not interactively approved. **Every decision below was made for you — review the
first section before anything else.**
**Builds on:** [Foundation](2026-08-10-moog-one-foundation-design.md),
[Per-Voice Pressure](2026-08-10-moog-one-per-voice-pressure-design.md),
[MOOG-ONE-INTERNALS](../../MOOG-ONE-INTERNALS.md)

---

## Decisions I made for you

Read these first. Each one is reversible; none is hidden.

| Decision | What I chose | Why | Change it if |
|---|---|---|---|
| **Name** | **Vox** — after the `vx` voice cards | Short, product-shaped, not "Moog One Tool v1" | You have a better one; it's a string |
| **Platform** | Python bridge on the Mac + a web UI served over the LAN | The only way to get Mac *and* iPad tonight. Browsers cannot send UDP, so a bridge is required anyway; the iPad just opens a URL | You want native feel enough to wait for a SwiftUI build you'd have to sign for iPad |
| **What is proven vs. not** | Every control in the UI carries a badge: **live** (verified on hardware this session), **untested** (plausible, never run), or **blocked** (needs a discovery step first) | This project's defining failure mode is confident output that was wrong. The UI should not repeat it | Never. This one stays. |
| **MPE scope** | Per-note **pressure** (and slide/bend where the controller sends them), decoded from MPE *or* poly-aftertouch, with a voice-tracking engine that owns its own note→voice map | The prior spec's reasoning holds: pressure is the dimension the S88 actually has | You get an MPE controller with real slide/bend and want those prioritised |
| **Where MPE goes** | The engine is complete and tested. Its *synth-side* destination — the per-voice write address — is a **blocked** slot until the go/no-go runs on live hardware | The address is somewhere in 464 unmapped `/p` entries. I will not guess it | The go/no-go passes; then it's one config value |
| **Effect creator** | Two tiers. (1) Live control of the 17 existing effect nodes — **live**. (2) A visual graph that generates SuperCollider code, pushed to `sclang` on the box — **untested** (the harness README admits the generated sclang has never run there) | Tier 1 is the working effect workbench tonight. Tier 2 is real but honest | You'd rather have a binary SynthDef compiler (`/d_recv`) — bigger job, later |
| **Modular routing** | A source→destination matrix with scaling, curves, and a patch-cable canvas. Proven destinations: effect params, MIDI to the synth. Unproven: raw OSC to `las-sc` / voice bus | Same badge rule | — |
| **MIDI path** | MIDI **in** from a controller on the Mac (rtmidi). MIDI **out** to the synth via the Komplete Audio 6 DIN out → Moog DIN in — **untested**: MIDI has only been proven *from the box's own ALSA*, not from the Mac | One cable check in the morning | The DIN path doesn't work: fall back to `amidi` over SSH (proven, slower) |
| **Build order** | Bridge → FX workbench → MPE engine → router → generator → UI shell | Proven paths first; each phase testable against the mock before hardware | — |
| **Scope tonight** | Phases 1–3 built and tested. Phase 4 (generator) built with tests. Phase 5 (UI) as a working shell hosting 1–3 | Honest for one night. The rest is planned, not pretended | — |

---

## The idea

A single app that treats the Moog One as what it is — two computers, a SuperCollider
effects engine, sixteen addressable voice cards — and lets you play with all of it from
one organic surface on a Mac or an iPad. Four faces on one bridge:

1. **Surface** — the Animoog / Native Instruments feel: big XY pads, rotary controls with
   inertia, glowing meters. Touch-first.
2. **FX Workbench** — every effect node, every control, live. Plus a visual effect builder
   that writes SuperCollider for you.
3. **Expression** — MPE / poly-aftertouch in, per-voice expression out. An adapter.
4. **Patch** — a modular routing canvas. Anything that changes routed to anything that
   listens, with cables.

The thing that makes all four possible is one process: the bridge.

---

## Architecture

```
  iPad Safari ─┐                                ┌─▶ scsynth  192.168.1.x:57110   UDP   LIVE
  Mac browser ─┴── HTTP + WebSocket ──▶  Vox bridge (Mac)  ├─▶ MIDI out → Komplete Audio 6 DIN → Moog      UNTESTED
                                          │                └─▶ ssh → oscsend / amidi on the box            LIVE (slow)
  MPE / poly-AT controller ── USB MIDI ───┘
```

**Why a bridge.** Browsers cannot open UDP sockets. OSC is UDP. So *something* on the
Mac must speak UDP to the synth. Once that exists, the UI is a web page, which is what
puts it on the iPad with zero signing.

**Why the bridge is Python.** The OSC codec, the SuperCollider client, the UDP transport
and a mock scsynth already exist in this repo with 328 passing tests. Vox reuses them.

**Why not on the box.** The per-voice-pressure spec is right that the *production* path
for gesture data should run on the instrument. But the box has no Python, and tonight is
about building something testable. The engine is written so the Mac-side bridge is one
host for it; a port to the box is a later decision, made after the go/no-go.

### Components

Each is a module with one job, a typed interface, and tests that run without hardware.

| Module | Job | Depends on | Tested against |
|---|---|---|---|
| `vox/bridge.py` | HTTP static + WebSocket server; routes JSON messages to the other modules; owns the scsynth connection | `moogone.sc`, `moogone.transport`, `websockets` | mock scsynth |
| `vox/fx.py` | Reads the node tree, exposes each effect's controls with ranges, applies `n_set`, confirms via tree re-read | `ScClient` | mock + `captures/tree.json` |
| `vox/mpe.py` | MPE / poly-AT decoder → normalised per-note events; voice-tracking with steal policy; zone config | nothing | synthetic MIDI bytes |
| `vox/router.py` | Source→destination graph; scaling, curves, smoothing; ticks at a fixed rate | nothing | synthetic sources |
| `vox/destinations.py` | The adapters: `ScParam` (live), `MidiCC`/`MidiNote` (untested), `RawOsc` (untested), `VoiceParam` (**blocked**) | `fx`, rtmidi | mock / recorded |
| `vox/gen.py` | Effect graph → SuperCollider `SynthDef` source text; pushes to `sclang` on the box via the harness path | `moogone.harness` | golden-file tests; on-box run is **untested** |
| `vox/static/` | The UI. One page, four panels, WebSocket client | — | browser preview against mock |

### Message protocol (bridge ⇄ UI)

JSON over WebSocket, one object per message, `type` discriminates.

```
UI → bridge
  {type:"fx.set",   node:1035, ctl:"feedback", value:0.42}
  {type:"fx.list"}
  {type:"route.add", src:"mpe.pressure[0]", dst:"sc.1035.mix", scale:[0,1], curve:"exp"}
  {type:"route.remove", id:"r7"}
  {type:"mpe.config", zone:"lower", master:1, members:15, bend_range:48}
  {type:"gen.compile", graph:{...}}          → returns .scd text
  {type:"gen.send"}                          → UNTESTED, requires ssh

bridge → UI
  {type:"fx.tree",   nodes:[{id,defname,controls:{name:{value,min,max,badge}}}]}
  {type:"fx.value",  node, ctl, value}       ← after confirmation, not after send
  {type:"meters",    mainl:[lo,hi], mainr:[..], send1:[..], send2:[..]}   ← LIVE getters, polled
  {type:"mpe.event", voice, note, pressure, slide, bend, on}
  {type:"route.list", routes:[...]}
  {type:"badge",     path, state:"live"|"untested"|"blocked", why}
  {type:"error",     where, what}
```

`fx.value` is emitted only after the bridge re-reads the tree and sees the value took —
because `/n_set` is never acknowledged (§4 of INTERNALS). The UI shows "sent" then
"confirmed" as two states. That is the harness lesson carried into the product.

### Data flow: one pressure event

```
S88 key pressed harder
  → rtmidi delivers 0xA0 note pressure (poly-AT) or 0xD0 on member channel (MPE)
  → mpe.py: which voice is playing that note? → {voice:3, note:60, pressure:0.71}
  → router.py: any routes with src "mpe.pressure[3]"?
      → "sc.1035.mix" scaled 0..0.6, curve exp          → destinations.ScParam → n_set   LIVE
      → "voice.3.cutoff"                                  → destinations.VoiceParam        BLOCKED
  → UI: mpe.event for the meter; fx.value once confirmed
```

The blocked destination does not silently drop. It surfaces a `badge` with *why* and the
exact experiment that unblocks it.

---

## The four faces

### 1. Surface

Dark ground, tactile controls, motion with weight. The design language is Native
Instruments' Reaktor-era panels and Animoog's XY performance surface — not a spreadsheet
of sliders.

- An **XY pad** per effect slot: X and Y assignable to any two controls; touch and drag,
  multi-touch on iPad.
- **Rotaries** with inertia and a fine-adjust ring on hold.
- **Meters** driven by the four live getters (`/a/stat/*`), polled at ~15 Hz — the one
  read the synth genuinely gives us, so it gets prominence.
- The **badge** on every control. Live = solid. Untested = outlined. Blocked = dashed, with
  a tap-to-read reason.

### 2. FX Workbench

Two tiers, badged differently.

**Tier 1 — live.** Every synth node the tree reports — 17 on this session's capture,
which includes the two routers — each control as a rotary with the range inferred from
its current value and name (`mix` 0–1, `feedback` 0–1, `timeL` in seconds, `gain` 0–2).
The count is read from the tree at connect time, never hardcoded, because the live tree
differed from `tree.json` twice tonight. `enable` as a switch. Changes go by `n_set`,
confirmed by tree re-read. A/B: hold two states, toggle, hear the difference — `ab.py`
as a UI.

**Tier 2 — untested.** A node graph of SuperCollider UGens (a curated set: `DelayC`,
`CombC`, `FreeVerb`, `LPF`, `HPF`, `BPF`, `SinOsc` as LFO, `Pan2`, `XFade2`, arithmetic)
with typed ports. The generator emits a `SynthDef` with named controls, formatted for
the box's `sclang`. "Send" pushes it through the existing screen-session path. It has
never run on the box; the UI says so until it has.

### 3. Expression

The MPE adapter.

**Input.** Either MPE (lower or upper zone, configurable master/member split, per-note
bend range) or poly-aftertouch. Auto-detect by what arrives.

**Voice tracking.** The engine owns its own map. Note-on allocates the lowest free voice
index (0–15); steal policy: oldest. This is the *take over* branch of the prior spec's
Phase 3 — chosen because the observe branch needs evidence from `/dumpOSC` that this
session did not find (no note→voice assignments appeared in the 2,801-message capture).

**Output.** Normalised per-voice events into the router. Where they go is the router's
business, and the only live destination tonight is an effect parameter — which is still
musically real: per-note pressure into delay feedback or reverb mix is expressive, and it
proves the plumbing end-to-end.

**The blocked slot.** `VoiceParam` — the per-voice write to the synth. Unblocking it is
the prior spec's go/no-go, unchanged: *hold one note, send OSC to move that one voice's
cutoff.* The UI has a **"Run go/no-go"** button that walks you through it with the synth
on: it plays a chord over MIDI, sends the candidate write, and asks you what you heard.

### 4. Patch

The modular canvas. Sources on the left, destinations on the right, cables between.

**Sources:** MPE fields per voice, MIDI CC, four software LFOs (sine/tri/saw/S&H, rate,
phase), the four meters (audio-reactive routing: main-L level → reverb mix is a real trick),
a clock.

**Destinations:** every effect control (live), MIDI CC / note to the synth (untested), raw
OSC to `las-sc` (untested), per-voice params (blocked).

**Per cable:** scale range, curve (lin / exp / log / S), slew, invert. The router ticks at
200 Hz and coalesces; effect writes are rate-limited to ~50 Hz per control so we never
flood scsynth.

---

## What "done" means tonight

| Phase | Deliverable | Verified by |
|---|---|---|
| 1 | Bridge serving the UI on the LAN; `fx.list` / `fx.set` round-trip | mock scsynth: set a value, re-read the tree, see it |
| 2 | FX Workbench panel: all 17 nodes, live controls, A/B | browser preview against mock |
| 3 | MPE engine: MPE + poly-AT decode, voice tracking, zone config | unit tests with synthetic MIDI; a recorded `midi_scan` capture if one exists |
| 3b | Router engine: routes, scaling, curves, rate limit | unit tests |
| 4 | Generator: graph → `SynthDef` text | golden-file tests; **not** run on the box |
| 5 | UI shell with Surface, FX, Expression, Patch panels; badges; meters | browser preview on Mac; iPad is a URL away |

**Not done tonight, and said so in the UI:** anything that touches the synth beyond
scsynth. The morning checklist is in the plan.

---

## Error handling

- **Bridge cannot reach scsynth** → UI shows a red state and every scsynth-badged control
  goes disabled. It does not pretend.
- **`n_set` sent, tree re-read disagrees** → UI shows *sent* → *unconfirmed*, with the
  value the tree actually holds. Never *confirmed* on a guess.
- **MIDI port disappears** → Expression panel says so; router keeps running for other
  sources.
- **Route to a blocked destination** → allowed to *create* (so you can set it up), shown
  dashed, never *sent*. The badge reason names the go/no-go.
- **Generator produces something `sclang` rejects** → the error text from the box comes
  back verbatim to the UI. No "success" without the box saying so.

---

## Testing

- **Unit:** `mpe.py`, `router.py`, `gen.py`, `fx.py` range inference — pure, fast, no I/O.
- **Integration against the mock:** `bridge.py` + `fx.py` against `MockScsynth` — set,
  re-read, confirm. This is the same discipline the foundation used, and it caught real
  bugs there.
- **Browser:** the UI previewed in the Claude browser pane against the mock-backed bridge.
- **Hardware (morning):** the checklist. Nothing in the UI shows *live* that this
  session did not verify live.

The discrimination rule from the foundation applies: a test that passes against a
broken implementation is not a test. Each module's tests include at least one case that
fails if the logic is wrong, not just one that passes when it's right.

---

## Other ideas, offered not built

- **Total recall.** `sqlite3` on the box + the 280 MB preset databases. Snapshot and
  restore the *whole* instrument state, with diff. Real, and the schema is readable.
- **Tuning viewer.** `vxtune db-csv` dumps all 48 oscillator tables. A page that plots
  them is a window into your specific instrument's analog character.
- **Audio over the network.** `jack_netsource` is on the box. The synth's output as a
  network audio stream into the Mac, no interface required. Untested; plausible.
- **Protocol learner.** `tcpdump` on `usbint` while playing, captured to the Mac. The
  definitive way to find the per-voice write path — and it may make the go/no-go trivial.
- **CV out.** `/hw/cvout/0` exists in firmware and nowhere else. Something drives it.

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Mac→DIN MIDI doesn't reach the synth | Expression can't prove plumbing | `amidi` over SSH fallback (proven, slower); a cable check is the first morning step |
| The go/no-go fails — no per-voice write path | MPE stays an effect-only adapter | Then `tcpdump` on `usbint` is the next experiment; the router and UI still work |
| iPad Safari WebSocket quirks | iPad experience degraded | Plain `ws://` on a LAN IP is the most boring possible configuration; tested on Mac Safari first |
| Generated SynthDef fails on the box's SuperCollider version | Tier 2 unusable until fixed | Errors surface verbatim; the curated UGen set is deliberately conservative |
| I built the wrong thing while you slept | A morning of redirect | This section, and every badge |
