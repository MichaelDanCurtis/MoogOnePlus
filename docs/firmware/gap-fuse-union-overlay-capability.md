# FUSE and unionfs-fuse: the only stacking filesystem this instrument has

Scope: the filesystem-FUSE stack — `fuse.ko`, `libfuse`, `fusermount`,
`unionfs`, `unionfsctl` — and the question the gap brief poses: *can a writable
layer be stacked over `/usr` using only software Moog ships, without writing to
flash, and does anything in the boot path already use it?*

Source: the decrypted v1.8.2 root filesystem at
`captures/firmware-1.8.2/rootfs-1.8.2` (written below as `<R>`), the **raw ext4
image** it was extracted from at `captures/firmware-1.8.2/pkg/rootfs.ext4`
(written as `<IMG>`), and `captures/rootfs-1.5.0` (`<R15>`) for comparison.
Live corroboration comes from `captures/dmesg-before-reboot.txt` and from
`captures/arch-harvest/runtime-state.txt` restricted to the categories its
`CAVEAT-runtime-state.md` marks uncontaminated (mounts, `lsmod`, kernel
cmdline).

No instrument was touched. No Moog binary was executed. Everything was read with
`strings`, `xxd`, `file`, `llvm-objdump -d --triple=armv7-none-linux-gnueabihf`,
and a purpose-written read-only ext4 inode parser (§3.1). Proposed live checks
are in §16 and are all read-only.

Every claim is graded **[READ]** (quoted from a file, with offset or line),
**[INFERRED]** (reasoning, with the evidence named), or **[UNKNOWN]**.

---

## 1. Headline

**The gap brief's central premise is wrong, and the error is an artifact of how
the firmware was unpacked.**

`/usr/bin/fusermount` **is setuid root.** Read straight out of the ext4
inode table in `<IMG>`: inode 5919, `mode=104755`, `uid=0`, `gid=0` — that is
`04755`, setuid, owner root **[READ, §3]**. The brief's question "whether
`fusermount`'s missing setuid bit matters" rests on `ls -l` of the *extracted*
tree, and the extraction dropped every setuid bit in the image: the extracted
`<R>` contains **zero** setuid files, while `<IMG>` contains **six** **[READ,
§3.2]**. Nothing about `fusermount`'s privileges is unusual. It is a stock,
correctly-installed, setuid-root FUSE helper.

Everything else the brief asserts about the FUSE stack holds up, and the answer
to the question it actually asks is **yes**:

* **FUSE is the only stacking filesystem in this kernel, and it is live.**
  `fuse.ko` is builtin; there is no overlayfs, aufs, unionfs or squashfs
  anywhere in `modules.builtin` **[READ, §4.1]** or in the kernel binary
  **[READ, §4.2]**. The single string `overlay` in the kernel image is the i.MX6
  framebuffer plane, not overlayfs **[READ, §4.3]**. On the real instrument the
  kernel prints `fuse init (API version 7.23)` at boot **[READ, §4.4]**.
* **Userspace is complete and correctly wired.** `libfuse` 2.9.5, `fusermount`
  2.9.5 setuid root, and `unionfs-fuse` 1.0 with copy-on-write support, all
  with resolvable dependencies **[READ, §5]**.
* **The two things that look like blockers are not.** The absent
  `/etc/fuse.conf` gates only `allow_other`/`allow_root`, and `getuid()==0`
  bypasses that gate entirely — verified in the disassembly at `0x11c2c`
  **[READ, §7]**. `fusermount`'s shelling out to `/bin/mount` (busybox, which
  would choke on `--no-canonicalize`) never happens, because `/etc/mtab` is a
  symlink to `/proc/mounts` and `mtab_needs_update()` returns 0 for a symlink —
  verified in the disassembly at `0x1387c` **[READ, §8]**.
* **Nothing in the firmware uses any of it.** A whole-tree content grep for
  `unionfs` or `fusermount` across all 6,035 files of `<R>` matches **only the
  four FUSE files themselves** **[READ, §10]**. No init script, no binary, no
  config. There is no COW residue (`.unionfs`, `_HIDDEN~`, `.fuse_hidden*`)
  anywhere **[READ, §10.2]**. `lsmod` on the live machine is empty and no FUSE
  mount exists **[READ, §10.3]**.

So: Moog ships a complete, working, entirely unused union-mount capability, and
it is the *only* one the kernel can offer.

A second correction, smaller but load-bearing for anyone planning to use `/mnt/u1`
as a branch: those partitions are **`noauto` and are not mounted at runtime**
(§11.2). The brief describes `etc/fstab` as mounting them ro; it declares them
ro, but `mount -a` skips `noauto` and the live mount table confirms their
absence.

---

## 2. Why this was worth reading

**[READ]** Grepping the documentation corpus — 62 `.md` files under `docs/` —
for `fusermount`, `unionfs`, `overlayfs`, `aufs`, `fuse.ko`, `libfuse` or
`/dev/fuse` returns **nothing at all**. Zero hits, all seven terms.

**[READ]** Every occurrence of the substring `fuse` in the corpus is one of
three unrelated senses, and I checked all ten:

| file:line | text | sense |
|---|---|---|
| `firmware/gap-uboot-env-and-flash-fuse-tooling.md:6` | "…exposes for fuse reading…" | i.MX6 OTP eFuse |
| `firmware/gap-uboot-env-and-flash-fuse-tooling.md:542` | "…from the NXP i.MX6 fuse map…" | OTP eFuse |
| `firmware/gap-uboot-env-and-flash-fuse-tooling.md:894` | "BootROM can be fused to boot from boot0" | OTP eFuse |
| `firmware/gap-uboot-env-and-flash-fuse-tooling.md:955` | "`/sys/fsl_otp/` … a fuse-blowing surface" | OTP eFuse |
| `arch/xmos-deep.md:961` | "if the JTAG security fuse is burned" | OTP eFuse |
| `firmware/network.md:196` | ``kill -9 `fuser 9799/udp` `` | busybox `fuser` |
| `firmware/gap-observability-toolkit.md:784` | "`busybox top`, `free`, `uptime`, `fuser`, `df`, `du`" | busybox `fuser` |
| `ASSUMPTIONS.md:25` | "Refuses rather than reporting" | English |
| `firmware/js-sandbox.md:341` | "should refuse `OSC` messages" | English |
| `arch/doc-audit.md:1168` | "\"Refuse to write\" describes…" | English |

The near-miss is worth naming explicitly, because it is the kind of thing that
produces a false "already covered": **`fuser` is not FUSE.** `<R>/usr/bin/fuser`
is a symlink to `../../bin/busybox` **[READ]** — the applet that lists processes
holding a file. It has no relationship to the filesystem-in-userspace stack.

---

## 3. The setuid correction, in full

This section is first because it overturns a premise, and because the method
matters for every other permission claim anyone makes from these extracted trees.

### 3.1 Method

`<R>` and `<R15>` are directory trees on a macOS HFS+/APFS volume, extracted by
an unprivileged process. Two things did not survive that:

**[READ]** Ownership. Every file in both trees reports `michaelcurtis staff`.
The real image has `uid=0 gid=0` throughout (§3.2). So the extraction discarded
uid/gid outright.

**[READ]** Device nodes. `<R>/dev/` contains only `log -> ../tmp/log`, `pts/`
and `shm/`. `<IMG>` `/dev` additionally contains `console`, `mode=020622` — a
character device **[READ, §6.2]**. macOS cannot create character devices without
privilege, so it was dropped.

Given two demonstrable losses, mode bits could not be trusted either. I wrote a
read-only ext4 parser (superblock → group descriptors → inode table → block-map
and extent-tree directory walk) and read the inodes directly out of `<IMG>`.
The parser is at
`/private/tmp/claude-501/-Volumes-Main-External-Development-MoogOnePlus/4498fa57-df38-4913-85d3-e2c8733e0bf5/scratchpad/ext4read.py`
(scratch, not part of the repo). It opens the image `'rb'` and never writes.

**[READ]** Image geometry, from the superblock: `block_size=1024`,
`inode_size=128`, `inodes_count=8320`, `blocks_per_group=8184`,
`inodes_per_group=104`, 64-bit feature off, descriptor size 32. Directory
inodes on this image use **classic block mapping**, not extents
(root inode flags `0x0`, `i_block[0]=0x14`) — worth recording because an
extent-only reader silently finds nothing here.

A full tree walk visited **7,684** directory entries, consistent with the 6,035
regular files plus directories and symlinks counted in `<R>`.

### 3.2 What the image actually says

**[READ]** The complete set of setuid/setgid inodes in `<IMG>`:

| path | mode | uid | gid | size |
|---|---|---|---|---|
| `/bin/busybox` | `104755` | 0 | 0 | 651144 |
| `/usr/bin/Xorg` | `104755` | 0 | 0 | 1629672 |
| `/usr/bin/cgexec` | `104755` | 0 | 0 | 8784 |
| **`/usr/bin/fusermount`** | **`104755`** | **0** | **0** | **20912** |
| `/usr/bin/screen` | `104755` | 0 | 0 | 318268 |
| `/usr/libexec/dbus-daemon-launch-helper` | `104755` | 0 | 0 | 37848 |

No setgid inodes at all.

**[READ]** The corresponding find over the extracted tree:
`find . -perm -4000 -type f` → empty; `find . -perm -2000 -type f` → empty. In
both `<R>` and `<R15>`.

**[READ]** The individual inodes for the FUSE stack in `<IMG>`:

| path | inode | mode | uid | gid | size |
|---|---|---|---|---|---|
| `/usr/bin/fusermount` | 5919 | `104755` (setuid) | 0 | 0 | 20912 |
| `/usr/bin/unionfs` | 1239 | `100755` | 0 | 0 | 76136 |
| `/usr/bin/unionfsctl` | 8207 | `100755` | 0 | 0 | 5748 |
| `/usr/lib/libfuse.so.2.9.4` | 6564 | `100755` | 0 | 0 | 156508 |

**[INFERRED]** The extraction dropped setuid across the board rather than
`fusermount` specifically. Evidence: all six setuid binaries in the image show
as `0755` in the tree, including `busybox`, which no packager would ship
non-setuid on a system whose `/bin/su` is a busybox symlink (§3.3).

**[INFERRED]** Mode bits *below* setuid did survive: the extracted tree shows
seven distinct file modes (`0644` ×4766, `0755` ×1242, `0664` ×11, `0444` ×7,
`0600` ×4, `0555` ×3, `0666` ×2). A extractor that flattened permissions would
not preserve `0600` and `0444`. So the loss is specific to the high bits, which
is the documented behaviour of unprivileged extraction. Any claim about setuid,
setgid, sticky, ownership, or device nodes in this project must be sourced from
`<IMG>`, never from `<R>`.

### 3.3 Corroboration that setuid is real and needed

**[READ]** `<IMG>` `/bin/su` is `mode=120777`, a symlink, target `busybox`
(7 bytes). Same for `/bin/mount` and `/bin/umount`. A busybox `su` applet is
non-functional unless `/bin/busybox` is setuid root — and it is.

### 3.4 Consequence for the brief's question

The brief asks "whether `fusermount`'s missing setuid bit matters when
everything runs as root". Two independent answers, both negative:

1. **[READ]** The bit is not missing.
2. **[READ, §7]** Even with the bit absent, it would not matter for a root
   caller. `fusermount`'s privilege-dependent checks are all guarded by
   `getuid()`, and `libfuse` mounts via `mount(2)` directly rather than via
   `fusermount` when it can (§9.2). Root needs no setuid helper.

The bit matters only for a **non-root** caller, and this instrument has no
non-root callers to speak of (§11.4).

### 3.5 What I could not check for 1.5.0

**[UNKNOWN]** I have no raw filesystem image for 1.5.0 — `captures/rootfs-1.5.0`
is an extracted tree only, and `captures/firmware-1.8.2/pkg/` has no 1.5.0
counterpart. So the 1.5.0 setuid bits are unverified. **[INFERRED]** They are
almost certainly identical: `fusermount` is byte-identical across the two
versions (§12), and the extracted 1.5.0 tree shows the same zero-setuid
signature that 1.8.2's extraction produced from an image that *does* have them.

---

## 4. The kernel side

### 4.1 `modules.builtin`

**[READ]** `<R>/lib/modules/4.1.15-rt18/modules.builtin`, 344 lines. Line 12:

    kernel/fs/fuse/fuse.ko

**[READ]** The complete `kernel/fs/` block, lines 1–31, is:
`binfmt_misc`, `binfmt_script`, `mbcache`, `autofs4`, `configfs`, `ext2`,
`ext3`, `ext4`, `fat`, `vfat`, `msdos`, **`fuse`**, `isofs`, `jbd`, `jbd2`,
`jffs2`, `lockd`, `nfs`, `nfsv2`, `nfsv3`, `nfsv4`, `nfs_acl`, `grace`,
`nls_base`, `nls_cp437`, `nls_ascii`, `nls_iso8859-1`, `nls_iso8859-15`,
`nls_utf8`, `ubifs`, `udf`.

**[READ]** Grepping the same 344 lines for `union|overlay|aufs|squash|fuse`
matches exactly one line — the `fuse.ko` line above. There is no
`kernel/fs/overlayfs/overlay.ko`, no aufs, no unionfs, no squashfs.

**[READ]** `modules.builtin` is identical byte-for-byte between `<R>` and
`<R15>` (`diff` clean). Both kernels are `4.1.15-rt18`.

**[INFERRED]** `fuse.ko` appearing in `modules.builtin` means `CONFIG_FUSE_FS=y`
— compiled into the kernel image, not loadable. `modules.builtin` is generated
by the kernel build from exactly that set.

### 4.2 The kernel binary agrees

`<R>/boot/uImage` is 5,060,456 bytes. **[READ]** Its U-Boot header:
magic `0x27051956`, name field `Linux-4.1.15-rt18`, `os=0x05` (Linux),
`arch=0x02` (ARM), `type=0x02` (kernel), `comp=0x00` (none) — so the payload at
`0x40` is a self-decompressing ARM zImage (zImage magic `0x016f2818` present at
`0x64`). Its inner gzip stream begins at `0x4758`; decompressed it is
10,214,816 bytes.

**[READ]** Banner in the decompressed image:

    Linux version 4.1.15-rt18 (root@terry) (gcc version 4.8.5
    (Buildroot 2016.02-rc2-dirty) ) #1 SMP PREEMPT RT Mon Sep 15 14:38:28 EDT 2025

**[READ]** Exact-match string counts in the decompressed kernel:

| filesystem name | count |
|---|---|
| `fuse` | 1 |
| `fuseblk` | 1 |
| `devtmpfs` | 1 |
| `overlay` | 1 (see §4.3 — not overlayfs) |
| `overlayfs` | 0 |
| `aufs` | 0 |
| `squashfs` | 0 |
| `unionfs` | 0 |
| `ecryptfs` | 0 |

**[READ]** The FUSE code is unmistakably present — a sample of the symbol and
message strings, with offsets into the decompressed image:

    845fed  4fuse: trying to steal weird page
    846058  fs/fuse/dev.c
    846068  fuse_request
    846078  fuse
    846080  fs/fuse/file.c
    846149  7fuse exit
    8461cd  6fuse init (API version %i.%i)
    8461f0  fuse_inode
    8461fc  %u:%u-fuseblk
    84620c  fuseblk
    8462a0  fusectl
    8c3309  fuse_dev_operations
    8c331d  fuse_dev_release
    8c332e  fuse_abort_conn
    8c3421  fuse_conn_init

**[READ]** `fusectl` is present, so `CONFIG_FUSE_FS` brings the control
filesystem too (mountable at `/sys/fs/fuse/connections`).

**[READ]** Two sysctl knobs exist: `fuse.max_user_congthresh` (`0x6ccd20`) and
`fuse.max_user_bgreq` (`0x6ccd3c`).

### 4.3 The one `overlay` string is not overlayfs

This is exactly the kind of single-token match that produces a wrong claim, so I
resolved it rather than counting it.

**[READ]** The string sits at `0x8567a0`. Its neighbours in the string table:

    8566cc  timeout when waiting for flip irq
    8566f0  Error updating SDC buf %d to address=0x%08lX, ...
    85675c  2-layer-fb-bg
    85676c  2-layer-fb-fg
    85677c  1-layer-fb
    856788  err: no display chan
    8567a0  overlay          <-- here
    8567ac  mxcfb
    8567b4  can not get alias id
    8567cc  disp_dev
    8567d8  mode_str
    8567e4  interface_pix_fmt
    8567f8  default_bpp

It is surrounded by i.MX6 IPU/framebuffer identifiers (`mxcfb`, `disp_dev`,
`interface_pix_fmt`, the layer names). **[INFERRED]** This is the framebuffer
*overlay plane* device-tree/parameter name, not the `overlay` filesystem type.
Corroborated by `modules.builtin` having no overlayfs entry (§4.1) and by
`overlayfs` scoring zero (§4.2).

**So FUSE is the only stacking/union filesystem this kernel can offer.** That is
the brief's claim, and it is confirmed twice over.

### 4.4 FUSE is not merely compiled in — it initialises on the real machine

**[READ]** `captures/dmesg-before-reboot.txt`, a capture from the owner's
instrument. Line 5 identifies the kernel:

    [    0.000000] Linux version 4.1.15-rt18 (root@terry) (gcc version 4.8.5
    (Buildroot 2016.02-rc2-dirty) ) #1 SMP PREEMPT RT Mon May 16 10:55:36 EDT 2022

Line 132:

    [    0.406545] fuse init (API version 7.23)

**[READ]** Surrounding lines, for the boot-order picture:

    [    0.141203] devtmpfs: initialized
    [    0.401981] VFS: Disk quotas dquot_6.6.0
    [    0.406545] fuse init (API version 7.23)
    [    1.364802] VFS: Mounted root (ext4 filesystem) readonly on device 179:3.
    [    1.366255] devtmpfs: mounted
    [    1.992679] udevd[170]: starting version 3.1.5

**[INFERRED]** That dmesg is from the **1.5.0** kernel (build date 2022-05-16;
the 1.8.2 kernel is 2025-09-15). It transfers to 1.8.2 with high confidence:
same kernel version string `4.1.15-rt18`, byte-identical `modules.builtin`
(§4.1), and the 1.8.2 kernel binary contains the same `fuse init (API version
%i.%i)` format string (§4.2).

**[READ]** Kernel FUSE protocol is **7.23**. **[INFERRED]** `libfuse` 2.9.5
(§5.3) implements an older minor and the two negotiate down to the lower on
`FUSE_INIT`; this is the normal, supported case and is why a 2.9.x userspace
runs on a newer kernel. The pairing here is stock Buildroot 2016.02 and is not
unusual.

---

## 5. Userspace inventory

### 5.1 The files

**[READ]** `find` for `fuse|union|overlay|aufs` over `<R>` returns exactly these
FUSE-stack entries (plus three unrelated: `usr/bin/fuser` → busybox,
`PV_Diffuser.schelp`, and two vendor sample directories `g2d/overlay_test`,
`test_vivante/unions`):

| path | bytes | mode (from `<IMG>`) | kind |
|---|---|---|---|
| `usr/bin/fusermount` | 20,912 | `04755` root:root | ELF, ARM EABI5, dynamic, stripped |
| `usr/bin/unionfs` | 76,136 | `0755` root:root | ELF, ARM EABI5, dynamic, stripped |
| `usr/bin/unionfsctl` | 5,748 | `0755` root:root | ELF, ARM EABI5, dynamic, stripped |
| `usr/lib/libfuse.so.2.9.4` | 156,508 | `0755` root:root | ELF shared object, stripped |
| `usr/lib/libfuse.so` | → `libfuse.so.2.9.4` | symlink | dev symlink |
| `usr/lib/libfuse.so.2` | → `libfuse.so.2.9.4` | symlink | SONAME symlink |

**[READ]** All are `ELF 32-bit LSB, ARM, EABI5 version 1 (SYSV), dynamically
linked, interpreter /lib/ld-linux-armhf.so.3, for GNU/Linux 2.6.32, stripped`.
`fusermount`'s `.ARM.attributes` names `Cortex-A9` — the i.MX6 core.

**[READ]** There is **no** `/etc/fuse.conf` in either version.
**[READ]** There is **no** `fuse` group in `<R>/etc/group` and no `fuse` user in
`<R>/etc/passwd` (grep returns nothing).
**[READ]** There is **no** `/sbin/mount.fuse` helper (`resolve('/sbin/mount.fuse')`
against `<IMG>` → NOT FOUND), and no `sbin/mount.*` of any kind.

### 5.2 Dependencies all resolve

**[READ]** `llvm-objdump -p`:

| binary | NEEDED |
|---|---|
| `unionfs` | `libfuse.so.2`, `libpthread.so.0`, `librt.so.1`, `libc.so.6` |
| `fusermount` | `libc.so.6` |
| `unionfsctl` | `libc.so.6` |
| `libfuse.so.2.9.4` | `libdl.so.2`, `libpthread.so.0`, `libc.so.6`; SONAME `libfuse.so.2` |

**[READ]** Every one is present: `<R>/lib/libc.so.6 → libc-2.21.so`,
`libdl.so.2 → libdl-2.21.so`, `libpthread.so.0 → libpthread-2.21.so`,
`librt.so.1 → librt-2.21.so`, `ld-linux-armhf.so.3 → ld-2.21.so`. glibc 2.21.
`libfuse.so.2` is the `/usr/lib` symlink above.

**[READ]** There is **no** `/etc/ld.so.conf`, **no** `/etc/ld.so.conf.d/`, and
**no** `/etc/ld.so.cache`. So `ld.so` searches only its compiled-in default
path.

**[INFERRED]** `/usr/lib` is in that default path on this system, so
`unionfs` will find `libfuse.so.2`. The evidence is empirical and strong:
`<R>/usr/bin/las-sc` — the audio engine, which unquestionably runs — has
`NEEDED libchicken.so.8` **[READ]**, and `libchicken.so.8` exists **only** at
`<R>/usr/lib/libchicken.so.8` (3,439,204 B), not in `/lib` **[READ]**. With no
`ld.so.conf` and no cache, `las-sc` could not start unless `/usr/lib` were
searched by default. `/lib` holds 43 shared objects, `/usr/lib` holds 650.

### 5.3 Versions

**[READ]** `fusermount` contains `fusermount version: %s` and the string
`2.9.5` (at file offset `0x41bf`).
**[READ]** `libfuse.so.2.9.4` contains `2.9.5` (at `0x1b0e0`) and versioned
symbol tags `FUSE_2.2` … `FUSE_2.9`, `FUSE_2.9.1`.
**[READ]** The string `2.9.4` does **not** appear anywhere inside
`libfuse.so.2.9.4`.

**[INFERRED]** The package is FUSE **2.9.5**; the `2.9.4` in the filename is the
libtool ABI triple (`current:revision:age`), which upstream FUSE advances
independently of the package version. This is normal upstream behaviour, not a
mismatch or a repackaging error. Recorded because the discrepancy invites a
wrong "version skew" conclusion.

**[READ]** `unionfs` reports `unionfs-fuse version 1.0` and
`unionfs-fuse version: 1.0`, `by Radek Podgorny <radek@podgorny.cz>`. It links
`FUSE_2.5`, `FUSE_2.6`, `FUSE_2.8` symbol versions and `GLIBC_2.4/2.6/2.7`.

---

## 6. `/dev/fuse`: how it comes to exist

The brief asks whether `/dev/fuse` is created by the udev rules the udev gap
catalogued. **It is named by them, and it is also created without them.**

### 6.1 The udev rule

**[READ]** `<R>/lib/udev/rules.d/50-udev-default.rules`, line 75 — the only
`fuse` match in either rules directory (`etc/udev/rules.d/` and
`lib/udev/rules.d/` both grepped):

    KERNEL=="fuse", MODE="0666", OPTIONS+="static_node=fuse"

**[READ]** It sits with two structurally identical neighbours, line 73
(`KERNEL=="tun", MODE="0666", OPTIONS+="static_node=net/tun"`) and line 65
(`KERNEL=="loop-control", GROUP="disk", OPTIONS+="static_node=loop-control"`).

**[READ]** This file is byte-identical between `<R>` and `<R15>` (`diff` clean).

**[INFERRED]** Two effects. `MODE="0666"` makes the node world-read/write, so
even a non-root process could open it. `static_node=fuse` instructs `udevd` to
create the node at startup from the rule alone, independent of whether a device
has appeared — the mechanism upstream provides so that opening the node can
trigger module autoload. Here that path is redundant because FUSE is builtin,
not a module (§4.1), but it is a second, independent guarantee that the node
exists.

**[READ]** `<R>/lib/modules/4.1.15-rt18/modules.devname` contains only its
header comment (`# Device nodes to trigger on-demand module loading.`) and no
entries — consistent with a kernel that has no loadable filesystem modules to
autoload.

### 6.2 devtmpfs creates it anyway

**[READ]** `<IMG>` `/dev` (inode 3008) contains exactly four entries:

| name | mode | type |
|---|---|---|
| `console` | `020622` | character device |
| `log` | `120777` | symlink |
| `pts` | `040755` | directory |
| `shm` | `040755` | directory |

That is a bootstrap `/dev` only — one console node and two mount points.

**[READ]** `<R>/etc/inittab` never mounts devtmpfs. Its `sysinit` lines are:

     17  ::sysinit:/bin/mount -t proc proc /proc
     18  ::sysinit:/bin/mount -o remount,rw /
     19  ::sysinit:/bin/mkdir -p /dev/pts
     20  ::sysinit:/bin/mkdir -p /dev/shm
     21  ::sysinit:/bin/mount -a
     22  ::sysinit:/bin/hostname -F /etc/hostname
     24  ::sysinit:/etc/init.d/rcS

**[READ]** Nor does any init script: `<R>/etc/init.d/S10udev` only starts
`udevd -d` and runs `udevadm trigger`/`settle`; `S02sys` and `S14fs` touch no
mounts.

**[READ]** Yet on the live machine, `runtime-state.txt` mounts section — a
category `CAVEAT-runtime-state.md` explicitly marks uncontaminated — shows:

    devtmpfs on /dev type devtmpfs (rw,relatime,size=89972k,nr_inodes=22493,mode=755)

and dmesg line 277 shows `devtmpfs: mounted` at `[1.366255]`, immediately after
`VFS: Mounted root … readonly` at `[1.364802]` and **before** `udevd` starts at
`[1.992679]` (§4.4).

**[INFERRED]** The kernel mounts devtmpfs itself (`CONFIG_DEVTMPFS_MOUNT=y`),
before userspace. Since FUSE is builtin, its misc device is registered during
`fuse init` at `[0.406545]` — a full second before devtmpfs is mounted — so
devtmpfs materialises `/dev/fuse` as soon as it is mounted, with default
`0600 root:root`. `udevd` then applies the line-75 rule and relaxes it to
`0666`.

**[READ]** The kernel image contains the devtmpfs strings that back this:
`devtmpfs` (`0x861a90`), `6devtmpfs: error mounting %i` (`0x861aad`),
`6devtmpfs: mounted` (`0x861acd`), `6devtmpfs: initialized` (`0x861b51`),
`kdevtmpfs` (`0x861b18`), and the boot parameter `devtmpfs.mount=`
(`0x962b85`).

**[INFERRED]** Conclusion: `/dev/fuse` exists on a running instrument, mode
`0666`, by two independent mechanisms. Neither depends on anything Moog wrote.
**[UNKNOWN]** I have not confirmed the node's presence or mode by direct
observation — no capture in this repo lists `/dev`. §16 proposes the read-only
check.

**[READ]** `fusermount` looks for the node at `/dev/fuse`, falling back to
`/proc/fs/fuse/dev`, and prints `fuse device not found, try 'modprobe fuse'
first` if neither opens. `libfuse.so` also contains `/dev/fuse`.

---

## 7. `/etc/fuse.conf` is absent, and it does not matter for root

### 7.1 What the file would control

**[READ]** `fusermount`'s strings, with offsets, show the whole of its
`fuse.conf` handling:

    42da  /etc/fuse.conf
    42e9  user_allow_other
    42fa  mount_max = %i
    4399  %s: too many FUSE filesystems mounted; mount_max=N can be set in /etc/fuse.conf
    461b  %s: option %.*s only allowed if 'user_allow_other' is set in /etc/fuse.conf
          %s: unknown parameter in %s at line %i: '%s'
          %s: reading %s: line %i too long
          %s: reading %s: missing newline at end of file

So the file has exactly two settings: `user_allow_other` and `mount_max`.

### 7.2 The `allow_other` gate, disassembled

The question is whether the absent file blocks anything. I read the guard rather
than assuming it.

`.text` runs `0x11140`–`0x13e48`; the ELF is non-PIE and loads at `0x10000`, so
file offset + `0x10000` = vaddr. The message at file offset `0x461b` is at vaddr
`0x1461b`; its literal-pool slot is `0x1217c`, loaded once, at `0x11c68`.

**[READ]** `llvm-objdump -d --triple=armv7-none-linux-gnueabihf`:

    11c2c: ebfffc7a  bl   0x10e1c <getuid@plt>
    11c30: e3500000  cmp  r0, #0
    11c34: 0a000017  beq  0x11c98                <-- uid==0: jump past the whole check
    11c38: e59f9464  ldr  r9, [pc, #0x464]  @ 0x120a4
    11c3c: e5993118  ldr  r3, [r9, #0x118]       <-- the user_allow_other global
    11c40: e3530000  cmp  r3, #0
    11c44: 1a000013  bne  0x11c98                <-- set: allowed
    11c48: e1a00005  mov  r0, r5
    11c4c: e1a01004  mov  r1, r4
    11c50: e59f2520  ldr  r2, [pc, #0x520]  @ 0x12178
    11c54: eb000420  bl   0x12cdc                <-- option-name compare
    11c58: e3500000  cmp  r0, #0
    11c5c: 0a000007  beq  0x11c80                <-- not this option: continue
    11c60: e59f3448  ldr  r3, [pc, #0x448]  @ 0x120b0
    11c64: e58d5000  str  r5, [sp]
    11c68: e59f150c  ldr  r1, [pc, #0x50c]  @ 0x1217c   <-- "only allowed if 'user_allow_other'…"
    11c6c: e5930000  ldr  r0, [r3]
    11c70: e1a03004  mov  r3, r4
    11c74: e5992000  ldr  r2, [r9]
    11c78: ebfffcd6  bl   0x10fd8 <fprintf@plt>
    11c7c: ea000088  b    0x11ea4                <-- error exit

**[READ]** Literal pool slot `0x12178` holds `0x142ee`. The string
`user_allow_other` begins at `0x142e9`; `0x142e9 + 5 = 0x142ee` is the suffix
`allow_other`. The compiler shared the tail. So the option being gated is
`allow_other`.

**[READ]** The very first instruction of the guard is `getuid()`, and
`cmp r0,#0 / beq 0x11c98` jumps **past the entire `user_allow_other` test** when
the caller is uid 0.

**Therefore [READ]: the missing `/etc/fuse.conf` gates nothing at all for a root
caller.** `allow_other` and `allow_root` are available to root unconditionally.

### 7.3 `mount_max`

**[READ]** The `mount_max` machinery exists (`mount_max = %i` parser, the "too
many FUSE filesystems mounted" error).
**[UNKNOWN]** I could not read the compiled-in default from the binary: no
`#1000` immediate appears in the disassembly, so it is an initialised global in
`.data` that I did not resolve.
**[INFERRED]** It is not a practical constraint here regardless — there are
currently **zero** FUSE mounts (§10.3), and a root-initiated mount goes through
`libfuse`'s direct `mount(2)` path without invoking `fusermount` at all (§9.2),
where no such counter exists.

### 7.4 The other root-gated checks

**[READ]** `fusermount` also carries these mountpoint checks, all of which
concern a non-root caller's right to mount somewhere:

    %s: mountpoint %s not owned by user
    %s: user has no write access to mountpoint %s
    %s: mountpoint %s is no longer a regular file
    %s: mountpoint %s is not a directory or a regular file
    %s: option blkdev is privileged
    %s: unsafe option %s ignored
    %s: mountpoint is not empty
    %s: if you are sure this is safe, use the 'nonempty' mount option

**[INFERRED]** For root the ownership and write-access tests are vacuous — every
inode in the image is `uid=0 gid=0` (§3.2), so root owns every candidate
mountpoint. The one that still bites is `mountpoint is not empty`, which is a
plain non-empty-directory check and applies regardless of uid; mounting over a
populated `/usr` needs `-o nonempty`. **[READ]** Both `fusermount` and
`libfuse.so` carry the `nonempty` option string, so it is supported.

---

## 8. `/etc/mtab` is a symlink, so `fusermount` never runs busybox `mount`

This is the second apparent blocker, and it is also not one. It matters because
`fusermount` invokes `/bin/mount` with a flag busybox does not implement.

### 8.1 The setup

**[READ]** `fusermount` contains:

    48be  /bin/mount
    48c9  --no-canonicalize
    48e7  %s: failed to execute /bin/mount: %s
    491e  /bin/umount
    492d  %s: failed to execute /bin/umount: %s
    4954  --fake
    4389  /etc/mtab
    4710  /etc/mtab.fuselock

**[READ]** `<IMG>` `/bin/mount` is `mode=120777`, a symlink to `busybox`; so is
`/bin/umount`. `/bin/busybox` is the 651,144-byte setuid binary.

**[READ]** busybox's mount applet advertises `[OPTIONS] [-o OPT] DEVICE NODE`
and supports the option keywords `bind`, `rbind`, `move`, `remount`, `loop`.
**[INFERRED]** It does not implement util-linux's `--no-canonicalize`; that flag
is a util-linux mtab-maintenance affordance and does not appear in the busybox
strings. Had `fusermount` actually executed `/bin/mount --no-canonicalize …`,
busybox would have rejected the argument.

### 8.2 The guard, disassembled

**[READ]** `/etc/mtab` in `<IMG>` is `mode=120777`, a symlink whose target is
`/proc/mounts` (12 bytes).

The `/etc/mtab` string is at vaddr `0x14389`. Its literal-pool slot `0x138e4` is
loaded three times by one function beginning at `0x13810`. That function is
`mtab_needs_update()`:

    13810: e92d4070  push {r4, r5, r6, lr}
    13814: e24dd068  sub  sp, sp, #104
    13818: e59f50c4  ldr  r5, [pc, #0xc4] @ 0x138e4      <-- r5 = "/etc/mtab"
    1381c: e1a06000  mov  r6, r0                          <-- r6 = mnt argument
    13820: ebfff5e0  bl   0x10fa8 <strlen@plt>
    13824: e1a04000  mov  r4, r0                          <-- r4 = strlen(mnt)
    13828: e1a01005  mov  r1, r5
    1382c: e1a00006  mov  r0, r6
    13830: e1a02004  mov  r2, r4
    13834: ebfff629  bl   0x110e0 <strncmp@plt>           <-- strncmp(mnt,"/etc/mtab",len)
    13838: e3500000  cmp  r0, #0
    1383c: 1a000004  bne  0x13854
    13840: e7d53004  ldrb r3, [r5, r4]                    <-- "/etc/mtab"[len]
    13844: e353002f  cmp  r3, #47                         <-- '/'
    13848: 1a000001  bne  0x13854
    1384c: e3a00000  mov  r0, #0                          <-- return 0 (mtab inside new mount)
    13850: ea000021  b    0x138dc
    13854: e59f0088  ldr  r0, [pc, #0x88] @ 0x138e4       <-- "/etc/mtab"
    13858: e1a0100d  mov  r1, sp
    1385c: eb000175  bl   0x13e38                         <-- lstat("/etc/mtab", &stbuf)
    13860: e3700001  cmn  r0, #1
    13864: 1a000003  bne  0x13878
    13868: ebfff5e0  bl   0x10ff0 <__errno_location@plt>
    1386c: e5900000  ldr  r0, [r0]
    13870: e2500002  subs r0, r0, #2                      <-- errno==ENOENT -> 0
    13874: ea000017  b    0x138d8
    13878: e59d3010  ldr  r3, [sp, #0x10]                 <-- stbuf.st_mode
    1387c: e2033a0f  and  r3, r3, #61440                  <-- & 0xF000  (S_IFMT)
    13880: e3530a0a  cmp  r3, #40960                      <-- == 0xA000 (S_IFLNK)
    13884: 0afffff0  beq  0x1384c                         <-- SYMLINK -> return 0
    13888: ebfff563  bl   0x10e1c <getuid@plt>
    ...
    138a0: e59f003c  ldr  r0, [pc, #0x3c] @ 0x138e4
    138a4: e3a01002  mov  r1, #2
    138a8: ebfff5df  bl   0x1102c <access@plt>            <-- access("/etc/mtab", W_OK)
    ...
    138d4: e255001e  subs r0, r5, #30                     <-- errno==EROFS -> 0
    138d8: 13a00001  movne r0, #1
    138dc: e28dd068  add  sp, sp, #104
    138e0: e8bd8070  pop  {r4, r5, r6, pc}

**[READ]** At `0x1387c`–`0x13884`: mask `st_mode` with `61440` (`0xF000`),
compare against `40960` (`0xA000`), branch to the `return 0` at `0x1384c` if
equal. That is exactly `S_ISLNK(st.st_mode) → return 0`.

(Note for anyone re-running this: `llvm-objdump` prints these ARM immediates in
**decimal**. Grepping the listing for `0xf000`/`0xa000` finds nothing and looks
like the check is absent. It is not.)

**[READ] Therefore: because `/etc/mtab` is a symlink, `mtab_needs_update()`
returns 0, and `fusermount` never executes `/bin/mount` or `/bin/umount`.** The
busybox `--no-canonicalize` incompatibility is unreachable. The function also
returns 0 on `ENOENT` and on `EROFS`, so it is defensive in two further ways.

**[INFERRED]** The same `mount_util.c` object is linked into `libfuse.so` (which
carries the identical `/bin/mount`, `--fake`, and failure-message strings), so
the same short-circuit protects the library path.

---

## 9. `unionfs-fuse` 1.0: what it can do

### 9.1 The option surface

**[READ]** The complete usage text recovered from `<R>/usr/bin/unionfs`:

    unionfs-fuse version 1.0
    by Radek Podgorny <radek@podgorny.cz>
    Usage: %s [options] branch[=RO/RW][:branch...] mountpoint
    The first argument is a colon separated list of directories to merge
    When neither RO nor RW is specified, selection defaults to RO.

    general options:
        -d                     Enable debug output
        -o opt,[opt...]        mount options
        -h   --help            print help
        -V   --version         print version

    UnionFS options:
        -o chroot=path         chroot into this path. Use this if you
                               want to have a union of "/"
        -o cow                 enable copy-on-write
                               mountpoint
        -o debug_file          file to write debug information into
        -o dirs=branch[=RO/RW][:branch...]
                               alternate way to specify directories to merge
        -o hide_meta_files     ".unionfs" is a secret directory not
                               visible by readdir(), and so are
                               .fuse_hidden* files
        -o max_files=number    Increase the maximum number of open files
        -o relaxed_permissions Disable permissions checks, but only if
                               running neither as UID=0 or GID=0
        -o statfs_omit_ro      do not count blocks of ro-branches

**[READ]** Its internal symbol names confirm a full FUSE operation table:
`unionfs_getattr`, `readlink`, `mknod`, `mkdir`, `symlink`, `rename`, `link`,
`chmod`, `chown`, `truncate`, `open`, `read`, `write`, `statfs`, `flush`,
`release`, `fsync`, `create`, `utimens`, `unlink`, `rmdir`, `readdir`, `ioctl`,
`init`.

**[READ]** Its copy-on-write machinery is present and named:
`find_rw_branch_cow`, `find_rorw_branch`, `find_lowest_rw_branch`,
`find_rw_branch_cutlast`, `__find_rw_branch_cutlast`, `do_create_whiteout`,
`maybe_whiteout`, `hide_file`, `hide_dir`, `remove_hidden`, `path_hidden`,
`filedir_hidden`, `read_whiteouts`, `is_hiding`, `set_owner`, `dir_not_empty`.

**[READ]** Its metadata namespace: `.unionfs`, `.unionfs/`, `.fuse_hidden`,
`_HIDDEN~`, and the debug-time format `uopt.branches[branch].path = %s path = %s`.

**[READ]** One upstream oddity is carried: `deprecated mknod workaround, tell
the unionfs-fuse authors if you see this!`

**[INFERRED]** `-o cow` plus a `branch=RW` is precisely the "writable layer over
a read-only tree" primitive the brief asks about. `-o chroot=` exists for the
union-of-`/` case. `-o relaxed_permissions` is explicitly documented as
inoperative for UID 0, so it is irrelevant here.

### 9.2 How the mount actually happens as root

**[READ]** `libfuse.so.2.9.4` imports both mechanisms:

| symbol | purpose |
|---|---|
| `mount` | direct `mount(2)` |
| `umount2` | direct unmount |
| `fork`, `setuid`, `getuid`, `geteuid` | the `fusermount` fallback |

**[READ]** and carries both sets of strings: `/dev/fuse`,
`fd=%i,rootmode=%o,user_id=%u,group_id=%u` (the direct-mount option string) on
one side, and `/usr/bin/fusermount`, `_FUSE_COMMFD`,
`fuse: failed to exec fusermount` on the other.

**[READ]** `fuse_mount` at `0x14c64` tail-jumps to the common routine at
`0x14be4`, which opens a scratch fd in a loop until it exceeds 2 — the standard
"make sure the channel fd is not 0/1/2" guard — before proceeding to the mount
proper:

    14be4: e92d40f8  push {r3, r4, r5, r6, r7, lr}
    14bf8: e1a00007  mov  r0, r7
    14bfc: e3a01002  mov  r1, #2                    <-- O_RDWR
    14c00: ebffc01b  bl   0x4c74 <open64@plt>
    14c04: e3500002  cmp  r0, #2
    14c0c: da000000  ble  0x14c14
    14c10: ebffc1bb  bl   0x5304 <close@plt>
    14c14: e3550002  cmp  r5, #2
    14c18: 9afffff6  bls  0x14bf8                   <-- loop while fd <= 2

**[INFERRED]** `libfuse` attempts the direct `mount(2)` first and falls back to
exec'ing `fusermount` only if that fails — the upstream `fuse_mount_sys()` →
`fuse_mount_fusermount()` order. I did not trace the branch that selects
between them, so the *ordering* is inferred; the *presence of both* is read.

**This does not affect the conclusion**: both paths are available and both work
for a root caller. If the direct path is taken, `fusermount` is irrelevant to
mounting. If the fallback is taken, `fusermount` is present, setuid root, and
finds its device (§6) and its config gates open (§7).

**[READ]** `libfuse` hardcodes the helper path as `/usr/bin/fusermount`, which
is where it actually is.

### 9.3 `unionfsctl`

**[READ]** `<R>/usr/bin/unionfsctl`, 5,748 B, links only `libc.so.6`, and
imports `ioctl`, `open64`, `getopt`, `__xpg_basename`. Its usage:

    Usage:
         %s <parameter1> [<parameter2>] [file-path]
         List of parameters
           -p </path/to/debug/file>
           -d <on/off>
              Enable or disable debugging.

**[READ]** It shares the symbol `unionfs_ioctls_t` with `unionfs`.

**[INFERRED]** It is the runtime control channel for a mounted unionfs — it
opens a path inside the mount and drives it by `ioctl`. Its only documented
functions are toggling debug and setting the debug file. It is **not** a way to
add or remove branches at runtime. The brief did not mention this binary; it is
part of the shipped stack and is catalogued here for completeness.

---

## 10. Nothing uses any of it

### 10.1 Whole-tree content search

**[READ]** `grep -rl -a -E 'unionfs|fusermount'` over the entirety of `<R>`
(all 6,035 regular files, binaries included, text and non-text) matches exactly
four paths:

    usr/bin/fusermount
    usr/bin/unionfs
    usr/bin/unionfsctl
    usr/lib/libfuse.so.2.9.4

— the four FUSE files themselves. (`usr/share/SuperCollider/HelpSource/Classes/
PV_Diffuser.schelp` was excluded as an unrelated substring match on "Diffuser".)

**[READ]** The identical search over `<R15>` returns the identical four paths.

**[READ]** `grep -rn -I -E 'fusermount|unionfs|unionfsctl|libfuse|\bfuse\b|/dev/fuse'`
over the whole of `<R>/etc/` — every init script, every config file — returns
**nothing**.

**[READ]** `grep -rl -a '/dev/fuse'` over `<R>` matches only `usr/bin/fusermount`
and `usr/lib/libfuse.so.2.9.4`.

So: no init script mounts a union, no binary spawns `unionfs`, no configuration
references FUSE. The capability is shipped and untouched.

### 10.2 No copy-on-write residue

**[READ]** `find` over `<R>` for `.unionfs*`, `*_HIDDEN~`, `.fuse_hidden*` —
the three metadata patterns unionfs-fuse leaves behind (§9.1) — returns
nothing. The image has never had a unionfs COW layer written into it.

### 10.3 Nothing is mounted at runtime either

**[READ]** `runtime-state.txt` `--- modules ---` section, a category the caveat
marks valid:

    Module                  Size  Used by    Tainted: G

Empty. No loadable modules at all, consistent with §4.1.

**[READ]** The `--- mounts ---` section in full:

    /dev/root on / type ext4 (rw,relatime,errors=remount-ro,data=ordered)
    devtmpfs on /dev type devtmpfs (rw,relatime,size=89972k,nr_inodes=22493,mode=755)
    proc on /proc type proc (rw,relatime)
    devpts on /dev/pts type devpts (rw,relatime,gid=5,mode=620)
    tmpfs on /dev/shm type tmpfs (rw,relatime,mode=777)
    tmpfs on /tmp type tmpfs (rw,relatime)
    sysfs on /sys type sysfs (rw,relatime)
    /dev/mmcblk2p6 on /var type ext4 (rw,noatime,data=ordered)
    /dev/mmcblk2p7 on /mnt/fwu type ext4 (rw,noatime,data=ordered)
    /dev/mmcblk2p4 on /var/lib/sys type vfat (rw,noatime,...)
    tmpfs on /var/run type tmpfs (rw,nosuid,nodev,relatime,mode=755)
    /dev/sda1 on /var/local/media/sda1 type vfat (rw,relatime,gid=100,...)
    cgroup on /cgroup/cpuacct type cgroup (rw,relatime,cpuacct)
    cgroup on /cgroup/cpuset type cgroup (rw,relatime,cpuset)
    cgroup on /cgroup/cpu type cgroup (rw,relatime,cpu)
    cgroup on /cgroup/memory type cgroup (rw,relatime,memory)

No `fuse` mount, no `unionfs` mount, no `fuse.` subtype anywhere.

---

## 11. The live question: can a writable layer be stacked over `/usr`?

### 11.1 What is writable

**[READ]** From the mount table above, at runtime:

| path | device | state |
|---|---|---|
| `/` | `/dev/root` (ext4) | **rw**, `errors=remount-ro` |
| `/var` | `mmcblk2p6` (ext4) | rw, persistent |
| `/mnt/fwu` | `mmcblk2p7` (ext4) | rw, persistent, **wiped every boot** |
| `/var/lib/sys` | `mmcblk2p4` (vfat) | rw, persistent |
| `/tmp`, `/dev/shm`, `/var/run` | tmpfs | rw, volatile |
| `/var/local/media/sda1` | `/dev/sda1` (vfat) | rw, removable USB |

**[READ]** `/mnt/fwu` is cleared on every boot: `<R>/etc/init.d/S14fs:51`

    #destroy anything in fwu folder
    rm -rf /mnt/fwu/*

**[READ]** `/tmp` and `/var/local/tmp` are cleared too (`S14fs:45-48`).

**[INFERRED]** So a *persistent* writable branch has two realistic homes: `/var`
(on `mmcblk2p6`) or the USB stick at `/var/local/media/sda1`. A *volatile* one
can live in `/tmp`. `/mnt/fwu` is unsuitable — it is emptied at `S14fs`, which
runs before the audio stack.

**[UNKNOWN]** Free space on `mmcblk2p6`. No capture in this repo records `df`.
§16 proposes the read-only check.

### 11.2 `/mnt/u1` and `/mnt/u2` are not what the brief implies

**[READ]** `<R>/etc/fstab` in full:

     1  #<system>      <mount pt>      <type>  <options>       <dump>  <pass>
     2  /dev/root       /               ext4    rw,noauto,noatime       0       1
     3  proc            /proc           proc    defaults        0       0
     4  devpts          /dev/pts        devpts  defaults,gid=5,mode=620 0       0
     5  tmpfs           /dev/shm        tmpfs   mode=0777       0       0
     6  tmpfs           /tmp            tmpfs   mode=1777       0       0
     7  sysfs           /sys            sysfs   defaults        0       0
     8  /dev/mmcblk2p2  /mnt/u1         ext4    ro,noauto       0       0
     9  /dev/mmcblk2p3  /mnt/u2         ext4    ro,noauto       0       0
    10  /dev/mmcblk2p6  /var            ext4    defaults,noatime        0       1
    11  /dev/mmcblk2p7  /mnt/fwu        ext4    defaults,noatime        0       1
    12  /dev/mmcblk2p4  /var/lib/sys    vfat    defaults,noatime        0       1
    13  tmpfs           /var/run        tmpfs   mode=0755,nosuid,nodev  0       0

Lines 8 and 9 are **`ro,noauto`**. The brief characterises fstab as mounting
them ro; the `noauto` is the operative flag — `mount -a` (inittab line 21)
skips them.

**[READ]** They are absent from the live mount table (§10.3). They are not
mounted.

**[READ]** The only thing that ever mounts them is the firmware updater,
`<R>/usr/bin/lasfwu`, transiently:

    473:        mount /dev/mmcblk2p2 /mnt/u1 >/dev/null 2>&1
    480:        if [ -f /mnt/u1/etc/versionb ]; then
    481:            hex=`hexdump -C /mnt/u1/etc/versionb | awk -F " " '{print $5$4$3$2}'`
    488:        mount /dev/mmcblk2p3 /mnt/u2 >/dev/null 2>&1
    494:        if [ -f /mnt/u2/etc/versionb ]; then
    495:            hex=`hexdump -C /mnt/u2/etc/versionb | awk -F " " '{print $5$4$3$2}'`
    502:        umount /mnt/u1 >/dev/null 2>&1
    509:        umount /mnt/u2 >/dev/null 2>&1

**[INFERRED]** `mmcblk2p2` and `mmcblk2p3` are the two A/B root-filesystem
slots; `/mnt/u1` and `/mnt/u2` are the updater's inspection mount points, used
only to read `etc/versionb` out of each slot. dmesg records the running root as
device `179:3` **[READ]**, i.e. one of those two slots. They are not a
read-only data area to be stacked over — they are alternate copies of `/`.

### 11.3 The root filesystem is read-write, and the attempt to make it read-only fails

**[READ]** `<R>/etc/init.d/S99final`, lines 41–44:

    41  #no key or hot key press was found so kill xterms, dwm, and mount root RO
    42  killall xterm;
    43  killall las-dwm;
    44  mount -f -o remount,ro /

**[READ]** `-f` is busybox mount's *fake* flag: it performs no `mount(2)`, only
an mtab update. And `/etc/mtab` is a symlink to `/proc/mounts` (§8.2), so there
is no mtab to update either.

**[READ]** The live mount table confirms the outcome: `/` is
`rw,relatime,errors=remount-ro`. Root is read-write on a running instrument.

This independently corroborates `gap-observability-toolkit.md` §5.3, which the
brief cites. I verified it from `S99final` directly rather than taking it on
trust.

**[READ]** Note also lines 31–39 of the same script: a thumbdrive file
`/media/thumbdrive/k` whose hexdump equals `23051934` causes an early `exit`
that skips the remount and the `killall`s entirely. (Documented in
`network.md`; out of scope here, and moot given line 44 is a no-op anyway.)

### 11.4 Who would be doing the mounting

**[READ]** `runtime-state.txt` `--- processes ---` is a contaminated category
per the caveat, so I have not counted process UIDs from it.
**[INFERRED]** The system is effectively all-root: there is no `fuse` group and
no unprivileged service account referenced in the FUSE stack (§5.1), inittab
launches `rcS` directly as init's child with no `su`/`setuidgid` anywhere in
`<R>/etc/init.d/`, and `S14fs` freely writes `/root/.ssh` (line 38–42). This is
the assumption the brief makes and I found nothing contradicting it — but I did
not enumerate every service's credentials, so it is inferred, not read.

### 11.5 So: yes, and here is the shape of it

**[INFERRED]** Every prerequisite is satisfied:

| requirement | status |
|---|---|
| kernel FUSE | builtin, initialised at boot (§4) |
| `/dev/fuse` | created by devtmpfs, relaxed to `0666` by udev (§6) |
| union daemon | `unionfs-fuse` 1.0 with `-o cow` (§9.1) |
| library | `libfuse` 2.9.5, resolvable from `/usr/lib` (§5.2) |
| privileged mount | root; `fusermount` setuid root as backup (§3, §9.2) |
| config gates | none block root (§7) |
| mtab hazard | unreachable (§8) |
| writable storage | `/var` persistent, `/tmp` volatile (§11.1) |
| mounting over non-empty dir | supported via `-o nonempty` (§7.4) |
| bind mounts to stage a branch | busybox supports `bind`/`rbind` (§8.1) |

**[INFERRED]** The shape that works is *not* "union `/usr` onto `/usr`" — that
is recursive. It is: bind the real `/usr` to a staging point first, then union
the staging point (RO) with a writable directory (RW) onto `/usr`. Something
like:

    mkdir -p /var/usr-rw /mnt/usr-ro
    mount --bind /usr /mnt/usr-ro
    unionfs -o cow,nonempty /var/usr-rw=RW:/mnt/usr-ro=RO /usr

**This is a sketch, not a tested procedure. It is untested, it is not
recommended, and §11.6 lists why it is dangerous.** I did not run it — nothing
in this report was executed anywhere.

**[INFERRED]** The bind mount is what avoids recursion: it is an independent
VFS view of the same underlying inodes and is not routed through the FUSE
daemon, so the daemon can read its RO branch while simultaneously serving
`/usr`.

**[INFERRED]** No flash write is involved in the union itself. `/var` is already
a mounted read-write ext4 partition, so writes to the RW branch do land on eMMC
— "without writing to flash" is satisfied only in the sense of *not modifying
the root filesystem or its A/B slots*. For a genuinely no-flash arrangement the
RW branch must be under `/tmp` (tmpfs), which is wiped at every boot by
`S14fs:45`.

### 11.6 Why this is dangerous

**[INFERRED]** Recording these because "it is possible" is not "it is safe", and
this project's stated history is of inference shipped as fact:

1. **The daemon becomes a single point of failure for `/usr`.** If the `unionfs`
   process dies, `/usr` becomes an unreadable stub. Every binary the instrument
   needs — `las-sc`, `las-frontend`, `Xorg`, `libchicken.so.8` — lives there
   (§5.2). The watchdog (`las-watchdog`, started at `S99final:24`) would be
   unable to restart anything.
2. **The daemon's own dependencies live in the tree it serves.** `unionfs` is
   `/usr/bin/unionfs` and needs `/usr/lib/libfuse.so.2`. Once resident this is
   fine (its pages are already mapped), but it cannot be restarted after a
   failure without first unmounting, and unmounting needs `fusermount` — also in
   `/usr/bin`.
3. **`errors=remount-ro` on `/`.** Any ext4 error on the root device flips it
   read-only mid-session, which the union will not shield.
4. **Nothing in Moog's firmware exercises this path** (§10). There is no
   evidence Moog has ever tested FUSE on this hardware, no `/etc/fuse.conf` to
   suggest anyone configured it, and no COW residue to suggest anyone tried.
   It is stock Buildroot furniture.
5. **The real-time audio path.** `cpu1` is isolated for `scsynth` at SCHED_FIFO
   99. A FUSE daemon servicing `/usr` introduces userspace round-trips into
   every `exec` and page-fault on that tree. **[UNKNOWN]** I have not measured
   any of this, and cannot from disk. It is the single largest unquantified risk
   and it is the one most likely to matter musically.

---

## 12. 1.5.0 versus 1.8.2: no change whatsoever

**[READ]** MD5 comparison across the two trees:

| file | 1.5.0 | 1.8.2 | same |
|---|---|---|---|
| `usr/bin/fusermount` | `aca98280d5b0001f093b00b6c3bd7002` | `aca98280d5b0001f093b00b6c3bd7002` | yes |
| `usr/bin/unionfs` | `0c900d92c0bdcd36fc91cb5ddb5eb1d2` | `0c900d92c0bdcd36fc91cb5ddb5eb1d2` | yes |
| `usr/bin/unionfsctl` | `cafe488032d16f348f60c64c2a6fbaf0` | `cafe488032d16f348f60c64c2a6fbaf0` | yes |
| `usr/lib/libfuse.so.2.9.4` | `5ac629714d07a148a99483969665764b` | `5ac629714d07a148a99483969665764b` | yes |

(`usr/bin/fuser` differs, but only because it is a symlink to `busybox` and
`busybox` itself changed between releases — the md5 follows the link.)

**[READ]** Also byte-identical: `lib/modules/4.1.15-rt18/modules.builtin`,
`lib/udev/rules.d/50-udev-default.rules`, `etc/fstab` (all `diff` clean).

**[READ]** Neither version has `/etc/fuse.conf`.

**[READ]** Neither version references the FUSE stack anywhere outside the four
files (§10.1).

**[INFERRED]** The FUSE/union capability is inert Buildroot furniture that has
been carried unchanged across at least three years of releases (2022-05-16 →
2025-09-15) without Moog ever touching it.

---

## 13. Conflicts with existing documentation

Per the brief I report conflicts rather than fixing them. I edited no existing
file.

**1. The gap brief's setuid premise — refuted.** The brief asks "whether
`fusermount`'s missing setuid bit matters when everything runs as root". The bit
is not missing; `/usr/bin/fusermount` is `04755 root:root` in the shipping image
(§3.2). The premise came from `ls -l` on an extraction that dropped all six
setuid bits.

**2. A methodological conflict affecting every doc that cites permissions or
ownership from the extracted trees.** `captures/firmware-1.8.2/rootfs-1.8.2` and
`captures/rootfs-1.5.0` do **not** preserve uid/gid (everything reads
`michaelcurtis staff`), do **not** preserve setuid/setgid (six bits lost), and
do **not** preserve device nodes (`/dev/console` lost). I did not audit the
corpus for downstream claims that rely on these. Anything asserting a file's
owner, its privilege bits, or the existence of a device node should be re-sourced
from `captures/firmware-1.8.2/pkg/rootfs.ext4`. This is a conflict I am flagging,
not one I have measured the blast radius of.

**3. The brief's description of `/mnt/u1` and `/mnt/u2` — imprecise.** It says
"`etc/fstab` mounts `/dev/mmcblk2p2 /mnt/u1` and `/dev/mmcblk2p3 /mnt/u2` **ro**".
Both entries carry `noauto` as well as `ro`, `mount -a` therefore skips them,
and the live mount table shows neither mounted (§11.2). They are the A/B root
slots, touched only transiently by `lasfwu`.

**4. The brief's doc count.** It says "all 28 docs"; `find docs -name '*.md'`
counts **62**. The zero-coverage finding holds either way — I grepped all 62
(§2). Possibly "28" refers to `docs/firmware/` plus `docs/arch/` only.

**5. No conflict with `gap-observability-toolkit.md` §5.3.** Its finding that
`S99final:44`'s `mount -f -o remount,ro /` is a fake-flag no-op is confirmed
independently, both from the script and from the live mount table (§11.3).

**6. No conflict with `gap-uboot-env-and-flash-fuse-tooling.md`.** Its `fuse`
usage is uniformly the i.MX6 OTP eFuse sense (§2). The two documents share a
word and nothing else. This document does not touch OTP.

**7. No conflict with the established architecture summary.** Nothing here bears
on the XMOS/MIDI boundary, the OSC namespace, `_m` addresses, or `scsynth -z
128`. I did not rely on `runtime-state.txt` for any contaminated category.

---

## 14. What I could not determine

* **[UNKNOWN]** Whether `/dev/fuse` is actually present on a running instrument,
  and at what mode. Inferred present at `0666` by two mechanisms (§6); not
  observed. No capture in this repo lists `/dev`.
* **[UNKNOWN]** `CONFIG_DEVTMPFS_MOUNT` as a config symbol. Inferred `=y` from
  boot ordering and the live mount table (§6.2); there is no `/proc/config.gz`
  and no `config-*` file in either tree.
* **[UNKNOWN]** The compiled-in `mount_max` default in `fusermount` (§7.3).
* **[UNKNOWN]** Free space and inode headroom on `mmcblk2p6` (`/var`), and the
  sizes of `mmcblk2p2`/`p3`. No `df` in any capture.
* **[UNKNOWN]** The exact branch order between `libfuse`'s direct `mount(2)` and
  its `fusermount` fallback (§9.2). Both paths are read; the selection logic is
  not traced. Does not affect the conclusion.
* **[UNKNOWN]** Any latency or xrun cost of interposing FUSE on `/usr` while
  `scsynth` runs SCHED_FIFO 99 on the isolated `cpu1`. Not measurable from disk.
  This is the risk that most deserves measurement before anyone acts on §11.5.
* **[UNKNOWN]** The 1.5.0 setuid bits, for want of a 1.5.0 filesystem image
  (§3.5).
* **[UNKNOWN]** Whether `unionfsctl`'s ioctl interface exposes anything beyond
  the two documented debug controls. I read its usage text and imports, not its
  ioctl number table.
* **Not attempted:** any dynamic behaviour. Nothing was executed, on the
  instrument or otherwise. The two ARM binaries disassembled here were read
  only.

---

## 15. Claim summary

| § | claim | grade |
|---|---|---|
| 1, 3 | `/usr/bin/fusermount` is setuid root (`04755`, uid 0) in the shipping image | READ |
| 3.2 | The extracted trees lost all six setuid bits, all ownership, and device nodes | READ |
| 4.1 | `fuse.ko` is builtin; no overlayfs/aufs/unionfs/squashfs in `modules.builtin` | READ |
| 4.2 | Kernel binary contains FUSE code; zero `overlayfs`/`aufs`/`squashfs`/`unionfs` | READ |
| 4.3 | The single `overlay` string is the i.MX framebuffer plane | READ |
| 4.4 | Live kernel prints `fuse init (API version 7.23)` at boot | READ |
| 5.1 | Four-file userspace stack; no `/etc/fuse.conf`, no `fuse` group, no `mount.fuse` | READ |
| 5.2 | All dynamic dependencies present; `/usr/lib` resolves without ld.so.conf | INFERRED |
| 5.3 | FUSE 2.9.5; the `2.9.4` filename is the libtool ABI triple | INFERRED |
| 6.1 | `50-udev-default.rules:75` sets `/dev/fuse` `MODE="0666"`, `static_node=fuse` | READ |
| 6.2 | devtmpfs is kernel-mounted before udev; `/dev/fuse` exists either way | INFERRED |
| 7.2 | `getuid()==0` bypasses the `user_allow_other` gate (disassembled at `0x11c2c`) | READ |
| 8.2 | `/etc/mtab` is a symlink; `mtab_needs_update()` returns 0 for symlinks (`0x1387c`) | READ |
| 8.2 | Therefore `fusermount` never execs busybox `/bin/mount` | READ |
| 9.1 | `unionfs-fuse` 1.0 supports `-o cow`, `-o chroot=`, RO/RW branches, whiteouts | READ |
| 9.2 | `libfuse` carries both direct-`mount(2)` and `fusermount` paths | READ |
| 10.1 | Nothing in either firmware references the FUSE stack | READ |
| 10.3 | No FUSE mount and no loaded modules at runtime | READ |
| 11.2 | `/mnt/u1`,`/mnt/u2` are `noauto` A/B slots, not mounted at runtime | READ |
| 11.3 | `S99final:44` remount-ro is a fake-flag no-op; `/` is rw at runtime | READ |
| 11.5 | A writable layer over `/usr` is achievable with shipped software alone | INFERRED |
| 11.6 | Doing so is hazardous; RT audio cost unmeasured | INFERRED / UNKNOWN |
| 12 | The FUSE stack is byte-identical between 1.5.0 and 1.8.2 | READ |

---

## 16. Validation plan — read-only commands for a human to run

**Do not run these from an agent.** Every one is read-only: no mount, no write,
no module load, no `fusermount`, no `unionfs`. Nothing here changes state.

Confirming `/dev/fuse` (§6, the main UNKNOWN):

    ls -l /dev/fuse
    stat -c '%n %A %u %g %t:%T' /dev/fuse
    cat /proc/fs/fuse/version

Confirming FUSE is registered and builtin (§4):

    grep -w fuse /proc/filesystems
    grep -w fuseblk /proc/filesystems
    lsmod
    dmesg | grep -i 'fuse init'

Confirming devtmpfs and the absence of alternatives (§4, §6):

    grep -E 'devtmpfs|overlay|aufs|squashfs|unionfs' /proc/filesystems
    grep devtmpfs /proc/mounts
    cat /proc/cmdline

Confirming the setuid finding on the live machine (§3) — the decisive check:

    ls -l /usr/bin/fusermount /usr/bin/unionfs /usr/bin/unionfsctl
    stat -c '%n %A %u %g' /usr/bin/fusermount /bin/busybox /usr/bin/Xorg
    find / -xdev -perm -4000 -type f 2>/dev/null

Confirming the mtab short-circuit (§8):

    ls -l /etc/mtab
    readlink /etc/mtab

Confirming mount state and writable space (§11):

    cat /proc/mounts
    df -h
    df -i
    ls -l /etc/fuse.conf          # expected: No such file or directory

Confirming nothing is using it (§10):

    cat /proc/mounts | grep -i fuse
    ls -la /sys/fs/fuse/connections 2>/dev/null

Version confirmation without executing the Moog stack — note that `fusermount`
and `unionfs` are *not* Moog binaries but stock FUSE tools, so `--version` is
safe in a way the Moog binaries emphatically are not; even so, it is listed last
and is optional:

    /usr/bin/fusermount --version
    /usr/bin/unionfs --version

If there is any doubt about that last pair, skip them — every claim in this
document about their versions is already sourced from strings in the files
themselves (§5.3), and nothing depends on running them.
