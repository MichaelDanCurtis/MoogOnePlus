# moogone — Moog One sound-engine toolkit

A Python toolkit for talking to the Moog One's internal SuperCollider audio engine
(`las-sc`, OSC over UDP), plus a measurement rig for diagnosing its effects noise.

> **This paragraph used to say "Nothing in this repository has ever touched the
> hardware."** That was true when it was written and has been false since September
> 2026. The toolkit now runs against the instrument routinely; the mock remains the
> place this project's assumptions are written down, and a green suite still means
> "internally consistent with `src/moogone/mock/server.py`", not "correct about the
> device". The difference is that many of those assumptions have since been checked
> against the real thing — and a good number of them were wrong. See
> `docs/CORRECTIONS-2026-09-08.md` and `docs/firmware/VALIDATION.md`.

## What the instrument actually is

Established by reading Moog's own shipping firmware (see **The firmware, read**
below), and confirmed on the hardware. Several of these reverse long-held beliefs
in this repository, so they are worth having before anything else:

- **The voices are analog.** The i.MX6 is an effects-and-routing engine, not a
  synthesis engine. Most voice audio never enters it.
- **cpu1 is the audio core, not a spare one.** `isolcpus=1` exists to keep things
  *off* it: `scsynth`'s audio thread runs there at `SCHED_FIFO` 99. `taskset -p`
  shows only a process's main thread, which is how that was missed for months.
  Anything you add belongs on **cpu0**.
- **Block size is 128** — `init_sc_1.scd`, the `scsynth` argv, and ALSA's own
  `period_size` all agree. The 256 that appears in some captures is `buffer_size`,
  two periods, and in one snapshot it was this project's own experiment.
- **The i.MX6 is the USB *host*.** The XMOS is the device, and it also enumerates
  the rear USB-B "Moog One" MIDI port. `ethext` is `cdc_ether` over that same link.
- **No MIDI byte from either port reaches Linux.** DIN and USB MIDI both terminate
  in XMOS firmware. Nothing installed on the Linux side can see or inject MIDI at
  the port level.
- **The modulation matrix does not go through `las-sc`.** An edited row is compiled
  to a blob and sent to the XMOS at `/g/<synth>/t/e/s`, `203.0.113.2:7770`, sixteen
  bytes per slot. `las-sc` contains zero matrix code, and
  `matrix_expression_slots` is a **preset-file field, not an OSC address**.
- **`_m` addresses are outputs, not inputs.** They are `las-sc`'s computed
  modulation sums. Writing one is accepted and ignored — verified live.
- **Main left is bus 7, right is bus 0, and both are phase-inverted**
  (`synthdefs.scd:564-565`). Not adjacent, not in the obvious order; three modules
  in this repo had it backwards.

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

- **Which port** does the sound engine actually use? Measured on hardware: **57110**,
  scsynth's own port, bound to `0.0.0.0` and reachable from the Mac. 9300 — the 2021
  writeup's claim, and this tool's default until it was tested — is `las-sc`, a
  different service speaking a Moog dialect on loopback. `--port` now defaults to 57110.
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
| `moogd/` | A static Go binary that runs **on** the instrument from a USB drive |
| `docs/firmware/` | **36 reports over Moog's decrypted shipping firmware.** Start at its `README.md`. |
| `docs/CORRECTIONS-2026-09-08.md` | What this project believed, what is true, and how each is known |
| `docs/arch/` | Earlier subsystem reports — superseded in places by `docs/firmware/` |

## The firmware, read

The official 1.8.2 update package decrypts with the key Moog ships on every
instrument (`/etc/bob.bmp`, 4-bit LSB steganography, passphrase `bob`, per
`/usr/bin/lasfwu`). Both filesystems are now readable as plain files — v1.5.0 from
this instrument and v1.8.2 from the download — and **36 reports, ~35,800 lines,**
cover them in `docs/firmware/`.

It is Moog's copyrighted firmware. It lives under `captures/`, which is gitignored,
and it does not leave the machine it was decrypted on. A repackaged installer
cannot be made to work regardless: the **signing key never left Moog**, and
`lasfwu` verifies `IMAGE-SIG` unconditionally before writing. `--accept-unsigned`
is documented in its man page and **is not implemented**.

**The verification pass refuted 64 of 120 load-bearing claims.** The refutations
are listed in `docs/firmware/README.md` and are the most useful thing there. They
share one failure mode worth internalising: reading a capability out of a *string
or a name* rather than a call site.

### What it turned up that is actually useful

- **734 UGens are loaded and unused.** The 96 plugin `.so` register **795**; the
  104 shipping synthdefs use **61**. Idle and resident: JPverb, Greyhole, FreeVerb,
  GVerb, TALReverb, MoogVCF, the complete STK physical-modelling set, the Ambisonic
  Toolkit, the whole granular family. A new effect is a SynthDef sent at runtime
  over `/d_recv` — no rootfs edit, nothing to cross-compile, gone on restart.
- **`/usr/bin/eec` is an expression compiler.** It compiles expression text to Q24
  words and ships an OSC blob to `vc:7770`, and carries a 47-entry instruction
  reference with five documented defects. `--asm-out` compiles **without sending**,
  which makes the whole instruction set explorable at zero risk.
- **Between 1.5.0 and 1.8.2, Moog changed exactly two files** — the XMOS firmware
  pair. `las-sc`'s OSC namespace did not change at all; the entire 1.8.x MIDI
  overhaul is 67 new keys in `las-frontend`.
- **A live bug in the shipping firmware.** A missing slash writes `999950` into a
  *file* at `/sched_rt_runtime_us` instead of the sysctl, so the realtime throttle
  sits at the 95% default where Moog intended 99.995%. Recreated every boot. In
  practice harmless here — RT throttling has fired zero times on this instrument.

### Two cautions carried forward

- **Bound every packet capture.** Use `tcpdump -c <n>` and verify nothing is left
  running. An unbounded capture preceded an RT-throttle lockup on 2026-09-11.
- **The ext4 extraction drops setuid bits.** Any permission claim made against an
  extracted tree is unreliable and must be re-read from the image itself.

---

## The USB drive

Everything this project puts on the instrument arrives on a thumb drive, and the
drive is also the service-mode unlock. Nothing here requires modifying the rootfs.

### How the instrument finds it

```
 you plug in a stick
        │
        ▼
 40-usb-thumbdrive.rules ──► mounts every sd[a-z][0-9] at /media/<kernel-name>
        │                     with options taken from blkid
        ▼
 sort-part.sh ────────────► symlinks /media/thumbdrive ──► the LARGEST
                                                           mounted partition
```

> **Format it FAT32.** The manufacturer's own instructions say so, and a drive
> formatted on a Mac must be reformatted. Every "USB key" test in the boot
> scripts resolves through the `/media/thumbdrive` symlink, so a stick with one
> big partition is the predictable case. Pulling the drive unmounts lazily and
> deletes the symlink.

### `k` — the unlock dongle

A file named **`k`** at the root of the drive, containing bytes that `hexdump`
reads back as **`23051934`**.

That is **23 / 05 / 1934 — Bob Moog's birthday.**

It is checked twice during boot, and it is the difference between a sealed
appliance and a Linux box you can log into:

| script | with `k` present | without |
|---|---|---|
| `S50dropbear` | starts `dropbear` — **this is the only way SSH ever runs** | no sshd at all |
| `S99final` | leaves the desktop alone | `killall xterm`, `killall las-dwm` |

```sh
# on the Mac, writing the key onto a mounted FAT32 stick
printf '\x34\x19\x05\x23' > /Volumes/MOOG/k      # verify before trusting it:
hexdump /Volumes/MOOG/k                           # expect: 1934 2305
```

> **The "read-only root" is theatre.** `S99final` finishes with
> `mount -f -o remount,ro /`, and busybox's `-f` means *fake* — it skips the
> syscall entirely. The live instrument reports `/dev/root on / type ext4 (rw,…)`.
> Root is writable the whole time the synth is on, key file or not. **[READ]**

### What to put on the drive

| File | Why |
|---|---|
| `k` | SSH, and keeps the desktop alive. Everything else assumes it. |
| `moog-one-v1.8.2` | A firmware package, at the **root** of the drive — not in a folder. `SETTINGS → UTILITIES → UPDATE FIRMWARE` lists every package it finds there. |
| `moogd` | The static Go server (`moogd/`). Run it with `taskset -c 0` — cpu1 is the audio core. |
| `vox/` | The web UI `moogd` serves. |

---

## The boot slots, and getting back in

### A/B, and the one file that chooses

Two full root filesystems, ~767 MiB each. An update writes the **other** one and
points the bootloader at it, which is why a firmware update cannot destroy the
system you are running, and why `/var` — presets, settings, `tuning.vxtune` —
comes through untouched on partition 6.

| partition | size | holds |
|---|---|---|
| `mmcblk2p2` | 785,455 KB | firmware slot B |
| `mmcblk2p3` | 785,479 KB | slot A — the live rootfs |
| `mmcblk2p4` | 64,583 KB | **`/var/lib/sys`** — vfat, and the slot chooser |
| `mmcblk2p6` | 4,164,608 KB | `/var` — presets and calibration, never touched by an update |
| `mmcblk2p7` | 913,391 KB | `/mnt/fwu` — update staging |

Three files in `/var/lib/sys` steer the next boot, all written by `lasfwu`:

| file | value |
|---|---|
| `bootme` | `2` or `3` — the slot to boot |
| `sentinelu1`, `sentinelu2` | commit markers: `0` before flashing, the new `versionb` after |
| `bootversion` | the human-readable version string |

> **Nothing in the 492 MB rootfs reads any of them.** `grep -rl` over the whole
> tree matches only `lasfwu` and `fstab`. **The consumer is U-Boot**, which does
> not live in the rootfs — so what happens when a sentinel is zero, or when both
> slots look bad, **cannot be determined from the firmware**. It is the one part
> of the update path this project has not been able to read. **[UNKNOWN]**

And it is the fragile part. `/var/lib/sys` is **FAT with no journal**, left
mounted and dirty, and the live kernel log already says so:

```
FAT-fs (mmcblk2p4): Volume was not properly unmounted.
                    Some data may be corrupt. Please run fsck.
```

### "Restart your Moog One" means the power switch

There is no software restart. **Nothing in the rootfs calls `/sbin/reboot`,
`halt` or `poweroff`** — the only matches are a commented-out `ctrlaltdel` line
and busybox applet symlinks. `las-frontend` contains no `reboot` string at all
and only ever execs `las-sc`, `lasfwu` and `vxtune`. **[READ]**

> **Do not run `/sbin/reboot` yourself.** It wedges the USB link — LEDs on, one
> line on the OLEDs, no display, no network — and needs the power removed. To
> restart just the audio engine, use `/etc/init.d/S42sc restart`.

That also explains why the eMMC is routinely found dirty: the sanctioned way to
restart this instrument is to throw the switch.

### Service mode

**Hold HOME + SETTINGS while powering on.** `detect-held-buttons` polls the panel
through `las-frontpanel-poll /cb`; on button code **48** it stops
`las-watchdog`, `las-frontend` and `las-sc`, and launches **`lassvc`** — the
factory service console, 3.4 MB, with its own OSC plane: `/cal`, `/info`, `/fw`,
`/hw`, `/mix`, `/testosc`.

> `lassvc` can write the instrument's **serial number, MAC and UUIDs**. It also
> links the voice-card flasher — though the live flash call sites are in `las-sc`,
> not here. A bricked voice card has **no software recovery path** and the boards
> are not sold. Read `docs/firmware/lassvc.md` before touching any of it, and
> treat `/fw/*` as off-limits.

## The question this is all for — ANSWERED, 2026-09-04

> Is the Moog One's effects noise coming from the **DSP** (fixable in software) or
> from the **converters** (a hardware ceiling)?

**The DSP is clean.** Measured by recording real audio from inside `scsynth`, so the
signal never touches a converter:

| bus | | rms | floor | A-weighted |
|---|---|---|---|---|
| 12 | voices arriving from the ADC | −93.2 | −93.9 | −92.8 |
| 50 | after `pingpongDelay_0` | −104.2 | −104.9 | −103.0 |
| 62 | after `et_blackhole_2` | −108.7 | −109.6 | −107.5 |
| **0** | **main output** | **−112.1** | **−112.9** | **−111.0** |

The delay *attenuates* by 11 dB. The reverb adds **+0.44 dB**. The loudest thing in
the idle spectrum is −120 dBFS. **The effects are not making the noise.**

The loudest component is at exactly **375.0 Hz**, which is `48000 / 128` — the block
rate, leaking in at −124 dBFS. Earlier in this project that was measured at 376.8 Hz
and written down as a hypothesis. It is confirmed, and it is inaudible.

### The analog output, measured — and the makeup gain is NOT worth it

Moog One main outs into a Komplete Audio 6, recorded on the Mac. This is the half the
digital measurement could not see: the DAC, the output stage and the cable.

```
analog floor at rest              -94.6 dBFS   (interface reference)
peak at MIDI volume 64            -18.5 dBFS   ->  SNR  76 dB
peak at MIDI volume 100            +0.1 dBFS   ->  SNR  95 dB
```

**About 95 dB of analog SNR at full output.** That is a respectable number, and it
does not describe an instrument with a noise defect.

The loudest component in the analog floor is **374.7 Hz** — the block rate again,
which measured -124 dBFS inside the DSP and is the largest single line out here.
Second is 59.7 Hz, mains.

**The makeup gain does not earn its place.** Driving the converter 12 dB harder
raised the analog floor by 6.7 dB, not 0:

    a 12 dB boost lifting the floor 6.7 dB means the noise added AFTER the gain
    stage is only +4.8 dB relative to the noise that travels WITH the signal

So the best it could ever buy is 5.3 dB, the measured signal rise was 9.1 dB, and
the net was **+2.44 dB against a trial-to-trial scatter of 2.5-3.5 dB**. The effect
is inside the measurement noise. `moogone.makeup` stays in the tree because the
headroom finding is real and the tool is how it was measured — but on this
instrument, at this preset, it is not a fix worth applying.

### The gain staging, for the record



At maximum MIDI volume, eight notes at velocity 127 — as loud as the instrument goes:

```
voices arriving (bus 12)   peak  -7.4 dBFS   floor  -93.9   SNR 86.5 dB
main output    (bus 0)     peak -20.6 dBFS   floor -112.9   SNR 92.4 dB
```

The input is staged well. The output drives the converter **20.6 dB below full
scale**, which puts the DAC's analog noise that much closer to the music.

`moogone.makeup` inserts a gain stage at the tail of the root group to recover it —
`ReplaceOut` so it replaces rather than mixes, with a limiter after the gain so no
setting can clip the converter. **Verified on the instrument: +12.16 dB rms, and
removing it restored the original level exactly.**

What that buys is a hotter DAC and then the same amount off your volume knob — which
is that much less output-side noise at the same listening level. It does **not** fix
the −93.9 dBFS floor arriving from the analog voice path; raising the output lifts
that with everything else. Which end dominates is not yet known, and answering it
means recording the analog outputs, which nothing here does.

**Caveat worth its own line:** all of this is one preset. Whether another patch drives
the output harder has not been tested.

## The original question, as first written

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

**On an iPad:** open the URL, then Share → Add to Home Screen. It carries a web app
manifest and the iOS meta tags, so it runs full-screen with no browser furniture. The
bridge stays on the Mac — it needs SSH to the instrument and an SC client, neither of
which belongs on a tablet.


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

Panels: **FX** (every effect node, live, with A/B), **Expression** (MPE / poly-AT in, a
voice grid, the go/no-go), **Patch** (route anything to anything, with curves and slew),
**Surface** (an XY pad and two rotaries), **Vector** (four corner snapshots, a 3D landscape
you can orbit, and a recordable motion envelope on a free or tempo-locked clock),
**Patcher** (a node canvas that becomes a SynthDef), and **Ask AI**.

### The patcher

SuperCollider is installed on the Mac now, so the generated source is compiled by a
real `sclang` in the test suite (`tests/vox/test_patch_compiles.py`) rather than only
compared against what we meant to write. Those tests skip, with a reason, where
`sclang` is absent.

Drag UGens from the palette, wire them, and Vox generates SuperCollider. The graph is
validated before a line is written — unconnected required inputs, feedback loops, rate
mismatches, two cables into one input — each reported with the node and port it concerns,
so a patch fails here rather than on a server.

**Run on the Moog** compiles the graph with a real `sclang`, sends it over `/d_recv`
and starts it at the tail of the instrument's root group. **Free** takes it back out.
So a patch goes from a canvas in a browser to audio in the room with nothing pasted
anywhere.

`Out` *adds* to a bus, so a patch ending in `Out` layers over the instrument; read
`In` and write `ReplaceOut` to make an insert instead. Both work; neither is imposed.

**The main outputs are buses 0 and 7**, not 0 and 1, and `Out` writes *consecutive*
buses — so a stereo signal into `Out bus 0` sends its right channel somewhere that
never leaves the instrument. Use two `Out` nodes. The panel says so above the source.

Historical note: this emitted **source, not compiled bytes**. `/d_recv` takes a compiled SynthDef, and there is
no SuperCollider on the Mac to check an encoder's output against; an unverifiable binary
encoder is the exact failure mode this project keeps documenting. Read the source, paste it
into SuperCollider, or send it to the instrument's own `sclang`. A binary backend can slot
in behind the same graph once there is a reference compiler to test it against.

### Library — browse and compare the instrument's own presets

Copy a user space off the instrument and put it in `captures/`:

```sh
scp -O root@<ip>:/var/las-frontend/MOOG\ ONE.db captures/
```

Library tab. **398 presets**, searchable by name, comment or tag; click one for its
parameter count and the handful of values that describe a sound; shift-click a second
to diff them.

Each preset is a flat list of `/p/...` paths — three thousand or so of them, which is
the `/p` namespace an earlier sweep found and could not read. A raw diff runs to
thousands of lines of sequencer steps and effect state, so the comparison shows only
timbre 1's panel controls; the total is reported beside it.

Opened **immutable**, not merely read-only: the file may be a copy of one the
instrument still has open, and sqlite must not write a journal beside it. And the
library is opened per request rather than cached, because a sqlite connection may only
be used on the thread that made it and the bridge dispatches on a pool.

Nothing here writes to a preset, and `captures/` is gitignored.

### Sampler — your audio, inside the instrument, played by its keys

Sampler tab. Give it a path to a stereo WAV; the file is copied to the instrument and
read into a buffer **there**. Press Start live and the instrument's own keyboard
triggers it — the voice controller announces every note on port 7772 whatever the
source, so this responds to your keys exactly as it responds to MIDI. Nothing is
plugged in, and the samples come out the Moog's own jacks through its own effects.

**Two ways to trigger it, and they are not equivalent.**

- *From the Moog's keys* watches the instrument's own performance port, so its keyboard
  plays your samples with nothing plugged in. **Measured at +373 ms with a 767 ms
  spread** — the note travels keyboard, voice controller, port 7772, a `tcpdump`, an
  SSH pipe and back, and none of that is scheduled. Fine for pads and drones. Not
  playable in time, and the panel says so.
- *From MIDI in* triggers from MIDI arriving at this machine, which skips the capture
  entirely and is the only tight path. Needs `--midi-in`. The instrument still sounds,
  because the same notes reach it over its own MIDI input.

**Drop files onto the page** — they travel over the websocket rather than by path,
because this page also runs on an iPad, which has no path to hand over. The name and
the first four bytes are both checked before anything is written: a traversal name, a
non-audio extension, an empty file and something that merely claims to be a WAV are
each refused with a reason.

**Voices are round-robin.** Repeating a key layers a second copy over the first the
way a hardware sampler does, up to `voices_per_note` (4 by default), and only then
takes the oldest. Measured on the instrument: five strikes 250 ms apart into a 2.5 s
bell peaked at four simultaneous voices, back to baseline once they ended.

One sample spreads across the keyboard, transposed from its root note. Click a key
then a sample to assign that key individually, so a drum map and a pitched instrument
can share one keyboard.

Two details that are not obvious and were both learned the hard way:

- **The main outputs are buses 0 and 7**, not 0 and 1, and `Out.ar` writes
  *consecutive* buses — so the voice makes two separate writes. A single stereo
  `Out.ar(0, ...)` measures as a perfectly balanced pair and *sounds* like a dead
  speaker on one side.
- **Note-off does not stop a sample.** `doneAction: 2` ends a voice when its buffer
  runs out; cutting it when a key lifts would clip every percussion sample and every
  tail. Retriggering the same key does free its previous voice, so a repeated note
  layers nothing.

A note plays the instrument's own voice *and* the sample — this layers rather than
replaces. Turning the analog voice down is a job for the panel.

### Panel — the instrument's own screens, mirrored

```sh
uv run vox --sc-host 192.168.1.138 --panel 192.168.1.138
```

**The main display**, 832x480, live. It is not on the panel bus at all:
`las-frontend` runs with `--host-oleds=203.0.113.2`, so the small screens go over
the network while the big one is an X server drawing into `/dev/fb0` on the
instrument's own Linux. Which means it can simply be read. A frame is 1.6 MB raw
and about 28 KB gzipped, so the capture pipes `dd` through `gzip` on the device and
this end slices frames out of one continuous stream — one SSH session for the feed,
not one per frame. Measured at ~1.8 fps and 25 KB a frame; conversion and PNG
encoding cost about 3 ms, so the pipe is the limit, not the CPU.

**The OLEDs** come over the panel bus as 64x16 tiles to `/od/{0,1}/l8m`. Their
arrangement is **not settled**: the 192x96 model here was derived from a capture
taken while the panel was in screen saver — two blocks bouncing and nothing else
drawing — and the instrument actually has three small screens and a large one,
which that model does not describe. `recon/knob.py --screens-only` reports what the
displays really send while you touch the panel.

#### The old note


```sh
uv run vox --sc-host 192.168.1.138 --panel 192.168.1.138
```

Not a rendering of the panel: the actual screens. The Moog One redraws them by
sending 64x16 tiles to `/od/{0,1}/l8m`, and this reassembles both **192x96**
displays from that traffic. It also lights a keyboard from the notes the voice
controller reports on port 7772 — so it shows what the instrument is playing
whatever the source, its own keys included, not just what Vox sent.

One SSH capture serves both, because they share a bus. Frames go out on a timer as
PNGs rather than per tile: the displays emit ~135 tiles a second each, and the
picture changes far less often than that. Measured at ~8 fps and about 130 bytes a
frame — a mostly-dark 192x96 screen compresses to very little.

If the screens look like two drifting blocks, that is the instrument's screen saver.
Touch any knob.

### Pick a control instead of describing one

The Panel tab lists **127 physical controls** — three oscillators, four LFOs, three
envelopes, both filters, the mixer — read from the instrument's own `/p` namespace
rather than from a manual. Type to filter; click one and it arms a learn pass with
that name already filled in.

Every path in the catalogue is checked against `tests/fixtures/panel-paths.txt`,
which was read off the instrument, one test per control. Curating a list by hand is
exactly where a plausible control that does not exist gets invented.

### Panel hotspots — the instrument names its own knobs

```sh
uv run python3 recon/hotspots.py src/moogone/vox/static/moog_one_01_3.webp
```

Finds the knobs in the photo and writes `hotspots.json`. Detection is deliberately
dull: bright, colourless, roughly circular blobs inside the dark control surface.
Knob caps are light grey, the panel is black, LEDs are coloured, and the white page is
outside the surface — those four facts are the whole method. It found **108**, and
every one of their centres lands on a bright grey pixel when checked against the
photo's own data.

**It does not guess what any of them do.** A map of a photograph would look
authoritative and be wrong in places nobody would check. Instead, click a hotspot,
name it, and turn that knob on the instrument: the parameter that moves gets the name,
via the same Learn pass the Panel tab uses. Bound spots turn green and say what they
are on hover. Saved to `presets/hotspots.json`.

Both files are gitignored — they are derived from a photo this repo does not ship.

### The panel photo (optional)

Drop a top-down photo at `src/moogone/vox/static/panel.jpg` and the live display is
positioned into it where the real screen sits; click the screen to zoom it up, click
again to go back. Without a photo the display simply shows on its own — both states
are deliberate. The file is gitignored: panel photography is Moog's.

The inset position is CSS custom properties (`--sx`, `--sy`, `--sw`, `--sh`) on
`.screen-inset`, so a differently cropped photo is four numbers to nudge.

### Can the panel LEDs be driven? No — and that settles the write question

```sh
uv run python3 recon/blink.py
```

`las-frontend` paints the panel by sending blobs to port 9100. `/lsleds` is the big
field, 184 bytes, refreshed only a couple of times a second — slow enough that an
injected frame could hold long enough to see. This alternates all-on and all-off and
counts you in.

**Answered: nothing lights up.** The frames are confirmed to arrive — captured on
the wire with a distinctive `0xAB` fill — and a hundred alternating frames over six
seconds produced no visible change. The panel ignores LED frames that are not
`las-frontend`'s.

That closes the write question. Notes to 7772, parameters to 7770 and LEDs to 9100
were each confirmed delivered and each did nothing. And it is **not** the source
port: `las-frontend` sends its own LED frames from five different ephemeral ports.
The likely gate is the startup cookie its argv (`--cookie=1`) and log
(`Writing startup cookie`) refer to — a hypothesis, not a result, and testing it
means capturing a boot.

### Learn — the instrument names its own parameters

The voice engine addresses parameters by 16-bit id, and nothing on the machine
publishes what those ids mean. But every change is announced on the voice bus as
`/x`, so **moving a control tells you its id**. Panel tab, Learn card: type what you
are about to move, press Learn, move it, press Done.

Saved to `presets/params.json`, which starts with the one id confirmed against a
known control — `358`, master volume, driven by MIDI CC 7.

The hard part is that a control is never the only thing moving: a note tail or an
LFO will emit a few writes during the same window. So a pass does not take "the
parameter that appeared". It ranks candidates by span times count — a sweep beats a
single jump — requires the winner to beat the runner-up by 2x, and **refuses rather
than guessing**, naming both parameters when two move together.

Nothing is written to the instrument. This reads the bus the instrument is already
talking on.

### Presets — snapshot the whole effects chain and switch

```sh
uv run python3 -m moogone.vox.presets list
uv run python3 -m moogone.vox.presets save "as found" --note "before I touch anything"
uv run python3 -m moogone.vox.presets apply "as found"
uv run python3 -m moogone.vox.presets show "as found"
```

So an experiment need not be destructive: capture what the instrument is doing, try
something, come back. It does not touch the synth's own preset system — this is the
SuperCollider effects layer only.

**Snapshots are keyed by `(defname, nth of that defname)`, never by node id.** The
engine reallocates ids whenever a preset is loaded on the front panel; a chain that
was `1035 pingpongDelay_0` became `1055 stereoChorus_0` mid-session here, and an
id-keyed snapshot would have written a delay's settings into a chorus. Applying one
to a chain it does not fit reports what it could not match instead of writing the
half that happens to line up.

Routing controls — `inBus`, `outBus`, `ctlIn`, `ctlOut`, `ctl` — are captured by
neither `save` nor `apply`. A snapshot restores settings, not wiring. And because
`/n_set` is never acknowledged, `apply` reads the tree back rather than assuming.

### Ask AI

Providers are the local agent CLIs already logged in on your machine — no API keys, and
nothing here reads or prints a credential. The model returns a *proposal*, re-validated
against the live node tree (unknown nodes dropped, read-only refused, values clamped to
each control's range) and re-validated again on apply. Model output is data describing a
patch, never an instruction.

### Morning checklist — what turns badges from untested to live

Nothing below was possible with the synth off. Do them in order; each is one experiment.

1. **Cable.** Komplete Audio 6 DIN out → Moog DIN in. `uv run vox --midi-out "Komplete"`,
   Expression → "Send test chord". You should hear C-E-G. If not, MIDI out from the Mac is
   dead and the `amidi`-over-SSH fallback is the path.
2. **Meters live.** `uv run vox --live-meters --device 192.168.1.138`. The strip should
   move with the synth's output. Note the real update rate; the spec guessed and was told
   not to.
3. **MIDI — done, 2026-09-03.** Komplete Audio 6 MK2 DIN out → Moog DIN in.
   A chord sent through Vox raised the instrument's own meters **+18.2 dB** against
   silence, and the notes came back decoded off the performance port as the exact
   numbers sent. `MidiNote` is now `live`. `MidiCC` is **not**: CC1, CC74 and both
   flavours of aftertouch swept with no measurable effect and no performance-port
   traffic, so that badge stays `untested` with the reason written into it.

4. **Meters — done, 2026-09-03.** `live` now. Rate measured rather than guessed:
   **0.17 Hz**, one frame per ~5.8 s. Of a 4.5 s read only 0.37 s is SSH; the rest is
   four sequential one-second listens. Running them concurrently is 2.9× faster and
   returns nothing parseable, because the replies interleave. A level indicator,
   honestly — not a VU meter. **One reader at a time**: a second concurrent reader
   steals replies and both get partial results.

5. **MIDI, re-checked at any time.** `uv run python3 recon/midi-probe.py` plays a chord and
   sweeps mod wheel, brightness, pitch bend, channel aftertouch and poly aftertouch
   while capturing both internal buses. Loopback is silent at idle, so anything it
   records was caused by the probe. If nothing appears on either bus it says the MIDI
   did not arrive rather than presenting an empty capture as a result — which is what
   it reported on its first run, correctly.
6. **The effects, for real.** `uv run vox --sc-host 192.168.1.138`. FX panel, move
   `pingpongDelay_0 → mix`. The chip should go *sent* → *confirmed* and you should hear it.
   This is the one path already verified; it should just work.
7. **The go/no-go.** Hold a chord on the synth. Expression → "Run go/no-go". It will show
   you the blocked reason: the per-voice write address is in the 464 unmapped `/p` entries.
   The way to find it is `tcpdump -i usbint` on the box while `las-sc` boots the cards, or
   while moving any per-voice control the panel exposes. That capture is the next project.
8. **Raw OSC.** Patch → route `meter.mainl` to `osc.lc.kbd.oct`. If the synth's octave
   changes, `las-sc` writes work and that badge flips. If not, the session's six-silent-
   writes result is now reproducible.
