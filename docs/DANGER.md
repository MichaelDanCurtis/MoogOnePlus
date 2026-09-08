# What will break this instrument

Consolidated from the full architecture teardown. Read before touching anything.

Ranked by how bad the outcome is, not how likely.

---

## Tier 1 — permanent damage, needs Moog service

### Voice-card calibration and tuning data
`/var/cal/vxcal.db` and `/var/tuning.vxtune` hold this unit's per-card analog
calibration. They are unique to this instrument's hardware and **cannot be
regenerated without factory equipment**.

Written by: `vxtune write … [--tune|--cal]`, the `/cal/*` OSC namespace (62 leaves),
`/load_cal`, `/load_tuning`, and a calibration-DB reset screen in `las-frontend`
whose own text says it "cannot be recovered".

Both files are backed up in `captures/backup/` in this repo. **That backup is the
only copy.** Verify it before anything near calibration.

### Firmware flash paths
* **Voice controller:** `las-sc` runs `flashrom … -w <vcfw> -p linux_spi:dev=/dev/spidev0.0`,
  armed on every boot via `--vcfw`/`--vcfv` and skipped only on a version match.
* **Voice cards:** `/fw/start` + `/fw/data` to `203.0.113.2:7770` — **hand-sendable
  OSC**. `--force-vx-update` flashes even when versions match.
* **No signature or checksum check** anywhere in `las-frontend`; it hands a USB file
  to `/usr/bin/lasfwu`.

An interrupted flash of either processor is a service call.

### Serial number and MAC
`las-frontend` contains a `SerialMacWritePanel`. It overwrites the unit's identity.

---

## Tier 2 — needs power removed, instrument unusable until then

### The USB gadget wedge — two ways in
`2662:800d "LAS internal"` carries **both** `ethext` (LAN) and `usbint` (the voice
controller link). Lose it and you lose the network *and* the voice cards at once:
LEDs on, OLEDs showing a single line, no display, no network.

1. **`/sbin/reboot`.** Verified, twice-documented. **Use `/etc/init.d/S42sc restart`.**
2. **A microburst** of network traffic at the gadget. And `S95dhcpd` DNATs UDP
   **7770, 7771, 9100, 9300** from the LAN straight to it with forwarding on — so
   anything on the network can do this without authenticating.

### The lock-up mechanism, now understood
This is what happened on 2026-09-03. Both `las-sc`'s calibration path and
`las-frontend`'s calibration transfer do:

```
killall las-watchdog      # remove the supervisor
… then write to the voice cards (vxtune write, config-las-spi, las-sc --cli)
```

Watchdog dead, SPI or card write in flight, no recovery. **This is why running an
unknown Moog script is dangerous: they ignore `--help` and run their real action.**

### Reading and writing calibration are THE SAME ADDRESS

The single most dangerous property of this instrument's control surface, from the
firmware teardown:

> Most `/cal/*` and `/hw/*` addresses are the same address for reading and writing.
> **Zero arguments is a query. One argument is a persistent write** to a voice
> card's trim table. There is no separate setter namespace to stay out of.

That is 168 `/cal` families plus the PID auto-tune (`/hw/enable_pid`). An address
you send to "just to see what it returns", with one argument attached by accident,
permanently alters this unit's analog calibration.

This is what makes the earlier finding load-bearing rather than academic: a
zero-argument message really is inert (tested — `/hw/mute` acked one and the
instrument played on), and that is the *only* reason a 767-address census was safe
to run. **Never attach an argument to an address you have not identified.**

### Voice-card flash is writable over the bus, ungated

Both firmware images implement flash read **and write** handlers reachable over the
voice bus — `Read from flash` / `Write to flash complete`, with errors `550 CRC`,
`wrong image version`, `magic number` (controller 0x2AA72, card 0x1C0B9).

Writing a card's flash is **not** gated behind `lasfwu`. The host side is just
`/fw/start` followed by `/fw/data` in 200-byte blocks. `las-sc --cli
--force-vx-update` explicitly bypasses the version-match guard, and `las-sc`
contains the literal string **`Flashing VC Anyway`** — it will reflash the
controller after a network error.

### `config-las-spi som` without the reverse
`config-las-spi som ; sleep 1 ; config-las-spi xmos` is a hardware power-cycle of
the voice engine. Stopping halfway leaves the SPI bus switched away from the XMOS.

---

## Tier 3 — the instrument is compromised or unsafe, but recoverable

### Unauthenticated remote root
`efx_server.scd:344` interprets its first argument as SuperCollider source whenever
the second is absent. `sclang` runs as root and can shell out. **UDP 7775 is bound to
`0.0.0.0`** — verified live. One packet from anywhere on the network.

Mitigation until Moog fix it: keep the instrument off untrusted networks. There is
no authentication anywhere in this control plane.

### DC at twice full scale on an aux output
Routing bus effect slot 3 to any aux output writes `dry_dir4_r` non-zero, and
`dry_dir4` is the integer `1`, not a signal. The output stage's array broadcast and
`.sum()` double it: **2.0 on a physical output.** Protect monitors before
experimenting with aux routing on slot 3.

### NaN from the stereo delays
`stereoDelay_*` and `pingpongDelay_*` feed `sigL * 2` through a loop containing only
an `LPF`. Above roughly 0.5 feedback they diverge to `inf` then `NaN`, and the node
stays poisoned until replaced. `bbdDelay` and `tapeDelay` in the same file saturate
*inside* the loop and are fine.

### `/fx/start 1` reload loop
`efx_server.scd:71` reloads `init_sc_1.scd` in-band if a `kill -0` fails. That
spawns a second state thread without stopping the first, orphans every group, and
creates **ten more LADSPA reverbs** on a box with ~11 MB free. If `~serverPID` is
ever nil, `kill -0 nil` always fails — a self-sustaining loop.

---

## Tier 4 — audible or operational, no lasting harm

* **`/n_free` on a LADSPA node terminates `scsynth`.** The load-bearing invariant is
  `doneAction: 1` on the ten `et_*` synthdefs — every other synthdef uses `2`.
  "Tidying" that to `2` kills the audio engine on the next release.
* **Two `/fxN` messages to one slot within ~250 ms** leave a waiter spinning at
  100 Hz forever, and can orphan a synth.
* **The same Eventide on both bus slots** — they share one object; slot 4 steals the
  node from slot 3, and slot 3's next change parks it, killing slot 4.
* **Hidden `las-frontend` entry points:** `--test-fixture` (factory hardware test),
  `--script=<path>` (arbitrary JS with hardware access), `FormatUSBDrivePanel`. No
  PIN protects these; they are simply unlisted.

---

## The safety net that is switched off

`las-watchdog` ships and runs on every stock boot. It polls `las-frontend`,
`las-sc`, `sclang` and `scsynth`, pings the voice controller, and recovers — up to
and including an XMOS power-cycle via `config-las-spi`.

**`S99final:36` kills it whenever `/media/thumbdrive/k` is present.** That is the
file that enables SSH. So the drive that makes this instrument hackable also disarms
every automatic recovery it has, including the one that might have caught the
reboot wedge.

There is no debounce on the watchdog either: a single missed poll restarts the whole
audio and GUI stack. Before genuinely invasive work, `killall las-watchdog`
deliberately — but know that you are then working without a net.

---

## Safe to modify

**Green — put new work here.** `/media/thumbdrive/**` (234 GB), `/var/log/**`, the
tmpfs mounts, `/proc/sys` at runtime. `moogd` is the right shape: the binary and the
UI live on the USB stick and cost the root filesystem exactly one file.

**Amber — back up first.** `/var/**` (3.3 GB free), `/var/las-frontend` (the preset
databases are ~280 MB), `/etc/init.d/S99*` (must `exit 0`, must not block).
`/mnt/fwu` is wiped every boot by `S14fs`.

**Red — reflash if damaged.** `/var/cal/*`, `/var/tuning.vxtune`,
`/usr/share/xmosfw/*.bin`, `config-las-spi`, `S25xmosfw`, `S42sc`, `S43gui`,
`S99final`, `inittab`, `fstab`, the `las-*` binaries, and all of
`/usr/share/las-fx/**`. A syntax error in `init_sc_1.scd` yields an instrument that
boots normally with no effects at all.

**There are ~148 MB free on root, no package manager, and no second copy of
anything.**

## The recovery path — CONFIRMED, and it changes the risk calculus

**There is a complete second firmware on the eMMC.** `mmcblk2p2` mounts as a full,
intact root filesystem:

```
mmcblk2p2   las-v1.4.0   las-sc dated Jun 15 2020   636.7M, 75% used
mmcblk2p3   las-v1.5.0   las-sc dated May 16 2022   636.8M, 75% used   <- live
```

An A/B firmware slot pair. `p2` holds the previous release, is **pristine** — no
`S99moogd`, factory `blockSize = 128` — and nothing this project has done has
touched it. The partition table shows a second symmetric pair too (`p4`/`p5`, ~64 MB
each) which is very likely kernel and device tree.

So a damaged live rootfs is **not** a service call. The fallback is already on the
device, and the update mechanism (`/mnt/fwu` staging, `/usr/bin/lasfwu`) exists to
write the inactive slot and switch.

**What that does not cover.** Rolling back to `p2` means losing whatever v1.5.0
added, so an image of the live slot is still worth holding —
`captures/backup/rootfs-p3-las-v1.5.0-*.img.gz`. And **neither slot protects the
calibration data**: `/var` is a separate partition (`mmcblk2p6`), so `vxcal.db` and
the sixteen voices' tuning tables survive a firmware rollback and are destroyed by
anything that writes them. Those remain the only truly irreplaceable thing on the
instrument.

Verified backup: `captures/backup/calibration-*.tar.gz`, 66 of 66 files checked
against the instrument's own md5sums.
