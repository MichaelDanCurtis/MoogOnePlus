# Moog One — system, boot sequence and failure modes

Companion to `docs/MOOG-ONE-INTERNALS.md`. That document maps the *protocol*; this
one maps the *machine underneath it* and the ways it breaks. It extends §2a, §8b-bis,
§8c, §8d and §10 rather than repeating them, and corrects four claims made there.

**Nothing here was learned by touching the instrument.** Every statement is derived
from files already on this workstation:

| Source | Path |
|---|---|
| Init scripts (complete set) | `captures/arch-harvest/init.d/` |
| System config | `captures/arch-harvest/{inittab,fstab,crontab/,asound.conf}` |
| Live snapshot | `captures/arch-harvest/runtime-state.txt` |
| Kernel log, cold boot | `captures/dmesg-before-reboot.txt` |
| Binaries (ARM ELF, read with `strings`) | `captures/arch-harvest/las-{watchdog,fb-config,frontpanel-poll,sc,dwm,frontend}` |
| Earlier harvests | `captures/harvest/`, `captures/sysmap/`, `captures/moog-recon/` |

Claims are marked **[READ]** when a cited file says it directly, and **[INFERRED]**
when it is a conclusion drawn from those files. Every inference names its evidence.

Two files the brief expected are **not in the capture set**: `mdev.conf` and
`/etc/network/interfaces`. `mdev.conf` is very likely a red herring — this device does
not use mdev. `init.d/S10udev:20-35` starts `udevd`, and `S10udev:31` writes four NUL
bytes to `/proc/sys/kernel/hotplug`, which disables the kernel's hotplug-helper path
entirely. udev is the hotplug manager. See "Gaps" at the end for the rest.

---

## 1. The boot sequence

### 1.0 Before userspace

**[READ]** `captures/dmesg-before-reboot.txt`:

| line | fact |
|---|---|
| 5 | `Linux 4.1.15-rt18 #1 SMP PREEMPT RT`, Buildroot 2016.02-rc2, built 2022-05-16 |
| 8 | Variscite i.MX6 DL/Solo SOM on a Moog "SoloCustomBoard" |
| 21 | cmdline as documented in §"isolcpus" of INTERNALS — confirmed verbatim |
| 25 | 179 MB of 512 MB available to the kernel; **320 MB is a CMA pool** for GPU/IPU |
| 223 | `imx2-wdt 20c0000.wdog: timeout 60 sec (nowayout=0)` — **a hardware watchdog exists** |
| 245 | `mmcblk2: p1 p2 p3 p4 p5 p6 p7`, a 7.21 GiB eMMC |
| 267 | `rtc-pcf85063` sets the system clock — there *is* a working battery RTC |
| 270-279 | root ext4 journal replayed, mounted RO, then re-mounted `errors=remount-ro,data=ordered` |
| 286 | `FAT-fs (mmcblk2p4): Volume was not properly unmounted` — routine unclean shutdown |
| 301-305 | at **t=11.9 s** the internal USB gadget enumerates; `usbint` and `ethext` both appear as `cdc_ether` interfaces of the *same* device `2-1` |
| 306-329 | at **t=45.3 s** ESAI/audio starts — this is `scsynth` opening the PCM |
| 330 | at **t=1049 s**, `sched: RT throttling activated` — see failure mode **F-11** |

Boot-to-sound is therefore about **46 seconds** from power-on.

Line 301-305 is the direct confirmation of §8c's central claim, from the kernel itself:
`usbint` (the voice-controller link) and `ethext` (the LAN) are two `cdc_ether`
functions of one USB device. There is no separate Ethernet MAC in play.

Harmless-but-alarming kernel noise, so it is not misread later as a fault:
`gpmi-nand ... -19` (line 155, no NAND fitted), the `spidev_probe` WARNING backtrace
(156-187, a device-tree style complaint), `pin MX6DL_PAD_SD1_DAT3 already requested`
(203-206, USB OTG pinmux collides with PWM — the port still works as host),
`rtc-ds1307 ... -5` (218, wrong RTC probed; the pcf85063 at line 219 is the real one),
and `imx6q-pcie ... phy link never came up` (263-265, no PCIe fitted).

### 1.1 `init` — `captures/arch-harvest/inittab`

BusyBox init. `sysinit` entries run **in order, each to completion**, before any
`respawn` entry starts.

```
inittab:17   mount -t proc proc /proc
inittab:18   mount -o remount,rw /          <- root becomes writable here
inittab:19   mkdir -p /dev/pts
inittab:20   mkdir -p /dev/shm
inittab:21   mount -a                       <- everything in fstab
inittab:22   hostname -F /etc/hostname
inittab:24   /etc/init.d/rcS                <- the whole boot
inittab:27   console::respawn:/sbin/getty -L console 0 vt100
inittab:33-35 shutdown: rcK, swapoff -a, umount -a -r
```

**[INFERRED] The serial-console getty does not exist until `rcS` returns.** `inittab:27`
is a `respawn` action, and BusyBox init starts respawn entries only after all `sysinit`
entries have finished. `rcS` ends in `S99final`, which contains an *unbounded* wait
(§F-02). So the one out-of-band way into the machine is unavailable during precisely
the failure it would be most wanted for. Evidence: `inittab:24` and `inittab:27`
ordering plus BusyBox init's documented action semantics.

`inittab:30` (`ctrlaltdel`) is commented out.

### 1.2 `rcS` — `captures/arch-harvest/init.d/rcS`

```
rcS:7    for i in /etc/init.d/S??* ; do
rcS:10       [ ! -f "$i" ] && continue
rcS:13-20    *.sh)  sourced in a subshell
rcS:23       *)     $i start   (forked, return value ignored)
```

**[READ]** Return values are discarded. No script can fail the boot by exiting
non-zero — only by *not returning*. That single property is why §2 below is organised
around "can it hang" rather than "can it fail".

Glob order is lexicographic, so the real order is:

`S01logging → S02sys → S05avahi-setup.sh → S10udev → S12splash → S14fs → S20urandom →
S25xmosfw → S30dbus → S40network → S42sc → S43gui → S50avahi-daemon → S50dropbear →
S80dhcp-relay → S80dhcp-server → S95dhcpd → S99final → S99moogd`

Note `S99final` sorts **before** `S99moogd`.

### 1.3 Script by script

Every script below was read in full. "Hang" means it can block `rcS` indefinitely.

---

**`S01logging`** — `start-stop-daemon -b` launches `syslogd -n` and `klogd -n`
(`S01logging:8-9`). Backgrounded. Cannot hang, cannot fail meaningfully.
*Depends on:* nothing. *Failure:* no logs. Non-fatal.

---

**`S02sys`** — the realtime and clock setup, and it contains a bug.

```
S02sys:6   echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
S02sys:7   echo 0 > /proc/sys/vm/swappiness
S02sys:8   echo 999950 > sched_rt_runtime_us          <-- BUG: relative path
S02sys:10  echo 0 > /sys/class/backlight/backlight/brightness
S02sys:14-27 clock offset from /var/clock_offset, date -s, hwclock -w
```

**[INFERRED, high confidence] Line 8 writes to the wrong place and the RT throttle is
never lifted.** The intended target is `/proc/sys/kernel/sched_rt_runtime_us`. With no
directory component the redirect creates a *file* named `sched_rt_runtime_us` in the
script's working directory — `/`, since BusyBox init runs with cwd `/` and `inittab:18`
has just made root writable. The kernel value therefore stays at its 950000 µs default,
i.e. RT tasks are throttled at 95 % of each period. The corroborating evidence is
`dmesg` line 330: `sched: RT throttling activated`. See **F-11**.

*Depends on:* `/var` mounted (for `clock_offset`), `bc`, `hwclock`.
*Failure:* wrong wall clock; RT throttle left on. Non-fatal, but audibly consequential.

---

**`S05avahi-setup.sh`** — creates `/tmp/avahi-autoipd` (`S05avahi-setup.sh:5-9`).
The only `.sh` script, so `rcS:15-19` *sources* it in a subshell. Cannot hang.

---

**`S10udev`** — hotplug.

```
S10udev:21  test -x /sbin/udevd || exit 5
S10udev:25  test -r /etc/udev/udev.conf || exit 6
S10udev:31  printf '\000\000\000\000' > /proc/sys/kernel/hotplug
S10udev:32  udevd -d
S10udev:33-34 udevadm trigger --type=subsystems / --type=devices --action=add
S10udev:35  udevadm settle --timeout=30 || echo "udevadm settle failed"
```

Bounded at 30 s (`:35`), and the `||` makes even a timeout non-fatal. This is the
script that runs `/etc/udev/rules.d/usb-int.sh` for the `02:00:00:00:00:00` NIC
(rule quoted in `captures/harvest/03-system-deep.txt`), creating `usbint` and its
static ARP entry. *Load-bearing.* Without it there is no voice controller.

---

**`S12splash`** — framebuffer, X server, splash image.

```
S12splash:9   las-fb-config 1 0                 (fb1 alpha -> 0)
S12splash:11-12 unblank fb0 and fb1
S12splash:14-16 fbset fb1 to 832x480, then set mode "U:832x480p-40"
S12splash:18-19 rm -f /tmp/.X0-lock ; X :0 -nocursor -s 0 &
S12splash:21  dd if=/boot/moog_splash.fb of=/dev/fb1
S12splash:23  brightness -> 99
S12splash:25-27 for i in $(seq 255 $END): las-fb-config 1 $i ; usleep 1000
```

`las-fb-config` is 3.8 KB and does exactly one thing: **[READ]** its strings are
`Usage: %s framebuffer [0,1] [ alpha_val[0-255] ]`, `/dev/fb%s`, and a single `ioctl`
import. It sets the global alpha of a framebuffer overlay. Nothing else.

**[READ]** `$END` at `:25` is never assigned, so the loop is `seq 255` = 1..255 — a
255 ms fade-in. Harmless, but it is an unset variable, not a range.

*Depends on:* `/boot/moog_splash.fb` on the rootfs, `X`, `fbset`.
*Failure:* if `X` fails to start, `S43gui` cannot map `las-frontend` and the screen
stays dark. `S43gui`'s cookie waits are bounded, so it degrades rather than hangs.

---

**`S14fs`** — filesystem hygiene, and two more bugs.

```
S14fs:6-8    mkdir -p /var/empty
S14fs:10-25  a block of `ln -sf` calls with target and linkname transposed
S14fs:28-36  mkdir /var/local/{media,gnupg} + more transposed symlinks
S14fs:38-42  mkdir -p /root/.ssh ; cp /etc/authorized_keys /root/.ssh ; sync
S14fs:45-48  rm -rf /tmp/* ; rm -f /tmp/.X0-lock ; rm -rf /var/local/tmp/*
S14fs:51     rm -rf /mnt/fwu/*                 <-- firmware staging wiped every boot
S14fs:54-55  rm -rf /var/*.cookie ; rm /var/las-frontend/las-frontend.cookie
S14fs:58     /etc/log-refresh
S14fs:61     crontab -c /etc/crontab -l        <-- BUG: lists, does not start
S14fs:64     rm -rf /var/log/*.0.*
S14fs:67     mv /var/log/las-watchdog.log /var/log/las-watchdog.log.0
S14fs:70     rm -rf /var/log/phonehome*
```

**[READ] `S14fs:38-40` is where SSH authorised keys come from**, copied from
`/etc/authorized_keys` into `/root/.ssh` — but *only if `/root/.ssh` does not already
exist*. Once created it is never refreshed.

**[INFERRED] `S14fs:61` does not start cron.** `crontab -l` lists a crontab; it does not
launch `crond`. Corroborated by `runtime-state.txt:4-126` — there is **no `crond` in the
process table**. The crontab itself (`captures/arch-harvest/crontab/root`) contains one
line, `0 3 * * * /etc/log-refresh`, which therefore never runs. Log rotation happens
once per boot at `S14fs:58` and never again. See **F-12**.

**[INFERRED] The `ln -sf` block at `:10-36` is inert or backwards.** `ln -sf /srv
/var/local/srv` creates `/var/local/srv` pointing at `/srv`, guarded by `[ ! -e /srv ]`
— i.e. it only fires when the target does not exist, producing a dangling link. The
intent was plainly the reverse (put the writable copy on `/var`, link it into `/`).
It is harmless because the guards fail on a normal image, but do not rely on any of
these paths existing.

*Failure:* `S14fs` cannot hang. Its most consequential act is `:51`, which makes
`/mnt/fwu` (861 MB, `mmcblk2p7`) useless as persistent storage — see §5.

---

**`S20urandom`** — restores the entropy seed. **[READ]** `S20urandom:15-19` probes for a
read-only root by trying to `touch /etc/random-seed`, and exits quietly if it fails.
That is the only script that tests root writability. Cannot hang.

---

**`S25xmosfw`** — one line that matters.

```
S25xmosfw:7   test -r /etc/default/dropbear && . /etc/default/dropbear   <- copy-paste
S25xmosfw:11  config-las-spi xmos
```

`config-las-spi` (full source in `captures/harvest/03-system-deep.txt`) rewrites four
IOMUXC registers with `devmem` so the SPI1 pins become GPIO inputs and the XMOS owns
the flash bus, then pulses `/sys/class/leds/XMOS_RESET_N/brightness` 0 then 1.

**[INFERRED] `config-las-spi` is dangerous when `devmem` is not on `PATH`.** In
`captures/harvest/04-tools.txt` an invocation produced
`/usr/bin/config-las-spi: line 57: devmem: not found` and then still printed
`XMOS network cycled`. The reset pulse is a `sysfs` write and needs no external binary;
the pin remux does. **Resetting the XMOS without handing it the SPI bus releases it into
a flash it cannot read.** That is a plausible mechanism for the documented `open_ladder`
damage (`/v/voices` returning `-1`, INTERNALS §"`--help` is not safe"). Always invoke it
with a full `PATH`, or not at all.

*Load-bearing.* Without it the XMOS never boots. *Failure:* silent — the script returns
0 regardless, and the symptom appears 15-45 s later as a dead voice engine.

---

**`S30dbus`** — `dbus-uuidgen --ensure` then `dbus-daemon --system` (`S30dbus:26-27`).
Note `dbus-daemon --system` **is not backgrounded** and no `&` is present; it daemonises
itself. Confirmed alive as PID 793 in `runtime-state.txt:101`. Cannot hang in practice.

---

**`S40network`**

```
S40network:7    mkdir -p /run/network
S40network:12   /sbin/ifdown -a
S40network:13   /sbin/ifup -a &            <- "so dhcp doesn't hold up startup"
S40network:15-16 rm -rf /var/run/avahi-daemon/pid ; rm -rf /var/run/*.pid
S40network:17   echo 1 > /proc/sys/net/ipv4/ip_forward
```

**[INFERRED] `S40network` races the USB gadget and usually loses.** dmesg line 301 puts
the gadget's enumeration at t=11.9 s; `S40network` runs several scripts before
`S42sc`, which itself is running by the time `runtime-state` was taken. `ifup -a` is
backgrounded at `:13` precisely so the race is survivable. The consequence is that
`ethext` is configured by whichever of two DHCP clients wins — see **F-08**.

`:16` deleting *all* of `/var/run/*.pid` is a blunt instrument; `/var/run` is a tmpfs
(`fstab:13`) so it is empty on a cold boot anyway.

---

**`S42sc`** — the audio stack. The single most important script on the machine.

```
S42sc:4    /usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300
             --vxfw=/usr/share/xmosfw/app_vx_10M_v2.1.0.bin
             --vxdb=/var/tuning.vxtune
             --vcfw=/usr/share/xmosfw/app_las_v2.1.2.bin --vcfv=33620735
             --temp --expr-syms=/usr/share/vx_ee.scm
             --panel-state=localhost:9500 $1
S42sc:23-24 runsc -q & ; sleep 3
S42sc:28-32 stop: killall sclang ; killall jackd ; killall scsynth ; killall las-sc ;
            kill -9 `pidof jackd`
S42sc:46-49 a fourth verb, `nobg`: stop, then run las-sc in the foreground
```

### Correction to `MOOG-ONE-INTERNALS.md`

INTERNALS §"Scope and cautions" states that `S42sc` has an asymmetric stop/start —
that `stop()` kills four processes and `start()` relaunches only `las-sc`, leaving
"a running control layer with no audio engine behind it". **That is wrong, and this is
why the field experience contradicts it.**

**[READ]** `las-sc` contains the literal string
`,screen -d -m /usr/share/las-fx/launch-sc-1 &`
(`strings las-sc`, match #1294). It also carries `Creating cookie` / `/las-sc.cookie` /
`Couldn't create cookie` (#1149-1151). **`las-sc` spawns the SuperCollider stack
itself.** `launch-sc-1` then runs `sclang init_sc_1.scd`, which boots `scsynth`. The
process tree in `runtime-state.txt:112-115` shows exactly that chain:

```
1212 {screen} SCREEN -d -m /usr/share/las-fx/launch-sc-1
1214 {launch-sc-1} /bin/bash /usr/share/las-fx/launch-sc-1
1257 sclang -a -l sclang_config.yaml init_sc_1.scd
1294 scsynth -u 57110 -a 129 -i 9 -b 1026 -z 256 -Z 256 -m 100000 -w 128 -S 48000 -R 0 -C 0 -l 1
```

Starting `las-sc` starts everything. `S42sc restart` is symmetric in effect, which is
consistent with the observed record of it recovering cleanly every time. The INTERNALS
caution should be replaced with: *`S42sc restart` is the supported recovery and it works;
the loaded patch is lost and it takes about 45 seconds.*

Two things worth carrying forward from that argv:

* `scsynth -l 1` — **[READ]** maximum logins is one. A second OSC client that issues
  `/notify` may be refused a client ID. Commands without `/notify` are unaffected.
* `-z 256 -Z 256` on the running server, while the harvested
  `captures/arch-harvest/init_sc_1.scd:9-10` says `blockSize = 128`. The file and the
  running process disagree, which means `init_sc_1.scd` **has been edited on the device
  since the running `scsynth` was launched**. That file lives on the root filesystem.
  See §5.

*Depends on:* `S25xmosfw` having booted the XMOS; `/var/tuning.vxtune`; `/var/cal`.
*Failure:* `runsc` is backgrounded and followed by a fixed `sleep 3`, so `S42sc` itself
cannot hang — but `S99final` waits on the cookie `las-sc` drops, so a failure here
hangs the *boot* (**F-02**).

---

**`S43gui`** — X clients, the JUCE frontend, the window manager.

```
S43gui:8     cgconfigparser -l /etc/cgconfig.conf
S43gui:11-13 three xterms on DISPLAY=:0
S43gui:16-18 mkdir /var/las-frontend if missing
S43gui:21    las-frontend --usb-path=/media/thumbdrive --data-path=/var/las-frontend
               --host-paneloutput=203.0.113.2 --host-performance=vc
               --host-oleds=203.0.113.2 --affinity-mask=1 --host-systemclock=vc
               --cookie=1 --affinity-panel=1 --startup-coordination --host-vc=vc &
S43gui:26-41 wait for /var/las-frontend/las-frontend.cookie, timeout 1000 x 100 ms
S43gui:46    las-dwm &
S43gui:49-62 wait for /var/las-dwm.cookie, same bounded loop
S43gui:65    save brightness to /var/lcd_brightness
S43gui:68-69 brightness 0, alpha 0
S43gui:72-73 xrandr -o inverted ; usleep 1000000
S43gui:76    /usr/bin/detect-held-buttons &
S43gui:78    restore brightness
S43gui:81    echo "U:10x10p-40" > /sys/class/graphics/fb1/mode   (shrink fb1)
```

**[READ] Both cookie waits are bounded** at 1000 iterations of 100 ms = 100 s each, and
both `break` on timeout with a message rather than looping. Worst case `S43gui` adds
**200 seconds** to the boot and then continues. It cannot hang.

`--host-vc=vc`, `--host-performance=vc`, `--host-systemclock=vc` resolve `vc` by
`/etc/hosts`; `--host-oleds` and `--host-paneloutput` are the literal `203.0.113.2`.
**Everything the panel and screen need is on the far side of the USB gadget.** This is
why an OLED reduced to a single line is the signature of a wedged gadget (INTERNALS
§8b-bis) rather than a display fault.

`S43gui:76` starts `detect-held-buttons`, which INTERNALS records as a bash script that
loops forever — it is *meant* to, it is the held-button hotkey watcher, and it is
backgrounded here. Do not run it by hand.

---

**`S50avahi-daemon`** — `$DAEMON -c || $DAEMON -D` (`S50avahi-daemon:8`). This is what
publishes `moog-one.local`. Cannot hang.

---

**`S50dropbear`** — SSH, gated.

```
S50dropbear:17-27 fix up /etc/dropbear if it is a symlink into /var/run
S50dropbear:29    if [ -e /media/thumbdrive/k ]; then
S50dropbear:30      keyval=`hexdump /media/thumbdrive/k | awk '{print $3 $2}'`
S50dropbear:32      if [ $keyval = 23051934 ]; then
S50dropbear:34        log to /var/log/messages
S50dropbear:36-37     start-stop-daemon --exec /usr/sbin/dropbear -- $DROPBEAR_ARGS
S50dropbear:40        exit
```

**[READ]** The gate is the first four bytes of `/media/thumbdrive/k` read as two
byte-swapped 16-bit words. No key file, no `sshd`. `DROPBEAR_ARGS` gains `-R`
(`:10`), which regenerates host keys on demand — so the host key fingerprint can change
if `/etc/dropbear` is ever lost.

---

**`S80dhcp-relay`** and **`S80dhcp-server`** — both **[READ]** no-ops on this image.
`S80dhcp-relay:22-23` exits 0 because `INTERFACES` and `SERVERS` are empty;
`S80dhcp-server:21-22` exits 0 unless `/usr/sbin/dhcpd` *and* `/etc/dhcp/dhcpd.conf`
both exist. `dhcpd` is present in `/usr/sbin` per `captures/harvest/04-tools.txt`, so
whether this one fires depends on a config file that is not in the capture set.

---

**`S95dhcpd`** — despite the name, this is the DHCP *client* plus the NAT rules.

```
S95dhcpd:9     /sbin/dhcpcd start ethext &
S95dhcpd:11-14 iptables -t nat -A PREROUTING -i ethext -p udp --dport {7770,7771,9100,9300}
                 -j DNAT --to 203.0.113.2:{same}
```

**[READ] Four UDP ports arriving from the LAN are forwarded straight to the XMOS voice
controller.** Combined with `S40network:17` enabling `ip_forward`, this means anything
on the local network can send UDP to `<instrument>:7770` and have it delivered to the
gadget. This is the exposed edge of the §8c microburst wedge. See **F-05**.

`restart` and `stop` are both no-ops (`S95dhcpd:21-24`), so the rules are never removed —
but running `S95dhcpd start` twice would append duplicate rules.

---

**`S99final`** — priorities, the watchdog, and the read-only remount.

```
S99final:6-7   iputasks=`ps | grep ipu | awk '{print $1} NR==2{exit}'`
               ipuirq=`ps | grep 2400000 | awk '{print $1} NR==2{exit}'`
S99final:9-12  assign_ipu_pri() { chrt -f -p "${3}" "${1}" ; chrt -f -p "${3}" "${2}" ; }
S99final:14-15 assign_ipu_pri $iputasks 93 ; assign_ipu_pri $ipuirq 80
S99final:17    devmem 0x020e0018 w 0xffffffff          <- IOMUXC_GPR6, IPU1 AXI QoS
S99final:20-28 while true: wait for /var/las-sc.cookie   <-- UNBOUNDED
S99final:24      (sleep 1; las-watchdog -t=10000 > /var/log/las-watchdog.log 2>&1) &
S99final:31-39 if /media/thumbdrive/k has the magic: sleep 3 ; killall las-watchdog ; exit
S99final:42-44 else: killall xterm ; killall las-dwm ; mount -f -o remount,ro /
```

Three findings here, in ascending order of importance.

**[INFERRED] `assign_ipu_pri` works only by accident.** The function reads `${1}`,
`${2}` and `${3}` but is called with two arguments. It survives because
`awk '{print $1} NR==2{exit}'` emits *two* PIDs, which word-split into `$1` and `$2`,
making the literal `93` land in `$3`. Confirmed by `runtime-state.txt:38-41`, which
shows exactly two `[ipu1_task]` and two `[irq/29x-2400000]` kernel threads. If either
`ps | grep` ever returns one line, `chrt` is handed a PID as a priority and the IPU
threads keep default priority — display tearing and IPU overruns, silently.

**[READ] The wait at `:20-28` has no timeout.** If `las-sc` never writes
`/var/las-sc.cookie`, `S99final` loops forever, `rcS` never returns, `S99moogd` never
runs, and — per §1.1 — **the serial-console getty never starts**. This is the one true
boot hang on the machine. See **F-02**.

**[READ, and this is the headline] The USB key disables the instrument's own watchdog.**
`S99final:24` starts `las-watchdog`; `S99final:36` kills it thirty-odd lines later if
`/media/thumbdrive/k` is present. Corroborated by `runtime-state.txt` — the process table
contains **no `las-watchdog`**. Every automatic recovery described in §3 is switched off
on this instrument right now, because the SSH key is installed. See **F-01**.

**[INFERRED, needs one check] The read-only remount at `:44` is probably fake.**
`mount -f` means *fake* — in both BusyBox and util-linux it performs everything except
the `mount(2)` call. If that reading is right, the root filesystem stays read-write for
the entire life of a stock boot, and the instrument has no protection against a
power-cut corrupting `/`. The available captures cannot settle it, because every capture
was taken with the key installed and therefore with `:44` never reached — `runtime-state.txt:174`
shows `/dev/root ... (rw,...)` for that reason, not necessarily this one. See **F-10**
for the one safe test.

---

**`S99moogd`** — locally added; not Moog's. Read in full; it is well built.

```
S99moogd:21-24 MARK=/media/thumbdrive/moogd.autostart, BIN, UI, LOG=/var/log/moogd.log
S99moogd:28-30 pids() matches the full path "[/]media/thumbdrive/moogd"
S99moogd:35-62 double-backgrounded; bounded 30 x 1 s wait for the marker and binary
S99moogd:48-49 no marker or non-executable binary -> exit 0
S99moogd:55-57 refuses to start a second instance
S99moogd:60    truncates the log rather than appending
S99moogd:61    taskset -c 0 "$BIN" -addr :8080 -ui "$UI" >> "$LOG" 2>&1 &
S99moogd:82    exit 0 unconditionally
```

It cannot hang (`:35`/`:62` double background, `:39` bounded loop) and cannot fail the
boot (`:82`). It runs after `S99final`, so it inherits whatever `S99final` did.

**One inconsistency worth resolving.** `S99moogd:61` pins to **cpu0**, and the header
comment at `S99moogd:16-18` says the opposite — "It runs on cpu1, which `isolcpus=1`
reserves". The code is right and the comment is wrong: cpu1 is where `scsynth`'s audio
thread sits at `SCHED_FIFO` 99, and it is the last place a Go HTTP server belongs.
But `usb/README.md` records a cold-boot test showing `affinity=2 last-cpu=1` — mask
`0x2` is **cpu1**. That output cannot have come from the `taskset -c 0` in the current
file. Either the README records an older build, or the deployed copy differs from the
repo copy. `runtime-state.txt:123` shows the process but `ps` cannot show affinity.
**Verify with `grep Cpus_allowed_list /proc/$(pidof moogd)/status`** before trusting
either. See **F-13**.

---

## 2. Where the boot can stop, in one table

| # | Script:line | Bounded? | If it never completes |
|---|---|---|---|
| 1 | `S10udev:35` `udevadm settle` | 30 s, `||` guarded | continues |
| 2 | `S42sc:24` `sleep 3` | fixed | continues |
| 3 | `S43gui:26-41` frontend cookie | 100 s | continues, no UI |
| 4 | `S43gui:49-62` dwm cookie | 100 s | continues, unmanaged window |
| 5 | `S99final:20-28` las-sc cookie | **none** | **boot hangs; no getty; `S99moogd` never runs** |
| 6 | `S99moogd:39-45` USB marker | 30 s | continues |

Row 5 is the only unbounded wait in the entire boot.

---

## 3. Service map

Every long-running process in `runtime-state.txt`, what starts it, and what brings
it back.

| Process | Started by | Restarted by | If it stays dead |
|---|---|---|---|
| `syslogd`, `klogd` | `S01logging:8-9` | nothing | no logs |
| `udevd` | `S10udev:32` | nothing | no hotplug; a replugged USB drive is not mounted |
| `X :0` | `S12splash:19` | `las-watchdog` (GUI script) | no screen |
| `dbus-daemon --system` | `S30dbus:27` | nothing | JUCE/X plumbing degraded |
| `udhcpc -i ethext` | `S40network:13` via `ifup -a` | ifupdown | primary LAN address lost |
| `dhcpcd start ethext` | `S95dhcpd:9` | nothing | **secondary** LAN address lost |
| `las-sc` | `S42sc:23` | `las-watchdog` | no voice engine, no firmware upload, no FX chain |
| `screen`→`launch-sc-1`→`sclang` | **`las-sc` itself** (string `screen -d -m /usr/share/las-fx/launch-sc-1 &`) | `las-watchdog` | no FX engine |
| `scsynth` | `sclang` via `init_sc_1.scd:21` | `las-watchdog` | no effects, no DAC output path |
| `xterm` ×3 | `S43gui:11-13` | nothing (killed by `S99final:42` in stock boot) | nothing |
| `las-frontend` | `S43gui:21` | `las-watchdog` | **screen and panel both dead** |
| `las-dwm` | `S43gui:46` | `las-watchdog` (GUI script) | window unmanaged |
| `detect-held-buttons` | `S43gui:76` | nothing | held-button hotkeys inert |
| `avahi-daemon` | `S50avahi-daemon:8` | nothing | `moog-one.local` stops resolving |
| `dropbear` | `S50dropbear:36` | nothing | no SSH until next boot |
| `getty` on console | `inittab:27` | **init, respawn** | — |
| `las-watchdog` | `S99final:24` | nothing | **all of the above lose their supervisor** |
| `moogd` | `S99moogd:61` | nothing, by design | web UI down until next boot |

### `las-watchdog` is the supervisor, and it is more capable than expected

**[READ]** `strings las-watchdog` recovers the complete set of shell fragments it
executes through `system()`, and the OSC it speaks. In order of appearance:

*What it checks* — `pidof las-frontend`, `pidof las-sc`, `pidof sclang`,
`pidof scsynth`, `ping -c1 -W1 203.0.113.2`, and OSC `/vx/<n>/ping`, `/ping` and
`/v/voices` against `203.0.113.2`. Its messages:

```
FRONTEND IS DOWN!! PIDOF LAS-FRONTEND RETURNED : %d
SOUND ENGINE CONTROLLER IS DOWN!! PIDOF LAS-SC RETURNED : %d
SCLANG IS DOWN!! PIDOF SCLANG RETURNED : %d
SCSYNTH IS DOWN!! PIDOF LAS-SC RETURNED : %d
VC Ping %d returned : %d : failure count  = %d
LAS-WATCHDOG :  !!!VX %d IS DOWN!!!
LAS-WATCHDOG :  !!!VC IS DOWN!!!
LAS-WATCHDOG :  VC IS STILL UP BUT A VOICE IS DOWN
LAS-WATCHDOG : VC REPORTING %d VOICES
LAS-WATCHDOG :  VX INIT PROCESS TIMEOUT!!
LAS-WATCHDOG : successful check up...
```

*What it does about it* — four embedded scripts:

```sh
# 1. full stop
/etc/init.d/S42sc stop ; killall scsynth sclang screen
/etc/init.d/S43gui stop ; killall X ; sleep 2

# 2. restart the audio stack
/etc/init.d/S42sc stop ; killall scsynth sclang screen ; /etc/init.d/S42sc start &

# 3. restart the GUI
/etc/init.d/S43gui stop ; killall X ; /etc/init.d/S12splash start
/etc/init.d/S43gui start & ; sleep 5 ; killall las-dwm ; DISPLAY=:0 las-dwm &

# 4. XMOS is down  ->  power-cycle it
config-las-spi som ; sleep 1 ; config-las-spi xmos ; sleep 1
```

plus two socket-unwedging fragments, ``kill -9 `fuser 9799/udp` `` and
``kill -9 `fuser 9666/udp` ``, run on `sendto failed, cycling sockets`.

### This resolves an open question in INTERNALS §8d

§8d proposes resetting the XMOS via `XMOS_RESET_N` as "a candidate software recovery"
for the §8c wedge, calls it untested, and notes it "would have to be armed **before**
the fault, by a watchdog already running on the instrument."

**That watchdog exists, ships in the stock image, and already implements exactly that
recovery** — script 4 above, triggered by a failed `ping 203.0.113.2`. `las-watchdog`
is started at `S99final:24` on every boot.

And it is **not running on this instrument**, because `S99final:36` kills it whenever
`/media/thumbdrive/k` is present. Whether it would have saved the reboot wedge of
§8b-bis is unknown — that wedge is at the USB-enumeration layer, and `config-las-spi`
resets the XMOS rather than re-enumerating the bus — but it has never been given the
chance to try.

---

## 4. The failure-mode catalogue

Severity key: **S** software-recoverable · **P** needs power removed ·
**R** needs reflash or service.

---

### F-01 · The watchdog is disabled by the SSH key — **S**

**Trigger.** `/media/thumbdrive/k` present at boot.
**Mechanism.** `S99final:31-38` matches the key, `sleep 3`, `killall las-watchdog`,
`exit` — skipping both the watchdog and the read-only remount.
**Evidence.** `S99final:36`; absence of `las-watchdog` from `runtime-state.txt:4-126`.
**Symptom.** None, until something else dies. Then it stays dead: a crashed `scsynth`,
`sclang`, `las-frontend` or a hung XMOS is no longer restarted automatically.
**Recovery.** Start it by hand:
`(las-watchdog -t=10000 >> /var/log/las-watchdog.log 2>&1) &`.
**Caveat.** Running it re-arms scripts 1-4 above, which kill and restart the audio
stack and the GUI on their own initiative. That is fine for an instrument and hostile
to an experiment. Do not have it running while probing; do consider starting it before
leaving the instrument unattended or playing a gig.

---

### F-02 · Boot hangs waiting for `/var/las-sc.cookie` — **P**

**Trigger.** `las-sc` fails to start or fails to write its cookie. Causes seen or
plausible: XMOS not booted (see F-03), `/var` full or read-only, a missing or corrupt
`--vxdb=/var/tuning.vxtune`, a damaged `/usr/share/xmosfw/*.bin`.
**Mechanism.** `S99final:20-28` is an unbounded `while true` loop.
**Symptom.** Splash screen or a dark panel, forever. No SSH (`S50dropbear` already ran,
so SSH *is* up if the key is installed — but `S99moogd` never starts), and **no serial
getty**, because `inittab:27` is a `respawn` entry that init has not reached.
**Recovery.** With the SSH key installed, SSH still works and `S42sc restart` may clear
it. Without the key: power cycle. If it recurs, it is a reflash-class problem.
**Prevention.** Never leave `/var` full; never edit `/usr/share/xmosfw/`.

---

### F-03 · XMOS reset without the SPI bus handed over — **P**

**Trigger.** `config-las-spi xmos` (or anything calling it — `S25xmosfw`,
`las-watchdog` script 4, `open_ladder`, `start_tune`) run with a `PATH` that does not
contain `devmem`.
**Mechanism.** The IOMUXC remux at `config-las-spi` lines 8-20 needs `devmem`; the
`XMOS_RESET_N` pulse needs only `sysfs`. Lose the first and you get a reset into an
unreadable flash.
**Evidence.** `captures/harvest/04-tools.txt`: `config-las-spi: line 57: devmem: not
found` followed by `XMOS network cycled.` — and, in the same capture, `open_ladder`
ending in `Error: Unable to determine voice count`. INTERNALS records the same run
leaving `/v/voices` at `-1`.
**Symptom.** Voice cards silent, `/v/voices` reports `-1` or `0`, OLEDs single-line.
**Recovery.** Documented as the boot path or a power cycle. With a full `PATH`, try
`config-las-spi som ; sleep 1 ; config-las-spi xmos ; sleep 1 ; /etc/init.d/S42sc restart`
— that is verbatim what `las-watchdog` does, so it is a Moog-sanctioned sequence, not
an invention. If it does not take, remove power.
**Prevention.** `export PATH=/usr/sbin:/sbin:/usr/bin:/bin` before touching anything
in `/usr/bin` that is a shell script. Check with `file $(which TOOL)` first.

---

### F-04 · Warm `reboot` wedges the instrument — **P**

Established in INTERNALS §8b-bis and unchanged. What this survey adds is a mechanism
and a possible mitigation, both **[INFERRED]** and neither tested.

**Mechanism, proposed.** On a warm reboot the i.MX6 resets its USB host controller
while the XMOS gadget stays powered and never sees a disconnect. On the way back up the
host tries `SET_CONFIGURATION` on a device that believes it is still configured — which
is exactly the `usb 2-1: can't set config #1, error -71` (`EPROTO`) that §8c recorded
after a forced unbind/rebind. Nothing in the shutdown path holds the XMOS in reset:
`inittab:33` runs `rcK`, and `rcK` calls `S25xmosfw stop`, which is empty
(`S25xmosfw:18-19`).
**Possible mitigation, UNTESTED, do not try casually.** `config-las-spi som` holds the
XMOS in reset and would force a real USB disconnect before the reboot; `S25xmosfw`
releases it on the way up. The risk is that it kills the voice engine immediately, and
if the reboot then misbehaves anyway you are in the same place as before. The known-good
answer remains: **do not reboot; use `S42sc restart`, or the power switch.**

---

### F-05 · Network microburst wedges the USB gadget — **P**

Established in INTERNALS §8c. Two additions from the init scripts.

**The attack surface is wider than the OSC ports.** `S95dhcpd:11-14` DNATs UDP
7770, 7771, 9100 and 9300 arriving on `ethext` straight to `203.0.113.2` — the gadget.
`S40network:17` turns on `ip_forward` to allow it. Any host on the LAN that bursts UDP
at those ports on the instrument's address is bursting at the XMOS, with no rate limit
in between.
**The recovery that was thought not to exist, exists.** `las-watchdog` script 4 pings
`203.0.113.2` and, on failure, runs `config-las-spi som ; config-las-spi xmos`. If the
wedge is at the XMOS application layer this may clear it. If it is at the USB
enumeration layer (`-71`), it probably will not — the reset does not re-enumerate the
bus. Untested either way, and untestable while F-01 keeps the watchdog dead.
**Prevention.** `MIN_SEND_INTERVAL` in `moogone.transport.udp` (already in place), and
do not let anything else on the network scan the instrument's UDP ports.

---

### F-06 · `las-frontend` dies — **S**

**Trigger.** Killing it; OOM; a crash.
**Symptom.** Screen and panel both go. The instrument may still make sound.
**Recovery.** `/etc/init.d/S43gui restart`, which also restarts X. `las-watchdog`
does this automatically via its GUI script — when it is running (F-01).
**Note.** `S43gui:21` passes `--data-path=/var/las-frontend`; the ~280 MB preset
databases live there. It is also where the cookie is written and deleted
(`S43gui:29`, `S14fs:55`).

---

### F-07 · `/n_free` on an effect kills `scsynth` — **S**

Established in INTERNALS §"`/n_free` on an effect terminates scsynth". Recorded here
because the recovery is now clearer: with `las-watchdog` running, script 2 restarts the
audio stack within one poll period. With it dead (F-01, the current state), `scsynth`
stays down until `S42sc restart` is run by hand. Use `/n_run 0` and `enable = 0`
instead of `/n_free`.

---

### F-08 · Two DHCP clients, two addresses, one confusion — **S**

**[READ]** `runtime-state.txt:108` `udhcpc -R -n -p /var/run/udhcpc.ethext.pid -i ethext`
and `:121` `/sbin/dhcpcd start ethext` — two independent DHCP clients on one interface.
`:171-172`:

```
inet 192.168.1.136/24 brd 192.168.1.255 scope global ethext
inet 192.168.1.138/24 brd 192.168.1.255 scope global secondary ethext
```

**Cause.** `S40network:13` `ifup -a` starts BusyBox `udhcpc`; `S95dhcpd:9` separately
starts `dhcpcd`. Neither knows about the other. The router issues two leases to two
client identifiers.
**This explains a documented oddity.** INTERNALS notes that `scsynth` "answers from the
*secondary* address on `ethext`". The secondary address is `dhcpcd`'s, added after
`udhcpc`'s; the source-address selection follows from that, not from anything in
SuperCollider.
**Symptom when it bites.** Either lease can expire or change independently, so an
address written down in notes goes stale, and the address that OSC replies arrive from
can change across a boot.
**Recovery.** Use `moog-one.local` (avahi, `S50avahi-daemon:8`) rather than an address.
**Do not "fix" it** by killing one client — `S95dhcpd`'s `dhcpcd` is what the DNAT rules
and the reply path have been observed working with.

---

### F-09 · Root filesystem goes read-only under an ext4 error — **S/P**

**[READ]** `runtime-state.txt:174`: `/dev/root on / type ext4 (rw,relatime,errors=remount-ro,data=ordered)`.
Confirmed set at boot by `dmesg:279`.
**Trigger.** Any ext4 metadata error on `mmcblk2p3` — bad eMMC block, an interrupted
write, a full-disk edge case.
**Symptom.** Everything that writes to `/` starts failing. `/var` is a *different*
partition (`mmcblk2p6`) with the same `errors=remount-ro` default, so presets and logs
may keep working while the root FS is frozen — a confusing half-alive state.
**Also affected:** `mmcblk2p4` (`/var/lib/sys`, vfat) and any USB stick, both mounted
`errors=remount-ro` (`runtime-state.txt:183`, `:185`).
**Recovery.** `mount -o remount,rw /` clears the flag but not the cause. The correct
response is a clean power cycle and, if it repeats, `e2fsck` from a rescue path —
`fsck.ext4`, `e2fsck`, `dumpe2fs`, `tune2fs` and `resize2fs` are all present in
`/usr/bin` (`captures/harvest/04-tools.txt`).
**Note.** `dmesg:272-274` shows an ext4 journal replay happening on a *normal* boot.
The instrument is routinely powered off without a clean unmount, and `dmesg:286`
(`FAT-fs (mmcblk2p4): Volume was not properly unmounted`) says the same about the vfat
partition. It survives this, but it is running on the journal's goodwill.

---

### F-10 · Root may never actually become read-only — **S**, and a latent **R**

**[INFERRED]** `S99final:44` is `mount -f -o remount,ro /`. `-f` is the *fake* flag in
both BusyBox and util-linux: everything except the `mount(2)` call. If that reading is
right, root stays read-write for the whole of a stock (keyless) boot, and every
power-cut is a power-cut on a mounted-rw root filesystem carrying the only copy of the
OS.
**Why the captures cannot settle it.** Every capture on hand was taken with
`/media/thumbdrive/k` installed, and `S99final:37` `exit`s before line 44 in that case.
The `rw` in `runtime-state.txt:174` is explained by the key, not necessarily by `-f`.
**The one safe test**, from an SSH session:

```sh
grep ' / ' /proc/mounts          # expect: ... ext4 rw,relatime,errors=remount-ro ...
mount -f -o remount,ro /
grep ' / ' /proc/mounts          # still rw?  -> -f is fake, and S99final:44 does nothing
mount -o remount,rw /            # unconditional, in case it was not fake
```

If the second `grep` shows `ro`, the mitigation is that one un-`-f`'d command; if it
still shows `rw`, `-f` is fake and the instrument has never been protected.
**Consequence either way.** Assume `/` is writable and treat every power-off as
potentially damaging to it. Keep a backup (§6).

---

### F-11 · RT throttling steals the audio thread — **S**

**[READ]** `dmesg:330`: `sched: RT throttling activated`, at t≈1049 s on the captured
boot.
**[INFERRED] cause.** `S02sys:8` is `echo 999950 > sched_rt_runtime_us` with **no
directory**. The write lands in the cwd (`/`), not `/proc/sys/kernel/`. The kernel keeps
its 950000/1000000 µs default, so any `SCHED_FIFO` task that runs more than 95 % of a
period is forcibly descheduled — and `scsynth`'s audio thread is `SCHED_FIFO` 99 pinned
to the isolated cpu1.
**Symptom.** Periodic audio glitching or dropouts under load, appearing minutes into a
session rather than at boot, and invisible to `/status` (which the realtime thread
answers).
**Recovery / mitigation.** `echo 999950 > /proc/sys/kernel/sched_rt_runtime_us`, or
`echo -1` to disable throttling entirely. **The `-1` form removes the kernel's last
protection against a runaway RT task locking a CPU**; on an isolated cpu1 that is a
survivable trade, on cpu0 it is not. Prefer `999950`, which is what Moog intended.
This is a runtime write to `/proc`, reverted by any reboot — it changes nothing on disk.
**Corroborating check before acting:** `cat /proc/sys/kernel/sched_rt_runtime_us`
(expect `950000` if the bug is real) and `ls -l /sched_rt_runtime_us` (expect a stray
7-byte file if it is).

---

### F-12 · Logs are never rotated after boot — **S**

**[INFERRED]** `S14fs:61` runs `crontab -c /etc/crontab -l`, which lists a crontab.
It does not start `crond`, and `runtime-state.txt` shows no `crond`. The single crontab
entry (`captures/arch-harvest/crontab/root`) — `0 3 * * * /etc/log-refresh` — therefore
never fires. `/etc/log-refresh` runs exactly once per boot at `S14fs:58`.
**Symptom.** `/var/log` grows without bound on a machine left on for weeks. `/var` is
3.8 GB with ~3.3 GB free (`captures/sysmap/01-hardware.txt:50`), so this is slow — but
`las-watchdog` logs every poll, and with `-t=10000` that is one line per 10 s forever.
**Recovery.** `/etc/log-refresh` by hand, or `crond` (it exists in `/usr/bin`) — but
starting `crond` is a behaviour change Moog did not ship, so prefer the manual call.

---

### F-13 · `moogd` may be pinned to the audio core — **S**

**[READ]** `S99moogd:61` says `taskset -c 0`. `usb/README.md` records a cold-boot test
reporting `affinity=2 last-cpu=1`, which is cpu1 — the core `isolcpus=1` reserves and
`scsynth`'s `SCHED_FIFO` 99 audio thread owns.
**Symptom if real.** Cache pressure and occasional priority inversion against the audio
thread; with F-11 also in play, a plausible contributor to glitching.
**Check.** `grep Cpus_allowed_list /proc/$(pidof moogd)/status` — expect `0`.
**Recovery.** `taskset -pc 0 $(pidof moogd)`, and confirm the deployed
`/etc/init.d/S99moogd` matches `usb/S99moogd`.

---

### F-14 · `/media/thumbdrive` stops resolving — **S**

**[INFERRED]** The drive mounts at `/var/local/media/sda1`
(`runtime-state.txt:185`), not at `/media/thumbdrive`. The path every gate uses —
`S50dropbear:29`, `S99final:31`, `S99moogd:21-23`, `S43gui:21` `--usb-path=` — is
`/media/thumbdrive`, which must therefore be a symlink or a second mount created
somewhere not in the capture set (`S14fs:28-31` creates `/var/local/media` but its
`ln -s` is transposed and does not produce it).
**Trigger.** A second USB drive enumerating first, so the intended stick becomes `sdb1`;
a slow drive that is not mounted when `S50dropbear` runs; a drive reformatted exFAT
(invisible to a 4.1 kernel).
**Symptom.** **No SSH on the next boot**, `moogd` does not start, and — the sharp edge —
`S99final` does *not* find the key, so it proceeds to `killall xterm; killall las-dwm;
mount -f -o remount,ro /`. The instrument boots and plays perfectly and you cannot get in.
**Recovery.** Physical: put the correct FAT32/MBR stick in the only USB port and power
cycle. There is no software recovery from a machine you cannot log into except the
serial console (§6).
**Prevention.** One stick, FAT32/MBR, in the port, always. Verify with
`ls -l /media/thumbdrive/k` before any reboot or power-off.

---

### F-15 · Memory exhaustion — **S**

**[READ]** `runtime-state.txt:194-198`: `MemTotal 507956 kB`, `MemFree 11192 kB`,
`MemAvailable 96684 kB`. No swap (`S02sys:7` sets `swappiness 0`; `inittab:34` runs
`swapoff -a`; there is no swap partition in `fstab`). 320 MB of the 512 MB is reserved
as a CMA pool at boot (`dmesg:9`, `dmesg:25` leaves 179 MB to the kernel).
**Comparison point.** An earlier capture two minutes after boot
(`captures/moog-recon/01-system.txt`) shows `MemFree 240776 kB`. The difference is the
preset databases, `las-frontend`'s working set, and now `moogd`.
**Symptom.** The OOM killer picks the largest RSS — almost certainly `las-frontend`,
which takes the screen and panel with it (F-06).
**Recovery.** `S43gui restart`. **Prevention.** Anything added should be measured, not
assumed; `moogd` is ~6 MB of binary but a Go heap is not free.

---

### F-16 · The hardware watchdog — dormant, but present — **P**

**[READ]** `dmesg:223`: `imx2-wdt 20c0000.wdog: timeout 60 sec (nowayout=0)`.
**Current state.** Nothing in the init scripts or the process table opens `/dev/watchdog`,
and the `imx2-wdt` driver starts its timer on open. So it is inert today.
**The hazard.** If anything added ever opens `/dev/watchdog` and then stops writing to
it, the SoC hard-resets 60 seconds later — which is a warm reset, i.e. **F-04, the wedge**.
`nowayout=0` means closing the file cleanly (writing `V` first) disarms it, but a crash
does not.
**Rule.** Do not open `/dev/watchdog`. If a supervisor is wanted, use `las-watchdog`
(§3), which supervises processes without arming silicon.

---

### F-17 · Firmware update staging is wiped every boot — **S**

**[READ]** `S14fs:51`: `rm -rf /mnt/fwu/*`. `/mnt/fwu` is `mmcblk2p7`, 861 MB
(`fstab:11`, `captures/sysmap/01-hardware.txt:51`). It is emptied on every single boot.
**Consequence.** `/mnt/fwu` is scratch space for an update in progress, not storage.
Anything left there is gone at the next power-on, with no warning.

---

## 5. What is safe to modify

### The constraint

`/` is `mmcblk2p3`: **636.8 MB total, 451.7 MB used, 149.2 MB free**
(`captures/sysmap/01-hardware.txt:46`). It holds the entire OS, ~700 binaries, X11,
the JUCE frontend, the SuperCollider class library, and both XMOS firmware images.
There is no second copy of it reachable from a running system, and no package manager.
**A damaged root filesystem is a reflash, and there is no evidence in these captures of
a user-accessible reflash path** (§6).

### Green — write freely

| Path | Why | Recovery if damaged |
|---|---|---|
| `/media/thumbdrive/**` | removable; the instrument treats it as opt-in cargo | re-copy from this workstation |
| `/var/log/**` | rebuilt by `/etc/log-refresh` at `S14fs:58` | next boot |
| `/tmp`, `/dev/shm`, `/var/run` | tmpfs (`fstab:5,6,13`), 248 MB each | reboot |
| `/var/local/tmp/**` | cleared at `S14fs:47` | next boot |
| `/proc/sys/**` at runtime | never persists | reboot |

**Put everything you add on the USB stick.** `moogd` already does this and it is the
right shape: 6 MB of binary and 2.2 MB of UI on a 234 GB FAT32 drive
(`captures/sysmap/01-hardware.txt:54`), costing the root filesystem exactly one file.

### Amber — writable, but earn it

| Path | Notes |
|---|---|
| `/var/**` (3.8 GB, 3.3 GB free) | plenty of room, but see the two rows below |
| `/var/las-frontend/**` | the ~280 MB preset databases. Back up before touching. `S14fs:55` deletes only the cookie |
| `/etc/init.d/S99*` | the only sane place for a new service. Must exit 0, must not block — `S99moogd` is the model |
| `/proc/sys/kernel/sched_rt_runtime_us` | the F-11 fix. Runtime only |
| `/mnt/fwu` | 861 MB and **wiped every boot** (F-17). Scratch only |
| `/var/lib/sys` (`mmcblk2p4`, vfat, 63 MB) | purpose unidentified in these captures; vfat and repeatedly unclean (`dmesg:286`). Leave alone |

### Red — load-bearing; a mistake here costs a service call

| Path | What it breaks | Recovery |
|---|---|---|
| `/var/cal/vxcal.db`, `/var/tuning.vxtune/**` | **the only copy of the analog calibration** — 48 oscillator tables, 16 voice files | a backup helps only if the failure is file corruption. Nothing else does |
| `/usr/share/xmosfw/*.bin` | `las-sc` cannot boot the XMOS → F-02, boot hang | reflash |
| `/etc/init.d/S25xmosfw`, `/usr/bin/config-las-spi` | no XMOS at all | reflash |
| `/etc/init.d/S42sc`, `S43gui`, `S99final` | audio stack, UI, and the boot's last gate | reflash |
| `/etc/inittab`, `/etc/fstab` | unbootable | reflash |
| `/usr/bin/las-{sc,frontend,dwm,watchdog}` | the instrument | reflash |
| `/usr/share/las-fx/**` | the effects engine | reflash |
| `/boot/moog_splash.fb` | `S12splash:21` `dd`s it to `/dev/fb1`; wrong size = garbage on screen | copy back |
| `/etc/authorized_keys` | copied to `/root/.ssh` only if that directory is absent (`S14fs:38-42`) | edit `/root/.ssh/authorized_keys` on `/var`-backed storage instead |

### One amber file that is already amber

`captures/arch-harvest/init_sc_1.scd:9-10` says `blockSize = 128`; the running
`scsynth` (`runtime-state.txt:115`) says `-z 256 -Z 256`. **`/usr/share/las-fx/init_sc_1.scd`
has been edited on the device.** That is a *red* path by the table above — it is the
effects engine's bootstrap, on the root filesystem.

It is a defensible edit (INTERNALS documents the block-size measurement), but it means:

1. `/usr/share/las-fx/init_sc_1.scd` no longer matches the shipped image. **Keep the
   pristine copy** — `captures/arch-harvest/init_sc_1.scd` is *not* it, it is the
   modified one.
2. A syntax error there produces an `sclang` that never boots `scsynth`. `las-sc` still
   drops its cookie, so the boot completes — you get an instrument with a control layer,
   a screen, and no effects, and the cause is a file that was edited weeks ago.
3. It is not tracked by anything. Note the block size in the log of the run it belongs to.

### Rules for adding software

1. **Binary and data on the USB stick. One file on root, an `S99*` init script.**
2. **`exit 0` unconditionally, and never block.** `rcS:23` ignores exit codes, so the
   only way to break the boot is to not return (§2). `S99moogd:82` is right.
3. **Bound every wait.** `S99moogd:39-45` (30 s) is right; `S99final:20-28` is the
   counter-example Moog shipped.
4. **`taskset -c 0`.** cpu1 belongs to the audio thread. Verify with
   `/proc/<pid>/status`, not `taskset -p`, which shows only the main thread.
5. **No new listener on UDP 7770/7771/9100/9300** — `S95dhcpd:11-14` already DNATs those
   to the XMOS.
6. **Pace UDP.** The §8c interlock is not optional.
7. **No `/dev/watchdog`** (F-16). No `reboot` (F-04).
8. **Check free space before writing to `/`.** 149 MB, and no way to get more.

---

## 6. Recovery paths

### What exists, ranked by how much is known

**1 · `S42sc restart` — proven.** Cycles `las-sc`, which cycles the whole SuperCollider
stack (§1.3 correction) and re-runs the XMOS firmware upload. Costs the loaded patch and
~45 s. The recorded track record is unbroken.

**2 · `las-watchdog` — shipped, capable, currently disabled.** Four recovery scripts
including an XMOS power-cycle (§3). Re-arm it manually if wanted; understand that it
will restart things without asking (F-01).

**3 · `config-las-spi som` / `xmos` — the XMOS reset line.** `/sys/class/leds/XMOS_RESET_N`.
`las-watchdog` already uses it as a recovery, so it is Moog's own sequence rather than
an experiment. Requires `devmem` on `PATH` (F-03).

**4 · Power cycle.** The universal answer to F-04, F-05 and F-03. Not clean — `dmesg:272`
and `:286` show journal replay and a dirty FAT on every boot — but survivable.

**5 · Serial console — present, and better than it looks.** `console=ttymxc1,115200` on
the cmdline; `dmesg:146-147` confirms `21e8000.serial: ttymxc1 ... console [ttymxc1]
enabled`; `inittab:27` respawns a `getty` on it. **[UNKNOWN]** whether the physical
header is accessible without opening the case, and whether root has a password
(`/etc/shadow` is not in the capture set). **[READ]** the caveat from §1.1: the getty
does not start until `rcS` returns, so it is useless during F-02 — but it is available
for everything else, including a machine with no working network, which is exactly the
F-14 case.

**6 · U-Boot — [INFERRED] present, and the real rescue path.** `fw_printenv` and
`fw_setenv` are in `/usr/bin` (`captures/harvest/04-tools.txt`), and those tools exist
only to manipulate a U-Boot environment. `mkimage`, `mkenvimage` and `kobs-ng` are there
too. i.MX6 SoCs also have a mask-ROM serial-download mode reachable over USB OTG with
`imx_usb_loader` from a host. **[UNKNOWN]** the boot-mode strap and whether the OTG port
is exposed. This is what a Moog service centre would use.

**7 · A second root filesystem — [INFERRED], and worth checking.**
`fstab:8-9`:

```
/dev/mmcblk2p2  /mnt/u1  ext4  ro,noauto  0 0
/dev/mmcblk2p3  /mnt/u2  ext4  ro,noauto  0 0
```

`mmcblk2p3` is the *live root* (cmdline `root=/dev/mmcblk2p3`). It is listed here a
second time as "u2", alongside "u1" = `mmcblk2p2`, both `ro,noauto`. `dmesg:245` shows
seven partitions on a 7.21 GiB card; `/var` (p6, 3.8 G), `/mnt/fwu` (p7, 862 M),
`/var/lib/sys` (p4, 63 M) and root (p3, 637 M) account for about 5.3 GB, leaving p1, p2
and p5 unmapped. **The symmetric `u1`/`u2` naming of two `ro,noauto` ext4 partitions is
the signature of an A/B root pair**, which together with `/mnt/fwu` (the update staging
area, wiped at `S14fs:51`) and `/usr/bin/lasfwu` describes a complete
download-to-fwu → write-the-other-slot → switch-U-Boot-env update scheme.

**This is the single highest-value thing to confirm**, because if `mmcblk2p2` holds a
bootable root, a damaged `/` is a U-Boot environment change rather than a service call.
The read-only checks, all safe:

```sh
cat /proc/partitions                       # sizes of p1, p2, p5
mount -o ro /dev/mmcblk2p2 /mnt/u1 && ls /mnt/u1 && umount /mnt/u1
fw_printenv                                # U-Boot env: which slot, and how it chooses
head -60 /usr/bin/lasfwu                   # it is a bash script -- READ it, do not run it
```

**8 · Firmware update via `lasfwu` — exists, unexplored.** `/usr/bin/lasfwu` is a bash
script (`captures/harvest/04-tools.txt` shows its man page: "searches for LAS firmware
package files, checks their validity, and upgrades the LAS firmware"). `las-frontend`
carries `--firmware-path=<path>` (default the USB path), `--firmware-dry-run`, and the
strings `Looking for firmware updates in`, `Loading firmware`, `/usr/bin/lasfwu` and
`DON'T POWER OFF THE INSTRUMENT WHILE THE UPDATE IS IN PROCESS`. **The normal user
update path is: put Moog's update package on the USB stick, and the frontend finds it.**
`--firmware-dry-run` is the safe way to see what it would do.

**9 · Factory data restore — partial.** `las-frontend` strings include
`Populating with complete factory data`, `Done populating with complete factory data`
and `Restore factory default FX preset for`. **[INFERRED]** this restores *presets*, not
the OS and not calibration. `Can't open calibration database:` /
`Created / opened calibration database at:` appear separately, and INTERNALS is explicit
that calibration is unique per instrument.

### There is no evidence of

* a rescue partition that boots on its own,
* a recovery menu on the panel (`detect-held-buttons` at `S43gui:76` implies a held-button
  hotkey exists, but nothing in the captures says what it does),
* a network reflash,
* or any way to rebuild `/var/cal/vxcal.db` and `/var/tuning.vxtune` without running
  Moog's calibration passes on the hardware (`start_tune`, `open_ladder` — both bash
  scripts that run on invocation; see INTERNALS §"`--help` is not safe").

### The backup that should exist and does not

Nothing in `captures/` is a filesystem image. Before any further change to `/`, take:

```sh
# to this workstation, over SSH, read-only on the device:
tar czf - /var/cal /var/tuning.vxtune            # the irreplaceable part, ~1 MB
tar czf - /etc /usr/share/las-fx                 # the configuration and FX engine
dd if=/dev/mmcblk2p3 bs=1M | gzip                # a full root image, ~637 MB raw
```

The third is the one that turns "reflash" from a service call into an afternoon,
*provided* recovery path 6 or 7 turns out to exist. Take it while the instrument is
healthy; a `dd` of a mounted rw filesystem is crash-consistent, not clean, so quiesce
first with `S42sc stop` and `sync`.

---

## 7. Corrections to `MOOG-ONE-INTERNALS.md`

1. **§"Scope and cautions" — `S42sc` is not asymmetric.** `las-sc` spawns
   `screen -d -m /usr/share/las-fx/launch-sc-1`, which starts `sclang` and `scsynth`.
   Starting `las-sc` starts the whole stack. Evidence: the literal string in the binary,
   plus the process tree in `runtime-state.txt:112-115`. §1.3 above.
2. **§8d — the "candidate software recovery" is not a candidate; it is shipped.**
   `las-watchdog` already pings `203.0.113.2` and runs
   `config-las-spi som ; sleep 1 ; config-las-spi xmos ; sleep 1` on failure. It is
   started at `S99final:24` on every boot and killed at `S99final:36` whenever the SSH
   key is present. §3.
3. **§8c — the exposure is wider than the OSC ports.** `S95dhcpd:11-14` DNATs UDP 7770,
   7771, 9100 and 9300 from the LAN directly to the gadget, with `ip_forward` enabled at
   `S40network:17`. F-05.
4. **The "secondary address" is not a SuperCollider quirk.** Two DHCP clients run on
   `ethext`: BusyBox `udhcpc` from `S40network:13` and `dhcpcd` from `S95dhcpd:9`. F-08.

---

## 8. Gaps — what to capture next, all read-only

| Want | Command | Answers |
|---|---|---|
| Partition sizes | `cat /proc/partitions` | is p2 a second root? (recovery path 7) |
| Second root | `mount -o ro /dev/mmcblk2p2 /mnt/u1; ls /mnt/u1` | the same, definitively |
| U-Boot env | `fw_printenv` | how the boot slot is chosen |
| `/etc/network/interfaces` | `cat` | which client owns which address (F-08) |
| `/media` resolution | `ls -l /media /var/local/media; cat /proc/mounts` | F-14's actual mechanism |
| udev rules | `ls -l /etc/udev/rules.d/; cat` each | what creates `thumbdrive`, and the NIC rule |
| `/etc/log-refresh` | `cat` | what rotation actually does (F-12) |
| RT throttle | `cat /proc/sys/kernel/sched_rt_runtime_us; ls -l /sched_rt_runtime_us` | confirms F-11 |
| `moogd` affinity | `grep Cpus_allowed_list /proc/$(pidof moogd)/status` | F-13 |
| Root RW state | the F-10 sequence | whether `mount -f` is fake |
| `lasfwu` | `head -60 /usr/bin/lasfwu` — **read, do not run** | the update mechanism |
| Serial console | `cat /etc/securetty /etc/shadow; grep root /etc/passwd` | whether the console is a real way in |
| Free space | `df -h /` before and after any change | the 149 MB budget |

Every one of those is a read. None of them starts, stops or resets anything.
