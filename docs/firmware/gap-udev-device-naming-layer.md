# The upstream udev layer: `/lib/udev`, `/usr/lib/udev`, `etc/udev/hwdb.d`

Scope: everything under the udev device-naming layer that is *not* Moog's own
four rules. Source: the decrypted v1.8.2 root filesystem at
`captures/firmware-1.8.2/rootfs-1.8.2` (written below as `<R>`), compared
against `captures/rootfs-1.5.0` (`<R15>`), with live corroboration from
`captures/arch-harvest/runtime-state.txt` restricted to the categories its
`CAVEAT-runtime-state.md` marks as uncontaminated (ALSA enumeration, network
interfaces, mounts, `lsmod`, kernel cmdline).

No instrument was touched. Every binary was read with `strings`, `xxd`,
`file` and `llvm-objdump`; none was executed. Proposed live checks are in
§16 and are read-only.

Every claim is graded **[READ]** (quoted from a file, with offset or line),
**[INFERRED]** (reasoning, with the evidence named), or **[UNKNOWN]**.

---

## 1. Headline

**[READ]** `/etc/udev/hwdb.bin` does not exist anywhere in the 1.8.2 image, no
init script or binary ever runs `udevadm hwdb --update`, and `udevd` hardcodes
exactly that one path. The 5.1 MB of hardware databases under
`<R>/etc/udev/hwdb.d/` are therefore **inert data that is never consulted**, and
the **twelve** rule lines that depend on `IMPORT{builtin}="hwdb"` all fail,
taking their whole rule line with them.

Second: the module alias index is empty, so `80-drivers.rules`' on-demand
`modprobe` can never match anything. Third: `80-net-name-slot.rules` is a
guaranteed no-op on this SoC. Together these mean the upstream layer contributes
far less to this machine than its file count suggests — but it is not
*inactive*, and three of its rules do real work on every boot (§7, §8, §12).

---

## 2. Inventory, as shipped

**[READ]** `ls -la` of the three directories.

`<R>/lib/udev/` — six helper binaries plus `rules.d`:

| file | bytes | ELF |
|---|---|---|
| `ata_id` | 84988 | ARM EABI5, dynamic, stripped |
| `cdrom_id` | 97288 | " |
| `collect` | 85024 | " |
| `mtd_probe` | 3884 | " |
| `scsi_id` | 91676 | " |
| `v4l_id` | 64464 | " |

**[READ]** `<R>/lib/udev/rules.d/` holds 18 upstream rule files:
`50-udev-default`, `60-block`, `60-cdrom_id`, `60-drm`, `60-evdev`,
`60-persistent-alsa`, `60-persistent-input`, `60-persistent-storage`,
`60-persistent-storage-tape`, `60-persistent-v4l`, `60-serial`, `64-btrfs`,
`70-mouse`, `75-net-description`, `75-probe_mtd`, `78-sound-card`,
`80-drivers`, `80-net-name-slot`.

**[READ]** `<R>/usr/lib/udev/` is a **separate** tree (not a merged-`/usr`
symlink — `<R>/lib` has 47 entries, `<R>/usr/lib` has 672, and neither is a
symlink). It holds `libinput-device-group`, `libinput-model-quirks`,
`hwdb.d/90-libinput-model-quirks.hwdb`, and two more rule files:
`80-libinput-device-groups.rules`, `90-libinput-model-quirks.rules`.

**So the upstream rule count is 20, not 18** — the gap brief's 18 omits the two
libinput rules in the second libexec tree.

**[READ]** `<R>/etc/udev/hwdb.d/` holds 14 databases totalling 5.1 MB, largest
`20-pci-vendor-model.hwdb` (2 648 842 B) and `20-OUI.hwdb` (1 292 931 B, 22 694
`OUI:` records). The gap brief says 15 in this directory; the listing shows
**14** here plus **1** in `<R>/usr/lib/udev/hwdb.d/` — 15 across both trees,
which is presumably where the figure came from.

**[READ]** `<R>/etc/udev/udev.conf` is three lines, all comment:

```
# see udev.conf(5) for details

#udev_log="info"
```

So the log level is the compiled default, not a configured one.

---

## 3. The engine: eudev 3.1.5

**[READ]** `strings <R>/sbin/udevd` → `udev-3.1.5` at file offset `0x2cd68`.
`<R15>/sbin/udevd` carries the same version string. `file` reports both as
`ELF 32-bit LSB executable, ARM, EABI5 … dynamically linked … stripped`.
`<R>/lib/libudev.so.1.6.3`, `<R>/sbin/udevd` (223 840 B),
`<R>/usr/bin/udevadm` (231 600 B).

**[READ]** Compiled-in builtins, from the builtin name/description string table
in `<R>/sbin/udevd` (`0x2cf33`–`0x2dd80`):

`blkid`, `btrfs`, `hwdb`, `input_id`, `keyboard`, `kmod`, `net_id`, `path_id`,
`usb_id`.

**[READ]** Absent: `net_setup_link` and `uaccess`. There is no
`.link`-file mechanism and no `MACAddressPolicy` string in the binary — this
build predates systemd's `80-net-setup-link.rules`, which is why interface
naming here is governed by `80-net-name-slot.rules` alone.

### 3.1 Which directories are scanned

I initially read the string table as showing that `/lib/udev/rules.d` was *not*
scanned. **That was wrong, and the correction matters**: GCC merges string
suffixes, so `"/lib/udev/rules.d"` is stored as a pointer four bytes into
`"/usr/lib/udev/rules.d"` and does not appear as its own string.

**[READ]** Resolving the actual NULL-terminated pointer array in
`.data.rel.ro` at file offset `0x32294` of `<R>/sbin/udevd`:

```
0x32294  0x0003adb7  "/etc/udev/rules.d"
0x32298  0x0003ccf6  "/lib/udev/rules.d"
0x3229c  0x0003adc9  "/run/udev/rules.d"
0x322a0  0x0003ccf6  "/lib/udev/rules.d"
0x322a4  0x0003ccf6  "/lib/udev/rules.d"
0x322a8  0x0003ccf2  "/usr/lib/udev/rules.d"
0x322ac  0x00000000  NULL
```

`<R>/usr/bin/udevadm` carries the identical array at `0x34114`. The repeated
entries are eudev's split-`/usr` handling; duplicates are harmless because the
file list is de-duplicated by basename.

**All 20 upstream rule files are loaded**, alongside Moog's four in
`/etc/udev/rules.d`.

**[READ]** `<R>/usr/bin/udevadm` additionally carries a two-entry hwdb source
array at `.rodata` `0x2be9c`: `{"/etc/udev/hwdb.d", "/lib/udev/hwdb.d"}`.
**[READ]** `<R>/lib/udev/hwdb.d` **does not exist**; the second hwdb tree is at
`<R>/usr/lib/udev/hwdb.d`. So even if the hwdb were built, libinput's
`90-libinput-model-quirks.hwdb` would be missed — its directory is not on the
search path. **[INFERRED]** from those two reads.

---

## 4. The hwdb is never compiled — the load-bearing finding

**[READ]** `find` over both rootfs trees for `hwdb.bin`: **no match**, in 1.8.2
or 1.5.0.

**[READ]** `<R>/sbin/udevd`, `<R>/usr/bin/udevadm` and `<R>/lib/libudev.so.1.6.3`
each contain the literal:

```
/etc/udev/hwdb.bin does not exist, please run udevadm hwdb --update
```

plus `error mapping /etc/udev/hwdb.bin: %m`. The path is hardcoded and
singular — there is no fallback location.

**[READ]** `grep -rn hwdb` across `<R>/etc`, `<R>/usr/share`, `<R>/bin`,
`<R>/sbin`, `<R>/usr/bin`, `<R>/usr/sbin` returns **only comment lines inside
the `hwdb.d` data files themselves** (`60-evdev.hwdb:18`, `60-keyboard.hwdb:49`,
`70-mouse.hwdb:34`, `70-pointingstick.hwdb:30` — each the boilerplate
"`#   udevadm hwdb --update`" instruction). No init script, no `S*` service, no
Moog binary invokes it. **[READ]** `<R>/etc/init.d/S10udev` runs only
`udevd -d`, two `udevadm trigger`s and `udevadm settle --timeout=30`.

**[INFERRED]** Therefore on every boot of a stock instrument the hwdb is absent
and every `IMPORT{builtin}="hwdb …"` returns non-zero. Evidence: the three reads
above, plus **[READ]** the udevd diagnostic `IMPORT builtin '%s' returned
non-zero` at `0x2ca41`.

### 4.1 The twelve dead lines

**[READ]** `grep -rn hwdb` over all three rules directories:

| file:line | what is lost |
|---|---|
| `50-udev-default.rules:13` | `hwdb --subsystem=usb` on every `usb_device` |
| `50-udev-default.rules:15` | `hwdb --subsystem=$env{SUBSYSTEM}` on every device with a `MODALIAS` |
| `60-evdev.rules:7` | `evdev:` prefix lookup **and** the `RUN{builtin}+="keyboard"` on the same line |
| `60-evdev.rules:12` | `evdev:atkbd:` + `keyboard` builtin |
| `60-evdev.rules:16` | `evdev:name:…` + `keyboard` builtin |
| `60-serial.rules:7` | `hwdb --subsystem=pci` |
| `60-serial.rules:8` | `hwdb --subsystem=usb` |
| `70-mouse.rules:9` | `mouse:usb:…` quirks |
| `70-mouse.rules:12` | `mouse:bluetooth:…` quirks |
| `70-mouse.rules:15` | `mouse:ps2:…` quirks |
| `75-net-description.rules:8` | `hwdb --subsystem=usb` on net devices |
| `75-net-description.rules:12` | `hwdb --subsystem=pci` on net devices |
| `78-sound-card.rules:40` | bare `hwdb` lookup on the sound card |
| `90-libinput-model-quirks.rules:25,30,34` | all three libinput quirk lookups |

**[INFERRED]** The consequence is *not* uniform, because a failed `IMPORT`
aborts the remainder of **that rule line only**:

* Where the hwdb import is the last token on its line (`50-udev-default:13,15`,
  `60-serial:7,8`, `75-net-description:8,12`, `78-sound-card:40`) the only loss
  is the `*_FROM_DATABASE` properties. Note that on `50-udev-default:13` the
  preceding `IMPORT{builtin}="usb_id"` has **already run and already added its
  properties** before the hwdb import fails, so `ID_VENDOR_ID`/`ID_MODEL_ID`
  survive — only the human-readable name is lost.
* Where the hwdb import **gates further action on the same line**, that action
  is lost too. This is the real damage, and it is confined to input devices:
  `60-evdev.rules` lines 7, 12 and 16 each end `RUN{builtin}+="keyboard",
  GOTO="evdev_end"`. All three fail, so **no scancode remapping and no
  force-release quirks are ever applied**, and the file falls through to its
  `LABEL="evdev_end"` doing nothing at all. `70-mouse.rules` behaves the same
  way and is likewise wholly inert.

**[READ]** What this costs concretely: the shipped
`<R>/etc/udev/hwdb.d/20-usb-vendor-model.hwdb:50579-50580` contains

```
usb:v20B1*
 ID_VENDOR_FROM_DATABASE=XMOS Ltd
```

so a working hwdb would label the instrument's own XMOS USB device by vendor
name. **[READ]** `20-OUI.hwdb` likewise resolves `8C:AE:4C` →
`ID_OUI_FROM_DATABASE=Plugable Technologies`, and **[READ]** `net_id` contains
the format string `OUI:%02X%02X%02X%02X%02X%02X` at `0x2d2c2`, i.e. it *does*
attempt a MAC-OUI hwdb lookup on every network interface. That lookup fails too.

**[INFERRED]** None of this is load-bearing for audio, MIDI or the control
plane. It is load-bearing for anyone reading `udevadm info` output on the
instrument and wondering why every `*_FROM_DATABASE` property is missing — the
answer is here, not in the kernel.

---

## 5. Rule load order, and a correction to the brief

**[INFERRED]** udev merges all scanned directories and processes rule *files* in
basename sort order (standard udev semantics; I did not disassemble
`conf_files_list` to confirm, hence the grade). With Moog's four in
`/etc/udev/rules.d` that gives:

```
20-xmos-nic          (Moog)
30-usb-nic           (Moog)
40-usb-thumbdrive    (Moog)
50-eth-ext-nic       (Moog)
50-udev-default
60-block
60-cdrom_id
60-drm
60-evdev
60-persistent-alsa
60-persistent-input
60-persistent-storage
60-persistent-storage-tape
60-persistent-v4l
60-serial
64-btrfs
70-mouse
75-net-description
75-probe_mtd
78-sound-card
80-drivers
80-libinput-device-groups
80-net-name-slot
90-libinput-model-quirks
```

**The gap brief states that `60-persistent-storage.rules` "creates the
`/dev/disk/by-*` links that run *before* Moog's `40-usb-thumbdrive.rules` fires
`mount`". The conclusion is right; the stated mechanism is wrong.** `40-` sorts
*before* `60-`, so Moog's rule is *parsed* first. The by-`*` links nevertheless
exist before the mount happens, because **[INFERRED]** `RUN+=` commands are
collected during rule processing and executed only after all rules have been
processed and the device node has been set up — so Moog's three `RUN`s
(`mkdir`, `mount`, `sort-part.sh`) fire last, after `60-persistent-storage` has
run `blkid` and created the symlinks. The distinction matters if anyone ever
tries to reorder these files by renaming them: renaming `40-` to `70-` would
change *nothing*, because the ordering that produces this outcome is
`RUN`-deferral, not filename sort.

---

## 6. `50-udev-default.rules` — the one that actually shapes `/dev`

**[READ]** 77 lines, and the only upstream rule whose effects are visible
everywhere. Relevant on this hardware:

* `:4-5` — `ACTION=="remove", ENV{REMOVE_CMD}!="", RUN+="$env{REMOVE_CMD}"`,
  then an unconditional `GOTO="default_end"` on remove.
* `:19-26` — tty ownership: `ptmx` and `tty` at `0666` group `tty`,
  `tty[0-9]*` at `0620`, and `KERNEL=="tty[A-Z]*[0-9]…", GROUP="dialout"`.
  **[INFERRED]** this is what gives `/dev/ttymxc1` (the serial console, from
  `console=ttymxc1,115200` **[READ]** `runtime-state.txt:2`) group `dialout`.
* `:30-31` — `SUBSYSTEM=="input", GROUP="input"`.
* `:33-36` — `video4linux`, `graphics`, `drm`, `dvb` → group `video`.
* `:38-39` — `SUBSYSTEM=="sound", GROUP="audio"`, plus
  `OPTIONS+="static_node=snd/seq"` and `static_node=snd/timer`. **[INFERRED]**
  These two static nodes are created by udev at start-up regardless of whether
  the ALSA sequencer/timer modules are present, which is why `/dev/snd/seq` and
  `/dev/snd/timer` exist on a kernel with no loadable modules at all.
* `:41` — `SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", MODE="0664"`.
* `:55-56` — `SUBSYSTEM=="block", GROUP="disk"`. This is what makes the USB
  stick's `/dev/sda1` group `disk`.
* `:73` — `KERNEL=="tun", MODE="0666", OPTIONS+="static_node=net/tun"`.
* `:75` — `KERNEL=="fuse", MODE="0666", OPTIONS+="static_node=fuse"`.

**[READ]** Every group named by this file exists in `<R>/etc/group`:
`tty:5`, `disk:6`, `lp:7`, `kmem:9`, `cdrom:11`, `dialout:18`, `video:28`,
`audio:29`, `tape:32`, and `input:1002` (buildroot-assigned, non-standard).
**[INFERRED]** so udev logs no "unknown group" errors from this file — a
failure mode worth ruling out explicitly, because it would silently leave
device nodes root-owned.

---

## 7. `60-block.rules` — two live side effects

**[READ]** 14 lines.

* `:4-5` — sets `block.events_dfl_poll_msecs` to 2000 if it is 0. Media-presence
  polling.
* `:11` — `ACTION!="remove", SUBSYSTEM=="block",
  KERNEL=="loop*|nvme*|sd*|vd*|xvd*", OPTIONS+="watch"`. **[INFERRED]** This
  installs an inotify watch on `/dev/sda` and `/dev/sda1`; when a userspace
  process that opened the block device for writing closes it, udev synthesises a
  `change` event and re-runs the whole rule set for that device. Note the
  pattern does **not** include `mmcblk*`, so the eMMC is not watched.
* `:14` — `SUBSYSTEM=="block", ACTION=="add", ATTR{queue/rotational}=="0",
  ATTR{queue/scheduler}="noop"`. **[INFERRED]** the eMMC and any USB stick
  report `rotational=0`, so **the I/O scheduler for `mmcblk2` is set to `noop`
  by this upstream udev rule** — not by the kernel default and not by anything
  Moog wrote. That is a genuine, non-obvious performance-relevant behaviour
  hiding in this layer, on a machine whose whole design is about latency.

**[UNKNOWN]** whether `noop` is also the kernel's compiled default here; if it
is, the rule is a no-op. `cat /sys/block/mmcblk2/queue/scheduler` settles it
(§16).

---

## 8. Storage: `60-persistent-storage.rules`

**[READ]** 83 lines. Gate at `:9`:

```
KERNEL!="loop*|mmcblk*[0-9]|msblk*[0-9]|mspblk*[0-9]|nvme*|sd*|sr*|vd*|xvd*|bcache*|cciss*|dasd*|ubd*", GOTO="persistent_storage_end"
```

**[INFERRED]** `mmcblk*[0-9]` matches `mmcblk2`, `mmcblk2p1`…`mmcblk2p7`, and
also `mmcblk2boot0`, `mmcblk2boot1` (they end in a digit). So on every boot this
rule runs `IMPORT{builtin}="blkid"` (`:66`) against the whole eMMC and each of
its partitions, then creates:

* `:69` `/dev/disk/by-uuid/$ID_FS_UUID_ENC`
* `:70` `/dev/disk/by-label/$ID_FS_LABEL_ENC`
* `:44-46` `/dev/disk/by-id/mmc-<name>_<serial>` and `-part%n` for MMC
* `:55-56` `/dev/disk/by-path/<ID_PATH>` and `-part%n`

**[INFERRED]** The eMMC by-`*` links are created but **nothing uses them**:
`<R>/etc/fstab` **[READ]** names every filesystem by kernel device
(`/dev/mmcblk2p2`, `p3`, `p4`, `p6`, `p7`), and the kernel command line
**[READ]** `runtime-state.txt:2` uses `root=/dev/mmcblk2p3`. The persistent-name
machinery runs and is then ignored.

### 8.1 The external helpers are never reached on this hardware

Tracing each `IMPORT{program}` against the device inventory actually present
(**[READ]** `runtime-state.txt:174-189` mounts, `:96-98` `scsi_eh_0`/
`usb-storage` kernel threads, and the DTB):

| helper | call site | why it does not fire |
|---|---|---|
| `ata_id` | `:22` | needs `SUBSYSTEMS=="scsi", ATTRS{vendor}=="ATA"` — a USB mass-storage stick reports its own vendor string |
| `ata_id` | `:25` | needs `ATTRS{type}=="5"` (CD-ROM) |
| `ata_id` | `:28` | needs `ATTR{removable}=="0"` — a thumb drive reports removable |
| `scsi_id` | `:34,:35` | both guarded by `ENV{ID_SERIAL}!="?*"`, but `:31` (`SUBSYSTEMS=="usb", IMPORT{builtin}="usb_id"`) has already **set** `ID_SERIAL` for a USB stick, so the guard fails |
| `cdrom_id` | `60-cdrom_id.rules:12,16` | file exits at `:5` unless `KERNEL=="sr[0-9]*\|xvd*"`; no optical device exists |
| `scsi_id` | `60-persistent-storage-tape.rules:8,16` | needs `scsi_generic` type 8 or `scsi_tape`; none exists |
| `v4l_id` | `60-persistent-v4l.rules:7` | needs `SUBSYSTEM=="video4linux"`; no V4L device in the DTB or live tree |
| `collect` | — | **referenced by no rule in any of the three directories** |

**[INFERRED]** So five of the six `/lib/udev` helpers are dead weight on this
machine, and `collect` is dead weight on any machine using these rules. The
sixth, `mtd_probe`, is the open question — §11.

### 8.2 What an untrusted stick can name

**[READ]** `:70` creates `/dev/disk/by-label/$env{ID_FS_LABEL_ENC}` from the
filesystem label, which is attacker-controlled on removable media.
**[INFERRED]** path traversal is blocked: the `_ENC` form is blkid's escaped
variant (`/` and non-printables become `\x..`), and udevd carries the
`string_escape=` / `replace` option machinery **[READ]** (`0x2c80f`, `0x2c823`)
plus a `/dev/` prefix constant at `0x2cb6a` used for symlink creation. The
residual exposure is that a crafted label creates an attacker-*named* symlink
inside `/dev/disk/by-label/` — bounded, and nothing on this instrument reads
that directory.

---

## 9. `80-drivers.rules` and the empty module index

**[READ]** `<R>/lib/udev/rules.d/80-drivers.rules:5`:

```
ENV{MODALIAS}=="?*", RUN{builtin}+="kmod load $env{MODALIAS}"
```

plus six fixed `kmod load` lines for `tifm`, `memstick`, `i2o`, `parport_pc`,
and `sm_ftl` (`:6-11`).

**[READ]** `<R>/lib/modules/4.1.15-rt18/` contains exactly two `.ko` files
(`imx_rpmsg_tty.ko`, `imx_rpmsg_pingpong.ko`) and:

```
modules.alias      45 B   → "# Aliases extracted from modules themselves."  (comment only)
modules.symbols    49 B   → comment only
modules.devname    52 B   → comment only
modules.softdep    55 B   → comment only
modules.dep        83 B   → the two .ko paths, no dependencies
```

**[READ]** `modules.alias.bin` is 12 bytes:
`b007 f457 0002 0001 0000 000c` — the kmod index magic `0xB007F457`, version
2.1, root node offset 12, i.e. **the header with an empty root: zero alias
entries**. `modules.symbols.bin` is byte-identical.

**[INFERRED]** `kmod load <modalias>` can therefore never resolve a module.
**[READ]** the udevd diagnostic for exactly this path exists at `0x2dd0c`:
`No module matches '%s'`.

**[READ]** Live confirmation, from a category `CAVEAT-runtime-state.md`
explicitly certifies as uncontaminated: `runtime-state.txt:191-192` shows
`lsmod` output with a header row and **no module rows at all**. Nothing is
loaded, including the two `.ko` files that exist.

**[INFERRED]** `80-drivers.rules` runs on every device event, evaluates
`ENV{MODALIAS}=="?*"` (true for most platform and USB devices), invokes the
`kmod` builtin, and it fails every time. Harmless, but it is per-event work on a
machine that spends 30 seconds in `udevadm settle` **[READ]**
(`S10udev:35`, and `init-boot.md:238` budgets "up to 30 s" for this step).

---

## 10. `80-net-name-slot.rules` is a guaranteed no-op

**[READ]** the whole file:

```
ACTION!="add", GOTO="net_name_slot_end"
SUBSYSTEM!="net", GOTO="net_name_slot_end"
NAME!="", GOTO="net_name_slot_end"
IMPORT{cmdline}="net.ifnames"
ENV{net.ifnames}=="0", GOTO="net_name_slot_end"
NAME=="", ENV{ID_NET_NAME_ONBOARD}!="", NAME="$env{ID_NET_NAME_ONBOARD}"
NAME=="", ENV{ID_NET_NAME_SLOT}!="",    NAME="$env{ID_NET_NAME_SLOT}"
NAME=="", ENV{ID_NET_NAME_PATH}!="",    NAME="$env{ID_NET_NAME_PATH}"
```

**[READ]** `net.ifnames` appears nowhere in `<R>/boot/cmdline.txt`,
`<R>/boot/cmdline.img`, `<R>/etc` or `<R>/usr/share`, and not in the live
`/proc/cmdline` (`runtime-state.txt:2`). So the `ENV{net.ifnames}=="0"` escape
is **not** taken — predictable naming is nominally *enabled*.

It still does nothing, because the three properties it consumes are never set.
**[READ]** the complete string vocabulary of the `net_id` builtin in
`<R>/sbin/udevd`, `0x2d24c`–`0x2d3d1`:

```
/config  ifindex  iflink  wlan  wwan  addr_assign_type
%x:%x:%x:%x:%x:%x        %sx%02x%02x%02x%02x%02x%02x     ID_NET_NAME_MAC
OUI:%02X%02X%02X%02X%02X%02X
ccwgroup  ccw%s          ID_NET_NAME_PATH
acpi_index  dev_port  label  %x:%x:%x.%u  p%us%u  %s/slots  %s/%s/address
ID_NET_NAME_ONBOARD  ID_NET_LABEL_ONBOARD  ID_NET_NAME_SLOT
usb_interface  %s%s%s
bcma  bcma%*u:%u
net_id  "Network device properties"
```

**[INFERRED]** Every prefix-producing path is PCI-based (`p%us%u`, `%s/slots`,
`acpi_index`, `label`) or s390 (`ccw`). `names_usb` contributes only a *suffix*,
composed by `%s%s%s` onto a PCI path. There is **no** `names_platform`, no
device-tree/OF naming, and no `names_vio`. The only non-PCI producer is
`names_mac` → `ID_NET_NAME_MAC` — which this rule file never reads.

**[READ]** The board has PCIe enabled (`/soc/pcie@0x01000000`,
`compatible = fsl,imx6q-pcie,snps,dw-pcie`, `status = okay`, parsed from
`<R>/boot/imx6dl-profili-som.dtb`), so the PCI paths are not structurally
impossible — but no network device is behind it. **[READ]** the on-board FEC,
`/soc/aips-bus@02100000/ethernet@02188000` (`fsl,imx6q-fec`), is
**`status = "disabled"`**. **[INFERRED]** every network interface on this
machine is USB-attached, hence parented by `ci_hdrc` on `aips-bus` with no PCI
ancestor, hence unnameable by `net_id`.

**[READ]** Live outcome, `runtime-state.txt:166-172`:

```
1: lo
2: usbint  inet 203.0.113.1/24
3: ethext  inet 192.168.1.136/24  (+ .138 secondary)
```

No `enp*`, no `enx*`, no `eth0` remnant. Consistent with the analysis.

**[INFERRED]** Practical consequence: Moog's `usb-int.sh` / `usb-ext.sh` /
`eth-ext.sh` receive `%k` as the plain kernel name and their
`ip link set $1 name …` succeeds. They would have survived a rename anyway
(udev updates a renamed net device's sysname before running `RUN`), but nobody
should rely on that — the reason they work is that this rule is inert.

**[READ]** Incidental, and relevant to `network.md` rather than to me:
`20-OUI.hwdb` resolves `8C:AE:4C` (`30-usb-nic.rules` → `usbext`) to
**Plugable Technologies**, a USB-Ethernet adapter vendor. `A4:11:63`
(`50-eth-ext-nic.rules` → `ethext`) is **not present** in the shipped OUI
database at all, in any prefix length. Flagged in §15.

---

## 11. MTD: the one genuinely open question

**[READ]** `<R>/lib/udev/rules.d/75-probe_mtd.rules` is four active lines:

```
ACTION!="add", GOTO="mtd_probe_end"
KERNEL=="mtd*ro", IMPORT{program}="mtd_probe $devnode"
LABEL="mtd_probe_end"
```

**[READ]** `<R>/lib/udev/mtd_probe` is a 3 884-byte ARM ELF whose entire import
list is `open64/read/memcmp/ioctl/lseek64/malloc/free/perror/puts/abort` — it
reads the device and emits at most `MTD_FTL=smartmedia`, which
`80-drivers.rules:11` would turn into `kmod load sm_ftl` (which cannot succeed,
§9).

**[READ]** The board **does** have NAND enabled:
`/soc/gpmi-nand@00112000`, `compatible = fsl,imx6q-gpmi-nand`,
**`status = "okay"`**. **[READ]** the MTD core is built into the kernel, not
modular — `<R>/lib/modules/4.1.15-rt18/modules.builtin` lists `mtd.ko`,
`ofpart.ko`, `cmdlinepart.ko`, `mtd_blkdevs.ko`, `mtdblock.ko` and the CFI chip
drivers.

**[UNKNOWN]** whether an MTD chip is actually populated on this SOM. Nothing
mounts an MTD device (**[READ]** `runtime-state.txt:174-189` — root is
`/dev/mmcblk2p3`, everything else is eMMC or tmpfs), and the harvest did not
capture `/proc/mtd` or `/dev`. If MTD devices do exist, `75-probe_mtd.rules` is
the one upstream rule with an unresolved dependency on a `/lib/udev` helper —
see §13. Resolved by one read-only command (§16).

---

## 12. ALSA: what these rules do, and what they do not

The gap brief's premise here should be corrected. It states that
`60-persistent-alsa.rules` and `78-sound-card.rules` "are what make ALSA card
numbering stable" and that they "can confirm or overturn" `audio-io.md:230`.
**They can do neither.** Card *index* assignment is performed by the ALSA core
in the kernel when a card registers; **[READ]** neither rule file contains any
token that sets, reserves or reorders a card index — `60-persistent-alsa.rules`
emits only `SYMLINK+=` entries under `/dev/snd/by-id/` and `/dev/snd/by-path/`,
and `78-sound-card.rules` sets only `ENV{}` properties plus one re-emitted
event. udev cannot renumber an ALSA card.

What they actually do here:

**[READ]** `60-persistent-alsa.rules:5` gates on `KERNEL!="controlC[0-9]*"`, so
only `controlC0` reaches the body. `:7-9` need `SUBSYSTEMS=="usb"` and
`ID_SERIAL` for a `by-id` link. **[INFERRED]** the card is **not** USB — it is
an ASoC platform card: **[READ]** the DTB node `/sound-xmos-esai`,
`compatible = fsl,imx-audio-xmos-esai`, with `esai@02024000` `status = "okay"`
and codec node `xmos_codec@11`. So **no `/dev/snd/by-id/` link is created**.
`:11-12` then run `IMPORT{builtin}="path_id"` and create
`/dev/snd/by-path/$ID_PATH`; **[READ]** `path_id` does support platform devices
(format string `platform-%s` at `0x2d634`), so **[INFERRED]** a single
`/dev/snd/by-path/platform-…` link should exist. Testable (§16).

**[READ]** `78-sound-card.rules:5` — `ACTION=="add|change", KERNEL=="controlC*",
ATTR{../uevent}="change"` — writes to the parent card's `uevent` to synthesise a
`change` event once all child nodes exist, and `:38` sets
`ENV{SOUND_INITIALIZED}="1"`. **[INFERRED]** this is a PulseAudio-oriented
synchronisation mechanism; nothing on this instrument consumes it (there is no
PulseAudio, and `scsynth` opens `hw:0,0` directly), so its only effect is one
extra `change` event per boot which re-runs the whole rule set for the card.

**[READ]** `:65-87` classify form factor by model-string matching; all are
preceded by `:40`'s failing `IMPORT{builtin}="hwdb"` for the database-derived
variants, and the card's `ID_MODEL` is unset for a platform card, so
**[INFERRED]** `SOUND_FORM_FACTOR` and `SOUND_CLASS` are never set.

### 12.1 `audio-io.md:230` is confirmed, from a source it did not cite

`audio-io.md:230` marks **[INFERRED]** "There is no card 3 — there is only card
0", resting on `runtime-state.txt`'s ALSA block. That verdict is untouched by
this layer, and I can now corroborate it **from the device tree**, which is
independent of the runtime capture and immune to its contamination:

**[READ]** parsing `<R>/boot/imx6dl-profili-som.dtb`:

```
/sound             status = "disabled"
/sound-hdmi        status = "disabled"
/sound-xmos-esai   (no status property → defaults to okay)
```

**[INFERRED]** exactly one ASoC machine driver can register, so exactly one card
can exist, so it is card 0. `/.jackdrc`'s `-dhw:3` is dead, as `audio-io.md`
says. No conflict; the claim is strengthened and its grade could arguably be
raised.

---

## 13. `UDEVLIBEXECDIR`, and how far I can honestly take it

Relative program names in `IMPORT{program}` / `RUN+=` are resolved against
udev's compiled libexec directory. Which one is it here, given two candidate
trees?

**[READ]** `<R>/sbin/udevd` file offset `0x2b4d3` holds the string
`/usr/lib/udev/` (with trailing slash), sitting immediately between
`pipe failed: %m` (`0x2b4c3`) and `starting '%s'` (`0x2b4e2`) — both of which
are diagnostics from udev's process-spawn function.

**[READ]** A control test rules out the naive inference: I searched for a 32-bit
absolute pointer to that string and found none — but the same search finds no
pointer to `pipe failed: %m`, `starting '%s'` or `open /dev/null failed: %m`
either, while it *does* find two references to `/etc/udev/rules.d` (which lives
in a pointer array). Strings passed directly as function arguments are loaded
via `movw`/`movt` or PC-relative arithmetic on ARM and leave no searchable
pointer. **Absence of a pointer proves nothing here**, which is why I am not
claiming more than the following.

**[INFERRED]** `UDEVLIBEXECDIR = /usr/lib/udev`, on three pieces of evidence:
(a) the string's position inside the spawn function's string cluster;
(b) the trailing slash, the signature of a `UDEVLIBEXECDIR "/"` concatenation;
(c) libinput installed its two helpers into `/usr/lib/udev/`, which is what a
package does after detecting udev's advertised libexec directory at build time.

**[INFERRED]** If that is right, the six helpers in `/lib/udev` are **not
resolvable by relative name**, and every rule that calls one by bare name would
fail. Per §8.1 the practical blast radius is nil for `ata_id`, `cdrom_id`,
`scsi_id`, `v4l_id` and `collect` — none of them can fire on this hardware
anyway — and is confined entirely to `mtd_probe` (§11), which fires only if MTD
devices exist.

**[UNKNOWN]** I did not resolve the `movw`/`movt` pair to prove the value. This
is the weakest link in the document and I am flagging it as such rather than
rounding it up. Two read-only commands settle it (§16).

Note the asymmetry this creates, which is a genuine packaging inconsistency in
the image: **[READ]** rules are read from *both* `/lib/udev/rules.d` and
`/usr/lib/udev/rules.d` (§3.1), hwdb sources from `/etc/udev/hwdb.d` and
`/lib/udev/hwdb.d` (§3.1), while programs resolve against one directory only.
Three different search policies over two trees.

---

## 14. Input, and the two libinput rules nobody has looked at

**[READ]** `<R>/usr/lib/udev/rules.d/80-libinput-device-groups.rules` runs
`PROGRAM="libinput-device-group %S%p"` for every `event[0-9]*` device that has
an `ATTRS{phys}`, and sets `ENV{LIBINPUT_DEVICE_GROUP}="%c"`.

**[READ]** The board has input hardware: the DTB contains a `/gpio-keys` node
(`compatible = gpio-keys`) with a `Back` key, and **[READ]**
`runtime-state.txt:86` shows the kernel IRQ thread `[irq/189-Back]`.

**[INFERRED]** so this rule fires at least once per boot, invoking
`libinput-device-group` — which, per §13, is in `/usr/lib/udev` and is
therefore the *one* helper likely to be resolvable. `90-libinput-model-quirks`
is inert (§4.1, hwdb).

**[INFERRED]** `60-persistent-input.rules` runs `IMPORT{builtin}="input_id"`
(via `50-udev-default.rules:14`) and creates `/dev/input/by-path/` links for the
gpio-keys node (`:31-36`, `SUBSYSTEMS=="…platform…", IMPORT{builtin}="path_id"`).
Since `.INPUT_CLASS` is unset for a plain key device and the device is
`platform`, the applicable line is `:35-36` (empty-class platform fallback),
giving `/dev/input/by-path/platform-gpio-keys-event`. Testable (§16).

**[UNKNOWN]** whether the Moog front panel presents any evdev node at all beyond
`gpio-keys`; the panel is polled by `las-frontpanel-poll` over its own
transport, and the harvest captured no `/dev/input` listing.

---

## 15. The build-tree leak: `.sort-part.sh.swp`

**[READ]** `<R>/etc/udev/rules.d/.sort-part.sh.swp`, 12 288 bytes, shipped in
both the 1.5.0 and 1.8.2 images. It is a Vim swap file, and it has never been
mentioned in any prior report.

`file` identifies it as: `Vim swap file, version 8.0, pid 26149, user chris,
host terry, file ~chris/fe-buildroot/board/moog/las-profili-prod/rootfs_overlay/etc/udev/rules.d/sort-part.sh, modified`.

**[READ]** Header fields decoded from the raw bytes:

| field | offset | value |
|---|---|---|
| magic | `0x00` | `b0VIM 8.0` |
| page size | `0x0c` | 4096 |
| file mtime | `0x10` | `0x59f9cd1e` = **2017-11-01 13:33:18 UTC** |
| inode | `0x14` | 729354 |
| pid | `0x18` | 26149 |
| user | `0x1c` | `chris` |
| host | `0x40` | `terry` |
| path | `0x6c` | `~chris/fe-buildroot/board/moog/las-profili-prod/rootfs_overlay/etc/udev/rules.d/sort-part.sh` |

**[READ]** The data block (page 2, `0x2f85`–`0x2fff`) holds an **earlier,
different draft** of the script than the one that shipped:

```
#!bin/bash
declare -A array
PARTS=`ls /media/ | tr " " "\n" | awk -F "s" '{print "\"dev/s" $2"\""}'`
for PART in $PARTS
```

against the shipped `<R>/etc/udev/rules.d/sort-part.sh`, which uses `MOUNTS`,
`declare -A LIST`, and a correct `#!/bin/bash`. **[INFERRED]** the draft is the
buggy predecessor — note the broken shebang `#!bin/bash` (missing leading
slash) and the extra quoting in the `awk` action — and the swap file was left
behind when the editor exited abnormally, then committed into the overlay.

**What this establishes, and it is new:**

* **[INFERRED]** `/etc/udev/rules.d` is a hand-maintained **buildroot
  `rootfs_overlay`** directory, structurally distinct from `/lib/udev` and
  `/usr/lib/udev`, which buildroot installs from the `eudev` and `libinput`
  packages. This is the mechanical reason the two layers differ so much in
  style and quality, and it predicts that anything Moog adds will land in
  `/etc/udev/rules.d` and sort **before** every upstream rule (§5).
* **[READ]** The buildroot tree is named `fe-buildroot`, the board directory is
  `board/moog/las-profili-prod`, matching the DTB name `imx6dl-profili-som`.
* **[READ]** Build-host identity: user `chris`, host `terry`, Vim 8.0, and a
  November 2017 timestamp — roughly a year before the Moog One shipped.
* **[INFERRED]** The file is inert at runtime: udev loads only `*.rules` from
  its rules directories, and a dotfile ending `.swp` is not matched. It is a
  disclosure artefact, not a functional one.

**[READ]** Also worth noting for anyone diffing permissions: all four Moog
`.rules` files and all four `.sh` helpers in `/etc/udev/rules.d` are mode
`0755`, i.e. rule *data* files carry the executable bit. Harmless; udev does not
care. The upstream rules in `/lib/udev/rules.d` are all `0644`.

---

## 16. 1.5.0 vs 1.8.2: the layer is frozen

**[READ]** MD5 comparison of every file in the layer between
`<R15>` (dated 2021-11-15 / 2022-05-16) and `<R>` (2025-09-15):

| group | result |
|---|---|
| all 18 `lib/udev/rules.d/*.rules` | **identical** |
| both `usr/lib/udev/rules.d/*.rules` | **identical** |
| `usr/lib/udev/hwdb.d/90-libinput-model-quirks.hwdb` | **identical** |
| all 14 `etc/udev/hwdb.d/*.hwdb` | **identical** |
| all 4 Moog `.rules` + all 4 `.sh` + `udev.conf` | **identical** |
| `lib/udev/mtd_probe` | **identical** |
| `lib/udev/{ata_id,cdrom_id,collect,scsi_id,v4l_id}` | differ |
| `usr/lib/udev/libinput-{device-group,model-quirks}` | differ |
| `sbin/udevd`, `usr/bin/udevadm` | differ |

**[READ]** Both `udevd` binaries report `udev-3.1.5`, and both contain the same
`/etc/udev/hwdb.bin does not exist` string; `<R15>` likewise contains **no**
`hwdb.bin`. Sizes: `udevd` 223 816 → 223 840 B; `udevadm` 231 600 B in both.

**[INFERRED]** The binaries were rebuilt (differing build IDs / embedded paths)
without a version change; the *configuration* of this layer has not been touched
in the ~4 years between the two releases. Nobody at Moog has revisited it, which
is consistent with the hwdb never having been noticed.

**[READ]** `captures/rootfs-1.5.0` is present and complete for this layer — the
gap brief's caveat about it possibly still extracting does not apply.

---

## 17. Conflicts with existing docs

Reported, not fixed, per instruction.

1. **The gap brief's ALSA premise.** It states these rules "are what make ALSA
   card numbering stable" and can "confirm or overturn" `audio-io.md:230`. They
   do not touch card numbering (§12). `audio-io.md:230` is unaffected, and is
   independently corroborated by the DTB (§12.1).

2. **The gap brief's ordering claim.** "`60-persistent-storage.rules` creates
   the `/dev/disk/by-*` links that run *before* Moog's `40-usb-thumbdrive.rules`
   fires `mount`." The outcome is right, the mechanism is wrong: `40-` sorts
   before `60-`; the ordering comes from `RUN`-deferral (§5).

3. **Rule and database counts.** The brief says 18 upstream rules and 15 hwdb
   files in `etc/udev/hwdb.d`. Counting both libexec trees the rule count is
   **20**, not 18 (§2). The hwdb figure of 15 is right only if both trees are
   counted: `etc/udev/hwdb.d` holds 14, `usr/lib/udev/hwdb.d` holds 1 — and the
   split matters, because udevadm searches `/lib/udev/hwdb.d`, not
   `/usr/lib/udev/hwdb.d` (§3.1).

4. **`hwdb` coverage in `init-boot.md`.** `init-boot.md:1643` refers to the
   hwdb files only as "vendor-ID tables" encountered incidentally while grepping
   for `usb_gadget`. That is accurate as far as it goes, but the document does
   not record that they are never compiled and never read. Not a contradiction —
   a gap that this report fills.

5. **Architecture premise: "eth0/ethext is cdc_ether over that same link."**
   Outside my assignment, but my reads bear on it and it should be checked by
   whoever owns `network.md`: the on-board FEC is **`status = "disabled"`** in
   the DTB (§10), `8C:AE:4C` (→ `usbext`) is **Plugable Technologies**, a
   USB-Ethernet dongle vendor (§10), and `A4:11:63` (→ `ethext`) is absent from
   the shipped OUI database entirely. `ethext` held the studio-LAN address
   `192.168.1.136` while `usbint` held `203.0.113.1` **[READ]**
   (`runtime-state.txt:168-172`). I make no claim as to what `ethext` is; I
   record that the FEC is disabled and that the two rules match two different
   non-XMOS OUIs.

---

## 18. Validation plan — read-only, for a human to run

None of these was run. All are read-only; none writes, mounts, loads or
triggers. `udevadm test` is deliberately excluded — it re-runs rules and,
although documented as non-destructive, it is not worth the risk on this box.

```sh
# §4 — the headline. Expect: No such file.
ls -l /etc/udev/hwdb.bin

# §4 — confirm udev is complaining. Expect the "does not exist" line.
grep -i hwdb /var/log/messages | tail -20

# §13 — settles UDEVLIBEXECDIR without running anything.
#        Expect exactly one of these two to be non-empty.
ls -l /usr/lib/udev/ /lib/udev/

# §13 — the decisive one: which directory does udevd have open/mapped?
tr '\0' '\n' < /proc/$(pidof udevd)/cmdline; ls -l /proc/$(pidof udevd)/cwd
grep -c . /proc/$(pidof udevd)/maps

# §11 — the one open functional question. Expect empty if no NAND is populated.
cat /proc/mtd 2>/dev/null; ls -l /dev/mtd* 2>/dev/null

# §7 — is the noop scheduler actually being set by udev?
cat /sys/block/mmcblk2/queue/scheduler /sys/block/mmcblk2/queue/rotational

# §12 — predicted: a platform- link, and no by-id directory.
ls -lR /dev/snd/

# §8 — predicted: by-uuid/by-label/by-path present for mmcblk2*, unused.
ls -lR /dev/disk/

# §14 — predicted: platform-gpio-keys-event, and ID_INPUT* properties present
#        while every *_FROM_DATABASE property is absent.
ls -lR /dev/input/
udevadm info --query=property --name=/dev/input/event0

# §10 — predicted: ID_NET_NAME_MAC only; no ONBOARD/SLOT/PATH.
udevadm info --query=property --path=/sys/class/net/usbint
udevadm info --query=property --path=/sys/class/net/ethext

# §10 — the OUI question flagged in §17.5.
cat /sys/class/net/ethext/address /sys/class/net/ethext/addr_assign_type
readlink -f /sys/class/net/ethext

# §9 — expect empty module list.
lsmod; cat /proc/modules
```

---

## 19. What I did not do

* I did not resolve the `movw`/`movt` pair that loads `UDEVLIBEXECDIR`, so §13
  remains **[INFERRED]** rather than **[READ]**. This is the document's weakest
  claim.
* I did not disassemble `conf_files_list` to prove basename-sort ordering or
  `RUN`-deferral semantics (§5); both are graded **[INFERRED]** on standard udev
  behaviour.
* I did not examine `60-drm.rules`, `64-btrfs.rules` or
  `60-persistent-storage-tape.rules` beyond establishing that no matching
  hardware exists (no DRM-over-PCI/USB/platform match asserted; no btrfs
  filesystem; no tape).
* I did not audit the 14 hwdb databases for content beyond the three lookups
  quoted (XMOS vendor, the two NIC OUIs). They are inert, so content is moot
  unless someone builds the hwdb.
* I did not trace what, if anything, consumes `/dev/disk/by-*` or
  `/dev/snd/by-path/*` in `las-frontend`, `las-sc` or the `S*` scripts. Grep
  suggests nothing does, but I did not verify it against the binaries.
* I did not investigate the `S14fs` symlink construction beyond noting that
  `S14fs:28-31` creates `/var/local/media` **after** `S10udev` has already
  started, so a stick present at power-on races the directory that
  `40-usb-thumbdrive.rules` needs. That belongs to `init-boot.md`.
