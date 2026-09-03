# moogone — Moog One sound-engine toolkit

A Python toolkit for talking to the Moog One's internal SuperCollider audio engine
(`las-sc`, OSC over UDP), plus a measurement rig for diagnosing its effects noise.

**Nothing in this repository has ever touched the hardware.** The whole toolkit was built
against a mock server. A green test suite means "internally consistent with the assumptions
written down in `src/moogone/mock/server.py`" — not "correct about the device". Every
assumption that turns out wrong in September should surface as a failing test rather than a
mystery; that is what the mock is for.

---

## The September checklist

This is the operator sequence the whole repository exists to serve. The hardware window is
short and does not repeat. **Print this page.**

Steps 1–3 are passive. Nothing transmits to the device until step 4.

### 1. Establish access

USB `k` file, ethernet, boot, `ssh root@<ip>`.

**Nothing else matters until this holds.** Do not start step 2 until you have a shell.

### 2. Passive recon

```sh
scp recon/moog-recon.sh root@<ip>:/tmp/
ssh root@<ip> 'sh /tmp/moog-recon.sh --out /tmp/moog-recon --active'
scp -r root@<ip>:/tmp/moog-recon ./captures/
```

Read-only. It never transmits OSC in either mode; `--active` only writes the runbook for
steps 4–8 into `07-active-probes.txt`. It cannot abort: every external command is guarded, and
it exits 0 and produces output even on a host where none of the target paths exist.

If it reports `***** TRUNCATED *****` anywhere, read that marker before treating an absence of
results as evidence of absence.

### 3. Read `03-sockets.txt`

Confirm the real port and the bind address **before transmitting anything**.

The two questions it answers:

- **Which port** does the sound engine actually use? (9300 is a 2021 writeup's claim, six
  firmware releases stale.)
- **Is it bound to `127.0.0.1` or `0.0.0.0`?** Loopback means you must run on-box or use
  `--tunnel`; `0.0.0.0` means the Mac can reach it directly.

`ss` and `netstat` are both optional on a stripped device. If they are missing, read the
`/proc/net/udp` and `/proc/net/tcp` tables in the same file — the header there explains the
byte-reversed hex.

### 4. `moogone status`

```sh
moogone status                     # add --port <real-port> if step 3 says otherwise
```

Confirms `las-sc` speaks the SuperCollider protocol at all. Cheapest possible check.
**If this fails, everything downstream needs rethinking** — do not proceed to step 5 assuming
it will work.

If the reply comes back with an unexpected number of arguments, the error names the message and
echoes exactly what arrived. Keep that text; it is what a first-contact failure has to tell you.

### 5. `moogone tree`

```sh
moogone tree --json > captures/tree.json
moogone tree                       # human-readable
```

The live FX chain and **every control name**. This is the source of truth for the FX SynthDef's
real control names, which step 8's harness template needs.

If the server answers without the control values, this refuses rather than showing every effect
as having no controls.

### 6. dumpOSC capture — **the highest-value artifact in the project**

Turns guesswork about Moog's own OSC namespace into observed fact, for both this project and
the per-voice pressure project at once. **Read all of step 6 before starting any of it.**

```sh
screen -ls                                    # find the engine's session name
screen -S <session> -X logfile captures/08-dumposc.log
screen -S <session> -X logfile flush 1
screen -S <session> -X log on                 # BEFORE dump mode, not after
moogone dump 1
# --- now: 30 FULL SECONDS moving every front panel FX control. Play chords too. ---
moogone dump 0
screen -S <session> -X log off
wc -l captures/08-dumposc.log
```

Log to **disk**, not to the scrollback. `screen -X hardcopy -h` dumps the scrollback buffer,
which defaults to 100 lines; thirty seconds of knob motion is plausibly thousands, and you would
get a file that looks complete and holds only the tail. A result near 100 lines is a warning
sign, not a small capture.

`moogone dump` fails loudly if the engine rejects `/dumpOSC`, rather than printing success over
a rejection. That check exists because there is no second attempt at this.

**Do it once, thoroughly. You are not back tomorrow.**

### 7. Go/no-go for per-voice pressure

Hold a note, then:

```sh
moogone set <voice-node-id> <param>=<value>
```

Node ids come from step 5. One voice changes, or the per-voice pressure project is dead.

Read the output; it distinguishes three outcomes, and the difference matters:

| Output | Meaning |
|---|---|
| `sent to node N (synth): {...}` | write went out and the server confirmed it processed it |
| `sent to node N (synth), UNCONFIRMED: {...}` | write went out; this server does not answer `/sync`. Run `moogone tree` to check. |
| `error: ...` | nothing was sent — wrong node id, or the node is a group |

`/n_set` is fire-and-forget and scsynth never acknowledges it, so **no** outcome here proves the
*value* took. `moogone tree` is what confirms that.

### 8. FX probe

Render the harness script with the real defname and control names from step 5:

```sh
python3 -c "from moogone.harness import render_probe_script; \
  print(render_probe_script('<fx-defname>', '/tmp/probe-before.wav'))"
```

Paste it into the engine's sclang session. It writes **two** files — a **silence probe** and a
**tone probe**. Change something, run it again with a different `out_path`, copy all four WAVs
off, and compare.

The **silence probe** is the one that answers the question. See `harness/README.md`; the short
version is that a noise floor is measured in the gaps, and a continuous tone has none — fed tone
probes, `compare_recordings` refuses rather than returning a plausible number.

Two caveats worth carrying into the room:

- That refusal is near-total, not total. A very slow, very shallow modulation — chorus or flanger
  around 0.5 ms depth at 0.05–0.12 Hz — can slip through a 5-second capture and report ≈ −0.1 dB
  against a true −12. **If you are probing a modulated effect, use `seconds=20` or more**; the
  gap is caused by capturing less than one LFO cycle and closes entirely at that length.
- The error never inverts. Across 882 measured comparisons of a true 12 dB improvement there were
  zero sign flips. An improvement may be understated; it will not be reported as a regression.

---

## Getting `moogone` onto the device

The core package has **no third-party dependencies** (`pyproject.toml`: `dependencies = []`), so
this is a copy, not an install:

```sh
scp -r src/moogone root@<ip>:/tmp/
ssh root@<ip>
cd /tmp && python3 -m moogone.cli status
```

Check `06-toolchain.txt` from step 2 for whether `python3` exists on the device at all.

If it does not, run from the Mac instead:

- **Socket bound to `0.0.0.0`** — connect directly: `moogone status --host <ip> --port <port>`.
- **Socket bound to `127.0.0.1`** — use `--tunnel`. It routes through three different ports, not
  one; `moogone --help` spells out the topology in full. Both the `ssh -L` forward and the
  device-side `socat` bridge must already be running — `moogone` starts neither.
- **No `socat` on the device** — do not fight this. Run on-box with a plain UDP connection.

The analysis and harness modules additionally need `numpy` and `soundfile`, but those run on the
**Mac**, on WAVs copied off the device. Nothing on the device needs them.

## Install (Mac side)

```sh
uv sync
uv run moogone --help
uv run pytest
uv run ruff check src tests
```

## What is in here

| Path | What it is |
|---|---|
| `src/moogone/osc/` | OSC 1.0 codec — messages and bundles, encode and decode |
| `src/moogone/transport/` | UDP transport, and an SSH+socat tunnel for reaching a loopback-bound engine |
| `src/moogone/sc/` | SuperCollider client: `/status`, `/sync`, `/g_queryTree`, `/n_set`, `/n_query`, `/d_recv`, `/dumpOSC` |
| `src/moogone/mock/` | A mock scsynth. Where this project's assumptions about `las-sc` are written down. |
| `src/moogone/analysis/` | WAV loading, noise floor, spectrum, A-weighting, SNR |
| `src/moogone/harness.py` | The FX noise probe: sclang script generation and before/after comparison |
| `src/moogone/cli.py` | The `moogone` command |
| `recon/moog-recon.sh` | Single-pass, read-only device reconnaissance (POSIX sh, busybox-compatible) |
| `harness/README.md` | Why the probe is decisive, and how to read a comparison |

## The question this is all for

Is the Moog One's effects noise coming from the **DSP** (fixable in software, via `/n_set` or a
replacement SynthDef through `/d_recv`) or from the **converters** (a hardware ceiling, and the
project ends in a diagnosis)?

Step 8 answers it. The probe generates a tone inside SuperCollider and records the effect's
output on-box, so the signal never passes through the ADC:

| Probe recording | Real playing | Verdict |
|---|---|---|
| Hissy | Hissy | Noise is DSP-side — **fixable** |
| Clean | Hissy | Noise enters at the converters — **hardware ceiling** |
| Hissy | Worse | Both contribute; fix what is reachable |

---

## Vox — the workbench

A bridge on the Mac that serves a touch-first UI over the LAN. Mac or iPad, one URL.
Design: `docs/superpowers/specs/2026-09-03-vox-workbench-design.md`.

```sh
uv sync --extra dev --extra analysis --extra vox
uv run vox --mock                        # no synth needed; mock scsynth in-process
uv run vox --sc-host 192.168.1.138       # the real effects engine
open http://<your-mac-ip>:8765           # or type it into the iPad
```

Every control carries a badge. **live** was verified on hardware this session (scsynth
`/n_set` + `/g_queryTree`, and the four output meters). **untested** is plausible and has
never been run. **blocked** needs a discovery step, and the badge says which.

Four panels: **FX** (every effect node, live, with A/B), **Expression** (MPE / poly-AT in,
a voice grid, the go/no-go), **Patch** (route anything to anything, with curves and slew),
**Surface** (an XY pad and two rotaries bound to any effect controls).

### Morning checklist — what turns badges from untested to live

Nothing below was possible with the synth off. Do them in order; each is one experiment.

1. **Cable.** Komplete Audio 6 DIN out → Moog DIN in. `uv run vox --midi-out "Komplete"`,
   Expression → "Send test chord". You should hear C-E-G. If not, MIDI out from the Mac is
   dead and the `amidi`-over-SSH fallback is the path.
2. **Meters live.** `uv run vox --live-meters --device 192.168.1.138`. The strip should
   move with the synth's output. Note the real update rate; the spec guessed and was told
   not to.
3. **The effects, for real.** `uv run vox --sc-host 192.168.1.138`. FX panel, move
   `pingpongDelay_0 → mix`. The chip should go *sent* → *confirmed* and you should hear it.
   This is the one path already verified; it should just work.
4. **The go/no-go.** Hold a chord on the synth. Expression → "Run go/no-go". It will show
   you the blocked reason: the per-voice write address is in the 464 unmapped `/p` entries.
   The way to find it is `tcpdump -i usbint` on the box while `las-sc` boots the cards, or
   while moving any per-voice control the panel exposes. That capture is the next project.
5. **Raw OSC.** Patch → route `meter.mainl` to `osc.lc.kbd.oct`. If the synth's octave
   changes, `las-sc` writes work and that badge flips. If not, the session's six-silent-
   writes result is now reproducible.
