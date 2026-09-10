# Boot, init and the service graph — Moog One v1.8.2

Definitive reference for the region: `/etc/inittab`, `/etc/init.d/*`, the A/B
partition scheme, the firmware updater, the startup-coordination handshake, the
cookie files, the watchdog, and the shutdown path.

**Source of record.** Everything below was read from files on local disk. The
instrument was not contacted. Primary material:

| what | where |
|---|---|
| decrypted v1.8.2 rootfs | `captures/firmware-1.8.2/rootfs-1.8.2/` |
| v1.5.0 rootfs (owner's instrument) | `captures/rootfs-1.5.0/` |
| live kernel log | `captures/dmesg-before-reboot.txt` |
| live process/mount snapshot | `captures/arch-harvest/runtime-state.txt` (see its CAVEAT file) |
| device tree | `rootfs-1.8.2/boot/imx6dl-profili-som.dtb`, parsed with a local FDT reader |

Paths written `<R>/…` are relative to `captures/firmware-1.8.2/rootfs-1.8.2/`.

**Grading.** Every claim carries one of:

- **[READ]** — read directly out of a named file at a named line/offset.
- **[INFERRED]** — reasoning from evidence; the evidence is named.
- **[UNKNOWN]** — not determined.

---

## 0. Executive summary

Twelve findings, ordered by how much they should change someone's behaviour.

1. **The root filesystem is read-write the whole time the instrument is on.**
   `S99final:44` runs `mount -f -o remount,ro /`. Busybox `mount`'s `-f` is
   *fake* — it skips the syscall. The live instrument reports
   `/dev/root on / type ext4 (rw,relatime,…)`. **[READ]** §9.1
2. **`S99final`'s wait for `las-sc` has no timeout**, unlike both loops in
   `S43gui`. If `las-sc` never drops its cookie, `rcS` never returns, and the
   watchdog that would have restarted `las-sc` is started *inside* that same
   loop — so it never starts either. **[READ]** §9.2
3. **There is no USB gadget on the i.MX6 to wedge.** All four `usb@` nodes in
   the DTB are `dr_mode = "host"`, and the OTG port additionally loses its
   pinmux to the backlight PWM on every boot. Nothing in the rootfs calls
   `/sbin/reboot`, which is stock busybox. **[READ]** §11
4. **The XMOS is held in reset for the first ~11 seconds of every boot** by
   `leds-gpio` (`default-state = "off"` on `XMOS_RESET_N`), and released only by
   `S25xmosfw`. This is why the USB device appears at t=11.9 s. **[READ]** §7
5. **`S02sys:8` writes to a file called `sched_rt_runtime_us` in the current
   directory** — there is no path. The RT throttle is never disabled. **[READ]** §9.3
6. **Root has a blank password and dropbear is started with `-B`** ("Allow blank
   password logins"), gated only on a magic file on a USB stick. **[READ]** §10.2
7. **`lasfwu`'s "wipe falcon space" guard is a redirection, not a comparison.**
   `[ $x > 60000 ]` writes a file named `60000`; the `dd if=/dev/zero of=/dev/mmcblk2`
   behind it runs on every successful update. **[READ]** §8.6
8. **No cron daemon is ever started.** `S14fs:61` runs `crontab … -l`, which
   *lists*. Log rotation happens once per boot and never again. **[READ]** §9.5
9. **The cgroup configuration is inert.** `S43gui` parses `cgconfig.conf` into
   four hierarchies; nothing ever places a process into any of them. **[READ]** §9.4
10. **The boot sequence is byte-identical between v1.5.0 and v1.8.2** except for
    four XMOS firmware arguments in `S42sc`. **[READ]** §12
11. **`versionb` is a comparable big-endian integer `0xMM_mm_pp_FF`**; v1.8.2 =
    `0x010802FF` = 17302271, and the same encoding carries the XMOS voice-controller
    version (`--vcfv=33686271` = `0x020202FF` = v2.2.2). **[READ]** §8.3
12. **The A/B slot is not fixed.** This owner's instrument boots
    `root=/dev/mmcblk2p3` (slot U2). An existing doc states root is p2. Both are
    correct for their own machine. §13

---

## 1. What runs before `init`

Not present in the rootfs and therefore **[UNKNOWN]** in detail: the i.MX6 boot
ROM, U-Boot, and whatever U-Boot does with `/var/lib/sys/bootme`. What can be
established:

* The kernel is `Linux-4.1.15-rt18`, uncompressed, load/entry `0x10008000`,
  5,060,392 bytes, carried **inside each rootfs** at `<R>/boot/uImage`.
  **[READ]** — legacy U-Boot image header at `boot/uImage` offset 0:
  magic `27 05 19 56`, size `0x004D3728`, `os=5 arch=2 type=2 comp=0`, name
  `Linux-4.1.15-rt18`.
* The device tree is `<R>/boot/imx6dl-profili-som.dtb`, 42,345 bytes, also inside
  the rootfs. **[READ]**
* `/boot` has **no fstab entry** — it is a directory in the root filesystem, not a
  partition. **[READ]** `<R>/etc/fstab` contains no `boot`.
  **Consequence [INFERRED]:** each A/B slot ships its own kernel and DTB, so
  U-Boot must load the kernel *from the rootfs partition it has selected*. An
  update therefore replaces kernel, DTB and userspace atomically as one ext4
  image.
* `<R>/boot/cmdline.img` is a **U-Boot script image** (magic `27 05 19 56`,
  `type=6`), 189 bytes, whose body is exactly `<R>/boot/cmdline.txt`: **[READ]**

  ```
  setenv add_args isolcpus=1 quiet loglevel=0  galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1
  ```

  Note it sets `add_args`, not the whole command line — `root=` is supplied by
  U-Boot from elsewhere. **[INFERRED]** from the live command line, which is the
  above **plus** `console=ttymxc1,115200{smp} root=/dev/mmcblk2p3 rootwait`:
  **[READ]** `dmesg-before-reboot.txt:21`.
* `cmdline.txt` is **identical between v1.5.0 and v1.8.2**. **[READ]** (`diff`)

The literal `{smp}` in the live command line is an unsubstituted U-Boot variable
placeholder. **[READ]** `dmesg-before-reboot.txt:21`. Harmless — the kernel
ignores unknown tokens.

### 1.1 Kernel-stage facts that matter to userspace

All **[READ]** from `dmesg-before-reboot.txt`:

| t (s) | line | event |
|---|---|---|
| 0.4931 | 203–206 | `pin MX6DL_PAD_SD1_DAT3 already requested by 2080000.pwm; cannot claim for 2184000.usb` → `imx_usb 2184000.usb: Error applying setting, reverse things back` |
| 0.4971 | 207 | `ci_hdrc ci_hdrc.0: EHCI Host Controller` (the OTG port, forced host) |
| 0.5194 | 212 | `ci_hdrc ci_hdrc.1: EHCI Host Controller` (the XMOS link) |
| 0.5440 | 223 | `imx2-wdt 20c0000.wdog: timeout 60 sec (nowayout=0)` |
| 0.8688 | 245 | `mmcblk2: p1 p2 p3 p4 p5 p6 p7` — 7.21 GiB eMMC plus boot0/boot1/rpmb |
| 1.3330 | 272–274 | `EXT4-fs (mmcblk2p3): INFO: recovery required on readonly filesystem` … `recovery complete` |
| 1.3648 | 276 | `VFS: Mounted root (ext4 filesystem) readonly on device 179:3` |
| 1.4527 | 279 | `EXT4-fs (mmcblk2p3): re-mounted. Opts: errors=remount-ro,data=ordered` ← this is `inittab`'s remount |
| 1.7043 | 280 | `usb 1-1: new high-speed USB device number 2` — the front-panel thumb drive |
| 1.7543 | 281 | `EXT4-fs (mmcblk2p6): 1 orphan inode deleted` … `recovery complete` |
| 1.7717 | 284 | `EXT4-fs (mmcblk2p7): recovery complete` |
| 1.7822 | 286 | `FAT-fs (mmcblk2p4): Volume was not properly unmounted. Some data may be corrupt.` |
| 11.9036 | 301 | `usb 2-1: new high-speed USB device number 2` — **the XMOS**, ten seconds late |
| 12.0577 | 302 | `cdc_ether 2-1:1.0 usb0 … 02:00:00:00:00:00` |
| 12.0600 | 303 | `cdc_ether 2-1:1.2 eth0 … a4:11:63:b0:28:9b` |
| 12.1068 | 304 | `usbint: renamed from usb0` |
| 12.1695 | 305 | `ethext: renamed from eth0` |
| 45.29 | — | ESAI/`xmos-codec` starts — the audio link comes up |
| 1048.96 | — | `sched: RT throttling activated` |

Three of these deserve emphasis and are picked up below: the USB pinmux failure
(§11.1), the ten-second XMOS gap (§7), and the dirty FAT on p4 — the partition
that holds the A/B boot selector (§8.7).

---

## 2. `/etc/inittab`

Busybox init. **[READ]** `<R>/etc/inittab`, complete:

```
::sysinit:/bin/mount -t proc proc /proc
::sysinit:/bin/mount -o remount,rw /
::sysinit:/bin/mkdir -p /dev/pts
::sysinit:/bin/mkdir -p /dev/shm
::sysinit:/bin/mount -a
::sysinit:/bin/hostname -F /etc/hostname
::sysinit:/etc/init.d/rcS

console::respawn:/sbin/getty -L  console 0 vt100 # GENERIC_SERIAL

#::ctrlaltdel:/sbin/reboot

::shutdown:/etc/init.d/rcK
::shutdown:/sbin/swapoff -a
::shutdown:/bin/umount -a -r
```

Points of substance:

* **Line 2 is what makes the root filesystem writable**, and it does not pass
  `noatime`, so root ends up `relatime` even though `fstab:2` says `noatime`.
  Confirmed live: `/dev/root on / type ext4 (rw,relatime,errors=remount-ro,data=ordered)`
  **[READ]** `runtime-state.txt:174`. Every read of the 145 MB `las-frontend`
  binary and the preset database therefore also writes an atime. **[INFERRED]**
* **`ctrlaltdel` is commented out.** **[READ]** inittab.
* **`rcS` runs as a `sysinit` action, which busybox init runs to completion, in
  order, before it starts any `respawn` entry.** **[INFERRED]** — standard
  busybox init semantics. **Consequence: if `rcS` hangs, the serial getty never
  appears.** This makes §9.2 a hard hang, not a degraded boot.
* `hostname -F /etc/hostname` sets `las-production`. **[READ]** `<R>/etc/hostname`.
  Avahi separately advertises `moog-one` (§10.3) — the instrument has two names.

### 2.1 `mount -a`

`fstab` in file order, which is the order `mount -a` uses. **[READ]** `<R>/etc/fstab`:

| device | mount point | type | options |
|---|---|---|---|
| `/dev/root` | `/` | ext4 | `rw,noauto,noatime` (noauto — skipped) |
| `proc` | `/proc` | proc | — |
| `devpts` | `/dev/pts` | devpts | `gid=5,mode=620` |
| `tmpfs` | `/dev/shm` | tmpfs | `mode=0777` |
| `tmpfs` | `/tmp` | tmpfs | `mode=1777` |
| `sysfs` | `/sys` | sysfs | — |
| `/dev/mmcblk2p2` | `/mnt/u1` | ext4 | `ro,noauto` — **A slot**, mounted only by `lasfwu` |
| `/dev/mmcblk2p3` | `/mnt/u2` | ext4 | `ro,noauto` — **B slot**, mounted only by `lasfwu` |
| `/dev/mmcblk2p6` | `/var` | ext4 | `defaults,noatime` |
| `/dev/mmcblk2p7` | `/mnt/fwu` | ext4 | `defaults,noatime` |
| `/dev/mmcblk2p4` | `/var/lib/sys` | **vfat** | `defaults,noatime` |
| `tmpfs` | `/var/run` | tmpfs | `mode=0755,nosuid,nodev` |

The ordering is correct: `/var` is mounted before `/var/lib/sys` and `/var/run`
nest inside it. **[READ]**

**`/var` is a separate partition and is not touched by a firmware update** —
`lasfwu` writes only `/dev/mmcblk2p2` or `p3` (§8.4). User presets, tuning data,
logs and settings survive updates. **[INFERRED]** from `fstab` + `lasfwu`.

The shipped rootfs `<R>/var/` contains symlinks (`log -> ../tmp`,
`cache -> ../tmp`, …) **[READ]**, but these are shadowed by the p6 mount and are
never visible at runtime. **[INFERRED]** Do not cite them.

`p1` and `p5` are never referenced by `fstab` or by any script. `lasfwu`'s
partition case statement calls partition **1** "the factory partition"
**[READ]** `lasfwu:528`, so p1 is a third, bootable, factory rootfs.
`p5` is **[UNKNOWN]**.

---

## 3. `rcS` and `rcK`

**[READ]** `<R>/etc/init.d/rcS`:

```sh
for i in /etc/init.d/S??* ;do
     [ ! -f "$i" ] && continue
     case "$i" in
        *.sh)  ( trap - INT QUIT TSTP ; set start ; . $i ) ;;
        *)     $i start ;;
    esac
done
```

* Glob order is ASCII sort. Scripts ending `.sh` are **sourced in a subshell**;
  everything else is forked. Only `S05avahi-setup.sh` takes the sourced path.
* **No exit status is checked, ever.** A script that fails is indistinguishable
  from one that succeeded. **[READ]**
* `rcK` is the same loop over `$(ls -r /etc/init.d/S??*)` with `stop`. **[READ]**

### 3.1 The eighteen scripts, in order

| # | script | forks? | what it is for | blocks boot? |
|---|---|---|---|---|
| 1 | `S01logging` | yes | `syslogd -n`, `klogd -n` via `start-stop-daemon -b` | no |
| 2 | `S02sys` | yes | cpufreq governor, swappiness, RT throttle (broken), backlight off, clock offset, `hwclock -w` | no |
| 3 | `S05avahi-setup.sh` | **sourced** | creates `/tmp/avahi-autoipd` owned by `avahi` | no |
| 4 | `S10udev` | yes | `udevd -d`, two `udevadm trigger`s, `udevadm settle --timeout=30` | **up to 30 s** |
| 5 | `S12splash` | yes | framebuffer geometry, starts **X**, `dd`s the splash to `/dev/fb1`, backlight to 99, alpha fade | ~0.3 s |
| 6 | `S14fs` | yes | directory/symlink repair, **clears `/tmp`**, empties `/mnt/fwu`, **removes all cookies**, rotates logs | no |
| 7 | `S20urandom` | yes | restores/saves `/etc/random-seed` | no |
| 8 | `S25xmosfw` | yes | `config-las-spi xmos` — **releases the XMOS from reset** | no |
| 9 | `S30dbus` | yes | `dbus-uuidgen --ensure`, `dbus-daemon --system` | no |
| 10 | `S40network` | yes | `ifdown -a`, `ifup -a &`, clears stale PIDs, `ip_forward=1` | no (backgrounded) |
| 11 | `S42sc` | yes | starts **`las-sc`**, then `sleep 3` | **3 s, always** |
| 12 | `S43gui` | yes | cgroups, three xterms, **`las-frontend`**, **`las-dwm`**, screen inversion, `detect-held-buttons` | **up to 200 s** |
| 13 | `S50avahi-daemon` | yes | `avahi-daemon -D` | no |
| 14 | `S50dropbear` | yes | SSH — **only if the USB key file is present** | no |
| 15 | `S80dhcp-relay` | yes | exits immediately (`INTERFACES` empty) | no |
| 16 | `S80dhcp-server` | yes | starts `dhcpd`, which has no subnet to serve | no |
| 17 | `S95dhcpd` | yes | `dhcpcd start ethext &`, four `iptables` DNAT rules | no |
| 18 | `S99final` | yes | IPU priorities, AXI priority, **waits for `las-sc` forever**, starts the watchdog, kills xterms, fake-remounts root ro | **unbounded** |

---

## 4. Each script in detail

### S01logging — `<R>/etc/init.d/S01logging`

```sh
start-stop-daemon -b -S -q -m -p /var/run/syslogd.pid --exec /sbin/syslogd -- -n
start-stop-daemon -b -S -q -m -p /var/run/klogd.pid  --exec /sbin/klogd  -- -n
```
**[READ]** `:8-9`. Busybox syslogd, default destination `/var/log/messages`.
Runs **before** `mount -a` has… no — `mount -a` is an inittab sysinit that
precedes `rcS`, so `/var` (p6) is already mounted. **[INFERRED]** from inittab
ordering. Writes are persistent.

**Failure mode:** none that blocks. `start-stop-daemon -q` swallows errors.

### S02sys — `<R>/etc/init.d/S02sys`

**[READ]** `:6-27`, verbatim:

```sh
echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo 0 >  /proc/sys/vm/swappiness
echo 999950 > sched_rt_runtime_us

echo 0 > /sys/class/backlight/backlight/brightness

if [ ! -f /var/clock_offset ]; then
      echo 0 > /var/clock_offset
fi
CLOCKOFFSET=`cat /var/clock_offset`
CLOCKOFFSET_SEC=`echo $CLOCKOFFSET/1000 | bc`;
…
date -s @"$NEWTIME"
hwclock -w
```

Four observations:

1. **`echo 999950 > sched_rt_runtime_us` has no path.** The intended target is
   `/proc/sys/kernel/sched_rt_runtime_us`. As written it creates a regular file
   named `sched_rt_runtime_us` in the process's working directory. **[READ]**
   The working directory of a busybox-init `sysinit` child is `/` **[INFERRED]**,
   and `/` is writable at that point (§2). So the file lands at
   `/sched_rt_runtime_us` and the kernel default of 950000 µs per 1,000,000 µs
   stands. **Corroboration [READ]:** `dmesg-before-reboot.txt` records
   `sched: RT throttling activated` at t≈1049 s on the live instrument — the
   throttle is demonstrably still armed. (This is corroboration, not proof: a
   999950 setting could in principle also trip.)
   The pristine v1.8.2 image contains no `/sched_rt_runtime_us` **[READ]**,
   as expected — it has never been booted.
2. Only `cpu0`'s governor is set. On i.MX6 the two cores share one cpufreq
   policy, so this covers cpu1 as well. **[INFERRED]** — not verified against
   this kernel's policy layout.
3. `date -s` then `hwclock -w` **writes the offset-adjusted time back into the
   RTC on every boot.** `/var/clock_offset` is created as `0` if missing, so on a
   normal machine the adjustment is zero and this is a no-op that still costs an
   I²C write. **[READ]** An RTC (PCF85063) is present per
   `docs/arch/hardware-external.md:456`.
4. The backlight is driven to 0 here and again in `S12splash:10`. **[READ]**

**Failure modes:** `bc` is present **[READ]** `<R>/usr/bin/bc`. If
`/var/clock_offset` contained garbage, `bc` would error and `date -s @""` would
fail; the script has `exit 0` regardless **[READ]** `:46`.

### S05avahi-setup.sh — `<R>/etc/init.d/S05avahi-setup.sh`

```sh
if [ ! -d /tmp/avahi-autoipd ]; then
    rm -rf /tmp/avahi-autoipd
    mkdir /tmp/avahi-autoipd
    chown avahi.avahi /tmp/avahi-autoipd
fi
```
**[READ]** `:5-9`. The guard is inverted relative to its body — it only recreates
the directory when it is *not* already a directory, which is the correct
behaviour, but the `rm -rf` inside is then pointless unless a non-directory
exists there. Harmless. Note this directory is created **before** `S14fs` clears
`/tmp`; `rm -rf /tmp/*` at `S14fs:45` deletes it again. **[READ]** The avahi
daemon starts later (`S50avahi-daemon`) and recreates what it needs, or does not
— **[UNKNOWN]** whether autoipd is used at all, since `interfaces` uses `dhcp`
not `zeroconf`.

### S10udev — `<R>/etc/init.d/S10udev`

```sh
printf '\000\000\000\000' > /proc/sys/kernel/hotplug
$UDEV_BIN -d || (echo "FAIL" && exit 1)
udevadm trigger --type=subsystems --action=add
udevadm trigger --type=devices --action=add
udevadm settle --timeout=30 || echo "udevadm settle failed"
```
**[READ]** `:31-35`. Stock Buildroot. **`settle --timeout=30` is the first place
the boot can stall for a long time**, and its failure is only echoed. **[READ]**

The `|| (echo "FAIL" && exit 1)` runs `exit 1` **in a subshell** — it does not
terminate the script. **[READ]** Another swallowed error.

#### udev rules — `<R>/etc/udev/rules.d/`

All **[READ]**, complete:

```
20-xmos-nic.rules:   SUBSYSTEM=="net", ATTR{address}=="02:00:00:00:00:00", ACTION=="add", RUN+="…/usb-int.sh %k"
30-usb-nic.rules:    SUBSYSTEM=="net", ATTR{address}=="8c:ae:4c:*",        ACTION=="add", RUN+="…/usb-ext.sh %k"
50-eth-ext-nic.rules:SUBSYSTEM=="net", ATTR{address}=="a4:11:63:b*",       ACTION=="add", RUN+="…/eth-ext.sh %k"
```

**Interfaces are named by MAC address, not by bus path.** `usb-int.sh` renames to
`usbint` and pins the ARP entry:

```sh
/sbin/ifdown -f $1
/sbin/ip link set $1 name usbint
/sbin/ifup -f usbint
arp -i usbint -s 203.0.113.2 02:00:00:00:00:00
```
**[READ]** `usb-int.sh:3-6`.

`eth-ext.sh` and `usb-ext.sh` are identical to each other except for the name,
and each installs four DNAT rules **[READ]** `eth-ext.sh:7-10`:

```
iptables -t nat -A PREROUTING -i ethext -p udp --dport 7770 -j DNAT --to 203.0.113.2:7770
                                              …7771 …9100 …9300  likewise
```

**These same four rules are installed a second time by `S95dhcpd:11-14`.**
**[READ]** Duplicate `-A PREROUTING` rules — functionally harmless, cosmetically
wrong, and they accumulate if an interface re-appears.

**Load-bearing consequence.** `S42sc:4` starts `las-sc` with `-l localhost:9300`,
and `las-sc`'s own help text reads `Listen address (default localhost:9300`
**[READ]** (`strings las-sc`). So `las-sc` binds loopback only, while the DNAT
rule sends externally-arriving UDP/9300 to **203.0.113.2** — the XMOS. **An OSC
packet sent to the instrument's Ethernet address on port 9300 does not reach
`las-sc`.** **[INFERRED]** from those two [READ] facts. Anyone reaching `las-sc`
from outside is doing it by some other route; that route is **[UNKNOWN]** and is
outside this region.

The thumb-drive rule, `40-usb-thumbdrive.rules` **[READ]**, mounts any
`sd[a-z][0-9]` under `/media/%k` with options from `blkid`, then runs
`sort-part.sh`, which symlinks `/media/thumbdrive` to **the largest mounted
partition** **[READ]** `sort-part.sh:17-32`. Removal unmounts lazily and deletes
`/media/thumbdrive`. Every "USB key" check in the boot scripts resolves through
that symlink.

### S12splash — `<R>/etc/init.d/S12splash`

**[READ]** `:7-27`:

```sh
echo -e '\033[?17;0;0c' > /dev/tty1          # blank the VT cursor
las-fb-config 1 0                            # fb1 global alpha = 0 (transparent)
echo 0 > /sys/class/backlight/backlight/brightness
echo 0 > /sys/class/graphics/fb0/blank
echo 0 > /sys/class/graphics/fb1/blank
fbset --geometry 10 10 832 5022 32 --timings … -fb /dev/fb1
fbset --geometry 832 480 832 5022 32 --timings … -fb /dev/fb1
echo "U:832x480p-40" > /sys/class/graphics/fb1/mode
rm -f /tmp/.X0-lock
X :0 -nocursor -s 0 &
dd if=/boot/moog_splash.fb of=/dev/fb1
echo 99 > /sys/class/backlight/backlight/brightness
for i in $(seq 255 $END); do las-fb-config 1 $i; usleep 1000; done;
```

* `las-fb-config` is a 3.8 KB ELF whose usage string is
  `Usage: %s framebuffer [0,1] [ alpha_val[0-255] ]` **[READ]** (`strings`). It
  sets the IPU overlay's global alpha by `ioctl`. So `1 0` = fb1 fully
  transparent, and the loop fades it in.
* **`$END` is never set.** `$(seq 255 $END)` collapses to `seq 255`, which emits
  1…255 — so the fade runs in the right direction by accident. **[READ] +
  [INFERRED]** (shell word-splitting). The author plainly meant a countdown.
  Duration ≈ 255 ms plus 255 process spawns.
* The virtual framebuffer is **832 × 5022 × 32bpp = 16,713,216 bytes**, which is
  exactly the size of `<R>/boot/moog_logo.fb`. `<R>/boot/moog_splash.fb` is
  16,716,544 bytes = 832 × **5023** × 4 — one scanline larger than the
  framebuffer it is `dd`'d into. **[READ]** (arithmetic on the two file sizes).
  `dd` writes until the device is full and reports a short write; nothing checks.
  **[INFERRED]**
* **X is started here, backgrounded, and never waited for.** `S43gui` opens
  xterms against `DISPLAY=:0` roughly 3–4 seconds later (§4, `S42sc` sleeps 3).
  There is no readiness check anywhere. **[READ]**
* `<R>/boot/moog_splash_ver.bmp`, `moog_splash_version.bmp`, `moog_splash.bmp`,
  `moog_splash.bmp.gz`, `moog_splash_ver.bmp.gz` and `moog_logo.fb` are **not
  referenced by any script or binary in the rootfs** — the only file that names
  any splash asset is `S12splash`. **[READ]** (`grep -rl` over `etc`, `bin`,
  `sbin`, `usr/bin`, `usr/sbin`). Presumably U-Boot draws the versioned one.
  **[UNKNOWN]**
* **`psplash` and `psplash-write` exist at `<R>/usr/bin/` and are invoked by
  nothing.** **[READ]** The Buildroot splash package ships; the product does not
  use it. Any prior documentation attributing the Moog One's boot splash to
  psplash is wrong.

**Failure modes.** If `/dev/fb1` is absent, `fbset` and `dd` fail and the script
still `exit 0`s **[READ]** `:45`. If X fails to start, `S43gui`'s xterms and
`las-frontend` all fail, `las-frontend` never writes its cookie, and `S43gui`
spends 100 s in its first timeout loop (§6).

### S14fs — `<R>/etc/init.d/S14fs`

The housekeeping script, and the messiest file in the region. What it
**definitely** does, all **[READ]**:

| line | action |
|---|---|
| `:45-46` | `rm -rf /tmp/*` ; `rm -f /tmp/.X0-lock` |
| `:47-48` | same again via `/var/local/tmp` |
| `:51` | `rm -rf /mnt/fwu/*` — **empties the firmware staging partition on every boot** |
| `:54-55` | `rm -rf /var/*.cookie` ; `rm -rf /var/las-frontend/las-frontend.cookie` |
| `:58` | `/etc/log-refresh` |
| `:61` | `crontab -c /etc/crontab -l` |
| `:64` | `rm -rf /var/log/*.0.*` |
| `:67` | `mv /var/log/las-watchdog.log /var/log/las-watchdog.log.0` |
| `:39-41` | `mkdir -p /root/.ssh ; cp /etc/authorized_keys /root/.ssh ; sync` |

Findings:

1. **`rm -f /tmp/.X0-lock` at `:46` runs *after* `S12splash` has already started
   X**, deleting the lock file of a running X server. **[READ]** (script
   numbering: 12 < 14). The X **socket** survives — `rm -rf /tmp/*` does not
   match the dotted `/tmp/.X11-unix` **[INFERRED]**, shell globbing — so the
   display keeps working; only the mutual-exclusion lock is lost. Latent, but a
   second `X :0` would no longer be prevented.
2. **`crontab … -l` lists a crontab; it does not install or start anything.**
   Busybox usage: `[-c DIR] [-u USER] [-ler]|[FILE]` with `-l  List crontab`
   **[READ]** (`strings busybox`). And **`crond` is started by nothing** — the
   string `crond` appears in no init script and no inittab entry **[READ]**
   (`grep -rn` over `etc/init.d` and `etc/inittab`). `<R>/etc/crontab/root`
   contains `0 3 * * * /etc/log-refresh` **[READ]**, which therefore never runs.
   The script's own comment — "start cron job for log refresh just in case
   someone leaves this thing on for a year" — describes an outcome that does not
   occur. Log rotation happens exactly once, at boot, in `:58`.
3. **`/etc/authorized_keys` does not exist in the shipped image** **[READ]**, so
   the `cp` at `:40` fails silently every boot and no SSH public key is ever
   provisioned. Combined with §10.2, password auth is the only path in.
4. The `ln -sf` calls at `:11-25` have their arguments in the wrong order —
   `ln -sf /srv /var/local/srv` creates `/var/local/srv -> /srv`, while `/srv` is
   already a symlink to `/var/local/srv` **[READ]** (`ls -la <R>/`). On a machine
   whose `/var/local/*` directories already exist the guards are false and none
   of this runs. On a blank `/var` it would build symlink loops. **[INFERRED]**
   `:25` (`ln -sf /tmp /var/local/tmp`) is unguarded and runs every boot; if
   `/var/local/tmp` is a directory it silently creates `/var/local/tmp/tmp`
   instead. **[INFERRED]** — standard `ln` semantics.
5. `:28-36` `mkdir` then `ln -s` onto the same path; the `ln` can never succeed.
   Dead code, harmless. **[READ]**
6. **`rm -rf /mnt/fwu/*` at `:51` is the reason a half-finished update cannot
   resume.** Whatever `lasfwu` had staged is gone at the next boot. **[READ]**

`/etc/log-refresh` **[READ]** in full: for each file in `/var/log/*`, if larger
than 512,000 bytes, `mv $i $i.0`. One generation, no compression.

### S20urandom

Stock Buildroot. Restores `/etc/random-seed` into `/dev/urandom`, deletes it,
writes a fresh 512-byte seed. **[READ]** `:26-30`. Because root is genuinely
writable (§9.1) this succeeds; the "read-only file system detected" branch at
`:15-19` never fires. **[INFERRED]**

### S25xmosfw — `<R>/etc/init.d/S25xmosfw`

The whole script **[READ]**:

```sh
test -r /etc/default/dropbear && . /etc/default/dropbear   # copy-paste artefact

start() {
    echo "Cycle XMOS Power"
    config-las-spi xmos
}
case "$1" in
  start)   start ;;
  stop)    ;;                     # <-- EMPTY
  restart|reload) ;;              # <-- EMPTY
  …
```

* It sources the **dropbear** defaults file. Harmless (`DROPBEAR_ARGS="-B "`),
  and a clear sign this file was copied from `S50dropbear`. **[READ]**
* **`stop` and `restart` are both empty.** The XMOS is never reset on the way
  down and cannot be reset by `S25xmosfw restart`. **[READ]** This is the fact
  §11 turns on.

`<R>/usr/bin/config-las-spi` **[READ]** in full (POSIX shell, `set -e`):

```sh
config_spi_xmos() {
    devmem 0x20e0244 32 5      # IOMUXC KEY_COL0 -> ALT5 (GPIO)
    devmem 0x20e0248 32 5      # KEY_COL1
    devmem 0x20e0258 32 5      # KEY_ROW0
    devmem 0x20e025c 32 5      # KEY_ROW1
    devmem 0x20a8004 32 0x40008020   # GPIO4_GDIR: 6,7,8,9 = inputs
    echo 0 > /sys/class/leds/XMOS_RESET_N/brightness
    echo 1 > /sys/class/leds/XMOS_RESET_N/brightness
}
config_spi_som() {
    echo 0 > /sys/class/leds/XMOS_RESET_N/brightness   # hold in reset
    devmem 0x20e0244 32 0      # -> ALT0 (ECSPI1)
    devmem 0x20e0248 32 0
    devmem 0x20e0258 32 0
    devmem 0x20e025c 32 5
    devmem 0x20a8004 32 0x40008220
}
```

So "Cycle XMOS Power" is a **misnomer** — it is a GPIO reset, not a power cycle.
`xmos` hands the SPI1 bus to the XMOS (i.MX6 pins become GPIO inputs) and
releases reset; `som` takes the bus back and **leaves the XMOS held in reset**.
**[READ]**

`set -e` means any failed `devmem` aborts before the reset is released.
**[READ]** `config-las-spi:2`. `S25xmosfw` does not check the result.

The reset line: **`XMOS_RESET_N` is GPIO6_IO05**, from the device tree
**[READ]** (`imx6dl-profili-som.dtb`, node `/misc_output/xmosreset`):

```
compatible = "gpio-leds"     (on the parent, /misc_output)
label = "XMOS_RESET_N"
gpios = <0x36 0x5 0x0>        phandle 0x36 = /soc/aips-bus@02000000/gpio@020b0000 = GPIO6, flags 0 = ACTIVE_HIGH
default-state = "off"
```

**This is the key device-tree fact of the whole boot.** `leds-gpio` applies
`default-state = "off"` at probe, driving GPIO6_5 **low**. The signal is
active-low reset. **The XMOS is therefore forced into reset early in every
kernel boot and stays there until `S25xmosfw` writes `1`.** **[INFERRED]** from
the DTB + `config-las-spi`, and **corroborated [READ]** by the ten-second gap in
dmesg (§7).

### S30dbus

Stock. `dbus-uuidgen --ensure ; dbus-daemon --system`. **[READ]** `:26-27`.
Creates `/tmp/dbus`, `/var/run/dbus`, `/var/lock/subsys`. Nothing in the audio or
UI path is known to use D-Bus; avahi is configured `enable-dbus=no` **[READ]**
`<R>/etc/avahi/avahi-daemon.conf`. Whether anything uses it is **[UNKNOWN]**.

### S40network — `<R>/etc/init.d/S40network`

```sh
mkdir -p /run/network
/sbin/ifdown -a
/sbin/ifup -a &            # so dhcp doesn't hold up startup
rm -rf /var/run/avahi-daemon/pid
rm -rf /var/run/*.pid
echo "1" > /proc/sys/net/ipv4/ip_forward
```
**[READ]** `:7-17`.

* **`rm -rf /var/run/*.pid` deletes the PID files `S01logging` just wrote** for
  syslogd and klogd. **[READ]** (`S01logging:8-9` writes
  `/var/run/syslogd.pid`, `/var/run/klogd.pid`; `S40network:16` removes them).
  Consequence: `rcK`'s `S01logging stop` — `start-stop-daemon -K -p /var/run/syslogd.pid`
  — has no PID file to work from and cannot stop the loggers. **[INFERRED]**
  They die with the reboot anyway.
* `ip_forward=1` turns the instrument into an IP router between `usbint`
  (203.0.113.0/24), `eth0` (192.168.1.0/24), `ethext` and `usbext`. **[READ]**
* `<R>/etc/network/interfaces` **[READ]**, complete:

  ```
  auto lo eth0 usbint usbext ethext
  iface eth0   inet static   address 192.168.1.1  netmask 255.255.255.0  gateway 192.168.1.254
  iface usbint inet static   address 203.0.113.1  netmask 255.255.255.0
  iface usbext inet dhcp
  iface ethext inet dhcp
  ```

  `eth0` is configured with a **static 192.168.1.1 and a default gateway** even
  though the i.MX6's own MAC is disabled in the DTB (per
  `docs/CORRECTIONS-2026-09-08.md` §1). Leftover. **[READ]**
* `/etc/network/if-pre-up.d/wait_iface` waits for a slow interface **only if
  `IF_WAIT_DELAY` is set** **[READ]**, and `interfaces` sets no `wait-delay`
  option **[READ]**. So the wait is a no-op and `ifup -a` runs before the XMOS
  has enumerated. Coverage comes from the udev rules instead, which `ifup -f`
  each interface as it appears (§4, S10udev). **[INFERRED]**

### S42sc — `<R>/etc/init.d/S42sc`

The single most important line in the boot **[READ]** `:4`:

```
/usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300 \
  --vxfw=/usr/share/xmosfw/app_vx_10M_v2.2.1.bin \
  --vxdb=/var/tuning.vxtune \
  --vcfw=/usr/share/xmosfw/app_las_v2.2.2.bin \
  --vcfv=33686271 \
  --temp --expr-syms=/usr/share/vx_ee.scm \
  --panel-state=localhost:9500 $1
```

`start()` runs `runsc -q &` then **`sleep 3`** unconditionally **[READ]** `:23-24`
— three seconds of every boot, whether or not `las-sc` is ready. There is a
commented-out `config-las-spi xmos` in `start()` labelled
`#!!!HACK … workaround for startup problems with the VC firmware` **[READ]**
`:17-21`.

`stop()` **[READ]** `:28-32`: `killall sclang jackd scsynth las-sc` then
`kill -9 \`pidof jackd\``.

`nobg` runs `runsc` in the foreground — the supported way to watch `las-sc`
start. **[READ]** `:46-49`.

`/etc/hosts` maps `203.0.113.2 vc` **[READ]**, so `-t vc` targets the XMOS.

### S43gui — `<R>/etc/init.d/S43gui`

`#!/bin/bash` (not `sh`). **[READ]** `:1`. Sequence, all **[READ]**:

```sh
cgconfigparser -l /etc/cgconfig.conf
DISPLAY=:0 xterm -name xterm1 …  &     # three of them
mkdir /var/las-frontend                # if absent
DISPLAY=:0 las-frontend --usb-path=/media/thumbdrive --data-path=/var/las-frontend \
   --host-paneloutput=203.0.113.2 --host-performance=vc --host-oleds=203.0.113.2 \
   --affinity-mask=1 --host-systemclock=vc --cookie=1 --affinity-panel=1 \
   --startup-coordination --host-vc=vc &
<wait for /var/las-frontend/las-frontend.cookie, max 1000 x 100 ms>
DISPLAY=:0 las-dwm &
<wait for /var/las-dwm.cookie, max 1000 x 100 ms>
cat /sys/class/backlight/backlight/brightness > /var/lcd_brightness
echo 0 > /sys/class/backlight/backlight/brightness
las-fb-config 1 0                      # hide the splash overlay
DISPLAY=:0 xrandr -o inverted
usleep 1000000
/usr/bin/detect-held-buttons &
cat /var/lcd_brightness > /sys/class/backlight/backlight/brightness
echo "U:10x10p-40" > /sys/class/graphics/fb1/mode
```

* The argv is confirmed live, character for character: `runtime-state.txt:107`
  shows `915 root las-frontend --usb-path=/media/thumbdrive … --host-vc=vc`.
  **[READ]**
* **The splash-to-GUI transition is hidden behind a one-second backlight blank**
  while the GPU rotation is applied. Then fb1 is shrunk to 10×10 "to avoid ipu
  overruns" (the script's own comment). **[READ]**
* **The cgroups are created and never used.** `<R>/etc/cgconfig.conf` **[READ]**
  defines `dsp` (cpuset.cpus=1, shares 100), `frontend` (cpus=0,
  `sched_load_balance=0`, shares 25, `memory.soft_limit_in_bytes=16756736`) and
  `sc` (cpus=0, shares 25). `cgexec` and `cgclassify` exist as binaries
  **[READ]** but **no script or binary in the rootfs references them, or
  `/cgroup/`, other than `cgconfig.conf` itself** **[READ]** (`grep -rl` over
  `etc` and `usr/bin`). There is no `cgrules.conf` and no `cgrulesengd`
  **[READ]**. The live snapshot shows the four hierarchies mounted
  **[READ]** `runtime-state.txt:186-189` and no process assignment.
  **CPU placement is done instead by `las-frontend --affinity-mask=1
  --affinity-panel=1` and by `chrt` in `S99final`.** **[INFERRED]**
* **Both cookie waits have a 1000-iteration timeout (100 s each) and, on
  timeout, print a message and continue.** **[READ]** `:37-40`, `:58-61`.
  Worst case `S43gui` contributes **200 seconds** to the boot and still returns.
  Contrast `S99final` (§9.2).
* Each wait deletes the cookie it found **[READ]** `:29`, `:52`, so the cookie is
  strictly an edge, not a state.

### S50avahi-daemon

`$DAEMON -c || $DAEMON -D`. **[READ]** `:8`. `-c` checks for a running daemon;
if none, `-D` daemonises.

### S50dropbear — `<R>/etc/init.d/S50dropbear`

**[READ]** `:10`, `:29-42`:

```sh
DROPBEAR_ARGS="$DROPBEAR_ARGS -R"
…
if [ -e /media/thumbdrive/k ]; then
    keyval=`hexdump /media/thumbdrive/k | awk '{print $3 $2}'`
    if [ $keyval = 23051934 ]; then
        echo "`date` : DROPBEAR : You have a key! Aren't you special!" >> /var/log/messages
        start-stop-daemon -S -q -p /var/run/dropbear.pid --exec /usr/sbin/dropbear -- $DROPBEAR_ARGS
        exit;
    fi;
fi;
```

See §10.2 for what this means. Note the `if` has **no `else`** — with no key, the
function simply falls off the end and `exit $?` returns success. No SSH.

### S80dhcp-relay, S80dhcp-server

* `S80dhcp-relay` has `test -n "$INTERFACES" || exit 0` with `INTERFACES=""` and
  no `/etc/default/dhcrelay` **[READ]** — it exits immediately. `dhcrelay` is not
  even installed **[READ]**.
* `S80dhcp-server` has **no such guard**. Its only checks are that
  `/usr/sbin/dhcpd` and `/etc/dhcp/dhcpd.conf` exist **[READ]** `:21-22` — and
  **both do** **[READ]**. So it runs `start-stop-daemon -S -q -x /usr/sbin/dhcpd -- -q`.
  `<R>/etc/dhcp/dhcpd.conf` is the **unmodified ISC example file** — `example.org`
  name servers, `default-lease-time 600`, and **no `subnet` declaration at all**
  **[READ]**. ISC dhcpd with no subnet matching any interface refuses to start.
  **[INFERRED]** — so the instrument does **not** run a rogue DHCP server, but it
  does spawn a daemon that immediately exits, silently, on every boot.

### S95dhcpd — `<R>/etc/init.d/S95dhcpd`

```sh
/sbin/dhcpcd start ethext &
iptables -t nat -A PREROUTING -i ethext -p udp --dport 7770 -j DNAT --to 203.0.113.2:7770
                                              7771 / 9100 / 9300 likewise
```
**[READ]** `:9-14`. This is the second, unconditional installation of the four
DNAT rules already installed by `eth-ext.sh` (§4, S10udev). **[READ]**

Note the naming: the script is called `dhcpd` but starts `dhcpcd`, the **client**.

### S99final — `<R>/etc/init.d/S99final`

`#!/bin/bash`. **[READ]** `:1`. Complete `start()`:

```sh
iputasks=`ps | grep ipu | awk  '{print $1} NR==2{exit}'`
ipuirq=`ps | grep 2400000 | awk  '{print $1} NR==2{exit}'`
function assign_ipu_pri { chrt -f -p "${3}" "${1}"; chrt -f -p "${3}" "${2}"; }
assign_ipu_pri $iputasks 93
assign_ipu_pri $ipuirq 80
devmem 0x020e0018 w 0xffffffff          # AXI/IOMUXC GPR6 - bus priority

while true; do
        if [ -e /var/las-sc.cookie ]; then
                echo LAS-SC is up! Cookie has been found!;
                rm -rf /var/las-sc.cookie;
                (sleep 1; las-watchdog -t=10000 > /var/log/las-watchdog.log 2>&1) &
                break;
        fi;
        usleep 100000
done;

if [ -e /media/thumbdrive/k ]; then
        keyval=`hexdump /media/thumbdrive/k | awk '{print $3 $2}'`
        if [ $keyval = 23051934 ]; then
                echo "`date` : S99 : You have a key! Aren't you special!" >> /var/log/messages
                sleep 3;
                killall las-watchdog;
                exit;
        fi;
fi;

killall xterm;
killall las-dwm;
mount -f -o remount,ro /
```

Five things, each treated below: the `chrt` calls (§4 note), the AXI write, the
**unbounded** cookie wait (§9.2), the developer key (§10.1), and the **fake**
read-only remount (§9.1).

**`assign_ipu_pri` is broken in two ways at once.** It is defined to take three
arguments — two PIDs and a priority — and is called with **two**: a PID and the
priority. **[READ]** `:9-15`. So inside the function `${1}` is the PID, `${2}` is
the *priority value*, and `${3}` is **empty**. The two lines that execute are:

```
chrt -f -p ""  "$iputasks"     # empty priority
chrt -f -p ""  "93"            # empty priority, and PID 93 as the target
```

The priority argument is empty in both, and the second call additionally treats
the literal priority number as a **process ID**. **[READ] + [INFERRED]** (shell
positional-parameter semantics). `chrt` with an empty priority should reject the
invocation before touching anything **[INFERRED]** — which is the only reason the
stray `chrt … 93` and `chrt … 80` are not a hazard in their own right.

Net effect: **this script sets no scheduling priority at all.** The live
snapshot's IPU thread priorities are therefore either kernel defaults or set
somewhere else; `docs/CORRECTIONS-2026-09-08.md` §8 records display threads at
FIFO 93/80 as an **[AGENT]**-grade observation. **These two readings are in
tension and the tension is unresolved — see §13.**

`devmem 0x020e0018 w 0xffffffff` targets **IOMUXC_GPR6** **[INFERRED]** from the
i.MX6 IOMUXC base 0x020E0000; the comment calls it "set axi bus pri".

---

## 5. The service graph

```
                       busybox init (PID 1)
                              |
        sysinit: mount proc, remount / rw, mount -a, hostname, rcS
                              |
   +--------------------------+----------------------------------+
   |                                                             |
 S01 syslogd/klogd                                        S10 udevd
 S02 governor/clock                                          |
 S05 avahi dir                          +--------------------+---------------------+
 S12 X  +  splash on fb1                |                    |                     |
 S14 wipe /tmp, /mnt/fwu, cookies    net rules          thumbdrive rule       (settle 30 s)
 S20 random seed                    usbint/usbext/ethext  /media/thumbdrive
 S25 config-las-spi xmos ---> XMOS out of reset ---> USB device enumerates
 S30 dbus                                              (t ~ 11.9 s)
 S40 ifup -a &, ip_forward
 S42 las-sc -----------------------------+  OSC 7775 / 9300 / 9500, target vc
     sleep 3                             |
 S43 cgconfigparser (inert)              |
     3 x xterm                           |
     las-frontend --startup-coordination-+---- waits for las-sc's go-ahead
        |                                |
        +--> /var/las-frontend/las-frontend.cookie  --> S43 proceeds
     las-dwm                             |
        +--> /var/las-dwm.cookie         |
     xrandr -o inverted, backlight       |
     detect-held-buttons &               |
 S50 avahi-daemon                        |
 S50 dropbear   [only with USB key]      |
 S80 dhcp-relay (exits), dhcp-server (exits)
 S95 dhcpcd ethext, iptables DNAT        |
 S99 chrt, devmem                        |
     wait forever for  <------------------+
        /var/las-sc.cookie
     -> las-watchdog -t=10000
     [key? keep xterms + dwm, kill watchdog, exit]
     killall xterm; killall las-dwm; mount -f (no-op)
                              |
              inittab respawn: getty on console
```

---

## 6. Startup coordination and the cookie files

Three cookies. All three are **one-shot edges**: the waiter deletes the file it
found. **[READ]**

| cookie | written by | waited on by | timeout |
|---|---|---|---|
| `/var/las-frontend/las-frontend.cookie` | `las-frontend` (`--cookie=1`) | `S43gui:27` | 1000 × 100 ms = 100 s |
| `/var/las-dwm.cookie` | `las-dwm` | `S43gui:50` | 1000 × 100 ms = 100 s |
| `/var/las-sc.cookie` | `las-sc` | `S99final:21` **and** `las-watchdog` | **none** |

Evidence for the writers, all **[READ]** from `strings`:

* `las-frontend` carries `las-frontend.cookie`, `Writing startup cookie`,
  `ReadCookie`, `SetCookie`,
  `ZN3las22LASFrontEndApplication5Pimpl18writeStartupCookieEvEUlvE_`, and the
  option help `--cookie=<string>      Cookie value to write out once startup is
  fully completed`.
* `las-dwm` carries the literal `/var/las-dwm.cookie` and nothing else
  cookie-related.
* `las-sc` carries `/las-sc.cookie`, `Creating cookie`, `Couldn't create cookie`,
  and the Scheme frames `M(drop-cookie path3310)` and `sc/sc.scm:429: drop-cookie`.
* `las-watchdog` carries `/var/las-sc.cookie`.

**`S14fs:54-55` deletes all cookies at boot**, before any of the writers start
**[READ]**, so a stale cookie from the previous boot cannot short-circuit a wait.
That is the one piece of this design that is unambiguously right.

### 6.1 The `--startup-coordination` handshake

`las-frontend`'s own help text **[READ]**:

```
--startup-coordination Coordinate the startup with the sound engine controller
```

and its runtime strings **[READ]**:

```
Beginning startup coordination
No startup coordination, starting immediately
Applying startup status
ending startup status thread          (this one is in las-sc)
```

`las-sc` implements the other end **[READ]**, Scheme frame names preserved in the
binary:

```
M(startup-dispatch s3187 msg3188)          sc/sc.scm:369, :388
M(startup-msg-handler s3204 sock3205 chan3206)   sc/sc.scm:888
M(handle-status-messages s3164 msg3165)    sc/sc.scm:252, :375
M(drop-cookie path3310)                    sc/sc.scm:429
```

**Reconstruction [INFERRED]** — the shape is clear, the wire detail is not:

1. `S42sc` starts `las-sc`; `S42sc` sleeps 3 s and returns regardless.
2. `S43gui` starts `las-frontend` with `--startup-coordination` and
   `--panel-state`/`--host-*` all pointing at `vc` (203.0.113.2) or localhost.
3. `las-frontend` connects to `las-sc` and waits rather than drawing a UI —
   `Beginning startup coordination`. Without the flag it would print
   `No startup coordination, starting immediately`.
4. `las-sc` performs the long work — XMOS voice-controller and voice-card
   firmware checks and flashes, tuning-data upload (§8.8) — and reports progress
   as **status messages** which `las-frontend` renders in `StartupPanel`
   (`Applying startup status`).
5. When `las-sc` is serving, it calls `drop-cookie` → `/var/las-sc.cookie`, which
   releases `S99final`.
6. `las-frontend`, once *its* startup is "fully completed", writes
   `las-frontend.cookie`, which released `S43gui` much earlier.

The two cookies are therefore **not** ordered by the script sequence:
`S43gui` (frontend cookie) runs long before `S99final` (sc cookie), so on a boot
that includes firmware work, `S43gui` returns first and `S99final` holds the boot
open until the engine is genuinely up. **[INFERRED]**

The exact OSC transport of the status messages is **[UNKNOWN]** from this
region; `--panel-state=localhost:9500` is the likely channel **[INFERRED]**
from the argv.

---

## 7. Why the XMOS appears at t = 11.9 s

Chain of evidence:

1. DTB: `/misc_output/xmosreset`, `gpio-leds`, `label = "XMOS_RESET_N"`,
   `gpios = <GPIO6 5 ACTIVE_HIGH>`, `default-state = "off"`. **[READ]**
2. `leds-gpio` drives the line to its inactive level at probe. Active-high flag +
   "off" = **logic low**. The net is named `…_N`. Low = reset asserted.
   **[INFERRED]** — standard `leds-gpio` and reset-net conventions.
3. The **only** code in the rootfs that writes `1` to that node is
   `config-las-spi`'s `config_spi_xmos()`. **[READ]** (`grep -rl XMOS_RESET_N`
   returns `config-las-spi` alone).
4. `config-las-spi xmos` is invoked from exactly two places: `S25xmosfw:11`
   **[READ]**, and `las-watchdog`'s embedded recovery script **[READ]** (§10.4).
5. dmesg: EHCI host buses are up at t = 0.497 and 0.519; the thumb drive on bus 1
   enumerates at t = 1.703; **the XMOS on bus 2 enumerates at t = 11.904**.
   **[READ]**

**Conclusion [INFERRED, strongly supported]:** the XMOS is held in reset from
kernel probe until `S25xmosfw` runs, roughly eleven seconds into the boot, and
enumerates about 1.5 s later. The delay is by design, not a fault. Everything
that talks to `vc` — `las-sc`, `las-frontend`, `detect-held-buttons`,
`las-watchdog` — is gated behind it.

`detect-held-buttons` handles this explicitly with its own retry loop
(`ping vc -c1 -q` … `sleep 1`) **[READ]**. `S40network`'s `ifup -a` does not, and
relies on the udev rules firing later (§4, S10udev).

---

## 8. A/B partitions and the firmware update

`<R>/usr/bin/lasfwu` is a **33,940-byte bash script** — not a binary — created by
"Chris Howe on 6/26/17". **[READ]** `lasfwu:1-5`. It is fully readable and
everything in this section is quoted from it.

### 8.1 The partition map

| partition | role | evidence |
|---|---|---|
| `mmcblk2p1` | **factory rootfs** | `lasfwu:469` `case $currentpartition in 1)` → `:528` "Currently booted from factory partition" **[READ]** |
| `mmcblk2p2` | **slot U1** (rootfs A) | `fstab:8` → `/mnt/u1`; `lasfwu:473` **[READ]** |
| `mmcblk2p3` | **slot U2** (rootfs B) | `fstab:9` → `/mnt/u2`; `lasfwu:488` **[READ]** |
| `mmcblk2p4` | **vfat**, `/var/lib/sys` — the boot selector | `fstab:12`; `lasfwu:809` **[READ]** |
| `mmcblk2p5` | — | **[UNKNOWN]** |
| `mmcblk2p6` | `/var` — user data, survives updates | `fstab:10` **[READ]** |
| `mmcblk2p7` | `/mnt/fwu` — update staging, labelled **FWU** in the GPT | `fstab:11`; `lasfwu:456` **[READ]** |

The owner's instrument runs from **p3** (slot U2): `root=/dev/mmcblk2p3`
**[READ]** `dmesg-before-reboot.txt:21` and `runtime-state.txt:2`.

### 8.2 How `lasfwu` learns where it is

```sh
currentpartition=`cat /proc/cmdline | awk -F "root=" '{print $2}' \
   | awk -F " " '{print $1}' | awk -F "/dev/mmcblk2p" '{print $2}'`
```
**[READ]** `lasfwu:465`. Note this **requires** the literal string
`/dev/mmcblk2p<N>` in the kernel command line; a `PARTUUID=` or `root=/dev/root`
boot would yield an empty `currentpartition` and fall through the `case` to `*)`
with **`replacepart` unset** **[READ]** `:539-540`. The subsequent
`dest="/dev/mmcblk2p$replacepart"` would then be `/dev/mmcblk2p`. **[INFERRED]**
Not reachable on this hardware as configured, but it is an unguarded path.

### 8.3 `versionb` — the comparison key

`<R>/etc/versionb` is **8 bytes**: `ff 02 08 01 00 00 00 00`. **[READ]** (`xxd`)

`lasfwu` converts it like this **[READ]** `:481-483`:

```sh
hex=`hexdump -C /mnt/u1/etc/versionb | awk -F " " '{print $5$4$3$2}'`
long=`echo $hex | tr '[a-z]' '[A-Z]' | awk '{print "ibase=16; " $1}' | bc`
```

`hexdump -C` prints `00000000  ff 02 08 01 …`, so `$2..$5` are `ff 02 08 01` and
`$5$4$3$2` reassembles them **reversed**: `010802ff`. Through `bc` that is
**17,302,271**.

**So the format is a big-endian-assembled `0xMM_mm_pp_FF`** — major, minor,
patch, then a constant `0xFF` — and larger means newer. v1.8.2 → `0x010802FF`.
**[READ] + [INFERRED]** (arithmetic).

**Independent confirmation, and this is what makes it certain:** the same
encoding carries the XMOS voice-controller version.

| | v1.5.0 | v1.8.2 |
|---|---|---|
| `S42sc --vcfv=` | `33620735` = `0x020102FF` = **v2.1.2** | `33686271` = `0x020202FF` = **v2.2.2** |
| `--vcfw=` file | `app_las_v2.1.2.bin` | `app_las_v2.2.2.bin` |
| `--vxfw=` file | `app_vx_10M_v2.1.0.bin` | `app_vx_10M_v2.2.1.bin` |
| `<R>/etc/git-tags` `LAS_FW_GIT_TAG` | — | `lasvc-v2.2.2` |
| `<R>/usr/share/xmosfw/VERSIOND` | — | `33686271` |

All **[READ]**. Two independent version series decode correctly under the same
rule, and `VERSIOND` equals `--vcfv` exactly.

`<R>/etc/version` is the human string `las-v1.8.2` **[READ]**, and `lasfwu:131`
parses it with `awk -F "r"` to strip a release suffix. **[READ]**

### 8.4 Slot selection

**[READ]** `lasfwu:469-541`:

```
booted from p1 (factory):  mount u1 and u2, read both /etc/versionb,
                           replacepart = the OLDER of p2/p3
                           (and p2 if they are equal - "only zero at first upgrade")
booted from p2 (U1):       replacepart = 3
booted from p3 (U2):       replacepart = 2
anything else:             replacepart unset
```

**An update always writes the slot you are not running from.** This is why the
`docs/CORRECTIONS-2026-09-08.md` §6 conclusion holds: a rootfs modification does
not survive an update, because the update boots the *other* slot.

### 8.5 The load pipeline

Order of operations, all **[READ]** `lasfwu:455-836`:

1. Pick `MOUNTDIR` — `/mnt/fwu` if GPT partition 7 is labelled `FWU`
   (`sgdisk -p /dev/mmcblk2 | grep FWU`), else `/var`. `:456-460`
2. Determine `replacepart` (§8.4).
3. Mount `/var/lib/sys` if not mounted. `:550-560`
4. **`echo 0 > /var/lib/sys/sentinelu$part`** — invalidate the target slot's
   sentinel *before* touching it. `:563-564`
5. `echo "$version" > /var/lib/sys/bootversion`. `:566-567`
6. `getkey()` — extract the GPG **encryption** private key from
   `/etc/bob.bmp` via `str /etc/bob.bmp 4`, import it, delete the temp file.
   `:49-51`
7. `pv | tar -xf - -C "$MOUNTDIR/tmpfs/"` — unpack the package. `:416`
8. `pv | gpg … --passphrase bob --decrypt` → `$imagename.ext4`. `:458`
9. `pv | gpg … --verify "$imagesigname"` — **signature check of the decrypted
   image, unconditional**. `:493`
10. Delete the encryption secret key. `:527`
11. `dd if="$upgradefs" bs=2048 | pv | dd bs=2048 of=/dev/mmcblk2p$replacepart`. `:535`
12. `rm -rf "$MOUNTDIR/tmpfs"`, `rm -rf /var/local/gnupg/*`. `:792-794`
13. Mount the newly written slot, copy its `/etc/versionb` into
    `/var/lib/sys/sentinelu$part`, and **`echo $replacepart > /var/lib/sys/bootme`**. `:800-810`
14. Unmount it. `:813`
15. "Wipe falcon space" — see §8.6.
16. Emit `{"progress":"100","status":"200",…}`. `:836`

Progress is reported as JSON on stdout throughout, with `pv -n` writing
percentages to `/tmp/las-fwprct` and status to `/tmp/las-fwstatus`. **[READ]**
`:168-169`, `:735-736`. `las-frontend` invokes `/usr/bin/lasfwu` **[READ]**
(literal string in the binary) and renders those JSON blobs.

### 8.6 The "wipe falcon space" defect

**[READ]** `lasfwu:821-827`, verbatim:

```sh
startofpartmap=`sgdisk -i=1 /dev/mmcblk2 | awk -F "First sector:" '{print $2}' | awk -F "(" '{
print $1}'`

if [ $startofpartmap > 60000 ]; then
    dd if=/dev/zero of=/dev/mmcblk2 bs=1024 count=16384 seek=1024
fi;
rm 60000;
```

`>` inside `[ … ]` in bash is **not** a numeric comparison — it is **output
redirection**. The command that actually runs is `[ $startofpartmap ]` (true for
any non-empty string) with stdout redirected into a new file literally named
`60000`. The `rm 60000` on the next line shows the author saw the stray file and
did not recognise why it was there. **[READ] + [INFERRED]** (bash `[` semantics).

**Consequence:** the guard never guards. `dd if=/dev/zero of=/dev/mmcblk2
bs=1024 count=16384 seek=1024` — **zeroing 16 MiB of the raw eMMC starting at
offset 1 MiB** — runs on every successful update, on every SOM, regardless of
where partition 1 begins. **[INFERRED]**

On this hardware it is very likely harmless: partition 1 evidently starts beyond
sector 60000 (~30 MB), so 1–17 MiB is unallocated space reserved for U-Boot
Falcon-mode payloads. **[INFERRED]** — the actual GPT layout was **not** read and
is **[UNKNOWN]**. On any variant whose first partition starts earlier, this
destroys it.

Two secondary notes. `rm 60000` runs with the working directory wherever
`lasfwu` was invoked; if that directory were read-only the redirection would fail,
the `if` would be false, and the `dd` would be skipped — an accidental safety
that does **not** apply here because root is genuinely writable (§9.1).
**[INFERRED]**

### 8.7 The `bootme` / sentinel handshake

Three files, all on the **vfat** partition `/dev/mmcblk2p4` mounted at
`/var/lib/sys`:

| file | written | value |
|---|---|---|
| `bootme` | `lasfwu:809` after a successful `dd` | `2` or `3` — the slot to boot |
| `sentinelu1`, `sentinelu2` | `lasfwu:564` (`0`, before flashing) and `:808` (the new slot's `versionb`, after) | 8-byte `versionb` blob, or `0` |
| `bootversion` | `lasfwu:566` | the human version string from the MANIFEST |

**Nothing else in the entire rootfs reads or writes any of them.** **[READ]** —
`grep -rl` for `sentinel`, `bootme`, `bootversion` and `/var/lib/sys` over the
whole 492 MB tree returns only `lasfwu` (and `fstab`). **The consumer is
therefore U-Boot**, which is not in the rootfs. **[INFERRED]**

**Reconstruction of the intent [INFERRED]:** `bootme` names the slot; the
sentinel is a commit marker. Set to `0` before the write and to the real
`versionb` after, it distinguishes "this slot is mid-flash and must not be
booted" from "this slot is complete". U-Boot presumably prefers `bootme` when the
matching sentinel is non-zero and falls back to the other slot, or to factory
p1, otherwise. **The fallback rule is [UNKNOWN]** and can only be read out of
U-Boot.

**This is the single point of failure in the update, and the evidence says it is
already fragile.** `/var/lib/sys` is FAT, has no journal, and the live kernel log
records `FAT-fs (mmcblk2p4): Volume was not properly unmounted. Some data may be
corrupt. Please run fsck.` **[READ]** `dmesg-before-reboot.txt:286`. `lasfwu`
does `sync` after writing `bootme` **[READ]** `:810`, which is the right thing,
but the partition is left mounted and dirty for the rest of the session.

### 8.8 What a firmware-update reboot actually does, and where ten minutes go

The manufacturer's own wording, quoted in `docs/arch/performance.md:802-805`
from `captures/firmware-1.8.2/Moog One Firmware Update v1.8.2.pdf`: the update
takes about five minutes, and **"This restart process may take longer than
normal … (approximately 10 minutes)."**

**First, the mechanics of the restart itself.** There is no software restart.
**Nothing in the rootfs calls `/sbin/reboot`, `halt` or `poweroff`** — `grep -rl
reboot` over `etc`, `bin`, `sbin`, `usr/bin`, `usr/sbin` matches only
`/etc/inittab` (in a commented-out `ctrlaltdel` line), `S20urandom` (a comment),
`/etc/dhcp/dhclient.conf`, and every busybox applet symlink, which all share the
one binary. **[READ]** `las-frontend` contains no `/sbin/reboot` string and
execs only `/usr/bin/las-sc`, `/usr/bin/lasfwu` and `/usr/bin/vxtune`.
**[READ]** So "restart your Moog One" means **the user throws the power switch**.
That also explains why the eMMC is routinely found dirty (§1.1).

**Then the boot itself.** On the first boot into a new slot:

1. U-Boot reads `bootme` and boots the *other* rootfs, with **that slot's own
   kernel and DTB** (§1). **[INFERRED]**
2. `/var` (p6) is untouched and carries the **old** preset database, settings and
   `tuning.vxtune` forward. **[READ]** (`fstab` + `lasfwu` never writes p6).
3. `S42sc` starts `las-sc` with the **new** `--vcfv`, `--vcfw` and `--vxfw`
   arguments. `las-sc` queries the running voice controller and compares. Its own
   strings **[READ]**:

   ```
   ( version matches file, no update needed.
   ' version does not match, update needed.
   & version not available, update needed.
   *Update VX firmware even if versions match.
   /info/versionb    /info/vc-version    /fw/version
   ```

4. If the VC version differs, `las-sc` reflashes it. The mechanism is
   **flashrom over SPI**, and the command line is a literal in the binary
   **[READ]**:

   ```
   flashrom -l /usr/share/xmosfw/las_layout -i firmware -w
     -p linux_spi:dev=/dev/spidev0.0
   ```

   with `<R>/usr/share/xmosfw/las_layout` = `00000000:0x001BFFFF firmware`
   **[READ]** — a 1.75 MiB region. The image `app_las_v2.2.2.bin` is 2,097,152
   bytes **[READ]**, i.e. **larger than the layout region it is written into**;
   what flashrom does with the excess is **[UNKNOWN]**.
   Note `las-sc` must take the SPI bus back from the XMOS to do this — hence
   `M(can-power-cycle?)`, `M(set-power-state on706)`, `M(cycle-and-update)`,
   `/usr/bin/config-las-spi`, and the error string
   `VC firmware file provided, but can't power-cycle LAS. (Are you running off
   target?)`. **[READ]**
5. Voice cards are updated **individually**, block by block, not via flashrom.
   `las-sc`'s Scheme frames **[READ]**:

   ```
   M(vxfw-send-block card127 adr128 ofs129 blob130)
   M(vxfw-send-block-from-port card135 adr136 ofs137 port138 block-size139)
   M(vxfw-send-fw-cards ip183 cards184 fwfile185 …)
   M(update-vx s3526 ip3527 fw-file3528 file-version3529 card-versions3530 cards3531 tuning-data3532 force3533)
   ```

   `app_vx_10M_v2.2.1.bin` is 164,352 bytes **[READ]**, per card.
6. Tuning data is re-uploaded and verified —
   `/usr/bin/vxtune write -c vc -f /var/tuning.vxtune`, a literal string in both
   `las-sc` and `las-frontend`. **[READ]**
7. Meanwhile `las-frontend` sits in `StartupPanel` displaying, in this order
   **[READ]** (`strings las-frontend`, file order at offsets 2936502–2936512):

   ```
   POPULATING WITH FACTORY DATA...
   POPULATING WITH FACTORY DATA... 0%
   POPULATING WITH FACTORY DATA... DONE!
   UPDATING VOICE CONTROLLER FIRMWARE...
   UPDATING VOICE CARD FIRMWARE...
   FAILED ENUMERATING VOICE CARDS
   UPDATING TUNING DATA...
   VERIFYING TUNING DATA...
   ```

   plus `UPDATING FIRMWARE ...` and `DON'T POWER OFF THE INSTRUMENT WHILE THE
   UPDATE IS IN PROCESS` at 2936647/2936649.
8. `las-sc` drops `/var/las-sc.cookie`; `S99final` — which has been spinning at
   10 Hz for the entire ten minutes — finally breaks out, starts the watchdog,
   kills the xterms, and the boot completes.

**So the ten minutes is: SQLite factory-data population and schema migration
against a `/var` carried over from the old version, plus a VC flashrom write,
plus a per-card VX transfer (4 cards on an 8-voice instrument, 8 on a 16-voice),
plus a tuning-data write and verify — all of it serialised behind `S99final`'s
untimed spin.** **[INFERRED]** — every component is [READ]; the **time split
between them is [UNKNOWN]** and can only be established by timing a real update.

`docs/arch/performance.md` §5.3 reached the same four-part decomposition from the
`las-frontend` side against the v1.5.0 numbers. This section corroborates it from
the boot side and supplies the v1.8.2 versions. Its warning also stands:
**`THIS PROCESS WILL TAKE UP TO TEN MINUTES.` in `las-frontend` belongs to
`19WarningConfirmPanel` and oscillator compensation — a different ten minutes.**

### 8.9 Package format and why a modified image cannot be installed

Confirmed against `lasfwu` in this pass, consistent with
`docs/CORRECTIONS-2026-09-08.md` §6 **[READ]**:

* A package is a **tar** containing `MOOGFW`, `MANIFEST`, the encrypted image,
  and detached signature files. `validate()` checks the tar is readable, that
  `MOOGFW` and `MANIFEST` both exist, that `MOOGFW`'s content equals the
  MANIFEST's `.MOOGFW` field, that `packed_size` is within 100 bytes of the
  actual member size, and that the version is not the one already running
  (error 5 = "image is currently running"). **[READ]** `:92-140`
* Keys: `<R>/usr/share/sec/` holds `mmepubk`, `mmspubk`, `pubring.gpg`,
  `trustdb.gpg`, and **`secring.gpg` at 0 bytes**. **[READ]** (`ls -la`)
* The **encryption** private key is steganographed in `<R>/etc/bob.bmp`
  (741,056 bytes) and extracted by `str /etc/bob.bmp 4`; passphrase `bob`.
  **[READ]** `lasfwu:49`, `:458`
* The **signature** check at `:493` runs unconditionally before the `dd`.
  `--accept-unsigned` is documented in the help text but is absent from the
  option parser. **[READ]**

Nothing found in this pass contradicts the existing conclusion: **decrypt yes,
re-sign no.**

---

## 9. Defects in the boot path

Numbered for citation. Each is stated with its evidence and its consequence.

### 9.1 The read-only root remount is a no-op — **[READ]**

`S99final:44`:
```sh
mount -f -o remount,ro /
```

`/bin/mount` is a symlink to `/bin/busybox` **[READ]** (`ls -la`). Busybox's
mount applet parses `o:t:rwanfvsiO:T:` **[READ]** — the literal getopt string is
present in the binary — in which `f` is the *fake* flag; busybox's help text for
the sibling `halt` applet uses the same convention (`-f  Force (don't go through
init)`), and the mount applet's `-f` skips the `mount(2)` call entirely.
**[INFERRED]** for the semantics.

**The observation settles it regardless of the mechanism.** The live instrument:

```
/dev/root on / type ext4 (rw,relatime,errors=remount-ro,data=ordered)
```
**[READ]** `captures/arch-harvest/runtime-state.txt:174` — and mounts are
explicitly listed as uncontaminated evidence by
`captures/arch-harvest/CAVEAT-runtime-state.md`.

**Consequences:**

* The rootfs is exposed to corruption on every hard power-off. The kernel log
  confirms this is not theoretical: `EXT4-fs (mmcblk2p3): INFO: recovery
  required` **[READ]** `dmesg:272`.
* Anything running as root can modify the running rootfs. Relevant to any
  extension plan — though §8.4 still applies: an update boots the other slot and
  the modification is gone.
* Whether making the remount real would be *safe* is **[UNKNOWN]**: `S20urandom`
  writes `/etc/random-seed`, `S14fs` writes `/root/.ssh`, `S02sys` writes the
  stray `sched_rt_runtime_us`, and unknown consumers may write elsewhere. **Do
  not "fix" this without auditing every writer.**

### 9.2 `S99final`'s wait for `las-sc` is unbounded, and it gates its own rescue — **[READ]**

```sh
while true; do
        if [ -e /var/las-sc.cookie ]; then
                …
                (sleep 1; las-watchdog -t=10000 > /var/log/las-watchdog.log 2>&1) &
                break;
        fi;
        usleep 100000
done;
```
`S99final:20-28`. No counter, no timeout, no upper bound — in a script whose
sibling `S43gui` bounds **both** of its equivalent loops at 1000 iterations
**[READ]** `S43gui:37`, `:58`. The omission is not stylistic; it is the one loop
that was left open.

Two consequences:

1. **`rcS` never returns**, so busybox init never leaves `sysinit`, so the
   `console::respawn:/sbin/getty` entry never runs — **no serial console
   appears**. **[INFERRED]** from busybox init's ordering of `sysinit` before
   `respawn`.
2. **`las-watchdog` is started *inside* the loop.** The process whose entire
   purpose is to detect `SOUND ENGINE CONTROLLER IS DOWN!! PIDOF LAS-SC RETURNED`
   and restart it **[READ]** (`strings las-watchdog`) cannot start until `las-sc`
   has already succeeded. A `las-sc` that dies before dropping its cookie is
   unrecoverable without a power cycle.

Also note `S99final`'s three trailing statements — `killall xterm`,
`killall las-dwm`, the remount — are **after** the loop, so on a hang the xterms
and the window manager stay alive on screen. **[READ]** That is what a wedged
boot looks like from the front panel.

### 9.3 The RT throttle is never disabled — **[READ]**

`S02sys:8`: `echo 999950 > sched_rt_runtime_us`, no path. See §4, S02sys.
Corroborated by `sched: RT throttling activated` in the live kernel log.

This matters because `scsynth` runs `SCHED_FIFO 99` on the isolated cpu1. With
the throttle at its 950000/1000000 default, an RT task that saturates its
runqueue is descheduled for 50 ms in every second. Whether the audio engine ever
reaches that threshold is **[UNKNOWN]** — but `RT throttling activated` fired at
t ≈ 1049 s on a live instrument, so *something* did.

### 9.4 The cgroup configuration is inert — **[READ]**

See §4, S43gui. Four hierarchies mounted, three groups defined, zero processes
ever assigned. `cgexec`/`cgclassify` ship and are called by nothing.

### 9.5 No cron daemon — **[READ]**

See §4, S14fs. `crontab … -l` lists; `crond` is never started; the 03:00 log
rotation in `/etc/crontab/root` never fires.

### 9.6 `S99final`'s `chrt` calls pass the wrong argument — **[READ]**

A three-parameter function called with two arguments: `${3}` (the priority) is
empty in both `chrt` calls, and the second call passes the literal `93`/`80` as a
**PID**. **[READ]** `S99final:9-15`. No priority is set. See §4, S99final, and §13.

### 9.7 `S40network` deletes `S01logging`'s PID files — **[READ]**

`rm -rf /var/run/*.pid` at `S40network:16`. See §4, S40network.

### 9.8 `S14fs` deletes the running X server's lock file — **[READ]**

`rm -f /tmp/.X0-lock` at `S14fs:46`, after `S12splash:19` started X. See §4, S14fs.

### 9.9 Duplicate iptables DNAT rules — **[READ]**

Installed once by `eth-ext.sh`/`usb-ext.sh` from udev and again by `S95dhcpd`.
See §4, S10udev and S95dhcpd.

### 9.10 No exit status is ever checked in `rcS` — **[READ]**

See §3. Combined with `config-las-spi`'s `set -e` (which makes it exit silently
on a failed `devmem`) and `S25xmosfw`'s unchecked call, a failure to release the
XMOS from reset would be completely silent up to the point where `S99final` hangs.
**[INFERRED]**

---

## 10. Recovery paths and escape hatches

### 10.1 The developer key on a USB stick

Two scripts check for the same file, with identical code **[READ]**
`S50dropbear:29-32` and `S99final:31-33`:

```sh
if [ -e /media/thumbdrive/k ]; then
    keyval=`hexdump /media/thumbdrive/k | awk '{print $3 $2}'`
    if [ $keyval = 23051934 ]; then
```

`hexdump`'s default output is little-endian 16-bit words: `$2` is word 0, `$3` is
word 1. `$3$2` therefore requires word1 = `0x2305` and word0 = `0x1934`, i.e. the
file's first four bytes are **`34 19 05 23`**. **[READ] + [INFERRED]**
(hexdump output format). The concatenation reads `23051934` — **23 May 1934**,
Bob Moog's date of birth. `/media/thumbdrive` is the symlink `sort-part.sh`
points at the largest mounted USB partition (§4, S10udev).

With the key present:

* **`S50dropbear` starts SSH.** Without it, dropbear never runs at all.
* **`S99final` sleeps 3 s, kills `las-watchdog`, and `exit`s** — so the three
  xterms and `las-dwm` are **not** killed and the fake remount is skipped. You
  get a live desktop with terminals, and no watchdog interfering.

Note the log line both scripts write: `You have a key! Aren't you special!` into
`/var/log/messages`. **[READ]**

### 10.2 What SSH access actually costs — **[READ]**

Three facts compose:

1. `<R>/etc/shadow:1` is **`root::10933:0:99999:7:::`** — the password field is
   **empty**. **[READ]**
2. `<R>/etc/default/dropbear` is **`DROPBEAR_ARGS="-B "`** **[READ]**, and
   `S50dropbear:10` appends `-R`.
3. In `<R>/usr/sbin/dropbear`'s own server usage block, the options appear in the
   fixed order **[READ]**:

   ```
   Create hostkeys as required          (-R)
   Don't fork into background           (-F)
   Log to stderr rather than syslog     (-E)
   Don't display the motd on login      (-m)
   Disallow root logins                 (-w)
   Disable password logins              (-s)
   Disable password logins for root     (-g)
   Allow blank password logins          (-B)
   ```

   and the binary also carries the runtime messages
   `Auth succeeded with blank password for '%s' from %s` and
   `User '%s' has blank password, rejected`. **[READ]**

**So `-B` is "Allow blank password logins", root's password is blank, and the
only gate is a four-byte file on a USB stick.** **[INFERRED]** from the three
[READ] facts. Anyone on the same network as an instrument with that stick
inserted can `ssh root@…` with no password.

Compounding: `/etc/authorized_keys` does not exist, so `S14fs`'s key
provisioning is dead (§4, S14fs), leaving password auth as the sole mechanism.
And `-R` means **host keys are regenerated whenever `/etc/dropbear` is not
persistent** — `/etc/dropbear` is a symlink to `/var/run/dropbear`, which is a
**tmpfs** **[READ]** (`ls -la <R>/etc/dropbear`, `fstab:13`). `S50dropbear:17-26`
tries to replace the symlink with a real directory and, because root is writable
(§9.1), **succeeds** — so host keys land on the rootfs and do persist, until an
update replaces that slot. **[INFERRED]**

### 10.3 mDNS advertises SSH whether or not it is running — **[READ]**

`<R>/etc/avahi/services/ssh.service` and `sftp-ssh.service` advertise
`_ssh._tcp` and `_sftp-ssh._tcp` on port 22. `<R>/etc/avahi/avahi-daemon.conf`
sets `host-name=moog-one`, `allow-interfaces=ethext`, `enable-dbus=no`,
`enable-wide-area=yes`. **[READ]**

`S50avahi-daemon` runs unconditionally, so **an instrument on Ethernet
advertises `moog-one._ssh._tcp` even on boots where dropbear was never started.**
**[INFERRED]** Note also the hostname mismatch: `/etc/hostname` is
`las-production`, avahi publishes `moog-one`.

### 10.4 Service mode — `detect-held-buttons`

Started backgrounded by `S43gui:76`. Complete **[READ]**
`<R>/usr/bin/detect-held-buttons`:

```sh
while true; do
ping vc -c1 -q
if [ $? -eq 0 ]; then
        echo VC is up
        button_pressed=`las-frontpanel-poll /cb`
        echo Button pressed : $button_pressed
                if [ $button_pressed = 48 ]; then
                        echo HOME+SETTINGS pressed at startup, launching service mode.
                        sleep 5
                        killall las-watchdog
                        killall las-frontend
                        killall `pidof las-sc`
                        killall xterm
                        sleep 1
                        DISPLAY=:0 xterm -name xterm1 -fn 10x20 … -hold -e 'lassvc -t vc:7770 -p vc:9100' &
                        DISPLAY=:0 xdotool key "alt+2"
                fi;
        exit;
else
        echo VC not up yet
        sleep 1
fi;
done;
```

* **HOME + SETTINGS held at startup** → code **48** from `las-frontpanel-poll /cb`
  → everything is killed and `lassvc -t vc:7770 -p vc:9100` is launched in an
  xterm with `-hold`, and `las-dwm` is switched to workspace 2 via `xdotool`.
* The loop retries `ping vc` once per second until the XMOS answers — the only
  script in the whole boot that correctly handles the eleven-second XMOS gap (§7).
* It reads the button state **once** and then `exit`s, so this is genuinely a
  power-on-hold gesture, not a runtime hotkey.
* This runs **before** `S99final` kills the xterms — but `S99final` is blocked on
  the `las-sc` cookie meanwhile, and service mode kills `las-sc`. **If service
  mode is entered before `las-sc` has dropped its cookie, `S99final` waits
  forever** and the xterms survive by accident, which happens to be what service
  mode wants. **[INFERRED]** — a race whose two outcomes are both survivable.

### 10.5 `las-watchdog`

Started by `S99final:24` as `las-watchdog -t=10000`, one second after the
`las-sc` cookie appears, logging to `/var/log/las-watchdog.log` (which `S14fs:67`
rotates to `.log.0` at each boot). **[READ]**

It is a 15 KB C program that binds a UDP socket, speaks OSC to **203.0.113.2**,
and drives recovery by handing shell scripts to `system()`. Twelve `system()`
call sites **[READ]** (`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`);
eleven of them load a string constant whose address matches a script in
`.rodata`. Mapping call site → string, all **[READ]**:

| code addr | string addr | script |
|---|---|---|
| `0x122e8` | `0x2e34` | `kill -9 \`fuser 9799/udp\`` |
| `0x124a8` | `0x2e5c` | `S42sc stop` ; `killall scsynth sclang screen` ; `S43gui stop` ; `killall X` ; `sleep 2` |
| `0x124b4` | `0x2ed4` | `S42sc stop` ; `killall scsynth sclang screen` ; `S42sc start &` |
| `0x124c0` | `0x2f38` | `S43gui stop` ; `killall X` ; `S12splash start` ; `S43gui start &` ; `sleep 5` ; `killall las-dwm` ; `DISPLAY=:0 las-dwm &` |
| `0x1251c` | `0x2ff0` | `pidof las-frontend &> /dev/null` |
| `0x12570` | `0x3058` | `pidof las-sc &> /dev/null` |
| `0x125c4` | `0x30c0` | `pidof sclang &> /dev/null` |
| `0x12604` | `0x3118` | `pidof scsynth &> /dev/null` |
| `0x12664` | `0x3174` | `ping -c1 -W1 203.0.113.2` |
| `0x12754` | `0x31e8` | `config-las-spi som` ; `sleep 1` ; `config-las-spi xmos` ; `sleep 1` |
| `0x12794` | `0x324c` | `kill -9 \`fuser 9666/udp\`` |

and the diagnostic strings it prints **[READ]**:

```
FRONTEND IS DOWN!! PIDOF LAS-FRONTEND RETURNED : %d
SOUND ENGINE CONTROLLER IS DOWN!! PIDOF LAS-SC RETURNED : %d
SCLANG IS DOWN!! PIDOF SCLANG RETURNED : %d
SCSYNTH IS DOWN!! PIDOF LAS-SC RETURNED : %d
VC Ping %d returned : %d : failure count  = %d
-->!!SYS XMOS is down!!!
----> Cycling Sockets
LAS-WATCHDOG :  !!!VX %d IS DOWN!!!
LAS-WATCHDOG :  !!!VC IS DOWN!!!
LAS-WATCHDOG :  VC IS STILL UP BUT A VOICE IS DOWN
Expecting %d voices          Poll time of %d
LAS-WATCHDOG : VC REPORTING %d VOICES
LAS-WATCHDOG : VC ENUM ATTEMPT %d
LAS-WATCHDOG :  VX INIT PROCESS TIMEOUT!!
LAS-WATCHDOG : successful check up...
```

Notable:

* **The XMOS recovery is a proper long reset** — `config-las-spi som` asserts and
  *holds* `XMOS_RESET_N` low, `sleep 1`, then `config-las-spi xmos` releases it.
  That is a one-second reset assertion, versus `S25xmosfw`'s single call which
  relies on the line already being held low by `leds-gpio` since kernel probe
  (§7). Two different, both-correct mechanisms. **[READ] + [INFERRED]**
* It uses OSC addresses `/mode` (with argument `normal`), `/ping`, `/vx/`,
  `/v/voices`, `/status`, and ports **9799/udp** and **9666/udp** for socket
  recycling. **[READ]**
* `-t=10000` is parsed with `atoi` **[READ]** (two `atoi@plt` call sites at
  `0x129fc` and `0x12a40`); given the adjacent `Poll time of %d` string it is
  almost certainly a millisecond poll interval, i.e. 10 s. **[INFERRED]** —
  the argument-to-variable binding was not traced to certainty.
* `killall … screen` implies GNU `screen` is expected to be running at some
  point. `<R>/etc/screenrc` exists **[READ]**, but nothing in `init.d` starts
  `screen`. **[READ]** Presumably `lassvc` or manual use. **[UNKNOWN]**

### 10.6 The factory partition

`mmcblk2p1` is a bootable factory rootfs (§8.1). **How a user selects it is
[UNKNOWN]** — nothing in the rootfs writes `bootme = 1`, and `lasfwu`'s case
statement only *reads* the situation "currently booted from factory". The
selection must be a U-Boot behaviour, possibly a button combination or a
sentinel-failure fallback. **Not determined.**

---

## 11. Shutdown, `/sbin/reboot`, and the USB question

### 11.1 There is no USB gadget on the i.MX6

The brief asks what `/sbin/reboot` does that wedges the USB gadget. The honest
answer, from the device tree, is that **there is no gadget to wedge, and there
never was on this board.**

All four USB controller nodes in `<R>/boot/imx6dl-profili-som.dtb` carry
`dr_mode = "host"`. **[READ]**

| node | `dr_mode` | `status` | role |
|---|---|---|---|
| `usb@02184000` (OTG) | **`"host"`** | `okay` | `ci_hdrc.0` — front-panel USB-A, thumb drives |
| `usb@02184200` (H1) | `"host"` | `okay` | `ci_hdrc.1` — **the XMOS link** |
| `usb@02184400` (H2, HSIC) | `"host"` | `disabled` | — |
| `usb@02184600` (H3, HSIC) | `"host"` | `disabled` | — |

The OTG port is pinned to host mode in the device tree. dmesg agrees:
`ci_hdrc ci_hdrc.0: EHCI Host Controller` **[READ]** `dmesg:207`. There is no
`g_ether`, no `configfs` gadget, no `usb_gadget` reference anywhere in
`etc`, `bin`, `sbin`, `usr/bin` or `usr/sbin` — `grep -rl` returns only two
udev **hwdb** data files, which are vendor-ID tables. **[READ]**

**And it is worse than a configuration choice.** The OTG node's
`pinctrl-0 = <0x1f>` resolves to `usbotggrp-1`; `pwm@02080000`'s
`pinctrl-0 = <0x11>` resolves to `pwm1grp` **[READ]** (phandles resolved against
the DTB). They collide, and the PWM — the LCD backlight — wins:

```
imx6dl-pinctrl 20e0000.iomuxc: pin MX6DL_PAD_SD1_DAT3 already requested by 2080000.pwm; cannot claim for 2184000.usb
imx6dl-pinctrl 20e0000.iomuxc: pin-188 (2184000.usb) status -22
imx6dl-pinctrl 20e0000.iomuxc: could not request pin 188 (MX6DL_PAD_SD1_DAT3) from group usbotggrp-1  on device 20e0000.iomuxc
imx_usb 2184000.usb: Error applying setting, reverse things back
```
**[READ]** `dmesg-before-reboot.txt:203-206`.

So the OTG port comes up **without its pin group applied at all**, every boot,
permanently, on a conflict that lives in the device tree. `/sbin/reboot` cannot
clear it because there is no state to clear.

This is consistent with, and supplies the mechanism for,
`docs/CORRECTIONS-2026-09-08.md` §1: the i.MX6 is the host and the XMOS is the
device. It also means the rear USB-B "Moog One" port a computer sees is **the
XMOS's** USB device function, not Linux's.

### 11.2 What `/sbin/reboot` actually is, and what it does

`/sbin/reboot`, `/sbin/halt` and `/sbin/poweroff` are all symlinks to
`/bin/busybox` **[READ]** (`ls -la`). Stock busybox halt applet; its usage text
in this build is `[-d DELAY] [-n] [-f]` with `-n  Do not sync` and
`-f  Force (don't go through init)`. **[READ]** (`strings busybox`). There is no
Moog customisation.

**Nothing in the shipped system ever calls it.** §8.8 documents the exhaustive
grep. The only shutdown path a user has is the power switch.

Without `-f`, `reboot` signals PID 1 and busybox init runs the `::shutdown:`
entries **[INFERRED]** (standard busybox init):

```
/etc/init.d/rcK        # S99final, S95dhcpd, S80*, S50dropbear, S50avahi,
                       # S43gui, S42sc, S40network, S30dbus, S25xmosfw,
                       # S20urandom, S14fs, S12splash, S10udev, S05*, S02sys, S01logging
/sbin/swapoff -a
/bin/umount -a -r
```

What that sequence does **not** do, all **[READ]**:

* **`S25xmosfw stop` is empty.** The XMOS is never reset, never told anything,
  and keeps running while the i.MX6 disappears from under it.
* `S14fs`, `S02sys` and `S12splash` have empty `stop` cases too.
* `S01logging stop` cannot work, because `S40network` deleted its PID files
  (§9.7).
* `S95dhcpd stop` is empty — the four DNAT rules are never removed.

**What actually resets the XMOS on the way back up is not `rcK` and not
`S25xmosfw` alone — it is `leds-gpio` applying `default-state = "off"` at kernel
probe (§7), which drives `XMOS_RESET_N` low and holds it there for the first
eleven seconds.** `S25xmosfw` only *releases* it.

**Therefore the observable symptom [INFERRED]:** a host computer attached to the
rear USB-B port sees the "Moog One" device vanish the moment the i.MX6 resets,
and not return for roughly twelve seconds. A MIDI client that does not
re-enumerate on hot-unplug — which is most of them — will look wedged and stay
wedged until it is restarted or the port is re-opened. The instrument recovers on
its own; the host does not. That behaviour is caused by the XMOS reset window,
not by `/sbin/reboot`, and it is identical for a power-switch restart.

**Explicitly [UNKNOWN]:** whether the i.MX6's warm reset asserts an external
`WDOG_B` that also resets the XMOS. `wdog@020bc000` (WDOG1) is `status =
"disabled"` while `wdog@020c0000` (WDOG2) is `"okay"` and is what `imx2-wdt`
binds to; the GPC node carries `fsl,wdog-reset = <0x1>`, which selects WDOG1
**[READ]**. Resolving what that combination does to board-level reset needs the
kernel source for this tree and the carrier schematic, neither of which is here.

### 11.3 The shutdown is not clean, and the evidence is in the log

`EXT4-fs (mmcblk2p3)` needed journal recovery, `mmcblk2p6` had an orphan inode,
`mmcblk2p7` needed recovery, and `FAT-fs (mmcblk2p4)` — the A/B boot selector —
`was not properly unmounted`. **[READ]** `dmesg:272-286`.

Since no software shutdown path exists (§8.8), **every restart of this instrument
is a hard power-off**, and `/var/lib/sys` is dirty as a matter of routine. That
is the fragility flagged in §8.7.

---

## 12. v1.5.0 → v1.8.2: what changed in this region

**`diff -r` over `etc/init.d` reports exactly one changed file and one extra
file.** **[READ]**

The change is `S42sc:4`, the four XMOS firmware arguments:

```
- --vxfw=…/app_vx_10M_v2.1.0.bin  --vcfw=…/app_las_v2.1.2.bin --vcfv=33620735
+ --vxfw=…/app_vx_10M_v2.2.1.bin  --vcfw=…/app_las_v2.2.2.bin --vcfv=33686271
```

`inittab`, `fstab` and `boot/cmdline.txt` are **identical** between the two
versions. **[READ]** (`diff` reports no differences).

**So the entire init and service graph is unchanged from v1.5.0 to v1.8.2.**
Every defect in §9 has been shipping for at least three years.

**Warning about the 1.5.0 capture.** `captures/rootfs-1.5.0/etc/init.d/S99moogd`
is **this project's own addition**, not factory — its header says so
("the USB-hosted workbench … This is the only file added to the root
filesystem"), and `captures/arch-harvest/CAVEAT-runtime-state.md` records that
`S99moogd` "was present then and has since been removed". **[READ]** Do not cite
it as stock v1.5.0 content.

The 1.8.2 XMOS images were built in September 2025 —
`<R>/usr/share/xmosfw/app_las_gitinfo.json` records commit `d888eec9`,
2025-09-11, "Fix Local On/Off dumping held notes", and
`app_vx_gitinfo.json` records `02619910`, 2025-09-10, "Clamp min eg release",
both by Sylvan Williams at `gitlab.inmusicbrands.com/moog/hardware/moog-one/`.
**[READ]**

`<R>/etc/git-tags` **[READ]** gives the full component manifest:

```
LAS_FRONTEND 2.1.4   LAS_VX lasvx-v2.2.1   LAS_FW lasvc-v2.2.2   LAS_SC 1.1.0r2
LAS_FX v1.1.1r4      LAS_FWU v0.9.1        LAS_WATCHDOG v0.2.0   LAS_DWM v0.3.0
LAS_VX_DSP vxdsp-v1.0.0rc1                 LAS_BUILDROOT v1.8.2
```

(The file is not valid JSON — two entries lack a trailing comma. **[READ]**)

Base distribution: `Buildroot 2016.02-rc2` **[READ]** `<R>/etc/os-release`.
`<R>/etc/issue`: `L:A:S Production Image / (c)2017 Moog Music Inc.` **[READ]**

---

## 13. Conflicts with existing documentation

Reported, not fixed, per instruction.

1. **`docs/arch/hardware-external.md:450`** — "Root is **p2, ext4**". This
   owner's instrument boots `root=/dev/mmcblk2p3` **[READ]**
   `dmesg-before-reboot.txt:21`, `runtime-state.txt:2`. Neither statement is
   wrong for its own machine: the root partition is the **A/B slot last written
   by an update** and differs per unit and per update (§8.4). The doc states it
   as a fixed property of the hardware, which it is not.

2. **`docs/CORRECTIONS-2026-09-08.md` §8** records, as **[AGENT]**, "Display
   threads run `SCHED_FIFO` 93/80, above every threaded IRQ including
   `irq/26-esai`." The only code that sets 93 and 80 is `S99final:14-15`, and its
   `assign_ipu_pri` helper reads `${3}` while being called with two arguments
   (§9.6) — so as written those `chrt` invocations pass an empty priority and
   should fail. Either the observed 93/80 comes from somewhere else, or bash's
   handling of the empty argument differs from my reading. **Unresolved.** The
   observation and the script cannot both be straightforwardly true.

3. **Any documentation attributing the boot splash to `psplash`** is wrong.
   `psplash` and `psplash-write` ship at `<R>/usr/bin/` and are invoked by
   nothing; the splash is `S12splash`'s `fbset` + `dd` of `/boot/moog_splash.fb`
   onto `/dev/fb1`, faded in with `las-fb-config`. **[READ]** (§4, S12splash)

4. **`docs/arch/performance.md` §5.3** uses the v1.5.0 XMOS versions
   (`app_las_v2.1.2.bin`, `--vcfv=33620735`, `app_vx_10M_v2.1.0.bin`). For 1.8.2
   these are `app_las_v2.2.2.bin`, `--vcfv=33686271`, `app_vx_10M_v2.2.1.bin`.
   **[READ]** Not an error — the doc predates the 1.8.2 read — but the numbers
   are now stale. Its four-part decomposition of the ten minutes is corroborated
   here from the boot side (§8.8).

5. **Not a conflict, but a correction to a natural assumption:** `las-sc` binds
   `localhost:9300` **[READ]**, while the boot's own NAT rules route external
   UDP/9300 to the XMOS at 203.0.113.2 **[READ]**. Any document that describes
   port 9300 as "the way to reach `las-sc` from outside" needs checking against
   this. (§4, S10udev)

---

## 14. Validation plan

**READ-ONLY commands.** None writes, restarts, or reconfigures anything. Run
them over SSH with the developer key inserted, or in a service-mode xterm. They
are listed with the claim each one settles.

```sh
# --- 9.1  Is the root filesystem actually read-write? (the headline claim)
cat /proc/mounts | grep ' / '
#   expect:  /dev/root / ext4 rw,relatime,errors=remount-ro,data=ordered 0 0
#   "rw" confirms S99final's remount is a no-op.

# --- 9.3  Was the RT throttle ever disabled?
cat /proc/sys/kernel/sched_rt_runtime_us      # expect 950000, not 999950
ls -l /sched_rt_runtime_us                    # expect a real file containing 999950
cat /sched_rt_runtime_us

# --- 8.2 / 13.1  Which A/B slot is this instrument running?
cat /proc/cmdline

# --- 8.1  The partition map, including the unidentified p1 and p5
sgdisk -p /dev/mmcblk2
cat /proc/partitions

# --- 8.7  The A/B boot selector: does it say what lasfwu should have written?
ls -l  /var/lib/sys/
cat    /var/lib/sys/bootme
cat    /var/lib/sys/bootversion
hexdump -C /var/lib/sys/sentinelu1
hexdump -C /var/lib/sys/sentinelu2
hexdump -C /etc/versionb                      # expect: ff 02 08 01 00 00 00 00

# --- 8.6  Did the broken "falcon space" guard leave its stray file?
ls -l /60000 / | head -40
#   a file named 60000 in / (or wherever lasfwu last ran) confirms the redirection.

# --- 7 / 11.2  Is the XMOS reset line where this report says it is?
cat /sys/class/leds/XMOS_RESET_N/brightness   # expect 1 on a running system
ls  /sys/class/leds/

# --- 7  Confirm the eleven-second XMOS gap on THIS boot
dmesg | grep -E 'ci_hdrc|cdc_ether|renamed from|usb 2-1'

# --- 11.1  Confirm the OTG pinmux failure recurs every boot
dmesg | grep -E 'SD1_DAT3|usbotggrp|imx_usb|iomuxc'

# --- 11.3  Confirm the previous shutdown was unclean
dmesg | grep -E 'recovery|orphan|not properly unmounted'

# --- 9.4  Are the cgroups genuinely empty?
cat /cgroup/cpuset/dsp/tasks
cat /cgroup/cpuset/frontend/tasks
cat /cgroup/cpuset/sc/tasks
#   expect all three empty.

# --- 9.5  Is crond running?
ps | grep -c '[c]rond'                        # expect 0

# --- 9.7  Did S40network delete the logger PID files?
ls -l /var/run/*.pid

# --- 9.9  Are the DNAT rules installed twice?
iptables -t nat -L PREROUTING -n --line-numbers

# --- 9.6 / 13.2  What priority do the IPU threads really have?
ps -eo pid,cls,rtprio,comm 2>/dev/null | grep -Ei 'ipu|irq/' || \
  for p in $(pidof -x ' ' 2>/dev/null; ls /proc | grep '^[0-9]*$'); do \
    chrt -p $p 2>/dev/null | head -2; done | head -60

# --- 4/S42sc  Confirm las-sc binds loopback only
netstat -lnup 2>/dev/null | grep -E '9300|7775|9500'

# --- 6  Are the cookies gone, as this report claims (one-shot edges)?
ls -la /var/*.cookie /var/las-frontend/ 2>&1

# --- 10.5  What has the watchdog been doing?
tail -50 /var/log/las-watchdog.log

# --- 10.2  Confirm the blank root password and the dropbear flags
grep '^root:' /etc/shadow
cat /etc/default/dropbear
ls -la /etc/dropbear /var/run/dropbear 2>&1

# --- 8.8  Confirm the XMOS versions the running system expects vs has
cat /usr/share/xmosfw/VERSIOND
cat /etc/git-tags
```

One optional, still read-only, check that would settle §8.7's most important
open question — **it reads the FAT partition, writes nothing:**

```sh
dosfsck -n /dev/mmcblk2p4        # -n = no-write check. Verify the flag on THIS
                                 # busybox/dosfstools build before running it.
```

Do **not** run `lasfwu` in any mode, including `--dry-run`: the dry-run path
still `dd`s to a destination (`lasfwu:172-174`), and `search`/`verify` import and
delete GPG keys (`lasfwu:49-51`, `:527`).

---

## 15. Unexplored

Named honestly, so the next pass knows where the edges are.

1. **U-Boot.** Not in the rootfs. Everything about how `bootme` and the sentinels
   are consumed, how the factory partition is selected, whether a button
   combination reaches the bootloader, and where `root=` comes from, is
   reconstruction from the writer's side only. This is the largest hole in the
   A/B story.
2. **`mmcblk2p1` and `mmcblk2p5`.** p1 is called "factory" by `lasfwu`; p5 is
   entirely unidentified. No GPT dump was available.
3. **`las-sc`'s Scheme internals.** I extracted frame names and literals from
   `sc/sc.scm` and `vxfw-lib.scm` but did not disassemble the CHICKEN-compiled
   logic. The exact XMOS reflash sequencing, the retry policy, and the
   `startup-dispatch` wire protocol are inferred from names, not traced.
4. **The startup-coordination message format.** `--panel-state=localhost:9500` is
   the presumed channel; not confirmed.
5. **`las-frontend`.** 145 MB. I read only its option help, its `StartupPanel`
   strings, and its exec targets. Its cookie-writing and firmware-update UI paths
   were not traced.
6. **`lassvc`, `vxtune`, `las-frontpanel-poll`, `las-dwm`.** Only touched where
   the boot scripts call them. `las-frontpanel-poll /cb` returning `48` for
   HOME+SETTINGS is taken from `detect-held-buttons`; the encoding of other
   button combinations was not derived.
7. **`las-watchdog`'s state machine.** I mapped its `system()` sites and its
   diagnostic strings but did not trace the failure counters, the ordering of
   checks, the voice-count logic, or what `-t=10000` binds to.
8. **`flashrom` behaviour** when the image (2,097,152 B) exceeds the layout region
   (0x1C0000 = 1,835,008 B).
9. **Whether the i.MX6 warm reset asserts an external `WDOG_B`** that also resets
   the XMOS (§11.2). Needs kernel source and schematic.
10. **`/etc/bob.bmp` steganography** — the mechanism is recorded in
    `docs/CORRECTIONS-2026-09-08.md` §6 and I confirmed `lasfwu` calls
    `str /etc/bob.bmp 4`; I did not re-derive it.
11. **The GPT `FWU` label check** at `lasfwu:456` — whether partition 7 actually
    carries that label on this instrument, which decides whether staging uses
    `/mnt/fwu` (800 MB, tight) or `/var` (3.3 GB). `docs/arch/performance.md`
    §5.2 puts the margin at 12.19 MiB; that number depends on this.
12. **Actual boot timing on the current firmware.** Every duration here except
    the dmesg timestamps is derived from script structure, and those timestamps
    came from a v1.5.0-era boot.
