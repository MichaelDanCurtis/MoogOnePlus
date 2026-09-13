# `/usr/share/las-fx` — the SuperCollider effects engine, firmware v1.8.2

Complete reading of the region from the decrypted v1.8.2 root filesystem at
`captures/firmware-1.8.2/rootfs-1.8.2`. The instrument was not contacted. Every
claim below carries a grade.

**Grades**

- **[READ]** — literally present in a file on disk. File and line/offset given.
- **[INFERRED]** — a conclusion drawn from evidence. The evidence is named.
- **[UNKNOWN]** — not determined from the material available.

Paths are relative to the 1.8.2 rootfs unless prefixed. `las-fx` = `usr/share/las-fx`.

---

## 0. Headline

**`/usr/share/las-fx` is byte-for-byte identical between v1.5.0 and v1.8.2.** All
442 files, `diff -rq` clean, exit 0. **[READ]** The entire SuperCollider effects
engine — the state machine, all 104 compiled synthdefs, the launcher, the forked
class library — did not change across the interval this project has been reading.
Anything learned from the v1.5.0 harvest applies unchanged to 1.8.2, and anything
hoped for in 1.8.2 is not there.

Two things did change **around** it:

- `usr/bin/scsynth` and `usr/bin/sclang` differ by md5 between the two images. **[READ]**
- `usr/lib/ladspa` — see §8, and read the contamination warning there before using
  the 1.5.0 capture as evidence about anything.

The one genuinely new result in this pass is that **the long-open LADSPA path
question is closed** (§8): the directory scsynth actually searches is
`/usr/lib/ladspa`, by a compiled-in default, and `las-fx/ladspa` — a *different
build* of the same five plugins plus the spring — is never read by anything.

---

## 1. Inventory of the region

`find . -type f -o -type l` under `las-fx` = **442 entries**. **[READ]**

### 1.1 Top level

| Entry | Bytes | Role | Live? |
|---|---|---|---|
| `README.md` | 581 | Developer note about the OSX/Linux synthdef archive split | doc only |
| `SCClassLibrary/` | 195 `.sc` + 4 `.so` | **The class library sclang actually compiles** (§6) | **live** |
| `assign-pids` | 1345 | RT priority / IRQ script (§5) | **live** |
| `compile-synthdefs` | 63 | `sclang -a -l sclang_config.yaml synthdefs.scd` | build tool |
| `efx_server.scd` | 35364 | The state machine and OSC API | **live** |
| `init.scd` | 3052 | Old single-server `Server.internal` + jackd config | **dead** |
| `init_sc_1.scd` | 4136 | **The live boot script** | **live** |
| `init_sc_2.scd` | 7205 | Two-scsynth JACK-patched config | **dead** |
| `init_sn.scd` | 3657 | supernova config | **dead** |
| `ladspa/` | 6 `.so` | Eventide LADSPA plugins — **not on the search path** (§8) | **dead** |
| `launch-sc` | 196 | `cd /usr/share/efx/` — that directory does not exist | **dead** |
| `launch-sc-1` | 418 | **The live launcher** | **live** |
| `launch-sc-2` | symlink | → `launch-sc-1` | inert |
| `launch-sn` | 258 | `cd /usr/share/efx/` — same dead path | **dead** |
| `sclang_config.yaml` | 57 | `includePaths: [SCClassLibrary]`, `postInlineWarnings: false` | **live** |
| `synthdefs/` | 104 `.scsyndef` + 104 `.txarcmeta` | **The compiled effect library** | **live** |
| `synthdefs.scd` | 113367 (3875 lines) | SynthDef **source**. Not executed at boot | build input |
| `tables/` | `coefsEnvir` (5.4 MB) + 2 `.scd` | Filter lookup tables — **unused** (§12) | **dead** |
| `util/` | 12 files | Developer scratch (§11) | **dead** |

**[READ]** all sizes from `ls -l`; live/dead determinations are justified per-section
below.

`usr/share/efx` does not exist in the 1.8.2 rootfs. **[READ]** — `ls -d usr/share/efx`
→ "No such file or directory". This is what makes `launch-sc` and `launch-sn` dead:
both `cd /usr/share/efx/` before invoking sclang.

### 1.2 The `synthdefs/` directory

104 `.scsyndef` and 104 `.txarcmeta`, exactly paired. **[READ]**

Every `.scsyndef` was parsed byte-exactly with a purpose-written reader: all 104 are
**SynthDef format version 2**, all parse to zero trailing bytes. **[READ]** The
control names, widths and defaults quoted throughout this document come from those
binaries, not from `synthdefs.scd` — i.e. from what the server actually loads.

`.txarcmeta` is a plain-text SuperCollider `asCompileString` archive of the
SynthDef's `metadata` Event (the `specs` ControlSpecs and the `description` array).
**[READ]** — `synthdefs/delay_0.txarcmeta` opens `var o, p;\no = [\n\tEvent.prNew,
Array.prNew(8), …` and contains the literal strings `"Mix"`, `"Wet/Dry Blend"`,
`"Feedback"`, `"Amount of output signal fed back into the delay unit"`.

`.txarcmeta` is read by `SynthDescLib.global.read` at boot (`init_sc_1.scd:37`
**[READ]**), but **`metadata.specs` is never consulted by `efx_server.scd`** — no
reference to `.specs` exists in the file. **[READ]** (grep). Consequence: the
ControlSpecs shipped alongside every effect are documentation the engine ignores;
all range discipline lives inside the SynthDef graph or in the controller.

---

## 2. How the engine is started

Chain, each link **[READ]**:

| Step | Evidence |
|---|---|
| `etc/init.d/S42sc:23` runs `runsc -q &` | `S42sc:4` defines `runsc()` as `/usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300 --vxfw=… --vcfw=… --expr-syms=/usr/share/vx_ee.scm --panel-state=localhost:9500 $1` |
| `las-sc` spawns the effects engine | `strings usr/bin/las-sc` contains `screen -d -m /usr/share/las-fx/launch-sc-1 &` (adjacent strings: `launching fx server`) |
| `launch-sc-1:6` | `cd /usr/share/las-fx/` |
| `launch-sc-1:7` | `ifdown lo && ifup lo` |
| `launch-sc-1:9-21` | background subshell polls for `/var/local/tmp/scsynth.cookie` every 1 s; on sight runs `assign-pids`, removes the cookie, breaks |
| `launch-sc-1:23` | `DISPLAY=:0 SCSYNTH_IP=$scip SERVER_SEND_PORT=9999 SERVER_RECV_PORT=7775 sclang -a -l sclang_config.yaml init_sc_1.scd` |
| `init_sc_1.scd:111` | `"echo 1 > /var/local/tmp/scsynth.cookie".systemCmd` — the last statement of the boot block, which releases `assign-pids` |

`launch-sc-1` **does not start `jackd`.** **[READ]** — `launch-sc` (dead) and
`launch-sn` (dead) both do (`jackd -dalsa -dhw:4 -p256 -n3 -r48000 -S &`);
`launch-sc-1` does not. scsynth on this machine drives ALSA directly.

**Note the ordering guarantee this buys**: `assign-pids` cannot run until the whole
graph — server booted, synthdefs loaded, all five slots and all ten Eventides
instantiated — exists, because the cookie is written last. **[INFERRED]** from the
placement of `:111` after `:107`'s `sync`.

`SERVER_SEND_PORT=9999` and `SCSYNTH_IP` are exported into sclang's environment but
`init_sc_1.scd` **never reads them** — no `.getenv` appears in the file. **[READ]**
(The dead `init.scd:4-7` does read them.) `~scIP` is therefore nil at runtime, which
is why `/fxN/ph` sends to `NetAddr(nil.asString, 7777)` (`efx_server.scd:985`).

---

## 3. `sclang -a` — the forked class library

`launch-sc-1:23` passes **`-a`**. **[READ]** sclang's own usage text describes it:

> `-a  Standalone mode (exclude SCClassLibrary and user and system Extensions folders from search path)`

**[READ]** — `strings usr/bin/sclang`.

So the class library sclang compiles is **exactly** `las-fx/SCClassLibrary`
(195 `.sc` files, added by `sclang_config.yaml`'s `includePaths`), and **not**
`/usr/share/SuperCollider/SCClassLibrary` (340 `.sc` files). **[INFERRED — firmly]**
from the `-a` semantics plus the config file.

This matters more than it looks:

- It explains why a 195-file library can sit next to a 340-file one without the
  duplicate-class error sclang carries a message for (`duplicate Class found: '%s'`,
  **[READ]** in `usr/bin/sclang`).
- **Any reasoning about sclang-side behaviour must use `las-fx/SCClassLibrary`.**
  Comparing basenames against the stock tree: 78 identical, 97 differing, 20 present
  only in the las-fx copy. **[READ]** (byte comparison by basename). Whether the 97
  differ because Moog edited them or because the two trees are different SuperCollider
  builds is **[UNKNOWN]** — `usr/bin/sclang` carries both `3.6.0` and `3.9.0` version
  strings **[READ]**, so a version skew is at least as likely as customisation, and
  the 97 should not be described as "Moog's modifications" without a per-file check.

The 20 files with no stock counterpart are the Moog additions: `APFTable.sc`,
`BPFTable.sc`, `CheckBadValues.sc`, `ControlModel.sc`, `Crossover.sc`,
`DistortionPlugins.sc`, `DualChorus.sc`, `Fb.sc`, `Flanger.sc`, `HPFTable.sc`,
`Infinitum.sc`, `LPFTable.sc`, `LadspaUGen.sc`, `M_Delay.sc`, `Module.sc`, `OSC.sc`,
`Phaser6Stage.sc`, `StereoSpread.sc`, `bhobGens.sc`, `extMethods.sc`. **[READ]**

`DualChorus`, `Flanger`, `Phaser6Stage`, `StereoSpread`, `Crossover`, and the four
`*Table` classes are **pure-sclang composites**, not bindings to native plugins —
each is a bare class with a `*ar` class method that assembles stock UGens. **[READ]**
(class heads inspected). They therefore need nothing on the scsynth side.

### 3.1 The four `.so` files in `SCClassLibrary/Effects/` are dead

`M_Delay.so`, `M_Phaser4.so`, `M_Vocoder.so`, `SIMDBPF.so` are **ARM ELF shared
objects** (`e_machine = 0x28`, `elf32-littlearm`). **[READ]** — llvm-objdump `-f`
and the ELF header bytes at offset 18.

They are dead for three independent reasons:

1. scsynth's plugin search path is the compiled-in `/usr/lib/SuperCollider/plugins`
   plus `SC_PLUGIN_PATH`. **[READ]** — both strings present in `usr/bin/scsynth`;
   `-U <ugen-plugins-path>` is the override flag. `SC_PLUGIN_PATH` is set nowhere in
   the rootfs. **[READ]** (grep; the only hits are SuperCollider's own help files).
   `SCClassLibrary/Effects/` is not on that path.
2. None of the four UGens is referenced by `synthdefs.scd`. **[READ]** — grep for
   `M_Delay|M_Phaser4|M_Vocoder|SIMDBPF` returns zero hits in the file.
3. None appears in any compiled synthdef. The complete census of UGen classes across
   all 104 `.scsyndef` is **61 classes** (§9.4), and none of the four is among them.
   **[READ]** (parsed from the binaries).

`SCClassLibrary/Effects/Makefile` is a macOS developer Makefile —
`DESTINATION= /Users/gregsurges/Documents/Code/sc-example-plugins/delay`, `SHARED = -bundle`,
`LIBTEXT = scx` — with rules only for `M_Delay` and `M_Phaser4`. **[READ]** It cannot
have produced the ARM ELF files sitting beside it.

---

## 4. Server configuration (`init_sc_1.scd`)

`init_sc_1.scd` is 117 lines. Line 1 is a single enormous comment into which the
whole original header was collapsed. **[READ]**

| Line | Statement | Value |
|---|---|---|
| 7 | `Server.default = Server.new(\server_main, NetAddr("127.0.0.1", 57110))` | UDP 57110 |
| 9 | `options.blockSize` | **128** |
| 10 | `options.hardwareBufferSize` | **128** |
| 11 | `options.numOutputBusChannels` | **8** |
| 12 | `options.numInputBusChannels` | **9** |
| 13 | `options.numWireBufs` | **128** |
| 14 | `options.memSize` | **100000** |
| 15 | `latency` | **0.05** |
| 18 | `options.sampleRate` | **48000** |

**[READ]** all nine. This corroborates `CORRECTIONS-2026-09-08.md` §2 — stock block
size is 128, and the `-w 128` wire-buffer count is a separate number.

Everything from line 21 runs inside `waitForBoot({ … })`, i.e. **after scsynth is
already running**. **[READ]** That timing is what kills the `LADSPA_PATH` line (§8).

| Line | Action |
|---|---|
| 23 | `("export LADSPA_PATH=/usr/share/las-fx/ladspa").systemCmd` — **inert**, see §8 |
| 24 | `SynthDef.synthDefDir = "/usr/share/las-fx/synthdefs/"` |
| 28 | `// {"tables/load_tables.scd".loadRelative;}.fork;` — **commented out** |
| 32 | `//"synthdefs.scd".loadRelative;` — **commented out** |
| 36 | `loadDirectory("/usr/share/las-fx/synthdefs/")` — loads all 104 |
| 37 | `SynthDescLib.global.read` |
| 40 | `"efx_server.scd".loadRelative` — registers every OSCdef **and starts `~fxStateThread`** |
| 43 | `~efxServer[\state].value` — **a no-op**; `\state` is never bound in the Environment (§7.1) |
| 45-48 | `~efxGroups = []`; `~insertGroup = Group.new(server)`; `~busGroup = Group.new(server)` |
| 51-60 | five-slot loop: `initUnit(i)`, then `Group.new(~insertGroup or ~busGroup, \addToTail)`, then `initEffect(\none_1, i)` |
| 65-66 | `~dspInputWrapper = Synth(\inputRouter, ~busGroup, \addToHead)`; `~dspOutputWrapper = Synth(\outputRouter, ~busGroup, \addToTail)` |
| 68 | `~busGroup.moveAfter(~insertGroup)` |
| 73 | `~eventideGroup = Group.after(~busGroup)` |
| 74-104 | `~eventides = Dictionary.new(10)`; ten `et_*` Synths, each followed by `.run(false)` |
| 109 | `stopAliveThread` |
| 111 | write `scsynth.cookie` |

**[READ]** all rows.

Because lines 28 and 32 are commented out, the boot path **never compiles a SynthDef
and never loads a filter table**. It loads only what is already in `synthdefs/`. This
is the mechanism by which the orphan synthdefs of §9.2 stay alive and by which
`et_spring` stays dead.

### 4.1 Node topology at the end of boot

**[READ] as of 2026-09-13.** This was `[INFERRED — firmly]` from the source below
until `/api/tree` was built to ask the running server. A live `/g_queryTree`
returns exactly the shape derived here — 29 nodes, `~insertGroup` (1000) with
three slot groups, `~busGroup` (1001) with `inputRouter` at the head, two slot
groups and `outputRouter` at the tail, and `~eventideGroup` (1014) holding
**exactly ten** `et_*` synths. The derivation was right.

Derived from the `Group.new` targets, `addAction`s and `moveAfter`
above:

```
RootNode (0)
└── default group (1)
    ├── ~insertGroup
    │    ├── ~efxGroups[0]     slot 0   insert 1
    │    ├── ~efxGroups[1]     slot 1   insert 2
    │    └── ~efxGroups[2]     slot 2   insert 3
    ├── ~busGroup
    │    ├── Synth(\inputRouter)     ~dspInputWrapper   (head)
    │    ├── ~efxGroups[3]     slot 3   master / bus 1
    │    ├── ~efxGroups[4]     slot 4   master / bus 2
    │    └── Synth(\outputRouter)    ~dspOutputWrapper  (tail)
    └── ~eventideGroup        10 paused et_* synths
```

`~eventideGroup` is created with `Group.after(~busGroup)` (`:73` **[READ]**), i.e.
**downstream of the output router**. A parked Eventide that were un-paused there
would run after everything, with whatever `inBus`/`outBus` it last held; a
never-adopted one holds the SynthDef defaults `inBus = 0, outBus = 0`
(`synthdefs.scd:3383` **[READ]**), i.e. it would read hardware output bus 0 and write
it again. **[INFERRED] consequence: an immediate feedback loop on the main output.**
Nothing in the code does this by itself. It makes `/n_run <id> 1` on anything in
`~eventideGroup` a command never to issue on the instrument.

---

## 5. `assign-pids` — what it actually does

1345 bytes, run once per boot from `launch-sc-1:14`. **[READ]** Complete behaviour:

| Line | Statement | Effect |
|---|---|---|
| 21 | `core=2` | **set and never used** — the only consumers are commented out |
| 23-27 | `#for i in "${sclangarr[@]}" … #taskset -p $core $i` | **commented out** |
| 30 | `chrt -r -p 94 $SCSYNTHPID` | scsynth's **main thread → SCHED_RR, priority 94** |
| 32-41 | for each scsynth thread: read field 18 of `/proc/$SCSYNTHPID/task/$i/stat`; `if [ $pri -ne -100 ]` then `chrt -f -p 94 $i` | every scsynth thread **not already at RT priority 99 → SCHED_FIFO 94** |
| 44-45 | `esaiirq=$(ps \| grep esai \| awk '{print $1} NR==1{exit}')`; `chrt -f -p 89 $esaiirq` | ESAI IRQ thread → **SCHED_FIFO 89** |
| 48-49 | same shape for `sdma`; `chrt -f -p 99 $sdmairq` | SDMA IRQ thread → **SCHED_FIFO 99** |
| 51-53 | `sdmadir=$(ps \| grep sdma \| awk '{print $3} NR==1{exit}' \| awk -F"-" '{print $1}' \| awk -F"/" '{print $2}')`; `echo 1 > /proc/irq/$sdmadir/smp_affinity` | intended: pin the SDMA hard-IRQ to **CPU 0** |
| 55-59 | `#for i in "${frontendarr[@]}" … #taskset -p 1 $i` | **commented out** |

**[READ]** every row from `assign-pids`.

### 5.1 `assign-pids` sets no CPU affinity for any process

Both `taskset` loops are commented out. **[READ]** The only affinity write the script
attempts is the SDMA `smp_affinity` at `:52`, and that is an *interrupt* affinity, not
a process one.

`usr/bin/taskset` and `usr/bin/chrt` both exist (util-linux binaries, 22352 and 21520
bytes) **[READ]**, so the commented-out lines would have worked.

### 5.2 The `-100` test is a rt-priority-99 test

Field 18 of `/proc/<pid>/task/<tid>/stat` is `priority`; for a real-time task
`priority = -1 - rt_priority`, so `-100` ⇔ `rt_priority == 99`. **[INFERRED]** from
the kernel's `proc` field layout. The guard therefore reads *"leave alone any thread
already at RT 99, put everything else at FIFO 94"*, which implies **scsynth sets one
of its own threads to RT 99 before this script runs**. That is consistent with the
architecture brief, and with the fact that `usr/bin/scsynth` imports
`pthread_setaffinity_np` and carries the messages
`SC_AlsaDriver : Trying to set thread realtime prio =` and
`SC_AlsaDriver : Unsuccessful in setting thread core affinity`. **[READ]**

**So the audio thread's priority and core placement come from scsynth's own ALSA
driver, not from `assign-pids`.** **[INFERRED]** This is worth stating plainly because
the repository currently attributes the machine's CPU policy to `assign-pids`
(see §14, conflict C4).

### 5.3 The SDMA core-lock at `:52` almost certainly does nothing

`ps` is busybox (`bin/ps -> busybox`, BusyBox v1.24.1). **[READ]** This build contains
exactly **one** ps header format string:

```
  PID  PPID USER     STAT   VSZ %VSZ %CPU COMMAND
```

**[READ]** — `strings bin/busybox`, single match for `^ *PID`.

Under that layout `$1` = PID and **`$3` = USER**, not the command. So:

- `esaiirq` and `sdmairq` (`awk '{print $1}'`) get correct PIDs — those two `chrt`
  calls work. **[INFERRED]**
- `sdmadir` (`awk '{print $3}'`, then split on `-`, then take field 2 of a split on
  `/`) evaluates `"root"` → `"root"` → **empty**. **[INFERRED]**
- `echo 1 > /proc/irq//smp_affinity` targets a path that does not exist; the
  redirection fails and the script continues. The following `echo` prints
  `CORE LOCK SDMA TO : ` with an empty value. **[INFERRED]**

The script was evidently written against a `ps` whose third column is the command.
This is a **[INFERRED]** conclusion about runtime behaviour from a **[READ]** format
string; it is the single cheapest thing in this report to confirm on the instrument
(§15, V6) and it is load-bearing for anyone reasoning about interrupt placement.

### 5.4 The cgroups are defined but nothing is ever put in them

`etc/cgconfig.conf` defines three groups — `dsp` (`cpuset.cpus = 1`, `cpu.shares = 100`),
`frontend` (`cpuset.cpus = 0`, `cpu.shares = 25`, `memory.soft_limit_in_bytes = 16756736`),
and `sc` (`cpuset.cpus = 0`, `cpu.shares = 25`). **[READ]** They are created by
`cgconfigparser -l /etc/cgconfig.conf` at `etc/init.d/S43gui:8`. **[READ]**

**No process is ever classified into them.** **[READ]** — the only `cgclassify`
invocations in the rootfs are in `las-fx/init.scd:36`, `las-fx/init_sn.scd:48` and
`las-fx/util/test_server.scd:33`, all three of which are dead files, and all three
name groups (`scsynth0`, `sclang0`) that **do not exist** in `cgconfig.conf`. No
`cgclassify`/`cgexec` string appears in `las-sc`, `las-frontend`, `scsynth`, `sclang`
or `las-watchdog`. **[READ]**

Kernel command line carries `isolcpus=1` (`boot/cmdline.txt:1` **[READ]**).

**[INFERRED]** Therefore the `dsp`/`frontend`/`sc` cgroups are empty scaffolding, and
whatever reaches CPU 1 gets there by scsynth's own `pthread_setaffinity_np`, not by
cgroup or `taskset`. Flagged rather than asserted: confirming it needs a live read
(§15, V7).

---

## 6. The OSC surface (`efx_server.scd`)

`thisProcess.openUDPPort(7775)` at `efx_server.scd:3`. **[READ]**
`OSCFunc.trace(false)` at `:2`, `~debug = false` at `:4`. **[READ]** — the whole file
is heavily instrumented behind `~debug`, and all of it is off.

### 6.1 Global handlers, registered once at file load

| Line | Address | Target |
|---|---|---|
| 13 | `/ping` | echoes `/ping` back to sender |
| 21 | `/fx/send1Gain` | `~dspInputWrapper.set(\send1Gain, …)` |
| 26 | `/fx/send2Gain` | `\send2Gain` |
| 31 | `/fx/send1Thresh` | `\send1Thresh` |
| 36 | `/fx/send2Thresh` | `\send2Thresh` |
| 41 | `/fx/sendClampTime` | `\clampTime` |
| 46 | `/fx/sendRelaxTime` | `\relaxTime` |
| 51 | `/fx/sendGainFactorMin` | `\gainFactorMin` |
| 90 | `/fx/start` | starts/stops `~fxStateThread`; on `kill -0` failure **reloads `init_sc_1.scd`** |
| 127 | `/fx/state` | replies `/fx/state <1\|0\|-1>` to the sender's port |
| 142 | `/fx/bus-mode` | sets `\mode` and the `send1_r`/`send2_r` matrices |
| 163 | `/fx/hw-rev` | `digDryGain := 1.9` (rev 0) or `0.9` (rev ≠ 0) |
| 174 | `fx/spread` *(no leading slash)* | `~dspOutputWrapper.set(\stereoSpread, …)` |

**[READ]** all thirteen.

### 6.2 Per-slot handlers, registered five times by `~initUnit` (N = 0..4)

| Line | Address | Note |
|---|---|---|
| 322 | `/fxN` | the effect-change / preset-recall message |
| 657 | `/fxN/en` | |
| 698 | `fxN/mix` | no leading slash |
| 709 | `fxN/g-in` | no leading slash |
| 720 | `fxN/g-out` | no leading slash |
| 746 | `/fxN/ctl` | |
| 754 | `/fxN/pan` | also drives `outputRouter.dry_(N+1)_p` |
| 769 | `/fx/run` | **not per-slot** — same OSCdef key five times, so it replaces itself; targets the unbound `~state` (§7.1) |
| 782 | `fxN/wet` | **body's only write is commented out** (`:793`) — a no-op |
| 805 | `fxN/in` | `chan = msg[k+1] + 8` |
| 836 | `fxN/out` | sets `outputRouter.insert(N+1)_r` and `dry_dir(N+1)_r` |
| 866 | `fxN/sends` | sets `inputRouter.insert(N+1)_r` |
| 892 | `fxN/par` | sets `inputRouter.par_amount` |
| 917 | `fxN/dry` | sets `outputRouter.timbre_(N+1)_dry` |
| 938 | `fxN/dig-dry` | sets `outputRouter.timbre_(N+1)_dry_main` |
| 964 | `/fxN/pl` | builds a parameter-list string and **discards it** |
| 972 | `/fxN/ph` | replies to `NetAddr(~scIP.asString, 7777)` and hard-codes the reply address `'/fx0/ph'` |

**[READ]** all seventeen.

Eleven of these register **without a leading slash**. **[READ]** They work because
`OSCFunc` normalises the path — **[INFERRED]**, and corroborated by the fact that the
instrument demonstrably responds to `fx0/sends` and `fx0/in` in this project's prior
live work. Do not "tidy" them.

### 6.3 The fifteen parameter handlers per slot are not registered at boot

`~initEffectParamHandlers` (`efx_server.scd:193-217`) registers `/fxN/p/0` …
`/fxN/p/14`. **[READ]** It is called from **exactly one place**: `efx_server.scd:626`,
inside the effect-change waiter routine. **[READ]** (grep — the only other occurrence
is the definition itself.)

**[INFERRED]** So after a cold boot, before any slot has completed an effect *change*,
`/fxN/p/k` messages are silently dropped by SuperCollider.

Address count at end of boot: 13 global + `/fx/run` + 5 × 16 = **94**. After all five
slots have changed effect once: + 5 × 15 = **169**. **[INFERRED]** from the counts above.

---

## 7. The state machine

### 7.1 `~efxServer[\state]` and `~state` do not exist

`init_sc_1.scd:43` calls `~efxServer[\state].value`. The `Environment.make` block
(`efx_server.scd:182-998`) binds `~efx_active`, `~efx_i`, `~efx_type`,
`~initEffectParamHandlers`, `~initEffect`, `~initUnit` — and nothing named `state`.
**[READ]** (grep for `~state`/`\state` in `efx_server.scd` returns only `~statereturn`
at `:96,109,112,120`, the `'/fx/state'` message name at `:124`, and the two unbound
uses at `:773,775`.)

`Environment.at(\state)` is therefore nil, and `Object:value` returns the receiver, so
`:43` is a silent no-op. **[INFERRED]** — from SuperCollider's `Object:value` semantics.

`/fx/run` (`:769-778`) calls `~state.play` / `~state.pause` on that same unbound
variable. **[READ]** It is dead.

The real state machine is `~fxStateThread` (`efx_server.scd:1033-1081`), a `Routine`
that **`.play`s itself on the last line of the file** (`:1081`) — i.e. during
`init_sc_1.scd:40`, *before* the slot loop at `:51`. **[READ]**

### 7.2 `~fxStateThread`

10 Hz loop (`0.10.wait`, `:1044`). For each active slot, if `fxN_change_needed`:

1. `.set(\enable, 0)` on the current effect (`:1053`)
2. `~fxEnableCheckRoutine` — a nested Routine that re-asserts `enable = 0` every 20 ms
   until the node id reads 0 or `enable` reads 0 (`:1005-1028`, `:1055`)
3. `0.125.wait` for the envelope release (`:1057`)
4. `~initEffect` with the newly requested effect (`:1066`)
5. `fxN_en_prev := 1` (`:1070`), `fxN_change_needed := false` (`:1073`)

**[READ]** all five steps.

The 0.125 s wait matches the `Env.asr(0.1, 1, 0.1)` release of 0.1 s used by every
effect except `stereoOutput` and `et_spring`, which use a **2 second** release
(`synthdefs.scd:619`, `:3657`). **[READ]** Neither is reachable at runtime.

### 7.3 `~initEffect` has two branches and the insert branch knows nothing about Eventides

`efx_server.scd:225-282`. **[READ]**

- **`\ins` branch** (`:236-240`), taken when `~efxServer[fxN_category] == \ins`:
  three lines, `Synth(effect, target: ~efxGroups[unitNum], addAction: 'addToHead')`.
  No Eventide check. No freeing or parking of the previous node.
- **else branch** (`:241-271`): parks the previous node if it was an Eventide
  (`moveToTail(~eventideGroup)`, `run(false)` — `:245-251`); then either adopts the
  parked Eventide (`~eventides.at(effect)`, `moveToTail(~efxGroups[unitNum])` —
  `:257-261`) or creates a new Synth `addToTail` (`:265`); then
  `~dspOutputWrapper.moveToTail(~busGroup)` (`:269`).

### 7.4 An explanation for the observed eleventh Eventide node

`CORRECTIONS-2026-09-08.md` §8 records, as an unexplained **[AGENT]** observation,
"An **eleventh** Eventide node (`et_room_1`) appears in live `/g_queryTree` dumps".

The source supports a specific mechanism. **[INFERRED]**, from these **[READ]** facts:

1. `~initUnit` sets `fxN_category := \ins` for **all five** slots
   (`efx_server.scd:310`).
2. `~initEffect` reads `fxN_category` at `:236` to choose its branch.
3. `fxN_category` is only ever updated at `efx_server.scd:515`, which sits **inside**
   the `Routine` at `:489` that waits for `~efxServer[fxN_effect].defName == msg[1]`
   — i.e. it is written *after* `~fxStateThread` has already called `~initEffect`.

So on the **first** effect-change message a bus slot receives, `~initEffect` still
sees the boot-time `\ins` and takes the three-line insert branch, which calls
`Synth(effect, …)` unconditionally — creating a **fresh** `et_room_1` node alongside
the one already parked in `~eventideGroup`, and registering it nowhere. Because every
`et_*` SynthDef uses `doneAction: 1` (§10), `enable = 0` only pauses it; it never
leaves the graph. On subsequent changes `category` is correct and the adoption path is
used.

This predicts **at most one extra node per bus slot per boot**, which matches an
eleventh node exactly. It is **[INFERRED]**, not proven — confirming it needs a live
`/g_queryTree` before and after the first bus-slot Eventide selection (§15, V8).

**Partially checked, 2026-09-13.** `/api/tree` now provides that dump. On a freshly
restarted engine with no bus-slot Eventide ever selected, there are **exactly ten**
`et_*` nodes, all inside `~eventideGroup` — the designed state, and the "before" half
of the experiment. The "after" half still needs somebody to select a reverb on bus
slot 3 or 4 at the panel and re-read the tree. `/api/tree` reports the `et_*` count
directly so the answer is one request, not a hunt.

---

## 8. LADSPA — the open question, closed

`docs/arch/effects-engine.md` §1 and `docs/arch/audio-graph.md` §4 both record that
`("export LADSPA_PATH=/usr/share/las-fx/ladspa").systemCmd` cannot work, and both
leave the real mechanism open. It is determinable from the 1.8.2 image.

### 8.1 The `export` is inert, twice over

**[READ]** `init_sc_1.scd:23`. `String:systemCmd` is a primitive
(`SCClassLibrary/Collections/String.sc:450`: `systemCmd { _String_System ^this.primitiveFailed }`
**[READ]**) that runs the string in a child shell. An `export` there cannot alter
sclang's environment. **[INFERRED — firmly]**

And it could not matter even if it did: line 23 executes **inside** `waitForBoot`'s
completion function (`:21`), i.e. after scsynth has already been spawned with
sclang's environment as it was. **[READ]**

### 8.2 What scsynth actually searches

`usr/lib/SuperCollider/plugins/LadspaUGen.so` contains, adjacent in `.rodata`:

```
LADSPA
/usr/lib/ladspa:/usr/local/lib/ladspa
LADSPA_PATH
ladspa_descriptor
```

**[READ]** — `strings -a`, lines 52-55 of the output. The plugin imports `getenv`,
`opendir`, `readdir64`, `dlopen`, `dlsym`, `qsort`. **[READ]** — dynamic symbol table.

`LADSPA_PATH` is set **nowhere** in the rootfs. **[READ]** — a full-tree grep finds
exactly four hits: the two inert `systemCmd` lines (`init_sc_1.scd:23`,
`init_sc_2.scd:44`) and two SuperCollider documentation files. No `setenv`/`putenv` of
it in `las-sc`, and `S42sc` sets no environment. **[READ]**

**[INFERRED — firmly]** Therefore the directory scsynth scans is the compiled-in
default, **`/usr/lib/ladspa`** (then `/usr/local/lib/ladspa`, which does not exist).
`/usr/share/las-fx/ladspa` is never read by anything.

`LADSPA.ladspalist_path` in `SCClassLibrary/LadspaUGen/LadspaUGen.sc:13` is unrelated:
it points at the `ladspalist` helper binary and is used only by `*listPlugins`, which
shells out (`:17`). **[READ]** `SCClassLibrary/LadspaUGen/ladspalist` is itself an ARM
ELF executable, not a text listing, and carries the same default string
`/usr/lib/ladspa:/usr/local/lib/ladspa`. **[READ]**

### 8.3 The two directories hold different builds

| Plugin | `/usr/lib/ladspa` bytes | md5 | `las-fx/ladspa` bytes | md5 |
|---|---|---|---|---|
| blackhole | 569304 | `62e8bef8…` | 399692 | `98647227…` |
| hall | 597832 | `3e28fdc2…` | 389944 | `aa375b5e…` |
| plate | 446552 | `389a1d40…` | 420456 | `a2eb978d…` |
| room | 601128 | `3c6b17d1…` | 397832 | `00d408c3…` |
| shimmer | 425536 | `0d882dfe…` | 402480 | `e9e19ebe…` |
| **spring** | **absent** | — | 412704 | `bac2c22b…` |

**[READ]** — `ls -l` and `md5`. These are not copies of one another; the two trees are
distinct builds. Which is newer is **[UNKNOWN]**.

### 8.4 LADSPA UniqueIDs, verified by disassembly

Each plugin's `ladspa_descriptor` opens with a Thumb-2 `movw r11, #<id>`:

| Plugin | instruction | id | `LADSPA.ar(2, …)` call site |
|---|---|---|---|
| blackhole | `f247 1bde  movw r11, #0x71de` | **29150** | `synthdefs.scd:3417`, `:3419` |
| hall | `f247 1bdf  movw r11, #0x71df` | **29151** | `:3584`, `:3586` |
| room | `f247 1be0  movw r11, #0x71e0` | **29152** | `:3501`, `:3503` |
| **spring** | `f247 1be1  movw r11, #0x71e1` | **29153** | `:3662` (inside a comment) |
| plate | `f247 1be2  movw r11, #0x71e2` | **29154** | `:3742`, `:3744` |
| shimmer | `f247 1be3  movw r11, #0x71e3` | **29155** | `:3827`, `:3829` |

**[READ]** — `llvm-objdump -d --triple=thumbv7-none-linux-gnueabihf
--disassemble-symbols=ladspa_descriptor` on each `.so`, and grep of `synthdefs.scd`.
The mapping is exact and unambiguous: the id in each plugin matches the id in the
SynthDef that names that reverb.

### 8.5 Consequence for the spring

`/usr/lib/ladspa` in the stock 1.8.2 image supplies ids 29150, 29151, 29152, 29154,
29155 — **everything except 29153**. **[READ]**

So the spring is unreachable for **two independent reasons**, and the repository
currently records only one of them:

1. Its SynthDef is inside a block comment — `/*` at `synthdefs.scd:3629`, `*/` at
   `:3700`, `SynthDef(\et_spring,` at `:3632`. **[READ]** Hence no
   `et_spring.scsyndef` exists in `synthdefs/`. **[READ]**
2. Even if it were uncommented and compiled, `LADSPA.ar(2, 29153, …)` would fail at
   instantiation, because plugin 29153 is not in the directory scsynth searches.
   scsynth carries the message `LADSPA: ERROR, plugin %lu not found!` for exactly this.
   **[READ]** **[INFERRED]** for the consequence.

`docs/arch/effects-engine.md:276-278` says "The LADSPA library `eventide_spring.so`
**is** present". That is true of `las-fx/ladspa`, which is not on the search path. See
conflict C2 in §14.

### 8.6 Contamination warning on the v1.5.0 capture

**Do not use `captures/rootfs-1.5.0/usr/lib/ladspa` as evidence about Moog's stock
1.5.0.** It contains six plugins, including `eventide_spring.so`
(md5 `bac2c22b…`, mode 755, mtime "May 16 2022") — **byte-identical to
`las-fx/ladspa/eventide_spring.so`**. **[READ]** The other five are mode 644, mtime
"Nov 15 2021". **[READ]** The **directory's own mtime is 2026-09-07** — during this
project's work. **[READ]**

This project's own audit records the cause: `docs/arch/doc-audit.md:282` —
"This project itself later copied `eventide_spring.so` into `/usr/lib/ladspa`" — and
`:283` records that it was later removed and the instrument restored to stock.
**[READ]**

So the difference between the two captures' `/usr/lib/ladspa` is **an artefact of this
project**, not a firmware change. It must not be reported as "Moog removed the spring
in 1.8.2". The 1.8.2 figure (five plugins) is from the untouched vendor image and is
sound; the 1.5.0 figure is not usable.

---

## 9. The compiled synthdef corpus

### 9.1 Families

37 families across 104 compiled definitions. **[READ]** — parsed from the binaries.

Non-Eventide effects are built in **four** variants `_0`…`_3` by `(0..3).do{|n| …}`;
the Eventides in **two**, `_1`/`_2`, by `(1..2).do{|n| …}`. **[READ]** — 20 `(0..3).do`
loop headers at `synthdefs.scd:32,640,725,854,974,1124,1278,1390,1507,1628,1721,1929,2071,2205,2306,2505,2607,2751,2969,3200`
and 5 `(1..2).do` at `:3379,3464,3548,3707,3789`.

`n` encodes **input topology**, not slot. Read from `delay_n`
(`synthdefs.scd:669-695`) **[READ]**:

| `n` | input | output stage |
|---|---|---|
| 0 | `In.ar(inBus,1) * g_in * 0.4`, `FbNode(1)` | `XFade2` vs `Silent.ar(1)`, then `Balance2` (panned) |
| 1 | `In.ar(inBus,2).sum * 0.5 * g_in`, `FbNode(1)` | same — stereo in, mono processing, panned |
| 2 | `In.ar(inBus,2) * g_in`, `FbNode(2)` | `XFade2` vs `Silent.ar(2)`, **no pan** — true stereo |
| 3 | `In.ar(inBus,1) * g_in`, `FbNode(1)` | as 0, without the `0.4` trim |

For the Eventides the split is the same idea in two values: `n == 1` feeds
`input.sum * 0.45` (blackhole/plate/shimmer) or `input.sum * 0.5` (room/hall) into
**both** plugin inputs — a mono sum; `n == 2` feeds `input[0], input[1]` — true
stereo. **[READ]** `synthdefs.scd:3417` vs `:3419`, `:3501` vs `:3503`, `:3584` vs
`:3586`, `:3742` vs `:3744`, `:3827` vs `:3829`.

### 9.2 Compiled with no source, and source with no binary

**Compiled but absent from `synthdefs.scd` (7):** `echo_0`, `echo_1`, `echo_2`,
`bitcrusher2`, `spaceFlanger`, `spacePhaser`, `timeEnsemble`. **[READ]** — the
SynthDef declaration list in `synthdefs.scd` contains no `\echo`, `\bitcrusher2`,
`\spaceFlanger`, `\spacePhaser` or `\timeEnsemble`. Because `init_sc_1.scd:36` does
`loadDirectory` of the whole directory, these are **live, instantiable synthdefs whose
source is not in this firmware**.

This confirms `docs/arch/audio-graph.md:877-887`, which reached the same list.

**Source but no binary (1):** `et_spring` — see §8.5.

### 9.3 The four orphans break the generic-parameter layout

`efx_server.scd:201,325` set `num_generic_params = 11` and address effect parameters
as `controlNames[k + 11]`. **[READ]** For 26 of the 37 families the first eleven
controls are exactly:

```
0 enable   1 inBus   2 outBus   3 ctlIn   4 ctlOut
5 ctl      6 g_in    7 g_out    8 wet     9 dry     10 pan
```

so `controlNames[11] = mix` and panel parameter 0 is `mix`. **[READ]** — verified
against every compiled binary.

**Four definitions do not have `pan` in the head:** `bitcrusher2`, `spaceFlanger`,
`spacePhaser`, `timeEnsemble`. Their heads end `… 8 wet  9 dry  10 mix`, and `pan` is
instead the **last** effect parameter. **[READ]**

**[INFERRED]** consequences, if a preset ever names one of them:
- every panel parameter index is shifted by one relative to the other families;
- `~effect.set(\pan, msg[6])` (`efx_server.scd:429`, `:575`) still finds a `pan`
  control, but at the far end of the list where the controller does not expect it.

`et_spring`, in its comment block, has the same defect — no `pan` argument
(`synthdefs.scd:3633-3654` **[READ]**). All four live Eventide families do have it.

### 9.4 UGen census

61 distinct UGen classes across all 104 compiled definitions. **[READ]** — parsed
from the binaries:

`AllpassN, Amplitude, BAllPass, BBandPass, BHiPass, BLowPass, BPF, Balance2,
BinaryOpUGen, BufRd, BufWr, ClearBuf, Clip, Compander, Control, ControlDur, DC,
Decimator, DelayC, DelayL, DelayN, DetectSilence, DoubleNestedAllpassN, EnvGen, HPF,
In, InFeedback, IndexL, K2A, LADSPA, LFCub, LFNoise0, LFNoise1, LPF, Lag, Lag3,
LagControl, LeakDC, LinPan2, LinXFade2, Line, LocalBuf, LocalIn, LocalOut,
MaxLocalBufs, MulAdd, NumOutputBuses, OnePole, Out, Pan2, Phasor, RHPF, RLPF, SOS,
Select, SetBuf, Sum3, Sum4, UnaryOpUGen, WhiteNoise, XFade2`

Every one resolves inside `/usr/lib/SuperCollider/plugins` (96 `.so`). **[READ]** —
spot-checked by symbol: `DoubleNestedAllpassN` → `BhobFilt.so`, `Decimator` →
`DistortionUGens.so`, `BAllPass`/`BBandPass` → `FilterUGens.so`, `LADSPA` →
`LadspaUGen.so`, `ClearBuf`/`SetBuf`/`DelayC` → `DelayUGens.so`, `Balance2` →
`PanUGens.so`.

`usr/share/SuperCollider/Extensions` contains **no** `.so` at all. **[READ]** All
native UGen code lives in `/usr/lib/SuperCollider/plugins`.

### 9.5 Complete parameter map

Read from the 104 compiled binaries. `psize = ncontrols − 11`; the p-index column is
`k` in `/fxN/p/k` and in the preset `(index, value)` pairs. A negative `psize` means
every `if(pindex < psize)` test is false and the slot swallows all parameter writes.

<!-- The `input`, `output`, `inputRouter`, `outputRouter`, `sendInput`, `stereoOutput`
     rows are infrastructure synths, not slot effects; their "effect params" column is
     an artefact of applying the +11 rule and has no OSC meaning. -->

| family | variants | controls | psize | effect parameters (p-index = k in `/fxN/p/k`) |
|---|---|---|---|---|
| `bbdDelay` | 4 (0,1,2,3) | 18 | 7 | 0=`mix`, 1=`feedback`, 2=`time`, 3=`noise`, 4=`tone`, 5=`modulation`, 6=`gain` |
| `bitcrusher` | 4 (0,1,2,3) | 15 | 4 | 0=`mix`, 1=`bitDepth`, 2=`sampleRate`, 3=`gain` |
| `bitcrusher2` ⚠ | 1 | 18 | 7 | 0=`splitFrequency`, 1=`lowDepth`, 2=`lowRate`, 3=`highDepth`, 4=`highRate`, 5=`gain`, 6=`pan` |
| `chorus` | 4 (0,1,2,3) | 18 | 7 | 0=`mix`, 1=`feedback`, 2=`time`, 3=`rate`, 4=`depth`, 5=`tone`, 6=`gain` |
| `default` | 1 | 8 | −3 | _none_ |
| `delay` | 4 (0,1,2,3) | 15 | 4 | 0=`mix`, 1=`feedback`, 2=`time`, 3=`gain` |
| `dualChorus` | 4 (0,1,2,3) | 20 | 9 | 0=`mix`, 1=`feedback`, 2=`time`, 3=`rate`, 4=`depth`, 5=`tone`, 6=`vibratoRate`, 7=`vibratoDepth`, 8=`gain` |
| `echo` ⚠ | 3 (0,1,2) | 20 | 9 | 0=`mix`, 1=`tone`, 2=`time`, 3=`feedback`, 4=`space`, 5=`decay`, 6=`modRate`, 7=`modDepth`, 8=`gain` |
| `ensemble` | 4 (0,1,2,3) | 20 | 9 | 0=`mix`, 1=`feedback`, 2=`time`, 3=`rate`, 4=`depth`, 5=`tone`, 6=`vibratoRate`, 7=`vibratoDepth`, 8=`gain` |
| `et_blackhole` | 2 (1,2) | 22 | 11 | 0=`mix`, 1=`modDepth`, 2=`modRate`, 3=`feedback`, 4=`res`, 5=`highLvl`, 6=`lowLvl`, 7=`preDelay`, 8=`size`, 9=`invGravity`, 10=`gain` |
| `et_hall` | 2 (1,2) | 22 | 11 | 0=`mix`, 1=`lowDecay`, 2=`highDecay`, 3=`modLvl`, 4=`midLvl`, 5=`highLvl`, 6=`lowLvl`, 7=`preDelay`, 8=`size`, 9=`decay`, 10=`gain` |
| `et_plate` | 2 (1,2) | 22 | 11 | 0=`mix`, 1=`distance`, 2=`diffusion`, 3=`modLvl`, 4=`tone`, 5=`highDamp`, 6=`lowDamp`, 7=`preDelay`, 8=`size`, 9=`decay`, 10=`gain` |
| `et_room` | 2 (1,2) | 22 | 11 | 0=`mix`, 1=`reflection`, 2=`diffusion`, 3=`modLvl`, 4=`highFreq`, 5=`highLvl`, 6=`lowLvl`, 7=`preDelay`, 8=`size`, 9=`decay`, 10=`gain` |
| `et_shimmer` | 2 (1,2) | 22 | 11 | 0=`mix`, 1=`aPitch`, 2=`bPitch`, 3=`pitchDecay`, 4=`midDecay`, 5=`highDecay`, 6=`lowDecay`, 7=`delay`, 8=`size`, 9=`decay`, 10=`gain` |
| `flanger` | 4 (0,1,2,3) | 19 | 8 | 0=`mix`, 1=`feedback`, 2=`time`, 3=`rate`, 4=`depth`, 5=`tone`, 6=`noiseGain`, 7=`gain` |
| `input` ‡ | 1 | 9 | −2 | _none_ |
| `inputRouter` ‡ | 1 | 16 | 5 | — infrastructure, see §10 |
| `none` | 4 (0,1,2,3) | 8 | −3 | _none_ |
| `output` ‡ | 1 | 15 | 4 | — infrastructure |
| `outputRouter` ‡ | 1 | 35 | 24 | — infrastructure, see §10 |
| `phaser12stage` | 4 (0,1,2,3) | 19 | 8 | 0=`mix`, 1=`feedback`, 2=`sweep`, 3=`rate`, 4=`depth`, 5=`tone`, 6=`noiseGain`, 7=`gain` |
| `phaser6stage` | 4 (0,1,2,3) | 19 | 8 | 0=`mix`, 1=`feedback`, 2=`sweep`, 3=`rate`, 4=`depth`, 5=`tone`, 6=`noiseGain`, 7=`gain` |
| `pingpongDelay` | 4 (0,1,2,3) | 18 | 7 | 0=`mix`, 1=`feedback`, 2=`timeL`, 3=`timeR`, 4=`offset`, 5=`tone`, 6=`gain` |
| `resonator` | 4 (0,1,2,3) | 23 | 12 | 0=`mix`, 1=`resonance`, 2=`cutoff1`, 3=`cutoff2`, 4=`cutoff3`, 5=`levelLow`, 6=`levelMid`, 7=`levelHigh`, 8=`filterType`, 9=`rate`, 10=`depth`, 11=`gain` |
| `sendInput` ‡ | 1 | 11 | 0 | _none_ |
| `spaceFlanger` ⚠ | 1 | 21 | 10 | 0=`feedback`, 1=`time`, 2=`modRate`, 3=`modDepth`, 4=`tone`, 5=`spread`, 6=`space`, 7=`decay`, 8=`gain`, 9=`pan` |
| `spacePhaser` ⚠ | 1 | 20 | 9 | 0=`rate`, 1=`depth`, 2=`sweep`, 3=`feedback`, 4=`tone`, 5=`space`, 6=`decay`, 7=`gain`, 8=`pan` |
| `stereoChorus` | 4 (0,1,2,3) | 22 | 11 | 0=`mix`, 1=`feedbackLeft`, 2=`feedbackRight`, 3=`timeLeft`, 4=`timeRight`, 5=`rateLeft`, 6=`rateRight`, 7=`depth`, 8=`phaseOffset`, 9=`tone`, 10=`gain` |
| `stereoDelay` | 4 (0,1,2,3) | 22 | 11 | 0=`mix`, 1=`timeL`, 2=`timeR`, 3=`feedbackL`, 4=`feedbackR`, 5=`modRateL`, 6=`modRateR`, 7=`modDepthL`, 8=`modDepthR`, 9=`tone`, 10=`gain` |
| `stereoFlanger` | 4 (0,1,2,3) | 22 | 11 | 0=`mix`, 1=`feedbackLeft`, 2=`feedbackRight`, 3=`timeLeft`, 4=`timeRight`, 5=`rateLeft`, 6=`rateRight`, 7=`depth`, 8=`phaseOffset`, 9=`tone`, 10=`gain` |
| `stereoOutput` ‡ | 1 | 15 | 4 | — infrastructure, never instantiated |
| `tapeDelay` | 4 (0,1,2,3) | 18 | 7 | 0=`mix`, 1=`feedback`, 2=`time`, 3=`flutter`, 4=`wow`, 5=`bias`, 6=`gain` |
| `timeEnsemble` ⚠ | 1 | 20 | 9 | 0=`rate`, 1=`intensity`, 2=`feedback`, 3=`vibrato`, 4=`tone`, 5=`time`, 6=`regen`, 7=`gain`, 8=`pan` |
| `timePhaser` | 4 (0,1,2,3) | 20 | 9 | 0=`mix`, 1=`feedback`, 2=`sweep`, 3=`rate`, 4=`depth`, 5=`tone`, 6=`regen`, 7=`time`, 8=`gain` |
| `vocoder10` | 4 (0,1,2,3) | 16 | 5 | 0=`mix`, 1=`sib`, 2=`sensitivity`, 3=`tone`, 4=`noiseGain` |
| `vocoder16` | 4 (0,1,2,3) | 16 | 5 | 0=`mix`, 1=`sib`, 2=`sensitivity`, 3=`tone`, 4=`noiseGain` |
| `vocoder21` | 4 (0,1,2,3) | 16 | 5 | 0=`mix`, 1=`sib`, 2=`sensitivity`, 3=`tone`, 4=`noiseGain` |

⚠ = orphan, no source in this firmware. ‡ = infrastructure synth, not a slot effect.
**[READ]** — every row parsed from the corresponding `.scsyndef`. Within each family
all variants carry identical control names (checked; no family is flagged as varying).

Two things worth pulling out:

- The **vocoders are the only effect families with no trailing `gain`** — their last
  parameter is `noiseGain` at index 4.
- `none_N` has 8 controls, so `psize = −3`. **[READ]** Every `if(pindex < psize)` is
  false, and `.set(\pan/\g_in/\g_out, …)` on a `none_N` slot targets controls that do
  not exist. A `none_N` slot silently swallows every gain and pan message.

---

## 10. The bus map

Read directly out of the two router SynthDefs. All **[READ]**.

### 10.1 Absolute bus numbers

With `numOutputBusChannels = 8` and `numInputBusChannels = 9`
(`init_sc_1.scd:11-12`): buses **0-7 = hardware out**, **8-16 = hardware in**,
17 upward private. **[INFERRED — firmly]** from SuperCollider's fixed bus layout.

This is why `efx_server.scd:508` and `:813` add **8** to an incoming hardware input
index, and why `:511` (the bus-slot branch) does **not** — those numbers are already
absolute private buses.

### 10.2 `inputRouter` (`synthdefs.scd:224-398`)

Reads:

| Source | Line |
|---|---|
| `send1 = SoundIn.ar(2) * send1Gain` | `:276` |
| `send2 = SoundIn.ar(3) * send2Gain` | `:288` |
| `insert1 = In.ar([50, 51])` | `:294` |
| `insert2 = In.ar([52, 53])` | `:295` |
| `insert3 = In.ar([54, 55])` | `:296` |
| `InFeedback.ar(master1_out_busses[0..1])` where `master1_out_busses = [60, 61]` | `:273`, `:362`, `:371` |

Writes:

| Destination | Line |
|---|---|
| `Out.ar(56, to_master1[0])`, `Out.ar(57, to_master1[1])` | `:380-381` |
| `Out.ar(58, to_master2[0])`, `Out.ar(59, to_master2[1])` | `:384-385` |

The send noise gate is `DetectSilence.ar(send, thresh, 0.01)`, inverted, `Lag.ar`ed
with a `Select.kr`-chosen time constant (`relaxTime` when silent, `clampTime` when
not), clipped to `[gainFactorMin, 1]` (`:277-279`, `:289-291`).

Defaults: `send1Thresh = send2Thresh = 0.0001`, `clampTime = 0.01`, `relaxTime = 4.0`,
`gainFactorMin = 0.1` (`:258-262`).

`/fx/bus-mode` (`efx_server.scd:132-142`):

- **mode 0, dual mono** — `send1_r = [1,1,0,0]`, `send2_r = [0,0,1,1]`: send 1 doubled
  into master 1 L+R, send 2 doubled into master 2 L+R.
- **mode 1, stereo** — `send1_r = [0,0,1,0]`, `send2_r = [0,0,0,1]`: **master 1
  receives nothing from the sends**; master 2 gets a genuine stereo pair.

### 10.3 `outputRouter` (`synthdefs.scd:401-593`)

Reads:

| Source | Line |
|---|---|
| `insert1 = In.ar([50, 51])` | `:460` |
| `insert2 = In.ar([52, 53])` | `:461` |
| `insert3 = In.ar([54, 55])` | `:463` |
| `master1 = In.ar([60, 61])` | `:464` |
| `master2 = In.ar([62, 63])` | `:465` |
| `dry_dir1..3 = Pan2.ar(In.ar(synthN_in_ch), dry_N_p)` | `:473-475` |

Writes — and this is the ESAI channel map:

| Statement | Line |
|---|---|
| `Out.ar(7, main[0] * -1)` | `:564` |
| `Out.ar(0, main[1] * -1)` | `:565` |
| `Out.ar(2, sub[0])` | `:566` |
| `Out.ar(1, sub[1])` | `:567` |
| `Out.ar(5, aux1.sum)` | `:568` |
| `Out.ar(6, aux2.sum)` | `:569` |
| `Out.ar(3, aux3.sum)` | `:570` |
| `Out.ar(4, aux4.sum)` | `:571` |

The block is preceded by the comment `// esai` (`:563`) and **followed by a
commented-out alternative labelled `// usb`** with a different permutation
(`:573-581`). **[READ]** This is direct file evidence for the repository's recent
"ESAI, not USB" correction (commit `cf7c6bd`): the USB map was tried and abandoned in
the shipping source.

Note the **phase inversion on both main channels** (`* -1`) and its absence on sub and
aux. **[READ]**

`main` and `sub` pass through `StereoSpread.ar(…, stereoSpread)` (`:560-561`), a
pure-sclang composite from `SCClassLibrary/Effects/StereoSpread.sc`, driven by
`fx/spread`.

### 10.4 The complete chain

**[INFERRED — firmly]** from the read constants above:

```
hw in 2 ──► send1 ─┐   (noise gate)
hw in 3 ──► send2 ─┤
                   ├─► inputRouter ──► 56,57 ──► slot 3 ──► 60,61 ─┐
bus 50,51 (slot 0) ┤                └─► 58,59 ──► slot 4 ──► 62,63 ┤
bus 52,53 (slot 1) ┤                                                │
bus 54,55 (slot 2) ┘        InFeedback(60,61) * par_amount ─────────┘
                                        (master 1 into master 2)

outputRouter reads 50-55, 60-63, plus 3 panned analog dry taps
   → main (StereoSpread) → hw out 7, 0   (both phase-inverted)
   → sub  (StereoSpread) → hw out 2, 1
   → aux1..aux4 (mono)   → hw out 5, 6, 3, 4
```

The 56-59 → 60-63 gap is exactly the two bus effect slots: **slot 3 in 56,57 out
60,61; slot 4 in 58,59 out 62,63**. **[INFERRED]** — nothing else writes 60-63, and
`efx_server.scd:511` builds bus-slot `inBus` as `[msg[3], msg[3]+1]`, an adjacent
pair.

### 10.5 Two defects in `outputRouter`

- **`dry_dir4 = 1`** (`synthdefs.scd:476`) — a **constant**, not a signal, added to
  each aux as `dry_dir4 * dry_dir4_r[k]` (`:525,535,545,555`). Its routing vector
  defaults to `[0,0,0,0]` (`:422`), so it contributes nothing today; setting any
  element non-zero would inject **DC** into that aux. **[READ]** for the constant and
  the default, **[INFERRED]** for the consequence.
- The per-slot controls are **not** dimensioned for five slots. `insert_N_g`,
  `timbre_N_dry`, `timbre_N_dry_main`, `dry_N_p` and `synthN_in_ch` exist only for
  **N = 1, 2, 3**; `dry_dir_N_r` exists for **N = 1..4** (`synthdefs.scd:419-446`,
  and confirmed against the 35 parsed control names of `outputRouter.scsyndef`).
  **[READ]** But `efx_server.scd` computes these names as `unitNum + 1` for all five
  slots:
  - `:443`, `:583`, `:723` → `insert_4_g` / `insert_5_g` for slots 3, 4 — do not exist;
  - `:759` → `dry_4_p` / `dry_5_p` — do not exist;
  - `:824` → `synth4_in_ch` / `synth5_in_ch` — do not exist;
  - `:853` → `dry_dir5_r` for slot 4 — does not exist;
  - `:928`, `:950` → `timbre_4_dry` / `timbre_5_dry` and their `_main` twins — do not exist.

  **[READ]** for the name construction, **[INFERRED]** for the outcome: each is a
  silent "Control not found" no-op on the server. This is consistent — the router was
  designed for three insert returns and two master returns, and the five-slot loop in
  `efx_server.scd` addresses it as if all five were inserts.

---

## 11. The ten parked Eventides and the `doneAction` invariant

### 11.1 The invariant, exactly

`grep -n doneAction synthdefs.scd` returns **32 occurrences**, and they partition
cleanly. **[READ]**

- **`doneAction: 2`** (free the synth) — 26 occurrences, at lines 49, 83, 125, 160,
  200, 377, 619, 667, 754, 880, 1038, 1178, 1313, 1427, 1548, 1656, 1764, 1976, 2107,
  2237, 2339, 2546, 2662, 2769, 2988, 3218. That is every non-Eventide definition,
  including `inputRouter` (`:377`) and the `none_N` family (`:49`).
- **`doneAction: 1`** (pause the synth) — **6** occurrences, at lines **3407**
  (`et_blackhole`), **3492** (`et_room`), **3576** (`et_hall`), **3657**
  (`et_spring`, inside the comment block), **3735** (`et_plate`), **3817**
  (`et_shimmer`). That is every Eventide definition and nothing else.

Five of the six carry `Env.asr(0.1, 1, 0.1)`; `et_spring` alone uses
`Env.asr(0.1, 1, 2)` — a 2-second release — and it is the one that is commented out.
**[READ]**

**This is the load-bearing invariant.** `.run(false)` at boot merely stops them; it is
`doneAction: 1` that guarantees `enable → 0` **pauses rather than frees**, which is
what lets one node be parked, adopted into a slot, returned to the parking lot and
adopted again for the life of the process. Change any of those six to `2` and the
first bypass destroys the instance; the next selection of that reverb finds
`~eventides.at(\et_hall_1)` pointing at a freed node, every `.set` vanishes, and
`~fxEnableCheckRoutine` spins forever against a node id that will never report 0.
**[INFERRED]** from the code paths at `efx_server.scd:245-261` and `:1005-1028`.

### 11.2 The ten instances

`init_sc_1.scd:74` `~eventides = Dictionary.new(10)`, then five reverbs × two
variants, each created and immediately `.run(false)` on the next line:

| Key | Created | Paused |
|---|---|---|
| `et_blackhole_1` | `:76` | `:77` |
| `et_blackhole_2` | `:79` | `:80` |
| `et_room_1` | `:82` | `:83` |
| `et_room_2` | `:85` | `:86` |
| `et_hall_1` | `:88` | `:89` |
| `et_hall_2` | `:91` | `:92` |
| `et_plate_1` | `:94` | `:95` |
| `et_plate_2` | `:97` | `:98` |
| `et_shimmer_1` | `:100` | `:101` |
| `et_shimmer_2` | `:103` | `:104` |

**[READ]** No spring. The dead `init.scd:93-98` creates **six** (bare `\et_blackhole`,
`\et_room`, `\et_hall`, `\et_plate`, `\et_shimmer`, `\et_spring`) and `init_sn.scd`
likewise — that is where the "six reverbs" impression comes from, and both files are
dead. **[READ]**

### 11.3 `mix` is forced to 1 on every Eventide

Each Eventide SynthDef declares `mix = 0.5` as an argument and then **overwrites it
with the constant 1** immediately before the `LADSPA.ar` call:

`synthdefs.scd:3415` (blackhole), `:3499` (room), `:3582` (hall), `:3661` (spring),
`:3739` (plate), `:3825` (shimmer) — all six read `mix = 1;`. **[READ]**

**[INFERRED]** Therefore `\mix` on an Eventide — whether written via `/fxN/mix`
(`efx_server.scd:698`) or as panel parameter 0 — is **inert**: the plugin always runs
100% wet, and the wet/dry blend has to come from the router's dry paths
(`timbre_N_dry`, `dry_dir*`) instead. This is checkable statically in the compiled
graph (§15, V5) and would explain any report that the mix knob on a reverb behaves
differently from the mix knob on a delay.

The output stage is `Out.ar(outBus, ((sig * g_out *
ControlSpec.new(0.01, 2.25, \exp, 0.01).map(gain)).softclip) * env)`
(`synthdefs.scd:3422` and equivalents). **[READ]** — an exponential 0.01–2.25 gain
map, then `softclip`, then the envelope.

The Eventides also use `env.floor` on the structural parameters — `preDelay * env.floor`,
`size * env.floor`, `decay * env.floor` (`:3417-3419` and equivalents). **[READ]**
`floor` of the ASR envelope is 1 only while the envelope is exactly at 1, so those
parameters collapse to 0 for the whole duration of any fade. **[INFERRED]** — this is
the mechanism that keeps the reverb tail from being dragged through a size change.

---

## 12. Dead weight inside the region

All **[READ]** unless noted.

| Item | Why it is dead |
|---|---|
| `launch-sc`, `launch-sn` | both `cd /usr/share/efx/`, which does not exist |
| `launch-sc-2` | symlink to `launch-sc-1`; loading `init_sc_2.scd` would need a different argument, and nothing passes one |
| `init.scd` | `Server.internal`, blockSize 256, `LADSPA.ladspalist_path`, `cgclassify -g cpu,cpuset:scsynth0` (a group that does not exist), six bare `et_*` |
| `init_sc_2.scd` | two-scsynth config (`\server_a` 57110 / `\server_b` 57111, blockSize 256), 22 `jack_connect`/`jack_disconnect` calls; only reachable through `launch-sc-2`, which is `launch-sc-1` |
| `init_sn.scd` | supernova variant |
| `tables/` | `load_tables.scd` is invoked **only** from `init_sc_1.scd:28`, which is commented out; and `synthdefs.scd` uses **no** lookup-filter UGen — grep for `APFTable\|BPFTable\|LPFTable\|HPFTable\|Crossover\|~coefs` returns zero hits. `coefsEnvir` is 5,426,278 bytes of unused data. |
| `util/*` | developer scratch: `bootServer.scd` (2 lines), `bootServers.scd` (two servers on 57711/57712, hard-coded `192.168.1.1`), `env_test.scd`, `soundcard-test.scd` (white noise to all 8 outs — **do not run**), `osc.scd`, `audioIn.scd`, `test.scd`, `test_gui.scd`, `test_server.scd` |
| `SCClassLibrary/Effects/*.so` | §3.1 |
| `ladspa/` | §8.2 |
| `README.md` | describes an OSX/Linux `sys=` build split that `compile-synthdefs` does not use |

### 12.1 `util/cpu.rtf` — a developer CPU-cost table, at the wrong block size

Its first line is **`block size 512`**. **[READ]** The shipping configuration is 128
(§4). Every number below is therefore *not* the cost on a shipping instrument.

| effect | % | effect | % |
|---|---|---|---|
| overhead | 3.4-3.9 | 4 stage phaser | 11.9-12.4 |
| delay | 3.8-4.3 | 6 stage phaser | 14.6-15.2 |
| bbdelay | 13.8-14.4 | 12 stage phaser | 23.1-23.9 |
| pingpongdelay | 8.8-9.3 | bit crusher | 5.6-6.3 |
| tape delay | 20.8-21.1 | resonator | 11.5-12.4 |
| tape echo | 18.8-20 | **eventide blackhole** | **34.2-35.5** |
| echo | 19.2-21.2 | **eventide hall** | **39.8-40.5** |
| chorus | 6.7-7.2 | **eventide room** | **31.9-32.2** |
| dual chorus | 21.4-22 | **eventide plate** | **36.9-37.5** |
| triple chorus | 19.1-19.6 | **eventide shimmer** | **46.3-47.5** |
| space ensemble | 16.3-17.3 | time ensemble | 19.3-20.1 |
| space phaser | 22.1-22.6 | time phaser | 13.6-14.2 |
| phase ensemble | 12.9-13.5 | | |

**[READ]** verbatim from the RTF.

Two observations:

- The table names effects that do not exist as shipping families — "tape echo",
  "triple chorus", "space ensemble", "phase ensemble", "4 stage phaser" — and matches
  four of the seven orphans (`echo`, `timeEnsemble`, `spacePhaser`, and "space
  ensemble"/`spaceFlanger` by family). **[INFERRED]** the table predates the current
  synthdef set and is the closest thing in the region to documentation of what the
  orphans were.
- **There is no spring row.** **[READ]** Consistent with the spring never having been
  in a shipping build.
- The Eventides cost 32-47% each. **[INFERRED]** With five slots and two shimmer-class
  reverbs at ~47%, the practical ceiling on concurrent Eventides is two — and that is
  measured at block size 512, i.e. under the most favourable buffering.

### 12.2 `util/jack_ports.rtf` — a stale 2-in/2-out development note

Lists `system:capture_1/2` ↔ `SuperCollider:in_1/2` and `system:playback_1/2` ↔
`SuperCollider:out_1/2`, then a 20-entry port index. **[READ]** It describes a JACK
graph with **two** hardware channels; the shipping server has 8 out and 9 in and no
jackd at all (§2). Archaeology only.

---

## 13. What changed between v1.5.0 and v1.8.2

| Scope | Result |
|---|---|
| `usr/share/las-fx` entire tree | **identical**, `diff -rq` exit 0, 442 files each side **[READ]** |
| `usr/lib/SuperCollider` | **identical**, `diff -rq` clean **[READ]** |
| `usr/lib/ladspa` | 1.8.2 has 5; the 1.5.0 capture has 6 — **but the capture is contaminated**, see §8.6 **[READ]** |
| `usr/bin/scsynth` | md5 `570f38c5…` → `9b2519e3…` **[READ]** — content of the change **[UNKNOWN]** |
| `usr/bin/sclang` | md5 `724eb191…` → `34faeb22…` **[READ]** — content of the change **[UNKNOWN]** |

**[INFERRED]** The effects engine as a body of code and data did not change across
three minor releases. Any behavioural difference an owner perceives between 1.5.0 and
1.8.2 in the effects section comes from `las-sc`/`las-frontend` (which drive it), from
the two rebuilt SuperCollider binaries, or from preset content — not from this region.

---

## 14. Conflicts with existing documentation

Reported, not fixed, per the working rules.

**C1 · `docs/arch/effects-engine.md:119-141` (§1.1) is stale on block size.** It reads
"**Treat block size as 256 when reasoning about the live machine**". That was
superseded the same week by `docs/CORRECTIONS-2026-09-08.md` §2, which establishes
stock as 128 and identifies the 256 in `runtime-state.txt` as this project's own
running experiment. The 1.8.2 vendor image confirms 128 independently
(`init_sc_1.scd:9-10`). The paragraph should be retired or annotated.

**C2 · `docs/arch/effects-engine.md:276-278` overstates the spring's availability.**
It says "The LADSPA library `eventide_spring.so` **is** present". True of
`/usr/share/las-fx/ladspa`, but that directory is not on scsynth's search path (§8.2),
and the directory that *is* — `/usr/lib/ladspa` — does not contain plugin 29153 in the
stock 1.8.2 image (§8.4-8.5). The practical statement is: uncommenting and compiling
`et_spring` would **not** be sufficient; the plugin would also have to be placed in
`/usr/lib/ladspa` or `LADSPA_PATH` genuinely set.

**C3 · The LADSPA-resolution open question can be closed.**
`docs/arch/effects-engine.md:113-118` ("Not resolvable from this harvest — flagged as
an open question") and `docs/arch/audio-graph.md:431-433` ("Whatever makes the plugins
load, it is not that line") are both correct as far as they go. §8.2 answers it:
compiled-in default in `LadspaUGen.so`, `LADSPA_PATH` unset everywhere in the rootfs.

**C4 · `docs/arch/extension-points.md:1261-1264` attributes the CPU policy to
`assign-pids`.** It reads: "processes are placed into the groups by
`/usr/share/las-fx/assign-pids` … **This is the machine's whole CPU-affinity policy in
597 bytes** — `dsp` on cpu1, `frontend` and `sc` on cpu0". `assign-pids` contains no
`cgclassify` and no `cgexec`, and both of its `taskset` loops are commented out
(`:23-27`, `:55-59`). **[READ]** It sets scheduling *classes and priorities* and one
IRQ affinity, nothing else. The cgroup definitions come from `etc/cgconfig.conf` via
`cgconfigparser` at `S43gui:8`, and **nothing in the rootfs ever classifies a process
into them** (§5.4). The sentence conflates two mechanisms and credits a third that is
absent.

*(Note on the same passage: its "597 bytes" is **not** an error — `etc/cgconfig.conf`
is exactly 597 bytes **[READ]**, and its "1,345 bytes" for `assign-pids` is also
correct. Only the "processes are placed into the groups by … `assign-pids`" clause is
wrong.)*

**C5 · `docs/arch/effects-engine.md` does not record the `mix = 1` override.** §11.3
is, as far as this pass can tell, absent from `effects-engine.md` and `audio-graph.md`
(grep for `mix = 1` across `docs/**/*.md` hits only `doc-audit.md:1379`, and there only
in passing as a check on a Python file). It bears directly on §5's parameter model,
because it makes panel parameter 0 inert on five of the shipping effects.

**C6 · No document records the `assign-pids` priority values.** `SCHED_RR`, `chrt -r`
and `smp_affinity` appear in **zero** `.md` files in `docs/`. **[READ]** The numbers in
§5 (RR 94 main, FIFO 94 threads, FIFO 89 ESAI IRQ, FIFO 99 SDMA IRQ) are new to the
repository and are load-bearing for anything reasoning about xrun behaviour.

**Agreements worth recording** (checked, not conflicts): the orphan-synthdef list in
`audio-graph.md:877-887` is exactly right; the `doneAction` partition in
`effects-engine.md` §0.2 is exactly right; the `~efxServer[\state]` no-op in
`effects-engine.md` §0 is exactly right; the `et_spring` comment-block bounds in
`doc-audit.md:273` (`/*` 3629, `*/` 3700) are exactly right; the bus numbers in
`effects-engine.md` §2.2-2.3 all reproduce.

---

## 15. Validation plan

**READ-ONLY commands.** Nothing here writes, sets, or sends. For a human to run on the
instrument; this agent did not contact it. Each is tied to a claim above.

**V1 — the LADSPA directory scsynth actually used (§8.2, §8.5).** The decisive test.
scsynth prints `Found %d LADSPA plugins` at plugin-load time. If the engine's screen
session still holds the boot log:

```
screen -ls
grep -ri "LADSPA" /var/log/messages /var/log/* 2>/dev/null | head
```

Failing that, read the environment of the running scsynth — this both confirms
`LADSPA_PATH` is unset and shows the working directory:

```
tr '\0' '\n' < /proc/$(pidof scsynth | awk '{print $1}')/environ
```

Expected: **no `LADSPA_PATH` line**.

**V2 — the plugin files actually open (§8.2, §8.3).** Which `.so` the process has
mapped is conclusive:

```
grep -i ladspa /proc/$(pidof scsynth | awk '{print $1}')/maps
```

Expected: paths under `/usr/lib/ladspa/`, and **none** under `/usr/share/las-fx/ladspa/`.

**V3 — the stock plugin inventory (§8.3, §8.6).** Confirms the vendor image against
the live instrument and re-checks that the spring copy is gone:

```
ls -la /usr/lib/ladspa/ /usr/share/las-fx/ladspa/
md5sum /usr/lib/ladspa/*.so /usr/share/las-fx/ladspa/*.so
```

**V4 — block size and server options (§4).** Independent of `runtime-state.txt`:

```
cat /proc/$(pidof scsynth | awk '{print $1}')/cmdline | tr '\0' ' '; echo
sed -n '9,18p' /usr/share/las-fx/init_sc_1.scd
```

Expected `-z 128 -Z 128` if the harvested script is the running one; anything else
means the on-device script differs.

**V5 — the Eventide `mix` override (§11.3), no instrument needed.** Purely local, on a
copy of the compiled definition:

```
xxd /usr/share/las-fx/synthdefs/et_hall_1.scsyndef | head -40
```

Better done off-instrument: the constants pool of `et_hall_1.scsyndef` should contain
`1.0` reaching the `LADSPA` UGen's mix input, and the `mix` control should feed nothing.
Confirming this needs a UGen-graph walk of the `.scsyndef`, which is offline work —
listed here because it closes §11.3 without touching anything.

**V6 — the SDMA core-lock defect (§5.3).** The cheapest confirmation in this document.
Run exactly the pipeline `assign-pids:51` runs, and print the result:

```
ps | grep sdma
ps | grep sdma | awk '{print $3} NR==1{exit}'
ps | grep sdma | awk '{print $3} NR==1{exit}' | awk -F "-" '{print $1}' | awk -F "/" '{print $2}'
```

Expected under BusyBox's `PID PPID USER STAT VSZ %VSZ %CPU COMMAND`: the second command
prints `root` and the third prints **nothing**. Then check whether the intended pin
took effect anyway:

```
for d in /proc/irq/*/; do [ -e "$d/smp_affinity" ] && printf "%s %s\n" "$d" "$(cat $d/smp_affinity)"; done | head -40
grep -i sdma /proc/interrupts
```

**V7 — cgroups populated or empty (§5.4).** If the `tasks` files are empty, the cgroup
policy is scaffolding:

```
for g in dsp frontend sc; do echo "== $g"; cat /cgroup/cpuset/$g/tasks 2>/dev/null; done
cat /proc/$(pidof scsynth | awk '{print $1}')/cgroup
```

**V8 — the eleventh Eventide node (§7.4).** Needs a `/g_queryTree` from the effects
server, which is a read but is an OSC send; **this one should only be run if the owner
is comfortable sending the query that this project has already used before**, and it is
listed last for that reason. The static half can be done without it:

```
grep -n "fx.*_category" /usr/share/las-fx/efx_server.scd
sed -n '236,271p;505,520p' /usr/share/las-fx/efx_server.scd
```

**V9 — scheduling actually applied (§5.1, §5.2).** Confirms the RR 94 / FIFO 94 / 89 /
99 picture and shows whether any thread sits at RT 99 before `assign-pids` runs:

```
for t in /proc/$(pidof scsynth | awk '{print $1}')/task/*/; do
  printf "%s " "$(basename $t)"; awk '{print $18, $40}' $t/stat; done
chrt -p $(pidof scsynth | awk '{print $1}')
ps | grep -E "irq/[0-9]+-(esai|sdma)"
```

**V10 — the region is unchanged on the live 1.8.2 instrument (§13).** Cheap integrity
check of the claim that `las-fx` is identical to the vendor image:

```
find /usr/share/las-fx -type f | sort | xargs md5sum | md5sum
ls -la /usr/share/las-fx/
cat /etc/version
```

Compare the first line against the same command run over
`captures/firmware-1.8.2/rootfs-1.8.2/usr/share/las-fx`.

---

## 16. Unexplored

Honest list of what this pass did not reach.

1. **The UGen graphs of the 104 compiled synthdefs.** The parser reads the header,
   constants, parameters, control names and UGen *names*; it does not walk the input
   wiring. So the per-effect DSP topology of the seven orphans — which have no source
   at all — is undetermined. That is the largest single gap in the region, and it is
   pure offline work.
2. **What changed in `scsynth`/`sclang` between 1.5.0 and 1.8.2.** Both binaries
   differ by md5; neither was diffed. Given that everything around them is identical,
   this is where any behavioural change in the effects section must live.
3. **The 97 differing class-library files.** Counted, not diffed. Whether they are
   Moog edits or a SuperCollider version skew is undetermined (§3), and the two
   version strings in `sclang` (3.6.0 and 3.9.0) make it worth a proper pass.
4. **`tables/coefsEnvir`** — 5.4 MB of binary `IdentityDictionary` archive, never
   parsed. Established as unreachable at runtime, not as uninteresting; it holds the
   biquad coefficient tables for the `*Table` filter classes and would document a
   filter design.
5. **`util/test.scd`, `util/test_gui.scd`, `util/test_server.scd`** — read for
   references and `cgclassify` calls only, not analysed. `test_gui.scd:279` mentions
   `\et_spring` in an effect picker, which suggests it is the closest thing to a
   developer harness for the region.
6. **Whether `LadspaUGen.so` scans at `load()` time or lazily.** `load` is 188 bytes
   at `0x0f48` and is ARM-mode, not Thumb; it was not disassembled cleanly. This does
   not change the §8 conclusion (`LADSPA_PATH` is unset either way) but it does
   determine whether the plugin set is fixed at scsynth start.
7. **`.txarcmeta` parameter documentation for the seven orphans.** The format was
   identified and one file read; the human-readable parameter descriptions for
   `echo`, `bitcrusher2`, `spaceFlanger`, `spacePhaser` and `timeEnsemble` are sitting
   in those files unread, and they are the only documentation of those effects that
   exists.
8. **`Node.set` with an array value against a scalar control.** `efx_server.scd:824`
   and `:928` pass arrays to `synthN_in_ch` and `timbre_N_dry`, which are scalar
   controls. Whether scsynth takes the first element, errors, or writes a control
   range was not determined.
9. **The relationship between the shipping effect list the panel offers and the 37
   compiled families.** Requires the `las-frontend`/`las-sc` side, which is outside
   this region.
