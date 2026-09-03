# Moog One internals

Field notes from a Moog One running firmware **v1.8.2**, mapped over SSH on a
private network in September 2026.

Everything here was read back from a running instrument. Where something is
inferred rather than observed, it says so. Where an earlier conclusion turned
out to be wrong, that is recorded too — the wrong turns are load-bearing, because
several of them produced confident, well-formatted, entirely false results.

---

## Scope and cautions

This documents an instrument its owner owns, on their own network, for
interoperability. It does not describe defeating firmware signing, and it
reproduces none of Moog's copyrighted code, firmware images, or preset data.

**This voids your warranty and can brick your synthesiser.** Specifically:

- `/var/cal/vxcal.db` and `/var/tuning.vxtune` are the **only copy** of your
  instrument's analog calibration. There are 48 oscillator tuning tables in
  there — 16 voices × 3 oscillators — plus 16 voice-level files. Restoring a
  backup only helps if the failure mode is "file corrupted". It does not help if
  a card has been driven out of calibration.
- `/etc/init.d/S42sc` has an **asymmetric stop/start**: `stop()` kills `sclang`,
  `jackd`, `scsynth` and `las-sc`, but `start()` relaunches only `las-sc`. Run
  `S42sc restart` and you get a running control layer with no audio engine
  behind it. The instrument looks alive and makes no sound.
- Killing `las-frontend` takes the screen and panel with it.

### `--help` is not safe on this device

Several `/usr/bin` entries are **bash scripts that ignore their arguments and simply run**.
Passing `--help` does not print usage — it executes them. Learned the hard way:

| Script | What passing `--help` actually did |
|---|---|
| `open_ladder` | Cycled the XMOS network, then began **flashing oscillator VCA calibration** |
| `start_tune` | Began an **initial tune and vx calibration** pass |
| `detect-held-buttons` | Entered an infinite polling loop |
| `las-watchdog` | Entered a continuous voice-controller ping loop |

`open_ladder` reset the XMOS and left `/v/voices` reporting **`-1`** instead of `16` — the
controller came back but never re-enumerated its cards. Restarting `las-sc` with identical
argv did *not* fix it; the recovery is the boot path (`config-las-spi xmos`, which
`S25xmosfw` runs) or a power cycle.

The calibration files survived only because the calibration pass aborted with "Unable to
determine voice count" before writing anything. That was luck, not care.

**Check what a tool is before you run it:**

```sh
file $(which TOOL)
head -40 $(which TOOL)
```

A compiled binary with a real argument parser (`vxtune`, `vxreport`, `lassvc`, `vxping`) is
safe to query. A `#!/bin/bash` script is not.

Back up before you write anything. Read freely — but read the script first.

---

## 1. Hardware

```
SoC          Freescale i.MX6 Quad/DualLite, 2 × ARMv7 rev 10 (Cortex-A9)
Module       Variscite i.MX6 DL/Solo SOM on a Moog carrier board
             device-tree model: "SOM-SOLO SOM-DUAL SoloCustomBoard"
             compatible:        fsl,imx6q-var-som
Kernel       Linux 4.1.15-rt18 #1 SMP PREEMPT RT  armv7l   (built 2022-05-16)
Distro       Buildroot 2016.02-rc2
             /etc/issue: "L:A:S Production Image  (c)2017 Moog Music Inc."
RAM          507,956 kB total  (~508 MB)
Swap         none
Hostname     las-production
Voice cards  16, XMOS, individually addressable
```

The compute module is a **commercially available Variscite SOM**, not a Moog design — so
the i.MX6 side is documented publicly by Variscite. Only the carrier board is custom.

**There is no FPGA.** No Xilinx, no Altera, no Lattice, no bitstream anywhere on the
filesystem. The signal path is i.MX6 → ESAI → XMOS → analog. `dmesg` confirms the audio
link:

```
imx-xmos-esai sound-xmos-esai: xmos-codec <-> 2024000.esai mapping ok
```

The `PREEMPT_RT` kernel is the giveaway that this is a real-time audio box, not a
general-purpose Linux appliance that happens to make noise.

`exFAT` is **not** supported — it was mainlined in Linux 5.7 and this is 4.1.15.
A USB stick formatted exFAT is invisible to the instrument. Use FAT32/MBR.

---

## 2. It is two computers

This is the single most important structural fact, and it is not obvious from
outside the case.

```
    ┌──────────────────────────────────────────┐
    │  i.MX6 / Linux            203.0.113.1    │
    │                                          │
    │   las-frontend  ──9500──▶  las-sc        │
    │   (JUCE app,               (voice        │
    │    panel + screen)          controller)  │
    │        │                       │         │
    │        │                       │         │
    │   sclang ──57110──▶ scsynth    │         │
    │   (57120)           (FX engine)│         │
    └────────────────────────────────┼─────────┘
                                     │ usbint
                                     │ USB network
                            ┌────────▼─────────┐
                            │  203.0.113.2     │
                            │  "vc"            │
                            │                  │
                            │  voice-card      │
                            │  processor       │
                            │      :7770       │
                            │        │         │
                            │   16 × XMOS      │
                            │   voice cards    │
                            └──────────────────┘
```

The two halves talk over a **USB network interface** (`usbint`) using private
addresses in the `203.0.113.0/24` block. Confirmed in `/proc/net/udp`:

```
017100CB:8E1E  →  027100CB:1E5A
```

Byte-reversed hex: `203.0.113.1:36382` → `203.0.113.2:7770`.

### Firmware images

| Image | Version | Runs on |
|---|---|---|
| `app_las_v2.1.2.bin` | v2.1.2 | the voice **controller** (`lasvc`) |
| `app_vx_10M_v2.1.0.bin` | v2.1.0 | each **voice card** (`vx`) |

Both versions are readable at runtime — see §5.

---

## 2a. How the XMOS is booted

Both firmware images live in `/usr/share/xmosfw/` and are pushed to the hardware **over
SPI** at boot. Three pieces do it.

**`/etc/init.d/S25xmosfw`** runs one command: `config-las-spi xmos`.

**`/usr/bin/config-las-spi`** is a shell script that rewrites i.MX6 IOMUXC registers with
`devmem` so the SPI1 pins become GPIO inputs and *the XMOS owns the bus*, then pulses the
reset line. It has a `som` mode that does the inverse — returns the pins to the SOM and
holds the XMOS in reset.

The reset line is exposed to userspace as a **Linux LED device**:

```sh
echo 0 > /sys/class/leds/XMOS_RESET_N/brightness   # hold in reset
echo 1 > /sys/class/leds/XMOS_RESET_N/brightness   # release
```

`/sys/class/leds/` also carries `LCD0 ON!OFF`, `LCD1 ON!OFF`, and the two MMC activity LEDs.

**`las-sc` loads the firmware.** Its full argv on a running instrument:

```
las-sc -t vc -f localhost:7775 -l localhost:9300
       --vxfw=/usr/share/xmosfw/app_vx_10M_v2.1.0.bin
       --vxdb=/var/tuning.vxtune
       --vcfw=/usr/share/xmosfw/app_las_v2.1.2.bin
       --vcfv=33620735
       --temp
       --expr-syms=/usr/share/vx_ee.scm
       --panel-state=localhost:9500 -q
```

So `las-sc` is not merely a controller — it is the thing that flashes and boots both the
voice-card firmware and the controller firmware, feeds in the tuning database, and loads
the expression-engine symbol table. `--vcfv=33620735` is the expected firmware version
(`0x020102FF`), matching `/usr/share/xmosfw/VERSIOND` and `/info/versionb` exactly.

`las_layout` declares the flash map: `00000000:0x001BFFFF firmware` — 1.75 MiB of the
2 MiB controller image.

### The voice-bus network, in four lines

`/etc/udev/rules.d/20-xmos-nic.rules` fires when a NIC with MAC `02:00:00:00:00:00`
appears, and runs `usb-int.sh`:

```sh
ifdown -f $1
ip link set $1 name usbint
ifup -f usbint
arp -i usbint -s 203.0.113.2 02:00:00:00:00:00
```

That is the whole thing. The XMOS enumerates as a USB network interface, gets renamed to
`usbint`, and the voice controller is pinned with a **static ARP entry**. No DHCP, no
discovery — the address is hard-wired on both ends.

---

## 3. Process topology and ports

```
las-frontend ──9500──▶ las-sc ──7770 (UDP ×4)──▶ voice cards (203.0.113.2)
                          ▲
                          └── replies to las-frontend on 7775

sclang (57120) ──57110──▶ scsynth        ← the SuperCollider effects engine
```

Decoded from `/proc/net/udp` (all values are byte-reversed hex):

| Hex | Port | What |
|---|---|---|
| `251C` | 9500 | `las-frontend` → `las-sc` (panel state) |
| `1E5A` | 7770 | the voice-card bus |
| `1E57` | 7775 | `las-sc` → `las-frontend` replies |
| — | 9100 | **the panel**, per `lassvc`'s default `--panel-target` |
| `DF16` | 57110 | **scsynth** — the SuperCollider server |
| `DF20` | 57120 | **sclang** |

Port **9100** comes from `lassvc --help`, whose defaults are `las.local:7770` for the voice
controller and `las.local:9100` for the panel. Note `las.local` — the instrument advertises
itself over **mDNS/avahi**, so it is reachable by name, not just by address.

`las-frontend`'s argv is equally informative:

```
las-frontend --usb-path=/media/thumbdrive --data-path=/var/las-frontend
             --host-paneloutput=203.0.113.2  --host-performance=vc
             --host-oleds=203.0.113.2        --host-systemclock=vc
             --host-vc=vc  --affinity-mask=1 --affinity-panel=1 --cookie=1
```

`--host-oleds=203.0.113.2` is the interesting one: **the per-button OLED displays are
network-addressed** on the voice-card processor, the same box that runs the voice cards.
The panel, the OLEDs, the performance controls and the system clock are all endpoints on
that second computer.

`ss` is absent and busybox `netstat` rejects `-p`. Read `/proc/net/udp` and
`/proc/net/tcp` directly; the addresses are little-endian hex, so `0100007F:2454`
is `127.0.0.1:9300`.

### A correction worth inheriting

Public writeups describe "the sound engine `las-sc` on `localhost:9300`". That
conflates two different things:

- **`las-sc` is not SuperCollider.** It is the voice-card controller. It speaks a
  Moog-specific OSC dialect, not the SuperCollider server protocol.
- **`scsynth` on 57110** is the SuperCollider server, and it is where the digital
  effects actually run.

An entire toolkit was built against port 9300 on the strength of that writeup
before the socket table was read. Read `/proc/net/udp` first.

### `avg_cpu` reads 0.0 — and that means nothing

`scsynth`'s `/status.reply` reports `avg_cpu = 0.0` on this build. That is **not**
evidence that it is idle. It holds `/dev/snd/pcmC0D0p` and `/dev/snd/pcmC0D0c`
open and is processing audio; CPU metering is simply unimplemented here.

---

## 4. The SuperCollider effects engine

`scsynth` on **57110** speaks the standard SuperCollider server protocol. The
usual commands work: `/status`, `/g_queryTree`, `/n_set`, `/sync`, `/d_recv`,
`/dumpOSC`.

`/n_query` is **not implemented** on this firmware. It answers nothing. Any tool
that guards `/n_set` behind an `/n_query` node-type check will hang or refuse.
Use `/g_queryTree` to inspect the graph instead.

`/n_set` is fire-and-forget — SuperCollider never acknowledges a control write,
by design. `/g_queryTree` is the only confirmation that a value took.

### What the FX noise investigation actually found

The premise was a documented gain-staging/noise defect. Measured on hardware, the
effects path contributed **−0.01 dB** to the noise floor. The premise did not
survive contact.

A separate, real artifact was found: a **376.8 Hz tone**, present with effects on *and*
off. Muting all routed effects at once made it much quieter, and `StereoDelay` was the
largest single contributor — but no effect parameter eliminated it, and disabling delay
feedback did not behave the way a feedback path would.

**The scsynth command line explains it.** Read off the running process:

```
scsynth -u 57110 -a 129 -i 9 -b 1026 -z 128 -Z 128 -m 100000 -w 128 -S 48000 -R 0 -C 0 -l 1
```

`-S 48000` and `-z 128` — 48 kHz at a 128-sample block.

```
48000 / 128 = 375.0 Hz
```

The measured tone was 376.8 Hz, **0.5 % away**. That is the audio block rate, and it now
has a mechanism grounded in the engine's actual configuration rather than a guess.

Stated carefully, because an earlier pass in this project got burned by loose tolerance
matching: this is a **strongly supported hypothesis, not a confirmed result**. Confirming it
means restarting `scsynth` with a different `-z` and checking the tone moves with the block
rate. That test has not been run.

Two wrong turns from that hunt, preserved because both produced confident output:

- A comb-resonance theory predicted that `feedback=0` would silence the tone and
  that delay time would shift its pitch. Neither happened.
- Spectral peaks were labelled as harmonics using a 0.8 % matching tolerance,
  which at 19 kHz is ±152 Hz — wide enough that nearly anything matched. Those
  labels were retracted.

---

## 5. The voice-card bus

`203.0.113.2:7770`, reachable only from the instrument itself.

### Two processors answer

| Address form | `/info/product` | `/info/version` | What |
|---|---|---|---|
| bare — `/info/product` | `lasvc` | `v2.1.2` | the voice **controller** board |
| `/vx/<0-15>/…` | `vx` | `v2.1.0` | one individual **voice card** |

`/info/versionb` returns the same version packed as hex: `33620735` =
`0x020102FF` → 2.1.2. The voice card returns `33620223` = `0x020100FF` → 2.1.0.

Other confirmed reads:

```
/v/voices              i:16
/vx/<n>/info/hwrev     i:9
/a/stat/mainl          f f     main L, two floats
/a/stat/mainr          f f     main R
/a/stat/send1          f f     FX send 1
/a/stat/send2          f f     FX send 2
```

### The output meters

`/a/stat/{mainl,mainr,send1,send2}` are **live level meters**, readable over the
network while the instrument plays. Each returns **two floats** — minimum and
maximum sample excursion over the measurement window, i.e. a peak meter, not an
average.

On an idle instrument they read **−90 to −118 dBFS**, and they vary between
consecutive reads. They are controller-scoped: `/vx/0/a/stat/mainl` returns 404.

This is four channels of real-time output telemetry with no cable attached.

### Absent on this firmware

`/info`, `/info/fwrev`, `/info/vc-version`, `/info/vc-git`, `/info/voice-count`,
`/stat`, `/status`, `/statr`, `/stat/decay`, `/fw/version`, `/fx/hw-rev` all
return 404 — the strings exist in the binary but the handlers do not.

There are **no container queries**: `/info` 404s while `/info/product` answers.
Every address is a leaf.

---

## 6. How to query the bus safely

### The wrong way, and why it looks right

`vxping` is the tool Moog ships. It is **not a ping** — it sends a blob of random
bytes and expects the same blob echoed. An address holding a real value answers
with the value instead, which `vxping` reports as a *mismatch*:

```
expected /vx/0/info/hwrev b:#${...}
got      /vx/0/info/hwrev i:9        ← the answer
```

So `failed 1` means "this address gave me a real value". Confusing, but usable.

Three traps, each of which silently produces "every address is silent":

1. **`vxping` never exits.** `-r` is a *rate in Hz*, not a count. There is no
   `timeout(1)`, no python, and no perl on the device.
2. **Job control does not work.** Bounding it with `%1` inside a command
   substitution discards the output entirely.
3. **Piping into a parser loses the reply** when the process is killed.

The bounded form that works:

```sh
vxping -r 20 -l 0 -a "$ADDR" vc:7770 > /tmp/out 2>&1 &
P=$!; sleep 1; kill $P; wait $P 2>/dev/null
grep "^got $ADDR " /tmp/out
```

A first sweep of 37 addresses using `%1` reported all 37 silent — including two
that were already known to answer. **Validate any sweep against a known-good and
a known-bad address before believing a single result.**

### The safer way: zero-argument queries

`vxping` sends a blob. Whether a blob arriving at a *setter* is inert is
**unproven**, and the most interesting addresses (`/hw/mute`, `/seq/dest/port`,
`/testosc/freq`) are plausibly writable.

A zero-argument OSC message carries no value a setter could store, and it works:

```
/info/product  ,\0\0\0   →   28 bytes:  /info/product  s:lasvc
```

The netcat on the device is **GNU netcat 0.7.1**, not busybox nc:

```sh
printf '\x2f\x69\x6e\x66\x6f\x2f\x70\x72\x6f\x64\x75\x63\x74\x00\x00\x00\x2c\x00\x00\x00' \
  | nc -u -w 1 203.0.113.2 7770 > /tmp/r.bin 2>/dev/null &
P=$!; sleep 1; kill $P 2>/dev/null; wait $P 2>/dev/null
od -An -tx1 < /tmp/r.bin | tr -d ' \n'
```

**Do not pass `-c`.** It closes the connection on EOF from stdin, and `printf`
reaches EOF immediately, so netcat tears the socket down before the reply
arrives. Measured:

| Command | Reply |
|---|---|
| `nc -u` | 28 bytes |
| `nc -u -w 1` | 28 bytes |
| `nc -u -w 2` | 28 bytes |
| `nc -u -c` | **0 bytes** |
| `nc -u -c -w 1` | **0 bytes** |

Zero bytes is indistinguishable from "this address does not exist". This one flag
is the difference between a working map and 300 confident false negatives.

There is no `base64` on the device, which is why packets are shipped as
`printf '\xNN'` escapes.

### Reply forms — there are five, not two

| Reply | Kind | Meaning |
|---|---|---|
| address + arguments | `value` | real data came back |
| address, **no arguments** | `ack` | the handler exists but returned nothing |
| `s:503 s:"Unavailable"` | `unavailable` | exists, but will not answer *this form* of request |
| `s:404 s:"Not found"` | `not_found` | absent on this firmware |
| nothing at all | `silent` | **not proof of absence** — the bus drops replies |

Both status replies arrive as **two strings**, not int + string. Compare textually.

**`ack` is the common case and the easy mistake.** Sweeping all 303
controller-scoped addresses:

| Kind | Count |
|---|---:|
| `value` — returned data | **7** |
| `ack` — exists, no arguments | 113 |
| `unavailable` — 503 | 1 |
| `not_found` — 404 | 182 |
| `silent` | 0 |

121 addresses exist. **Seven** of them return anything.

That is the headline result, and it is easy to get backwards: **a zero-argument
query is an existence probe, not a reader.** The controller's OSC surface is
overwhelmingly *write*-oriented — you set things through it, you do not read them
back. The complete set of true getters is:

```
/a/stat/mainl      f f     main L, min/max
/a/stat/mainr      f f     main R
/a/stat/send1      f f     FX send 1
/a/stat/send2      f f     FX send 2
/info/product      s       "lasvc"
/info/version      s       "v2.1.2"
/info/versionb     i       33620735  (0x020102FF)
```

Everything else that exists acknowledges and tells you nothing. Rendering that
empty answer as a "value" makes a bare acknowledgement look like a measurement —
which is how an earlier pass here reported "121 values" when it had seven.

Keeping `silent` distinct from `404` is the other half. Collapsing them is how the
first sweep produced 37 uniformly wrong answers.

### The two query forms are not equivalent

`/vx/0/info/hwrev` answers `i:9` to a `vxping` **blob** query, and
`s:503 s:"Unavailable"` to a **zero-argument** query. Per-card paths appear to
require the blob form.

So the two tools are complementary, not redundant:

- **zero-argument** — safe against setters, works for controller-scoped addresses
- **blob (`vxping`)** — reads per-card `/vx/<n>/…` values, but carries a payload
  whose effect on a setter is unproven

---

## 7. The address space

**767 OSC addresses** were extracted from the device binaries:

```sh
strings -n 3 /usr/bin/las-sc | grep '^/' | grep -E '^(/[A-Za-z0-9_-]+)+$' | sort -u
```

By family:

| Family | Count | What |
|---|---|---|
| `/p` | 464 | the synthesis parameter set |
| `/cal` | 94 | calibration |
| `/a` | 51 | voice allocation, routing, metering |
| `/mix` | 36 | mixer matrix |
| `/g` | 31 | global |
| `/in` | 23 | inputs — MIDI, CV, local control |
| `/fa` | 14 | |
| `/info` | 12 | |
| `/fx*` | 26 | effects, three slots |
| `/testosc` | 6 | built-in test oscillator |
| `/hw` | 6 | hardware |
| `/seq` | 4 | sequencer |

### The interesting ones

**Network destination for the sequencer.** Not a fixed internal link — an IP, a
MAC and a port, all addressable:

```
/seq/dest/ip
/seq/dest/mac
/seq/dest/port
/seq/direct-kbd
```

**Local control.** The switch that turns the keyboard into a pure controller:

```
/in/local/en
/in/local/note-min
/in/local/note-max
```

**CV input scaling**, fully parameterised:

```
/in/cv/0/dest      /in/cv/0/en
/in/cv/0/in-min    /in/cv/0/in-max
/in/cv/0/out-min   /in/cv/0/out-max
```

**MIDI input configuration**, including a programmable CC map:

```
/in/midi/ccmap     /in/midi/ch      /in/midi/en
/in/midi/tr        /in/midi/note-min  /in/midi/note-max
/in/com/tuning     /in/com/tr       /in/com/note-min  /in/com/note-max
```

**A signal generator inside the voice card:**

```
/testosc/freq
/testosc/dac/2
/testosc/dac/3
```

**Voice allocation policy:**

```
/a/max-voices   /a/max-stack    /a/note-steal   /a/note-limit
/a/mono         /a/mono-note-pri /a/pri         /a/rnd    /a/hold
/a/unison/en    /a/unison/max-stack  /a/unison/pitch-spread
/a/chord/en     /a/chord/ofs
```

**Output routing:**

```
/a/main   /a/main_mute   /a/vol    /a/hp   /a/hph   /a/hph_mute
/a/aux1..4   /a/in1   /a/in2   /a/subl   /a/subl-en   /a/subr-en
/a/dir1-aux1 … /a/dir4-aux4
```

**Mixer matrix** — each oscillator's contribution to Filter A and Filter B:

```
/mix/o1/fa  /mix/o1/fb    /mix/o2/fa  /mix/o2/fb    /mix/o3/fa  /mix/o3/fb
/mix/rm/fa  /mix/rm/fb    /mix/ext/ext0  /mix/ext/ext1  /mix/ext/fa  /mix/ext/fb
/mix/bal    /mix/aux-bal  /mix/g   /mix/main-en   /mix/sub-en
```

**Effects**, three slots plus a generic form:

```
/fx/bus-mode   /fx/spread   /fx/hw-rev
/fx<0|1|2>/{in,out,dry,dig-dry,g-out,pan,sends,par}
/fxn/{en,g-out,mix,pan}
```

**Keyboard and controllers:**

```
/lc/kbd/curve   /lc/kbd/oct   /lc/kbd/tr
/lc/xy/hold     /lc/xy/mode
/hw/mute        /hw/hpf
/fb/hp          /fb/tap
```

**Per-timbre output routing** — confirmed live. The Moog One has three timbres,
and each carries its own send, direct-out, pan and enable set:

```
/g/{0,1,2}/t/aux1        /g/{0,1,2}/t/aux2
/g/{0,1,2}/t/mix/g       /g/{0,1,2}/t/mix/pan
/g/{0,1,2}/t/mix/dir1-en … dir4-en
/g/{0,1,2}/t/mix/main-en /g/{0,1,2}/t/mix/sub-en
```

**Master and headphone, with independent mutes:**

```
/m/main   /m/main_mute   /m/hph   /m/hph_mute
```

**A second test oscillator**, richer than `/testosc` — it has a waveform and a
gain, which makes it a usable measurement source:

```
/cal/testosch/freq   /cal/testosch/wave   /cal/testosch/g   /cal/testosch/ch
/cal/testoscl/ch
```

**System telemetry:**

```
/therm/sys-temp      system temperature
/dbg/oscl_ctl        debug oscillator control
/mode                /ping
```

**Calibration** — read-only territory unless you have a verified backup and a
reason:

```
/cal/o1  /cal/o2  /cal/o3          oscillator trim
/cal/p1  /cal/p2  /cal/p3
/cal/biasfa  /cal/biasfb           filter bias, A and B
/cal/svf1f  /cal/svf1r  /cal/svf2f  /cal/svf2r    state-variable filters
/cal/ladf/x  /cal/ladf/x0  /cal/ladf/x1          ladder filter
/cal/ladr/{h,l,x}   /cal/gldr/{h,l,x}   /cal/gsvf/x
/cal/noisecw/{h,l,x}   /cal/noiseccw/{h,l,x}
/cal/hpf  /cal/rm  /cal/decay  /cal/extin
/cal/mainl  /cal/mainr  /cal/mainl/x  /cal/mainr/x
```

---

## 8. The performance and panel namespaces

Recovered by observation rather than guesswork — `scsynth`'s `/dumpOSC` for the
engine side, and `las-frontend --log-panel-osc` for the panel. A 30-second
capture while moving every control produced 2,801 messages across 771 addresses.

**Performance output** (what the instrument emits as you play):

```
/r/g/{0,1,2}/m/w        f      mod wheel, per timbre
/r/g/{0,1,2}/m/xyz      fff    XY pad: x, y, pressure
/r/g/{0,1,2}/l{1-4}/r   ii     the four LFOs
/mo/din0                iii    MIDI OUT to the DIN socket
/mo/usb0                iii    MIDI OUT to USB
```

`/mo/din0` and `/mo/usb0` mean the instrument can be driven as a **network-
controlled MIDI transmitter** for the rest of a rig.

**Panel input:**

```
/lb      iii            
/cenc    i              encoders
/lk      b <blob:84>    key/button matrix, 84-byte blob
/cvin    i              CV in
```

**Settings tree** (from `/g_queryTree`), e.g.:

```
/m/settings/midi_cv/cv_input/cvin_1/dest    s
```

### On the wire: what the two computers actually say to each other

The above was recovered from log files. This is `tcpdump -i usbint` on the
instrument itself — 20 seconds, **10,565 UDP packets**, the machine sitting idle
with nobody touching it. `203.0.113.1` is the i.MX6; `203.0.113.2` is the voice
and panel controller.

| Direction | Port | Msgs | What |
|---|---|---|---|
| `.1 → .2` | 9876 | 7,227 | the two OLED displays |
| `.1 → .2` | 9100 | 2,840 | panel LEDs, and per-board polls |
| `.2 → .1` | 9500 | 261 | panel input: buttons, knobs, encoders |
| `.2 → .1` | 9600 | 195 | `/cb i` |
| `.1 ↔ .2` | 7770 | 40 | `/therm/sys-temp i` — **and nothing else** |

**The displays are a framebuffer protocol on port 9876**, which no previous map
recorded at all:

```
/od/0/l8m   iiiiiib    ~135 updates/sec   1,052 arg bytes
/od/1/l8m   iiiiiib    ~135 updates/sec   1,052 arg bytes
/od/{0,1}/cp  i        page or cursor
/od/s         i        display select
```

`od` = OLED display, `l8m` = 8-bit luminance map. The two displays differ in the
first integer — `0x40` and `0x80` — which reads as an x-offset, followed by what
look like extents (`0x40`, `0x10`) and a colour or mask pair (`0xffffffff`,
`0x000000ff`) before the pixel blob. **Two-thirds of all voice-bus traffic on an
idle Moog One is redrawing its own screens.**

**Panel LEDs are blobs on 9100**, each with a big-endian length prefix:

```
/lsleds    b   184 bytes    the large panel LED field
/seqleds   b    24 bytes    sequencer row
/lfoleds   b     4 bytes    ~95/sec, the fastest LED update
/clkleds   b     4 bytes    clock
```

**Panel input arrives on 9500**, one message per board per poll, at 1.45 Hz:

```
/lb   iii          /lk    b  84 bytes     left board: buttons, then the key matrix
/cb   i            /ck    b   8 bytes     centre board
/cenc i                                   centre encoder
/rb   ii           /rk    b  66 bytes     right board
/lhcb i            /lhck  b  16 bytes     left-hand controller (wheels, ribbon)
```

The 84-byte `/lk` blob is the same key/button matrix the `las-frontend` logs
show, now confirmed on the wire and attributable to a specific board.

`/auto s i i` carries `"127.0.0.1", 9500, 2` — the registration that tells the
panel where to send what it reads.

### The finding that matters for writing to voices

**Port 7770 carried only `/therm/sys-temp` for the entire capture.** Twenty
seconds, an idle instrument, and the voice bus said nothing but its own
temperature (`0x42` = 66).

That is a real constraint on the open question of whether voice-bus *writes* do
anything. It means an idle capture cannot answer it: there is no live example of
a parameter write to imitate, because at idle the machine never sends one. The
capture has to be taken **while a control is moved or a note is played**, and
until that exists, six accepted-but-inaudible writes remain unexplained rather
than explained.

---

## 9. The modulation engine

`/usr/share/vx_ee.scm` is Moog's own documentation of the expression engine,
shipped on the device. It is their copyrighted file and is not reproduced here,
but structurally it defines:

**Sources** — a 16-element `m` array, a 128-element `c` array, a 16-element `v`
array, and `vspr` (voice spread, −1 … +1).

**Destinations** — 3 oscillators, Filter A and Filter B, two state-variable
filters, the ladder filter, 4 LFOs, 3 envelope generators, the mixer, VCA, pan,
and the effects sends.

`vspr` is the interesting one: a per-voice spread parameter in the modulation
matrix is exactly the hook a per-voice-pressure feature would need.

---

## 10. Filesystem map

| Path | What |
|---|---|
| `/usr/bin/las-sc` | voice-card controller — 799 OSC address strings |
| `/usr/bin/las-frontend` | the JUCE panel/screen app (23 CLI options) |
| `/usr/bin/vxmon`, `/usr/bin/vxping` | CHICKEN Scheme tools, built from `las/las-comm.scm` |
| `/usr/share/vx_ee.scm` | Moog's expression-engine documentation |
| `/etc/init.d/S42sc` | audio stack init — **asymmetric stop/start, see cautions** |
| `/var/las-frontend/*.db` | preset databases, ~280 MB |
| `/var/las-frontend/las-frontend.log` | JUCE log; panel OSC logging lands here |
| `/var/cal/vxcal.db` | calibration database, 241 KB |
| `/var/tuning.vxtune/` | 48 oscillator tables + 16 voice files |
| `/dev/snd/{pcmC0D0p,pcmC0D0c,seq,timer,controlC0}` | ALSA — including the sequencer |

### The tuning tables

```
v0 … v15            16 files, ~1.4 kB    per-voice
v0-o1 … v15-o3      48 files, ~56 kB     per-oscillator
vxtune-db           13 bytes
```

56 kB per oscillator is a dense lookup table, not a handful of trim values. Moog
tracks every VCO in the instrument independently.

---

## 11. What is actually installed

This is the section that changes what is possible, and it is much larger than expected.
The instrument ships a full Linux userland — roughly 700 binaries in `/usr/bin` and
`/usr/sbin`.

### OSC tools are already on the device

```
oscsend   oscdump   osclog   oscterm
```

The liblo command-line OSC tools are installed. Every `printf '\xNN' | nc` incantation in
§6 exists only because this was discovered late. **Use `oscsend` and `oscdump` instead** —
they speak OSC properly, including type tags.

### MIDI, natively

```
amidi   aplaymidi   arecordmidi   aconnect
/dev/snd/seq  present
```

The ALSA sequencer and its tools are there, so MIDI can be sent and received on the box
without any of the OSC-layer indirection.

### JACK — including network audio

```
jackd  jack_lsp  jack_connect  jack_disconnect  jack_midi_dump  jack_transport
jack_net_master   jack_net_slave   jack_netsource
```

The full JACK suite, and critically **netjack**. `jack_netsource` / `jack_net_master` /
`jack_net_slave` are JACK's network audio transport. That is a path to streaming audio
in or out of the instrument over ethernet, using software already present.

### Debugging and inspection

```
gdb   gdbserver   strace   ltrace   tcpdump   lsof   htop
apitrace  glretrace  eglretrace
```

A complete debug toolchain, including a **packet sniffer**. `tcpdump` on `usbint` would
capture the entire voice-bus conversation — the definitive way to learn the write protocol.

### Databases and storage

```
sqlite3
flashrom  kobs-ng  mkimage  mtd_debug  flash_erase  flashcp  nandwrite
ubiattach ubiformat mkfs.ubifs  mksquashfs  unsquashfs
```

`sqlite3` means the ~280 MB of preset databases in `/var/las-frontend/` can be queried
directly — the obvious foundation for a preset librarian.

### Wi-Fi is supported but not fitted

```
wpa_supplicant   wpa_cli   wpa_passphrase
/lib/firmware/rtlwifi/   rtl8188/8192 firmware blobs present
```

The driver firmware and supplicant are both installed. A supported Realtek USB dongle is
plausibly all that stands between this instrument and wireless networking. **Untested.**

### X11, and a window manager

```
Xorg  Xvfb  xterm  startx  xdotool  xrandr  xinput  setxkbmap
las-dwm        (running — a dwm derivative)
```

The panel UI runs under X, managed by a Moog build of `dwm`. `xdotool` is present, so the
UI is scriptable.

### Moog's own tools, mostly unexplored

```
vxtune      operations: pol, tcode, tcal, lf-curve, freq-curve, autor-curve,
                        tune, cal, set, send, db-csv, csv-db, write,
                        gen-c-freq-tables
            options:    -c/--connect  -v/--voice  -n/--nvoices  -o/--osc
                        -F/--force  --force-all  -f/--db

vxreport    -T/--type {data,summary,completion}  -v/--voice  -o/--osc
            -f/--db  --tcal-db  -O/--outpath  -p/--phase

lassvc      -t/--vc-target    (default las.local:7770)
            -p/--panel-target (default las.local:9100)
            --no-vx

lasfwu      "upgrade the firmware on LAS" — searches for firmware package
            files, validates them, and flashes

las-watchdog, las-frontpanel-poll, las-fb-config, vxtest, vxmon, vxping
```

`vxtune`'s `db-csv` and `csv-db` operations are notable: the tuning database converts to
and from **CSV**. That is a documented, non-destructive way to read out all 48 oscillator
tuning tables in a human-readable form.

### And, genuinely, games

```
gnuchess   gnuchessu   gnuchessx   lbreakout2   ltris   sl
```

GNU Chess, LBreakout2, LTris and `sl` are installed on the synthesiser. Buildroot default
package selection, left in the production image.

### Still absent

`timeout`, `python`, `python3`, `perl`, `base64`, `ss`, `sftp-server`, `fw_printenv`.

### What we built against it

`moogone.vox` — a bridge and web UI for the effects engine, MPE / poly-aftertouch
decoding, and modular routing, badged by exactly what this session verified. Runs on a
Mac, serves an iPad. `README.md` → "Vox".

Consequences:

- Bound long-running processes by PID (`$!` + `kill`), never by job control.
- `scp` from macOS fails — macOS `scp` uses SFTP and dropbear has no
  `sftp-server`. Use `cat file | ssh root@host 'cat > /dest'`.
- Ship binary payloads as `printf '\xNN'` escapes.

Two shell traps that cost real time here:

- `screen -ls` shows the session as `1213..las-production` — a **double** dot.
  A grep expecting one dot matches nothing and yields an empty session name,
  which then fails with "Must be connected to a terminal".
- In zsh, a variable holding ssh flags does **not** word-split. Inline the
  options or use an array.

---

## 11a. Inside the firmware images

Both XMOS images were analysed offline after the instrument was powered down —
82 agents across seven dimensions, every finding adversarially re-verified against the
bytes. **67 of 75 headline claims were refuted.** What follows is only what a second,
independent pass reproduced. Exact offsets are deliberately omitted here; the images are
Moog's copyright and this is a description, not a map.

### The 2 MiB file is 88 % empty

```
app_las_v2.1.2.bin     2,097,152 B file    253,552 B real content   87.9 % zero fill
app_vx_10M_v2.1.0.bin    164,096 B file    163,940 B real content   156 B zero fill
```

`las_layout`'s `00000000:0x001BFFFF firmware` is the **flash partition**, not the size of
the firmware. The controller program is 253 KB — the same order of magnitude as the
voice-card program, not ten times it. Anyone verifying a dump only needs the first 256 KB.

### They are stored in SPI bit order, and `strings` cannot see them

Neither image yields a single readable string as delivered. That is not obfuscation — it
is how XMOS SPI-boot flash images are laid down. Each byte is bit-permuted, and the two
images use **different** permutations:

| Image | Stored as | Recovered by |
|---|---|---|
| controller (`las`) | every byte bit-reversed | reversing the 8 bits of each byte |
| voice card (`vx`) | every byte nibble-swapped | swapping the high and low nibble |

An exhaustive search over all 40,320 bit permutations finds exactly one hit per image,
and each is confirmed independently by its own build tag appearing in cleartext only under
that transform. Every "the firmware contains no strings" claim — and there were many — was
this, misread.

Once decoded, both images carry conventional C string tables. The tables are
LZ-style token-compressed, so most entries survive only as fragments — `Not foun`,
`Unavail`, `Malformed messag`. Enough survives to be useful.

### A third status code

Live, the bus has only ever answered `404 Not found` and `503 Unavailable`. The firmware's
status table holds exactly three entries:

```
404   Not found
400   Malformed message      ← never observed live
503   Unavailable
```

No `200` exists in that table. Success is signalled by answering, not by a code.

### OSC addresses the host binary does not mention

The controller's string table carries leaves that never appeared in the 767-address
census from `las-sc`:

```
/hw/cvout/0            a CV OUTPUT — the host side only ever referenced CV in
/hw/hs/start-offset
/fan-duty              fan speed control
therm/vx-temp-max      per-card thermal limit
/v2/nw                 a v2 namespace, contents unknown
/local/note-min        /lc/kbd/oct
load-timbre            note-enable
```

Plus a thermal vocabulary — `max-vx`, `trip-`, `-avg`, `normal`, `min-s`, `spd` — which is
the fan-control state machine. Given the fan pegged the moment the controller lost its
voice cards, `/fan-duty` is very likely what a fail-safe drove to maximum.

`/hw/cvout/0` is the notable one. The instrument's control surface exposes CV *in*; the
firmware knows about CV *out*.

### The controller speaks bundles; the cards are told who they are

`#bundle` appears four times in the controller image and once in the voice-card image —
both ends handle OSC bundles, even though no bundle traffic has been observed.

The voice-card image is **byte-identical across all sixteen cards**. Its string table
includes `address set to %d` and `%s voice %d: %s error %d`: a card does not know its
slot until the controller assigns it at boot. That is why `/v/voices` read `-1` after the
XMOS reset — the assignment step never re-ran.

### The images describe themselves

The voice-card image opens with a self-describing header: magic `0x00FF51DE`, a size
field that matches the measured content boundary to the byte, and the packed version
`0x020100FF`. The controller image is a **two-stage boot image** — a short outer wrapper
recording total size and the 0x1C0000 partition, a loader, then an inner header with the
same magic and layout. Both payloads begin with the same 12 bytes.

Both images also carry a flash-update vocabulary — `Read from flash`, `Write to flash
complete`, `wrong image version`, `CRC` — so the controller validates magic, version and
CRC before accepting a new image over its own protocol.

### The two programs share a table

After decoding, 96 byte-identical runs totalling 14.6 KB — 8.9 % of the voice-card
program — are common to both images. They are visibly tabular: monotonically ascending
32-bit values. The voice-card image holds two copies at a constant offset, consistent with
one per tile on a dual-tile part. *Inference:* shared coefficient tables compiled into both
from one source. Confirming that needs the consumers disassembled, which was not done.

### Where the calibration actually lives — a correction to §10

`/var/cal/vxcal.db` is **an empty scaffold**. 35 of its 38 tables have zero rows, and the
three populated ones hold all-zero coefficients. It declares a complete schema — two-point
line fits for every gain stage, 12-breakpoint ladder-filter curves, 4-breakpoint SVF
curves, temperature columns throughout — and stores none of it.

**The real calibration is `/var/tuning.vxtune/`.** A backup of only the `.db` would lose
everything. The backup taken in §0 includes both.

The `.vxtune` files are a tagged object serialiser, and they decode. Each oscillator file
holds four records: two fully populated tuning phases — a low-frequency sweep of ~150
rows over 18–100 Hz, a high-frequency sweep, and a **119-point semitone table** from
C0 = 16.3516 Hz — plus a third record with two further tables reaching into the hundreds
of kHz, and an empty record tagged `ffsaw`. Every measured sweep row carries a
temperature; across all 48 files they span **48.8–59.1 °C**, which is the board running
warm during factory tuning. The tuning relation is affine in code with a temperature term.

None of this is in the firmware. The voice-card image is uniformly high-entropy with no
table of that shape anywhere in it — the tables are loaded into the cards at boot by
`las-sc --vxdb`.

### What did not survive

For honesty's sake, the shape of the 67 refutations: roughly a third were "no strings
exist" (wrong transform); a third reported correct measurements and then concluded
something the bytes did not support; the rest had a wrong offset, a wrong count, or
attributed a host-filesystem fact to the firmware. The adversarial pass was worth every
token.

---

## 12. Reproducing this

1. Get a shell. (The USB `k`-file method is documented publicly elsewhere; it is
   not reproduced here.) Format the stick **FAT32/MBR** — exFAT is invisible to a
   4.1 kernel.
2. Find the instrument by hostname: it ARPs as `las-production`.
3. Read `/proc/net/udp` and `/proc/net/tcp` before transmitting anything. Do not
   trust a port number from any writeup, including this one.
4. Capture the namespace by **observation**, not guesswork:
   - `scsynth`: enable `/dumpOSC`, log `screen` to **disk** (`hardcopy -h` only
     dumps ~100 lines of scrollback), then move every control for 30 seconds.
   - panel: `las-frontend --log-panel-osc`, read `/var/las-frontend/las-frontend.log`.
5. Extract the address table from the binaries with `strings`.
6. Query with zero-argument OSC messages, and **self-test the harness against a
   known-good and a known-bad address before trusting any sweep**.

---

## 13. What is still unknown

- **Whether writes to `las-sc` take effect.** Six writes were accepted without
  audible result. `las-frontend --enable-osc-sec` hints at an old-vs-new protocol
  distinction that may explain it.
- **The 376.8 Hz tone.** Present with effects on and off. Mechanism unidentified.
- **Whether a zero-argument message to a setter is truly inert.** It is safer
  than a blob and it reads correctly, but "inert" is unproven.
- **The `/p` namespace**, 464 addresses, largely unmapped.
- Whether `/seq/dest/*` does what its name so strongly suggests.
- **What `/hw/cvout/0` drives.** The firmware knows a CV output; nothing on the
  panel or in the host binary exposes one.
- **What `/v2/nw` is.** A `v2` namespace root in the controller, never seen live.
- **Whether the 14.6 KB shared table is coefficients**, and for what. Inference only.
- **The string-table compression.** Token-based, tokens near `0xad`; no decompressor
  was written, so most addresses are known only as fragments.

Resolved since first writing:

- ~~The third status code.~~ `400 Malformed message` exists in the firmware table.
  It has not been provoked live.
- ~~Where `/info/versionb` comes from.~~ The voice-card header stores `0x020100FF`
  at a fixed offset; the controller's equivalent field is zeroed, so its value is
  synthesised or read from `VERSIOND`.

---

*Corrections and additions welcome. If a claim here does not reproduce on your
instrument, the claim is probably wrong — firmware drifts, and this is one
instrument on one firmware version at one point in time.*
