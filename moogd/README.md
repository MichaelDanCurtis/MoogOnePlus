# `moogd` — the instrument hosting its own control surface

A static Go binary that runs **on** the Moog One instead of beside it. Put it on a
USB drive, plug the drive in, and the workbench is reachable from anything on the
network with no computer in the middle.

## Why this shape

**The instrument has no interpreter.** No python, perl, lua, node or php. The
existing Python bridge can never run there, so anything on-box has to be a native
binary — and `CGO_ENABLED=0` gives a fully static one with no libc dependency at
all, which sidesteps the ABI matching that building `scsynth` for this machine
needed (`tools/README-scsynth-jack.md`).

**Run it on cpu0, NOT cpu1.** cpu1 looks free — `isolcpus=1` keeps it out of the
scheduler — and it is not: it is where `scsynth`'s audio thread runs, pinned there
by Moog's own ALSA driver at `SCHED_FIFO` 99. `taskset -p <pid>` shows only the main
thread's mask, which is how that was missed here at first. A web server belongs
beside `las-frontend` and X on the shared core:

    taskset -c 0 /media/thumbdrive/moogd -addr :8080

**Running on-box deletes the SSH layer, and with it a class of bug.** Every remote
feature currently reaches the instrument through `ssh`, and that transport has
produced: a framebuffer capture loop leaked on every reconnect, a screen feed that
never noticed it had died, a HUD push that blocked for 8.9 seconds a frame, and a
115 ms OSC round trip. On-box, `/dev/fb0` is a file, `/proc` is a file, and scsynth
is a UDP socket on localhost.

**And the remote architecture is expensive.** Measured with this binary, from the
network, while toggling the Python bridge:

| | cpu0 busy |
|---|---|
| bridge off | 0.67 – 0.87 |
| bridge on, screen mirror running | **1.00, saturated** |

The screen mirror alone saturates cpu0. That is the *shared* core, not the audio
one — `scsynth`'s audio thread is on cpu1 — so this competes with `las-frontend`,
X and the panel, not directly with the DSP. Still worth removing: it reads 1.6 MB
from `/dev/fb0` every 0.4 s, gzips it and ships it over SSH, and on-box the same
frame is an mmap copy and a PNG encode.

## What is proven

Phase 1, working on hardware today:

- static ARM binary, no interpreter, no libc, 5.7 MB
- executes from the vfat USB drive (`fmask=0002` leaves it 0775)
- runs on **cpu0**, beside `las-frontend` and X — *this line used to say "pinned
  to the isolated core, confirmed `mask=2 last-cpu=1`", which was the mistake the
  warning at the top of this file now exists to prevent*
- serves HTTP to the LAN
- queries `scsynth` over **local UDP OSC**, no SSH: 498 ugens, 105 synthdefs
- reads temperature and per-core load straight from `/proc` and `/sys`

```json
{
  "temp_c": 67.1,
  "cores": {"cpu0": 0.677, "cpu1": 0.161},
  "scsynth": {"ugens": 498, "synths": 18, "groups": 10, "defs": 105, "sample_rate": 48000.0}
}
```

## Would C++ or Rust be faster? Measured, on the chip

The only hot path here is turning a framebuffer into something a browser can show.
Everything else -- OSC, `/proc`, HTTP -- is microseconds and language-independent.
Measured on the i.MX6, in Go. (These numbers were taken while this binary was
still wrongly pinned to cpu1. They stand: the hot path is an I/O-bound
framebuffer read, which does not care which core issues it.)

```
frame 832x480, 1597440 bytes raw
  read  /dev/fb0     331.0 ms      <- 65% of the time
  BGRA -> RGBA        30.5 ms      <-  6%
  PNG (BestSpeed)    149.7 ms      <- 29%
  TOTAL              511.2 ms      = 2.0 fps
```

**Two thirds of it is an I/O-bound read that no language changes.** Framebuffer
memory is uncached on ARM and reading it back is slow in C, Rust and Go alike. Of
the rest, C or Rust would plausibly halve the PNG (system zlib rather than Go's pure
implementation) and vectorise the pixel conversion with NEON — worth perhaps 100 ms
of 511, so **a rewrite in a faster language buys about 20%**.

Against that, two changes available in *any* language, including this one:

```
  mmap + copy         12.8 ms      (vs 331.0 ms for read)   -- 26x
  bytes changed in 300ms: 0 of 1597440 (0.00%)
```

`mmap` is **26x** faster than `read()` on the term that dominates. And the
instrument's screen does not change at all unless someone is touching it, so
change-detection skips the remaining work almost always.

So the ordering is not close. The algorithmic wins are 26x and the language win is
1.2x, and the language win is only available after paying for a rewrite in something
with no standard HTTP or WebSocket server. Go also cross-compiles to a static ARM
binary in one command with no toolchain at all, which is worth remembering next to
the six attempts and several hours that building `scsynth` for this machine took.

Two arguments against Go do not survive contact with this machine either. **GC
pauses** do not matter: `isolcpus=1` reserves cpu1 for `scsynth`'s audio thread,
and this runs on cpu0, so a pause here cannot stall the one thread that must not
stall. **Memory** looked like the real risk — the instrument has 508 MB with only
76 MB available — but the measured resident size is **5.4 MB**.

The case for reaching for C or Rust would be a hot path that is genuinely CPU-bound
after the algorithmic work is done. This one is not, and it is worth re-measuring
rather than assuming if that ever changes.

## The screen mirror, built — measured on the instrument

`GET /api/screen` returns only the tiles that changed since the last call, packed
into one atlas image. `?full=1` forces the lot, which is what a new viewer needs.

```
                       tiles      grab    diff   encode    payload
full frame            130/130   19.6ms   0.0ms  226.2ms     47.6 kB
screen untouched        0/130   19.7ms   8.6ms    0.0ms      0.0 kB
```

Against the Python bridge doing the same job over SSH on cpu0: **511 ms and 52 kB
every 0.4 s, saturating the audio core**.

Three decisions, each measured rather than assumed:

**mmap, not read.** 12.8 ms against 331 ms for the same 1.6 MB. Two thirds of the
old cost was the syscall path, not the memory.

**Diff by tile.** 832 = 13x64 and 480 = 10x48, so the frame divides exactly and no
tile is partial. Comparison is row-wise `bytes.Equal`, a few memcmps per tile rather
than a per-pixel loop, and it costs 8 ms for the whole frame. A synthesiser's screen
changes nothing at all unless somebody is touching it, so this is the win that
matters: zero encode, zero bytes.

**One atlas, not one PNG per tile.** Encoding tiles individually is the obvious
design and it is much worse — 130 separate PNGs took **784 ms and 100 kB**, against
150 ms and 52 kB for a single whole-frame PNG, because each carries its own header
and its own zlib stream. Packing the changed tiles into one image pays that once:
**226 ms and 47.6 kB**, better than the whole frame on both counts, while keeping the
property that only changed pixels are sent.

## The real Vox UI, served by the instrument — working

The instrument now serves the actual workbench from its USB drive, over a WebSocket
it terminates itself, with no computer in the middle.

```
2026/09/08 moogd on :8080, UI from /media/thumbdrive/vox, scsynth at 127.0.0.1:57110
2026/09/08 client connected (1 now)
```

Confirmed in a browser on another machine: header reads `connected`, the scsynth dot
is lit from a real `/status` over localhost, and the display mirror arrives as a
69 kB PNG at its true 832x480 on both the standalone figure and the one inset into
the panel photograph.

**The UI is unchanged.** Its `handle` is a switch that ignores message types it does
not know, so a server can implement a useful subset and the page degrades rather
than breaks. `status` and `panel.screen` are implemented; the rest of the 101 types
are not, and the panels that need them are simply empty.

Two details cost a round each and are worth writing down. The UI opens its socket on
**`/`** -- the same path it fetched the page from -- so the root handler has to
decide by the `Upgrade` header rather than by path. And `panel.screen` carries a
**whole-frame** PNG, so that is what is sent; the tile diffing still does the work
that matters, which is deciding *whether* to send at all.

### What it costs

Measured from the network, with a live client watching the display:

| | cpu0 (shared) | cpu1 (audio) |
|---|---|---|
| Python bridge, screen mirror over SSH | **1.00, saturated** | 0.13 |
| `moogd` on-box, same job | **0.60-0.83**, its idle baseline | 0.20 |

Read this carefully: **cpu1 is the audio core**, and the 0.20 in the bottom right was
`moogd` sharing it with the DSP thread, because it was started with `taskset -c 1` on
the mistaken belief that cpu1 was spare. It runs on cpu0 now. What the table does
show is the Python bridge saturating the shared core, and the on-box version not.

---

# What it serves

| Page | What it is |
|---|---|
| **`/engine`** | **Add DSP the instrument cannot reach.** The reason this exists. |
| **`/patch`** | The patch designer — a signal chain, compiled on the instrument |
| **`/meter`** | A meter on the main pair, read inside `scsynth` |
| **`/diag`** | What the instrument will not tell you about itself |
| **`/matrix`** | The modulation-matrix composer (composes; does not send — see below) |
| `/` · `/ws` | The Vox UI from the USB drive, over a WebSocket this binary terminates |

<details>
<summary><b>The JSON API behind them</b></summary>

```
/api/engine          /api/engine/add      /api/engine/remove   /api/engine/set
/api/engine/graph    /api/engine/chain    /api/engine/reset
/api/chain           /api/preset          /api/presets
/api/meter           /api/scan            /api/record
/api/tree            /api/lassc           /api/diag
/api/modmatrix       /api/modmatrix/write
/api/status          /api/screen          /health   /bench
```

</details>

---

# The Engine — `/engine`

**DSP that is already in the instrument, and that the instrument cannot reach.**

`scsynth` loads 96 plugin binaries at boot and registers **795 UGens**. The
`sclang` beside it runs against a 195-file class library — and **435 of those
UGens have no class in it.** The machine cannot name them, cannot write them into
a SynthDef, and never has.

`ReverbUGens.so` is on that list *in its entirety*:

> **FreeVerb, FreeVerb2 and GVerb are resident, registered, and unnameable from
> the instrument.** They have been loaded into memory on every Moog One ever
> booted, and nothing has ever been able to ask for them.

**The way in is that `scsynth` resolves a UGen by _name_** when a definition
arrives over `/d_recv`. It never consults the class library — that is the client's
problem. So a SynthDef compiled *elsewhere*, by a real `sclang` with the real
classes, works: the server only ever sees the string. Definitions are built on a
workstation by `tools/build-engine-synthdefs.py` and embedded here as bytes.

### Three rules this file exists to keep

| | |
|---|---|
| **1. Free nothing we did not create.** | `/n_free` on a LADSPA node **terminates `scsynth`**. The instrument keeps ten permanently resident — the Eventide reverbs, *moved* between groups rather than created, precisely because freeing them is fatal. Only ids this process allocated are ever freed, from a range nothing else uses. |
| **2. Moog's rack is not touched.** | The five effect slots and their groups are left exactly alone. Everything goes at the **tail of the root group**, after all of it, replacing the main pair on the way out. |
| **3. The audio core decides.** | An effect is refused if the realtime thread has no room. A dropout is worse than a missing reverb — and **this instrument's throttle has fired three times.** |

## Building a SynthDef without `sclang`

Two files, two different problems:

- **`scsyndef.go`** reads and writes SuperCollider's compiled format, byte for
  byte. Until it existed, this project produced those bytes by shelling out to a
  real `sclang` on a workstation — deliberately, because
  `src/moogone/synthdef.py` says why: *"an unverifiable encoder is the
  confident-looking wrong answer this codebase keeps finding."*
- **`graph.go`** constructs one from nothing. It does **not** try to match
  `sclang`'s bytes, and should not — `sclang` runs an optimiser, and matching its
  output would mean reimplementing that too.

## The patch designer — `/patch`

A **chain**, not a node graph. The node-graph editor is the obvious thing to build
and the wrong thing to use: drag-to-connect is fiddly on glass — the same argument
that kept it out of the matrix editor — and an arbitrary graph can be wired into
nonsense. A chain cannot. It is ordered by construction, so there are no forward
references and no unconnected inputs, and it is how a musician already thinks.

---

# Watching what it does

The instrument is far more observable from the inside than anyone assumed, and
each of these exists because something went wrong without it.

**`/meter` — the main pair, measured inside `scsynth`.** Born from
`docs/INCIDENT-2026-09-12-runaway.md`: a sound that would not stop, chased through
four theories, three of them wrong, over an evening — while the signal sat
observable inside the server the whole time and nothing was looking at it.

**`/api/record` — the main pair to a file.** The meter answers *how loud, now*. It
cannot answer *what is that* — a pitch, a filter self-oscillating, an envelope
that never closes. Polled over HTTP it tops out near 5 Hz, and on 2026-09-13 that
produced two contradictory pictures of the same fault: one trace showing a level
flat for seven seconds, another showing it decaying to the floor over the same
seven.

**`/api/tree` — the node graph as it actually is.** `docs/firmware/las-fx.md`
derives the topology from `init_sc_1.scd` and marks it `[INFERRED — firmly]`. It
also predicts a specific defect — an eleventh Eventide node, orphaned when
`~initEffect` takes the insert branch the first time a bus slot changes — and says
what would settle it: *"confirming it needs a live `/g_queryTree`."* This is that.

**`/api/lassc` — asking `las-sc` a question.** The voice allocator lives behind the
XMOS and Linux cannot see MIDI, so how many voices are sounding was unobservable
for an entire session; every stuck-note finding was inferred from a level meter.
But `las-sc` serves `/info/voice-count` and `/v/voices` on `127.0.0.1:9300`, which
this binary can reach. It had been reporting the answer the whole time.

**`/diag` — what the front panel will not tell you.** Firmware version and
temperature are what the instrument shows. This reads the numbers that decide
whether the next thing you do works, including the realtime headroom and the
throttle count — and it can, because it runs *on* the instrument, where `/proc`
and `/sys` are just files.

## Reset, at two levels

Kept separate because they carry very different consequences and one button would
hide that.

| | |
|---|---|
| **Soft** | Frees every node this process created and rebuilds the meter. Instant, cannot hurt anything, and the one to reach for. |
| **Hard** | `/etc/init.d/S42sc restart`. Restarts Moog's audio engine. **Never `/sbin/reboot`** — that wedges the USB link and needs the power removed. |

---

# Build and install

    cd moogd
    CGO_ENABLED=0 GOOS=linux GOARCH=arm GOARM=7 go build -ldflags="-s -w" -o moogd .
    ssh root@<ip> 'cat > /media/thumbdrive/moogd && chmod +x /media/thumbdrive/moogd' < moogd
    ssh root@<ip> 'taskset -c 0 /media/thumbdrive/moogd -addr :8080 &'

There is no `sftp-server` on the device, so `scp` does not work — pipe through `cat`.
Nothing is written to the rootfs and nothing is replaced; removing the file from the
USB drive undoes it entirely.

**`-c 0`, not `-c 1`.** See the warning at the top of this file: cpu1 is the audio
core.

---

# The modulation matrix composer — `/matrix`

`/p/part/t/{1,2,3}/p/modmatrix/matrix_expression_slots`
is a flat array of seven-token rows — source, controller, transform, destination, and
three coefficients — and it is the *whole* modulation mechanism: the panel writes
exactly this, with no richer path behind it. The engine that evaluates it runs on the
XMOS voice controller, so **a row costs nothing on either i.MX6 core.**

What the panel does not give you is the rest of the table. The factory library of
1,329 presets reaches **71 of 126 destinations**; the other 55 have never been used by
anybody.

    GET  /matrix               the editor, built for a tablet
    GET  /api/modmatrix        the id tables, each entry marked attested or not
    POST /api/modmatrix/write  validate, and send unless dry_run

Ids come from `tables.go`, generated by `tools/gen-modmatrix-tables.py` from
`/usr/share/vx_ee.scm` — the engine's own symbol table, recovered from the v1.5.0
rootfs. `attested: false` means the id follows from its position in that table and no
factory preset has ever exercised it. The distinction is kept everywhere, including in
the UI, because "the symbol table says this exists" is a weaker claim than "we have
watched the instrument do this".

`go test ./moogd` decodes all 300 matrices in the factory corpus, re-encodes them, and
requires byte-for-byte agreement — then requires `Validate` to accept every one. A
table that rejects a preset Moog ships is a wrong table.

### What it cannot do, and why that is settled

**There is no live OSC endpoint for the modulation matrix.** An earlier version of
this file claimed one and worried about the argument encoding. The encoding was
never the problem — the address does not exist:

    las-sc, occurrences of "modmatrix"          0
    las-sc, occurrences of "matrix_expression"  0

`las-sc` is the only process listening on `127.0.0.1:9300` and the owner of `/p`,
and it has no matrix code at all. Every occurrence of that address in the firmware
is inside `las-frontend`, and every one is an embedded `.m1p` preset body — data,
not protocol. A capture of a real panel edit confirms it: nothing to 9300, and the
only `/p` traffic `las-frontend` ever sends `las-sc` is the effects-and-mixer slice.

Two further live probes closed the remaining doors. Writing an `_m` address (both
`/p/pan_m` and the prefixed form) was delivered and ignored — `_m` is `las-sc`'s
computed *output*, the modulation sum it pushes to the voice controller, not a
settable input. And `/p/pre-expr` with an RPN string was likewise delivered and
ignored.

So `matrix_expression_slots` is a **preset-file field**. Compose a matrix here,
take the token array, and write it into a preset. That is what the encoder is for,
and the round-trip test is what makes it trustworthy.

**It also cannot read the instrument back.** `las-sc` sends its replies to
`las-frontend` on `:7775` and never to whoever asked.
