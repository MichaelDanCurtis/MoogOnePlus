# The on-device profiling, tracing and system-accounting toolkit

Firmware 1.8.2 root filesystem, cross-checked against 1.5.0.
Written 2026-09-10 entirely from files on local disk. Nothing was run on the
instrument. No Moog binary was executed.

---

## 0. Headline

The shipping rootfs carries **17.5 MiB of measurement tooling across 77 files**
— strace, ltrace, gdb, gdbserver, htop, the complete sysstat suite, the complete
blktrace suite, apitrace, the libcap-ng process scanners, and ~35 JACK measurement
clients — and the inventory has **not changed by a single file between v1.5.0
(May 2022) and v1.8.2 (September 2025)**.

Roughly half of it cannot work on this device, and the reasons are specific and
checkable:

| group | verdict |
|---|---|
| sysstat (`iostat`/`mpstat`/`pidstat`/`sar`) | **works, and is the most valuable thing here.** Never scheduled, so no history exists — but live mode needs nothing but `/proc`. |
| blktrace suite (11 files) | **dead.** The kernel has no `CONFIG_BLK_DEV_IO_TRACE` and no ftrace at all, and `debugfs` is not mounted. |
| apitrace (12.4 MiB, the single largest item) | **effectively dead.** Requires `LD_PRELOAD` into a restarted GUI; its helper scripts are Python and there is no Python interpreter on the device. |
| ~35 `jack_*` clients | **inert.** `scsynth` uses its own `SC_AlsaDriver` straight to ALSA; no `jackd` process exists on any capture. Starting one would fight `scsynth` for the sound card. |
| gdb / gdbserver | **low value, high risk.** Every Moog binary is stripped to `.dynsym` only, gdb 7.9.1 has no Python, and attaching stops a `SCHED_FIFO 99` audio thread. |
| `netcap`, `pscap`, `cpuload`, `lscpu`, `dumpe2fs` | **safe, read-only, and each closes a question this project has already recorded as unanswerable.** |
| `memtester`, `stress`, `jack_cpu`, `chcpu`, `devmem`, `filecap` (2-arg form) | **destructive.** Named here so nobody reaches for them by mistake. |

The single most useful sentence in this report: **`pidstat -t -w -p $(pidof scsynth)`
gives per-thread CPU and per-thread involuntary-context-switch counts for the audio
engine, reads nothing but `/proc`, writes nothing, and is already installed.**

---

## 1. Two corrections to the premise of this assignment

The brief that commissioned this report contained two claims that do not survive
checking. Both are recorded here rather than quietly worked around.

### 1.1 These tools *are* named in the existing documentation — once, in a list

**[READ]** `docs/MOOG-ONE-INTERNALS.md:1794-1795`:

```
gdb   gdbserver   strace   ltrace   tcpdump   lsof   htop
apitrace  glretrace  eglretrace
```

under the heading `### Debugging and inspection`, with the one-line gloss that
`tcpdump` "would capture the entire voice-bus conversation". The same block is
mirrored in `docs/site/moog-one-internals.html:1201`.

So the brief's "`strace` 0, `ltrace` 0, `gdbserver` 0, `htop` 0, `lsof` 0,
`apitrace` 0" is wrong as an occurrence count. What *is* true, and is the real
gap: **`blktrace` 0, `iostat` 0, `mpstat` 0, `pidstat` 0, `sadc` 0, `sysstat` 0,
`usr/lib/sa` 0, `gcore` 0, `memtester` 0, `cpuload` 0, `gmem_info` 0, `pscap` 0,
`filecap` 0, `netcap` 0, `btt` 0, `iowatcher` 0, `sadf` 0, `jack_cpu_load` 0,
`jack_iodelay` 0** — verified by `grep -rIF` across `docs/` on 2026-09-10. And
no document anywhere states what any of these tools *does on this hardware*, or
whether it is safe to run. That is the gap, and it is real.

### 1.2 sysstat would **not** write into RAM — `/var` is a persistent ext4 partition

The brief inferred: "were it enabled it would write into RAM and vanish at reboot",
from `var/log -> ../tmp` plus `/tmp` being tmpfs.

That symlink exists **[READ]** (`rootfs-1.8.2/var/log -> ../tmp`, and identically in
`rootfs-1.5.0/var/log`), but it lives in the *root* filesystem's `/var` skeleton,
and that skeleton is **shadowed at boot**:

**[READ]** `rootfs-1.8.2/etc/fstab:10`

```
/dev/mmcblk2p6  /var    ext4    defaults,noatime        0       1
```

**[READ]** `captures/arch-harvest/runtime-state.txt`, `--- mounts ---` section — a
section the project's own `CAVEAT-runtime-state.md` explicitly certifies as
uncontaminated ("`runtime-state.txt` remains valid evidence for … mounts"):

```
/dev/root on / type ext4 (rw,relatime,errors=remount-ro,data=ordered)
tmpfs on /tmp type tmpfs (rw,relatime)
/dev/mmcblk2p6 on /var type ext4 (rw,noatime,data=ordered)
```

**[READ]** `captures/moog-recon/01-system.txt`, `df` from a second, independent boot:
`/dev/mmcblk2p6  3.8G  290.4M used  3.3G available  8%  /var`, while `/tmp` shows
92 KB used of 248 MB.

**[INFERRED]** `SA_DIR=/var/log/sa` therefore resolves onto a 3.8 GB ext4 partition
with 3.3 GB free, not onto tmpfs. Seven days of `sadc` at one sample per ten
minutes is on the order of a few megabytes — trivially affordable, and it would
survive reboots.

**[UNKNOWN]** — and this is the one thing that cannot be settled from disk —
whether `/var/log` *on that partition* is a real directory or is itself a symlink
to `/tmp`. The partition contents are not in this capture set. Two independent
pieces of circumstantial evidence say "real directory":

* **[READ]** `etc/init.d/S14fs:67` — `mv /var/log/las-watchdog.log /var/log/las-watchdog.log.0`
  runs at boot, i.e. the code expects the *previous boot's* log to still be there.
* **[READ]** `etc/init.d/S99final:24` — `las-watchdog -t=10000 > /var/log/las-watchdog.log 2>&1`,
  and **[READ]** `etc/init.d/S12splash:5` appends to `/var/log/messages`.

One `readlink /var/log` settles it. It is Block 1 of the validation plan in §8.

---

## 2. Method and grading

Sources, all local:

* `captures/firmware-1.8.2/rootfs-1.8.2/` — decrypted v1.8.2 root filesystem.
* `captures/rootfs-1.5.0/` — v1.5.0 root filesystem.
* `captures/arch-harvest/runtime-state.txt` — live capture, read under the
  restrictions in `CAVEAT-runtime-state.md`.
* `captures/moog-recon/*.txt`, `captures/harvest/*.txt` — earlier live captures.
* `boot/uImage` — see below.

Techniques: `ls`, `readlink`, `md5`, `strings -a`, `xxd`, `diff`, and
`llvm-objdump -p` for `DT_NEEDED`/`RPATH`. No binary was executed.

**The kernel was decompressed and read.** `boot/uImage` is a U-Boot image with
`comp=0`, `name="Linux-4.1.15-rt18"`, load `0x10008000` **[READ]** — i.e. a
self-decompressing zImage. Its payload is a single gzip stream at file offset
**18264**, decompressing to a **10,214,816-byte** ARM kernel image, whose banner
reads **[READ]**:

```
Linux version 4.1.15-rt18 (root@terry) (gcc version 4.8.5 (Buildroot 2016.02-rc2-dirty)) #1 SMP PREEMPT RT Mon Sep 15 14:38:28 EDT 2025
```

Kernel feature claims below are made by testing for **exported-symbol names**,
which appear verbatim and NUL-separated in `__ksymtab_strings`, and for
**distinctive printk/seq_printf format strings**. Every such test is run
alongside controls known to be present. The control set used throughout:

| probe | count | meaning |
|---|---|---|
| `_raw_spin_lock` | 1 | control — exported symbol, must be present |
| `sched_setscheduler` | 1 | control |
| `kmem_cache_alloc` | 1 | control |
| `snd_pcm_hw_constraint_list` | 1 | control — ALSA present |
| `isolcpus` | 1 | control |
| `RT throttling activated` | 1 | control |

`grep -x` on exported symbol names is reliable. `grep -x` on *format* strings is
not — e.g. `Cpus_allowed_list` fails an exact-line match but matches as a
substring (`Cpus_allowed_list:`), because it is embedded in a larger format
string. Substring matching is used for those, and the matched line is quoted.

**Grades.** `[READ]` = read directly out of a named file, with offset or line.
`[INFERRED]` = reasoned from stated evidence. `[UNKNOWN]` = not determinable from
the material.

---

## 3. Complete inventory

All sizes in bytes, from `ls -la` on `rootfs-1.8.2` **[READ]**. "1.5.0" column:
`IDENT` = byte-identical `md5` to the 1.5.0 copy; `rebuilt` = same file present,
different hash.

### 3.1 The ptrace family

| path | bytes | version | `DT_NEEDED` | 1.5.0 |
|---|---|---|---|---|
| `usr/bin/strace` | 288,804 | **4.11** | `libc.so.6` | IDENT `8c66b380…` |
| `usr/bin/strace-log-merge` | 944 | — | `#!/bin/sh` | IDENT |
| `usr/bin/ltrace` | 198,960 | **0.7.91** | `libelf.so.1`, `libstdc++.so.6`, `libdw.so.1`, `libc.so.6` | IDENT `068138ac…` |
| `usr/bin/gdb` | 3,367,328 | **7.9.1** | `libdl`, `libncurses.so.5`, `libz`, `libm`, `libexpat.so.1`, `libc` | rebuilt |
| `usr/bin/gdbserver` | 223,008 | **7.9.1** | `libdl.so.2`, `libc.so.6` | IDENT `042ff277…` |
| `usr/bin/gcore` | 2,945 | — | `#!/bin/sh` | IDENT |

**[READ]** Every one of those `DT_NEEDED` libraries is present: `usr/lib/libelf.so.1`,
`usr/lib/libdw.so.1`, `usr/lib/libncurses.so.5`, `usr/lib/libexpat.so.1`,
`usr/lib/libstdc++.so.6`, `usr/lib/libz.so.1`, `lib/libgcc_s.so.1`. Nothing here
fails to load.

**[READ]** `gdb`'s `RPATH` leaks the vendor's build root:
`/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/host/usr/arm-buildroot-linux-gnueabihf/sysroot/usr/lib`.
The same `las-ci-builds` prefix appears in the `RPATH` of `pscap`, `filecap` and
`netcap` (`…/output/build/libcap-ng-0.7.4/src/.libs`). **[INFERRED]** These are
Moog's own Buildroot packages, selected deliberately, not vendor BSP leftovers.

**[READ]** `strace`'s usage banner is `usage: strace [-CdffhiqrtttTvVwxxy] [-I n] [-e expr]...`
— note there is **no `-k`**, so no stack unwinding; it is not linked against
libunwind either.

**[READ]** Every Moog binary is stripped. `llvm-objdump -h` on `usr/bin/scsynth`,
`usr/bin/las-sc`, `usr/bin/las-frontend`, `usr/bin/sclang` and `usr/bin/las-dwm`
shows `.dynsym` and **no `.symtab`, no `.debug_info`, and no `.gnu_debuglink`**.
There is no `/usr/lib/debug` tree anywhere in the image.

**[INFERRED]** Consequence: `gdb` on this device can resolve dynamic symbols and
nothing else. A backtrace inside `las-sc` or `scsynth` will be a list of raw
addresses. `ltrace`, which hooks PLT entries and therefore only needs `.dynsym`,
is strictly more useful here than `gdb` — the exact opposite of the usual
expectation.

### 3.2 sysstat 11.2.0 — the part that actually works

| path | bytes | 1.5.0 |
|---|---|---|
| `usr/bin/iostat` | 34,756 | rebuilt |
| `usr/bin/mpstat` | 30,656 | rebuilt |
| `usr/bin/pidstat` | 42,984 | rebuilt |
| `usr/bin/sar` | 76,724 | rebuilt |
| `usr/bin/sadf` | 141,180 | rebuilt |
| `usr/bin/tapestat` | 26,572 | rebuilt |
| `usr/bin/cifsiostat` | 24,268 | rebuilt |
| `usr/lib/sa/sadc` | 67,380 | rebuilt |
| `usr/lib/sa/sa1` | 968 | — |
| `usr/lib/sa/sa2` | 1,287 | — |

All link `libc.so.6` only.

**[READ]** Build stamps prove this is rebuilt with every firmware, not a stale
artifact:

```
1.8.2  @(#)sysstat-11.2.0: sar.c compiled Sep 15 2025 15:09:28
1.5.0  @(#)sysstat-11.2.0: sar.c compiled May 16 2022 11:31:27
```

**[READ]** `sar` contains the literal `/usr/lib/sa/sadc` and a `--sadc` option,
so live mode locates the collector by absolute path.

**[READ]** `pidstat`'s compiled-in usage string — this is the capability list that
matters:

```
Usage: %s [ options ] [ <interval> [ <count> ] ]
[ -d ] [ -h ] [ -I ] [ -l ] [ -R ] [ -r ] [ -s ] [ -t ] [ -U [ <username> ] ]
[ -u ] [ -V ] [ -v ] [ -w ] [ -C <command> ] [ -G <process_name> ]
[ -p { <pid> [,...] | SELF | ALL } ] [ -T { TASK | CHILD | ALL } ]
```

`-t` is per-thread. `-w` is context switches. `-R` is realtime priority/policy.
Which of these actually function is settled in §4.

**[READ]** `sadc`'s compiled-in source paths — every input it reads:

```
/sys/dev/block            /proc/stat              /proc/meminfo
/proc/uptime              /proc/loadavg           /proc/vmstat
/proc/diskstats           /proc/tty/driver/serial /proc/sys/fs/dentry-state
/proc/sys/fs/file-nr      /proc/sys/fs/inode-state /proc/sys/kernel/pty/nr
/proc/net/dev             /sys/class/net/%s/duplex /sys/class/net/%s/speed
/proc/net/rpc/nfs         /proc/net/rpc/nfsd      /proc/net/sockstat
/var/log/sa
```

Everything on that list except `/var/log/sa` is a read.

### 3.3 The blktrace suite — 11 files, all dead

| path | bytes | 1.5.0 |
|---|---|---|
| `usr/bin/blktrace` | 32,412 | IDENT `0abfd412…` |
| `usr/bin/blkparse` | 40,796 | IDENT `927faa13…` |
| `usr/bin/btt` | 53,844 | IDENT `30ba0330…` |
| `usr/bin/iowatcher` | 47,656 | IDENT |
| `usr/bin/blkiomon` | 19,024 | IDENT |
| `usr/bin/btrecord` | 12,924 | rebuilt |
| `usr/bin/btreplay` | 19,260 | rebuilt |
| `usr/bin/blkrawverify` | 8,132 | IDENT |
| `usr/bin/verify_blkparse` | 4,252 | IDENT |
| `usr/bin/btrace` | 891 | `#!/bin/sh` |
| `usr/bin/bno_plot.py` | 3,422 | `#! /usr/bin/env python` |

**[READ]** `blktrace` version string `2.0.0`; links `libpthread.so.0`, `libc.so.6`.

**[READ]** `btrace` is a shell wrapper whose last line is
`${DIRNAME}/blktrace ${TRACEOPTS} -o- $@ | ${DIRNAME}/blkparse ${PARSEOPTS} -i-`,
and it exposes `-r <dbg mnt>` — the debugfs mountpoint.

**[READ]** `bno_plot.py` needs `/usr/bin/env python`. There is **no Python
interpreter in the image**: `usr/lib/python2.7/` exists but contains only an empty
`site-packages/`, and there is no `python`, `python2`, `python3`, `perl` or `php`
binary anywhere in `bin`, `sbin`, `usr/bin` or `usr/sbin`. Corroborated live —
**[READ]** `captures/moog-recon/06-toolchain.txt`: `python: (absent)`,
`python3: (absent)`, `perl: (absent)`.

Why the whole suite is dead: §4.

### 3.4 apitrace — 12.43 MiB, the single largest item, and it is vendor BSP

| path | bytes |
|---|---|
| `usr/bin/apitrace` | 255,568 |
| `usr/bin/glretrace` | 3,345,796 |
| `usr/bin/eglretrace` | 3,345,316 |
| `usr/lib/apitrace/wrappers/glxtrace.so` | 3,051,908 |
| `usr/lib/apitrace/wrappers/egltrace.so` | 3,031,396 |
| `usr/lib/apitrace/scripts/*.py` | 8 files, 77,410 total |

Total **13,029,984 B = 12.43 MiB**. `apitrace`, `glretrace` and `eglretrace` are
byte-identical to their 1.5.0 copies (`apitrace` md5 `997d5121…`).

**[READ]** A build path embedded in `usr/bin/apitrace`:

```
/home/bamboo/automation/3.14.52-1.1.1/graphics_pkg/temp_build_dir/build-imx6qsabresd/
  tmp/work/cortexa9hf-vfp-neon-mx6qdl-poky-linux-gnueabi/imx-apitrace-x11/git-r0/git/
  common/os_string.hpp
```

**[INFERRED]** This is NXP's `imx-apitrace-x11` from the i.MX graphics package
3.14.52-1.1.1, built under Yocto/Poky for the `imx6qsabresd` reference board —
*not* built by Moog's Buildroot (contrast the `las-ci-builds` RPATHs in §3.1).
Same story for `gmem_info`, which links `libGAL.so`. So the largest single block
of "profiling tooling" on the instrument is a vendor BSP default that nobody chose.
The eight `usr/lib/apitrace/scripts/*.py` helpers are dated **10 March 2016**,
nine years older than the rest of the image, and are Python — dead per §3.3.

### 3.5 libcap-ng process scanners — small, safe, and useful

| path | bytes | `DT_NEEDED` |
|---|---|---|
| `usr/bin/pscap` | 6,480 | `libcap-ng.so.0`, `libc.so.6` |
| `usr/bin/netcap` | 9,952 | `libcap-ng.so.0`, `libc.so.6` |
| `usr/bin/filecap` | 6,220 | `libcap-ng.so.0`, `libc.so.6` |

`usr/lib/libcap-ng.so.0` is present **[READ]**. libcap-ng 0.7.4, from the RPATH.

**[READ]** `netcap`'s compiled-in strings show exactly how it works:

```
/proc            /proc/%d/stat        /proc/%d/status      /proc/%d/fd
socket:          /proc/net/packet     /proc/net/dev
%-5s %-5s %-10s %-16s %-4s %-6s %s        <- header: ppid pid acct command type port …
%d: %64[0-9A-Fa-f]:%X %64[0-9A-Fa-f]:%X %X %lX:%lX %X:%lX %lX %d %d %lu %512s
```

It walks `/proc/<pid>/fd`, matches `socket:` symlinks, and joins them against the
`/proc/net/{tcp,udp,packet}` tables. That is precisely a `netstat -p`. See §7.3.

**[READ]** `pscap` reads only `/proc/<pid>/{stat,status}`.

**[READ]** `filecap` contains `Could not open %s for writing (%s)` — **[INFERRED]**
its two-argument form *sets* file capabilities. Bare `filecap` is a read-only scan;
`filecap <path> <cap>` is a write. Treat with care.

### 3.6 Process, CPU and memory tools

| path | bytes | notes |
|---|---|---|
| `usr/bin/htop` | 95,440 | **1.0.3**; `libncurses.so.5`, `libm`, `libc`. IDENT to 1.5.0 (`34d7fdc9…`) |
| `usr/bin/cpuload` | 18,228 | NXP; reads `/proc/stat` only. IDENT |
| `usr/bin/gmem_info` | 7,852 | links `libGAL.so`; Vivante GPU memory. IDENT |
| `usr/bin/memtester` | 14,300 | **allocates and mlocks RAM.** IDENT |
| `usr/bin/lscpu` | — | util-linux |
| `usr/bin/taskset` | — | util-linux, a real binary (not busybox) |
| `usr/bin/chrt` | — | util-linux, a real binary |
| `sbin/chcpu` | — | util-linux — **can offline a CPU** |
| `usr/sbin/readprofile` | — | reads `/proc/profile` |
| `usr/bin/stress` | — | **load generator** |
| `usr/bin/lsof` | 17 | **symlink → `../../bin/busybox`** |
| `usr/bin/top`, `free`, `fuser`, `du`, `uptime`, `time`, `watch`, `bin/ps`, `bin/df` | 7–17 | all busybox symlinks |

`bin/busybox` is **BusyBox v1.24.1, built 2025-09-15 14:21:08 EDT** **[READ]**.

**[READ]** — a detail with consequences — **`lsof` is busybox's applet, not real
lsof.** Any prior reasoning that treated `lsof` as the full tool is wrong about
its options. Busybox `lsof` takes no arguments and dumps every process's fd table.

**[READ]** `stat` is compiled into busybox (it appears in the applet name table)
but **is not symlinked anywhere** — there is no `stat` on `PATH`. It is reachable
only as `busybox stat`. **[UNKNOWN]** whether this build has
`CONFIG_FEATURE_STAT_FILESYSTEM` (i.e. `stat -f`); the long-help strings are
compiled out, so it cannot be determined from the binary. One command settles it
(§8, Block 7).

**[READ]** `cpuload`'s complete option set:

```
-h --help             Print this help screen
-s --simple           Simplify the output
-q --quiet            Suppress all normal output
-c --cpu <num>        choose the cpu you care about (default: -1, overall)
-d --duration <min>   Duration in minutes (default: 5 min, 1<=d<=10)
-i --interval <msec>  interval in milliseconds (default: 1000 ms; 500 or 1000)
```
plus `/proc/stat`, `/proc`, and
`Error: could not read procfs (compiled to look in %s).` — it opens exactly one
file. **[INFERRED]** `cpuload -c 1` is a per-core load meter for the audio core
with no dependency on sysstat, and it is one of the two lowest-risk active
measurements on the box.

**[READ]** `memtester`'s strings — `Usage: %s [-p physaddrbase [-d device]] <mem>[B|K|M|G] [loops]`,
`want %lluMB (%llu bytes)`, `got  %lluMB (%llu bytes)`, `mlock`,
`Continuing with unlocked memory; testing will be slower and less reliable.`
**[INFERRED]** It allocates and locks the amount you ask for. With ~95–127 MB
available (§4.6) this is an OOM generator, not a diagnostic.

**[READ]** `stress`'s strings — `-c/--cpu N spawn N workers spinning on sqrt()`,
`-i/--io N … sync()`, `-m/--vm N … malloc()/free()`, `-d/--hdd N … write()/unlink()`.
A deliberate load generator.

**[READ]** `chcpu`'s strings — `-e, --enable <cpu-list>`, `-d, --disable <cpu-list>`,
`/sys/devices/system/cpu/cpu%d/configure`. **[INFERRED]** `chcpu -d 1` would take
the audio core offline.

### 3.7 The JACK measurement clients — 35 binaries, all inert

**[READ]** `usr/bin/` contains `jackd` plus 35 non-symlink `jack_*` binaries
(286,928 B total), including the measurement set the brief highlights:
`jack_cpu_load` (4,408), `jack_iodelay` (7,228), `jack_bufsize` (5,256),
`jack_midi_latency_test` (18,684), `jack_showtime` (4,740), `jack_samplerate`,
`jack_evmon`, `jack_lsp`, `jack_test` (43,060), `jack_simdtests`.

They cannot be used, and the reason is decisive:

**[READ]** `usr/bin/scsynth` (457,220 B) contains the C++ symbol `13SC_AlsaDriver`
and its error strings —

```
SC_AlsaDriver : Opening with buffer size :
SC_AlsaDriver : Error setting number of periods %d: %s
SC_AlsaAudioDriver : Playback X Run!
SC_AlsaAudioDriver : Capture X Run!
```

— and contains **no JACK symbols at all**. SuperCollider here is built against a
custom direct-ALSA driver.

**[READ]** No `jackd` appears in either live process capture:
`captures/arch-harvest/runtime-state.txt` (which does show `scsynth -u 57110 …`)
or `captures/moog-recon/02-processes.txt` (554 lines).

**[READ]** `rootfs-1.8.2/.jackdrc` contains exactly `/usr/bin/jackd -dalsa -dhw:3 -S`,
naming ALSA card **3**. **[READ]** `runtime-state.txt` `--- alsa ---` shows a
single card: `0 [xmosaudio]`. The default JACK invocation on this box points at a
card that does not exist.

**[INFERRED]** Every `jack_*` client will fail to connect (no server). Starting
`jackd` to make them work would put a second client on the one ALSA device
`scsynth` owns — an audio outage at best. The whole group is a Buildroot
`BR2_PACKAGE_JACK2` side-effect.

**[READ]** Note also `usr/bin/jack_cpu` (7,520 B) — `--cpu OR -c percent_cpu_load (1-99)`,
`Running jack-cpu for %d seconds…`. It is a **load generator**, one underscore
away from `jack_cpu_load`, which is a meter. Do not confuse them.

### 3.8 Adjacent tooling the name sweep turned up

Not part of the brief, found while enumerating `bin`, `sbin`, `usr/bin`, `usr/sbin`
(71 + 82 + 433 + 110 = 696 entries) **[READ]**:

`tcpdump` (`usr/sbin`, 703,400 B), `oscdump`, `osclog`, `netstat`, `traceroute`,
`lsusb`, `lspci`, `hdparm`, `i2cdetect`, `i2cget`, `i2cdump`, `devmem` (busybox),
`readprofile`, `xload`, `libinput-debug-events`, `dumpe2fs` (`usr/sbin`, 15,244 B),
`e2freefrag`, `resize2fs`, `tune2fs → e2label` (57,692 B), `logsave`, `logger`,
`watchdog`, `flashbench`, `nandtest`, `baud_test`, `serial_test`, `mtdev-test`,
`ts_test`, `captest`, `speaker-test`, `amixer`, `aplay`, `arecord`, `vxmon`,
`vxtest`, `chicken-dump`.

Three of those matter:

* **`dumpe2fs` and `tune2fs` are present.** `docs/firmware/VALIDATION.md` states
  "neither `dumpe2fs` nor `tune2fs` is present". They are — in `/usr/sbin`, in
  **both** rootfs versions. `tune2fs` is a symlink to `e2label`, which is
  e2fsprogs' normal multi-call arrangement, so it is functional. See §9, row 1.
* **`tcpdump` is present**, at `/usr/sbin/tcpdump`, in both versions —
  yet `captures/moog-recon/06-toolchain.txt` records `tcpdump: (absent)` **[READ]**.
  **[INFERRED]** Both of these are the same failure: an on-instrument probe run
  with a `PATH` that excluded `/usr/sbin`. Any future capability sweep must
  enumerate `/usr/sbin` explicitly rather than trust `which`.
* **`vxmon`, `vxtest`** are Moog binaries. Do not execute (project rule 2).

### 3.9 Footprint

Computed from `os.path.getsize` over the file lists above **[READ]**:

| group | bytes | MiB | files |
|---|---:|---:|---:|
| apitrace | 13,029,984 | 12.43 | 5 |
| ptrace/debug | 4,081,989 | 3.89 | 6 |
| sysstat | 446,775 | 0.43 | 10 |
| `jack_*` clients | 286,928 | 0.27 | 35 |
| blktrace | 242,613 | 0.23 | 11 |
| process/CPU/mem | 241,780 | 0.23 | 10 |
| **total** | **18,330,069** | **17.48** | **77** |

For scale: **[READ]** `captures/moog-recon/01-system.txt` shows the rootfs as
`636.8M total, 451.7M used, 149.2M available, 75%`. The toolkit is 2.7% of the
partition and **11.7% of what is free**; apitrace alone is 8.3% of free space.

---

## 4. The kernel gate — what 4.1.15-rt18 actually permits

This is the section that decides which half of the toolkit is real.

### 4.1 There is no ftrace and no block-I/O tracing

Exported-symbol probe on the decompressed kernel, run against the control set in §2 **[READ]**:

| exported symbol | count | implies |
|---|---:|---|
| `ring_buffer_alloc` | **0** | no trace ring buffer |
| `register_ftrace_function` | **0** | `CONFIG_FUNCTION_TRACER=n` |
| `trace_seq_printf` | **0** | no trace output layer |
| `trace_print_seq` | **0** | " |
| `__trace_bprintk` | **0** | no `trace_printk` |
| `tracing_generic_entry_update` | **0** | " |
| `blk_trace_setup` | **0** | **`CONFIG_BLK_DEV_IO_TRACE=n`** |
| `blk_trace_startstop` | **0** | " |
| `perf_trace_buf_prepare` | **0** | no tracepoint→perf bridge |

Format-string probe **[READ]**:

| string | count |
|---|---:|
| `# tracer:` | 0 |
| `entries-in-buffer` | 0 |
| `tracing_thresh` | 0 |
| `trace_clock` | 0 |
| `set_ftrace_pid` | 0 |
| `kprobe` | 0 |
| `uprobe` | 0 |
| `Concurrent blktraces` | 0 |

**[INFERRED]** `CONFIG_FTRACE`, `CONFIG_BLK_DEV_IO_TRACE`, `CONFIG_KPROBES` and
`CONFIG_UPROBES` are all off. There is no `/sys/kernel/debug/tracing` to be had
even if debugfs were mounted.

### 4.2 debugfs exists as a filesystem but is not mounted

**[READ]** The kernel contains the exact string `debugfs` — **[INFERRED]**
`CONFIG_DEBUG_FS=y`, the filesystem type is registered.

**[READ]** `runtime-state.txt` `--- mounts ---` lists no debugfs mount, and the
capture's own `--- usb ---` section, generated by
`cat /sys/kernel/debug/usb/devices 2>/dev/null | head -40`, came back **empty**.
This agrees with `docs/arch/midi-stack.md:1038`, which already recorded that
debugfs is not mounted.

**[INFERRED]** `blktrace` therefore fails twice over: it would need a debugfs
mount (a write action, `mount -t debugfs …`), and even with one the
`BLKTRACESETUP` ioctl has no kernel implementation to answer it. The 11-file
blktrace suite, `btrace`, `blkparse`, `btt`, `iowatcher`, `blkiomon`,
`blkrawverify`, `verify_blkparse`, `btrecord`, `btreplay` and `bno_plot.py`,
is **inert on this device**. It is Buildroot's `BR2_PACKAGE_BLKTRACE`.

### 4.3 perf events exist; nothing consumes them

**[READ]** `perf_event_create_kernel_counter` — count **1**, an exported symbol.
**[READ]** `perf_event_paranoid` — count 1 (the sysctl name).
**[READ]** `runtime-state.txt` process list contains kernel thread `29 root [perf]`.

**[INFERRED]** `CONFIG_PERF_EVENTS=y`; `perf_event_open(2)` and the Cortex-A9 PMU
are available. **[READ]** There is no `perf` binary anywhere in `bin`, `sbin`,
`usr/bin` or `usr/sbin`, and no `libperf`. So the hardware counters are reachable
in principle and unreachable in practice with what ships. This is the largest
genuinely-missing capability on the box.

### 4.4 Per-task accounting: what `pidstat` can and cannot report

Substring probes with the matched line quoted **[READ]**:

| probe | count | matched | consequence |
|---|---:|---|---|
| `voluntary_ctxt_switches` | 2 | `voluntary_ctxt_switches:` | **`pidstat -w` works** |
| `Cpus_allowed_list` | 1 | `Cpus_allowed_list:` | confirms `VALIDATION.md`'s read |
| `read_bytes` | 1 | `read_bytes_from_xdr_buf` (sunrpc — a false positive) | — |
| `cancelled_write_bytes` | **0** | — | **`CONFIG_TASK_IO_ACCOUNTING=n`** |
| `delayacct` | **0** | — | `CONFIG_TASK_DELAY_ACCT=n` |
| `sched_debug` | **0** | — | **`CONFIG_SCHED_DEBUG=n`** |
| `usage_in_bytes` | 10 | `memory.usage_in_bytes` | memory cgroup present |
| `rt_runtime_us` | 1 | `sched_rt_runtime_us` | the RT throttle sysctl exists |

**[INFERRED]**, tool by tool:

* `pidstat -u -t` — **works.** Per-thread CPU from `/proc/<pid>/task/<tid>/stat`.
* `pidstat -w -t` — **works.** Per-thread voluntary and involuntary context
  switches. On an RT thread, the involuntary count is a direct preemption
  counter.
* `pidstat -r -t` — **works.** RSS/VSZ from `statm`.
* `pidstat -R` — **works.** Policy and priority from `stat` field 18, the same
  field `assign-pids` reads (**[READ]** `usr/share/las-fx/assign-pids`,
  `pri=\`cat /proc/$SCSYNTHPID/task/$i/stat | awk '{print $18}'\``).
* `pidstat -d` — **does not work.** No `CONFIG_TASK_IO_ACCOUNTING`, so
  `/proc/<pid>/io` is absent.
* `pidstat -s` (stack) — reads `/proc/<pid>/stat` fields; harmless, low value.

**[INFERRED]** The absence of `CONFIG_SCHED_DEBUG` is the single most limiting
kernel choice for this project's questions: there is **no `/proc/sched_debug`**
and **no `/proc/<pid>/sched`**, which are where per-task run-delay, wakeup
latency and `nr_migrations` would live. `pidstat -w`'s involuntary-switch count
is the best remaining proxy.

**[READ]** `/proc/profile` — probe `profile` as an exact line: **0**; and
**[READ]** the kernel command line
(`captures/arch-harvest/runtime-state.txt`, `--- cmdline ---`) contains no
`profile=` argument. **[INFERRED]** `/usr/sbin/readprofile` has nothing to read.

**[READ]** `/proc/timer_list` — probe `timer_list` count 1; present.
**[READ]** `/proc/softirqs`, `/proc/diskstats` — present.
**[READ]** `schedstat` as an exact line — **0**; `CONFIG_SCHEDSTATS=n`.

### 4.5 cgroups: mounted, and a free per-CPU accountant

**[READ]** `etc/cgconfig.conf` lines 1–6 mount `cpuacct`, `cpuset`, `cpu` and
`memory` under `/cgroup/…`; **[READ]** `etc/init.d/S43gui:8` runs
`cgconfigparser -l /etc/cgconfig.conf`; **[READ]** `runtime-state.txt` confirms all
four are mounted live.

This is already covered by `docs/firmware/kernel.md:1476-1503` and
`docs/firmware/las-fx.md:339-357`, which correctly conclude that the `dsp`,
`frontend` and `sc` groups are created and never populated. Nothing here
contradicts that.

The observability point those documents do not make: **the root cgroup always
contains every task.** `/cgroup/cpuacct/cpuacct.usage_percpu` is therefore a
cumulative per-CPU nanosecond counter for the whole system, readable with `cat`,
costing nothing, whether or not the child groups are ever used. Two reads a
minute apart give a per-core busy fraction that is independent of `/proc/stat`
sampling.

### 4.6 Memory headroom, which constrains everything above

**[READ]** `captures/moog-recon/01-system.txt`, two minutes after boot:

```
             total       used       free     shared    buffers     cached
Mem:        507956     503688       4268       8412      36080      86288
-/+ buffers/cache:     381320     126636
```

**[READ]** `runtime-state.txt`: `MemTotal: 507956 kB, MemFree: 11192 kB,
MemAvailable: 96684 kB`.

**[INFERRED]** Real headroom is roughly **95–127 MB**, and `MemFree` proper is
**4–11 MB**. Anything that allocates tens of megabytes — `gdb` loading a 3.4 MB
binary plus symbol tables, a 3 MB `LD_PRELOAD` apitrace wrapper, `memtester`, a
`stress --vm` worker — is competing directly with the audio engine's page cache
on a machine with **no swap** (`Swap: 0 0 0`, **[READ]**). The sysstat tools, at
30–77 KB each and linking only libc, are the right size for this box.

---

## 5. sysstat: installed, configured, and never scheduled

### 5.1 The configuration is deliberate, not stock-empty

**[READ]** `etc/sysconfig/sysstat`, which is **byte-identical between 1.5.0 and
1.8.2** (`diff` clean, 931 B):

```
 6: HISTORY=7
 9: COMPRESSAFTER=10
13: SADC_OPTIONS=" "
16: SA_DIR=/var/log/sa
19: ZIP="xz"
```

`etc/sysconfig/sysstat.ioconf` (6,228 B) is present alongside it **[READ]**.
Seven days of retention, xz compression after ten. Somebody set this up.

### 5.2 Nothing ever calls `sa1`

**[READ]** `etc/crontab/root` is 43 bytes and contains exactly one line:

```
0 3 * * * /etc/log-refresh >/dev/null 2>&1
```

(hex-verified: `30 20 33 20 2a 20 2a 20 2a 20 2f 65 74 63 2f 6c 6f 67 2d 72 65 66
72 65 73 68 20 3e 2f 64 65 76 2f 6e 75 6c 6c 20 32 3e 26 31 0a` — 42 bytes plus
newline, single entry, no trailing blank.)

**[READ]** `etc/crontab/cron.update` contains `root\n`.

No `sa1`, no `sa2`. **[READ]** A `grep` for `sa1|sa2|sadc|sar|pidstat|mpstat|iostat`
across `etc/` and `usr/share/` returns only the sysstat config files' own comments
and `usr/share/applications/htop.desktop`. Nothing on the instrument invokes the
collector.

### 5.3 …and there is no cron daemon to call it with

This goes further than the brief. **`crond` is never started.**

**[READ]** `etc/init.d/` holds exactly 18 `S??*` scripts: `S01logging`, `S02sys`,
`S05avahi-setup.sh`, `S10udev`, `S12splash`, `S14fs`, `S20urandom`, `S25xmosfw`,
`S30dbus`, `S40network`, `S42sc`, `S43gui`, `S50avahi-daemon`, `S50dropbear`,
`S80dhcp-relay`, `S80dhcp-server`, `S95dhcpd`, `S99final`, plus `rcS`/`rcK`.
None of them starts `crond`. **[READ]** `etc/inittab` starts only
`/bin/mount`, `hostname`, `/etc/init.d/rcS` and a `getty`.

**[READ]** The only line in the entire image that looks like it intends to start
cron is `etc/init.d/S14fs:61`, with the comment above it at line 60:

```
60:     #start cron job for log refresh just in case someone leaves this thing on for a year
61:     crontab -c /etc/crontab -l
```

**`crontab -l` lists a crontab. It starts nothing.** The daemon that would have to
run is `crond`; **[READ]** both `crond` and `crontab` exist only as busybox
symlinks (`usr/sbin/crond -> ../../bin/busybox`, `usr/bin/crontab -> ../../bin/busybox`),
and `crond` is the applet that was needed.

**[READ]** Live confirmation, from two independent boots:
`captures/arch-harvest/runtime-state.txt` — zero matches for `crond`;
`captures/moog-recon/02-processes.txt`, a 554-line process table — zero matches
for `cron` of any kind.

**[INFERRED]** Therefore:

1. The `/etc/log-refresh` job at 03:00 has **never run on any shipped instrument**.
   Log rotation happens only at boot, via `S14fs` lines 58, 64, 67 and 70.
2. Adding `sa1`/`sa2` lines to `/etc/crontab/root` would accomplish nothing on its
   own. Enabling sysstat history requires **starting `crond`** as well — two
   writes, not one.

This is the third defect of the same shape that this project has found in these
init scripts, and they are worth seeing together:

| file:line | written | intended | effect |
|---|---|---|---|
| `S02sys:8` **[READ]** | `echo 999950 > sched_rt_runtime_us` | `> /proc/sys/kernel/sched_rt_runtime_us` | creates a file at `/`; RT throttle stays at 95%. Already documented in `VALIDATION.md`. |
| `S14fs:61` **[READ]** | `crontab -c /etc/crontab -l` | start `crond` | cron never runs |
| `S99final:44` **[READ]** | `mount -f -o remount,ro /` | remount root read-only | `-f` is *fake* in both busybox and util-linux `mount` — it updates `/etc/mtab` and calls no `mount(2)`. **[READ]** `/etc/mtab` is a symlink to `/proc/mounts`, so even that is a no-op. |

**[INFERRED]** on the third row: the intended hardening at end of boot does not
happen. **[READ]** corroboration is weak and must be flagged: `runtime-state.txt`
shows `/dev/root on / type ext4 (rw,relatime,…)`, but that capture was taken while
a USB drive was attached, and **[READ]** `S99final:31-38` contains an early-exit
branch keyed on `/media/thumbdrive/k` holding the value `23051934`, which skips the
remount entirely. So the live `rw` is not by itself proof. The `-f` flag is. This
is stated as an observation about the init scripts, not as a security claim; it is
listed in §9, row 8, as something the maintainers of `docs/firmware/init-boot.md` should
check.

### 5.4 What "no history" costs, and what it does not

**[READ]** `rootfs-1.8.2/tmp/sa/` exists and is empty; `rootfs-1.5.0` has the same.

**[INFERRED]** There is no historical performance record on any Moog One, and
there never has been. But **none of that is needed to use sysstat now**: `iostat`,
`mpstat`, `pidstat` and `sar` in *live* mode read `/proc` directly and write
nothing. **[READ]** `sar` contains a `--sadc` option and the literal path
`/usr/lib/sa/sadc`; **[INFERRED]** in live mode `sar` forks that collector with
its output on a pipe and never touches `SA_DIR`. Only `sa1`, or `sadc` invoked
with a directory argument, writes files. Prefer the standalone `mpstat`/`pidstat`
/`iostat` binaries if you want to be certain nothing is written.

---

## 6. Per-tool verdict

Four verdicts:

* **SAFE** — reads `/proc`, `/sys` or a block device read-only; allocates
  kilobytes; cannot perturb the audio thread beyond ordinary scheduler noise on
  cpu0. Suitable for the validation plan in §8.
* **CAUTION** — works, but has a specific hazard named in the note. Owner's
  judgement required.
* **INERT** — will run and fail, or has nothing to attach to. Harmless, useless.
* **UNSAFE** — will or may disturb the running instrument. Do not run.

### 6.1 SAFE

| tool | what it gives here | evidence |
|---|---|---|
| `mpstat -P ALL` | per-core `%usr/%sys/%irq/%soft/%idle`, the direct cpu0-vs-cpu1 measurement | 30,656 B, libc only, `/proc/stat` |
| `pidstat -t -u` | **per-thread CPU for `scsynth`** | §4.4 |
| `pidstat -t -w` | **per-thread voluntary/involuntary context switches** — the preemption counter for the RT thread | §4.4 |
| `pidstat -t -r` | per-thread RSS/VSZ | §4.4 |
| `pidstat -R` | policy and priority, from `stat` field 18 | §4.4 |
| `iostat -x` | eMMC service time and queue depth | `/proc/diskstats` present |
| `sar -q`, `sar -u`, `sar -r` (live) | run-queue length, load, memory | §5.4 |
| `cpuload -c N -i 1000 -d 1 -s` | single-core load meter, one file read | §3.6 |
| `netcap` | **`netstat -p` equivalent: socket → owning process** | §3.5, §7.3 |
| `pscap` | process/UID/capability table | §3.5 |
| `filecap` *(no arguments)* | read-only capability scan | §3.5 |
| `lscpu` | topology, cache sizes, CPU flags | util-linux |
| `lsusb`, `lspci` | bus enumeration | reads sysfs |
| `busybox lsof` | every process's open-fd table, `socket:[inode]` included | §3.6 |
| `busybox top`, `free`, `uptime`, `fuser`, `df`, `du` | standard | busybox 1.24.1 |
| `dumpe2fs -h <dev>` | superblock: **free inodes**, mount count, features | §3.8, §7.4 |
| `e2freefrag <dev>` | free-space fragmentation, read-only | `usr/sbin`, 8,368 B |
| `cat /cgroup/cpuacct/cpuacct.usage_percpu` | cumulative per-CPU nanoseconds | §4.5 |
| `cat /proc/asound/card0/pcm0p/sub0/status` | ALSA `state` and `avail_max` — an audio-margin reading (§7.5) | §7.5 |
| `cat /proc/timer_list`, `/proc/softirqs`, `/proc/interrupts` | RT timer and IRQ accounting | §4.4 |
| `screen -ls` | lists the `scsynth` screen session without attaching | §7.5 |

### 6.2 CAUTION

| tool | hazard |
|---|---|
| `htop` | Read-only *until you touch a key.* **[INFERRED]** htop 1.0.3 binds **F9 = kill** and F7/F8 = renice, one keystroke from the process list. Needs `TERM` set (**[READ]** `usr/share/terminfo/{x/xterm, v/vt100, l/linux}` are present). If used at all, use it to look and then press `q`. `mpstat`/`pidstat` give the same numbers with no kill key. |
| `gmem_info` | **[READ]** links `libGAL.so` and calls `gcoHAL_SetHardwareType`/`gcoOS_DeviceControl` — it opens `/dev/galcore` and issues driver ioctls while X and `las-frontend` hold the GPU. Read-oriented, but it is not a `/proc` read. |
| `sar` live mode | See §5.4 — believed pipe-only, but `sadc` *can* write to `SA_DIR`. Prefer `mpstat`/`pidstat`/`iostat`. |
| `sadf` | Only useful against a `sa` file, of which there are none (§5.4). |
| `tcpdump` | Fully capable, and **[READ]** present at `/usr/sbin/tcpdump` (703,400 B). Capturing on `usbint` is the documented route to the voice-bus protocol, but it is a promiscuous open of a live interface plus a large write. Out of scope for a read-only pass; belongs in its own plan. |
| `ltrace` | The most useful of the ptrace family here (§3.1) — and it still stops the tracee at every PLT call. Never against `scsynth` or `las-sc`. |
| `libinput-debug-events` | Reads `/dev/input/*`; **[INFERRED]** may take a grab on the touchscreen. |
| `i2cdetect`, `i2cget`, `i2cdump` | `i2cdetect` probes by *writing* to addresses in its default mode. On a live synth's I²C bus this is not a read. |
| `hdparm` | Query flags are read-only; most other flags are not. |
| `readprofile` | Harmless but pointless — no `/proc/profile` (§4.4). |
| `screen -r` / `-x` | Attaching changes session state and is how you would see `scsynth`'s `X Run!` messages (§7.5). Not read-only. |

### 6.3 INERT

| tool | why |
|---|---|
| `blktrace`, `btrace`, `blkparse`, `btt`, `iowatcher`, `blkiomon`, `blkrawverify`, `verify_blkparse`, `btrecord`, `btreplay` | No `CONFIG_BLK_DEV_IO_TRACE`, no ftrace, debugfs unmounted (§4.1, §4.2) |
| `bno_plot.py`, `usr/lib/apitrace/scripts/*.py` | No Python interpreter (§3.3) |
| all 35 `jack_*` clients | No JACK server; `scsynth` is direct-ALSA (§3.7) |
| `sadf` against history | No `sa` files exist (§5.4) |
| `readprofile` | No `/proc/profile` (§4.4) |
| `cifsiostat`, `tapestat` | No CIFS mounts, no tape devices |

### 6.4 UNSAFE — do not run

| tool | what it does |
|---|---|
| `strace -p <scsynth\|las-sc>` | **[INFERRED]** ptrace stops the tracee twice per syscall. `scsynth`'s audio thread is `SCHED_FIFO 99` pinned to cpu1 (**[READ]** `VALIDATION.md`: `tid 1341 prio=-100 policy=1 last_cpu=1`). Attaching guarantees missed periods and risks wedging the engine, because the stopping thread (`strace` on cpu0) must be scheduled before the RT thread can continue. |
| `ltrace -p`, `gdb -p`, `gdbserver --attach` on any Moog process | Same mechanism, worse: gdb sends `SIGSTOP` to every thread. |
| `gcore <pid>` | **[READ]** shell wrapper around gdb's `generate-core-file`. Stops the process *and* writes a ~100–500 MB core into a filesystem with 149 MB free. |
| `memtester` | **[READ]** allocates and `mlock`s the requested size; ~95–127 MB available, no swap (§3.6, §4.6). |
| `stress` | **[READ]** `--cpu`/`--io`/`--vm`/`--hdd` load generators (§3.6). |
| `jack_cpu` | **[READ]** `--cpu percent_cpu_load (1-99)` — a load generator, not a meter (§3.7). |
| `jackd` | Would contend with `scsynth` for the only ALSA card; **[READ]** `.jackdrc` points at `hw:3`, which does not exist (§3.7). |
| `chcpu -d 1` | **[READ]** offlines a CPU — that CPU is the audio core (§3.6). |
| `devmem` | **[READ]** busybox applet; raw physical memory writes. `S99final:17` uses it (`devmem 0x020e0018 w 0xffffffff`), which shows how casually it is available. |
| `filecap <path> <cap>` | Two-argument form sets file capabilities (§3.5). |
| `watchdog` | Hardware watchdog daemon; opening `/dev/watchdog` and stopping arms a reboot. |
| `apitrace trace` / `LD_PRELOAD=…/egltrace.so` | Requires killing and relaunching `las-frontend` (**[READ]** started by `etc/init.d/S43gui:21`), injects a 3.0 MB library, and writes an unbounded trace file. §4.6. |
| `nandtest`, `flashbench`, `mtd_debug`, `nanddump`, `flash_erase`, `e2fsck`, `resize2fs`, `mke2fs`, `tune2fs` (write forms) | Storage writers. |
| `vxmon`, `vxtest`, `vxtune`, `lasfwu`, `lassvc`, any `las-*` | Moog binaries. Project rule 2: never execute. **[READ]** `captures/harvest/04-tools.txt` shows `vxtune` exposes `cal`, `tune`, `write` operations. |

---

## 7. Five open questions this toolkit closes

Each of these is an existing, recorded gap in this project's documentation, and
each is answerable by a tool already on the instrument, read-only.

### 7.1 Per-thread CPU cost of the audio engine

**The gap.** `docs/firmware/VALIDATION.md` established *which* thread runs on cpu1
(`tid 1341`, `SCHED_FIFO 99`) but not what fraction of cpu1 it consumes, and noted
that `taskset -p $(pidof scsynth)` reports only the main thread — "exactly how this
project spent months believing cpu1 was spare".

**The answer.** `pidstat -t -p $(pidof scsynth | awk '{print $1}') 1 10` prints one
row per TID with `%usr`, `%system`, `%CPU` and `CPU` (which core it last ran on).
`mpstat -P ALL 1 10` gives the same picture from the core's side. Two independent
views, both `/proc`-only, both writing nothing.

### 7.2 How often the realtime thread is actually preempted

**The gap.** `VALIDATION.md` shows the RT throttle is stuck at 95% because of the
`S02sys:8` missing slash, and asks what raising it would buy. Nothing measures the
current cost.

**The answer.** `pidstat -t -w -p <scsynth-pid> 1 30` prints `cswch/s` and
`nvcswch/s` per thread. For a `SCHED_FIFO 99` thread on an isolated core,
`nvcswch/s` — involuntary switches — is close to a direct preemption count: it
should be near zero, and whatever it is not is the number to compare before and
after any RT-throttle change. **[INFERRED]** from §4.4: this is the best available
substitute for `/proc/sched_debug`, which this kernel does not build.

### 7.3 Which process owns which UDP port

**The gap.** `docs/firmware/VALIDATION.md`, "Not checkable this way": *"Per-process
socket ownership. Busybox `netstat` does not support `-p`."* The instrument listens
on at least 17 UDP ports (**[READ]** `runtime-state.txt`, `--- listening udp ---`:
57110, 9500, 57120, 49967, 47680, 68, 9300, 7772, 7775, 9600, 57735, 46479, 36791,
60603, 5353, 45818, 34013) and the mapping from port to owner has been inferred,
not read.

**The answer.** `netcap`. **[READ]** §3.5 shows it walks `/proc/<pid>/fd` for
`socket:` links and joins them against `/proc/net/{tcp,udp,packet}` — which is
exactly what `netstat -p` does. It prints `ppid pid acct command type port`. This
question has been open since the first recon capture and the tool to answer it has
been in `/usr/bin` the whole time.

Fallback if `netcap`'s output is awkward: `busybox lsof` prints every
`socket:[inode]`, and `/proc/net/udp` column 10 is that inode. The join is two
lines of shell.

### 7.4 Free inodes on the root filesystem

**The gap.** `VALIDATION.md`, "Not checkable this way": *"Free inodes (claimed 609).
Busybox `df` has no `-i`, and neither `dumpe2fs` nor `tune2fs` is present. Needs
another method."*

**The answer.** Both are present, at `/usr/sbin/dumpe2fs` and `/usr/sbin/tune2fs`
(→ `e2label`), in **both** rootfs versions (§3.8). `dumpe2fs -h /dev/mmcblk2p3`
prints `Free inodes:` from the superblock and opens the device read-only. It is
the strictly safer of the two — use `dumpe2fs -h`, never `tune2fs`, whose default
mode is to modify.

**[INFERRED]** The original "not present" conclusion, and `moog-recon`'s
`tcpdump: (absent)`, are the same error: a `PATH` without `/usr/sbin`. 110 binaries
live there (**[READ]**).

A third route, if it exists in this build: `busybox stat -f /` (**[UNKNOWN]**
whether `CONFIG_FEATURE_STAT_FILESYSTEM` is on — §3.6). Costs one command to find out.

### 7.5 Whether the engine is actually dropping audio, and by how much margin

**The gap.** No document records an xrun measurement. `VALIDATION.md` refutes the
claim that `sched: RT throttling activated` fires in normal use, but that is a
different thing from an ALSA underrun.

**The answer**, in three parts, all read-only:

1. **[READ]** `usr/bin/scsynth` contains `SC_AlsaAudioDriver : Playback X Run!`
   and `SC_AlsaAudioDriver : Capture X Run!`. Those go to stdout, which
   **[READ]** `runtime-state.txt` shows is inside a detached screen session
   (`1212 root {screen} SCREEN -d -m /usr/share/las-fx/launch-sc-1`). `screen -ls`
   is a safe read; actually *seeing* the messages requires attaching, which is not
   (§6.2).
2. **[READ]** The kernel has `avail_max   : %ld` and the `XRUN` state name, and
   **[READ]** does **not** have `xrun_debug` — so `CONFIG_SND_PCM_XRUN_DEBUG=n`
   and there is no `/proc/asound/card0/pcm0p/xrun_debug` counter. But
   `/proc/asound/card0/pcm0p/sub0/status` still reports `state:` and `avail_max:`.
   `avail_max` is the high-water mark of available frames — with
   **[READ]** `period_size: 128, buffer_size: 256` (from `VALIDATION.md`'s
   driver read), an `avail_max` approaching 256 means the buffer emptied.
   A `state:` of `XRUN` catches one in the act.
3. `pidstat -t -w` (§7.2) tells you whether preemption is the cause.

**[UNKNOWN]** Whether `avail_max` is reset between reads on this kernel. Worth a
second read a minute later to see whether it moves.

---

## 8. Proposed read-only validation plan

**For a human to run. Nothing below was run by the author of this document.**

Every command here reads `/proc`, `/sys`, `/cgroup`, or a block device opened
read-only. None writes a file, starts or stops a service, or executes a Moog
binary. Copy them one block at a time over SSH; each block is independent.

The instrument is `las-v1.5.0`, whose binaries are byte-identical to 1.8.2's for
every tool used below except the sysstat set, which is the same version 11.2.0
rebuilt (§3.2). **[INFERRED]** all of this applies unchanged to a 1.5.0
instrument.

**Prelude — set a sane PATH.** The single biggest source of wrong conclusions in
the prior captures (§3.8, §7.4) is `/usr/sbin` missing from `PATH`:

```sh
export PATH=/usr/sbin:/sbin:/usr/bin:/bin
```

### Block 1 — settle the `/var/log` question (§1.2)

```sh
ls -ld /var/log; readlink /var/log; ls -ld /var/log/sa
df /var /tmp /var/log
ls -la /var/log/ | head -40
```

Expected if §1.2's inference is right: `/var/log` is a **directory** on
`/dev/mmcblk2p6`, `readlink` prints nothing, and `ls` shows `messages`,
`las-watchdog.log` and `las-watchdog.log.0`. If `readlink` prints `../tmp`, the
brief's tmpfs inference was correct after all and this section of the report is
wrong — say so.

### Block 2 — confirm cron never runs (§5.3)

```sh
ps | grep -c '[c]rond'
ls -la /etc/crontab/ ; cat /etc/crontab/root
ls -la /var/log/sa/ 2>&1
ls -la /var/log/*.0 /var/log/*.0.* 2>&1
```

Expected: `0` for the first, the single `log-refresh` line for the second, an
empty or missing `sa` directory for the third.

### Block 3 — confirm the kernel gate (§4)

```sh
cat /proc/mounts | grep -E 'debugfs|/var |/tmp '
ls /sys/kernel/debug 2>&1 | head -5
ls -l /proc/sched_debug /proc/profile /proc/schedstat 2>&1
ls -l /proc/$(pidof scsynth | awk '{print $1}')/io 2>&1
head -3 /proc/timer_list
cat /proc/sys/kernel/perf_event_paranoid
```

Expected: no debugfs line; `/sys/kernel/debug` empty; `sched_debug`, `profile`,
`schedstat` and `<pid>/io` all "No such file or directory";
`/proc/timer_list` present; `perf_event_paranoid` prints a number.

If `/sys/kernel/debug/tracing` turns out to exist, §4.1 is wrong — stop and say so.

### Block 4 — per-thread audio measurement (§7.1, §7.2). The important one.

```sh
SC=$(pidof scsynth | awk '{print $1}'); echo "scsynth=$SC"
pidstat -t -u -p $SC 1 10
pidstat -t -w -p $SC 1 30
pidstat -t -r -p $SC 1 3
pidstat -R -p $SC 1 3
mpstat -P ALL 1 10
```

Read: which TID accumulates `%CPU` and on which `CPU` column; and `nvcswch/s`
(involuntary switches) for the `SCHED_FIFO 99` thread. Cross-check `mpstat`'s
cpu1 `%usr` against the sum of that thread's `%usr`.

### Block 5 — the second, independent CPU meter (§3.6, §4.5)

```sh
cpuload -c 1 -i 1000 -d 1 -s
cpuload -c 0 -i 1000 -d 1 -s
cat /cgroup/cpuacct/cpuacct.usage_percpu; sleep 60
cat /cgroup/cpuacct/cpuacct.usage_percpu
```

Two reads of `usage_percpu` a minute apart give per-core busy nanoseconds
independent of `/proc/stat`. `-d 1` is required — the default duration is 5
minutes.

### Block 6 — socket ownership (§7.3)

```sh
netcap
netcap | grep -E '7770|7772|7775|9300|9500|9600|57110|57120'
```

Fallback if the output is hard to read:

```sh
busybox lsof | grep 'socket:'
cat /proc/net/udp
```

### Block 7 — filesystem facts (§7.4)

```sh
dumpe2fs -h /dev/mmcblk2p3 2>&1 | grep -Ei 'inode|block count|free|mount count|state|features'
dumpe2fs -h /dev/mmcblk2p6 2>&1 | grep -Ei 'inode|free|mount count|state'
busybox stat -f / 2>&1
lscpu
```

`dumpe2fs -h` reads the superblock only. Do **not** substitute `tune2fs`.

### Block 8 — audio margin (§7.5)

```sh
cat /proc/asound/card0/pcm0p/sub0/hw_params
cat /proc/asound/card0/pcm0p/sub0/status
sleep 60
cat /proc/asound/card0/pcm0p/sub0/status
screen -ls
```

Read `state:` (should be `RUNNING`, never `XRUN`) and whether `avail_max:` grows
between the two reads. `hw_params` re-confirms `period_size: 128`.

### Block 9 — I/O, if anyone still cares about the eMMC

```sh
iostat -x 1 5
cat /proc/diskstats | grep mmcblk2
```

`blktrace` will not work; do not try it (§4.2).

### Block 10 — capability and process inventory

```sh
pscap | head -40
filecap 2>&1 | head -20
```

`filecap` with **no arguments** only. Two arguments writes.

### Nothing in this plan requires

`strace`, `ltrace`, `gdb`, `gdbserver`, `gcore`, `htop`, `memtester`, `stress`,
`jackd`, any `jack_*` client, `apitrace`, `blktrace`, `tcpdump`, `devmem`,
`chcpu`, `i2cdetect`, or any Moog binary.

---

## 9. Conflicts with existing documents

Reported, not fixed, per project rule 4.

| # | document | what it says | what the files say |
|---|---|---|---|
| 1 | `docs/firmware/VALIDATION.md`, "Not checkable this way" | *"neither `dumpe2fs` nor `tune2fs` is present"* | **[READ]** `usr/sbin/dumpe2fs` (15,244 B) and `usr/sbin/tune2fs → e2label` (57,692 B) exist in **both** 1.5.0 and 1.8.2. The free-inode question is answerable — §7.4. |
| 2 | `docs/firmware/VALIDATION.md`, same section | *"Per-process socket ownership. Busybox `netstat` does not support `-p`."* | True about `netstat`, but **[READ]** `usr/bin/netcap` does exactly this job — §3.5, §7.3. |
| 3 | `captures/moog-recon/06-toolchain.txt` | `tcpdump: (absent)` | **[READ]** `usr/sbin/tcpdump`, 703,400 B, present in both versions. **[INFERRED]** the probe's `PATH` omitted `/usr/sbin`. Note this also makes `docs/MOOG-ONE-INTERNALS.md:1794` (which lists `tcpdump` as present) the correct one of the two. |
| 4 | `docs/MOOG-ONE-INTERNALS.md:1780-1787`, "JACK — including network audio" | *"The full JACK suite, and critically netjack … a path to streaming audio in or out of the instrument over ethernet, using software already present."* | The binaries are present, but **[READ]** `scsynth` is built on `SC_AlsaDriver` with no JACK symbols, no `jackd` runs in either live capture, and `.jackdrc` names a nonexistent `hw:3`. **[INFERRED]** netjack is not a path that exists today; it is a path that would require displacing the audio engine. §3.7. |
| 5 | `docs/MOOG-ONE-INTERNALS.md:1792-1799`, "Debugging and inspection" | Lists `gdb gdbserver strace ltrace tcpdump lsof htop` / `apitrace glretrace eglretrace` as *"A complete debug toolchain"* | Present, but **[READ]** every Moog binary is stripped to `.dynsym`, gdb 7.9.1 has no Python, `lsof` is a busybox symlink, and apitrace is NXP BSP with Python-only helpers and no interpreter. **[INFERRED]** "complete" overstates it considerably. §3.1, §3.4, §3.6. |
| 6 | The brief commissioning this report | *"`strace` 0, `ltrace` 0, `gdbserver` 0, `htop` 0, `lsof` 0, `apitrace` 0"* occurrences in the docs | **[READ]** all six appear at `MOOG-ONE-INTERNALS.md:1794-1795`. The counts that *are* zero are listed in §1.1. |
| 7 | The brief | *"were it enabled it would write into RAM and vanish at reboot"* | **[READ]** `/var` is `/dev/mmcblk2p6`, ext4, 3.3 GB free. §1.2. The residual uncertainty is `/var/log` itself — Block 1. |
| 8 | `docs/firmware/init-boot.md` *(not read in full for this report — flagged for its maintainer)* | — | **[READ]** `etc/init.d/S99final:44` is `mount -f -o remount,ro /`; `-f` is the *fake* flag in both busybox and util-linux `mount`, and **[READ]** `/etc/mtab` is a symlink to `/proc/mounts`. **[INFERRED]** the end-of-boot read-only remount does not happen. Third instance of the pattern in §5.3's table. Someone should check whether `init-boot.md` asserts that root goes read-only. |

Nothing in this report contradicts `docs/firmware/kernel.md` or
`docs/firmware/las-fx.md` on cgroups (§4.5), or `docs/arch/midi-stack.md:1038` on
debugfs (§4.2); those are corroborated.

---

## 10. What I did not do

* **The instrument was not touched.** No SSH, no OSC, no MIDI, no network access
  of any kind. Everything above is from local files.
* **No binary was executed** — not the ARM binaries (which would not run on macOS
  anyway) and not the shell and Python scripts.
* **`/var` partition contents were not examined.** They are not in the capture
  set. This is the source of the one `[UNKNOWN]` that matters (§1.2, Block 1).
* **The kernel `.config` was not recovered.** There is no `/proc/config.gz`
  equivalent on disk and no `config-*` file in `boot/`. Every kernel claim in §4
  is a symbol- or string-presence inference with controls, not a config read. A
  live `zcat /proc/config.gz` — if `CONFIG_IKCONFIG_PROC` happens to be on —
  would settle §4 in one command; **[UNKNOWN]** whether it is.
* **`las-sc`, `scsynth` and `las-frontend` were not disassembled** for this
  report beyond section headers and driver strings. Other reports cover them.
* **The `X`/EGL stack was not characterised**, so which of `glxtrace.so` or
  `egltrace.so` would be the correct wrapper is **[UNKNOWN]**. Moot while
  apitrace stays in the UNSAFE column.
* **`sar`'s live-mode file behaviour was inferred, not proven.** §5.4. If
  certainty matters, use `mpstat`/`pidstat`/`iostat`, which have no writing mode
  at all.
* **The `oscdump`/`osclog` liblo tools** were noted (§3.8) and not investigated;
  they belong with the OSC namespace work, not here.
* **No timing was measured.** Every performance number in this document is a file
  size or a capture from someone else's earlier read.

---

## Appendix A — one-line file manifest

Paths relative to `captures/firmware-1.8.2/rootfs-1.8.2/`. All **[READ]**.

```
usr/bin/strace           288804   usr/bin/blktrace          32412   usr/bin/iostat        34756
usr/bin/strace-log-merge    944   usr/bin/btrace              891   usr/bin/mpstat        30656
usr/bin/ltrace           198960   usr/bin/blkparse          40796   usr/bin/pidstat       42984
usr/bin/gdb             3367328   usr/bin/blkrawverify       8132   usr/bin/sar           76724
usr/bin/gdbserver        223008   usr/bin/blkiomon          19024   usr/bin/sadf         141180
usr/bin/gcore              2945   usr/bin/btrecord          12924   usr/bin/tapestat      26572
usr/bin/htop              95440   usr/bin/btreplay          19260   usr/bin/cifsiostat    24268
usr/bin/lsof                 17   usr/bin/btt               53844   usr/lib/sa/sa1          968
usr/bin/memtester         14300   usr/bin/iowatcher         47656   usr/lib/sa/sa2         1287
usr/bin/cpuload           18228   usr/bin/verify_blkparse    4252   usr/lib/sa/sadc       67380
usr/bin/gmem_info          7852   usr/bin/bno_plot.py        3422
usr/bin/filecap            6220   usr/bin/apitrace         255568   etc/sysconfig/sysstat        931
usr/bin/netcap             9952   usr/bin/glretrace       3345796   etc/sysconfig/sysstat.ioconf 6228
usr/bin/pscap              6480   usr/bin/eglretrace      3345316   etc/crontab/root              43
usr/sbin/dumpe2fs         15244   usr/lib/apitrace/wrappers/glxtrace.so  3051908
usr/sbin/tcpdump         703400   usr/lib/apitrace/wrappers/egltrace.so  3031396
usr/bin/jack_* (35 files, 286928 total)
```

## Appendix B — reproducing the kernel read

```sh
# offset 64 skips the U-Boot header; comp=0 means the payload is a self-
# decompressing zImage whose piggy is a plain gzip stream at file offset 18264.
python3 -c "
import zlib
d=open('boot/uImage','rb').read()
open('vmlinux.bin','wb').write(zlib.decompressobj(31).decompress(d[18264:]))"
# -> 10,214,816 bytes; banner: Linux version 4.1.15-rt18 (root@terry) …
strings -a vmlinux.bin | grep -cx blk_trace_setup      # 0
strings -a vmlinux.bin | grep -cx _raw_spin_lock       # 1  (control)
```
