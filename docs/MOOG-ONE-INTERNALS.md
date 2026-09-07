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

**Confirmed 2026-09-07 by running that test.** `init_sc_1.scd` was edited to
`blockSize = 256` and `hardwareBufferSize = 256`, the engine restarted, and the
instrument's idle output measured through an interface either side:

| | idle output |
|---|---|
| `-z 128` | **375.00 Hz**, which is `48000/128` to two decimal places |
| `-z 256` | **187.5 Hz** present, with **562.5 Hz** alongside it |

The reasoning needs one step of care, because 375 Hz does **not** vanish at
`-z 256` -- it becomes the *second harmonic* of 187.5, so its presence proves
nothing either way. What cannot be explained away runs the other direction:
**187.5 Hz is a subharmonic of 375 and cannot be produced by a 375 Hz
fundamental**, and neither can 562.5 Hz, which is 3 x 187.5. Their appearance is
the evidence; the fading of 375 is not.

The tone is the audio block rate, and it moves with `-z`.

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
controlled MIDI transmitter** for the rest of a rig — but neither appears on the
wire until MIDI out is enabled, which no factory preset does. See §8a.

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

### The control path is silent until you touch something

`tcpdump -i lo`, twelve seconds, idle: **zero packets**. Not a trickle — nothing.
`las-frontend` and `las-sc` say nothing to each other unless a control moves.

This is the most useful capture surface on the machine, and the opposite of
`usbint`, where two thirds of the traffic is the OLEDs redrawing themselves. A
loopback capture taken while the instrument is played contains **only** what the
playing caused. There is no noise floor to subtract.

`recon/capture-voicebus.sh` records both at once for this reason.

### Which ports are reachable from another machine

Owners resolved by matching socket inodes in `/proc/net/udp` against `/proc/*/fd`.
Worth knowing before assuming something must run on-box:

| Port | Bind | Owner |
|---|---|---|
| 22 (TCP) | `0.0.0.0` | `sshd` — **the only TCP listener on the machine** |
| 7772 | `0.0.0.0` | `las-frontend` |
| 7775 | `0.0.0.0` | `sclang` |
| 9300 | `127.0.0.1` | `las-sc` — **loopback only**, so on-box or via SSH |
| 9500 | `0.0.0.0` | `las-frontend` — panel input |
| 9600 | `0.0.0.0` | `las-dwm` |
| 57110 | `0.0.0.0` | `scsynth` |
| 57120 | `0.0.0.0` | `sclang` |

`las-sc` additionally holds around thirty ephemeral loopback sockets.

**There is no MIDI-over-network service.** No RTP-MIDI daemon, and while `jackd`
and `jack_netsource` are both installed, neither is running. MIDI reaches this
instrument over DIN or USB, or not at all — the network carries OSC, not MIDI.

### Port 7772: the performance protocol, decoded

Found by difference. Eighteen seconds idle and eighteen seconds playing, compared
signature by signature: everything matched except one port, which was silent at
idle and carried 291 messages while notes sounded.

`203.0.113.2:7772 -> 203.0.113.1:7772` — the voice controller reporting to Linux.

**These messages have no address.** It is literally `"/"`, padded to four bytes.
All the meaning is in the type tag and a leading integer opcode:

```
/  ,iifi   4  <note>  <velocity>  0      a note began or ended
/  ,ii     8  <mask>                     which voices are sounding
```

That absent address is why no address-space sweep ever found this: there is
nothing to sweep for. A generic OSC dump renders the whole protocol as a wall of
identical `/` lines.

Verified by playing known notes and reading them back — 60, 67 and 72 arrived as
`0x3c`, `0x43`, `0x48`, and MIDI velocity 100 as the float `0.7874`, which is
`100/127`.

**Note-off is a negative zero velocity.** Not a separate opcode, and not a zero —
the sign bit on a zero:

```
note on   00000004  0000003c  3f499326   velocity  0.7874
note off  00000004  0000003c  80000000   velocity -0.0
```

`-0.0 == 0.0` is true in every language worth using, so a decoder that asks
whether velocity is zero cannot tell these apart. `moogone.performance` uses
`math.copysign`, and carries a test that fails if anyone rewrites it as a
comparison.

### Opcode 8 is the voice-allocation mask

Earlier this was recorded as unidentified: the only samples were `0xffff` and
`0xfff7`, a sixteen-bit field with one bit clear, and a stacking test that
appeared not to move it.

It moves. Measured 2026-09-05 by stacking six notes one at a time over USB MIDI
and releasing them in the same order, reading the `,ii` that follows each note
event:

| after | mask | bits set | notes held |
|---|---|---|---|
| 60 on  | `0x0020` | 1 | 1 |
| 62 on  | `0x0060` | 2 | 2 |
| 64 on  | `0x00e0` | 3 | 3 |
| 65 on  | `0x01e0` | 4 | 4 |
| 67 on  | `0x03e0` | 5 | 5 |
| 69 on  | `0x07e0` | 6 | 6 |
| 60 off | `0x07c0` | 5 | 5 |
| 62 off | `0x0780` | 4 | 4 |
| 64 off | `0x0700` | 3 | 3 |
| 65 off | `0x0600` | 2 | 2 |
| 67 off | `0x0400` | 1 | 1 |
| 69 off | `0x0000` | 0 | 0 |

The popcount tracks the held-note count at every one of the twelve steps, and
each release clears **the same bit its note-on set** — the first note off clears
bit 5, not the most recent bit. So it is a live map of which analog voices are
sounding, and the allocator hands out voices in ascending order from wherever it
left off.

The two old samples fit without contradiction: `0xffff` is every voice busy and
`0xfff7` is one of them released.

`moogone.performance.Voices` decodes it, with `count` and `voices`.

### The output bus map is not what you would guess

`scsynth` on this instrument runs with more output buses than the two a stereo
program expects, and **the main outputs are buses 0 and 7 — not 0 and 1.**

Mapped by putting a 1 kHz tone on one bus at a time and watching which physical
output responded, with the main outs cabled into an interface:

| bus | reaches |
|---|---|
| **0** | **main L** |
| **7** | **main R** |
| 5 | both, about 15 dB down — a sum of some kind |
| 1-4, 6, 8-15 | nothing on the main jacks |

This matters because `Out.ar` writes **consecutive** buses. The obvious
`Out.ar(0, stereoSignal)` puts the left channel on the main left and the right
channel on bus 1, which does not reach the main outs at all — audible as a signal
that is somehow only on one side while a meter of buses 0 and 1 shows a perfectly
balanced stereo pair. That is exactly how it was found.

Two writes are needed:

```supercollider
var sig = PlayBuf.ar(2, buf, rate, loop: 1);
Out.ar(0, sig[0]);
Out.ar(7, sig[1]);
```

The remaining buses presumably carry the headphone feed and SEND 1 / SEND 2 — the
meter strip reports `/a/stat/send1` and `/a/stat/send2` — but they were not cabled
to the interface when this was mapped, so which is which is **not established**.

### The instrument is readable everywhere and writable nowhere

Settled, by measurement rather than inference. Three different injections, three
different protocols, all **confirmed to arrive** and all ignored:

| Injected | Confirmed delivered | Effect |
|---|---|---|
| `/` note event to 7772 | captured arriving | none (0.1 dB against a 6 dB threshold) |
| `/x` parameter to 7770 | captured arriving | none (four alternating trials overlap randomly) |
| `/lsleds` to 9100 | captured arriving, `0xAB` fill | none (watched on the panel) |

The LED test is the one that closes it. It is the cheapest possible write — an
output device, repainted twice a second anyway, no state to corrupt — and 100
alternating all-on/all-off frames over six seconds produced nothing visible.

**It is not the source port.** That was the obvious theory after `/x`, and it is
wrong: `las-frontend` sends its own LED frames from *five different* ephemeral
source ports within a few seconds. A fixed socket cannot be what the panel checks.

**The likely gate is a startup cookie.** `las-frontend`'s argv carries `--cookie=1`
and `--startup-coordination`; its log reads:

```
Beginning startup coordination
Applying startup status 0 / 131 / 151 / 121
Writing startup cookie
SystemClock created socket to coordinate with vc:9501
```

There is no cookie *file* anywhere on the filesystem, so it is exchanged over the
wire — which fits the otherwise unexplained `LTRQ` / `LTRS` pair seen once each on
9501 and 60084, at the only moment a capture ever overlapped a boot. **This is a
hypothesis, not a result.** Testing it means capturing a full boot sequence, which
needs a capture running before the instrument is powered on.

#### What this means in practice

The internal control bus is a **read** interface for anything that is not
`las-frontend`. That is not a small thing — everything in this document was read off
it, including the note protocol, the parameter protocol, the panel input and both
displays.

Writing goes through the two doors the instrument actually opens:

- **`scsynth` on 57110**, which accepts `/n_set` from anywhere and is where the
  digital effects live. Fully writable, verified repeatedly.
- **MIDI**, over DIN or USB, which is how notes and mapped controllers get in.

### Where notes actually come from

`las-frontend`'s argv names no MIDI device, ALSA exposes no MIDI ports, and a
loopback capture during heavy MIDI playing stays at **zero packets**. Sound is
produced, notes are reported on 7772, and Linux is not consulted.

The voice engine is autonomous inside the XMOS. MIDI arrives at the voice
controller over DIN or USB, the voice controller allocates and sounds the note
itself, and only then tells the i.MX6 what it did. Linux runs the panel, the
displays, and the SuperCollider effects.

Replaying a captured note message *to* the instrument on 7772 confirms the
direction: the bytes are accepted and **nothing sounds**, measured on the output
meters as a 0.1 dB change against a 6 dB threshold. 7772 is where the voice
controller says what it has already done, not where it is told to do anything.

This is the likeliest explanation for the six accepted-but-inaudible voice-bus
writes recorded earlier in this project. Linux is not in the note path at all.
It does not settle whether the modulation and mix matrices can be set from Linux
— those are configuration rather than performance, and remain open.

### `/x` — the voice-engine parameter protocol, and why writes fail

`las-frontend` sets a voice parameter by sending `/x` to the voice controller on
port 7770:

```
/x  ,b   <u16 param_id> <u16 zero> <f32 value>
```

**The blob is little-endian inside a big-endian OSC message.** Address, type tag
and blob length are OSC and big-endian; the payload is the XMOS's byte order.

That single fact hid this protocol completely. Read big-endian, the values are
denormals around `1e-36` — they look like noise rather than like a wrong guess,
so nothing invites a second look. And no address sweep could have found it: `/x`
carries a parameter *id*, not an address.

Decoded by sweeping MIDI CC 7 and reading the float back:

| CC7 | float | | CC7 | float |
|---|---|---|---|---|
| 0 | 0.00000 | | 64 | 0.50394 |
| 1 | 0.00787 | | 100 | 0.78740 |
| 32 | 0.25197 | | 127 | 1.00000 |

Exactly `value / 127`, on **parameter 358 — master volume**.

**Writes are delivered and ignored.** Not refused, not lost: delivered. A
byte-identical `/x` sent to `203.0.113.2:7770` was captured arriving —

```
203.0.113.1:38075 -> 203.0.113.2:7770   param=358 value=0.12300
```

— and four alternating trials of 0.05 against 0.90 on master volume produced
readings that overlap randomly. The same message sent to `las-frontend`'s own
socket from another machine entirely also arrives, and also does nothing.

The genuine writes all come from `203.0.113.1:40255`, which `/proc` attributes to
**`las-frontend`**, not `las-sc`. The voice controller appears to act only on the
socket that registered with it at startup — the `/auto` message, and the LTRQ/LTRS
exchange on 9501/60084.

**This is the likeliest explanation for the accepted-but-inaudible writes recorded
earlier in this project.** They were accepted. They were also ignored, and there is
no reply that distinguishes those two things.

Reading this bus is how you learn a parameter's id — move a control and watch what
`/x` carries. Changing one still goes through the instrument's own control path.

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

## 8a. USB: MIDI both directions, and no audio at all

Measured 2026-09-05 with a USB-B cable from a Mac to the instrument's USB port.
The question was whether the Moog One presents itself the way an Elektron
Digitone does — audio and MIDI over one cable. **It does not: the socket is MIDI
only.**

### What the descriptors say

`0x2662:0x000d`, "Moog Music, Inc" / "Moog One", `bDeviceClass` 239 (composite,
with an interface association descriptor), two configurations. The active one:

| interface | class | subclass | endpoints |
|---|---|---|---|
| 0 | Audio | AudioControl | 0 |
| 1 | Audio | AudioControl | 0 |
| 2 | Audio | **MIDIStreaming** | 2 |

```
ep 0x02  OUT  bulk  512 bytes    host -> instrument
ep 0x82  IN   bulk  512 bytes    instrument -> host
```

**There is no AudioStreaming interface**, which is the one that would carry
samples, so no audio device appears on the host — correctly, not as a driver
failure. The two zero-endpoint AudioControl interfaces are the topology
descriptors an audio function would hang off; that they are present and empty is
suggestive, but nothing hangs off them.

### The second configuration is a duplicate, not a hidden audio mode

The device reports `bNumConfigurations = 2`, which looked for a while like the one
place a USB audio interface could still be. It is not. **Both configuration
descriptors are byte-identical** — 143 bytes, the same SHA-256, and both carrying
`bConfigurationValue = 1`.

Getting that answer took more than it should have, and the detour is the useful
part. `libusb` on macOS returns the **active** configuration for every index, so
it reports the second configuration as a copy of the first whether or not it is
one. That failure is invisible until you ask it for **index 4**, which no device
has: it returns the same 143 bytes again, with no error. Anything built on libusb
here is answering from a cache and cannot see a second configuration at all.

`IOUSBLib`'s `GetConfigurationDescriptorPtr` indexes the cache macOS built during
enumeration, and returns `kIOReturnNotFound` (`0xe0004056`) past the end — which
is how you can tell it is answering honestly rather than repeating itself. It also
needs no `USBDeviceOpen`, so it reads descriptors while `MIDIServer` keeps its
exclusive claim and the instrument's MIDI is never interrupted. `recon/usb-configs.c`
is that tool.

Two configurations sharing `bConfigurationValue = 1` is itself irregular: the
value is what `SET_CONFIGURATION` selects, and duplicates leave nothing to choose
between. So there is no second mode to switch into, even in principle.

### The USB port is not on the Linux board

The i.MX6 has no USB gadget at all: no `/sys/kernel/config/usb_gadget`, no
`/sys/class/udc`, no `g_midi`, and `/proc/asound/cards` lists only `xmosaudio`.
`amidi -l` finds no rawmidi device and there is no `aconnect`. So the USB socket
is wired to the XMOS side, and USB MIDI never touches Linux.

A capture confirms it. Playing eight notes into the USB port produced **zero
packets on `lo`** — the entire las-frontend/las-sc control path stayed silent —
while `usbint` carried the notes as performance messages from `203.0.113.2`.

### Input works, and arrives on port 7772

Notes sent to the USB MIDI port drive the voice engine: silence measured
−88.0 dBFS, a chord over USB −20.2 dBFS, a rise of **+67.8 dB**. On the wire each
note appears as the ordinary opcode-4 performance message, velocity normalised:

```
,iifi  4  0x30  0x3f499326  0     note 48, velocity 0.7874 = 100/127
,iifi  4  0x30  0x80000000  0     note 48, negative zero = note off
```

This is the same stream the instrument's own keyboard writes to, so nothing in
`moogone.performance` needed changing to read it.

### Output works once it is switched on — confirmed on hardware

Enabled on the instrument and played, 2026-09-06: **44 note events reached the
host over USB**, every note-on triggering a sample inside the instrument's own
scsynth. So the IN endpoint is not decorative and the transmit path is real.

Two details the live traffic settled that the descriptors could not:

- **Note-off arrives as `0x80` carrying a non-zero release velocity** — values of
  43 and 45 were seen, higher than most of the note-ons in the same passage. A
  decoder that treats `0x80` as a note-off only when its velocity is zero would
  hang every note. `trigger_from_midi` keys on the status byte, which is why it
  needed no change.
- **Velocities came back compressed**: 1 to 35 out of 127 across 22 note-ons, with
  `/p/lc/kbd/curve` at its default `med`. Light playing explains it, but it is
  worth knowing that the sampler's own curve puts velocity 1 exactly on its
  −36 dB floor, so a compressed input range is inaudible before it is uneven.

#### The switch, and where it lives

The IN endpoint exists, so the hardware can transmit — but nothing arrives at the
host: three seconds of idle produced no messages, not even clock or active
sensing, and a note sent in was not echoed.

The reason is in the preset, not the hardware. Every preset carries its own MIDI
output switches:

```
/p/part/t/{1,2,3}/in/midi_out/en         master, per timbre
/p/part/t/{1,2,3}/in/midi_out/usb0/en    USB
/p/part/t/{1,2,3}/in/midi_out/din0/en    DIN
/p/part/t/{1,2,3}/in/midi_out/usb0/ch    channel
```

Across all **398 presets** in the factory library:

- `midi_out/en` is `False` in **every one of them**, for every timbre.
- `usb0/en` is `True` in only 13 — `INIT`, `MAIN MENU`, `ATAVACHRON`,
  `GLASSWORKS` and nine others — and the master switch is off in those too, so
  they transmit nothing either.

The global `/p/part/midi_io/midi_out_ports` is `'b'`, which selects both ports;
it is a routing choice, not an enable. An earlier note in the roadmap read `'b'`
as meaning MIDI out was already on. It is not.

**So MIDI out has to be switched on before the instrument will transmit**, and
because the switch lives in the preset it is per-sound and is saved with it.

### Why this matters more than it sounds

The sampler's `keys` trigger mode watches the instrument's keyboard by
SSH-tcpdumping port 7772, which costs a measured **+373 ms**. If MIDI out is
enabled, the same notes reach the host over USB in about a millisecond, and the
sampler's `midi` mode replaces `keys` outright — with no DIN cable and no second
interface. That is the single highest-value setting on the instrument for this
toolkit.


## 8b. Audio over the network, which USB cannot give

USB carries no audio on this instrument, so the question became whether the
network could. It can, in real time, using only what is already running.

### The sound card is taken, and that turns out not to matter

`/proc/asound/pcm` shows one card, 8 in and 8 out, `S24_LE` at 48 kHz with a
128-frame period. `/proc/asound/card0/pcm0c/sub0/status` reports
`subdevices_avail: 0` with the owner PID being **scsynth** — which runs as
`scsynth -u 57110 -a 129 -i 9 …`, nine input channels and the card to itself. So
`arecord` cannot open it, and neither can anything else.

It does not matter, because scsynth is a server this machine already talks to. It
will write audio anywhere a file can go:

```
mkfifo /tmp/vox-netaudio.raw
cat /tmp/vox-netaudio.raw | nc <host> <port> &
```

then, over OSC, `/b_alloc` a ring, `/b_write` it to the FIFO as **raw float**, and
start a `DiskOut` synth on the bus. WAV is the wrong container here: its header
carries a length that has to be seeked back and written at close, and a FIFO
cannot be seeked. Raw has no header to finalise.

There is no SSH in the audio path. Measured: **5.03 seconds of stereo audio in 5
seconds of wall clock**, with the loudest component at 375.0 Hz — the block-rate
tone, which confirms the stream really is the output bus and not something else.

### The ring buffer is the latency, and the default is the wrong one

`DiskOut` drains a ring, and for a live stream that ring **is** the delay. The
same measurement at two sizes:

| ring | trigger → sound | trigger → bytes here |
|---|---|---|
| 65536 frames | 372.5 ms | 586.2 ms |
| 2048 frames | 22.1 ms | 29.1 ms |

65536 is SuperCollider's usual size and what `moogone.record` uses, which is right
for writing a file and catastrophic for a stream.

### What it costs, measured properly

This is also the honest way to time a trigger, and it settles a measurement that
an audio interface could not. Both ends are this machine's clock and the answer is
a byte offset in a stream, so there is nothing to align and nothing to drift.

Six triggers at a 2048-frame ring:

```
trigger -> sound on the instrument : median  22.9 ms   spread  9.8 ms
trigger -> bytes on this machine   : median  21.4 ms   spread 11.2 ms
```

The two agree to within one TCP segment (1448 bytes ≈ 3.8 ms of audio), so the
network transport costs less than this method can resolve. **Per-hit subtraction
of the two is meaningless** and produces negative "transport" times, because an
arrival stamp belongs to the chunk carrying a byte rather than to the byte.

Against `keys` mode's +373 ms and 767 ms spread, that is the same instrument
answering roughly sixteen times faster.

### The trap that makes the stream silent

Nodes execute in creation order. A recorder added to the tail of the root group
hears everything that already exists — which is why `moogone.record` captures the
instrument's own output correctly — but a **sampler voice created afterwards
writes the bus too late for it to be read**, and the stream stays silent with no
error anywhere. `/g_tail 0 <recorder>` after each trigger puts the recorder back
at the end. The symptom is silence, not lateness, so it does not look like an
ordering problem until you go looking for one.

`recon/net-audio.py` is all of this in one command.


## 8c. Why bursts of network traffic lock the instrument up

Twice this project took the instrument off the network hard enough to need a power
cycle, and twice the cause was misdiagnosed — once as a hung `scsynth`, once as
the host's Wi-Fi. It is neither, it is reproducible on demand, and the fix is a
rule about how you send rather than anything on the instrument.

### One USB gadget carries both networks

The i.MX6 is the USB **host**. `2662:800d`, product string **"LAS internal"**, is
the gadget, and it presents four interfaces:

| interface | class | endpoints | serves |
|---|---|---|---|
| `2-1:1.0` | CDC control | `ep_81` interrupt | `usbint` — the voice controller |
| `2-1:1.1` | CDC data | `ep_01`/`ep_82` bulk, 512 B | `usbint` |
| `2-1:1.2` | CDC control | `ep_83` interrupt | `ethext` — the LAN |
| `2-1:1.3` | CDC data | `ep_02`/`ep_84` bulk, 512 B | `ethext` |

**The LAN and the link to the voice controller are two functions of one device.**
That is the whole shape of the problem: traffic aimed at the network can take out
the instrument's own internal bus, which is why a flood looks like a dead
instrument rather than merely a dead network.

### The trigger is burst rate, not throughput

Measured by stepping a paced load up and then sending the same datagrams unpaced:

| shape | rate | result |
|---|---|---|
| paced, 25→550 datagrams/s of 1308 B | 719 kB/s, **1.47× realtime 48 kHz stereo** | untroubled: zero drops, zero errors, memory flat |
| unpaced, 2000 datagrams back to back | 18 ms, ~145 MB/s, **296× realtime** | wedged before the burst finished |

Identical size, identical port, identical destination. Only the spacing differed.
The sustained rate any real work needs is comfortably safe; a microburst is not.

### What the kernel says, and why the host cannot fix it

A black box logging to `/var` — the log has to outlive the network — caught both
halves:

```
[467.013682] NETDEV WATCHDOG: usbint (cdc_ether): transmit queue 0 timed out
[491.910429] usb 2-1: can't set config #1, error -71
```

The first names **`usbint`**, not `ethext`. Flooding the LAN stalls the transmit
queue of the *voice controller* link, on the shared gadget.

The second is the important one. `-71` is `EPROTO`: after unbinding and rebinding
the USB device to force a full re-enumeration, the gadget would not accept
`SET_CONFIGURATION`. **The device is wedged below the level the host can reach.**
Bouncing `ethext` with a fresh DHCP lease does nothing either. Only removing power
clears it.

So the fault is in the gadget — Moog's own silicon — and not in Linux's `usbnet`.
At the moment of the wedge `MemFree` was 5704 kB, normal for this machine, with
`rx_dropped` and `rx_errors` both zero: it is not memory exhaustion and the driver
never saw a packet it had to discard. It simply stopped being answered.

### The interlock

`moogone.transport.udp` now spaces datagrams by `MIN_SEND_INTERVAL` (1 ms, so
1000/s). That is roughly three times what streaming 48 kHz stereo through OSC
needs and two orders of magnitude below the burst that wedges the gadget, and it
is invisible in practice — thirty round trips measured 23.1 ms each, all of it
network, none of it the floor. It is a safety interlock on someone else's
hardware, not a tuning parameter.

TCP paces itself, which is why streaming audio *out* was safe from the first
attempt and never once misbehaved. Raw UDP does not, so OSC is where the hazard
lives.

### A note on the watchdog that found this

The recovery ladder that produced the `-71` evidence also reported
`RECOVERED BY STEP 2`, and that verdict was **wrong** — a bug in the diagnostic,
not a result. After the unbind, `ethext` no longer existed, so reading its
`rx_packets` returned an empty string, and `"" != "8369"` compared true. A probe
that reads a counter through a path the experiment is expected to destroy has to
distinguish *changed* from *unreadable*, or it will cheerfully report success at
the exact moment it loses the ability to tell.


## 8d. Where the wedging USB gadget's firmware is not

§8c established that a microburst wedges the `2662:800d "LAS internal"` gadget
below the level the host can reset. The obvious next step was to read that
gadget's firmware. It is not on the filesystem, and proving so was quick.

### Both XMOS images are plain code, and neither speaks USB

`/usr/share/xmosfw/` holds exactly two images, and `las-sc` names both on its
command line — `--vcfw=app_las_v2.1.2.bin` and `--vxfw=app_vx_10M_v2.1.0.bin`.

Neither is compressed or encrypted:

| | app_las | app_vx |
|---|---|---|
| content | 253,552 B in a 2 MiB image | 163,940 B |
| entropy, 1 KiB windows | 4.14 – 7.20, median 6.85 | 3.25 – 7.21, median 6.64 |
| windows above 7.9 bits/byte | **0** | **0** |
| most common byte | `0x0f`, **11.3×** flat | `0x3a`, **14.5×** flat |

Encrypted data sits at ~7.99 uniformly and compressed data has a flat histogram.
An 11–14× byte bias is neither. These are plain, uncompressed code images. (The
"strings" a naive scan finds in `app_vx` are an artefact of `0x3a` and `0x5b`
being common code bytes: `'[ [ 4[ H[ T:A4['`.)

Which makes the next result conclusive rather than merely suggestive:

```
LANGID descriptor (04 03 09 04) : 0 hits in both
USB string descriptors          : 0 in both
CDC functional descriptors      : 0 in both
"Moog" in ascii or utf-16       : 0 in both
```

**Every USB device must carry a LANGID string descriptor.** Its absence from plain,
uncompressed images is proof, not inference: the USB stack is in neither file. The
gadget's firmware lives in the XMOS's own SPI flash — the boot image these
application images are loaded on top of — and nothing on the i.MX6 filesystem
contains it.

So disassembly stops here for want of a target, not for want of a disassembler.

### What the search found instead: a reset line

`/etc/init.d/S25xmosfw` runs `config-las-spi xmos`, and that script — 1047 bytes
of shell, safe to read — shows the i.MX6 and the XMOS **share a SPI bus**, with
the host stepping aside by making its SPI1 pins GPIO inputs. Then:

```sh
echo 0 > /sys/class/leds/XMOS_RESET_N/brightness
echo 1 > /sys/class/leds/XMOS_RESET_N/brightness
```

**The XMOS's reset line is exposed as a LED device**, and the boot sequence itself
uses it. That is a candidate software recovery for the §8c wedge: reset the gadget
rather than removing power from the instrument.

It is untested, and testing it has a catch worth stating plainly — when the wedge
happens the network is gone, so nothing can be typed at the machine. The reset
would have to be armed **before** the fault, by a watchdog already running on the
instrument. `S42sc` is the script that would then reload the firmware.


## 8e. Audio *into* the instrument, and the graph that decides where it can go

§8b got audio out. Getting it in is not the mirror image, and the obvious
construction fails in a way that looks like success for a long time.

### The instrument's effects engine is SuperCollider source, on the device

`/usr/share/las-fx/` holds `synthdefs.scd` (3875 lines), `efx_server.scd` (1087)
and the `init_sc_*.scd` that `launch-sc-1` runs. `init_sc_1.scd` loads
**pre-compiled** defs from `synthdefs/`, so the source is a guide to what runs
rather than proof of it — but every live control value matches its default, and
it explains behaviour that months of probing had not.

The graph, read off `inputRouter` and `outputRouter`:

| bus | carries |
|---|---|
| 0-7 | the output buses (`-o` defaults to 8). Mains are 0 and 7 (§8) |
| 8-16 | the input buses (`-i 9`). `SoundIn.ar(n)` is bus `8+n` |
| 50-55 | insert returns 1, 2, 3 — where the three insert effects write |
| 56-59 | what `inputRouter` writes |
| 60-63 | what `outputRouter` reads as master 1 and master 2 |
| 64-128 | unused (`-a 129`) |

**`inputRouter` writes 56-59 and `outputRouter` reads 60-63, and that is correct.**
Reading only the source it looks like a disconnect, and this document said so.
It is not: buses 56-59 are the *inputs* to the two bus-effect slots and 60-63 are
their *outputs*, so the chain meets through the effect in between.

```
 1038  none_2        inBus=56  outBus=60     <- send 1's slot
 1024  et_shimmer_2  inBus=58  outBus=62     <- send 2's slot
```

A sweep of buses 50-63 appeared to confirm the disconnect -- 56 and 57 reached
nothing while everything either side of them did -- and the real explanation is the
patch: send 1 held `none_2`, which passes nothing, and send 2 held a live shimmer.
**A bus that reaches nothing is not evidence of a broken graph when a no-op effect
is sitting in it.** `master1_out_busses = [60, 61]` inside `inputRouter` is used
only for the `par_amount` feedback tap, which is what made the misreading
plausible.

An effect's input is not fixed either. `efx_server.scd` sets it from an OSC
message as `msg[3] + 8` — a hardware input channel — so the effects read the voice
cards directly and write the insert returns.

### Injecting on an input bus reaches nothing, and the patch is why

The first attempt summed into bus 8, reasoning that the voice cards land there and
the effects read them. Measured with a locally generated tone on one bus at a
time, buses 0 through 16: only 0 and 1 ever reached the recorder.

`outputRouter`'s live controls say why. Every digital dry gain is **zero** —
`timbre_1_dry`, `timbre_2_dry`, `timbre_3_dry`, `dry_1_p` — and all five effect
slots hold `none_1`. With the shipped patch there is no digital path from the
inputs to the main outs at all. **What reaches an injected signal depends on the
user's patch**, which is not a foundation to build a plugin on.

### So: private buses, and the instrument's own effects on them

Every effect in `synthdefs.scd` has the same shape:

```supercollider
var input = In.ar(inBus, 2);
sig = LADSPA.ar(2, 29153, distance, diffusion, ..., input[0], input[1]);
Out.ar(outBus, (sig * env * g_out));
```

`inBus` and `outBus` are plain controls, so an effect can be pointed anywhere.
Pointing one at buses 100 and 102 — above everything the instrument uses — runs
our audio through the instrument's real DSP while **modifying no patch and
touching no gain of the user's**. The whole rack is reachable this way: 25
distinct effects, including the five Eventide reverbs, which are LADSPA plugins
in `las-fx/ladspa/` (`eventide_blackhole.so` and friends, IDs 29150-29155).

### `/n_free` on an effect terminates scsynth

Measured on its own, with nothing else running: create `et_plate_1`, `/n_free` it,
and the server stops answering. Twice out of two, and it took the audio engine
down both times it happened by accident first.

Moog's effects are created once at boot and never freed, so the free path is the
part of their lifecycle their own firmware never exercises. Their envelope says
how they are meant to be stopped:

```supercollider
var env = EnvGen.kr(Env.asr(0.1, 1, 2), enable, doneAction: 1);
```

**doneAction 1 is pause, not free.** `enable = 0` releases the envelope and parks
the synth; it stays allocated, costs no CPU, and can be resumed with `/n_run 1`
and `enable = 1`. Setting the control alone does nothing, because a paused synth
is not running to see it.

### The FIFO route does not work, and fails quietly

The mirror of §8b would be a FIFO fed by `nc` and read by `DiskIn`. Three
measurements, in the order they were made:

* **`/b_read` reads a FIFO honestly.** Given a WAV header and nothing else it
  blocked for **4.02 s** until the frames it was asked for arrived. libsndfile
  parses a header from a stream without seeking, exactly as hoped.
* **`DiskIn` will not continue from one.** Cued from a FIFO it plays what
  `/b_read` left in the buffer and never asks again: twenty seconds of a realtime
  feed and the instrument accepted **0.00× realtime**. The same synthdef reading
  an ordinary file on the instrument sounds at rms 0.141, so DiskIn is fine and
  the pipe is the difference.
* **It puts the disk thread at risk.** That thread serves `/d_recv`, `/b_alloc`,
  `/sync` *and the instrument's own preset and sample loading*, and a read of an
  empty FIFO blocks it. An under-fed one left `/sync` unanswered for over eight
  seconds. It recovers when the writer closes — EOF unblocks the read — but
  blocking it is not a corner case of that design, it is the design.

`/status` cannot see any of this. It is answered by the **realtime** thread and
stays perfect while the disk thread is stuck. `/sync` is the only probe that
touches the thread at risk, which is why the health checks in
`recon/net-audio-in.py` ask for both.

### The route that works: `/b_setn` into a ring

No disk thread at all. Samples go straight into a buffer over OSC, and a `Phasor`
and `BufRd` read them back as an endless ring:

```supercollider
var phase = Phasor.ar(0, BufRateScale.kr(buf), 0, BufFrames.kr(buf));
Out.kr(pos, A2K.kr(phase));            // so the writer can see the reader
Out.ar(bus, BufRd.ar(1, buf, phase, loop: 1) * gain ! 2)
```

The traffic rides the same paced UDP transport as every other command here, so the
§8c interlock covers it. 256 samples per `/b_setn` keeps the datagram sub-MTU and
means 188 messages a second against the 1000/s the interlock allows.

**Mono, and that is arithmetic.** Stereo ingress is ~420 kB/s, which alongside the
384 kB/s of egress exceeds the 719 kB/s §8c measured as untroubled. Mono halves it
to ~210 kB/s and puts the pair at ~594 kB/s, inside what was measured.

The writer holds a lead over the reader and watches it through the control bus,
because the two clocks are not the same one. Measured, 6000-frame ring with a
2000-frame lead, `et_plate_1` in the path:

```
round trip           median 115.2 ms   spread 5.3 ms
writer               1.000x realtime, rate correction 1.00000
gap                  held within 1232 frames of the 2000-frame target
disk thread          8-13 ms for /sync throughout
ethext / usbint      no new errors
```

Doubling the ring and lead took the round trip to 264.9 ms and bought nothing.

### Block size is the cheapest CPU there is, and it is set in one line

`init_sc_1.scd` runs the engine at `blockSize = 128`. Raising it to 256 and
restarting measured, on the same 496-ugen default graph:

| graph | `-z 128` | `-z 256` |
|---|---|---|
| the bare default, 496 ugens | 22% | **17%** |
| a real patch, 682 ugens, five effects routed | 72% | **51%** |

The second row is the one that matters. That patch carries `pingpongDelay_0`, two
`delay_0`s, `et_hall_2` and `et_room_1`, and the change hands back **21 points of
a core**. Adding a sixth effect through a send then measures 79% -- under the
throttle, where at `-z 128` the same thing measured 101% and dropped out
audibly.

About a quarter off the graph's cost, for 2.7 ms of extra block latency. **The
effects themselves barely change** -- `et_plate_1` cost +29% at 128 and +27% at
256 -- so the saving is in per-block overhead across the whole graph rather than
in any one synth. That matters because the five Eventide reverbs cost 25-31% each
and a normal patch already sits at 72%: the headroom has to come from somewhere,
and it is not going to come from the reverb.

Reverting is the same one line. The backup taken before the change is at
`/var/init_sc_1.scd.blocksize-backup` on the instrument.

### The pacing bug worth inheriting

The writer runs on an absolute schedule and originally **reset it** whenever a
block ran long, on the reasoning that catching up means sending faster and a burst
is what costs a power cycle. That reasoning is right about bursts and wrong about
this: resetting throws the overshoot away permanently. It came to **0.982×
realtime**, and because the instrument reads at exactly 1.000× the lead drained at
864 frames a second — the round trip fell from 149 ms to 89 ms across five hits
while the rate controller sat pinned at its clamp, unable to make up 1.8 %.

Carrying a bounded deficit is not a burst, because the loop sends exactly one
block per pass whatever happens: catching up only means not sleeping, and the
transport's 1 ms interlock still caps the rate. Only a stall longer than 20 ms is
given up on.

### Never block the writer to ask how the writer is doing

The gap poll ran with `ScClient`'s two-second default timeout, on the writer's own
thread. One lost `/c_get` reply and the feed stopped for two seconds — which
drained a 16000-frame lead to 3200 and left the instrument's reader replaying
lap-old blocks. **It is heard as stuttering**, and it was reported by ear before
any measurement caught it: `/status` was perfect throughout, the round trip
measured fine, and the network counters were clean.

The correct response to no new information is to keep the last rate. The gap moves
by a fraction of a percent per second, so a skipped reading costs nothing and a
blocked writer costs everything. `moogone.ingress.RingWriter` now abandons the poll
after 50 ms and counts the miss.

Two numbers make this visible where the obvious one does not. `worst_gap_error` is
symmetric and hides the failure; **`min_gap` is the one that matters**, because
when it reaches zero the reader has caught the writer. At a 2000-frame lead it fell
to 256 — five milliseconds of margin — while every other indicator read healthy.

### The demo's own settings can be the fault

`et_plate_1` at `size=0.9, decay=0.85` is not a big plate, it is a self-sustaining
wash. Recorded off the analog outs it read a **crest factor of 2.1** — a saturated
drone rather than plucked notes — and it clipped the interface at six times less
send level. Backed off to `size=0.55, decay=0.4` the same phrase records at crest
4.6 with the tail still obvious.

Worth stating because the first instinct on seeing a clipped recording was to
suspect the audio path, and the audio path was fine.

### One `ScClient` cannot serve two threads

The writer polls the read pointer four times a second while the main thread asks
for `/status` and `/synced`. `ScClient` matches replies by reading whatever the
socket hands it and discarding what does not match, so two threads waiting on one
socket steal each other's answers. There is no error: both sides simply get slower
and start timing out. It presented as an unexplained crawl with the audio still
flowing perfectly. Give each thread its own client.

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
- **Whether a zero-argument message to a setter is truly inert.** It is safer
  than a blob and it reads correctly, but "inert" is unproven.
- **Why a microburst wedges the USB gadget at the protocol level.** The trigger
  and the envelope are known (§8c) and the toolkit is interlocked against it, but
  what the gadget's firmware does to get into a state where it refuses
  `SET_CONFIGURATION` is unread, and §8d rules out both on-disk firmware images as
  the place to look: the gadget's USB stack is in the XMOS's own SPI flash.
- **Why sample triggers read short.** Firing the sampler at exact one-second
  intervals and reading the bursts back gives gaps near 900 ms, with the implied
  delay falling monotonically across a run. The capture is not the cause:
  differencing a 2 s against an 8 s recording isolates a fixed ~0.42 s stream
  start-up and leaves 6.000 s of audio taking 5.97 s of wall clock, with or
  without concurrent OSC traffic, and the instrument's idle 375 Hz tone reads
  374.94-374.96 Hz in every window of a six-second buffer. The sends are exact to
  0.01 ms. Two real bugs were found while hunting it (see below) and fixing them
  narrowed the spread from 127 ms to 99 ms, but the systematic part remains.
- **The `/p` namespace**, 464 addresses, largely unmapped.
- Whether `/seq/dest/*` does what its name so strongly suggests.
- **What `/hw/cvout/0` drives.** The firmware knows a CV output; nothing on the
  panel or in the host binary exposes one.
- **What `/v2/nw` is.** A `v2` namespace root in the controller, never seen live.
- **Whether the 14.6 KB shared table is coefficients**, and for what. Inference only.
- **The string-table compression.** Token-based, tokens near `0xad`; no decompressor
  was written, so most addresses are known only as fragments.

Resolved since first writing:

- ~~Why the sampler added hundreds of milliseconds that looked like jitter.~~ Two
  causes, both fixed. `Sampler.note_on` applied its expiry test to the voice slot
  it was reusing but not to the note's oldest layer, so holding a key past
  `voices_per_note` sent `/n_free` for a one-shot that had ended -- drawing
  `/fail: Node N not found`. And `ScClient._await_reply` raised any `/fail` it saw
  as the current request's, so that unsolicited failure was read by the *next*
  request instead. Measured as a delay falling 953, 757, 603, 533, 389 ms across
  five triggers as the backlog drained. `/n_free` is now in `HARMLESS_FAILURES`,
  since a free that arrives after the node ended is the normal case for a one-shot
  and never something to raise.
- ~~Opcode 8 on the performance port.~~ It is the voice-allocation mask; the
  popcount tracks held notes exactly. See §8.
- ~~What the second USB configuration contains.~~ A byte-identical copy of the
  first. Read with `recon/usb-configs.c` via IOUSBLib, which indexes the cache
  properly where libusb returns the active configuration for every index — a
  failure that only shows itself when you ask for an index past the end and get
  data instead of an error. §8a.
- ~~Whether the instrument presents USB audio like a Digitone.~~ It does not, in
  the configuration the host selects: MIDIStreaming only, no AudioStreaming. §8a.
- ~~The third status code.~~ `400 Malformed message` exists in the firmware table.
  It has not been provoked live.
- ~~Where `/info/versionb` comes from.~~ The voice-card header stores `0x020100FF`
  at a fixed offset; the controller's equivalent field is zeroed, so its value is
  synthesised or read from `VERSIOND`.

---

*Corrections and additions welcome. If a claim here does not reproduce on your
instrument, the claim is probably wrong — firmware drifts, and this is one
instrument on one firmware version at one point in time.*
