# Audio I/O, the mixer, and the physical back panel

Region report against the decrypted **v1.8.2** root filesystem
(`captures/firmware-1.8.2/rootfs-1.8.2`), cross-checked against **v1.5.0**
(`captures/rootfs-1.5.0`), the harvested boot sources in `captures/arch-harvest/`,
and the owner's manual (`captures/Moog_One_Manual_8_2_19.pdf`).

**The instrument was not contacted.** Everything below is static analysis of files
on local disk. Proposed live reads are in [§14 Validation plan](#14-validation-plan)
for a human to run.

## Grading

Every claim carries a grade. This is not decoration — this project has shipped
inference as fact before.

* **[READ]** — read directly out of a named file at a named offset or line. Quoted.
* **[INFERRED]** — reasoning from evidence. The evidence is named.
* **[UNKNOWN]** — not established. Said so.

Two facts in this document are established by **three mutually independent
sources** (the SuperCollider graph, the compiled `las-sc` constant table, and the
`las-frontend` UI strings). Those are flagged **[READ ×3]**. They are the load-bearing
ones.

---

## 1. Headline

The eight DAC channels and nine ADC channels are not a mystery any more, and they
are not in the order anyone would guess.

`las-sc` is a **CHICKEN Scheme** program, and its compiled image contains a
named, statically-initialised table of every hardware channel index. Recovering it
gives the complete map by name — including four ADC channels no prior document in
this repository accounted for.

The other result: the EXT INPUT question is settled, and one part of the **owner's
manual is wrong about its own instrument**. See [§7](#7-the-ext-input-combo-and-line)
and [§13](#13-conflicts).

---

## 2. The stack, jack to sample

```
   back panel jack
        │
   analog board / voice cards          ← MAIN & SEND VCAs, EXT VCA, insert normalling
        │
   XMOS "LAS" voice controller         ← app_las_v2.2.2.bin; also the USB device
        │  ESAI (TDM), 12.288 MHz codec_osc
        │
   i.MX6DL ESAI @ 0x02024000           ← irq/26-esai
        │
   ASoC card "xmos-audio", PCM "HiFi"  ← 1 playback + 1 capture substream
        │
   scsynth  -i 9   (-o defaults to 8)  ← 48 kHz, block 128
        │
   inputRouter → efx units → outputRouter
```

**[READ]** The i.MX6 is the ESAI *master-side peripheral*; the codec is a Moog-custom
"faux codec" implemented in XMOS firmware, not a codec chip.
`vmlinux` (unpacked from `boot/uImage`) contains the literals
`Assigned faux codec/esai link ` and `Got clock from codec ` in the
`imx-xmos-esai` machine driver.

---

## 3. The ALSA / kernel layer

### 3.1 Device tree

Source: `boot/imx6dl-profili-som.dtb` (flattened device tree, 42,345 bytes; parsed
with a purpose-written FDT reader — `dtc` is not installed on this machine).

**[READ]** The machine node:

```
sound-xmos-esai {
    compatible = "fsl,imx-audio-xmos-esai";
    esai  = <0x3b>;      → esai@02024000
    codec = <0x3c>;      → xmos_codec@11
};
```

**[READ]** The codec is an I²C device, not an audio chip in the usual sense:

```
i2c@021a0000 {                     /* I2C1 */
    xmos_codec@11 {
        compatible       = "moog,las,xmos";
        reg              = <0x11>;          /* I²C address 0x11 */
        clocks           = <0x2d 0x0>;
        clock-names      = "codec_osc";
        #sound-dai-cells = <0x0>;
    };
};
```

**[READ]** The codec clock is a fixed clock in the DT:

```
codec_osc {
    compatible      = "fixed-clock";
    clock-frequency = <0xbb8000>;      /* 12,288,000 Hz */
};
```

12,288,000 = **256 × 48,000**. **[INFERRED]** The audio clock domain is 256·f<sub>s</sub>
at 48 kHz — the usual MCLK ratio — and it is generated on the XMOS side, which is why
the driver logs "Got clock from codec".

**[READ]** The ESAI itself:

```
esai@02024000 {
    compatible            = "fsl,imx35-esai";
    reg                   = <0x2024000 0x4000>;
    interrupts            = <0x0 0x33 0x4>;
    clock-names           = "core", "mem", "extal", "fsys", "dma";
    dma-names             = "rx", "tx";
    status                = "okay";
    fsl,esai-synchronous  = true;
    pinctrl-0             = <0xe>;      → esaigrp
};
```

`fsl,esai-synchronous = true` means **transmit and receive share the clock and frame
sync**. That is consistent with a single bidirectional TDM link to one device.

**[READ]** Every other audio path on the SoC is switched off:

| node | status |
|---|---|
| `ssi@02028000`, `ssi@0202c000`, `ssi@02030000` | `disabled` |
| `spdif@02004000` | `disabled` |
| `sound-hdmi` | `disabled` |
| `sound` (the generic simple-card node) | `disabled` |
| `asrc@02034000` | `okay`, `fsl,asrc-rate = <0xbb80>` (48000), `fsl,asrc-width = <0x10>` (16) |

So **ESAI is the only live audio transport**. There is no I²S, no S/PDIF, no HDMI
audio. This is the static-source confirmation of commit `cf7c6bd`
("correct the architecture from the hardware: ESAI, not USB").

### 3.2 The ESAI pinmux

**[READ]** `esaigrp` in the `imx6qdl-var-som-mx6` pinctrl node contains **eight**
pin tuples (each is `mux_reg conf_reg input_reg mux_mode input_val pad_setting`):

```
0x234 0x604 0x840 0x0 0x1 0x1b030
0x224 0x5f4 0x830 0x0 0x1 0x1b030
0x23c 0x60c 0x858 0x0 0x1 0x1b030
0x218 0x5e8 0x844 0x0 0x0 0x1b030
0x210 0x5e0 0x83c 0x0 0x1 0x1b030
0x240 0x610 0x82c 0x0 0x1 0x1b030
0x22c 0x5fc 0x838 0x0 0x1 0x1b030
0x228 0x5f8 0x834 0x0 0x1 0x1b030
```

**[UNKNOWN]** Which pad is which ESAI signal. Decoding `mux_reg`/`input_reg` to pad
names needs `imx6dl-pinfunc.h`, which is not in this repository, and the kernel image
carries no `MX6QDL_PAD_*` name strings (`grep -c MX6QDL_PAD` over the unpacked
`vmlinux` returns **0**). I will not guess pad names; the ESAI select-input register
block is adjacent to the ENET block in this SoC's IOMUXC map, and getting it wrong by
one register would produce a confident, wrong answer.

**[INFERRED]** Eight pads is consistent with three clock pads (bit clock, frame sync,
high-frequency clock — RX borrows TX's under `fsl,esai-synchronous`) plus five data
pads. On i.MX6 ESAI, `SDO0` and `SDO1` are transmit-only while `SDO2..SDO5` are shared
with `SDI3..SDI0`, so five data pads can supply two transmit lines and three receive
lines. That would suit 8 out / 9 in. **This is arithmetic that fits, not evidence.**
The TDM slot count and word width are **[UNKNOWN]** — see the validation plan.

### 3.3 The ASoC card

**[READ]** From the unpacked kernel (`boot/uImage` → gzip at file offset 18200 →
10,214,816-byte image, link base `0x80008000`):

| item | value |
|---|---|
| platform driver name | `imx-xmos-esai` |
| card name | `xmos-audio` |
| CPU DAI | `2024000.esai` |
| codec DAI | `xmos-codec` |
| codec device | `xmos-codec.0-0011` (I²C bus 0, address 0x11) |
| platform | `imx-pcm-audio` |

**[READ]** Three `snd_soc_dai_link` structures are statically defined at
`0x809bcb50`, `0x809bcbb0`, `0x809bcc10`:

1. **`HiFi`** — `2024000.esai` ↔ `xmos-codec`
2. **`HiFi-ASRC-FE`** — `xmos-codec.0-0011` ↔ `snd-soc-dummy-dai`, flag word `0x00020000`
3. **`HiFi-ASRC-BE`** — `xmos-codec`, platform `imx-pcm-audio`, flag word `0x00010000`

**[READ]** In all three, the word that would carry a static `dai_fmt` is **zero** —
the machine driver sets no format constant at build time. Whether it sets one at
`hw_params` is **[UNKNOWN]**.

**[INFERRED]** Links 2 and 3 are a DPCM front-end/back-end pair for the ASRC. They do
not appear at runtime (below), so either the driver registers only link 1 by default
or the ASRC path is conditionally enabled.

### 3.4 What actually enumerates

**[READ]** `captures/arch-harvest/runtime-state.txt:154-157`. Per
`CAVEAT-runtime-state.md`, this file is contaminated for block size and process
state but **remains valid evidence for ALSA card enumeration**, which is exactly
what this is:

```
--- alsa ---
 0 [xmosaudio      ]: xmos-audio - xmos-audio
                      xmos-audio
00-00: HiFi xmos-codec-0 :  : playback 1 : capture 1
```

* **One** sound card: index 0, id `xmosaudio`.
* **One** PCM device: `hw:0,0`, name `HiFi`, one playback and one capture substream.
* The ASRC FE/BE links did **not** register a PCM.

**[READ]** `/.jackdrc` in the rootfs says:

```
/usr/bin/jackd -dalsa -dhw:3 -S
```

**[INFERRED]** This file is **dead**. There is no card 3 — there is only card 0.
`S42sc` launches `las-sc`, which launches `sclang`/`scsynth` directly
(`etc/init.d/S42sc:4`, `usr/share/las-fx/launch-sc-1`); JACK is never started on the
boot path, and `S42sc`'s `stop()` kills `jackd` only defensively. The `jack_*` tools in
`/usr/bin` are buildroot package residue. Do not infer a JACK graph from this file.

---

## 4. The scsynth layer

**[READ]** `usr/share/las-fx/init_sc_1.scd`, lines 9-18 — this is the stock
configuration, and it is the file to cite, not the runtime snapshot:

```supercollider
Server.named.at(\server_main).options.blockSize            = 128;
Server.named.at(\server_main).options.hardwareBufferSize   = 128;
Server.named.at(\server_main).options.numOutputBusChannels = 8;
Server.named.at(\server_main).options.numInputBusChannels  = 9;
Server.named.at(\server_main).options.numWireBufs          = 128;
Server.named.at(\server_main).options.memSize              = 100000;
Server.named.at(\server_main).latency                      = 0.05;
Server.named.at(\server_main).options.sampleRate           = 48000;
```

**8 output channels, 9 input channels, 48 kHz, block size 128.**

**[READ]** `runtime-state.txt:115` shows the resulting argv:

```
scsynth -u 57110 -a 129 -i 9 -b 1026 -z 256 -Z 256 -m 100000 -w 128 -S 48000 -R 0 -C 0 -l 1
```

`-z 256 -Z 256` is this project's own contamination (see the caveat file); stock is
128. Everything else corroborates the `.scd`:

* **`-i 9`** is explicit; there is no `-o`, so the output count takes SuperCollider's
  default of 8. **[INFERRED]** — consistent with `numOutputBusChannels = 8`.
* **`-a 129`** is a useful independent check. SuperCollider computes
  `numAudioBusChannels = numPrivateAudioBusChannels + numInputBusChannels +
  numOutputBusChannels`, and the default private count is 112.
  **112 + 9 + 8 = 129.** **[INFERRED]** The live instrument therefore agrees, from the
  other direction, that there are 9 in and 8 out.

### 4.1 Bus layout

**[INFERRED]** from the two numbers above and SuperCollider's fixed bus ordering:

| SC bus range | meaning |
|---|---|
| 0 – 7 | hardware **outputs** (DAC channels 0-7) |
| 8 – 16 | hardware **inputs** (ADC channels 0-8) |
| 17 – 128 | private busses |

**[READ]** `usr/share/las-fx/efx_server.scd:813` confirms the `+8` translation
explicitly — the OSC message from `las-sc` carries a *hardware* input index, and
sclang converts it to an SC bus:

```supercollider
chan = msg[k+1].asInteger + 8;
```

---

## 5. The DAC map — 8 channels to 8 jacks

This is one of the two **[READ ×3]** results.

### 5.1 Source A — the SuperCollider graph

**[READ]** `usr/share/las-fx/synthdefs.scd:563-571`, inside `SynthDef(\outputRouter)`.
The comment `// esai` is the firmware's own:

```supercollider
        // esai
        Out.ar(7, main[0] * -1);
        Out.ar(0, main[1] * -1); // good
        Out.ar(2, sub[0]);
        Out.ar(1, sub[1]);
        Out.ar(5, aux1.sum);
        Out.ar(6, aux2.sum);
        Out.ar(3, aux3.sum);
        Out.ar(4, aux4.sum);
```

**[READ]** Immediately below it, lines 573-581, sits a commented-out alternative
labelled `// usb`, with a *different* channel order and **no polarity inversion**:

```supercollider
        //	usb
         // Out.ar(1, main[0]);
         // Out.ar(0, main[1]); // good
         // Out.ar(3, sub[0]);
         // Out.ar(2, sub[1]);
         // Out.ar(6, aux1);
         // Out.ar(7, aux2);
         // Out.ar(4, aux3);
         // Out.ar(5, aux4);
```

That the two maps differ, and that the live one is the one labelled `esai`, is direct
in-firmware evidence that the channel order and the main-bus inversion are properties
of the ESAI/XMOS path specifically.

### 5.2 Source B — the compiled `las-sc` constant table

`las-sc` is a **CHICKEN Scheme** program compiled to C and then to ARM
(`libchicken.so.8`, `CHICKEN_main`, `C_h_intern`, `C_decode_literal` all present).
Its toplevel `define`s of the channel constants survive as a run of stores into the
CHICKEN literal frame.

Method: the symbol names are interned by `C_h_intern(&lf[i], len, "name")` in the
module init at `0x121xx`, which gives *name → literal-frame index*; the values are
written as CHICKEN fixnums (`(n << 1) | 1`) at `0x8c28c`–`0x8c3c8`, which gives
*index → value*. Joining the two recovers the table.

The table below was first read by hand from the disassembly and then **re-derived
automatically** by a script that tracks ARM register state across the initialisation
block, to remove the risk of a hand-reading error. The two agree on every row.
The join is self-checking: if the *name → index* and *index → value* mappings were
misaligned by even one slot, the fourteen private-bus rows in [§11.3](#113-the-internal-supercollider-busses)
would not come out as exactly 50…63, the values `synthdefs.scd` independently uses.

**[READ]** `usr/bin/las-sc`, disassembled with
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`:

| symbol | lf index | init address | fixnum | **DAC channel** |
|---|---|---|---|---|
| `main-out-l` | 426 | `0x8c28c` | — (see note) | **7** |
| `main-out-r` | 430 | `0x8c2b0` | `#1` | **0** |
| `sub-out-l` | 428 | `0x8c2a0` | `#5` | **2** |
| `sub-out-r` | 433 | `0x8c2d4` | `#3` | **1** |
| `aux-out-1` | 427 | `0x8c298` | `#11` | **5** |
| `aux-out-2` | 429 | `0x8c2a8` | `#13` | **6** |
| `aux-out-3` | 432 | `0x8c2c8` | `#7` | **3** |
| `aux-out-4` | 431 | `0x8c2bc` | `#9` | **4** |

Note on `main-out-l`: its store at `0x8c28c` takes its value from `r9`, which is set
before the disassembled window. **[INFERRED]** it is 7, by elimination from
{0..7} and because `synthdefs.scd:564` writes `main[0]` to channel 7. Every other
row is **[READ]**.

**Sources A and B agree on all eight channels.** They are independent artefacts —
one an interpreted `.scd` text file, the other a compiled ARM binary — written by
different parts of the system.

### 5.3 Source C — the front-panel UI

**[READ]** `usr/bin/las-frontend`, the `MasterPanel` OUTPUT MATRIX block at file
offsets `0x7e701ec`–`0x7e703d6`, enumerates the output destinations exhaustively:

```
0x7e70359  INSERT 4
0x7e70362  INSERT 3
0x7e7036b  INSERT 2
0x7e70374  INSERT 1
0x7e7037d  SUB L/R
0x7e70385  MAIN L/R
0x7e7038e  INSERT 4 - VOLUME
0x7e703a0  INSERT 3 - VOLUME
0x7e703b2  INSERT 2 - VOLUME
0x7e703c4  INSERT 1 - VOLUME
0x7e703d6  OUTPUT MATRIX
```

Six destinations: MAIN L/R, SUB L/R, INSERT 1-4. **[READ]** `synthdefs.scd:412`
names the same six in the same role:

```supercollider
insert1_r = #[0, 0, 1, 0, 0, 0], // columns are main, sub, aux1, aux2, aux3, aux4
```

**[READ]** And `las-sc`'s own rodata (`0x1e4fc6`–`0x1e5073`) pairs the OSC address with
the internal name, index for index:

```
/g/0/t/mix/dir1-en        timbre-1-aux1-en
/g/0/t/mix/dir2-en        timbre-1-aux2-en
/g/0/t/mix/dir3-en        timbre-1-aux3-en
/g/0/t/mix/dir4-en        timbre-1-aux4-en
```

**Therefore `aux1`, `aux2`, `aux3`, `aux4` in the firmware *are* the INSERT 1-4 jacks.**
The word "aux" never appears on the instrument; the panel says INSERT.

### 5.4 The DAC map

| DAC ch | firmware name | rear-panel jack | polarity |
|---|---|---|---|
| **0** | `main-out-r` | **MAIN R** | **inverted** (`* -1`) |
| **1** | `sub-out-r` | **SUB R** | normal |
| **2** | `sub-out-l` | **SUB L** | normal |
| **3** | `aux-out-3` | **INSERT 3** (tip / send) | normal |
| **4** | `aux-out-4` | **INSERT 4** (tip / send) | normal |
| **5** | `aux-out-1` | **INSERT 1** (tip / send) | normal |
| **6** | `aux-out-2` | **INSERT 2** (tip / send) | normal |
| **7** | `main-out-l` | **MAIN L** | **inverted** (`* -1`) |

**[READ]** MAIN L and MAIN R are both multiplied by −1 in `outputRouter`; SUB and all
four INSERT sends are not. The pair-internal polarity of MAIN is therefore correct,
but **MAIN is 180° out of phase with SUB and with the INSERT sends.**

**Practical consequence.** Anything that writes to busses 0 and 7 must invert to match,
or it will cancel against the instrument's own output. Anything that sums a MAIN
output against a SUB or INSERT output outside the instrument will get partial
cancellation. **[INFERRED]** the inversion compensates an inverting stage in the
analog MAIN output driver that the SUB/INSERT drivers do not have; the commented-out
`usb` map's lack of inversion is consistent with that map predating the current
analog board. The cause is **[UNKNOWN]** — only the compensation is read.

### 5.5 Output level parameters

| OSC address | UI label | reachable from |
|---|---|---|
| `/p/mix/aux1-db` | INSERT 1 - VOLUME | preset + panel |
| `/p/mix/aux2-db` | INSERT 2 - VOLUME | preset + panel |
| `/p/mix/aux3-db` | INSERT 3 - VOLUME | preset + panel |
| `/p/mix/aux4-db` | INSERT 4 - VOLUME | preset + panel |
| `/p/mix/sub-db` | SUB VOLUME | preset + panel |

**[READ]** All five appear as preset keys in the 580 factory presets embedded in
`las-frontend` (e.g. `/p/mix/aux1-db 0.00000000000000000000`) and in the live preset
key dump `captures/p-namespace-keys.txt`.

**[READ]** Range, from the manual: SUB VOLUME on PDF page 53 (printed 54) and each
INSERT n - VOLUME on PDF page 54 (printed 55) are **−96 dB to 0 dB to +22 dB**.

**[READ]** There is **no `/p` address for MASTER VOLUME or HEADPHONES.** Neither
appears anywhere in `las-frontend`'s `/p` address set nor in the preset key dump. See
[§9](#9-headphones-and-master-volume).

---

## 6. The ADC map — 9 channels

This is the second **[READ ×3]** result, and the part no prior document in this
repository had.

### 6.1 The `las-sc` table

**[READ]** Same method and same instruction run as §5.2 — `usr/bin/las-sc`,
`0x8c2dc`–`0x8c324`:

| symbol | lf index | init address | fixnum | **ADC channel** |
|---|---|---|---|---|
| `main-in-r` | 435 | `0x8c2e8` | `#3` | **1** |
| `send1-in` | 436 | `0x8c2f0` | `#5` | **2** |
| `send2-in` | 437 | `0x8c2fc` | `#7` | **3** |
| `direct-in-1` | 254 | `0x8c304` | `#9` | **4** |
| `direct-in-2` | 253 | `0x8c30c` | `#11` | **5** |
| `direct-in-3` | 252 | `0x8c318` | `#13` | **6** |
| `direct-in-4` | 251 | `0x8c324` | `#15` | **7** |
| `main-in-l` | 434 | `0x8c2e0` | `#17` | **8** |

The name strings are at `usr/bin/las-sc` file offsets `0x1e7579` (`direct-in-1`),
`0x1e768c` (`main-in-l`), `0x1e76a0` (`send1-in`) and neighbours.

### 6.2 Corroboration

**[READ]** `synthdefs.scd:276` and `:288`, in `SynthDef(\inputRouter)`:

```supercollider
/*SEND 1 is LEFT CHAN when in STEREO MODE and Send 1 when in MONO MODE*/
send1 = SoundIn.ar(2) * send1Gain;
...
/*SEND 2 is RIGHT CHAN when in STEREO MODE and Send 2 when in MONO MODE*/
send2 = SoundIn.ar(3) * send2Gain;
```

`SoundIn.ar(2)` is hardware input 2, `SoundIn.ar(3)` is hardware input 3 — matching
`send1-in = 2`, `send2-in = 3` exactly.

**[READ]** `synthdefs.scd:441-443` and `:473-475`, in `SynthDef(\outputRouter)`:

```supercollider
        synth1_in_ch = 4,
        synth2_in_ch = 5,
        synth3_in_ch = 6,
...
        // analog dry inputs
        dry_dir1 = Pan2.ar(In.ar(synth1_in_ch), dry_1_p);
        dry_dir2 = Pan2.ar(In.ar(synth2_in_ch), dry_2_p);
        dry_dir3 = Pan2.ar(In.ar(synth3_in_ch), dry_3_p);
```

The defaults 4, 5, 6 are exactly `direct-in-1`, `direct-in-2`, `direct-in-3`, and the
firmware's own comment calls them **"analog dry inputs"**.

> **A latent bug, noted in passing.** Those `synth*_in_ch` *defaults* are wrong as
> written: with `numOutputBusChannels = 8`, `In.ar(4)` reads **output** bus 4
> (INSERT 4's send), not an input. They are harmless only because
> `efx_server.scd:824` overwrites them at runtime with the `+8`-corrected value from
> `/fxN/in`. If `outputRouter` is ever instantiated before `las-sc` sends
> `/fx0/in`, it reads the INSERT sends back into the dry path. **[INFERRED]** from
> `synthdefs.scd:441-443,473-475` + `efx_server.scd:813,824` + §4.1.

**[READ]** `las-sc` also publishes four metering addresses whose names line up
one-for-one with the four non-`direct` capture channels
(`usr/bin/las-sc` at `0x218f5c` and neighbours):

```
/a/stat/mainl    /a/stat/mainr    /a/stat/send1    /a/stat/send2
```

### 6.3 The ADC map

| ADC ch | firmware name | carries | read by |
|---|---|---|---|
| **0** | *(unnamed)* | **[UNKNOWN]** — see below | nothing |
| **1** | `main-in-r` | analog MAIN R bus, digitised | `las-sc` (metering, calibration) |
| **2** | `send1-in` | analog **SEND 1** bus (sum of the voice cards' send-1 VCAs) | `inputRouter`, `SoundIn.ar(2)` |
| **3** | `send2-in` | analog **SEND 2** bus | `inputRouter`, `SoundIn.ar(3)` |
| **4** | `direct-in-1` | **Synth 1** analog output | `outputRouter` dry path + Synth-1 insert effect |
| **5** | `direct-in-2` | **Synth 2** analog output | as above |
| **6** | `direct-in-3` | **Synth 3** analog output | as above |
| **7** | `direct-in-4` | a fourth "direct in" | **nothing in the SC graph** |
| **8** | `main-in-l` | analog MAIN L bus, digitised | `las-sc` (metering, calibration) |

**ADC 0 is not named anywhere in `las-sc` and is not read anywhere in
`synthdefs.scd`.** `scsynth` is opened with 9 inputs and only 8 are accounted for.
**[UNKNOWN]** what is on it, or whether anything is. It is possible the count is 9
purely so that channel 8 (`main-in-l`) is addressable.

**ADC 7 (`direct-in-4`) is defined by `las-sc` but dead in the SC graph.**
**[READ]** `synthdefs.scd:476` sets `dry_dir4 = 1` — a constant, not an `In.ar` — and
`:422` sets `dry_dir4_r = #[0, 0, 0, 0]`, i.e. routed nowhere. So the fourth direct
input is provisioned in the control plane and unused in the audio plane.
**[INFERRED]** it is a fourth Synth slot that was designed for and never built; the
whole `dry_dir1..4` / `insert1..3` asymmetry (four direct inputs, three Synths, three
insert effect slots) points the same way.

### 6.4 Why MAIN comes back in

**[READ]** `las-frontend` at `0x7e9783e`, in `VoiceCardCalibrationPanel`:

```
PLEASE CONNECT COMBO AND LINE INS TO SUB L AND SUB R OUTS.
```

**[READ]** and in the same panel's step list:

```
CALIBRATING EXTERNAL INPUT VCA
CALIBRATING MAIN VCA
CALIBRATING SEND VCA
```

**[INFERRED]** — and this is a satisfying closure — voice-card calibration works by
**closing a loop through the instrument's own converters**:

```
SUB L/R out (DAC 2,1) → patch cable → COMBO / LINE in
   → voice-card EXT input VCA → filters → MAIN bus
      → MAIN L/R in (ADC 8, ADC 1) → measurement
```

That is why `main-in-l` / `main-in-r` exist as capture channels at all, and why the
calibration needs two patch cables. It also explains `/cal/mainl`, `/cal/mainr`,
`/cal/extin`, `/cal/aux1`, `/cal/aux2` in `las-sc`'s calibration namespace: those are
per-voice-card VCA trims, not output-jack settings.

---

## 7. The EXT INPUT: COMBO and LINE

The task set this as an open question. It is now settled, in both directions:
the prior claim was **right on substance and wrong on one word**, and *the manual
contradicts the firmware* on where the two inputs go.

### 7.1 The connector and the trim — the prior claim was correct

`docs/arch/extension-points.md:919-924` recorded three assertions as
**[UNVERIFIED]** and asked for the manual to be added to `captures/`. The manual is
now there (`captures/Moog_One_Manual_8_2_19.pdf`, added 2026-09-08). All three close:

**[READ]** Manual, PDF page 19 (printed page 20), "EXT INPUT":

> Moog One provides an External Audio Input featuring a **Neutrik connector**,
> capable of accepting either a balanced XLR cable, a balanced 1/4" TRS cable, or an
> unbalanced 1/4" TS cable. The **TRIM knob can adjust the input gain from −9 dB to
> +65 dB**. There is also a Line Level (LINE) input equipped with a 1/4" balanced TRS
> jack…

**[READ]** Manual, PDF page 140 (printed 141), SPECIFICATIONS:

> EXTERNAL MIC/LINE INPUT : XLR + 1/4" TRS **combo jack** with trim knob
> EXTERNAL LINE INPUT : 1/4" TRS (TS compatible)

| assertion | verdict |
|---|---|
| "Neutrik" | **CONFIRMED** [READ] |
| "TRIM −9 to +65 dB" | **CONFIRMED** [READ] |
| the word "**combi**" | **WRONG.** The manual says **combo**; the firmware says **COMBO** (`las-frontend` `0x7e9783e`). Both agree. Use *combo*. |
| "tip = send, ring = return, stereo-normalled pairs" (INSERTs) | **CONFIRMED** [READ] — see §8 |

So: the substance was right, it simply had never been cited. It is cited now. The one
correction is orthographic and worth making because *combo jack* is the industry term
and *combi* is not what either the manual or the firmware writes.

### 7.2 The two inputs, as the firmware names them

**[READ]** `las-frontend` `MixerPanel`, offsets `0x7e70ef8`–`0x7e70f1a`:

```
0x7e70ef8  EXT. INPUT LEVEL
0x7e70f09  EXT. INPUT ROUTE
0x7e70f1a  EXT. INPUT SOURCE
```

**[READ]** offsets `0x7e7118f`, `0x7e71198`:

```
0x7e7118f  MIC/LINE
0x7e71198  MIC/LINE + LINE
```

**[READ]** Manual, PDF page 31 (printed 32), "MIXER MORE PAGE (EXTERNAL INPUT CHANNEL)":

> EXT. INPUT SOURCE  (NONE, MIC/LINE, LINE, MIC/LINE+LINE)
> This parameter specifies which physical EXT. INPUT jack(s) is the source of the
> EXT. INPUT signal.

So the firmware's vocabulary is:

* **MIC/LINE** = the Neutrik **combo** jack (XLR + 1/4" TRS), the one with the TRIM
  knob. `las-sc` shortens this to **`mic`**.
* **LINE** = the separate 1/4" TRS line input. `las-sc` calls it **`line`**.

**[READ]** The per-Synth encoding is a pair of booleans,
`/p/part/t/N/p/mix/ext/ext0` and `/p/part/t/N/p/mix/ext/ext1`, both `false` in all
580 embedded factory presets. **[INFERRED]** four enum values over two booleans:
`ext0` = MIC/LINE enable, `ext1` = LINE enable, with NONE = neither and
MIC/LINE+LINE = both. Which boolean is which is **[INFERRED]** from the enum's
listed order, not read.

### 7.3 Where they go — and the manual is wrong

**[READ]** `las-frontend` OUTPUT MATRIX, offsets `0x7e701ec` and `0x7e70239`:

```
0x7e701ec  INSERT 4 - EXT LINE
0x7e70239  INSERT 3 - EXT MIC
```

**[READ]** `las-sc` OSC addresses (`usr/bin/las-sc` at `0x1e64e8`, `0x1e6501`):

```
/p/mix/mic-aux3
/p/mix/line-aux4
```

**[READ]** `las-sc` voice-controller addresses (`0x1e091e`, `0x1e0ee0`):

```
/a/in1-ins4
/a/in2-ins3
```

**[READ]** The preset fields, present in all 580 embedded presets and in the live key
dump:

```
/p/part/mix/ext-dir3
/p/part/mix/ext-dir4
```

Four independent places in the firmware, and they all say the same thing:

> **MIC/LINE (the combo jack) → INSERT 3.  LINE → INSERT 4.**

**[READ]** The manual says the opposite. Twice.

Manual PDF page 19 (printed 20):

> From the Output module's MORE page, the LINE Input can be routed to the **Insert 3**
> buss, and the XLR/1/4" combo jack can be routed to **Insert 4**.

Manual PDF page 54 (printed 55):

> **INSERT 3 - EXT 1/4** (OFF, ON) — …route an audio signal arriving at the
> EXT INPUT 1/4" jack to the INSERT 3 buss.
> **INSERT 4 - EXT XLR** (OFF, ON) — …route an audio signal arriving at the
> EXT INPUT XLR jack to the INSERT 4 buss.

**[READ]** This is not a version drift. `captures/rootfs-1.5.0/usr/bin/las-frontend`
carries the identical strings `INSERT 4 - EXT LINE` and `INSERT 3 - EXT MIC`, and
`captures/rootfs-1.5.0/usr/bin/las-sc` carries the identical `/p/mix/mic-aux3` and
`/p/mix/line-aux4`. The firmware has said MIC→3, LINE→4 since at least v1.5.0.

**[INFERRED]** The manual (dated 8/2/19) is in error, or describes pre-release
hardware. The instrument's own screen is the thing the owner will actually see, and
it reads `INSERT 3 - EXT MIC` / `INSERT 4 - EXT LINE`. This is
**load-bearing**: anyone patching by the manual will send the wrong input to the
wrong insert buss. It is also cheap to settle on the instrument — see the validation
plan.

### 7.4 The EXT input has two destinations, not one

Worth stating plainly, because the two are often conflated:

1. **Into the analog voice mixer**, per Synth, as a *sound source* alongside the
   oscillators. **[READ]** `/p/part/t/N/p/mix/ext/{g, fa, fb, ext0, ext1}` — level,
   route-to-filter-A, route-to-filter-B, and the two source enables. The manual's spec
   sheet lists it: "MIXER: Independent levels and filter routing for OSC 1, OSC 2,
   OSC 3, RING MOD, NOISE, and **EXT IN**". This path has its own VCA on each voice
   card (**[READ]** `CALIBRATING EXTERNAL INPUT VCA`, `/cal/extin`).
2. **Into the INSERT 3 / INSERT 4 output busses**, as a straight pass-through.
   **[READ]** `/p/part/mix/ext-dir3`, `/p/part/mix/ext-dir4`.

Only one of 580 factory presets sets either: **[READ]** `ext-dir4` is `true` in
exactly one, `false` in 579; `ext-dir3` is `false` in all 580.

---

## 8. The INSERT jacks

**[READ]** Manual, PDF page 18 (printed 19) and page 55 (printed 56), plus the
specification line:

> AUDIO INSERTS : Insert 1, Insert 2, Insert 3, Insert 4 (1/4" TRS Send / Returns —
> Can be used as TS monaural outs)

The mechanism, from the manual, PDF page 55:

* **Tip = Send, Ring = Return**, on a single 1/4" TRS jack per insert. [READ]
* Used with a plain TS cable, an insert is simply a **mono output**. [READ]
* Odd inserts (1, 3) merge their return to the **MAIN L** buss; even inserts (2, 4)
  merge their return to the **MAIN R** buss. [READ]
* Adjacent pairs (**1 & 2**, **3 & 4**) are **normalled**: if nothing is plugged into
  the return of insert 2, insert 1's return goes to *both* MAIN L and MAIN R.
  Likewise 3 → both, if 4 is empty. [READ]
* **[READ]** "When active, the onboard Synth Effect is applied to each Synth
  **before** its signal reaches the output (Tip) of the insert jack."
* **[READ]** "Output Routing for the Insert channels is one-to-one, meaning each
  Synth can only be assigned to one Insert at a time, and each Insert can only host
  one Synth at a time." (PDF page 52)

### 8.1 The normalling is visible in the DSP

**[READ]** `synthdefs.scd:228-236` — the `inputRouter`'s send routing vectors, with
the firmware's own comments:

```supercollider
send1_r = #[1, 1, 0, 0], // route to [master1L, master1R, master2L, master2R]
send2_r = #[0, 0, 1, 1], // route to [master1L, master1R, master2L, master2R]
/* DUAL MONO CONFIG
send1_r = [1,1,0,0];
send2_r = [0,0,1,1];
STEREO CONFIG
send1_r = [0,0,1,0];
send2_r = [0,0,0,1];
*/
```

**[READ]** `efx_server.scd:134-140` switches between them on
`/p/part/las-fx/mode`. In **DUAL MONO**, `send1` goes to *both* channels of master
bus 1 — the same "one signal, both sides" behaviour the manual describes for an
un-normalled return. In **STEREO**, `send1` is the left channel and `send2` the
right.

**[READ]** The mode enum's UI strings are at `las-frontend` `MasterEffectTypePanel`:
`PING PONG`, `DUAL MONO`, `STEREO`, under the label `MASTER BUS MODE`.

> **Careful.** The *manual's* normalling is an **analog** property of the insert
> return wiring, feeding the MAIN buss. The `send1_r`/`send2_r` matrix is a
> **digital** property of the master-effect send busses. They are the same *shape* of
> behaviour in two different places, and the shape is what makes the correspondence
> legible — but I have **not** read anything that says the digital matrix implements
> the analog normalling. Treat the connection as **[INFERRED]**, and weakly.

### 8.2 Insert send routing, per Synth

**[READ]** Preset fields, per Synth N ∈ {1,2,3}:

| field | meaning | UI label |
|---|---|---|
| `/p/part/t/N/mix/main-en` | route Synth N to MAIN L/R | `MAIN - SYNTH N` |
| `/p/part/t/N/mix/sub-en` | route Synth N to SUB L/R | `SUB - SYNTH N` |
| `/p/part/t/N/mix/dir1` | route Synth N to INSERT 1 | `INSERT 1 - SYNTH N` |
| `/p/part/t/N/mix/dir2` | route Synth N to INSERT 2 | `INSERT 2 - SYNTH N` |
| `/p/part/t/N/mix/dir3` | route Synth N to INSERT 3 | `INSERT 3 - SYNTH N` |
| `/p/part/t/N/mix/dir4` | route Synth N to INSERT 4 | `INSERT 4 - SYNTH N` |
| `/p/part/t/N/mix/aux1` | **master effect send 1** level (float) | `SEND 1 - SYNTH N` |
| `/p/part/t/N/mix/aux2` | **master effect send 2** level (float) | `SEND 2 - SYNTH N` |

> **The word `aux` is overloaded, and this has probably caused confusion before.**
> At *timbre* scope, `/p/part/t/N/mix/aux1` and `aux2` are the **two master-effect
> sends**. At *global* scope, `/p/mix/aux1-db … aux4-db` are the **four INSERT jack
> output levels**. Inside `las-sc`, `timbre-N-aux1`/`aux2` are the send levels while
> `timbre-N-aux1-en … aux4-en` are the four INSERT enables. Same prefix, three
> meanings. All **[READ]** from the rodata name pairs at `0x1e4ed7`–`0x1e5297` and the
> preset field list.

---

## 9. Headphones and MASTER VOLUME

**[READ]** Manual, PDF page 140: `HEADPHONES : 2x Stereo 1/4" jacks (located on the
front edge of the Left Hand Controller)`. Two jacks, both fed the same signal
(PDF page 17: "a pair of front-facing stereo headphone outputs").

**[READ]** Manual, PDF page 52:

> MASTER VOLUME (0 to 10) — controls the MAIN L/R output level.
> HEADPHONES (0 to 10) — controls the volume of the HEADPHONES jacks, **which are not
> affected by the MASTER VOLUME knob**.
> …Unlike every other knob on the Front Panel, these knobs always display their true
> value in a "what you see is what you get" manner.

**[READ]** and: `NOTE: The SUB OUTS are not affected by the MASTER VOLUME knob.`

### 9.1 There is no headphone DAC channel

All eight DAC channels are accounted for by MAIN L/R, SUB L/R and INSERT 1-4 (§5.4).
**[INFERRED]** The headphone feed is therefore derived in the **analog** domain,
tapped from the MAIN bus *ahead* of the master volume control — which is exactly what
"not affected by the MASTER VOLUME knob" requires.

### 9.2 But it is under digital control

**[READ]** `usr/bin/las-sc` at `0x1e63b2` and `0x1e63fe`, as a paired table:

```
/a/main        /m/main
/a/main_mute   /m/main_mute
/a/hph         /m/hph
/a/hph_mute    /m/hph_mute
```

**[READ]** These four appear in `las-sc` only. `grep -c` over `las-frontend` returns
**0** for `/a/` and `/m/` addresses of any kind.

**[INFERRED]** `/a/…` is the address `las-sc` sends *to the XMOS voice controller*
(the same family as `/a/main`, `/a/subl`, `/a/aux1..4`, `/a/vol`, `/a/in1`, `/a/in2`,
`/a/stat/*`); `/m/…` is a parallel mirror. So MASTER VOLUME and HEADPHONES level
**are** digital values that `las-sc` pushes to the analog control hardware — but they
are **not preset parameters and not `/p` addresses**. That is consistent with the
manual's "always display their true value": they are live panel state, not recalled
values.

**[INFERRED]** `las-sc` is started with `--panel-state=localhost:9500`
(**[READ]** `etc/init.d/S42sc:4`; the string `:9500` is in `las-sc` rodata at
`0x1e4d36`), so the knob positions reach it by querying the frontend's panel-state
service rather than through the preset namespace.

**[UNKNOWN]** the scaling of `/a/hph` and `/a/main`, and whether they are directly
writable.

---

## 10. CV I/O and the pedal jacks

**[READ]** Manual, PDF page 140:

```
CONTROL VOLTAGE INPUTS  : CV IN 1, CV IN 2 (1/4" TS)
CONTROL VOLTAGE OUTPUTS : CV OUT 1, CV OUT 2, CV OUT 3, CV OUT 4 (1/4" TS)
PEDAL INPUTS            : Sustain, EXP 1, EXP 2 (1/4" TRS; configurable through the
                          Modulation Matrix, or as 1/4" TS CV Inputs)
```

**[READ]** Manual, PDF page 130: "Moog One is equipped with **five** 1/4" TS Control
Voltage (CV) Inputs on the rear panel — CV IN 1 and CV IN 2, plus the PEDALS inputs
for Expression — EXP 1, EXP 2, and SUSTAIN."

So: **2 dedicated CV inputs + 3 pedal jacks usable as CV inputs = 5 CV inputs**, and
**4 CV outputs**. The firmware agrees exactly.

### 10.1 The namespace

**[READ]** From `las-frontend`'s `/p` address set and from the embedded factory
presets:

```
/p/part/cv_settings/cv_input/cvin_1/{dest,min,max,synth}
/p/part/cv_settings/cv_input/cvin_2/{dest,min,max,synth}
/p/part/cv_settings/cv_input/expr_in_1/{dest,min,max,synth}
/p/part/cv_settings/cv_input/expr_in_2/{dest,min,max,synth}
/p/part/cv_settings/cv_input/sustain/{dest,min,max,synth,type}
/p/part/cv_settings/cv_output/{1,2,3,4}/{source,min,max,synth,voice_rule}
```

Five inputs (the sustain jack alone has the extra `type`, for normally-open vs
normally-closed pedals), four outputs. Per-Synth duplicates exist at
`/p/part/t/N/in/cv/{cv1,cv2,exp1,exp2,sus}/{dest,out-min,out-max}`.

### 10.2 The voltage encoding

**[READ]** A factory preset from `las-frontend`:

```
/p/part/cv_settings/cv_output/1/max 1000
/p/part/cv_settings/cv_output/1/min 0
/p/part/cv_settings/cv_output/1/source "PITCH CV"
/p/part/cv_settings/cv_output/2/max 1000
/p/part/cv_settings/cv_output/2/min 500
/p/part/cv_settings/cv_output/2/source "GATE"
```

**[READ]** Manual, PDF page 131: `VOLTAGE MIN (−5.00V to +5.00V)`,
`VOLTAGE MAX (−5.00V to +5.00V)`, and the same for
`OUT VOLTAGE MIN` / `OUT VOLTAGE MAX`.

**[INFERRED]** The integer field is **0…1000 mapping linearly onto −5.00 V … +5.00 V**,
so 500 = 0 V and one step = 10 mV. The corroboration is the GATE default: a gate
should swing 0 V to +5 V, and the preset sets `min 500, max 1000` — exactly 0 V to
+5 V under this mapping. PITCH CV, which wants the full range, is `min 0, max 1000`.
Three further presets in the same block (`PITCH WHEEL` 0…1000, `MOD WHEEL` 500…1000)
fit the same reading.

### 10.3 The hardware is a separate DAC, and it is calibrated

**[READ]** `las-frontend`, `CVOutCalibrationPanel` and `CVInCalibrationPanel`:

```
CV OUT CALIBRATION (1/10)
USE A MULTIMETER TO MONITOR THE DC VOLTAGE OUTPUT OF EACH CV OUT.
USE THE ENCODER AND SOFT POT TO CALIBRATE +5V AND -5V FOR EACH
BY ADJUSTING THE CORRESPONDING DAC VALUE.
+5V
-5V

CV IN CALIBRATION (2/10)
CONNECT CV OUT 1 TO CV IN 1 AND CV OUT 2 TO CV IN 2.
USE THE SOFT KNOBS TO SET THE OUTPUT OF CV OUT 1 AND
CV OUT 2. VERIFY CORRECT READINGS FROM CV IN 1 AND CV IN 2.
```

with the calibration addresses

```
/cal/cv/3/x   /cal/cv/4/x
/cal/cvin/cvin0/{x0,x1}
/cal/cvin/cvin1/{x0,x1}
```

**[READ]** ±5 V is the calibrated hardware range, confirming §10.2's endpoints.
CV outputs are driven by **their own DAC** ("the corresponding DAC value"), not by
the audio DAC — the eight audio channels are fully accounted for by §5.4.
CV inputs get a **two-point** calibration (`x0`, `x1` = offset and gain);
CV outputs get a single coefficient each.

**[READ]** `/cal/cv*` appears in `las-frontend` but **not** in `las-sc`
(`grep -c` = 0). **[INFERRED]** CV calibration is dispatched by the frontend, not
through the sound-engine controller — a different path from voice-card calibration.

### 10.4 `voice_rule` — closing an open question

`docs/CORRECTIONS-2026-09-08.md` §9 left this open: "only Lisa Bella Donna's 25
[presets] also set `cv_output/N/voice_rule`, which this instrument's namespace dump
does **not** list. Firmware difference, or a hole in the dump — undetermined."

**It is a firmware difference.** **[READ]**

| | v1.5.0 `las-frontend` | v1.8.2 `las-frontend` |
|---|---|---|
| occurrences of the token `voice_rule` | **1** (the bare node name at `0x2ce…`, plus the UI label `VOICE RULE`) | **5** |
| `/p/part/cv_settings/cv_output/N/voice_rule` as a preset key | **0** | **4** (N = 1..4) |

The parameter and its UI label exist in both builds; only from 1.8.2 are the four
addresses **serialised into presets**. The owner's instrument runs 1.5.0, whose
factory presets never write the field — which is precisely why the live dump taken
from it does not list it. Not a hole in the dump.

---

## 11. The two mixers

The firmware has **two** distinct things called a mixer, at different points in the
signal path and in different domains. Conflating them is easy and this document
should make it hard.

### 11.1 The per-voice analog mixer (front panel MIXER module)

**[READ]** `/p/part/t/N/p/mix/{o1,o2,o3,rm,n,ext}/…`, and in `las-sc`'s flat
single-timbre form `/p/mix/{o1,o2,o3,rm,n,ext}/…`:

| source | leaf parameters |
|---|---|
| `o1`, `o2`, `o3` — oscillators 1-3 | `g` (level), `fa`, `fb` (route to filter A / B), `plsbal` |
| `rm` — ring modulator | `g`, `fa`, `fb` |
| `n` — noise | `g`, `fa`, `fb` |
| `ext` — **EXT INPUT** | `g`, `fa`, `fb`, `ext0`, `ext1` |

Plus `/p/part/t/N/p/mix/en` and `/p/part/t/N/p/mix/ngate/gain`.

**[READ]** Each has a `_m` twin in `las-sc` (`/p/mix/o1/g_m`, `/p/mix/ext/g_m`, …) —
the modulation sums described in the project's existing architecture notes.

**[READ]** UI labels, `las-frontend` `MixerPanel` at `0x7e70f35`–`0x7e70f50`:
`VCO 1`, `VCO 2`, `VCO 3`, `RING MOD`, `EXTERNAL`, and the label suffix ` - MIXER`.

This mixer is **analog, on the voice card**, and it is where EXT INPUT becomes a
playable sound source.

### 11.2 The digital output mixer (OUTPUT MORE page)

Everything in §5.5 and §8.2: `/p/mix/*-db`, `/p/part/t/N/mix/*`,
`/p/part/mix/ext-dir{3,4}`. This mixer lives in `scsynth`'s `outputRouter`
(**[READ]** `synthdefs.scd:401-593`) plus the analog output section the XMOS drives.

### 11.3 The internal SuperCollider busses

**[READ]** Recovered by the same `las-sc` method as §5.2 and §6.1 (lf 438-451,
initialised at `0x8c328`–`0x8c3c8` as fixnums 101…127), and **independently
confirmed** by the `In.ar`/`Out.ar` calls in `synthdefs.scd`:

| symbol | bus | confirmed at |
|---|---|---|
| `insert1-out-l` / `insert1-out-r` | 50 / 51 | `synthdefs.scd:294`, `:460` |
| `insert2-out-l` / `insert2-out-r` | 52 / 53 | `:295`, `:461` |
| `insert3-out-l` / `insert3-out-r` | 54 / 55 | `:296`, `:463` |
| `master1-in-l` / `master1-in-r` | 56 / 57 | `:380-381` (`Out.ar(56/57)`) |
| `master2-in-l` / `master2-in-r` | 58 / 59 | `:384-385` |
| `master1-out-l` / `master1-out-r` | 60 / 61 | `:273`, `:464` |
| `master2-out-l` / `master2-out-r` | 62 / 63 | `:465` |

All fourteen agree between the compiled binary and the `.scd`. "insert 1/2/3" here
means the **three Synth-effect insert slots**, not the four INSERT jacks — a third
sense of the word. `las-sc` also carries the routing keys
`insert-{1,2,3}-{inbus,outbus}`, `master-{1,2}-{inbus,outbus}`,
`timbre-{1,2,3}-send{1,2}` and `timbre-{1,2,3}-aux{1,2}` as string literals at
`0x1e4d41`–`0x1e4f36`. **[READ]**

---

## 12. Parameters with no UI and no preset field

**[READ]** These OSC addresses exist as literal strings in `las-sc` (both v1.5.0 and
v1.8.2), appear **zero** times in `las-frontend`, and appear **zero** times in the
live preset key dump `captures/p-namespace-keys.txt`:

| address | count in `las-sc` | count in `las-frontend` | in preset dump |
|---|---|---|---|
| `/p/mix/mic-db` | 2 | 0 | no |
| `/p/mix/line-db` | 2 | 0 | no |
| `/p/mix/mic-aux3` | 2 | 0 | no |
| `/p/mix/line-aux4` | 2 | 0 | no |
| `/p/mix/aux3-send1` | 2 | 0 | no |
| `/p/mix/aux4-send2` | 2 | 0 | no |
| `/p/mix/sub-bal` | 2 | 0 | no |
| `/p/mix/aux-bal` | 2 | 0 | no |

Controls, for comparison — same greps, addresses that *are* exposed:

| address | count in `las-sc` | count in `las-frontend` | in preset dump |
|---|---|---|---|
| `/p/mix/aux1-db` | 2 | 581 | yes |
| `/p/mix/sub-db` | 2 | 581 | yes |
| `/p/part/mix/ext-dir3` | 2 | 581 | yes |

**[INFERRED]** `mic-db` / `line-db` are the two EXT input trims *in the digital
domain*, `mic-aux3` / `line-aux4` are the `las-sc`-side form of the `ext-dir3` /
`ext-dir4` preset fields, and `sub-bal` / `aux-bal` are L/R balance controls for the
SUB pair and the insert group. None of them has a front-panel control and none is
saved in a preset.

**Two important caveats, because this is the sort of finding that gets over-claimed:**

1. `captures/p-namespace-keys.txt` is a **preset key** listing, not a live OSC
   namespace enumeration — it contains `matrix_expression_slots` but **zero**
   occurrences of `/p/pre-expr` or `/p/post-expr`, which `las-sc` is known to own. So
   absence from it proves only *"not preset state"*, **not** *"not reachable"*.
2. Whether `las-sc` actually accepts a write to these addresses at runtime is
   **[UNKNOWN]**. `/p/mix/sub-bal` in particular would be an attractive thing to have,
   and it is exactly the sort of address the project has been burned by assuming into
   existence. A read-only probe is in the validation plan.

---

## 13. Conflicts

Reported, not fixed, per the task's rules.

| # | where | what it says | what this report found |
|---|---|---|---|
| 1 | `captures/Moog_One_Manual_8_2_19.pdf` PDF p.19 and p.54 | LINE → INSERT 3; XLR/combo → INSERT 4 | **Reversed.** Firmware says MIC (combo) → INSERT 3, LINE → INSERT 4, in four independent places, in both v1.5.0 and v1.8.2. §7.3. The manual's *specification* page (p.140) is correct and is what identifies "MIC/LINE" as the combo jack. |
| 2 | `docs/ROADMAP.md:171` | EXT INPUT is a "Neutrik **combi** + LINE" | Substance correct, **word wrong**: manual and firmware both say **combo**. §7.1. |
| 3 | `docs/arch/extension-points.md:919-924, 1659` | "Neutrik combi", "TRIM −9 to +65 dB", "tip = send, ring = return, stereo-normalled pairs" are **[UNVERIFIED]**, "there is no manual in this repository" | The manual **is** now in `captures/` (added 2026-09-08). All three assertions **confirm** [READ], modulo *combi* → *combo*. These three entries can be retired. §7.1, §8. |
| 4 | `docs/ARCHITECTURE.md:77` | "`scsynth` runs with 9 input and 8 output hardware channels, **block size 256**, 48 kHz (`init_sc_1.scd`)" | The channel counts are right; **256 is wrong and the cited file says 128**. `init_sc_1.scd:9-10` sets `blockSize = 128` and `hardwareBufferSize = 128`. This also contradicts `docs/CORRECTIONS-2026-09-08.md` §2, which already corrected it. |
| 5 | `docs/ARCHITECTURE.md:84-93` "Hardware channel map" | ADC table lists only channels 2, 3, 4, 5, 6 | Correct as far as it goes, and the DAC half is exactly right. It is **incomplete**: ADC 1 = `main-in-r`, ADC 7 = `direct-in-4`, ADC 8 = `main-in-l` are missing, and ADC 0 is unaccounted for. §6.3. |
| 6 | `docs/arch/audio-graph.md:288-289, 304-306` | ADC 4/5/6 = timbre 1/2/3 dry, marked **[inferred]** | **Confirmed and upgraded to [READ]** — `las-sc`'s own `direct-in-1/2/3` constants are 4/5/6. §6.1. |
| 7 | `docs/arch/audio-graph.md:290` | bus 7 is "Read by `input`/`default` via `AudioIn.ar(0)` → `In.ar(7)` **[inferred]**" | Arithmetically right (`AudioIn` is 1-based, so `AudioIn.ar(0)` → `In.ar(numOutputBuses − 1)` = 7) and therefore a latent bug in an uninstantiated synthdef, not a conflict. Flagged only so it is not later "discovered" as a routing fact. |
| 8 | `docs/CORRECTIONS-2026-09-08.md` §9 | `voice_rule`: "firmware difference, or a hole in the dump — undetermined" | **Resolved: firmware difference.** The four `cv_output/N/voice_rule` preset keys exist in v1.8.2 and not in v1.5.0. §10.4. |

---

## 14. Validation plan

**READ-ONLY** commands for a human to run on the instrument. Nothing here writes,
calibrates, resets, or plays. **Do not run any Moog binary**: everything below is
`cat`, `amixer`-free, and uses only busybox/coreutils on paths under `/proc` and
`/sys`, or `oscsend`/`oscdump` against `las-sc`'s *own* listen port.

### 14.1 Confirms the ALSA layer (§3)

```sh
cat /proc/asound/cards
cat /proc/asound/pcm
cat /proc/asound/card0/id
cat /proc/asound/card0/pcm0p/info
cat /proc/asound/card0/pcm0c/info
```

Expect one card, `xmosaudio`, one PCM `HiFi`, and — the load-bearing number —
`subdevices_count: 1` on each. If `pcm0c/info` reports a channel maximum other than
9, §4 is wrong.

### 14.2 Confirms the channel counts and block size while running (§4)

```sh
cat /proc/asound/card0/pcm0p/sub0/hw_params
cat /proc/asound/card0/pcm0c/sub0/hw_params
```

Expect `channels: 8` on playback, `channels: 9` on capture, `rate: 48000`,
`period_size: 128`. **This is the single command that settles the block-size
question for good** and closes conflict #4. Run it with the instrument idle but
booted; `hw_params` reads `closed` if the stream is not open.

### 14.3 Determines the TDM geometry — the main **[UNKNOWN]** (§3.2)

```sh
cat /sys/kernel/debug/asoc/xmos-audio/dais 2>/dev/null
ls /sys/kernel/debug/asoc/ 2>/dev/null
cat /sys/kernel/debug/clk/clk_summary | grep -iE 'esai|extal|osc|codec'
```

and, if `debugfs` has no ASoC tree, the ESAI registers directly — **read only**:

```sh
devmem 0x02024000 32     # ESAI ETDR/ECR block base; read the first ~0x40 words
devmem 0x02024004 32
devmem 0x02024008 32
```

`devmem` with **one** argument is a read. Do **not** pass a third argument.
(This project has already established that a single-argument `/cal` write is a
different matter — this is not that; `devmem <addr> <width>` reads.)
The TCCR/RCCR and TFCR/RFCR words give the frame length, slot count and word width
that §3.2 leaves unknown.

### 14.4 Settles the EXT INPUT routing on the instrument itself (§7.3, conflict #1)

No shell needed, and this is the most valuable single check in the list:

> On the instrument, press **MORE** on the **OUTPUT** module and scroll the OUTPUT
> MATRIX to the INSERT 3 and INSERT 4 rows. Photograph the two rows.

The firmware predicts the screen reads `INSERT 3 - EXT MIC` and
`INSERT 4 - EXT LINE`. The manual predicts the opposite. A photograph settles it in
ten seconds and needs no software at all.

A second, physical confirmation, if the owner wants it: plug a signal into the
**combo** (XLR/TRS) jack only, set `INSERT 3 - EXT MIC` to ON, and listen at the
INSERT 3 jack.

### 14.5 Probes the unexposed parameters (§12) — **NOT provably read-only; optional**

This is the one item in this list I cannot certify as safe, and it should be treated
differently from the rest.

`las-sc` listens on `localhost:9300` (**[READ]** `etc/init.d/S42sc:4` passes
`-l localhost:9300`; `las-sc`'s own option help string reads
`Listen address (default localhost:9300`). The project has previously established
that in the `/cal` namespace **one argument writes**, which implies that an address
sent with **no** argument is a query — the basis for the commands below:

```sh
oscdump 9999 &            # or whatever port the reply is addressed to
oscsend localhost 9300 /p/mix/sub-bal
oscsend localhost 9300 /p/mix/mic-db
oscsend localhost 9300 /p/mix/aux-bal
```

**Send no argument, ever, on these three.** But note the honest gap: the
"no argument = read" rule was established for `/cal`, **not** for `/p/mix`, and §12
already shows these three addresses behave unlike their exposed neighbours. If
`las-sc` happens to treat a bare `/p/mix/sub-bal` as "set to default" rather than
"report", this probe changes the mix. Nothing is written to flash either way
(established previously for `/cal`), so the worst case should be a live mixer change
that a power cycle or preset reload undoes — **should**, not *will*.

**Recommendation: skip this unless you specifically want the answer.** Nothing else
in this report depends on it. If it is skipped, §12's finding stands exactly as
written — "present in the `las-sc` binary, absent from the UI and from presets,
live reachability **[UNKNOWN]**" — which is already the useful part.

If it is run and nothing comes back, that is consistent with the addresses not being
served at all.

### 14.6 Confirms the ADC map behaviourally (§6.3)

The safest read-only confirmation is by observation rather than command:

> With a signal source in one INSERT return at a time, watch which Synth's dry path
> and which insert-effect input responds. `direct-in-1..3` predicts Synth 1, 2, 3 on
> ADC 4, 5, 6.

For ADC 0 — the unexplained channel — and ADC 7 (`direct-in-4`), no in-band test
exists from the shell. **[UNKNOWN]** is the honest answer until someone captures the
raw ESAI RX stream, which is not a read-only operation on this instrument.

---

## 15. Unexplored

Named so the next pass does not have to rediscover the gaps.

1. **The ESAI TDM geometry.** Slot count, word width, frame length, and which of the
   eight muxed pads is which signal. §3.2. Needs `imx6dl-pinfunc.h` (not in this
   repository) or the live register read in §14.3.
2. **ADC channel 0.** Nine capture channels are configured; eight are named in
   `las-sc` and read in `synthdefs.scd`. Channel 0 is neither. §6.3.
3. **`direct-in-4` (ADC 7).** Defined by `las-sc`, dead in the SuperCollider graph.
   What, if anything, is physically on it. §6.3.
4. **The XMOS side.** `usr/share/xmosfw/app_las_v2.2.2.bin` (2,097,152 bytes) is the
   voice controller and owns the other end of the ESAI link, the analog output
   section, the insert normalling and the CV hardware. I did not open it. Note that
   the existing corrections doc records XMOS strings being stored **bit-reversed**,
   so a naive `strings` pass will find little. `docs/arch/xmos-deep.md` and
   `docs/firmware/xmos.md` are the places to look first.
5. **The `/a/` and `/m/` namespaces in full.** I enumerated them
   (`/a/main`, `/a/subl`, `/a/aux1..4`, `/a/hp`, `/a/hph`, `/a/hph_mute`, `/a/vol`,
   `/a/in1`, `/a/in2`, `/a/in1-ins4`, `/a/in2-ins3`, `/a/stat/*`, `/m/main`,
   `/m/main_mute`, `/m/hph`, `/m/hph_mute`) but did not trace their argument types,
   scaling, or which are writable. `/a/hp` vs `/a/hph` is an unresolved distinction.
6. **`/p/mix/aux3-send1` and `/p/mix/aux4-send2`.** Present in `las-sc`, absent from
   the frontend. **[INFERRED]** they sum an INSERT buss into a master-effect send,
   but the direction is not read. §12.
7. **The `dai_fmt` set at `hw_params`.** Static value is 0; the runtime value would
   say whether the codec is clock master and whether the format is I²S or DSP_A. §3.3.
8. **Insert one-to-one enforcement.** The manual says each Synth can be on only one
   insert and each insert can host only one Synth. Where that constraint is enforced
   — frontend, `las-sc`, or neither — I did not find.
9. **The `/g/N/…` namespace.** `las-sc` carries `/g/0/…`, `/g/1/…`, `/g/2/…` forms of
   the per-timbre mix addresses (`main-en`, `sub-en`, `dir1-en … dir4-en`, `pan`,
   `aux1`, `aux2`). Its relationship to `/p/part/t/N/…` is **[INFERRED]** to be
   "0-based index instead of 1-based, `las-sc`'s internal form", not read.
10. **Headphone signal origin.** §9.1's tap-before-master-volume is an inference from
    channel-count arithmetic plus the manual's behavioural statement. No schematic or
    firmware string states it.
11. **`bob.bmp` in `/etc` and `/usr/bin/lassvc`.** Adjacent to this region (service
    mode reaches audio calibration) and covered by other passes; not read here.
