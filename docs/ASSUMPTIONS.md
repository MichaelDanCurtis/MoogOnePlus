# What this toolkit assumes, and what it costs if the assumption is wrong

Read this before the September session, and again if a result surprises you.

**Nothing in this repository has ever contacted the Moog One.** 282 passing tests mean the code
is internally consistent with assumptions written down in `src/moogone/mock/server.py`. They do
not mean the code is correct about the device.

The published findings everything was built from — sound engine `las-sc` on `localhost:9300`,
effects under `/usr/share/las-fx/`, `/etc/init.d/S42sc` — come from firmware around v1.2/v1.3 in
2021. The current release is v1.8.2, September 2025. That is roughly six releases of drift.

---

## Assumptions that fail loudly

These are safe. If they are wrong you get an error naming the problem, not a wrong answer.

| Assumption | How you find out | What the error tells you |
|---|---|---|
| `las-sc` speaks the SuperCollider protocol | `moogone status` | If it is trimmed, the reply arity mismatch names `/status.reply` and echoes what actually arrived |
| The engine is on port 9300 | `03-sockets.txt`, step 3 | The real port, read from the socket table rather than assumed |
| It is bound to `127.0.0.1` vs `0.0.0.0` | `03-sockets.txt` | Decides on-box vs `--tunnel` vs direct |
| Replies come from the port we sent to | any command | The sender-validation error prints **both** the expected and the actual address — that is how you learn the real reply port |
| The node graph has the shape we guessed | `moogone tree` | Refuses rather than reporting every effect as having no controls |
| `/dumpOSC` is accepted | `moogone dump 1` | Raises on `/fail` rather than printing success over a rejection |
| Voice cards are individually addressable | the go/no-go, step 7 | Distinguishes "sent", "unconfirmed", and "refused — that node is a group" |
| The `k`-file access path still works | step 1 | Binary. Nothing downstream matters until it holds. |

---

## Assumptions that fail *quietly* — the ones to actually worry about

These produce a plausible, well-formatted number when the assumption is wrong.

### 1. A noise-like effect can defeat the probe guards

Distortion and granular effects can make a tone probe look measurable to both the
single-recording and pairwise guards. Known, unclosed, and structural — the guards test tonality,
and these effects destroy tonality without creating quiet windows.

**Mitigation:** always compare the **silence probes**. The tone probe measures what the effect
does to signal; the silence probe measures what it adds on its own, and it is the one that
answers the DSP-versus-converters question.

### 2. Very slow, very shallow modulation on a short capture

Comb depth around 0.5 ms at 0.05–0.12 Hz on a 5-second probe reports about **−0.1 dB against a
true −12 dB**. Reads as "the change did nothing."

Cause is duration, not depth: at those rates 5 seconds holds less than three-quarters of an LFO
cycle, so the notch never sweeps far enough for the floors to diverge.

**Mitigation:** `render_probe_script(..., seconds=20)` for any modulated effect — chorus,
flanger, phaser, tremolo. The gap closes entirely at that length.

**It never inverts.** 882 measured comparisons of a true 12 dB improvement produced zero sign
flips and zero "worse" verdicts. An improvement may be understated; it will not be reported as a
regression.

### 3. The generated sclang has never been executed

`sclang` was unavailable throughout. The probe template is verified structurally — bracket
balance, node ordering, bus wiring, no surviving placeholders — but nothing has ever run it.

A Python model of SuperCollider's bus semantics was considered and deliberately rejected: it
would test the model, not SuperCollider.

**Mitigation:** the first time you paste it, check the `screen` session for errors before
trusting the recording. A `SynthDef not found` means the defname from step 5 is wrong, not that
the effect is silent.

### 4. `/n_set` is never acknowledged

scsynth does not confirm parameter writes — this is protocol, not a gap. `moogone set` reports
what it *sent*, never that the value took.

**Mitigation:** `moogone tree` is the confirmation. Always.

### 5. The mock's node metadata is invented

`/n_info`'s parent/prev/next come from a synthetic tree. Only `is_group` is read anywhere, so
nothing depends on the rest today — but do not start trusting those fields without checking them
against real hardware.

---

## Parked deliberately, with reasoning

Real, understood, and not fixed — recorded so they are not rediscovered as bugs.

- **Nested-bundle sibling relocation.** A corrupted size prefix can silently move a bundle
  element into a preceding nested bundle's children. Undetectable *in principle*: the two byte
  streams are identical and both are structurally valid OSC. No decoder can resolve it. The
  server sends plain reply messages, not nested bundles.
- **Recon watchdog exit-code ambiguity.** Kill detection uses status 143, which cannot be
  distinguished from a `find` that voluntarily exits 143. No real `find` implementation does;
  no portable-`sh` alternative exists without `timeout(1)`.
- **Narrow-band no-change refusals.** Bands under ~20 Hz wide get refused on genuine no-change
  comparisons at a low single-digit rate. Those fixtures carrying a real change still measure
  correctly — what a refusal costs is being told "nothing changed", not the ability to measure
  something that did.
- **Tunnel framing.** `TunnelTransport` does a bare TCP `recv`, so OSC message boundaries are not
  guaranteed across the `socat` bridge. Development convenience only; the on-box UDP path has no
  such problem, and that is where the real work runs.

---

## The honest summary

The engineering is well tested against a fiction. Every defect this project found late — a NaN
that made three measurement functions return `nan`, a DC bin reading 6 dB high, a truncated
search indistinguishable from an empty one, a probe its own analysis rig could not measure — was
**output that lied about its own completeness**, and none of them announced themselves.

The `dumpOSC` capture in step 6 is what converts this from assumption to fact. Everything above
is provisional until then.
