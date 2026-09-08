# The MIDI stack, and whether MIDI 2.0 is achievable on this instrument

Written 2026-09-08 against the v1.5.0 unit. Nothing here touched the instrument;
every finding comes from `captures/` on local disk.

Every claim is graded:

* **[READ]** — read directly out of a binary, a filesystem image, a capture, or a
  vendor PDF. File and offset/line given.
* **[TESTED]** — observed on hardware. Where the test was run in an *earlier*
  session and I am relying on the recorded result, it is marked
  **[TESTED, prior]** and the recording is cited.
* **[INFERRED]** — reasoning over the above.
* **unknown** — said plainly where that is the honest answer.

---

## 0. The short version

The Moog One's MIDI stack **is not on the Linux board**. Both the DIN jacks and
the rear USB-B socket belong to the XMOS interface board; the i.MX6 kernel has
no USB gadget framework at all, no ALSA rawmidi, and both of its USB controllers
are configured as **hosts** in the device tree. The USB MIDI class descriptors the
Mac sees are baked into `app_las_v2.1.2.bin` — the encrypted, signed XMOS
controller image — not into anything Linux can be persuaded to emit.

That single fact settles the headline question. USB MIDI 2.0 needs a USB **device**
that speaks the MIDI 2.0 class. The only USB device in this instrument is an XMOS
xcore-200 running closed firmware we cannot build, and the Linux kernel that *could*
in principle be upgraded is not on the wire at all. Kernel 6.5's `f_midi2` and
`snd-ump` would land on a board with nothing to plug them into.

The verdict, argued in §9: **possible on the host side only** — and that is not a
consolation prize, because the instrument already exposes a float-valued OSC
parameter tree that is *higher* resolution than MIDI 2.0's own CC space is useful
at on this hardware.

---

## 1. The MIDI path, end to end

### 1.1 Which processor owns which MIDI surface

| surface | physical location | owned by | evidence |
|---|---|---|---|
| MIDI IN / MIDI OUT 1 / MIDI OUT 2 (5-pin DIN) | interface board | XMOS | §1.2, §1.3 |
| USB-B "USB" client socket → host computer | interface board | XMOS | §1.3, §3.3 |
| USB-A "USB HOST" socket | jack on the interface board, wired to the i.MX6 | Linux — **but no MIDI class driver exists**, §5.6 | §5.6 |
| LAN (RJ45) | interface board, bridged to Linux over USB | XMOS | §1.4 |

The interface board `PCB-01-011-1200` carries **two XMOS XU216-512-TQ128-C20**
parts (U26, U28) — the *U* series, i.e. **with an integrated USB 2.0 PHY** — and
the MIDI IN / MIDI OUT 1 / MIDI OUT 2 DIN jacks, the RJ45, the USB-A host jack and
the USB-B client jack are all on that board. **[READ]** —
`docs/arch/hardware-external.md:513-526`, from board photographs in an earlier pass.

Two USB-capable XMOS parts is exactly what the firmware needs: `app_las_v2.1.2.bin`
contains **two distinct USB device descriptor sets** (§3.3).

### 1.2 The Linux side is provably not in the MIDI path

Four independent reads, any one of which would be suggestive; together they are
conclusive.

1. **No ALSA rawmidi in the kernel.** `/lib/modules/4.1.15-rt18/modules.builtin`
   lists `snd-seq`, `snd-seq-device`, `snd-seq-midi-event`, `snd-seq-dummy`,
   `snd-seq-oss`, `snd-pcm`, `soundcore` — and **no `snd-rawmidi`, no
   `snd-seq-midi`, no `snd-usb-audio`**. `modules.dep` lists exactly two loadable
   modules on the whole system, `imx_rpmsg_pingpong.ko` and `imx_rpmsg_tty.ko`, so
   nothing can be loaded later either. **[READ]** — v1.5.0 rootfs,
   `/lib/modules/4.1.15-rt18/modules.builtin`, `/lib/modules/4.1.15-rt18/modules.dep`.

2. **Nothing on the box knows the MIDI baud rate, or opens a UART.** The string
   `ttymxc` does not occur **anywhere** in the 767 MB v1.5.0 root filesystem
   (`grep -c -a ttymxc` → 0), and `31250` does not occur in `las-frontend` at all.
   **[READ]**. A DIN MIDI receiver on the i.MX6 would need both.

3. **`las-frontend`'s only MIDI backend is JUCE's ALSA *sequencer* client**, and it
   has no ports to bind to. The binary imports 29 `snd_seq_*` symbols plus
   `snd_midi_event_{new,free,encode,decode,reset_encode,reset_decode}` from
   `libasound.so.2`, and carries the JUCE class names
   `juce::(anonymous)::AlsaClient::MidiInputThread` and `juce::(anonymous)::AlsaClient`.
   **[READ]** — `las-frontend` `.dynstr` at 0x38cd-0x415a, RTTI strings for
   `*N4juce12_GLOBAL__N_110AlsaClient15MidiInputThreadE`. With `snd-seq-midi` and
   rawmidi absent, `snd_seq_query_next_client` returns no hardware ports, which is
   what the failure strings `Couldn't find MIDI input port "` (0x7ea570b) and
   `Couldn't find MIDI output port "` (0x7ea728e) exist for.

4. **The flags that would use it are not passed.** `--midi-in=<name>` /
   `--midi-out=<name>` ("Name of MIDI input/output device", usage block 0x7ea5fd3)
   exist, and the live `las-frontend` command line has neither. **[READ]** —
   `captures/arch-harvest/runtime-state.txt`, process 915. The command line is
   written out in full in `/etc/init.d/S43gui` **[READ]**, v1.5.0 rootfs — that is
   the only place it could be added, and `S43gui` also owns the three xterms,
   `las-dwm`, the startup-cookie handshake and the display flip, so it is not a
   light thing to restart.

Corroborating this from the other end: playing eight notes into the USB port
produced **zero packets on `lo`**, while `usbint` carried them as performance
messages from `203.0.113.2`. **[TESTED, prior]** —
`docs/MOOG-ONE-INTERNALS.md:1117-1123`.

### 1.3 What the XMOS controller actually owns

The controller's compressed string table (region `las-a`, `0x029800..0x02A800` of
the bit-reversed `app_las_v2.1.2.bin`) contains, as literals in one contiguous run
of NUL-separated address tokens at `0x029D84..0x029F20`:

```
nodect  voices  /v/voices  dis  load-timbre  set-group  note-enable
mi(di)  transpose  ch  local  usb  seq  bclk  com  mid(i)  …-out  thru
source  panic  lasv  /r/sq/  all  rtz  /mo/  g/  l/m/  mw …
```

and at `0x02A090..0x02A0A6`:

```
ccma(p)   cc-filter-enabl(e)
```

**[READ]** — `uv run python3 recon/strtab_decode.py --dump las-a`. So the voice
controller owns, by name: **midi**, **midi-out**, **thru**, **source**, **panic**,
**bclk** (beat clock), **transpose**, **note-enable**, **local**, **usb**, **com**,
the **ccmap**, and a **cc-filter-enable**. `/mo/` — the MIDI-out injection address —
is a controller address, and `/r/sq/` is the sequencer's.

`thru` and `cc-filter-enable` do not appear in any existing project document.

The i.MX6-side view of the same tree (`las-sc` and `las-frontend` address tables)
shows the settable half: `/in/midi/{en,ch,tr,ccmap,note-min,note-max}`,
`/in/midi_out/en`, `/p/part/midi/din-out/in`, `/r/din-out`, `/r/sq/N/midi`.
**[READ]** — `las-sc` strings; `docs/arch/xmos-firmware.md:290-293`.

### 1.4 The whole path, in order

```
                            ┌─────────────── interface board (2× XMOS XU216) ───────────────┐
 DIN MIDI IN ──────────────►│ MIDI parser: status bytes, running status, channel filter,     │
 USB-B (2662:000d,          │ port merge (din/usb), note-min/max, transpose, ccmap,          │
   MIDIStreaming) ─────────►│ cc-filter, panic, MIDI clock (bclk)                            │
                            │            │                              │                   │
                            │            ▼                              ▼                   │
                            │   voice allocator  ──► 16 voice cards   OSC performance msgs   │
                            └──────────────────────────────┬───────────────────────────────┘
                                                           │ USB CDC "LAS internal" (2662:800d)
                                                           │ usbint 203.0.113.2 → .1  UDP :7772
                                                           ▼
                            ┌──────────────── i.MX6 (Linux 4.1.15-rt18) ────────────────────┐
                            │ las-frontend  ,iifi 4 <note> <vel±0.0> 0   note on/off        │
                            │               ,ii   8 <voice mask>                            │
                            │  MidiMapping / MIDI learn / PerformanceSetPanel::              │
                            │  handleProgramChange / MidiClockListener                       │
                            │            │  /mo/din0  iii  ┐                                │
                            │            │  /mo/usb0  iii  ├─ MIDI OUT bytes, back to the VC │
                            │            └─────────────────┘   on 203.0.113.2:7770           │
                            └───────────────────────────────────────────────────────────────┘
```

**[READ]** for the address names and the message shapes
(`src/moogone/performance.py`, `docs/MOOG-ONE-INTERNALS.md:705-709`,
`docs/arch/control-plane.md:280`); **[TESTED, prior]** for the note/voice-mask
decoding; **[INFERRED]** for the box labelled "MIDI parser" — no capture of the
DIN path exists and the XMOS code is compressed, so *that the parser is there* is
inference from (1.2) plus the address names in (1.3), not a direct read of parser
code.

### 1.5 The gap I could not close

**How an incoming MIDI CC reaches `las-frontend` is unknown.** It must reach it:
MIDI learn ("`LISTENING FOR MIDI CC MESSAGES...`", 0x7e7fd94) needs the CC number,
`PerformanceSetPanel::handleProgramChange(int)` exists, and v1.8.0's release notes
describe MIDI CC causing **panel lag** — which is i.MX6-side by definition. But the
only performance opcodes ever observed on port 7772 are **4 (note)** and
**8 (voice mask)**, and both captures that exist were note-only.
**[READ]** — `src/moogone/performance.py:30-45`; **unknown** — the CC opcode.

Closing it needs one capture: `tcpdump -i usbint udp port 7772` while a CC is sent
into the DIN or USB port. That is the single highest-value MIDI capture still
missing, and it is a passive read.

---

## 2. The kernel

| fact | value | evidence |
|---|---|---|
| kernel version | **4.1.15-rt18** (Linux 4.1.15, `PREEMPT_RT` patch 18) | `/lib/modules/4.1.15-rt18/` **[READ]** |
| loadable modules on the system | **two** — `imx_rpmsg_pingpong.ko`, `imx_rpmsg_tty.ko` | `modules.dep` **[READ]** |
| USB gadget framework | **absent entirely** — 0 matches for `gadget`, `udc`, `composite`, `f_midi`, `rawmidi`, `snd-usb` across `modules.builtin` | **[READ]** |
| USB host drivers | `usbcore`, `ehci-hcd`, `ehci-mxc`, `ci_hdrc`, `ci_hdrc_imx`, `usbmisc_imx`, `phy-mxs-usb`, `usb-storage`, `usbhid`, `cdc-acm`, `usbserial` | `modules.builtin` **[READ]** |
| USB **networking** drivers | `usbnet`, `cdc_ether`, `cdc_eem`, `cdc_ncm`, `asix` — all **host-side** | `modules.builtin` **[READ]** |
| ALSA | `snd`, `snd-pcm`, `snd-timer`, `snd-seq*`, `snd-soc-core`, **`snd-soc-moog-xmos`**, **`snd-soc-imx-xmos-esai`**, `snd-soc-fsl-esai` | `modules.builtin` **[READ]** |
| both enabled USB controllers | `dr_mode = "host"` | `/boot/imx6dl-profili-som.dtb`, `usb@02184000` and `usb@02184200` **[READ]** |
| the other two USB controllers | `status = "disabled"` (HSIC) | same **[READ]** |
| the i.MX6's own Ethernet MAC | `ethernet@02188000 { … status = "disabled"; }` | same **[READ]** |

Two consequences worth stating separately.

**The i.MX6 cannot be a USB device.** Not "is not configured as one" — *cannot*.
There is no gadget function driver, no `libcomposite`, no UDC glue compiled in,
and the OTG controller is pinned to host mode in the device tree. Making it one
would take a kernel rebuild *and* a device-tree change *and* new hardware routing,
because the USB-B jack is not wired to it. **[READ]** + **[INFERRED]**.

**All of the instrument's networking rides through the XMOS.** The i.MX6's FEC is
disabled, so the rear RJ45 is not on the SOM. `udev` binds interfaces by MAC:

```
20-xmos-nic.rules   ATTR{address}=="02:00:00:00:00:00"  → usbint  (203.0.113.1/24)
50-eth-ext-nic.rules ATTR{address}=="a4:11:63:b*"       → ethext  (the RJ45, DHCP)
30-usb-nic.rules    ATTR{address}=="8c:ae:4c:*"         → usbext  (a USB Ethernet dongle)
```

**[READ]** — v1.5.0 rootfs `/etc/udev/rules.d/`. The string `GA41163B0FFFE` —
a MAC in exactly the `a4:11:63:b*` range that the `ethext` rule matches — appears
inside `app_las_v2.1.2.bin` at 0x11c17 (bit-reversed), immediately next to the USB
string descriptors `LAS internal` (0x11c25) and `Moog` (0x11c35). **[READ]**. So
`ethext` is a second CDC network function presented by the XMOS over the same
internal USB link — which is why the "LAS internal" configuration declares
**four** interfaces (two CDC functions × two interfaces each). **[INFERRED]**, and
it is the only reading consistent with the FEC being disabled.

The three interface scripts differ. `usb-int.sh` only renames the link and pins a
static ARP entry (`arp -i usbint -s 203.0.113.2 02:00:00:00:00:00`). `usb-ext.sh`
and `eth-ext.sh` — the two *external* paths — each install:

```
iptables -t nat -A PREROUTING -i <if> -p udp --dport {7770,7771,9100,9300} \
         -j DNAT --to 203.0.113.2:<same>
```

**[READ]** — `/etc/udev/rules.d/{usb-int,usb-ext,eth-ext}.sh`. The voice
controller's OSC bus is therefore **reachable from the LAN**, deliberately, which
matters in §9.

---

## 3. The USB descriptors, as actually configured

### 3.1 Two device descriptors, both in the XMOS image

Searching the bit-reversed `captures/arch-harvest/app_las_v2.1.2.bin` for the
16-bit LE pattern `62 26` (VID 0x2662) yields exactly two hits, and both sit at the
head of a well-formed USB device descriptor. **[READ]**

**0x11ca0 — the internal link:**

```
12 01 00 02 EF 02 01 40 62 26 0D 80 00 00 01 05 …
                         └PID 0x800D┘
09 02 85 00 04 01 00 C0 00     config: 133 bytes, 4 interfaces, cfg 1, self-powered
```

Strings in the same block: `LAS internal`, `Moog`, `GA41163B0FFFE`, `0200`.
This is the CDC-network composite the i.MX6 hosts. **[READ]**

**0x2ae85 — the rear USB-B socket:**

```
12 01 00 02 EF 02 01 40 62 26 0D 00 F2 06 01 03 …
                         └PID 0x000D┘ └bcdDev 0x06F2┘ iMfr=1 iProd=3
```

**[READ]** Every field matches the live macOS enumeration of the instrument
captured 2026-09-05 (`usb.plist`, IORegistry entry "Moog One"): `idVendor 9826`
(0x2662), `idProduct 13` (0x000D), `bcdDevice 1778` (0x06F2), `bcdUSB 512` (0x0200),
class/subclass/protocol 239/2/1, `iManufacturer 1`, `iProduct 3`, `iSerialNumber 0`,
`bNumConfigurations 2`, `UsbLinkSpeed 480000000` (**High Speed**).
**[TESTED, prior]**

macOS also records the flattened interface signature
`UsbDeviceSignature = 62 26 | 0D 00 | EF 02 01 | 01 01 20 | 01 01 00 | 01 03 00`
**[READ]** — i.e. three interfaces:

| # | class | subclass | protocol | meaning |
|---|---|---|---|---|
| 0 | 0x01 Audio | 0x01 AudioControl | **0x20** | UAC **2.0** audio-control function |
| 1 | 0x01 Audio | 0x01 AudioControl | **0x00** | UAC **1.0** audio-control function |
| 2 | 0x01 Audio | **0x03 MIDIStreaming** | 0x00 | the MIDI interface |

### 3.2 The 143-byte configuration, reconstructed

The descriptor bytes in the firmware are LZ-packed with the same token scheme as
the string tables (`docs/arch/decompressor.md`), so some bytes are literals and
some are back-references. The literals are **[READ]**; the reference-filled bytes
are **[INFERRED]** from USB class structure — and the inference is tightly
constrained, because `wTotalLength = 0x008F = 143` is read directly, the
MIDIStreaming `wTotalLength = 0x0041 = 65` is read directly, and the descriptor
sizes then sum to exactly 143 with no slack.

```
09 02 8F 00 03 01 00 C0 00   CONFIGURATION  143 bytes, 3 interfaces, cfg 1,
                             bmAttributes 0xC0 (self-powered), bMaxPower 0
08 0B 00 01 01 00 20 00      INTERFACE ASSOCIATION  first=0, count=1,
                             class Audio, subclass 0, protocol 0x20, iFunction 0
09 04 00 00 00 01 01 20 03   INTERFACE 0  0 EPs, Audio/AudioControl/UAC2, iInterface 3
09 24 01 00 02 08 19 00 00   AC HEADER    bcdADC 2.00, category 0x08, wTotalLength 25
08 24 0A 29 03 07 00 09      CLOCK SOURCE   ID 41, internal programmable, iClockSource 9
08 24 0B 28 01 29 03 08      CLOCK SELECTOR ID 40, 1 pin ← 41, iClockSelector 8
09 04 01 00 00 01 01 00 00   INTERFACE 1  0 EPs, Audio/AudioControl/UAC1, iInterface 0
09 24 01 00 01 09 00 01 02   AC HEADER    bcdADC 1.00, wTotalLength 9, collection → IF2
09 04 02 00 02 01 03 00 00   INTERFACE 2  2 EPs, Audio/MIDIStreaming
07 24 01 00 01 41 00         MS HEADER    bcdMSC 1.00, wTotalLength 65
06 24 02 01 01 00            MIDI IN JACK   EMBEDDED, id 1
06 24 02 02 02 0B            MIDI IN JACK   EXTERNAL, id 2, iJack 11
09 24 03 01 03 01 02 01 xx   MIDI OUT JACK  EMBEDDED, id 3, ← jack 2 pin 1
09 24 03 02 04 01 01 01 0A   MIDI OUT JACK  EXTERNAL, id 4, ← jack 1 pin 1, iJack 10
09 05 02 02 00 02 00 00 00   ENDPOINT 0x02 OUT, BULK, wMaxPacketSize 512
05 25 01 01 01               CS ENDPOINT    1 embedded jack: 1
09 05 82 02 00 02 00 00 00   ENDPOINT 0x82 IN,  BULK, wMaxPacketSize 512
05 25 01 01 03               CS ENDPOINT    1 embedded jack: 3
                             ─────
                             = 143 bytes exactly
```

Matching string descriptors are visible in the packed table region `las-b`:
`Moog Music, Inc` (0x2aae1), `(In)ternal Clo(ck)` (0x2ab08), ` Clock Selector`
(0x2aaf4), `MIDI` (0x2ab21), `Ou(t)`. **[READ]**

Two observations:

* The MIDIStreaming block is **the USB-MIDI 1.0 specification's Appendix B.1 sample
  descriptor**, verbatim (one embedded IN jack, one embedded OUT jack,
  `wTotalLength = 0x41`), with the endpoint packet size raised from 64 to 512 for
  high speed. That is the stock XMOS USB-Audio reference-design MIDI block.
  **[INFERRED]**, from the byte-for-byte match with the published example.
* The instrument is **High Speed** and its MIDI endpoints are 512-byte bulk — so
  the wire is not the bottleneck for anything; §5.

### 3.3 Two descriptor defects, and what v1.8.0 probably fixed

v1.8.0's release note reads, verbatim: *"Fixed USB descriptor to improve MIDI
compatiblity with Windows."* **[READ]** — `Moog One Firmware Update v1.8.2.pdf`.
Two candidate bugs are visible in the v1.5.0-era firmware and either would produce
exactly that symptom.

**Defect A — `bNumConfigurations = 2`, but only one configuration exists.**
The device descriptor advertises two configurations. A live read using
`IOUSBLib`'s `GetConfigurationDescriptorPtr` (which indexes macOS's own
enumeration cache and returns `kIOReturnNotFound` past the end, so it is answering
honestly) returned **two byte-identical 143-byte configurations, both carrying
`bConfigurationValue = 1`**. **[TESTED, prior]** —
`docs/MOOG-ONE-INTERNALS.md:1090-1101`. Searching the firmware confirms the other
half: the pattern `02 8F 00` (a configuration descriptor of length 143) occurs
**exactly once** in the whole image, as does the interface-association pattern
`0B 00 01 01 00 20`. **[READ]** So there is one configuration in ROM and the device
reports two. Two configurations sharing a `bConfigurationValue` is illegal — there
is nothing for `SET_CONFIGURATION` to choose between. Windows enumerates every
configuration at start-of-day; macOS and Linux take configuration 1 and never look.

**Defect B — the interface association descriptor covers one interface out of three.**
The IAD is `bFirstInterface 0, bInterfaceCount 1`. Interfaces 1 (UAC1 AudioControl)
and 2 (MIDIStreaming) are **not covered by any IAD**, and there is only one IAD in
the image **[READ]**. On a device declaring `bDeviceClass/SubClass/Protocol =
EF/02/01`, Windows' `usbccgp` composite parent uses IADs to group interfaces into
functions and enumerates every *ungrouped* interface as its own child device — so
`usbaudio.sys` would be handed an AudioControl interface (IF1) and a MIDIStreaming
interface (IF2) in **separate device stacks**, and would not associate them.
The classic result is "no MIDI ports on Windows, works fine on Mac".
**[INFERRED]** — the descriptor bytes are read; the Windows enumeration behaviour
is general knowledge, not something I verified here.

I cannot tell which one 1.8.0 fixed, or whether it fixed both: the fix lives in the
XMOS image, the XMOS image lives inside `pkg/rootfs`, and `pkg/rootfs` is still
GPG-encrypted. §10 lists exactly what to re-check.

---

## 4. What MIDI 1.0 capability this instrument actually has

This matters because it is the yardstick MIDI 2.0 has to beat.

### 4.1 14-bit CC, per mapping, auto-detected

MIDI learn stores four fields per assignment — `/src_cc`, `/bit_depth`,
`/dst_path`, `/dst_index` — and formats the depth as `" 14Bits"` / `" 7Bits"`.
**[READ]** — `las-frontend` 0x7e41a18-0x7e41a63, class `N3las11MidiMappingE`
(0x7e419f8), `BitMidiValueFormatter`. The panel enum is `7BIT` / `14BIT`
(0x7e41db2). The manual: *"14-bit MIDI CC support is automatically detected, but
can be set to 7 with the RESOLUTION soft knob."* **[READ]** — Moog One manual,
LEARN MIDI CC.

The assignable CC list in the binary runs **CC 0 … CC 127 with CC 84 omitted**
(0x7e41aa6 → 0x7e41dab; the sequence jumps 83 → 85). **[READ]** CC 84 is used by
the instrument's own sequencer MIDI stream — a `las::Sequencer` unit-test string
reads *"First should be the MIDI CC 84 / Second the note On / Third the note Off"*
(0x7e4d330). **[READ]**, with the *meaning* **[INFERRED]**: CC 84 is General MIDI
"portamento control", and the sequencer emits it as a per-step prefix ahead of
each note pair. The UI message for choosing it is `RESERVED CONTROLLER NUMBER X`.

### 4.2 A complete 14-bit NRPN parameter map

`las-frontend --print-nrpns` — *"Print the NRPN numbers that are supported"*
(0x7ea754c) — dumps a table whose column headers and value legends are in the
binary at 0x7ea64ba onward: `SYNTH 1 / SYNTH 2 / SYNTH 3 / OPTIONS or CONTINUOUS`,
with option ranges quantised over **0-16383**. **[READ]**

The same table is printed in full in `Moog One Midi Learn Addendum.pdf`. I decoded
all eight of its NRPN pages out of the PDF's subset-font content streams; the
numbers below are **[READ]**, and the arithmetic checks: every entry satisfies
`NRPN = MSB × 128 + LSB`, and Synth 2 = Synth 1 + 3840, Synth 3 = Synth 1 + 7680.

**120 addressable parameters, each 14-bit, each per-timbre.**


| group | parameter | SYNTH 1 | (MSB,LSB) | SYNTH 2 | SYNTH 3 |
|---|---|---|---|---|---|
| LFO 1 | WAVEFORM | 451 | 3,67 | 4291 | 8131 |
| LFO 1 | RATE FREE | 463 | 3,79 | 4303 | 8143 |
| LFO 1 | RATE SYNCD | 464 | 3,80 | 4304 | 8144 |
| LFO 2 | WAVEFORM | 501 | 3,117 | 4341 | 8181 |
| LFO 2 | RATE FREE | 513 | 4,1 | 4353 | 8193 |
| LFO 2 | RATE SYNCD | 514 | 4,2 | 4354 | 8194 |
| LFO 3 | WAVEFORM | 551 | 4,39 | 4391 | 8231 |
| LFO 3 | RATE FREE | 563 | 4,51 | 4403 | 8243 |
| LFO 3 | RATE SYNCD | 564 | 4,52 | 4404 | 8244 |
| LFO 4 | WAVEFORM | 601 | 4,89 | 4441 | 8281 |
| LFO 4 | RATE FREE | 613 | 4,101 | 4453 | 8293 |
| LFO 4 | RATE SYNCD | 614 | 4,102 | 4454 | 8294 |
| OSCILLATOR 1 | OCTAVE | 152 | 1,24 | 3992 | 7832 |
| OSCILLATOR 1 | FREQUENCY | 151 | 1,23 | 3991 | 7831 |
| OSCILLATOR 1 | BEAT | 156 | 1,28 | 3996 | 7836 |
| OSCILLATOR 1 | SAW | 158 | 1,30 | 3998 | 7838 |
| OSCILLATOR 1 | TRIANGLE | 157 | 1,29 | 3997 | 7837 |
| OSCILLATOR 1 | PULSE WIDTH | 300 | 2,44 | 4140 | 7980 |
| OSCILLATOR 1 | MIX | 900 | 7,4 | 4740 | 8580 |
| OSCILLATOR 1 | WAVE | 150 | 1,22 | 3990 | 7830 |
| OSCILLATOR 2 | OCTAVE | 202 | 1,74 | 4042 | 7882 |
| OSCILLATOR 2 | FREQUENCY | 201 | 1,73 | 4041 | 7881 |
| OSCILLATOR 2 | BEAT | 206 | 1,78 | 4046 | 7886 |
| OSCILLATOR 2 | SAW | 208 | 1,80 | 4048 | 7888 |
| OSCILLATOR 2 | TRIANGLE | 207 | 1,79 | 4047 | 7887 |
| OSCILLATOR 2 | PULSE WIDTH | 350 | 2,94 | 4190 | 8030 |
| OSCILLATOR 2 | MIX | 904 | 7,8 | 4744 | 8584 |
| OSCILLATOR 2 | WAVE | 200 | 1,72 | 4040 | 7880 |
| OSCILLATOR 2 | HARD SYNC | 217 | 1,89 | 4057 | 7897 |
| OSCILLATOR 3 | OCTAVE | 252 | 1,124 | 4092 | 7932 |
| OSCILLATOR 3 | FREQUENCY | 251 | 1,123 | 4091 | 7931 |
| OSCILLATOR 3 | BEAT | 256 | 2,0 | 4096 | 7936 |
| OSCILLATOR 3 | SAW | 258 | 2,2 | 4098 | 7938 |
| OSCILLATOR 3 | TRIANGLE | 257 | 2,1 | 4097 | 7937 |
| OSCILLATOR 3 | PULSE WIDTH | 400 | 3,16 | 4240 | 8080 |
| OSCILLATOR 3 | MIX | 908 | 7,12 | 4748 | 8588 |
| OSCILLATOR 3 | WAVE | 250 | 1,122 | 4090 | 7930 |
| OSCILLATOR 3 | HARD SYNC | 267 | 2,11 | 4107 | 7947 |
| PITCH MODULATION | LFO 1 AMOUNT | 850 | 6,82 | 4690 | 8530 |
| PITCH MODULATION | MOD EG AMOUNT | 851 | 6,83 | 4691 | 8531 |
| RING MOD | SOURCES | 52 | 0,52 | 3892 | 7732 |
| WAVEFORM MODULATION LFO 3 | WAVE ANGLE | 852 | 6,84 | 4692 | 8532 |
| WAVEFORM MODULATION LFO 3 | PULSE WIDTH | 853 | 6,85 | 4693 | 8533 |
| FREQUENCY MODULATION | FM AMOUNT | 66 | 0,66 | 3906 | 7746 |
| FREQUENCY MODULATION | ROUTE | 65 | 0,65 | 3905 | 7745 |
| NOISE | ATTACK | 802 | 6,34 | 4642 | 8482 |
| NOISE | RELEASE | 805 | 6,37 | 4645 | 8485 |
| NOISE | SUSTAIN | 804 | 6,36 | 4644 | 8484 |
| NOISE | COLOR MIX | 801 | 6,33 | 4641 | 8481 |
| NOISE | COLOR | 800 | 6,32 | 4640 | 8480 |
| POLYPHONY | DETUNE | 1211 | 9,59 | 5051 | 8891 |
| POLYPHONY | MONO | 1203 | 9,51 | 5043 | 8883 |
| POLYPHONY | UNISON | 1209 | 9,57 | 5049 | 8889 |
| MIXER | OSC 1 LEVEL | 901 | 7,5 | 4741 | 8581 |
| MIXER | OSC 1 SVF | 902 | 7,6 | 4742 | 8582 |
| MIXER | OSC 1 LADDER | 903 | 7,7 | 4743 | 8583 |
| MIXER | OSC 2 LEVEL | 905 | 7,9 | 4745 | 8585 |
| MIXER | OSC 2 SVF | 906 | 7,10 | 4746 | 8586 |
| MIXER | OSC 2 LADDER | 907 | 7,11 | 4747 | 8587 |
| MIXER | OSC 3 LEVEL | 909 | 7,13 | 4749 | 8589 |
| MIXER | OSC 3 SVF | 910 | 7,14 | 4750 | 8590 |
| MIXER | OSC 3 LADDER | 911 | 7,15 | 4751 | 8591 |
| MIXER | RING MOD LEVEL | 912 | 7,16 | 4752 | 8592 |
| MIXER | RING MOD SVF | 913 | 7,17 | 4753 | 8593 |
| MIXER | RING MOD LADDER | 914 | 7,18 | 4754 | 8594 |
| MIXER | NOISE LEVEL | 915 | 7,19 | 4755 | 8595 |
| MIXER | NOISE SVF | 916 | 7,20 | 4756 | 8596 |
| MIXER | NOISE LADDER | 917 | 7,21 | 4757 | 8597 |
| FILTERS | SVF CUTOFF | 950 | 7,54 | 4790 | 8630 |
| FILTERS | SVF RESONANCE | 952 | 7,56 | 4792 | 8632 |
| FILTERS | LADDER CUTOFF | 1150 | 8,126 | 4990 | 8830 |
| FILTERS | LADDER RESONANCE | 1152 | 9,0 | 4992 | 8832 |
| FILTERS | MIX | 1103 | 8,79 | 4943 | 8783 |
| FILTERS | SVF MODE | 958 | 7,62 | 4798 | 8638 |
| FILTERS | ROUTE | 1102 | 8,78 | 4942 | 8782 |
| FILTERS | LADDER MODE | 1158 | 9,6 | 4998 | 8838 |
| FILTERS | LADDER SLOPE | 1159 | 9,7 | 4999 | 8839 |
| CUTOFF MODULATION | SVF LFO 2 AMOUNT | 955 | 7,59 | 4795 | 8635 |
| CUTOFF MODULATION | SVF EG AMOUNT | 954 | 7,58 | 4794 | 8634 |
| CUTOFF MODULATION | SVF FM AMOUNT | 956 | 7,60 | 4796 | 8636 |
| CUTOFF MODULATION | LADDER LFO 2 AMOUNT | 1155 | 9,3 | 4995 | 8835 |
| CUTOFF MODULATION | LADDER EG AMOUNT | 1154 | 9,2 | 4994 | 8834 |
| CUTOFF MODULATION | LADDER FM AMOUNT | 1156 | 9,4 | 4996 | 8836 |
| FILTER ENVELOPE | ATTACK FREE | 667 | 5,27 | 4507 | 8347 |
| FILTER ENVELOPE | DECAY FREE | 669 | 5,29 | 4509 | 8349 |
| FILTER ENVELOPE | RELEASE FREE | 670 | 5,30 | 4510 | 8350 |
| FILTER ENVELOPE | ATTACK SYNCD | 672 | 5,32 | 4512 | 8352 |
| FILTER ENVELOPE | DECAY SYNCD | 674 | 5,34 | 4514 | 8354 |
| FILTER ENVELOPE | RELEASE SYNCD | 675 | 5,35 | 4515 | 8355 |
| FILTER ENVELOPE | SUSTAIN | 652 | 5,12 | 4492 | 8332 |
| FILTER ENVELOPE | MULTI TRIG | 659 | 5,19 | 4499 | 8339 |
| FILTER ENVELOPE | SYNC | 660 | 5,20 | 4500 | 8340 |
| FILTER ENVELOPE | LOOP | 661 | 5,21 | 4501 | 8341 |
| FILTER ENVELOPE | LATCH | 662 | 5,22 | 4502 | 8342 |
| AMPLIFIER ENVELOPE | ATTACK FREE | 717 | 5,77 | 4557 | 8397 |
| AMPLIFIER ENVELOPE | DECAY FREE | 719 | 5,79 | 4559 | 8399 |
| AMPLIFIER ENVELOPE | RELEASE FREE | 720 | 5,80 | 4560 | 8400 |
| AMPLIFIER ENVELOPE | ATTACK SYNCD | 722 | 5,82 | 4562 | 8402 |
| AMPLIFIER ENVELOPE | DECAY SYNCD | 724 | 5,84 | 4564 | 8404 |
| AMPLIFIER ENVELOPE | RELEASE SYNCD | 725 | 5,85 | 4565 | 8405 |
| AMPLIFIER ENVELOPE | SUSTAIN | 702 | 5,62 | 4542 | 8382 |
| AMPLIFIER ENVELOPE | MULTI TRIG | 709 | 5,69 | 4549 | 8389 |
| AMPLIFIER ENVELOPE | SYNC | 710 | 5,70 | 4550 | 8390 |
| AMPLIFIER ENVELOPE | LOOP | 711 | 5,71 | 4551 | 8391 |
| AMPLIFIER ENVELOPE | LATCH | 712 | 5,72 | 4552 | 8392 |
| MODULATION ENVELOPE | ATTACK FREE | 767 | 5,127 | 4607 | 8447 |
| MODULATION ENVELOPE | DECAY FREE | 769 | 6,1 | 4609 | 8449 |
| MODULATION ENVELOPE | RELEASE FREE | 770 | 6,2 | 4610 | 8450 |
| MODULATION ENVELOPE | ATTACK SYNCD | 772 | 6,4 | 4612 | 8452 |
| MODULATION ENVELOPE | DECAY SYNCD | 774 | 6,6 | 4614 | 8454 |
| MODULATION ENVELOPE | RELEASE SYNCD | 775 | 6,7 | 4615 | 8455 |
| MODULATION ENVELOPE | SUSTAIN | 752 | 5,112 | 4592 | 8432 |
| MODULATION ENVELOPE | MULTI TRIG | 759 | 5,119 | 4599 | 8439 |
| MODULATION ENVELOPE | SYNC | 760 | 5,120 | 4600 | 8440 |
| MODULATION ENVELOPE | LOOP | 761 | 5,121 | 4601 | 8441 |
| MODULATION ENVELOPE | LATCH | 762 | 5,122 | 4602 | 8442 |
| VCA | LEVEL | 50 | 0,50 | 3890 | 7730 |
| VCA | PAN | 51 | 0,51 | 3891 | 7731 |
| OUTPUT | MASTER VOLUME | 1 | 0,1 | - | - |
| OUTPUT | HEADPHONES | 2 | 0,2 | - | - |

`SYNCD` in the table is the addendum's `SYNC’D`. `-` in the SYNTH 2/3 columns means
the parameter is global, not per-timbre.

The `OPTIONS OR CONTINUOUS` column gives the quantisation for switched parameters,
e.g. `LFO WAVEFORM: TRI (0-4095) · PULSE (4096-8191) · SAW (8192-12287) ·
S&H (12288-16383)`; `LADDER SLOPE: 6dB (0-4095) · 12dB (4096-8191) ·
18dB (8192-12287) · 24dB (12288-16383)`; the sync-rate parameters divide
0-16383 into thirteen musical divisions from 64 to 1/64. **[READ]**

### 4.3 The MIDI settings surface

`las::Settings` carries a `midi_control` subtree (schema at 0x7e43b18-0x7e43c35)
**[READ]**:

```
midi_control/
  load_from_preset          UI: LOAD FROM PRESET
  output_running_status     ← no UI label anywhere in v1.5.0
  always_send_nrpn_numbers  UI: ALWAYS SEND NRPN NUM.
  sysex_device_id           ← no UI label anywhere in v1.5.0
  send_pots  send_keys  send_pitch_wheel  send_mod_wheel  send_aftertouch
  send_xy_pad  send_sust_pedal  send_expression
  send_midi_clock  send_midi_start_stop
  receive_midi_clock        UI: RECEIVE MIDI CLOCK
  receive_midi_start_stop   UI: RECEIVE MIDI START/STOP
  assignments               the CC map
```

and a per-preset `midi_io` subtree (0x7e42d3a-0x7e42e73) **[READ]**:

```
midi_io/
  midi_in_ports    "d" | "u" | "b"    DIN / USB / DIN & USB
  midi_in_route    "a" | "p"          ALL SYNTHS / PER SYNTH
  midi_in_channel_{all,synth1,synth2,synth3}      OFF, 1-16
  midi_out_ports / midi_out_route / midi_out_channel_*
  merge_din_in  merge_usb_in  merge_avb_in        default "o"
  seq_midi_out  arp_midi_out
```

Two things stand out.

**`output_running_status` and `sysex_device_id` exist in the settings schema and
have no user interface.** The strings `RUNNING STATUS`, `DEVICE ID`, `SYSEX`,
`SysEx` and `System Exclusive` occur **zero** times in the 145 MB binary; the only
occurrence of the substring `sysex` anywhere is the schema key itself, once, at
0x7e43b65. **[READ]** Both are dead settings in v1.5.0.

**`merge_avb_in` is a third MIDI input port that does not exist.** The token `avb`
appears exactly twice in `las-frontend` — the schema key and one preset value —
and nowhere else; there is no AVB stack, no AVB daemon, no AVTP anything.
**[READ]** It is a reserved slot for network MIDI over the LAN port that was never
implemented, which lines up with the manual's description of the LAN port as being
for *"remote servicing and future expansion"*. **[READ]** — Moog One manual, rear
panel.

### 4.4 SysEx: refuted in one direction, confirmed in the other

The vendor's position — that there is no accessible SysEx implementation — is
**correct**, and the manual contradicts the product.

* The manual says, on the rear-panel page: *"In addition to note data, the MIDI
  ports can be configured to send and/or receive MIDI Clock, controllers,
  expression, SysEx, and more."* **[READ]** — Moog One manual, MIDI (5-PIN DIN).
* There is **no** SysEx UI, no SysEx documentation anywhere in the manual or in any
  release note from v1.0.1 to v1.8.2, no `F0`/`F7` handling strings, and no
  SysEx-related token in the XMOS string tables (`--fragments` over all five
  regions yields nothing). **[READ]**
* The only trace is the orphan `sysex_device_id` setting. **[READ]**
* Externally, the vendor of the only commercial editor says the same thing.
  Sound Quest's *Midi Quest "Moog One CC"*, in their own words, exists because the
  instrument *"doesn't have an accessible SysEx implementation so all communication
  and editing is handled with CC or NRPN messages"*; it stores *"patches as CC
  values"* and cannot read the instrument's patch memory. **[READ]** —
  quoted in `docs/arch/hardware-external.md:618-622`.

So: a SysEx **device ID** was planned, the manual was written as if it shipped, and
it did not. There is no bulk dump, no parameter-by-SysEx, no handshake.

---

## 5. Defects and limits readable from the binaries

### 5.1 The buffer behind "crashes when receiving large amounts of MIDI data"

**I could not find it, and I will not guess.** The honest state:

* The crash is almost certainly **i.MX6-side**, not XMOS-side. Its sibling fix in
  the same release is *"Fixed changing OSC HARD SYNC through MIDI CC causing panel
  **lag** and crashes"* **[READ]** — panel lag is `las-frontend` by definition, so
  the flood is arriving as OSC parameter traffic at the frontend and the frontend
  is the thing falling over. **[INFERRED]**
* No buffer-size or overflow string exists in `las-frontend` that relates to MIDI
  or OSC: every `overflow`/`too many`/`buffer` string in the binary belongs to
  SQLite, libpng or zlib. **[READ]**
* `las-frontend` is stripped (`ELF 32-bit LSB executable, ARM, EABI5 … stripped`)
  **[READ]**, 145 MB, and the constant would be an immediate in code. Finding it
  needs a targeted disassembly around the OSC receive thread — worth doing, but it
  is a separate piece of work and `llvm-objdump` is not installed on this machine.
* **unknown** — the buffer size, the queue depth, and whether the failure is an
  overflow, an allocation storm, or unbounded UI work per message.

What *is* readable is that the wire cannot be blamed. The USB MIDI endpoints are
512-byte high-speed bulk **[READ]**, and DIN is 31.25 kbaud, so "large amounts of
MIDI data" is at most ~3 kB/s from DIN and a few hundred kB/s from USB. The failure
is in what the instrument does per message, not in how fast they arrive.

### 5.2 This is the second heavy-MIDI crash fix, not the first

v1.5.0's own release notes already say *"Heavy MIDI traffic should no longer result
in a crash"* and *"Fix for disappearing MIDI Mapping destinations."* **[READ]** —
`Moog One Firmware Update v1.5.0.pdf`, IMPROVEMENTS AND FIXES. v1.8.0 then says
*"Fixed crashes when receiving large amounts of MIDI data."* **[READ]**

So this class of bug has now been fixed twice, three years apart. Our unit has the
first fix and not the second. `docs/arch/hardware-external.md:657` says "Our v1.5.0
has the MIDI-input crash", which is true of the 1.8.0 defect but reads as if v1.5.0
had never addressed one; worth the qualifier.

### 5.3 Running status

`output_running_status` is a settings field with no UI (§4.3), so on v1.5.0 the
instrument's running-status *transmit* behaviour is whatever the default is, and
that default is not readable from the string table. **unknown.**

For *receive*, running status is mandatory in MIDI 1.0 and the parser is on the
XMOS, which we cannot read. **unknown.** The one indirect signal is a bug that was
fixed rather than a limit: v1.8.0's *"Fixed hanging notes while changing MIDI IN
ports or channels while receiving notes"* **[READ]** is the signature of a parser
whose per-port state (running status byte, partial message) is not reset when the
port/channel selection changes underneath it. **[INFERRED]** Our v1.5.0 has that
bug.

### 5.4 Note-off semantics — a real trap for anything reading the instrument

The instrument transmits note-off as **status 0x80 with a non-zero release
velocity** (values of 43 and 45 observed), not as note-on-with-velocity-0.
**[TESTED, prior]** — `docs/MOOG-ONE-INTERNALS.md:1145-1152`. A decoder that treats
0x80 as note-off only when velocity is zero will hang every note.

Internally the same event is carried as `,iifi 4 <note> <velocity> 0` with
**negative zero** velocity for note-off — `-0.0 == 0.0` is true everywhere, so a
comparison against zero cannot distinguish on from off; the sign bit must be
tested. **[READ]** — `src/moogone/performance.py:15-21`, `Note.is_note_off`.

### 5.5 Channel and port handling

Three synths, each on its own MIDI channel (PER SYNTH) or all on one (ALL SYNTHS),
in and out independently; ports are DIN / USB / both, in and out independently;
channel `OFF` is a valid value. **[READ]** — manual, MIDI I/O, and the `midi_io`
schema. The `merge_*_in` fields imply a per-port merge switch that the settings UI
never exposes. **[READ]** for the fields, **unknown** for the semantics of `"o"`.

Consequence for this project: **MIDI OUT is off in every factory preset.**
`midi_out/en` is `False` in all 398 presets, for every timbre; `usb0/en` is true in
only 13 of them and the master switch is off in those too. `midi_out_ports` = `'b'`
is a routing choice, not an enable. **[TESTED, prior]** —
`docs/MOOG-ONE-INTERNALS.md:1163-1186`.

### 5.6 The USB HOST port cannot do what the manual says it does

The manual: *"the USB HOST port can also incorporate any class-compliant MIDI
device (one that requires no additional software drivers) into Moog One
operations."* **[READ]** — Moog One manual, COMM.

The USB-A host port is on the i.MX6 — a thumb drive appears as `/dev/sda1` mounted
at `/var/local/media/sda1` **[READ]**, `runtime-state.txt` — and the kernel has
**no `snd-usb-audio`, no rawmidi, and no loadable modules to add them**
**[READ]**, §2. A class-compliant USB MIDI controller plugged into that jack
therefore cannot be seen by this firmware. **[INFERRED]**, strongly: the only escape
would be the jack being multiplexed to the XMOS, which is ruled out by the thumb
drive enumerating on Linux.

This is a documented feature that does not exist on v1.5.0. Whether 1.8.x added it
is **unknown** — it would need a kernel change, which is exactly the kind of thing
the encrypted rootfs would settle.

### 5.7 Reserved / special CC numbers

* **CC 84** — excluded from the assignable list; used by the sequencer's own MIDI
  stream. §4.1
* **CC 64 (sustain)** and **CC 66 (sostenuto)** — implemented in both directions
  since v1.5.0. **[READ]** — v1.5.0 notes.
* **CC 2 / 4 / 11 / 74** appear as named CV-output sources
  (`MIDI CC 2 (BREATH)`, `MIDI CC 4 (FOOT PEDAL)`, `MIDI CC 11 (EXPRESSION)`,
  `MIDI CC 74 (BRIGHTNESS)`, 0x7e805d3-0x7e80615) **[READ]** — i.e. these four CCs
  can be patched straight out to a CV jack.
* `RESERVED MIDI CC MAP ASSIGNMENTS` is a documented category in the mapping
  editor; the full reserved list is **unknown** (the binary only carries the
  message, not the set).

### 5.8 A 500 ms editor race, documented as a feature

*"If a MIDI CC number that has been previously mapped to a different control is
selected, then the previous mapping will become unassigned after 500ms."*
**[READ]** — manual, EDIT MIDI MAPPING. Mirrored in the binary by
`MidiMappingRow::unassignDoublons` and
`MidiMappingRow::restoreUnassignedDoublonIfNeeded` **[READ]**. Anything scripting
the mapping editor has to respect that delay or it will silently drop assignments.

---

## 6. What the 1.8.x MIDI overhaul changed, and what our v1.5.0 still has

Verbatim from `Moog One Firmware Update v1.8.2.pdf`, which carries all three
release notes. **[READ]**

**v1.8.0** — *"a hot fix … which focuses on bug fixes and improvements to Moog
One's MIDI support"*:

| # | fix | in our v1.5.0 path? |
|---|---|---|
| 1 | Fixed USB descriptor to improve MIDI compatibility with Windows | only if the owner uses Windows — §3.3 |
| 2 | **Fixed crashes when receiving large amounts of MIDI data** | **yes — directly in our path** |
| 3 | Fixed: when ARP is on, MIDI is output with the original key presses instead of just the ARP | yes if ARP + MIDI OUT are used |
| 4 | Fixed: turning ARP on while already playing only sends ARP notes after one loop | yes, same condition |
| 5 | Fixed EG ATTACK/DECAY/RELEASE SYNC not being MIDI mappable | **yes — nine parameters per timbre** |
| 6 | Fixed LFO RATE SYNC not being MIDI mappable | **yes — four more** |
| 7 | Fixed GLIDE ON and GLIDE RATE not being MIDI mappable | **yes — two more; GLIDE is absent from the NRPN map entirely** |
| 8 | Fixed LADDER filter slope change via MIDI not reflected in UI/panel | yes — display only |
| 9 | Fixed SVF filter mode change via MIDI not reflected in UI/panel | yes — display only |
| 10 | **Fixed changing OSC HARD SYNC through MIDI CC causing panel lag and crashes** | **yes — directly in our path** |
| 11 | Fixed LHC More Semitone Transpose not affecting MIDI note number | yes |
| 12 | **Fixed hanging notes while changing MIDI IN ports or channels while receiving notes** | **yes** |
| 13 | Fixed MIDI PANIC causing the note A5 to trigger | **yes** |
| 14 | Fixed multiple issues with EG LOOP and LATCH | yes |
| 15 | INIT patch changed: all OSC TRI 0%, SAW fastest reset | cosmetic |

**v1.8.1** — regression fix: presets with oscillator hard sync not loading correctly.
**v1.8.2** — regression fixes: envelopes rarely never going silent / never releasing
the voice; toggling KEYBOARD CONTROL ON for one synth stopping voices on the others.

Note that 1.8.1 and 1.8.2 exist **only** to repair regressions introduced by 1.8.0,
and that 1.8.2's first item is a stuck-voice bug. That is worth weighing before
recommending the update.

Note also that the package's own "Past Firmware Update Release Notes" folder runs
v1.0.1 → v1.5.0 and then jumps to the current v1.8.2 **[READ]** — there is no
v1.6.x or v1.7.x note in the distribution. Whether those versions existed is
**unknown**.

**The five that bite this project hardest**, given that the owner drives the
instrument over MIDI and OSC daily: #2 and #10 (crashes under exactly the traffic
pattern an automated controller produces), #12 (hanging notes on a port/channel
switch), #13 (PANIC firing A5 — `tools/midi-panic.py` in this repo sends CC64,
CC66, CC123, CC120, so it is on the panic path), and #5/#6/#7 (fifteen
parameters per timbre that cannot be mapped to a CC on our firmware).

One nuance on #5 and #6 that the release note hides: the nine EG `*_SYNC'D` and
four LFO `RATE SYNC'D` parameters **are already in the NRPN map** (§4.2, and the
2019 addendum lists them) **[READ]**. What 1.8.0 fixed was their absence from the
**MIDI-learn / CC mapping** destination list — a separate mechanism. So on our
v1.5.0 those thirteen are reachable by NRPN today and simply cannot be bound to a
7- or 14-bit CC. GLIDE ON and GLIDE RATE appear in neither: `glide` occurs zero
times in the NRPN table **[READ]**, so those two are genuinely unreachable over
MIDI on v1.5.0.

---

## 7. What MIDI 2.0 would actually buy, on this instrument

MIDI 2.0's headline features, each measured against what is already here.

### 7.1 Resolution — MIDI 2.0 loses to what is already installed

The control-voltage path on each voice card is built from **four TI/Burr-Brown
PCM1681 eight-channel 24-bit DACs per voice**, 32 CV channels per voice, 64 per
card. **[READ]** — `docs/arch/hardware-external.md:66, 87-89`.

| control path | resolution | reachable today? |
|---|---|---|
| MIDI 1.0 CC, 7-bit | 128 steps | yes |
| MIDI 1.0 CC pair / NRPN, 14-bit | 16 384 steps | **yes — 120 parameters, §4.2** |
| MIDI 2.0 CC, 32-bit | 4.29 × 10⁹ steps | no |
| OSC `/p/…` 32-bit float | ~16.7 × 10⁶ steps of mantissa | **yes, today, over the LAN** |
| **the DAC** | **24-bit = 16.7 × 10⁶ steps** | — |

The hardware tops out at 24 bits. A 32-bit float already carries a 24-bit
mantissa, so **the OSC `/p` namespace already saturates the instrument's own
converters**. MIDI 2.0's extra bits would be discarded at the DAC. **[INFERRED]**,
from the DAC part number and IEEE-754.

The one caveat I must flag: whether the XMOS *keeps* full float precision on the
way from `/p` to the DAC, or re-quantises to 14 bits internally, is **unknown**.
The 0-16383 legends in the NRPN table are the MIDI-side quantisation, not
necessarily the internal one. Settling it is a two-hour passive experiment
(sweep a `/p` float in steps below 1/16384 and measure the analog output), and it
is the only measurement that could change this section's conclusion.

### 7.2 Per-note controllers

MIDI 2.0 gives every note its own pitch, and per-note controller channels.
The instrument's *existing* answer is **MPE-shaped rather than MPE**: three
timbres, each on an independent MIDI channel, with a shared voice pool. That gives
three independent expression streams, not sixteen, and there is no per-note
pressure or per-note pitch bend.

Cheaper substitute: **MPE-style channel rotation is not available** (only three
receive channels exist), but **NRPN is**, and the mod matrix accepts `mw`, `padx`,
`pady`, `padz`, `pnt` (pressure), `v` (velocity), `gate` as sources with 71
destinations **[READ]** — SWARM-BRIEF, established from the 222-preset corpus. So
per-*timbre* continuous expression at 14-bit is already there; per-*note* is not,
and MIDI 2.0 would not create it either, because the voice engine's allocator has
no per-note controller concept to route it to. **[INFERRED]**

### 7.3 Property Exchange

This is the one genuine MIDI 2.0 win the instrument lacks: a standard way for a
host to ask the device what its parameters are. The instrument's non-standard
equivalent is far *more* capable — `las-frontend` and `las-sc` expose a queryable
OSC tree of ~35 000 concrete addresses collapsing to ~3 000 families
**[READ]** — `docs/arch/xmos-firmware.md:283-286`, and `captures/p-namespace-keys.txt`
already holds 3 197 harvested keys. Property Exchange would give you *less*
information in a format more tools understand. That is a real trade-off, and it
is an argument for a **host-side translator**, not for on-instrument MIDI 2.0.

### 7.4 Jitter reduction timestamps

Would help in principle. But the instrument's control path already runs through a
USB CDC network hop and a block-rate quantisation on the way to the voice cards,
and neither of those is addressed by a MIDI 2.0 timestamp the XMOS would have to
honour. Whether MIDI timing jitter is even the dominant term here has not been
measured. **unknown.**

---

## 8. The four blockers, named precisely

The brief asks which of these is the blocker and which is merely work. In order of
how fatal they are:

**Blocker 1 — the USB device is not on the Linux board (fatal, and it is the only
one that matters).** The rear USB-B socket is enumerated by the XMOS from
descriptors compiled into `app_las_v2.1.2.bin` **[READ]**, §3. The i.MX6's two
enabled USB controllers are both `dr_mode = "host"` **[READ]**, and its kernel has
no gadget framework of any kind **[READ]**. Upgrading Linux would therefore change
nothing about what the host computer sees. This blocker is not bridgeable by any
amount of Linux work.

**Blocker 2 — the XMOS firmware is closed, encrypted, signed, and flashed over a
path that bricks.** To put USB MIDI 2.0 on the rear socket you would have to
rewrite the XMOS USB device stack. That means: no source; an image that ships
GPG-encrypted inside `pkg/rootfs`; a flashing path (`flashrom -p
linux_spi:dev=/dev/spidev0.0`, `/fw/start` + `/fw/data`) that `docs/arch/xmos-firmware.md`
grades **Tier 1 — writes flash, can brick** **[READ]**; and the XMOS xC toolchain.
Additionally, XMOS's own USB-Audio library gained MIDI 2.0 / UMP support only on
the later xcore.ai generation, not on the xcore-200 XU216 this board uses
**[INFERRED]**, general knowledge, not verified here. Even with the key, this is a
rewrite of a real-time USB stack on a chip that also clocks the entire audio system
(the XMOS is the ESAI bit- and frame-clock master **[READ]**,
`docs/arch/hardware-external.md:459-477`). Getting it wrong stops the instrument
making sound.

**Blocker 3 — `f_midi2` needs Linux ≥ 6.5; this is 4.1.15-rt18 (Dec 2015).**
**[READ]** for the version. The gap is ~40 kernel releases across ten years, on a
vendor BSP whose out-of-tree content includes the Vivante `galcore` GPU driver,
the i.MX IPU/VPU/PXP stack, `PREEMPT_RT`, and **two Moog-specific ALSA drivers,
`snd-soc-moog-xmos` and `snd-soc-imx-xmos-esai`** **[READ]**, for which no source is
on disk. Porting is genuinely large. But note this blocker is **moot** — see
Blocker 1. A 6.5 kernel with `f_midi2` would have no USB device port to bind it to.

**Blocker 4 — `snd-ump` / ALSA UMP, also ≥ 6.5.** Same moot status, and worse:
ALSA UMP is the *internal* representation. Even with it, `las-frontend` speaks the
ALSA **sequencer** API through JUCE **[READ]**, §1.2, and JUCE's MIDI 2.0 support
would have to be present in the exact JUCE version Moog compiled against in 2022.
It is not.

**What is merely work, not a blocker:** everything on the host side. §9.

---

## 9. MIDI 2.0: the honest answer

### Verdict: **possible on the host side only.**

And the reasoning that forces it, in one line each:

1. USB MIDI 2.0 requires a USB **device** speaking the MIDI 2.0 class. The
   instrument's only USB device is the XMOS. **[READ]**
2. The XMOS's descriptors are inside encrypted, signed firmware, on a chip that is
   also the audio master clock, reachable only through a flash path graded as
   brick-capable. **[READ]**
3. The Linux board — the one thing we *can* modify — is not on the USB wire at all,
   has no gadget framework, and is pinned to host mode in its device tree.
   **[READ]**
4. Therefore no change to Linux, at any kernel version, changes what a host
   computer sees over USB. **[INFERRED]**, and it follows directly from 1-3.
5. Meanwhile the thing MIDI 2.0 is *for* — high-resolution, addressable parameter
   control — is already available at higher resolution than the instrument's own
   24-bit DACs can use, over OSC on the LAN. **[READ]** / **[INFERRED]**, §7.1.

A host-side MIDI 2.0 → OSC bridge running on the Mac achieves the entire
user-visible goal with **none** of the firmware risk. macOS has native MIDI 2.0 /
UMP in CoreMIDI (**[INFERRED]** — general knowledge, not verified against this
machine); a virtual UMP endpoint there can accept 32-bit per-note and
per-controller messages from any DAW and translate them into `/p` writes on the
instrument's LAN address. The instrument is already reachable that way: the
`ethext` NAT rules forward UDP 7770/7771/9100/9300 straight to the voice
controller, and `las-sc`'s 9300 as well. **[READ]**, §2. The instrument does not need to know MIDI
2.0 exists. **Say it plainly: this is the right answer.**

The one thing a host-side bridge cannot do is make the *instrument's keyboard*
transmit MIDI 2.0 to the host. That path stays MIDI 1.0 forever on this hardware.
If high-resolution *output* is the goal — MPE-grade expression captured from the
Moog's own keys — the answer is not MIDI 2.0 at all; it is reading the OSC
performance stream, which already carries velocity as a float and the voice mask
as a bitfield **[READ]**, §1.4.

### What the owner could actually have instead, cheapest first

| # | option | cost | risk | what it gets |
|---|---|---|---|---|
| 1 | **Switch MIDI OUT on** — `/p/part/t/{1,2,3}/in/midi_out/en` and `…/usb0/en` per preset | minutes | none | notes and controllers from the Moog's keys reach the Mac in ~1 ms over USB instead of ~373 ms via the SSH/tcpdump `keys` path. Highest value-per-minute setting on the instrument. **[TESTED, prior]** — `docs/MOOG-ONE-INTERNALS.md:1188-1196` |
| 2 | **Use the 14-bit NRPN map you already have** — §4.2, 120 parameters × 3 timbres | hours | none | 16 384-step control of every synth parameter from any sequencer, today, no firmware change. The table in §4.2 is the missing piece and is now written down |
| 3 | **Drive `/p` over OSC on the LAN** for anything that needs more than 14 bits | already built | none | float-valued control that saturates the 24-bit DACs. This is strictly better than MIDI 2.0 would be |
| 4 | **Host-side MIDI 2.0 → OSC bridge on the Mac** — a CoreMIDI UMP virtual endpoint that maps MIDI-CI/per-note/32-bit CC onto `/p` writes | days | none to the instrument | the DAW sees a MIDI 2.0 device; the instrument sees OSC. Delivers the user-visible feature completely |
| 5 | **Set 14-bit resolution per mapping in MIDI learn** (`RESOLUTION` soft knob) rather than accepting the auto-detected depth | minutes | none | removes 7-bit zipper on any control you map by hand |
| 6 | **Capture the CC opcode on port 7772** (§1.5) — one passive tcpdump | an hour | none, read-only | closes the last hole in this document and tells us whether CC input can be observed without the panel |
| 7 | **Inject MIDI into `las-frontend` via ALSA seq** — `snd-seq` and `snd-seq-dummy` are in the kernel, `las-frontend` accepts `--midi-in=<name>`; a small ALSA sequencer client on the i.MX6 could feed it | days | **moderate to high** — the argument list lives in `/etc/init.d/S43gui` **[READ]**, so this means editing an init script and restarting the whole UI, panel and startup-cookie handshake. `S42sc restart` does **not** restart the frontend; it kills `sclang`/`jackd`/`scsynth`/`las-sc` only **[READ]**. Never `reboot` | a MIDI input path that bypasses the XMOS entirely. Speculative: whether the frontend's MIDI-in path actually drives parameters is **unverified** |
| 8 | **Update to v1.8.2** | an evening, plus recalibration risk | **real** — 1.8.1 and 1.8.2 exist only to fix 1.8.0 regressions, one of which was stuck voices | fixes the two crash classes, the hanging notes, PANIC-triggers-A5, and fifteen CC-unmappable parameters. §6 |
| 9 | **Rebuild the Linux kernel to ≥ 6.5 for `f_midi2` / `snd-ump`** | months | high | **nothing**. The USB-B jack is not on this board. Do not do this |
| 10 | **Rewrite the XMOS USB stack for MIDI 2.0** | not feasible | brick | the nominal feature, at the cost of the instrument |

Options 9 and 10 are listed so that they are visibly ruled out, not as candidates.

---

## 10. What I would re-check once `pkg/rootfs` is decrypted

Ordered by how much it would change this document.

1. **`/usr/share/xmosfw/app_las_v*.bin` from 1.8.2** — diff the two USB descriptor
   blocks against §3.2. Specifically: did `bNumConfigurations` become 1, did the
   IAD's `bInterfaceCount` become 3, or did a second IAD appear covering interfaces
   1-2? That decides §3.3 outright. Also read the new `app_las` version string
   (ours is `-v2.1.2-0-gc38fe65`, at 0x2ac8e **[READ]**).
2. **`/lib/modules/<ver>/modules.builtin` from 1.8.2** — is the kernel still
   4.1.15-rt18? Did `snd-usb-audio` or rawmidi appear (which would mean §5.6 was
   fixed)? Did anything gadget-shaped appear?
3. **`/boot/*.dtb` from 1.8.2** — is either USB controller now `dr_mode = "otg"`?
4. **`las-frontend` from 1.8.2** — do `RUNNING STATUS` and `DEVICE ID` acquire UI
   labels? Does the CC list still omit 84? Do the fifteen sync/glide parameters
   appear in the CC-mappable set? Does an OSC receive buffer constant become visible
   near a new bounds check (§5.1)?
5. **`las-frontend --print-nrpns` table data from 1.8.2** — did the NRPN map grow to
   cover GLIDE and the SYNC parameters? If so, §4.2's table needs the additions.

Nothing in this document's **verdict** would change. §3.3, §5.1, §5.3 and §5.6
would move from inference to fact.

---

## 11. Reproducing everything here

Nothing below touches the instrument.

```sh
# kernel, modules, device tree, udev — needs an ext4 reader; macOS cannot mount ext4.
# A ~120-line pure-Python ext4 reader (superblock → group descriptors → extents →
# dirents) was written for this pass; 7z, debugfs and ext4fuse are all absent here.
gunzip -c captures/backup/rootfs-p3-las-v1.5.0-20260907.img.gz > rootfs.img
#   /lib/modules/4.1.15-rt18/modules.builtin      → the kernel's whole driver set
#   /lib/modules/4.1.15-rt18/modules.dep          → the two loadable modules
#   /boot/imx6dl-profili-som.dtb                  → dr_mode, FEC status
#   /etc/udev/rules.d/{20-xmos-nic,30-usb-nic,50-eth-ext-nic}.rules
#   /etc/udev/rules.d/{usb-int,usb-ext,eth-ext}.sh
LC_ALL=C grep -c -a ttymxc rootfs.img            # → 0

# XMOS USB descriptors: the image is bit-reversed per byte.
python3 - <<'PY'
raw = open('captures/arch-harvest/app_las_v2.1.2.bin','rb').read()
rev = bytes(int('{:08b}'.format(b)[::-1], 2) for b in raw)
import re
print([hex(m.start()) for m in re.finditer(b'\x62\x26', rev)])   # 0x11ca8, 0x2ae8d
print(rev[0x2ae85:0x2ae97].hex(' '))                             # the device descriptor
PY

# XMOS controller string tables
uv run python3 recon/strtab_decode.py --report
uv run python3 recon/strtab_decode.py --dump las-a      # the MIDI address tokens
uv run python3 recon/strtab_decode.py --dump las-b      # USB string descriptors

# las-frontend / las-sc
strings -a -t x captures/arch-harvest/las-frontend > fe-strings.txt
grep -aE '^[0-9a-f]+ snd_seq' fe-strings.txt            # JUCE's ALSA seq backend
grep -acF sysex fe-strings.txt                          # → 1, the orphan setting

# release notes and the NRPN table (all inside the 1.8.2 zip; the unpacked
# corpus/ directory on disk contains only the .m1p presets, not the PDFs)
unzip -j captures/firmware-1.8.2/Moog_One_v1.8.2.zip '*.pdf' -d fw182/
#   the NRPN table lives in "Moog One Midi Learn Addendum.pdf", pages 6-15, drawn
#   with an Identity-encoded subset font; decode via each page's ToUnicode CMap,
#   or via the glyph-index table recovered from the OPTIONS column
```

---

## 12. Conflicts with existing documents

Reported, not fixed, per the brief.

1. **`SWARM-BRIEF.md`**: "The USB gadget (`2662:800d`) carries CONTROL only
   (`usbint`…) plus `ethext`". Both PIDs are real, but **`2662:800d` is not a
   gadget on the i.MX6** — the i.MX6 is the USB *host* and the XMOS is the device.
   The functional description (usbint + ethext over one link) is correct and §2
   strengthens it: the i.MX6's own Ethernet MAC is disabled in the device tree, so
   `ethext` must come over that link.
2. **`SWARM-BRIEF.md`**: "`runtime-state.txt` has a `/sys/kernel/debug/usb/devices`
   and `lsmod` snapshot". It does not — both the `--- usb ---` and `--- modules ---`
   sections in that file are **empty** (debugfs is not mounted and `lsmod` printed
   nothing). **[READ]** All USB and module facts in this document come from the
   rootfs image and the device tree instead.
3. **`SWARM-BRIEF.md`**: "the v1.5.0 rootfs … 670,012,416 unpacked". That figure is
   `pkg/MANIFEST`'s `unpacked_size` for the **1.8.2** image. The v1.5.0 backup
   unpacks to **804,330,496** bytes. **[READ]**
4. **`docs/MOOG-ONE-INTERNALS.md:1117-1119`**: "USB MIDI never touches Linux."
   Correct for **note** data, and now proven from the kernel and device tree rather
   than from `/sys` probing. It needs a qualifier: **MIDI CC does reach
   `las-frontend`** — MIDI learn, `handleProgramChange`, and v1.8.0's
   "MIDI CC … causing panel lag" all require it. What arrives is OSC, not MIDI
   bytes; the opcode is §1.5's open question.
5. **`docs/MOOG-ONE-INTERNALS.md:816-818`**: "There is no MIDI-over-network
   service … the network carries OSC, not MIDI." Correct. Worth adding that the
   preset schema **reserves** one — `merge_avb_in` — which was never implemented.
6. **`docs/arch/hardware-external.md:657`**: "Our v1.5.0 has the MIDI-input crash."
   True of the v1.8.0 defect, but v1.5.0's own release notes claim a heavy-MIDI
   crash fix. This is the second such fix, not the first. §5.2
7. **The Moog One manual contradicts the Moog One** in two places: SysEx (§4.4) and
   class-compliant USB MIDI on the USB HOST port (§5.6). Neither exists on v1.5.0.
