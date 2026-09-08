# What is worth building, and why the architecture allows it

Every item is checked against `docs/ARCHITECTURE.md` and `docs/DANGER.md`. The
check is the point: three things were built in this project before the instrument
was understood, and none of them survived it.

**The constraints everything below respects.** Both CPU cores are committed — cpu1
runs `scsynth`'s audio thread alone at `SCHED_FIFO` 99, cpu0 runs everything else.
The effects rack is complete: five slots, ten pre-allocated Eventide instances. The
voices are analog and most of their audio never enters the computer. And the
instrument's own back panel already does more than the software surface suggests.

---

## 1. The modulation expression language — the standout

**What it is.** The Moog One runs a stack-machine language, stored as plain text in
every preset:

```
/modmatrix/expressions  "e3 c5 * o2pno sto   mw c1 * ofm sto   l4 c11 * vca sto"
```

Reverse Polish. Vocabulary `* + - ** *** min max sto rcl rnd rndb`, 64 constant
registers, ~70 destinations, and **36 shaping transforms** — sample-and-hold,
track-and-hold, quantiser, boolean logic, waveshapers, diode stages.

**The panel writes one sentence of it**: `src × amt → dst`, seven tokens. Factory
content uses six of the 36 transforms. Everything else is reachable and unused.

**Architecture check.**
* **CPU: none.** It runs on the XMOS voice controller. `modmatrix` appears in
  neither `las-sc` nor either firmware image — it is interpreted on the far side of
  the control link, on neither i.MX6 core. Nothing else on this list is free.
* **Risk: low.** It lives in `/p`, which is patch state — the same thing the panel
  writes when you turn a knob, recoverable by reloading the preset.
* **Not duplicating anything.** The panel cannot express these.

**Blocked on one file.** `las-sc` boots with `--expr-syms=/usr/share/vx_ee.scm`, the
symbol table, and it is not in the capture set. Fetch it first; it names the
destinations and transforms.

**Two attested oddities worth exploiting.** `dst` is free text — four factory
presets ship `dst "/dummy"` — and 3724 of 3850 entries say `t/1` regardless of which
timbre owns them, so cross-timbre routing already persists. There are also 30 unused
modulation inputs (`modmatrix/vars/var0-9`, named `VAR 1…10` as sources, zero uses
in all 398 presets).

---

## 2. The CV outputs

**What it is.** Four assignable CV outputs on the back panel, addressable at
`/p/part/cv_settings/cv_output/{1..4}/{source,min,max,synth}` and stored in every
preset. Sources include `PITCH`, `GATE`, `MOD`.

**Architecture check.** `/p` again — patch state, safe. Physical jacks confirmed in
Moog's manual, page 20. No CPU cost on either core.

**Why it belongs next to item 1.** A computed expression whose destination is a CV
output is arbitrary generated control voltage into a modular rig — from an
instrument whose panel offers a fixed list of sources. That is the combination worth
building, and neither half is any use without the other.

*This project previously closed CV out as impossible, on a 404 from a single address
in the wrong namespace. See `docs/CLAIMS-AUDIT.md`.*

---

## 3. Patch generation and analysis

**What it is.** Preset payloads are newline-separated `<OSC address> <JSON value>` —
no BLOBs, address set identical to the live tree, 4697 of 4697 lines round-tripped.
And `.m1p` files are ASCII dumps of the `/p` namespace carrying **~3,200 addresses
with types and defaults**.

**Architecture check.** No hardware required at all. It is a text problem.

**Why it matters more than it sounds.** It sidesteps the unsolved firmware
compression entirely: the namespace we wanted from the compressed table is obtainable
from a preset file. Bulk edit, diff, analyse, generate.

---

## 4. Drive the instrument's own effects rack

**What it is.** Control the five real slots over `/fx` instead of creating parallel
effect nodes.

**Architecture check.** Uses the ten pre-allocated Eventide instances rather than
adding an eleventh. **Zero added CPU**, against 23-33% for a duplicate reverb. It is
what the panel does.

**This replaces the effect send**, which duplicated a rack that already existed and
whose CPU cost caused the dropouts that then caused a block-size change that degraded
insert latency. The whole chain was self-inflicted.

---

## 5. Vector and surface mapping

Sound reasoning, unchanged, and better targeted now: an XY surface driving `/p`
destinations, and with item 1 in place, driving *expressions* rather than single
parameters. Zero DSP cost. Already partly built.

---

## 6. The sampler

**Architecture check.** `PlayBuf` plus an envelope is 1-3% of a core. Additive — the
Moog One has no sampler — and the 234 GB USB drive is the natural home for the audio.
Survives intact.

**One correction to carry over:** main outs are **bus 7 = L and bus 0 = R, both
phase-inverted**. Five files in this repo have that backwards.

---

## 7. FM

Survives, budgeted. Heavy FM measured ~24 points, comparable to a reverb, so it fits
on a light patch and not a heavy one. Additive, not duplicative. A per-patch choice,
not a free feature.

---

## Research, not features

**The firmware string table.** Not cracked. The 2-byte reference's length field is
solved exactly (`len = (operand >> k) + 3`, k by marker) and the "distance in the low
bits" family is *disproved*, not merely unfound. The next attempt should run the
merge rather than sweep parameters — the known 2-byte lengths make the
cross-encoding equations linear in the unknown 3-byte lengths, and solving those lets
the reference field be read off a few hundred token/source pairs instead of guessed.
Lower priority than it was, because item 3 delivers the namespace without it.

**`vx_ee.scm`.** One file, on the instrument, blocking item 1.

---

## Ruled out, with reasons, so they stop coming back

| | why |
|---|---|
| A second SuperCollider server for more DSP | No spare core. cpu1 is the audio core. |
| Any audio path over the network | 105-165 ms measured to the jacks; the instrument's value is being inside the sample clock, which is generated on the analog side. |
| The CLAP plugin's audio shapes | The back panel already has an **EXT INPUT** (Neutrik combi + LINE) appearing as a mixer channel, and **four INSERT jacks** with send/return. A cable does it at analog latency; the plugin did it over the network at 115 ms. Its *automation* shape survives. |
| More reverb, or rebuilding the rack | Five slots and ten pre-allocated Eventides already exist. |
| `outputRouter` aux routing for bus effects | `master1_r`/`master2_r` have no writer anywhere; only index `[0]` is live. The panel control that appears to do this writes `dry_dir4_r` and produces only the DC bug. |
| Freeing any LADSPA node | Terminates `scsynth`. `doneAction: 1` on the ten `et_*` defs is the load-bearing invariant. |
| Exposing `enable` as a UI control | On the routers and every native effect it carries `doneAction: 2` — writing 0 frees the node. |

---

## The rule this document exists to enforce

Check the instrument before building for it — **including its back panel and its
manual**. Two features in this project were built against the software surface alone,
and both turned out to reimplement hardware that was already there. Fifteen minutes
with the manufacturer's manual would have caught both.
