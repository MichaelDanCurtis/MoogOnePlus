# The decrypted firmware, read and then cross-examined

Thirty-six reports over the **decrypted v1.8.2 root filesystem** — the first time
this project has read Moog's shipping firmware as plain files — each cross-checked
against the owner's own **v1.5.0** filesystem. ~35,800 lines. Every claim is graded
`[READ]` (quoted from a file, with offset or line), `[INFERRED]` (reasoning, with the
evidence named), or `[UNKNOWN]`. **No agent contacted the instrument.** Proposed live
reads are collected in the Validation plan at the bottom, for a human to run.

This index is written *after* the adversarial verification pass, and it is not a
victory lap. **The verification pass refuted 64 of 120 load-bearing claims.** The
refutations are below, in full and by subsystem, because they are the most valuable
thing here: every one is a survey agent over-reaching from a string, a name, or an
extraction artefact, and the pattern is worth internalising before trusting any
remaining number.

Provenance: v1.8.2 was obtained by decrypting the official update package with the
key Moog ships on every instrument (`/etc/bob.bmp`, 4-bit LSB steganography,
passphrase `bob`, per `lasfwu`). It is Moog's copyrighted firmware; it lives under
`captures/` (gitignored) and does not leave this machine. The signing key never left
Moog — a repackaged installer cannot be made to install (`CORRECTIONS-2026-09-08.md`
§6). `etc/git-tags` in 1.8.2: `LAS_FRONTEND 2.1.4`, `LAS_FW lasvc-v2.2.2`,
`LAS_VX lasvx-v2.2.1`.

---

## The reports

### Subsystems (14)

| report | one line |
|---|---|
| [`lassvc.md`](lassvc.md) | The 3.4 MB factory service/bring-up console: `/cal` `/info` `/fw` `/hw` `/mix` `/testosc`, the "phone home (alpha)" reverse tunnel, identity writes. **Several of its headline claims were refuted — see below.** |
| [`las-sc-namespace.md`](las-sc-namespace.md) | The engine's OSC surface and `part-dispatch`; finds `/p/pre-expr`, `/p/post-expr` and the 115 `_m` twins are a never-read constant. Dispatch detail and namespace ownership corrected by the verifier. |
| [`las-frontend-ui.md`](las-frontend-ui.md) | JUCE UI architecture; establishes an edited mod-matrix row goes to the XMOS at `/g/<synth>/t/e/s` on 7770, not to `las-sc` on 9300. Outbound-MIDI ownership corrected. |
| [`las-frontend-data.md`](las-frontend-data.md) | Preset storage, the SQLite schema, the 580 embedded `.m1p`, `/p/version` migration. Schema-table count, the blob encoding, and the version-discriminator claim all corrected. |
| [`las-fx.md`](las-fx.md) | The SuperCollider effects engine: `/usr/share/las-fx` is byte-identical 1.5.0↔1.8.2; closes the LADSPA-path question; corrects the CPU-policy attribution. |
| [`init-boot.md`](init-boot.md) | Boot sequence, A/B(/C) slots, the updater, the watchdog, shutdown. Source of the `mount -f`, `sched_rt`, and `lasfwu` dd findings — each re-graded by the verifier. |
| [`kernel.md`](kernel.md) | Kernel 4.1.15-rt18, modules, DTB, the ESAI/TDM path, CPU isolation (`isolcpus=1`, not `nohz_full`), thermal. |
| [`network.md`](network.md) | Every listening service, dropbear + the `k`-file root hook, avahi, the two fighting DHCP clients, no host firewall. |
| [`xmos.md`](xmos.md) | The voice-controller images and `xmosfw` metadata; `las_layout` flashes a 1.75 MiB region of a 2 MiB chip. Version-word endianness and loader-sharing claims corrected. |
| [`calibration.md`](calibration.md) | `/cal` (223 literals across ten binaries), the 17 calibrations, `vxcal.db` (empty on this unit), `tuning.vxtune`, the user-runnable procedure. |
| [`small-binaries.md`](small-binaries.md) | Ten helpers never read: watchdog, dwm, fb-config, frontpanel-poll, `config-las-spi`, `flashbench`, `psplash`, `str`, `lasfwu`, `las_clock_demo`. |
| [`presets-content.md`](presets-content.md) | The factory library as shipped vs the download; 580 `.m1p` + 186 effect presets compiled into `las-frontend`, written to SQLite on first boot. |
| [`audio-io.md`](audio-io.md) | The channel map (8 DAC / 9 ADC) read from `las-sc`'s constant table; the EXT INPUT routing; one place the manual is wrong about its own instrument. |
| [`js-sandbox.md`](js-sandbox.md) | Verifies the JS sandbox claim: it is JUCE's `JavascriptEngine` under `LASScriptRunner`, 365 s runtime cap. `cal*` methods target the panel/keybed, not voice cards (a correction). |

### Diffs, 1.5.0 → 1.8.2 (4)

| report | one line |
|---|---|
| [`diff-files.md`](diff-files.md) | Between versions Moog replaced **two files**: the XMOS firmware pair. Everything else differing is rebuild noise or project contamination of the trees. |
| [`diff-binaries.md`](diff-binaries.md) | Symbol/string/function diffs of `las-sc`, `las-frontend`, `lassvc`, `las-watchdog`; `las-sc`'s `.rodata` string set is identical across versions. |
| [`diff-osc.md`](diff-osc.md) | `las-sc`'s OSC namespace did not change at all; all of the 1.8.x namespace work is 67 new `/p/…` keys in `las-frontend`. |
| [`diff-upgrade.md`](diff-upgrade.md) | Should the owner install 1.8.2? Recommends yes; the rollback slot destroyed is v1.4.0, not v1.5.0. |

### Gaps — regions no prior report had opened (18)

| report | one line |
|---|---|
| [`gap-eec-expression-compiler.md`](gap-eec-expression-compiler.md) | `/usr/bin/eec` compiles expression text to Q24 words and ships an OSC blob to `vc:7770`; carries a 47-entry instruction reference with five documented defects. Resolves `rcl`. |
| [`gap-sc-ugen-plugin-inventory.md`](gap-sc-ugen-plugin-inventory.md) | The 96 plugin `.so` register **795 UGens**; the live class library can name 360, the 104 synthdefs use 61 — 734 resident UGens nothing instantiates (STK, JPverb/Greyhole, Ambisonics…). |
| [`gap-chicken-egg-capability-inventory.md`](gap-chicken-egg-capability-inventory.md) | Every installed CHICKEN egg, which are linked into a shipping program, and which procedures are actually called. |
| [`gap-observability-toolkit.md`](gap-observability-toolkit.md) | 17.5 MiB of strace/gdb/sysstat/blktrace/apitrace/jack tooling, unchanged 1.5.0↔1.8.2; half cannot run here. `pidstat`/`netcap`/`dumpe2fs` are the usable, read-only wins. |
| [`gap-qt5-webkit-jsc-runtime.md`](gap-qt5-webkit-jsc-runtime.md) | A complete, loadable, entirely unused Qt5+QtWebKit install; `jsc` is a real second JS engine (JavaScriptCore) — buildroot residue nothing invokes. |
| [`gap-las-frontend-http-client.md`](gap-las-frontend-http-client.md) | A complete TLS-verifying HTTP client (JUCE `WebInputStream` / libcurl / 179-root CA bundle) that nothing calls; the one reachable endpoint is a never-constructed usage-reporting POST. |
| [`gap-directfb-graphics-stack.md`](gap-directfb-graphics-stack.md) | DirectFB 1.7.7 installed complete, wired to nothing, ever; its `linux_input` would find only `gpio-keys`, not the panel/keybed (correcting the brief's premise). |
| [`gap-x11-display-and-build-residue.md`](gap-x11-display-and-build-residue.md) | The X11/Vivante/GPU config; the 832×480 width is the kernel's own `CLAA-WVGA` modedb entry, not a stride; 39 MB of dead GPU samples. |
| [`gap-fuse-union-overlay-capability.md`](gap-fuse-union-overlay-capability.md) | FUSE + unionfs-fuse present; `fusermount` **is** setuid root (read from the ext4 image; the extraction dropped every setuid bit — a methodological warning for the whole corpus). |
| [`gap-uboot-env-and-flash-fuse-tooling.md`](gap-uboot-env-and-flash-fuse-tooling.md) | U-Boot env tools can't run as shipped; `flash_otp_*` can't answer the HAB question — `fsl_otp` sysfs can. Flags the single most destructive command surface in the project. |
| [`gap-factory-cal-scripts.md`](gap-factory-cal-scripts.md) | Five Moog cal scripts (not three); `run_process`'s 15-entry menu is the true `--cal-op` vocabulary; the built-in `vxtune` help is stale. |
| [`gap-las-fx-coefficient-archive.md`](gap-las-fx-coefficient-archive.md) | `tables/coefsEnvir` (5.4 MB) decodes completely — textbook RBJ/DAFX biquads on a linear grid, no proprietary design, and unreachable at runtime. |
| [`gap-mcast-fec-mtd-image-receiver.md`](gap-mcast-fec-mtd-image-receiver.md) | `recv_image`: a stock mtd-utils multicast+FEC flash writer — a second, entirely unwired image-deployment path, inert on an MTD-less eMMC board. |
| [`gap-wireless-802-11-orphan-stack.md`](gap-wireless-802-11-orphan-stack.md) | A full Wi-Fi userspace + 11 Realtek blobs on a kernel with **no wireless subsystem at all**; retrofit needs a kernel rebuild, not a dongle. |
| [`gap-udev-device-naming-layer.md`](gap-udev-device-naming-layer.md) | `hwdb.bin` never built, 5 MB of hwdb inert, 12 rule lines dead; the module-alias index is empty so on-demand modprobe can't match. |
| [`gap-ftdi-usb-serial-bringup-toolkit.md`](gap-ftdi-usb-serial-bringup-toolkit.md) | No FTDI device exists; the nine libftdi examples are buildroot residue; libftdi is present only because `flashrom` links it. |
| [`gap-firmware-pgp-trust-material.md`](gap-firmware-pgp-trust-material.md) | Decodes every key packet in `usr/share/sec/` offline (IDs, fingerprints, S2K) without reproducing secret bytes; confirms decrypt-yes / re-sign-no. |
| [`gap-on-device-editor-and-desktop-userland.md`](gap-on-device-editor-and-desktop-userland.md) | `em`, gnuchess, lbreakout2/ltris, `fluid`; the `/var/*.hscr` high scores are built-in defaults, **not** evidence anyone played. Nothing is wired to a launcher. |

---

## What the verification pass refuted

64 of 120 load-bearing claims were overturned or re-graded. Grouped by where the error
lives. Each entry states the **claim** and the **correction**, with the correction's own
grades preserved.

### lassvc — the service binary the survey overreached on most

1. **"`lassvc` is started at boot."** No. It appears nowhere in `etc/inittab` or
   `etc/init.d/` (inittab starts only `rcS` plus a vt100 getty). Exactly two scripted
   invocations exist, identical in both versions: `detect-held-buttons:19` (launched from
   `S43gui:76`; on front-panel code 48 it kills the stack and runs `lassvc` inside an
   `xterm` *because it is spawned from an init script with no controlling tty*), and
   `start_tune:17` (runs `lassvc` **directly**, no xterm). It needs a controlling terminal
   but **not X** — `llvm-objdump -p` shows zero libX11. Mode 0755 on PATH, with a serial
   getty and dropbear both available, so any root shell can invoke it. **[READ]**

2. **"`lassvc`'s namespace is 12 addresses, wholly disjoint from `las-sc`'s."** Wrong
   twice. It is **245 distinct `.rodata` literals** across ~30 first segments. The offered
   evidence "none begin with `/p`" is false — `/p1/d`, `/p2/d`, `/p3/d`, `/ping` all do.
   **155 of the 245 are byte-identical to literals in `las-sc`** (the whole `/cal/*`,
   `/mix/*`, `/hw/*`, `/fw/*`, `/testosc/*`, `/a/stat/*`, `/vx/`, `/dbg` sets). They are
   two clients of the **same** hardware plane; `las-sc` additionally serves `/p` on top.
   `lassvc` drives two endpoints — `--vc-target` (default `las.local:7770`) and
   `--panel-target` (default `las.local:9100`) — and the panel/LHC addresses belong to the
   panel endpoint. **[READ]**

3. **"`/info/write` and `/info/protect` are `[READ]` identity writers driven by the
   serial/MAC/UUID menu items."** Split by grade. `[READ]`: `lassvc` does contain write
   paths for serial/MAC/UUID, with dedicated Scheme symbols (`set-serial`, `set-mac`,
   `make-uuid`) driving `/info/serial` `/info/mac` `/info/uuid`. `[READ]` also that
   `/info/write` and `/info/protect` exist as literals. But `[INFERRED]` — not `[READ]` —
   that they *commit / write-protect*: there is **no handler symbol** and **no evidence**
   the menu items invoke them. The blanket `[READ]` grade was the defect.

4. **"`lassvc` is the only / primary Linux-side voice-card firmware flasher."** No. The
   flasher is a **shared CHICKEN library** (`vxfw-lib`) statically linked into at least
   five binaries (`las-sc`, `lassvc`, `vxtest`, `vxmon`, `vxtune`). `lassvc` links it but
   contains **no call site** and exposes no flash menu item. The live driver with call
   sites is in **`las-sc`** (`sc/sc.scm:659`, `:708`), the process that runs at boot.

5. **"A completed phone-home exposes passwordless root."** No. The phone-home starts its
   own dropbear with `start-stop-daemon … --exec /usr/sbin/dropbear -- -R` — a direct exec
   with **`-R` only** that never reads `/etc/default/dropbear` and contains no `-B`. Under
   `-R` alone, root's empty `/etc/shadow` field is a **lockout, not a bypass**: dropbear
   2015.71 gates the blank-password path on a flag set only by `-B`, and otherwise rejects
   the account ("User '%s' has blank password, rejected"). No pubkey fallback
   (`/root/.ssh/authorized_keys` absent). `-B` is supplied only by `S50dropbear`, and only
   when `/media/thumbdrive/k` hexdumps to `23051934` — i.e. the **physical service
   dongle**. What the tunnel actually exposes is a dropbear reachable as user **`las`**,
   whose password is **[UNKNOWN]** and protected by an obsolete 13-char DES hash — a real
   but password-gated, **non-root** exposure. **[READ]**

### las-sc — dispatch, ownership, and what it touches

6. **"An unmatched OSC address hits the terminal chunk and returns without sending."**
   Confirmed `[READ]` — but the `cond` is **not "twelve-way" and not uniformly
   `string-prefix?`**. It is 15 clauses / 16 literal tests: 8 `string-prefix?`
   (`sc.scm:237-244`), 6 **exact** `C_i_string_equal_p` (`:245-250`), and one `or` of two
   more `string-prefix?` (`:251`, `/status` and `/info`). `/p/pre-expr` takes the
   fall-through path **only when delivered to `las-sc`'s own socket** — not its normal
   path, since the flat `/p` namespace is served elsewhere. The drop is also not literally
   silent: when `quiet-mode` is false the loop formats the message via `osc-format` before
   dispatch. "Silent" means "no OSC reply." **[READ]**

7. **"`las-sc` constructs the `_m` addresses at runtime."** The 117 expression-nodes
   strings each occur **exactly once in the entire 1.8.2 rootfs**, all in `las-sc`
   (`[READ]`, strengthened — full byte scan + UTF-16 + decompression of 387 archives).
   `las-sc` contains **no standalone `_m` literal** `[READ]`. But "does not construct them
   at runtime" is `[INFERRED]`, not `[READ]`: CHICKEN can build `"_m"` from char
   immediates. The support is that `las-sc` has no string-building call site in the
   relevant units; and `las-frontend` holds no `"_m"` string at all.

8. **"`--expr-syms=/usr/share/vx_ee.scm` configures `las-sc`; the only file it opens is
   `thermal_zone0/temp`."** `--expr-syms` is declared and **never retrieved** `[READ]`;
   `"vx_ee"` does not occur in `las-sc`, so the flag does nothing. But the "only file it
   opens" half is wrong: that holds for `open-input-file` only. `las-sc` also **writes**
   `/var/las-sc.cookie` once at startup (`drop-cookie`, `sc.scm:417-421`). Safe form: the
   only file it **reads** is the thermal temp; it also **writes** the cookie; it never
   touches `vx_ee.scm`. **[READ]**

9. **"`las-sc` binds only `127.0.0.1:9300`, talks thermal to `las-sc` on 57120."** It
   binds `9300` `[INFERRED]` (argv `-l localhost:9300` + an unattributed `netstat`), but
   whether that is its **only** socket is `[UNKNOWN]` — the netstat lacked `-p` and there
   are three `string->bound-socket` sites. It talks to the VC at `203.0.113.2:7770`
   `[READ on the wire]`. It talks to the EFX server on **`localhost:7775`, not 57120**
   `[READ]` (`-f localhost:7775` in `S42sc:4`; the `:57120` literal is a default never
   reached in the shipped config). Transport is the CHICKEN **udp6** egg, not the
   socket-egg calls the claim cited.

10. **"`las-sc`'s `part-dispatch` prefix list and per-timbre rewrite."** Of 372 per-timbre
    suffixes, **344 are rewritten** by `handle-t-prefix` to `/g/N/t/…`, **27** (`/p/fx…`)
    map to themselves, and **1** (`/en`) has no branch. The part-dispatch prefix literals
    are exactly `/p/part/t/{1,2,3}/p/fx`, `…/mix`, `/p/part/las-fx`, `/p/part/mix`,
    `…/p/pan`, `…/p/g`, `/status`, `/info` — that half stands. **[READ]**

11. **"The flat `/p` namespace lives in `las-frontend`."** Reversed. **`las-sc` holds the
    498 flat `/p/…` strings** packed in `.rodata` (incl. `/p/o1/po`, `/p/pre-expr`,
    `/p/post-expr`, 107 `_m` twins), with 468 literal-pool refs; **`las-frontend` contains
    zero bare flat addresses** (its 1,832 `/p/o1/po` hits are all inside the 133 MB
    embedded preset blob). Across the whole rootfs, `las-sc` is the only file with
    `/p/pre-expr` or any `_m` twin. `[READ]` Whether `las-sc`'s dispatcher tests the
    **bare flat form** at runtime or only the `/p/part/t/N/…` prefixed form is
    **[UNKNOWN]**. (This overturns `las-sc-namespace.md`'s headline framing.)

12. **"Port 9300 reaches `las-sc` from outside; `--panel-state` sends panel state to
    9500."** 9300 is the `las-sc` OSC-tree link (`las-frontend --port-response` default
    9300; `las-sc -l localhost:9300`). `--panel-state=localhost:9500` means `las-sc`
    **queries** the frontend there and gets panel state back ("getting panel state from
    frontend"); it does not send. The two default port values are **not** readable from
    the help strings (they end at "(dflt " + NUL); they are in code. **[READ]**

### las-frontend — MIDI, the mod matrix, the preset store

13. **"Outbound CC/NRPN is composed by `las::MidiControlOutputUpdater`."** No — it is a
    method of `las::LASFrontEndApplication::Pimpl`. It builds a `/mo/din0` OSC message,
    appends each raw MIDI byte as a separate int32, and sends it via
    `las::PerformanceSender::send`; a port selector chooses DIN / USB / both (`/mo/usb0`
    for USB). `MidiControlOutputUpdater` only writes the output-routing enum. The XMOS
    still performs physical transmission. The perf-output port (commonly cited as 7771) is
    **[UNKNOWN]** by direct read — 7771 occurs nowhere in the binary. **[READ]**

14. **"Inbound MIDI arrives already parsed as OSC on 7772."** Downgrade to **[INFERRED],
    weakly.** `[READ]`: `las-frontend` binds UDP 7772 and has an NRPN/knob path; `--midi-in`
    /`--midi-out` open real ALSA MIDI but **are not passed**; and **no ALSA MIDI device
    exists** (no `snd-rawmidi`/`snd-seq-midi`/`snd-usbmidi` modules; one PCM-only card).
    But nothing read shows DIN/USB MIDI reaching Linux, nor that it arrives on 7772 — the
    receiver's entire inbound vocabulary is `/hw/*`, `/v/*`, `/therm/*`, `/info/serial`,
    **no MIDI-named address**, and `"/mi/"` occurs zero times. Whether inbound MIDI notes
    reach the frontend at all is **[UNKNOWN]**; needs a tcpdump on `lo` udp/7772 while a
    note is played.

15. **"ModMatrixPanel/Row lambdas capture a `Preset` and therefore mutate it."** They
    **receive** a `Ptr<las::Preset>` as a **parameter** (proven by the Itanium-ABI closure
    mangling, which encodes parameters only — captures are never mangled, so the capture
    set is **[UNKNOWN]** from strings). The shape is a generic scoped-accessor callback,
    occurring **51 times across 19 classes** including read-only browsers. Whether these
    write only in-memory is **[UNKNOWN]** (counter-evidence: a `LASDatabase&` lambda nested
    inside one body, and a `/p/modmatrix` literal in the panel's string block).

16. **"1.8.2 address-level findings apply to the owner's 1.5.0 instrument."** No. The two
    `las-frontend` builds share an identical CLI and `S43gui`, and nearly identical class
    inventories (1.8.2 adds `GlideOnOffTriggerUpdater`), **but `.text` differs in 81% of
    overlapping bytes, `.rodata` is 39 KB larger in 1.5.0, and 67 OSC addresses in 1.8.2
    are absent from 1.5.0.** **No vma or file offset measured on 1.8.2 carries over** —
    every address-level finding must be re-measured against `rootfs-1.5.0/usr/bin/las-frontend`.
    Only the launch-line/CLI transport wiring carries. **[READ]**

17. **"`matrix_expression_slots` holds 255 destination values; dst=255 sentinel."** Each
    integral element serialises as **exactly one byte** (`strb`, len 1; the float branch
    uses len 4), giving **256 values (0–255)**; `dst=0` is in live use, so the count is
    **256, not 255**. Observed destination ids reach **141** (a "no destination" sentinel,
    paired with `dst=""`/`"/dummy"`); the highest **real** destination observed is **126**.
    Whether the XMOS reads the byte as unsigned is **[UNKNOWN]**. **[READ/INFERRED]**

18. **"The blob encodes 1 byte for anything integral."** The updater tests exactly **two**
    `juce::var` predicates: `isInt()`→1 byte, `isDouble()`→4 bytes, else **nothing**.
    `isInt64()` and `isBool()` are **never consulted**, so an int64 or a boolean appends
    **zero bytes** and silently desynchronises the blob — worse than the 3-byte shift from
    writing `1` instead of `1.0`. A writer must keep `_a` fields as JSON **reals** and id
    fields as **int32-range** integers. (740 factory slots confirm positional typing with
    zero violations.) **[READ]**

19. **"The LASDatabase schema is twelve CREATE TABLE statements."** It is **fourteen**:
    eleven `CREATE TABLE` + **three `CREATE INDEX`**. They run **not** in `.rodata` address
    order — the creator issues them top-to-bottom from its literal pool as global, presets,
    the three indexes, tags, preset_tags, effects_presets, …, set_descriptions. The DDL
    diffs **empty** against the owner's stored `sqlite_master` (11 tables, 12 indexes of
    which 3 have non-null sql). **[READ]**

20. **"`/p/version` discriminates preset schema; the added/dropped field list is the
    1.5.0→1.8.2 migration."** `/p/version` is **not** a reliable discriminator — both
    firmwares stamp 14, yet 1.8.2 has 76 payloads at v14 of which 75 carry `sus/*` and no
    `voice_rule` and one is the reverse. The added/dropped list was **misattributed**
    (baseline wrong: `MOOG ONE.db` id=1 predates the 1.5.0 install by ~16 months).
    Correctly split: **genuinely new in 1.8.2** — `o*/hardsync`, `e*/{async,dsync,rsync}`,
    `fa/mode`, `l*/fsync`; **already in 1.5.0** — `cv_output/N/voice_rule`,
    `modmatrix/vars/cvout1-4`; **already dropped by 1.5.0** — `sus/mode`, `sus/src`. The
    owner's own 1.5.0 instrument demonstrably writes `voice_rule` (snapshots 30–33), so
    `CORRECTIONS-2026-09-08.md §9`'s resolution is itself wrong. **[READ]**

21. **"hardsync/async/rsync occur once each; 0 in 1.5.0."** Whole-file counts are 1.5.0/1.8.2
    = hardsync 0/10, async 1/11, rsync 0/10. The independent datum is one **node-name-table
    entry** present in 1.8.2 and absent in 1.5.0 (the rest are INIT-payload repeats; the
    lone 1.5.0 `async` is the English word). `/sus/mode` and `/sus/src` go 1740→1737, the 3
    being the INIT payload's three timbres. **[READ]**

22. **"`voice_rule` is absent from 1.5.0 (§9 open question)."** No. v1.5.0 ships
    `voice_rule` as a **global CV-output setting** (`/m/settings/midi_cv/cv_output/N/voice_rule "o"`
    in the owner's own DB, alongside `last_ui_version "2.0.8"` = the 1.5.0 tag), and
    `VOICE RULE` is a live 1.5.0 menu label. The real difference is **scope**: 1.8.2 also
    mirrors it into the per-preset block. §9's "hole in the dump" branch is correct
    (`p-namespace-keys.txt` walks only `/p`; the field lives under `/m/settings`). The 25
    presets are a **bulk import** (25 rows in 3.14 s); which firmware wrote them is
    **[UNKNOWN]**. **[READ]**

23. **"Stored preset rows are never rewritten; 368 v6 rows are old-firmware leftovers."**
    The version counts are exact (368 v6, 1 at 8, 29 at 14). But (a) the migration ladder
    does not write its result back to the row — `[INFERRED]`, not `[READ]`; (b) two DDL
    migrations **do** rewrite stored rows; (c) the 368 v6 rows are the **factory seed**
    (one 69-second burst at the unset-RTC date), not leftovers — the firmware that stamps
    14 on save also seeds v6 rows on first boot. **[READ/INFERRED]**

24. **"580 `.m1p` are JUCE BinaryData resources (20 resources)."** Exactly **one** (INIT)
    is a BinaryData resource; the other 579 are entries in a plain `const char*` table.
    The BinaryData resource list has **25 entries, not 20**, of which exactly one is a
    `.m1p`. **[READ]**

25. **"`seq_expression_slots` is a new, populated slot array; modmatrix has 10 VAR
    registers mapping to the engine's 16 v-registers."** `seq_expression_slots` exists but
    is **empty in every captured preset** (92× `[]`, 4× `null`) and was already recorded in
    `capability-survey.md`. `modmatrix/vars` persists **14** leaves (var0–9 **plus**
    cvout1–4), which map 1:1 onto the frontend's `VAR 1`..`VAR 10` + `CV OUT 1`..`4` table —
    ten VARs is the complete designed count, and no var10–15 exists. The engine register
    count is **[UNKNOWN]** from local files (`vx_ee.scm` contradicts itself: `v (array 16)`
    vs prose `v0..v63`, and says the v-registers are **not** saved in presets).

26. **"Global settings are scattered rows."** They are **one row** (`global`, key
    `'settings'`), 127,710 bytes over **658 lines**: 512 tuning-table lines (128 nodes × 4)
    + 101 midi_cv + 32 global + 8 root + 4 tunings + 1 clk. The only two SQL statements
    touching it are a `REPLACE` and a `SELECT`. **[READ]**

27. **"A user space is a folder."** A user space is selected by a **filename** —
    `ActiveUserSpace` property + `.db`, falling back to `MOOG ONE.db`. Each `.db` is an
    independent database; the two captured `global` rows differ in **exactly 8 lines**.
    Whether switching user space on a running instrument re-reads and applies tuning/MIDI/CV
    state is **[UNKNOWN]** (no code path from the switch to a DB reopen was traced; five
    `load_from_preset` flags complicate it). `SINGULARITY…db` may be an import container,
    not a live user space. **[READ / UNKNOWN]**

28. **"The DDL migrations are clean and version-keyed."** Two app-level migrations exist,
    neither keyed off a version number, keyed off **opposite** query outcomes. The
    timestamp-repair migration is keyed off a **failed** prepare and **cannot finish** — its
    refill batch targets `effect_presets` (singular), a table the rename already removed and
    which no CREATE recreates, so `sqlite3_exec` aborts, leaving `effects_presets`/
    `snapshots`/`sets` empty and six `old_*` tables behind. The `effect_presets→effects_presets`
    migration is a copy-and-drop keyed off a **successful** prepare. `PRAGMA foreign_keys=ON`
    **is** executed (per-connection). **[READ]**

29. **"`las-frontend`'s databases are all under `--data-path`; affinity-mask=1 is cpu1."**
    The **user** DBs are under `/var/las-frontend`; the **calibration** DB is separate at
    `/var/cal/vxcal.db` under its own `--cal-data-path` (never passed). `/var` is
    `mmcblk2p6`; `/media/thumbdrive` is a **symlink**, not a mount. `--affinity-mask=1` is a
    bitmask whose **bit 0 selects CPU 0** (proven in the binary). The `frontend` cgroup is
    created but nothing classifies a process into it. **[READ]**

30. **"v6→v14 is a clean schema migration."** Against a stored v6 and a stored v14 row the
    delta is **4 shapes removed, 32 added**, stable across all rows; the 8-field modmatrix
    entry table is **identical**. But 20 of the 32 additions are **user-facing parameters**
    outside `/modmatrix/`, the MIDI change is a third field on pre-existing per-port nodes
    (not a per-port split), and the RPN form is replaced by **three** structures. Scope
    caveat: this delta **bundles** migration-ladder change with serialiser drift and the two
    are not separated by this evidence. **[READ / INFERRED]**

### init / boot / update / security

31. **"`S99final:44` remounts root read-only."** No. Busybox 1.24.1 here is built with
    `FEATURE_MOUNT_FAKE` **disabled**, so `-f` is parsed and **ignored** — it does **not**
    skip `mount(2)`; `mount_it_now` calls `mount()` unconditionally. The live instrument is
    rw for a different reason: the captured boot took the `/media/thumbdrive/k` key branch
    and exited `S99final` early, so line 44 never ran. Identical in 1.5.0. What
    `mount -o remount,ro /` achieves on a keyless boot is **[UNKNOWN]**; needs a stock boot
    + `cat /proc/mounts`. **[READ]**

32. **"The XMOS is held in reset ~11 s every boot."** The DTB `/misc_output/xmosreset`
    (`XMOS_RESET_N`, gpio5 pin 5, `default-state "off"`) and `config-las-spi` as its only
    writer are `[READ]`; leds-gpio asserting reset at probe is `[INFERRED]` from standard
    semantics. But **nine** executables invoke `config-las-spi`, `S25xmosfw` is the first
    but not provably the only release, and the "~11 s" / "enumerates ~1.5 s later" figures
    are **unmeasured** — the single boot log bounds only the sum (≤11.9 s), not either term.

33. **"Password auth is the only way in / no authorized_keys."** The **boot** dropbear is
    `-B -R` (blank logins) gated on the USB `k` file — but that is **not the only start
    path**: `detect-held-buttons`→`lassvc` starts dropbear with **`-R` only**, where root's
    blank password is **rejected** and pubkey is the only path that could succeed. And key
    auth is **not demonstrably dead**: `/etc/ssh/authorized_keys` **exists** (745 B, one
    RSA key), and root's `$HOME` is `/var/local/root` — on `mmcblk2p6`, **not in the rootfs
    image** — so whether `/var/local/root/.ssh/authorized_keys` exists is **[UNKNOWN]**.
    "Password auth is the only path in" is an unproven inference. **[READ / UNKNOWN]**

34. **"`lasfwu`'s falcon-space guard discriminates on 60000."** It does not. `[ $x > 60000 ]`
    is a **single bracket** — `>` is an output redirection into a file literally named
    `60000` — so the test reduces to `[ $startofpartmap ]`, true for any single-word sgdisk
    value. The `dd if=/dev/zero of=/dev/mmcblk2 bs=1024 count=16384 seek=1024` (**16 MiB of
    zeros at 1 MiB offset of the raw eMMC**) therefore runs on essentially every non-dry-run
    update `[INFERRED]`. Whether that 16 MiB is harmless or destructive is **[UNKNOWN]** —
    the GPT of `/dev/mmcblk2` is on no captured disk. **This is the single most important
    thing to settle before any update; needs `sgdisk -p /dev/mmcblk2`.**

35. **"`lasfwu` writes only p2/p3; `/var` is never touched; U-Boot loads the kernel from
    the selected slot."** Slot selection is correct. But `/var` (p6) **is** written on every
    real update (`~/.gnupg`, `/var/local/gnupg`, ~800 MB staged to `/var/tmpfs` when p7 is
    not labelled FWU); `lasfwu` also does the raw `dd` to `/dev/mmcblk2` (#34). Each slot
    does carry its own kernel+DTB `[READ]`, but "U-Boot loads from the selected slot" is
    `[INFERRED]` — U-Boot, its env and `root=` are on no captured disk. What survives: the
    firmware **image** is written only to the inactive A/B slot, so p6 user data is not
    overwritten by the image copy.

36. **"`bootme`/`bootversion`/`sentinelu{1,2}` are one mechanism read by U-Boot."** They
    live on `mmcblk2p4` (vfat, `/var/lib/sys`); `lasfwu` is the only writer. They are **not
    one mechanism**: `bootme` is a slot number, the sentinels are `versionb` blobs,
    `bootversion` is a human string written **"for the frontend"** (per the script comment)
    — but `las-frontend` doesn't contain the string, so that comment is unconfirmed. Who
    consumes any of them is **[UNKNOWN]** (U-Boot is the leading hypothesis, not a read
    fact). The original grep evidence was invalid — `grep` here is ugrep, which no-matches
    binaries without `-a`, so 2,167 files including the 145 MB `las-frontend` were never
    searched.

37. **"A firmware update / every restart is a hard power-off; that is why the eMMC is
    dirty."** No whole-system reboot/halt/poweroff is invoked anywhere in the rootfs
    `[READ]` — an update ends with the user throwing the power switch. But a **service-level**
    software restart ships and runs continuously: `las-watchdog` (`S99final:24`) restarts
    `S42sc`/`S43gui` and kills X/dwm/scsynth on liveness failure. "Every restart is a hard
    power-off → dirty eMMC" is `[INFERRED]` from a single contaminated boot; rw-root and
    `lasfwu` leaving p4 mounted are alternative contributors the log can't separate.

38. **"The ~10-minute post-update restart is a four-step sequence."** Read out of 1.8.2, it
    is at least: `las-sc` compares VC version and `flashrom -i firmware`-writes a **1.75 MiB
    region** of the 2 MiB image (the 256 KiB excess fate **[UNKNOWN]**); sends `app_vx` to
    each voice card; writes/verifies tuning; runs `tune-the-untuned`; and interleaves **33**
    `pause-for`/`set-power-state` frames. `las-frontend` separately populates factory data
    and migrates. **Serialisation is not established** (the apparent message ordering is
    just `.rodata` literal order), and the time split is **[UNKNOWN]**.

### xmos

39. **"The controller and voice-card images share a loader byte-for-byte; the segment
    table's second field is in-RAM size."** They share only the **first 12 bytes**, then
    diverge — same loader *program*, separately linked. What is byte-identical is the loader
    **across releases**. The second segment field is **not a size** but a running
    end-offset; the ratio to the first field is **exactly 4** in every record (the first
    field counts 32-bit words). The decompression-at-boot conclusion stands; the field
    reading did not. **[READ]**

40. **"The version word is big-endian `MM mm pp FF`."** The **value** is `0x020102FF`, but
    the bytes on disk are `FF pp mm MM` and `las-sc` reads them with
    `bitstring->integer-little`. The value is `MM mm pp FF`; the **storage is
    little-endian**. Segment counts and region offsets in `xmos-firmware.md` are counted/
    version-specific and were likewise corrected. **[READ]**

### The meta-lesson

Every refutation is one of four failures: (a) a **name read as a behaviour** (`lassvc`
flashes; `/info/write` commits; MidiControlOutputUpdater builds MIDI); (b) a **string
inventory mistaken for a capability map** (12 vs 245 addresses; disjoint vs 155 shared);
(c) an **extraction artefact** (lost setuid bits; ugrep skipping binaries; a contaminated
runtime snapshot); (d) a **`[READ]` grade pasted onto an `[INFERRED]` conclusion**
(`mount -f`; the `60000` guard; "passwordless root"; `/p/version` as a schema key). None
required the instrument to catch. They required reading the bytes the claim skipped.

---

## What we now know that we did not this morning

The findings that survived, and that are new to the project. Graded as their reports grade
them.

- **`/p/pre-expr`, `/p/post-expr` and the 115 `_m` twins are a never-read constant in
  `las-sc`.** They decode into one quoted list assigned to `expression-nodes`, read exactly
  once — at its own definition. `las-sc` has no handler; an incoming `/p/pre-expr` falls off
  `part-dispatch` and is discarded — which is exactly the wire behaviour observed. 18 of the
  115 name symbols absent from `vx_ee.scm`: stale as well as unused. **[READ]**
- **An edited modulation-matrix row never goes to `las-sc`.** It is compiled to a flat
  binary blob and sent as one OSC message to the XMOS at `/g/<synth>/t/e/s` on port 7770.
  The frontend's own help says so ("Synth parameters are sent over xOSC directly to the
  Voice Controller"). That is why the 9300 capture saw nothing. **[READ]**
- **No MIDI byte from either port reaches Linux, for a stronger reason than the gadget
  argument:** there is no rawmidi/seq-midi/usbmidi kernel module and only a PCM-only sound
  card. The frontend *emits* MIDI (`/mo/din0`, `/mo/usb0`, one int32 per byte) but cannot
  *receive* raw MIDI. **[READ]** (Whether parsed MIDI returns over OSC/7772 is still
  **[UNKNOWN]** — see below.)
- **`eec` is the expression compiler** — text → Q24 words → OSC blob to `vc:7770`, carrying
  its own 47-entry instruction reference with five defects, and resolving what `rcl` means
  (register-direct load; the sequencer). No prior report mentioned it. **[READ]**
- **The audio path crosses cores.** The `sdma` interrupt (82.4M counts) is serviced on cpu0
  while scsynth's SCHED_FIFO-99 thread runs on cpu1 — an inter-core wakeup every audio
  period. CPU1 placement is done by `pthread_setaffinity_np(0x2)` inside scsynth's patched
  `SC_AlsaDriver`, **not** by `isolcpus`, the `dsp` cgroup (never populated), or
  `assign-pids` (its `taskset` lines are commented out). **[READ, live-confirmed in `VALIDATION.md`]**
- **A live bug: the RT throttle was never lifted.** `S02sys` wrote `999950` into a *file
  named* `/sched_rt_runtime_us` (missing path), so the sysctl stays at 95% for the life of
  the product. A one-line `/proc` write fixes it; nothing on disk changes. **[READ,
  live-confirmed]**
- **96 UGen plugins register 795 UGens; 734 are unreachable from the shipped client** — the
  complete STK set, JPverb/Greyhole, the Ambisonic Toolkit, the granular and chaotic
  families are all resident, linked, and unnameable in `sclang` as configured. **[READ]**
- **Four complete second-stacks ship dead:** Qt5 + QtWebKit + a real `jsc` JS engine
  (buildroot residue); DirectFB 1.7.7 (wired to nothing, ever); a full Wi-Fi userspace on a
  kernel with no wireless subsystem; a TLS-verifying HTTP client with a 179-root CA bundle
  that nothing calls. Each is now proven inert by linkage/call-graph, not just by grep.
  **[READ / INFERRED]**
- **`lassvc` is the factory service plane**, reachable from HOME+SETTINGS at power-on or any
  root shell — `/cal /info /fw /hw /mix /testosc`, identity writes, and a "phone home
  (alpha)" reverse tunnel to `remote.moogmusic.com`. The remote exposure it opens is a
  **password-gated `las` account**, not passwordless root (see refutation #5). **[READ]**
- **The `coefsEnvir` archive decodes fully** — textbook RBJ/DAFX biquads on a linear grid,
  no proprietary design — and is unreachable at runtime. **[READ]**
- **`fusermount` is setuid root** (read from the ext4 image, not the extraction) — and with
  it, the discovery that the extracted trees **lost every setuid bit, all uid/gid, and the
  device nodes**. Any doc asserting ownership or privilege bits from the extracted trees must
  be re-sourced from `pkg/rootfs.ext4`. **[READ]**
- **The update writes outside p2/p3:** `/var` on every update, and a raw 16 MiB `dd` to
  `/dev/mmcblk2` whose safety is unestablished (refutation #34). The firmware *image* still
  lands only in the inactive slot, so presets/tuning on p6 survive. **[READ / UNKNOWN]**

---

## Corrections to existing documentation

Contradictions these reports found in `docs/*.md` and `docs/arch/*.md`. **Reported, not
fixed** — per the project rule, no existing doc was edited. Ordered roughly by consequence.

**Security / update:**
- `docs/arch/control-plane.md:517-535` (finding **D10**): "firmware flashing has no
  signature check." **Wrong** — `lasfwu:686` verifies `IMAGE-SIG` unconditionally before the
  `dd`. `CORRECTIONS-2026-09-08.md:113` already has the right position; `control-plane.md`
  was never updated to match. (`diff-upgrade.md`)
- `docs/MOOG-ONE-INTERNALS.md:1812-1820`: "Wi-Fi is supported but not fitted … a dongle is
  all that stands between." **Wrong** — the kernel has **no wireless subsystem**; firmware
  blobs without a driver are unreachable; a retrofit needs a kernel rebuild. Should be
  retracted. (`gap-wireless`)
- `docs/MOOG-ONE-INTERNALS.md:1780-1799`: "netjack … a path to streaming audio over
  ethernet" and "a complete debug toolchain." **Overstated** — `scsynth` has no JACK symbols
  and no `jackd` runs; every Moog binary is stripped and gdb has no Python. (`gap-observability`)
- `docs/firmware/VALIDATION.md`, "Not checkable this way": `dumpe2fs`/`tune2fs` "not present"
  — they **are** present (both versions); the free-inode question is answerable. And busybox
  `netstat -p` isn't needed — `netcap` does per-process sockets. (`gap-observability`)

**Expression / namespace / control plane:**
- `docs/arch/xmos-deep.md:613,926,976`: "`las-sc` prepends a `pre-expr` and appends a
  `post-expr`." **Retract** — no code in `las-sc` reads the table or sends either address.
  (`las-sc-namespace.md`)
- `docs/arch/extension-points.md:211,421`: `/p/pre-expr`/`/p/post-expr` as "live engine-side
  endpoints." The `las-sc` half is now known — it accepts nothing; "live" is unsupported by
  anything on disk. (`las-sc-namespace.md`)
- `docs/arch/control-plane.md:103`: lists `/p/version` among `las-sc`'s "singles." **`/p/version`
  is not in `las-sc` at all.** (`las-sc-namespace.md`)
- `docs/arch/control-plane.md:187`: attributes UDP **9600** to "`las-sc` (2nd)." It is
  **`las-dwm`** (agreeing with `MOOG-ONE-INTERNALS.md:76`); `doc-audit.md:672` already flags
  this. (`network.md`)
- `docs/arch/expression-language.md:10.2`: `rcl` "unresolved," favouring an indexing reading.
  **Resolved** as a register-direct load; indexing ruled out. (`gap-eec`)

**Audio / CPU policy / LADSPA:**
- `docs/arch/effects-engine.md:119-141`: "treat block size as 256." **Stale** — it is 128
  (`init_sc_1.scd:9-10`, and live `hw_params`). (`las-fx.md`, `kernel.md`)
- `docs/arch/extension-points.md:1261-1264` and the surrounding text: CPU-affinity policy
  attributed to `assign-pids`. `assign-pids` has no `cgclassify`/`cgexec` and both `taskset`
  loops are commented out; the cgroups are defined but never populated; placement is
  scsynth's own `pthread_setaffinity_np`. (`las-fx.md`, `kernel.md`)
- `docs/arch/effects-engine.md:113-118` and `audio-graph.md:431-433`: LADSPA path "not
  resolvable / open question." **Closed** — compiled-in default `/usr/lib/ladspa`,
  `LADSPA_PATH` unset. And `effects-engine.md:276-278`'s "`eventide_spring.so` is present"
  overstates it: that directory is not on scsynth's search path. (`las-fx.md`)
- `docs/arch/extension-points.md:1227,1231`: "wavetable/coefficient store" (there are **no
  wavetables**) and a `moog_splash.fb` size/geometry that describes `moog_logo.fb`.
  (`gap-las-fx-coef`, `gap-x11`)

**Calibration / JS:**
- `docs/arch/capability-survey.md §B5`, `extension-points.md §10`: `Panel.calSave`/`calSet*`
  as **voice-card calibration writes** ("the one category of damage no backup covers"). They
  emit `/cal` to **panel / LHC / keybed**, which is user-recoverable; no `cal*` method targets
  a voice card. (`js-sandbox.md`)
- `docs/DANGER.md`: `vxcal.db` "holds this unit's per-card calibration" (it is **empty** on
  this instrument — the data that matters is in `tuning.vxtune`); "`/cal/*` 62 leaves" (it is
  **223** across ten binaries); `/load_cal`/`/load_tuning` as **writers** (they are queried
  with zero args and their replies string-matched); "no debounce on the watchdog" (true for
  `/ping` and `pidof`, but the voice-count path retries **30×**). (`calibration.md`,
  `small-binaries.md`)
- `docs/arch/cal-dispatch.md §6.3`: the `/cal:save`/`/cal/save` spellings graded `[INFERRED]`
  — all five are complete literals, promotable to `[READ]`. (`calibration.md`)

**XMOS / hardware / kernel:**
- `docs/arch/xmos-deep.md §0`: version word "big-endian." Value is `MM mm pp FF` but
  **storage is little-endian** (`FF pp mm MM`). `xmos-firmware.md §1`'s "shared loader
  byte-for-byte" and segment-size reading are also wrong (shared only 12 bytes; the field is
  an end-offset). (`xmos.md`)
- `docs/arch/hardware-external.md:450`: "Root is **p2**." Per-machine — this unit boots
  `root=/dev/mmcblk2p3`; `root=` is chosen per boot from `/var/lib/sys/bootme`. (`init-boot.md`,
  `gap-uboot`)
- `docs/firmware/kernel.md:944-947`: DTB `fb@1`/`fb@3` `disp_dev` "unknown" — they are
  `hdmi` and `ldb`. (`gap-x11`)
- `docs/arch/performance.md §5.3`: uses 1.5.0 XMOS versions (`2.1.2`/`33620735`/`2.1.0`); for
  1.8.2 these are `2.2.2`/`33686271`/`2.2.1`. Not an error — predates the 1.8.2 read — but now
  stale. (`init-boot.md`)

**`CORRECTIONS-2026-09-08.md` itself (the prior correction doc) needs two fixes:**
- §3: "`vx_ee.scm` … not from 1.8.2." It **is** in 1.8.2 at `usr/share/vx_ee.scm`,
  byte-identical. (`diff-files.md`)
- §9: the `voice_rule` open question is resolved the opposite way to its own framing — the
  owner's 1.5.0 instrument **does** write `voice_rule` (under `/m/settings`), so the "25
  presets need an intermediate firmware" reasoning is void; it is a hole in the `/p`-only
  dump. (`las-frontend-data.md`, `diff-osc.md`, refutations #20/#22)

**And a correction these reports made to one another:** `las-sc-namespace.md`'s headline
that "the flat `/p` namespace lives in `las-frontend`" was itself refuted — the flat `/p`
strings are in **`las-sc`** (refutation #11). Where `las-sc-namespace.md §0` and §11 say
otherwise, prefer the refutation.

---

## Still unknown

Load-bearing questions no file on disk can close. Ordered by how much they matter.

1. **Does the `lasfwu` 16 MiB `dd` to `/dev/mmcblk2` (offset 1 MiB) overlap partition 1?**
   Determines whether every update silently corrupts the partition map or writes dead space.
   The GPT is on no captured disk. **Settle before any update.** (Needs `sgdisk -p`.)
2. **Does any DIN/USB MIDI note reach Linux — and if so on UDP/7772?** The frontend can't
   receive raw MIDI; whether parsed MIDI returns over OSC is inferred, weakly, and never
   observed. Governs the entire "can we touch MIDI on the Linux side" question. (tcpdump on
   `lo` udp/7772 while playing a note.)
3. **Does the voice controller implement `/p/pre-expr` / `/p/post-expr`?** `las-sc` forwards
   nothing; the XMOS image is encoded and carries no readable address strings. Blocked on disk.
4. **Is `las-sc`'s only bound socket `localhost:9300`?** Three `string->bound-socket` sites;
   the only netstat lacked `-p`. Bears on what is reachable and from where.
5. **Does switching user space re-apply tuning / MIDI / CV state on a running instrument?**
   No code path from the switch to a DB reopen was traced; five `load_from_preset` flags make
   it non-trivial.
6. **Which firmware wrote the 25 `voice_rule` presets, and does `voice_rule` live on the `/p`
   OSC namespace at all?** The schema is newer than 1.5.0's serialiser but the timestamps are
   bulk-import insert times; the capture set has no evidence dating the writer.
7. **The engine's true register count** (`v`/`m`/`c` arrays). `vx_ee.scm` contradicts itself;
   needs the VX image's bounds checks disassembled.
8. **`/var/local/root/.ssh/authorized_keys` — does it exist?** Decides whether the service
   dropbear's pubkey path is live. The directory is on p6, not in the rootfs image.
9. **The i.MX6 HAB/secure-boot fuse state** (`/sys/fsl_otp/HW_OCOTP_CFG5` bit 1, SRK hashes).
   Reads are safe; **writes to `/sys/fsl_otp/` are the most destructive command surface in
   this project.**
10. **U-Boot, its environment, `root=`, and how `bootme`/sentinels are consumed.** Not in any
    capture. The largest single hole in the A/B story. A public U-Boot boot log from the
    2020–21 teardowns may settle it without touching the instrument.
11. **`mmcblk2p1` (factory) and `mmcblk2p5`** — p5 is referenced nowhere.
12. **What `flashrom` does with the 256 KiB of image past the 1.75 MiB `las_layout` region**,
    and the VM opcode numbering / instruction-word layout (in the encoded XMOS image).
13. **The ESAI TDM geometry** — slot count, word width, and which muxed pad carries which
    signal — needs the i.MX6DL reference manual or a live register read.
14. **Whether `scsynth` registers the plain `Index` UGen**, on which two reverbs' residency
    depends — answerable read-only on a copy.

---

## Validation plan

Consolidated, deduplicated, **READ-ONLY** commands for a human to run on the instrument,
ordered by how much each settles. Per this project's standing rules and the auto-memory
note: **no Moog binary or script is ever run here** (several ignore their args and perform
calibration/reset), **nothing writes**, and `devmem`/`mmc`/`sgdisk` are used only in their
read forms. Everything below is `cat`/`ls`/`hexdump`/`grep` on `/proc`, `/sys`, `/etc`,
`/var`, plus passive `tcpdump` and a small number of clearly-marked active probes. The
agent that wrote this index did not run any of them.

### Tier 1 — settle the destructive ambiguity and the architecture boundaries

```sh
# 1. Does the lasfwu 16 MiB dd land inside partition 1?  (Still-unknown #1 — do this first)
sgdisk -p /dev/mmcblk2                    # full partition map with start sectors
sgdisk -i=1 /dev/mmcblk2                  # partition 1's first sector; the number lasfwu:821 wanted
cat /proc/partitions                      # cross-check sizes against VALIDATION.md

# 2. Block size, channel counts, 24-bit — the canonical settle (refutations on 256)
cat /proc/asound/card0/pcm0p/sub0/hw_params   # expect channels 8, rate 48000, period_size 128
cat /proc/asound/card0/pcm0c/sub0/hw_params   # expect channels 9

# 3. The RT-throttle bug, read directly
ls -l /sched_rt_runtime_us ; cat /sched_rt_runtime_us          # expect a 7-byte file "999950"
cat /proc/sys/kernel/sched_rt_runtime_us                       # expect 950000 (the sysctl, untouched)

# 4. cpu1 is the audio core; the rest on cpu0 (mechanism, not isolcpus)
for t in /proc/$(pidof scsynth)/task/*; do grep -H Cpus_allowed_list $t/status; done
chrt -p $(pidof scsynth)
cat /sys/devices/system/cpu/isolated ; cat /sys/devices/system/cpu/nohz_full   # isolated=1, nohz_full empty
```

### Tier 2 — settle the refuted security and MIDI claims

```sh
# 5. dropbear's actual flags, and whether root login is exposed  (refutations #5, #33)
pidof dropbear && cat /proc/$(pidof dropbear)/cmdline | tr '\0' ' '; echo   # -R alone vs -B -R
getent shadow root las                                                      # root:: ; las DES hash
ls -l /root/.ssh/authorized_keys /var/local/root/.ssh/authorized_keys 2>/dev/null
ls -l /media/thumbdrive/k 2>/dev/null ; hexdump -C /media/thumbdrive/k 2>/dev/null | head

# 6. Does any MIDI reach Linux, and on 7772?  (Still-unknown #2 — passive capture)
#    Play a note into the DIN/USB port WHILE this runs; tcpdump only reads the wire.
tcpdump -i lo -n -s0 -c 200 'udp port 7772'

# 7. las-sc's bound sockets  (refutation #9, #12)
netstat -lnup 2>/dev/null | grep -E '9300|7775|9500|7770'
cat /proc/net/udp | head -40         # local 0100007F:2454 == 127.0.0.1:9300
```

### Tier 3 — settle the preset-schema and settings refutations (all on copies of the DBs)

```sh
# 8. Does las-sc forward /p/pre-expr?  (Still-unknown #3 — ACTIVE PROBE: injects one OSC packet
#    to las-sc's own loopback port. Not a pure read; the owner decides. Capture the VC link too.)
tcpdump -i usbint -n -s0 -w /tmp/preexpr.pcap 'udp port 7770' &
oscsend 127.0.0.1 9300 /p/pre-expr s "1 0 * pan sto"   # or the project's existing sender
sleep 2; kill %1 ; tcpdump -r /tmp/preexpr.pcap -X | head   # expect nothing forwarded

# 9. voice_rule / hardsync / version schema on the live unit  (refutations #20, #22)
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT substr(data,1,16), count(*) FROM presets GROUP BY 1;"   # version-stamp distribution
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT data FROM global WHERE key='settings';" | grep -E 'voice_rule|cv_output'  # /m/settings scope

# 10. The global settings row decomposition  (refutation #26)
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" "SELECT key, length(data) FROM global;"
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" ".schema"       # 11 tables + 3 idx (refutation #19)
cat /var/las-frontend/las-frontend.properties                     # ActiveUserSpace (refutation #27)
```

### Tier 4 — fuses, partitions, and the dead stacks (read-only confirmations)

```sh
# 11. i.MX6 HAB / secure-boot fuses  (Still-unknown #9 — READS ONLY; never write /sys/fsl_otp)
cat /sys/fsl_otp/HW_OCOTP_CFG5          # SEC_CONFIG bit1 = HAB closed
cat /sys/fsl_otp/HW_OCOTP_SRK0          # all-zero across SRK0..7 => no SRK burned

# 12. A/B/C slot state, and p4's bootme/sentinels  (refutations #35, #36)
cat /proc/cmdline                        # which slot is root= this boot
hexdump -C /var/lib/sys/sentinelu1 ; hexdump -C /var/lib/sys/sentinelu2
cat /var/lib/sys/bootme ; cat /var/lib/sys/bootversion
df -h /mnt/fwu                           # staging margin (VALIDATION.md: 12.2 MiB)

# 13. The dead stacks are really inert  (gap reports)
grep -l libQt5 /proc/*/maps 2>/dev/null ; grep -l jsc /proc/*/maps 2>/dev/null   # expect nothing
ls /sys/class/net                                          # lo usbint ethext — no wlan*
ls -d /sys/class/ieee80211 /sys/class/rfkill 2>&1          # expect: No such file
stat -c '%A %U' /usr/bin/fusermount                        # confirm setuid on the LIVE fs (refutation, gap-fuse)
cat /proc/mounts | grep ' / '                              # is root actually rw? (refutation #31)
```

### Tier 5 — version/identity provenance (cheap, corroborates the diffs)

```sh
cat /etc/version ; cat /etc/git-tags
cat /usr/share/xmosfw/VERSIOND           # 1.5.0: 33620735   1.8.2: 33686271
md5sum /usr/bin/las-sc /usr/bin/lassvc /usr/bin/las-frontend /usr/bin/las-watchdog
```

Items the reports wanted that are **not checkable this way**: free inodes (no `df -i`,
`dumpe2fs`/`tune2fs` present but run against an unmounted image only) and anything requiring
a stock keyless boot (the real `mount -o remount,ro /` outcome, refutation #31). U-Boot's
environment and `root=` source (#10) are not on the instrument's readable filesystem at all —
the cheapest lead is a public teardown boot log, not a device read.
