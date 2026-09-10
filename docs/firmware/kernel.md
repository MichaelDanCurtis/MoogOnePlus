# Moog One — kernel, modules, device tree and hardware configuration

Region: `boot/`, `lib/modules/`, the device tree, ALSA card and ESAI/TDM path,
memory reservations, CPU isolation and RT settings, thermal, USB controller roles.

Primary source: `/Volumes/Main External/Development/MoogOnePlus/captures/firmware-1.8.2/rootfs-1.8.2`
(decrypted v1.8.2 root filesystem, first read on 2026-09-08).
Comparison source: `/Volumes/Main External/Development/MoogOnePlus/captures/rootfs-1.5.0`
(present and complete; not still extracting).
Corroboration: `/Volumes/Main External/Development/MoogOnePlus/captures/dmesg-before-reboot.txt`
(a full boot log from the owner's instrument, captured 2026-09-06) and
`/Volumes/Main External/Development/MoogOnePlus/captures/arch-harvest/runtime-state.txt`
(contaminated — see `arch-harvest/CAVEAT-runtime-state.md`; used here only for the
categories the caveat marks as still valid: kernel cmdline, ALSA card enumeration,
network interfaces, mounts, `lsmod`).

**No instrument was contacted.** Everything below came off local disk.

Every claim is graded:
* **[READ]** — read directly out of a file; the file and the offset/line/node is cited.
* **[INFERRED]** — reasoning from cited evidence; the reasoning is stated.
* **[UNKNOWN]** — not determined.

---

## 0. Method and reproducibility

There is no `dtc` on this machine, so the device tree was decompiled with a
purpose-written FDT parser (structure block walk, string block resolution,
`memreserve` list, phandle map). The kernel was extracted from the U-Boot image
and its symbol table recovered so that driver code could be read rather than guessed:

```
# 1. strip the 64-byte U-Boot header from boot/uImage  -> zImage
dd if=boot/uImage of=zImage bs=64 skip=1
# 2. the ARM zImage carries one gzip stream at file offset 0x4718 (18200)
#    inflate it -> vmlinux.bin, 10,214,816 bytes, loads at 0x80008000
# 3. kallsyms recovered from the raw image:
#      kallsyms_addresses  file 0x72be50  (60,931 entries, first = 0x80008000)
#      kallsyms_num_syms   file 0x767660  (= 0x0000ee03 = 60931)
#      kallsyms_names      file 0x767670  (16-byte aligned, not 4/8)
#      kallsyms_markers    file 0x818650  (239 entries, first = 0)
#      kallsyms_token_table file 0x818a10
#      kallsyms_token_index file 0x818d90
# 4. wrap vmlinux.bin in a minimal ELF32 ARM header at vaddr 0x80008000 and
#    disassemble with llvm-objdump --triple=armv7-none-linux-gnueabihf
```

Validation of that recovery **[READ]**: the decoded symbol `_text` = `0x80008000`
(the definitional load address, and the first word of the address table), and
`linux_banner` = `0x806bf064`, which is exactly `0x80008000 + 0x6b7064`, the file
offset at which the string `Linux version 4.1.15-rt18 …` actually sits. Two
independent anchors agree, so the address→symbol mapping used below is sound.

No Moog binary was executed. Only `strings`, `xxd`/`dd`, Python, and `llvm-objdump`
were used.

---

## 1. Version identity and provenance

### 1.1 The images

| file | size | md5 | note |
|---|---|---|---|
| `boot/uImage` | 5,060,456 | `0187e5b8e206afe66b3c9d062c908d62` | u-boot legacy uImage, `Linux-4.1.15-rt18`, load/entry `0x10008000`, uncompressed OS Kernel Image |
| `boot/imx6dl-profili-som.dtb` | 42,345 | `87f2b786154093a604071df4d044824e` | DTB v17, boot CPU 0, string block 2,921 B, struct block 39,368 B |
| `boot/cmdline.img` | 189 | `6a6aa900d354c703cfdab914ba41640d` | u-boot script, "Additional Kernel Args" |
| `boot/cmdline.txt` | 117 | `5e41869298cbac7c8efca08feb25d983` | source text for the above |

**[READ]** from `file(1)` and `md5(1)` on those paths.

### 1.2 Kernel build

**[READ]** `boot/uImage`, decompressed, offset `0x6b7064`:

```
Linux version 4.1.15-rt18 (root@terry) (gcc version 4.8.5 (Buildroot 2016.02-rc2-dirty) ) #1 SMP PREEMPT RT Mon Sep 15 14:38:28 EDT 2025
```

* kernel 4.1.15 with the `-rt18` PREEMPT_RT patch set **[READ]**
* built by `root` on a host named `terry` **[READ]**
* toolchain gcc 4.8.5 from Buildroot 2016.02-rc2-dirty **[READ]**; `/etc/os-release`
  in the rootfs says `NAME=Buildroot / VERSION=2016.02-rc2-dirty` **[READ]**
* build stamp 2025-09-15 14:38:28 EDT **[READ]**
* the userspace release marker is `/etc/version` = `las-v1.8.2` **[READ]**

`/etc/git-tags` **[READ]** gives the component tags shipped in 1.8.2:

```
LAS_FRONTEND 2.1.4   LAS_VX lasvx-v2.2.1   LAS_FW lasvc-v2.2.2   LAS_SC 1.1.0r2
LAS_FX v1.1.1r4      LAS_FWU v0.9.1        LAS_WATCHDOG v0.2.0   LAS_DWM v0.3.0
LAS_VX_DSP vxdsp-v1.0.0rc1                 LAS_BUILDROOT v1.8.2
```

### 1.3 The kernel did not change between 1.5.0 and 1.8.2

This is the single most load-bearing finding in this region.

**[READ]** md5 comparison of `rootfs-1.5.0` vs `rootfs-1.8.2`:

| artefact | result |
|---|---|
| `boot/cmdline.txt` | **identical** (`5e41869298cbac7c8efca08feb25d983`) |
| `boot/cmdline.img` | **identical** (`6a6aa900d354c703cfdab914ba41640d`) |
| `boot/imx6dl-profili-som.dtb` | **identical** (`87f2b786154093a604071df4d044824e`) |
| `lib/modules/4.1.15-rt18/modules.builtin` | **identical** (`62314b607c7b64b69942f866cfc41d80`) |
| `lib/modules/4.1.15-rt18/modules.dep` | **identical** |
| `boot/uImage` | differs |
| the two `.ko` files | differ |

**[READ]** Both `uImage` payloads decompress to exactly **10,214,816 bytes**, and a
byte-by-byte diff of the two decompressed kernels shows **138 differing bytes in
6 runs**, all of which are build-identity, not code:

| offset | 1.5.0 | 1.8.2 | what it is |
|---|---|---|---|
| `0x6b70d4` (15 B) | `Mon May 16 10:55:36 EDT 2022` | `Mon Sep 15 14:38:28 EDT 2025` | `linux_banner` date |
| `0x6b70eb` (1 B) | — | — | adjacent pointer shifted |
| `0x75fb84` (1 B) | `2d` | `2e` | one entry in a rodata offset table |
| `0x9181b0` (20 B) | `a1b5b6b1…` | `b64b4999…` | GNU build-id |
| `0x9654c7` (106 B) | — | — | the embedded initramfs cpio (see below) |
| `0x97b6c9` + `0x97b6e0` (16 B) | `#1 SMP PREEMPT RT Mon May 16 …` | `#1 SMP PREEMPT RT Mon Sep 15 …` | `UTS_VERSION` |

**[INFERRED]** The 1.8.2 kernel is a *rebuild of the same source with the same
config* as the 1.5.0 kernel. Nothing in the kernel, the device tree, or the kernel
command line changed between May 2022 and September 2025. Reasoning: identical
output size, identical `modules.builtin` (which is generated from the `.config`),
identical DTB and cmdline, and the only differing bytes are two timestamp strings,
the build-id, and a cpio whose sole variable field is an mtime.

**Consequence, and it matters for the whole project:** the boot log at
`captures/dmesg-before-reboot.txt` — captured from a 1.5.0-era instrument
(its banner reads `Mon May 16 10:55:36 EDT 2022`) — is valid evidence for the
1.8.2 kernel's behaviour, because the kernel, the DTB and the cmdline are the
same bits. Every dmesg citation below is used on that basis. **[INFERRED]**

### 1.4 The built-in initramfs is the empty default

**[READ]** The kernel contains one gzip stream at file offset `0x9654a8`
(vaddr `0x8096d648`) that inflates to a 512-byte `newc` cpio containing exactly:

```
dev/          (mode 041ED)
dev/console   (mode 021 80, i.e. character device)
root/         (mode 041C0)
TRAILER!!!
```

mtime `0x68C85D1F` = 2025-09-16 UTC. **[INFERRED]** This is the kernel's own default
`usr/initramfs_data.cpio.gz`, not a Moog initramfs. There is **no** initrd/initramfs
stage: the kernel mounts `root=/dev/mmcblk2p3` directly, which the boot log confirms
(`VFS: Mounted root (ext4 filesystem) readonly on device 179:3`). **[READ]**

---

## 2. Boot chain and kernel command line

### 2.1 `boot/cmdline.txt` / `boot/cmdline.img`

**[READ]** `boot/cmdline.txt`, whole file:

```
setenv add_args isolcpus=1 quiet loglevel=0  galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1
```

`boot/cmdline.img` is that same text wrapped in a U-Boot legacy image header of
type "Script File", name `Additional Kernel Args`, 125 payload bytes. **[READ]**
So the *base* bootargs live in the U-Boot environment; this file only appends.

### 2.2 The command line the kernel actually got

**[READ]** `dmesg-before-reboot.txt` line 22, and identically
`arch-harvest/runtime-state.txt` `--- cmdline ---` (a category the caveat file
explicitly certifies as uncontaminated):

```
console=ttymxc1,115200{smp} root=/dev/mmcblk2p3 rootwait isolcpus=1 quiet loglevel=0 galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1
```

Parameter by parameter:

| parameter | consumed by | grade |
|---|---|---|
| `console=ttymxc1,115200` | `console_setup` → UART2 (`21e8000.serial`, `ttymxc1`), `console [ttymxc1] enabled` | **[READ]** dmesg |
| `{smp}` | nothing — no `__setup` entry matches; it is a stray U-Boot template artefact | **[INFERRED]** from the `__setup` table dump (§2.3) |
| `root=/dev/mmcblk2p3` | `root_dev_setup` — eMMC partition 3 | **[READ]** |
| `rootwait` | `rootwait_setup` | **[READ]** |
| `isolcpus=1` | `isolated_cpu_setup` | **[READ]** — present in the `__setup` table |
| `quiet` | `quiet_kernel` | **[READ]** |
| `loglevel=0` | `loglevel` | **[READ]** |
| `galcore.contiguousSize=67108864` | the built-in Vivante `galcore` driver; the string `galcore.contiguousSize` is at vaddr `0x807240bc` | **[READ]** |
| `gpumem=128M` | **nothing in this kernel** — see below | **[READ]** absence |
| `dmfc=3` | `dmfc_setup` (`__setup_str_dmfc_setup` → `"dmfc="`) | **[READ]** |
| `nohz=off` | `setup_tick_nohz` | **[READ]** |
| `skew_tick=1` | `skew_tick` (early param) | **[READ]** |

**`gpumem=128M` is inert as far as Linux is concerned. [READ]** The literal byte
string `gpumem` does not occur anywhere in the 10.2 MB decompressed kernel image
(exhaustive byte search: zero hits), and there is no `gpumem` entry in the 114-entry
`__setup` table between `__setup_start` (`0x8096c730`) and `__setup_end`
(`0x8096cc88`). **[INFERRED]** Since it contains an `=`, the kernel will hand it to
`init` as an environment variable and otherwise ignore it. **[UNKNOWN]** whether
U-Boot itself consumes `gpumem` before handoff — U-Boot is not in this capture.
The 128 MiB figure *does* appear in the device tree as the GPU's
`contiguous_mem` region size (§4.11), so the two are probably meant to agree, but
only `galcore.contiguousSize=67108864` (64 MiB) reaches the driver at runtime.

### 2.3 The full `__setup` parameter table

**[READ]** 114 entries decoded from `__setup_start` … `__setup_end`
(`struct obs_kernel_param` = `{const char *str; int (*setup)(char*); int early;}`,
12 bytes on ARM). The Moog/Variscite-specific and RT-relevant ones:

| name | handler | early |
|---|---|---|
| `isolcpus=` | `isolated_cpu_setup` | 0 |
| `nohz=` | `setup_tick_nohz` | 0 |
| `nohz_full=` | `tick_nohz_full_setup` | 0 |
| `skew_tick` | `skew_tick` | 1 |
| `rcu_nocbs=` | `rcu_nocb_setup` | 0 |
| `rcu_nocb_poll` | `parse_rcu_nocb_poll` | 1 |
| `cma` | `early_cma` | 1 |
| `coherent_pool` | `early_coherent_pool` | 1 |
| `dmfc=` | `dmfc_setup` | 0 |
| `screen_alternate=` | `alternate_screen_type` | 0 |
| `uart_from_osc` | `setup_uart_clk` | 0 |
| `vdoa_iram_size=` | `vdoa_iram_size_setup` | 0 |
| `max17135:` | `max17135_setup` | 0 |

`dmfc=`, `screen_alternate=`, `uart_from_osc`, `vdoa_iram_size=` and `max17135:`
are NXP-BSP/vendor additions, not mainline. **[INFERRED]** from their absence
from mainline 4.1 and their presence here.

### 2.4 The rest of `boot/`

**[READ]** `boot/` also holds the splash assets, which are raw framebuffer dumps and
bitmaps, not kernel artefacts:

```
moog_logo.fb           16,713,216   moog_splash.fb          16,716,544
moog_splash.bmp         1,152,056   moog_splash.bmp.gz           8,202
moog_splash_ver.bmp     1,152,138   moog_splash_ver.bmp.gz       8,202
moog_splash_version.bmp 1,536,138
```

`/etc/init.d/S12splash` does `dd if=/boot/moog_splash.fb of=/dev/fb1` after
resizing fb1 to 832×480×32 **[READ]**.

---

## 3. Loadable modules — there are effectively none

### 3.1 What is on disk

**[READ]** `lib/modules/4.1.15-rt18/` contains exactly two `.ko` files:

```
kernel/drivers/rpmsg/imx_rpmsg_pingpong.ko   4,216 bytes
kernel/drivers/rpmsg/imx_rpmsg_tty.ko        6,864 bytes
```

`modules.dep`, `modules.order` list only those two; `modules.alias`,
`modules.softdep`, `modules.devname` contain only their header comments — i.e. no
aliases, no soft dependencies, no on-demand loading rules at all. **[READ]**

Module metadata **[READ]** (from `strings` on the `.ko`s):

```
imx_rpmsg_tty.ko:      license=GPL v2  author=Freescale Semiconductor, Inc.
                       description=iMX virtio remote processor messaging tty driver
                       depends=  vermagic=4.1.15-rt18 SMP preempt ARMv7 p2v8
imx_rpmsg_pingpong.ko: license=GPL v2  author=Freescale Semiconductor, Inc.
                       description=iMX virtio remote processor messaging pingpong driver
                       depends=  vermagic=4.1.15-rt18 SMP preempt ARMv7 p2v8
```

**[INFERRED]** Both are NXP demo drivers for the RPMsg link to a Cortex-M4
companion core. The i.MX6DL has no M4. They are dead weight carried by the
Buildroot defconfig. Nothing in `/etc` or `/usr` references them (no `modprobe`
of either anywhere in the rootfs).

### 3.2 What is actually loaded

**[READ]** `arch-harvest/runtime-state.txt`, section `--- modules ---`:

```
Module                  Size  Used by    Tainted: G
```

— header only, **zero modules loaded**. (`lsmod` is one of the categories the
caveat file certifies as uncontaminated.) The boot log agrees: the `spidev` WARN
backtrace prints `Modules linked in:` with nothing after it **[READ]**.

**[INFERRED]** The kernel is entirely monolithic in practice. Any plan that
depends on inserting a kernel module has to bring its own toolchain and match
`vermagic=4.1.15-rt18 SMP preempt ARMv7 p2v8`.

### 3.3 What is built in

`modules.builtin` lists **344** built-in objects **[READ]**. The whole list is on
disk; the parts that matter here:

**Audio (all built in):**
```
sound/soundcore, sound/core/{snd,snd-timer,snd-hrtimer,snd-pcm,snd-pcm-dmaengine,snd-compress}
sound/core/oss/{snd-mixer-oss,snd-pcm-oss}
sound/core/seq/{snd-seq,snd-seq-device,snd-seq-midi-event,snd-seq-dummy}, seq/oss/snd-seq-oss
sound/soc/snd-soc-core
sound/soc/codecs/snd-soc-moog-xmos.ko          <-- Moog-authored codec driver
sound/soc/fsl/{snd-soc-fsl-asrc,snd-soc-fsl-sai,snd-soc-fsl-ssi,snd-soc-fsl-spdif,
               snd-soc-fsl-esai,snd-soc-fsl-utils,snd-soc-imx-audmux,imx-pcm-dma}
sound/soc/fsl/snd-soc-imx-xmos-esai.ko         <-- Moog-authored machine driver
sound/soc/generic/snd-soc-simple-card
```

**There is no `sound/usb/` entry at all. [READ]** No `snd-usb-audio`, no
`snd-usbmidi-lib`. Confirmed independently against the recovered symbol table:
a case-insensitive search of all 60,931 kallsyms entries for `snd_usb`, `usbmidi`
or `usb_audio` returns **0 hits** **[READ]**.

**USB:**
```
usb/chipidea/{ci_hdrc,ci_hdrc_usb2,ci_hdrc_msm,ci_hdrc_zevio,ci_hdrc_pci,usbmisc_imx,ci_hdrc_imx}
usb/core/usbcore, usb/common/usb-common, usb/host/{ehci-hcd,ehci-pci,ehci-mxc}
usb/phy/{phy-generic,phy-mxs-usb}
usb/class/cdc-acm, usb/storage/usb-storage, usb/serial/usbserial
hid/{hid,uhid,hid-generic}, hid/usbhid/usbhid
net/usb/{asix,cdc_ether,cdc_eem,cdc_ncm,usbnet}
```

**There is no USB gadget/device stack. [READ]** No `libcomposite`, no `udc-core`,
no `g_*`, nothing under `usb/gadget/`. Symbol-table cross-check: a case-insensitive
search of all kallsyms for `gadget` returns 0 real hits (only `clk_composite_*`
matches on the substring "composite"), and there is no `ci_udc_*` symbol
**[READ]**.

**Other notable built-ins:** `cpufreq/{cpufreq_stats,cpufreq_performance,imx6q-cpufreq}`,
`thermal/{thermal_sys,imx_thermal,device_cooling}`, `watchdog/imx2_wdt`,
`mxc/gpu-viv/galcore`, `gpu/drm/vivante`, `mmc/host/sdhci-esdhc-imx`,
`net/ethernet/freescale/fec`, `rtc/{rtc-pcf85063,rtc-snvs,rtc-ds1307,rtc-mxc}`,
`spi/{spidev,spi-imx,spi-bitbang}`, `input/keyboard/{gpio_keys,snvs_pwrkey,imx_keypad}`,
`video/fbdev/mxc/*`, plus ext2/3/4, jffs2, ubifs, nfs, netfilter/iptables. **[READ]**

**Only the `performance` cpufreq governor is built in. [READ]** `modules.builtin`
lists `cpufreq_performance.ko` and no other governor object (`cpufreq_ondemand`,
`cpufreq_conservative`, `cpufreq_powersave`, `cpufreq_userspace` are all absent).
The literal strings `"performance"` and `"powersave"` do both appear near
`drivers/cpufreq/cpufreq.c` in the image, but that is `cpufreq_parse_governor`'s
own comparison text and is not evidence that a powersave governor object exists.
**[INFERRED]** The CPU therefore has one available governor.

---

## 4. Device tree

`boot/imx6dl-profili-som.dtb`, DTB v17 (last-compatible 16), boot CPU 0,
total size 42,345 bytes. **[READ]** There are **no** `/memreserve/` entries
**[READ]**.

Root properties **[READ]**:

```
model      = "Variscite i.MX6 DL/Solo SOM-SOLO SOM-DUAL SoloCustomBoard"
compatible = "fsl,imx6q-var-som", "fsl,imx6q"
#address-cells = <1>;  #size-cells = <1>
chosen { }            <-- empty; U-Boot fills bootargs at runtime
```

The board is a **Variscite VAR-SOM-MX6 (DualLite/Solo) on a custom carrier**.
**[INFERRED]** from `model`/`compatible` plus the `imx6qdl-var-som-mx6` pinctrl
node name; the "SoloCustomBoard" and the file name `imx6dl-profili-som.dtb`
(Profili being the carrier) point at a Moog-specific carrier on a stock SOM.

The boot log identifies the silicon **[READ]**:
`CPU identified as i.MX6DL, silicon rev 1.3`, `CPU: ARMv7 Processor [412fc09a]
revision 10`, `Hardware name: Freescale i.MX6 Quad/DualLite (Device Tree)`.

Node census **[READ]**: 25 nodes carry `status = "okay"`, 44 carry
`status = "disabled"`, 77 more are addressable nodes with no explicit status
(i.e. enabled by default).

### 4.1 CPUs and operating points

**[READ]** `/cpus`:

```
cpu@0 {
    compatible = "arm,cortex-a9"; device_type = "cpu"; reg = <0x0>;
    next-level-cache = <&L2>;
    operating-points     = <996000 1250000  792000 1175000  396000 1150000>;   (kHz, uV)
    fsl,soc-operating-points = <996000 1175000  792000 1175000  396000 1175000>;
    clock-latency = <61036>;   (ns)
    clocks = <&clks 0x68 &clks 0x06 &clks 0x10 &clks 0x11 &clks 0xaa &clks 0xe7 &clks 0xee &clks 0xe0>;
    clock-names = "arm","pll2_pfd2_396m","step","pll1_sw","pll1_sys","pll1","pll1_bypass","pll1_bypass_src";
    arm-supply = <&reg_arm>;  pu-supply = <&reg_pu>;  soc-supply = <&reg_soc>;
};
cpu@1 { compatible = "arm,cortex-a9"; device_type = "cpu"; reg = <0x1>;
        next-level-cache = <&L2>; };
```

So three OPPs: **996 MHz @ 1.250 V, 792 MHz @ 1.175 V, 396 MHz @ 1.150 V**, with
the SoC rail held at 1.175 V at every point. **[READ]** `cpu@1` carries no OPP
table, which is normal for i.MX6 (the driver reads them from `cpu@0` only)
**[INFERRED]**.

Two CPUs come up **[READ]** (`Brought up 2 CPUs`, `SMP: Total of 2 processors
activated (12.00 BogoMIPS)`), and RCU notes `restricting CPUs from NR_CPUS=4 to
nr_cpu_ids=2` **[READ]** — so the kernel is configured for up to 4 CPUs and finds 2.

L2: **[READ]** `arm,pl310-cache` at `0x00a02000`, and the log reports
`L2C-310 cache controller enabled, 16 ways, 512 kB`, `CACHE_ID 0x410000c8,
AUX_CTRL 0x76050001`, with erratum 769419 enabled, early BRESP, full-line-of-zeros,
ID prefetch (offset 16 lines) and dynamic clock gating all on.

### 4.2 Memory and the reservations

**[READ]** the DTB's static `/memory` node says `reg = <0x10000000 0x40000000>`
— base `0x10000000`, size 1 GiB. That is **not** what the machine has;
U-Boot rewrites it. **[READ]** the boot log:

```
Memory: 179944K/524288K available (7095K kernel code, 327K rwdata, 2216K rodata,
        332K init, 473K bss, 16664K reserved, 327680K cma-reserved, 0K highmem)
On node 0 totalpages: 131072
lowmem : 0x80000000 - 0xa0000000   ( 512 MB)
```

**512 MiB (524,288 KiB) of DRAM at 0x10000000, entirely lowmem, no highmem.**
**[READ]**

**[READ]** `/reserved-memory`:

```
reserved-memory {
    #address-cells = <1>; #size-cells = <1>; ranges;
    linux,cma {
        compatible = "shared-dma-pool";
        reusable;
        size = <0x14000000>;         /* 335,544,320 = 320 MiB */
        linux,cma-default;
    };
};
```

and the boot log confirms it is honoured **[READ]**:

```
Reserved memory: created CMA memory pool at 0x1c000000, size 320 MiB
Reserved memory: initialized node linux,cma, compatible id shared-dma-pool
```

**320 MiB of the 512 MiB is CMA.** After the kernel image and reservations, the
log reports only **179,944 KiB (~176 MiB) of ordinary available memory**, with the
320 MiB carried separately as `cma-reserved`. **[READ]**

`/proc/meminfo` from the live capture **[READ]** (`runtime-state.txt`, a category
the caveat certifies): `MemTotal: 507956 kB, MemFree: 11192 kB,
MemAvailable: 96684 kB, Buffers: 32692 kB, Cached: 72176 kB`. `MemTotal` includes
the CMA pages (CMA is `reusable`, so its pages are released to the buddy allocator
as `MIGRATE_CMA` and count in `totalram`) **[INFERRED]**.

**[INFERRED]** `size = <0x14000000>` is the stock NXP `imx6qdl.dtsi` default for
this BSP, not a Moog decision — but whoever ships it, the consequence on a 512 MiB
board is real: non-movable allocations compete for ~176 MiB, and `MemFree` was
11 MiB on the running instrument. This is a hard constraint on anything that wants
to add a resident process.

Other memory-ish reservations **[READ]**:
* `coherent_pool` — not on the cmdline; the log shows the default,
  `DMA: preallocated 256 KiB pool for atomic coherent allocations`.
* on-chip SRAM: `sram@00900000` (`fsl,lpm-sram`, 16 KiB), `sram@00904000`
  (`fsl,ddr-lpm-sram`, 4 KiB), `sram@00905000` (`mmio-sram`, `0x1b000` = 108 KiB).
  The 108 KiB OCRAM block is referenced as `iram = <&ocram>` by exactly four nodes
  **[READ]**: `vpu@02040000` (disabled), `vpu_fsl@02040000` (which also carries
  `iramsize = <0>`), `mlb@0218c000` (disabled) and `vdoa@021e4000`. `sdma@020ec000`
  does **not** reference it **[READ]**, and the boot log agrees: `imx-sdma
  20ec000.sdma: no iram assigned, using external mem` **[READ]**. **[INFERRED]**
  SDMA runs its script/context buffers out of DRAM rather than on-chip SRAM, which
  is a latency-relevant fact for the audio DMA path.

### 4.3 Clocks

**[READ]** `/clocks`:

| node | compatible | frequency |
|---|---|---|
| `ckil` | `fsl,imx-ckil`, `fixed-clock` | 32,768 Hz |
| `ckih1` | `fsl,imx-ckih1`, `fixed-clock` | 0 (unused) |
| `osc` | `fsl,imx-osc`, `fixed-clock` | 24,000,000 Hz |
| **`codec_osc`** | `fixed-clock` | **12,288,000 Hz** |

`codec_osc` (phandle `0x2d`) is referenced only by `xmos_codec@11`. **[READ]**
12,288,000 = 256 × 48,000 **[INFERRED]** — the audio master clock, and exactly the
figure the ESAI is programmed with at runtime (§6).

CCM is `ccm@020c4000` (`fsl,imx6q-ccm`), phandle `0x3`; the `<&clks N>` indices used
throughout the DTB are `imx6qdl-clock.h` constants. **[UNKNOWN]** — the numeric
index → symbolic name mapping was not verified from local material, so raw indices
are quoted below rather than guessed names.

### 4.4 USB — confirming the assigned question

**Question posed: "both `ci_hdrc` controllers are `dr_mode="host"`". CONFIRMED, and
more strongly than the question asks.**

**[READ]** All four USB controller nodes, verbatim from
`/soc/aips-bus@02100000/`:

| node | Linux name | `dr_mode` | `status` | phy | vbus |
|---|---|---|---|---|---|
| `usb@02184000` (OTG) | `ci_hdrc.0` | **`"host"`** | **`"okay"`** | `usbphy@020c9000` | `usb_otg_vbus` (GPIO6_IO03, active high, 5 V) |
| `usb@02184200` (HOST1) | `ci_hdrc.1` | **`"host"`** | **`"okay"`** | `usbphy@020ca000` | `usb_h1_vbus` (GPIO4_IO15, active high, 5 V) |
| `usb@02184400` (HSIC1) | — | `"host"` | `"disabled"` | `usbphy_nop1`, `phy_type="hsic"` | — |
| `usb@02184600` (HSIC2) | — | `"host"` | `"disabled"` | `usbphy_nop2`, `phy_type="hsic"` | — |

`usb@02184000` additionally carries `disable-over-current;`, and both enabled
controllers carry `ahb-burst-config = <0>`, `tx-burst-size-dword = <0x10>`,
`rx-burst-size-dword = <0x10>` **[READ]**.

Runtime confirmation **[READ]** from the boot log:

```
ci_hdrc ci_hdrc.0: EHCI Host Controller
ci_hdrc ci_hdrc.0: new USB bus registered, assigned bus number 1
ci_hdrc ci_hdrc.0: USB 2.0 started, EHCI 1.00
hub 1-0:1.0: USB hub found / 1 port detected
ci_hdrc ci_hdrc.1: EHCI Host Controller
ci_hdrc ci_hdrc.1: new USB bus registered, assigned bus number 2
ci_hdrc ci_hdrc.1: USB 2.0 started, EHCI 1.00
hub 2-0:1.0: USB hub found / 1 port detected
```

Both come up as **EHCI Host Controllers**, one root port each. **[READ]**

**The i.MX6 physically cannot be a USB device on this firmware. [READ]/[INFERRED]**
Beyond `dr_mode`, the kernel contains no gadget stack at all (§3.3): no
`usb/gadget/` objects in `modules.builtin`, and zero `gadget`/`udc` symbols in the
60,931-entry symbol table. Even if `dr_mode` were changed, there is nothing for the
controller to be a device *with*. This closes the question independently of the DT.

**What is on each bus [READ]** (boot log):

* Bus 1 (`ci_hdrc.0`, the OTG controller): `usb 1-1: new high-speed USB device
  number 2 using ci_hdrc` → `usb-storage 1-1:1.0: USB Mass Storage device
  detected` → `sd 0:0:0:0: [sda] 491520000 512-byte logical blocks: (251 GB/234 GiB)`,
  `sda: sda1`, mounted vfat. This is the front/rear USB-A thumb drive port.
* Bus 2 (`ci_hdrc.1`): at **t = 11.9 s**, long after boot:

```
usb 2-1: new high-speed USB device number 2 using ci_hdrc
cdc_ether 2-1:1.0 usb0: register 'cdc_ether' at usb-ci_hdrc.1-1, CDC Ethernet Device, 02:00:00:00:00:00
cdc_ether 2-1:1.2 eth0: register 'cdc_ether' at usb-ci_hdrc.1-1, CDC Ethernet Device, a4:11:63:b0:28:9b
cdc_ether 2-1:1.0 usbint: renamed from usb0
cdc_ether 2-1:1.2 ethext: renamed from eth0
```

**This is one USB device with two CDC-Ethernet functions. [READ]** `2-1:1.0` and
`2-1:1.2` are interfaces 0 and 2 of the *same* device `2-1`. So the established
claim "eth0/ethext is cdc_ether over that same link" is **CONFIRMED** — `usbint`
(MAC `02:00:00:00:00:00`, address `203.0.113.1`, peer `203.0.113.2`) and `ethext`
(MAC `a4:11:63:b0:28:9b`, DHCP) are two functions of the single XMOS USB device,
not two separate NICs.

The renaming is done by udev **[READ]** (`/etc/udev/rules.d/`):

```
20-xmos-nic.rules:   SUBSYSTEM=="net", ATTR{address}=="02:00:00:00:00:00" → usb-int.sh  → usbint
30-usb-nic.rules:    SUBSYSTEM=="net", ATTR{address}=="8c:ae:4c:*"        → usb-ext.sh  → usbext
50-eth-ext-nic.rules:SUBSYSTEM=="net", ATTR{address}=="a4:11:63:b*"       → eth-ext.sh  → ethext
```

`usb-int.sh` also installs a static ARP entry: `arp -i usbint -s 203.0.113.2
02:00:00:00:00:00` **[READ]**. `eth-ext.sh`/`usb-ext.sh` install four DNAT rules
each, forwarding UDP 7770, 7771, 9100 and 9300 to `203.0.113.2` **[READ]**.

**Why 11.9 s?** Because the XMOS is held in reset until userspace releases it —
see §4.10 and §8.3. **[INFERRED]**

**Consequence for MIDI [READ]/[INFERRED]:** the XMOS device's interfaces 0–3 are
consumed by the two CDC-Ether functions. No USB-audio/USB-MIDI class driver exists
in this kernel at all. Therefore no USB-MIDI interface the XMOS might expose can be
claimed by Linux, and no MIDI byte can reach Linux over this link. This is
consistent with, and independent evidence for, the established architecture claim.

**One real DT defect on the OTG port [READ]:**

```
imx6dl-pinctrl 20e0000.iomuxc: pin MX6DL_PAD_SD1_DAT3 already requested by 2080000.pwm; cannot claim for 2184000.usb
imx6dl-pinctrl 20e0000.iomuxc: pin-188 (2184000.usb) status -22
imx6dl-pinctrl 20e0000.iomuxc: could not request pin 188 (MX6DL_PAD_SD1_DAT3) from group usbotggrp-1 on device 20e0000.iomuxc
imx_usb 2184000.usb: Error applying setting, reverse things back
```

`usbotggrp-1` (one pin) wants `MX6DL_PAD_SD1_DAT3`, which `pwm@02080000`
(`pwm1grp`, also one pin, used for the LCD backlight) already owns. **[INFERRED]**
The contested pad is the OTG ID pin; because `dr_mode = "host"` is forced, ID
detection is irrelevant and the failure is cosmetic. It does mean anyone editing
this DT must resolve the conflict before OTG role switching could ever work.

### 4.5 Ethernet — confirming the assigned question

**Question posed: "the i.MX6's own FEC ethernet is `status="disabled"`". CONFIRMED.**

**[READ]** `/soc/aips-bus@02100000/ethernet@02188000`, verbatim:

```
ethernet@02188000 {
    compatible = "fsl,imx6q-fec";
    reg = <0x2188000 0x4000>;
    interrupts-extended = <&gpc 0 0x76 4 &gpc 0 0x77 4>;
    clocks = <&clks 0x75 &clks 0x75 &clks 0xbe>;
    clock-names = "ipg", "ahb", "ptp";
    stop-mode = <&gpr 0x34 0x1b>;
    fsl,wakeup_irq = <0>;
    status = "disabled";                 <-- confirmed
    pinctrl-names = "default";
    pinctrl-0 = <&enetgrp>;
    phy-mode = "rgmii";
    phy-reset-gpios = <&gpio1 25 0>;
    fsl,magic-packet;
};
```

Corroboration **[READ]**: the FEC driver *is* built in (`modules.builtin` lists
`drivers/net/ethernet/freescale/fec.ko`, plus `libphy`, `micrel`, `mii`,
`of_mdio`), yet the boot log contains no `fec` probe line and no `eth` interface
other than the two `cdc_ether` ones. The `/etc/network/interfaces` file still has a
stanza for `eth0` (static `192.168.1.1/24`, gateway `192.168.1.254`) **[READ]** —
vestigial, since the name `eth0` is taken by the XMOS's second CDC function and
immediately renamed to `ethext`.

The `enetgrp` pinctrl group (15 pins, RGMII) and `enetirqgrp` (1 pin) are still in
the DT and unused **[READ]**. Note `enetirqgrp` claims mux register `0x234`, which
is also claimed by `esaigrp`; harmless only because FEC is disabled **[INFERRED]**.

### 4.6 The audio path — ESAI

**[READ]** `/soc/aips-bus@02000000/spba-bus@02000000/esai@02024000`:

```
esai@02024000 {
    #sound-dai-cells = <0>;
    compatible = "fsl,imx35-esai";
    reg = <0x2024000 0x4000>;
    interrupts = <0 0x33 4>;                       /* SPI 51 */
    clocks = <&clks 0xe4 &clks 0xe5 &clks 0x76 &clks 0xe4 &clks 0x9c>;
    clock-names = "core", "mem", "extal", "fsys", "dma";
    dmas = <&sdma 0x17 0x15 0  &sdma 0x18 0x15 0>;
    dma-names = "rx", "tx";
    status = "okay";
    fsl,esai-synchronous;                          <-- Rx uses the Tx clock section
    pinctrl-names = "default";
    pinctrl-0 = <&esaigrp>;
    phandle = <0x3b>;
};
```

Note `clocks[0]` ("core") and `clocks[3]` ("fsys") are the **same** clock index
`0xe4` **[READ]**. SDMA request lines 0x17 (23) Rx and 0x18 (24) Tx, peripheral
type 0x15 (21) **[READ]**.

`fsl,esai-synchronous` is present, and the driver logs `setting synchronous mode`
at startup **[READ]** (boot log t=45.29).

**`esaigrp` — the 8 pins [READ]**, verbatim (`<mux_reg conf_reg input_reg
mux_mode input_val pad_ctl>` × 8):

```
0x234 0x604 0x840 0x0 0x1 0x1b030
0x224 0x5f4 0x830 0x0 0x1 0x1b030
0x23c 0x60c 0x858 0x0 0x1 0x1b030
0x218 0x5e8 0x844 0x0 0x0 0x1b030
0x210 0x5e0 0x83c 0x0 0x1 0x1b030
0x240 0x610 0x82c 0x0 0x1 0x1b030
0x22c 0x5fc 0x838 0x0 0x1 0x1b030
0x228 0x5f8 0x834 0x0 0x1 0x1b030
```

Observations that stand on the numbers alone **[READ]**: eight pads; every
`conf_reg` is `mux_reg + 0x3d0`; every pad uses `mux_mode = 0` (ALT0) and the same
pad control value `0x1b030`; seven of the eight daisy-chain select-input registers
are consecutive (`0x82c, 0x830, 0x834, 0x838, 0x83c, 0x840, 0x844`) with an eighth
outlier at `0x858`; exactly one pad uses `input_val = 0` while the other seven use
`1`. **[UNKNOWN]** which ESAI signal each pad carries — that decode needs the
i.MX6DL reference manual's IOMUXC tables, which are not in this capture. Do not
guess it; §11 lists it as unexplored.

### 4.7 The audio path — codec node and machine node

**[READ]** `/soc/aips-bus@02100000/i2c@021a0000/xmos_codec@11`:

```
xmos_codec@11 {
    compatible = "moog,las,xmos";
    clocks = <&codec_osc>;
    reg = <0x11>;                       /* I2C address 0x11 on i2c-0 */
    clock-names = "codec_osc";
    #sound-dai-cells = <0>;
    phandle = <0x3c>;
};
```

**[READ]** `/sound-xmos-esai` (a root-level node):

```
sound-xmos-esai {
    compatible = "fsl,imx-audio-xmos-esai";
    esai  = <&esai>;      /* phandle 0x3b */
    codec = <&xmos_codec>;/* phandle 0x3c */
};
```

and the two stock sound cards are switched off **[READ]**:
`/sound-hdmi { status = "disabled"; }`, `/sound { status = "disabled"; }`.

Everything else on the audio bus is off **[READ]**: `ssi@02028000`,
`ssi@0202c000`, `ssi@02030000`, `spdif@02004000` and `audmux@021d8000` all carry
`status = "disabled"`. `asrc@02034000` is `"okay"` with `fsl,asrc-rate = <48000>`,
`fsl,asrc-width = <16>` and probes (`fsl-asrc 2034000.asrc: driver registered`)
but is not wired into the running card (§6.3) **[READ]**.

### 4.8 Storage

**[READ]** SD/eMMC:

| node | alias | status | configuration | what it is |
|---|---|---|---|---|
| `usdhc@02190000` | mmc1 | disabled | — | — |
| `usdhc@02194000` | mmc0 | okay | `bus-width = <4>`, `cd-gpios = <&gpio4 14 0>`, `cd-inverted`, `no-1-8-v`, `keep-power-in-suspend`, `enable-sdio-wakeup` | SD card slot |
| `usdhc@02198000` | mmc2 | okay | `bus-width = <4>`, `non-removable`, `cap-power-off-card`, `vmmc-supply = <&wlan_en_reg>`, three pinctrl states (default / 100 MHz / 200 MHz) | **eMMC, the boot device** |
| `usdhc@0219c000` | mmc3 | disabled | — | — |

Boot log **[READ]**:
```
sdhci-esdhc-imx 2194000.usdhc: Got CD GPIO / No vmmc regulator found / No vqmmc regulator found
mmc0: SDHCI controller on 2194000.usdhc using ADMA
mmc2: SDHCI controller on 2198000.usdhc using ADMA
mmc2: MAN_BKOPS_EN bit is not set
mmc2: new DDR MMC card at address 0001
mmcblk2: mmc2:0001 NCard  7.21 GiB
mmcblk2boot0/boot1: 4.00 MiB each ; mmcblk2rpmb: 4.00 MiB
 mmcblk2: p1 p2 p3 p4 p5 p6 p7
```

**8 GB eMMC ("NCard", 7.21 GiB user area), DDR mode, 7 partitions.** **[READ]**
Quirk worth flagging **[READ]**: the eMMC's `vmmc-supply` points at the
`wlan-en-regulator` fixed regulator (1.8 V, 70 ms startup delay, GPIO7_IO08) — a
Variscite SOM artefact, since Wi-Fi is disabled on this board.

Partition use, from `/etc/fstab` **[READ]** and the live mount table **[READ]**:

```
/dev/mmcblk2p2  /mnt/u1        ext4  ro,noauto
/dev/mmcblk2p3  /              ext4  (root; also listed as /mnt/u2 ro,noauto)
/dev/mmcblk2p4  /var/lib/sys   vfat  defaults,noatime
/dev/mmcblk2p6  /var           ext4  defaults,noatime
/dev/mmcblk2p7  /mnt/fwu       ext4  defaults,noatime
```

p1 and p5 are not mounted by fstab **[READ]**; **[INFERRED]** p2/p3 are an A/B pair
(`/mnt/u1`, `/mnt/u2`) for firmware update, consistent with `/mnt/fwu` and the
`lasfwu` binary.

**NAND is vestigial [READ].** `gpmi-nand@00112000` is `status = "okay"` with a
seven-partition map (spl 2 MiB, bootloader 2 MiB, kernel 6 MiB, rootfs 1014 MiB,
plus three android_* partitions overlapping the same space), but the boot log says:

```
nand: No NAND device found
gpmi-nand 112000.gpmi-nand: driver registration failed: -19
```

There is no NAND on this board. **[READ]**

`weim@021b8000` probes (`imx-weim 21b8000.weim: Driver registered`) with nothing
attached **[READ]**. `pcie@0x01000000` is `"okay"` but fails **[READ]**:
`imx6q-pcie 1ffc000.pcie: phy link never came up / failed to initialize host /
probe of 1ffc000.pcie failed with error -22`.

### 4.9 I2C, SPI, UART, PWM

**I2C [READ]** — aliases give the bus numbering:

| node | alias | status | devices |
|---|---|---|---|
| `i2c@021a0000` | i2c0 | okay, 100 kHz | `pfc85063@51` (`nxp,pcf85063` RTC), **`xmos_codec@11`** (`moog,las,xmos`) |
| `i2c@021a4000` | i2c1 | disabled | — |
| `i2c@021a8000` | i2c2 | okay, 100 kHz | `ft5x06_ts@38` (`focaltech,5x06`), `rtc@0x68` (`dallas,ds1307`) |
| `i2c@021f8000` | i2c3 | disabled | — |

Boot log confirms exactly two adapters **[READ]**: `i2c i2c-0: IMX I2C adapter
registered` / `can't use DMA`, and the same for `i2c-2`. The ASoC codec device is
named `xmos-codec.0-0011` **[READ]** (bus 0, address 0x11), which matches.

RTC **[READ]**: `rtc-pcf85063 0-0051: chip found, driver version 0.0.1` →
registered as **rtc0**; `snvs_rtc 20cc000.snvs:snvs-rtc-lp` → **rtc1**;
`rtc-ds1307: probe of 2-0068 failed with error -5` (the DS1307 in the DT is not
populated). At boot the system clock is set from rtc0
(`setting system clock to 2026-09-07 14:30:46 UTC`).

Touchscreen **[READ]**: `ft5x06_ts@38` on i2c-2 with `focaltech,display-coords =
<0 0 800 480>`, 2 max touches, IRQ on GPIO5_IO17, `mirror_h`, `mirror_v`,
`vdd-supply`/`vcc_i2c-supply` = `touch_3v3_regulator`. The FocalTech driver is in
the kernel (11 kallsyms symbols matching `focaltech`) **[READ]**, but the boot log
contains **no** FocalTech probe line and registers only one input device
(`input: gpio-keys as /devices/soc0/gpio-keys/input/input0`) **[READ]**.
**[INFERRED]** The touch controller is not present on this hardware; the node is a
Variscite carry-over.

**SPI [READ]**:

| node | alias | status |
|---|---|---|
| `ecspi@02008000` | spi0 (ECSPI1) | **okay** — `fsl,spi-num-chipselects = <1>`, `cs-gpios = <&gpio4 9 0>`, `pinctrl-0 = <&ecspi1grp_2>` (3 pins), DMA rx/tx via SDMA, child `spidev@0` (`compatible = "spidev"`, `spi-max-frequency = <12000000>`) |
| `ecspi@0200c000` / `@02010000` / `@02014000` | spi1/2/3 | disabled |

Boot log **[READ]**:
```
spidev spi0.0: buggy DT: spidev listed directly in DT
WARNING: CPU: 0 PID: 1 at drivers/spi/spidev.c:731 spidev_probe+0x1e0/0x1fc()
… spi_imx 2008000.ecspi: probed
```
The warning is cosmetic (upstream disapproves of `compatible = "spidev"` in DT) and
the device does bind. **[INFERRED]**

**UART [READ]**:

| node | alias | Linux | status |
|---|---|---|---|
| `serial@02020000` | serial0 | `ttymxc0`, irq 25, base_baud 5,000,000 | okay |
| `serial@021e8000` | serial1 | `ttymxc1`, irq 295 — **the console** | okay |
| `serial@021ec000` | serial2 | `ttymxc2`, irq 296 | okay |
| `serial@021f0000` / `@021f4000` | serial3/4 | — | disabled |

`/etc/inittab` puts a getty on `console` (`console::respawn:/sbin/getty -L console
0 vt100`) **[READ]**, and `console=ttymxc1,115200` makes that the serial console
**[READ]**.

**PWM [READ]**: only `pwm@02080000` (PWM1) is `"okay"` (`pwm1grp`, 1 pin); PWM2/3/4
are disabled. It drives `/backlight` (`compatible = "pwm-backlight"`,
`pwms = <&pwm1 0 20000>` → 20,000 ns = 50 kHz, a 100-entry brightness-levels table
from 0 to 0xff, `default-brightness-level = <0>`).

### 4.10 GPIO, keys, LEDs — and the XMOS reset line

GPIO banks and their phandles **[READ]** (i.MX6 base addresses):

```
0x25 -> gpio@0209c000 (GPIO1)   0x?? -> gpio@020a0000 (GPIO2)
0x07 -> gpio@020a4000 (GPIO3)   0x0a -> gpio@020a8000 (GPIO4)
0x06 -> gpio@020ac000 (GPIO5)   0x36 -> gpio@020b0000 (GPIO6)
0x37 -> gpio@020b4000 (GPIO7)
```

**[READ]** `/misc_output` — a `gpio-leds` node, all three on GPIO6:

```
misc_output {
    compatible = "gpio-leds";
    lcdon0     { label = "LCD0 ON/OFF"; gpios = <&gpio6 2 0>; default-state = "on";  };
    lcdon1     { label = "LCD1 ON/OFF"; gpios = <&gpio6 4 0>; default-state = "on";  };
    xmosreset  { label = "XMOS_RESET_N"; gpios = <&gpio6 5 0>; default-state = "off"; };
};
```

**The XMOS reset line is GPIO6_IO05, exposed to userspace as an LED class device
named `XMOS_RESET_N`, and its power-on default is `off`. [READ]**

This is corroborated by `/usr/bin/config-las-spi` **[READ]**, which is the only
thing that touches it:

```sh
config_spi_xmos() {            # give the SPI bus to the XMOS
  devmem 0x20e0244 32 5        # KEY_COL0 -> ALT5 (GPIO)
  devmem 0x20e0248 32 5        # KEY_COL1 -> ALT5
  devmem 0x20e0258 32 5        # KEY_ROW0 -> ALT5
  devmem 0x20e025c 32 5        # KEY_ROW1 -> ALT5
  devmem 0x20a8004 32 0x40008020   # GPIO4_GDIR
  echo 0 > /sys/class/leds/XMOS_RESET_N/brightness   # assert reset
  echo 1 > /sys/class/leds/XMOS_RESET_N/brightness   # release
}
config_spi_som() {             # take the SPI bus back
  echo 0 > /sys/class/leds/XMOS_RESET_N/brightness   # hold XMOS in reset
  devmem 0x20e0244 32 0        # KEY_COL0 -> ALT0 (ECSPI1)
  devmem 0x20e0248 32 0        # KEY_COL1 -> ALT0
  devmem 0x20e0258 32 0        # KEY_ROW0 -> ALT0
  devmem 0x20e025c 32 5        # KEY_ROW1 stays GPIO (it is the chip select)
  devmem 0x20a8004 32 0x40008220   # GPIO4_GDIR, bit 9 now an output
}
```

**[INFERRED]** ECSPI1 is a *shared* bus: the i.MX6 only drives it while the XMOS is
held in reset. Two READ sources cross-check the chip select: the DT says
`cs-gpios = <&gpio4 9>`, and the only bit that differs between the two `GPIO4_GDIR`
writes (`0x40008020` vs `0x40008220`) is **bit 9** — set to output when the SOM owns
the bus, input when the XMOS does. `devmem` is the busybox applet at `/sbin/devmem`
**[READ]**.

**[INFERRED]** Because `default-state = "off"` drives GPIO6_IO05 low at boot and
`RESET_N` is active-low, the XMOS is held in reset from kernel init until
`/etc/init.d/S25xmosfw` runs `config-las-spi xmos`. That explains the 11.9 s gap
before the XMOS USB device enumerates (§4.4).

**[READ]** `/gpio-keys`:

```
gpio-keys {
    compatible = "gpio-keys";
    pinctrl-names = "default"; pinctrl-0 = <&gpio_keysgrp>;
    back { label = "Back"; gpios = <&gpio5 20 0>; linux,code = <0>; gpio-key,wakeup; };
};
```

One key on GPIO5_IO20 labelled "Back", wakeup-capable, `linux,code = 0`. The
associated pinctrl group is malformed **[READ]** — `gpio_keysgrp { fsl,pins; }` has
an empty value, and the kernel says so:

```
imx6dl-pinctrl 20e0000.iomuxc: Invalid fsl,pins property in node /soc/…/imx6qdl-var-som-mx6/gpio_keysgrp
```

The key still works (`input: gpio-keys`, and an `[irq/189-Back]` thread in `ps`)
**[READ]**. `/usr/bin/detect-held-buttons` is launched from `S43gui` to sample it
after startup **[READ]**.

Other GPIO assignments **[READ]**: `usb_otg_vbus` = GPIO6_IO03 (active high, 5 V
fixed regulator); `usb_h1_vbus` = GPIO4_IO15 (active high, 5 V); SD card detect =
GPIO4_IO14 (inverted); PCIe reset = GPIO5_IO13, PCIe wake = GPIO3_IO22;
`wlan-en-regulator` = GPIO7_IO08; FEC PHY reset = GPIO1_IO25 (unused).
Three pads are hogged by `hoggrp` at ALT5 **[READ]**:
mux offsets `0x1b8`, `0x254`, `0x268`.

### 4.11 Display, GPU, video

**[READ]** `/soc/ipu@02400000` (`fsl,imx6q-ipu`, 4 MiB register window,
interrupts 6 and 5, seven clocks named `bus,di0,di1,di0_sel,di1_sel,ldb_di0,ldb_di1`,
`resets = <&src 2>`, `bypass_reset = <0>`). i.MX6DL has one IPU.

Frame buffers **[READ]**:

| node | `disp_dev` | status | notes |
|---|---|---|---|
| `fb@0` | `ldb` | disabled | LVDS |
| `fb@1` | ? | disabled | |
| `fb@2` | **`lcd`** | **okay** | `interface_pix_fmt = "RGB24"`, `mode_str = "CLAA-WVGA"`, `default_bpp = <24>` |
| `fb@3` | ? | disabled | |

`/lcd@0` (`fsl,lcd`) is `"okay"` with `default_ifmt = "RGB24"` and
`pinctrl-0 = <&ipu1grp>` **[READ]**. `ipu1grp` has **29 pins** **[READ]** —
consistent with 24 data lines plus clock, HSYNC, VSYNC, DE and one more
**[INFERRED]**. There is a second `ipu1grp-2` (12 pins) that nothing references
**[READ]**.

`ldb@020e0008` (LVDS bridge) and both `lvds-channel@N` are disabled; the whole
HDMI stack (`hdmi_core`, `hdmi_video`, `hdmi_audio`, `hdmi_cec`) is disabled;
`mipi@021e0000` (DSI) and `mipi_csi@021dc000` are disabled **[READ]**.
`dcic@020e4000`, `dcic@020e8000` and `pxp@020f0000` are `"okay"` **[READ]**.
`v4l2_cap_0` and `v4l2_out` are `"okay"` **[READ]**.

Boot log **[READ]**:
```
mxc_sdc_fb fb@2: registered mxc display driver lcd
Console: switching to colour frame buffer device 104x30
```

**A Moog-specific IPU patch [READ].** The boot log prints:

```
imx-ipuv3 2400000.ipu: IPU DMFC CUSTOM MOOG HIGH RESOLUTION: 5B(0~3), 5F(4~7)
```

and the kernel image contains four mutually exclusive DMFC allocation strings at
consecutive rodata addresses **[READ]**:

```
IPU DMFC DC HIGH RESOLUTION: 1(0~3), 5B(4,5), 5F(6,7)
IPU DMFC DP HIGH RESOLUTION: 1(0,1), 5B(2~5), 5F(6,7)
IPU DMFC CUSTOM MOOG HIGH RESOLUTION: 5B(0~3), 5F(4~7)
IPU DMFC NORMAL mode: 1(0~1), 5B(4,5), 5F(6,7)
```

The `dmfc=3` cmdline parameter selects the third. **[INFERRED]** This is a
Moog-authored modification to the NXP `ipu-dmfc.c` display-FIFO allocator —
one of only three Moog patches found anywhere in the kernel (the others being
the ESAI slave-mode change, §6.2, and the two `snd-soc-*xmos*` drivers).
`S43gui`'s comment "set fb1 back to smaller size to avoid ipu overruns" **[READ]**
and the single late log line `imx-ipuv3 2400000.ipu: IPU Warning -
IPU_INT_STAT_10 = 0x00080000` at t=12,844 s **[READ]** show the display FIFO is
tight on this part.

Related: `/etc/init.d/S99final` raises the IPU AXI QoS with
`devmem 0x020e0018 w 0xffffffff` **[READ]**. `0x020E0018` is `IOMUXC_GPR6`
**[INFERRED]** (IOMUXC base `0x020E0000`, GPR6 at offset 0x18 — cross-checked
against the DTB, which declares `iomuxc-gpr@020e0000` with `reg = <0x20e0000 0x38>`,
i.e. GPR0..GPR13). Writing all-ones sets every IPU1 read/write QoS field to its
maximum.

GPU **[READ]** `/soc/gpu@00130000`:

```
compatible = "fsl,imx6dl-gpu", "fsl,imx6q-gpu";
reg = <0x130000 0x4000   0x134000 0x4000   0x0 0x0   0x0 0x8000000>;
reg-names = "iobase_3d", "iobase_2d", "phys_baseaddr", "contiguous_mem";
interrupt-names = "irq_3d", "irq_2d";
power-domains = <&gpc 1>;
```

`contiguous_mem` is declared as **128 MiB** (`0x8000000`) with base 0 **[READ]** —
the same figure as the inert `gpumem=128M`. At runtime `galcore.contiguousSize=67108864`
(64 MiB) is what the driver is told **[READ]**. Boot log **[READ]**:
`galcore: clk_get vg clock failed, disable vg!`, `Galcore version 5.0.11.41671`,
`[drm] Initialized vivante 1.0.0 20120216 on minor 0`.
**[UNKNOWN]** which of the two wins in `gpu-viv`; that would need the galcore
source or a live `dmesg | grep contiguous`.

VPU **[READ]**: `vpu@02040000` (`fsl,imx6dl-vpu`, `cnm,coda960`) is **disabled**,
but `vpu_fsl@02040000` (`fsl,imx6-vpu`, the NXP out-of-tree driver, same register
window) has no status and probes: `mxc_vpu 2040000.vpu_fsl: VPU initialized`.
`vdoa@021e4000` probes too. `mlb@0218c000` and `epdc@020f4000` are disabled/unused.

### 4.12 Power, regulators, watchdog, security blocks

**Anatop regulators [READ]** (`anatop@020c8000`, `fsl,imx6q-anatop`, `syscon`):

| name | range | flags |
|---|---|---|
| `vdd1p1` | 800,000 – 1,375,000 µV | always-on |
| `vdd3p0` | 2,625,000 – 3,400,000 µV | |
| `vdd2p5` | 2,000,000 – 2,750,000 µV | always-on |
| `vddarm` | 725,000 – 1,450,000 µV | always-on, allow-bypass |
| `vddpu` | 725,000 – 1,450,000 µV | enable-ramp-delay 150 µs, allow-bypass |
| `vddsoc` | 725,000 – 1,450,000 µV | always-on, allow-bypass |

**Fixed regulators [READ]**: `usb_otg_vbus` 5 V (GPIO6_IO03), `usb_h1_vbus` 5 V
(GPIO4_IO15), `3P3V` 3.3 V always-on, `touch_3v3_supply` always-on,
`wlan-en-regulator` 1.8 V (GPIO7_IO08, 70 ms startup).

**GPC [READ]** `/soc/aips-bus@02000000/gpc@020dc000`: `fsl,ldo-bypass = <0>` (the
internal LDOs are **not** bypassed — the SoC runs off its own LDOs, which matters
for thermal), `fsl,wdog-reset = <1>`, `pu-supply = <&reg_pu>`, and it is the
interrupt parent for the whole `soc` node.

**Bus frequency scaling [READ]**: `/soc/busfreq` (`fsl,imx_busfreq`) with two
interrupts named `irq_busfreq_0`, `irq_busfreq_1`. Boot log: `Bus freq driver
module loaded`. **[UNKNOWN]** whether it is actually enabled at runtime — that
needs `/sys/bus/platform/drivers/imx_busfreq/…/enable` on the instrument.

**Watchdog [READ]**:

```
wdog@020bc000 (WDOG1) status = "disabled"
wdog@020c0000 (WDOG2) status = "okay"
```

Boot log: `imx2-wdt 20c0000.wdog: timeout 60 sec (nowayout=0)` **[READ]**.
So a 60-second hardware watchdog is registered.

**Nothing in the rootfs opens it. [READ]** A binary-safe search (`strings` over
every file in `/bin`, `/sbin`, `/usr/bin`, `/usr/sbin`, plus a `grep -ra` of the
whole tree) finds **zero** references to `/dev/watchdog` anywhere in the 1.8.2
rootfs. The `las-watchdog` binary is *not* a hardware-watchdog daemon: its strings
are `pidof las-frontend`, `pidof las-sc`, `pidof sclang`, `pidof scsynth`,
`ping -c1 -W1 203.0.113.2`, `LAS-WATCHDOG : !!!VC IS DOWN!!!`, `VC REPORTING %d
VOICES` — it is a process/liveness monitor **[READ]**. **[UNKNOWN]** whether
WDOG2 is actually counting: `imx2_wdt` only starts the counter on first open of
`/dev/watchdog`, *unless* the bootloader already enabled it, in which case the
driver keeps it alive itself. U-Boot is not in this capture. This is in the
validation plan.

**Security/OTP [READ]**: `caam@2100000` (`fsl,sec-v4.0`) with two job rings,
`caam-sm@00100000`, `caam_secvio`, `caam-snvs@020cc000`; `ocotp@021bc000`
(`fsl,imx6q-ocotp`, `syscon`) — used by the thermal driver for calibration;
`snvs@020cc000` (`fsl,sec-v4.0-mon`, `syscon`, `simple-mfd`) with `snvs-rtc-lp`
(rtc1) and a `snvs-poweroff` child that is **disabled**.

### 4.13 Everything switched off

For completeness, the 44 `status = "disabled"` nodes **[READ]**:
`fb@0`, `fb@1`, `fb@3`, `flexcan@02090000`, `flexcan@02094000`, `kpp@020b8000`,
`ldb@020e0008` + both `lvds-channel@N`, `pwm@02084000`, `pwm@02088000`,
`pwm@0208c000`, `snvs-poweroff`, `ecspi@0200c000`, `ecspi@02010000`,
`ecspi@02014000`, `spdif@02004000`, `ssi@02028000`, `ssi@0202c000`, `ssi@02030000`,
`vpu@02040000`, `wdog@020bc000`, `audmux@021d8000`, **`ethernet@02188000` (FEC)**,
`i2c@021a4000`, `i2c@021f8000`, `mipi@021e0000`, `mipi_csi@021dc000`,
`mlb@0218c000`, `serial@021f0000`, `serial@021f4000`, `usb@02184400`,
`usb@02184600`, `usdhc@02190000`, `usdhc@0219c000`, `hdmi_audio`, `hdmi_cec`,
`hdmi_core`, `hdmi_video`, `sound`, `sound-hdmi`, `wlan`, `wlan_bt_rfkill`,
`wlcore`.

---

## 5. Thermal management

**[READ]** `/soc/aips-bus@02000000/tempmon` — note it has **no** `status`, so it is
enabled:

```
tempmon {
    compatible = "fsl,imx6q-tempmon";
    interrupts = <0 0x31 4>;              /* SPI 49 */
    fsl,tempmon = <&anatop>;
    fsl,tempmon-data = <&ocotp>;
    clocks = <&clks 0xac>;
};
```

There is **no** `thermal-zones` node in the DTB **[READ]** — the zone is created by
the driver, not described in DT.

The `imx_thermal` driver is built in (`modules.builtin`) and it **does** probe: the
live process list shows the kernel threads `[irq/272-imx_the]` and
`[irq/272-s-imx_t]` **[READ]** (`arch-harvest/runtime-state.txt`, uncontaminated
category). It prints nothing at probe, which is why the boot log has no thermal
line: this BSP's `imx_thermal.c` has no "temperature grade" message — the string
does not exist in the image **[READ]** (exhaustive search for `grade`,
`Commercial`, `Industrial`, `Automotive` finds only ext3/ext4/AER text).

**Trip points, read out of the driver's code [READ].** `imx_thermal_probe` is at
`0x804cb6a4` (from the recovered symbol table). At `0x804cb858`:

```
804cb858: movw r2, #0x4c08     ; }
804cb85c: movw r3, #0x9a28     ; }
804cb860: movt r2, #0x1        ; r2 = 0x00014C08 =  85000
804cb864: movt r3, #0x1        ; r3 = 0x00019A28 = 105000
```

**Passive trip 85,000 m°C (85 °C); critical trip 105,000 m°C (105 °C).**
**[INFERRED]** that these are the passive/critical trip temperatures rather than
some other pair: they are the two temperature-shaped constants in the probe path,
they match the NXP BSP's `IMX_TEMP_PASSIVE` / critical convention, and the
surrounding code registers a thermal zone and a cpufreq cooling device.

Cooling **[READ]**: the driver's strings include `failed to register cpufreq
cooling device: %d`, `thermal-cpufreq-%d`, `thermal-devfreq-%d`,
`imx_thermal_zone`; `device_cooling` and `thermal_sys` are built in, and
`devfreq_cooling_register` is an exported symbol. **[INFERRED]** On crossing the
passive trip the kernel throttles via cpufreq (clamping `policy->max`), which works
regardless of governor, and can also throttle bus frequency via `device_cooling`.

Calibration comes from OCOTP **[READ]** (`fsl,tempmon-data = <&ocotp>`, and the
driver strings `invalid sensor calibration data`, `failed to read sensor data: %d`,
`failed to get sensor data`).

**[UNKNOWN]** the actual polling period, the hysteresis, and whether a
`thermal-devfreq` cooling device is bound. Those need `/sys/class/thermal` on the
instrument.

---

## 6. The ALSA card and the ESAI/TDM audio path

This is the most consequential part of the region, so it is documented from three
independent angles: the device tree, the driver machine code, and the boot log.

### 6.1 One card, one PCM

**[READ]** boot log:

```
imx-xmos-esai sound-xmos-esai: Assigned faux codec/esai link
imx-xmos-esai sound-xmos-esai: Got clock from codec
imx-xmos-esai sound-xmos-esai: xmos-codec <-> 2024000.esai mapping ok
ALSA device list:
  #0: xmos-audio
```

**[READ]** live `/proc/asound` (uncontaminated category):

```
 0 [xmosaudio      ]: xmos-audio - xmos-audio
                      xmos-audio
00-00: HiFi xmos-codec-0 :  : playback 1 : capture 1
```

**Exactly one sound card (`xmos-audio`), one PCM device (`HiFi`), one playback
substream and one capture substream.** **[READ]**

### 6.2 What the machine driver does, read out of its code

`imx_xmos_esai_probe` is at `0x805a5ddc`. Disassembled **[READ]**:

1. `of_parse_phandle(dev->of_node, "esai", 0)` and `of_parse_phandle(dev->of_node,
   "codec", 0)`; error paths print `phandle missing or invalid` and
   `failed to find ESAI platform device`.
2. `of_find_device_by_node(esai_np)`, then `dev_name()` of the resulting platform
   device is stored as `dai_link[0].cpu_dai_name` — this is how the string
   `2024000.esai` gets there.
3. `codec_np` → `dai_link[0].codec_of_node`; `esai_np` → `dai_link[0].platform_of_node`.
4. `card_priv.sysclk = 12288000` (`mov r3,#32768; movt r3,#0xbb` → `0x00BB8000`),
   `card_priv[0x10] = 1`, `card_priv.pdev = pdev`.
5. `card->dev = &pdev->dev`; **`card->num_links = 1`**.
6. `snd_soc_register_card(&snd_soc_card_imx_xmos_esai)`; failure prints
   `snd_soc_register_card failed (%d)`.

Static data **[READ]** (`snd_soc_card_imx_xmos_esai` at `0x809bca08`,
`imx_xmos_esai_dai` at `0x809bcb50`):

```
card.name       = "xmos-audio"
card.dai_link   = &imx_xmos_esai_dai[0]
card.num_links  = 2          <-- static initialiser
dai_link[0].name        = "HiFi"
dai_link[0].stream_name = "HiFi"
dai_link[0].cpu_dai_name   = "2024000.esai"   (filled in at probe)
dai_link[0].codec_dai_name = "xmos-codec"
```

**`num_links` is 2 in the static initialiser and is overwritten with 1 at probe.**
**[READ]** (probe stores `r8 = 1` to `card + 0x70`). **[INFERRED]** The second
link — the strings `HiFi-ASRC-FE` / `HiFi-ASRC-BE` and the symbol
`be_hw_params_fixup` are present in the image — is a DPCM path through the ASRC
that this firmware deliberately does not instantiate. That is why `/proc/asound/pcm`
shows one PCM and not three, and why `fsl-asrc` registers a driver but no card.

### 6.3 The codec driver is a stub

**[READ]** `snd-soc-moog-xmos` provides `xmos_esai_probe` (`0x8059abb0`),
`xmos_esai_remove`, `xmos_esai_i2c_probe`, `xmos_esai_i2c_remove`,
`xmos_esai_hw_params` (8 bytes long), `xmos_esai_shutdown` (4 bytes — a bare
`bx lr`), `xmos_esai_prepare`. The I2C device-id table entry name is
`"xmos-codec"` **[READ]**. `xmos_esai_dai_ops` has only `.shutdown` and
`.hw_params` populated, both pointing at those stubs **[READ]**.

`snd_soc_dai_driver xmos_esai_dai` at `0x809bbc30` **[READ]**:

```
.name = "xmos-codec"
.capture  = { .stream_name = "codec-Capture",  .formats = 0x44, .rates = 0x80,
              .rate_min = 0, .rate_max = 0, .channels_min = 1, .channels_max = 8 }
.playback = { .stream_name = "codec-Playback", .formats = 0x44, .rates = 0x80,
              .rate_min = 0, .rate_max = 0, .channels_min = 1, .channels_max = 8 }
```

`formats = 0x44` = bit 2 (`SNDRV_PCM_FMTBIT_S16_LE`) | bit 6
(`SNDRV_PCM_FMTBIT_S24_LE`); `rates = 0x80` = `SNDRV_PCM_RATE_48000`.
**[INFERRED]** from the standard ALSA bit numbering, and confirmed at runtime.

The boot log prints the negotiated capability set **[READ]**:

```
ASoC: xmos-codec <-> 2024000.esai info:
ASoC: rate mask 0x80
ASoC: min ch 1 max ch 8
ASoC: min rate 48000 max rate 48000
```

**The card supports 48 kHz only, S16_LE or S24_LE, 1–8 channels, in both
directions. [READ]**

**[INFERRED]** The "codec" is a software fiction — the machine driver's own log
line calls it a "faux codec/esai link". There is no register map, no I2C traffic in
the codec driver's DAI ops, no DAPM routing of substance. Real control of the XMOS
happens from userspace (`las-sc`), outside this region.

### 6.4 The exact TDM configuration

`imx_xmos_esai_surround_hw_params` is at `0x805a5d10`. Disassembled **[READ]**:

```
805a5d24: ldr  r5, [card_priv]        ; "already configured" flag
805a5d2c: cmp  r5, #0
805a5d30: beq  0x805a5d40             ; only run once
...
805a5d4c: str  r7(=1), [card_priv]    ; set the flag
805a5d50: bl   printk                 ; "ASoC : running hardware param setup/n"
805a5d54: ldr  r2, [card_priv+0xc]    ; 12288000
805a5d58: mov  r3, r5                 ; 0
805a5d5c: mov  r1, r7                 ; 1
805a5d64: bl   snd_soc_dai_set_sysclk ; (cpu_dai, clk_id=1, freq=12288000, dir=0)
805a5d6c: movw r1, #0x1203
805a5d70: bl   snd_soc_dai_set_fmt    ; (cpu_dai, 0x1203)
805a5d74: mov  r1, #255               ; tx_mask
805a5d78: mov  r12,#32                ; slot_width
805a5d80: mov  r2, r1                 ; rx_mask = 255
805a5d84: mov  r3, #8                 ; slots
805a5d88: str  r12,[sp]
805a5d8c: bl   snd_soc_dai_set_tdm_slot ; (cpu_dai, 0xFF, 0xFF, 8, 32)
```

`0x1203` decodes as **[INFERRED]** (standard ASoC `SND_SOC_DAIFMT_*` field layout):

* bits 0–3 = `0x3` = `SND_SOC_DAIFMT_LEFT_J`
* bits 4–7 = `0x0`
* bits 8–11 = `0x2` = `SND_SOC_DAIFMT_NB_IF` (normal bit clock, inverted frame)
* bits 12–15 = `0x1` = `SND_SOC_DAIFMT_CBM_CFM` (**codec is bit-clock and
  frame master**)

The boot log prints exactly this, from the ESAI driver's own instrumentation
**[READ]**:

```
[   46.530577] ASoC : running hardware param setup/n
[   46.530599] fsl-esai-dai 2024000.esai: setting clock direction as : 1
[   46.530611] fsl-esai-dai 2024000.esai: clock id: 1
[   46.530620] fsl-esai-dai 2024000.esai: clock rate: 12288000
[   46.530634] fsl-esai-dai 2024000.esai: Detected as clock input in slave mode
[   46.530644] fsl-esai-dai 2024000.esai: Config : LEFT_J - left justified
[   46.530651] fsl-esai-dai 2024000.esai: Config : NB_IF - normal block normal inverse frame sync
[   46.530660] fsl-esai-dai 2024000.esai: Config : CBM_CFM - Codec bit and frame master
[   46.530687] fsl-esai-dai 2024000.esai: setting tdm slot # : 8
[   46.530695] fsl-esai-dai 2024000.esai: setting tdm slot width  : 32
[   46.530702] fsl-esai-dai 2024000.esai: setting tdm masks : 255, 255
[   46.530711] fsl-esai-dai 2024000.esai: Bitclock will not be configured because slave mode
[   46.557452] fsl-esai-dai 2024000.esai: Bitclock will not be configured because slave mode
```

**Definitive TDM configuration:**

| parameter | value | grade |
|---|---|---|
| slots | **8** | **[READ]** — both disassembly and dmesg |
| slot width | **32 bits** | **[READ]** — both |
| tx_mask / rx_mask | **0xFF / 0xFF** (all 8 slots active both directions) | **[READ]** — both |
| format | **left-justified**, normal bit clock, **inverted frame sync** | **[READ]** — both |
| master | **the XMOS**; the i.MX6 ESAI is bit-clock and frame-sync **slave** | **[READ]** — both |
| sysclk | **12,288,000 Hz**, clk_id 1 | **[READ]** — both |
| Rx/Tx | synchronous (`fsl,esai-synchronous`; log: `setting synchronous mode`) | **[READ]** |
| sample rate | 48 kHz only | **[READ]** |
| sample format | S16_LE or S24_LE; **S24_LE in use** | **[READ]** — `hw_params` |

**[INFERRED]** 8 slots × 32 bits × 48 kHz = **12.288 MHz bit clock**, which is
exactly `codec_osc` and exactly the sysclk programmed. The whole clock tree is
internally consistent and it is generated on the XMOS side.

**One discrepancy, stated rather than resolved.** The disassembly shows the machine
driver calling `snd_soc_dai_set_sysclk(dai, 1, 12288000, 0)` — the fourth argument
(`dir`) is 0 — while the driver's log line reads `setting clock direction as : 1`.
**[UNKNOWN]** whether the driver's three `dev_info` calls print in the order
`(dir, clk_id, freq)` or some other order; the printed pair `direction 1 / id 1` is
ambiguous. It does not affect the conclusion: `Detected as clock input in slave
mode` and `CBM_CFM` both settle the master/slave question independently.

### 6.5 The ESAI driver has been modified by Moog

`fsl_esai_probe` is at `0x805a4a9c`. At `0x805a4bf4` **[READ]**:

```
805a4bf4: mov  r2, #1
805a4bf8: mov  r3, #2
805a4bfc: strb r2, [r4, #0x90]        ; esai_priv->slave = 1
805a4c00: mov  r0, r5                 ; dev
805a4c04: str  r3, [r4, #0x70]
805a4c08: movw r1, #0x610c            ; }
805a4c0c: movt r1, #0x808a            ; } "slave state boolean: %d\n"
805a4c10: bl   dev_err
```

**The slave flag is a hard-coded `1`.** It is not read from a device-tree property,
not from a module parameter, not from a board-file field. The boot log's
`fsl-esai-dai 2024000.esai: slave state boolean: 1` **[READ]** is therefore a
compile-time constant.

**[INFERRED]** `drivers/sound/soc/fsl/fsl_esai.c` in this tree has been patched by
Moog to force clock-slave operation unconditionally, and to add the block of
`dev_info`/`dev_err` instrumentation whose strings appear together in the image:

```
setting tdm slot # : %d          setting tdm slot width  : %d
setting tdm masks : %d, %d       Config : LEFT_J - left justified
Config : RIGHT_J - right justified
Config : NB_NF - normal block normal frame sync (non-inverted)
Config : NB_IF - normal block normal inverse frame sync
Config : CBM_CFM - Codec bit and frame master
setting clock direction as : %d  clock id: %d   clock rate: %d
Detected as clock input in slave mode
Bitclock will not be configured because slave mode
isr: Receiving overrun            isr: Transmition underrun
setting synchronous mode          esai startup complete!
slave state boolean: %d
```

Two of those are the xrun messages — `isr: Receiving overrun` and
`isr: Transmition underrun` — which is the string to look for when hunting audio
dropouts. Neither appears in the captured boot log. **[READ]**

The probe also reads `fsl,fifo-depth` from the DT via `of_get_property` (byte-swapped
into the private struct) and falls back to a default when absent **[READ]**; the
ESAI node in this DTB does **not** carry `fsl,fifo-depth` **[READ]**, so the
fallback (a constant `16` written into two fields at `0x805a4c3c`) applies
**[INFERRED]**.

### 6.6 The runtime PCM parameters — and a warning

`arch-harvest/runtime-state.txt` shows
`access: RW_INTERLEAVED / format: S24_LE / subformat: STD / channels: 8 /
rate: 48000 (48000/1) / period_size: 256 / buffer_size: 512`.

**Only the first four of those are safe to cite.** **[READ]** the caveat file:
`period_size 256 / buffer_size 512` reflect this project's own `-z 256 -Z 256`
experiment, since reverted. The stock configuration is set in
`/usr/share/las-fx/init_sc_1.scd` **[READ]**:

```
Server.named.at(\server_main).options.blockSize = 128;
Server.named.at(\server_main).options.hardwareBufferSize = 128;
Server.named.at(\server_main).options.numOutputBusChannels = 8;
Server.named.at(\server_main).options.numInputBusChannels = 9;
Server.named.at(\server_main).options.numWireBufs = 128;
Server.named.at(\server_main).options.memSize = 100000;
Server.named.at(\server_main).options.sampleRate = 48000;
Server.named.at(\server_main).latency = 0.05;
```

**[INFERRED]** stock ALSA period size is therefore 128 frames, i.e. 2.67 ms at
48 kHz, and the `-w 128` in the scsynth argv is `numWireBufs`, not the block size.

`imx-pcm-dma` is the ALSA platform driver (`.platform_name = "imx-pcm-audio"` in
the machine driver's link) **[READ]**, so the audio DMA is SDMA channels 23/24 on
peripheral type 21 as declared in the ESAI node.

---

## 7. CPU isolation and real-time configuration

### 7.1 What the kernel is configured for

**PREEMPT_RT is real, not just a version suffix. [READ]** Evidence, all
independent:

* banner `#1 SMP PREEMPT RT` — `mkcompile_h` emits the trailing `RT` only for
  `CONFIG_PREEMPT_RT_FULL` **[INFERRED]**
* the image contains `local_softirq_locks` (`&per_cpu(local_softirq_locks[i],
  __cpu).lock`) — a symbol that exists only in the RT patch's per-softirq lock
  scheme **[READ]**
* the image contains `irqfixup boot option not supported w/ CONFIG_PREEMPT_RT_BASE`
  and `irqpoll boot option not supported w/ CONFIG_PREEMPT_RT_BASE` **[READ]**
* the live process list contains RT-patch-only kernel threads: `ktimersoftd/0`,
  `ktimersoftd/1`, `posixcputmr/0`, `posixcputmr/1`, `rcuc/0`, `rcuc/1`,
  `kclksetdelayd`, `kcmosdelayd` **[READ]**
* threaded IRQs everywhere: `irq/26-esai`, `irq/284-sdma`, `irq/287-2184000`,
  `irq/288-2184200`, `irq/272-imx_the`, `irq/189-Back`, and the `-s-` shadow
  threads **[READ]**

Module `vermagic` is `4.1.15-rt18 SMP preempt ARMv7 p2v8` **[READ]**.

**`NO_HZ_FULL` is compiled in and applies to CPU1. [READ]** Boot log:

```
NO_HZ: Clearing 0 from nohz_full range for timekeeping
NO_HZ: Full dynticks CPUs: 1.
	Note: kernel parameter 'rcu_nocbs=' contains nonexistent CPUs.
	Offload RCU callbacks from CPUs: 1.
```

This is **not** on the command line (`nohz_full=` and `rcu_nocbs=` are absent from
the cmdline). **[INFERRED]** `CONFIG_NO_HZ_FULL_ALL=y`, which nominates every CPU
except the boot CPU; with `nr_cpu_ids = 2` that is exactly CPU1, and it implies
`rcu_nocbs` for the same set — the "nonexistent CPUs" note is the artefact of
`NR_CPUS=4` vs 2 present CPUs. So **CPU1 is tickless and its RCU callbacks are
offloaded to CPU0**, entirely by compile-time configuration.

`nohz=off` on the command line disables *idle* dynticks; it does not undo
nohz_full, which the log prints after it. **[INFERRED]** from the log ordering and
the fact that `nohz=` and `nohz_full=` have separate `__setup` handlers
(`setup_tick_nohz` and `tick_nohz_full_setup`) **[READ]**.

`skew_tick=1` is an early param that de-phases the per-CPU tick to avoid lock
convoying — a standard RT recommendation **[READ]** (`__setup_str_skew_tick`).

`cpuidle` governors: the log shows `cpuidle: using governor ladder` then
`cpuidle: using governor menu` **[READ]**.

### 7.2 `isolcpus=1` and who actually runs on CPU1

`isolcpus=1` is on the command line and is handled by `isolated_cpu_setup`
**[READ]**.

**[INFERRED]** `isolcpus` removes CPU1 from the scheduler's load-balancing domains
and from `init`'s inherited affinity mask, so by default *no* userspace task lands
on CPU1 — a task has to ask for it explicitly.

Nothing in `/etc` asks for it:

* `/etc/cgconfig.conf` **[READ]** creates the cgroups but assigns no tasks:

```
mount { cpuacct = /cgroup/cpuacct; cpuset = /cgroup/cpuset;
        cpu = /cgroup/cpu; memory = /cgroup/memory; }
group dsp      { cpuset { cpuset.cpus = 1; cpuset.mems = 0; }
                 cpu { cpu.shares = 100; } }
group frontend { cpuset { cpuset.cpus = 0; cpuset.mems = 0;
                          cpuset.sched_load_balance = 0; }
                 cpu { cpu.shares = 25; }
                 memory { memory.soft_limit_in_bytes = 16756736; } }
group sc       { cpuset { cpuset.cpus = 0; cpuset.mems = 0;
                          cpuset.sched_load_balance = 0; }
                 cpu { cpu.shares = 25; } }
```

* `/etc/init.d/S43gui` runs `cgconfigparser -l /etc/cgconfig.conf`
  (`/usr/sbin/cgconfigparser` exists) **[READ]**, which creates the hierarchy —
  the live mount table shows `/cgroup/{cpuacct,cpuset,cpu,memory}` mounted
  **[READ]** — but **nothing anywhere calls `cgclassify` or `cgexec`, and no
  binary in the image contains the string `cgroup`** (checked binary-safely with
  `strings` on `las-sc`, `las-frontend`, `scsynth`, `sclang`, `las-dwm`,
  `las-watchdog`: 0 hits each) **[READ]**.
* `/usr/share/las-fx/assign-pids` has `core=2` and two `taskset` loops, **both
  commented out** **[READ]**.

**[INFERRED]** The `dsp` cgroup (`cpuset.cpus = 1`) is created and never used. The
cgroup layer is not how work reaches CPU1.

**How work actually reaches CPU1: scsynth pins itself. [READ]** From the ARM
disassembly of `/usr/bin/scsynth` (read, not run), in the Moog-patched
`SC_AlsaDriver`, at file offsets `0x69f8c` and `0x6a5d8` — two near-identical
routines, one for the audio thread and one for the ALSA read thread:

```
69f9c: bl   pthread_self@plt
69fa4: mov  r0, #1                 ; SCHED_FIFO
69fa8: bl   sched_get_priority_max@plt
69fac: str  r0, [sp, #0x14]        ; sched_param.sched_priority = max
       ... prints "SC_AlsaDriver : Trying to set thread realtime prio = " ...
69fc8: mov  r1, #1                 ; SCHED_FIFO
69fd4: bl   pthread_setschedparam@plt
       ... on failure: "SC_AlsaDriver : Unsuccessful in setting thread realtime prio"
69ff8: mov  r2, #128
69ffc: add  r0, sp, #24
6a000: bl   memset@plt             ; cpu_set_t zeroed, 128 bytes
6a004: mov  r3, #2                 ; <-- bit 1
6a014: str  r3, [sp, #0x18]        ; cpuset.__bits[0] = 0x2  => CPU 1
6a018: bl   pthread_setaffinity_np@plt
       ... on failure: "SC_AlsaDriver : Unsuccessful in setting thread core affinity"
```

**Both scsynth threads set `SCHED_FIFO` at `sched_get_priority_max(SCHED_FIFO)` and
pin themselves to CPU 1 (mask `0x2`). [READ]** `sched_get_priority_max(SCHED_FIFO)`
is 99 on Linux **[INFERRED]**, so this is **SCHED_FIFO 99 on CPU1** — which
confirms the established architecture claim exactly, and identifies its mechanism:
it is inside the SuperCollider ALSA driver, not in any init script.

The associated strings **[READ]**: `SC_AlsaDriver : Trying to set thread realtime
prio = `, `SC_AlsaDriver : Trying to set read thread realtime prio = `,
`SC_AlsaDriver : Unsuccessful in setting thread core affinity`,
`Unsuccessful in read setting thread core affinity`,
`SC_AlsaDriver : Starting Audio Thread!`. (Stock SuperCollider has no affinity code
in `SC_AlsaDriver`; **[INFERRED]** this is a Moog patch.)

**[READ]** `las-frontend` is started with `--affinity-mask=1 --affinity-panel=1`
(mask 1 = CPU0) and its help text confirms the flags set pthread affinity.
`las-sc`, `las-dwm` and `las-watchdog` contain no affinity calls **[READ]**.

### 7.3 The rest of the RT priority map

`/usr/share/las-fx/assign-pids`, run once from `launch-sc-1` when scsynth drops its
cookie **[READ]**, whole relevant body:

```sh
chrt -r -p 94 $SCSYNTHPID                    # master process: SCHED_RR 94
for i in "${scsyntharr[@]}"; do              # every thread of scsynth
    pri=`cat /proc/$SCSYNTHPID/task/$i/stat | awk '{print $18}'`
    if [ $pri -ne -100 ]; then               # skip threads already at FIFO 99
        chrt -f -p 94 $i                     # SCHED_FIFO 94
    fi
done
esaiirq=`ps | grep esai | awk '{print $1} NR==1{exit}'`
chrt -f -p 89 $esaiirq                       # ESAI IRQ thread: SCHED_FIFO 89
sdmairq=`ps | grep sdma | awk '{print $1} NR==1{exit}'`
chrt -f -p 99 $sdmairq                       # SDMA IRQ thread: SCHED_FIFO 99
sdmadir=`ps | grep sdma | ...`               # -> 284
echo 1 > /proc/irq/$sdmadir/smp_affinity     # SDMA IRQ pinned to CPU0
```

**[READ]** Note the `$18 -ne -100` guard: `/proc/PID/task/TID/stat` field 18 is
`priority`, which the kernel reports as `-1 - rt_priority` for RT tasks, so
`-100` means FIFO 99. **[INFERRED]** The loop therefore deliberately *skips* the
threads scsynth has already put at FIFO 99 — the audio and read threads on CPU1 —
and demotes only the remaining scsynth threads to 94.

`/etc/init.d/S99final` adds **[READ]**:

```sh
iputasks=`ps | grep ipu   | awk '{print $1} NR==2{exit}'`
ipuirq=`ps   | grep 2400000 | awk '{print $1} NR==2{exit}'`
chrt -f -p 93 $iputasks   # ipu1_task threads: SCHED_FIFO 93
chrt -f -p 80 $ipuirq     # IPU IRQ threads:   SCHED_FIFO 80
devmem 0x020e0018 w 0xffffffff   # IOMUXC_GPR6: IPU1 AXI QoS to max
```

**Resulting priority map [READ], collated:**

| entity | policy / prio | CPU |
|---|---|---|
| scsynth audio thread | SCHED_FIFO 99 (self-set) | **1** (self-pinned) |
| scsynth ALSA read thread | SCHED_FIFO 99 (self-set) | **1** (self-pinned) |
| SDMA IRQ thread (irq 284) | SCHED_FIFO 99 | **0** (explicitly pinned) |
| scsynth main process | SCHED_RR 94 | 0 (default) |
| other scsynth threads | SCHED_FIFO 94 | 0 (default) |
| IPU `ipu1_task` | SCHED_FIFO 93 | 0 |
| ESAI IRQ thread | SCHED_FIFO 89 | 0 |
| IPU IRQ thread | SCHED_FIFO 80 | 0 |
| las-frontend | (not RT) | 0 (`--affinity-mask=1`) |

**[INFERRED]** The design splits the audio path across both cores: the ESAI/SDMA
interrupts are serviced on CPU0 (at FIFO 99 and 89) and the DSP callback runs on
the isolated, tickless CPU1 at FIFO 99. The wake-up therefore crosses cores every
period. `isolcpus=1` plus `NO_HZ_FULL` on CPU1 is what makes that CPU quiet enough
for it to work.

### 7.4 A real bug: RT throttling is never disabled

`/etc/init.d/S02sys`, whole `start()` body **[READ]**:

```sh
echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo 0 >  /proc/sys/vm/swappiness
echo 999950 > sched_rt_runtime_us            # <-- no path
echo 0 > /sys/class/backlight/backlight/brightness
```

The third line has **no directory prefix**. Busybox `init` runs `rcS` with cwd `/`,
so this creates a regular file at `/sched_rt_runtime_us` and never touches
`/proc/sys/kernel/sched_rt_runtime_us`. **[INFERRED]**

**And the artefact is right there in the live capture. [READ]** The owner's own
instrument dump, `captures/rootfs-1.5.0/sched_rt_runtime_us`, exists as a
7-byte regular file at the filesystem root containing exactly:

```
00000000: 3939 3939 3530 0a    999950.
```

The 1.8.2 packaged image does not have it (it has never booted); the live 1.5.0
dump does. **[INFERRED]** That is the S02sys write landing in the wrong place,
on a real machine, at least once.

`S02sys` is **byte-identical** between 1.5.0 and 1.8.2 (`diff` reports no
difference) **[READ]**, so the bug is still shipping in 1.8.2.

**Consequence, with direct evidence [READ]:** RT throttling stays at the kernel
default (950,000 µs of every 1,000,000 µs), and the boot log records it firing:

```
[ 1048.956052] sched: RT throttling activated
```

**[INFERRED]** At t≈17.5 minutes on the owner's instrument, an RT task consumed
more than 95 % of a scheduling period and the kernel clamped it. With the intended
999,950 the headroom would have been 99.995 %. **[UNKNOWN]** which task; the
message does not say, and `sched_rt_runtime_us` was not read on that machine.
Given the priority map above, the candidates are the FIFO-94 scsynth threads on
CPU0 or the FIFO-99 SDMA IRQ thread. This is the single highest-value item in the
validation plan.

`cgconfig.conf`'s `cpu.shares` values are also inert for the same reason as §7.2 —
no task is ever placed in those groups **[INFERRED]**.

### 7.5 CPU frequency

`S02sys` writes `performance` to `cpu0/cpufreq/scaling_governor` **[READ]**, and
`performance` is the only governor built into the kernel **[READ]** (§3.3). So the
CPU is pinned at the top OPP, **996 MHz at 1.250 V**, whenever cpufreq is up
**[INFERRED]**.

The boot log contains **no** `cpufreq` line at all — neither success nor failure
**[READ]**. `imx6q-cpufreq` is built in and `imx6q_cpufreq_probe` /
`imx6q_cpufreq_init` are present in the symbol table **[READ]**. **[UNKNOWN]**
whether the driver actually bound; `S02sys` writing to that sysfs path without a
visible error suggests it did, but no error would be visible either way (the script
has no error handling and the console is at `loglevel=0`). Put in the validation
plan.

### 7.6 Other kernel tunables set by userspace

**[READ]** `S02sys`: `vm.swappiness = 0` (there is no swap device anyway;
`/etc/fstab` declares none, and `::shutdown:/sbin/swapoff -a` is the only swap
reference in `inittab`).
**[READ]** `S40network`: `echo 1 > /proc/sys/net/ipv4/ip_forward`.
**[READ]** `S10udev`: `printf '\000\000\000\000' > /proc/sys/kernel/hotplug`
(disables the legacy hotplug helper before starting udevd).
**[READ]** `S99final` ends with `mount -f -o remount,ro /` — **the root filesystem
is read-only in normal operation**, unless a magic file `/media/thumbdrive/k`
containing the value `23051934` is present, in which case the xterms and window
manager are left running and root stays writable.

---

## 8. Boot sequence and boot-time anomalies

### 8.1 Sequence

`/etc/inittab` **[READ]**: mount `/proc`, remount `/` rw, create `/dev/pts` and
`/dev/shm`, `mount -a`, `hostname -F /etc/hostname` (= `las-production`), then
`/etc/init.d/rcS`, which runs every `S??*` in order **[READ]**:

```
S01logging   syslogd + klogd
S02sys       cpufreq governor, swappiness, the broken sched_rt_runtime_us, backlight off, RTC
S05avahi-setup.sh
S10udev      udevd -d, trigger subsystems then devices, settle (30 s timeout)
S12splash    las-fb-config, fbset 832x480x32 on fb1, X :0 -nocursor -s 0,
             dd /boot/moog_splash.fb > /dev/fb1, backlight up
S14fs        symlink farm under /var/local, clear /tmp and /mnt/fwu, log rotation, crontab
S25xmosfw    config-las-spi xmos   <-- releases the XMOS from reset
S30dbus
S40network   ifdown -a; ifup -a &; ip_forward=1
S42sc        las-sc  (the OSC/voice server)
S43gui       cgconfigparser; 3 xterms; las-frontend; las-dwm; xrandr -o inverted
S50avahi-daemon, S50dropbear, S80dhcp-relay, S80dhcp-server, S95dhcpd
S99final     IPU RT priorities, IOMUXC_GPR6 QoS, las-watchdog, kill xterms, remount / ro
```

Independently, `screen -d -m /usr/share/las-fx/launch-sc-1` starts `sclang`, which
boots `scsynth`; `assign-pids` runs when scsynth drops its cookie **[READ]**.

The timing in the boot log lines up **[READ]**: kernel done at ~1.37 s, udevd at
1.99 s, USB storage at 2.87 s, **XMOS USB device at 11.90 s** (S25xmosfw),
ESAI startup at 45.29 s, TDM configured at 46.53 s.

### 8.2 Anomalies visible at boot

All **[READ]** from `dmesg-before-reboot.txt`, listed because each is a real
defect someone will otherwise rediscover:

1. `imx6dl-pinctrl 20e0000.iomuxc: Invalid fsl,pins property in node …/gpio_keysgrp`
   — `gpio_keysgrp` has an empty `fsl,pins`.
2. `nand: No NAND device found` / `gpmi-nand … driver registration failed: -19`
   — NAND nodes with no NAND.
3. A full `WARNING` backtrace from `spidev_probe+0x1e0/0x1fc` (`drivers/spi/spidev.c:731`,
   "buggy DT: spidev listed directly in DT"). Harmless; the device binds.
4. `pin MX6DL_PAD_SD1_DAT3 already requested by 2080000.pwm; cannot claim for
   2184000.usb` → `imx_usb 2184000.usb: Error applying setting, reverse things back`.
5. `rtc-ds1307: probe of 2-0068 failed with error -5` — DS1307 in DT, not on board.
6. `imx6q-pcie 1ffc000.pcie: phy link never came up … probe … -22`.
7. `galcore: clk_get vg clock failed, disable vg!`.
8. `CPU PMU: Failed to parse /soc/pmu/interrupt-affinity[0]`.
9. `EXT3-fs (mmcblk2p3): error: couldn't mount because of unsupported optional
   features (40)` and the EXT2 equivalent, before EXT4 succeeds — the kernel simply
   tries the filesystems in order.
10. `EXT4-fs (mmcblk2p3): INFO: recovery required on readonly filesystem` and
    `FAT-fs (mmcblk2p4): Volume was not properly unmounted` — the machine had not
    been shut down cleanly. **[INFERRED]** unclean shutdown is the normal case for
    an instrument with a power switch.
11. `2000000.aips-bus:usbphy_nop1/2 supply vcc not found, using dummy regulator`,
    `2184800.usbmisc supply vbus-wakeup not found`, `backlight supply power not
    found`, `sdhci-esdhc-imx 2194000.usdhc: No vmmc/vqmmc regulator found` — all
    benign missing-regulator warnings.
12. `imx-sdma 20ec000.sdma: no iram assigned, using external mem`; SDMA firmware
    3.3 loaded.

### 8.3 Shutdown

`/etc/inittab` **[READ]**: `::shutdown:/etc/init.d/rcK`, `swapoff -a`,
`umount -a -r`. `rcK` is present but the `K??` scripts are not, so it iterates over
nothing meaningful **[READ]**. The `ctrlaltdel` line is commented out **[READ]**.

---

## 9. Answers to the two questions posed

| question | answer | evidence |
|---|---|---|
| Are both `ci_hdrc` controllers `dr_mode="host"`? | **CONFIRMED.** `usb@02184000` and `usb@02184200` both have `dr_mode = "host"` and `status = "okay"`. The two HSIC controllers also say `"host"` but are `"disabled"`. At runtime both register as `EHCI Host Controller` on USB bus 1 and 2. Independently, the kernel contains **no USB gadget stack at all** (no `usb/gadget/` in `modules.builtin`, zero `gadget`/`udc` symbols in 60,931 kallsyms entries), so device mode is not merely unconfigured — it is not compiled. | **[READ]** DTB `/soc/aips-bus@02100000/usb@*`; boot log; `modules.builtin`; recovered kallsyms |
| Is the i.MX6's own FEC ethernet `status="disabled"`? | **CONFIRMED.** `/soc/aips-bus@02100000/ethernet@02188000` has `status = "disabled"`. The `fec` driver is built in but never probes, and no FEC interface appears at runtime. Both network interfaces (`usbint`, `ethext`) are `cdc_ether` functions of the same USB device `2-1` on `ci_hdrc.1`. | **[READ]** DTB; boot log; `modules.builtin`; `/etc/udev/rules.d/*` |

---

## 10. Conflicts with existing documentation

These are recorded, not fixed, per the brief. I did not edit any existing document.

1. **`arch-harvest/runtime-state.txt` `period_size: 256 / buffer_size: 512`.**
   Already flagged by `CAVEAT-runtime-state.md`. Reconfirmed here from a second
   angle: `init_sc_1.scd` sets `blockSize = 128` and `hardwareBufferSize = 128`
   **[READ]**. Any document quoting 256 as the stock ALSA period is wrong. This is
   a conflict with the capture file, not with a `docs/` file.

2. **"The i.MX6 is the USB host / the XMOS is the USB device."** No conflict —
   confirmed and strengthened (§4.4, §9). Noted here only because I found a
   *stronger* argument than the one in circulation (the absent gadget stack), which
   any future doc should prefer, since it does not depend on a DT property that
   someone could in principle change.

3. **"cpu1 is the AUDIO core (scsynth's thread at SCHED_FIFO 99)."** Confirmed —
   but the *mechanism* is commonly mis-stated. It is not `isolcpus` alone, not the
   `dsp` cgroup (which is created and never populated), and not `assign-pids`
   (whose `taskset` lines are commented out). It is `pthread_setaffinity_np` with
   mask `0x2` inside scsynth's own patched `SC_AlsaDriver`, together with
   `pthread_setschedparam(SCHED_FIFO, sched_get_priority_max(SCHED_FIFO))`
   **[READ]**. Any doc that attributes CPU1 placement to the cgroup or to
   `assign-pids` is wrong about the mechanism even though it is right about the
   outcome. Separately: `assign-pids` sets scsynth's *other* threads to FIFO **94**
   and the SDMA IRQ to FIFO **99 on CPU0** — so "SCHED_FIFO 99" is true of the
   audio thread and of the SDMA IRQ thread, and not of the rest of scsynth.

4. **`docs/arch/` and `docs/CORRECTIONS-2026-09-08.md` were not audited against
   this report.** I read only their existence and directory listing; this document
   is a fresh, independent pass over the kernel region rather than a diff against
   prior text. **[UNKNOWN]** whether any specific prior statement about CMA size,
   thermal trips, TDM slot count, watchdog, or the RT-throttling bug already exists
   or contradicts the above. A reconciliation pass is worth doing and is listed
   under Unexplored.

---

## 11. Validation plan — READ-ONLY commands for a human to run

Every command below only reads. None writes, none reboots, none touches the XMOS
reset line, none invokes a Moog binary. Run over ssh as root.

**Highest value first — the RT throttling question (§7.4):**

```sh
cat /proc/sys/kernel/sched_rt_runtime_us      # expect 950000 if the S02sys bug is real
cat /proc/sys/kernel/sched_rt_period_us       # expect 1000000
ls -l /sched_rt_runtime_us ; cat /sched_rt_runtime_us   # expect a 7-byte file "999950"
dmesg | grep -i "RT throttling"
```

**CPU isolation, affinity and RT map (§7.2, §7.3):**

```sh
cat /proc/cmdline
cat /sys/devices/system/cpu/isolated
cat /sys/devices/system/cpu/nohz_full
grep -H . /proc/$(pidof scsynth)/task/*/stat | awk '{print $1, $3, $19, $20, $41}'
for t in /proc/$(pidof scsynth)/task/*; do echo -n "$t "; cat $t/status | grep Cpus_allowed_list; done
chrt -p $(pidof scsynth)
taskset -p $(pidof scsynth)
cat /proc/interrupts                          # which CPU is servicing esai / sdma
grep -H . /proc/irq/*/smp_affinity_list 2>/dev/null | grep -Ei "sdma|esai" 
cat /cgroup/cpuset/dsp/tasks                  # expect empty
cat /cgroup/cpuset/dsp/cpuset.cpus            # expect 1
```

**cpufreq (§7.5):**

```sh
ls /sys/devices/system/cpu/cpu0/cpufreq/
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies
cat /sys/devices/system/cpu/cpu0/cpufreq/stats/time_in_state 2>/dev/null
```

**Thermal (§5):**

```sh
for z in /sys/class/thermal/thermal_zone*/; do
  echo "== $z"; cat $z/type $z/temp $z/policy 2>/dev/null
  for t in $z/trip_point_*_temp $z/trip_point_*_type $z/trip_point_*_hyst; do
    [ -e "$t" ] && echo -n "$t = " && cat "$t"; done
done
ls /sys/class/thermal/
for c in /sys/class/thermal/cooling_device*/; do cat $c/type $c/cur_state $c/max_state; done
```

**Memory and CMA (§4.2):**

```sh
head -20 /proc/meminfo
grep -i cma /proc/meminfo
dmesg | grep -Ei "cma|Memory:"
cat /proc/iomem
cat /sys/kernel/debug/cma/*/count 2>/dev/null
```

**USB roles and the XMOS device (§4.4):**

```sh
cat /sys/kernel/debug/usb/devices        # full descriptor dump for bus 1 and 2
ls -l /sys/bus/usb/devices/
cat /sys/bus/platform/devices/ci_hdrc.0/role 2>/dev/null
cat /sys/bus/platform/devices/ci_hdrc.1/role 2>/dev/null
lsusb -v 2>/dev/null | head -200        # if lsusb exists; -v is read-only
ip -d link show
ls /sys/class/net/*/device/ -l
```

The `/sys/kernel/debug/usb/devices` dump is the one that would settle, once and for
all, whether the XMOS exposes any Audio-class (MIDI) interface that Linux is simply
declining to claim. It came back empty in the earlier harvest.

**ALSA and the ESAI/TDM path (§6):**

```sh
cat /proc/asound/cards
cat /proc/asound/pcm
cat /proc/asound/card0/pcm0p/sub0/hw_params
cat /proc/asound/card0/pcm0c/sub0/hw_params
ls /sys/kernel/debug/asoc/ 2>/dev/null
cat /sys/kernel/debug/asoc/xmos-audio/*/dapm_pop_time 2>/dev/null
dmesg | grep -E "fsl-esai-dai|imx-xmos-esai|ASoC"
# ESAI register dump (read-only, via debugfs regmap if CONFIG_REGMAP is exposed):
cat /sys/kernel/debug/regmap/2024000.esai/registers 2>/dev/null
```

**Watchdog (§4.12):**

```sh
ls /sys/class/watchdog/
cat /sys/class/watchdog/watchdog0/identity /sys/class/watchdog/watchdog0/timeout \
    /sys/class/watchdog/watchdog0/state /sys/class/watchdog/watchdog0/bootstatus 2>/dev/null
ls -l /proc/*/fd 2>/dev/null | grep watchdog
```

**Device tree as the kernel actually sees it (guards against a U-Boot fixup that
differs from the DTB on disk):**

```sh
cat /sys/firmware/devicetree/base/soc/aips-bus@02100000/usb@02184000/dr_mode; echo
cat /sys/firmware/devicetree/base/soc/aips-bus@02100000/usb@02184200/dr_mode; echo
cat /sys/firmware/devicetree/base/soc/aips-bus@02100000/ethernet@02188000/status; echo
hexdump -C /sys/firmware/devicetree/base/reserved-memory/linux,cma/size
hexdump -C /sys/firmware/devicetree/base/memory/reg
cat /sys/firmware/devicetree/base/model; echo
```

**Modules and build identity:**

```sh
lsmod
cat /proc/version
uname -a
cat /proc/config.gz 2>/dev/null | gunzip | head -50    # almost certainly absent
```

**Bus frequency (§4.12):**

```sh
cat /sys/bus/platform/drivers/imx_busfreq/*/enable 2>/dev/null
cat /sys/devices/soc0/busfreq/enable 2>/dev/null
dmesg | grep -i busfreq
```

---

## 12. Unexplored

Things inside this region that I did not reach, ordered by how much they would
change the picture.

1. **The `esaigrp` pad decode.** Eight pads are muxed to ALT0 with pad-control
   `0x1b030`, but which ESAI signal each carries (HCKT/SCKT/FST/SDO0..3/SDI) needs
   the i.MX6DL reference manual's IOMUXC select-input table, which is not in this
   capture. Knowing it would tell us the physical wire count between the i.MX6 and
   the XMOS, and whether 8 TDM channels ride one data line or several.
2. **U-Boot.** Not in the capture at all. It sets the base bootargs (everything
   before `isolcpus=1`), rewrites `/memory/reg` from 1 GiB to 512 MiB, may enable
   WDOG2, and may or may not consume `gpumem=128M`. The eMMC boot partitions
   (`mmcblk2boot0`/`boot1`, 4 MiB each) presumably hold it.
3. **`galcore` contiguous memory: 64 MiB or 128 MiB?** The DT declares
   `contiguous_mem` = 128 MiB and the cmdline says `galcore.contiguousSize=67108864`.
   Which wins would need the `gpu-viv` source or a live boot-log grep.
4. **Whether `imx6q-cpufreq` actually bound.** No boot-log evidence either way.
5. **Whether WDOG2 is counting.** Depends on U-Boot; nothing in userspace opens
   `/dev/watchdog`.
6. **`imx_busfreq` runtime state.** The driver loads; whether DDR/AXI frequency
   scaling is enabled during audio is unknown, and it would be a plausible source
   of period-boundary jitter.
7. **Which task triggered `sched: RT throttling activated`.** Not recoverable from
   the log.
8. **The thermal zone's polling interval, hysteresis and bound cooling devices.**
   Only the two trip temperatures were recovered from code.
9. **`fsl_esai_hw_params` / `fsl_esai_reset` / `esai_isr` internals.** I read
   `fsl_esai_probe`, the machine driver and the codec driver, but did not fully
   disassemble the ESAI hw_params path, the FIFO watermark setup, or the xrun
   handling — relevant if anyone chases dropouts.
10. **The `HiFi-ASRC-FE` / `HiFi-ASRC-BE` DPCM link.** Present in the binary,
    disabled at probe by `num_links = 1`. Whether it could be enabled, and what it
    would buy, is unexamined.
11. **The three Moog kernel patches' source.** I identified them by their strings
    and code (ESAI forced slave + instrumentation; IPU DMFC "CUSTOM MOOG"; the two
    `snd-soc-*xmos*` drivers) but there is no kernel source tree in the capture.
12. **`/etc/X11`, `las-fb-config`, `las-dwm`, the display stack above the
    framebuffer.** Adjacent to but outside this region.
13. **Reconciliation with `docs/arch/*.md` and `docs/CORRECTIONS-2026-09-08.md`.**
    I deliberately did not read them in depth, to keep this pass independent. A
    follow-up should diff this document against them.
14. **The 1.5.0 vs 1.8.2 userspace diff.** I compared only the kernel, DTB, cmdline
    and module metadata (and `S02sys` / `cgconfig.conf`, both identical). The rest
    of the two rootfs trees was not diffed.
15. **`/etc/vxtune`, `/var/tuning.vxtune`, `/etc/versionb`.** Present, unexamined,
    out of region.
