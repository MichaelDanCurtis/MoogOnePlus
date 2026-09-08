# Corrections — 2026-09-08

What changed on the day the 1.8.2 firmware package was opened and six parallel
reading passes ran over the capture set. Each row says what the repository
believed, what is true, and **how it is known**.

Grades: **[VERIFIED]** — checked directly in this session against a primary file,
independently of the agent that reported it. **[AGENT]** — reported by one reading
pass, plausible, not independently re-checked. **[CORROBORATED]** — two passes
reached it by different methods.

The instrument was not contacted at any point. Everything below is static analysis
of files on disk.

---

## 1. The USB link runs the other way round

| | |
|---|---|
| **Was** | "The i.MX6 exposes a USB gadget (`2662:800d`) carrying control to the voice controller." |
| **Is** | The **i.MX6 is the USB host**; the **XMOS is the device**. The XMOS also enumerates the rear USB-B socket a computer sees as "Moog One". `ethext` (the RJ45) is a second `cdc_ether` interface on that same link, because the i.MX6's own MAC is `status = "disabled"` in the DTB. |
| **Evidence** | **[VERIFIED]** `dmesg`: `ci_hdrc ci_hdrc.0: EHCI Host Controller` and `ci_hdrc.1` likewise (t=0.497, 0.519); `cdc_ether 2-1:1.0 usb0` and `cdc_ether 2-1:1.2 eth0` bind as a *driver to a peripheral* (t=12.06). USB string descriptors (`LAS internal`, `Moog`, and a serial `A41163B0FFFE` matching the `a4:11:63` OUI on `ethext`) are present in `app_las_v2.1.2.bin` at ~0x11c26 **bit-reversed**. |

**Consequence, and it is a large one:** no MIDI byte from either port ever reaches
Linux. `ttymxc` occurs zero times in the rootfs; `31250` zero times in
`las-frontend`. Nothing installable on the Linux side can observe or inject MIDI at
the port level. This is what makes on-instrument USB MIDI 2.0 an XMOS firmware
problem rather than a software one.

Fixed in `docs/ARCHITECTURE.md`. Note `MOOG-ONE-INTERNALS.md:1116` already said "no
USB gadget at all" while `:1337` says "one USB gadget carries both networks" — the
file contradicts itself and still needs a terminology pass.

## 2. Block size is 128 — and `runtime-state.txt` is contaminated

| | |
|---|---|
| **Was** | Briefly "corrected" mid-session to `-z 256`, on the strength of `runtime-state.txt`. |
| **Is** | **Stock is 128.** `init_sc_1.scd:9-10` sets `blockSize = 128` and `hardwareBufferSize = 128`; `:13` sets `numWireBufs = 128`. The `-z 256` in the snapshot was **this project's own experiment**, still running when the snapshot was taken on 2026-09-07, since reverted. |
| **Evidence** | **[VERIFIED]** `captures/arch-harvest/init_sc_1.scd`, re-harvested after the restore and clean against factory. |

`-w 128` is the wire-buffer count and is the number that has repeatedly been
mistaken for the block size. A caveat file now sits beside the snapshot at
`captures/arch-harvest/CAVEAT-runtime-state.md`; cite the boot sources, not the
snapshot, for anything about stock configuration.

## 3. The expression engine is much larger than recorded

| was | is | evidence |
|---|---|---|
| 64 constant registers | **128** | **[VERIFIED]** `vx_ee.scm:108` `(c (array 128))` |
| — | 16 engine variables, not saved in presets | **[VERIFIED]** `:112` `(v (array 16))` |
| — | 16 MIDI-mappable sources `m0…m15` | **[VERIFIED]** `:32` `(m (array 16))` |
| ~70 destinations | **126** (factory uses 71) | **[CORROBORATED]** |
| "36 transforms, factory uses 6" | **12 panel selectors**; `FUNCTION` id = `11 + tr_a` indexes **31** functions ⇒ ~42 operators. Factory uses all 12 selectors, 5 of 31 functions. | **[CORROBORATED]** — and cross-checked against Moog's own v1.3.0 release notes, which list the functions in the same order |

**`vx_ee.scm` itself lies in its prose.** The comment header says `c0..c31`,
`m0..m63`, `v0..v63`; the declarations three lines below say 128, 16, 16. Read the
declarations. **[VERIFIED]**

**The file was recovered** from `captures/backup/rootfs-p3-las-v1.5.0-20260907.img.gz`
at byte 637,856,768 — not from the instrument, and not from 1.8.2. `ROADMAP.md` §1's
"blocked on one file" is retired.

## 4. The RPN text form is retired

| | |
|---|---|
| **Was** | `/p/part/t/N/p/modmatrix/expressions` holds an RPN string; that is the interface. |
| **Is** | True only for `/p/version ≤ 12`. At **version 14 — this instrument** — presets carry `matrix_expression_slots`, a flat array of 7-tuples `[src, src_a, ctl, ctl_a, tr, tr_a, dst]`, and there is no `/p/c/*` block. |
| **Evidence** | **[VERIFIED]** the live namespace dump has **0** `/expressions` and **3** `matrix_expression_slots`. |

The RPN form structurally cannot carry per-slot state, which is why no stateful
transform (SLEW, S&H, BOUNCE, HIPASS…) appears anywhere in the text corpus. Write
tuples, not strings.

## 5. Retractions of our own earlier claims

- **"Cross-timbre routing already persists"** — a misreading. Of 7,476
  `entry/*/dst` strings, **zero** name a foreign timbre; `t/1` is fixed
  boilerplate and the numeric form has no timbre field. **[AGENT]**
- **`rcl` is scratch memory** — no. It is **the sequencer**. Every occurrence is
  `c64 rcl`. **[VERIFIED]** in the 222-preset corpus; **[AGENT]** for the wider
  1,329-payload corpus and the `seq/m/l/0/dst` correspondence.
- **106 `_m` twins** — there are **92**, and they are not preset state: they are
  the flat single-timbre engine tree `las-sc` pushes to the voice controller,
  `<leaf>` = base, `<leaf>_m` = modulation sum. **[AGENT]**
- **`las-frontend` is Qt** — it is **JUCE** (+ `libchicken.so.8`), zero Qt
  symbols, rendering in software on cpu0. **[CORROBORATED]**
- **`LTRQ`/`LTRS` is a startup cookie** — no, it is the clock query/response pair.
  **[AGENT]**
- **"AVB was the network-audio standard of that era"** — said while describing
  `merge_avb_in`, and it invited the inference that the instrument speaks AVB. **It
  does not, and structurally cannot.** See §7.

## 6. Firmware packaging — what is and is not possible

The 1.8.2 package was decrypted this session: `pkg/rootfs.ext4`, **670,012,416
bytes**, exactly the `unpacked_size` the MANIFEST declares, a valid ext4 filesystem,
`/etc/version` = `las-v1.8.2`. **[VERIFIED]**

The method is `lasfwu`'s own: the private **encryption** key is
LSB-steganographed into `bob.bmp` at 4 bits per byte, MSB-first, behind a decimal
length header (`3581`), passphrase `bob`.

| step | possible? | evidence |
|---|---|---|
| decrypt | **yes** | **[VERIFIED]** done |
| modify offline | yes | — |
| re-encrypt | yes — we hold the encryption keypair | **[VERIFIED]** |
| **re-sign** | **no** | **[VERIFIED]** `/usr/share/sec/secring.gpg` is **0 bytes**; only public halves (`mmspubk`, `mmepubk`) ship. The signing key never left Moog. |
| install a modified image | **no** | **[VERIFIED]** `lasfwu:686` verifies `IMAGE-SIG` against the decrypted image **unconditionally**, before the `dd` to `/dev/mmcblk2p*`. `--accept-unsigned` is documented at `:1009` but **is not implemented** — absent from the `load` option list (`:361`) and from the parser. |

**So a repackaged-firmware installer cannot work.** Not for want of effort — for
want of a signature that cannot be forged. Any "add our bits to the official
firmware" plan should be abandoned in favour of the USB-drive path, which touches no
firmware at all and, unlike a rootfs modification, survives an update (an update
writes the *other* A/B slot and boots it).

## 7. The network interface is not AVB, and cannot be

`/p/part/midi_io/merge_avb_in` exists as an address. Nothing implements it.

- `ethext` is **`cdc_ether`** — a USB CDC Ethernet device on the XMOS link, not a
  native MAC. AVB requires 802.1AS gPTP with **hardware timestamping in the
  MAC/PHY**; USB microframe scheduling makes that impossible in principle, not
  merely unimplemented. **[VERIFIED]**
- **Zero** AVB code in either XMOS image — searched plain and bit-reversed for
  `avb`, `AVB`, `1722`, `gPTP`, `AVTP`, `SRP`, `talker`, `listener`. **[VERIFIED]**
- **Zero** AVB tooling in the rootfs: no `avbtp`, `avdecc`, `openavb`, `gptp`,
  `ptp4l`, `linuxptp`. The 314 apparent `1722` matches are IBM codepage names
  (`ibm-17221`), float values (`-66.1722`) and Scheme line numbers
  (`cal/tests.scm:1722`). **[VERIFIED]**

XMOS shipped an AVB endpoint platform in that era. Moog did not take it.
`merge_avb_in` is an intention, not a capability.

## 8. Reported but not independently re-checked

Recorded here so they are not mistaken for verified facts:

- `las-frontend` is 92% `.rodata`, of which ~84% of the whole binary is
  uncompressed ASCII preset text; the same library is stored again in a 101 MB
  SQLite DB. **[AGENT]**
- 580 complete `.m1p` bodies are embedded in `las-frontend`, including the real
  factory `INIT_m1p`; 1,329 preset payloads exist across all sources. **[AGENT]**
- The firmware updater stages 788.31 MiB into a partition with 800.5 MiB free —
  **12.19 MiB of margin**. **[AGENT]** — worth re-checking before any update.
- An **eleventh** Eventide node (`et_room_1`) appears in live `/g_queryTree`
  dumps, making the leak `effects-engine.md` called latent an observed one.
  **[AGENT]**
- 609 free inodes on the rootfs. **[AGENT]**
- Display threads run `SCHED_FIFO` 93/80, above every threaded IRQ including
  `irq/26-esai`. **[AGENT]**
- Two factory presets ship malformed expressions (stack underflow). **[AGENT]**
- `las-sc`'s `_m` alias table maps `/p/noise/*_m` onto `e1am/e1dm/e1s/e1rm` —
  apparent copy-paste damage in v1.5.0. **[AGENT]**

## 9. Still open

- `voice_rule`: all 222 corpus presets set `cv_output/N/{source,min,max,synth}`,
  which this instrument has; only Lisa Bella Donna's 25 also set
  `cv_output/N/voice_rule`, which this instrument's namespace dump does **not**
  list. Firmware difference, or a hole in the dump — undetermined.
- `MOOG-ONE-INTERNALS.md` gadget terminology (§1).
- The ~50 further conflicts the six passes reported against older docs, on top of
  the 63 in `docs/arch/doc-audit.md`.
