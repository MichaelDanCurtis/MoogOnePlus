<!-- docs/arch/xmos-firmware.md -->
# The two XMOS firmware images

Static analysis of `app_las_v2.1.2.bin` (voice **controller**, `lasvc`) and
`app_vx_10M_v2.1.0.bin` (voice **card**, `lasvx`), plus the five ARM host
binaries that drive them. Nothing here was obtained from a running instrument —
every claim is reproducible from files in `captures/arch-harvest/`.

Tooling: `recon/strtab_decode.py`. It supersedes `recon/strtab.py`.
The string-table format itself is specified in [`decompressor.md`](decompressor.md).

---

## 1. What the images are

Both files are xcore boot images in the same container format, and they share a
loader stub byte-for-byte.

| | controller | voice card |
|---|---|---|
| File | `app_las_v2.1.2.bin` | `app_vx_10M_v2.1.0.bin` |
| On-flash encoding | **bit-reversed per byte** | **nibble-swapped per byte** |
| Declared size | `0x0003DF00` @ 0x08 | `0x00028064` @ 0x10 |
| Last non-zero byte | 0x3DE6F | 0x28063 |
| Version word | — | `0x020100FF` @ 0x14 and 0x1C048 |
| Build string | `lasvc-v2.1.2-0-gc38fe65` @ 0x2AC90 | `lasvx-v2.1.0-0-gd309cf3` @ 0x1C334 |
| Loader stub | 0x0085..0x0AAA | (inherited, shorter) |
| Segment table | 0x0AFC..0x0B60, **8 segments** | 0x002C..0x0054, **2 segments** |
| First code byte | 0xB60 | 0x54 |

The two encodings are not obfuscation, they are how each part's SPI flash
presents bits. Undo them first or nothing below is visible.

The segment table is a run of `(id, size_a, size_b)` triples; the controller's
ids are `0x00120002 0x00100002 0x00110002 0x00000002 0x00010002 0x00040002
0x00050002`, i.e. `(node << 16) | 2`. The two `size` fields differ by 3-20x,
which is consistent with `(stored, in-RAM)` — the images are decompressed at
boot, and the flash partition they live in is 1.75 MiB (`0x001C0000` appears
verbatim at offset 0x0C, matching `las_layout`'s `00000000:0x001BFFFF firmware`).

The controller image also carries USB descriptor text — `Moog Music, Inc`,
`LAS internal` (at 0x11C26), ` Clock Selector`, `…ternal Clo…` — so the
controller is the part that enumerates as the USB network interface the host
renames to `usbint`.

---

## 2. The string-table encoding

### 2.1 What was asked, and the honest answer

**The compression is partially cracked, and the full specification now lives in
[`decompressor.md`](decompressor.md).** Solved there: the framing, the token
widths, and the *length field of the two-byte reference*, exactly. Not solved:
what a reference points at — and `decompressor.md` proves that the low bits of
the operand are not a back-distance, which retires the whole family of
hypotheses the sweep below was searching inside.

Read this section for context; read `decompressor.md` for the format. Where the
two disagree, `decompressor.md` is newer. In particular §2.4's use of the
hex-digit tables as ground truth is **wrong** — the three regions do not put the
same text between the two tables, so the "eleven bytes" that fit was fitting
noise.

### 2.2 Corrections to the prior model

`recon/strtab.py` framed this as "three magic marker bytes, 0xAD/0xB5/0xDF, in
one region of the controller image." Three parts of that are wrong.

**It is not one region.** The same encoding appears in five places:

| region | image | extent | contents |
|---|---|---|---|
| `las-a` | controller | 0x29800-0x2A800 | `/hw`, `/a`, `/in`, thermal, the status-code table |
| `las-b` | controller | 0x2AA00-0x2AD90 | USB descriptors, flash-access messages, `/info` |
| `las-c` | controller | 0x3C400-0x3DF00 | a **second copy** of the address table, plus the sorted dictionary |
| `las-d` | controller | 0x0DB80-0x0DF00 | front-panel / keybed calibration (`cal_default`, `save`, `load`, `hyst`, `thresh`) |
| `vx-a` | voice card | 0x1BAC0-0x1C600 | the voice card's entire command surface |

**The marker bytes are not three, and they are not magic.** They differ per
region, which means the marker byte carries payload:

| region | 3-byte marker | 2-byte markers |
|---|---|---|
| `las-a`, `las-b` | `0xAD` | `0xB5`, `0xDF` |
| `las-c` | `0x9B` | `0xB5`, `0xE7` |
| `las-d` | `0x9B`, `0xA5` | `0xB5`, `0xF6` |
| `vx-a` | `0xA3`, `0x9B` | `0xB5`, `0xB7` |

`0xB5` is a 2-byte token in every region. `0xAD`, `0x9B`, `0xA3` are 3-byte in
the regions where they occur and absent from the others — so there is no
contradiction, only a marker alphabet larger than three. Every marker byte
observed is **odd**.

**The framing is a high-bit flag, not a marker set:**

```
byte <  0x80    literal, emitted verbatim   (all table text is 7-bit)
byte >= 0x80    back-reference, 2 or 3 bytes total
```

The width rule that fits every observation is `3 if b < 0xB0 else 2`. Only about
seven marker values have been seen, so treat 0xB0 as a fit, not a fact.

### 2.3 The proof that it is LZ77

The controller image encodes **the same address table twice**, at 0x2A2C0 and at
0x3CAC8, with identical literal fragments in identical order and *different*
literal/token splits:

```
las-a  db/            [AD 52 83] [B5 18] xy/mode [B5 56] hold [DF 6F] O [DF 2F] tune/fba
las-c  db/curv [9B 15 A9]        [E7 28] xy/mode [E7 A6] hold [B5 5F] O [B5 1F] tune/fba
```

A split that depends on what the encoder had already emitted, rather than on the
string being encoded, is the signature of a match finder. A dictionary, a trie
or a front-coder would produce the same output both times. This also disposes of
the "sorted token dictionary" theory: that dictionary (at 0x3D230 in `las-c`,
0x1C193 in `vx-a`) is itself compressed text, not a codebook the tokens index
into — `ringsrc` appears both in it *and* as a literal in the address table.

The same span is in fact encoded **three** times across the two images. The
upper- and lower-case hex-digit tables, `"0123456789ABCDEF"` then
`"0123456789abcdef"`, appear in `las-b`, `las-c` and `vx-a`, and each region
completes the eleven bytes between `…ABCDEF` and `abcde` with a different pair
of tokens:

```
las-b   [DF 43] [B5 7A]
las-c   [E7 32] [E7 EA]
vx-a    [B5 EA] [B5 2A]
```

### 2.4 Ground truths

`GROUND_TRUTH` in `recon/strtab_decode.py` carries ten. The strongest are the
ones where the plaintext is not a guess:

| region | tokens | must emit | how we know |
|---|---|---|---|
| `las-a` 0x2A0C9 | `AD 11 59` | `d\0` | the controller answers `s:404 s:"Not found"` |
| `las-a` 0x2A0E0 | `AD 10 5B` | `e\0` | `s:400 s:"Malformed message"` |
| `las-a` 0x2A0EE | `AD 22 5B` | `able\0` | `s:503 s:"Unavailable"` |
| `las-b` 0x2AA63 | `DF 43`,`B5 7A` | `\0` + `0123456789` | hex-digit table pair |
| `las-c` 0x3D27C | `E7 32`,`E7 EA` | same | same, different split |
| `vx-a` 0x1C0A5 | `B5 EA`,`B5 2A` | same | same again |
| `las-a` 0x2A3B2 | `B5 B8` | `\0/local/note-m` | `/in/local/note-min` then `note-max` |
| `las-c` 0x3CBB0 | `E7 E8`,`E7 28` | same 14 bytes, as **two** tokens | same span |
| `las-c` 0x3C616 | `9B 10 A7`,`E7 48` | `\0/mix/` | `/mix/main-en` then `/mix/sub-en` |

Two facts fall straight out of these and kill families of hypotheses:

* **Lengths vary from 2 to 14.** `AD 11 59` emits two bytes; `B5 B8` emits
  fourteen. So there is a real length field, or lengths are implicit.
* **Copy-until-NUL cannot be the whole story.** It fits every 3-byte token in the
  status table (`d\0`, `e\0`, `able\0` all terminate at a NUL) and is flatly
  contradicted by `B5 B8`, whose fourteen bytes *begin* with a NUL and continue
  past it. If copy-until-NUL is in the format at all, it is one opcode among
  several, not the format.

### 2.5 Negative results

Every one of these was tested and rejected. They are recorded so nobody spends
the afternoon again.

* Length in the operand's low nibble / low 3 bits / high nibble / high 3 bits,
  distance in the remaining bits of `(marker & 0x7F) << 8 | operand` — and the
  same with the marker dropped and only operands as payload.
* Length in the marker, distance in the operands. Killed directly: `las-a`'s
  `B5 06` and `las-c`'s `E7 06` sit at the same structural position with the same
  operand and different markers, so the marker cannot be the length alone.
* Every split point of the 15-bit (2-byte) and 23-bit (3-byte) payloads, both
  field orders, bases 1-3, swept over ~700 candidate stream starts per region.
  `recon/strtab_decode.py --search` (the subcommand has since been removed; see
  `decompressor.md` §4 for why the space it swept cannot contain the answer).
* Front coding, tested directly. The address table is not in sorted order
  (`fm/rout` is followed by `amt`), so it cannot be.
* Deflate-style length classes with extra bits: `a >> 4` looked like a class
  field (`1 -> len 2`, `2 -> len 5`) until `AD 24 F5` had to emit two bytes with
  the same class as `AD 22 5B`'s five.

**The trap in any future search.** Wrong parameter sets do not usually fail
loudly. They fail by making every distance tiny, which produces runaway repeats
that look like this and score 99% printable:

```
g/0/tgr/0g/0/tg/o1/tgr/0g/og/0/tg/o1/tgr/0g/og/0/tg/o1/tgr/0g/o...
```

Any scoring function must reject low 6-gram diversity. Printability alone is
worse than useless.

### 2.6 The most promising unexploited lever

The double encoding. Anchored on literal runs shared between `las-a` and
`las-c`, it yields equations of the form

```
sum(len of A's tokens) - sum(len of B's tokens) = |B's literals| - |A's literals|
```

over spans where both encode the same text. `--rosetta` emits them. At a
five-character anchor threshold there are only twelve anchors and one usable
segment; aligning at the **character** level (longest common subsequence of the
two literal streams) instead of the run level would produce many more, and a
solved length function makes the distance field fall out by subtraction.

---

## 3. The command namespace

### 3.1 What the firmware images add

Most of the namespace is recoverable in plaintext from the host binaries
(§3.2). The firmware images are worth reading because they contain things the
host does not, and because they are the authority on what the hardware actually
implements. Recover with `recon/strtab_decode.py --fragments`.

**Controller-only, not present in any host binary:**

```
/fan-duty          therm/vx-temp-max    trip-        max-vx      fan-normal
/v/voices          nodect               voices       dis         set-group
load-timbre        transpose            note-enable  panic       source
/r/sq/             /mo/                 usync-por(t) loopb(ack)  _test
force-error        direct-kb(d)         /hw/hs/start-offset      fs-width
/v2/nw             /mix/main-en         sub-en       stat/temp   pstat
mcv0  mcv?  gid    /m/pw                /xyz         bclk
200 OK well hmm    "%s:<<%s>>"          bug in vfprintf: bad
```

`/v2/nw`, `force-error`, `_test`, `loopb(ack)` and `panic` are the interesting
ones — a second-generation network path, a deliberate fault injector, a loopback
test mode and a panic. None appears in `las-sc`, so none has ever been exercised
by the shipping host.

**Voice-card command surface** (`vx-a`, 0x1BAC0-0x1C600) — this is the whole
thing, and it is what a voice card is:

```
ping                            liveness
hw   vaen  led0  sdac  hpf  sr  raw hardware: VCA enable, LEDs, DACs, HPF, slew
adc  temp_alpha  dsptime        telemetry
red-noise-gai(n)                the noise source
start-offset  fs-width  (s)hift oscillator phase/frame timing
pulse_inv  ph0  ofsco  phco     pulse invert, phase 0, offset/phase compensation
rco  tpd  tune  tc  dftc  aut   tuning: temperature coeff, default tc, auto
ctl  ...ast_bulk                bulk transfer
cal  min-main-vca  save_ca(l)   calibration + persist
data save  load  tuning         tuning table load/store
pid  pi                         the oscillator PID loop
osc  mix  dbg  ...l_report      oscillator control and debug reporting
mmcv?  ssta  stat               status
```

Plus the reply vocabulary — `400`, `404 Not foun(d)`, `Malformed messag(e)`,
`successful`, the printf template `%s voice %d: %s error %d`, and, decisively,
**`address set to %d`**: this is how a card that is byte-identical to the other
fifteen learns which voice it is. The address is assigned at runtime over the
bus, exactly as expected.

The voice card also has an OSC address of its own, `/e/q`, and the type-tag
table `,b ,f ,h ,s ,ss ,iiii` with `#bundle` — a full OSC parser lives on each
card.

**The voice card has essentially no plaintext.** Outside 0x1BAC0-0x1C600 the
image is 90% code. There is no address table on the card comparable to the
controller's: the controller does the name resolution and the card speaks a
compact binary/short-name protocol.

### 3.2 The host-side namespace

Extracted from `las-sc`, `las-frontend`, `las-watchdog`, `las-dwm`,
`las-frontpanel-poll` and the SuperCollider sources. ~35,000 concrete addresses
collapsing to ~3,000 families; `/p` alone is ~33,500 addresses because the step
sequencer is fully addressable (`/p/part/t/{1..3}/p/seq/n/l/{0..29}/s/{0..63}/{g,n,r,t,v}`).

Two coexisting shapes: a flat per-synth form used inside `las-sc`
(`/p/o1/…`, `/p/e1/…`) and the frontend's fully-qualified
`/p/part/t/{1..3}/p/…`. The members are identical; the flat form applies to
whichever timbre is active.

| family | what | notable members |
|---|---|---|
| `/p` | the preset/parameter tree | `o{1,2,3}` `p{1,2,3}` `e{1,2,3,4}` `l{1,2,3,4}` `fa` `fb` `f` `noise` `m` `mix` `lc` `fx/ins` `clk` `modmatrix` `arp` `seq` |
| `/cal` | calibration, 168 families | `o{N}/{l,h,x}` `ladf` `ladr` `gldr` `gsvf` `svf1f` `svf2r` `mainl` `noisecw` `rm` `extin` `biasfa` `biasfb` `hpf` `decay` `aux{1,2}` `lhck` `lk` `rk` `cv/{N}` `testosch` |
| `/a` | voice allocation, routing, metering | `max-voices` `max-stack` `note-steal` `note-limit` `mono` `mono-note-pri` `pri` `rnd` `hold` `unison/{en,max-stack,pitch-spread}` `chord/{en,ofs}` `main` `hph` `aux1..4` `dir{N}-aux{N}` `subl` `subr-en` `stat/{mainl,mainr,send1,send2,cvin0,cvin1}` |
| `/mix` | mixer matrix | `o{1,2,3}/{fa,fb}` `n/{fa,fb}` `rm/{fa,fb}` `ext/{ext0,ext1,fa,fb}` `bal` `aux-bal` `g` `main-en` `sub-en` `subl-en` `subr-en` `dir1..4` `mute` |
| `/in` | inputs | `local/{en,note-min,note-max}` `midi/{ccmap,ch,en,tr,note-min,note-max}` `midi_out/en` `com/{tuning,tr,note-min,note-max}` `cv/{N}/{dest,en,in-min,in-max,out-min,out-max}` `usb` `rseq/{en,id}` |
| `/hw` | hardware | `cvo0..3` `cvin0,1` `cvout/{N}` `expr0,1` `ph` `ph0` `ph1` `sus` `mute` `hpf` `autor` `autoroute` `reset_khz` `enable_pid` `hs/start-offset` |
| `/g` | per-group timbre | `{0,1,2}/t/{aux1,aux2,mix/{dir1-en..dir4-en,g,main-en,pan,sub-en}}` |
| `/r` | panel / remote routing | `din-out` `g/{N}/l{1..4}/r` `sq/{N}/{c/{N},midi}` `sys/local/en` `rLED` |
| `/therm` | thermal | `sys-temp` `vx-temp-avg` `min-som` `min-vx` `fan-normal-max` `ttrip-sys` |
| `/info` | identity | `version` `versionb` `git` `vc-git` `vc-version` `fwrev` `hwrev` `product` `voice-count` `uuid` `serial` `mac` `comment` `protect` `write` |
| `/fx*` | three effect slots + generic | `fx{0,1,2}/{in,out,dry,dig-dry,g-out,pan,sends,par}` `fxn/{en,g-out,mix,pan}` `fx/{bus-mode,spread,hw-rev}` |
| `/seq` | sequencer destination | `direct-kbd` `dest/{ip,mac,port}` |
| `/testosc` | built-in test oscillator | `freq` `wave` `dac/{0..3}` |
| `/lc` | local control | `kbd/{curve,oct,tr}` `xy/{hold,mode}` `sus/type` `kbd/lhc/…` |
| `/vx`, `/v` | per-card | `/vx/{0..15}/info/hwrev` `/v/voices` `/v/dis` |
| `/fw` | **firmware download** | `start` `data` `version` — see §5 |

**Argument enumerations** recovered next to the setters: waveforms
`tri / saw / pulse / s-h` (and `sqr`, `gldr` for the test oscillator); voice mode
`mono / uni / poly`; note priority `lru / mru / last / soft / loud / rnd`;
stealing `oldest / newest`; portamento `legato / gliss / gated`; band `low / high`;
noise `clockwise / counter-clockwise`; MIDI resolution `7BIT / 14BIT`;
FX bus mode `dual / ser / par / stereo / spread`; and 23 effect type names from
`delay` through `vocoder21` plus the five reverbs `et_room et_hall et_plate
et_shimmer et_blackhole`.

---

## 4. Controller versus voice card

| | controller (`lasvc`) | voice card (`lasvx`) |
|---|---|---|
| Image | 253 KB, 8 segments | 164 KB, 2 segments |
| Copies | one | sixteen, byte-identical |
| Identity | fixed | assigned at runtime — `address set to %d` |
| OSC | full address table, ~300 controller-scoped addresses, `404`/`400`/`503` replies | a parser, one address `/e/q`, short-name commands |
| Job | name resolution, allocation, routing, thermal, fan, USB-net | drives one voice's analog hardware |
| Analog surface | none directly | VCA enable, sample DACs, HPF, slew rate, ADC readback, noise gain, oscillator phase/frame offsets, pulse invert, phase/offset/temperature compensation, per-voice PID tuning loop |
| Persistence | reads/writes SPI flash | reads/writes its own flash: calibration and tuning tables |

The card is where the analog lives. The controller never touches a VCA; it tells
a card to. The tuning/calibration surface on the card — `tune`, `tc`, `dftc`,
`aut`, `cal`, `min-main-vca`, `save_cal`, `data save`, `load`, `tuning`, `pid` —
is the per-voice trim set that `/var/cal/vxcal.db` and `/var/tuning.vxtune`
back up, and it is stored **in the card's own flash**, not on the Linux side.
That is why the internals note says those two files are the only copy: the host
copy is a backup of card-resident state.

---

## 5. Things that must never be sent blind

Ordered by how bad it is. Everything here is a real command visible in the
binaries or the firmware, not a hypothetical.

### Tier 1 — writes flash, can brick

| Thing | Where | Why |
|---|---|---|
| `/fw/start`, `/fw/data`, `/fw/version` | `las-sc` `vxfw-lib.scm` | The raw firmware-download protocol to a voice card. 200-byte blocks with an address. Sending these by hand, or interrupting a stream, writes XMOS flash. Log strings `cannot start fw download`, `failure in send-block`. |
| `flashrom -l /usr/share/xmosfw/las_layout -i firmware -w <file> -p linux_spi:dev=/dev/spidev0.0` | `las-sc`, literal | Rewrites the **controller** firmware over SPI. `las-sc` will do this even after a network error — the string `Flashing VC Anyway` is in the binary. |
| `las-sc --cli` with `--vcfw/--vxfw/--force-vx-update` | `las-sc` | One invocation reflashes controller and all sixteen cards. `--force-vx-update` explicitly bypasses the version-match guard. |
| `/usr/bin/lasfwu` | via `UpdateFirmwarePanel` | The update tool. It has a `--dry-run`; the panel calls it without. |
| `Read from flash` / `Write to flash complete` handlers | **both firmware images** (`las-b` 0x2AA72, `vx-a` 0x1C0B9) | Both parts expose flash read *and* write over their own protocol, with errors `550 CRC`, `wrong image version`, `magic number`, `length`, `555 Internal error: invalid pointer`. The write path is reachable from the bus, not only from `lasfwu`. |
| `config-las-spi xmos` / `config-las-spi som` | `las-sc`, `las-watchdog`, `S25xmosfw` | Not a flash, but a hard reset of the XMOS SPI bus. Run mid-flash or mid-calibration and a normal boot becomes a hang. This is also what the watchdog fires automatically. |

### Tier 2 — writes calibration or tuning, persists, needs a power cycle

* `/save_cal`, `/cal/save`, `/cal:save`, `/save_tuning`, `/load_tuning`,
  `/load_cal`, `/save_pid` — commit to the calibration DB and to the cards.
  The panel path runs `vxtune write -c vc -f /var/tuning.vxtune`.
* **The entire `/cal/*` tree**, 168 families. Each one writes a trim, offset or
  gain-line coefficient into a live voice card: `/cal/o{N}/{l,h,x}`,
  `/cal/ladf/{x0,x1}`, `/cal/ladr/{l,h}`, `/cal/svf1f`, `/cal/svf2r`,
  `/cal/gldr`, `/cal/gsvf`, `/cal/biasfa`, `/cal/biasfb`, `/cal/noisecw`,
  `/cal/mainl/x`, `/cal/rm`, `/cal/extin`, `/cal/hpf`, `/cal/decay`,
  `/cal/aux{1,2}`, `/cal/cv/{N}`, `/cal/lk`, `/cal/rk`, `/cal/lhck/*`.
* `/cal:cal_default`, `/cal/lk:cal_{low,mid,high}`, `/cal/rk:cal_{low,mid,high}`,
  `/cal/lhck/xy:cal_{ul,lr}` — reset or re-point panel and left-hand-controller
  calibration.
* `/hw/enable_pid`, `/hw/reset_khz`, `/o{N}/hw/enable_pid_cal` — the oscillator
  PID auto-tune. The frontend's own copy takes "up to ten minutes" for one pass
  and "several hours" for a full calibration.
* `/testosc/dac/{0..3}`, `/testosc/freq`, `/testosc/wave` — raw DAC codes into
  the analog path, bypassing normal limits.
* On the card itself: `save_ca(l)`, `data save`, `tune`, `aut`, `dftc`,
  `min-main-vca`. These are the same operations one level down.

### Tier 3 — destroys data or identity

* Reset calibration database (`voiceCalReset`): `DELETE FROM …` against
  `/var/cal/vxcal.db`. The panel says `DATABASE CANNOT BE RECOVERED AFTER RESET`.
* Legacy-data write (`voiceCalLegacyWrite`): overwrites current card calibration.
* `/info/write` with `/info/serial` and `/info/mac` — writes the instrument's
  serial number and MAC. `/info/protect` and `/info/uuid` sit next to it.
* Factory-restore paths: `POPULATING WITH FACTORY DATA`, `CREATE FACTORY`,
  `RESTORE DEFAULT SETTINGS`.
* `FormatUSBDrivePanel` — erases the attached USB device.

### Tier 4 — the lock-up mechanism

`/reset`, and anything that makes the controller briefly unresponsive. The
watchdog is watching: on a missed ping it runs `kill -9 $(fuser 9799/udp)`,
`/etc/init.d/S42sc stop/start`, `killall scsynth sclang screen`, and the SPI
power-cycle. A probe that stalls the controller for a second will restart the
whole audio engine, which is what a lock-up looks like from the front panel.

### The trap that matters most

**Most `/cal/*` and `/hw/*` addresses are the same address for reading and
writing. Sending one with no arguments is a query; sending it with a value is a
write.** There is no separate setter namespace to avoid. This is why `vxq.py`
sends zero-argument packets and self-tests against `/info/product` (known-good)
and `/definitely/not/an/address/here` (known-404). Keep every probe
zero-argument, and never send `/fw/*` at all.

One more, not a hardware risk but worth knowing it is there: `las-dwm` embeds
`sshpass -p<redacted> ssh -N -T -y -R22222:localhost:22 -p4448 las@remote.moogmusic.com`
and logs to `/var/log/phonehome.log`. A reverse SSH tunnel to the vendor, with a
hardcoded password, gated behind a splash screen.

---

## 6. Reproducing this

```sh
uv run python3 recon/strtab_decode.py --report      # regions and reference statistics
uv run python3 recon/strtab_decode.py --verify      # the format against ground truth
uv run python3 recon/strtab_decode.py --rosetta     # the cross-encoding laws
uv run python3 recon/strtab_decode.py --merge       # text one encoding spells, the other references
uv run python3 recon/strtab_decode.py --dump las-b  # item-by-item listing of a region
uv run python3 recon/strtab_decode.py --fragments   # every recoverable literal
```

The parameter sweep (`--search`) is gone: `decompressor.md` §4 proves the space
it was searching cannot contain the answer.

Nothing in this file requires, or should be checked against, a powered
instrument. The `/status` reply forms quoted in §2.4 come from
`docs/MOOG-ONE-INTERNALS.md`, which recorded them from a live unit in an earlier
session.
