# Where this instrument is leaving performance on the table, and where it is at its limit

Scope: the i.MX6 board only — its two cores, its 512 MB, its SuperCollider engine,
its boot and its update. The analog voice cards are out of scope except where they
cost the i.MX6 time.

**No instrument was contacted for this document.** Everything below is derived from
files already on local disk, plus measurements this project took earlier and recorded.
Nothing here was executed on the device, and no Moog binary was run.

## How to read the evidence grades

* **[TESTED]** — this project ran it against the instrument and observed the result.
  The run is cited.
* **[READ]** — taken directly out of a file on disk. File and line/offset are given.
* **[INFERRED]** — reasoning. The premises are named so the reasoning can be attacked.
* **unknown** — used deliberately. It is an answer.

Sizes are MiB (1024²) unless a source quotes otherwise. Percentages of CPU are
**fractions of one core**, never of both, for the reason in §1.

---

## 0. Summary

| # | Finding | Grade | Why it matters |
|---|---|---|---|
| 1 | **83.8 % of the 145 MB `las-frontend` binary is uncompressed ASCII preset text** — 121.5 MiB of `/p/part/…` lines with 20-decimal floats, 2.93 M lines, 856 distinct preset names. It deflates 9.4×. | [READ] | The single biggest resource fact on the machine. It is also the most likely explanation for the 10-minute post-update restart. |
| 2 | `las-frontend` is **JUCE on bare X11 + CHICKEN Scheme. It has no Qt dependency at all.** | [READ] | Two docs and the swarm brief say Qt. |
| 3 | **cpu1 is isolated properly** — `isolcpus=1` **plus** `nohz_full` on cpu1 **plus** RCU-callback offload, and the audio thread pinned there at `SCHED_FIFO` 99. This is better than "a reserved core". | [READ] | The isolation is not the weak link. Do not "improve" it. |
| 4 | **cpu0 runs the display pipeline at `SCHED_FIFO` 93 and 80, above every threaded IRQ's RT default.** The ESAI audio interrupt is one of those threaded IRQs. | [READ] + [INFERRED] | This is the mechanism by which screen work can disturb audio *even though* audio has its own core. |
| 5 | The RT throttle Moog tried to lift is **still on**: `S02sys:8` writes `999950` to a relative path. `sched: RT throttling activated` appears in a captured dmesg at t=1049 s. | [READ] | The ceiling is 95 %, not 100 %. Already logged as F-11; the dmesg line is new corroboration in a performance context. |
| 6 | **Parking the ten Eventide instances costs approximately nothing in CPU** — of order 0.004 % of a core, and well under 0.5 % even at a 100× error — and Moog's reason for it is not CPU, it is that LADSPA `instantiate()` cannot be run from the audio thread. | [INFERRED] | Kills a recurring "free 280 ugens" idea. |
| 7 | **An eleventh Eventide node exists in the live graph, created by Moog's own code**: two `et_room_1` synths in `~eventideGroup` (node 1017 and node 1034) in all three captured `/g_queryTree` dumps. | [TESTED] | Live evidence for the LADSPA node leak `effects-engine.md:228-241` called latent. |
| 8 | The redundant arithmetic in `outputRouter`/`inputRouter` is real but small: **~1–2 points of one core**, and fixing it changes the aux gain structure. | [INFERRED] | "Optimise the SC graph" is not where the headroom is. Say so and stop. |
| 9 | `Out.ar` → `ReplaceOut` **buys nothing here**, because scsynth's `Out` already copies rather than accumulates on the first write of a block. | [INFERRED] | Closes a question the brief raised. |
| 10 | **`CPU_COST` in `src/moogone/effect.py` is a block-256 measurement being used on a block-128 instrument** and under-reads by roughly 5–10 % relative. | [READ] | Every "does this effect fit" decision uses it. |
| 11 | The firmware-update staging area has **12.19 MiB of margin on a 788.31 MiB requirement** (1.5 %). | [READ] | A 2 % larger image fails the update. |
| 12 | **Two DHCP clients run on `ethext` at once** (`udhcpc` from `S40network`, `dhcpcd` from `S95dhcpd`), which is why the interface carries two addresses. | [READ] | Trivial cost, real confusion. |
| 13 | Three `xterm`s and `las-dwm` **stay alive forever on this unit** because `S99final` exits early when `/media/thumbdrive/k` is present. | [READ] | The dev key does not just enable SSH; it leaves the boot's cleanup undone and `/` writable. |
| 14 | `~fxEnableCheckRoutine` zombies push **100 OSC messages/s each into scsynth's realtime thread**, forever, per occurrence, up to five from a clean boot. | [READ] + [INFERRED] | The only cpu1 waste with a plausible path to a full percentage point. |
| 15 | **Block size 128 is correct.** The retraction stands, and §6 gives the arithmetic rather than the assertion. | [TESTED] + [INFERRED] | Do not revisit this. |

**The blunt headline.** The stock instrument has roughly **3–7 points of one core** between
a maximal factory patch and the throttle, and every optimisation available inside the
audio engine is worth **1–2 points**, at the cost of editing files that a firmware update
overwrites. *There is no safe win in the DSP.* The genuine headroom is on cpu0, in
memory, and in boot/update time — none of which is where a synthesizer owner feels it.

---

## 1. How to measure anything on this machine

Three instruments on this box are broken, and this project has published wrong numbers
from two of them. Any figure quoted anywhere must say which method produced it.

**`/status.reply` CPU is dead.** `avg_cpu` and `peak_cpu` read exactly `0.000` on this
build while the process is demonstrably running audio.
[TESTED] — `src/moogone/load.py:3-6`, polled four times against a thread measured at
82 % of a core.

**busybox `top` reports a fraction of BOTH cores.** It said 42 % for a thread measured
at 82 % of one. Every `top` figure from this instrument is half the number that matters.
[TESTED] — `docs/CLAIMS-AUDIT.md:28`, `src/moogone/load.py:10-12`.

**`/proc/stat` per-core aggregates did not move when the load moved.** Twelve samples
read `cpu0=100 % cpu1=33 %` identically before and after a reverb started.
[TESTED] — `docs/MOOG-ONE-INTERNALS.md:2181-2195`. A figure that does not respond to the
load is not measuring the load. Do not use per-core `/proc/stat` here.

**There is no `getconf`,** so `CLK_TCK` is unknown, and timing the sample against
`/proc/uptime` put a single thread at 107 % of a core.
[TESTED] — `src/moogone/load.py:13-18`.

### The one method that is sound

`moogone.load` (`src/moogone/load.py:54-68`). Two reads of
`{ /proc/stat ; /proc/<pid>/task/*/stat }` separated by a `sleep`, differenced by one
`awk` afterwards. The busiest thread's `utime+stime` delta is divided by
`(total jiffies delta) / (number of cpuN lines)`, i.e. by exactly one core's worth of
jiffies over the same interval.

Why it is sound: the clock and the counter come from the **same read**, so nothing can
drift between them, and `CLK_TCK` cancels out of the ratio. It reports the **busiest
thread**, which is the right unit because the RT throttle is a per-thread phenomenon and
scsynth does its DSP on one thread.

### The trap that invalidated an earlier sweep, restated

**An effect's cost cannot be measured on an engine that is already near the throttle.**
Past 95 % the kernel deschedules the thread, and a difference taken across that ceiling
records the ceiling, not the work. Measured against an 82 % baseline every Eventide
reverb came back at 12–15 %; measured on an idle engine the same five came back at
23–33 %. [TESTED] — `src/moogone/effect.py:186-192`, `docs/CLAIMS-AUDIT.md:29`.

**And a caveat nobody has recorded.** `src/moogone/effect.py:192` says that idle sweep
was taken at a *"12-13 % baseline, 519 ugens"*. `docs/CLAIMS-AUDIT.md:20` and
`docs/arch/doc-audit.md:1302` both identify 12–13 % as the **block-size-256** figure;
the block-128 idle baseline is 16.6 %. So:

> **`CPU_COST` is a `-z 256` measurement being applied to a `-z 128` instrument.**
> [READ] — the one paired data point in the repo is `et_plate_1` at **+29 % at 128**
> against **+27 % at 256** (`docs/MOOG-ONE-INTERNALS.md:1645-1646`), so the table
> under-reads by roughly **5–10 % relative**.

Corrected to the shipped block size, the Eventide family is approximately
shimmer 0.35, hall 0.30, plate 0.28, blackhole 0.27, room 0.25. [INFERRED] — one
ratio applied to five measurements; re-run `recon/effect-cpu.py` on the restored
instrument to replace this with data.

---

## 2. The two cores

### 2.1 What the kernel was actually told

[READ] `captures/arch-harvest/runtime-state.txt:2` and `captures/dmesg-before-reboot.txt:21`:

```
console=ttymxc1,115200{smp} root=/dev/mmcblk2p3 rootwait isolcpus=1 quiet loglevel=0
galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1
```

[READ] `captures/dmesg-before-reboot.txt`:

```
Linux version 4.1.15-rt18 ... #1 SMP PREEMPT RT Mon May 16 10:55:36 EDT 2022
Machine model: Variscite i.MX6 DL/Solo SOM-SOLO SOM-DUAL SoloCustomBoard
RCU: Adjusting geometry for rcu_fanout_leaf=16, nr_cpu_ids=2
NO_HZ: Clearing 0 from nohz_full range for timekeeping
NO_HZ: Full dynticks CPUs: 1.
        Offload RCU callbacks from CPUs: 1.
L2C-310 cache controller enabled, 16 ways, 512 kB
```

That is more than `isolcpus`. **cpu1 is `nohz_full` and its RCU callbacks are offloaded
to cpu0** — the kernel was configured with `NO_HZ_FULL_ALL` and then cleared cpu0 for
timekeeping. Together with `skew_tick=1`, `PREEMPT_RT`, `isolcpus=1`, and Moog's own
patched `SC_AlsaDriver` pinning the audio thread, this is a **textbook realtime audio
isolation, done deliberately and done right**. [READ] for the lines, [INFERRED] for
`NO_HZ_FULL_ALL` being the source (the "Clearing 0 … for timekeeping" message is that
option's signature).

**Do not touch this.** The four `rcuop/1 rcuos/1 rcuob/1 ktimersoftd/1` threads that
exist on cpu1 are the offload machinery working correctly.

### 2.2 cpu1 — is there headroom?

[TESTED] Per-thread affinity and priority of the live `scsynth`
(`docs/MOOG-ONE-INTERNALS.md:2209-2213`):

```
tid 1294  affinity=1  last-cpu=0  jiffies=151     policy/prio=1/94
tid 1318  affinity=1  last-cpu=0  jiffies=2306    policy/prio=1/94
tid 1340  affinity=1  last-cpu=0  jiffies=1169    policy/prio=1/94
tid 1342  affinity=2  last-cpu=1  jiffies=71290   policy/prio=1/99   <-- audio
tid 1344  affinity=1  last-cpu=0  jiffies=2888    policy/prio=1/94
```

One thread on cpu1, at FIFO 99, doing 25× the work of the next busiest. Four other
scsynth threads (OSC receive, OSC send, non-realtime command queue) are on cpu0 at
FIFO 94 — which is *above* the IPU IRQ threads at 80 and below the IPU tasks at 93.

**The load, from the sound method:**

| state | ugens | % of one core | source |
|---|---|---|---|
| fresh boot, nothing selected | 496 | **16.6 %** | [TESTED] `docs/CLAIMS-AUDIT.md:48` |
| fresh boot, `-z 256` (not stock) | 519 | 12–13 % | [TESTED] `docs/CLAIMS-AUDIT.md:20` |
| one Eventide added, idle engine | +28 | +23…33 % | [TESTED] `src/moogone/effect.py:207-213` |
| native effect added, idle engine | varies | +1…10 % | [TESTED] same |
| leftover experimental graph | 752 | 82 % | [TESTED] `docs/CLAIMS-AUDIT.md:47` |
| throttle | — | **95 %** | [READ] `src/moogone/effect.py:240-242` |

A maximal *stock* patch is five slots: three insert effects (native, `~insertGroup`) and
two bus effects which are the only ones that can be Eventides. Corrected to `-z 128`
(§1) that is roughly:

```
16.6 (base) + 0.30 (hall) + 0.28 (plate) + ~0.17 (three inserts) ≈ 92 %
```

[INFERRED] — additive because each cost was measured on an idle engine where the
throttle was not clipping. **Headroom against the throttle is of order 3–7 points.**

Two independent facts agree that this is right at the edge:

* `sched: RT throttling activated` is in the captured dmesg at **t = 1048.96 s**
  [READ] `captures/dmesg-before-reboot.txt:330`. Something realtime hit the ceiling
  17 minutes into that session.
* Adding a *sixth* effect through a send measured **101 %** at `-z 128` and dropped out
  audibly [TESTED] `docs/MOOG-ONE-INTERNALS.md:1640-1642`.

**Answer: cpu1 is not saturated at idle, and it is close to saturated on a full patch.
There is no room on it for anything we add.**

One honest competing hypothesis about the throttle message, which the existing docs do
not raise: `S99final` puts **two `[ipu1_task]` kernel threads at `SCHED_FIFO` 93** on
cpu0. An RT task at prio 93 that ever runs hot would also trip
`sched: RT throttling activated`, and the message does not name the victim. The check is
in §8.

### 2.3 The RT throttle is still on, and it was meant not to be

[READ] `captures/arch-harvest/init.d/S02sys:8`:

```
echo 999950 > sched_rt_runtime_us
```

No directory component. BusyBox init runs `rcS` with cwd `/`, and `inittab:18` has
already remounted `/` read-write, so this creates a **file** called
`/sched_rt_runtime_us` and leaves `/proc/sys/kernel/sched_rt_runtime_us` at its 950000
default. [INFERRED, high confidence] — corroborated independently by
`src/moogone/effect.py:240-242`, which records the live value as `950000`.

This is already F-11 in `docs/arch/system-and-failure-modes.md:811-832` (F-11). It belongs here
because it is the number that sets the ceiling: **the budget on cpu1 is 95 %, not
100 %,** and Moog intended 99.995 %.

Note also `S02sys:6` sets the `performance` governor on **cpu0 only**. On i.MX6 with
`cpufreq-dt` both cores share one policy, so cpu1 inherits it — [INFERRED], and worth
confirming with `cat /sys/devices/system/cpu/cpu1/cpufreq/scaling_governor`, because if
that assumption is wrong, cpu1 is running `ondemand` under a `SCHED_FIFO` load, which
would be a real and easily-fixed defect.

### 2.4 cpu0 — what is actually competing

Every userspace process on this machine carries affinity mask 1, because `isolcpus=1`
takes cpu1 out of the scheduler's hands. [TESTED] `docs/MOOG-ONE-INTERNALS.md:2311-2321`.
So the following all share one 1 GHz Cortex-A9, read from
`captures/arch-harvest/runtime-state.txt` [READ]:

| process | why it is there | note |
|---|---|---|
| `las-frontend` | the UI, panel, OLEDs, MIDI | JUCE; software rendering (§4.2) |
| `X :0 -nocursor -s 0` | `S12splash:19` | |
| `las-dwm` | `S43gui` | **should have been killed by `S99final`** |
| `xterm` ×3 | `S43gui:11-13` | **should have been killed by `S99final`** |
| `las-sc` | voice-card controller | CHICKEN Scheme |
| `sclang` | the effects state machine | 10 Hz poll + zombies (§3.5) |
| `scsynth` ×4 non-audio threads | OSC in/out, NRT command queue | FIFO 94 |
| `screen` + `launch-sc-1` | how `las-sc` starts the audio stack | idle |
| `[ipu1_task]` ×2 | display pipeline | **`SCHED_FIFO` 93** |
| `[irq/297-2400000]`, `[irq/298-2400000]` | IPU interrupts | **`SCHED_FIFO` 80** |
| every other threaded IRQ, incl. `[irq/26-esai]` and `[irq/284-sdma]` | PREEMPT_RT threads all IRQs | RT default (50) |
| `dbus-daemon`, `avahi-daemon`, `syslogd`, `klogd`, `udevd`, `getty` | | idle |
| `dropbear` ×2, `udhcpc`, `dhcpcd` | | see below |
| `moogd` | this project's addition | `taskset -c 0`, correct |

**The one that matters.** [READ] `captures/arch-harvest/init.d/S99final:14-17`:

```
assign_ipu_pri $iputasks 93
assign_ipu_pri $ipuirq   80
devmem 0x020e0018 w 0xffffffff        # "set axi bus pri"
```

The display pipeline is deliberately promoted to `SCHED_FIFO` 93 and its interrupt to 80.
Under PREEMPT_RT **every** interrupt handler is a thread, and the untouched ones sit at
the RT default of 50 — including `irq/26-esai`, the audio interface's interrupt, and
`irq/284-sdma`, the DMA controller that actually moves the audio.

[INFERRED] **Consequence: on cpu0, display work outranks the audio interrupt.** The
audio *thread* is safe on cpu1 at 99, but the thing that wakes it is not. That is the
mechanism by which "the screen mirror saturated cpu0" was an audio problem and not just a
UI problem — and it explains why a design with a dedicated audio core still has a display
coupling. This is a hypothesis with a cheap test (§8): read `/proc/interrupts` for the
ESAI IRQ's CPU column, and `chrt -p` the `irq/26-esai` thread.

`devmem 0x020e0018 w 0xffffffff` writes IOMUXC_GPR6 on i.MX6, which is the IPU1 AXI QoS
register — the comment says "set axi bus pri" and the register address is consistent with
that. [READ] for the line and its comment; [INFERRED] for the register's identity, from
the i.MX6 reference manual's IOMUXC map. **Effect: the display gets maximum priority on
the memory bus, ahead of the audio DMA.** On a DDR3-starved dual-core this is not free.

**Things on cpu0 that are simply wrong or wasteful:**

1. **Three `xterm`s and `las-dwm` never get killed on this unit.** `S99final:30-38`
   exits early if `/media/thumbdrive/k` holds the magic value, skipping
   `killall xterm; killall las-dwm; mount -f -o remount,ro /`. The live process table
   shows PIDs 912/913/914 (`xterm`) and 1472 (`las-dwm`) still running. [READ]
   `S99final:30-44` + `runtime-state.txt` process list. The CPU cost is small; the
   *consequence* is that `/` also stays writable, which matters for every power-off.

2. **Two DHCP clients on one interface.** `S40network:13` runs `ifup -a`, which starts
   `udhcpc` on `ethext`; `S95dhcpd:9` separately runs `/sbin/dhcpcd start ethext`.
   Both are in the live process table (PIDs 929 and 1729), and `ip addr` shows
   `192.168.1.136` **and** `192.168.1.138 secondary` on `ethext`. [READ]
   `runtime-state.txt`. Cost is negligible CPU; the dual address has confused this
   project repeatedly.

3. **`ip_forward=1` plus four NAT DNAT rules** forwarding ports 7770/7771/9100/9300 from
   the LAN into the voice-card network. [READ] `S40network:17`, `S95dhcpd:11-14`. Every
   `ethext` packet traverses netfilter as a result. Trivial at idle, non-trivial under a
   burst — and §8c of INTERNALS already documents that bursts wedge this machine.

4. **`crond` is never started**, so `/etc/log-refresh` runs once per boot and never
   again, while `las-watchdog -t=10000` writes a line every 10 s forever. [READ]
   `S14fs:61` runs `crontab -c /etc/crontab -l` (a *listing*, not a daemon); no `crond`
   in any process capture. Already F-12. It is a disk and I/O drip, not CPU.

5. **`S12splash:25` is `for i in $(seq 255 $END)` with `$END` never assigned** — a
   255 ms fade loop that reads as a range and is not one. [READ]. Costs 255 ms of boot.

**Answer to "is anything pinned wrongly, niced wrongly, or spinning?"** Nothing is pinned
wrongly (once `moogd` moved to `taskset -c 0`). Nothing is niced wrongly. Two things
spin: the immortal `~fxEnableCheckRoutine`s in `sclang` (§3.5), and — potentially —
whatever tripped the RT throttle. Nothing else on cpu0 is a busy loop.

---

## 3. The SuperCollider graph

### 3.1 What the boot graph actually is

[READ] `captures/arch-harvest/init_sc_1.scd:9-18` and the live command line in
`captures/moog-recon/02-processes.txt:117` (this capture predates the project's
block-size edit, so it is the **stock** line):

```
scsynth -u 57110 -a 129 -i 9 -b 1026 -z 128 -Z 128 -m 100000 -w 128 -S 48000 -R 0 -C 0 -l 1
```

Node tree at boot [READ] `init_sc_1.scd:47-107`, corroborated by three live
`/g_queryTree` dumps (`captures/tree.json`, `tree-after.json`, `tree-live.json`):

```
~insertGroup   efxGroups[0..2]      3 native effects (or none_1)
~busGroup      inputRouter
               efxGroups[3..4]      2 bus effects
               outputRouter
~eventideGroup 10 parked et_* synths, run(false)
```

**A correction to the brief.** The brief says "~700-750 ugens". The measured fresh-boot
figure is **496 ugens** [TESTED] `docs/CLAIMS-AUDIT.md:48`. 752 was a leftover
experimental graph, and `docs/CLAIMS-AUDIT.md:46-48` retracts it explicitly. Use 496.

Composition of the 496 [INFERRED], from `et_plate_1 = 28 ugens` [TESTED]
(`docs/MOOG-ONE-INTERNALS.md:2172`) and `none_N` being a control-only synth with no audio
at all [READ] `synthdefs.scd:33-63`:

```
10 parked et_*      ~280 ugens   ~57 %   contributing ~0 % CPU (§3.2)
5 × none_N          ~50 ugens            contributing ~0 % CPU
inputRouter + outputRouter  ~166 ugens   ~all of the live audio-rate work
```

So **more than half the ugen count is parked and free, and essentially all the idle CPU
is the two routers plus fixed driver overhead.** That reframes the whole optimisation
question: the graph is not big, it is two synths and a parking lot.

### 3.2 What parking costs, and why Moog does it

**CPU cost of a parked node: approximately zero.**

`.run(false)` sets the node's `mCalcFunc` to `Node_NullCalc`; the group's calc function
still walks its doubly-linked child list and makes one indirect call per child, and that
call returns immediately. [INFERRED] from upstream SuperCollider's `Node_SetRun` and
`Group_Calc` — the shipped `scsynth` binary is not in this harvest, so this is a
reasoning claim about standard scsynth, not a read of Moog's build.

Arithmetic: 11 parked nodes × 375 blocks/s × ~10 cycles per indirect call ≈ 41 k
cycles/s against ~1 × 10⁹ = **0.004 % of one core**. Even a 100× error in the
per-call estimate leaves it below half a percent. [INFERRED]

**Freeing them instead would be worse, for three separate reasons:**

1. **`/n_free` on a LADSPA node terminates `scsynth`.** [TESTED] confirmed 2/2,
   `docs/CLAIMS-AUDIT.md:32`. Moog's design never frees them, so Moog never hits it.
2. **`doneAction` is the load-bearing invariant.** The ten `et_*` defs use
   `doneAction: 1` (pause); the other 26 use `doneAction: 2` (free). [READ]
   `synthdefs.scd:3407` (`et_blackhole`) against `synthdefs.scd:49` (`none_N`). Setting
   `enable = 0` on a native effect *frees* it; on an Eventide it *pauses* it. That
   asymmetry is what makes the swap-by-moving design work at all.
3. **The real reason, and it is a realtime one.** Creating a LADSPA node means calling
   the plugin's `instantiate()` and `activate()`, which allocate and clear the reverb's
   delay lines. Those calls use the plugin's own allocator, not scsynth's realtime pool,
   and `/s_new` is executed on the audio thread. A `malloc` plus a multi-hundred-kilobyte
   `memset` inside a 2.667 ms deadline is a dropout. **Parking pre-pays that cost once,
   at boot, where a dropout is invisible.** [INFERRED] — from the LADSPA API contract and
   scsynth's command-execution model; the `.so` files are not in this harvest, so the
   delay-line sizes are **unknown**.

`~initEffect` then swaps by **moving** the already-instantiated node between groups —
`moveToTail(~efxGroups[unitNum])` in, `moveToTail(~eventideGroup); run(false)` out
[READ] `efx_server.scd:248-260`. A pleasant side effect noted in
`effects-engine.md:540-541`: the plugin's internal state survives the swap.

**Conclusion: parking is correct engineering and the ten parked nodes are not a
resource to reclaim.** Anyone proposing to free them is proposing a crash.

### 3.3 The eleventh reverb — live evidence of the leak

[TESTED] All three captured `/g_queryTree` dumps show **eleven** `et_*` nodes, not ten:
node IDs 1015–1024 are the ten created in `init_sc_1.scd`'s exact order, and there is an
**extra `et_room_1` at node 1034**, parked in `~eventideGroup` alongside the original
`et_room_1` at node 1017.

```
captures/tree.json         1014 (group) kids=10 → ... 1017 et_room_1 ... 1034 et_room_1
captures/tree-after.json   same
captures/tree-live.json    same
```

Node 1034 was allocated from sclang's own 1000-block, immediately before the current
insert effects (1035–1038). This project's own tooling uses node IDs 96100+, 1100+ and
91000+ [READ] `src/moogone/effect.py:34,43`, so **1034 is not ours**.

`docs/arch/effects-engine.md:228-241` describes exactly this as "the single most
dangerous latent path in the file": `~initEffect`'s `\ins` branch is three lines that do
nothing but `Synth(effect, …)`, with no knowledge of `~eventides` and no free or park, so
an Eventide requested on an insert-category slot instantiates a **second** live LADSPA
node. **The evidence says it is not latent; it has happened at least once on this
instrument.** [TESTED] for the observation, [INFERRED] for the attribution to that branch.

Cost: one extra parked node (≈ 0 CPU) plus one extra LADSPA instance's delay-line memory
out of scsynth's realtime pool, size unknown. Consequence if it recurs: the pool is
finite, and every occurrence is permanent until `S42sc restart`.

### 3.4 Genuine waste in the two routers

All of this is [READ] from `captures/arch-harvest/synthdefs.scd`. SuperCollider's
`SynthDef` builder does **no common-subexpression elimination** — an expression written
twice becomes two UGens [INFERRED, from SC's graph construction, which folds `MulAdd` and
drops dead branches but never shares equal subtrees].

**(a) The mono fold of each insert is computed four times.**
`synthdefs.scd:517-555`: `0.5 * (insert1[0] + insert1[1])` appears once per aux, four
times, and likewise for `insert2` and `insert3`. That is 12 add-and-scale pairs where 3
would do — **18 wasted audio-rate UGens.**

**(b) Every aux is computed in stereo and then summed to mono.**
`dry_dir1..3` are `Pan2.ar(...)` [READ] `synthdefs.scd:473-475`, so adding them into an
otherwise-mono aux expands the whole sum to two channels; `Out.ar(5, aux1.sum)`
[READ] `:564-571`] then folds it back. Each aux therefore runs its ~10 binary operations
**twice**. Roughly **40 more wasted audio-rate UGens**, and it is also the cause of the
documented +6 dB insert-into-aux level error (`docs/arch/audio-graph.md:29`, item 4) —
the mono term is duplicated into both channels and then added to itself.

**(c) `dry_dir4 = 1`,** a bare DC constant, summed into all four auxes
[READ] `synthdefs.scd:476`. Four audio-rate adds of a constant, plus the correctness
hazard `docs/arch/audio-graph.md:27` (item 2) already documents.

**(d) A dead `EnvGen` that is also a footgun.**
`inputRouter` computes `env = EnvGen.kr(Env.asr(0.1,1,0.1), enable, doneAction: 2)`
[READ] `synthdefs.scd:377`] and then **never uses `env` again**. Its only effect is the
`doneAction`: setting `enable = 0` on the input router **frees the input router**. Same
pattern in `none_N` (`:49`) and `\default` (`:83`), where the whole synth is nothing but
that EnvGen. Cost: negligible. Value as a trap: high.

**(e) Audio-rate lags on what is a gate.** `synthdefs.scd:277-278` and `:289-290` run
`Lag.ar` on the 0/1 output of `DetectSilence.ar` for each send. Two audio-rate
one-pole filters where `Lag.kr` would be indistinguishable. Two UGens' worth.

**(f) `InFeedback.ar` on buses 60/61 with `par_amount` defaulting to 0**
[READ] `synthdefs.scd:362` and `:371`] — two `InFeedback` UGens plus multiplies and adds
running unconditionally to contribute silence in the default configuration.

**(g) Eight single-channel `Out.ar` UGens** where two multichannel ones would do
[READ] `synthdefs.scd:564-571`], and four more in `inputRouter` (`:380-385`).

**What it all adds up to.** Take the two measured idle points and fit
`cost(z) = A + B/z`:

```
z=128:  A + B/128 = 16.6      →   A ≈ 8.4   (per-sample work)
z=256:  A + B/256 = 12.5      →   B/128 ≈ 8.2  (per-block overhead at z=128)
```

[INFERRED] from two [TESTED] numbers and a two-term model. All of (a)–(g) is per-sample
work, i.e. inside the ~8.4 points, of which the routers are perhaps 3–4 points. Removing
roughly a third of the routers' UGens therefore buys **about 1–1.5 points of one core**;
being generous about the model error, call it **1–2 points**.

**That is not worth doing on a stock instrument.** It requires editing
`/usr/share/las-fx/synthdefs.scd` and recompiling the defs, it does not survive a
firmware update, and fixing (b) properly changes the aux send level by 6 dB — i.e. it
changes the sound. One point of a core does not buy that.

### 3.5 The one cpu1 waste worth caring about: OSC into the audio thread

[READ] `efx_server.scd:1005-1026`. `~fxEnableCheckRoutine` loops at `0.02.wait` — 50 Hz —
sending `synth.get(\enable, …)` and `synth.set(\enable, 0)` on each pass, and exits only
when the reply says `enable == 0` or the node ID reads 0. The reply is asynchronous and
its callback writes a closure variable that the *same iteration* has already tested.

If the target node has already freed itself — which is exactly what a `doneAction: 2`
native effect does the instant `set(\enable, 0)` lands — the `get` never gets a reply,
the captured `enable` stays 1, and **the routine loops at 50 Hz forever with no handle
to stop it**. `docs/arch/effects-engine.md:780-792` documents this as §6.2 and estimates
**up to five immortal routines from a clean boot**, at **100 msg/s each**.

The performance consequence that section does not draw:

> scsynth receives OSC on a separate thread but **executes** commands by draining a FIFO
> at the top of each block, **on the realtime audio thread**. [INFERRED, from scsynth's
> `mOscPacketsToEngine` design.] Five zombies at 100 msg/s is 500 messages per second
> arriving into a 375 Hz block loop — **1.3 node-tree lookups plus a reply per block,
> forever**, plus a `/fail` on each `n_set` to a node that no longer exists, plus the
> matching log line.

This is the only mechanism found that puts avoidable, unbounded work **on cpu1**. It is
also the only one where the fix is small: give `~fxEnableCheckRoutine` an iteration cap.
It still needs an edit to a file a firmware update overwrites.

### 3.6 Questions the brief raised, answered

**`Out.ar` versus `ReplaceOut`: no win.** scsynth's `Out` checks
`mAudioBusTouched[bus] == bufCounter` and **copies** if the bus has not been written in
this block, accumulating only if it has. [INFERRED, upstream scsynth `Out_next_a`.] For
buses 0–7 `outputRouter` is the only writer, so `Out` already behaves as `ReplaceOut`.
Switching would save nothing and would break the moment a second writer appeared.
`In.ar` has the mirror behaviour — it fills zeros from a bus not yet touched this block
— which is *why* node order is load-bearing (`docs/arch/audio-graph.md:106-112`).

**Duplicated buses: none found.** The only literal private buses anywhere in
`synthdefs.scd` are 50/51, 52/53, 54/55, 56/57, 58/59, 60/61, 62/63 — three insert
returns, two router-to-bus-effect paths, two bus-effect returns. [READ], corroborated
independently by `docs/arch/extension-points.md` §5.3. Nothing is allocated twice.

**Control-rate opportunities: (e) above, and nothing else material.** The routing
coefficient arrays are already control-rate; multiplying an audio signal by a k-rate
coefficient is unavoidable if the coefficient is to be settable.

**A phantom input channel.** `scsynth -i 9`, but the sound card is 8 channels in each
direction: [READ] `captures/dmesg-before-reboot.txt` — `ASoC: min ch 1 max ch 8`,
`setting tdm slot # : 8`, `setting tdm masks : 255, 255` — and `jackd` on the same card
published exactly 8 capture and 8 playback ports [TESTED]
`docs/MOOG-ONE-INTERNALS.md:2422`. So **input bus index 8 can never carry hardware
audio.** Harmless; costs one 128-float buffer. Recorded because it is a persistent source
of confusion in the bus map.

---

## 4. Memory

### 4.1 The map, and what is actually free

[READ] `captures/dmesg-before-reboot.txt`:

```
Reserved memory: created CMA memory pool at 0x1c000000, size 320 MiB
Memory: 179944K/524288K available (7095K kernel code, 327K rwdata, 2216K rodata,
        332K init, 473K bss, 16664K reserved, 327680K cma-reserved, 0K highmem)
```

**320 MiB of the 512 MiB is a CMA pool.** The kernel's "179944K available" line is taken
*before* CMA pages are released back to the buddy allocator, which is why
`/proc/meminfo` then reports `MemTotal: 507956 kB`. CMA pages are usable for movable
allocations — page cache, tmpfs, anonymous memory — and are migrated out when a DMA
client (IPU, GPU, VPU) claims a contiguous run. [INFERRED, standard Linux CMA behaviour.]

Three snapshots of the same machine, all [READ]:

| capture | when | MemFree | MemAvailable | Buffers | Cached |
|---|---|---|---|---|---|
| `captures/sysmap/01-hardware.txt:31-40` | shortly after boot | **240,716 kB** | 263,568 kB | 808 | 44,752 |
| `captures/moog-recon/01-system.txt` | 2 min uptime | **4,268 kB** | — | 36,080 | 86,288 |
| `captures/arch-harvest/runtime-state.txt:194-198` | with `moogd` running | **11,192 kB** | 96,684 kB | 32,692 | 72,176 |

**The honest reading:** free memory on this machine is not a stable quantity, and
`MemFree` near zero is not by itself alarming, because a large part of it is reclaimable
page cache. `MemAvailable` fell from **263 MB to 97 MB** between the first and third
snapshots. Roughly **166 MB of non-reclaimable memory appeared**, and nothing in the
captures identifies it.

`docs/arch/system-and-failure-modes.md:885-891` attributes `MemFree 240776 kB` to
`captures/moog-recon/01-system.txt`. That file says `4268`. The 240 MB figure is in
`captures/sysmap/01-hardware.txt:31`. **A citation error worth fixing** — the conclusion
survives, the pointer does not.

**No swap, by three separate mechanisms** [READ]: `S02sys:7` sets
`/proc/sys/vm/swappiness` to 0; `inittab:34` runs `swapoff -a` at shutdown; `fstab`
declares no swap device; and all three `free` outputs show `Swap: 0 0 0`. There is **no
zram** either — `lsmod` in `runtime-state.txt` lists **no modules at all** (the kernel is
monolithic). So an allocation failure is an OOM kill, not a slowdown. `kswapd0` exists
and can only reclaim page cache.

**Does anything grow?** Not resolvable from these captures — they are three different
boots, not a time series. The candidates with a mechanism are: the immortal sclang
Routines of §3.5 (a Routine each, small); leaked LADSPA instances of §3.3 (one reverb's
delay lines each, size unknown); `/var/log` under `las-watchdog`'s 10-second polling with
`crond` never started (disk, not RAM). **The measurement that would settle it is in §8.**

### 4.2 `las-frontend` — 145 MB, and what is really in it

This is the most useful thing in this document, and it is entirely local ELF analysis.

**Program headers** [READ], parsed from
`captures/arch-harvest/las-frontend` (145,070,812 bytes on disk):

| segment | file offset | filesz | memsz | flags |
|---|---|---|---|---|
| `LOAD` | 0x00000000 | **145,054,360** | 145,054,360 | R-X |
| `LOAD` | 0x08a55a98 | 15,080 | 58,416 | RW- |

So: **one 138.33 MiB read-only file-backed mapping, and 57 KiB of writable data.**

That mapping is `MAP_PRIVATE` from the file, demand-paged, and every page of it is
**clean** — the kernel can drop it and re-read it from eMMC at any time.
[INFERRED, ELF/mmap semantics.] **Its contribution to anonymous memory is zero**, and
its RSS is exactly however much of it has been touched. Whoever asked "how much of the
145 MB is actually mapped": all of it is mapped, essentially none of it is *committed*,
and the resident share is a page-cache question, not a footprint question.

**Section headers** [READ], same file:

| section | size | share of file |
|---|---|---|
| `.text` | 10,662,996 | 7.35 % |
| `.rodata` | **133,454,554** | **92.0 %** |
| `.ARM.extab` + `.ARM.exidx` | 898,136 | 0.6 % |
| `.data` + `.bss` | 53,288 | 0.04 % |

There is **no `.symtab`, no `.strtab`, no `.debug_*`** — the binary is fully stripped.
The 145 MB is not debug bloat.

**What is in `.rodata`.** Scanning it in 64 KiB blocks for ≥98 % printable-ASCII content
finds two runs of ≥256 KiB totalling **121,503,744 bytes = 91.0 % of `.rodata` and
83.8 % of the whole binary**, the larger being one contiguous 119,341,056-byte region at
file offset 0x00a44b60. The two runs sit inside one 121,569,280-byte span,
0x00a44b60 – 0x07e34b60, separated by a single 64 KiB gap. Inside it [READ]:

```
/p/part/t/2/p/e1/r 1.06166183948516845703
/p/part/t/2/p/e1/rk 1.00000000000000000000
/p/part/t/1/p/seq/n/l/0/s/42/g 0.50000000000000000000
/version 8
/package "0x1001C"
/fx/name "SCRATCH THIS VINYL"
```

Measured over that region:

* **2,925,253 newlines**, average line 41.6 bytes
* **2,907,687** occurrences of `/p/part/`
* **856 distinct** quoted `/name "…"` values — `1980 VHS STRINGS`,
  `ACHIEVING BLIP IN BRASS`, `330 STRINGS`, `RICH CHORUS` … i.e. factory preset names
* **771,254** occurrences of the literal `0.00000000000000000000`

**`las-frontend` carries the entire factory preset library compiled in, as
uncompressed ASCII, with every float written to twenty decimal places.**

**How much of that is slack:** deflate level 6 over the region gives
121,569,280 → **12,983,369 bytes, a 9.4× ratio**. [TESTED — run locally on the harvested
binary, not on the instrument.] So **103.6 MiB of the 138 MiB binary is encoding
overhead**, on a root partition with 149.2 MB free
[READ] `captures/sysmap/01-hardware.txt:46`.

And it exists **twice**: the same ASCII format is stored again in the SQLite preset
databases — `captures/MOOG ONE.db` is 101,920,768 bytes and its pages contain the
identical `/p/part/t/1/p/seq/n/l/1/s/44/g 0.50000000000000000000` text [READ, verified by
locating the string in the file].

**What follows for performance:**

* Anything `las-frontend` does that walks the whole factory library touches 119 MiB of
  file-backed pages. Under memory pressure those pages get evicted and re-read from
  eMMC — on cpu0, behind `SCHED_FIFO` 93 display threads and an IPU with maximum AXI
  priority. [INFERRED]
* It is the most plausible single explanation for the ten-minute post-update restart
  (§5.3).
* It is **not** something we can change. It is inside Moog's signed binary.

**A correction that matters for anyone reasoning about this process.**
`las-frontend` links [READ, ELF `DT_NEEDED`]:

```
libasound.so.2  libX11.so.6  libXinerama.so.1  libXext.so.6  libfreetype.so.6
libcurl.so.4  libssl.so.1.0.0  libcrypto.so.1.0.0  librt  libdl  libpthread
libchicken.so.8  libstdc++.so.6  libm  libgcc_s  libc
```

**There is no Qt dependency, and no Qt symbol anywhere in the binary** (870 `juce`
symbols, 0 matches for `Qt5`/`QWidget`/`QApplication`/`QObject`). It is a **JUCE**
application drawing on **bare X11 + FreeType**, which means **all UI rendering is
software on cpu0** — JUCE's Linux backend has no GPU path. It also embeds a **CHICKEN
Scheme** runtime, the same one `las-sc` uses, which is where the expression engine lives.

That contradicts `docs/arch/control-plane.md:25` ("Qt panel/display application") and
`:245` ("**JUCE + Qt**"), and the swarm brief's "Qt frontend". See §7.

**The GPU question.** `galcore.contiguousSize=67108864` (64 MiB) and `gpumem=128M` are on
the kernel command line, and three `galcore` kernel threads are running. If JUCE renders
in software and only `xrandr -o inverted` (`S43gui:72`) uses the GPU, then up to ~192 MiB
is reserved for a device doing one rotation blit. **This is unresolved** — the X driver
in use is not in any capture. The check is in §8, and it is the largest single memory
question on the machine.

### 4.3 scsynth's realtime pool

`-m 100000` is **kilobytes**, so scsynth reserves a **97.66 MiB** realtime allocation
pool against SC's default of 8 MiB — 12× larger. [READ] the flag;
[INFERRED] the unit, from SC's documented `memSize`. It is `malloc`'d once at startup, so
its *virtual* size is committed immediately but its *resident* size grows only as
buffers, wire buffers and graph instances are allocated from it.

On a 508 MB machine that reads as ~19 % of RAM, and it is plausibly a large part of the
166 MB of unexplained non-reclaimable memory in §4.1. **It is also load-bearing**:
`docs/arch/effects-engine.md:904-906` shows that a runtime reload of `init_sc_1.scd`
would create ten more LADSPA reverbs on top of the ten parked, and the pool is what
absorbs that. **Do not shrink it without measuring `/proc/<scsynth>/status` first.**

Everything else in the command line is small: `-a 129` audio buses is 129 × 128 × 4 =
66 KiB; `-b 1026` buffer slots is tens of kilobytes of descriptors. `-w 128` wire
buffers (SC default 64) costs per-graph memory, and is presumably sized for the
21-band vocoder defs.

---

## 5. Boot and restart

### 5.1 Cold boot: about 46 seconds, and where they go

[READ] `captures/dmesg-before-reboot.txt`, kernel timestamps:

| t (s) | event |
|---|---|
| 0.85 | eMMC enumerated — `mmc2: new DDR MMC card`, `NCard 7.21 GiB`, partitions p1–p7 |
| 1.33–1.79 | ext4 recovery on p3, p6, p7 — **journal replay on every boot** |
| 2.87–3.41 | USB stick enumerated and FAT mounted |
| 4.87 | `random: nonblocking pool is initialized` (`S20urandom`) |
| 11.90–12.17 | USB gadget enumerated; `usbint` and `ethext` renamed |
| **45.29** | `fsl-esai-dai: esai startup complete!` — **scsynth opens the audio device** |
| **46.53** | `ASoC : running hardware param setup` — **audio is running** |

`docs/arch/system-and-failure-modes.md:51` already states 46 seconds; the timeline above
is the evidence for it and shows the shape: **the first 12 seconds are the kernel and
udev, and then roughly 33 seconds go to `S25xmosfw` → `S30dbus` → `S40network` →
`S42sc` (which starts `las-sc`, which starts `screen` → `launch-sc-1` → `sclang` →
`scsynth`) → `S43gui`.** `S42sc:24` alone contains an unconditional `sleep 3`.

Two boot-time observations worth recording:

* **ext4 journal recovery runs on three partitions on every boot** (`recovery required`,
  `recovery complete`, `1 orphan inode deleted`). That is the signature of a filesystem
  that is never cleanly unmounted, which is consistent with `S99final`'s
  `mount -f -o remount,ro /` being a *fake* remount (the `-f`) and with the owner's unit
  skipping even that (§2.4).
* The boot is **serialised on cookie files**. `S43gui` waits up to 100 s for
  `las-frontend`'s cookie and again for `las-dwm`'s; `S99final` waits **without a
  timeout** for `/var/las-sc.cookie`. [READ] `S43gui:26-45,49-66`, `S99final:21-27`.
  A slow `las-frontend` directly delays the window manager and the audio-engine gate.

### 5.2 The update itself: ~5 minutes, and a 1.5 % space margin

[READ] `captures/firmware-1.8.2/pkg/MANIFEST`:

```
"version" : "las-v1.8.2",  "image" : "rootfs",
"packed_size" : "156599799",  "unpacked_size" : "670012416"
```

[READ] `captures/arch-harvest/lasfwu`, the `load` path, in order:

| line | stage | bytes moved |
|---|---|---|
| 589 | `pv "$file" \| tar -xf - -C /mnt/fwu/tmpfs/` | 149.3 MiB read from USB, written to eMMC |
| 642 | `pv … \| gpg --passphrase bob --decrypt -` → `rootfs.ext4` | 149.3 MiB in, **638.97 MiB out** (OpenPGP decrypt **and** decompress) |
| 686 | `pv … \| gpg --verify IMAGE-SIG -` | **638.97 MiB read and hashed** |
| 742 | `dd if=rootfs.ext4 bs=2048 \| pv \| dd bs=2048 of=/dev/mmcblk2pN` | **638.97 MiB written to eMMC** |
| 825 | `dd if=/dev/zero of=/dev/mmcblk2 bs=1024 count=16384 seek=1024` | 16 MiB |

**Roughly 1.6 GiB of eMMC traffic and two full cryptographic passes over 639 MiB, on a
1 GHz Cortex-A9 with no crypto acceleration.** Five minutes is entirely plausible; the
per-stage split is **unknown** without instrumenting the run.

Two specific inefficiencies, both [READ]:

* **`bs=2048` through a three-process pipe.** 638.97 MiB at 2 KiB per write is ~327,000
  write syscalls, split across `dd | pv | dd`. eMMC wants writes in the megabytes.
  `bs=4M` on a single `dd` would very likely be several times faster. [INFERRED]
* **The signature is verified over the decrypted 639 MiB image**, i.e. a second full
  pass, after gpg has already authenticated the packet during decryption.

**And the space margin is 1.5 %.** `/mnt/fwu` is 861.9 MiB with **800.5 MiB available**
[READ] `captures/sysmap/01-hardware.txt:51`. The pipeline holds both the packed 149.34 MiB
and the unpacked 638.97 MiB in `/mnt/fwu/tmpfs/` at the same time (the unpacked file is
only removed at `lasfwu:792`, after the `dd`):

```
149.34 + 638.97 = 788.31 MiB needed
                  800.50 MiB available
                  ------------------
                   12.19 MiB margin  =  1.5 % of the requirement
```

**A 2 % larger rootfs image will fail to update.** Since 83.8 % of `las-frontend` is
uncompressed ASCII (§4.2), that headroom is being consumed by exactly the data that
compresses 9.4×. Worth reporting to Moog; nothing we can do about it.

(If `/mnt/fwu` did not exist, `lasfwu:46` falls back to `/var`, which has 3.3 GB free.
The fallback is safe; the primary path is the tight one.)

### 5.3 The ten-minute restart — what actually runs

The owner is told this by the manufacturer. [READ]
`captures/firmware-1.8.2/Moog One Firmware Update v1.8.2.pdf`:

> "The firmware update process may take a few minutes to complete (approximately five
> minutes). When done, you will be prompted to restart your Moog One. This restart
> process may take longer than normal as the instrument may need to update its internal
> settings (approximately 10 minutes)."

The first-boot sequence is named in `las-frontend`'s own strings, under a class called
`StartupPanel` [READ, `strings las-frontend`, in file order]:

```
12StartupPanel
POPULATING WITH FACTORY DATA...
Applying startup status
POPULATING WITH FACTORY DATA... 0%
POPULATING WITH FACTORY DATA... DONE!
UPDATING VOICE CONTROLLER FIRMWARE...
UPDATING VOICE CARD FIRMWARE...
FAILED ENUMERATING VOICE CARDS
UPDATING TUNING DATA...
VERIFYING TUNING DATA...
```

and, nearby [READ]:

```
Populating with complete factory data
Done populating with complete factory data
N3las19PopulateFactoryDataE
ZN3las19PopulateFactoryData3runEvEUlvE_
Missing timestamp column in presets table, attempting table migration to adapt old
  database to new format.
Database structure timestamp column migration was successful.
Found old effect_presets table, migrating to new format.
Settings upgrade from version "
ZN3las11MidiMapping5Pimpl33sanitizeAndUpgradeSettingsMidiMapE...
```

**So the ten minutes is four things, in this order:**

1. **`las::PopulateFactoryData::run()`** — writing the embedded factory library (§4.2:
   121.5 MiB of ASCII, 856 preset names) into the SQLite preset database, plus a schema
   migration of any existing user database. With SQLite's rollback journal and ext4's own
   journal on top, ~120 MiB of logical writes becomes several hundred megabytes of eMMC
   traffic with an `fsync` per transaction. [INFERRED — the mechanism is [READ] from the
   strings and from `captures/MOOG ONE.db` being 101.9 MB of this exact text; the *time
   split* is unknown.] **This is the most likely dominant term.**
2. **Voice-controller XMOS firmware** — `app_las_v2.1.2.bin`, 2 MiB, over SPI.
   [READ] `S42sc:4` passes `--vcfw=` and `--vcfv=33620735`, and
   `captures/sweep/core.txt` shows the live controller answering
   `/info/versionb → i:33620735`, i.e. **the version integer is the reflash trigger**.
3. **Voice-card XMOS firmware** — `app_vx_10M_v2.1.0.bin`, 164,096 bytes, **per card**:
   4 cards on an 8-voice instrument, 8 on a 16-voice
   [READ] `docs/arch/hardware-external.md:29-30`.
4. **`UPDATING TUNING DATA` / `VERIFYING TUNING DATA`** — the panel path for this is
   `/usr/bin/vxtune write -c vc -f /var/tuning.vxtune`
   [READ, a literal string in `las-frontend`].

**Note what the ten-minute figure is *not*.** The string
`THIS PROCESS WILL TAKE UP TO TEN MINUTES.` in the binary belongs to
`19WarningConfirmPanel` and sits next to
`OSCILLATOR COMPENSATION NOT DETECTED AND IS HIGHLY RECOMMENDED. THIS PROCESS TAKES UP TO
TEN MINUTES.` — that is the **oscillator-compensation calibration**, a different
ten-minute operation. Two distinct ten-minute processes exist and are easy to conflate.
[READ]

---

## 6. The block size, settled

**`-z 128 -Z 128` is stock and it is correct. Do not change it.**

**The evidence that 128 is stock** [READ]: `init_sc_1.scd:9-10` sets
`blockSize = 128; hardwareBufferSize = 128`, and the *earliest* live capture,
`captures/moog-recon/02-processes.txt:117` — taken before this project edited anything —
shows `scsynth … -z 128 -Z 128`. The `-z 256` in `captures/arch-harvest/runtime-state.txt`
is this project's own edit, already retracted and settled in
`docs/arch/doc-audit.md` §0.1.

**What raising it buys** [TESTED]: on the default graph, 16.6 % → 12–13 %, about
**4 points of one core** (`docs/CLAIMS-AUDIT.md:20`). The earlier "21 points" claim is
retracted.

**Why the win is small and where it comes from.** Fitting the two measured points to
`cost(z) = A + B/z` (§3.4) splits the idle load into ~8.4 points of per-sample work,
which block size does not touch, and ~8.2 points of per-block overhead, which halves.
The per-block half is dominated not by DSP but by **375 ALSA period wakeups per second**
— an interrupt, a thread wake, a context switch, and `snd_pcm_readi` + `snd_pcm_writei`
each time. [INFERRED]. The corroborating measurement is that *the effects themselves
barely move*: `et_plate_1` cost +29 % at 128 and +27 % at 256 [TESTED]
`docs/MOOG-ONE-INTERNALS.md:1645-1646`. A reverb's cost is per-sample; you cannot buy it
back with a bigger block.

**What raising it costs, and this is the part that decides it.**

The i.MX6 is not in the main signal path. The voices are analog and most voice audio
never enters it. Its insert effects read **straight off the ADC** and write back out
through the DAC, while a timbre with no insert effect goes to the analog main mix
**undelayed** — `outputRouter`'s digital dry path is off by default
(`timbre_1_dry = 0`, `timbre_2_dry = 0`, `timbre_3_dry = 0`, [READ]
`synthdefs.scd:424-426`).

So the i.MX6 round trip is not "latency", it is **skew between one timbre and another**:

```
capture ring (2 × Z) + one processing block (z) + playback ring (2 × Z)
  at Z = z = 128:  ~5 × 128 = 640 frames = 13.3 ms worst case, ~10.7 ms typical
  at Z = z = 256:  ~5 × 256 = 1280 frames = 26.7 ms worst case, ~21.3 ms typical
```

[INFERRED] from the ALSA parameters — `captures/arch-harvest/runtime-state.txt` shows
`period_size: 256, buffer_size: 512` while `-Z 256` was in force, i.e. a **two-period
ring**, so the stock configuration is period 128 / buffer 256. `docs/CLAIMS-AUDIT.md:19`
gives the same conclusion as a range: **8–11 ms at 128, 16–21 ms at 256.**

Ten milliseconds of skew between two layered timbres is a soft attack and some comb
filtering. **Twenty is a flam.** Four points of one core does not pay for that, and Moog
knew it: the `-z 128` line is the same file where they set every other engine parameter
deliberately.

**Could you have both?** In principle: run the *bus* effects — the reverbs, where
latency genuinely does not matter — in a second `scsynth` at a large block, and keep the
inserts at 128. That is precisely the abandoned `init_sc_2.scd` two-server design
[READ] `init_sc_2.scd:22-38,75-77`. It needs `jackd` plus a JACK-capable `scsynth` (both
of which have now been demonstrated to work on this hardware [TESTED]
`docs/MOOG-ONE-INTERNALS.md:2337-2362` and `:2404-2430`) **and a spare core, which does not
exist**. Recorded as closed, not as an opportunity.

---

## 7. Ranked optimisations

### 7.A Changes to the stock instrument — mostly: don't

The owner's instrument is restored to stock and must stay updatable. Everything in this
table except #1 and #2 lives on the root filesystem and is **destroyed by a firmware
update**, which also means every one of them has to be re-applied and re-verified after
every update, forever.

| # | Change | Expected win | Risk | Survives update | Needs instrument FS | Verdict |
|---|---|---|---|---|---|---|
| 1 | `echo 999950 > /proc/sys/kernel/sched_rt_runtime_us` — the fix `S02sys:8` intended | Raises the ceiling from 95 % to 99.995 %. Removes the dropout class that appears minutes into a session. | Low on an isolated cpu1; the kernel's protection against a runaway RT task is what is being relaxed, and cpu1 has exactly one RT task. **Never use `-1`.** | It is a runtime `/proc` write — reverted by any reboot, changes nothing on disk. **Nothing to survive.** | **No.** One write, no file edited. | **Do it, per session, after measuring.** The only change here that is both worthwhile and free. |
| 2 | Confirm `cpu1`'s cpufreq governor is `performance` | Zero if it already is; potentially large if it is not | None (a read) | n/a | No | **Do it.** A read. |
| 3 | Cap `~fxEnableCheckRoutine`'s loop (§3.5) | Removes up to 500 OSC msg/s from the realtime thread. Plausibly a few tenths of a point, possibly ~1 point. | Medium. It is an edit to `efx_server.scd`, and a syntax error there boots an instrument **with no effects at all** (`extension-points.md` §0, the "Editing `/usr/share/las-fx/*.scd`" row). | **No** | **Yes** — `/usr/share/las-fx/efx_server.scd` | **Not worth it on a stock instrument.** Worth it on a scratch partition if someone is already editing that file. |
| 4 | CSE + de-stereo the aux sums in `outputRouter` (§3.4 a–c) | **1–2 points of one core** | High: (b) is entangled with the +6 dB aux level error, so fixing it **changes the sound**. Also needs synthdefs recompiled on-device. | **No** | **Yes** | **No. Not worth doing.** |
| 5 | `Lag.ar` → `Lag.kr` in `inputRouter` (§3.4 e) | Two UGens. Unmeasurable. | Same edit risk as #4 | No | Yes | **No.** |
| 6 | Raise `-z` to 256 | 4 points | Doubles inter-timbre skew to ~21 ms | No | Yes | **No — retracted, see §6.** |
| 7 | Free the ten parked Eventides | Nothing (§3.2) | **Terminates `scsynth`** | — | — | **No. This is a crash, not an optimisation.** |
| 8 | `Out.ar` → `ReplaceOut` | **Zero** (§3.6) | — | — | — | **No.** |
| 9 | Kill the three `xterm`s and `las-dwm` by hand | A little cpu0 and a few MB | Low, but `las-dwm` is the window manager — killing it may leave `las-frontend` unmapped | n/a (runtime) | No | **Marginal.** Only if cpu0 is measurably short. |
| 10 | Remove one of the two DHCP clients | Negligible | Low | No | Yes | **No.** Document it instead. |
| 11 | Start `crond` so logs rotate | Disk, not CPU | Behaviour change Moog did not ship | No | Yes | **No.** Run `/etc/log-refresh` by hand if `/var` fills. |
| 12 | `dd bs=4M` in `lasfwu` | Possibly minutes off a 5-minute update | It is the **firmware installer**. A mistake there bricks a partition. | No | Yes | **Absolutely not.** Report it to Moog. |

**The honest summary of 7.A: there is no safe DSP win available on this instrument.**
The one thing worth doing (#1) is a `/proc` write that raises a ceiling; it does not make
anything faster, it stops the kernel from making it slower.

### 7.B Headroom available to things we add

This is the useful half.

| resource | headroom | grade | notes |
|---|---|---|---|
| **cpu1 (audio)** | **None.** 3–7 points between a full stock patch and the throttle. | [TESTED] + [INFERRED] | Anything added to the SC graph competes with the instrument's own effects. Budget it with a *live* `moogone.load` reading, never with `TYPICAL_PATCH_LOAD`. |
| **cpu0** | **Real, but shared with the UI.** `moogd` already lives here. | [TESTED] | The constraint is not average load, it is the FIFO-93 display threads and the ESAI IRQ (§2.4). Anything added here should be `SCHED_OTHER` and should never busy-wait. |
| **Private audio buses** | 98 of 112 free (17–49 and 64–128) | [READ] | `extension-points.md` §5.3. Free. |
| **Sample buffers** | ~1026, essentially all | [READ] | `init_sc_1.scd` allocates none. |
| **scsynth realtime memory** | 97.66 MiB pool, current usage **unknown** | [READ] + unknown | Measure before adding buffers. §8. |
| **RAM** | `MemAvailable` was 96 MB at the last capture, and 166 MB of it is unexplained | [READ] | Anything added should be measured, not assumed. There is **no swap and no zram** — overshoot is an OOM kill, and the OOM killer picks `las-frontend`. |
| **Rootfs** | 149.2 MB free of 636.8 MB; 103.6 MiB of the *used* 451.7 MB is `las-frontend`'s ASCII slack, inside Moog's signed binary and not reclaimable | [READ] | Put nothing on `/`. |
| **`/var`** | 3.3 GB free | [READ] | The right place for anything persistent that is not on USB. |
| **USB** | 234 GB | [READ] | The right place for everything else. `moogd` already does this. |
| **Preset / modulation layers** | Effectively unlimited, **zero i.MX6 cost** | [READ] | See `extension-points.md` §2–3. The modulation expressions execute on the XMOS voice controller, not here. This is the one place with real, free compute. |
| **Thermal** | 11.5 °C to the passive trip, +5.3 °C measured under a full cpu1 load | [TESTED] | `docs/MOOG-ONE-INTERNALS.md:2364-2402`. **Thermal margin and CPU margin are the same budget**: the passive trip clocks 996 → 792 MHz, which breaks audio immediately. |

**The one-line answer for anything we build:** put the compute on cpu0 or off the box
entirely, put the data on USB or `/var`, and treat cpu1 as a fixed cost you are allowed
to *read* and not to spend.

---

## 8. What I could not determine, and exactly what to read

None of these requires touching the instrument's state — they are all reads, and all of
them are safe. They are listed because each one closes a question this document had to
leave open. **Do not run any of them without the owner's go-ahead; the instrument is at
stock and this document did not contact it.**

| # | Question | Command |
|---|---|---|
| 1 | Is the RT throttle bug real on this unit? | `cat /proc/sys/kernel/sched_rt_runtime_us` (expect `950000`) and `ls -l /sched_rt_runtime_us` (expect a stray 7-byte file) |
| 2 | Which thread is being throttled? | `grep -A3 'rt_rq' /proc/sched_debug` while a heavy patch plays |
| 3 | Is cpu1's governor `performance`? (§2.3) | `cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor` |
| 4 | Does display work outrank the audio IRQ? (§2.4) | `grep -iE 'esai\|sdma\|ipu' /proc/interrupts` and `for p in $(pgrep -f 'irq/'); do echo -n "$p "; chrt -p $p; done` |
| 5 | Where is the 166 MB of non-reclaimable memory? (§4.1) | `cat /proc/meminfo` **in full** — specifically `CmaTotal`, `CmaFree`, `AnonPages`, `Mapped`, `Shmem`, `Slab`, `SUnreclaim`, `PageTables` |
| 6 | How much of `las-frontend` is resident? (§4.2) | `grep -E 'VmRSS\|VmSize\|RssFile\|RssAnon' /proc/$(pidof las-frontend)/status` |
| 7 | How much of scsynth's 97.66 MiB pool is touched? (§4.3) | same, for `$(pidof scsynth)` |
| 8 | Is the GPU doing anything? (§4.2) | `ls /usr/lib/xorg/modules/drivers/`; `grep -i driver /var/log/Xorg.0.log`; `cat /proc/driver/gc/*` if present |
| 9 | Does anything grow? | `moogone.load` plus `/proc/meminfo` sampled hourly over a long session; and `/status` `num_synths` / `num_ugens` for the LADSPA leak of §3.3 |
| 10 | Is the eleventh `et_room_1` present on a clean boot? | `/g_queryTree 0` immediately after `S42sc restart`, before touching the panel. **This is the test that decides whether §3.3 is a boot-time leak or a use-time one.** |
| 11 | Which cgroups exist and what RT bandwidth do they have? | `cat /etc/cgconfig.conf`; `cat /cgroup/cpu/*/cpu.rt_runtime_us`. `S43gui:8` runs `cgconfigparser` and the config is not in this harvest. |
| 12 | What does `-C 0` mean? | Still **unknown**, as `docs/arch/extension-points.md` §5.3 already records. It comes from sclang's `ServerOptions.asOptionsString`, so it maps to some `ServerOptions` field; no documented upstream field emits `-C` on Linux. Low stakes. |
| 13 | Where do the five minutes and the ten minutes actually go? | Only answerable by timing an update, which means performing one. **Not worth doing to satisfy curiosity.** |

**What would change if `pkg/rootfs` for 1.8.2 became readable.** Four things, and only
four: (a) whether `init_sc_1.scd` still says `blockSize = 128` and whether `synthdefs.scd`
changed at all — if either moved, §3.4 and §6 need re-checking; (b) whether `S02sys:8`
still has the relative-path bug, which decides whether finding #1 in 7.A is still needed;
(c) whether `las-frontend` still carries the 121.5 MiB ASCII blob, and whether it grew —
which decides whether the 12.19 MiB update margin in §5.2 still exists; (d) the XMOS
firmware version integers, which decide whether a 1.5.0 → 1.8.2 update reflashes the
voice cards at all (§5.3 stage 2–3). Nothing else in this document depends on it.

---

## 9. Conflicts with existing documents

Reported, not fixed, per the brief.

| where | what it says | what the evidence says |
|---|---|---|
| `docs/arch/control-plane.md:25` | `las-frontend` is a "Qt panel/display application" | **No Qt dependency and no Qt symbol.** `DT_NEEDED` is X11 + FreeType + ALSA + CHICKEN; 870 JUCE symbols, 0 Qt. §4.2 |
| `docs/arch/control-plane.md:245` | "145 MB stripped ARM ELF, **JUCE + Qt**" | JUCE yes, Qt no. Same evidence. |
| swarm brief, §"The architecture" | "Qt frontend" | Same. |
| swarm brief, §"The SuperCollider graph" | "boots ~700-750 ugens" | **496** at a fresh boot [TESTED]. 752 was a leftover experimental graph and `docs/CLAIMS-AUDIT.md:46-48` retracts it. |
| `docs/arch/system-and-failure-modes.md:885-891` | cites `captures/moog-recon/01-system.txt` for `MemFree 240776 kB` | That file says `4268`. The 240 MB figure is in `captures/sysmap/01-hardware.txt:31`. Conclusion survives, citation does not. |
| `docs/MOOG-ONE-INTERNALS.md:1628-1652` | "Block size is the cheapest CPU there is" — 72 % → 51 %, "21 points of a core", "reverting is the same one line" | **Retracted** by `docs/CLAIMS-AUDIT.md:20`; already listed in `doc-audit.md:607,623`. The section is still in INTERNALS in full. |
| `docs/ARCHITECTURE.md:62` | "block size 256" | 128. Already `doc-audit.md` §0.1. |
| `docs/arch/audio-graph.md:66,245,473,895` | block size 256 and 5.333 ms | 128 and 2.667 ms. Already `doc-audit.md` §0.1. |
| `docs/arch/effects-engine.md:129-134` | "Treat block size as 256 when reasoning about the live machine" | Wrong instruction. Already `doc-audit.md` §0.1. |
| `src/moogone/effect.py:180-249` | `CPU_COST` presented as the cost on this instrument; `TYPICAL_PATCH_LOAD = 0.72` | The table was measured at a "12-13 % baseline, 519 ugens", i.e. **at `-z 256`**, and is used against a `-z 128` instrument. It under-reads by ~5–10 % relative. §1. `TYPICAL_PATCH_LOAD` is separately flagged in `doc-audit.md:1301`. |
| `usb/S99moogd:18`, header comment | "It runs on cpu1, which `isolcpus=1` reserves and nothing else uses, so it cannot take cycles from the audio engine on cpu0." | **Backwards, and the code disagrees with its own comment** — `usb/S99moogd:61` is `taskset -c 0`, which is correct. cpu1 *is* the audio core. Already F-13 (`system-and-failure-modes.md:848-862`), but the stale comment is still in the shipped file. |
| `docs/arch/effects-engine.md:228-241` | the `\ins` LADSPA-leak path is "the single most dangerous **latent** path" | **Not latent.** Three live `/g_queryTree` dumps show an eleventh `et_room_1` at node 1034. §3.3 |

---

## 10. One-paragraph answer, for anyone who reads only this

The Moog One's i.MX6 is a **correctly and deliberately built realtime audio machine**
that is close to its limit, and the limit is analog-adjacent: the reverbs are LADSPA
plugins costing 25–35 % of a core each, cpu1 has room for about two of them plus the
routing, and there is no second core to move anything to because cpu1 *is* the second
core. Every optimisation available inside the audio engine is worth **one or two points
of one core**, costs an edit to a file a firmware update overwrites, and in the worst
case changes the sound. **The block size of 128 is right and the reasons are latency, not
CPU.** The real slack in the machine is not in the DSP at all — it is **103 MiB of
uncompressed ASCII preset text inside a 145 MB binary**, a **1.6 % free-space margin in
the firmware updater**, a **95 % realtime ceiling that Moog tried and failed to lift with
one missing slash**, and a **display pipeline promoted above the audio interrupt on the
shared core**. Three of those four are Moog's to fix. The fourth is one `/proc` write.
