# 1.5.0 → 1.8.2: what changes, what is gained, what is risked, what cannot be undone

Static analysis only. The instrument was not contacted at any point during this
work. Every claim below is graded:

- **[READ]** — read directly out of a file on local disk; the file and the
  line/offset are given.
- **[INFERRED]** — reasoning from stated evidence; the evidence is named.
- **[UNKNOWN]** — not established.

Primary sources: `captures/firmware-1.8.2/rootfs-1.8.2/` (the decrypted 1.8.2
root filesystem), `captures/rootfs-1.5.0/` (the owner's own instrument),
`captures/firmware-1.8.2/pkg/` (the unpacked update package),
`captures/sysmap/01-hardware.txt` (a `df`/`mount` capture from the instrument,
2026-09-02), `captures/dmesg-before-reboot.txt`.

---

## Recommendation

**Install it.** The reasoning, in order of weight:

1. **The rollback slot the update destroys is v1.4.0, not v1.5.0.** The
   instrument boots from `mmcblk2p3`; the updater therefore writes `mmcblk2p2`,
   which currently holds v1.4.0. After the update the pair is
   `p2 = 1.8.2 (live)` / `p3 = 1.5.0 (fallback)`. The owner keeps a one-keystroke
   path back to exactly the firmware they are running today. **[READ]** +
   **[INFERRED]** — see §2.
2. **Nothing this project depends on changes.** The `las-sc` OSC address set is
   byte-for-byte identical between the two releases — 816 `/`-prefixed strings,
   zero added, zero removed. `vx_ee.scm` is byte-identical. Every file under
   `/usr/share/las-fx/` — `init_sc_1.scd`, `init_sc_2.scd`, `synthdefs.scd`,
   `efx_server.scd` — is byte-identical, so `-z 128` and the whole SuperCollider
   graph are unchanged. **[READ]** — see §4.
3. **The fixes are squarely in this project's path.** 1.8.0 fixed crashes on
   large MIDI input and crashes/panel lag from OSC hard sync via CC; 1.8.1 and
   1.8.2 fix regressions 1.8.0 introduced. **[READ]** — see §5.
4. **The space margin is real but adequate, and running out of it is safe.**
   Peak staging is 788.32 MiB into a partition with 800.50 MiB free — 12.18 MiB
   of headroom, and the staging partition is wiped on every boot so that figure
   is the steady state. There is no free-space precheck, but a space failure
   aborts *before* anything is written to the target partition. **[READ]** —
   see §3.

**Two conditions on that recommendation:**

- **Do it on mains power you trust, and do not interrupt it.** The one genuinely
  unrecoverable step is the XMOS voice-controller flash, which happens at the
  *first boot after* the update, not during it (§7).
- **Copy `captures/backup/` off that single drive first.** The calibration
  tarball and the p3 image are the only things on the instrument that no
  reflash can regenerate, and they exist in one place. This is not a risk the
  update introduces — it is a risk the update makes worth closing.

---

## 1. The updater is the same script in both releases

`/usr/bin/lasfwu` is **byte-identical** across v1.5.0, v1.8.2, and the copy
harvested from the live instrument: all three MD5 to
`29c03fc8651de8b3774025bef9448709`. **[READ]** — `md5` over
`captures/rootfs-1.5.0/usr/bin/lasfwu`,
`captures/firmware-1.8.2/rootfs-1.8.2/usr/bin/lasfwu`,
`captures/arch-harvest/lasfwu`.

This matters more than it looks. **The script that runs an update is the one in
the *currently booted* firmware**, so everything analysed below is what will
actually execute on the owner's 1.5.0 instrument. It is a 33,940-byte Bourne-Again
shell script, header `# Created by Chris Howe on 6/26/17` (`lasfwu:5`). **[READ]**

### What `lasfwu load` does, in order

| # | step | line | notes |
|---|---|---|---|
| 1 | pick staging dir: `/mnt/fwu` if GPT partition 7 is named `FWU`, else `/var` | `456-460` | |
| 2 | read current root from `/proc/cmdline`, pick the *other* slot | `465-541` | |
| 3 | `echo 0 > /var/lib/sys/sentinelu$part`; write `bootversion` | `564-568` | **before** any write |
| 4 | `rm -rf $MOUNTDIR/tmpfs; mkdir $MOUNTDIR/tmpfs` | `585-586` | clears prior attempt |
| 5 | `tar -xf` the package into `tmpfs/` | `589` | extracts `rootfs` (149.35 MiB) |
| 6 | extract the private key from `/etc/bob.bmp`, `gpg --import` | `637-638` | |
| 7 | `gpg --passphrase bob --decrypt` → `tmpfs/rootfs.ext4` | `642` | **alongside** the encrypted file |
| 8 | `gpg --verify IMAGE-SIG` against the decrypted image | `686` | unconditional |
| 9 | delete the secret key | `729` | |
| 10 | `dd if=tmpfs/rootfs.ext4 of=/dev/mmcblk2p$replacepart` | `742` | first write to the target |
| 11 | `rm -rf $MOUNTDIR/tmpfs` | `792` | |
| 12 | mount target, `cat etc/versionb > sentinelu$part`, `echo $replacepart > /var/lib/sys/bootme` | `808-809` | commit point |
| 13 | zero 16 MiB of raw eMMC at offset 1 MiB | `825` | see §6 |

All line numbers **[READ]** from `captures/firmware-1.8.2/rootfs-1.8.2/usr/bin/lasfwu`.

**The signature gate is unconditional and precedes the `dd`.** Step 8's exit code
is checked at `lasfwu:720-726` and returns 1 on failure. `--accept-unsigned` is
described in the embedded man text at `:1009` but has an **empty case body** —
the parser at `:1136-1150` handles `--version`, `--temp`, `--api`, `--verbose`,
`-v` and `-n`, and never sets a variable for it. **[READ]**

Likewise `--temp` is parsed at `:1140` with an empty body, and no `tmpdir`
variable exists anywhere in the file. **The staging location cannot be
redirected**; it is always `$MOUNTDIR/tmpfs`. **[READ]** — `grep -n
"tmpdir\|TMPDIR\|tempdir" lasfwu` returns nothing.

---

## 2. The slot arithmetic — and why the fallback is better than it looks

`fstab` and the live mount table agree on the layout:

```
/dev/mmcblk2p1   factory / recovery root      (not mounted at runtime)
/dev/mmcblk2p2   U1  — rootfs slot A          /mnt/u1, ro, noauto
/dev/mmcblk2p3   U2  — rootfs slot B          /mnt/u2, ro, noauto
/dev/mmcblk2p4   /var/lib/sys                 vfat — boot sentinels
/dev/mmcblk2p6   /var                         ext4, 3.8 G
/dev/mmcblk2p7   /mnt/fwu                     ext4, 861.9 M — update staging
```
**[READ]** — `rootfs-1.8.2/etc/fstab`; `sysmap/01-hardware.txt:50-52` and
`:64-66`; `dmesg-before-reboot.txt:245` (`mmcblk2: p1 p2 p3 p4 p5 p6 p7`).

The selection is a plain case statement on the booted partition — **not** a
"newest wins" rule:

```
2)  detail="Currently booted from U1, replacing U2 partition";  replacepart=3
3)  detail="Currently booted from U2, replacing U1 partition";  replacepart=2
```
**[READ]** — `lasfwu:531-538`.

The owner's instrument boots `root=/dev/mmcblk2p3`. **[READ]** —
`dmesg-before-reboot.txt:21` and `arch-harvest/runtime-state.txt:2` (kernel
cmdline is one of the fields the contamination caveat explicitly says
`runtime-state.txt` remains valid for).

So: **`currentpartition = 3` → `replacepart = 2` → the update overwrites
`mmcblk2p2`.** **[INFERRED]**, from the two [READ] facts above.

`docs/DANGER.md:268` records `mmcblk2p2` as holding **`las-v1.4.0`** (las-sc
dated Jun 15 2020, 636.7 M, 75% used), read from the instrument itself.

**Consequence: the update consumes the v1.4.0 slot, not the v1.5.0 slot.** After
the update the owner holds 1.8.2 live on p2 and 1.5.0 — the firmware they are
running today, with their tuning already matched to it — as the fallback on p3.
The thing being permanently given up is the ability to fall back to **1.4.0**.
**[INFERRED]**

`/var` (p6) and `/var/lib/sys` (p4) are separate partitions that the updater
never writes as block devices, so presets, the 101 MB preset DB, `/var/cal/*`
and `/var/tuning.vxtune` survive. **[READ]** — `fstab`; the only `dd of=` targets
in `lasfwu` are `/dev/mmcblk2p$replacepart` (`:742`) and `/dev/mmcblk2` (`:825`).

---

## 3. The 788.31 / 800.5 / 12.19 MiB claim — verified, with the exact numbers

`docs/CORRECTIONS-2026-09-08.md:148` records this as **[AGENT]**, unchecked. It
is essentially right. The precise figures:

**Where 788 MiB comes from.** Steps 5 and 7 above leave *both* the encrypted and
the decrypted image in `$MOUNTDIR/tmpfs` at the same time — `gpg` writes
`--output "$MOUNTDIR/tmpfs/$imagename.ext4"` while `$MOUNTDIR/tmpfs/$imagename`
still exists, and nothing deletes the encrypted file until `:792`, long after.
**[READ]** — `lasfwu:589`, `:642`, `:792`.

| component | bytes | MiB |
|---|---|---|
| `pkg/rootfs` (encrypted, = MANIFEST `packed_size`) | 156,599,799 | 149.35 |
| `pkg/rootfs.ext4` (decrypted, = MANIFEST `unpacked_size`) | 670,012,416 | 638.97 |
| `MANIFEST` + `MOOGFW` + `MANIFEST-SIG` + `IMAGE-SIG` | 418 | — |
| **peak, raw** | **826,612,633** | **788.32** |
| peak, rounded to 4 KiB ext4 blocks | 826,638,336 | 788.34 |

**[READ]** — `stat` on `captures/firmware-1.8.2/pkg/*`; the two sizes match the
MANIFEST's own `packed_size` and `unpacked_size` fields exactly. The ext4
superblock of `rootfs.ext4` reads 654,309 blocks × 1024 B = 670,012,416 B, of
which 453.82 MiB is used. **[READ]**

**Free space.** `/dev/mmcblk2p7  861.9M size, 888.0K used, 800.5M available, 0%,
/mnt/fwu`. **[READ]** — `captures/sysmap/01-hardware.txt:51`.

**Margin: 800.50 − 788.32 = 12.18 MiB** (12.16 MiB after block rounding). The
prior figure of 12.19 MiB is correct to within rounding. **[READ]/[INFERRED]**

### Three things that make that margin less alarming than it sounds

1. **The staging partition is wiped on every boot.** `S14fs` runs `rm -rf
   /mnt/fwu/*`, and the script is byte-identical in 1.5.0 and 1.8.2. **[READ]** —
   `rootfs-1.8.2/etc/init.d/S14fs`, comment `#destroy anything in fwu folder`;
   `diff` against the 1.5.0 copy is empty. So 800.5 MiB free is the state at
   every boot, not a lucky sample. (The 888 K in use is `lost+found`.)
2. **`lasfwu` also `rm -rf`s `tmpfs/` before extracting** (`:585`), so a previous
   failed attempt does not accumulate. **[READ]**
3. **Running out of space fails safe.** There is **no free-space check anywhere
   in the script** — the string `507` (documented at `:1110` as "No space left on
   device") appears exactly once, in the help text, and is never emitted.
   **[READ]** — `grep -n '507' lasfwu`. But a full filesystem makes `tar` (step
   5) or `gpg` (step 7) exit non-zero, both of which are checked and return 1
   (`:625-630`, `:678-684`) — **before** the `dd` at `:742`. The target partition
   is not touched. **[INFERRED]**, from the [READ] control flow.
4. If `/mnt/fwu` were somehow unavailable, `MOUNTDIR` falls back to `/var`
   (`lasfwu:459`), which has **3.3 G free**. **[READ]** —
   `sysmap/01-hardware.txt:50`.

### A documentation defect worth knowing about

`lasfwu`'s own man text says `--temp` "should be on a filesystem with at least
**200MiB** free" (`:1003`). The real requirement is **788 MiB**, and `--temp`
does not work anyway (§1). The 200 MiB figure is from 2017, when the image was
much smaller. **[READ]**

---

## 4. What actually changes in the root filesystem

6,027 files exist in both trees. **5,127 are byte-identical.** 900 differ, and
**only one differs by more than 1 KB.**

| bucket | count |
|---|---|
| identical | 5,127 |
| differ, identical size (build stamps, gzip mtimes, fonts, locale, docs) | 619 |
| differ, size delta 1–1000 B (buildroot build-path/build-ID churn) | 280 |
| differ, size delta > 1000 B | **1** — `usr/bin/las-frontend`, −37,288 B |

**[READ]** — byte-for-byte `cmp` over every common path.

Files present in only one tree:

- **added in 1.8.2:** `usr/share/xmosfw/app_las_v2.2.2.bin`,
  `usr/share/xmosfw/app_vx_10M_v2.2.1.bin`
- **removed in 1.8.2:** `usr/share/xmosfw/app_las_v2.1.2.bin`,
  `usr/share/xmosfw/app_vx_10M_v2.1.0.bin`

**[READ]**. (The other "only in 1.5.0" entries — `etc/init.d/S99moogd`,
`usr/lib/ladspa/eventide_spring.so`, `sched_rt_runtime_us`, `etc/random-seed`,
`etc/dhcpcd.duid`, `var/run/utmp` — are this project's own contamination and
runtime state, per `captures/arch-harvest/CAVEAT-runtime-state.md`, not stock
1.5.0. `mig150.asm` and `.omc/` inside `rootfs-1.8.2/` are today's scratch files,
not part of the image.)

### `/etc` differs in exactly four files

`git-tags`, `init.d/S42sc`, `version`, `versionb`. **[READ]** — `diff -rq`.

```
etc/version   las-v1.5.0            →  las-v1.8.2
etc/versionb  ff 00 05 01 …         →  ff 02 08 01 …
etc/git-tags  LAS_FRONTEND 2.0.8    →  2.1.4
              LAS_VX  lasvx-v2.1.0  →  lasvx-v2.2.1
              LAS_FW  lasvc-v2.1.2  →  lasvc-v2.2.2
```
**[READ]** — `cat`/`xxd`/`diff` on those paths.

`S42sc` changes only the three XMOS arguments to `las-sc`:

```
-  --vxfw=…/app_vx_10M_v2.1.0.bin  --vcfw=…/app_las_v2.1.2.bin  --vcfv=33620735
+  --vxfw=…/app_vx_10M_v2.2.1.bin  --vcfw=…/app_las_v2.2.2.bin  --vcfv=33686271
```
**[READ]** — `diff etc/init.d/S42sc`. `33620735 = 0x020102FF`, `33686271 =
0x020202FF` — the expected voice-controller firmware version, 2.1.2 → 2.2.2.
**[INFERRED]**, from the hex matching the filenames.

### What does *not* change — the load-bearing negatives

| thing | result | evidence |
|---|---|---|
| `las-sc` OSC namespace | **identical** — 816 `/`-prefixed strings, 503 of them `/p*`; **0 added, 0 removed** | **[READ]** `strings`+`comm` on both `usr/bin/las-sc` |
| `usr/share/vx_ee.scm` (expression symbol table) | **byte-identical**, 13,134 B both | **[READ]** `cmp` |
| `usr/share/las-fx/**` — every `.scd` incl. `init_sc_1.scd`, `init_sc_2.scd`, `synthdefs.scd`, `efx_server.scd` | **byte-identical** | **[READ]** `diff -rq`, empty output |
| SQLite schema (every `CREATE TABLE` literal in `las-frontend`) | **identical**, 0 added, 0 removed | **[READ]** `comm` on extracted `CREATE TABLE` strings |
| DB migration code paths (`Settings upgrade from version`, `sanitizeAndUpgradeMidiMap`, `Missing timestamp column in presets table`, `Found old effect_presets table`) | present in **both** 1.5.0 and 1.8.2 | **[READ]** |
| kernel version | `Linux-4.1.15-rt18`, same in both uImage headers; same payload size `0x004D3728`; modules dir `4.1.15-rt18` both | **[READ]** `xxd -l 64` on both `boot/uImage` |
| kernel cmdline (`boot/cmdline.txt`) | identical, `isolcpus=1` and all | **[READ]** `diff` |

The `-z 128` block size, the `isolcpus=1` audio-core arrangement, and the
`/p` namespace this project has mapped all survive the update untouched.
**[INFERRED]**, from the four [READ] rows above.

The **kernel image itself does differ** (1,213,510 differing bytes, different
header and data CRCs) despite the identical version string and identical size.
That is consistent with a rebuild of the same source; whether any code changed is
**[UNKNOWN]** from here.

### The one real payload change: `las-frontend`

145,070,812 → 145,033,524 bytes. Its human-readable string set is almost
unchanged: **the only added display strings are `On`, `Rate`, and the build date
`Sep 15 2025`; the only removed one is `May 16 2022`.** No new menus, no new
panels, no new `.qml`/`.js` paths (0 added, 0 removed). **[READ]** — `comm` on
sorted `strings` output.

What *did* change is the embedded default/INIT patch, exactly matching the
release notes' "Improved INIT patch". Newly present as addressed defaults:

```
/p/part/t/{1,2,3}/p/e{1,2,3}/{async,dsync,rsync} false     EG attack/decay/release sync
/p/part/t/{1,2,3}/p/l{1,2,3,4}/fsync false                 LFO rate sync
/p/part/t/{1,2,3}/p/o{1,2,3}/hardsync false                oscillator hard sync
/p/part/t/{1,2,3}/p/fa/mode false
/p/part/t/{1,2,3}/p/modmatrix/vars/cvout{1,2,3,4} 0.0
/p/part/cv_settings/cv_output/{1,2,3,4}/voice_rule "o"
```
and newly *absent*: `/p/part/t/{1,2,3}/p/arp/p/tempo 120.0`. **[READ]** — `comm`
on the two string sets.

These are preset-file field names, not engine endpoints — `las-sc`'s own address
set did not change, and the engine's hard-sync addresses remain `/p/o1/sync1..3`.
`hardsync` as a token is new to `las-frontend` in 1.8.2, but
`OscillatorHardSyncUpdater` already existed in 1.5.0. **[READ]/[INFERRED]**

### This resolves an open question in `CORRECTIONS-2026-09-08.md` §9

That section leaves undetermined whether `cv_output/N/voice_rule` — set by Lisa
Bella Donna's 25 presets but absent from this instrument's namespace dump — is a
firmware difference or a hole in the dump.

**It is a firmware difference.** 1.5.0's `las-frontend` emits five
`cv_output/N/*` defaults per output (`source`, `min`, `max`, `synth`); 1.8.2's
emits six, adding `voice_rule "o"` for outputs 1–4. **[READ]** — `grep
"cv_output"` over the sorted string sets of both binaries, 19 matches vs 23, the
four extra being exactly the `voice_rule` lines. Both binaries contain the bare
token `voice_rule`, so 1.5.0 may still *parse* the field — but it does not
*produce* it. **[INFERRED]**

---

## 5. What is gained

Straight from Moog's own release notes PDF, `captures/firmware-1.8.2/Moog One
Firmware Update v1.8.2.pdf`. **[READ]** — text extracted from the PDF's
compressed content streams.

**v1.8.2** — "a hot fix for v1.8.1":
- Fixed regression where envelopes very rarely would never fully go silent and
  release the voice.
- Fixed regression where toggling KEYBOARD CONTROL ON for a synth would stop
  voices for the other synths.

**v1.8.1:**
- Fixed regression where some presets with oscillator hard sync enabled were not
  loading correctly.

**v1.8.0** — the substance, and it is almost entirely MIDI:
- Fixed USB descriptor to improve MIDI compatibility with Windows.
- **Fixed crashes when receiving large amounts of MIDI data.**
- ARP: MIDI output was sending original key presses instead of ARP notes;
  turning ARP on while playing only sent ARP notes after one loop.
- EG ATTACK/DECAY/RELEASE SYNC, LFO RATE SYNC, GLIDE ON, GLIDE RATE — all now
  MIDI-mappable.
- LADDER filter slope and SVF filter mode changed via MIDI now reflected in the
  UI and front panel.
- **Fixed changing OSC HARD SYNC through MIDI CC causing panel lag and crashes.**
- Fixed LHC More Semitone Transpose not affecting MIDI note number.
- Fixed hanging notes while changing MIDI IN ports or channels while receiving.
- Fixed MIDI PANIC causing note A5 to trigger.
- Fixed multiple issues with EG LOOP and LATCH.
- Improved INIT patch (all OSCs TRI 0%, SAW fastest reset times).

The XMOS-side changes are visible in the shipped git metadata:

- voice controller `app_las` 2.1.2 → 2.2.2, head commit
  `d888eec9`, 2025-09-11: *"Fix Local On/Off dumping held notes"*
- voice cards `app_vx` 2.1.0 → 2.2.1, head commit `02619910`,
  2025-09-10: *"Clamp min eg release"*

**[READ]** — `usr/share/xmosfw/app_las_gitinfo.json` and `app_vx_gitinfo.json` in
both trees. (The repositories also moved from `gitlab.com/moogmusic` to
`gitlab.inmusicbrands.com/moog/hardware/moog-one`, and the maintainer's address
from `@moogmusic.com` to `@resonancedesign.group` — the inMusic transition, of no
technical consequence here.)

Two of these — the large-MIDI-input crash and the hard-sync-via-CC crash — are
the exact failure modes this project's tooling provokes. `docs/ARCHITECTURE.md:48`
already names them. **[READ]**

### One gap the release notes do not cover

The PDF documents **1.8.0, 1.8.1 and 1.8.2 only**. The owner is jumping from
**1.5.0**, so they also receive everything in 1.6.x and 1.7.x, whose notes are
not in this PDF. `docs/arch/expression-language.md:25` says
`Moog_One_v1.8.2.zip → Past Firmware Update Release Notes/*.pdf` holds v1.0.1
through v1.8.2 — those were **not read for this report**. The claim that "1.8.1
and 1.8.2 exist solely to fix 1.8.0 regressions" is **correct and [READ]**, but
it should not be mistaken for "1.5.0 → 1.8.2 is only bug fixes"; that is
**[UNKNOWN]** for the 1.6/1.7 span. What *is* [READ] is that whatever those
releases did, it left the OSC namespace, `vx_ee.scm`, the SuperCollider graph and
the DB schema untouched, and added no new UI strings.

---

## 6. What is risked

### R1 — the XMOS voice-controller flash, at first boot (the real one)

The XMOS firmware is **not** written by `lasfwu`. It is written by `las-sc` at
every boot, driven by `S42sc`'s `--vcfw`/`--vcfv`/`--vxfw` arguments. `las-sc`
contains:

```
flashrom -l /usr/share/xmosfw/las_layout -i firmware -w
Upgrading XMOS firmware:
Sound engine controller is updating VC firmware.
Sound engine controller is updating VX firmware.
```
**[READ]** — `strings` on `rootfs-1.8.2/usr/bin/las-sc`. `las_layout` reads
`00000000:0x001BFFFF firmware` — a single 1.75 MiB region. **[READ]**

**There is no A/B pair for the XMOS.** The layout defines one region and
`flashrom -w` overwrites it in place. A power loss during that write leaves the
voice controller — the part that terminates *all* DIN and USB MIDI and carries
`ethext`/`usbint` — with a partial image, and nothing in this repository or on
the instrument can restore it. `docs/DANGER.md` already states this:
"Still unprotected, and unprotectable from here: the sixteen voice cards' own
flash and the voice controller's flash." **[READ]/[INFERRED]**

**Timing.** This happens on the **first boot after** the update, not during the
`lasfwu` run — which is precisely the "restart process may take longer than
normal… approximately 10 minutes" the release notes warn about. **[INFERRED]**,
from `S42sc` running at boot and the release-notes text. So the dangerous window
is *after* the progress bar finishes, when it is most tempting to touch the power.

**Mitigation: none available from here.** Just: mains power, no switching off,
wait out the full ten minutes even if the screen looks idle.

### R2 — the unconditional 16 MiB raw-eMMC zeroing

`lasfwu:820-826`:

```
startofpartmap=`sgdisk -i=1 /dev/mmcblk2 | awk -F "First sector:" … `

if [ $startofpartmap > 60000 ]; then
	    dd if=/dev/zero of=/dev/mmcblk2 bs=1024 count=16384 seek=1024
fi;
rm 60000;
```
**[READ]**

`>` inside `[ ]` is parsed by the shell as **output redirection**, not
comparison. The test degrades to the one-argument form `[ $startofpartmap ]`,
true whenever the string is non-empty; the redirect creates a file named `60000`,
which the next line deletes. **The intended guard does not run, and the `dd`
executes on every successful update** — zeroing bytes 1,048,576 through
17,825,792 of the raw eMMC. **[INFERRED]**, from POSIX shell parsing of the
[READ] source. The stray `rm 60000` is the tell that the author never saw the
comparison work.

**Why this is almost certainly harmless in practice:** this script is unchanged
since 2017 and identical in 1.5.0 and 1.8.2 (§1), so this `dd` has run on every
Moog One firmware update ever shipped. If it overlapped anything needed for boot,
every updated unit would have failed. **[INFERRED]** — an empirical argument, not
a structural one.

**Why it should still be checked:** the actual start sector of partition 1 is
**[UNKNOWN]** — no partition table dump exists in the capture set. If p1 begins
before sector 34,816 (17 MiB) the wipe would land inside the factory recovery
partition. A read-only `sgdisk -p` settles it in one command (§9). This is the
single most worthwhile pre-flight check on the list.

### R3 — the sentinel is cleared before the write, not after

`lasfwu:564` writes `0` to `/var/lib/sys/sentinelu$part` **before** anything is
extracted; the real value is only written at `:808`, after a successful `dd`.
`bootme` is written at `:809`, also only on success. **[READ]**

So a mid-update failure leaves the *target* slot's sentinel at `0` while that
slot still holds its old (v1.4.0) contents, and `bootme` still points at the
live slot. The instrument should still boot normally into 1.5.0. **[INFERRED]**

But **what consumes `bootme` and `sentinelu1`/`sentinelu2` is U-Boot**, which
lives in the raw eMMC and is not present in any capture. `grep` finds those names
in `lasfwu` and nowhere else in the entire 1.8.2 root filesystem. **[READ]** —
so the exact fallback semantics are **[UNKNOWN]**, and the claim "rollback is one
keystroke" rests on `docs/DANGER.md`'s observation that both slots are intact,
plus the structural fact that the updater maintains a per-slot sentinel at all.
This is the weakest link in the recommendation and is the second item in the
validation plan.

### R4 — a failed update leaves ~788 MiB behind until the next boot

The cleanup at `:791-792` sits *after* every `return 1` path, so it is not
reached on failure. `S14fs` clears `/mnt/fwu/*` at the next boot, so this
self-corrects. **[READ]/[INFERRED]** If `MOUNTDIR` had fallen back to `/var`,
`S14fs` would **not** clear it — `S14fs` only wipes `/mnt/fwu`. **[READ]** In
that case a failed update would silently consume 788 MiB of the 3.3 G preset
partition until manually removed. Low probability, easy to check afterwards.

### R5 — the non-`--api` code path is broken

`lasfwu:745`, the `else` branch of the final write, reads
`dd if="$MOUNTDIR/tmpfs/$imagename.tar"` — a file that never exists; the image is
`rootfs`, and after decryption `rootfs.ext4`. **[READ]** Only the `--api` branch
at `:742` uses the correct `$upgradefs`. `las-frontend` contains both
`/usr/bin/lasfwu` and `--api` as strings, and `docs/arch/control-plane.md:322-325`
records the frontend shelling out to `lasfwu`. **[INFERRED]** the front-panel path
uses `--api` and is therefore the working one — which is also the only path the
owner will use. Do not run `lasfwu load` by hand from a shell without `--api`.

### R6 — not a risk: the image cannot be tampered with

`CORRECTIONS-2026-09-08.md:113` establishes that the signing key never left Moog
(`/usr/share/sec/secring.gpg` is 0 bytes) and that `IMAGE-SIG` is verified
unconditionally before the `dd`. Independently re-checked here: the verify at
`:686`, its exit-code gate at `:720-726`, and the dead `--accept-unsigned`.
**[READ]** The package on disk is Moog's, and only Moog's will install.

---

## 7. What is irreversible

Ranked by how much it should weigh on the decision.

| # | what | reversible? | evidence |
|---|---|---|---|
| 1 | **The v1.4.0 slot on `mmcblk2p2` is overwritten.** | **No.** Moog does not distribute 1.4.0. | **[INFERRED]** §2 |
| 2 | **The XMOS voice-controller flash** (2.1.2 → 2.2.2) and the sixteen voice cards (2.1.0 → 2.2.1). | **Yes, automatically** — see below. | **[READ]/[INFERRED]** |
| 3 | `/var/lib/sys/bootversion` and the sentinels are rewritten. | Trivially — rewritten by any subsequent update. | **[READ]** `lasfwu:564-568`, `:808-809` |
| 4 | **`/var` is shared between both slots.** Anything 1.8.2 writes there is seen by 1.5.0 after a rollback. | Depends. See below. | **[READ]** `fstab` |
| 5 | 16 MiB of raw eMMC zeroed at offset 1 MiB. | Unknown region. | **[INFERRED]** §6 R2 |

### On #2 — the XMOS flash undoes itself on rollback

`las-sc` compares versions for **equality**, not ordering:

```
version matches file, no update needed.
version does not match, update needed.
version not available, update needed.
) does not match file, update needed.
```
**[READ]** — `strings` on `rootfs-1.8.2/usr/bin/las-sc`; and the flag help text
"*Update VX firmware even if versions match*" confirms match/mismatch semantics
for the voice cards too.

So booting the 1.5.0 slot after an update finds VC at `0x020202FF`, expects
`0x020102FF` per `S42sc`'s `--vcfv=33620735`, sees a mismatch, and **reflashes
2.1.2 back down**. The XMOS state follows whichever slot is booted. **[INFERRED]**,
from the equality strings plus the version constant in each slot's own `S42sc`.

This is a genuinely good property: it means a rollback is a *complete* rollback,
not a half-rollback with new XMOS firmware stranded under old Linux. It also
means a rollback re-enters the R1 flash window — so a rollback deserves the same
power discipline as the update.

### On #4 — the shared `/var`, and why it is not a real problem here

This is where a firmware upgrade would normally hurt, because `/var` is not
slot-scoped: a migration written by the new firmware is still there after you
roll back. The release notes' "the instrument may need to update its internal
settings (approximately 10 minutes)" is exactly that shape of warning.

The evidence says it is benign in this specific pair:

- **The SQLite schema is identical.** Every `CREATE TABLE` literal in
  `las-frontend` matches between 1.5.0 and 1.8.2 — 0 added, 0 removed. **[READ]**
- **The migration routines are not new.** `Settings upgrade from version `,
  `sanitizeAndUpgradeMidiMap`, `sanitizeAndUpgradeSettingsMidiMap`,
  `Missing timestamp column in presets table`, `Found old effect_presets table`
  all appear in **both** binaries, once each. They are legacy paths for
  pre-1.5 databases, not something 1.8.2 introduces. **[READ]**
- The instrument's live DB reads `PRAGMA user_version = 0`, and its table set
  matches the 1.8.2 `CREATE TABLE` list exactly. **[READ]** — read-only open of
  the local copy at `captures/MOOG ONE.db`.

**[INFERRED]:** the "10 minutes" is the MIDI-map sanitize and settings-version
pass that 1.5.0 also runs, not a schema migration, and a rollback to 1.5.0 will
find a database it understands.

**The one asymmetry that remains.** Presets *saved* under 1.8.2 will carry
`cv_output/N/voice_rule` (§4), which 1.5.0 does not emit. Whether 1.5.0's parser
tolerates the extra field is **[UNKNOWN]** — the token exists in its binary, but
that is not proof it is handled on load. This affects only presets newly written
after the update, and only if the owner later rolls back. The preset DB should be
backed up before the update regardless, which makes this moot.

---

## 8. Conflicts with existing documentation

Reported, not fixed, per the working rule for this report.

1. **`docs/arch/control-plane.md:517-521` (finding "D10") says firmware flashing
   has *no signature check*** — "Any authenticity/integrity check lives in
   `lasfwu` … which is not in this capture set." `lasfwu` **is** in the capture
   set (three copies, all identical), and it **does** verify `IMAGE-SIG`
   unconditionally at `:686` before the `dd`. `control-plane.md:532-535`'s risk
   table row "D10 unsigned firmware path … yes (flash)" is wrong on the same
   basis. `CORRECTIONS-2026-09-08.md:113` already states the correct position;
   `control-plane.md` has not been updated to match.

2. **`docs/CORRECTIONS-2026-09-08.md:148` grades the 788.31 / 800.5 / 12.19 MiB
   measurement `[AGENT]` — "worth re-checking before any update."** It has now
   been re-checked and is confirmed, with the margin at **12.18 MiB** rather than
   12.19. The grade can be raised.

3. **`docs/CORRECTIONS-2026-09-08.md:160-165` (§9, "Still open") leaves
   `voice_rule` undetermined** between "firmware difference" and "hole in the
   dump." §4 above settles it: firmware difference. 1.8.2's `las-frontend` emits
   four `cv_output/N/voice_rule` defaults that 1.5.0's does not.

4. **`docs/DANGER.md:264-278` describes the slot pair as "A/B" and speculates
   "The partition table shows a second symmetric pair too (`p4`/`p5`, ~64 MB
   each) which is very likely kernel and device tree."** Two corrections: (a) the
   scheme is A/B/**C** — `lasfwu:469-541` has a `case 1)` branch for booting from
   a *factory* partition, `mmcblk2p1`, which picks the older of p2/p3 to replace;
   there is a third, recovery root. (b) `p4` is not a kernel partition — `fstab`
   mounts it as **vfat at `/var/lib/sys`**, and it is where `bootme`,
   `bootversion` and `sentinelu1`/`sentinelu2` live. The kernel is `/boot/uImage`
   *inside* each rootfs slot. `p5` remains **[UNKNOWN]**.

5. **`docs/ARCHITECTURE.md:48` says "Nothing tuning-related changed after
   1.5.0."** Consistent with this report — `vx_ee.scm` and all of
   `/usr/share/las-fx/` are byte-identical — but note the voice-card firmware
   *did* change (`app_vx` 2.1.0 → 2.2.1, "Clamp min eg release"), and the voice
   cards are where tuning is applied. The statement is safe for the *tuning
   tables*; it is not evidence about voice-card behaviour.

---

## 9. Validation plan — READ-ONLY commands for the human to run

Not run by this report. Every one is non-mutating. Run them on the instrument
before starting the update; the first two are the ones that matter.

```sh
# 1. Settle R2: where does partition 1 actually start?
#    The unconditional dd zeroes bytes 1,048,576 .. 17,825,792 of /dev/mmcblk2.
#    Partition 1 must begin at or after sector 34816 for that to be harmless.
sgdisk -p /dev/mmcblk2

# 2. Confirm the slot arithmetic and what is about to be destroyed.
cat /proc/cmdline                       # expect root=/dev/mmcblk2p3
mount -o ro /dev/mmcblk2p2 /mnt/u1 && cat /mnt/u1/etc/version && umount /mnt/u1
#   ^ expect las-v1.4.0 — this is the slot the update overwrites

# 3. Confirm the staging headroom at the moment of the update.
df -h /mnt/fwu                          # expect ~800.5M available, 0% used
#   Peak requirement is 788.32 MiB. Anything under ~800M available means stop.

# 4. Confirm the FWU partition is named such that MOUNTDIR resolves to /mnt/fwu
#    and not /var  (lasfwu:456 greps sgdisk output for the literal "FWU").
sgdisk -p /dev/mmcblk2 | grep -i fwu

# 5. Record the current boot-slot state, so a rollback can be reasoned about.
cat /var/lib/sys/bootme /var/lib/sys/bootversion 2>/dev/null
hexdump -C /var/lib/sys/sentinelu1 /var/lib/sys/sentinelu2 2>/dev/null

# 6. Record current XMOS versions, to confirm the reflash afterwards.
cat /usr/share/xmosfw/VERSIOND          # expect 33620735  (0x020102FF = VC 2.1.2)

# 7. Dry-run the package without writing anything.
#    --dry-run is honoured (lasfwu:451 gates the whole write path on it).
lasfwu search --api /media/thumbdrive
lasfwu verify-file --api /media/thumbdrive/moog-one-v1.8.2

# 8. After the update completes and the instrument has finished its long first
#    boot, confirm the XMOS actually took the new firmware:
cat /etc/version                        # expect las-v1.8.2
cat /usr/share/xmosfw/VERSIOND          # expect 33686271  (0x020202FF = VC 2.2.2)
df -h /mnt/fwu                          # expect the staging area cleared
```

Do **not** run `lasfwu load` by hand — the non-`--api` path is broken (§6 R5),
and the front-panel UPDATE FIRMWARE flow is the tested one.

---

## 10. Not established

- **The start sector of `/dev/mmcblk2p1`**, and therefore whether the
  unconditional 16 MiB wipe at `lasfwu:825` is genuinely harmless or merely
  has been so far. No partition table exists in the capture set.
- **What consumes `/var/lib/sys/bootme` and the sentinels.** Only `lasfwu`
  references them anywhere in the root filesystem; the consumer is U-Boot, in
  the raw eMMC, which is not captured. The rollback procedure is therefore
  inferred from the updater's bookkeeping, not read from the bootloader.
- **`mmcblk2p5`** — present in the kernel's partition scan, absent from `fstab`,
  purpose unknown.
- **What changed in the kernel.** Same version string, same payload size,
  1,213,510 differing bytes.
- **The 1.6.x and 1.7.x release notes**, which sit in
  `Moog_One_v1.8.2.zip → Past Firmware Update Release Notes/` and were not read.
  Everything about the 1.5.0 → 1.8.2 span other than 1.8.x is characterised here
  only by what the binary diff shows.
- **Whether 1.5.0 tolerates a `voice_rule` field on preset load** — relevant only
  to presets saved under 1.8.2 and then read after a rollback.
- **Whether `--dry-run` exercises the decrypt path.** It does not appear to.
  `lasfwu:451` gates the entire real path on `dryrun == 0`, and the dry-run
  branch at `:396` only `dd`s the package file to `$dest` — which defaults to
  `${PWD}/dd_image` (`:376`). So `lasfwu load --dry-run` is **not** read-only:
  it writes a 149 MB copy of the package into the current working directory, and
  it is **not** a test of the 788 MiB staging requirement. **[READ]** Use
  `verify-file`, not `load --dry-run`.
