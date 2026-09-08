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

**There is a spare core, and it is reserved.** `isolcpus=1` in the kernel command
line keeps cpu1 out of the scheduler; nothing runs there unless placed with
`taskset`. A web server on a synthesiser is only acceptable if it cannot take
cycles from audio, and here it provably cannot:

    taskset -c 1 /media/thumbdrive/moogd -addr :8080

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

The screen mirror alone saturates the audio core. It reads 1.6 MB from `/dev/fb0`
every 0.4 s, gzips it, and ships it over SSH — all on cpu0, competing with `scsynth`.
On-box the same frame is a read and a PNG encode, and it can run on cpu1.

## What is proven

Phase 1, working on hardware today:

- static ARM binary, no interpreter, no libc, 5.7 MB
- executes from the vfat USB drive (`fmask=0002` leaves it 0775)
- pinned to the isolated core, confirmed `mask=2 last-cpu=1`
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
Measured on the i.MX6, in Go, on the isolated core:

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
pauses** do not matter, because `isolcpus=1` keeps this process off the audio core
entirely. **Memory** looked like the real risk — the instrument has 508 MB with only
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

| | cpu0 (audio) | cpu1 (isolated) |
|---|---|---|
| Python bridge, screen mirror over SSH | **1.00, saturated** | 0.13 |
| `moogd` on-box, same job | **0.60-0.83**, its idle baseline | 0.20 |

The whole control surface moved off the audio core. `scsynth`'s DSP thread reads
13.0% either way, and `moogd` sits at 14 MB resident with `affinity 2, last-cpu 1`.

## What is not done

The workbench itself. The existing UI is 2369 lines of HTML/JS talking a WebSocket
protocol with **101 message types** to 4277 lines of Python. The UI is reusable
unchanged — it is the server behind it that has to be ported.

A sensible order, most valuable first:

1. **The screen mirror.** Direct `/dev/fb0`, on cpu1. Biggest win, smallest surface,
   and it removes the thing currently saturating the audio core.
2. **The always-on messages** — `status`, `meters`, `panel.screen` — plus serving the
   existing UI from the USB drive.
3. **The feature panels** — `effect.*`, `fm.*`, `sampler.*`. These are mostly OSC
   sequences that `src/moogone/` already documents and tests.
4. **Storage.** 234 GB of USB is about 40 hours of 8-channel 24-bit audio. The
   instrument could record its own outputs continuously, hold a sample library, and
   keep a preset archive — none of which fits in the 148 MB free on the rootfs.

## Build and install

    cd moogd
    CGO_ENABLED=0 GOOS=linux GOARCH=arm GOARM=7 go build -ldflags="-s -w" -o moogd .
    ssh root@<ip> 'cat > /media/thumbdrive/moogd && chmod +x /media/thumbdrive/moogd' < moogd
    ssh root@<ip> 'taskset -c 1 /media/thumbdrive/moogd -addr :8080 &'

There is no `sftp-server` on the device, so `scp` does not work — pipe through `cat`.
Nothing is written to the rootfs and nothing is replaced; removing the file from the
USB drive undoes it entirely.
