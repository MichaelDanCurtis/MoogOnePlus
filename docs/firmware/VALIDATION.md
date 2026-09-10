# Validated on the instrument

The fleet's reports were written entirely from files on disk. This is the other
half: their load-bearing claims checked against the real Moog One, over SSH,
**read-only** — no writes, no Moog binary executed, nothing left behind.

Instrument: `192.168.1.138`, `las-v1.5.0`, `LAS_FRONTEND_GIT_TAG 2.0.8`,
`LAS_VX_GIT_TAG lasvx-v2.1.0`, XMOS `VERSIOND 33620735`.
Run 2026-09-09, single boot.

---

## A live bug in Moog's shipping firmware

```
sched_rt_runtime_us   = 950000        <- kernel default: 95%
sched_rt_period_us    = 1000000
/sched_rt_runtime_us  = -rw-r--r-- 1 root root 7   (a FILE, at the filesystem root)
  contents            = 999950
```

Moog intended to raise the realtime throttle from 95% to **99.995%**. A missing
slash in the init script wrote `999950` into a *file called
`/sched_rt_runtime_us`* instead of into `/proc/sys/kernel/sched_rt_runtime_us`.
The sysctl was never touched.

The file is dated this boot, so it is recreated every time the instrument starts.
The audio engine has been throttled at 95% for the life of the product.

This is the one change identified anywhere in the documentation effort that
*raises a ceiling* rather than trading one cost for another. It is a single
`/proc` write. It does not survive a reboot, and it changes nothing on disk.

---

## Confirmed

**cpu1 is the audio core.** The correction made on 2026-09-08, now observed
rather than inferred:

```
tid 1341   prio=-100  policy=1  last_cpu=1   Cpus_allowed_list=1    <- SCHED_FIFO 99, cpu1 only
tid 1294   prio=-95   policy=1  last_cpu=0   Cpus_allowed_list=0    <- main thread
tid 1318/1323/1339/1343/1345 — all Cpus_allowed_list=0
```

One thread of seven is pinned to cpu1 at realtime priority 99; the rest are
confined to cpu0. **`taskset -p $(pidof scsynth)` reports only tid 1294 — cpu0.**
That is exactly how this project spent months believing cpu1 was spare.

**`las-frontend` runs on cpu0.** `Cpus_allowed_list: 0`, matching its
`--affinity-mask=1`.

**Block size is 128.** Confirmed a third independent way, at the driver:

```
format: S24_LE   channels: 8   rate: 48000 (48000/1)
period_size: 128   buffer_size: 256
```

`buffer_size 256` is two periods of 128 — which is the whole origin of the
"is it 128 or 256" confusion. It is 128. Also confirms 24-bit, 8-channel output.

**The firmware-update margin is 12.2 MiB**, as reported:

```
/mnt/fwu (mmcblk2p7)   882,636 KB total   819,696 KB available  =  800.5 MiB
staged: decrypted 639 MiB + still-packed 149 MiB                =  788.3 MiB
                                                        margin  =   12.2 MiB
```

**Partition layout**, previously inferred, now read:

| device | KB | role |
|---|---|---|
| `mmcblk2p2` | 785,455 | firmware slot B (767 MiB) |
| `mmcblk2p3` | 785,479 | slot A — the live rootfs (`root=` on the cmdline) |
| `mmcblk2p4` | 64,583 | vfat, `/var/lib/sys` |
| `mmcblk2p6` | 4,164,608 | `/var` — presets, calibration (3.5 GB free) |
| `mmcblk2p7` | 913,391 | `/mnt/fwu`, update staging |
| `sda` | 245,760,000 | the USB drive (234 GB) |

---

## Refuted

**"cpu1 is isolated with `nohz_full` and RCU offload."** No. The kernel command
line is:

```
console=ttymxc1,115200{smp} root=/dev/mmcblk2p3 rootwait isolcpus=1 quiet
loglevel=0 galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1
```

`nohz=off`, not `nohz_full=1`. Both `/sys/devices/system/cpu/isolated` and
`nohz_full` are **empty**. The isolation is plain `isolcpus=1` and nothing more.

**"`sched: RT throttling activated` fires in normal use."**
`dmesg | grep -c "RT throttling"` returns **0** on a stock boot. The occurrence
cited from a prior capture was this project's own experiment loading the engine —
the same contaminated snapshot that produced the block-size error. Not a property
of the instrument.

**"Display threads outrank `irq/26-esai`, coupling display activity into audio."**
The premise is void:

```
 26:          0          0   GPC  51 Level   esai      <- has never fired, on either core
284:   82384941          0   GPC   2 Level   sdma      <- 82.4 million, all on CPU0
```

The ESAI interrupt has fired **zero times in the life of this boot**. The audio
interrupt that actually runs is `sdma`, and it is serviced entirely on **cpu0**.

**"184.7 MiB free on the rootfs."** Actually **149 MiB**:
`/dev/root  652,070 KB total, 462,492 used, 152,766 available, 75%`.

---

## New, from the live reads

**The audio path crosses cores.** The DMA interrupt (`sdma`, 82.4M counts) is
serviced on cpu0 while the engine thread runs on cpu1. Every audio period
involves an inter-core wakeup. Nothing in the documentation had noticed this, and
it bears on any latency reasoning.

---

## Not checkable this way

- **Free inodes** (claimed 609). Busybox `df` has no `-i`, and neither
  `dumpe2fs` nor `tune2fs` is present. Needs another method.
- **Per-process socket ownership.** Busybox `netstat` does not support `-p`.

---

## Method

Every command was a read of `/proc`, `/sys`, `/etc` or `df`/`mount`/`netstat`.
No file was written, no service restarted, no Moog binary invoked. The instrument
was on firmware 1.5.0, stock, with the owner's USB drive attached.
