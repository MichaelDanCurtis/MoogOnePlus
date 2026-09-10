# las-frontend — preset, database and settings layer

Region report. Firmware **1.8.2** (`/etc/version` = `las-v1.8.2`), compared throughout
against **1.5.0**.

**The instrument was not contacted.** Everything below is static analysis of files on
local disk plus read-only queries against two SQLite databases already captured from
the instrument. Every claim carries a grade:

- **[READ]** — read directly out of a file; the file and the byte offset / line / SQL
  query is given.
- **[INFERRED]** — reasoning from evidence; the evidence is named.
- **[UNKNOWN]** — not established.

## Sources

| what | path | notes |
|---|---|---|
| 1.8.2 rootfs | `captures/firmware-1.8.2/rootfs-1.8.2` | decrypted, complete |
| 1.8.2 binary | `…/usr/bin/las-frontend` | 145,033,524 bytes, ELF 32-bit ARM EABI5, stripped, md5 `3aa501cfcf1bfc5f5694997e28fb690d` |
| 1.5.0 rootfs | `captures/rootfs-1.5.0` | `/etc/version` = `las-v1.5.0` |
| 1.5.0 binary | `…/usr/bin/las-frontend` | 145,070,812 bytes, md5 `ccf546d1cfbc34562a26e3fbe3549994` |
| live user DB | `captures/MOOG ONE.db` | 101,920,768 bytes, the owner's own instrument database |
| second user space | `captures/SINGULARITY VOL 1 - GEOSYNTHS.db` | 26,103,808 bytes, a commercial sound-pack user space |

All file offsets below are **decimal byte offsets into the 1.8.2 `las-frontend`
binary** unless stated. Virtual address = file offset + 0x10000 for the first LOAD
segment (`llvm-objdump -p`: `LOAD off 0x0 vaddr 0x10000`, filesz 0x08a4c8ec), and
file offset = vaddr − 0x20000 for the second (`LOAD off 0x08a4c8ec vaddr 0x08a6c8ec`).
**[READ]**

---

## 0. Headline

**`/p/version` is not a reliable discriminator of preset schema.** 1.5.0 and 1.8.2
both stamp `/p/version 14` on every preset they write — the migration ladder in both
binaries ends with the same `mov r1, #14` — yet the 1.8.2 preset tree has **ten
parameter families 1.5.0 does not have** and has **dropped two that 1.5.0 had**. Any
tool that keys off `/p/version` to decide what fields a preset contains will be wrong
on this instrument. Details in §12.

---

## 1. Where the data lives

`las-frontend` is launched once, from `/etc/init.d/S43gui:21`: **[READ]**

```
DISPLAY=:0 las-frontend --usb-path=/media/thumbdrive --data-path=/var/las-frontend \
  --host-paneloutput=203.0.113.2 --host-performance=vc --host-oleds=203.0.113.2 \
  --affinity-mask=1 --host-systemclock=vc --cookie=1 --affinity-panel=1 \
  --startup-coordination --host-vc=vc &
```

- `--data-path=/var/las-frontend` — the directory holding every user database.
  `S43gui:16-18` creates it if absent. **[READ]**
- `--usb-path=/media/thumbdrive` — the import/export root; `etc/udev/rules.d/sort-part.sh:30`
  symlinks the first mounted partition there. **[READ]**
- `--affinity-mask=1`, `--affinity-panel=1` — both thread pools pinned to CPU 0.
  **[READ]** (Consistent with the established architecture note that cpu1 is the
  audio core; no independent check attempted here.)
- `/var` is `/dev/mmcblk2p6`, ext4, `defaults,noatime` (`etc/fstab`). **[READ]**
  So the user database lives on a separate partition from the A/B rootfs slots
  (`mmcblk2p2` / `mmcblk2p3`, both `ro,noauto`) — a firmware update writes the other
  rootfs slot and does not touch the preset database. **[INFERRED]** from fstab plus
  the `lasfwu` behaviour recorded in `docs/CORRECTIONS-2026-09-08.md` §6.

Filenames the binary knows: **[READ]**

| string | offset | role |
|---|---|---|
| `MOOG ONE.db` | 132808411 | default user-space database name |
| `MOOG ONE EXAMPLES.db` | 132808390 | used when `--example-data` is given |
| `las-frontend.properties` | 132808261 | `juce::PropertiesFile` (`N4juce14PropertiesFileE` at 144022832) |
| `las-frontend.log` | 132807467-ish (`las-frontend.log` literal) | `las::LASLogger` |
| `fan-calibration.properties` | just after 132808261 | fan curve |
| `/var/cal/vxcal.db` | 132807323 | the **calibration** database (separate; see §3) |
| `/var/cal/vxcal-test.db` | 132447999 | calibration test database |
| `*.db` | 132640057 | glob used when enumerating user spaces |

`ActiveUserSpace` (offset 132807047) is the properties key naming the currently
selected `.db`. **[READ]** for the string; **[INFERRED]** that it is the properties
key — it sits in the same literal cluster as `las-frontend.properties` and
`MOOG ONE.db` and is the only string of that shape.

Command-line surface, from the usage text at offset 132800141 onward: **[READ]**

```
--version  --data-path=<path>  --cal-data-path=<path>  --startup-coordination
--enable-feature  --disable-feature  --example-data  --disable-tests  --enable-tests
--cookie=<string>  --port-{response,panelinput,paneloutput,oleds,perfinput,
  perfoutput,systemclock,vc,efx}=<p>
--host-{response,panelinput,paneloutput,oleds,performance,systemclock,efx,vc}=<h>
--usb-path=<path>  --firmware-path=<path>  --firmware-dry-run
--midi-in  --midi-out  --affinity-mask=<m>  --affinity-panel=<m>
--enable-osc-sec  --assume-auto-polling
--log-perf-input  --log-perf-output  --log-panel-osc  --log-tree-osc
--log-thread-heartbeat  --log-xmos-dsptime  --print-nrpns
--script=<path>  --upside-down-ui  --touch-to-vco  --always-on-top  --test-fixture
```

Two data-path failure messages: `ERROR: The data path '<p>' is not a writable
directory.` and `Quitting because no usable database could be opened.` **[READ]**
(offsets 132807700-ish and 132808480-ish, in the same literal run).

---

## 2. The two classes

The binary is stripped, but C++ RTTI type-name strings survive in `.rodata`. 433
distinct `N3las…E` mangled type names are present. The data layer is: **[READ]**

| mangled name | offset | demangled |
|---|---|---|
| `N3las11LASDatabaseE` | 132450317 region | `las::LASDatabase` |
| `N3las11LASDatabase5Pimpl19LowPriorityExecutorE` | 132449930 region | `las::LASDatabase::Pimpl::LowPriorityExecutor` |
| `N3las5CalDBE` | 132439318 | `las::CalDB` |
| `N3las6PresetE`, `N3las6Preset5PimplE` | — | `las::Preset` |
| `N3las8SettingsE`, `N3las8Settings5PimplE` | — | `las::Settings` |
| `N3las6MasterE`, `N3las6Master5PimplE` | — | `las::Master` |
| `N3las4RootE`, `N3las4NodeE`, `N3las5ParamE` | — | the OSC-address tree |
| `N3las11PresetMakerE`, `N3las16PresetMakerCacheE` | — | preset construction |
| `N3las12PresetSenderE` | — | preset → engine |
| `N3las21ImportExportProcessorE` | 132639756 | USB import/export |
| `N3las27CreateNewUserSpaceProcessorE` | 132626216 | user-space creation |
| `N3las19PopulateFactoryDataE` | — | factory seeding |
| `N3las9ModMatrixE` | 132392616 | modulation matrix |
| `N3las11MidiMappingE` | — | MIDI CC map |
| `N3las22ExpressionSlotsUpdaterE` | — | expression-slot compilation |

Four lambda type names pin down the four public store/load entry points: **[READ]**

```
_ZN3las11LASDatabase5Pimpl11storePresetEN4juce25ReferenceCountedObjectPtrINS_6PresetEEENS2_6StringE…
_ZN3las11LASDatabase5Pimpl10loadPresetEx…                       (loadPreset(long long))
_ZN3las11LASDatabase5Pimpl13storeSettingsEN4juce25ReferenceCountedObjectPtrINS_8SettingsEEE…
_ZN3las11LASDatabase5Pimpl13storeSnapshotEN4juce25ReferenceCountedObjectPtrINS_6PresetEEENS_12SnapshotTypeE…
```
(offsets 132450440 / 132450520 / 132450560 / 132450636)

`las::LASDatabase` is JUCE-flavoured throughout: `juce::ReferenceCountedObjectPtr`,
`juce::String`, `juce::var`. **[READ]** The `libchicken.so.8` dependency
(`llvm-objdump -p` NEEDED list) is the CHICKEN Scheme runtime, used by
`las::LASScriptRunner`, not by the database. **[INFERRED]** — no Scheme symbol appears
in any SQL or database literal.

---

## 3. There are two databases, not one

`las::CalDB` and `las::LASDatabase` are separate classes with separate schemas and
separate files.

- **`las::CalDB`** → `/var/cal/vxcal.db`, set by `--cal-data-path`. Voice-card
  calibration and oscillator tuning. Its DDL runs from offset 132439315 to about
  132443000. Tables: `system_cal_table`, `system_cvout_table`, `tune_info_table`,
  `tcode_table`, `tcal_low_table`, `tcal_high_table`, `lf_table`, `hf_table`,
  `ph0_ds_table`, `ph1_ds_table`, `autor_ds_table`, `autor_table`, `mt_table`,
  `freq_table`, `autor_freq_table`, `cal_info`, `svf_freq`, `svf_res`, `ladf`,
  `ladr`, `pid`, `cal_results`, `error_log`, plus per-VCA tables created from a
  format string (`CREATE TABLE IF NOT EXISTS <name> (voice INTEGER NOT NULL PRIMARY
  KEY, …)`) for `osc_vca`, `pulse_vca`, `rm_vca`, `extin_vca`, `gsvf`, `gldr`,
  `mainl`, `mainr`, `send1`, `send2`, `noisecw`, `noiseccw`, `ladhp`, `bias_gsvf`,
  `bias_gldr`. **[READ]** at 132439315–132443000 and the name list at 132442990.
  CalDB is **out of scope** for this report beyond noting its existence; see
  `docs/arch/cal-dispatch.md`.
- **`las::LASDatabase`** → `<data-path>/<name>.db`, default `MOOG ONE.db`. Everything
  a musician saves. The rest of this document.

A useful consequence: `PRESS ENCODER TO EXPORT CALIBRATION DATABASE TO USB`
(offset 132741418) and `Copied Cal DB to USB:` (132439280) are CalDB, not preset data.
**[READ]**

---

## 4. The LASDatabase schema

Twelve `CREATE` statements, executed in this order at database open. Reproduced
verbatim; whitespace as in the binary (the multiple spaces are real). **[READ]**

| offset | statement |
|---|---|
| 132450896 | `CREATE TABLE IF NOT EXISTS global (   key TEXT NOT NULL,   data TEXT NOT NULL,   CONSTRAINT uq_global_key UNIQUE (key))` |
| 132451016 | `CREATE TABLE IF NOT EXISTS presets (   id INTEGER PRIMARY KEY ASC,    timestamp DATETIME NOT NULL,    name TEXT,   comment TEXT,   synth1Name TEXT,   synth2Name TEXT,   synth3Name TEXT,   data TEXT NOT NULL,   CONSTRAINT uq_preset_name UNIQUE (name))` |
| 132451267 | `CREATE INDEX IF NOT EXISTS idx_preset_synth1Name ON presets (synth1Name)` |
| 132451340 | `CREATE INDEX IF NOT EXISTS idx_preset_synth2Name ON presets (synth2Name)` |
| 132451413 | `CREATE INDEX IF NOT EXISTS idx_preset_synth3Name ON presets (synth3Name)` |
| 132451486 | `CREATE TABLE IF NOT EXISTS preset_tags (   presetId INTEGER NOT NULL REFERENCES presets (id) ON DELETE CASCADE,   tagId INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,   CONSTRAINT uq_preset_tag UNIQUE (presetId, tagId))` |
| 132451716 | `CREATE TABLE IF NOT EXISTS effects_presets (   id INTEGER PRIMARY KEY ASC,    timestamp DATETIME NOT NULL,    type TEXT NOT NULL,   name TEXT NOT NULL,   data TEXT NOT NULL,   CONSTRAINT uq_effect_preset UNIQUE (type, name))` |
| 132451941 | `CREATE TABLE IF NOT EXISTS mod_matrix_presets (   id INTEGER PRIMARY KEY ASC,    timestamp DATETIME NOT NULL,    name TEXT NOT NULL,   comment TEXT,   data TEXT NOT NULL,   CONSTRAINT uq_mod_matrix_preset UNIQUE (name))` |
| 132452161 | `CREATE TABLE IF NOT EXISTS midi_map_presets (   id INTEGER PRIMARY KEY ASC,    timestamp DATETIME NOT NULL,    name TEXT NOT NULL,   comment TEXT,   data TEXT NOT NULL,   CONSTRAINT uq_midi_map_preset UNIQUE (name))` |
| 132452377 | `CREATE TABLE IF NOT EXISTS sequence_presets (   id INTEGER PRIMARY KEY ASC,    timestamp DATETIME NOT NULL,    name TEXT NOT NULL,   comment TEXT,   data TEXT NOT NULL,   CONSTRAINT uq_sequence_preset UNIQUE (name))` |
| 132452593 | `CREATE TABLE IF NOT EXISTS snapshots (   id INTEGER PRIMARY KEY ASC,    timestamp DATETIME NOT NULL,    presetId INTEGER NOT NULL REFERENCES presets (id) ON DELETE CASCADE,   type INTEGER NOT NULL,   comment TEXT,   data TEXT NOT NULL)` |
| 132452829 | `CREATE TABLE IF NOT EXISTS sets (   setNumber INTEGER NOT NULL,   bankNumber INTEGER NOT NULL,   presetNumber INTEGER NOT NULL,   presetId INTEGER NOT NULL REFERENCES presets (id) ON DELETE CASCADE,   CONSTRAINT uq_set_bank_preset UNIQUE (setNumber, bankNumber, presetNumber) ON CONFLICT REPLACE)` |
| 132453126 | `CREATE TABLE IF NOT EXISTS set_descriptions (   setNumber INTEGER NOT NULL,    ordinal INTEGER NOT NULL,   timestamp DATETIME NOT NULL,    name TEXT NOT NULL,   comment TEXT)` |
| 132453301 | `CREATE TABLE IF NOT EXISTS tags (   id INTEGER PRIMARY KEY ASC,    type TEXT NOT NULL,   name TEXT NOT NULL,   CONSTRAINT uq_type_name UNIQUE (type, name))` |

At offset 132470088: `PRAGMA foreign_keys = ON;` **[READ]** —
so the `ON DELETE CASCADE` clauses are live and deleting a preset really does remove
its tag links, its snapshots and its set positions.

Transaction control literals: `COMMIT TRANSACTION` at 132450856 and
`ROLLBACK TRANSACTION` at 132450875; `BEGIN TRANSACTION` exists only in the CalDB
literal run. **[READ]**

### The schema is identical in 1.5.0

The 90 distinct SQL statements mentioning `presets|tags|sets|snapshots|global|
set_descriptions|preset_tags` are **byte-for-byte identical** between the 1.5.0 and
1.8.2 binaries (`diff` of the extracted, sorted statement sets: empty). **[READ]**
The relational schema has not moved between these two firmwares. Only the *content*
of the `data` TEXT columns has (§12).

### The live database agrees

`sqlite3 "captures/MOOG ONE.db" .schema` returns exactly these twelve tables and
three indexes, with the same column definitions. **[READ]**

Row counts in the owner's database: **[READ]**

| table | rows |
|---|---|
| `global` | 1 |
| `presets` | 398 |
| `tags` | 58 |
| `preset_tags` | 1578 |
| `effects_presets` | 169 |
| `mod_matrix_presets` | 0 |
| `midi_map_presets` | 0 |
| `sequence_presets` | 0 |
| `snapshots` | 31 |
| `sets` | 64 |
| `set_descriptions` | 1 |

`PRAGMA user_version` = 0, `PRAGMA application_id` = 0, `page_size` = 4096,
`encoding` = UTF-8. **[READ]** The database carries **no version stamp of its own**;
all versioning is inside the text payloads.

### Proof that `CREATE TABLE IF NOT EXISTS` is the migration mechanism

`SELECT type,name,tbl_name,rootpage FROM sqlite_master ORDER BY rootpage` on the
owner's database: every table has a rootpage in 2…22 **except**
`midi_map_presets` at rootpage **23387** and its auto-index at **23388**. **[READ]**

A table's rootpage is allocated when the table is created. `midi_map_presets` was
therefore created long after the others, on a database that already held tens of
megabytes — i.e. by a later firmware's `CREATE TABLE IF NOT EXISTS` on an existing
file. **[INFERRED]**, but the inference is tight: there is no other way for a table
to acquire a rootpage 23,365 pages past its siblings.

So: **new tables are added by re-running the whole DDL at every open.** There is no
schema-version table and no migration script for new tables.

### The two real DDL migrations

Only two structural repairs exist, both keyed off a failed query rather than a
version number. **[READ]**, offsets 132455750–132456400:

**(a) missing `timestamp` column.** After preparing
`UPDATE presets SET timestamp = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', <timeDelta>), name = ?1, …`
the code checks the error text against `no such column: timestamp`; on a match it
logs `Missing timestamp column in presets table, attempting table migration to adapt
old database to new format.` and runs:

```sql
DROP INDEX idx_preset_synth1Name; DROP INDEX idx_preset_synth2Name;
DROP INDEX idx_preset_synth3Name;
ALTER TABLE presets       RENAME TO old_presets;
ALTER TABLE tags          RENAME TO old_tags;
ALTER TABLE preset_tags   RENAME TO old_preset_tags;
ALTER TABLE effect_presets RENAME TO old_effect_presets;
ALTER TABLE snapshots     RENAME TO old_snapshots;
ALTER TABLE sets          RENAME TO old_sets;
```
then re-creates the tables and refills them:
```sql
INSERT INTO presets SELECT rowid AS id,
  strftime('%Y-%m-%dT%H:%M:%fZ','now') AS timestamp,
  name, comment, synth1Name, synth2Name, synth3Name, data FROM old_presets;
INSERT INTO tags        SELECT rowid AS id, type, name FROM old_tags;
INSERT INTO preset_tags SELECT presetId, tagId FROM old_preset_tags;
INSERT INTO effect_presets SELECT * FROM old_effect_presets;
INSERT INTO snapshots   SELECT * FROM old_snapshots;
INSERT INTO sets        SELECT setNumber, bankNumber, presetNumber, presetId FROM old_sets;
```
Success is logged as `Database structure timestamp column migration was successful.`
Note it never drops the `old_*` tables. **[READ]** — no `DROP TABLE old_presets`
literal exists anywhere in the binary. A database that went through this migration
still carries duplicates of every table. The owner's database did **not** go through
it (no `old_*` in `sqlite_master`). **[READ]**

**(b) `effect_presets` → `effects_presets` rename.** On finding the singular-named
table it logs `Found old effect_presets table, migrating to new format.` and runs
```sql
INSERT INTO effects_presets (id, timestamp, type, name, data)
  SELECT id, timestamp, type, name, data FROM effect_presets;
DROP TABLE effect_presets;
```
logging `Database structure effect presets migration was successful.` or
`… couldn't be migrated.` **[READ]**

Note (a) writes into `effect_presets` (old name) and (b) then renames it — so the two
run in that order on a sufficiently old file. **[INFERRED]** from the literal order
and the SQL.

### `<timeDelta>` is a textual placeholder

Every timestamped INSERT/UPDATE contains the literal token `<timeDelta>` inside the
`strftime` call. Beside it in `.rodata` sit `, <timeDelta>`, `, '` and ` seconds'`
(offsets 132455680–132455710). **[READ]** The code substitutes the token with either
nothing or `, '<n> seconds'` before preparing the statement. **[INFERRED]** — the
three fragments are exactly the pieces needed, and the test names include
"Store preset with time offset", "Insert effect with time offset",
"Store SetDescription with time offset". Purpose is to give a batch of imported items
distinct, ordered timestamps. **[INFERRED]**

---

## 5. The record format

Everything stored in a `data TEXT` column — presets, snapshots, settings, effect
presets, mod-matrix presets, MIDI maps, sequences — uses the **same text format**:
one `<osc-address> <value>` pair per line, `\n`-separated, addresses sorted
ASCII-ascending, values in JUCE `var` literal syntax. **[READ]** — e.g.
`sqlite3 "MOOG ONE.db" "SELECT substr(data,1,1200) FROM presets WHERE id=1"`:

```
/p/version 14
/p/clk/loadPresetTempo true
/p/clk/nudge_mode 0
/p/clk/rate 120.0
/p/clk/swing 0.5
/p/lc/kbd/curve "med"
…
/p/lc/kbd/lhc/1/pad_xyz [0.5000076293945312, 0.5000076293945312, 0.0]
```

Value forms observed: `true`/`false`, bare integers, floats, `"quoted strings"`,
`[a, b, c]` arrays, and `null`. **[READ]**

### Three float serialisations exist in the wild

| form | example | where seen |
|---|---|---|
| shortest round-trip | `0.009999999776482582`, `1.0`, `120.0` | 1.8.2-written and `/p/version 14` rows |
| 20-decimal fixed | `0.00999999977648258209`, `1.00000000000000000000` | every embedded factory payload; `/p/version 6` rows |
| JUCE default / scientific | `1`, `2.8229621052742e-1` | `mod_matrix_presets` rows written 2019 |

**[READ]** — all three appear in the captured databases and the binary. A reader must
accept all three. **[INFERRED]** that the change is chronological rather than
per-record-type: the same address (`entry/N/src_a`) appears in all three forms in
records of different ages.

### The `/meta/` export header

A record written to a **file** (export) is prefixed with a nine-line `/meta/` block;
a record written to the **database** is not — those fields go into columns and tags.
**[READ]** — the 580 payloads embedded in the binary all begin:

```
/meta/name "ANSWERS FOR ASKING"
/meta/comment ""
/meta/type "SINGLE"
/meta/category "PAD"
/meta/mood "CHILL"
/meta/group "KING"
/meta/synth1name "ANSWERS FOR ASKING"
/meta/synth2name ""
/meta/synth3name ""
/p/version 8
…
```
(offset 10834042 for this one.) The mapping is: `name`/`comment`/`synth1name`…
`synth3name` → the corresponding `presets` columns; `type`/`category`/`mood`/`group`
→ four rows in `tags` linked through `preset_tags`. **[INFERRED]** from the four tag
types actually present in the live database (§7) and the load SQL, which selects
`name, comment, (tag subselect), (tag subselect), synth1Name, synth2Name, synth3Name,
data`.

### Preset size and shape (1.8.2)

The embedded 1.8.2 INIT preset is 116,054 bytes: 9 `/meta/` lines + **3,250 `/p/`
lines**, in **754 distinct address shapes** (indices collapsed). **[READ]**
Section breakdown: **[READ]**

| prefix | lines |
|---|---|
| `/p/part/t/…` (3 timbres) | 2411 |
| `/p/part/las-fx/…` (2 master FX slots) | 611 |
| `/p/part/tuning/…` | 132 |
| `/p/part/cv_settings/…` | 41 |
| `/p/lc/kbd/…` | 19 |
| `/p/part/midi_io/…` | 17 |
| everything else (`/p/clk`, `/p/mix`, `/p/panel_focus`, `/p/lc/xy`, `/p/lc/sus`, `/p/version`) | 19 |

Observed preset `data` lengths in the owner's database: min 111,779, max 911,659,
mean 238,444, n = 398. **[READ]** The 911 KB outlier is a preset with a full
three-timbre sequencer.

---

## 6. LASDatabase's SQL inventory

The complete set of prepared statements, in binary order from offset 132456400.
**[READ]** Failure to prepare is logged as `Failed to prepare statement "<sql>": <err>`
(offset 132453457).

**Presets**
```sql
INSERT INTO presets (timestamp, name, comment, synth1Name, synth2Name, synth3Name, data)
  VALUES (strftime('%Y-%m-%dT%H:%M:%fZ','now',<timeDelta>), ?1,?2,?3,?4,?5,?6)
UPDATE presets SET timestamp = strftime(…), name=?1, comment=?2, synth1Name=?3,
  synth2Name=?4, synth3Name=?5, data=?6 WHERE id = ?7
DELETE FROM presets WHERE id = ?1
SELECT name, comment,
  (SELECT name FROM tags, preset_tags WHERE tags.type='<T>' AND preset_tags.presetId=?1 AND tags.id=preset_tags.tagId), …,
  synth1Name, synth2Name, synth3Name, data FROM presets WHERE id = ?1
SELECT … (same without `data`) …                       -- the "sparse" load
SELECT id, name, timestamp FROM presets ORDER BY name ASC
SELECT id, name FROM presets WHERE name = ?1
```
The tag-type literals substituted into `'<T>'` are `category` (132457812), `mood`
(132457821) and `group` (132457826) — three consecutive strings — plus `type`.
**[READ]** for the first three; **[INFERRED]** for `type` — the string is common
elsewhere in the binary so its identity as the fourth tag type rests on the live
`tags` table containing exactly `category`, `group`, `mood`, `type` (§7).

**Tags**
```sql
INSERT OR IGNORE INTO tags (type, name) VALUES (?1, ?2)
UPDATE tags SET name = ?3 WHERE type = ?1 AND name = ?2
DELETE FROM tags WHERE tags.type = ?1 AND tags.name = ?2
DELETE FROM preset_tags WHERE presetId = ?1
INSERT INTO preset_tags (presetId, tagId)
  SELECT ?1 AS presetId, id AS tagId FROM tags WHERE type = ?2 AND name = ?3
SELECT name FROM tags WHERE type = ?1 ORDER BY name ASC
```

**Browsing.** Six `WITH tmp1 AS (…)` queries, one per number of active tag filters
(0, 1, 2, 3, 4) plus a "browse by synth name" variant. All page seven rows at a time:
`SELECT count(1),'','' FROM tmp1 UNION ALL SELECT * FROM (SELECT presetId, name,
timestamp FROM tmp1 LIMIT 7 OFFSET ?n) AS tmp2`. **[READ]** — the literal `LIMIT 7`
appears in every one of them, so the preset browser's page size is fixed at **7 rows**.
The synth-name browser groups with `GROUP_CONCAT(presetId, '\t')` prefixed `1:`/`2:`/`3:`
to record which of the three timbre-name columns matched. **[READ]**
A companion query computes the row number of a given preset inside the current
filter, for scroll positioning:
`SELECT tmp3.rowNum FROM (SELECT presetId, (SELECT COUNT(*) FROM tmp1 AS tmp2 WHERE
tmp2.name <= tmp1.name) as rowNum FROM tmp1) AS tmp3 WHERE tmp3.presetId = ?n;`
**[READ]** — an O(n²) correlated subquery over the whole filtered set. **[INFERRED]**
that this is the reason the preset browser is slow on large libraries; not measured.

**Effects presets**
```sql
INSERT INTO effects_presets (timestamp, type, name, data) VALUES (strftime(…), ?1,?2,?3)
SELECT id, timestamp, type, name FROM effects_presets WHERE (type = ?1 OR ?1 = 'ALL') ORDER BY name ASC
DELETE FROM effects_presets WHERE type = ?1 AND name = ?2
SELECT id, name, data FROM effects_presets WHERE type = ?1 AND name = ?2
```

**Mod-matrix / MIDI-map / sequence presets** — three identical five-statement sets:
```sql
INSERT INTO <t> (timestamp, name, comment, data) VALUES (strftime(…), ?1,?2,?3)
SELECT id, timestamp, name, comment FROM <t> ORDER BY id ASC
DELETE FROM <t> WHERE id = ?1
SELECT id, timestamp, name, comment, data FROM <t> WHERE id = ?1
SELECT id, timestamp, name, comment, data FROM <t> WHERE name = ?1
UPDATE <t> SET comment = ?2 WHERE id = ?1
```
for `<t>` ∈ {`mod_matrix_presets`, `midi_map_presets`, `sequence_presets`}. **[READ]**
Note the list query is `ORDER BY id ASC` — these three lists are in creation order,
unlike presets and effects, which sort by name.

**Sets**
```sql
INSERT INTO sets (setNumber, bankNumber, presetNumber, presetId) VALUES (?1,?2,?3,?4)
DELETE FROM sets WHERE setNumber=?1 AND bankNumber=?2 AND presetNumber=?3
SELECT presetId FROM sets WHERE setNumber=?1 AND bankNumber=?2 AND presetNumber=?3
SELECT * FROM sets WHERE (setNumber=?1 AND bankNumber=?2 AND presetNumber>=?3)
   OR (setNumber=?1 AND bankNumber>?2) OR setNumber>?1
   ORDER BY setNumber ASC, bankNumber ASC, presetNumber ASC LIMIT 1     -- "this or next"
… > ?3 …                                                                -- "next"
… < ?3 … ORDER BY … DESC LIMIT 1                                        -- "previous"
SELECT * FROM sets ORDER BY … ASC  LIMIT 1                              -- "first"
SELECT * FROM sets ORDER BY … DESC LIMIT 1                              -- "last"
INSERT INTO sets SELECT ?2, bankNumber, presetNumber, presetId FROM sets WHERE setNumber = ?1
DELETE FROM sets WHERE setNumber = ?1
SELECT * FROM sets WHERE setNumber = ?1 ORDER BY …
```
**[READ]** The "next/previous populated slot" queries are what make the front-panel
preset-advance skip empty positions.

**Settings** — exactly two statements, and they are the whole of the settings layer:
```sql
REPLACE INTO global (key, data) VALUES ('settings', ?1)
SELECT data FROM global WHERE key = 'settings'
```
**[READ]** (offsets 132468033 and 132468089). The `global` table therefore holds
**one row**, key `settings`. Confirmed live: `SELECT key, length(data) FROM global`
→ `settings|127710`. **[READ]**

**Snapshots**
```sql
SELECT presets.id, presets.name, presets.comment, (tag subselect), (tag subselect),
  presets.synth1Name, presets.synth2Name, presets.synth3Name,
  snapshots.data, snapshots.comment
  FROM snapshots INNER JOIN presets ON presets.id = snapshots.presetId WHERE snapshots.id = ?1
INSERT INTO snapshots (timestamp, presetId, type, comment, data) VALUES (strftime(…), ?1,?2,?3,?4)
UPDATE snapshots SET comment = ?2 WHERE id = ?1
SELECT id, timestamp, type, comment FROM snapshots WHERE snapshots.presetId = ?1
  ORDER BY (strftime('%s',timestamp)-strftime('%S',timestamp)+strftime('%f',timestamp))*1000 DESC, id ASC
DELETE FROM snapshots WHERE id = ?1
DELETE FROM snapshots WHERE presetId = ?1 AND type = ?2
```
**[READ]** The ORDER BY reconstructs milliseconds from the ISO-8601 text because
SQLite's `%s` truncates to whole seconds.

**Set descriptions**
```sql
INSERT INTO set_descriptions (timestamp, setNumber, ordinal, name, comment) VALUES (strftime(…), ?1,?2,?3,?4)
UPDATE set_descriptions SET timestamp=strftime(…), name=?2, comment=?3 WHERE setNumber=?1
UPDATE set_descriptions SET timestamp=strftime(…), ordinal=?2 WHERE ordinal=?1
UPDATE set_descriptions SET timestamp=strftime(…) WHERE setNumber=?1
SELECT setNumber, ordinal, timestamp, name, comment FROM set_descriptions WHERE setNumber=?1
SELECT … WHERE ordinal = ?1
SELECT … WHERE name = ?1
DELETE FROM set_descriptions WHERE setNumber = ?1
SELECT … FROM set_descriptions ORDER BY ordinal ASC
```
**[READ]** `ordinal` is the display order of performance sets, separate from
`setNumber` which is the storage key.

### Threading

`las::LASDatabase::Pimpl::LowPriorityExecutor` (RTTI name at ~132449930) and the
thread-name literal `Low Priority` at 132453491, directly beside the
`Failed to prepare statement` message. **[READ]** All four public entry points
(`storePreset`, `loadPreset`, `storeSettings`, `storeSnapshot`) exist as lambda types
— i.e. the work is packaged and handed to the executor rather than run inline.
**[INFERRED]** — the lambda RTTI names are the evidence; the dispatch was not traced.

The UI reaches the database through lambdas taking `las::LASDatabase&`, e.g.
`ZN18LoadModMatrixPanel14refreshPresetsEvEUlRN3las11LASDatabaseEE_`,
`ZN19SettingsExportPanel20importNextItemThreadEvEUlRN3las11LASDatabaseEE0_`.
**[READ]** — there are dozens of these, one per panel action.

---

## 7. Presets, tags, sets, snapshots — as observed

### Tags

Four types, live: **[READ]** (`SELECT type, group_concat(name,', ') FROM tags GROUP BY type`)

- `type` (4): `LAYER, MULTI, SINGLE, SPLIT`
- `category` (20): `ARPEGGIO, ATMOSPHERIC, BASS, BRASS, CINEMATIC, CLASSIC, EVOLVING, FX, KEYS, LEADS, MODERN, MONO, ORGANS, PAD, PERCUSSION, PLUCKED, SEQUENCE, STRINGS, VOCODER, WINDS`
- `mood` (32): `AGGRESSIVE, ATMOSPHERIC, BLISSFUL, BRIGHT, CALM, CHAOTIC, CHILL, COLD, COMPLEX, COSMIC, DARK, DREAMY, EERIE, ENERGETIC, FUNKY, HAPPY, HARSH, HEAVY, HOPEFUL, INTENSE, MELANCHOLY, MELLOW, MYSTERIOUS, NOSTALGIC, PLAYFUL, SAD, SCARY, SMOOTH, SOMBER, STOKED, SUSPENSEFUL, WEIRD`
- `group` (2 in this database): `FACTORY, HORIZONS`

The **factory seed** list is in the binary at 132470334–132470701, immediately after
`Populating with minimal data` (132470305): `LAYER MULTI SINGLE SPLIT` then `ARPEGGIO ATMOSPHERIC
CINEMATIC CLASSIC EVOLVING FX LEADS MODERN ORGANS PERCUSSION PLUCKED STRINGS WINDS`
then `AGGRESSIVE BLISSFUL BRIGHT CALM CHAOTIC CHILL COMPLEX COLD COSMIC DARK DREAMY
EERIE ENERGETIC FUNKY HAPPY HARSH HEAVY HOPEFUL INTENSE MELLOW MELANCHOLY MYSTERIOUS
NOSTALGIC PLAYFUL SAD SCARY SMOOTH SOMBER STOKED SUSPENSEFUL WEIRD` then the single
group `MOOG ONE`. **[READ]** Note the seed `category` list lacks `BASS`, `BRASS`,
`KEYS`, `PAD`, `SEQUENCE`, `VOCODER`, `MONO` and the seed `mood` list lacks
`ATMOSPHERIC` — those exist in the live table because they arrived with imported
presets. **[INFERRED]** from `INSERT OR IGNORE INTO tags` being run for each
imported preset's meta fields.

Tags are user-editable: `EDIT CATEGORIES`, `EDIT MOODS`, `EDIT GROUPS`,
`CATEGORY NAMES`, `MOOD NAMES`, `GROUP NAMES`, `NEW CATEGORY`, `NEW MOOD`,
`NEW GROUP`, `UNTITLED`, `NAME ALREADY IN USE`, `DELETE THIS <x> NAME?`
(`EDIT CATEGORIES` at 132649938 onward, and `DELETE THIS ` / ` NAME?` at 132624312 /
132624325). **[READ]** The `type` tag is not editable — no
"EDIT TYPES" string exists. **[INFERRED]**

Tag distribution: 391 of 398 presets carry all four tags; 3 carry three; 1 carries
two; 3 carry one. **[READ]**

### Sets

A "performance set" is 8 banks × 8 presets = **64 positions**. **[READ]**
Owner's database: `setNumber` 1..1, `bankNumber` 1..8, `presetNumber` 1..8, 64 rows,
64 distinct `presetId`. The SINGULARITY user space has `setNumber` 1..2, 128 rows,
128 distinct presets, and two `set_descriptions` rows (`SINGULARITY VOL 1 - SET A`
ordinal 1, `SINGULARITY VOL 1 - SET B` ordinal 2). **[READ]**
All three indices are **1-based**. **[READ]**

`ON CONFLICT REPLACE` on `uq_set_bank_preset` means assigning a preset to an occupied
slot silently overwrites it. **[READ]** (from the DDL).

UI: `EDIT PERFORMANCE SET` (132600908), `SAVE NEW PERFORMANCE SET` (132601047),
`26PerformanceSetArrangePanel` with `refreshSets`, `changeBrowsingOffsetMoveSet`,
`deleteConfirmed`, `editSelectedSet`. **[READ]**

### Snapshots

`snapshots.type` is an integer; the C++ type is `las::SnapshotType`
(`…storeSnapshotE…NS_12SnapshotTypeE…`). **[READ]** Two values occur live: 0 (7 rows)
and 1 (24 rows). **[READ]** The binary carries both `Store snapshot` and
`Store auto save` as test names (132479891, 132479938), and the message
`Error while deleting autosave snapshots for preset "…"` sits next to
`DELETE FROM snapshots WHERE presetId = ?1 AND type = ?2`. **[READ]**
So one of {0,1} is "autosave" and the other "user snapshot". **[UNKNOWN]** which is
which — I did not trace the enum. The autosave deletion is per-preset and per-type,
i.e. saving a preset clears its previous autosaves but not its user snapshots.
**[INFERRED]**

Snapshot `data` is a full preset payload: lengths 113,493–532,002 bytes in the owner's
database. **[READ]** Four snapshots of preset 39 alone occupy 2.1 MB. **[READ]**

UI: `BrowseSnapshotsPanel` with `refreshSnapshots`, `SnapshotComponentUpdater`,
`BrowseSnapshotsEncoderKnobUpdater` (132528945–132529700). **[READ]**

---

## 8. Effects presets and effect packages

`effects_presets` is keyed `UNIQUE (type, name)`, so the same name may exist once per
effect type. **[READ]** Owner's database: 169 rows across 23 types. **[READ]**

The payload is the FX subtree with a `/fx/` root: **[READ]**
```
/version 8
/package "0x1001C"
/fx/mix 0.5
/fx/name "SLOW AND DEEP"
/fx/sync true
/fx/type "stereoFlanger"
/fx/c/control1_a 4
/fx/c/control2_a 5
/fx/p/0 1.0
…
```
`/fx/c/control1`, `/fx/c/control1_a`, `/fx/c/control2`, `/fx/c/control2_a` are the two
assignable macro controls and their sources; `/fx/p/N` the raw parameter array.
**[INFERRED]** from the naming and from `CONTROLLER`/`TRANSFORM` UI strings; not
traced to the DSP.

**`/version` on an effect preset is a different counter from `/p/version`.** Values
seen: absent, 5, 8, 9, 10. **[READ]** — 185 embedded payloads: 42 absent, 98 at 5,
26 at 8, 16 at 9, 3 at 10. Live database: 126 of 169 rows begin `/version`. **[READ]**

**Effect packages.** `/package "<hex>"` tags a preset with the FX package that
installed it. **[READ]** Values in the binary: `0x1001C` (28 presets), `0x1001E` (14),
`0x10102` (21); 122 have no `/package` line. The literal `0x10000` appears beside
`Populating with effect package ` (132455300), `0x10000` (132455332), `/package `
(132455360), `Added FX package : ` (132455370), `Done populating effect package `
(132455390) and `Restore factory default FX preset for ` (132455440). **[READ]** So `0x10000` is the base package and the untagged 122
belong to it. **[INFERRED]**

The package sets are **identical in 1.5.0 and 1.8.2** — same three ids, same counts.
**[READ]**

`triChorus` appears exactly once in each binary, as a bare type string with no
factory presets. **[READ]** — an effect type that is named but unpopulated.

The preset tree exposes **24** effect types under `/p/part/las-fx/<1|2>/types/<name>/`
and `/p/part/t/<n>/p/fx/types/<name>/`, identical in both firmwares: **[READ]**
`bbdDelay bitcrusher chorus delay dualChorus ensemble et_blackhole et_hall et_plate
et_room et_shimmer flanger phaser12stage phaser6stage pingpongDelay resonator
stereoChorus stereoDelay stereoFlanger tapeDelay timePhaser vocoder10 vocoder16
vocoder21`. `vocoder21` has no factory presets. **[READ]**

There are exactly **two** master FX slots: `/p/part/las-fx/1/` and
`/p/part/las-fx/2/`. **[READ]**

---

## 9. Mod Matrix presets

This is the `SAVE NEW MOD MATRIX PRESET` / `LOAD MOD MATRIX` feature.

UI strings: `SAVE NEW MOD MATRIX PRESET` (132587276), `LOAD MOD MATRIX` (132568158),
`NO MOD MATRIX PRESETS` (132568136), `LOAD (ADD)` (132568174) and `LOAD (REPLACE)` (132568185). **[READ]** Panels: `14ModMatrixPanel`, `18LoadModMatrixPanel` with
`loadAdd`, `loadReplace`, `saveNotes`, `deleteConfirmed`, `deleteFocusedPreset`,
`refreshPresets`. **[READ]**

So a mod-matrix preset can be **merged into** the current matrix or **replace** it.
**[INFERRED]** from the two button labels and the two distinct lambda symbols.

### Payload format

Address prefixes `/modmatrix/` (132568218) and `/modmatrix/entry/` (132568200).
**[READ]** A real example, from the SINGULARITY user space
(`SELECT data FROM mod_matrix_presets WHERE id=1`, name `EP ONE GEO`, 1142 bytes,
timestamp 2019-05-16): **[READ]**

```
/modmatrix/comment ""
/modmatrix/expressions "e3 c5 * o2pno sto mw c1 * ofm sto e3 c8 * mixrm sto l4 c11 * vca sto"
/modmatrix/name ""
/modmatrix/entry/0/ctl "MOD WHEEL"
/modmatrix/entry/0/ctl_a 1
/modmatrix/entry/0/dst "/p/part/t/1/p/fm/amt"
/modmatrix/entry/0/mute false
/modmatrix/entry/0/src "-"
/modmatrix/entry/0/src_a 1
/modmatrix/entry/0/tr "-"
/modmatrix/entry/0/tr_a 0
… entries 1..3 …
```

Points that matter:

1. **The payload carries no version field.** There is no `/version` and no
   `/p/version` line. **[READ]** Old and new forms must be told apart by the presence
   of `expressions` (old) versus `matrix_expression_slots` (new). **[INFERRED]**
2. **`dst` is fully qualified and always says `t/1`.** The stored destination is
   `/p/part/t/1/p/fm/amt` even though the preset it came from could be any timbre.
   **[READ]** This corroborates `docs/CORRECTIONS-2026-09-08.md` §5's finding that
   `t/1` is boilerplate.
3. `/modmatrix/name` and `/modmatrix/comment` are **empty in the payload** — the name
   lives in the `mod_matrix_presets.name` column. **[READ]** But the *preset* tree has
   `/p/part/t/N/p/modmatrix/name` and `…/comment`, which is where a loaded mod-matrix
   preset's identity is stamped into the preset. **[INFERRED]**

### The matrix has 20 entry slots per timbre

The 32-bit constant **20** sits at `.rodata` vaddr 0x07e526c4, immediately followed by
the seven entry-field suffixes: **[READ]**
```
14 00 00 00  "/src" "/src_a" "/ctl" "/ctl_a" "/tr" "/tr_a" "/dst"
```
and it is loaded as a loop bound in the `/p/version` migration function
(`ldr r10,[pc] → 0x07e526c4; ldr r3,[r10]`, at 0x8c8d7c–0x8c8d94). **[READ]**
So: 20 slots × 3 timbres. **[INFERRED]** — the loop that uses it is nested inside a
`for timbre in 1..3` loop (`mov r7,#1 … cmp r7,#4 … bne`, 0x8c8d80–0x8c8db8).
**[READ]**

Entries are stored **sparsely**: the 1.8.2 INIT preset contains only
`entry/0/*` and `entry/1/*`, not all 20. **[READ]**

### The compiled forms

The seven suffixes are in exactly the order of the `matrix_expression_slots` tuple.
A `/p/version 14` preset from the owner's database: **[READ]**
```
/p/part/t/1/p/modmatrix/matrix_expression_slots [48, 1.0, 6, 0.009999999776482582, 43, 0.0, 52,
                                                 22, 1.0, 48, 1.0, 43, 0.0, 92]
/p/part/t/1/p/modmatrix/seq_expression_slots []
/p/part/t/1/p/modmatrix/entry/0/ctl "MOD WHEEL"   ctl_a 0.00999…  src "-"  src_a 1.0  tr "-"  tr_a 0.0  dst "/p/part/t/1/p/m/l1_p"
/p/part/t/1/p/modmatrix/entry/1/ctl ""            ctl_a 1.0       src "FILTER EG" src_a 1.0 tr "" tr_a 0.0 dst "/p/part/t/1/p/mix/n/g"
```
14 numbers = 2 slots × 7 = `[src, src_a, ctl, ctl_a, tr, tr_a, dst]`. **[READ]**
Cross-reading the two representations gives concrete codes: source/controller `48` =
none (matches both `"-"` and `""`), `6` = `MOD WHEEL`, `22` = `FILTER EG`; transform
`43` = none; destination `52` = `/p/part/t/1/p/m/l1_p`, `92` = `/p/part/t/1/p/mix/n/g`.
**[INFERRED]** — position-by-position correspondence between two encodings of the
same two entries. This independently corroborates the tuple order recorded in
`docs/CORRECTIONS-2026-09-08.md` §4 and adds the missing observation that
`seq_expression_slots` is a **second, separate** slot array for the sequencer.
**[READ]**

The version-6 form of the same preset instead carries: **[READ]**
```
/p/part/t/1/p/modmatrix/expressions "padx c17 * fbpn sto mw c1 * a c14 * + l1po sto …"
/p/part/t/1/p/c/0 … /p/part/t/1/p/c/N …           (the constant registers)
```
with the `entry/N/*` block **identical** in both. So the human-facing matrix is
unchanged across the version boundary; only its compiled form changed.

### `vars`

`/p/part/t/N/p/modmatrix/vars/var0` … `var9` — **ten** saved engine variables.
**[READ]** `captures/arch-harvest/vx_ee.scm:112` declares 16 (`(v (array 16))`), so
six of the engine's `v` registers are **not** persisted. **[INFERRED]** from the two
counts. 1.8.2 adds four more: `vars/cvout1` … `cvout4` (§12).

---

## 10. MIDI map presets and sequence presets

### MIDI maps

`midi_map_presets`, empty in both captured databases. **[READ]** Format is the
`/midi_mapping/` subtree (prefix at 132566522, root name `/midi_mapping` at 132620024).
**[READ]** Its live shape is visible inside the settings blob: **[READ]**
```
/m/settings/midi_cv/midi_control/midi_mapping/assignments null
/m/settings/midi_cv/midi_control/midi_mapping/comment ""
/m/settings/midi_cv/midi_control/midi_mapping/name ""
/m/settings/midi_cv/midi_control/midi_mapping/version 14
```
The MIDI map has its **own** `version`, here 14. **[READ]** The upgrade path is
`las::MidiMapping::Pimpl::sanitizeAndUpgradeMidiMap(int, juce::StringArray&)` and
`…::sanitizeAndUpgradeSettingsMidiMap(juce::String)` (RTTI names at 132391008 and
132391144). **[READ]** Their bodies were not traced. **[UNKNOWN]** whether the MIDI
map version tracks `/p/version` or is independent — the shared value 14 could be
either.

Assignment fields, from the literal cluster at 132390960–132391000: **[READ]**
`/src_cc`, `/bit_depth`, `/dst_path`, `/dst_index`, plus the display forms
` 14Bits` / ` 7Bits` and the log line `Added MIDI learn mapping CC:<n> Resolution:<r>
Param: <p>`.

The CC name table runs `RESERVED`, `CC 0` … `CC 127` — **with `CC 84` absent**: `CC 83` is at offset
132391950 and the next string is `CC 85` at 132391956, six bytes later, exactly
`"CC 83\0"`. There is no gap for `CC 84`. **[READ]** `RESERVED CONTROLLER NUMBER (` and
`(RESERVED)` exist as separate messages. **[READ]** **[INFERRED]** that CC 84 is
reserved by the firmware and cannot be mapped; the reason was not established.

### Sequences

`sequence_presets`, empty in both databases. **[READ]** Prefixes `/sequence/`
(132569865), `/sequence/n/l/` (132569930), `/sequence/m/l/` (132569945),
`/sequence/name ` and `/sequence/name "` (132619977, 132619993). **[READ]**

The in-preset sequencer, read from a real preset with sequence data
(`MOOG ONE.db` id 223, `PIG SKINS`): **[READ]**

```
/p/part/t/<n>/p/seq/p/{on,length,div,tim,tempo,sync,global_swing,one_shot,
                       note_trigger,notereset,out_mode,rec_mode,key_transpose,
                       restart_on_hold,restart_on_trig,transpose_mode_interval}
/p/part/t/<n>/p/seq/name
/p/part/t/<n>/p/seq/knobs/r
/p/part/t/<n>/p/seq/r/<0..63>/en          -- 64 rows, boolean
/p/part/t/<n>/p/seq/n/l/<lane>/s/<0..63>/{n,v,g,r,t}   -- note lanes
/p/part/t/<n>/p/seq/m/l/<lane>/s/<0..63>/o             -- modulation lanes
```
- **64 steps** per lane (`s/0` … `s/63`) and **64 row-enable flags**. **[READ]**
- Note-step fields: `n` (note number, e.g. 48), `v` (velocity, 85), `g` (gate,
  0.8), `r` (ratchet count, 1), `t` (tie, boolean). **[READ]** for the values;
  **[INFERRED]** for the field meanings, from the value ranges.
- Lanes are created as needed: in this preset timbre 1 has note lanes 0,1,2 and
  timbre 2 and 3 have lane 0 only. **[READ]**
- `/p/part/t/1/p/seq/p/length 16` with 13 of 64 rows enabled. **[READ]**

`/p/part/midi_io/seq_midi_out` and `/p/part/t/N/p/arp/p/sequencer_coupling` connect
the sequencer to MIDI out and the arpeggiator. **[READ]**

---

## 11. The settings tree — `/m/settings/*`

The whole of global settings is **one row** in `global`, key `settings`, value a
`/m/settings/…` text blob. **[READ]** The owner's is 127,710 bytes over **659
lines**. **[READ]**

Line budget: **[READ]**

| subtree | lines |
|---|---|
| `/m/settings/tunings/tables/0/…` | 512 |
| `/m/settings/midi_cv/…` | 101 |
| `/m/settings/global/…` | 32 |
| `/m/settings/tunings/{fine_tune,frequency_base,load_from_preset,selected_tuning_table}` | 4 |
| scalars at the root | 8 |
| **total** | **659** |

Root scalars: **[READ]**
```
/m/settings/active_panel_focus 0
/m/settings/active_preset_id 244
/m/settings/active_set 1
/m/settings/active_set_bank 3
/m/settings/active_set_preset 4
/m/settings/chord_learn false
/m/settings/last_ui_version "2.0.8"
/m/settings/version 1
```
`active_preset_id` is a foreign key into `presets.id` — this is how the instrument
remembers what was loaded across a power cycle, and it matches the RTTI name
`…LASFrontEndApplication5Pimpl30recallActivePresetFromSettingsEv…`. **[READ]** for
both; **[INFERRED]** for the linkage.

`/m/settings/version` is **1** in both captured databases. **[READ]** It is a
separate counter from `/p/version` and from the MIDI-map version. The message
`Settings upgrade from version "<a>" to version "<b>"` sits at offset 132800141,
beside `LAS Frontend` and `las-frontend.cookie`. **[READ]** **[UNKNOWN]** what the
current settings version is in 1.8.2 — the constant was not located; the tree-building
function that references the `/m/settings/version` literal (only cross-reference, at
file 0x22c54c → vaddr 0x23c54c) is a single enormous node-construction routine and
was not fully read.

`last_ui_version "2.0.8"` is the UI version stamp of the firmware that last wrote the
blob. **[INFERRED]** — the string is also referenced by the export code
(`/m/settings/last_ui_version` at 132640220 is loaded inside `SettingsExportPanel`).
1.8.2's own UI version was not read; `/etc/version` says `las-v1.8.2` and the binary
carries the git commit `9144962cb`. **[READ]**

### `/m/settings/global/*` (32 lines) — [READ]

```
local_control/{aftertouch, cv_inputs, expression_inputs, keys, mod_wheel,
               panel_knobs_buttons, pitch_wheel, sustain_pedal, xy_pad}
system/{aftertouch_curve, chord_memory, date_format, display_active_voices,
        dup_name_on_export, dup_name_on_import, enabled_voices, fan_mode,
        gate_gain, gmt_offset, keyboard_velocity_curve, knob_mode,
        landing_auto_load, lcd_alpha, lcd_dim, led_brightness, light_show,
        oscillator_tuning_compensation, show_bank_preview, show_edited_values,
        step_edit_auto_scroll, time_format, timestamp_format}
```
`enabled_voices -1` is a bitmask with all bits set. **[INFERRED]** from the value and
the UI label `PRESS ENCODER TO EDIT THE ENABLED VOICES`.

`dup_name_on_import` / `dup_name_on_export` are both `2` in the owner's settings.
**[READ]** The enum labels sit consecutively in `.rodata`: `IGNORE`, `AUTO RENAME`,
`IGNORE` (132648865), `AUTO RENAME` (132648872) and `MANUAL RENAME` (132648884), in
the run `… | MM/DD/YYYY | CLOSED | OPEN | IGNORE | AUTO RENAME | MANUAL RENAME |
SILENT LEARN | AUDIBLE LEARN | ABSOLUTE | PASS-THROUGH | RELATIVE | …`. **[READ]**
So 0=IGNORE, 1=AUTO RENAME, 2=MANUAL RENAME. **[INFERRED]** from the order.

### `/m/settings/midi_cv/*` (101 lines) — [READ]

```
cv_input/load_from_preset
cv_input/{cvin_1, cvin_2, expr_in_1, expr_in_2}/{dest,max,min,note_1,note_2,synth,velocity}
cv_input/sustain/{dest,max,min,note_1,note_2,synth,type,velocity}     -- note extra `type`
cv_output/load_from_preset
cv_output/{1,2,3,4}/{max,min,source,synth,value,voice_rule}
midi_control/{always_send_nrpn_numbers, load_from_preset, output,
              output_running_status, receive_midi_clock, receive_midi_start_stop,
              send_aftertouch, send_expression, send_keys, send_midi_clock,
              send_midi_start_stop, send_mod_wheel, send_pitch_wheel, send_pots,
              send_sust_pedal, send_xy_pad, sysex_device_id}
midi_control/midi_mapping/{assignments, comment, name, version}
midi_io/{arp_midi_out, load_from_preset, merge_avb_in, merge_din_in, merge_usb_in,
         midi_in_channel_all, midi_in_channel_synth1..3, midi_in_ports, midi_in_route,
         midi_out_channel_all, midi_out_channel_synth1..3, midi_out_ports,
         midi_out_route, seq_midi_out}
```

The `load_from_preset` flags — one each for `cv_input`, `cv_output`, `midi_control`,
`midi_io`, `tunings` — are the switches that decide whether a loaded preset's copy of
those blocks overrides the global settings. **[INFERRED]** from the names plus the
lambda symbols `SettingsGlobalPanel::copyMidiSettingsToPreset`,
`applyMidiSettingsFromPreset`, `copyCvInputsToPreset`, `applyCvInputsFromPreset`,
`copyCvOutputsToPreset`, `applyCvOutputsFromPreset`, `copyNoiseGateAmountToPreset`
(offsets 132643818–132645208). **[READ]** for the symbols.

`merge_avb_in "o"` is present here as it is in the preset tree. Nothing implements it
(see `docs/CORRECTIONS-2026-09-08.md` §7).

### `/m/settings/tunings/*` (516 lines) — [READ]

```
/m/settings/tunings/fine_tune 0.0
/m/settings/tunings/frequency_base 440.0
/m/settings/tunings/load_from_preset false
/m/settings/tunings/selected_tuning_table 1
/m/settings/tunings/tables/0/name_<k>    for k = 0 … 127
/m/settings/tunings/tables/0/root_<k>    for k = 0 … 127
/m/settings/tunings/tables/0/type_<k>    for k = 0 … 127
/m/settings/tunings/tables/0/data_<k>    for k = 0 … 127
```
**128 tuning-table slots**, four fields each, all under a single `tables/0` node with
the slot index as a **field-name suffix**, not a path element. **[READ]** Slot 0 is
`name_0 "FROM PRESET"`. **[READ]** `data_<k>` is a long hex string; slot 0's begins
`"000102030405060708090a0b0c0d0e0f10…"` — a 128-entry identity map. **[INFERRED]**
from the byte pattern.

This subtree is 512 of the 659 lines and the bulk of the 127 KB.

### Other `/m/` addresses

Only ten distinct `/m/` string literals exist in the binary: `/m/at`, `/m/w`,
`/m/xyz`, `/m/xyz/hold`, `/m/xyz/pol`, `/m/settings`, `/m/settings/global`,
`/m/settings/midi_cv`, `/m/settings/version`, `/m/settings/last_ui_version`.
**[READ]** The first five are live performance state under `las::Master`, not
persisted in `global`. **[INFERRED]** — they do not appear in either captured
settings blob.

---

## 12. `/p/version` 6…14 — how migration actually works

### It is one function, one ladder, run at load

The literal `/p/version` (offset 132807063, vaddr 0x07eb7997) has **exactly one**
cross-reference in the binary: a literal-pool word at file 0x8b80d8, inside a single
function spanning file 0x8b7800–0x8b90a4 (vaddr 0x8c7800–0x8c90a4, 6,308 bytes).
**[READ]**

The function reads `/p/version` into `r5` (0x8c781c–0x8c7870) and then falls through a
cascade of version cases in increasing order: **[READ]** — the `cmp r5, #N` sites are

| from-version | vaddr |
|---|---|
| 1 | 0x8c787c |
| 2 or 3 | 0x8c7888 |
| 4 | 0x8c7b40 |
| 5 | 0x8c7e74 |
| 6 | 0x8c7f3c |
| 7 | 0x8c807c |
| 8 | 0x8c8128 |
| 9 | 0x8c82cc |
| 10 | 0x8c856c |
| 11 | 0x8c8b70 |
| 12 | 0x8c8c98 |
| 13 | 0x8c8d74 |

(Three further `cmp r5,#…` at 0x8c7f58 (#28), 0x8c87e4 (#3) and 0x8c8cec (#4) are
out of sequence and are loop bounds — `r5` is reused inside case bodies. **[INFERRED]**
from the ordering and from 0x8c8d9c `mov r5, r0`.)

The entry dispatch is `cmp r5,#1 / beq case1 / blt case4` then `cmp r5,#3 /
movle r7,#1 / ble <case-1 tail> / b case4` — so versions 2 and 3 join case 1's tail,
and anything above 3 enters at case 4. **[READ]**

At the end, unconditionally: **[READ]**
```
8c8ddc:  ldr  r3, [r8]
8c8de0:  mov  r1, #14          ; <-- the target version
8c8de4:  add  r0, sp, #128
8c8de8:  ldr  r4, [r3, #0x18]
8c8dec:  bl   <juce::var::var(int)>
8c8df0:  mov  r0, r8
8c8df8:  blx  r4               ; <-- setProperty(/p/version, 14)
```

**The same ladder, with the same twelve cases and the same `mov r1, #14`, is present
in 1.5.0** at vaddr 0x8c6764–0x8c7cc8. **[READ]**

The function is called from exactly one place (0x8cab58, inside a routine at
0x8caab0), which is itself called from **seven** sites (0x8b2270, 0x8cac34, 0x8cae2c,
0x8cae94, 0x8caf24, 0x8caf4c, 0x8cb66c). **[READ]** These are the paths that
materialise a `Preset` from text — load from DB, load a snapshot, import a file,
instantiate `INIT_m1p`, and the mod-matrix add/replace. **[INFERRED]** — the call
sites were not individually attributed.

### Migration is in memory; rows are never rewritten

The owner's database, running on a firmware that stamps 14, still contains: **[READ]**

| stored `/p/version` | rows |
|---|---|
| 6 | 368 |
| 8 | 1 |
| 14 | 29 |

and the SINGULARITY user space contains 126 at version 10 and 3 at version 14.
**[READ]** A stored payload keeps whatever version it was written with until the user
saves over it. There is no bulk upgrade pass. **[INFERRED]** — 368 unmigrated rows in
a working instrument is decisive.

### What each step does — as far as it was read

| step | evidence | what it touches |
|---|---|---|
| 1, 2, 3 → 4 | strings `l1pno l2pno l3pno l4pno pno o1pno o2pno o3pno fpn fapn fa1pn fa2pn fbpn` loaded at 0x8c7940–0x8c7a30 **[READ]** | renames 13 expression-engine destination mnemonics inside stored expressions |
| 4 → 5 | strings `/p/part/t/`, `/p/fx/ins/p`, `/p/fx/types/`, `/p/part/las-fx/`, `/p`, `/types/` loaded at 0x8c7ba0–0x8c7da4 **[READ]** | re-roots the effects addressing between the per-timbre insert FX and the master `las-fx` slots |
| 5 → 6 … 11 → 12 | no string constants in the blocks **[READ]** | **[UNKNOWN]** — these operate on `Node`/`Param` handles built from numeric indices, so nothing legible survives |
| 12 → 13 | `ldr r3,[pc] → 0x08a6ed0c` at 0x8c8d44 **[READ]**; 0x08a6ed0c is the head of a name table whose entries include `LIMIT HIGH SQUARED CUBED LOPASS HIPASS` **[READ]** | indexes a modulation source/transform name table; **[UNKNOWN]** what it rewrites |
| 13 → 14 | 0x8c8d74–0x8c8ecc **[READ]** | for each of 3 timbres × 20 matrix slots, compares `entry/<i>/src` and `entry/<i>/ctl` against `"RANDOM KEYED"` (0x07eb79f3) and replaces with `"RANDOM KEYED 1"` (the `.data` word at vaddr 0x08a6edb0 holds a pointer to a string reading `RANDOM KEYED 1`, sitting in a run `… RANDOM KEYED 3 \0 RANDOM KEYED 2 \0 RANDOM KEYED 1 \0 RANDOM BIPOLAR \0 RANDOM \0 …`) **[READ]** |

So version 14's user-visible change includes splitting one `RANDOM KEYED` source into
three numbered ones. **[INFERRED]** from the rename plus the presence of
`RANDOM KEYED 2` and `RANDOM KEYED 3` in the same string run.

### What actually changed between v6 and v14 — from the data

Address-shape diff between a stored `/p/version 6` preset and a stored
`/p/version 14` preset in the owner's database (indices collapsed; 707 vs 735 shapes):
**[READ]**

**Removed at 14**
```
/p/part/t/N/in/midi/ch
/p/part/t/N/in/midi/en
/p/part/t/N/p/c/N                       -- the expression constant registers
/p/part/t/N/p/modmatrix/expressions     -- the RPN text form
```

**Added at 14**
```
/p/part/t/N/in/din0/note-enable         -- replaces in/midi/en, now per port
/p/part/t/N/in/usb0/note-enable
/p/part/t/N/p/modmatrix/matrix_expression_slots
/p/part/t/N/p/modmatrix/seq_expression_slots
/p/part/t/N/p/modmatrix/vars/var0 … var9
/p/part/t/N/p/{arp,l1,l2,l3,l4,seq}/knobs/r
/p/part/t/N/p/fx/knobs/N
/p/part/t/N/p/fx/types/stereoChorus/{N, ctl1_a, ctl2_a}
/p/part/t/N/p/fx/types/stereoFlanger/{N, ctl1_a, ctl2_a}
/p/part/las-fx/N/types/stereoChorus/N
/p/part/las-fx/N/types/stereoFlanger/N
/p/part/las-fx/spread
/p/part/t/N/p/pan-spread
/p/part/t/N/p/mix/ngate/gain
```

The `in/midi/{ch,en}` → `in/{din0,usb0}/note-enable` change is the per-port MIDI
routing split; the `c/N` + `expressions` → `matrix_expression_slots` change is the
RPN-to-tuple change; `stereoChorus`/`stereoFlanger` are new effect types; `pan-spread`,
`las-fx/spread` and `mix/ngate/gain` are new parameters. **[INFERRED]** — the address
names are the only evidence.

### The headline: schema drift at constant version

Diff the **1.8.2-embedded INIT payload** (written by 1.8.2's own serialiser,
`/p/version 14`, 116,054 bytes, offset 143840307) against the **owner's stored INIT
row** (written by his 1.5.0-era firmware, `/p/version 14`, 114,427 bytes,
`presets.id = 1`): **[READ]**

**Present in 1.8.2's v14, absent from 1.5.0's v14**
```
/p/part/cv_settings/cv_output/N/voice_rule          (N = 1..4)
/p/part/t/N/p/e1/{async,dsync,rsync}
/p/part/t/N/p/e2/{async,dsync,rsync}
/p/part/t/N/p/e3/{async,dsync,rsync}
/p/part/t/N/p/fa/mode
/p/part/t/N/p/l1/fsync   /p/part/t/N/p/l2/fsync
/p/part/t/N/p/l3/fsync   /p/part/t/N/p/l4/fsync
/p/part/t/N/p/o1/hardsync  /p/part/t/N/p/o2/hardsync  /p/part/t/N/p/o3/hardsync
/p/part/t/N/p/modmatrix/vars/cvout1 … cvout4
```
all with value `false` (or `0.0` for the `cvout` vars) in INIT. **[READ]**

**Present in 1.5.0's v14, absent from 1.8.2's v14**
```
/p/part/t/N/p/sus/mode
/p/part/t/N/p/sus/src
```

Three independent corroborations that this is a real schema change and not a quirk of
one payload:

1. The node-name literals `hardsync`, `async` and `rsync` occur **0 times** in the
   1.5.0 binary and once each in 1.8.2. **[READ]**
2. `/sus/mode` and `/sus/src` occur **1740** times in the 1.5.0 binary and **1737**
   times in 1.8.2 — a difference of exactly 3, the three timbres of the one payload
   that was re-serialised (INIT). Every other embedded payload is an old one and still
   carries them. **[READ]**
3. `voice_rule` occurs once in 1.5.0 (a bare node name, used by the settings tree) and
   five times in 1.8.2 (the same bare name plus four preset lines). **[READ]**

And both firmwares stamp 14. **[READ]**

**This resolves the open question in `docs/CORRECTIONS-2026-09-08.md` §9.** The 25
presets in the owner's database that set `cv_output/N/voice_rule` (all timestamped
2022-05-29, all `/p/version 14`) are not anomalous and are not a hole in the namespace
dump: they were authored on a firmware between 1.5.0 and 1.8.2 that had already added
the field. **[READ]** for the 25 rows and their version; **[INFERRED]** for the
authoring firmware. The owner's own 1.5.0 instrument cannot produce the field, which
is why a live namespace dump taken on 1.5.0 does not list it.

**Consequence for tooling.** `/p/version` tells you which *migration steps* have been
applied. It does not tell you which *fields* are present. A v14 preset may or may not
have `voice_rule`, `hardsync`, `fsync`, the envelope `*sync` flags, `fa/mode` or the
`cvout` vars, and may or may not still have `sus/{mode,src}`. Readers must be
tolerant; writers must not assume.

---

## 13. Embedded factory data

**91.99%** of the 1.8.2 binary is `.rodata` (0x07f3c122 = 133,415,202 bytes of
145,033,524). **[READ]** — from `llvm-objdump -h`. Of the whole file, **83.89%**
(121,664,624 bytes) is factory preset text. **[READ]** — measured by walking the
NUL-delimited C strings that contain a `/p/version <n>` line.

### 580 preset payloads, in two different places

**580** payloads contain `/p/version`. **[READ]** Each is a complete `.m1p` body:
nine `/meta/` lines followed by the `/p/` tree. **[READ]** Every one carries a
distinct `/meta/name`. **[READ]**

- **579** of them are reachable through a contiguous `const char*` table at
  **vaddr 0x08a6e3a8** (file 145023912), 579 entries, alphabetically descending by
  name (`ANSWERS FOR ASKING`, `ANOTHER BASS`, `ANNIHILATION DRONE`, … `1892 HORROR
  FILM`). **[READ]** These are the factory library, seeded by
  `las::PopulateFactoryData` (`Populating with complete factory data` /
  `Done populating with complete factory data` at 132471647; the seeding message pair
  is 132470754 / 132471647). **[READ]**
- **1** of them — `INIT` — is **not** in that table. It is the JUCE BinaryData
  resource `INIT_m1p`, original filename `INIT.m1p`. **[READ]**

The JUCE BinaryData resource list contains **twenty** entries, of which exactly one is
a `.m1p`: **[READ]** (offsets 133741050–133741730)
```
BRD-10-011-1204_SYS_TEST.js   BRD-10-011-1207_RIGHT_TEST.js
BRD-10-011-1208_MIDDLE_TEST.js BRD-10-011-1209_LEFT_TEST.js
FRONT_PANEL_ASSEMBLY_TEST.js  LHC_SUBASSEMBLY_TEST.js
DejaVuSans-Bold.ttf DejaVuSans.ttf DejaVuSansMono-Bold.ttf DejaVuSansMono.ttf
"FTN55 Futura PT Medium.otf" "FTN75 Futura PT Heavy.otf"
SourceHanSansCN-Regular.aa … .ah   slotmachine.png
INIT.m1p   adjectives.txt   nouns.txt   verbs.txt
```
(the `adjectives/nouns/verbs` triple feeds the `slotMachine` random-name panel.
**[INFERRED]**)

**Correction to an existing claim.** `docs/CORRECTIONS-2026-09-08.md` §8 records, as
`[AGENT]`, "580 complete `.m1p` bodies are embedded in `las-frontend`, including the
real factory `INIT_m1p`". The count of 580 is right and the presence of a real
`INIT_m1p` is right, but they are **not** 580 BinaryData resources: 579 are a plain
pointer table and only INIT is a named resource. **[READ]**

### Corpus statistics (1.8.2) — [READ]

| field | distribution |
|---|---|
| `/p/version` | 6:369, 7:18, 8:29, 9:9, 10:49, 11:1, 12:29, 14:76 |
| `/meta/type` | SINGLE:411, MULTI:126, SPLIT:26, LAYER:17 |
| `/meta/group` | FACTORY:367, TRANSFORMERS:53, CLASSICS:51, STEREO FUTURES:45, KING:26, `1.0.4`:13, POLYPHONIC DESTINATIONS:13, MOOG:9, empty:3 |
| `/meta/category` | 24 distinct, KEYS:74 PAD:67 CLASSIC:56 … including `LUSH`, `SEQUENCE`, `CHORD`, `VOCODER`, `MONO`, `ORGAN` which are **not** in the seed tag list |
| `/meta/mood` | 34 distinct, DREAMY:67 BRIGHT:46 NOSTALGIC:44 … including `ATMOSPHERIC` and `LIGHT`, not in the seed list |
| payload length | min 114,210, max 911,854, mean 209,766 |

Note versions 6…12 and 14 appear; **13 does not**, and neither does anything below 6.
**[READ]**

### Between 1.5.0 and 1.8.2, exactly one payload changed

SHA-256 of all 580 payloads in each binary: **579 identical, 1 different — `INIT`.**
**[READ]**

- 1.5.0: `INIT`, `/p/version 6`, 155,569 bytes
- 1.8.2: `INIT`, `/p/version 14`, 116,054 bytes

The 39,515-byte shrink is the removal of the `/p/part/t/N/p/c/*` constant-register
block plus the switch from 20-decimal to shortest-round-trip floats. **[INFERRED]**
from the v6/v14 address diff and the observed float forms.

The factory *library* was therefore not touched at all between these two firmware
releases; only the INIT template was re-saved. **[READ]**

### 185 embedded effects presets

A contiguous 185-entry `const char*` table at **vaddr 0x08a6e0c0** (file 145023680),
89,246 bytes total, 162 distinct names across 23 types. **[READ]**
Distribution given in §8. Both binaries carry the same set. **[READ]**

### Minimal vs factory seeding

Two seeding modes: `Populating with minimal data` (132470305) / `Done populating with minimal data`
(tags plus a single group named `MOOG ONE` at 132470693) and
`Populating with complete factory data` (132470754) (the 579 presets). **[READ]** These correspond to the user-space creation buttons
`CREATE EMPTY` and `CREATE FACTORY` (offsets 132626395, 132626408). **[INFERRED]**

The literal block at 132471690 onward (`LASDatabaseTests`, then `WIZARD SPELL`,
`SUBLIMINAL KITTEN`, `FREE BEER`, `APOLLO`, `FOXY ROXY`, … with tiny payloads such as
`/p/part/t/1/p/o1/fo 0.01`) is **test fixture data for `LASDatabaseTests`**, not
factory content. **[READ]** — it sits immediately after the string `LASDatabaseTests` (132471690) and
its payloads are three lines long. Do not mistake these names
for presets.

---

## 14. User Spaces

A "user space" is **a separate SQLite database file** in `--data-path`. **[READ]**

Evidence: the glob `*.db` at 132640057 is used by `SettingsExportPanel`; the class
`las::CreateNewUserSpaceProcessor` (132626216) sits beside the literals
`LASCreateDatabase` (132626368) and `CreateNewDatabase` (132626400); the properties key
`ActiveUserSpace` names the current one; and the owner has two such files
(`MOOG ONE.db`, `SINGULARITY VOL 1 - GEOSYNTHS.db`) whose schemas are identical.
**[READ]**

UI strings (offsets 132625537–132650260): **[READ]**
```
USER SPACES        SWITCH USER SPACE   EDIT USER SPACE    ACTIVE USER SPACE
USER SPACE:        USER SPACE NAME     LOADED USER SPACE <n>
ENTER A NAME FOR THE NEW USER SPACE
(THE NEW USER SPACE WILL AUTOMATICALLY BECOME ACTIVE)
CREATE FACTORY     CREATE EMPTY
ENTER A NEW NAME FOR THIS USER SPACE   COPY OF    COPY OF: "
DELETE THIS USERSPACE?
CREATING <n> USER SPACE   PLEASE WAIT   PROCESSING
NAME IS EMPTY    NAME IS INVALID
ALL DATA (USER SPACE)
```
So a user space can be created empty, created with the factory library, copied, renamed
and deleted. **[INFERRED]** from the strings; the code paths were not traced.

The second captured user space confirms the model: it is a complete, independent
database with its own `global` settings row (`active_preset_id 16`,
`active_set 1`, `active_set_bank 1`, `active_set_preset 7`, `last_ui_version "2.0.8"`),
its own 57 tags, 129 presets, 177 effects presets, 3 mod-matrix presets, 81 snapshots,
2 sets and 2 set descriptions. **[READ]**

**Global settings are per user space, not global.** The `global` table lives inside
each `.db`, and both captured files have their own. **[READ]** Switching user space
therefore switches tuning tables, MIDI routing and CV assignment as well as presets.
**[INFERRED]**

### Storage pressure

```
SYSTEM STORAGE CRITICALLY LOW.
PLEASE EXPORT AND DELETE ANY UNUSED USER SPACES
OR EXCESS PRESET DATA.
CANNOT SAVE <item>
```
at offsets 132619696, 132619727, 132619793, 132619825. **[READ]**

The literal-pool word immediately preceding the string pointer, at vaddr 0x006236dc,
is **0x05F5E100 = 100,000,000**. It is loaded into `r2` with `r3 = 0` (a 64-bit
argument pair) and passed to a call at 0x6b0e28 whose zero return leads directly to
the message. **[READ]** So the warning fires when free space falls below **100 MB
(decimal)**. **[INFERRED]** — the constant and the control flow are read; the callee
was not identified.

For scale: the owner's single user space is 101.9 MB and the second is 26.1 MB.
**[READ]**

---

## 15. Import / export

Class `las::ImportExportProcessor` (132639756), panel `19SettingsExportPanel`
(132639800). **[READ]** Per-category refresh lambdas: **[READ]**
```
refreshPresets  refreshPerformanceSets  refreshEffectsPresets  refreshModMatrixPresets
refreshMidiMapPresets  refreshSequences  refreshGlobalSettings  selectAllOrNone
parseAndAddPerformanceSetItems  importNextItemThread  exportNextItemThread
databaseNameCheck  applyFocusedPresetId
```

UI category list (offsets 132640230–132640350): `SEQUENCES`, `PERFORMANCE SETS`,
`EFFECT PRESETS`, `GLOBAL SETTINGS`, `USER SPACES`, plus `EXPORT PRESETS`,
`EFFECTS PRESETS`, `ALL DATA (USER SPACE)`. Menus: `EXPORT MENU`, `IMPORT MENU`,
`PRESS ENCODER TO EXPORT`, `PRESS ENCODER TO IMPORT`, `PRESS ENCODER TO TOGGLE ON/OFF`,
`EXPORT GLOBAL SETTINGS?`. **[READ]** Progress and error messages:
`IMPORT <n> TO DEVICE <p>`, `EXPORT <n> TO USB DRIVE <p>`,
`Imported <n> items successfully in <t>`, `Exported <n> …`, `IMPORTING`, `EXPORTING`,
`NOT ENOUGH SPACE LEFT ON USB DEVICE`, `COULD NOT READ FILE FROM USB DEVICE`,
`COULD NOT WRITE FILE TO USB DEVICE`, `COULD NOT IMPORT FILE`, `NO <x>`,
`NO MATCHING <x>`. **[READ]**

### The eight file extensions

Seven sit in one contiguous `.rodata` run at offset 132640414: **[READ]**
```
2e 6d 31 73 00  2e 6d 31 66 00  2e 6d 31 78 00  2e 6d 31 6d 00
2e 6d 31 63 00  2e 6d 31 67 00  2e 6d 31 75 00
 .m1s            .m1f            .m1x            .m1m
 .m1c            .m1g            .m1u
```
The eighth, **`.m1p`**, does not exist as its own string: it is the **tail-merged
suffix of `"INIT.m1p"`** at offset 133741142 (vaddr 0x07f9ba56), and is referenced
from a literal pool word at file offset 0x6b3b70 — two words (8 bytes) before `.m1s`
at 0x6b3b78 — in an 8-entry initialiser table of 8-byte stride, each entry pairing a
`const char*` with a `.bss` `juce::String` global (`.m1p`→0x08a778a0, `.m1s`→0x08a77894,
`.m1f`→0x08a77888, `.m1x`→0x08a778a4, `.m1m`→0x08a7788c, `.m1c`→0x08a77890,
`.m1g`→0x08a77898, `.m1u`→0x08a7789c). **[READ]**

A switch on an item-type field (`ldr r3, [r4, #0xa4]`) selects among them, at vaddr
0x6b6284–0x6b6390: **[READ]**

| type index | extension |
|---|---|
| 0 | `.m1p` |
| 1 | `.m1s` |
| 2 | `.m1f` |
| 3 | *(no extension appended)* |
| 4 | `.m1x` — and this case first appends two extra strings, i.e. builds a compound file name |
| 5 | `.m1m` |
| 6 | `.m1c` |
| 7 | `.m1g` |
| 8 | `.m1u` |

**[READ]** for the switch and the mapping from index to extension.

Partial identification of what the indices mean:
- `0 = .m1p` is the preset extension, since the only `.m1p` filename in the binary is
  `INIT.m1p`, an actual preset. **[READ]**
- `7 = .m1g` — the nearest literal to `.m1g`'s other use site (file 0x6a16e8) is
  `" SETTINGS"` (0x6a16f8). **[INFERRED]** → global settings.
- `8 = .m1u` — the nearest literal to its other use site (0x6a1adc) is `"*.db"`
  (0x6a1ae0). **[INFERRED]** → user space, exported as a `.db`.
- `4 = .m1x` — the literals near its other use site (0x6a23cc) are `triChorus`,
  `" - "` and `ensemble` (effect type names and a separator). **[INFERRED]** → effect
  presets, whose file name must carry both type and name because
  `effects_presets` is keyed `UNIQUE(type,name)`; the case's two extra string appends
  are consistent with `"<name> - <type>.m1x"`. **[INFERRED]**
- `1 = .m1s`, `2 = .m1f`, `5 = .m1m`, `6 = .m1c` map, in some order, to sequences,
  performance sets, mod-matrix presets and MIDI maps. Letter mnemonics suggest
  `.m1s`=sequence, `.m1m`=mod matrix, `.m1c`=MIDI **c**ontrol map, `.m1f`=performance
  set — but `f` for "performance set" is a poor fit and I could not confirm any of
  the four. **[UNKNOWN]**
- Index 3 appends no extension at all. **[UNKNOWN]** what it is.

**Do not treat the four uncertain mappings as established.** They are the one part of
this region I could not close.

### Duplicate-name policy

`DUPL. ON IMPORT` / `DUPL. ON EXPORT` settings, values `IGNORE` (132648865) / `AUTO RENAME` (132648872) /
`MANUAL RENAME` (132648884), stored as `/m/settings/global/system/dup_name_on_import` and
`…/dup_name_on_export`. **[READ]** Owner's value: 2 for both. Supporting UI:
`NAME ALREADY IN USE`, `settingsRenameDuplicates` panel, `COPY OF `. **[READ]**

### Firmware update is a separate path

`--firmware-path`, `--firmware-dry-run`, `Looking for firmware updates in `,
`CHECKING USB FOR NEW FIRMWARE`, `PRESS ENCODER TO UPDATE FIRMWARE`,
` FROM USB DRIVE [` and `upgradeFirmware` — all present, all distinct from the
preset import/export code. **[READ]** Out of scope here; see
`docs/CORRECTIONS-2026-09-08.md` §6 and `docs/arch/decompressor.md`.

---

## 16. Conflicts with existing docs

Reported, not fixed, per instruction.

1. **`docs/CORRECTIONS-2026-09-08.md` §8**, `[AGENT]`: "580 complete `.m1p` bodies are
   embedded in `las-frontend`, including the real factory `INIT_m1p`". The number and
   the INIT claim are correct, but the framing "BinaryData resources" (used elsewhere
   in the project's notes) is wrong: the JUCE BinaryData resource list has 20 entries
   and exactly one `.m1p`. The other 579 are entries in a plain `const char*` table at
   vaddr 0x08a6e3a8. **[READ]**

2. **`docs/CORRECTIONS-2026-09-08.md` §8**, `[AGENT]`: "`las-frontend` is 92% `.rodata`,
   of which ~84% of the whole binary is uncompressed ASCII preset text". Both figures
   are now confirmed: `.rodata` = 91.99% of the file; preset payload text = 83.89% of
   the file. **[READ]** Upgrade from `[AGENT]` to verified.

3. **`docs/CORRECTIONS-2026-09-08.md` §9**, open question on `voice_rule`: resolved.
   It is a **firmware difference**, not a hole in the namespace dump.
   `/p/part/cv_settings/cv_output/N/voice_rule` does not exist in 1.5.0 and does exist
   in 1.8.2, at the same `/p/version 14`. **[READ]**

4. **`docs/CORRECTIONS-2026-09-08.md` §4** says version 14 presets "carry
   `matrix_expression_slots`, a flat array of 7-tuples `[src, src_a, ctl, ctl_a, tr,
   tr_a, dst]`, and there is no `/p/c/*` block". Confirmed independently here, and
   extended: there is a **second** array, `seq_expression_slots`, for the sequencer,
   and the tuple order is corroborated by the seven field-name suffixes stored
   consecutively at vaddr 0x07e526c8. **[READ]** No conflict; an addition.

5. **The brief's own framing** — "how `/p/version` 6..14 schema migration works" —
   assumes version numbers track schema. They do not, across firmware releases (§12).
   The migration ladder covers 1→14 and is identical in 1.5.0 and 1.8.2; the schema
   drift between those two firmwares happened *without* a version bump. Any document
   that says "a `/p/version 14` preset has fields X" needs a firmware qualifier.

6. Not a conflict but worth flagging for `docs/arch/preset-format.md` (not read in
   detail here, to avoid contaminating this pass): if it enumerates preset addresses,
   it should say which firmware's tree it enumerates.

---

## 17. Validation plan

Read-only commands a human could run **on the instrument** to confirm the load-bearing
claims. I have not run any of them. Every one is a read; none writes, none triggers
calibration. Run them over SSH as root.

**A. The database file and its schema**
```sh
ls -l /var/las-frontend/
cat /var/las-frontend/las-frontend.properties
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" ".schema"
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT type,name,rootpage FROM sqlite_master ORDER BY rootpage;"
```
Confirms §4 (twelve tables, three indexes) and the additive-migration evidence
(`midi_map_presets` with a far-later rootpage).

**B. Preset version distribution — confirms §12's "rows are never rewritten"**
```sh
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT substr(data,1,16), count(*) FROM presets GROUP BY 1;"
```

**C. The schema-drift headline.** Save one preset on the instrument under a new name
(this is the only step that writes, and it writes only a new preset row — the owner
should decide whether to do it), then:
```sh
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT data FROM presets ORDER BY id DESC LIMIT 1;" \
  | grep -E 'hardsync|/fa/mode|/l1/fsync|e1/async|voice_rule|/sus/(mode|src)|^/p/version'
```
On 1.5.0 this must print `/p/version 14`, the two `/sus/*` lines, and **nothing else**.
On 1.8.2 it must print `/p/version 14`, the new fields, and **no** `/sus/*`.
A purely read-only variant, if the owner would rather not save: run the same grep over
an existing row known to have been saved by the current firmware.

**D. Settings blob**
```sh
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" "SELECT key, length(data) FROM global;"
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT data FROM global WHERE key='settings';" | grep -v '/tunings/tables/' | wc -l
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT data FROM global WHERE key='settings';" | grep -E '^/m/settings/(version|last_ui_version)'
```
Expect one row, 147 non-tuning lines, `/m/settings/version 1`, and a
`last_ui_version` matching the running firmware. A `last_ui_version` other than
`"2.0.8"` on a 1.8.2 machine would pin the UI version I could not read (§11).

**E. User spaces**
```sh
ls -l /var/las-frontend/*.db
df -h /var
```
Confirms the one-file-per-user-space model and lets the 100 MB storage threshold (§14)
be checked against when the warning actually appears.

**F. Extension mapping — the one open item.** Export one of each item type to a USB
stick from the front panel, then:
```sh
find /media/thumbdrive -type f \( -name '*.m1*' \) -printf '%f\n' | sort
```
This closes the `.m1s` / `.m1f` / `.m1m` / `.m1c` assignment in §15 in one shot, and
reveals what type index 3 is.

**G. Effect packages**
```sh
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT count(*) FROM effects_presets;"
sqlite3 -readonly "/var/las-frontend/MOOG ONE.db" \
  "SELECT type, count(*) FROM effects_presets GROUP BY type ORDER BY 1;"
```
185 embedded presets versus whatever is installed shows how much of the library is
package-delivered.

**H. Migration ladder target, on the running binary**
```sh
md5sum /usr/bin/las-frontend
cat /etc/version
```
Only to establish which binary is running before interpreting any of the above.

---

## 18. Unexplored

Things in this region I did not reach.

1. **Migration steps 5→6 through 11→12.** Eight of the twelve ladder cases contain no
   string constants and operate on `Node`/`Param` handles addressed numerically. Each
   would need a full disassembly read of a few hundred instructions plus the node-index
   tables. The 12→13 step is half-read (it indexes a name table at vaddr 0x08a6ed0c
   whose visible entries are transform names) and 13→14 is fully read.
2. **The `.m1s`/`.m1f`/`.m1m`/`.m1c` ↔ item-type mapping** and what export type index 3
   is. Validation step F closes it trivially on hardware.
3. **`las::SnapshotType`** — which of {0,1} is autosave.
4. **The current `/m/settings/version` constant in 1.8.2.** The settings tree is built
   by one enormous routine (stack frame > 9 KB) that I did not read through.
5. **`las::MidiMapping::sanitizeAndUpgradeMidiMap`** — the MIDI map's own version
   ladder, and whether its version 14 is coincidentally equal to `/p/version` 14 or
   deliberately shared.
6. **`las::PresetMaker` / `las::PresetMakerCache`** — how a `Preset` object is built
   from the node tree, and what the cache holds. Named only.
7. **`las::Master`** — the `/m/at`, `/m/w`, `/m/xyz` live-state object, and how
   `applyMasterData` differs from `applyPresetData` / `applySettingsData`.
8. **The `sparse` load path.** The test names distinguish "Load existing preset" from
   "Load existing preset sparse", and there is a node-flag string
   `/p generatesData=1 blueprint=0 blueprintInstance=0 synthesized=0`, assembled from
   the format fragments ` generatesData=`, ` blueprint=`, ` blueprintInstance=` and
   ` synthesized=` stored consecutively at 132403044–132403110, implying `Node` has
   those four flags and that they decide what gets serialised. Not investigated.
9. **`las::FeatureFlags`** and the `--enable-feature` / `--disable-feature` names. I
   found the class RTTI name but the flag-name table eluded me; the cluster I first
   took for it turned out to be SVG attribute names and UI panel ids.
10. **Whether the `old_*` tables left behind by DDL migration (a) are ever cleaned up.**
    No `DROP TABLE old_presets` literal exists, but I did not exhaustively rule out a
    runtime-composed statement.
11. **The `.m1u` user-space export.** Whether it copies the `.db` verbatim or
    re-serialises. `*.db` sits next to the code, which suggests a file copy, but I did
    not confirm.
12. **Effect package installation.** `Added FX package : ` and `<n> items installed)`
    imply packages arrive from somewhere (USB? firmware?) and are merged. Not traced.
13. **`docs/arch/preset-format.md`** — deliberately not read, so this pass would not
    inherit its claims. It should be reconciled against §12 by someone else.
