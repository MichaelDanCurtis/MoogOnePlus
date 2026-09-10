<!-- docs/firmware/xmos.md -->
# `/usr/share/xmosfw` in firmware 1.8.2, and the two XMOS images

Region report. Source of record: the decrypted v1.8.2 root filesystem at
`captures/firmware-1.8.2/rootfs-1.8.2`, compared throughout against
`captures/rootfs-1.5.0` (the owner's own instrument) and
`captures/arch-harvest`. Nothing here came from a powered instrument. Every
claim is graded:

* **[READ]** — read directly out of a named file at a named offset or line.
* **[INFERRED]** — reasoning from stated evidence.
* **[UNKNOWN]** — said so.

Two earlier reports cover adjacent ground: `docs/arch/xmos-firmware.md` (the
2.1.2 / 2.1.0 images) and `docs/arch/xmos-deep.md` (the protocol). This report
does not edit them. Where it disagrees, see §12.

---

## 1. The directory, complete

`captures/firmware-1.8.2/rootfs-1.8.2/usr/share/xmosfw/` — six files, no
subdirectories, no hidden files. **[READ]**

| file | bytes | mode | mtime | sha256 (first 64 hex) |
|---|---:|---|---|---|
| `VERSIOND` | 9 | `-rw-r--r--` | 2025-09-15 | `7164fac08fcb8e950eaa38eee419a80b090f527031eead753222464148284786` |
| `app_las_gitinfo.json` | 899 | `-rw-r--r--` | 2025-09-15 | `5e3d60cff2b144ea48c3b758bef28ac425f4f6e3a75e9c481fc1bed8b8cf2b75` |
| `app_las_v2.2.2.bin` | 2 097 152 | `-rwxr-xr-x` | 2025-09-15 | `302e1edc0d47ee603bdf415885616575a24e4bf8c61825ec388254f37d230f69` |
| `app_vx_10M_v2.2.1.bin` | 164 352 | `-rwxr-xr-x` | 2025-09-15 | `55eb4f8c149b96a917ba07e76e030ed89c89c2b9437473cc684138c310d46132` |
| `app_vx_gitinfo.json` | 889 | `-rw-r--r--` | 2025-09-15 | `a66a3e2c967662dfb2b68b02ab2d7a1bc1e9a1729f952ecc32fbdc8b181f1c1b` |
| `las_layout` | 29 | `-rw-r--r--` | 2025-03-11 | `7d54e3e4b2ecf2f9bfbc9fa26bacf291905fea21e82901c507404161bdd8ab1d` |

The v1.5.0 directory has exactly the same six names with the version numbers
changed. **[READ]**

| file | 1.5.0 bytes | sha256 prefix |
|---|---:|---|
| `VERSIOND` | 9 | `5e4306aa477a709f…` |
| `app_las_gitinfo.json` | 766 | `483a0056fc75b4e4…` |
| `app_las_v2.1.2.bin` | 2 097 152 | `ece76f084bbda035…` |
| `app_vx_10M_v2.1.0.bin` | 164 096 | `1252d4583aa8ed8f…` |
| `app_vx_gitinfo.json` | 782 | `fbe8c2a147d9fbdb…` |
| `las_layout` | 29 | `7d54e3e4b2ecf2f9…` — **byte-identical to 1.8.2** |

The two `.bin` files in `captures/arch-harvest/` are byte-identical (md5) to
the ones in `rootfs-1.5.0`, so the harvest set is a faithful copy of the
instrument's own images and the owner's unit is on the 1.5.0 pair. **[READ]**

`las_layout` is unchanged between the two releases; the two `.bin` files, the
two `gitinfo.json` files and `VERSIOND` all changed.

---

## 2. `las_layout` — a flashrom layout file

29 bytes, one line, `\n`-terminated: **[READ]**

```
00000000:0x001BFFFF firmware
```

hexdump: `30303030 30303030 3a307830 30314246 46464620 6669726d 77617265 0a`

This is a **flashrom region layout**, consumed as
`flashrom -l /usr/share/xmosfw/las_layout -i firmware …` (§7). **[INFERRED
from the literal command string in `las-sc`, §7.]** It defines one named
region, `firmware`, spanning flash addresses `0x000000`–`0x1BFFFF` inclusive =
**1 835 008 bytes = 1.75 MiB**. **[READ]**

The image file is 2 MiB. So the layout deliberately stops **256 KiB short of
the end of the chip**: `0x1C0000`–`0x1FFFFF` is never written. **[INFERRED]**
Three pieces of evidence say what lives there:

* In the shipped `.bin` the whole of `0x1C0000`–`0x1FFFFF` is zero — the last
  non-zero byte in `app_las_v2.2.2.bin` is at `0x3E0CF`. Writing that range
  would erase whatever the unit had. **[READ]**
* `flashrom` 0.9.9 in this rootfs states `Layout files are currently supported
  for write operations only`, i.e. `-i firmware` restricts the write and
  preserves the rest of the chip. **[READ, `usr/sbin/flashrom` string]**
* The controller image contains the *placeholder* MAC string
  `A41163B0FFFE` (§5.4) while the owner's unit reports
  `a4:11:63:b0:28:9b` on `ethext`. The per-unit identity is therefore not in
  the image. **[READ for both values; INFERRED that the difference is stored
  in the un-flashed top 256 KiB.]**

The host also exposes `/info/serial`, `/info/mac`, `/info/uuid`,
`/info/protect`, `/info/write`, `/info/comment`, `/info/hwrev` (strings in
`usr/bin/las-frontend`) **[READ]**, which is the read/write interface to that
per-unit block. Where those bytes physically live — the top of this SPI flash,
an XMOS OTP row, or elsewhere — is **[UNKNOWN]**.

---

## 3. `VERSIOND` — the controller version, in decimal

9 bytes, ASCII decimal plus newline. **[READ]**

| release | contents | as hex |
|---|---|---|
| 1.8.2 | `33686271\n` | `0x020202FF` |
| 1.5.0 | `33620735\n` | `0x020102FF` |

`0x02 0x02 0x02 0xFF` = 2.2.2; `0x02 0x01 0x02 0xFF` = 2.1.2. Both match the
`app_las_*` filename in the same directory exactly. **[READ for the bytes;
INFERRED for the `MM mm pp FF` field layout — but it is confirmed by two
independent releases and by the voice-card word at §5.3.]**

The file is consumed verbatim by the init script. `etc/init.d/S42sc` line 4,
1.8.2: **[READ]**

```
/usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300 \
  --vxfw=/usr/share/xmosfw/app_vx_10M_v2.2.1.bin \
  --vxdb=/var/tuning.vxtune \
  --vcfw=/usr/share/xmosfw/app_las_v2.2.2.bin \
  --vcfv=33686271 \
  --temp --expr-syms=/usr/share/vx_ee.scm \
  --panel-state=localhost:9500 $1
```

and 1.5.0, same script, `--vcfv=33620735` with the 2.1.x filenames. **[READ]**

`las-sc --help` describes `--vcfv` as `Expected voice control firmware
version.` **[READ, `las-sc` string pool]**

**The asymmetry is real and worth stating.** The controller's version is a
*build-time constant* that the packaging pipeline copies from `VERSIOND` into
the init script; `las-sc` never reads the controller `.bin` to find out what
version it is. The voice card's version, by contrast, `las-sc` reads out of
the file itself (`vxfw-read-fw-version`, §5.3). **[INFERRED from: `--vcfv`
exists at all and equals `VERSIOND`; `vxfw-read-fw-version` takes `fwfile` and
does bitstring reads on it; there is no corresponding `vcfw-read-fw-version`
symbol in `las-sc`.]** The practical consequence: if `VERSIOND` and the
`app_las_*.bin` ever disagreed, `las-sc` would compare the wrong number
against the running controller and either reflash needlessly or skip a needed
flash. Nothing checks them against each other.

---

## 4. The two `gitinfo.json` files — never previously copied

Both are single-line JSON, a verbatim GitLab commit object. Reproduced in full
because the provenance is the point.

### 4.1 `app_las_gitinfo.json` (1.8.2), 899 bytes **[READ]**

```json
{ "id": "d888eec913efd7922b051f2a3711d7ceeff74880",
  "short_id": "d888eec9",
  "created_at": "2025-09-11T17:36:53.000+00:00",
  "parent_ids": [ "e531a1443478ea60b5eddbc4571a66f0b64da368",
                  "27b8b8aa7ece97af63a24af4d933e8a1f230be5b" ],
  "title": "Merge branch 'fix-local-on-off' into 'master'",
  "message": "Merge branch 'fix-local-on-off' into 'master'\n\nFix Local On/Off dumping held notes\n\nSee merge request moog/hardware/moog-one/las-fw!109",
  "author_name": "Sylvan Williams",
  "author_email": "sylvan.williams@resonancedesign.group",
  "authored_date": "2025-09-11T17:36:53.000+00:00",
  "committer_name": "Sylvan Williams",
  "committer_email": "sylvan.williams@resonancedesign.group",
  "committed_date": "2025-09-11T17:36:53.000+00:00",
  "trailers": {}, "extended_trailers": {},
  "web_url": "https://gitlab.inmusicbrands.com/moog/hardware/moog-one/las-fw/-/commit/d888eec913efd7922b051f2a3711d7ceeff74880" }
```

### 4.2 `app_vx_gitinfo.json` (1.8.2), 889 bytes **[READ]**

```json
{ "id": "0261991033c1a5324eb1ae7f11ec7c1d20d879cf",
  "short_id": "02619910",
  "created_at": "2025-09-10T19:54:13.000+00:00",
  "parent_ids": [ "25c828c2bc936d8c8ff514fed32c70c7966c638e",
                  "e46fbf1c613d8c3f12fdff612ee2dcf906b02c2b" ],
  "title": "Merge branch 'clamp-min-eg-release' into 'master'",
  "message": "Merge branch 'clamp-min-eg-release' into 'master'\n\nClamp min eg release\n\nSee merge request moog/hardware/moog-one/vx-fw!45",
  "author_name": "Sylvan Williams",
  "author_email": "sylvan.williams@resonancedesign.group",
  … committed_date "2025-09-10T19:54:13.000+00:00",
  "web_url": "https://gitlab.inmusicbrands.com/moog/hardware/moog-one/vx-fw/-/commit/0261991033c1a5324eb1ae7f11ec7c1d20d879cf" }
```

### 4.3 The 1.5.0 pair, for comparison **[READ]**

| | `app_las` 2.1.2 | `app_vx` 2.1.0 |
|---|---|---|
| id | `c38fe65079f0231e6886ad7e933e8ab9dad06be8` | `d309cf3beeb1ada98c86f7e8924685db5480247d` |
| short_id | `c38fe650` | `d309cf3b` |
| committed | 2022-04-01T13:21:26Z | 2021-11-03T20:42:52Z |
| title | `Merge branch 'dev/rick' into 'master'` | `Merge branch 'dev/luke/cvin/modw-pad' into 'master'` |
| message body | `1.5 Beta Bug fixes` | `Dev/luke/cvin/modw pad` |
| MR | `moogmusic/las-fw!98` | `moogmusic/vx-fw!42` |
| author | Sylvan Williams `<sylvan@moogmusic.com>` | Luke Craig `<luke@moogmusic.com>` |
| host | `gitlab.com/moogmusic/las-fw` | `gitlab.com/moogmusic/vx-fw` |

### 4.4 What the metadata actually tells you

* **The two firmwares are separate git repositories**, `las-fw` and `vx-fw`,
  versioned and merged independently. Their version numbers are not locked
  together (2.1.2/2.1.0 → 2.2.2/2.2.1). **[READ]**
* **The projects moved.** `gitlab.com/moogmusic/{las,vx}-fw` (2021–2022) →
  `gitlab.inmusicbrands.com/moog/hardware/moog-one/{las,vx}-fw` (2025), and the
  author domain moved `moogmusic.com` → `resonancedesign.group`. **[READ]**
  Merge-request numbering is continuous across the move (`las-fw!98` → `!109`,
  `vx-fw!42` → `!45`), so the repositories were migrated with history, not
  restarted. **[INFERRED]**
* **The whole delta, named.** Between the owner's firmware and 1.8.2, the
  controller repo advanced 11 merge requests (`!98`→`!109`) and the voice-card
  repo 3 (`!42`→`!45`). The tip commits are titled `Fix Local On/Off dumping
  held notes` and `Clamp min eg release`. **[READ]** Those are the *last*
  changes in each, not the sum of them — but they are the only human-readable
  description of what changed in the XMOS firmware that exists anywhere on
  this disk. **[INFERRED]**
* **Build window.** The two commits are 2025-09-10 and 2025-09-11; every file
  in the 1.8.2 rootfs that changed carries mtime 2025-09-15. So the 1.8.2
  package was built no earlier than 2025-09-11. **[INFERRED from mtimes and
  commit dates.]**
* The `gitinfo.json` is emitted by a CI step that queries the GitLab commits
  API and drops the raw response next to the artefact — the key set
  (`trailers`, `extended_trailers`, `web_url`) is GitLab's commit
  representation. **[INFERRED]** The 1.5.0 files lack `extended_trailers`,
  which is a later GitLab addition. **[READ]**

Nothing on the instrument appears to read these two files. A text-file grep
(`grep -rIl`) over the whole 1.8.2 rootfs for `xmosfw`/`VERSIOND`/`las_layout`
returns only `etc/init.d/S42sc` and `usr/bin/lasfwu` — and `lasfwu` matches
only on its own name: grepping it for `xmos`, `VERSIOND`, `las_layout`,
`app_las`, `app_vx`, `vcfv` and `spi` returns nothing. **[READ]** A byte-level
scan of every file under `bin`, `sbin`, `usr/bin`, `usr/sbin`, `usr/lib` and
`etc` (including `las-frontend`) for the string `gitinfo` returns **no hits at
all**. **[READ]** The `gitinfo.json` files are shipped documentation, not
runtime data. **[INFERRED]**

A methodological warning for anyone repeating this: plain `grep` on this
material **silently reports nothing** for binaries containing NUL bytes.
`grep -c 'las_layout' usr/bin/las-sc` returns empty; `grep -a -c` returns 1.
**[READ]** Every binary search in this report was done with `-a`, with
`strings`, or byte-wise in Python.

---

## 5. The two images

### 5.1 At a glance

| | controller | voice card |
|---|---|---|
| 1.8.2 file | `app_las_v2.2.2.bin` | `app_vx_10M_v2.2.1.bin` |
| 1.5.0 file | `app_las_v2.1.2.bin` | `app_vx_10M_v2.1.0.bin` |
| file size (both releases) | 2 097 152 (2 MiB, fixed) | 164 352 / 164 096 |
| last non-zero byte, 1.8.2 | `0x3E0CF` | `0x2812B` |
| last non-zero byte, 1.5.0 | `0x3DE6F` | `0x28063` |
| padding | to the full 2 MiB flash device | to the next 256-byte boundary |
| byte transform | **bit-reverse each byte** | **swap the nybbles of each byte** |
| header | 24 bytes at `0x00` | 64 bytes at `0x00` |
| segment table | `0x0AFC`–`0x0B5F` | `0x002C`–`0x0053` |
| first segment byte | `0x0B60` | `0x0054` |
| segments | 8 records, 7 node ids | 3 records, 2 node ids |
| git build string | `-v2.2.2-0-gd888eec9` (partly referenced) | `lasvx-v2.2.1-0-g0261991` (literal) |

The two transforms are how each part's boot path presents bits, not
obfuscation. Undo them or nothing below is visible. Both are confirmed
independently below rather than assumed.

**Why bit-reversal is right for the controller** — three independent checks,
all **[READ]**:

1. `strings` on the raw file yields 372 runs of noise; on the bit-reversed
   file, 889 runs including `LAS internal`, `Moog`, `Moog Music, Inc`,
   `Internal Clo…`, `Write to flash complet…`, `#bundle`.
2. Header word at `+0x0C` reads `0x001C0000` bit-reversed — exactly the
   `las_layout` firmware-region size — and `0x00380000` raw, which matches
   nothing.
3. Header word at `+0x08` reads `0x0003E100` bit-reversed in 2.2.2 and
   `0x0003DF00` in 2.1.2 — in both cases exactly the last non-zero offset
   rounded up to a 256-byte boundary. Raw it reads `0x00C08700` / `0x00C0FB00`,
   which matches nothing.

**Why nybble-swap is right for the voice card** — **[READ]**:

1. Nybble-swapped, the word at `+0x10` is `0x0002812C` in 2.2.1 and
   `0x00028064` in 2.1.0 — in both cases exactly the last non-zero offset plus
   one. Raw it reads `0x002018C2`, which matches nothing.
2. Nybble-swapped, the word at `+0x14` is `0x020201FF` (=2.2.1) and
   `0x020100FF` (=2.1.0), the same `MM mm pp FF` encoding as `VERSIOND`.
3. `las-sc`'s own reader calls `nybble-swap-string` immediately after opening
   the firmware file (`vxfw-lib.scm:169, 180-184`). **[READ, `las-sc` string
   pool]**

### 5.2 Controller header, 24 bytes at file offset 0

Bit-reversed. Bytes 0x15–0x7F are zero; the first segment table word is at
`0x0AFC`. **[READ]**

| off | 2.2.2 | 2.1.2 | reading |
|---|---|---|---|
| `+0x00` | `0x000002B2` | `0x000002B2` | constant across releases; **[UNKNOWN]** |
| `+0x04` | `0x9000733F` | `0x9000733F` | constant across releases; **[UNKNOWN]** |
| `+0x08` | `0x0003E100` | `0x0003DF00` | image size, rounded up to 256 **[INFERRED, exact in both releases]** |
| `+0x0C` | `0x001C0000` | `0x001C0000` | boot-partition size = `las_layout`'s `firmware` region **[INFERRED, exact match]** |
| `+0x10` | `0x00000005` | `0x00000005` | **[UNKNOWN]** |
| `+0x14` | `0x00000008` | `0x00000008` | equals the segment-record count (8) **[INFERRED, weak — one data point]** |

The only field that differs between the two releases is the size at `+0x08`.
**[READ]**

### 5.3 Voice-card header, 64 bytes at file offset 0

Nybble-swapped. `+0x0C` = `0x40` = the header length; the segment table starts
at `+0x2C` inside it and the first segment byte is `0x54`. **[READ]**

| off | 2.2.1 | 2.1.0 | reading |
|---|---|---|---|
| `+0x00` | `0x00FF51DE` | `0x00FF51DE` | magic, identical across releases **[INFERRED]** |
| `+0x04` | `0x0142F67F` | `0xCED3DD5D` | per-build; **[UNKNOWN]** — not CRC-32 of any of eight tested ranges |
| `+0x08` | `0x2A8A8337` | `0x744EA06E` | per-build; **[UNKNOWN]** |
| `+0x0C` | `0x00000040` | `0x00000040` | header size / first-segment offset **[INFERRED]** |
| `+0x10` | `0x0002812C` | `0x00028064` | image size in bytes **[INFERRED, exact]** |
| `+0x14` | `0x020201FF` | `0x020100FF` | version `MM mm pp FF` **[READ]** |
| `+0x18` | `0x0002812C` | `0x00028064` | image size, repeated **[READ]** |
| `+0x1C` | `0x00000002` | `0x00000002` | equals the node-id count (2) **[INFERRED, weak]** |
| `+0x20…+0x28` | zero | zero | |
| `+0x2C…` | segment table | segment table | §5.5 |

The version word also appears a second time deeper in the image — `0x1C0BB` in
2.2.1, `0x1C048` in 2.1.0 — inside a table of small constants
(`…FE FF 7F 7F FE B5 04 | FF 01 02 02 | FF FF 0F 00 FF FF 7F…`). **[READ]**
That is the copy the firmware reports over the bus; the header copy is the one
`vxfw-read-fw-version` reads off disk. **[INFERRED]**

### 5.4 Build strings

**Voice card, fully literal** — the only completely uncompressed identity
string in either image: **[READ]**

* 2.2.1: `lasvx-v2.2.1-0-g0261991` — matches `app_vx_gitinfo.json`
  `short_id` `02619910` at 7-character abbreviation.
* 2.1.0: `lasvx-v2.1.0-0-gd309cf3` — matches `d309cf3b`.

**Controller, partly back-referenced** — at `0x2AC83` in 2.2.2 the bytes are
**[READ]**

```
2d 76 32 2e  e7 01  2d 30 2d 67 64 38 38 38 65 65 63 39
 -  v  2  .  <tok>   -  0  -  g  d  8  8  8  e  e  c  9
```

i.e. `-v2.` + a two-byte token + `-0-gd888eec9`. The token stands for the
three characters `2.2`, which the encoder emitted as an overlapping match at
distance 2 into the just-written `2.`. **[INFERRED]** The reconstructed string
is `…v2.2.2-0-gd888eec9`, matching `app_las_gitinfo.json` `short_id`
`d888eec9`. In 2.1.2 the same field is fully literal at `0x2AC8D` —
`-v2.1.2-0-gc38fe65` — because `1.2` is not a repeat of `1.` **[READ]**. This
single comparison is the cleanest proof in either image that the payload is
LZ-compressed (§6).

Nearby, in both releases: `fwtime\0\0git\0`, `hwre[v]`, `product`,
`i32:%ld`, `iAP`, `int:`. **[READ]**

**USB string descriptors.** At `0x11C17`–`0x11C47` in 2.2.2 (and `0x11C07`
onward in 2.1.2 — the same 48 bytes, shifted by exactly 16), bit-reversed:
**[READ]**

```
30 32 30 30   a9 15 95   47 41 34 31 31 36 33 42 30 46 46 46 45
"0200"                    "G" "A41163B0FFFE"
95 45  4c 41 53 20 69 6e 74 65 72 6e 61 6c   95 45  4d 6f 6f 67   95 41
       "LAS internal"                                "Moog"
```

The literal text present is `0200`, `A41163B0FFFE`, `LAS internal`, `Moog`.
The `95 …` bytes are compression tokens, so the exact string boundaries — in
particular whether the serial really starts at `G` or at `A` — are
**[UNKNOWN]** until the format is solved. The 12 hex digits are a MAC address
in the `a4:11:63:b0` range. The owner's unit's `ethext` interface reports
`a4:11:63:b0:28:9b`; the udev rule `etc/udev/rules.d/50-eth-ext-nic.rules`
matches `ATTR{address}=="a4:11:63:b*"`. **[READ, dmesg + rules file]** So
`A4:11:63:B0:FF:FE` is a firmware default that the real unit overrides —
consistent with §2.

This block is **byte-identical between 2.1.2 and 2.2.2**. **[READ]**

### 5.5 The segment table, and what it lays out

Both images carry a table of the same shape. Reading it, bit-reversed /
nybble-swapped, as little-endian 32-bit words: **[READ]**

**Controller `app_las_v2.2.2.bin`, at `0x0AFC`:**

```
0x0AFC  0x00000034      0x0B28  0x00110002    <- id
0x0B00  0x0000003C      0x0B2C  0x00000F65
0x0B04  0x00000090  <-  0x0B30  0x000113D8
0x0B08  0x0000040F      0x0B34  0x00000002    <- id
0x0B0C  0x000010CC      0x0B38  0x00000B91
0x0B10  0x00120002  <-  0x0B3C  0x0001421C
0x0B14  0x00000D5E      0x0B40  0x00010002    <- id
0x0B18  0x00004644      0x0B44  0x00000AC1
0x0B1C  0x00100002  <-  0x0B48  0x00016D20
0x0B20  0x00002400      0x0B4C  0x00040002    <- id
0x0B24  0x0000D644      0x0B50  0x00005074
                        0x0B54  0x0002AEF0
                        0x0B58  0x00050002    <- id
                        0x0B5C  0x000049C4
                        0x0B60  first segment byte
```

**Voice card `app_vx_10M_v2.2.1.bin`, at `0x002C`:**

```
0x002C  0x00000034
0x0030  0x0000003C
0x0034  0x00000054   <- base
0x0038  0x000000AE   <- size, words
0x003C  0x0000030C   <- running end
0x0040  0x00000002   <- id
0x0044  0x00007137
0x0048  0x0001C7E8
0x004C  0x00010002   <- id
0x0050  0x00002E51
0x0054  first segment byte
```

**The arithmetic law**, exact in all four images: **[READ / INFERRED — the
arithmetic is read, the field names are inferred]**

```
end[0] = base + 4 * words[0]
end[k] = end[k-1] + 4 * words[k]
```

Every step checks to the byte. The size field is a count of 32-bit **words**;
the third field is a running byte offset. Two independent confirmations:

* Voice card: `0x54 + 4·(0xAE + 0x7137 + 0x2E51) = 0x2812C`, which is exactly
  the `+0x10` image-size field and exactly `last non-zero + 1`. **[READ]**
* Controller: `0xB60 + 4·(0x40F + 0xD5E + 0x2400 + 0xF65 + 0xB91 + 0xAC1 +
  0x5074 + 0x49C4) = 0x3E0D0`, exactly `last non-zero + 1`. **[READ]**
  (The table's own offsets run from `0x90`; the whole chain is displaced by
  `0xB60 − 0x90 = 0xAD0` when mapped onto the file. **[INFERRED]**)

Mapping the chain onto file offsets gives the segment layout:

| # | node id | words | file range | size (bytes) |
|---:|---|---:|---|---:|
| 0 | — (loader) | `0x040F` | `0x00B60`–`0x01B9C` | 4 156 |
| 1 | `0x12` | `0x0D5E` | `0x01B9C`–`0x05114` | 13 688 |
| 2 | `0x10` | `0x2400` | `0x05114`–`0x0E114` | 36 864 |
| 3 | `0x11` | `0x0F65` | `0x0E114`–`0x11EA8` | 15 764 |
| 4 | `0x00` | `0x0B91` | `0x11EA8`–`0x14CEC` | 11 844 |
| 5 | `0x01` | `0x0AC1` | `0x14CEC`–`0x177F0` | 11 012 |
| 6 | `0x04` | `0x5074` | `0x177F0`–`0x2B9C0` | 82 384 |
| 7 | `0x05` | `0x49C4` | `0x2B9C0`–`0x3E0D0` | 75 536 |

| # | node id | words | file range | size |
|---:|---|---:|---|---:|
| 0 | — (loader) | `0x00AE` | `0x00054`–`0x0030C` | 696 |
| 1 | `0x00` | `0x7137` | `0x0030C`–`0x1C7E8` | 116 188 |
| 2 | `0x01` | `0x2E51` | `0x1C7E8`–`0x2812C` | 47 428 |

Note the ambiguity: an id word sits **between** consecutive `(words, end)`
pairs, so it can be read as belonging to the record after it or the record
before it. I take it as *preceding* its record, leaving record 0 as an
unlabelled loader. **[INFERRED]** Supporting it: record 0 in both images is
the only one that is uncompressed machine code (§6), which is what a
decompressing loader has to be; and the voice card is a two-tile part, giving
exactly the two ids seen.

**Node ids are `(node << 16) | 2`.** The controller carries code for **seven**
xcore nodes — `0x00, 0x01, 0x04, 0x05, 0x10, 0x11, 0x12` — the voice card for
**two**, `0x00` and `0x01`. **[READ for the ids; INFERRED for the
`node << 16` decomposition, which matches `xmos-firmware.md`'s independent
reading.]** What physical parts those nodes are — one multi-tile package, two
packages on an xCONNECT link, or a mix — is **[UNKNOWN]** from these files.

### 5.6 Which node owns which text

Cross-referencing the plaintext regions against the segment map:

| plaintext at | node | contents |
|---|---|---|
| `0x0DB80`–`0x0DC80` | `0x10` | front-panel / keybed calibration (`cal_defaul[t]`, `save`, `print`, `alpha`, `thresh`, `decay`, `kbd`, `low`, `high`, `pitch`, `glide`, `atouch`, `seqleds`, `leds`) |
| `0x11C17`–`0x11C47` | `0x11` | USB string descriptors (`LAS internal`, `Moog`, the MAC serial) |
| `0x29D80`–`0x2A100` | `0x04` | the OSC address table, thermal/fan, status codes |
| `0x2AA00`–`0x2AD80` | `0x04` | flash-access messages, `/info`, `Moog Music, Inc`, `Clock Selector`, `MIDI`, the git build string |
| `0x3C800`–`0x3CE00` | `0x05` | a **second** copy of the address table |

**[READ for the offsets and contents; INFERRED for the node attribution, via
§5.5.]** This resolves what looked like duplication: the address table appears
twice because two different nodes each carry their own copy, compiled from the
same source. The LZ window never spans the ~77 KiB between them, so the second
copy is re-emitted rather than referenced.

Node `0x11` holding the USB descriptors makes it the USB tile. **[INFERRED]**
Nodes `0x12`, `0x00` and `0x01` in the controller image carry no recoverable
plaintext at all. **[READ]**

Voice card: the whole command surface is in node `0x00`'s segment, around
`0x1BB40`–`0x1C5C0` in 2.2.1. **[READ]**

### 5.7 What changed 2.1.x → 2.2.x, measured

Per-segment word counts: **[READ]**

| node | 2.1.2 | 2.2.2 | Δ words |
|---|---:|---:|---:|
| loader | `0x040F` | `0x040F` | 0 |
| `0x12` | `0x0D5E` | `0x0D5E` | 0 |
| `0x10` | `0x23FE` | `0x2400` | +2 |
| `0x11` | `0x0F65` | `0x0F65` | 0 |
| `0x00` | `0x0B91` | `0x0B91` | 0 |
| `0x01` | `0x0AC1` | `0x0AC1` | 0 |
| `0x04` | `0x505F` | `0x5074` | +21 |
| `0x05` | `0x4943` | `0x49C4` | +129 |
| **total** | `0x3D310` B | `0x3D570` B | **+608 bytes** |

| node | 2.1.0 | 2.2.1 | Δ words |
|---|---:|---:|---:|
| loader | `0x00AE` | `0x00AE` | 0 |
| `0x00` | `0x711B` | `0x7137` | +28 |
| `0x01` | `0x2E3B` | `0x2E51` | +22 |
| **total** | `0x28010` B | `0x280D8` B | **+200 bytes** |

Additional facts:

* The **loader segment is byte-identical** between 2.1.2 and 2.2.2, and
  between 2.1.0 and 2.2.1. **[READ]**
* The USB descriptor block is byte-identical between 2.1.2 and 2.2.2 (§5.4).
  **[READ]**
* Diffing every recoverable literal fragment between the two controller images
  and between the two voice-card images turns up **no new command, address or
  message string** — every difference is a token-boundary shift of text
  already present, plus the git hash. **[READ]** So neither firmware gained a
  new OSC endpoint or reply string that survives as plaintext.

That is consistent with the git titles (§4): small behavioural fixes, not new
surface. **[INFERRED]** Note the caveat: text that is entirely back-referenced
would not show up in this diff, so "no new strings" is a statement about
literals, not a proof that no string was added.

---

## 6. Both payloads are compressed; both loaders are not

The prior report established that the string tables are LZ77-compressed with a
high-bit-flagged token format that is not fully solved. This pass confirms it
and adds two things: a quantitative separation of code from compressed data,
and the observation that the marker alphabet is build-dependent.

**Code-versus-not, measured.** Counting distinct 16-bit little-endian words and
the share of the twenty commonest, over each segment: **[READ]**

| region | words | distinct | top-20 share |
|---|---:|---:|---:|
| ARM reference (`usr/bin/las-watchdog`, real machine code) | 7 524 | 1 321 | **44.4 %** |
| LAS segment 0 (loader) | 2 078 | 689 | **46.0 %** |
| VX segment 0 (loader) | 348 | 197 | **44.3 %** |
| LAS node `0x12` | 6 844 | 4 568 | 7.4 % |
| LAS node `0x04` | 41 192 | 15 965 | 7.2 % |
| LAS node `0x05` | 37 768 | 15 102 | 6.7 % |
| VX node `0x00` | 57 966 | 19 246 | 8.9 % |
| VX node `0x01` | 23 714 | 11 133 | 8.0 % |

The loaders behave exactly like machine code. Every node segment behaves like
nothing that has an instruction-set distribution. **[INFERRED: the loaders are
uncompressed code and the node segments are compressed.]** The loaders are
also visibly the *same program* in both images — they open with the identical
twelve bytes `00 F0 40 77 40 7F 8C 91 40 60 80 64` and then diverge only in
branch immediates. **[READ]**

Standard container formats are excluded: raw-deflate, zlib, gzip at every
offset in the first 512 bytes, and LZMA-alone, all fail. **[READ, tested]**

**The markers move between builds.** At `0x2AC10` the same span of text is
encoded with tokens `AD …` / `B5 …` in 2.1.2 and `DF …` / `E7 …` in 2.2.2.
**[READ]** In 2.2.2, node `0x04`'s segment is dominated by `DF`/`E7` bytes and
node `0x05`'s by `B5`/`AD`. **[READ, from the 16-bit histograms:
`02E7`, `04E7`, `10DF` lead in node `0x04`; `02B5`, `04B5`, `B504`, `10AD`
lead in node `0x05`.]** So the marker byte carries payload and is not a fixed
magic — which is what `docs/arch/xmos-firmware.md` §2.2 concluded, now
confirmed against a second release.

The format remains unsolved. See §11.

---

## 7. The update and flash paths — documented, not proposed

**Read §10 before reading this section as anything but description.**

### 7.1 Nothing in this directory updates itself

`etc/init.d/S25xmosfw` is titled `Writes XMOS firmware to the system as
needed.` It does no such thing. In full: **[READ]**

```sh
#!/bin/sh
# Writes XMOS firmware to the system as needed.
test -r /etc/default/dropbear && . /etc/default/dropbear   # copy-paste residue
start() {
    echo "Cycle XMOS Power"
    config-las-spi xmos
}
case "$1" in
  start) start ;;
  stop) ;;  restart|reload) ;;
  *) echo "Usage: $0 {start|stop|restart}"; exit 1
esac
exit $?
```

It power-cycles the XMOS and exits. The comment and the `dropbear` line are
both leftovers. Byte-identical in 1.5.0. **[READ]** All actual firmware
comparison and flashing happens later, inside `las-sc`, started by `S42sc`.
**[INFERRED from the argv in §3 and the string evidence below.]**

`usr/bin/lasfwu` — the whole-system update tool — contains no reference to
`xmosfw`, `app_las`, `app_vx`, SPI or flashrom. **[READ, grep]** It is the
rootfs updater; the XMOS path is separate and lives in `las-sc`.

### 7.2 The bus: how the SPI flash is shared

`usr/bin/config-las-spi` (byte-identical in 1.5.0) has two modes. **[READ]**

```sh
config_spi_xmos()                     config_spi_som()
  devmem 0x20e0244 32 5   KEY_COL0      echo 0 > .../XMOS_RESET_N/brightness
  devmem 0x20e0248 32 5   KEY_COL1      devmem 0x20e0244 32 0
  devmem 0x20e0258 32 5   KEY_ROW0      devmem 0x20e0248 32 0
  devmem 0x20e025c 32 5   KEY_ROW1      devmem 0x20e0258 32 0
  devmem 0x20a8004 32 0x40008020        devmem 0x20e025c 32 5
  echo 0 > .../XMOS_RESET_N/brightness  devmem 0x20a8004 32 0x40008220
  echo 1 > .../XMOS_RESET_N/brightness
```

with the script's own comments: *"forces SPI1 pins to be GPIO inputs so that
XMOS may control the bus"* and *"returns SPI1 pins to original function and
places XMOS in reset so that SOM may control the bus."* **[READ]**

The four addresses are i.MX6 IOMUXC mux-control registers for `KEY_COL0`,
`KEY_COL1`, `KEY_ROW0`, `KEY_ROW1`; `0x20A8004` is `GPIO4_GDIR`. **[INFERRED
from the i.MX6 memory map.]** Mux value 0 selects the ECSPI1 function and 5
selects GPIO. **[INFERRED]** The two `GDIR` values differ in exactly one bit,
bit 9: `0x40008020` (xmos, bit 9 clear = input) versus `0x40008220` (som, bit
9 set = output). **[READ]**

That bit is identified by the device tree. `boot/imx6dl-profili-som.dtb`
(byte-identical between the two releases, md5 `87f2b786…`) **[READ]**:

* `/soc/aips-bus@02000000/spba-bus@02000000/ecspi@02008000` — ECSPI1,
  `status = "okay"`, `fsl,spi-num-chipselects = <1>`,
  `cs-gpios = <&phandle-0x0a 9 0>`, child `spidev@0` with `reg = <0>` and
  `spi-max-frequency = 0x00B71B00` (**12 000 000 Hz**). This is
  `/dev/spidev0.0`. **[READ]**
* `/misc_output/xmosreset` — a `gpio-leds` entry, `label = "XMOS_RESET_N"`,
  `gpios = <&phandle-0x36 5 0>`, `default-state = "off"`. This is the
  `/sys/class/leds/XMOS_RESET_N/brightness` node the script writes. **[READ]**
* `/soc/aips-bus@02100000/i2c@021a0000/xmos_codec@11` — the XMOS is *also* an
  I2C slave at address `0x11` on I2C1, `compatible = "moog,las,xmos"`,
  `clock-names = "codec_osc"`. **[READ]** With `/sound-xmos-esai`
  (`compatible = "fsl,imx-audio-xmos-esai"`) this is the audio link. **[READ]**

So the chip-select GPIO in `cs-gpios` is pin **9** of the same bank whose
`GDIR` bit 9 the script toggles. The two files agree exactly. **[INFERRED]**
In `som` mode the SoC drives SCLK/MISO/MOSI as ECSPI1 and the chip select by
hand as a GPIO output; in `xmos` mode all four pins go high-impedance GPIO
inputs and the XMOS is released from reset to own the bus and boot from it.
**[INFERRED, and it is what the script's comments say.]**

`XMOS_RESET_N` is active-low by its name, so `brightness 0` asserts reset and
`1` releases it: `config-las-spi som` leaves the XMOS **held in reset**, and
`config-las-spi xmos` pulses it. **[INFERRED]**

### 7.3 Controller (VC) firmware: flashrom over SPI

The literal command, assembled from three adjacent strings in `las-sc`. The
CHICKEN Scheme string constants carry a length prefix, which pins the text
exactly — the `8` before `flashrom` is `0x38` = 56 = the length of the string
that follows, and the leading space of the second fragment is `0x20` = 32 =
its length. **[READ]**

```
flashrom -l /usr/share/xmosfw/las_layout -i firmware -w <vcfw path> -p linux_spi:dev=/dev/spidev0.0
```

preceded by the log line `Upgrading XMOS firmware:`. **[READ]** These strings
are **identical in the 1.5.0 `las-sc`** — the controller flash mechanism did
not change between the releases. **[READ]** `usr/sbin/flashrom` is
`0.9.9-unknown` and is byte-identical (md5 `46eaf656…`) in both releases.
**[READ]**

The surrounding decision logic, from `las-sc`'s string pool in order:
**[READ]**

```
Provided VC Firmware Filename Invalid
Network Error - Flashing VC Anyway
Other exception:  … - Flashing VC Anyway
no vc firmware update needed
file vc firmware version:            <- the --vcfv value
installed vc firmware version:       <- queried from the running VC
/info/versionb
vc firmware file:
VC firmware file provided, but can't power-cycle LAS. (Are you running off target?)
DONE
Update Failed (Not Enabling XMOS)
```

and the Scheme trace names `sc/sc.scm:768/772/784: update-vc-firmware`,
`sc/sc.scm:898: handle-vc-firmware`. **[READ]**

Two things follow. First, `las-sc` reads the *running* controller's version
over OSC (`/info/versionb`) and compares it against the number handed to it on
the command line, not against the file. **[INFERRED from the two adjacent log
strings plus §3.]** Second, **a network failure does not abort the flash** —
`Network Error - Flashing VC Anyway` is a real branch. **[READ]**

### 7.4 Voice-card (VX) firmware: OSC over the internal network

There is no SPI path to a card. The cards are reached over the internal
CDC-Ethernet link to the controller.

The network, from the 1.8.2 rootfs (all byte-identical to 1.5.0): **[READ]**

* `etc/hosts`: `203.0.113.2 vc` — so `las-sc -t vc` (help text: `Xmos Target
  address`) targets `203.0.113.2`. **[READ]**
* `etc/network/interfaces`: `usbint` static `203.0.113.1/24`; `usbext` and
  `ethext` DHCP; `eth0` static `192.168.1.1`.
* `etc/udev/rules.d/20-xmos-nic.rules`: the interface whose MAC is
  `02:00:00:00:00:00` is renamed `usbint`, then
  `arp -i usbint -s 203.0.113.2 02:00:00:00:00:00` pins the controller's ARP
  entry.
* `etc/udev/rules.d/50-eth-ext-nic.rules` + `eth-ext.sh`: the `a4:11:63:b*`
  interface becomes `ethext`, and UDP **7770, 7771, 9100, 9300** are DNATed
  from `ethext` (and identically from `usbext`) straight to `203.0.113.2`.
  So four of the controller's UDP ports are exposed on the rear RJ45 and the
  rear USB socket.

Corroboration from the instrument's own boot log
(`captures/dmesg-before-reboot.txt`, lines 302–305): **[READ]**

```
cdc_ether 2-1:1.0 usb0: … CDC Ethernet Device, 02:00:00:00:00:00
cdc_ether 2-1:1.2 eth0: … CDC Ethernet Device, a4:11:63:b0:28:9b
cdc_ether 2-1:1.0 usbint: renamed from usb0
cdc_ether 2-1:1.2 ethext: renamed from eth0
```

Both are functions `1.0` and `1.2` of the **same** USB device `2-1`. The XMOS
presents two CDC Ethernet interfaces on one link.

The `/fw` protocol itself, from `las-sc`'s `vxfw-lib.scm` string pool and
symbol table (function signatures are recovered verbatim from the CHICKEN
symbol table): **[READ]**

```
vxfw-send-block(card, adr, ofs, blob)
vxfw-send-block-from-port(card, adr, ofs, port, block-size)
vxfw-send-data(card, data-port, data-length)
vxfw-send-fw(card, fwfile)
vxfw-send-fw-cards(ip, cards, fwfile)
vxfw-read-fw-version(fwfile)
vxfw-get-card-version(card)
vxfw-check-card(card, version)      vxfw-check(ip, cards, fwfile)
vxfw-versions(ip, cards)            vxfw-list(ip, cards)
```

with the OSC addresses `/fw/start`, `/fw/data`, `/fw/version`,
`/info/product`, `/info/versionb`, and the messages `Sending firmware to `
… ` cards`, `cannot start fw download (`, `failure in send-block`,
`sent firmware to card `, `invalid firmware file`, `version not available`,
plus the table headers `Card` / `Version`. **[READ]**

Source-line trace, in the order the strings appear: **[READ]**

```
 84- 97  response checking (osc?, osc-arg-count, osc-value, string-prefix?,
         response-prefix?) then string->blob -> vxfw-send-block
105-109  vxfw-send-data: block-size keyword, loop over send-block-from-port
111-120  vxfw-send-fw: file-size; las-card-query "/fw/start"; response check;
         call-with-input-file; vxfw-send-data; las-card-nr
123-141  vxfw-send-fw-cards: las-open, pause-for, las-card-count, iota,
         las-card-open, vxfw-send-fw   (per card)
169      nybble-swap-string  (string-map)
180-184  vxfw-read-fw-version: call-with-input-file, with-input-from-port,
         ->bitstring, bitstring-read, bitstring->integer-little, bitstring-length
207-232  vxfw-get-card-version: las-card-query x3, -query-string, -query-uint
239-254  vxfw-check / vxfw-check-card / vxfw-error
259-276  las-open, las-card-count, iota, map-cards, fmt#radix
287-300  vxfw-list: las-open, las-card-count, las-fwrev, las-gitrev, print-table
307-312  CONFIG-LAS-SPI: regular-file? and file-execute-access? checks, then
         (system "/usr/bin/config-las-spi xmos")
```

`bitstring->integer-little` at line 183 with `nybble-swap-string` at 184 is
exactly how the version word at file offset `0x14` (§5.3) is read. **[INFERRED,
and it decodes correctly for both voice-card releases, which is the check.]**

Version gating and the escape hatches: `--force-vx-update` (`Update VX firmware
even if versions match.`), the outcomes ` version matches file, no update
needed.` / ` version does not match, update needed.` / ` version not
available, update needed.`, and `Force-updating cards: `. **[READ]**
`vxfw-send-fw-cards` iterates `(iota (las-card-count))`, so one invocation
addresses every card present. **[READ]**

Failure handling: `Failed to enumerate VX.`, `Failed to enumerate VX after
trying 10 times.`, `Network Unreachable - Power-cycling XMOS`,
`power-cycling xmos`, `Opening lasport`. **[READ]**

The status strings the front panel sees during all this: `Sound engine
controller is updating VC firmware.`, `Sound engine controller is updating VX
firmware.`, `Sound engine controller is updating tuning data.`, `Sound engine
controller is verifying tuning data.` **[READ]** The frontend's own label is
`UPDATING VOICE CARD FIRMWARE...`. **[READ, `usr/bin/las-frontend`]**

### 7.5 The card side of the flash protocol

Both images contain a flash read *and* write handler with its own reply
vocabulary. Recoverable literals, voice card `app_vx_10M_v2.2.1.bin` around
`0x1C120`–`0x1C1C0` (nybble-swapped): **[READ]**

```
200 Read from flash …      Write to flash complete      Failed to r(ead) …
550 CRC     (wr)ong image version     magic number     leng(th)
555 Internal error: invalid poi(nter)     9 Other     successful
Not foun(d)     Malformed messag(e)     %s voice %d: %s error %d
address set to %d
```

and the same `Read from flash` / `Write to flash complet(e)` /
`Failed to … data from` pair in the controller image around `0x2AA6A`.
**[READ]** `wrong image version` and `magic number` name two of the checks the
card applies to what it is sent — consistent with the header fields at
`+0x00` (magic) and `+0x14` (version) in §5.3. **[INFERRED]**

---

## 8. What is *not* in this directory, and why that matters

* **No signature, no checksum file, no manifest.** The whole-system updater
  `lasfwu` validates its payload with GPG (`/etc/mmsk`, `/etc/mmek`, a key
  extracted from `/etc/bob.bmp`, a tar containing `MOOGFW` and `MANIFEST`).
  **[READ]** None of that applies to `/usr/share/xmosfw`: once a rootfs is on
  the device, the two `.bin` files are flashed on the strength of a version
  number in a shell script. **[INFERRED]**
* **No recovery image.** There is one controller image and one voice-card
  image. No factory copy, no fallback, no second slot. **[READ — the directory
  has six files and that is all of them.]**
* **No `10M` explanation.** The voice-card filename is
  `app_vx_10M_v2.2.1.bin`. `10M` appears in no other file in the rootfs.
  **[UNKNOWN]**

---

## 9. Validation plan (read-only, for a human to run)

None of these were run. Every one is a query; none writes. They are ordered so
that a failure at step *n* makes *n+1* pointless. Note the standing hazard from
`docs/arch/xmos-deep.md` §6.3: **`/fw/*` must not be sent at all**, and most
`/cal` and `/hw` addresses are the same address for read and write, so any
probe must carry zero arguments.

**On the Linux side, over SSH — all read-only:**

```sh
# 1. Confirm the directory the owner's unit actually has.
ls -la /usr/share/xmosfw/ ; cat /usr/share/xmosfw/VERSIOND ; cat /usr/share/xmosfw/las_layout
sha256sum /usr/share/xmosfw/*
#    Expect for a 1.5.0 unit: VERSIOND 33620735, app_las_v2.1.2.bin,
#    app_vx_10M_v2.1.0.bin, and the sha256 values in §1.

# 2. Confirm the version the init script hands to las-sc.
grep -o -- '--vcfv=[0-9]*' /etc/init.d/S42sc
grep -o -- '--v[cx]fw=[^ ]*'  /etc/init.d/S42sc

# 3. Confirm the gitinfo files are present and match §4.3.
cat /usr/share/xmosfw/app_las_gitinfo.json ; echo
cat /usr/share/xmosfw/app_vx_gitinfo.json  ; echo

# 4. Confirm the SPI bus and the reset line exist as the DTB says.
ls -l /dev/spidev0.0
cat /sys/class/leds/XMOS_RESET_N/brightness      # read only; do NOT write
cat /sys/bus/spi/devices/spi0.0/modalias 2>/dev/null

# 5. Confirm the network shape.
cat /etc/hosts ; ip -o addr ; arp -n
iptables -t nat -S PREROUTING
```

**Deliberately excluded**, and why:

* `flashrom -p linux_spi:dev=/dev/spidev0.0` even with only `--flash-name`.
  Probing requires the SPI bus, and the bus belongs to the XMOS unless the
  XMOS is first put into reset. Getting there means running `config-las-spi
  som`, which halts the instrument. Not a read-only operation in practice.
* Any `/fw/version` query. It is a read, but it is one message away from
  `/fw/start` in the same namespace, and there is no recovery path for a card.
* `las-sc --cli` in any form. It exists to update firmware.

**If a value from the controller is genuinely needed**, the safe reads are the
ones the shipping host already performs every boot — `/info/version`,
`/info/versionb`, `/info/git`, `/info/vc-version`, `/info/vc-git`,
`/info/product`, `/info/fwrev`, `/info/voice-count`, `/v/voices`, `/ping` —
sent zero-argument to `203.0.113.2`. That would confirm §3's claim that the
number in `--vcfv` is compared against `/info/versionb`. **It still touches the
instrument, so it belongs to the owner to run, not to this report.**

---

## 10. Do not use any of §7 to update anything

Stated once, plainly, because §7 is a working recipe.

A voice card that fails a flash has **no recovery path**: the only way in is
the very bus whose firmware just failed, and the boards are unobtainable. The
controller is scarcely better — its own SPI path requires holding the XMOS in
reset, and a half-written 1.75 MiB region leaves a part that cannot boot to
answer the next attempt.

Two specific traps are visible in the code and are worth naming:

* `las-sc` proceeds to flash the controller after a network error
  (`Network Error - Flashing VC Anyway`). **[READ]** A flash begun on a link
  that is already failing is exactly the case that ends badly.
* `vxfw-send-fw-cards` loops over every card. **[READ]** There is no
  single-card mode in the shipping path, so a bad image is a bad image sixteen
  times.

§7 is here so that the mechanism is understood and so that an *accidental*
trigger can be recognised. It is not an instruction.

---

## 11. Unexplored

1. **The compression format is still unsolved.** This pass confirmed it is
   LZ77-family with a high-bit flag and added a new lever the prior work did
   not have: the *same span of text* is now available in **four** encodings —
   `las-a`/`las-b` and `las-c` within 2.2.2, and again within 2.1.2, where the
   marker alphabet differs (`AD`/`B5` versus `DF`/`E7`). A ground truth like
   the git build string, where 2.1.2 spells `-v2.1.2-` literally and 2.2.2
   encodes `2.2` as the two bytes `E7 01` at a known distance (2) and length
   (3), is a directly solvable equation for one token. That single pair was not
   pursued here.
2. **Header fields `+0x00`, `+0x04`, `+0x10` of the controller and `+0x04`,
   `+0x08` of the voice card.** The voice card's two per-build words are not
   CRC-32 of any of eight tested byte ranges. Not tested: CRC-32C, the XMOS
   `crc32` polynomial `0xEDB88320` applied word-wise as `xcore`'s `CRC32`
   instruction does, or a hash over the nybble-swapped versus raw bytes with
   the header excluded.
3. **The loader.** Both images' segment 0 is uncompressed xcore machine code
   and contains the decompressor. It was not disassembled — no xcore
   disassembler is installed (`llvm-objdump` on this machine registers only
   AArch64/ARM/x86). A `binutils` or LLVM build with the XCore target, or
   `xobjdump` from the XMOS toolchain, would read it directly and give the
   compression format for free. That is the shortest path to item 1.
4. **Which physical parts nodes `0x00,0x01,0x04,0x05,0x10,0x11,0x12`
   correspond to.** The board photographs in `docs/arch/hardware-external.md`
   were not consulted for this.
5. **`10M`** in `app_vx_10M_*.bin`. **[UNKNOWN]**
6. **`usr/bin/lassvc`** (3.4 MB, present in both releases, unchanged in size)
   and `las_clock_demo`. `lassvc-connect-to-socket` appears in `las-sc`'s
   symbol table, so `lassvc` is on the controller path, but it was not read.
7. **`las-frontend`'s update UI.** 145 MB; only grepped. The panel that calls
   `/usr/bin/lasfwu` and shows `UPDATING VOICE CARD FIRMWARE...` was not traced.
8. **Whether the 1.8.2 controller image still contains no AVB code.**
   `docs/CORRECTIONS-2026-09-08.md` §7 established that for 2.1.2; not re-run
   against 2.2.2.
9. **The top 256 KiB of the controller flash** — what is actually stored at
   `0x1C0000`–`0x1FFFFF` on a real unit. Only a read of the live chip would
   settle it, and that requires taking the SPI bus from the XMOS.

---

## 12. Conflicts with existing documents

Reported, not fixed.

1. **`docs/arch/xmos-firmware.md` §1: "they share a loader stub
   byte-for-byte."** Not correct for either release pair. The controller's
   segment-0 and the voice card's segment-0 share only their first **12 bytes**
   exactly (`00 F0 40 77 40 7F 8C 91 40 60 80 64`), then diverge in branch
   immediates — `01 F0 3E DA` versus `00 F0 E6 D8` at offset +12. **[READ]**
   The correct statement is that it is the *same loader program*, separately
   linked for each part. What *is* byte-identical is the loader across
   *releases*: LAS 2.1.2 ≡ 2.2.2 and VX 2.1.0 ≡ 2.2.1. **[READ]**

2. **`docs/arch/xmos-firmware.md` §1: the segment table's "two `size` fields
   differ by 3-20x, which is consistent with `(stored, in-RAM)` — the images
   are decompressed at boot."** The conclusion (decompression at boot) is
   right, but the field reading is wrong. The second field is not a size at
   all: it is a **running end-offset**, and the ratio to the first field is
   **exactly 4 in every record of all four images**, because the first field
   is a count of 32-bit words. `end[k] = end[k-1] + 4·words[k]`, and the chain
   closes on the byte in every image (§5.5). No in-RAM size is recorded
   anywhere in the table.

3. **`docs/arch/xmos-firmware.md` §1: segment counts.** It reports the
   controller as "**8 segments**" (8 records, 7 ids) and the voice card as
   "**2 segments**" (2 ids, but 3 records) over the same byte extents I read.
   The two numbers are counted differently. Consistently counted, it is 8
   records / 7 node ids and 3 records / 2 node ids.

4. **`docs/arch/xmos-deep.md` §0: the version word is "`MM mm pp FF`,
   big-endian."** The *value* is `0x020102FF`, but in the file the bytes are
   `FF pp mm MM` — `FF 01 02 02` at voice-card offset `0x14`. **[READ]**
   `las-sc` reads it with `bitstring->integer-little`. **[READ]** Calling the
   layout big-endian will mislead anyone who goes looking for `02 01 02 FF` in
   a hex dump. The value is `MM mm pp FF`; the storage is little-endian.

5. **`docs/arch/xmos-firmware.md` §2.2 region table** lists five encoded
   regions and gives `las-c` as `0x3C400-0x3DF00`. In 2.2.2 the corresponding
   dense-text runs are at `0x3C800-0x3C900` and `0x3CD00-0x3CE00`, and in
   2.1.2 at `0x3CA80-0x3CC00`. **[READ]** Not a contradiction — region bounds
   are version-specific — but any offset in that document should be read as
   applying to 2.1.2 only. The same goes for the voice-card region
   `0x1BAC0-0x1C600` (2.1.0), which is `0x1BB40-0x1C5C0` in 2.2.1.

6. **`docs/arch/xmos-deep.md` §9 item 7** lists "the rest of
   `/usr/share/xmosfw/`" — the two `gitinfo.json` files, `las_layout` and
   `VERSIOND` — as not yet read. This report closes that item; §§1–4 above
   supersede it.

No conflict was found with `docs/CORRECTIONS-2026-09-08.md`. Its §1 (the i.MX6
is the USB host, `ethext` is a second `cdc_ether` function on the XMOS link,
the serial `A41163B0FFFE` in the bit-reversed controller image) is
independently reconfirmed here from the 1.8.2 image and from
`dmesg-before-reboot.txt`. **[READ]**
