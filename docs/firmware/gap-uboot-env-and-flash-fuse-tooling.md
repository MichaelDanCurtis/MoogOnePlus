# The on-device U-Boot environment, boot-media and OTP-fuse toolchain

Scope: everything in the v1.8.2 root filesystem that can **read or write the boot
chain** — the U-Boot environment tools, the U-Boot image tools, the MTD/NAND/UBI
tools, the OTP-fuse tools, the eMMC tools, and the SPI flasher — plus what the
kernel actually exposes for fuse reading, and what any of it can do on *this*
hardware.

Sources read for this report:

* `captures/firmware-1.8.2/rootfs-1.8.2/` — decrypted v1.8.2 root filesystem
* `captures/rootfs-1.5.0/` — v1.5.0 root filesystem, for the version diff
* `captures/dmesg-before-reboot.txt` — live boot log
* `captures/arch-harvest/runtime-state.txt` — live state (see
  `arch-harvest/CAVEAT-runtime-state.md`; only categories that file certifies as
  uncontaminated are cited here: kernel cmdline, mounts)
* `captures/harvest/04-tools.txt`, `captures/sysmap/01-hardware.txt`,
  `captures/moog-recon/01-system.txt` — live tool/storage probes
* `captures/firmware-1.8.2/pkg/` — the unpacked update package

Method for binaries: `strings`, `xxd`, a hand-written FDT parser, and
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`. **No Moog binary was
executed.** Nothing on the network was touched.

Every claim below carries **[READ]**, **[INFERRED]** or **[UNKNOWN]**.

---

## 0. Headline

**[READ]** `/usr/sbin/fw_printenv` (and its `fw_setenv` twin) is shipped on the
instrument but **cannot run as shipped**: it hard-codes `/etc/fw_env.config` as
its device-description file, that file does not exist in *either* firmware
version, and the disassembled failure path is fatal. Nothing else in the
492 MB tree references it. **The U-Boot environment's location on the eMMC is
therefore not declared anywhere on disk, and no report — including this one —
has read the environment.**

**[READ] + [INFERRED]** Second headline, and a correction to the framing of this
gap: **`flash_otp_info` / `flash_otp_lock` cannot answer the HAB-fuse question.**
They are MTD OTP tools (NOR/NAND factory+user OTP regions, `OTPSELECT` /
`OTPGETREGIONCOUNT` ioctls), not i.MX6 OCOTP tools, and this board has **no MTD
device at all**. The tool that *does* answer it is already in the kernel:
**`fsl_otp` is built in**, and it publishes the entire i.MX6 fuse map — including
`HW_OCOTP_CFG5`, `HW_OCOTP_SRK0..7`, `HW_OCOTP_SRK_REVOKE` and `HW_OCOTP_LOCK` —
as plain sysfs files that a human can `cat`.

**[READ] + [INFERRED]** Third: the boot-side toolchain can now be dated.
`mkimage` and `mkenvimage` both report version **`2016.01`**, and the kernel
banner records the whole system as built with **Buildroot 2016.02-rc2** on
2022-05-16. Buildroot 2016.02's `u-boot-tools` is U-Boot 2016.01. These are this
tree's own `u-boot-tools`, and the bootloader on the eMMC is very likely U-Boot
2016.01 from the same build (§6).

---

## 1. Inventory

**[READ]** Complete list of boot-chain-capable tools in `rootfs-1.8.2`, with the
v1.5.0 comparison. Sizes in bytes, MD5 of the file (symlinks resolved).

| path | size | md5 (1.8.2) | vs 1.5.0 |
|---|---|---|---|
| `/usr/sbin/fw_printenv` | 26700 | `6f85af03a99cd0602dbf67a8fa86d065` | same |
| `/usr/sbin/fw_setenv` | 11 (symlink → `fw_printenv`) | — | same |
| `/usr/bin/mkimage` | 93884 | `9851c9beeda0950957b1dc85ef0f74ac` | same |
| `/usr/bin/mkenvimage` | 8836 | `8b919cc0f19143010e3a22d2465bd8f4` | same |
| `/usr/bin/kobs-ng` | 178968 | `7ca92eaa8a3aacebde869152d8f148ce` | **differs** (`aa295e09804bc28108a393b6b54729e9`) |
| `/usr/bin/mmc` | 69460 | `089edf1cb5a5006c59fe5736ac995af1` | same |
| `/usr/sbin/sgdisk` | 112740 | `700fd047d3b7541a35fa35e920596b4c` | same |
| `/usr/sbin/flashrom` | 334416 | `46eaf6560ed9b9873b899da498a4b3d3` | same |
| `/usr/sbin/flash_otp_dump` | 3724 | `d8383f5021a108260026fb4769dafdc5` | same |
| `/usr/sbin/flash_otp_info` | 3820 | `964506ed7c616e43f85c3f01caa1c940` | same |
| `/usr/sbin/flash_otp_lock` | 4612 | `c70a963e0788fad081d6557e86436719` | same |
| `/usr/sbin/flash_otp_write` | 4544 | `aee64d3aba5a8c233e30067dcb6fc8ae` | same |
| `/usr/sbin/flash_lock` | 4148 | `6a0cb603bbaf70f71321165f77819c17` | same |
| `/usr/sbin/flash_unlock` | 4152 | `6c271f4791c182fa2e742c576f5cf8da` | same |
| `/usr/sbin/flash_erase` | 25060 | `20735805a68e6e540ec3e699732190f8` | same |
| `/usr/sbin/flashcp` | 10008 | `d90cc0ea0ea95f7fec681eb141ac8e53` | same |
| `/usr/sbin/mtd_debug` | 7512 | `25b0ac26881efb77fff0851140122845` | same |
| `/usr/sbin/mtdinfo` | 26252 | `ee335d2de65f37c3e347a74b99b7dfcb` | same |
| `/usr/sbin/nanddump` | 26324 | `efc48717280b40b61633adb9874f41fb` | same |
| `/usr/sbin/nandwrite` | 28340 | `cc8ba7b5fdc7e5e014f6307cad2ddeb2` | same |
| `/usr/sbin/nandtest` | 7764 | `ba26c5a992ea2773537f5672ec66714d` | same |
| `/usr/bin/flashbench` | 23532 | `16f46c3536f86c09d7d10b28c14fd229` | same |
| `/usr/bin/mksquashfs` | 124768 | `1a6cc5986154b8682995d376f2066d56` | same |
| `/usr/bin/unsquashfs` | 64324 | `d04911a3235795757d445df0cde914b2` | same |
| `/usr/sbin/mkfs.jffs2` | 31332 | `e0a5f57a1b4518be5b2b3d7a0c8b5977` | same |
| `/usr/sbin/ubiattach` | 16740 | `fe90154a2645ee95a8e354b1e9a393bb` | same |
| `/usr/sbin/ubiblock` | 11420 | `6e57966c6741b4b8d3aa2423954e5c27` | same |
| `/usr/sbin/ubicrc32` | 5696 | `7a10c707c970087b3b81526b5a2e09ee` | same |
| `/usr/sbin/ubidetach` | 12784 | `8d7959690411b4903be0ccfde8fbe98c` | same |
| `/usr/sbin/ubiformat` | 47356 | `b2ae7efc8609966474223aa2cb4aebfd` | same |
| `/usr/sbin/ubimkvol` | 19068 | `67cf3bb42969da6a14d8f26f34c206d9` | same |
| `/usr/sbin/ubinfo` | 20780 | `88a15d7fead58a90f82ac466f776a944` | same |
| `/usr/sbin/ubinize` | 30476 | `90f20e8bcd8677ba04e2c7f03357cca0` | same |
| `/usr/sbin/ubirename` | 13932 | `49baf545874ef42b0d8fe5a753963ebc` | same |
| `/usr/sbin/ubirmvol` | 14932 | `2d7891ed88d9438aaafc8b4de558a29c` | same |
| `/usr/sbin/ubirsvol` | 16348 | `fcbd7074bac4e17612b85b468a940aa4` | same |
| `/usr/sbin/ubiupdatevol` | 15728 | `bd6f3d9077f5338cd59641e67c0d282b` | same |
| `/lib/udev/mtd_probe` | 3884 | `d99380509e7eb1c313e3585b707fa897` | same |
| `/lib/udev/rules.d/75-probe_mtd.rules` | 174 | — | same |
| `/sbin/devmem` | symlink → `../bin/busybox` | — | symlink same, busybox differs |
| `/sbin/fdisk` | 82804 | `e11dec8d7367a471b129e059f70c441b` | differs |

**[READ]** All are `ELF 32-bit LSB executable, ARM, EABI5 … dynamically linked …
stripped`, `Cortex-A9` ABI tag, `interpreter /lib/ld-linux-armhf.so.3`.

**[READ]** `/etc/fw_env.config` **does not exist** — `find . -name 'fw_env*'`
over the whole of `rootfs-1.8.2` and `rootfs-1.5.0` returns nothing but the
binary itself.

**[READ]** The name lists of `/usr/bin` and `/usr/sbin` are **identical** between
1.5.0 (May 2022) and 1.8.2 (September 2025) — `diff <(ls 1.5.0/usr/sbin) <(ls
1.8.2/usr/sbin)` and the same for `usr/bin` are both empty. Nothing in this
toolchain was added or removed in three and a half years.

### 1.1 Who calls any of it: nobody

**[READ]** `grep -rl --binary-files=text` over the entire 492 MB tree:

| string | files that contain it |
|---|---|
| `fw_printenv` | `usr/sbin/fw_printenv` only |
| `fw_setenv` | `usr/sbin/fw_printenv` only |
| `fw_env` | `usr/sbin/fw_printenv` only |
| `kobs-ng` | `usr/bin/kobs-ng` only |
| `mkenvimage` | **nothing** |
| `mkimage` | `usr/bin/mkimage` only |
| `flash_otp` | the four `flash_otp_*` binaries only |
| `flashcp`, `flash_unlock`, `nandwrite`, `ubiformat` | each, only itself |
| `flash_erase` | itself and `usr/bin/gdb` (unrelated symbol table) |
| `bootcmd` | `usr/sbin/fw_printenv` only |
| `bootargs` | `usr/sbin/fw_printenv` only |
| `mtdparts` | **nothing** |
| `add_args` | `boot/cmdline.img`, `boot/cmdline.txt` |
| `mmcblk2` | `usr/bin/lasfwu` (7×), `etc/fstab` |

No init script, no service, no updater, no cron job invokes a single one of these
tools. They are **inert payload from the BSP image recipe**. **[INFERRED]** —
from the exhaustive grep plus the absence of any config file for them.

---

## 2. `fw_printenv` / `fw_setenv`, read out of the binary

### 2.1 Identity and command line

**[READ]** `strings -a -t d usr/sbin/fw_printenv`, offsets shown:

```
18672  fw_printenv/fw_setenv, a command line interface to U-Boot environment
18750  fw_printenv [-c /my/fw_env.config] [-a key] [-n] [variable name]
18816  fw_setenv [-c /my/fw_env.config] [-a key] [variable name] [variable value]
18892  fw_setenv -s [ file ]
18915  fw_setenv -s - < [ file ]
19496  a:c:ns:h
19508  fw_printenv
19520  fw_setenv
19532  Identity crisis - may be called as `fw_printenv' or as `fw_setenv' but not as `%s'
19616  script
19624  help
```

**[READ]** The getopt string is `a:c:ns:h`; `--script` (`s`) and `--help` (`h`)
are the only long options — confirmed by reading the `struct option[]` array in
`.data` at vaddr `0x26238`: `{"script", 1, NULL, 's'}`, `{"help", 0, NULL, 'h'}`,
`{0,0,0,0}`.

**[READ]** `/var/lock/fw_printenv.lock` (offset 19376) is `flock`ed at entry —
the first thing `main` does is `movw r0, #0x4bb0 / movt r0, #0x1` (= vaddr
`0x14bb0` = that string) at `0x10af4`, followed by `bl flock@plt` at `0x10b24`.

### 2.2 The config file it demands, exactly

**[READ]** `.data` at vaddr `0x2631c` holds the pointer `0x00015240`, and vaddr
`0x15240` is the string `/etc/fw_env.config`. This is U-Boot's
`static char *config_file = CONFIG_FILE;` and is what `-c` overwrites.

**[READ]** The parser is the function at `0x122ac`. Disassembled:

```
122ac: push  {r4..r11, lr}
122b0: movw  r11, #0x6268
122b4: movw  r1,  #0x4ff8          ; r1 = "r"
122b8: movt  r11, #0x2             ; r11 = 0x26268
122c4: ldr   r0,  [r11, #0xb4]     ; r0 = *(0x2631c) = config_file
122c8: bl    fopen@plt
122cc: subs  r7,  r0, #0
122d0: beq   0x128cc                ; NULL -> failure path
...
122dc: cmp   r5, #1                 ; loop bound: at most 2 entries
122f4: mov   r1, #128               ; 128-byte line buffer
12300: bl    fgets@plt
12320: ldrb  r12, [sp, #0x18]
12324: cmp   r12, #35               ; '#' -> comment, skip line
12338: bl    sscanf@plt             ; format at 0x14ffc
1233c: cmp   r0, #2
12340: ble   0x122f4                ; fewer than 3 fields -> skip line
```

**[READ]** the format string at vaddr `0x14ffc` is `%ms %lx %lx %lx %lx`, and
five destination pointers are passed (`r2`, `r3`, then `r4+4`, `r4+8`, `r4+12` on
the stack).

So the file this binary needs is, precisely:

* up to **two** entries (two lines) — two means a **redundant** environment pair;
* each line: `<device-path> <hex offset> <hex env size> [<hex erase/sector size>] [<hex sector count>]`;
* at least three fields per line or the line is silently ignored;
* lines beginning `#` are comments; line buffer 128 bytes.

### 2.3 What it does with no config file — the failure is fatal

**[READ]** The `beq 0x128cc` above lands on:

```
128cc: bl    __errno_location@plt
128d0: ldr   r0, [r0]              ; r0 = errno
128d4: b     0x12510
...
12510: movw  r3, #0x6320           ; r3 = &stderr
12520: bl    strerror@plt
12524: movw  r1, #0x50cc           ; "Cannot parse config file '%s': %s\n"
12538: bl    fprintf@plt
1253c: mvn   r7, #0                ; return -1
12548: pop   {r4..r11, pc}
```

**[READ]** `0x150cc` is `Cannot parse config file '%s': %s\n`. **[INFERRED]**
(from the fixed control flow above, and `ENOENT` → `strerror` → "No such file or
directory"): running `fw_printenv` on a stock instrument prints

```
Cannot parse config file '/etc/fw_env.config': No such file or directory
```

and exits non-zero, having touched nothing but the lock file. It is **safe** but
**useless** as shipped.

### 2.4 The compiled-in default environment is a decoy

**[READ]** `.data`, vaddr `0x26264`–`0x2631c`, 184 bytes, NUL-separated:

```
bootcmd=bootp; setenv bootargs root=/dev/nfs nfsroot=${serverip}:${rootpath} ip=${ipaddr}:${serverip}:${gatewayip}:${netmask}:${hostname}::off; bootm
bootdelay=5
baudrate=115200
```

**[READ]** and the binary contains `Warning: Bad CRC, using default environment`
(offset 20580).

**[INFERRED]** This is U-Boot's *generic* `default_environment[]` — a plain NFS
netboot. It is **not** this board's default environment: no Moog string, no
`mmc`, no `mmcblk`, no `add_args`, no reference to `/boot/uImage`. The tool was
built from a stock U-Boot tree with no board config applied. **Consequence:** if
anyone ever gets this tool working and the stored environment fails its CRC, what
it prints will be this NFS boilerplate, and it will look like a real reading of
the device. It is not. Anyone citing `fw_printenv` output must first confirm no
"Bad CRC" warning was emitted.

### 2.5 It supports a plain block device — the eMMC qualifies

This matters, because the instrument has no MTD (§3) and a naive reading of the
tool's MTD strings would suggest it cannot work here at all.

**[READ]** The device-open function at `0x11384`:

```
113ac: bl    open@plt              ; open(DEVNAME(dev), mode)
113b8: blt   0x11b50               ; -> "Can't open %s: %s"
113c4: mov   r0, #3
113d0: bl    __fxstat@plt          ; fstat(fd, &st)
113d8: blt   0x11b98               ; -> "Cannot stat the file %s"
113dc: ldr   r3, [sp, #0x68]       ; st.st_mode
113e0: and   r3, r3, #0xF000
113e4: cmp   r3, #0x2000           ; S_IFCHR
113e8: beq   0x11704               ; only then: MEMGETINFO ioctl
113ec: mov   r3, #0                ; else mtd_type = 0  (MTD_ABSENT)
```

**[READ]** `0x11704` is the branch that reaches `Cannot get MTD information for
%s` (vaddr `0x14ea4`). **[INFERRED]** Therefore: the `MEMGETINFO` ioctl and every
"Unsupported flash type"/"Cannot access MTD device" path applies **only when the
configured device is a character device**. A *block* device such as
`/dev/mmcblk2` skips all of it and is treated as a flat file with an offset. This
is the standard U-Boot `MTD_ABSENT` behaviour and it means **`fw_printenv` can
read a raw-sector environment on this eMMC, given a correct config line.**

**[READ]** `fw_printenv` opens the device with the mode passed into that
function; the caller path for printing does not take the `cmp r5, #2`
(`O_RDWR`) branch at `0x113bc`. **[INFERRED]** (standard `O_RDONLY == 0`):
`fw_printenv` opens the backing device **read-only**. It cannot write, whatever
config file it is given. `fw_setenv` is the same binary dispatched on `argv[0]`
and *can* write.

### 2.6 Redundant environment, AES, flags

**[READ]** Strings present, all part of U-Boot's `fw_env.c`:

| offset | string | meaning |
|---|---|---|
| 20016 | `Cannot seek to set the flag on %s ` | redundant-env obsolete-flag write |
| 20052 | `Could not set obsolete flag` | redundant-env commit |
| 20656 | `Unknown flag scheme %u ` | flag scheme dispatch |
| 20628 | `Incompatible flash types!` | two config lines of different type |
| 19640 | `## Error: '-a' option requires 16-byte AES key` | AES support compiled in |
| 19688 | `## Error: '-a' option requires valid AES key` | |
| 20292 | `Error: can't encrypt env for flash` | AES **write** support |
| 22508 | `.flags` | U-Boot per-variable flags variable |
| 22516 | `serial#:so,` | compiled-in static flags list |
| 22528 | `## Error: flags type check failure for "%s" <= "%s" (type: %c)` | |
| 22392 | `## Warning: Unknown environment variable type '%c'` | |
| 22444 | `## Warning: Unknown environment variable access method '%c'` | |
| 20204 | `## Error: environment not terminated` | |
| 20244 | `## Error: default environment not terminated` | |
| 20428 | `Error: environment overflow, "%s" deleted` | |

**[READ]** AES S-box and inverse tables occupy `.rodata` from roughly offset
22640 to 24700 (the characteristic `c|w{`, `AAAAAA`/`BBBBBB` and the four
T-table blocks), confirming a real AES-128 implementation rather than just the
error strings.

**[INFERRED]** So the environment on this device *could* be AES-encrypted and
this tool could still read it — but only with the 16-byte key, which is not
present anywhere in the rootfs (**[READ]**: no `fw_env`-adjacent key file exists;
`/etc/mmsk` and `/etc/mmek`, referenced as variables in `lasfwu:29-30`, are also
absent from the shipped rootfs). Whether the environment is encrypted at all is
**[UNKNOWN]**.

### 2.7 Correction: a prior capture's "fw_printenv: not found" is a PATH artifact

**[READ]** `captures/harvest/04-tools.txt`, section `################ U-BOOT
ENVIRONMENT ################`, records exactly one line from the live
instrument:

```
sh: fw_printenv: not found
```

**[INFERRED]** This is **not** evidence that the binary is absent. The same
capture file records `/usr/bin/config-las-spi: line 57: devmem: not found`, and
`devmem` demonstrably exists at `/sbin/devmem` (**[READ]**, symlink to busybox,
in both rootfs versions). The harvest shell's `PATH` excluded `/sbin` and
`/usr/sbin`. `fw_printenv` was present at `/usr/sbin/fw_printenv` in the exact
1.5.0 image the instrument was running (**[READ]**, `rootfs-1.5.0`, md5 identical
to 1.8.2). Any future live probe must use the absolute path.

---

## 3. The MTD half of the toolchain is inert: there is no flash device

### 3.1 The device tree says NAND; the hardware says no

**[READ]** `boot/imx6dl-profili-som.dtb` (42345 bytes, md5
`87f2b786154093a604071df4d044824e`, **identical in 1.5.0 and 1.8.2**), root
properties:

```
model      = "Variscite i.MX6 DL/Solo SOM-SOLO SOM-DUAL SoloCustomBoard"
compatible = "fsl,imx6q-var-som", "fsl,imx6q"
```

**[READ]** `/soc/gpmi-nand@00112000` is `compatible = "fsl,imx6q-gpmi-nand"`,
**`status = "okay"`**, with `reg-names = "gpmi-nand","bch"` and a seven-entry
partition table:

| node | label | offset | size |
|---|---|---|---|
| `partition@0` | `spl` | `0x00000000` | `0x00200000` |
| `partition@1` | `bootloader` | `0x00200000` | `0x00200000` |
| `partition@2` | `kernel` | `0x00400000` | `0x00600000` |
| `partition@3` | `rootfs` | `0x00a00000` | `0x3f600000` |
| `partition@4` | `android_boot` | `0x00400000` | `0x01000000` |
| `partition@5` | `android_recovery` | `0x01400000` | `0x01c00000` |
| `partition@6` | `android_rootfs` | `0x03000000` | `0x3d000000` |

**[INFERRED]** This is Variscite's stock VAR-SOM-MX6 NAND map (note the
overlapping "android_*" alternatives and the `imx6qdl-var-som-mx6` pinctrl group
names in the same DTB, **[READ]**). It describes a SOM variant Moog does not
ship. It is **not** a description of this instrument's storage.

**[READ]** `dmesg-before-reboot.txt`:

```
[    0.485131] nand: No NAND device found
[    0.485276] gpmi-nand 112000.gpmi-nand: driver registration failed: -19
```

**[READ]** The only SPI controller that is enabled is
`ecspi@02008000` (`spi0`, `status = "okay"`), and its only child is
`spidev@0` (`compatible = "spidev"`) — a userspace character device, **not** an
`m25p80`/`spi-nor` flash node. `ecspi@0200c000`, `@02010000` and `@02014000` are
all `status = "disabled"`. `fsl-quadspi` is built in but no QSPI node exists.

**[INFERRED]** Therefore **no MTD device is instantiated and `/dev/mtd*` does not
exist**. **[READ]** corroboration: `rootfs-1.8.2/dev/` contains only `log`,
`pts`, `shm` — devtmpfs creates everything at runtime, and udev's
`75-probe_mtd.rules` (`KERNEL=="mtd*ro", IMPORT{program}="mtd_probe $devnode"`)
has nothing to match.

### 3.2 Every MTD tool therefore has no target

**[READ]** Each of these opens a `/dev/mtdN` node and fails without one:

| tool | evidence |
|---|---|
| `flash_erase` | `Usage: %s [options] MTD_DEVICE …`, `/dev/mtd%d`, `MEMGETINFO ioctl request failed` |
| `flashcp` | `<device>  Flash device to write to (e.g. /dev/mtd0, /dev/mtd1, etc.)` |
| `mtd_debug` | `usage: %1$s info <device>`, `MEMGETINFO`, `MEMERASE` |
| `mtdinfo` | `Usage: %1$s <MTD node file path>`, `mtdinfo /dev/mtdX` |
| `nanddump`, `nandwrite`, `nandtest` | `/dev/mtd%d`, `MEMGETINFO` |
| `flash_lock`, `flash_unlock` | `%s: error!: %#x is beyond device size %#x` |
| `ubi*` (12 tools) | UBI attaches to MTD |
| `kobs-ng` | see below |

**[READ]** `kobs-ng` internals: `mtd_init failed!`, `mtd_read_page`,
`mtd_write_page`, `mtd_commit_bcb`, `mtd: device %s not NAND`, `mtd: device %s
fails MEMGETINFO: %d`, `mtd: found NCB%d candidate version %d @%d:0x%llx`,
`mtd: NCB%d not found`, `/dev/mtd1`, `FCB `, and the commands `extract`,
`init`, `update`, `imgverify`. It writes NAND Boot Control Blocks (FCB/DBBT).
Useless without NAND.

**[READ]** The **only** difference between the 1.5.0 and 1.8.2 `kobs-ng`
binaries — same size, 178968 — is one 40-hex-character build identifier in
`.rodata`, sitting between the strings `imgverify` and `mtd_read_page`:

```
1.5.0:  f77b0d82fd7581dd8c139a451f88c736cda70030
1.8.2:  9144962cb109e97cfde5926b97e254f070df7c6c
```

**[READ]** the adjacent format string is `kobs-ng version : [ %d.%d ] git hash
(%s)`. **[INFERRED]** the tool was rebuilt from a newer `imx-kobs` commit and is
otherwise byte-identical; nothing about the instrument changed.

**[READ]** `mksquashfs`/`unsquashfs`/`mkfs.jffs2` are present; **[READ]** no
`.squashfs` or `.sqfs` file exists anywhere in the tree, and every root
filesystem is ext4 (`etc/fstab`, and `EXT4-fs (mmcblk2p3): mounted filesystem` in
dmesg). **[READ]** `jffs2` is built into the kernel (`jffs2: version 2.2. (NAND)`
at boot) and `ubifs.ko` is in `modules.builtin`; neither has a device.

### 3.3 The `flash_otp_*` tools do **not** read i.MX6 fuses

This corrects the premise of this gap assignment.

**[READ]** `flash_otp_info` strings, with offsets:

```
2028  factory
2036  user
2041  [locked]
2050  [unlocked]
2067  Usage: %s [ -f | -u ] <device>
2114  OTPSELECT
2124  OTPGETREGIONCOUNT
2142  Number of OTP %s blocks on %s: %d
2177  block %2d:  offset = 0x%04x  size = %2d bytes  %s
```

**[READ]** `flash_otp_dump`: `OTPSELECT`, `OTP %s data for %s`, `0x%04x:`, ` %02x`.
**[READ]** `flash_otp_lock`: `OTPSELECT`, `OTPLOCK`, `CAUTION! ONCE LOCKED, OTP
REGIONS CAN'T BE UNLOCKED!`, `About to lock OTP user data on %s from 0x%x to
0x%x`, `Are you sure?`. **[READ]** `flash_otp_write`: `MEMGETINFO`, `Writing OTP
user data on %s at offset 0x%llx`, `Wrote %d bytes of OTP user data`.

`OTPSELECT`, `OTPGETREGIONCOUNT`, `OTPLOCK` and `MEMGETINFO` are **MTD** ioctls.
The "factory" and "user" OTP regions they address are a property of NOR and NAND
flash chips (**[INFERRED]**, from the ioctl names and the `-f`/`-u` region
selector). They have no connection to the i.MX6 OCOTP block at `0x021bc000`, and
on this board they have no device to open at all.

**Nothing in this rootfs can blow an i.MX6 fuse via these four binaries.**
**[INFERRED]**

---

## 4. The path that *does* answer the HAB question: `fsl_otp` in the kernel

### 4.1 It is built in

**[READ]** `lib/modules/4.1.15-rt18/modules.builtin`, line 93:

```
kernel/drivers/char/fsl_otp.ko
```

**[READ]** `lib/modules/4.1.15-rt18/` contains only **two** `.ko` files in total;
everything else in `modules.builtin` is compiled into `uImage`.

**[READ]** In the decompressed kernel (`boot/uImage`, `Linux-4.1.15-rt18`, gzip
payload at offset `0x4718` past the 64-byte header, 10,214,816 bytes
uncompressed):

```
fsl_otp
imx-ocotp
&otp_mutex
&(&otp_mutex)->lock
fsl,imx6q-ocotp
fsl,imx6sl-ocotp
fsl,imx6sx-ocotp
fsl,imx6ul-ocotp
fsl,imx7d-ocotp
```

**[READ]** The DTB node `/soc/aips-bus@02100000/ocotp@021bc000` is
`compatible = "fsl,imx6q-ocotp", "syscon"` with `clocks = <&clks 0x80>` and no
`status` property (therefore enabled).

**[INFERRED]** The driver's compatible list contains `fsl,imx6q-ocotp`, the DTB
node advertises it, so the driver binds and its sysfs tree is created. The NXP
`fsl_otp` driver creates a kobject named `fsl_otp` directly under `/sys`, giving
`/sys/fsl_otp/HW_OCOTP_*` — **[INFERRED]** from the driver name string and the
attribute-name table below; the exact directory has not been observed on the
instrument and is a validation-plan item.

### 4.2 The full fuse surface it publishes

**[READ]** 266 distinct `HW_OCOTP_*` attribute names in the kernel image. The
ones that bear on secure boot, identity and boot media:

| name | what it holds | grade |
|---|---|---|
| `HW_OCOTP_CFG5` | `SEC_CONFIG` — the "HAB open vs closed" word | [READ] name; [INFERRED] meaning |
| `HW_OCOTP_SRK0` … `HW_OCOTP_SRK7` | the 256-bit SRK (super-root-key) hash | [READ] name; [INFERRED] meaning |
| `HW_OCOTP_SRK_REVOKE` | per-key revocation bits | [READ] name |
| `HW_OCOTP_LOCK` | per-region lock bits, incl. the SRK-hash lock | [READ] name |
| `HW_OCOTP_BOOT_CFG0`…`BOOT_CFG4` | boot-device / boot-mode fuses | [READ] name |
| `HW_OCOTP_FIELD_RETURN` | field-return (un-secure) fuse | [READ] name |
| `HW_OCOTP_CFG0`, `HW_OCOTP_CFG1` | the chip UID | [READ] name; [INFERRED] meaning |
| `HW_OCOTP_MAC0`…`MAC2`, `MAC_ADDR0`…`2` | MAC addresses | [READ] name |
| `HW_OCOTP_ANA0`…`ANA2`, `MEM_TRIM0/1`, `TESTER0`…`5` | analog/thermal calibration | [READ] name |
| `HW_OCOTP_OTPMK0`…`OTPMK7` | CAAM master key (write-only in silicon) | [READ] name |
| `HW_OCOTP_GP1`, `GP2`, `GP_LO0..7`, `GP_HI0..7`, `SW_GP0..4`, `GP30..GP83` | general-purpose / customer fuses | [READ] names |
| `HW_OCOTP_ROM_PATCH0`…`15`, `HSJC_RESP1`, `SJC_RESP0/1`, `RESP0` | ROM patch, JTAG challenge/response | [READ] names |
| `HW_OCOTP_HDCP_KEY0`…`71`, `HDCP_KSV0/1`, `DTCP_KEY0..4`, `MAU_KEY0..7` | content-protection keys | [READ] names |
| `HW_OCOTP_CRC`, `CRC0..7`, `CRC_GP10/11/20/21` | fuse CRCs | [READ] names |
| `HW_OCOTP_MISC_CONF`, `USB_ID`, `MEM0..4` | misc | [READ] names |

**[INFERRED]**, from the NXP i.MX6 fuse map (an external reference, **not**
anything in this capture): `SEC_CONFIG[1]` lives in bit 1 of `CFG5`; `0` means
the chip is in **open** configuration (HAB does not enforce signatures) and `1`
means **closed**. **Nothing in the rootfs, the kernel or the DTB states this**,
and this report has not verified it against silicon. Treat the reading of the
value as data and the interpretation as hypothesis until the reference manual is
consulted alongside the actual word.

### 4.3 This is the one genuinely dangerous surface, and it is a `cat` away

**[UNKNOWN]** whether the `/sys/fsl_otp/*` attributes are writable in this build
— the NXP driver historically registers them read-write, and writing one **blows
a fuse permanently**. The mode bits were not recovered from the binary.

Consequence for the validation plan: **`cat` only. Never `echo` into anything
under `/sys/fsl_otp/`.** There is no undo. This is the single most destructive
thing reachable on this instrument from a shell, more so than any of the flash
tools in §1, because it survives a full re-image.

### 4.4 Where the existing docs stand

**[READ]** `docs/firmware/kernel.md:1071-1076` records `ocotp@021bc000` only as
`fsl,imx6q-ocotp`, `syscon` — "used by the thermal driver for calibration" — and
`kernel.md` §5 documents `fsl,tempmon-data = <&ocotp>` and the driver strings
`invalid sensor calibration data`. That is correct and is a *different* consumer
(the `syscon` regmap path used by `imx_thermal`). The `fsl_otp` character driver
and the sysfs fuse surface are a second, independent consumer of the same block
and are not mentioned in any of the 25 reports in `docs/firmware/`.

---

## 5. The eMMC: the boot media that actually exists

### 5.1 What the boot log says

**[READ]** `dmesg-before-reboot.txt`:

```
[    0.593757] mmc0: SDHCI controller on 2194000.usdhc [2194000.usdhc] using ADMA
[    0.714617] mmc2: SDHCI controller on 2198000.usdhc [2198000.usdhc] using ADMA
[    0.821350] mmc2: MAN_BKOPS_EN bit is not set
[    0.844722] mmc2: new DDR MMC card at address 0001
[    0.853731] mmcblk2: mmc2:0001 NCard  7.21 GiB
[    0.853894] mmcblk2boot0: mmc2:0001 NCard  partition 1 4.00 MiB
[    0.863627] mmcblk2boot1: mmc2:0001 NCard  partition 2 4.00 MiB
[    0.863791] mmcblk2rpmb: mmc2:0001 NCard  partition 3 4.00 MiB
[    0.868809]  mmcblk2: p1 p2 p3 p4 p5 p6 p7
```

**[READ]** `usdhc@02198000` is the eMMC (`non-removable`, `vmmc-supply`,
`pinctrl` states for 100 MHz and 200 MHz); `usdhc@02194000` is a removable slot
(`cd-gpios`, `cd-inverted`, `no-1-8-v`); `usdhc@02190000` and `@0219c000` are
`disabled`.

**[READ]** The eMMC has three hardware partitions besides the user area: two
4 MiB boot partitions and a 4 MiB RPMB. These are already noted in
`kernel.md:742`, `init-boot.md:115`, `gap-udev-device-naming-layer.md:344` and
`arch/hardware-external.md:450`, and `kernel.md:1942-1945` already offers the
hypothesis that they hold U-Boot. What is new here is that `/usr/bin/mmc` is on
the instrument and can read `PARTITION_CONFIG` to settle which of them (if
either) the BootROM is actually pointed at (§5.3, §12.4).

### 5.2 Seven GPT partitions, five accounted for

**[READ]** `etc/fstab` and the live `mount`/`df`:

| partition | mount | fs | size |
|---|---|---|---|
| `mmcblk2p1` | — | ext4 | factory root (`lasfwu:469-470`, `case $currentpartition in` / `1)`) |
| `mmcblk2p2` | `/mnt/u1` (`ro,noauto`) | ext4 | upgrade slot 1 |
| `mmcblk2p3` | `/mnt/u2` (`ro,noauto`) | ext4 | upgrade slot 2 |
| `mmcblk2p4` | `/var/lib/sys` | vfat | 62.9 M |
| `mmcblk2p5` | **not referenced anywhere** | ? | ? |
| `mmcblk2p6` | `/var` | ext4 | 3.8 G |
| `mmcblk2p7` | `/mnt/fwu` | ext4 | 861.9 M |

**[READ]** the live root reports `636.8M` (`sysmap/01-hardware.txt`), matching the
update package's `"unpacked_size" : "670012416"` (639 MiB) in
`captures/firmware-1.8.2/pkg/MANIFEST`.

**[UNKNOWN]** What `mmcblk2p5` is, and where the first partition begins. `grep`
for `mmcblk2p5` over the whole tree returns nothing. **[INFERRED]** arithmetic:
3 × ~655 MiB + 64 MiB + 3.9 GiB + 896 MiB ≈ 6.76 GiB of the 7.21 GiB, leaving
roughly 450 MiB for `p5` plus whatever gap precedes `p1`. That is a weak bound
and it is a validation-plan item.

### 5.3 `mmc-utils` is on the instrument and nobody has said so

**[READ]** `/usr/bin/mmc`, 69460 bytes, identical in both versions. Command set,
from its usage strings:

| command | effect |
|---|---|
| `extcsd read <dev>` | dump EXT_CSD — **read-only** |
| `status get <dev>` | SEND_STATUS — read-only |
| `cid read` / `csd read` / `scr read` | read-only |
| `writeprotect boot get` / `user get` | read-only |
| `bootpart enable <n> <ack> <dev>` | sets `PARTITION_CONFIG` — chooses which boot partition the i.MX6 BootROM reads |
| `bootbus set …` | `BOOT_BUS_CONDITIONS` |
| `writeprotect boot set` / `user set <type>…` | `pwron` or **`perm`** write protection |
| `hwreset enable` / `hwreset disable` | **permanent** — `H/W Reset is already permanently enabled/disabled on %s` |
| `gp create`, `enh_area set`, `write_reliability set` | one-shot partitioning; guarded by `PARTITION_SETTING_COMPLETED` |
| `sanitize`, `bkops enable`, `cache enable/disable`, `disable 512B emulation` | |
| `rpmb write-key / read-counter / read-block / write-block` | **compiled out** |

**[READ]** the binary states:

```
mmc-utils has been compiled without MMC_IOC_MULTI_CMD support, needed by RPMB operation.
mmc-utils has been compiled without MMC_IOC_MULTI_CMD support, needed by FFU.
```

so RPMB and field firmware update are non-functional in this build.

**[READ]** the `gp create` path prints `setting OTP PARTITION_SETTING_COMPLETED!`
and `Setting OTP PARTITION_SETTING_COMPLETED on %s SUCCESS`. **[INFERRED]** That
bit is one-time-programmable in the eMMC and, once set, the partition geometry is
frozen for the life of the device. `mmc gp create` and `mmc enh_area set` are
therefore as irreversible as an i.MX6 fuse, on a par with §4.3.

**[READ]** Nothing in the rootfs invokes `/usr/bin/mmc` — the only occurrences of
`mmcblk0` in the tree are inside the binary's own help text.

### 5.4 The updater's `dd`, and what it implies about the front of the disk

**[READ]** `usr/bin/lasfwu` is a 33940-byte bash script, identical in both
versions, header `# Created by Chris Howe on 6/26/17`. It writes the new
root filesystem with `dd … of=/dev/mmcblk2p$replacepart` and then, at
`lasfwu:821-827`:

```sh
#wipe falcon space check if the SOM even supports falcon space first
startofpartmap=`sgdisk -i=1 /dev/mmcblk2 | awk -F "First sector:" '{print $2}' | awk -F "(" '{
print $1}'`

if [ $startofpartmap > 60000 ]; then
	    dd if=/dev/zero of=/dev/mmcblk2 bs=1024 count=16384 seek=1024
fi;
rm 60000;
```

The bash defect here (`>` is a redirection, not a comparison, so the guard never
guards) is already documented in `init-boot.md` §8.6 and is not re-claimed here.
What is new is the **boot-chain consequence**:

**[INFERRED]** every successful firmware update zeroes the raw eMMC from byte
offset **0x100000 (1 MiB) to 0x1100000 (17 MiB)**. The author's comment names
that region "falcon space" — U-Boot's Falcon mode stores its pre-parsed kernel
`args` blob at a raw sector offset. Therefore:

* **Any U-Boot environment stored in a raw region inside 1–17 MiB would be
  destroyed on every update.** Since updates demonstrably work, either the
  environment is outside that window, or it is not in a raw region at all, or the
  environment is re-created by U-Boot from its built-in defaults on every boot.
  **[INFERRED]**
* The i.MX6 BootROM reads its boot image from **offset 1 KiB** (sector 2) of the
  selected boot medium, which is *below* the wiped window — so U-Boot/SPL itself
  survives. **[INFERRED]** (BootROM offset is external NXP reference, not read
  from this capture.)
* The `> 60000` sector threshold (≈30.7 MB) tells us the author expected
  partition 1 to begin well past the 17 MiB wipe on SOMs that use Falcon mode.
  **[INFERRED]** It does not tell us where it begins here.

**[READ]** The update package contains **no bootloader**:
`captures/firmware-1.8.2/pkg/` holds `MANIFEST`, `MOOGFW`, `MANIFEST-SIG`,
`IMAGE-SIG` and a single 156,599,799-byte `rootfs` image, and `MANIFEST` names
exactly one payload: `"image" : "rootfs"`. `lasfwu` writes it to one ext4
partition and nothing else. **[INFERRED]** **U-Boot is never updated by a
firmware update.** The bootloader on the instrument may predate v1.5.0 by years,
and is the same binary regardless of which firmware version is installed.

### 5.5 Boot-slot selection is FAT files, not U-Boot environment variables

Already documented in `init-boot.md` §8.7 and `diff-upgrade.md` §R3; restated
here only because it is the answer to "does anything on this device use
`fw_setenv` to steer the boot?" — **no**.

**[READ]** `lasfwu:564` `echo 0 > /var/lib/sys/sentinelu$part`; `:566-568`
`echo "$version" > /var/lib/sys/bootversion`; `:808` `cat
"/mnt/u$part/etc/versionb" > "/var/lib/sys/sentinelu$part"`; `:809`
`echo $replacepart > "/var/lib/sys/bootme"`. All on `/dev/mmcblk2p4`, **vfat**.

**[READ]** — new detail — the sentinel payload is `etc/versionb`, an 8-byte
binary file:

```
1.8.2:  ff 02 08 01 00 00 00 00
1.5.0:  ff 00 05 01 00 00 00 00
```

**[INFERRED]** little-endian `u32` = `0x010802ff` and `0x010500ff`, i.e.
`(major<<24)|(minor<<16)|(patch<<8)|0xff` — 1.8.2 and 1.5.0 respectively —
followed by four zero bytes. **[READ]** `etc/version` alongside it is the text
`las-v1.8.2` / `las-v1.5.0`. A consumer comparing two slots' sentinels as a
single little-endian `u32` gets a correct "newer version" ordering.

**[INFERRED]** U-Boot must therefore be built with FAT support and a boot script
that reads `bootme` and the sentinels from `mmcblk2p4`. That is a fifth
independent argument (alongside `init-boot.md`'s) that the boot policy lives in
U-Boot and is invisible from Linux.

### 5.6 How the kernel command line is assembled

**[READ]** the command line the kernel actually received —
`dmesg-before-reboot.txt` and `arch-harvest/runtime-state.txt` line 2, a category
the caveat file certifies as uncontaminated:

```
console=ttymxc1,115200{smp} root=/dev/mmcblk2p3 rootwait isolcpus=1 quiet loglevel=0 galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1
```

**[READ]** `boot/cmdline.img` (189 bytes, md5 `6a6aa900d354c703cfdab914ba41640d`,
**identical in 1.5.0 and 1.8.2**) is a U-Boot legacy image, magic `0x27051956`,
type "Script File", name `Additional Kernel Args`, 125-byte payload:

```
setenv add_args isolcpus=1 quiet loglevel=0  galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1
```

**[INFERRED]** The only U-Boot command that consumes a "Script File" image is
`source`. The payload's only effect is to define `add_args`, whose only possible
consumer is U-Boot's own bootargs assembly. Splitting the observed cmdline at the
seam gives the **base bootargs that live in the U-Boot environment**:

```
console=ttymxc1,115200{smp} root=/dev/mmcblk2p3 rootwait
```

with `root=` chosen per-boot from `bootme`. This is the closest anyone has come
to reading the environment, and it is a reconstruction, not a reading.
`kernel.md:169` states the same split; `kernel.md:186` grades `{smp}` as a stray
U-Boot template artefact. This report neither confirms nor contradicts that.

**[READ]** The console is `ttymxc1` at 115200, and `etc/inittab` has
`console::respawn:/sbin/getty -L  console 0 vt100 # GENERIC_SERIAL`. **[INFERRED]** the same UART
carries U-Boot's own console, and interrupting `bootdelay` on it is the only
route to `printenv` that requires no software change — see §8.

---

## 6. `mkimage` and `mkenvimage` date the U-Boot toolchain

**[READ]** Both print a version string, and both say the same thing:

```
usr/bin/mkimage    : "mkimage version %s"  /  "2016.01"
usr/bin/mkenvimage : "%s version %s"       /  "2016.01"
```

**[INFERRED]** The U-Boot source tree these host tools were built from is
**v2016.01**. This is the first hard date anyone has attached to the bootloader
side of this system. It is a bound on the *tools*, not proof that the U-Boot
running on the instrument is v2016.01.

It is, however, strongly corroborated. **[READ]** `dmesg-before-reboot.txt:5`:

```
Linux version 4.1.15-rt18 (root@terry) (gcc version 4.8.5 (Buildroot 2016.02-rc2-dirty) ) #1 SMP PREEMPT RT Mon May 16 10:55:36 EDT 2022
```

**[READ]** the whole system is built with **Buildroot 2016.02-rc2**, on a host
named `terry`, and (**[READ]**, file mtimes) the 1.5.0 root filesystem's binaries
carry `May 16 2022` — the same day. **[INFERRED]** Buildroot 2016.02's
`u-boot-tools` package tracks U-Boot 2016.01, which is exactly the version both
`mkimage` and `mkenvimage` report. So `fw_printenv`, `mkimage` and `mkenvimage`
are not stray third-party binaries: they are this Buildroot tree's own
`u-boot-tools` output, and the bootloader on the eMMC is overwhelmingly likely to
be U-Boot 2016.01 from the same tree. **[INFERRED]** — the running bootloader was
not read.

**[READ]** `mkimage` supports `imximage` ("Freescale i.MX Boot Image") among its
image types, so it is capable of producing a bootable `u-boot.imx`. It also
supports `script`, which is what produced `cmdline.img`. **[READ]** it contains
FIT machinery (`Verifying Hash Integrity`, `Bad Data Hash`, `Can't get hash algo
property…`).

**[READ]** `mkenvimage` usage, in full:

```
%s [-h] [-r] [-b] [-p <byte>] -s <environment partition size> -o <output> <input file>
This tool takes a key=value input file (same as would a `printenv' show) and
generates the corresponding environment image, ready to be flashed.
-r : the environment has multiple copies in flash
-b : the target is big endian (default is little endian)
-p <byte> : fill the image with <byte> bytes instead of 0xff bytes
```

**[INFERRED]** `mkenvimage -s <size> -o env.bin env.txt` followed by
`dd of=/dev/mmcblk2 seek=<offset>` is a complete environment-writing path that
needs no `fw_env.config` at all — and no report has noted that this capability is
sitting on the instrument. It is also the most direct way to brick it, since the
offset and size are both **[UNKNOWN]**.

---

## 7. The SPI side: `flashrom` and `/dev/spidev0.0`

`xmos.md` §2 and §7.3 already establish that `flashrom -l
/usr/share/xmosfw/las_layout -i firmware -w <fw> -p linux_spi:dev=/dev/spidev0.0`
is the VC firmware path. Two additions from this pass, both bearing on boot
media:

**[READ]** `flashrom` reports itself as `0.9.9-unknown` and its compiled-in
programmer list includes `internal`, `dummy`, `nicintel`, `nicintel_eeprom`,
`gfxnvidia`, `drkaiser`, `ft2232_spi`, `buspirate_spi`, `dediprog`, `ch341a_spi`,
`pony`, `ogp`, and — the relevant one — **`linux_spi`**, with the message
`No SPI device given. Use flashrom -p linux_spi:dev=/dev/spidevX.Y`.

**[READ]** `/usr/bin/config-las-spi` is a 57-line shell script that *arbitrates
the ECSPI1 bus between the i.MX6 and the XMOS* by writing IOMUXC registers with
`devmem`:

```sh
config_spi_xmos() {   # SPI1 pins -> GPIO inputs, XMOS drives the bus
  devmem 0x20e0244 32 5 ; devmem 0x20e0248 32 5
  devmem 0x20e0258 32 5 ; devmem 0x20e025c 32 5
  devmem 0x20a8004 32 0x40008020
  echo 0 > /sys/class/leds/XMOS_RESET_N/brightness
  echo 1 > /sys/class/leds/XMOS_RESET_N/brightness
}
config_spi_som() {    # XMOS held in reset, SOM drives the bus
  echo 0 > /sys/class/leds/XMOS_RESET_N/brightness
  devmem 0x20e0244 32 0 ; devmem 0x20e0248 32 0
  devmem 0x20e0258 32 0 ; devmem 0x20e025c 32 5
  devmem 0x20a8004 32 0x40008220
}
```

**[READ]** `etc/init.d/S25xmosfw` — despite its name, and despite its own comment
"Writes XMOS firmware to the system as needed" — does **nothing but**
`config-las-spi xmos` in v1.8.2. It flashes nothing.

**[INFERRED]** So at runtime the SPI bus belongs to the XMOS and `/dev/spidev0.0`
is idle; `flashrom -p linux_spi:dev=/dev/spidev0.0` would only reach the flash
after `config-las-spi som` puts the XMOS in reset. This is the instrument's
**second boot medium** (the XMOS boot flash) and the second write path in the
rootfs, and it is guarded only by a shell script that nothing calls at boot in
the flashing direction.

---

## 8. Where the U-Boot environment actually is: hypotheses and discriminators

Nothing in either root filesystem states it. **[READ]** — no `/etc/fw_env.config`,
no `uboot.env`, no `boot.scr`, no `u-boot*` or `*.imx` file anywhere
(`find` for all of those returns only `boot/uImage` and `boot/imx6dl-profili-som.dtb`).

The live candidates, with what would settle each:

| # | hypothesis | consistent with | discriminator |
|---|---|---|---|
| 1 | Raw sectors in the eMMC **user area**, below 1 MiB (`CONFIG_ENV_IS_IN_MMC`, `CONFIG_ENV_OFFSET` in the 0x60000–0xC0000 range typical of i.MX6 boards) | survives the 1–17 MiB wipe; below the first partition | `dd bs=1k skip=<n> count=8 /dev/mmcblk2 \| strings` looking for `bootcmd=`; or `sgdisk -p` to confirm the gap is big enough |
| 2 | Raw sectors in an eMMC **boot partition** (`mmcblk2boot0/1`, 4 MiB each) | i.MX6 BootROM can be fused to boot from boot0 | `mmc extcsd read /dev/mmcblk2` → `PARTITION_CONFIG`; then `strings` the boot partition |
| 3 | A file on the **vfat** partition (`CONFIG_ENV_IS_IN_FAT`) | U-Boot already reads FAT there for `bootme` | `ls -la /var/lib/sys/` — an `uboot.env` would be visible |
| 4 | **No stored environment at all**; U-Boot uses its compiled-in default every boot and `saveenv` is disabled | explains why nothing on the system ever calls `fw_setenv`, and why no config file exists | U-Boot console: `printenv` then `saveenv` behaviour, or `env info` |
| 5 | Raw sectors **inside 1–17 MiB** | — | would be destroyed by every update (§5.4); **[INFERRED]** effectively ruled out, unless U-Boot rewrites it on the next boot |

**[INFERRED]** Hypothesis 4 deserves more weight than it would normally get. The
evidence for it: no config file was ever shipped, in either release; nothing in
userland reads or writes the environment; the boot policy that *would* normally
live in environment variables (`bootme`, sentinels) was deliberately put in FAT
files instead; and `fw_printenv`'s presence is fully explained as BSP payload
(§1.1) rather than as a deployed tool.

**[UNKNOWN]** which of the five is true. No file on disk decides it.

---

## 9. Version drift, 1.5.0 → 1.8.2

**[READ]**

* Every tool in §1 is byte-identical between the two releases **except**
  `kobs-ng`, whose only difference is one embedded git hash (§3.2).
* `boot/cmdline.img`, `boot/cmdline.txt` and `boot/imx6dl-profili-som.dtb` are
  byte-identical: `6a6aa900d354c703cfdab914ba41640d`,
  `5e41869298cbac7c8efca08feb25d983`, `87f2b786154093a604071df4d044824e`.
* `boot/uImage` differs (1.5.0 `6847177b5eb5cb07a53647070111dd91` → 1.8.2
  `0187e5b8e206afe66b3c9d062c908d62`) yet is 5,060,456 bytes in **both**, and both
  carry the uImage name field `Linux-4.1.15-rt18`.
* `usr/bin/lasfwu` is byte-identical (`29c03fc8651de8b3774025bef9448709`),
  including the falcon-space defect.
* `boot/` contains the same eleven files in both.
* `/etc/fw_env.config` is absent from both.
* `etc/versionb` differs as described in §5.5; `etc/version` is `las-v1.5.0` →
  `las-v1.8.2`.

**[INFERRED]** The boot chain, the device tree, the kernel command line, the
updater and the entire flash toolchain are frozen. Only the kernel binary and the
userland application layer moved between 2022 and 2025.

---

## 10. Defects and hazards found in this pass

1. **[READ]** `lasfwu:795` calls `gnupg --list-keys &> /dev/null`.
   **[READ]** there is no `gnupg` binary in the tree (`find . -name gnupg` →
   nothing; only `usr/bin/gpg` exists). The redirection hides the failure.
   Impact: whatever that call was meant to initialise (the keyring directory,
   presumably, after `rm -rf /var/local/gnupg/*` at `:794`) does not
   happen. **[UNKNOWN]** whether this breaks anything in practice, since `gpg`
   creates its own keyring on first use.
2. **[READ]** `lasfwu:29-30` set `sigkey="/etc/mmsk"` and `decrpytkey="/etc/mmek"`;
   **[READ]** neither file exists in the shipped rootfs. The variables appear to
   be dead — the live path imports the key from `/etc/bob.bmp` via
   `str /etc/bob.bmp 4` at `:49`.
3. **[READ]** `etc/init.d/S99final` ends with `mount -f -o remount,ro /`, so the
   root filesystem is read-only for the rest of the session unless the developer
   key file is present. **Consequence for this gap [INFERRED]:** you cannot create
   `/etc/fw_env.config` on a running stock instrument without remounting rw. A
   config file under `/var` or `/tmp` passed with `fw_printenv -c` avoids that
   entirely and is the correct approach. (The read-only remount itself is already
   documented in `kernel.md:1673`, `network.md:454`, `init-boot.md:33`.)
4. **[READ]** `/sys/fsl_otp/` (§4.3) is a fuse-blowing surface reachable from any
   root shell, with no confirmation prompt of its own, unlike `flash_otp_lock`
   which at least asks `Are you sure?`.
5. **[READ]** `mmc hwreset enable|disable` and `mmc gp create` set one-time eMMC
   bits (`H/W Reset is already permanently …`, `setting OTP
   PARTITION_SETTING_COMPLETED!`). Also unguarded.

---

## 11. Conflicts with existing docs

Reported, not fixed, per instruction.

1. **The framing of this gap assignment itself.** It states that
   "`flash_otp_info`/`flash_otp_lock` are the tools that answer" whether the i.MX6
   HAB/secure-boot fuses are blown. They are not (§3.3): they are MTD OTP tools
   and this board has no MTD device. The tool that answers it is the built-in
   `fsl_otp` kernel driver (§4).
2. **`kernel.md:1071-1076`** treats `ocotp@021bc000` as the thermal driver's
   calibration source only. That is true but incomplete: `fsl_otp.ko` is in
   `modules.builtin` and binds to the same node, exposing the full fuse map. Not
   a contradiction — an omission.
3. **`kernel.md` §4.13** lists `ecspi@0200c000`, `@02010000`, `@02014000` as
   disabled, which is correct, but the surrounding text should not be read as
   saying ECSPI is off: `ecspi@02008000` is `status = "okay"` and is the XMOS
   flash bus (`kernel.md:815` does record this correctly; the two passages are
   easy to read as inconsistent).
4. **`init-boot.md:1130-1132`** says of the falcon-space wipe, "partition 1
   evidently starts beyond sector 60000 (~30 MB) … **[INFERRED]**". This pass did
   not confirm that and cannot: `sgdisk -p` was never run. The `> 60000` figure is
   the *author's expectation* encoded in a broken test, not a measurement. The
   `[INFERRED]` grade there is doing more work than the evidence supports; the
   partition offset remains `[UNKNOWN]` (which `init-boot.md` does also say two
   sentences later).
5. **`captures/harvest/04-tools.txt`** records `sh: fw_printenv: not found` under
   a heading `################ U-BOOT ENVIRONMENT ################`. Read
   literally this is wrong (§2.7) — it is a `PATH` artifact, and the same file
   shows the identical artifact for `devmem`. Any future report citing that line
   as evidence of absence would be repeating the error.
7. **`arch/hardware-external.md:450`** states of the eMMC: "Root is **p2, ext4**".
   That is a per-machine snapshot, not a general fact. **[READ]** this
   instrument's own boot log and `runtime-state.txt` both show
   `root=/dev/mmcblk2p3`, i.e. slot U2. Both are correct for their own machine;
   the sentence should not be read as fixed layout, because `root=` is chosen per
   boot from `/var/lib/sys/bootme` (§5.5).
8. **`docs/firmware/README.md` / `VALIDATION.md`** were not amended by this pass.
   If they index the reports or aggregate validation commands, the §12 block here
   needs folding in — in particular the `/sys/fsl_otp/` warning in §4.3, which is
   the most destructive command surface documented anywhere in this project.

6. **Capture hygiene.** `captures/firmware-1.8.2/rootfs-1.8.2/.omc/` exists
   inside the extracted root filesystem (**[READ]**,
   `.omc/state/sessions/…/last-tool-error-state.json`). It is tooling residue,
   not firmware. A `grep -rl` over the tree will match it. It should be removed or
   the tree re-extracted, and no report should cite anything under it.

---

## 12. Validation plan — READ-ONLY commands for a human to run

None of these were run. All are read-only. **Do not run anything not on this
list**, and in particular never `echo` into `/sys/fsl_otp/*` or run any
`flash_*`, `nand*`, `ubi*`, `kobs-ng`, `mmc <anything but read/get>`, or
`fw_setenv` command.

Ordered by value.

```sh
# --- 12.1  The fuses.  Pure reads.  These answer the HAB question.
ls -la /sys/fsl_otp/ 2>/dev/null || find /sys -maxdepth 3 -name 'HW_OCOTP_CFG5'
cat /sys/fsl_otp/HW_OCOTP_CFG5          # SEC_CONFIG: bit1 = HAB closed (see 4.2 caveat)
cat /sys/fsl_otp/HW_OCOTP_LOCK
cat /sys/fsl_otp/HW_OCOTP_SRK0 /sys/fsl_otp/HW_OCOTP_SRK1 /sys/fsl_otp/HW_OCOTP_SRK2 \
    /sys/fsl_otp/HW_OCOTP_SRK3 /sys/fsl_otp/HW_OCOTP_SRK4 /sys/fsl_otp/HW_OCOTP_SRK5 \
    /sys/fsl_otp/HW_OCOTP_SRK6 /sys/fsl_otp/HW_OCOTP_SRK7   # all-zero => no SRK burned
cat /sys/fsl_otp/HW_OCOTP_SRK_REVOKE
cat /sys/fsl_otp/HW_OCOTP_BOOT_CFG0 /sys/fsl_otp/HW_OCOTP_BOOT_CFG1 \
    /sys/fsl_otp/HW_OCOTP_BOOT_CFG2 /sys/fsl_otp/HW_OCOTP_BOOT_CFG3 \
    /sys/fsl_otp/HW_OCOTP_BOOT_CFG4
cat /sys/fsl_otp/HW_OCOTP_FIELD_RETURN
cat /sys/fsl_otp/HW_OCOTP_CFG0 /sys/fsl_otp/HW_OCOTP_CFG1     # chip UID

# --- 12.2  Confirm there really is no MTD device (settles all of §3)
cat /proc/mtd                    # expect: "No such file" or an empty table
ls -la /dev/mtd* 2>&1            # expect: no such file
lsmod                            # expect: at most the two .ko in lib/modules

# --- 12.3  The partition layout.  sgdisk -p and -i are read-only.
sgdisk -p /dev/mmcblk2
sgdisk -i=1 /dev/mmcblk2         # the number lasfwu:821 wanted
cat /proc/partitions
blkid 2>/dev/null

# --- 12.4  eMMC configuration.  'extcsd read' is a read.
/usr/bin/mmc extcsd read /dev/mmcblk2 | head -80
/usr/bin/mmc extcsd read /dev/mmcblk2 | grep -iE 'PARTITION_CONFIG|BOOT_CONFIG|BOOT_SIZE|BOOT_BUS|RST_N|PARTITION_SETTING|WR_REL|SEC_'
/usr/bin/mmc writeprotect boot get /dev/mmcblk2
/usr/bin/mmc status get /dev/mmcblk2
ls -la /sys/block/mmcblk2boot0/force_ro /sys/block/mmcblk2boot1/force_ro
cat /sys/block/mmcblk2boot0/force_ro /sys/block/mmcblk2boot1/force_ro

# --- 12.5  Hunt for the environment.  All reads.  Redirect to /tmp, which is tmpfs.
ls -la /var/lib/sys/                       # hypothesis 3: an uboot.env would show here
strings /var/lib/sys/* 2>/dev/null | head
# first 1 MiB of the user area (below the wipe window; hypothesis 1)
dd if=/dev/mmcblk2 bs=4096 count=256 2>/dev/null | strings -a | grep -nE 'bootcmd|bootargs|bootdelay|mmcargs|add_args|baudrate' | head -40
# the two eMMC boot partitions (hypothesis 2)
dd if=/dev/mmcblk2boot0 bs=4096 count=1024 2>/dev/null | strings -a | grep -nE 'bootcmd|U-Boot|add_args' | head -40
dd if=/dev/mmcblk2boot1 bs=4096 count=1024 2>/dev/null | strings -a | grep -nE 'bootcmd|U-Boot|add_args' | head -40
# and confirm where U-Boot itself lives
dd if=/dev/mmcblk2 bs=1k skip=1 count=8 2>/dev/null | xxd | head -4     # IVT at 1 KiB?
dd if=/dev/mmcblk2boot0 bs=1k skip=1 count=8 2>/dev/null | xxd | head -4

# --- 12.6  Once §12.5 finds a plausible offset, and ONLY then, a read-only fw_printenv.
#   Write the config to tmpfs, never to /etc.  fw_printenv opens the device O_RDONLY (§2.5).
#   Substitute the offset and size actually found.  If the output shows
#   "Warning: Bad CRC, using default environment", DISCARD IT - see §2.4.
# printf '/dev/mmcblk2 0x%x 0x2000\n' <OFFSET> > /tmp/fw_env.config
# /usr/sbin/fw_printenv -c /tmp/fw_env.config | head -60

# --- 12.7  The bootloader console.  Physical, and the only guaranteed reading.
#   Serial console is ttymxc1 @ 115200 (kernel cmdline, etc/inittab).
#   Interrupt bootdelay, then at the U-Boot prompt:
#     printenv
#     env info          (if built)
#     mmc info ; mmc part
#     bdinfo
#   These are all read-only U-Boot commands.  Do NOT type saveenv, setenv, mmc write,
#   mw, or anything under the 'fuse' command.

# --- 12.8  Version / build identity of the running bootloader, if the console is reachable
#     version           (prints the U-Boot version string - confirms or refutes 2016.01)
```

---

## 13. Unexplored

* **The instrument's actual GPT.** Everything about partition offsets in §5.2 and
  §5.4 is arithmetic on `df` output. `sgdisk -p` settles it and was not run.
* **`mmcblk2p5`.** Referenced nowhere in the rootfs. Purpose unknown.
* **Whether `/sys/fsl_otp/*` attributes are writable in this build.** The sysfs
  mode bits were not recovered from the kernel image; only the attribute-name
  table was.
* **`kobs-ng`'s version numbers.** The two git hashes were recovered; the `%d.%d`
  version they accompany is a runtime printf and cannot be read statically.
* **The 156 MB `pkg/rootfs` payload and the GPG trust chain** (`MOOGFW`,
  `IMAGE-SIG`, `MANIFEST-SIG`, `/etc/bob.bmp` as a key carrier). Touched only
  enough to establish that the package contains no bootloader. `diff-upgrade.md`
  and `small-binaries.md` cover the update flow; the signature chain itself is a
  separate gap.
* **`flashbench`** (23532 bytes). Present, unreferenced, not examined — it is an
  eMMC/SD timing profiler, harmless but it does write in some modes.
* **`/dev/spidev0.0`'s actual flash chip.** `flashrom --flash-name` would
  identify it; `xmos.md:891` already lists that as an open item.
* **The 1.5.0 boot log.** Only one `dmesg` exists in the captures, from the
  1.5.0-era instrument. No 1.8.2 boot log exists, so nothing in §3.1/§5.1 has
  been re-confirmed against 1.8.2 hardware behaviour.
* **A public U-Boot boot log may already exist and was not consulted.**
  **[READ]** `arch/hardware-external.md:447` says "U-Boot prints `Ram size 512`"
  and attributes the source family (`arch/hardware-external.md:19-22`) to Ryan
  Zachry's 2020-2021 teardown posts, which that report says include "root shell,
  and boot logs". If those logs captured U-Boot's banner and `bootcmd`, they would
  settle §8 and §6 without touching the instrument at all. This is a
  documentary lead, not an instrument operation, and it is the cheapest next step
  in this whole area.
* **`/proc/config.gz`.** Not checked for; if present it would settle
  `CONFIG_ENV_*` questions on the kernel side and the `fsl_otp` write question.
