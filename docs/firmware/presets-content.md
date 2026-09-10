# The factory preset library as 1.8.2 ships it

Static analysis only. **The instrument was not contacted** — no ssh, no OSC, no MIDI,
no network. Every claim below comes from files on local disk. No Moog binary was
executed; the ARM binaries were read with `strings`, `dd`, and
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`.

## Evidence grades

| grade | meaning |
|---|---|
| **[READ]** | read directly out of a named file at a named offset, or computed by a script over named files and reproducible from them |
| **[INFERRED]** | reasoning from [READ] facts; the reasoning is stated |
| **[UNKNOWN]** | not determined from the material available |

## Sources used

| path | what | size / hash |
|---|---|---|
| `captures/firmware-1.8.2/rootfs-1.8.2/usr/bin/las-frontend` | the 1.8.2 UI binary — **the only carrier of preset content in the whole rootfs** | 145,033,524 B, sha256 `7b2ea057388c91553b45e74fc2c3848e98811919ce52f53b34d1ee45d7d10bfe` |
| `captures/rootfs-1.5.0/usr/bin/las-frontend` | the 1.5.0 UI binary, for the version diff | 145,070,812 B, sha256 `42670ca0c2b7dabfed4459d2c4a210b28e2ca023706a37998e706aa2025969c9` |
| `captures/arch-harvest/las-frontend` | harvested from the instrument | **byte-identical to the 1.5.0 rootfs copy** (same sha256) [READ] |
| `captures/firmware-1.8.2/corpus/Moog One v1.8.2/Past Preset Packs/**/*.m1p` | the six download packs from the 1.8.2 zip | 222 files, 32,615,778 B |
| `captures/firmware-1.8.2/Moog_One_v1.8.2.zip` | the distribution zip | 249 entries |
| `captures/MOOG ONE.db` | the owner's default user space, pulled from the instrument | 101,920,768 B, sha256 `68ebadaff3dd6bdd501f03a679fdb65ecc86a447af24706c8a8c2a0f4f921c78` |
| `captures/SINGULARITY VOL 1 - GEOSYNTHS.db` | a third-party user space | 26,103,808 B, sha256 `061092a5c161f391c6d455b055469cf5fd50109d7d587472bfcf6d1d7c9c5e46` |
| `captures/firmware-1.8.2/rootfs-1.8.2/etc/init.d/S43gui`, `etc/fstab` | where the library lands at runtime | — |
| `captures/firmware-1.8.2/Moog One Firmware Update v1.8.2.pdf` | Moog's own release notes | 40,847 B |

---

# 1. Headline

**The entire factory preset library ships compiled into `/usr/bin/las-frontend` as
plain ASCII `.m1p` text, and `las-frontend` writes all of it into a fresh SQLite
database the first time it starts.** There is no preset file anywhere in the root
filesystem. [READ]

* **580** complete `.m1p` bodies are embedded — 579 in one contiguous run plus a
  separate `INIT.m1p` JUCE resource. [READ]
* **186** complete effect-preset bodies are embedded alongside them. [READ]
* On a fresh database `las-frontend` inserts **all 579** presets and **all 186**
  effect presets, then writes a 64-entry Performance Set called `MOOG ONE`
  (8 banks × 8 presets) from a hard-coded name list. [READ — the loop bounds are in
  the disassembly, §5]
* The preset library is **bit-for-bit identical between 1.5.0 and 1.8.2**. 579 of the
  580 blobs have the same SHA-256 in both binaries. Only `INIT` changed. [READ]
* 197 of the 222 `.m1p` files in the download zip are **byte-for-byte identical**
  (including the trailing newline) to blobs inside the binary. The 25 that are not
  are the whole **Lisa Bella Donna pack**, which is *not* in the firmware at all. [READ]

---

# 2. Where the presets live

## 2.1 Not in the root filesystem

`find` over all 6,035 regular files of `rootfs-1.8.2` returns **zero** `*.m1p` files,
zero `*.db` files, and no `/var/las-frontend` directory. [READ]

`grep -rl --binary-files=text '/meta/name "'` over the whole rootfs returns exactly
one path: `usr/bin/las-frontend`. The same is true of `/fx/name "`. `las-sc` (the
engine) contains **zero** `/meta/name` occurrences. [READ]

## 2.2 The runtime data path is `/var/las-frontend`, on its own partition

```
etc/init.d/S43gui:16-21
        if [ ! -d "/var/las-frontend/" ]; then
          mkdir /var/las-frontend
        fi
        DISPLAY=:0 las-frontend  --usb-path=/media/thumbdrive --data-path=/var/las-frontend …
```
[READ]

```
etc/fstab:
/dev/mmcblk2p6  /var        ext4    defaults,noatime        0       1
```
[READ] — so the databases are on eMMC partition 6, a read-write ext4 volume separate
from the read-only rootfs (`/dev/mmcblk2p2`, `p3` appear as `/mnt/u1`, `/mnt/u2`, both
`ro,noauto`). This is why a firmware update does not disturb the library.

`las-frontend` refuses to run without a writable data path:
`ERROR: The data path '…' is not a writable directory.` and
`Quitting because no usable database could be opened.` [READ, `las-frontend` file
offsets 132,808,207 and 132,808,526 — VMA 0x07EB7E0F and 0x07EB7F4E]

## 2.3 The two database file names

Two database file names are compiled in, adjacent in `.rodata`: [READ, file offsets
132,808,390 and 132,808,411 — VMA 0x07EB7EC6 and 0x07EB7EDB]

```
MOOG ONE EXAMPLES.db
MOOG ONE.db
```

`MOOG ONE.db` is the default user space; the owner's capture has exactly that name.
[READ]

`las-frontend` accepts a `--example-data` switch [READ, file offset 132,807,484 —
VMA 0x07EB7B3C — in the same option-string block as `--data-path` and
`--cal-data-path`]. `S43gui:21` does
**not** pass it. [READ] That `--example-data` selects `MOOG ONE EXAMPLES.db` is
**[INFERRED]** from the adjacency of the two literals and the absence of any other
consumer of that file name; the pairing was not traced through the disassembly.

## 2.4 The USB side

`--usb-path=/media/thumbdrive` [READ, `S43gui:21`]. In the rootfs `/media` is a
symlink to `/var/local/media` [READ, rootfs symlink listing]; `etc/init.d/S14fs:27-30`
creates `/var/local/media` at boot. The UI reports `Looking for USB files in ` and
`Looking for firmware updates in `. [READ] So `.m1p` files only ever exist on the
instrument transiently, on a mounted FAT32 stick — never on eMMC. **[INFERRED]**

---

# 3. The `.m1p` format on the device versus in the download zip

## 3.1 They are the same bytes

For every one of the 197 presets that exists both as a `.m1p` file in
`Moog_One_v1.8.2.zip` and as an embedded blob in `las-frontend`, the file and the blob
are **exactly equal, byte for byte, including the trailing `\n`**. [READ — computed by
locating each blob between its NUL delimiters and comparing to the file; zero
differences, zero length differences]

Worked example: `Past Preset Packs/KING/ANSWERS FOR ASKING.m1p` is 158,578 bytes; the
blob at `las-frontend` file offset **10,834,042** is 158,578 bytes; `raw == blob` is
true. [READ]

Per-pack byte totals agree exactly with the embedded group totals:

| pack directory in the zip | files | bytes | embedded `/meta/group` | embedded bytes |
|---|---:|---:|---|---:|
| CLASSICS | 51 | 7,208,807 | `CLASSICS` (51) | 7,208,807 |
| KING | 26 | 5,247,111 | `KING` (26) | 5,247,111 |
| STEREO FUTURES | 45 | 6,844,138 | `STEREO FUTURES` (45) | 6,844,138 |
| TRANSFORMERS | 53 | 6,956,243 | `TRANSFORMERS` (53) | 6,956,243 |
| POLYPHONIC DESTINATIONS | 22 | 2,931,772 | `POLYPHONIC DESTINATIONS` (13) + `MOOG` (9) | 1,529,275 + 1,402,497 = 2,931,772 |
| LISA BELLA DONNA | 25 | 3,427,707 | **absent** | — |
[READ]

## 3.2 On the device the nine `/meta/` lines are stripped into columns

A `.m1p` file is 9 `/meta/…` lines followed by the `/p/…` body. In the database the
body goes into `presets.data` verbatim and the nine metadata fields are split out:

| `.m1p` line | database home |
|---|---|
| `/meta/name` | `presets.name` (UNIQUE) |
| `/meta/comment` | `presets.comment` |
| `/meta/type` | `preset_tags` → `tags` where `type='type'` |
| `/meta/category` | `preset_tags` → `tags` where `type='category'` |
| `/meta/mood` | `preset_tags` → `tags` where `type='mood'` |
| `/meta/group` | `preset_tags` → `tags` where `type='group'` |
| `/meta/synth1name` … `synth3name` | `presets.synth1Name` … `synth3Name` |
[READ — schema in §4.1 and the `SELECT … (SELECT name FROM tags, preset_tags WHERE tags.type = '…')` statements in `las-frontend`]

**Proof that `data` is the file minus the nine lines:** for every one of the 368
presets in `captures/MOOG ONE.db` that also exists as an embedded blob, deleting the
`/meta/` lines from the blob yields a line-for-line identical `data` column. Verified
on `1892 HORROR FILM` (3,425 body lines both sides, equal). [READ]

The writer side exists too: `las-frontend` carries the nine prefixes as separate
string constants in writer order —
`/meta/name "`, `/meta/comment "`, `/meta/type "`, `/meta/category "`, `/meta/mood "`,
`/meta/group "`, `/meta/synth1name "`, `/meta/synth2name "`, `/meta/synth3name "`
[READ, `las-frontend` file offsets 132,397,014 … 132,397,156, one NUL-terminated
string each, in that order] — so an export reconstructs the header from the columns rather than storing it.

**[INFERRED]** Therefore a preset exported back to USB should reproduce the original
`.m1p` byte for byte, because `data` is stored unmodified and the header is rebuilt in
the same order. This is the single most valuable thing to check on the instrument
(§10, item 1). It is **not** proven here, and in particular it is **[UNKNOWN]** whether
export re-serialises the body at the current `/p/version` — the evidence points the
other way (the 368 seeded rows in the owner's database are still `/p/version 6` after
seven years and many firmware updates [READ]), but that shows loading does not rewrite,
not that exporting does not.

## 3.3 Export/import file-type table

`las-frontend` holds an eight-entry table of export extensions at VMA `0x006C3B70`,
stride 8 bytes, first word = `const char*` extension: [READ]

```
0x6c3b70 .m1p   0x6c3b78 .m1s   0x6c3b80 .m1f   0x6c3b88 .m1x
0x6c3b90 .m1m   0x6c3b98 .m1c   0x6c3ba0 .m1g   0x6c3ba8 .m1u
```

`.m1p` is the preset extension [READ — it is literally the tail of the `INIT.m1p`
resource-name string at file offset 133,741,138, reused by the linker (the table entry
points at 133,741,142, four bytes in), and it is the
extension of all 222 files in the zip]. User spaces are exported as whole databases —
`*.db` is a separate literal in the same import/export string block. [READ]
The remaining seven extensions are **[UNKNOWN]** individually; the export panel's item
list in the same block reads `EXPORT PRESETS`, `SEQUENCES`, `PERFORMANCE SETS`,
`EFFECT PRESETS`, `GLOBAL SETTINGS`, `USER SPACES` [READ], and mapping those onto
`.m1s/.m1f/.m1x/.m1m/.m1c/.m1g/.m1u` by first letter is guesswork, so it is not done here.

## 3.4 Text properties worth recording

* Every one of the 222 zip files ends in `\n`; so does every one of the 580 embedded
  blobs. No CR anywhere. [READ]
* Two of the 222 files have a `/meta/name` that differs from the file name:
  `CLASSICS/HOW DOES IT FEEL.m1p` → `HOW DOES IT FEEL?` (the `?` is illegal in a
  FAT32 filename), and `TRANSFORMERS/FASCINATЕ.m1p` (Cyrillic Е, U+0415 in the file
  *name*) → `/meta/name "FASCINATЕ"` (JSON escape in the file *content*, so the
  file stays ASCII). [READ]
* Longest `/meta/comment` in the embedded library: `HUMAN BASS`, 900 characters. 205
  of the 580 have a non-empty comment. [READ]
* 239 of 580 have a non-empty `synth2name`, 150 a non-empty `synth3name`. [READ]

---

# 4. The preset database

## 4.1 Schema (11 tables)

Read out of `captures/MOOG ONE.db` with `sqlite3 .schema`, and independently present in
`las-frontend` as `CREATE TABLE IF NOT EXISTS …` literals. [READ]

| table | columns | notes |
|---|---|---|
| `global` | `key`, `data` | one row, `key='settings'`, `data` = the `/m/settings/*` tree as `.m1p`-style text |
| `presets` | `id`, `timestamp`, `name`, `comment`, `synth1Name`, `synth2Name`, `synth3Name`, `data` | `UNIQUE(name)`; indexes on the three synth-name columns |
| `tags` | `id`, `type`, `name` | `UNIQUE(type,name)`; `type` ∈ {`type`,`category`,`mood`,`group`} |
| `preset_tags` | `presetId`, `tagId` | `ON DELETE CASCADE` both sides |
| `effects_presets` | `id`, `timestamp`, `type`, `name`, `data` | `UNIQUE(type,name)` |
| `mod_matrix_presets` | `id`, `timestamp`, `name`, `comment`, `data` | |
| `sequence_presets` | `id`, `timestamp`, `name`, `comment`, `data` | |
| `midi_map_presets` | `id`, `timestamp`, `name`, `comment`, `data` | |
| `snapshots` | `id`, `timestamp`, `presetId`, `type`, `comment`, `data` | autosave; `type` 0 and 1 observed |
| `sets` | `setNumber`, `bankNumber`, `presetNumber`, `presetId` | `UNIQUE(...) ON CONFLICT REPLACE` |
| `set_descriptions` | `setNumber`, `ordinal`, `timestamp`, `name`, `comment` | |

`PRAGMA foreign_keys = ON;` is issued at open. [READ]

There is a migration path for older files: `Missing timestamp column in presets table,
attempting table migration…`, `Found old effect_presets table, migrating to new
format.` (note the singular `effect_presets` → plural `effects_presets`), with a
`DROP INDEX … ALTER TABLE presets RENAME TO old_presets …` script. [READ]

## 4.2 Banks and sets

`sets` is (set, bank, preset) → presetId. The panel has 8 BANK LEDs and 8 PRESET LEDs
[READ, factory-test script strings `"Is BANK 1 LED off?"` … `"Is BANK 8 LED off?"`,
`"Is PRESET 1 LED off?"` … `"Is PRESET 8 LED off?"`, and `"Bank 1"…"Bank 8"`,
`"Preset 1"…"Preset 8"`], so one set is 8 × 8 = 64 slots. The owner's database holds
exactly one set of 64; the Singularity user space holds two sets of 64. [READ]

## 4.3 The tag vocabulary the database is seeded with

`Populating with minimal data` is followed in `.rodata` by a run of tag names
[READ, `las-frontend` file offset 132,470,305 onward]:

* types (4): `LAYER`, `MULTI`, `SINGLE`, `SPLIT`
* categories, contiguous (13): `ARPEGGIO`, `ATMOSPHERIC`, `CINEMATIC`, `CLASSIC`,
  `EVOLVING`, `FX`, `LEADS`, `MODERN`, `ORGANS`, `PERCUSSION`, `PLUCKED`, `STRINGS`, `WINDS`
* moods, contiguous (31): `AGGRESSIVE`, `BLISSFUL`, `BRIGHT`, `CALM`, `CHAOTIC`,
  `CHILL`, `COMPLEX`, `COLD`, `COSMIC`, `DARK`, `DREAMY`, `EERIE`, `ENERGETIC`,
  `FUNKY`, `HAPPY`, `HARSH`, `HEAVY`, `HOPEFUL`, `INTENSE`, `MELLOW`, `MELANCHOLY`,
  `MYSTERIOUS`, `NOSTALGIC`, `PLAYFUL`, `SAD`, `SCARY`, `SMOOTH`, `SOMBER`, `STOKED`,
  `SUSPENSEFUL`, `WEIRD`
* then `MOOG ONE` — the set-description name.

The owner's database has **20** categories and **32** moods. The seven categories and
one mood missing from the contiguous run (`BASS`, `BRASS`, `KEYS`, `MONO`, `PAD`,
`SEQUENCE`, `VOCODER`; mood `ATMOSPHERIC`) are all words that occur elsewhere in the
binary, so **[INFERRED]** the linker merged those string constants and they are simply
not adjacent. 13 + 7 = 20 and 31 + 1 = 32 exactly. Group tags are not seeded; they
arrive from `/meta/group` (`INSERT OR IGNORE INTO tags (type, name) VALUES (?1, ?2)`
is present [READ]).

### Out-of-vocabulary tags in the shipped content — a real wart

Four tag values used by shipped presets are **not** in the seeded vocabulary: [READ]

| tag | value | used by | groups |
|---|---|---|---|
| category | `CHORD` | 7 presets | KING ×4, STEREO FUTURES, 1.0.4, TRANSFORMERS |
| category | `LUSH` | 14 presets | TRANSFORMERS ×6, STEREO FUTURES ×5, 1.0.4 ×2, KING |
| category | `ORGAN` (singular) | 1 preset — `SKIPPING STONES` | TRANSFORMERS |
| mood | `LIGHT` | 2 presets — `MINNEHAHA`, `ACRYLIC` | KING, STEREO FUTURES |

None of the 367-preset base `FACTORY` bank uses them, which is why the owner's
1.5.0-era database (base bank + one imported pack) has never seen them. [READ]
Whether the seeding/import path creates the missing tag row before linking it, or
silently drops the tag, is **[UNKNOWN]** from static reading — both
`INSERT OR IGNORE INTO tags` and
`INSERT INTO preset_tags (presetId, tagId) SELECT ?1, id FROM tags WHERE type=?2 AND name=?3`
exist, and the ordering was not traced. §10 item 4 tests it.

---

# 5. How the library gets into the database

## 5.1 The content is a generated table, not a JUCE resource

The JUCE `BinaryData` resource list contains exactly 20 names [READ, `las-frontend`
file offsets 133,741,000–133,741,320, each name twice — once as the file name, once as
the C identifier]: six factory-test `.js` scripts, eight fonts, `slotmachine.png`,
`INIT.m1p`, `adjectives.txt`, `nouns.txt`, `verbs.txt`. **`INIT.m1p` is the only
preset in that list.** (The three word lists feed the random preset-name generator.)

The other 579 presets are NUL-terminated C string literals in `.rodata`, reached
through a **579-entry pointer array in `.data` at VMA `0x08A6E3A8` … `0x08A6ECB0`**,
and the 186 effect presets through a **186-entry array immediately before it at
`0x08A6E0C0` … `0x08A6E3A4`**. Every entry resolves to the start of a blob; the two
arrays are contiguous and the preset array is in ascending address order. [READ]

Layout in the 1.8.2 binary [READ]:

| region | file offsets | bytes |
|---|---:|---:|
| `.rodata` | 10,703,584 – 144,118,786 | 133,415,202 |
| 186 effect-preset blobs | 10,743,555 – 10,834,040 | 90,115 (sum of blob lengths) |
| 579 preset blobs, contiguous | 10,834,042 – 132,386,090 | 121,548,570 (sum of blob lengths; span 121,552,048) |
| unit-test string region | from 132,386,090 (`BitPackedTests`, `SoundEngineBlockTests`, `PresetTests`) | — |
| `INIT.m1p` resource | 143,840,307, length 116,054 | 116,054 |

Total preset text **121,664,624 bytes = 83.9 % of the 145,033,524-byte binary.** [READ]

The blob run is *adjacent* to the unit-test strings, which invites the reading that it
is a test fixture. It is not: `PresetTests` uses its own tiny synthetic fixtures
(`Preset Name 1`, `/p/clk/rate 101`, `/p/part/t/1/p/e1/a 0.10` …) [READ, file offset
132,397,002 onward], and the real blobs are consumed by the database-populate routine
below.

## 5.2 The populate routine — the decisive evidence

Two log strings sit in `.rodata`: [READ]

* `Populating with minimal data` … `Done populating with minimal data` (file offset
  132,470,305, VMA 0x07E65621)
* `Populating with complete factory data` … `Done populating with complete factory data`
  (file offset 132,470,754, VMA 0x07E657E2)

Between them: the tag vocabulary (§4.3) and, after the second, **a list of exactly 64
preset names** (§6).

The 579-entry array's indexed accessor (entry at VMA `0x000F3D68`, guarded by
`movw r3, #0x242` / `cmp r0, r3` / `ldrls pc, [pc, r0, lsl #2]` — indices 0…578) has
**exactly one caller in the whole binary**, at VMA `0x002349E4`. [READ — exhaustive
scan of every `BL`/`B` in `.text`]

That caller is a loop: [READ, `llvm-objdump -d --triple=armv7-none-linux-gnueabihf`]

```
  2349b8: mov   r9, #0                       ; i = 0
  2349e0: mov   r0, r9
  2349e4: bl    0xf3d68                      ; preset_text[i]
  2349f0: bl    0xf6abc                      ; preset_len[i]
  234a00: bl    …                            ; build juce::String
  234a50: bl    0x22c5f4                     ; insert preset
  …
  2356fc: add   r9, r9, #1
  235724: movw  r3, #0x243                   ; 579
  235728: cmp   r9, r3
  23572c: bne   0x2349e0
  235730: bl    sync@plt
```

**The loop runs 579 times.** The effect-preset loop in the same function runs 186
times (`234628: cmp r4, #186` / `bne 0x234240`). [READ]

The same two bounds are in the 1.5.0 binary at VMA `0x00235194` (`movw r3, #0x243`)
and `0x0023409C` (`cmp r4, #186`). [READ]

**[INFERRED]** So a Moog One whose `/var/las-frontend/MOOG ONE.db` is missing or empty,
running 1.5.0 or 1.8.2, builds a library of 579 presets and 186 effect presets. The
inference is only that this path runs when the database is new; the *content* and the
*counts* are [READ].

## 5.3 The owner's instrument shows the seeding actually happened — with an older binary

`captures/MOOG ONE.db` contains **368 presets inserted in one burst** with timestamps
from `2000-01-01T00:00:36.610Z` to `2000-01-01T00:01:45.907Z` — 69 seconds, ~5.3
presets/second, at the epoch date an unset RTC produces. Ids 2…370, in ascending name
order (`1892 HORROR FILM` first, `ZEUS` last). [READ]

The set-description row is `setNumber 1, ordinal 1, 2000-01-01T00:00:24.560Z, name
"MOOG ONE"` — 12 seconds before the first preset, i.e. the minimal-data pass, then the
complete-factory pass. [READ]

That 368 is **not** today's 579. The differences: [READ]

* 366 of the 368 are in today's embedded library; the two that are not are
  `PD AMPEXAGON` and `ZEUS`.
* Two of today's `FACTORY` group are missing from it: `AMPEXAGON` and
  `HAUNTED ORGAN RECORD`.
* None of the KING / CLASSICS / STEREO FUTURES / TRANSFORMERS / POLYPHONIC
  DESTINATIONS / MOOG / `1.0.4` presets is present.

**[INFERRED]** The database was seeded once, by the firmware the instrument shipped
with (which contained ~368 presets, `PD AMPEXAGON` not yet renamed to `AMPEXAGON`,
`ZEUS` not yet dropped, `HAUNTED ORGAN RECORD` not yet added), and **no later firmware
re-seeds an existing database**. The packs Moog later released were added to the binary
but are only installed on a *new* user space — otherwise they have to be imported from
USB by hand.

**This is a user-visible consequence:** every Moog One that has been in service since
before the packs shipped is carrying 579 presets' worth of dead weight in `las-frontend`
of which its database only ever received the original bank. Making a **new user space**
on current firmware is (by §5.2) the way to get the full 579 without importing
anything — **[INFERRED]**, and §10 item 2 tests it.

---

# 6. The factory Performance Set

`Populating with complete factory data` is followed by 64 name literals, then
`populate factory `. Those 64 names are **exactly** the 64 rows of `sets` in
`captures/MOOG ONE.db`, in the same order, filling set 1, banks 1–8, presets 1–8.
[READ — list compared element-by-element, identical]

The same 64 names in the same order are in the 1.5.0 binary. [READ]

| bank | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| **1** | KEY LIME | AMBIOSIS | DRIFTING FOG | APPLIED MAGIC | GENTLE HARPOON | I AM A GOLDEN GOD | BELLPEGGIO | SPACE WAVES |
| **2** | FALLING FILTRATOS | FLOOTY | GHOST TOWN | COOL PIANO DUDE! | TIMEFRAMES | UNICORN DREAM | TRAVELER | PLECTAR |
| **3** | ATMOSFEARIC | DIODE DIVA | SOLINA BIG SWIRL | RHOMBITRUNCATED | LOW PH | SOLO CELLO | NYLON SYNTH | SERGIO |
| **4** | STEREO LEADBATH | POLYPOP | STEREO ELECTRIC KEYS | RUBBERBANDS | DUSTY UPRIGHT | BASS BASE | WESTERN CANYON | TRI SAW GRIND |
| **5** | THE ADVENT | ONENESS | WAVE TANGLE | DELICATE HARP | LONG HAIR | WORLD OF PLUCKY | MEREDITH'S WEAVING PAD | STEEL OIL DRUMS |
| **6** | YOU WERE PUT HERE TO PLAY BANJO | WHEEL TONES | MARIMBA-ISH | STRANGE KEYS | THAT ONE TIME | UR BRIGHTS | SEARING 78 | SOLAR SAILOR |
| **7** | FUTURELAND | WHIRLY | TRIANGULAR LOVE | STEEL STRINGZ | MELO D KICK | LUSH POLYBRASS | CASSETTE SAVES | OH BE BRASSY |
| **8** | SPARKLEHORSE | I BELIEVE | MEZZOPIANO | OUCH BOT | ANNIHILATION DRONE | UNCERTAINTY | JOVIAN MISSION | RALPH'S SOLILOQUY |

39 SINGLE and 25 MULTI; 62 carry `/meta/group "FACTORY"` and two — `WESTERN CANYON`
(bank 4/7) and `UR BRIGHTS` (bank 6/6) — carry an **empty** group string. [READ]

---

# 7. The library, group by group

`/meta/group` is the only in-file marker of which pack a preset belongs to. Over the
580 embedded blobs: [READ]

| `/meta/group` | n | bytes | `/p/version` | types | shipped as `.m1p`? |
|---|---:|---:|---|---|---|
| `FACTORY` | 367 | 90,251,860 | 6 ×367 | 285 SINGLE, 82 MULTI | no — firmware only |
| `TRANSFORMERS` | 53 | 6,956,243 | 14 ×53 | 43 SINGLE, 10 MULTI | yes, 53 |
| `CLASSICS` | 51 | 7,208,807 | 8 ×21, 10 ×30 | 27 SINGLE, 22 SPLIT, 1 LAYER, 1 MULTI | yes, 51 |
| `STEREO FUTURES` | 45 | 6,844,138 | 10 ×15, 11 ×1, 12 ×29 | 27 MULTI, 12 SINGLE, 4 LAYER, 2 SPLIT | yes, 45 |
| `KING` | 26 | 5,247,111 | 7 ×18, 8 ×8 | 19 SINGLE, 3 LAYER, 2 MULTI, 2 SPLIT | yes, 26 |
| `1.0.4` | 13 | 1,618,013 | 9 ×9, 10 ×4 | 7 SINGLE, 6 LAYER | **no** |
| `POLYPHONIC DESTINATIONS` | 13 | 1,529,275 | 14 ×13 | 12 SINGLE, 1 LAYER | yes, in the PD folder |
| `MOOG` | 9 | 1,402,497 | 14 ×9 | 4 SINGLE, 3 MULTI, 2 LAYER | yes, **also in the PD folder** |
| *(empty)* | 3 | 606,680 | 6 ×2, 14 ×1 | `UR BRIGHTS` (MULTI), `WESTERN CANYON` (SINGLE), `INIT` (SINGLE) | no |
| **total** | **580** | **121,664,624** | | | |

Notes:

* **`1.0.4` is a version number used as a group name.** Thirteen presets carry
  `/meta/group "1.0.4"` — `COLOUR WHEEL`, `CODE RED`, `CROWN`, `COPTER STRIKE`,
  `DIAMOND`, `GREY EXIT`, `HORIZON`, `MEDICINE`, `METROPOLITAN`, `PANTHER`,
  `SHARED TALE`, `SHADOWLAND`, `SWORDFISH`. Their `/p/version` (9 and 10) puts them
  after the base bank (6) and before Classics/Stereo Futures. They appear in **no**
  download pack. **[INFERRED]** these were added by the v1.0.4 firmware release
  (`Moog One Firmware Update v1.0.4.pdf`, dated 2019-04-15 in the zip) and the group
  name is simply the release that introduced them.
* **The `MOOG` group is the Polyphonic Destinations pack's other half.** The zip's
  `POLYPHONIC DESTINATIONS` folder holds 22 files: 13 with `/meta/group
  "POLYPHONIC DESTINATIONS"` and 9 with `/meta/group "MOOG"` — `APOCRYPHA`,
  `APOLLYON'S SUN`, `ARCADIA`, `CLOUDPATH`, `PROTO-COSMOS`, `SUN-ROAD`,
  `THE GREAT STREAM`, `THE PLANETS`, `TRANCEFER`. All nine are `/p/version 14` and all
  nine are byte-identical to their embedded twins. [READ]
* **`INIT` has an empty group and is not in the pointer array** — it is the
  `INIT.m1p` JUCE resource (§8).
* The `FACTORY` bank is 90.3 MB of the 121.7 MB, and every one of its 367 presets is
  still `/p/version 6` — the original 2018 serialisation, never regenerated. [READ]

---

# 8. What actually changed between 1.5.0 and 1.8.2

**579 of the 580 blobs are identical** — same SHA-256 in both binaries, same names, no
additions, no removals. The 186 effect presets are likewise identical, name for name,
type for type, byte for byte. [READ]

**Only `INIT` changed.**

| | 1.5.0 | 1.8.2 |
|---|---|---|
| length | 155,569 B | 116,054 B |
| `/p/version` | **6** | **14** |
| lines | 3,387 | 3,260 |
| distinct addresses | 3,386 | 3,259 |
[READ]

It got *smaller* because v14 uses a compact float formatter
(`0.00000000000000000000` → `0.0`), not because it lost content.

Structural changes [READ]:

* **Gone in 1.8.2** (399 addresses): `/p/part/t/{1,2,3}/p/c/{0…127}` — 384 legacy
  mod-matrix compiled-constant slots — plus per-timbre `in/midi/ch`, `in/midi/en`,
  `p/modmatrix/expressions`, `p/sus/mode`, `p/sus/src`.
* **New in 1.8.2** (272 addresses): `p/modmatrix/matrix_expression_slots`,
  `seq_expression_slots`, `modmatrix/vars/{var0…var3, cvout1…cvout4}`,
  `p/fx/types/stereoChorus/*` and `stereoFlanger/*` (36 each per timbre + 24 each on
  the two `las-fx` sends), `p/e{1,2,3}/{async,dsync,rsync}`, `p/l{1..4}/fsync`,
  `p/l{1..4}/knobs/r`, `p/arp/knobs/r`, `p/o{1,2,3}/hardsync`,
  `p/mix/ngate/gain`, `in/din0/note-enable`, `in/usb0/note-enable`,
  `cv_settings/cv_output/{1..4}/voice_rule`, `p/fa/mode`.

This is exactly the `expressions` → `matrix_expression_slots` migration recorded in
`docs/CORRECTIONS-2026-09-08.md` §4, visible here as a **default-patch** diff.

Only **42** addresses present in both changed value: [READ]

| address | 1.5.0 | 1.8.2 |
|---|---|---|
| `/p/version` | 6 | 14 |
| `/p/part/midi_io/midi_in_route` | `"a"` | `"p"` |
| `/p/part/midi_io/midi_out_route` | `"a"` | `"p"` |
| `/p/part/midi_io/midi_in_channel_synth{2,3}` | 1, 1 | 2, 3 |
| `/p/part/midi_io/midi_out_channel_{all,synth1,synth2,synth3}` | 0 | 1 |
| `/p/part/t/{2,3}/en` | `true` | `false` |
| `/p/part/t/{2,3}/in/{din0,usb0}/ch` | 1 | 2, 3 |
| `/p/part/t/N/in/midi_out/{din0,usb0}/en` | `false` | `true` |
| `/p/part/t/N/a/voice-limit-mode` | `"all"` | `"avail"` |
| `/p/part/t/N/a/unison/pitch-spread` | 0.0 | 0.04956130310893059 |
| `/p/part/t/N/p/o1/d` | 0.50017547607421875 | 0.5 |
| `/p/part/t/N/p/o{2,3}/d` | 0.0 | **0.5** |
| `/p/part/t/N/p/fx/ins/p/2`, `…/types/delay/2` | 0.033581964671611786 | 0.031245963647961617 |

The 1.8.2 release notes say, under v1.8.0: *"Improved INIT patch by setting all OSCs
TRI by default to 0% and SAW to have the fastest reset times."* [READ,
`Moog One Firmware Update v1.8.2.pdf`]. **[UNKNOWN]** — that change is not visible in
this diff: `/p/part/t/N/p/o{1,2,3}/tr` is `0.006000000052154064` in *both* resources.
The 1.5.0 `INIT.m1p` resource is stale (v6 while the running 1.5.0 already wrote v14 —
see §9.2), so the two resources bracket, but do not isolate, the v1.8.0 edit.

---

# 9. Factory space versus user space

## 9.1 User spaces are whole databases

The UI vocabulary is explicit [READ, `las-frontend` strings]:

```
USER SPACES              ACTIVE USER SPACE          SWITCH USER SPACE
EDIT USER SPACE          ENTER A NAME FOR THE NEW USER SPACE
ENTER A NEW NAME FOR THIS USER SPACE                DELETE THIS USERSPACE?
(THE NEW USER SPACE WILL AUTOMATICALLY BECOME ACTIVE)
LOADED USER SPACE        ALL DATA (USER SPACE)      USER SPACE NAME
PLEASE EXPORT AND DELETE ANY UNUSED USER SPACES
```

plus the C++ symbols `SaveUserSpacePanel`, `las::CreateNewUserSpaceProcessor`, and the
settings keys `ActiveUserSpace`, `settingsSaveUserSpace`, `userSpaceName`,
`userSpaceOnUse`. [READ]

A user space is one `*.db` file in `--data-path`; `*.db` is the import/export glob.
[READ] There is **no "factory" partition inside a database** — the only thing marking
factory content is the `group` tag. Factory presets are ordinary rows and are
deletable (`BrowsePresetsPanel::deleteFocusedPreset` exists, and the schema has no
protection). [READ, symbol names + schema]

`Restore factory default FX preset for ` is the one restore affordance in the strings.
[READ]

## 9.2 What the owner's `MOOG ONE.db` actually contains

398 presets, 58 tags, 1,578 preset-tag links, 169 effect presets, 31 snapshots, 64 set
rows, 1 set description, 0 mod-matrix / sequence / MIDI-map presets. [READ]

| when | n | what |
|---|---:|---|
| `2000-01-01` | 368 | the first-boot seeding (§5.3) |
| `2000-07-03` | 1 | `OBEY PAD` (id 207) — overwritten in place, still RTC-less |
| `2021-01-23` | 4 | `INIT` (id 1, overwritten), `MAIN MENU`, `CHANGEABLE PSEUDOSCIENCE`, `STARFOX ADRIFT` |
| `2022-05-29` | 25 | the Lisa Bella Donna pack, imported |
[READ]

`/p/version` distribution: 368 × v6, 1 × v8, 29 × v14. Group tags: `FACTORY` 367,
`HORIZONS` 25, 6 rows with no group tag. [READ]

Note **id 1 is `INIT` and its timestamp is 2021-01-23 with `/p/version 14`** — so the
INIT row was rewritten by a firmware that already serialised at v14, even though that
firmware's compiled `INIT.m1p` resource was still v6. The stored row matches neither
resource exactly (103 differing lines against the 1.8.2 resource, 2,250 against the
1.5.0 one). [READ] **[INFERRED]** the compiled `INIT.m1p` is a seed that the running
application re-serialises from its live parameter tree, which is why the resource
version lags the schema.

Global settings live as one text blob in `global`:
`/m/settings/active_preset_id 244`, `/m/settings/active_set 1`,
`/m/settings/active_set_bank 3`, `/m/settings/active_set_preset 4`,
`/m/settings/last_ui_version "2.0.8"`, `/m/settings/version 1`. [READ]

## 9.3 The Lisa Bella Donna pack is the only pack that is *not* in the firmware

All 25 files in `Past Preset Packs/LISA BELLA DONNA/` carry `/meta/group "HORIZONS"`
— not "LISA BELLA DONNA" — and all 25 are `/p/version 14`. None of the 25 names occurs
anywhere in the 1.8.2 or 1.5.0 binary. [READ]

```
80'S BALLAD GUITAR   A MOOD BEYOND        ASTRAL CLOUDPATH     ATAVACHRON
AUTOMATIC MAN        BEYOND THE STARGATES CONFLUENCE - SOLO FOR MOOG FACTORY FLOOR
COSMIC MESSENGER     FM BELLS OF EVENING SKIES...              GLASSWORKS
JUPITER WAVES        M O O G T O P I A    MIAMI GETAWAY        MOOG FM BASS SEQUENCE
MOOGMENTUM           MOONDAWN             NEXUS - 6            PHOTOSYNTHESIS
QUEEN OF PENTACLES   SLOWLY DEPARTING FILM SCORE               SOLAR SAILER
TRAPPER KEEPERS      VOYAGE TO ETERNITY   VOYAGE TRANSPORTER 2062
WAYS OF CHANGES
```
[READ]

The zip's file dates place them in **2022-05-22/23/24**, after the 1.5.0 binary
(2022-05-16). All the other packs are dated 2020-06-01 or 2020-06-15, except seven
Polyphonic Destinations files whose zip date is a bogus 2001-08-06. [READ, `unzip -l`]

**[INFERRED]** The Horizons/Lisa Bella Donna pack was released after 1.5.0 was cut and
was never folded into a firmware binary — it is download-and-import only. That makes it
the one pack a fresh user space will **not** contain.

## 9.4 A third-party user space, for contrast

`SINGULARITY VOL 1 - GEOSYNTHS.db` is 129 presets (126 × v10, 3 × v14), **zero** of
which appear in the factory library; 128 are tagged `group = GEOSYNTHS`. It carries
two full sets — `SINGULARITY VOL 1 - SET A` (2019-05-31) and `SET B` (2019-06-07),
64 slots each — 177 effect presets and 3 `mod_matrix_presets`. Its `tags` table still
contains the seeded `FACTORY` group name even though no preset uses it, which is what
you would expect if the space was created empty by the app and then filled by import.
[READ]

---

# 10. Validation plan (read-only commands for a human to run on the instrument)

None of these was run. They are ordered by how much they would settle.

1. **Does export round-trip a `.m1p` byte-for-byte?** (§3.2 is the only inference in
   this document that anything else depends on.) Export one preset that exists in the
   zip — e.g. `ANSWERS FOR ASKING` — to a USB stick from SETTINGS → export, then on the
   computer:
   ```
   shasum -a 256 "/Volumes/<stick>/…/ANSWERS FOR ASKING.m1p" \
     "captures/firmware-1.8.2/corpus/Moog One v1.8.2/Past Preset Packs/KING/ANSWERS FOR ASKING.m1p"
   ```
   Equal hashes confirm §3.2 and prove export does not re-serialise. (Export is a
   panel action, not a shell command — it writes to the stick and touches nothing else.)
2. **Does a new user space get all 579?** Create a new user space from the panel, then
   over ssh, **read only**:
   ```
   ls -l /var/las-frontend/
   sqlite3 -readonly "/var/las-frontend/<NEW NAME>.db" "select count(*) from presets;"
   sqlite3 -readonly "/var/las-frontend/<NEW NAME>.db" \
     "select t.name, count(*) from presets p join preset_tags pt on pt.presetId=p.id \
      join tags t on t.id=pt.tagId where t.type='group' group by t.name order by 2 desc;"
   ```
   Expected if §5.2 is right: 579 (or 580 with INIT), with groups
   FACTORY 367, TRANSFORMERS 53, CLASSICS 51, STEREO FUTURES 45, KING 26,
   POLYPHONIC DESTINATIONS 13, MOOG 9, `1.0.4` 13. Creating a user space is a write,
   but only to a new file; the queries are `-readonly`.
3. **Confirm the current library is only the old bank.**
   ```
   sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" "select count(*) from presets;"
   sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" "select count(*) from effects_presets;"
   sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
     "select min(timestamp), max(timestamp) from presets where timestamp like '2000-01-01%';"
   ```
   Expected: 398, 169, `2000-01-01T00:00:36.610Z` / `2000-01-01T00:01:45.907Z` — i.e.
   the capture on disk is current and nothing re-seeded during the 1.8.2 update.
4. **Do out-of-vocabulary tags survive seeding?** In the new user space from step 2:
   ```
   sqlite3 -readonly "/var/las-frontend/<NEW NAME>.db" \
     "select type, name from tags where name in ('CHORD','LUSH','ORGAN','LIGHT');"
   sqlite3 -readonly "/var/las-frontend/<NEW NAME>.db" \
     "select p.name from presets p where p.name in ('SKIPPING STONES','MINNEHAHA','ACRYLIC') \
      and not exists (select 1 from preset_tags pt join tags t on t.id=pt.tagId \
                      where pt.presetId=p.id and t.type='category');"
   ```
   Four rows in the first query = the tags are created on demand; an empty first query
   plus names in the second = the tags are silently dropped (§4.3).
5. **Confirm the data path and partition.**
   ```
   cat /proc/mounts | grep -E ' /var '
   df -h /var
   ls -l /var/las-frontend/
   ```
   Expected: `/dev/mmcblk2p6 /var ext4 rw,noatime`, and the `.db` files plus
   `las-frontend.log`.
6. **Confirm nothing preset-shaped is on the rootfs.**
   ```
   find / -xdev -name '*.m1p' 2>/dev/null
   ```
   Expected: no output (`-xdev` keeps it off `/var`).
7. **Confirm the running binary is the one analysed.**
   ```
   sha256sum /usr/bin/las-frontend
   cat /etc/version
   ```
   Expected on 1.8.2: `7b2ea057388c91553b45e74fc2c3848e98811919ce52f53b34d1ee45d7d10bfe`
   and `las-v1.8.2`. On the owner's current 1.5.0:
   `42670ca0c2b7dabfed4459d2c4a210b28e2ca023706a37998e706aa2025969c9` / `las-v1.5.0`.
8. **How long does a fresh seed take?** If step 2 is done, time it. The owner's
   database shows 368 inserts in 69 s; 579 + 186 at the same rate is ≈ 145 s. This is a
   plausible component of the "approximately 10 minutes" restart the 1.8.2 release
   notes warn about, and is worth a stopwatch.

---

# 11. Conflicts with existing documents

Reported, not fixed, per the brief.

1. **`docs/CORRECTIONS-2026-09-08.md` §8** lists "580 complete `.m1p` bodies are
   embedded in `las-frontend`, including the real factory `INIT_m1p`" as **[AGENT]**,
   not independently re-checked. It is now independently confirmed, in **both** the
   1.8.2 and the 1.5.0 binary, by a different method (NUL-delimited record extraction
   plus the `.data` pointer arrays plus the disassembled loop bounds). The row can be
   promoted. The same §8 row says the library "is stored again in a 101 MB SQLite DB" —
   that is imprecise: `MOOG ONE.db` holds **398** presets, a 368-preset subset of an
   older library plus 30 user rows, not the 580.

2. **`docs/arch/performance.md` §"856 distinct quoted `/name "…"` values … i.e. factory
   preset names"** — 856 counts all `/name "` occurrences, which includes the 186
   `/fx/name` blobs and the `/p/part/las-fx/N/name` and `/p/part/t/N/p/fx/ins/name`
   values *inside* presets. The distinct preset names are **580**, the distinct
   embedded effect-preset names **186**. Not a contradiction, but the sentence reads as
   if 856 were the preset count.

3. **`docs/arch/preset-format.md` §"Corpus actually used"** attributes the 580 embedded
   bodies to `captures/arch-harvest/las-frontend`, described as "the firmware-1.5.0 UI
   binary". That is correct — `arch-harvest/las-frontend` and
   `rootfs-1.5.0/usr/bin/las-frontend` have the same SHA-256 — but the document does
   not say the same 580 are in 1.8.2 unchanged, which is the more useful fact.

4. **`docs/arch/preset-format.md` §1.3** assigns `/p/version` 6/7/8/9 to formatter A
   (`%.20f`). The 1.8.2 `INIT` resource is `/p/version 14` and uses the compact
   formatter, while the 1.5.0 `INIT` at v6 uses `%.20f` — consistent, and this document
   adds `INIT` as a clean A-vs-C pair of the *same* patch, which is a better formatter
   test case than any two different presets.

5. **`docs/CORRECTIONS-2026-09-08.md` §9 ("Still open")** says only Lisa Bella Donna's
   25 presets set `cv_output/N/voice_rule`, and asks whether that is a firmware
   difference. This document supplies half the answer: `voice_rule` **is** in the 1.8.2
   `INIT` resource (`/p/part/cv_settings/cv_output/{1..4}/voice_rule`, four addresses)
   and **is not** in the 1.5.0 one. So it is a firmware difference — the address was
   added between 1.5.0 and 1.8.2 — and the instrument's namespace dump lacks it because
   the instrument is on 1.5.0. [READ]

6. **`docs/MOOG-ONE-INTERNALS.md:1735` and `docs/INTERNAL-DO-NOT-DISTRIBUTE.md:134`**
   give `/var/las-frontend/*.db` as "~280 MB". The two databases captured here total
   128.0 MB. The 280 MB figure is presumably a live `du` including more user spaces;
   worth re-checking, since §10 item 2 adds a database.

---

# 12. Unexplored

* **The gate on the populate path.** I proved the loops run 579 and 186 times and that
  the 579-entry table has exactly one caller. I did **not** trace the condition under
  which `populateWithCompleteFactoryData` is called (its one caller is at VMA
  `0x0022B4C0`), nor whether `--example-data` selects it, nor whether a
  partially-populated database is topped up or left alone.
* **`--example-data` / `MOOG ONE EXAMPLES.db`.** Adjacency only; the pairing is not
  proven and the file has never been seen.
* **The seven non-`.m1p` export extensions** (`.m1s .m1f .m1x .m1m .m1c .m1g .m1u`).
  Each is referenced once, from a table of `{const char* ext, juce::String* label}`
  pairs whose labels are runtime-initialised, so the mapping needs either a live
  export or dynamic analysis.
* **`snapshots.type`.** Values 0 and 1 occur (7 and 24 rows in `MOOG ONE.db`; 8 and 73
  in the Singularity space). Which is the autosave and which the manual snapshot is
  untraced. `DELETE FROM snapshots WHERE presetId = ?1 AND type = ?2` and
  `Error while deleting autosave snapshots for preset "` are the only clues.
* **Per-preset content.** I documented the *library* — names, packs, versions, sizes,
  provenance. I did not analyse what any individual preset does; `docs/arch/preset-format.md`,
  `expression-language.md` and `capability-survey.md` own that.
* **The 42 effect blobs that begin `/fx/mix` instead of `/version 5`.** 143 of the 186
  carry a `/version` line (5 ×98, 8 ×26, 9 ×16, 10 ×3) and 42 do not; whether the
  missing line means "version 0" or "pre-versioning" is untested. One blob's first line
  is binary garbage where a `/version` line should be, at file offset 10,809,xxx — it
  is a pointer into the middle of a blob and may just be my scanner's boundary
  heuristic; not chased.
* **The three word lists** (`adjectives.txt`, `nouns.txt`, `verbs.txt`, JUCE resources)
  that generate random preset names. Not extracted.
* **The base `FACTORY` bank's own provenance.** 367 presets, all `/p/version 6`, no
  designer attribution in the metadata. Whether Moog ever published them as `.m1p` is
  unknown; they are not in the 1.8.2 zip.
* **`MOOG ONE.db` history.** `PD AMPEXAGON` → `AMPEXAGON`, the removal of `ZEUS` and
  the addition of `HAUNTED ORGAN RECORD` are real between the shipping bank and today's
  embedded bank, but I have no intermediate firmware to date the change.

---

# Appendix A — all 580 embedded presets

Regenerable: for each occurrence of `/meta/name "` in
`rootfs-1.8.2/usr/bin/las-frontend` that begins immediately after a NUL byte, take the
bytes up to the next NUL; that is the `.m1p` body. 581 such records exist, one of which
(file offset 132,397,014, 12 bytes) is the printf-style fragment `/meta/name "` and is
discarded because it has no `/p/version` line. Groups are ordered oldest-first.

"in download zip" names the `Past Preset Packs/` folder the same preset appears in, or
`—` if it ships only inside the firmware.

### `/meta/group` = `FACTORY` — 367 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | 1892 HORROR FILM | SINGLE | KEYS | MELANCHOLY | 6 | 157,970 | — |
| 2 | A DESTINY | SINGLE | ATMOSPHERIC | HEAVY | 6 | 236,298 | — |
| 3 | ACCUMULATING SUBTLETIES IN STRINGS | SINGLE | STRINGS | HEAVY | 6 | 158,271 | — |
| 4 | ACHIEVING BLIP IN BRASS | SINGLE | BRASS | HAPPY | 6 | 206,813 | — |
| 5 | AIR PLUCK | MULTI | ARPEGGIO | ENERGETIC | 6 | 175,811 | — |
| 6 | ALEATORIC TRAVELS | SINGLE | EVOLVING | COSMIC | 6 | 170,984 | — |
| 7 | ALTERED ORGANISM | SINGLE | MODERN | COMPLEX | 6 | 532,532 | — |
| 8 | AMBIOSIS | SINGLE | CINEMATIC | COSMIC | 6 | 220,716 | — |
| 9 | AMPEXAGON | SINGLE | ATMOSPHERIC | COSMIC | 6 | 223,155 | — |
| 10 | ANALOG ELECTRIC PIANO | SINGLE | KEYS | INTENSE | 6 | 160,349 | — |
| 11 | ANALOG GLORY | SINGLE | ORGANS | ENERGETIC | 6 | 156,278 | — |
| 12 | ANALOOG | SINGLE | CLASSIC | MELLOW | 6 | 193,985 | — |
| 13 | ANNIHILATION DRONE | MULTI | EVOLVING | COMPLEX | 6 | 156,021 | — |
| 14 | ANOTHER BASS | SINGLE | BASS | HEAVY | 6 | 159,077 | — |
| 15 | APOLLO STRINGS | SINGLE | STRINGS | SMOOTH | 6 | 156,042 | — |
| 16 | APPLIED MAGIC | SINGLE | ATMOSPHERIC | PLAYFUL | 6 | 530,484 | — |
| 17 | ARCHITECTS OF TIME | MULTI | EVOLVING | COMPLEX | 6 | 156,930 | — |
| 18 | AROUND THE BEND | SINGLE | ORGANS | COMPLEX | 6 | 532,085 | — |
| 19 | ARP SOLUTION | SINGLE | ARPEGGIO | SUSPENSEFUL | 6 | 157,291 | — |
| 20 | ARPEGGIOLEO | SINGLE | ARPEGGIO | INTENSE | 6 | 194,821 | — |
| 21 | ARPEGINATOR | MULTI | ARPEGGIO | SMOOTH | 6 | 158,570 | — |
| 22 | ARRIVAL | SINGLE | FX | SUSPENSEFUL | 6 | 155,529 | — |
| 23 | ASTRAL DREAM FORCE | SINGLE | PAD | BRIGHT | 6 | 156,459 | — |
| 24 | ATMOSFEARIC | SINGLE | ATMOSPHERIC | DREAMY | 6 | 232,434 | — |
| 25 | BA$ICS | SINGLE | CLASSIC | FUNKY | 6 | 205,847 | — |
| 26 | BALLAD GUITAR | SINGLE | PLUCKED | DREAMY | 6 | 162,092 | — |
| 27 | BARITONE PLUCK | SINGLE | PLUCKED | MELLOW | 6 | 182,670 | — |
| 28 | BARKLEY | SINGLE | LEADS | AGGRESSIVE | 6 | 219,747 | — |
| 29 | BARMY WAVES | SINGLE | KEYS | INTENSE | 6 | 532,983 | — |
| 30 | BASS BASE | SINGLE | BASS | DARK | 6 | 158,166 | — |
| 31 | BELA HORIZON | SINGLE | PAD | DREAMY | 6 | 530,473 | — |
| 32 | BELLFLOOT | MULTI | CINEMATIC | HOPEFUL | 6 | 186,803 | — |
| 33 | BELLPEGGIO | MULTI | ARPEGGIO | BRIGHT | 6 | 208,305 | — |
| 34 | BIG CHORUS SYNTH PAD | SINGLE | PAD | HEAVY | 6 | 160,872 | — |
| 35 | BIG CLOUDY CUMULUS | SINGLE | PAD | COMPLEX | 6 | 233,386 | — |
| 36 | BIG DARK BASS | SINGLE | BASS | ENERGETIC | 6 | 158,595 | — |
| 37 | BIGBELL | SINGLE | PERCUSSION | EERIE | 6 | 182,584 | — |
| 38 | BLADES | MULTI | FX | EERIE | 6 | 186,908 | — |
| 39 | BLATHER | SINGLE | BRASS | HAPPY | 6 | 531,340 | — |
| 40 | BLUES FOR BOB | SINGLE | BRASS | NOSTALGIC | 6 | 532,134 | — |
| 41 | BOOM KICK | SINGLE | PERCUSSION | HEAVY | 6 | 168,574 | — |
| 42 | BOOM SLAP | SINGLE | LEADS | BRIGHT | 6 | 231,470 | — |
| 43 | BOWED BALLOON | SINGLE | CLASSIC | HAPPY | 6 | 530,171 | — |
| 44 | BOWED CYMBAL | SINGLE | FX | EERIE | 6 | 183,359 | — |
| 45 | BOWED ELECTRICITY | SINGLE | STRINGS | NOSTALGIC | 6 | 533,564 | — |
| 46 | BRASS PUNCH FLANGE | SINGLE | BRASS | BRIGHT | 6 | 159,216 | — |
| 47 | BRASS SUCKERPUNCH | SINGLE | BRASS | ENERGETIC | 6 | 173,529 | — |
| 48 | BREAD AND BUTTER | SINGLE | BRASS | MELLOW | 6 | 159,874 | — |
| 49 | BRIGHT ARPEGGIATOR | SINGLE | ARPEGGIO | BRIGHT | 6 | 159,428 | — |
| 50 | BRIGHT SIZE SQUARES | MULTI | LEADS | SMOOTH | 6 | 280,210 | — |
| 51 | BRIGHT UTILITY PAD | SINGLE | PAD | BRIGHT | 6 | 158,993 | — |
| 52 | BRONZE GARBAGE | SINGLE | BRASS | COSMIC | 6 | 182,917 | — |
| 53 | BRUISED AND BATTERED | SINGLE | MODERN | BRIGHT | 6 | 531,701 | — |
| 54 | BRUTAL BASS | SINGLE | BASS | AGGRESSIVE | 6 | 159,915 | — |
| 55 | BUTTERFLY SWARM | SINGLE | ATMOSPHERIC | COMPLEX | 6 | 531,401 | — |
| 56 | CALL AND RESPONSE LEAD | SINGLE | LEADS | BRIGHT | 6 | 170,823 | — |
| 57 | CALM ORCHESTRA | SINGLE | STRINGS | CALM | 6 | 537,174 | — |
| 58 | CASSETTE SAVES | MULTI | CLASSIC | NOSTALGIC | 6 | 306,874 | — |
| 59 | CELESTOID | SINGLE | PERCUSSION | WEIRD | 6 | 170,379 | — |
| 60 | CENTAURUS PAD | SINGLE | PAD | MELLOW | 6 | 156,895 | — |
| 61 | CHORALTHING | SINGLE | ATMOSPHERIC | DREAMY | 6 | 161,091 | — |
| 62 | CINEMA REVERSO | SINGLE | MODERN | MELANCHOLY | 6 | 159,023 | — |
| 63 | CINEMATIC FULLNESS | SINGLE | CINEMATIC | DARK | 6 | 157,766 | — |
| 64 | CLAV ANOTHER | SINGLE | KEYS | ENERGETIC | 6 | 157,926 | — |
| 65 | CLAVINOTT | SINGLE | KEYS | MELLOW | 6 | 532,132 | — |
| 66 | CLOCKWORK IMMERSIONS | SINGLE | KEYS | DARK | 6 | 170,013 | — |
| 67 | COLD STRINGS | SINGLE | STRINGS | COLD | 6 | 156,907 | — |
| 68 | CONTINUUM ARP | MULTI | EVOLVING | DREAMY | 6 | 156,819 | — |
| 69 | COOL PIANO DUDE! | SINGLE | KEYS | CHILL | 6 | 158,424 | — |
| 70 | COPPERPOT | SINGLE | PERCUSSION | CHILL | 6 | 158,193 | — |
| 71 | COSMIC TALE | SINGLE | PAD | MYSTERIOUS | 6 | 156,003 | — |
| 72 | CREEPY ORGAN | SINGLE | ORGANS | SUSPENSEFUL | 6 | 158,012 | — |
| 73 | CRYSTAL APPARITION | SINGLE | PAD | MYSTERIOUS | 6 | 531,649 | — |
| 74 | CRYSTAL FORMANT | SINGLE | CINEMATIC | SCARY | 6 | 206,273 | — |
| 75 | CYMBALON | SINGLE | PLUCKED | ENERGETIC | 6 | 531,267 | — |
| 76 | DARK BASS | SINGLE | BASS | DARK | 6 | 158,133 | — |
| 77 | DAYDREAMER | SINGLE | CLASSIC | EERIE | 6 | 530,380 | — |
| 78 | DEEP UNDERGROUND | SINGLE | FX | COSMIC | 6 | 530,824 | — |
| 79 | DELICATE HARP | SINGLE | PLUCKED | CALM | 6 | 159,455 | — |
| 80 | DIAMOND SPACES | MULTI | ARPEGGIO | DARK | 6 | 224,398 | — |
| 81 | DIFIGIANO BASS | SINGLE | BASS | AGGRESSIVE | 6 | 156,667 | — |
| 82 | DIODE DIVA | SINGLE | EVOLVING | COSMIC | 6 | 179,628 | — |
| 83 | DIRTYTUB | SINGLE | BASS | AGGRESSIVE | 6 | 230,762 | — |
| 84 | DOWN THE DRAIN | MULTI | FX | CHAOTIC | 6 | 185,637 | — |
| 85 | DRAGONFLYS | SINGLE | PLUCKED | CHILL | 6 | 169,696 | — |
| 86 | DREAM IN A DREAM | SINGLE | PAD | DREAMY | 6 | 254,735 | — |
| 87 | DRIFTING FOG | MULTI | STRINGS | CALM | 6 | 156,464 | — |
| 88 | DUAL FILTER BASS | SINGLE | BASS | MYSTERIOUS | 6 | 158,575 | — |
| 89 | DUAL FILTER VOWEL | SINGLE | KEYS | FUNKY | 6 | 530,959 | — |
| 90 | DUCKTINES | SINGLE | KEYS | FUNKY | 6 | 218,932 | — |
| 91 | DULL ELECTRIC PIANO BODY | SINGLE | KEYS | DARK | 6 | 158,578 | — |
| 92 | DUSTY UPRIGHT | SINGLE | STRINGS | DARK | 6 | 246,847 | — |
| 93 | DYNAMIC CLAV | SINGLE | KEYS | BRIGHT | 6 | 183,528 | — |
| 94 | DYNOROTOR | MULTI | CINEMATIC | EERIE | 6 | 911,774 | — |
| 95 | ELECTRIC WIZARD | SINGLE | LEADS | BRIGHT | 6 | 195,281 | — |
| 96 | ELECTRO TOM | SINGLE | PERCUSSION | NOSTALGIC | 6 | 156,905 | — |
| 97 | ELECTRONIC HARMONICA | SINGLE | WINDS | BRIGHT | 6 | 155,911 | — |
| 98 | ENCOM'S GAME | MULTI | EVOLVING | CHAOTIC | 6 | 156,778 | — |
| 99 | ENVOY | MULTI | ARPEGGIO | BRIGHT | 6 | 160,718 | — |
| 100 | EPULSOR | SINGLE | CINEMATIC | INTENSE | 6 | 220,130 | — |
| 101 | EQUAL LATERALS | SINGLE | MODERN | BRIGHT | 6 | 198,717 | — |
| 102 | ESSENTIAL PAD | SINGLE | PAD | DREAMY | 6 | 158,122 | — |
| 103 | EVOLUTION SWEEP | SINGLE | EVOLVING | DREAMY | 6 | 156,463 | — |
| 104 | FADING LIGHT | SINGLE | KEYS | DREAMY | 6 | 530,029 | — |
| 105 | FALLING FILTRATOS | SINGLE | CINEMATIC | DREAMY | 6 | 532,082 | — |
| 106 | FELT ARPEGGIATOR | SINGLE | ARPEGGIO | DREAMY | 6 | 156,861 | — |
| 107 | FIRM BASS | SINGLE | BASS | ENERGETIC | 6 | 158,562 | — |
| 108 | FLOOTY | SINGLE | WINDS | CALM | 6 | 159,878 | — |
| 109 | FOND MEMORIES | MULTI | CLASSIC | ENERGETIC | 6 | 161,626 | — |
| 110 | FOREVER AGO | SINGLE | LEADS | PLAYFUL | 6 | 218,407 | — |
| 111 | FORTHRIGHT BASS | SINGLE | BASS | NOSTALGIC | 6 | 158,092 | — |
| 112 | FRANK'S THEME | SINGLE | KEYS | COMPLEX | 6 | 157,947 | — |
| 113 | FREAKIN' ENORMOUS | SINGLE | LEADS | AGGRESSIVE | 6 | 169,111 | — |
| 114 | FRETFUL BASS | SINGLE | CLASSIC | DARK | 6 | 156,663 | — |
| 115 | FROM THE BEGINNING | MULTI | CLASSIC | WEIRD | 6 | 157,094 | — |
| 116 | FUNKY THING | SINGLE | KEYS | FUNKY | 6 | 218,507 | — |
| 117 | FUTURE BLUES | MULTI | CINEMATIC | EERIE | 6 | 158,583 | — |
| 118 | FUTURE SICK | MULTI | LEADS | HOPEFUL | 6 | 242,123 | — |
| 119 | FUTURELAND | MULTI | CINEMATIC | DREAMY | 6 | 180,431 | — |
| 120 | GAMELAN GONG | SINGLE | PERCUSSION | CALM | 6 | 532,240 | — |
| 121 | GAMELAN TAMTAM | SINGLE | PERCUSSION | COMPLEX | 6 | 531,098 | — |
| 122 | GATED SYNTH PAD | SINGLE | MODERN | CHILL | 6 | 159,968 | — |
| 123 | GAZERBEAM | MULTI | LEADS | INTENSE | 6 | 306,204 | — |
| 124 | GENTLE HARPOON | MULTI | PAD | CALM | 6 | 161,940 | — |
| 125 | GHOST STORY | MULTI | CINEMATIC | HOPEFUL | 6 | 158,118 | — |
| 126 | GHOST TOWN | SINGLE | BASS | HEAVY | 6 | 284,792 | — |
| 127 | GIDDYUP | MULTI | BASS | AGGRESSIVE | 6 | 183,777 | — |
| 128 | GLASSIAN | MULTI | ARPEGGIO | ENERGETIC | 6 | 186,607 | — |
| 129 | GLASSY | MULTI | CLASSIC | SOMBER | 6 | 155,993 | — |
| 130 | GODFREY HO LEAD | SINGLE | LEADS | NOSTALGIC | 6 | 158,184 | — |
| 131 | GOOEY PULSE PAD | SINGLE | PAD | COSMIC | 6 | 167,281 | — |
| 132 | HALCYON ANGLES | SINGLE | CLASSIC | CALM | 6 | 218,102 | — |
| 133 | HAP HAPPY | SINGLE | BASS | BRIGHT | 6 | 231,194 | — |
| 134 | HARMONICHORD | SINGLE | KEYS | INTENSE | 6 | 233,705 | — |
| 135 | HARPSIBLONK | SINGLE | KEYS | DREAMY | 6 | 209,539 | — |
| 136 | HAUNTED ORGAN RECORD | SINGLE | ORGANS | EERIE | 6 | 158,560 | — |
| 137 | HAWKINS SPLIT | MULTI | ARPEGGIO | INTENSE | 6 | 250,093 | — |
| 138 | HIGH STRINGS | SINGLE | STRINGS | INTENSE | 6 | 156,324 | — |
| 139 | HIGH VELOCITY FUNK | SINGLE | CLASSIC | FUNKY | 6 | 182,260 | — |
| 140 | HIGHPASSMADNESS | SINGLE | ARPEGGIO | BRIGHT | 6 | 156,830 | — |
| 141 | HIGHWAY ONE | SINGLE | KEYS | HOPEFUL | 6 | 158,152 | — |
| 142 | HOLDANDWASH | SINGLE | ATMOSPHERIC | WEIRD | 6 | 159,238 | — |
| 143 | HUMAN BASS | SINGLE | BASS | NOSTALGIC | 6 | 156,779 | — |
| 144 | I AM A GOLDEN GOD | MULTI | CINEMATIC | INTENSE | 6 | 160,662 | — |
| 145 | I BELIEVE | MULTI | ATMOSPHERIC | COSMIC | 6 | 282,331 | — |
| 146 | ICE CREAM BRASS | MULTI | BRASS | AGGRESSIVE | 6 | 282,242 | — |
| 147 | ICE PLUMBS | SINGLE | KEYS | COLD | 6 | 181,599 | — |
| 148 | IMPOSSIBLE TINES | SINGLE | CLASSIC | COSMIC | 6 | 169,609 | — |
| 149 | IN SEARCH OF | SINGLE | PAD | DREAMY | 6 | 530,499 | — |
| 150 | INHABITANT SEQUENCE | MULTI | CLASSIC | CHILL | 6 | 272,966 | — |
| 151 | INSTANT SUSPENSE | MULTI | ATMOSPHERIC | EERIE | 6 | 241,133 | — |
| 152 | ITALO BASS | SINGLE | BASS | NOSTALGIC | 6 | 156,659 | — |
| 153 | J. P. DOUBLE BUBBLE | SINGLE | KEYS | FUNKY | 6 | 530,500 | — |
| 154 | JOVIAN MISSION | MULTI | PAD | HEAVY | 6 | 155,558 | — |
| 155 | JOYTOWN | SINGLE | PAD | MELLOW | 6 | 533,024 | — |
| 156 | JUICYFRUIT | MULTI | MODERN | AGGRESSIVE | 6 | 244,269 | — |
| 157 | KALIMBALOID | SINGLE | PERCUSSION | MELANCHOLY | 6 | 169,943 | — |
| 158 | KEEP IT CLOSE | SINGLE | ATMOSPHERIC | COLD | 6 | 532,505 | — |
| 159 | KEY LIME | SINGLE | KEYS | SMOOTH | 6 | 207,376 | — |
| 160 | KNOCKOUT PUNCH | SINGLE | BRASS | AGGRESSIVE | 6 | 530,373 | — |
| 161 | LADDER BASS | SINGLE | BASS | NOSTALGIC | 6 | 155,455 | — |
| 162 | LASER CONTROLLED OSCILLATOR | SINGLE | ATMOSPHERIC | COMPLEX | 6 | 532,347 | — |
| 163 | LAST LIGHT | SINGLE | MODERN | BRIGHT | 6 | 232,583 | — |
| 164 | LAZER VIKING PLUCK | SINGLE | PLUCKED | DREAMY | 6 | 158,058 | — |
| 165 | LFOLISCIOUS | MULTI | MODERN | COMPLEX | 6 | 233,197 | — |
| 166 | LIGHT IT UP | SINGLE | MODERN | MELANCHOLY | 6 | 246,431 | — |
| 167 | LO PAN KEYS | SINGLE | KEYS | FUNKY | 6 | 169,963 | — |
| 168 | LONESOME SUNSET | SINGLE | PAD | CALM | 6 | 531,748 | — |
| 169 | LONG FILM PAD | SINGLE | CINEMATIC | DARK | 6 | 159,383 | — |
| 170 | LONG HAIR | SINGLE | MODERN | BRIGHT | 6 | 221,453 | — |
| 171 | LOOSE TETHERS | SINGLE | KEYS | AGGRESSIVE | 6 | 218,845 | — |
| 172 | LOW PH | SINGLE | LEADS | FUNKY | 6 | 156,895 | — |
| 173 | LUSH POLYBRASS | MULTI | BRASS | ENERGETIC | 6 | 246,393 | — |
| 174 | MADFROGS | SINGLE | ATMOSPHERIC | WEIRD | 6 | 185,183 | — |
| 175 | MAGIC COMPILER | MULTI | FX | HARSH | 6 | 238,155 | — |
| 176 | MAINROOM DUST | MULTI | MODERN | BRIGHT | 6 | 308,891 | — |
| 177 | MAJESTIQUE FM | MULTI | CINEMATIC | COLD | 6 | 207,110 | — |
| 178 | MARIMBA-ISH | MULTI | PERCUSSION | PLAYFUL | 6 | 156,899 | — |
| 179 | MARS LEAD | SINGLE | CLASSIC | NOSTALGIC | 6 | 156,724 | — |
| 180 | MEDITATE | MULTI | ATMOSPHERIC | BRIGHT | 6 | 161,481 | — |
| 181 | MEGA CITY 1 | MULTI | CINEMATIC | AGGRESSIVE | 6 | 195,710 | — |
| 182 | MEGALADON | MULTI | CINEMATIC | MYSTERIOUS | 6 | 229,447 | — |
| 183 | MELLO VIBRATO | SINGLE | PAD | EERIE | 6 | 156,279 | — |
| 184 | MELO D KICK | SINGLE | PERCUSSION | DARK | 6 | 158,653 | — |
| 185 | MERCIFUL SIDEBURNS | MULTI | BRASS | DARK | 6 | 157,713 | — |
| 186 | MERCURIAL STRINGS | SINGLE | STRINGS | COSMIC | 6 | 536,358 | — |
| 187 | MEREDITH'S WEAVING PAD | SINGLE | PAD | DARK | 6 | 160,404 | — |
| 188 | METAL RODS | SINGLE | PERCUSSION | AGGRESSIVE | 6 | 183,729 | — |
| 189 | MEZZOPIANO | SINGLE | KEYS | DARK | 6 | 218,100 | — |
| 190 | MICROTONAL BELL | SINGLE | PERCUSSION | COLD | 6 | 207,072 | — |
| 191 | MIGHTY BRASS | SINGLE | BRASS | HEAVY | 6 | 157,299 | — |
| 192 | MIX DRIVE HOLLOW | SINGLE | BASS | CHILL | 6 | 158,644 | — |
| 193 | MONOBOT VOCODER | SINGLE | VOCODER | WEIRD | 6 | 155,664 | — |
| 194 | MORPHEUS | SINGLE | KEYS | WEIRD | 6 | 159,413 | — |
| 195 | MULTISYNC | SINGLE | MODERN | BRIGHT | 6 | 157,752 | — |
| 196 | MYSTERIOUS BEAUTY | SINGLE | ATMOSPHERIC | COMPLEX | 6 | 531,750 | — |
| 197 | NARANJALOG | SINGLE | MODERN | ENERGETIC | 6 | 182,583 | — |
| 198 | NASEL COMP KEYS | SINGLE | CLASSIC | FUNKY | 6 | 156,855 | — |
| 199 | NEBULA ONE | MULTI | FX | COMPLEX | 6 | 163,268 | — |
| 200 | NEBULA SYMPHONY | MULTI | PAD | HEAVY | 6 | 155,565 | — |
| 201 | NERVOUS EUPHONIUM | SINGLE | CLASSIC | CHILL | 6 | 157,316 | — |
| 202 | NEXUS LEVEL 5 | SINGLE | ATMOSPHERIC | SCARY | 6 | 530,301 | — |
| 203 | NIGHT BIRDS | SINGLE | FX | COSMIC | 6 | 531,585 | — |
| 204 | NOISY PLUNK | MULTI | ARPEGGIO | HOPEFUL | 6 | 158,527 | — |
| 205 | NOT A VITAL ORGAN | SINGLE | ORGANS | BRIGHT | 6 | 159,061 | — |
| 206 | NOTCHBRASS | SINGLE | BRASS | HEAVY | 6 | 195,349 | — |
| 207 | NYLON SYNTH | SINGLE | KEYS | CALM | 6 | 160,838 | — |
| 208 | OBEY PAD | SINGLE | PAD | CHILL | 6 | 157,745 | — |
| 209 | OBLIGATORY LYLE LEAD | SINGLE | CLASSIC | HOPEFUL | 6 | 157,800 | — |
| 210 | ODDVOX | SINGLE | LEADS | NOSTALGIC | 6 | 158,161 | — |
| 211 | OFFWORLD SUNRISE | SINGLE | ATMOSPHERIC | HEAVY | 6 | 184,428 | — |
| 212 | OH BE BRASSY | SINGLE | CLASSIC | CALM | 6 | 155,979 | — |
| 213 | ONE 4 U | MULTI | PAD | COMPLEX | 6 | 156,844 | — |
| 214 | ONE AT ON(C)E | SINGLE | CLASSIC | DARK | 6 | 181,839 | — |
| 215 | ONENESS | MULTI | EVOLVING | COMPLEX | 6 | 285,250 | — |
| 216 | ORCHESTRAL SYNTH PAD | MULTI | STRINGS | COSMIC | 6 | 159,457 | — |
| 217 | ORGANO | SINGLE | ORGANS | BRIGHT | 6 | 219,872 | — |
| 218 | OUCH BOT | SINGLE | BASS | INTENSE | 6 | 184,716 | — |
| 219 | PAD IN 5THS | MULTI | PAD | CALM | 6 | 157,727 | — |
| 220 | PAD IN THE AIR | SINGLE | PAD | CALM | 6 | 157,295 | — |
| 221 | PARALLEL UNIVERSE | MULTI | ATMOSPHERIC | DARK | 6 | 158,132 | — |
| 222 | PASTEL BRASS | MULTI | BRASS | HAPPY | 6 | 306,387 | — |
| 223 | PIG SKINS | MULTI | PERCUSSION | COMPLEX | 6 | 230,387 | — |
| 224 | PINK MACHINE | SINGLE | LEADS | NOSTALGIC | 6 | 156,365 | — |
| 225 | PLAY4U | SINGLE | LEADS | COMPLEX | 6 | 369,397 | — |
| 226 | PLECTAR | SINGLE | KEYS | WEIRD | 6 | 197,483 | — |
| 227 | PLUCK SYNTH | SINGLE | KEYS | BRIGHT | 6 | 156,061 | — |
| 228 | POLARIZED ATMOSPHERE | SINGLE | PAD | DREAMY | 6 | 232,110 | — |
| 229 | POLY SPLITTER | SINGLE | ATMOSPHERIC | COSMIC | 6 | 531,621 | — |
| 230 | POLYPOP | MULTI | CINEMATIC | ENERGETIC | 6 | 158,191 | — |
| 231 | PULL THE WHEEL | SINGLE | ATMOSPHERIC | BRIGHT | 6 | 222,037 | — |
| 232 | PULSAR | SINGLE | ATMOSPHERIC | COSMIC | 6 | 159,843 | — |
| 233 | PULSATRONIX | MULTI | EVOLVING | CALM | 6 | 247,442 | — |
| 234 | PULSE VOCODER | SINGLE | VOCODER | WEIRD | 6 | 155,663 | — |
| 235 | PULSETRILL | SINGLE | ATMOSPHERIC | NOSTALGIC | 6 | 157,486 | — |
| 236 | RAIN BRASS | MULTI | BRASS | ENERGETIC | 6 | 156,884 | — |
| 237 | RAINY SILENCE | SINGLE | CLASSIC | MELANCHOLY | 6 | 156,909 | — |
| 238 | RALPH'S SOLILOQUY | SINGLE | ATMOSPHERIC | CHAOTIC | 6 | 169,983 | — |
| 239 | RAPID EYE MOVEMENT | SINGLE | ATMOSPHERIC | BRIGHT | 6 | 156,022 | — |
| 240 | RAZOR LEAD | SINGLE | MODERN | AGGRESSIVE | 6 | 160,285 | — |
| 241 | REFLECTED STARLIGHT | SINGLE | ATMOSPHERIC | CHILL | 6 | 195,372 | — |
| 242 | RELEASE DETUNE | SINGLE | ATMOSPHERIC | BRIGHT | 6 | 170,796 | — |
| 243 | RESONANT SPACE | SINGLE | ATMOSPHERIC | MELANCHOLY | 6 | 530,446 | — |
| 244 | RHOMBITRUNCATED | SINGLE | CINEMATIC | ENERGETIC | 6 | 245,944 | — |
| 245 | RIBBONS | SINGLE | CINEMATIC | MELANCHOLY | 6 | 299,769 | — |
| 246 | RIGHT PLACES | SINGLE | KEYS | HOPEFUL | 6 | 222,606 | — |
| 247 | RIPE TONE | SINGLE | CLASSIC | DARK | 6 | 205,858 | — |
| 248 | RISING PANIC | SINGLE | FX | WEIRD | 6 | 533,003 | — |
| 249 | RMI PIANO | SINGLE | KEYS | HOPEFUL | 6 | 173,508 | — |
| 250 | ROBOT MONSTER | SINGLE | LEADS | BRIGHT | 6 | 531,899 | — |
| 251 | ROOM FULL OF MIRRORS | SINGLE | PAD | DREAMY | 6 | 533,412 | — |
| 252 | ROTUND BASS | SINGLE | BASS | ENERGETIC | 6 | 156,853 | — |
| 253 | ROUND BASS | SINGLE | BASS | NOSTALGIC | 6 | 158,615 | — |
| 254 | RUBBER HARMONICS | SINGLE | KEYS | SMOOTH | 6 | 529,205 | — |
| 255 | RUBBERBANDS | SINGLE | PLUCKED | SOMBER | 6 | 158,884 | — |
| 256 | RUNNN | MULTI | CINEMATIC | COLD | 6 | 161,110 | — |
| 257 | RYEMAN | SINGLE | KEYS | CALM | 6 | 218,906 | — |
| 258 | S&H PAD | SINGLE | ARPEGGIO | HOPEFUL | 6 | 157,211 | — |
| 259 | S&H SWEEPER | MULTI | ATMOSPHERIC | CHAOTIC | 6 | 162,018 | — |
| 260 | SAW VOCODER | SINGLE | VOCODER | WEIRD | 6 | 155,657 | — |
| 261 | SAWNAUSAGE | SINGLE | LEADS | AGGRESSIVE | 6 | 196,813 | — |
| 262 | SEARING 78 | MULTI | LEADS | AGGRESSIVE | 6 | 281,416 | — |
| 263 | SECRET WEAPON | MULTI | LEADS | AGGRESSIVE | 6 | 156,442 | — |
| 264 | SEQUENCE OF EVENTS | SINGLE | EVOLVING | BRIGHT | 6 | 533,105 | — |
| 265 | SERGIO | MULTI | CINEMATIC | SUSPENSEFUL | 6 | 158,063 | — |
| 266 | SHIFTING IMAGES | SINGLE | ARPEGGIO | DREAMY | 6 | 532,214 | — |
| 267 | SHIMMERING IMAGE | SINGLE | KEYS | DARK | 6 | 530,967 | — |
| 268 | SHORE LEAVE PAD | SINGLE | PAD | COLD | 6 | 159,211 | — |
| 269 | SHORES OF EUROPA | SINGLE | WINDS | AGGRESSIVE | 6 | 378,095 | — |
| 270 | SHORT PLUCKED ARPEGGIATOR | SINGLE | ARPEGGIO | CHAOTIC | 6 | 159,916 | — |
| 271 | SIBILANT STRINGS | MULTI | STRINGS | ENERGETIC | 6 | 280,684 | — |
| 272 | SLEEVE ME ALONE | SINGLE | BASS | FUNKY | 6 | 157,027 | — |
| 273 | SLIGHT OMEGA | SINGLE | KEYS | COLD | 6 | 219,749 | — |
| 274 | SLOW AND LUSH | SINGLE | PAD | COLD | 6 | 158,157 | — |
| 275 | SLOW TWO TONE | MULTI | PAD | DARK | 6 | 164,587 | — |
| 276 | SMACKY TINES | SINGLE | PLUCKED | HAPPY | 6 | 183,120 | — |
| 277 | SOARING | SINGLE | LEADS | MYSTERIOUS | 6 | 531,684 | — |
| 278 | SOFT SYNTH BELL | SINGLE | ARPEGGIO | HOPEFUL | 6 | 158,161 | — |
| 279 | SOLAR SAILOR | MULTI | PAD | DARK | 6 | 155,070 | — |
| 280 | SOLINA BIG SWIRL | SINGLE | PAD | BRIGHT | 6 | 532,906 | — |
| 281 | SOLO CELLO | SINGLE | STRINGS | CALM | 6 | 162,893 | — |
| 282 | SONIC SCAN | SINGLE | PAD | COSMIC | 6 | 531,269 | — |
| 283 | SOUND WHIP | SINGLE | ARPEGGIO | AGGRESSIVE | 6 | 533,513 | — |
| 284 | SPACE CHUTZPAH | MULTI | BRASS | COMPLEX | 6 | 156,419 | — |
| 285 | SPACE KEYS | SINGLE | KEYS | CALM | 6 | 195,282 | — |
| 286 | SPACE ORGAN | MULTI | ORGANS | COLD | 6 | 155,562 | — |
| 287 | SPACE WAVES | SINGLE | ORGANS | COSMIC | 6 | 156,918 | — |
| 288 | SPACEBOT VOCODER | SINGLE | VOCODER | WEIRD | 6 | 155,673 | — |
| 289 | SPARKLEHORSE | SINGLE | PAD | COSMIC | 6 | 531,737 | — |
| 290 | SPONGY | SINGLE | CLASSIC | FUNKY | 6 | 197,424 | — |
| 291 | SPONTANEOUS DIRECTION | SINGLE | KEYS | COLD | 6 | 160,339 | — |
| 292 | SPRITES | SINGLE | ATMOSPHERIC | DREAMY | 6 | 531,275 | — |
| 293 | STEEL OIL DRUMS | SINGLE | PERCUSSION | BRIGHT | 6 | 158,174 | — |
| 294 | STEEL PIANO | SINGLE | KEYS | CALM | 6 | 159,835 | — |
| 295 | STEEL STRINGZ | SINGLE | STRINGS | DREAMY | 6 | 162,067 | — |
| 296 | STEREO ELECTRIC KEYS | MULTI | KEYS | DARK | 6 | 183,569 | — |
| 297 | STEREO LEADBATH | MULTI | EVOLVING | COMPLEX | 6 | 205,466 | — |
| 298 | STRANGE KEYS | SINGLE | KEYS | DARK | 6 | 206,293 | — |
| 299 | STRINGY PULSE PAD | SINGLE | STRINGS | COLD | 6 | 159,038 | — |
| 300 | STRINGY THINGEE | SINGLE | STRINGS | CHILL | 6 | 162,048 | — |
| 301 | STRONG BASS | SINGLE | BASS | AGGRESSIVE | 6 | 157,700 | — |
| 302 | SVF MONO LEAD | SINGLE | LEADS | BRIGHT | 6 | 159,438 | — |
| 303 | SWINDY FLUTE | SINGLE | LEADS | CALM | 6 | 158,109 | — |
| 304 | SWIRLING | SINGLE | KEYS | MELLOW | 6 | 157,691 | — |
| 305 | SWIRLING PAD | MULTI | PAD | BRIGHT | 6 | 160,742 | — |
| 306 | SWIRLY CLAV | SINGLE | KEYS | CALM | 6 | 206,608 | — |
| 307 | SYNCHOLE | SINGLE | PAD | DARK | 6 | 195,699 | — |
| 308 | SYNCNOTCH | SINGLE | MODERN | COSMIC | 6 | 158,606 | — |
| 309 | TALK FILTER | SINGLE | KEYS | FUNKY | 6 | 168,737 | — |
| 310 | TALKYPHONE | SINGLE | CLASSIC | FUNKY | 6 | 530,528 | — |
| 311 | TELEKOMPADRE | SINGLE | STRINGS | BRIGHT | 6 | 231,142 | — |
| 312 | THAT ONE TIME | SINGLE | BRASS | CALM | 6 | 209,400 | — |
| 313 | THE ADVENT | MULTI | ATMOSPHERIC | CHILL | 6 | 382,094 | — |
| 314 | THE ARPEST | SINGLE | ARPEGGIO | CHAOTIC | 6 | 911,854 | — |
| 315 | THE DRONE ARMY | SINGLE | ATMOSPHERIC | DARK | 6 | 182,923 | — |
| 316 | THE EIGHTH WAVE | SINGLE | FX | COSMIC | 6 | 156,524 | — |
| 317 | THE LIVING VCO | SINGLE | PAD | HEAVY | 6 | 536,258 | — |
| 318 | THE MOONLIT PATHWAY | SINGLE | KEYS | DARK | 6 | 170,570 | — |
| 319 | THE THRESHOLD OF COMPASSION | SINGLE | EVOLVING | COSMIC | 6 | 532,255 | — |
| 320 | THREE SQUARES A DAY | SINGLE | LEADS | NOSTALGIC | 6 | 173,076 | — |
| 321 | THRU ZERO | SINGLE | ATMOSPHERIC | MELLOW | 6 | 531,799 | — |
| 322 | TIGHT BRASS BLAST | SINGLE | BRASS | AGGRESSIVE | 6 | 532,221 | — |
| 323 | TIMEFRAMES | MULTI | ARPEGGIO | ENERGETIC | 6 | 216,045 | — |
| 324 | TIN TINES | SINGLE | KEYS | HOPEFUL | 6 | 158,139 | — |
| 325 | TIRED PONY | MULTI | STRINGS | AGGRESSIVE | 6 | 238,158 | — |
| 326 | TK-421 | MULTI | EVOLVING | HOPEFUL | 6 | 162,993 | — |
| 327 | TOBOR RADAR ROBOT | SINGLE | ATMOSPHERIC | EERIE | 6 | 530,471 | — |
| 328 | TOMITA WHISTLE | SINGLE | LEADS | CALM | 6 | 155,749 | — |
| 329 | TOMS | SINGLE | PERCUSSION | ENERGETIC | 6 | 156,021 | — |
| 330 | TONTO AND I | MULTI | CLASSIC | NOSTALGIC | 6 | 291,561 | — |
| 331 | TRANQUILITY CHIME | SINGLE | PERCUSSION | CALM | 6 | 158,595 | — |
| 332 | TRANSMIT AND RECEIVE | SINGLE | EVOLVING | AGGRESSIVE | 6 | 533,305 | — |
| 333 | TRANSWARP ARRIVAL | SINGLE | PAD | BRIGHT | 6 | 532,157 | — |
| 334 | TRAVELER | MULTI | ARPEGGIO | EERIE | 6 | 161,046 | — |
| 335 | TRI SAW GRIND | SINGLE | LEADS | AGGRESSIVE | 6 | 156,689 | — |
| 336 | TRIANGLE OCTAVE KEYS | SINGLE | KEYS | DREAMY | 6 | 155,000 | — |
| 337 | TRIANGULAR LOVE | SINGLE | ATMOSPHERIC | DREAMY | 6 | 533,093 | — |
| 338 | TRIPLE UNISAW ARP | SINGLE | ARPEGGIO | AGGRESSIVE | 6 | 169,475 | — |
| 339 | TUBBY BASS | SINGLE | BASS | AGGRESSIVE | 6 | 158,132 | — |
| 340 | UNCERTAINTY | SINGLE | FX | WEIRD | 6 | 158,915 | — |
| 341 | UNIBOT VOCODER | SINGLE | VOCODER | WEIRD | 6 | 155,668 | — |
| 342 | UNICORN DREAM | MULTI | CLASSIC | COMPLEX | 6 | 160,213 | — |
| 343 | VANILLA PAD | SINGLE | PAD | DREAMY | 6 | 161,644 | — |
| 344 | VCOS BREATHING | SINGLE | STRINGS | DREAMY | 6 | 536,777 | — |
| 345 | VELVET BRASS SECTION | SINGLE | BRASS | AGGRESSIVE | 6 | 531,356 | — |
| 346 | VELVET MARIMBA | SINGLE | PLUCKED | BLISSFUL | 6 | 533,498 | — |
| 347 | VERY BASS | SINGLE | BASS | AGGRESSIVE | 6 | 158,958 | — |
| 348 | VIBE KEYS | SINGLE | KEYS | NOSTALGIC | 6 | 219,838 | — |
| 349 | VIRGIL'S DREAM | SINGLE | ORGANS | CALM | 6 | 158,586 | — |
| 350 | WARPING | SINGLE | KEYS | DREAMY | 6 | 181,821 | — |
| 351 | WATER ON MARS | MULTI | ATMOSPHERIC | COLD | 6 | 157,764 | — |
| 352 | WAVE ANGLE BASS | SINGLE | BASS | NOSTALGIC | 6 | 157,337 | — |
| 353 | WAVE TANGLE | SINGLE | PAD | DARK | 6 | 159,803 | — |
| 354 | WEBB'S CAR | SINGLE | CLASSIC | NOSTALGIC | 6 | 157,585 | — |
| 355 | WHALE BEAR'S DESCENT | SINGLE | KEYS | WEIRD | 6 | 170,371 | — |
| 356 | WHEEL MORPH PAD | SINGLE | PAD | CALM | 6 | 157,322 | — |
| 357 | WHEEL TONES | SINGLE | ORGANS | CALM | 6 | 157,820 | — |
| 358 | WHIRLY | SINGLE | KEYS | MELLOW | 6 | 209,915 | — |
| 359 | WHISPERPHONE | SINGLE | FX | COLD | 6 | 530,406 | — |
| 360 | WINDY FLUTE | SINGLE | WINDS | CALM | 6 | 158,107 | — |
| 361 | WINDY PATH | SINGLE | WINDS | DREAMY | 6 | 156,924 | — |
| 362 | WINTER'S SOLSTICE | SINGLE | KEYS | CALM | 6 | 171,749 | — |
| 363 | WOODEN DOLL | SINGLE | PLUCKED | PLAYFUL | 6 | 183,112 | — |
| 364 | WORLD OF PLUCKY | MULTI | ARPEGGIO | DREAMY | 6 | 234,072 | — |
| 365 | YOKOTO | SINGLE | PLUCKED | DREAMY | 6 | 231,210 | — |
| 366 | YOU WERE PUT HERE TO PLAY BANJO | MULTI | ARPEGGIO |  | 6 | 163,166 | — |
| 367 | ZAPPY POLY | MULTI | BRASS | HAPPY | 6 | 156,843 | — |

### `/meta/group` = `1.0.4` — 13 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | CODE RED | SINGLE | CLASSIC | FUNKY | 10 | 121,450 | — |
| 2 | COLOUR WHEEL | SINGLE | LUSH | DREAMY | 10 | 125,174 | — |
| 3 | COPTER STRIKE | SINGLE | FX | WEIRD | 9 | 119,121 | — |
| 4 | CROWN | SINGLE | LUSH | DREAMY | 9 | 121,111 | — |
| 5 | DIAMOND | SINGLE | PLUCKED | CALM | 9 | 120,519 | — |
| 6 | GREY EXIT | SINGLE | PAD | MELANCHOLY | 9 | 132,648 | — |
| 7 | HORIZON | SINGLE | CINEMATIC | ATMOSPHERIC | 9 | 120,509 | — |
| 8 | MEDICINE | LAYER | KEYS | DREAMY | 9 | 121,422 | — |
| 9 | METROPOLITAN | LAYER | CHORD | MELANCHOLY | 9 | 120,935 | — |
| 10 | PANTHER | LAYER | LEADS | AGGRESSIVE | 9 | 121,907 | — |
| 11 | SHADOWLAND | LAYER | ARPEGGIO | MYSTERIOUS | 10 | 125,187 | — |
| 12 | SHARED TALE | LAYER | STRINGS | MELANCHOLY | 10 | 136,323 | — |
| 13 | SWORDFISH | LAYER | CLASSIC | COMPLEX | 9 | 131,707 | — |

### `/meta/group` = `KING` — 26 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | AEROBICS | MULTI | PERCUSSION | FUNKY | 7 | 208,214 | KING |
| 2 | ANSWERS FOR ASKING | SINGLE | PAD | CHILL | 8 | 158,578 | KING |
| 3 | BEAMING | SINGLE | LEADS | BRIGHT | 8 | 158,826 | KING |
| 4 | BLENDED BELLS | SINGLE | KEYS | DREAMY | 8 | 245,050 | KING |
| 5 | BLURRY HURRY | SINGLE | KEYS | CHILL | 8 | 234,411 | KING |
| 6 | CLEANER PIPES | SINGLE | PAD | CALM | 7 | 258,239 | KING |
| 7 | CLOUD 13 | LAYER | CHORD | CALM | 7 | 162,530 | KING |
| 8 | CRUISE CONTROL | SINGLE | KEYS | FUNKY | 7 | 163,871 | KING |
| 9 | DAYDREAMING | SINGLE | LEADS | MELANCHOLY | 7 | 172,638 | KING |
| 10 | EARTHWORM SLIM | SINGLE | ATMOSPHERIC | SOMBER | 7 | 171,881 | KING |
| 11 | ELECTRIC GLIDE | SINGLE | LEADS | DREAMY | 7 | 196,289 | KING |
| 12 | EP LIFT MOD FOR BRIGHTNESS | SINGLE | KEYS | MELLOW | 8 | 196,141 | KING |
| 13 | EUPHORICA | SINGLE | ARPEGGIO | SMOOTH | 7 | 160,357 | KING |
| 14 | FAIRY HAIR | MULTI | SEQUENCE | DREAMY | 7 | 190,065 | KING |
| 15 | INSIDE VOICES | LAYER | KEYS | HOPEFUL | 7 | 185,778 | KING |
| 16 | MINNEHAHA | SINGLE | KEYS | LIGHT | 7 | 159,965 | KING |
| 17 | NIGHTLY NEWS | SINGLE | CHORD | CHILL | 7 | 195,879 | KING |
| 18 | NOKOMIS | SINGLE | CHORD | INTENSE | 7 | 182,466 | KING |
| 19 | OPEN DOORS | LAYER | KEYS | PLAYFUL | 8 | 164,521 | KING |
| 20 | ORGANIC GO | SINGLE | ORGANS | COMPLEX | 7 | 244,373 | KING |
| 21 | RACEWAY | SINGLE | CHORD | DARK | 7 | 160,062 | KING |
| 22 | SOMBER SONG | SINGLE | KEYS | MELANCHOLY | 8 | 244,622 | KING |
| 23 | TEXAS INSTRUMENT | SINGLE | LUSH | DREAMY | 7 | 160,517 | KING |
| 24 | THE WASH | SPLIT | ATMOSPHERIC | COMPLEX | 7 | 544,564 | KING |
| 25 | WATER WELL | SPLIT | ATMOSPHERIC | DREAMY | 7 | 166,419 | KING |
| 26 | WAVERING PEARL | SINGLE | PAD | MELLOW | 8 | 160,855 | KING |

### `/meta/group` = `CLASSICS` — 51 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | 330 STRINGS | SINGLE | STRINGS | NOSTALGIC | 10 | 120,336 | CLASSICS |
| 2 | ANALOG KIT | SPLIT | PERCUSSION | NOSTALGIC | 10 | 153,619 | CLASSICS |
| 3 | AXEL F | SPLIT | CLASSIC | NOSTALGIC | 8 | 194,557 | CLASSICS |
| 4 | BIG UNISON BASS X2 | SINGLE | BASS | FUNKY | 10 | 119,939 | CLASSICS |
| 5 | BREAK FREE | SPLIT | CLASSIC | NOSTALGIC | 8 | 170,656 | CLASSICS |
| 6 | CAN'T GET ENOUGH | SPLIT | CLASSIC | NOSTALGIC | 8 | 182,411 | CLASSICS |
| 7 | CARPENTER BASS | SINGLE | BASS | AGGRESSIVE | 10 | 118,806 | CLASSICS |
| 8 | CHAMBER STRINGS | SPLIT | CLASSIC | SOMBER | 10 | 131,805 | CLASSICS |
| 9 | COCKTAIL BAR | SPLIT | CLASSIC | NOSTALGIC | 8 | 171,820 | CLASSICS |
| 10 | DD  SAVES | SPLIT | CLASSIC | NOSTALGIC | 8 | 170,017 | CLASSICS |
| 11 | EQUINOX PAD | SINGLE | PAD | COLD | 10 | 120,305 | CLASSICS |
| 12 | FALKOR | SINGLE | CLASSIC | NOSTALGIC | 8 | 158,347 | CLASSICS |
| 13 | FILTER SWEEPS | LAYER | EVOLVING | BRIGHT | 10 | 122,021 | CLASSICS |
| 14 | FRIENDS DON'T LIE | SPLIT | MODERN | SUSPENSEFUL | 8 | 170,174 | CLASSICS |
| 15 | FUTURE OB PAD | SINGLE | PAD | DREAMY | 10 | 120,021 | CLASSICS |
| 16 | HERE IN MY ARMS | SPLIT | CLASSIC | NOSTALGIC | 8 | 171,467 | CLASSICS |
| 17 | HOW DOES IT FEEL? | SPLIT | CLASSIC | NOSTALGIC | 8 | 170,820 | CLASSICS |
| 18 | J6 POLY | SINGLE | KEYS | FUNKY | 10 | 120,680 | CLASSICS |
| 19 | JAM ON THE ONE | SPLIT | KEYS | MELLOW | 10 | 120,161 | CLASSICS |
| 20 | LAZER JARRE | SINGLE | LEADS | AGGRESSIVE | 10 | 118,813 | CLASSICS |
| 21 | MINIBASS | SINGLE | BASS | INTENSE | 10 | 118,863 | CLASSICS |
| 22 | MODERN DAY WARRIOR | SPLIT | LEADS | NOSTALGIC | 8 | 157,842 | CLASSICS |
| 23 | MR EMERSON | SINGLE | LEADS | NOSTALGIC | 10 | 119,590 | CLASSICS |
| 24 | NEO LA | SPLIT | CLASSIC | NOSTALGIC | 8 | 159,146 | CLASSICS |
| 25 | OB LINES | SINGLE | PAD | CALM | 10 | 118,854 | CLASSICS |
| 26 | OB PAD | SINGLE | PAD | SMOOTH | 10 | 120,413 | CLASSICS |
| 27 | OB STRINGPAD | SINGLE | STRINGS | BLISSFUL | 10 | 119,483 | CLASSICS |
| 28 | OB TO LADDER PAD | SINGLE | PAD | DREAMY | 10 | 118,945 | CLASSICS |
| 29 | ORGANIX | SINGLE | ORGANS | BRIGHT | 10 | 120,158 | CLASSICS |
| 30 | OVERTIME | SPLIT | CLASSIC | NOSTALGIC | 8 | 158,385 | CLASSICS |
| 31 | P5 PAD & KEYS | SINGLE | PAD | DARK | 10 | 120,823 | CLASSICS |
| 32 | PACK OF LEADS | MULTI | LEADS | FUNKY | 10 | 123,763 | CLASSICS |
| 33 | PADTASTIC | SINGLE | PAD | DARK | 10 | 121,256 | CLASSICS |
| 34 | PASS THE POLY | SINGLE | KEYS | DREAMY | 10 | 119,154 | CLASSICS |
| 35 | PIPE DREAM | SINGLE | LEADS | MELLOW | 10 | 118,772 | CLASSICS |
| 36 | REPLICAS | SPLIT | CLASSIC | NOSTALGIC | 8 | 185,349 | CLASSICS |
| 37 | ROY'S TEARS | SPLIT | CLASSIC | NOSTALGIC | 8 | 170,613 | CLASSICS |
| 38 | SEPARATE JOURNEY | SPLIT | CLASSIC | BRIGHT | 8 | 158,665 | CLASSICS |
| 39 | SHINING DIAMOND | SPLIT | CLASSIC | NOSTALGIC | 8 | 160,085 | CLASSICS |
| 40 | SQUARE JUPITER | SINGLE | KEYS | MELLOW | 10 | 119,526 | CLASSICS |
| 41 | STEEL GUITAR | SINGLE | PLUCKED | BRIGHT | 10 | 118,840 | CLASSICS |
| 42 | SUITCASE EP | SINGLE | KEYS | FUNKY | 10 | 119,758 | CLASSICS |
| 43 | SUPERSYNC | SINGLE | LEADS | AGGRESSIVE | 10 | 120,173 | CLASSICS |
| 44 | SWEEP OVER ME | SINGLE | EVOLVING | COSMIC | 10 | 119,918 | CLASSICS |
| 45 | SWEET DREAMS | SPLIT | CLASSIC | NOSTALGIC | 8 | 183,645 | CLASSICS |
| 46 | TAKE ONE ME | SPLIT | CLASSIC | NOSTALGIC | 8 | 183,259 | CLASSICS |
| 47 | TOM & BOB'S BRASS | SINGLE | BRASS | HEAVY | 10 | 119,412 | CLASSICS |
| 48 | VOIGHT KAMPFF | SINGLE | CLASSIC | NOSTALGIC | 8 | 158,271 | CLASSICS |
| 49 | VOX HUMANA | SINGLE | STRINGS | NOSTALGIC | 10 | 119,227 | CLASSICS |
| 50 | WAITING | SPLIT | CLASSIC | NOSTALGIC | 8 | 157,833 | CLASSICS |
| 51 | WRATH OF KHAN | SPLIT | CLASSIC | NOSTALGIC | 8 | 172,011 | CLASSICS |

### `/meta/group` = `STEREO FUTURES` — 45 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | ACRYLIC | MULTI | PAD | LIGHT | 12 | 126,074 | STEREO FUTURES |
| 2 | ADAPTATION | MULTI | CLASSIC | CHILL | 12 | 129,280 | STEREO FUTURES |
| 3 | ARCHITECT | LAYER | CINEMATIC | DARK | 12 | 164,745 | STEREO FUTURES |
| 4 | BLOOM | MULTI | CINEMATIC | INTENSE | 10 | 122,726 | STEREO FUTURES |
| 5 | CASUAL BUNGALOW | LAYER | KEYS | DREAMY | 10 | 122,156 | STEREO FUTURES |
| 6 | CELESTE | SINGLE | STRINGS | COMPLEX | 12 | 124,166 | STEREO FUTURES |
| 7 | CIVIC MAESTRO | SINGLE | LEADS | DARK | 12 | 152,348 | STEREO FUTURES |
| 8 | COOL INPUT | MULTI | CHORD | BRIGHT | 12 | 127,111 | STEREO FUTURES |
| 9 | CRABBY EQUIPMENT | SINGLE | SEQUENCE | MELANCHOLY | 10 | 145,754 | STEREO FUTURES |
| 10 | CRAYON | SINGLE | BRASS | CALM | 11 | 673,685 | STEREO FUTURES |
| 11 | DANCER | MULTI | LEADS | HOPEFUL | 12 | 128,558 | STEREO FUTURES |
| 12 | DATA ROLL | SINGLE | ARPEGGIO | COMPLEX | 12 | 124,295 | STEREO FUTURES |
| 13 | DRAWBRIDGE | MULTI | LUSH | DREAMY | 12 | 151,419 | STEREO FUTURES |
| 14 | ELEGANT PREMIER | MULTI | PLUCKED | PLAYFUL | 10 | 127,651 | STEREO FUTURES |
| 15 | ENCOURAGING TINKLE CONTROL | MULTI | KEYS | DREAMY | 12 | 504,013 | STEREO FUTURES |
| 16 | ESCAPE | SINGLE | WINDS | CALM | 10 | 120,497 | STEREO FUTURES |
| 17 | EXTERNAL DREAM | MULTI | LUSH | DREAMY | 12 | 127,525 | STEREO FUTURES |
| 18 | FANATIC | LAYER | CINEMATIC | EERIE | 10 | 127,603 | STEREO FUTURES |
| 19 | GLOSSY DROP | MULTI | CLASSIC | DREAMY | 12 | 129,207 | STEREO FUTURES |
| 20 | GOOD SMUGGLING PILOT | MULTI | LEADS | ENERGETIC | 12 | 130,180 | STEREO FUTURES |
| 21 | GRAND SWELL | SPLIT | ARPEGGIO | DREAMY | 12 | 131,274 | STEREO FUTURES |
| 22 | ITALIAN JAGUAR | SINGLE | MODERN | CALM | 10 | 120,907 | STEREO FUTURES |
| 23 | LIVING FORMS | SINGLE | PAD | DARK | 12 | 154,016 | STEREO FUTURES |
| 24 | LOW SHIVER | MULTI | CINEMATIC | EERIE | 10 | 123,131 | STEREO FUTURES |
| 25 | LUCKY VALLEY | MULTI | PAD | CHILL | 12 | 129,907 | STEREO FUTURES |
| 26 | MADLY SICK | MULTI | BASS | FUNKY | 12 | 150,175 | STEREO FUTURES |
| 27 | MARKSMAN | MULTI | LEADS | DREAMY | 12 | 131,775 | STEREO FUTURES |
| 28 | NET PLEASURE | MULTI | CLASSIC | FUNKY | 12 | 163,342 | STEREO FUTURES |
| 29 | NICETY FILM | MULTI | PAD | DREAMY | 12 | 127,444 | STEREO FUTURES |
| 30 | NOVEL CREME | MULTI | LUSH | HEAVY | 12 | 140,689 | STEREO FUTURES |
| 31 | OIL PAINTS | SINGLE | LUSH | DREAMY | 12 | 128,906 | STEREO FUTURES |
| 32 | POTENTIAL FUN | MULTI | ARPEGGIO | HAPPY | 12 | 143,495 | STEREO FUTURES |
| 33 | RENEWAL | MULTI | PAD | HOPEFUL | 12 | 128,812 | STEREO FUTURES |
| 34 | RIVER | MULTI | ARPEGGIO | DREAMY | 12 | 128,242 | STEREO FUTURES |
| 35 | ROMANTICA | MULTI | KEYS | DARK | 12 | 129,836 | STEREO FUTURES |
| 36 | ROUGH DRUG | MULTI | LEADS | FUNKY | 10 | 122,186 | STEREO FUTURES |
| 37 | SABLE | SINGLE | LEADS | HARSH | 12 | 127,364 | STEREO FUTURES |
| 38 | SCHOOLHOUSE | MULTI | BRASS | HEAVY | 10 | 122,888 | STEREO FUTURES |
| 39 | SKY BELONG | MULTI | KEYS | DARK | 10 | 123,133 | STEREO FUTURES |
| 40 | STORYBOARD | MULTI | ARPEGGIO | HAPPY | 12 | 132,454 | STEREO FUTURES |
| 41 | TRADITIONAL PLAYGROUND | MULTI | LUSH | DREAMY | 10 | 121,348 | STEREO FUTURES |
| 42 | TWILIGHT | LAYER | ATMOSPHERIC | CALM | 10 | 120,544 | STEREO FUTURES |
| 43 | TYRELL | SINGLE | CINEMATIC | HEAVY | 10 | 123,102 | STEREO FUTURES |
| 44 | VICTORIA | SPLIT | ARPEGGIO | DREAMY | 10 | 123,565 | STEREO FUTURES |
| 45 | WITCH | SINGLE | PAD | DARK | 12 | 136,610 | STEREO FUTURES |

### `/meta/group` = `POLYPHONIC DESTINATIONS` — 13 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | 1976 PHASER SOLO | SINGLE | CLASSIC | SMOOTH | 14 | 124,892 | POLYPHONIC DESTINATIONS |
| 2 | DEFLATING THE BIG TOP | SINGLE | ORGANS | EERIE | 14 | 114,541 | POLYPHONIC DESTINATIONS |
| 3 | EMERALD EYE | SINGLE | PAD | DREAMY | 14 | 114,210 | POLYPHONIC DESTINATIONS |
| 4 | ETHER | SINGLE | MODERN | BLISSFUL | 14 | 114,328 | POLYPHONIC DESTINATIONS |
| 5 | FM HARMONIES | SINGLE | MODERN | COMPLEX | 14 | 114,762 | POLYPHONIC DESTINATIONS |
| 6 | GENTLE SWAY | SINGLE | KEYS | DREAMY | 14 | 114,640 | POLYPHONIC DESTINATIONS |
| 7 | GLASS SLIPPER | SINGLE | PLUCKED | BLISSFUL | 14 | 114,701 | POLYPHONIC DESTINATIONS |
| 8 | MELLOW GOLD | LAYER | KEYS | DREAMY | 14 | 140,631 | POLYPHONIC DESTINATIONS |
| 9 | PHASES | SINGLE | PAD | COLD | 14 | 114,609 | POLYPHONIC DESTINATIONS |
| 10 | POLYMORPHIA | SINGLE | CINEMATIC | DREAMY | 14 | 118,521 | POLYPHONIC DESTINATIONS |
| 11 | SLIPPERY SLOPE | SINGLE | CINEMATIC | MYSTERIOUS | 14 | 114,289 | POLYPHONIC DESTINATIONS |
| 12 | SUPERSAW SWEEP | SINGLE | ATMOSPHERIC | DREAMY | 14 | 114,770 | POLYPHONIC DESTINATIONS |
| 13 | TAPE PLUCK | SINGLE | PLUCKED | CALM | 14 | 114,381 | POLYPHONIC DESTINATIONS |

### `/meta/group` = `MOOG` — 9 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | APOCRYPHA | SINGLE | CINEMATIC | MYSTERIOUS | 14 | 229,594 | POLYPHONIC DESTINATIONS |
| 2 | APOLLYON'S SUN | MULTI | CINEMATIC | DREAMY | 14 | 117,737 | POLYPHONIC DESTINATIONS |
| 3 | ARCADIA | SINGLE |  | STOKED | 14 | 137,897 | POLYPHONIC DESTINATIONS |
| 4 | CLOUDPATH | SINGLE | SEQUENCE | ATMOSPHERIC | 14 | 163,567 | POLYPHONIC DESTINATIONS |
| 5 | PROTO-COSMOS | MULTI | SEQUENCE | COSMIC | 14 | 129,132 | POLYPHONIC DESTINATIONS |
| 6 | SUN-ROAD | MULTI | CLASSIC | DREAMY | 14 | 142,051 | POLYPHONIC DESTINATIONS |
| 7 | THE GREAT STREAM | LAYER | PAD | DREAMY | 14 | 117,792 | POLYPHONIC DESTINATIONS |
| 8 | THE PLANETS | LAYER | PAD | COSMIC | 14 | 115,611 | POLYPHONIC DESTINATIONS |
| 9 | TRANCEFER | SINGLE | ATMOSPHERIC | COSMIC | 14 | 249,116 | POLYPHONIC DESTINATIONS |

### `/meta/group` = `TRANSFORMERS` — 53 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | 1980 VHS STRINGS | SINGLE | STRINGS | SUSPENSEFUL | 14 | 182,920 | TRANSFORMERS |
| 2 | ALCOVE | SINGLE | STRINGS | CALM | 14 | 116,991 | TRANSFORMERS |
| 3 | AUDIENCE | SINGLE | ORGANS | BRIGHT | 14 | 118,441 | TRANSFORMERS |
| 4 | BEHIND THE VEIL | SINGLE | LUSH | ATMOSPHERIC | 14 | 118,740 | TRANSFORMERS |
| 5 | BOTANY | SINGLE | KEYS | CHILL | 14 | 116,878 | TRANSFORMERS |
| 6 | CIRCULUS | SINGLE | CINEMATIC | COMPLEX | 14 | 117,918 | TRANSFORMERS |
| 7 | CLOCK SHADE | SINGLE | LUSH | COMPLEX | 14 | 120,222 | TRANSFORMERS |
| 8 | CLOUD COVER | SINGLE | PAD | BLISSFUL | 14 | 114,672 | TRANSFORMERS |
| 9 | DAWN PATROL | MULTI | SEQUENCE | EERIE | 14 | 161,416 | TRANSFORMERS |
| 10 | DEVILISH ENSEMBLE | SINGLE | BRASS | DREAMY | 14 | 117,873 | TRANSFORMERS |
| 11 | DISTANT VISTAS | SINGLE | PAD | BLISSFUL | 14 | 114,820 | TRANSFORMERS |
| 12 | DISTINCT HUE | MULTI | BRASS | ENERGETIC | 14 | 122,373 | TRANSFORMERS |
| 13 | ENORMOUS NETWORK | SINGLE | PERCUSSION | SUSPENSEFUL | 14 | 115,793 | TRANSFORMERS |
| 14 | FACEOFF | SINGLE | CLASSIC | BRIGHT | 14 | 114,989 | TRANSFORMERS |
| 15 | FADED | SINGLE | MODERN | COLD | 14 | 116,792 | TRANSFORMERS |
| 16 | FASCINAT\u0415 | SINGLE | EVOLVING | COMPLEX | 14 | 119,290 | TRANSFORMERS |
| 17 | FIERCE BLOSSOM | MULTI | ARPEGGIO | NOSTALGIC | 14 | 123,340 | TRANSFORMERS |
| 18 | FIGURE | SINGLE | STRINGS | CALM | 14 | 116,027 | TRANSFORMERS |
| 19 | FLOWER GARDEN | MULTI | ARPEGGIO | DREAMY | 14 | 177,137 | TRANSFORMERS |
| 20 | FUNKY MINIONS | SINGLE | PLUCKED | FUNKY | 14 | 116,384 | TRANSFORMERS |
| 21 | GAMMA-RAY | SINGLE | MODERN | COMPLEX | 14 | 118,576 | TRANSFORMERS |
| 22 | GEYSER | MULTI | CINEMATIC | SOMBER | 14 | 122,836 | TRANSFORMERS |
| 23 | GUSTY GHOST | SINGLE | KEYS | SAD | 14 | 118,663 | TRANSFORMERS |
| 24 | HYPERLIGHT | SINGLE | LUSH | DREAMY | 14 | 116,213 | TRANSFORMERS |
| 25 | IM DREAMING | SINGLE | STRINGS | INTENSE | 14 | 119,321 | TRANSFORMERS |
| 26 | JUICY SMOKE | SINGLE | EVOLVING | ENERGETIC | 14 | 124,394 | TRANSFORMERS |
| 27 | KAMIKAZE | SINGLE | MONO | HEAVY | 14 | 122,829 | TRANSFORMERS |
| 28 | LOOK AROUND YOU | MULTI | PAD | DREAMY | 14 | 141,482 | TRANSFORMERS |
| 29 | LOW SEGMENT | SINGLE | BASS | HEAVY | 14 | 122,091 | TRANSFORMERS |
| 30 | MAGIC | SINGLE | LUSH | DREAMY | 14 | 122,668 | TRANSFORMERS |
| 31 | MIDAS TOUCH | SINGLE | CLASSIC | BRIGHT | 14 | 114,994 | TRANSFORMERS |
| 32 | MOUNTAINS | SINGLE | PAD | CHILL | 14 | 129,708 | TRANSFORMERS |
| 33 | MUSICAL SON | SINGLE | STRINGS | SOMBER | 14 | 118,734 | TRANSFORMERS |
| 34 | MUSICAL SON (TUNED) | SINGLE | STRINGS | SOMBER | 14 | 118,726 | TRANSFORMERS |
| 35 | NIGHT PASSAGE | MULTI | PAD | DARK | 14 | 124,649 | TRANSFORMERS |
| 36 | NIGHT-MOOGS | MULTI | SEQUENCE | COSMIC | 14 | 148,952 | TRANSFORMERS |
| 37 | NIGHTCAP | SINGLE | CHORD | FUNKY | 14 | 116,452 | TRANSFORMERS |
| 38 | OMNI - RIDER | SINGLE | CINEMATIC | SUSPENSEFUL | 14 | 457,411 | TRANSFORMERS |
| 39 | PAINTED FACES | SINGLE | MODERN | MYSTERIOUS | 14 | 114,561 | TRANSFORMERS |
| 40 | PRESSURE SPREAD | SINGLE | KEYS | BRIGHT | 14 | 115,019 | TRANSFORMERS |
| 41 | SIDE TO SIDE | SINGLE | PAD | BLISSFUL | 14 | 116,378 | TRANSFORMERS |
| 42 | SKIPPING STONES | SINGLE | ORGAN | HAPPY | 14 | 115,073 | TRANSFORMERS |
| 43 | SPACE SOLO SYNTHESIZER | SINGLE | LEADS | COSMIC | 14 | 115,002 | TRANSFORMERS |
| 44 | SPHERICAL - SCIENCES | MULTI | ATMOSPHERIC | COSMIC | 14 | 152,464 | TRANSFORMERS |
| 45 | SPLENDID TOUCH | SINGLE | KEYS | DREAMY | 14 | 117,637 | TRANSFORMERS |
| 46 | STRANGER | SINGLE | CLASSIC | PLAYFUL | 14 | 120,346 | TRANSFORMERS |
| 47 | SUNROOM | SINGLE | PAD | DREAMY | 14 | 116,250 | TRANSFORMERS |
| 48 | SUNSTROKE | SINGLE | MODERN | BRIGHT | 14 | 116,974 | TRANSFORMERS |
| 49 | TAPE MUSIC CENTER | SINGLE | SEQUENCE | COMPLEX | 14 | 162,213 | TRANSFORMERS |
| 50 | TOKYO MOONRISE | SINGLE | LUSH | DREAMY | 14 | 115,056 | TRANSFORMERS |
| 51 | TRICK MIRROR | SINGLE | PLUCKED | MYSTERIOUS | 14 | 156,995 | TRANSFORMERS |
| 52 | VAST EDGE | MULTI | LUSH | MYSTERIOUS | 14 | 123,378 | TRANSFORMERS |
| 53 | VIBIN | SINGLE | KEYS | NOSTALGIC | 14 | 117,182 | TRANSFORMERS |

### `/meta/group` = `` — 3 presets

| # | name | type | category | mood | `/p/version` | bytes | in download zip |
|---:|---|---|---|---|---:|---:|---|
| 1 | INIT | SINGLE |  |  | 14 | 116,054 | — |
| 2 | UR BRIGHTS | MULTI | MODERN | HARSH | 6 | 334,667 | — |
| 3 | WESTERN CANYON | SINGLE | PLUCKED | BRIGHT | 6 | 155,959 | — |

# Appendix B — all 186 embedded effect presets

Same extraction, keyed on `/fx/name "` with a `/fx/type ` line present. 23 effect
types; each has one preset literally named `DEFAULT`.

| # | type | name | `/version` | bytes |
|---:|---|---|---:|---:|
| 1 | bbdDelay | ANCIENT BUCKETS | — | 581 |
| 2 | bbdDelay | COMB WARBLE | — | 577 |
| 3 | bbdDelay | DARK SPIRAL | 5 | 512 |
| 4 | bbdDelay | DEFAULT | 5 | 527 |
| 5 | bbdDelay | IMPOSSIBLE ELECTRONS | — | 586 |
| 6 | bbdDelay | QUICK NOISE | 5 | 512 |
| 7 | bitcrusher | BIT DISTORT | 5 | 514 |
| 8 | bitcrusher | CHAOS MACHINE | 5 | 516 |
| 9 | bitcrusher | DEFAULT | 5 | 529 |
| 10 | bitcrusher | LOW RES | 5 | 510 |
| 11 | bitcrusher | TOY PIANO | — | 577 |
| 12 | chorus | CRYSTAL CHORUS | — | 578 |
| 13 | chorus | DEFAULT | 5 | 525 |
| 14 | chorus | POSITIVE VIBRATO | — | 580 |
| 15 | chorus | READY FOR TAKEOFF CHORUS | 5 | 523 |
| 16 | chorus | SUBTLE CHORUS | 5 | 512 |
| 17 | delay | DEFAULT | 5 | 524 |
| 18 | delay | INFINITE MADNESS | — | 579 |
| 19 | delay | SLAP HAPPY | — | 573 |
| 20 | delay | SMALL ROOM | 5 | 508 |
| 21 | delay | TIME LOOP | 5 | 506 |
| 22 | dualChorus | BRIGHT DUAL CHORUS | 5 | 521 |
| 23 | dualChorus | DEFAULT | 5 | 529 |
| 24 | dualChorus | DUAL CHORUS SEA SICK | — | 588 |
| 25 | dualChorus | DUAL CHORUS SUBTLE | — | 586 |
| 26 | dualChorus | DUAL CHORUS VIBRATO | — | 587 |
| 27 | ensemble | DARK SPACE | — | 576 |
| 28 | ensemble | DEFAULT | 5 | 527 |
| 29 | ensemble | HUGE SWIRL | — | 576 |
| 30 | ensemble | LARGE VIBRATO | — | 579 |
| 31 | ensemble | NEGATIVE SPACE | — | 580 |
| 32 | ensemble | POSITIVE VIBES | — | 580 |
| 33 | ensemble | SUBTLE STRINGS | 5 | 515 |
| 34 | et_blackhole | AMEBLACKDRONE | 5 | 449 |
| 35 | et_blackhole | CENTAURUS | 5 | 445 |
| 36 | et_blackhole | CIGAROOS | 5 | 444 |
| 37 | et_blackhole | DARKMATTER | 5 | 446 |
| 38 | et_blackhole | DEFAULT | 5 | 462 |
| 39 | et_blackhole | DOGSTAR | 5 | 443 |
| 40 | et_blackhole | FISHHOLE | 5 | 444 |
| 41 | et_blackhole | HEY HONEY | 5 | 445 |
| 42 | et_blackhole | NEBULA | 5 | 442 |
| 43 | et_blackhole | NEUTRINO | 5 | 444 |
| 44 | et_blackhole | PULSAR | 5 | 442 |
| 45 | et_blackhole | STARCRATER | 5 | 446 |
| 46 | et_blackhole | TRAIN TRACKS | 5 | 448 |
| 47 | et_blackhole | TRASNFIGURED | 5 | 448 |
| 48 | et_blackhole | VORTEXTING | 5 | 446 |
| 49 | et_hall | 1985 DAMAGE | 5 | 442 |
| 50 | et_hall | AMEDEO-SLAP | 5 | 442 |
| 51 | et_hall | CARNEGIE HALL | 5 | 444 |
| 52 | et_hall | CAVE SPACE | 5 | 441 |
| 53 | et_hall | CORRIDORS | 5 | 440 |
| 54 | et_hall | DARK CAVE | 5 | 440 |
| 55 | et_hall | DEFAULT | 5 | 457 |
| 56 | et_hall | DELAYED PLATE | 5 | 444 |
| 57 | et_hall | DISH DELAY | 5 | 441 |
| 58 | et_hall | DOOM CHAMBER | 5 | 443 |
| 59 | et_hall | EARTH HALL | 5 | 441 |
| 60 | et_hall | HI FI | 5 | 436 |
| 61 | et_hall | KUBRIX | 5 | 437 |
| 62 | et_hall | PANOROMANCE | 5 | 442 |
| 63 | et_hall | PHANTOM VERB | 5 | 443 |
| 64 | et_hall | TORNADIAN | 5 | 440 |
| 65 | et_hall | VAPOR TRAIL | 5 | 442 |
| 66 | et_plate | CENTAURI | 5 | 440 |
| 67 | et_plate | DEFAULT | 5 | 458 |
| 68 | et_plate | DINNER PLATE | 5 | 444 |
| 69 | et_plate | GUITPLATE | 5 | 441 |
| 70 | et_plate | JUST CUZ | 5 | 440 |
| 71 | et_plate | OILDRUM | 5 | 439 |
| 72 | et_plate | PRESSURE | 5 | 440 |
| 73 | et_plate | SIFT PLATE | 5 | 442 |
| 74 | et_room | BOXY ROOM | 5 | 440 |
| 75 | et_room | CANISMAJOR | 5 | 441 |
| 76 | et_room | DEFAULT | 5 | 457 |
| 77 | et_room | GUITAR ROOM | 5 | 442 |
| 78 | et_room | LUX SPACE | 5 | 440 |
| 79 | et_room | PCM 60 ROOM | 5 | 442 |
| 80 | et_room | ROOM 667 | 5 | 439 |
| 81 | et_room | SHUTTER ROOM | 5 | 443 |
| 82 | et_shimmer | AMEDEO BASS SHIM | 5 | 450 |
| 83 | et_shimmer | DARK ANGELS | 5 | 445 |
| 84 | et_shimmer | DEFAULT | 5 | 460 |
| 85 | et_shimmer | DEMON CALL | 5 | 444 |
| 86 | et_shimmer | GUNSHOT SNARE | 5 | 447 |
| 87 | et_shimmer | HELLS GATE | 5 | 444 |
| 88 | et_shimmer | IRONWORX | 5 | 442 |
| 89 | et_shimmer | MOUNTAINS | 5 | 443 |
| 90 | et_shimmer | NEROS ASCENT | 5 | 446 |
| 91 | et_shimmer | QUASAR | 5 | 440 |
| 92 | et_shimmer | SIZE MATTERS | 5 | 446 |
| 93 | et_shimmer | SNEAKY VERB | 5 | 445 |
| 94 | et_shimmer | TOUCHED BY AN H9 | 5 | 450 |
| 95 | flanger | DEFAULT | 5 | 526 |
| 96 | flanger | FLANGER BASIC NEGATIVE | — | 587 |
| 97 | flanger | FLANGER BASIC POSITIVE | — | 587 |
| 98 | flanger | FLANGER DARK HUGE | — | 582 |
| 99 | flanger | FLANGER JET PLANE | — | 582 |
| 100 | flanger | FLANGER VIBRATO | — | 580 |
| 101 | phaser12stage | 12 LITTLE GREEN MEN | — | 590 |
| 102 | phaser12stage | DEFAULT | 10 | 342 |
| 103 | phaser12stage | HUGE FEEDBACK PHASER | 5 | 526 |
| 104 | phaser12stage | SLOW MOPRH | — | 581 |
| 105 | phaser12stage | SUBTLE 12 STAGE PHASER | — | 869 |
| 106 | phaser6stage | 6 LITTLE GREEN MEN | — | 588 |
| 107 | phaser6stage | DEFAULT | 10 | 357 |
| 108 | phaser6stage | FEEDBACK 6 STAGE | — | 586 |
| 109 | phaser6stage | SUBTLE 6 STAGE PHASER | 5 | 526 |
| 110 | phaser6stage | VIBRATO PHASE 6 STAGE | 5 | 526 |
| 111 | pingpongDelay | DARK ROOM PING PONG | — | 589 |
| 112 | pingpongDelay | DEFAULT | 5 | 532 |
| 113 | pingpongDelay | DIZZY LOOP | 5 | 515 |
| 114 | pingpongDelay | PING PONG SMALL ROOM | 5 | 526 |
| 115 | pingpongDelay | RHYTHMIC FEEDBACK | 5 | 522 |
| 116 | pingpongDelay | RINGING PING PONG | 5 | 523 |
| 117 | resonator | BAND PASS RES | — | 565 |
| 118 | resonator | DEFAULT | 10 | 324 |
| 119 | resonator | HIGH PASS RES | — | 565 |
| 120 | resonator | HIGH PASS RES MOD | — | 569 |
| 121 | resonator | LOW PASS RES | — | 564 |
| 122 | resonator | LOW PASS RES MOD | — | 568 |
| 123 | stereoChorus | ANIMATER | 9 | 375 |
| 124 | stereoChorus | BASIC | 8 | 452 |
| 125 | stereoChorus | CHROME | 9 | 354 |
| 126 | stereoChorus | DARK MOOD | 8 | 437 |
| 127 | stereoChorus | DEFAULT | 9 | 431 |
| 128 | stereoChorus | DEPHASED | 8 | 399 |
| 129 | stereoChorus | DETUNED | 8 | 416 |
| 130 | stereoChorus | DETUNED REFLECTIONS | 8 | 390 |
| 131 | stereoChorus | DRY CHORUS | 8 | 457 |
| 132 | stereoChorus | FUZZY | 8 | 451 |
| 133 | stereoChorus | LANDSCAPE | 9 | 336 |
| 134 | stereoChorus | RICH CHORUS | 8 | 439 |
| 135 | stereoChorus | SCRATCH THIS VINYL | 8 | 351 |
| 136 | stereoChorus | SLOW MOTION | 8 | 422 |
| 137 | stereoChorus | SPREADER | 8 | 455 |
| 138 | stereoChorus | SPRING CHORUS | 8 | 422 |
| 139 | stereoChorus | STINGER | 9 | 354 |
| 140 | stereoChorus | TABOO | 9 | 372 |
| 141 | stereoChorus | THUNDERBOLT | 9 | 347 |
| 142 | stereoChorus | WAH CHORUS | 8 | 344 |
| 143 | stereoChorus | WANDERER | 9 | 375 |
| 144 | stereoChorus | WIDENER | 8 | 434 |
| 145 | stereoChorus | WOOZY | 9 | 334 |
| 146 | stereoDelay | DARK HALL | — | 578 |
| 147 | stereoDelay | DEFAULT | 5 | 529 |
| 148 | stereoDelay | HALF TIME  MOD | — | 583 |
| 149 | stereoDelay | STEREO COMB | 5 | 515 |
| 150 | stereoDelay | STUMBLING HOME | — | 583 |
| 151 | stereoFlanger | ACID EARS | 8 | 456 |
| 152 | stereoFlanger | ARRIVAL | 9 | 413 |
| 153 | stereoFlanger | BASIC | 8 | 434 |
| 154 | stereoFlanger | CLASSIC | 8 | 454 |
| 155 | stereoFlanger | CURVED THINGS | 9 | 442 |
| 156 | stereoFlanger | DARK WOBBLES | 8 | 460 |
| 157 | stereoFlanger | DEFAULT | 9 | 413 |
| 158 | stereoFlanger | DIFFUSER | 8 | 475 |
| 159 | stereoFlanger | FAST AND WARM | 8 | 443 |
| 160 | stereoFlanger | HARMONICS | 8 | 438 |
| 161 | stereoFlanger | METALLIC | 8 | 494 |
| 162 | stereoFlanger | OLYMPIA | 9 | 417 |
| 163 | stereoFlanger | ROBOTIC | 8 | 455 |
| 164 | stereoFlanger | SLOW AND DEEP | 8 | 442 |
| 165 | stereoFlanger | STAR | 9 | 409 |
| 166 | stereoFlanger | SUPERCOPTER | 8 | 402 |
| 167 | stereoFlanger | TINCAN | 9 | 431 |
| 168 | stereoFlanger | UNDERWATER | 8 | 439 |
| 169 | stereoFlanger | VENOMOUS | 9 | 434 |
| 170 | tapeDelay | BRIGHT TAPE | — | 578 |
| 171 | tapeDelay | DEFAULT | 5 | 528 |
| 172 | tapeDelay | FAST MOD | 5 | 510 |
| 173 | tapeDelay | TAPE FEEDBACK | — | 580 |
| 174 | tapeDelay | TAPE LOOP | 5 | 510 |
| 175 | tapeDelay | VIBRATO FEEDBACK | — | 583 |
| 176 | timePhaser | DARK MATTER | 5 | 514 |
| 177 | timePhaser | DEFAULT | 5 | 529 |
| 178 | timePhaser | PHASE RING | — | 578 |
| 179 | timePhaser | SPRING NEBULA | 5 | 516 |
| 180 | timePhaser | VIBRATO PHASE DELAY | — | 587 |
| 181 | vocoder10 | 10 BAND NOISE | 5 | 515 |
| 182 | vocoder10 | 10 BAND VOCAL | — | 565 |
| 183 | vocoder10 | DEFAULT | 5 | 528 |
| 184 | vocoder16 | 16 BAND NOISE | — | 565 |
| 185 | vocoder16 | 16 BAND VOCAL | — | 565 |
| 186 | vocoder16 | DEFAULT | 5 | 589 |