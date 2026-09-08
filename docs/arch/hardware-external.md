# The Moog One as a physical object

External research, September 2026. Companion to `docs/ARCHITECTURE.md`, which is
assembled from the instrument's own software. Nothing here is repeated from there
except where it confirms or contradicts it, and those places are called out.

**Grading.** Every claim carries one of:

* **[OFFICIAL]** — Moog / inMusic documentation, spec sheets, release notes.
* **[TECH]** — a teardown or technician account with photographs or logs I read myself.
* **[COMMUNITY]** — owner or forum report. Attestation stated in each case.
* **[SPECULATION]** — inference. Mine, unless attributed.

Two source families do most of the work and deserve naming up front:

* **Ryan Zachry's four posts** (2020-2021, `ryanzachry.com`) — the only public
  teardown, plus root shell, boot logs, and a software survey. Photographs at full
  resolution; I read the board silkscreen and chip markings out of them directly,
  so component identifications below marked [TECH] are mine from his images.
* **The Gearspace "Moog One — Owners Discussion" thread** — 300+ pages, 2018-2026.
  The fault picture in §3 is drawn from ~30 pages of it read verbatim.

---

## 1. The voice card

### Physical arrangement — settled

**Two voices per card, four cards per side, one stack per side.** [TECH]
So **8 voices = 4 cards (one stack)**, **16 voices = 8 cards (two stacks)**. The
stacks sit under the black fan shrouds left and right. Cards are edge-connected and
daisy-chained: the silkscreen carries two **`TO NEXT VX`** connectors and a
**`Voice Stack Power In`** header.
(https://www.ryanzachry.com/2020/05/01/moog-one-inside.html)

**There is no upgrade path from 8 to 16.** Moog support's answer to an owner was
that it is "technically possible" but not offered as a service. [COMMUNITY]
(https://forum.moogmusic.com/viewtopic.php?t=32587). Whether the 8-voice chassis
has a physically populated second stack position is **not** documented anywhere I
found — do not assume it. [SPECULATION]

### Board identity — from the silkscreen

```
ONE, VOICE CARD (VX)   REV A   3/16/2018
BRD-30-011-1205 REV A
(C) Moog Music Inc.
```
[TECH] — read off the photograph. **`BRD-30-011-1205`** is the only Moog One board
part number I found anywhere in public. Date code on the board is week 28, 2018.
All components are on one side; the reverse is bare solder side. A **JTAG** header
sits at the top-left corner.

Silkscreen block labels, per voice: `VCO1 Core` / `VCO2 Core` / `VCO3 Core`,
`NOISE`, `MIX`, `VCFA_SUM`, `VCFB_SUM`, `VCA`, `MAIN`, `SUB1`, `SUB2`, plus
`VX1` / `VX2` marking the two voice halves and a `Howland` annotation next to the
+15 V section (a Howland current pump — the classic V/I converter for driving a
current-controlled core). Power rails brought onto the card: **+19 V in**, locally
regulated to +15, +9, −9, +5.75, +5 (`+5V DAC`), +3.3, +3.0 and 1.0 V.

### What is actually on it [TECH — all read from the photographs]

| Part | Qty (per card) | Role |
|---|---|---|
| **XMOS XL216-512-TQ128-C20** (marked `L11690C20`) | 1 | the card's processor |
| **TI/Burr-Brown PCM1681** | 8 (4 per voice) | 8-channel 24-bit audio DAC |
| **ON Semi 74HC595A** | ~10 | serial-in shift registers (switching/muxing) |
| **THAT 2172** | 1 per VCO core | pre-trimmed Blackmer VCA |
| **LM13700M** | several | dual OTA with linearising diodes |
| **NJM/JRC 4558, 4580; TL072** | many | op-amps |
| **Dual NPN in SOT-363, marked `S7x`** | 4-5 per filter | the ladder |

Four observations that matter:

1. **There is no synth-on-a-chip.** No CEM, no AS33xx, no SSI. The voice is built
   from THAT 2172 VCAs, LM13700 OTAs, jellybean op-amps and discrete transistors.
   Every "it uses CEM chips" claim you may meet is wrong.

2. **The ladder is genuinely discrete.** In the filter block, `Q16 / Q18 / Q20`
   (and neighbours) are 6-pin SOT-363 **dual** transistors alternating with SMD
   capacitors in a vertical chain — one dual transistor plus one capacitor per
   ladder stage. Dual-in-one-package gives thermal coupling and matching. The
   `S7x` marking is consistent with a BC847BS-class dual NPN, but the exact type
   is [SPECULATION]; the *topology* — a discrete transistor ladder, not an IC — is
   [TECH] and unambiguous from the photograph.

3. **Four PCM1681s per voice = 32 DAC channels per voice**, i.e. **64 per card**.
   This is the answer to "dedicated DACs per voice": yes, and lavishly. Moog used
   *8-channel audio* DACs as the control-voltage source. That is why the control
   path is clocked and why an audio-capable processor sits on each card — the CVs
   are literally generated as 24-bit audio streams. It also explains why "tuning"
   is a table of numbers rather than a trimmer.

4. **The XMOS on the voice card is the XL variant — no USB PHY.** It talks over the
   `TO NEXT VX` chain to the voice controller, not to the computer. Its firmware is
   `/usr/share/xmosfw/app_vx_10M_v1.0.14rc8.bin` ("vx" = the board's own name).

### The synthesis architecture [OFFICIAL, from the manual's spec page]

* **3 VCOs per voice**, "triangle core", described by Moog as a new **variable core**
  design. Waveform 1 is a saw/ramp/triangle hybrid whose *reset time* is variable
  from **6 µs to 1 ms** (the `Wave Angle` parameter, a modulation destination);
  waveform 2 is a variable-width pulse. The two are mixed per oscillator.
  Octave 32'-2', ±7 semitones, ±7 Hz beat offset. Osc 2 and 3 hard-sync to osc 1.
* **State Variable Filter**: "Two −12 dB per octave filters operating as one
  filter", configurable NOTCH / BP / LP / HP at −12 or −24 dB. Does not
  self-oscillate.
* **Ladder Filter**: Moog transistor ladder, HP or LP, selectable **−6 / −12 / −18 /
  −24 dB** slopes. Self-oscillates in LP. The HP mode is made by subtracting the
  LP output from its input, which gives it unusual transfer functions
  (Sound On Sound).
* Series or parallel, mixable. Dual-source noise (red/white, red/purple,
  white/purple), ring modulator (1-2 or 2-3), 6-channel mixer (3 osc, ring, noise,
  ext in) with per-source filter routing, then the VCA (level + pan + spread).

**Reconciling the "three filters" confusion:** Sound On Sound says three analogue
filters per voice; the spec sheet says two. Both are right — the SVF *is* two
12 dB sections, so the count is 2 SVF halves + 1 ladder = 3 filter blocks, 2 filter
*sections*. Chief Engineer Cyril Lance's figure of **"48 oscillators and 32 filters
on no fewer than 16 printed circuit boards"** [OFFICIAL, via SOS
https://www.soundonsound.com/news/birth-moog-one] uses the sections count:
16 voices × 3 = 48 oscillators, 16 × 2 = 32 filters. The **16 PCBs** does *not*
mean 16 voice cards — there are 8 — so it must count panel and I/O boards too, or
be loose. Flagged rather than resolved.

---

## 2. Calibration: what it holds, and what losing it would cost

This is the question with the most at stake, so it gets the most care.

### There are **three** separate calibrations, and they are routinely confused

| Routine | Where | Duration | What it does |
|---|---|---|---|
| **Oscillator Compensation** | `SETTINGS → UTILITIES` | ~10 min | Builds the real-time pitch-correction table |
| **Voice Card Calibration** | hidden: `SHIFT + SETTINGS + POLY MORE` | **≥ 4 hours** | 17 calibrations of the analog voice circuits |
| **System Calibration** | same hidden menu | — | Inputs, outputs, **potentiometers**, and the LHC |

[OFFICIAL] — the procedure is published at
https://moogmusic-help.freshdesk.com/en/support/solutions/articles/69000875671-moog-one-calibrating-moog-one-s-voice-cards
and mirrored at support.inmusicstore.com.

### What each one actually calibrates

**Voice Card Calibration** — Moog's own words: it exists "to ensure optimal tuning
and response of **all components of the analog voice circuits**" [OFFICIAL, v1.5.0
release copy]. Not just the oscillators. Owners watching it run report it stepping
through **every envelope on every voice** [COMMUNITY, KVR
https://www.kvraudio.com/forum/viewtopic.php?t=552979]. The menu exposes it as
**`CALIBRATIONS = 17/17`** and individual failed calibrations can be re-run from
the results screen — so it is 17 discrete named sub-calibrations. **I could not
find the list of the 17 names anywhere in public.** That is a real gap; the only
way to get it is to read the menu on the instrument, or the firmware.

**Oscillator Compensation** — this one is well explained. The instrument holds a
stored table giving, **for each oscillator, at each note, for both the square and
the triangle waveform**, the control voltage correction needed to play in tune. At
note-on the firmware applies the correction. Running the calibration re-measures
the oscillators and regenerates the table. [OFFICIAL, firmware v1.4.0, June 2020;
https://www.synthtopia.com/content/2020/06/16/moog-one-updated-with-real-time-tuning-calibration/
and https://forum.moogmusic.com/viewtopic.php?t=34148]

> **This is `/var/tuning.vxtune`.** Ryan Zachry names the same file as "voice card
> tuning data" [TECH]. `ARCHITECTURE.md`'s reading of it as a per-voice,
> per-oscillator table is **confirmed by the official description**, and the
> description adds two axes we should expect to find in it: **per note** and
> **per waveform (square vs triangle)**.

**System Calibration** is a different animal: "inputs, outputs, potentiometers, and
the LHC" [OFFICIAL]. Panel pot end-stops and the left-hand controller. There is no
public statement about where it is stored, but it is almost certainly **not** in
`vxcal.db` — different subsystem entirely. [SPECULATION]

### Does it self-tune at power-on? **No.**

There is no automatic calibration at boot. The manual asks for up to **5 minutes**
warm-up for oscillator tuning to stabilise; the calibration routines demand
**45 minutes** and the firmware **checks uptime since last reboot** before it will
let you run one [COMMUNITY, Moog forum]. Correction at play-time is table lookup
(Oscillator Compensation), not measurement. So the tables are the only thing
standing between the instrument and its raw analog tolerances.

### How bad would losing the tuning data be?

**Recoverable, without Moog, at a cost of one day.** The honest answer:

* The full Voice Card Calibration is **user-runnable** on firmware ≥ 1.5.0. It needs
  two audio cables looped from `SUB OUTS L & R` back into `LINE IN` and
  `MIC/LINE IN`, 45 minutes of warm-up, and about **4 hours** unattended. Then
  Oscillator Compensation must be re-run afterwards — mandatory, even if it was run
  before. [OFFICIAL]
* So the data is **regenerated in full**, not partially. Nothing in it is a
  factory secret or a per-unit constant that cannot be re-measured.
* **Caveats that make the backup still worth holding:**
  * Moog gates the procedure — "**THIS CALIBRATION SHOULD ONLY BE PERFORMED AT THE
    DIRECTION OF MOOG SERVICE**" [OFFICIAL]. That is advice, not a lock, but it
    signals that a bad run leaves you worse off than before.
  * Calibration **ages with ambient temperature**; owners re-run it seasonally, and
    Oscillator Compensation is explicitly temperature-dependent and must be re-run
    whenever **Fan Mode** is changed [COMMUNITY, well attested]. A restored old
    backup may be worse than a fresh run.
  * A **failed** calibration is itself diagnostic: one owner was told a card that
    would not pass calibration *was* the faulty card [COMMUNITY]. If you ever wipe
    and re-run and it fails, that is information, not necessarily a lost backup.
  * The 17 sub-calibrations cover more than pitch. Envelopes and filter response
    are in there. Losing it is not merely "it will be out of tune."

**Net:** the backup is insurance against a bad calibration run and a reference for
comparison, not the last copy of something irreplaceable. Treat it as valuable, not
as unique. The genuinely irreplaceable artefact would be a *voice card* with a
hardware fault, not its numbers.

### Why the tuning was never fully fixed [COMMUNITY, one strong analysis]

An owner who watched the routine reports that calibration samples each card at only
**two temperature points (~50 °C and ~60 °C)** and applies a single averaged CV
offset per card; cards cannot be trimmed individually and never reach thermal
equilibrium with each other. That would explain why the residual error is
voice-dependent, temperature-dependent, worst in the low register, and only
partially fixable in firmware. This is a careful owner's inference from observing
the procedure, **not** a Moog statement — but it is the best mechanism anyone has
offered, and it fits every symptom.
(Gearspace owners thread, p.166)

---

## 3. Known hardware faults

Ordered by how well attested, not how alarming.

### Low-register tuning instability — **officially acknowledged**, partly architectural

Worst below roughly 75-80 Hz. Described by owners not as smooth analog drift but as
**bouncing, random, "like an S&H modulation"**. Usually isolated to **specific
voices**, so the standard workaround is confining bass parts to known-good voices.
Many independent reporters, 2018-2024. [COMMUNITY, very well attested]

Moog's response was firmware: Oscillator Compensation (1.4.0) then user-accessible
calibration (1.5.0). Sound On Sound records Moog engineers stating, at review time,
that **ladder filter cutoff can vary by up to a semitone between voices** — a
designed-in tolerance, not a defect [OFFICIAL].

Most owners who ran the calibration then **switched Oscillator Compensation off**,
describing it as a "cheesy autotune effect" that removes the drift they wanted.
[COMMUNITY, multiple]

An early and separate bug: patches derived from factory presets could contain
**invalid oscillator frequency-offset parameters** that persistently detuned the
instrument until reboot, not enterable through the UI. Present at v1.0.4, fixed in
a later firmware. [COMMUNITY, one very detailed report,
https://www.matrixsynth.com/2019/05/moog-one-16-voice-tuning-problems.html]

### Boot loop on "Updating Voice Controller Firmware" — the most consequential

Four or more independent owners. The unit hangs during the per-card firmware pass;
in at least two cases the fix was **replacing voice boards**, one via the German
distributor with ~3 months out of service, one under warranty after a botched 2019
update. Related error text seen: **"failed enumerating voice cards"**.
[COMMUNITY, well attested]
(https://forum.moogmusic.com/t/v-1-31-freeze/20859)

**Recovery move, worth knowing:** hold the **master encoder** while powering on to
reach a firmware selector offering the current install, the previous install, and
the original **v1.0.0**. [TECH, Zachry; corroborated by owners]

**No one has ever published Moog's root cause for this loop.** Owners note the
absence explicitly.

### Voice card failure

Roughly **6-8 distinct owners** over 2018-2026 in a 300-page thread — a real failure
mode, not an epidemic, though the sample self-selects. Symptoms: a voice that shows
**inactive in hardware settings and cannot be re-enabled**; a voice that fails
calibration; voices drifting after a firmware update. Cards are swapped by Moog
under warranty. In one case Moog **mailed a replacement board plus fitting
instructions** for the owner to install. [COMMUNITY]

The worst-attested-but-most-alarming account: a unit that went in with voice 11 bad,
returned with 11 and 12 bad, went back, and returned with voice 1 unreliable and
11/12 still wrong — about 18 months. [COMMUNITY, single detailed account,
Gearspace p.145]

### Fans and thermal — the best-documented subsystem

**5 × Delta AFB0412VHB**, 40×40×15 mm, high static pressure (they must force air
between densely stacked cards). Full speed ~9500 rpm at boot as a self-test.
Measured **53-54 dB(A) at boot peak, 33.8 dB(A) idle**, two owners' measurements
agreeing. [TECH — owner teardown with photographs and level-matched recordings,
Gearspace p.196; corroborated p.61]

The dominant noise is **not** the fans but air striking the **edges of the voice
cards** — an edge-tone effect. Only the vibration component is fixable; silicone
decoupling mounts gain ~5-6 dB. Modifying fans voids warranty.

**Chassis ticking and popping** from differential expansion of the metal mesh
against the wooden back panel is common and **officially normal** [OFFICIAL, Moog
forum]. Fan Mode NORMAL/LOW is a documented setting; LOW is specified for ambient
≤ 75 °F (24 °C) and the machine overrides it when hot [OFFICIAL, manual].
Operating range 10-35 °C optimal, 10-43 °C safe.

The **thermal → tuning link is direct**: Oscillator Compensation must be re-run
whenever Fan Mode changes, and an owner reported several voices going sharply out
of tune the moment a cold draught entered the room.

### Keybed — **Fatar TP-8S** [OFFICIAL, spec sheet]

Well-attested **creaking/squeaking keys from new**. Root cause photographed: Fatar
greased the player side of the keys but left the **pivot** — plastic on plastic
under spring load — dry. Fix is disassembling 61 keys and greasing pivots.
Cross-confirmed by the same complaint on the Waldorf Quantum with the same Fatar
batch. Still a used-buying caveat. [COMMUNITY/TECH, photographed]

**Warning:** the **aftertouch ribbon cable is easily broken** during keybed
disassembly, and one owner who swapped a keybed then hit the
"Updating Voice Controller Firmware" boot hang. [COMMUNITY]

### Left Hand Controller

Wheel calibration drifts out of register with the physical stops; when the wheel
can no longer reach its calibrated endpoint the instrument **self-pitch-shifts by
up to 3-4 octaves while playing**. Moog issued a **private LHC service routine
document** to the affected owner — not published. [COMMUNITY, one detailed account]

### Power supply — almost nothing

External brick, Moog part **`TRN-01-000-0022`**, **19 VDC**, 4-pin locking
connector, rated **160 W**; measured draw **~126-127 W** steady on a 16-voice.
[OFFICIAL spec + COMMUNITY measurement] Syntaur stocks it
(https://syntaur.com/Part-9410-Power-adapter-19VDC-for-Moog-One).
**No electrical failure reports found at all** — one broken cable strain relief is
the entire corpus. This is a genuine null result.

### Output board — early-production defect

An op-amp change late in the design meant the **first units off the line had the
sub outs cross-wired**, causing phase cancellation. Moog shipped a replacement card
with owner-fitting instructions. [COMMUNITY, single detailed first-hand account]

Separately, a high noise floor above 12 o'clock on master volume is widely reported
and was **officially ruled by design**: 12 o'clock is unity, above is additive, and
the VCA/master are voiced hot deliberately to allow overdrive in place of a
dedicated drive circuit. A UK service centre disagreed. Unit-to-unit variance at
12 o'clock remains unexplained. [OFFICIAL vs COMMUNITY, unresolved]

### Displays, OLEDs, encoders, buttons, X/Y pad — **no failures found**

Searched directly across Gearspace and the Moog forum. The only items are one
transient display glitch that never recurred, and one case of **debris migrating
between the cover glass and the LCD** after a distributor opened the case.
Cosmetic wear on the X/Y pad surface on used units. **This is a null result, not a
search failure** — the panel appears to be the reliable part of this instrument.

### Storage

**No confirmed eMMC device failure.** What owners hit is *user-space* trouble:
presets apparently lost across firmware updates (often in a different User Space),
preset export soft-rebooting mid-export, and many USB sticks simply not recognised
(FAT32, root directory, no hubs; owners keep a known-good stick dedicated to it).
Moog's standard remedy — rebuild the User Space and reload firmware — implies
filesystem corruption is anticipated. [COMMUNITY + OFFICIAL troubleshooting]

---

## 4. Service documentation and parts

### No service manual, no schematics, no BOM. This is a firm negative.

Checked and came up empty: archive.org, elektrotanya, ManualsLib, manua.ls,
SynthXL's Moog service-manual index, Moog/inMusic support portals, general web.

The finding is sharper than a plain absence. **SynthXL carries leaked service
manuals for modern Moogs** — Voyager, Little Phatty, Slim Phatty, Sub Phatty,
Minitaur, Taurus 3, Theremini, Moogerfoogers — and **no Moog One**. Moog Music Inc.
post-2002 never *published* service manuals; the modern ones in circulation are
leaked dealer documents. None has leaked for the One. [TECH — I checked the index]

The only public service-adjacent document is the **calibration** article, which is
software-only and explicitly gated behind Moog Service.

### Parts: effectively unavailable

**Syntaur** — the main independent Moog parts vendor — stocks exactly **ten** Moog
One parts: the 19 VDC power adapter, and nine keyboard-key variants. **No voice
cards, no boards, no ICs.** eBay and Reverb show complete instruments only; no bare
voice cards. **No price for a voice card exists in public.** [TECH — vendor
inventory read directly]

`BRD-30-011-1205` (voice card) and `PCB-01-011-1200` (interface board), read off the
silkscreen in §1 and §5, are — as far as I can tell — the **only Moog One board part
numbers anywhere in public**. They are not orderable.

### Support status in 2026: better than you would expect

**The Moog One is NOT on Moog's "Notice of Discontinuation of Service."** [OFFICIAL]
That list — 500 Series Delay, 500 Series Ladder Filter, Little Phatty, Minifooger,
Moog Guitar, Moogerfooger, MP-201, Piano Bar, Slim Phatty, Taurus 3, Voyager,
VX-351, VX-352 — was current as of **November 2025** and the One does not appear on
it.
(https://support.inmusicstore.com/en/support/solutions/articles/69000840624-moog-notice-of-discontinuation-of-service)

The instrument was **discontinued from manufacture in June 2024** [OFFICIAL,
https://support.inmusicstore.com/en/support/solutions/articles/69000857951-moog-are-you-still-building-the-moog-one-],
but firmware shipped in **August and September 2025** (§7) and parts/service are
nominally still offered. Moog states it services any instrument it made after 2002.
Service centres are found via moogmusic.com/dealers filtered by "Service"; there is
no Moog One-specific list.

Set against that: repeated 2021-2024 owner reports of **4-week-plus** support
response times and needing a dealer or distributor to get traction. [COMMUNITY]

inMusic acquired Moog in mid-2023 and cut roughly 20-25 of 60 Asheville positions in
September 2023, with manufacturing largely moving to Taiwan. **No evidence that this
removed Moog One service capability** — the Nov 2025 list and the Sept 2025 firmware
both post-date it.

**Third-party repair: no one advertises it.** Shops advertise as Moog-authorised
generally; none names the Moog One. With zero schematics and zero parts, independent
board-level repair does not appear to exist as a service. [SPECULATION from a
thorough negative search]

**And note the service model Moog actually built:** the rear Ethernet port plus a
**"phone home"** item in the hidden service menu opens an **SSH tunnel to Asheville**
so a Moog technician can work on the instrument remotely. The manual describes the
LAN port as being "for future expansion and **remote service**" [OFFICIAL]. Servicing
was designed around the factory, not around you.

---

## 5. The digital board

### The SOM — identified exactly

```
Machine model: Variscite i.MX6 DL/Solo SOM-SOLO SOM-DUAL SoloCustomBoard
Linux 4.1.15-rt18 #1 SMP PREEMPT RT, armv7l, gcc 4.8.5 (Buildroot 2016.02-rc2)
U-Boot SPL 2013.10 (Jul 30 2018)
hostname: las-production      "L:A:S Production Image  (c)2017 Moog Music Inc."
```
[TECH — from Zachry's archived `dmesg-boot.txt` and `serial-boot.txt`, which I
downloaded and read]

* **Variscite VAR-SOM** module on a Moog-designed carrier. This **confirms
  `ARCHITECTURE.md`'s i.MX6 DualLite** — `nr_cpu_ids=2`, CPU ID `412fc09a`.
* **512 MB RAM**, of which 320 MB is a CMA pool and only ~180 MB is available to
  the kernel. **The teardown's claim of "2 GB DDR3" is wrong** — H5TQ2G63FFR is a
  2 **Gbit** part. U-Boot prints `Ram size 512`. Correct this if it is anywhere in
  our notes.
* **eMMC**: `NCEMASD9-08G`, enumerating as 7.21 GiB with **seven partitions**
  (`mmcblk2p1`-`p7`) plus boot0/boot1/rpmb. Root is **p2, ext4**; p4 is **FAT**;
  p6 and p7 are further ext4 filesystems. All were recovered from an unclean
  shutdown in the captured log — this machine is routinely powered off hard.
* Kernel command line matches `ARCHITECTURE.md` exactly, including `isolcpus=1`.
* PCIe is present on the SoC and **fails to probe** (`phy link never came up`) —
  unused.
* An **RTC (PCF85063)** sets the system clock at boot. The instrument keeps real
  time and has date/time settings in the UI.

### The audio link is **ESAI, not USB** — correction to `ARCHITECTURE.md`

```
fsl-esai-dai 2024000.esai: slave state boolean: 1
imx-xmos-esai sound-xmos-esai: Assigned faux codec/esai link
imx-xmos-esai sound-xmos-esai: Got clock from codec
imx-xmos-esai sound-xmos-esai: xmos-codec <-> 2024000.esai mapping ok
ALSA device list:  #0: xmos-audio
fsl-esai-dai 2024000.esai: Config : CBM_CFM - Codec bit and frame master
```
[TECH]

The ALSA card `xmos-audio` that `scsynth` opens is **the i.MX6's ESAI peripheral**
(Enhanced Serial Audio Interface — a hardware TDM/I²S port), bound to a *faux*
codec that is really the XMOS. **The XMOS is bit-clock and frame master
(`CBM_CFM`); the i.MX6 is the slave.** There is no audio codec chip in the usual
sense and no USB audio device.

This matters practically: **the instrument's sample clock originates on the XMOS
side**, and `ARCHITECTURE.md`'s point that the machine's value is being "inside the
sample clock" is stronger than stated — the i.MX6 is slaved to the analog engine's
clock, not the other way round.

### The USB gadget link is the **control** path — confirmation

The boot log shows network interfaces `lo`, `eth0`, **`usbint`**, **`usbext`**,
`ethext`, and then:

```
PING vc (203.0.113.2): 56 data bytes
1 packets transmitted, 1 packets received, 0% packet loss
VC is up
```
[TECH]

So the **voice controller is an IP host at `203.0.113.2`** on an internal USB
network interface (`usbint`), and OSC rides over UDP to it. `ARCHITECTURE.md`'s
"USB gadget link" to the voice controller is **confirmed and refined**: it is a
USB-CDC network link carrying IP, not a raw pipe. `usbext` is the rear USB client
port; `ethext` is the rear Ethernet.

Also in the log: **`Cycle XMOS Power`** early in init — the XMOS devices are
power-cycled deliberately at every boot before enumeration.

### The interface board

```
moog
PCB-01-011-1200   Rev: C
Profili Design Company, Inc.   5/30/2018
(c) 2017 MOOG MUSIC INC.
```
[TECH — from the photograph. Profili Design Company is the contract design house.]

It carries **two XMOS parts, U26 and U28, marked `U11690C20`** — that is
**XMOS XU216-512-TQ128-C20**: xCORE-200, 16 logical cores across 2 tiles, 512 KB
SRAM, 2000 MIPS, TQFP-128, **with integrated USB 2.0 PHY**. The voice card's
`L11690C20` is the **XL216-512-TQ128-C20**: the same die and speed grade in the
general-purpose variant, **without** the USB PHY.

That is the whole topology in one fact: **U-series where USB is needed (talking to
the i.MX6), L-series out on the cards where it is not.** Voice-controller firmware
is `/usr/share/xmosfw/app_las_v1.0.17rc2.bin`; voice-card firmware is
`app_vx_10M_v1.0.14rc8.bin`.

Also on the board: **`J_XTAG`** (an XMOS XTAG debug header — the standard way in),
`XO_DBG0` / `XO_DBG1` / `X2_DBG3` debug pads, RJ45 with magnetics, USB-A host,
USB-B client, **MIDI IN / MIDI OUT 1 / MIDI OUT 2** DIN jacks, `J_FAN CTRL` and
`J_FAN_ALT`, `J_KB` (keybed), `JA_HP` (headphones), and FFC connectors
`JD_VX1_LEFT1` / `JD_VX1_RIGHT` / `JA_VX1_LEFT` / `JA_VX1_RIGHT` / `JA_AUD_O`
carrying digital and analog to each voice stack.

### Display

* The LCD is **physically mounted upside-down**. The framebuffer and X are both
  inverted to compensate (`xrandr -o inverted`). Anyone drawing to `/dev/fb*`
  directly must flip. [TECH]
* There are **at least two framebuffers**; `las-fb-config framebuffer [0,1]
  [alpha 0-255]` sets per-framebuffer opacity, so the UI is composited from two
  layers. [TECH] `dd` to `/dev/fb1` is visible in the boot log.
* The panel OLEDs are driven separately — `las-frontend` takes a `--host-oleds`
  argument. [TECH]
* X.Org 1.18.3 with `fbdev`, plus a window manager `las-dwm`. [TECH]

### Panel spec — contradicts `ARCHITECTURE.md`

Moog's specification page says **"73 knobs and 144 buttons"** [OFFICIAL, manual
p.140]. `ARCHITECTURE.md` says "the panel has 108 knobs". One of the two is wrong;
the official figure should win unless we have counted them ourselves.

---

## 6. Community reverse engineering

**The field is small, published, and dormant since September 2021.**

### Ryan Zachry — four posts, and they are the whole public corpus [TECH]

1. `2020/05/01/moog-one-inside.html` — teardown, photographs.
2. `2021/09/05/moog-one-ssh.html` — serial console and root.
3. `2021/09/06/moog-one-doom.html` — Chocolate Doom cross-built for it.
4. `2021/09/07/moog-one-initial-findings.html` — the software survey. **Read this
   one.**

**Root access is a factory hook, not an exploit.** `/etc/init.d/S50dropbear`
checks for a file named **`k`** (lowercase, no extension) at the root of a USB
drive, and starts Dropbear if its first bytes are **`\x34\x19\x05\x23`** — i.e.
the value **`23051934`**, Bob Moog's birthday. Login is **root, no password**, over
Ethernet. [TECH]

**Firmware update format.** A `moog-one-vX.Y.Z` file is a **tar** containing
`IMAGE-SIG` (GPG), `MANIFEST` (JSON), `MANIFEST-SIG`, `rootfs` (**GPG-encrypted
ext4**), and `MOOGFW` (constant `0`). Installer is `/usr/bin/lasfwu`; public keys
at `/usr/share/sec/mmepubk` and `mmspubk`. **The decryption key is hidden
steganographically in `/etc/bob.bmp` and extracted with `/usr/bin/str`, password
`"bob"`.** [TECH]

**Two boot-time menus** worth having written down:
* **Master encoder held at power-on** → firmware selector: current, previous, and
  the original **v1.0.0**. (So there is effectively a third, immutable fallback
  beyond our two partitions.)
* **HOME + SETTINGS at the end of boot** → **service menu**, including "phone home"
  (SSH tunnel to Moog).

**OSC ports observed** [TECH]: `las-sc` listens on **9300**; the effects server is
typically **7775**; panel state is queried on **9500**; and **57120** appears — the
SuperCollider `sclang` default. `las-frontend` takes `--host-vc`,
`--host-performance`, `--host-oleds`. Watchdog is `las-watchdog`; there is a
`/var/log/vxtune-log`.

### The preset format is the OSC namespace — the single most useful external finding

**`github.com/mlazarev/MoogOne`** (Java, 2021, abandoned at 3 stars) reads and
writes Moog One `.m1p` preset files. The format is **plain ASCII, one
`path value` pair per line**, ~3,200 lines per preset, and the paths **are** the
instrument's OSC addresses:

```
/meta/name "INIT0"
/meta/type "SINGLE"
/p/version 14
/p/clk/rate 120.0
/p/lc/kbd/lhc/1/pad_xyz [0.5000076293945312, 0.5000076293945312, 0.0]
/p/lc/sus/type "inv"
/p/mix/aux1-db 0.0
```
[TECH — verified directly against the repo's `INIT0.m1p`]

**A single `.m1p` file is therefore a partial map of the `/p` namespace, with types
and default values, obtainable without touching the hardware.**
`ARCHITECTURE.md` counts 464 `/p` addresses as unmapped — this is a shortcut to
several thousand of them.

`github.com/johndavidmiller/moog_one` adds 23 more `.m1p` patches (2018) as corpus.
`github.com/mleysens/deconstrucing-moog-one` is empty — a LICENSE and a one-line
README, never committed to.

### Editors

**Midi Quest "Moog One CC"** (Sound Quest) is the only commercial editor, and in
their own words the instrument "doesn't have an accessible SysEx implementation so
all communication and editing is handled with CC or NRPN messages" — it stores
"patches as CC values". It is a **remote control, not a librarian**; it cannot read
the instrument's patch memory. **No free or open-source editor or librarian
exists.** [OFFICIAL — vendor]

### What nobody has done

* Published a map of the OSC namespace as such — only the `.m1p` route above.
* Documented the `vxcal.db` schema or the 17 calibration names.
* Run custom SuperCollider effects on the instrument. Zachry identified the
  mechanism (`/usr/share/las-fx`, `/etc/init.d/S42sc`, `launch-sc-1`,
  `util/cpu.rtf`) and explicitly flagged the opportunity. **Five years, nobody
  followed through.**
* Any board-level repair account, by anyone, ever.

---

## 7. Firmware history — **1.5.0 is not the last**

This is the correction most likely to matter operationally.

| Version | Date | Substance |
|---|---|---|
| 1.0.0 | 2018 | ship; retained as the recovery fallback |
| 1.0.4 | 2019 | era of the invalid-osc-offset detuning bug |
| **1.4.0** | **Jun 2020** | **Oscillator Compensation** — the real-time tuning table |
| **1.5.0** | **May 2022** | user-accessible **voice card** and **system** calibrations; 10 new CV/pedal input functions, 14 new CV output sources; sustain/sostenuto completed; "Return to Zero All"; stuck notes in Unison fixed; 25 Lisa Bella Donna presets |
| — | — | **no public 1.6.x or 1.7.x** — a three-year gap |
| **1.8.0** | **Aug 2025** | MIDI overhaul: USB descriptor fixed for Windows; **crashes on large MIDI input fixed**; ARP no longer echoes original key presses; EG ATTACK/DECAY/RELEASE SYNC, LFO RATE SYNC, GLIDE ON/RATE made MIDI-mappable; ladder slope and SVF mode changes via MIDI now reflected in UI/panel; **OSC HARD SYNC via CC no longer causes panel lag and crashes**; hanging notes on MIDI port/channel change fixed; MIDI PANIC no longer triggers A5; EG LOOP/LATCH fixes; INIT patch changed (all OSC TRI 0%, SAW fastest reset) |
| **1.8.1** | 2025 | fixed presets with oscillator hard sync not loading correctly |
| **1.8.2** | **Sep 2025** | fixed envelopes very rarely never going silent / never releasing the voice; fixed KEYBOARD CONTROL ON for one synth stopping voices on the others |

[OFFICIAL — I extracted the v1.8.2 release-note PDF text directly:
https://cdn.inmusicbrands.com/Moog/MoogOne/Moog%20One%20Firmware%20Update%20v1.8.2.pdf]

**Implications for us:**

* We are **three major releases behind**. Our v1.5.0 has the MIDI-input crash, the
  OSC-hard-sync-via-CC crash, and the stuck-envelope bug that 1.8.x fixed. Given
  that this project drives the instrument over MIDI and OSC, those are directly
  in our path.
* **1.8.x is MIDI/stability only. Nothing tuning-related since 1.5.0** — the
  calibration work is finished as far as Moog is concerned, and our calibration
  data format is unlikely to have changed.
* The rootfs is GPG-encrypted and signed, so a firmware upgrade is not something we
  can inspect first without the `bob.bmp` key (§6).
* Moog was still shipping fixes for a discontinued instrument in September 2025.
  Worth remembering before assuming abandonment.

---

## 8. What I could not find

Stated plainly, because the absences are informative:

* **The names of the 17 voice-card calibrations.** Nowhere in public.
* **Any service manual, schematic, BOM, or parts list.** Firm negative, checked
  against the sites that *do* carry leaked modern Moog service manuals.
* **Any price for, or source of, a replacement voice card.** No evidence they are
  sold as spares to anyone.
* **Moog's root cause for the "Updating Voice Controller Firmware" boot loop.**
  Owners note this absence themselves.
* **Any technician-authored, board-level Moog One repair account.** The three best
  technical documents on this instrument are all by *owners*.
* **Any display, OLED, encoder, button, or X/Y-pad failure report.** Searched
  directly. Real null.
* **Any power-supply electrical failure report.** Real null.
* **Documented backup/restore of calibration data** as a user-facing feature. The
  User Space export covers presets and settings; **calibration is not part of it.**
* **Confirmation of whether the 8-voice chassis has a populated second stack
  position.**
* Reliable failure *rates*. Forum threads self-select; I can say which faults are
  real and roughly how many independent reporters each has, not incidence.
* **Access to ModWiggler** (Cloudflare) and to most of the KVR thread. The
  ModWiggler item about a boot loop on a Moog One prototype rests on search
  indexing only — treat as unverified.

---

## Where this touches `docs/ARCHITECTURE.md`

**Confirmed:**
* i.MX6 DualLite, two cores, `isolcpus=1` — exact match to the kernel command line.
* Voices analog on separate cards with per-card XMOS processors — confirmed
  visually and by the two firmware images `app_vx_*` / `app_las_*`.
* A USB gadget link to the voice controller — confirmed as `usbint`, an IP link to
  a host at `203.0.113.2`.
* `/var/tuning.vxtune` as a per-voice, per-oscillator tuning table — confirmed, and
  extended: also **per note** and **per waveform**.
* SuperCollider doing effects and routing only — confirmed independently by Zachry,
  including `/usr/share/las-fx/util/cpu.rtf`, the same CPU-cost file the
  architecture notes cite.

**Corrected or refined:**
* **The audio path to the XMOS is ESAI (TDM), not USB.** ALSA's `xmos-audio` is the
  i.MX6 ESAI port with the XMOS as a faux codec, and **the XMOS is the clock
  master**.
* **Panel control count**: official spec is **73 knobs and 144 buttons**, not 108
  knobs.
* The teardown figure of **2 GB DDR3 is wrong — it is 512 MB**.
* There is a **third firmware fallback** (original v1.0.0) beyond the two
  partitions, reachable by holding the master encoder at power-on.
* **v1.5.0 is not the newest firmware**; 1.8.2 (Sep 2025) is.

**New and directly actionable:**
* Root is a documented factory hook: a USB file `k` containing `23051934`.
* `.m1p` preset files are ASCII dumps of the `/p` OSC namespace — thousands of
  addresses, no hardware required.
* `J_XTAG` header on the interface board for XMOS debugging.
* HOME+SETTINGS service menu; master-encoder recovery menu.
* The full voice-card calibration is user-runnable and regenerates everything, so
  the tuning backup is insurance, not a unique artefact.

---

## Sources

**Official**
* Moog One owner's manual, 8/2/2019 — https://cdn.inmusicbrands.com/Moog/MoogOne/Moog_One_Manual_8_2_19.pdf (note: contains **no** calibration section; the routines postdate it)
* Calibrating Moog One's Voice Cards — https://moogmusic-help.freshdesk.com/en/support/solutions/articles/69000875671-moog-one-calibrating-moog-one-s-voice-cards
* General Troubleshooting — https://moogmusic-help.freshdesk.com/en/support/solutions/articles/69000840575-general-troubleshooting
* Notice of Discontinuation of Service — https://support.inmusicstore.com/en/support/solutions/articles/69000840624-moog-notice-of-discontinuation-of-service
* Are you still building the Moog One? — https://support.inmusicstore.com/en/support/solutions/articles/69000857951-moog-are-you-still-building-the-moog-one-
* Firmware v1.8.0 / v1.8.2 release notes — https://cdn.inmusicbrands.com/Moog/MoogOne/Moog%20One%20Firmware%20Update%20v1.8.2.pdf

**Teardown and logs [TECH]**
* https://www.ryanzachry.com/2020/05/01/moog-one-inside.html
* https://www.ryanzachry.com/2021/09/05/moog-one-ssh.html
* https://www.ryanzachry.com/2021/09/06/moog-one-doom.html
* https://www.ryanzachry.com/2021/09/07/moog-one-initial-findings.html
* https://archive.ryanzachry.com/moog-one/dmesg-boot.txt
* https://archive.ryanzachry.com/moog-one/serial-boot.txt
* Board photographs (chip IDs in §1 and §5 were read from these):
  `.../assets/images/moog-one/voice-card-front.jpg`, `main-interface.jpg`

**Press / review**
* Sound On Sound review — https://www.soundonsound.com/reviews/moog-one
* The birth of the Moog One (Cyril Lance, Amos Gaynes) — https://www.soundonsound.com/news/birth-moog-one
* Oscillator Compensation announcement — https://www.synthtopia.com/content/2020/06/16/moog-one-updated-with-real-time-tuning-calibration/
* v1.5.0 coverage — https://www.synthtopia.com/content/2022/05/26/moog-one-gets-major-firmware-update/
* v1.8.0 coverage — https://www.synthtopia.com/content/2025/08/21/moog-one-firmware-update-fixes-bugs-improves-midi-support/

**Community**
* Gearspace "Moog One — Owners Discussion" thread 1236885 (pages 2, 32, 33, 61, 74, 82, 92, 116, 120, 122, 131, 145, 154, 166, 181, 196, 226, 241 cited above)
* Moog forum: v1.4 Oscillator Compensation — https://forum.moogmusic.com/viewtopic.php?t=34148
* Moog forum: v1.31 freeze / failed enumerating voice cards — https://forum.moogmusic.com/t/v-1-31-freeze/20859
* Moog forum: 8→16 voice upgrade — https://forum.moogmusic.com/viewtopic.php?t=32587
* KVR tuning thread — https://www.kvraudio.com/forum/viewtopic.php?t=552979
* Matrixsynth 2019 tuning report — https://www.matrixsynth.com/2019/05/moog-one-16-voice-tuning-problems.html

**Code and parts**
* https://github.com/mlazarev/MoogOne — `.m1p` reader/writer
* https://github.com/johndavidmiller/moog_one — patch corpus
* https://squest.com/Products/MidiQuest13/Instruments/MoogOneCC/index.html
* https://syntaur.com/Part-9410-Power-adapter-19VDC-for-Moog-One
* XL216 / XU216 datasheets — https://www.xmos.com/develop/xcore-200
