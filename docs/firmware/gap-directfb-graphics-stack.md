# DirectFB: a complete second graphics-and-input stack, installed and never used

**Scope.** Everything in firmware 1.8.2 belonging to DirectFB 1.7.7 — the four
core shared libraries, twenty-three loadable modules, three executables, four
data files — plus the question the gap assignment asked: is this live, residue,
or a selectable fallback, and does its `linux_input` driver give a second,
independent description of the front panel.

**Instrument was not touched.** Every statement below comes from files on local
disk. Proposed live reads are in [§16](#16-validation-plan-read-only) for a
human to run.

**Grading.** `[READ]` = read directly out of a named file, with offset or line.
`[INFERRED]` = reasoned from stated evidence. `[UNKNOWN]` = not established.

---

## 1. Headline

**DirectFB 1.7.7 is installed complete and correct on the Moog One, is wired to
nothing, and has never been wired to anything.** A case-insensitive search of
the entire 1.8.2 root filesystem for the string `directfb` returns thirty-one
files: the thirty that *are* DirectFB, plus one GObject enum name inside
`libcairo-gobject.so` **[READ]**. No init script, no `las-*` binary, no
configuration file, and no running process references it **[READ]**.

The second half of the assignment's premise does not survive contact with the
evidence. DirectFB's `linux_input` driver would enumerate `/dev/input/event*`
**[READ]** — and on this machine the kernel creates exactly **one** evdev node,
`gpio-keys` → `input0` **[READ, dmesg]**. The Moog One's panel and keybed are
**not** Linux input devices; they arrive as OSC over UDP from the XMOS at
`203.0.113.2` **[READ]**. So DirectFB cannot document the front panel from a
second source, because from Linux's point of view there is no front panel to
document. See [§8](#8-what-linux_input-would-actually-find).

---

## 2. What was read, and how

| item | path |
|---|---|
| 1.8.2 rootfs | `/Volumes/Main External/Development/MoogOnePlus/captures/firmware-1.8.2/rootfs-1.8.2` |
| 1.5.0 rootfs | `/Volumes/Main External/Development/MoogOnePlus/captures/rootfs-1.5.0` (present and complete) |
| live harvest | `/Volumes/Main External/Development/MoogOnePlus/captures/arch-harvest` |
| boot log | `/Volumes/Main External/Development/MoogOnePlus/captures/dmesg-before-reboot.txt` |

Tools: `strings`, `xxd`, `grep -a`, `md5`, `cmp`, `python3` (struct parsing),
and `llvm-objdump -p` / `llvm-nm -D` from
`/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/`.
**No Moog or DirectFB binary was executed.** They are `elf32-littlearm`,
`Cortex-A9` **[READ, `llvm-objdump -f`]**, and this host is macOS/arm64.

`runtime-state.txt` is cited only for process enumeration, which
`CAVEAT-runtime-state.md` explicitly lists as unaffected by this project's own
modifications. The contamination in that file (block size 256, extra nodes,
`/var` residue) does not bear on whether a DirectFB process exists.

---

## 3. Complete inventory (1.8.2)

Total regular-file footprint: **2,786,184 bytes** across 34 files
(4 core libraries, 3 executables, 23 modules, 4 data files) plus 6 symlinks
**[READ, `stat`/`os.walk`]**.

### 3.1 Core libraries — `/usr/lib`

| md5 | size | path |
|---|---:|---|
| `65757a08ef79d21a13a1a3d97d75bc8a` | 952,056 | `libdirectfb-1.7.so.7.0.0` |
| `94f6ba68e9200efb3ad4e2daa0b29590` | 97,416 | `lib++dfb-1.7.so.7.0.0` |
| `2bf671048b5b1dc3dd4a7b046baa2cce` | 113,928 | `libdirect-1.7.so.7.0.0` |
| `596c0f44409aa18c6dad24c708bdcfde` | 43,916 | `libfusion-1.7.so.7.0.0` |

Symlinks, all `lrwxrwxrwx` **[READ, `ls -la`]**:
`libdirectfb.so` and `libdirectfb-1.7.so.7` → `libdirectfb-1.7.so.7.0.0`;
`lib++dfb.so` and `lib++dfb-1.7.so.7` → `lib++dfb-1.7.so.7.0.0`;
`libdirect.so` → `libdirect-1.7.so.7.0.0`;
`libfusion.so` → `libfusion-1.7.so.7.0.0`.

`libdirect` and `libfusion` are **not** named `*dfb*` and are therefore missed
by the obvious `find -iname '*dfb*'`. Any future sweep for this stack must
search for `libdirect-` and `libfusion-` as well **[READ]**.

### 3.2 Executables — `/usr/bin`, mode `-rwxr-xr-x`

| md5 | size | name | purpose (from its own usage string) |
|---|---:|---|---|
| `15512c46c3f54e4ebbfba4d39151ccdc` | 14,168 | `dfbplay` | `Usage: %s [-f] <filename>` **[READ]** — video playback via `IDirectFBVideoProvider` |
| `40bc9be13a631f4f5ce904758d8a3a6d` | 17,240 | `dfbshow` | `Usage: … <filename>` **[READ]** — image display via `IDirectFBImageProvider` |
| `0d5c4e66c302a6bf6adcd36d8f939266` | 10,352 | `dfbswitch` | `Usage: … <width>x<height>`, prints `Video Modes` / `  - %dx%d` **[READ]** — enumerate and set display-layer modes |

All three link `lib++dfb-1.7.so.7` and carry mangled C++ symbols
(`_ZN7DFBShow…`, `_ZN7DFBPlay…`, `_ZN8Switcher…`) **[READ, `strings`]**.
`[INFERRED]` These are upstream DirectFB C++-binding sample programs, not
Moog-authored: their `DT_RPATH` includes
`…/build/directfb-1.7.7/lib/++dfb/.libs`, i.e. they were linked inside the
DirectFB source tree during the DirectFB package build.

### 3.3 Loadable modules — `/usr/lib/directfb-1.7-7`, mode `-rwxr-xr-x`

`[READ]` `libdirect-1.7.so.7.0.0` hard-codes the default search path
`/usr/lib/directfb-1.7-7` and documents it as
`module-dir=<directory>  Override default module search directory (default = $libdir/directfb-x.y-z)`.
The directory exists at exactly that path, so modules would be found.

**`systems/` — 3 backends**

| md5 | size | module | what it drives |
|---|---:|---|---|
| `868ad771b26864c63d9d289c3650b463` | 47,428 | `libdirectfb_fbdev.so` | raw Linux framebuffer; registers `FBDev Primary Screen` / `FBDev Primary Layer` **[READ, off. 41418]** |
| `92a3526f7a70eb2c373faa7b689e3ca7` | 12,292 | `libdirectfb_devmem.so` | `/dev/mem` direct-aperture backend (driven by the `video-phys=` / `mmio-phys=` options) |
| `40d27e4e03cc730ec0f475539b45f104` | 8,668 | `libdirectfb_dummy.so` | headless null backend |

**`inputdrivers/` — 5 drivers**

| md5 | size | module | device it opens **[READ]** |
|---|---:|---|---|
| `b26cf6ec8ab2258526b4ea5875fd78bc` | 20,444 | `libdirectfb_linux_input.so` | `/dev/input/event%d` (off. 18083) |
| `f05c778453422d6037b2c386c27d3dcf` | 7,252 | `libdirectfb_tslib.so` | `/dev/input/tslib%d`, honours `$TSLIB_TSDEVICE` |
| `c4034df9089aad540b36fffb88db080d` | 9,176 | `libdirectfb_keyboard.so` | `/dev/tty0` |
| `76ea018818c587f8a6019d6d3d8ef130` | 9,960 | `libdirectfb_ps2mouse.so` | `/dev/input/mice`, `/dev/psaux`, `/dev/misc/psaux` |
| `04c40a92d7cbe47ef94848da0550168e` | 9,252 | `libdirectfb_serialmouse.so` | device from `mouse-source=`; protocols `MouseMan`, `MouseSystems` |

**`wm/` — 1 window manager**

| md5 | size | module |
|---|---:|---|
| `686c00f2b22094a591d3fe99c5218374` | 35,976 | `libdirectfbwm_default.so` — strings `WM/Default: …`, `dfb_windowstack_cursor_enable` **[READ]** |

`[READ]` The `wm=<wm>` option advertises `'default' or 'unique'`; only
`default` is installed. Requesting `unique` would fail to load.

**`interfaces/` — 14 modules in 5 families**

| family | modules |
|---|---|
| `IDirectFBImageProvider` | `png` (13,348), `jpeg` (10,712), `gif` (11,464), `bmp` (8,928), `pnm` (11,140), `svg` (10,320), `dfiff` (6,916), `mpeg2` (38,728) |
| `IDirectFBFont` | `ft2` (15,704, FreeType), `dgiff` (8,188, DirectFB's own pre-rendered format) |
| `IDirectFBVideoProvider` | `gif` (14,156) |
| `IDirectFBWindows` | `default` (6,948) |
| `IWater` | `default` (51,640) |
| `ICoreResourceManager` | `test` (6,588) |

`[READ]` `IWater` exports `IWater_RenderShape`, `IWater_RenderElementList`,
`IWater_SetAttributes`, and identifies itself as
`IWater Interface default Implementation` — DirectFB 1.7's vector/shape
rendering interface. `[READ]` `ICoreResourceManager/libicoreresourcemanager_test.so`
is the upstream *test* resource-manager implementation, selectable only via
`resource-manager=<impl>`.

Per-module md5s for all 23 are in [§17](#17-appendix-a--module-tree-md5-manifest).

### 3.4 Data — `/usr/share/directfb-1.7.7`, mode `-rw-r--r--`

| md5 | size | file |
|---|---:|---|
| `6708ceae125b158dd59396ba508de9e6` | 6,400 | `cursor.dat` |
| `a3a2b0ed1d8d46c977478a8c08414d0d` | 16,032 | `cursor.png` |
| `15da3786e1a07590befe5113ceaf551b` | 1,102,400 | `decker.dgiff` |
| `11b8753a0075a59a8d93e0d3b5669833` | 37,048 | `decker.ttf` |

Fully decoded in [§11](#11-the-four-data-files-decoded).

---

## 4. Provenance: who built it, when, from what

### 4.1 The build path is in every binary

`[READ]` Every DirectFB ELF in 1.8.2 carries a `DT_RPATH`
(`llvm-objdump -p`). For `libdirectfb-1.7.so.7.0.0` the string sits at byte
offset **141530** and reads:

```
/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/build/directfb-1.7.7/lib/direct/.libs:
/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/build/directfb-1.7.7/lib/fusion/.libs:
/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/host/usr/arm-buildroot-linux-gnueabihf/lib
```

This establishes, all `[READ]`:

* the package is **Buildroot's `directfb` at version 1.7.7**, unpatched enough
  that the source directory is literally `build/directfb-1.7.7`;
* the toolchain tuple is **`arm-buildroot-linux-gnueabihf`**;
* the build tree is **`las-buildroot`** under a repository path
  `moog/hardware/moog-one`;
* it was built on a CI runner whose working directory is
  `/home/las-ci-builds/glrt-t3_/0/…`.

`[INFERRED]` `glrt-t3_` is a GitLab-Runner identifier and `…/0/` its
concurrency slot; combined with the `moog/hardware/moog-one` group/subgroup
path this is a GitLab CI job. Evidence: the shape of the path and the
`las-ci-builds` home directory shared by every Moog binary in this rootfs.

### 4.2 The build date is in the library

`[READ]` `libdirectfb-1.7.so.7.0.0`, byte offset **868365**:

```
DirectFB/Core: %s Application Core. (2025-09-15 18:34) %s%s
```

The parenthesised date is the compile timestamp baked in at build time. It
matches the `Sep 15 2025` mtime carried by essentially every non-symlink file
in this rootfs.

`[READ]` The same format string in **1.5.0** reads `(2022-05-16 14:51)`.

`[READ]` Byte offset **850313** of the 1.8.2 library holds the startup banner:

```
   ~~~~~~~~~~~~~~~~~~~~~~~~~| DirectFB 1.7.7 |~~~~~~~~~~~~~~~~~~~~~~~~~~
```

### 4.3 The `%s` is `Single` — this is a single-application build

`[READ]` The only candidate substitution string in the library is `Single`
(offset 868390); there is no bare `Multi` string. `[READ]` `libfusion` contains
no `/dev/fusion` reference at all — its only device-ish configuration is
`tmpfs=<directory>  Location of shared memory file`. `[READ]` The rootfs
contains exactly two kernel modules
(`imx_rpmsg_tty.ko`, `imx_rpmsg_pingpong.ko` under
`/lib/modules/4.1.15-rt18/kernel/drivers/rpmsg/`); there is no `fusion.ko`.

`[INFERRED]` DirectFB was configured **without multi-application support**.
Consequence: even if someone started a DirectFB program here, a *second* one
could not attach to it. The banner would print `Single Application Core.`

### 4.4 1.5.0 → 1.8.2: a rebuild, not a change

`[READ]` The 1.5.0 `DT_RPATH` is different:

```
/home/las-ci-builds/6c53963c/0/moogmusic/las-buildroot/output/build/directfb-1.7.7/…
```

`[READ]` `moogmusic` (20 chars for `6c53963c/0/moogmusic`) became
`moog/hardware/moog-one` (33 chars for `glrt-t3_/0/moog/hardware/moog-one`) —
**+13 bytes per occurrence**, which is exactly the delta
`docs/firmware/diff-files.md:217` attributes to "the +13-byte CI path".

`[READ]` Observed size deltas, 1.8.2 minus 1.5.0:

| file | 1.5.0 | 1.8.2 | Δ |
|---|---:|---:|---:|
| `libdirectfb-1.7.so.7.0.0` | 952,056 | 952,056 | 0 |
| `libdirect-1.7.so.7.0.0` | 113,928 | 113,928 | 0 |
| `libfusion-1.7.so.7.0.0` | 43,888 | 43,916 | +28 |
| `lib++dfb-1.7.so.7.0.0` | 97,360 | 97,416 | +56 |
| `dfbplay` | 14,168 | 14,168 | 0 |
| `dfbshow` | 17,176 | 17,240 | +64 |
| `dfbswitch` | 10,288 | 10,352 | +64 |
| most modules | — | — | +52 (= 4 × 13) |
| `fbdev`, `ps2mouse`, `mpeg2` | — | — | 0 |

`[INFERRED]` The deltas are the RPATH string growth, rounded up by ELF section
alignment: where the growth fits in existing padding the size is unchanged,
otherwise it appears as a multiple of the alignment quantum. Evidence: the
4-entry RPATHs grow by exactly 4 × 13 = 52 and that is the modal delta.

**The decisive test — the exported ABI is byte-for-byte the same set.**
`[READ]` `llvm-nm -D --defined-only` on `libdirectfb-1.7.so.7.0.0` yields
**2003** exported symbols in 1.8.2 and **2003** in 1.5.0, and `comm` shows an
empty difference in both directions.

`[READ]` `/usr/share/directfb-1.7.7` is **md5-identical** between the two
firmwares, all four files.

`[INFERRED]` DirectFB did not change between 1.5.0 and 1.8.2. It was recompiled
from identical source because the whole Buildroot tree was recompiled after the
repository was reorganised from `moogmusic/` to `moog/hardware/moog-one/`. The
23 "changed" DirectFB files counted at `diff-files.md:136` are entirely
accounted for by this. `[READ]` 30 DirectFB ELFs differ in total (23 modules +
4 core libs + 3 executables); the "23" bucket is consistent with the core libs
having been counted under `shared libraries` (108) and the executables under
`/usr/bin executables` (119).

---

## 5. What is *not* installed — the negative inventory

Each line `[READ]`, by direct absence check.

| absent | consequence |
|---|---|
| **`/usr/lib/directfb-1.7-7/gfxdrivers/`** — the directory does not exist | **No graphics acceleration driver of any kind.** DirectFB would run entirely on its built-in software rasteriser. |
| any `vivante`, `galcore`, `libGAL`, `imx`, or `ipu` string inside `libdirectfb-1.7.so.7.0.0` | No i.MX6/Vivante backend was ever compiled in, statically or otherwise. |
| `/etc/directfbrc`, `~/.directfbrc`, or any file named `directfbrc` | The string `directfbrc` occurs **only** inside the library itself (offsets 897433, 897448) — the code that would read a config file that does not exist. Every option would take its compiled-in default. |
| `/etc/fb.modes` | `libdirectfb_fbdev.so` exports `dfb_fbdev_read_modes` **[READ]**, but has no mode file to read. Mode selection would fall back entirely to the framebuffer's current `FBIOGET_VSCREENINFO` state. |
| `dfbdump`, `dfbinfo`, `dfbinput`, `dfblayer`, `dfbscreen`, `dfbg`, `dfbpenmount`, `directfb-csource`, `mkdfiff`, `mkdgiff`, `mkifff`, `fusion_bench` | The diagnostic and asset-authoring half of the DirectFB tool set is not shipped. Only the three display sample programs are. |
| any `df_*` demo binary; any `directfb` subdirectory under `/usr/share/examples` | The `directfb-examples` package was not built. |
| `/usr/include/directfb*`, `/usr/lib/pkgconfig/*` (the whole pkgconfig dir is empty), `*.la`, `*.a`, `directfb-config` | Runtime-only install. Nothing on the instrument can compile against DirectFB. |
| `.symtab` / `.debug_*` in any DirectFB ELF | All stripped. |
| `/etc/ld.so.conf`, `/etc/ld.so.conf.d/`, `/etc/ld.so.cache` | The loader falls back to its built-in trusted directories plus `DT_RPATH`. `/usr/lib` is a default, so the libraries would still resolve. |

`[READ]` The library *does* contain the strings `gfxdrivers`,
`dfb_graphics_drivers`, `Software Rasterizer`, and 57 occurrences of `Genefx`
(DirectFB's software blitting engine). `[INFERRED]` The lookup path for
hardware drivers exists but has nothing to find; all rendering would go through
Genefx on the CPU.

---

## 6. Every dependency resolves — the stack is functionally complete

`[READ]` For all 30 DirectFB ELFs, every `DT_NEEDED` entry was resolved against
`{rootfs}/lib` and `{rootfs}/usr/lib`. **Zero unresolved.**

Dependency shape **[READ, `llvm-objdump -p`]**:

```
dfbplay/dfbshow/dfbswitch
  → lib++dfb-1.7.so.7 → libdirectfb-1.7.so.7 → libfusion-1.7.so.7 → libdirect-1.7.so.7
  (+ libz, libstdc++, libdl, librt, libpthread, libm, libgcc_s, libc)

systems/*, inputdrivers/*, wm/*, interfaces/*
  → libdirect-1.7.so.7, libfusion-1.7.so.7, libdirectfb-1.7.so.7 (+ the same C runtime set)
```

Modules with extra dependencies, all satisfied **[READ]**:

| module | extra `DT_NEEDED` | present |
|---|---|---|
| `IDirectFBFont/…_ft2.so` | `libfreetype.so.6`, `libpng16.so.16` | yes |
| `IDirectFBImageProvider/…_png.so` | `libpng16.so.16` | yes |
| `IDirectFBImageProvider/…_jpeg.so` | `libjpeg.so.8` | yes |
| `inputdrivers/…_tslib.so` | `libts-1.0.so.0` | yes (`/usr/lib/libts-1.0.so.0.0.0`, 6,556 B) |
| `IDirectFBImageProvider/…_svg.so` | 20 libraries: `libsvg-cairo.so.1`, `libsvg.so.1`, `libcairo.so.2`, `libpixman-1.so.0`, `libfontconfig.so.1`, `libexpat.so.1`, `libfreetype.so.6`, `libjpeg.so.8`, `libpng16.so.16`, `libGLESv2.so.2`, `libEGL.so.1`, `libOpenVG.so`, `libX11.so.6`, `libXext.so.6`, `libXrender.so.1`, `libXau.so.6`, `libXdmcp.so.6`, `libxcb.so.1`, `libxcb-shm.so.0`, `libxcb-render.so.0`, `libatomic.so.1` | **all yes** |

The SVG image provider is worth calling out: `[READ]` it drags in the entire
X11 client chain and EGL/OpenVG, because Buildroot's `libsvg-cairo` was linked
against the X-enabled cairo. `[READ]` `libatomic.so.1` lives in **`/lib`**, not
`/usr/lib` — a check confined to `/usr/lib` would wrongly report this module
broken. It is not broken.

`[INFERRED]` Nothing prevents this stack from initialising. It is complete,
self-consistent, and dependency-clean. Its inertness is a matter of nothing
calling it, not of it being unusable.

---

## 7. Is it wired in? Four independent sweeps say no

### 7.1 Linkage sweep

`[READ]` `grep -rlai directfb` over the whole 1.8.2 rootfs (`du -sh` = 488 M **[READ]**) returns
exactly 31 files. Thirty are the DirectFB stack itself. The thirty-first is
`/usr/lib/libcairo-gobject.so.2.11400.4`, which contains two matches:
`CAIRO_SURFACE_TYPE_DIRECTFB` and `directfb`.

`[READ]` `libcairo.so.2.11400.4` — the actual cairo library — contains **zero**
`directfb` strings, and `llvm-nm -D` finds no `cairo_directfb_*` symbols.

`[INFERRED]` Cairo has **no** DirectFB backend here. The two strings are the
GObject enum-name table for `cairo_surface_type_t`, which is generated from the
public header and lists every backend cairo *can* have, compiled or not. This
is a false positive and should not be recorded as a DirectFB consumer.

`[READ]` Targeted check of the binaries that plausibly could have used it:

| binary | size | `directfb` hits | `IDirectFB` hits |
|---|---:|---:|---:|
| `usr/bin/las-frontend` | 145,033,524 | 0 | 0 |
| `usr/bin/las-dwm` | 61,272 | 0 | 0 |
| `usr/bin/las-sc` | 2,499,540 | 0 | 0 |
| `usr/bin/psplash` | 47,564 | 0 | 0 |
| `usr/bin/fbv` | 22,608 | 0 | 0 |
| `usr/bin/fbgrab` | 10,432 | 0 | 0 |
| `usr/bin/detect-held-buttons` | 738 | 0 | 0 |

**This settles the open question in the gap assignment.** `las-fb-config` and
`psplash` do touch the framebuffer, but neither links DirectFB. `[READ]`
`las-fb-config`'s only `DT_NEEDED` is `libc.so.6`; its entire dynamic import
list is `exit, sprintf, perror, abort, memset, __errno_location, stderr, ioctl,
atoi, close, open, fprintf, strerror, __libc_start_main`. It is a bare `ioctl`
program.

### 7.2 Boot sweep

`[READ]` `grep -rniE 'dfb|directfb|/dev/fb|…'` across `/etc` matches DirectFB
nowhere. The only framebuffer references in `/etc` are:

* `etc/init.d/S12splash:9,26` — `las-fb-config 1 0` / `las-fb-config 1 $i`
* `etc/init.d/S12splash:14,15` — two `fbset … -fb /dev/fb1` calls
* `etc/init.d/S12splash:21` — `dd if=/boot/moog_splash.fb of=/dev/fb1`
* `etc/init.d/S43gui:69` — `las-fb-config 1 0`
* `etc/X11/xorg.conf:4,5` — `Option "fbdev" "/dev/fb0"`, `Option "vivante_fbdev" "/dev/fb0"`

`[READ]` The init system is BusyBox SysV (`/etc/init.d/S01logging` …
`S99final`); there is no `/etc/systemd` or `/lib/systemd`. All 20 scripts were
read; none mentions DirectFB.

`[READ]` The graphics path that *is* wired is X11: `S12splash:19` runs
`X :0 -nocursor -s 0 &`, `S43gui:11-13` starts three `xterm`s on `DISPLAY=:0`,
`S43gui:21` starts `las-frontend` on `DISPLAY=:0`, `S43gui:46` starts
`las-dwm`, and `S43gui:72` runs `xrandr -o inverted`.

### 7.3 Process sweep

`[READ]` `arch-harvest/runtime-state.txt`, `--- processes ---` section: the
graphics-related processes are `217 X :0 -nocursor -s 0`, `912/913/914 xterm`,
`915 las-frontend`, `1472 las-dwm`. No `dfbplay`, `dfbshow`, `dfbswitch`, or
any other DirectFB client. (Per `CAVEAT-runtime-state.md`, process
*enumeration* is one of the categories this capture's contamination could not
affect — the contamination added test synths and changed scsynth's block size,
not the graphics stack.)

### 7.4 Configuration sweep

`[READ]` No `directfbrc` anywhere on disk; no `DFBARGS` or `directfb` in any
environment file, profile, or `/etc` config.

### 7.5 Verdict

`[INFERRED]` **DirectFB on the Moog One is build-system residue.** It is not
live, and it is not a fallback the boot path can select — nothing in the boot
path contains a branch that could select it. The most economical explanation is
that a Buildroot package (most plausibly the SVG/cairo/tslib cluster, or a
default in the board `defconfig`) pulled `directfb` in as a dependency or an
enabled-by-default option, and it was never removed. `[UNKNOWN]` The actual
`defconfig` line that enables it — the Buildroot configuration is not in this
capture.

---

## 8. What `linux_input` would actually find

This is the part of the gap assignment's premise that the evidence overturns.

`[READ]` `libdirectfb_linux_input.so` string table:

| offset | string |
|---:|---|
| 18006 | `/org/kernel/udev/monitor` |
| 18083 | `/dev/input/event%d` |
| 18207 | `Linux Input Driver` |
| 18239 | `TSLIB_TSDEVICE` |
| 18298 | `/dev/tty0` |
| — | `no keymap support (requires /dev/tty0 - CONFIG_VT)` |
| — | `Linux/Input: Fail to open udev socket, disable detecting hotplug with Linux Input provider` |
| — | `DirectFB/linux_input: could not grab device` |

`[INFERRED]` The driver scans `/dev/input/event0…N` by `open()`+`ioctl()`,
optionally `EVIOCGRAB`s each one (`[no-]linux-input-grab`), and binds a netlink
socket to the udev monitor for hotplug.

**What is there to find:** `[READ]` `dmesg-before-reboot.txt:266`

```
[    1.306641] input: gpio-keys as /devices/soc0/gpio-keys/input/input0
```

That is the **only** `input:` registration line in the entire boot log.
`[READ]` The device tree `boot/imx6dl-profili-som.dtb` contains a `gpio-keys`
node with `linux,code`, `label`, and `gpio-key,wakeup` properties.

**What is not there:** `[READ]` `/etc/udev/rules.d/` contains five rules files
(`20-xmos-nic.rules`, `30-usb-nic.rules`, `40-usb-thumbdrive.rules`,
`50-eth-ext-nic.rules`) and three helper scripts — all network and storage.
None mentions `input`, `event`, or `graphics`.

**Where the panel actually is:** `[READ]` `usr/bin/las-frontpanel-poll`
(9,864 B) has `libc.so.6` as its only `DT_NEEDED` and its complete import list
is `socket, htonl, htons, perror, strncpy, puts, putchar, select, abort,
printf, strlen, memset, bind, inet_addr, memcpy, recvfrom, sendto, ntohl`. Its
string table contains `203.0.113.2`, `cannot create socket`, `bind failed`,
`sendto failed`, and an OSC type-tag decoder (`Error while reading OSC buffer:
%i`, `[%i bytes] %s %s`, ` false`, ` inf`, ` nil`, ` true`,
` Unknown format: '%c'`). `[READ]` `S43gui:21` launches `las-frontend` with
`--host-paneloutput=203.0.113.2 --host-oleds=203.0.113.2 --panel-state=…`.

`[INFERRED]` The front panel and keybed reach Linux as **OSC over UDP from the
XMOS**, not as evdev. This is consistent with the established architecture
("no MIDI byte from either port reaches Linux; DIN and USB MIDI both terminate
in XMOS firmware") and extends it: no *panel* byte reaches Linux as an input
event either.

`[INFERRED]` **DirectFB's `linux_input` driver, started today, would enumerate
exactly one device: `gpio-keys`.** It cannot serve as a second source on the
panel or keybed. `[UNKNOWN]` What keys `gpio-keys` actually carries — the
`linux,code` values are in the DTB but were not decoded here; see
[§16](#16-validation-plan-read-only).

### 8.1 The touchscreen node, and why it is not a second panel source

`[READ]` The DTB contains `ft5x06_ts@38` with `focaltech,display-coords` and
`focaltech,num-max-touches`, plus `ft5406_pins`. `[READ]` The boot log shows no
`ft5x06` probe line and no touchscreen `input:` registration. `[READ]` The
tslib input driver and `libts-1.0.so.0` are both installed.

`[INFERRED]` The i.MX6 SOM's device tree carries a FocalTech capacitive-touch
controller definition at I²C address 0x38 that does not come up on this
machine — either not populated on the Moog One's panel, or its node is
disabled. `[UNKNOWN]` Which. The boot log is captured with `quiet loglevel=0`
**[READ, `boot/cmdline.txt`]**, so absence of a probe message is weaker
evidence than it would otherwise be. This is the single most interesting
loose thread in this report; a live `ls /dev/input/` settles it.

---

## 9. What `fbdev` would actually do — and why running it is hazardous

`[READ]` The default device is `/dev/fb0`, from the option help at offset
897858 of `libdirectfb-1.7.so.7.0.0`:

```
  fbdev=<device>                 Open <device> instead of /dev/fb0
```

`[READ]` `/dev/fb0` also appears at offset 891527. `[READ]` The other device
paths in the library are `/dev/dri/card0`, `/dev/gpmdata`, `/dev/mouse`.

### 9.1 `/dev/fb0` belongs to X

`[READ]` `etc/X11/xorg.conf` lines 4–5 give the Vivante DDX both
`Option "fbdev" "/dev/fb0"` and `Option "vivante_fbdev" "/dev/fb0"`.
`[READ]` `S12splash:19` starts X before anything else touches the display.

`[INFERRED]` A DirectFB program launched with defaults would open the same
framebuffer X is scanning out of, and both would write it. `[READ]` The fbdev
module additionally calls `FBIOPUT_CON2FBMAP` (offset 42798) — it remaps which
framebuffer the console is bound to.

### 9.2 The fbdev backend performs a VT takeover

`[READ]` `libdirectfb_fbdev.so` string table:

| offset | string |
|---:|---|
| 42825 | `/dev/tty%d` |
| 42798 | `FBIOPUT_CON2FBMAP failed!` |
| 43108 | `KD_GRAPHICS failed!` |
| 43206 | `VT Switcher` |
| — | `DirectFB/core/vt: Couldn't open neither '/dev/tty%d' nor '/dev/vc/%d'!` |
| — | `DirectFB/fbdev/vt: K_MEDIUMRAW failed!` |
| — | `DirectFB/fbdev/vt: VT_SETMODE failed!` |
| — | `DirectFB/fbdev/vt: tcsetattr for new values failed!` |

`[READ]` It exports `dfb_vt_initialize`, `dfb_vt_switch`, `dfb_vt_detach`,
`dfb_vt_leave`, `dfb_vt_shutdown`, and spawns a thread named `vt_thread`.

`[INFERRED]` Starting a DirectFB fbdev program would: allocate or switch to a
VT; put the console keyboard into `K_MEDIUMRAW`; put the VT into
`KD_GRAPHICS`; install `VT_SETMODE` signal handlers; and change `tcsetattr`
terminal settings. On a machine whose only console is the serial port
(`console=ttymxc1,115200` **[READ, `boot/cmdline.txt`]**) and whose display is
already owned by X, this is a good way to lose the panel, the console, or both.
The relevant switches to defeat it are `[no-]vt`, `[no-]vt-switch`, and
`[no-]graphics-vt` **[READ, option table]**.

### 9.3 The framebuffer geometry it would inherit

`[READ]` `S12splash:14-16`:

```
14	    fbset --geometry 10 10 832 5022 32 --timings 54000 40 28 3 3 20 10 -vsync high -fb /dev/fb1
15	    fbset --geometry 832 480 832 5022 32 --timings 54000 40 28 3 3 20 10 -vsync high -fb /dev/fb1
16	    echo "U:832x480p-40" > /sys/class/graphics/fb1/mode
```

`[READ]` `S43gui:81`: `echo "U:10x10p-40" > /sys/class/graphics/fb1/mode`
— fb1 is shrunk back to 10×10 once the GUI is up, with the comment
`#set fb1 back to smaller size to avoid ipu overruns`.

`[READ]` `etc/X11/xorg.conf` Screen section: `Depth 24`, `Virtual 832 480`,
`Modes "800x480 LCD"`.

`[READ]` The device tree declares four framebuffer nodes `fb@0` … `fb@3` under
`fsl,mxc_sdc_fb`, plus `ldb@020e0008`, `lvds-channel@0`, `lvds-channel@1`,
`pwm-backlight`, and HDMI nodes. `[READ]` The boot log registers one:
`[0.418252] mxc_sdc_fb fb@2: registered mxc display driver lcd`, followed by
`[0.433059] Console: switching to colour frame buffer device 104x30`.

`[INFERRED]` With no `/etc/fb.modes` and no `mode=` option, DirectFB would take
whatever `FBIOGET_VSCREENINFO` reports at the moment it starts — meaning
832×480×32 on fb0, or 10×10 on fb1 after `S43gui` has run. `dfbswitch` exists
precisely to change that, and its `EnumVideoModes` call would have nothing to
enumerate from without a mode file.

The 832-vs-800 question is **already settled** in
`docs/firmware/gap-x11-display-and-build-residue.md` (headline: the visible
framebuffer is 832 wide, not 800 padded to 832). This report defers to it and
adds only the arithmetic in [§10](#10-a-side-result-the-splash-blobs-are-exact-fb1-images).

### 9.4 The other two `systems` backends

`[READ]` `libdirectfb_devmem.so` is driven by `video-phys=<hexaddress>`,
`video-length=<bytes>`, `mmio-phys=`, `mmio-length=`, `accelerator=<id>` — it
maps an arbitrary physical aperture out of `/dev/mem`.
`[READ]` `libdirectfb_dummy.so` is the null backend.

`[INFERRED]` `system=dummy` is the only way to initialise this stack on the
instrument without contending for a display or a VT. Anyone who wants to poke
at DirectFB here safely should use it.

`[READ]` The fbdev module also carries a complete AGP sub-driver
(`dfb_agp_initialize`, `/dev/agpgart`, `/dev/misc/agpgart`,
`/proc/bus/pci/%02x/%02x.%01x`, `DirectFB/FBDev/agp: …` messages). On an i.MX6
this is unreachable dead code inside dead code.

---

## 10. A side result: the splash blobs are exact fb1 images

Not DirectFB, but it fell out of the same directory read and it is checkable
arithmetic.

`[READ]` `/boot` contains, alongside the kernel and DTB:

| file | size | mtime |
|---|---:|---|
| `moog_logo.fb` | 16,713,216 | Mar 11 2025 |
| `moog_splash.fb` | 16,716,544 | Mar 11 2025 |
| `moog_splash.bmp` | 1,152,056 | Mar 11 2025 |
| `moog_splash_ver.bmp` | 1,152,138 | Sep 15 2025 |
| `moog_splash_version.bmp` | 1,536,138 | Mar 11 2025 |
| `moog_splash.bmp.gz` | 8,202 | Sep 15 2025 |
| `moog_splash_ver.bmp.gz` | 8,202 | Sep 15 2025 |

`[READ]` `S12splash:14-15` sets fb1's virtual geometry to `832 5022` at 32 bpp.

`[INFERRED]` `832 × 5022 × 4 = 16,713,216` — **exactly** `moog_logo.fb`.
`832 × 5023 × 4 = 16,716,544` — **exactly** `moog_splash.fb`, one scanline
larger. These are raw dumps of the entire fb1 virtual framebuffer, which is why
`S12splash:21` can `dd` one straight onto `/dev/fb1` with no conversion.

`[READ]` BMP headers, decoded from bytes 0–0x35:

| file | width | height | bpp | DIB header | compression |
|---|---:|---:|---:|---|---|
| `moog_splash.bmp` | 800 | 480 | 24 | 40 (BITMAPINFOHEADER) | 0 |
| `moog_splash_ver.bmp` | 800 | 480 | 24 | 124 (BITMAPV4HEADER) | 0 |
| `moog_splash_version.bmp` | 800 | 480 | 32 | 124 (BITMAPV4HEADER) | 3 (BI_BITFIELDS) |

`[INFERRED]` The BMP assets are **800** wide while the framebuffer they would
land on is **832** wide. Sizes corroborate the header fields exactly:
`800×480×3 + 138 = 1,152,138` and `800×480×4 + 138 = 1,536,138`.
`[READ]` `S12splash` references only `moog_splash.fb`; nothing in `/etc`,
`/usr/bin`, or `/usr/share` references any of the `.bmp` or `.bmp.gz` files.
`[UNKNOWN]` Whether the BMPs are stale authoring intermediates or are consumed
by U-Boot before Linux starts. `gap-x11-display-and-build-residue.md` owns this
territory; flagging it here rather than adjudicating it.

---

## 11. The four data files, decoded

### 11.1 `cursor.dat` — 6,400 bytes

`[READ]` First bytes: `fd fd fd e8 | e8 e8 e8 83 | d3 d3 d3 40 | d0 d0 d0 1e`.
`[READ]` `libdirectfb-1.7.so.7.0.0` at offsets 886505 and 886564 holds
`/usr/share/directfb-1.7.7/cursor.dat` and
`Core/WindowStack: '/usr/share/directfb-1.7.7/cursor.dat' could not be opened!`.

`[INFERRED]` `6400 = 40 × 40 × 4`: a 40×40 ARGB image in little-endian byte
order (B,G,R,A), giving pixel 0 = `#fdfdfd` at alpha 0xe8. This is the default
mouse cursor, and it is the **only** data file the library itself loads by
absolute path.

### 11.2 `cursor.png` — 16,032 bytes

`[READ]` IHDR: width `0x0000003f` = **63**, height **63**, bit depth 8, colour
type 6 (RGBA), followed by an `sRGB` chunk. `[READ]` Nothing in `/usr/lib` or
`/usr/bin` references the string `cursor.png`.

`[INFERRED]` A source asset shipped alongside the runtime `.dat`, unreferenced
by any code. Note it is 63×63 while `cursor.dat` is 40×40 — they are not the
same image at the same size.

### 11.3 `decker.dgiff` — 1,102,400 bytes, fully parsed

DirectFB's own pre-rendered glyph format. The parse below is `[READ]` in the
strong sense: the structure sizes were *validated* by walking the face chain,
which lands on byte 0x10d240 — **exactly** the file length — and by the
per-face accounting `40 + n_glyphs×32 + 16 + pitch×height` reproducing each
face's declared byte count.

Header: magic `DGIFF`, major 0, minor 0, flags 1, **16 faces**.

| face | pt size | ascender | descender | line height | max advance | glyphs | rows | pixelformat |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | 8 | 8 | −2 | 11 | 10 | 216 | 1 | `0x00118005` |
| 1 | 9 | 9 | −3 | 13 | 12 | 216 | 1 | " |
| 2 | 10 | 10 | −3 | 14 | 13 | 216 | 1 | " |
| 3 | 11 | 11 | −3 | 15 | 14 | 216 | 1 | " |
| 4 | 12 | 12 | −3 | 16 | 16 | 216 | 1 | " |
| 5 | 14 | 14 | −4 | 19 | 18 | 216 | 1 | " |
| 6 | 16 | 16 | −4 | 21 | 21 | 216 | 1 | " |
| 7 | 18 | 18 | −5 | 24 | 23 | 216 | 1 | " |
| 8 | 20 | 20 | −5 | 26 | 26 | 216 | 1 | " |
| 9 | 23 | 23 | −6 | 30 | 30 | 216 | 2 | " |
| 10 | 24 | 24 | −6 | 31 | 31 | 216 | 2 | " |
| 11 | 28 | 27 | −7 | 35 | 36 | 216 | 2 | " |
| 12 | 32 | 31 | −8 | 40 | 41 | 216 | 2 | " |
| 13 | 36 | 35 | −9 | 45 | 47 | 216 | 2 | " |
| 14 | 42 | 41 | −10 | 52 | 54 | 216 | 3 | " |
| 15 | 48 | 47 | −12 | 60 | 62 | 216 | 3 | " |

`[READ]` Every face carries the same 216 glyphs, code points **U+0020 to
U+2219** in strictly ascending order (the highest three are U+203A `›`,
U+2122 `™`, U+2219 `∙`).

`[READ]` Face 0's single glyph row declares width **815**, height **8**, pitch
**816**. `[INFERRED]` pitch/width = 1 byte per pixel, so pixelformat
`0x00118005` is an **8-bit alpha-only** format — DirectFB's `DSPF_A8`, the
natural output of an antialiased glyph rasteriser. This is derived from the
file's own arithmetic, not from memory of the DirectFB headers.

`[READ]` Glyph records are 32 bytes: `unicode, row, offset, width, height,
left, top, advance`. Verified by the offsets being the running sum of the
widths — U+0020 (w 0) at 0, U+0021 (w 1) at 0, U+0022 (w 3) at 1, U+0023 (w 5)
at 4, U+0024 at 9 — and by the last glyph ending at 814 + 1 = 815 = the row
width.

### 11.4 `decker.ttf` — 37,048 bytes

`[READ]` sfnt header `00 01 00 00`, 15 tables, first table tag `OS/2`, second
`PCLT`. `[READ]` Nothing in `/usr/lib` or `/usr/bin` references the string
`decker`.

`[INFERRED]` The TrueType source from which `decker.dgiff` was pre-rendered.
Both are inert here: DirectFB fonts are loaded by application-supplied
filename, and there is no application.

---

## 12. The configuration surface, in full

Recorded because it is the complete list of levers, and because no other report
carries it. All `[READ]`, from the option help tables compiled into the
libraries.

### 12.1 `libdirectfb` — valued options

`system=`, `fbdev=`, `busid=`, `mode=WxH`, `scaled=WxH`, `depth=`,
`pixelformat=`, `primary-id=`, `surface-shmpool-size=`,
`system-surface-base-alignment=`, `system-surface-pitch-alignment=`,
`session=`, `remote=host[:port]`, `primary-layer=`, `primary-only`,
`resource-id=`, `force-desktop`, `screen-frame-interval=` (default 16666 µs),
`max-frame-advance=` (default 100000 µs), `max-render-tasks=`, `font-format=`,
`block-all-signals`, `vt-num=`, `mouse-source=`, `mouse-protocol=`,
`linux-input-ir-only`, `cursor-resource-id=`, `wm=`, `init-layer=`,
`layer-size=`, `layer-format=`, `layer-depth=`, `layer-buffer-mode=`,
`layer-bg-none`, `layer-bg-color=`, `layer-bg-color-index=`,
`layer-bg-image=`, `layer-bg-tile=`, `layer-src-key=`, `layer-rotate=`,
`image-format=`, `flip-notify-max-latency=` (default 200 ms),
`videoram-limit=`, `agpmem-limit=`, `screenshot-dir=`, `video-phys=`,
`video-length=`, `mmio-phys=`, `mmio-length=`, `accelerator=`,
`font-resource-id=`, `resource-manager=`, `software-cores=`,
`matrox-tv-standard=`, `matrox-cable-type=`, `mut-device=`,
`zytronic-device=`, `elo-device=`, `penmount-device=`,
`linux-input-devices=`, `tslib-devices=`, `unichrome-revision=`,
`include=`, `max-font-rows=`, `max-font-row-width=`,
`graphics-state-call-limit=` (default 5000), `window-surface-policy=`,
`desktop-buffer-mode=`.

### 12.2 `libdirectfb` — boolean `[no-]` options

`ownership-check`, `banner`, `surface-sentinel`, `force-windowed`, `hardware`,
`software`, `software-warn`, `software-trace`, `always-indirect`,
`always-flush-callbuffer`, `layers-fps[=ms]`, `gfxcard-stats[=ms]`, `dma`,
`sync` (default no), `agp[=mode]`, `thrifty-surface-buffers`, `font-premult`,
`deinit-check`, `core-sighandler`, `vt-switch`, `vt-switching`, `graphics-vt`,
`vt`, `mouse-gpm-source`, `motion-compression`, `lefty`, `capslock-meta`,
`linux-input-grab`, `linux-input-force`, `cursor`, `cursor-automation`,
`cursor-updates`, `cursor-videoonly`, `layers-clear`, `surface-clear`,
`wm-fullscreen-updates`, `smooth-upscale`, `smooth-downscale`,
`translucent-windows`, `decorations`, `startstop`, `autoflip-window`,
`discard-repeat-events`, `gfx-emit-early`, `flip-notify`, `task-manager`
(default no), `force-frametime`, `matrox-sgram`, `matrox-crtc2`.

Plus the vsync forcing pair `vsync-after` / `vsync-none`.

### 12.3 `libdirect`

`memcpy=`, `debug-all`, `debug-none`, `log-file=`, `log-udp=host:port`,
`fatal-level=` (NONE / ASSERT / ASSUME, default ASSERT), `dont-catch=`,
`disable-module=`, `module-dir=`, `thread-priority-scale=`,
`default-interface-implementation=type/name`, `perf-dump-interval=`,
`log-delay-rand-loops=`, `log-delay-rand-us=`, `log-delay-min-loops=`,
`log-delay-min-us=`, `delay-trap-ms=`.

### 12.4 `libfusion`

`[no-]secure-fusion` (default yes), `tmpfs=<directory>`, `trace-ref=<hexid>`.

### 12.5 Core coupling notes

`[READ]` `DirectFB/Core: Option task-manager without secure-fusion is
unsupported!` and `DirectFB/Core: Forcing 'secure-fusion' option (requested by
system module)` — the fbdev system module can force `secure-fusion` on.
`[READ]` `DirectFB/Graphics: Acceleration disabled (by 'no-hardware')` exists
as a message; here acceleration is disabled by there being no driver at all.

---

## 13. If anyone ever runs this: the hazards

`[INFERRED]` in each case, from the `[READ]` evidence cited above.

1. **VT and console.** The fbdev backend takes a VT, sets `K_MEDIUMRAW` and
   `KD_GRAPHICS`, changes `tcsetattr`, and calls `FBIOPUT_CON2FBMAP`
   ([§9.2](#92-the-fbdev-backend-performs-a-vt-takeover)). The only console on
   this machine is `ttymxc1` at 115200. Use `no-vt`, `no-vt-switch`,
   `no-graphics-vt`.
2. **Display contention.** Default `/dev/fb0` is X's framebuffer
   ([§9.1](#91-devfb0-belongs-to-x)); X is running from `S12splash:19` onward
   and `las-frontend` and `las-dwm` are drawing on it.
3. **Audio.** The architecture as established has cpu1 isolated
   (`isolcpus=1`, **[READ, `boot/cmdline.txt`]**) carrying scsynth's
   `SCHED_FIFO 99` thread. `libdirect` offers `thread-priority-scale=` and
   `libdirectfb` offers `software-cores=<num>`; with no graphics driver, *all*
   rendering is Genefx on the CPU. A DirectFB program is a CPU-bound
   soft-real-time renderer competing on a two-core box.
4. **Nothing is idempotent.** `S43gui:81` deliberately shrinks fb1 to 10×10
   "to avoid ipu overruns"; `S12splash` deliberately sequences fbset, backlight,
   and alpha. A DirectFB mode set would walk over that state with no way to
   restore it, and `DirectFB/FBDev: Could not restore variable screen
   information!` is a real error string in the module **[READ]**.
5. **Safe path.** `system=dummy` initialises the whole stack with no display,
   no VT, and no input grab.

---

## 14. Conflicts with existing docs

Reported, not fixed, per the working rule.

1. **No contradiction found with `gap-x11-display-and-build-residue.md`.** It
   covers X11/Xorg/Vivante and `usr/share/examples`; it does not mention
   DirectFB. Its 832×480 conclusion is independently corroborated here by the
   `.fb` blob arithmetic in [§10](#10-a-side-result-the-splash-blobs-are-exact-fb1-images).

2. **No contradiction with `small-binaries.md`.** Its line 29 ("`las-fb-config`
   … `ioctl` on `/dev/fb1`; first arg is a no-op") and line 34 ("`psplash` …
   unreferenced anywhere … dead code") are both confirmed here from the
   linkage side: neither binary links DirectFB, and `las-fb-config`'s only
   `DT_NEEDED` is `libc.so.6`.

3. **Soft tension with `diff-files.md:136`, "DirectFB | 23".** Thirty DirectFB
   ELF files differ between 1.5.0 and 1.8.2 (23 modules + 4 core libraries +
   3 executables). Twenty-three is correct if and only if the bucket means the
   `/usr/lib/directfb-1.7-7` module tree, with `libdirectfb`/`libdirect`/
   `libfusion`/`lib++dfb` counted under "shared libraries (108)" and
   `dfbplay`/`dfbshow`/`dfbswitch` under "/usr/bin executables (119)". That
   reading is consistent, but the label is ambiguous. Not an error; a naming
   risk for anyone reading the table later.

4. **Correction to the gap assignment's own premise.** The brief infers that
   DirectFB's `linux_input` driver "enumerates the same evdev devices the panel
   and keybed present — so reading it would also document, from a second
   source, how the front panel appears to Linux." **This is wrong.** The panel
   and keybed present *no* evdev devices; the only one on the machine is
   `gpio-keys` ([§8](#8-what-linux_input-would-actually-find)). Recording this
   explicitly because the premise is plausible enough to be re-derived by the
   next reader.

5. **Correction to the gap assignment's inventory.** The brief lists
   `systems/libdirectfb_fbdev.so`, `inputdrivers/libdirectfb_linux_input.so`,
   `inputdrivers/libdirectfb_ps2mouse.so`, and the `IDirectFBFont` /
   `IDirectFBImageProvider` interface directories. The real module tree has
   **23** modules: it also includes `systems/{devmem,dummy}`,
   `inputdrivers/{tslib,keyboard,serialmouse}`, `wm/default`,
   `interfaces/IDirectFBVideoProvider`, `interfaces/IDirectFBWindows`,
   `interfaces/IWater`, and `interfaces/ICoreResourceManager`. The brief also
   omits `libdirect-1.7.so.7.0.0` and `libfusion-1.7.so.7.0.0`, which are part
   of the same stack but do not match a `*dfb*` glob.

---

## 15. What remains unknown

* `[UNKNOWN]` **Why DirectFB is in the image.** No Buildroot `defconfig` or
  package manifest is in the capture. The candidates — an explicit
  `BR2_PACKAGE_DIRECTFB`, or a reverse dependency of the `libsvg-cairo` /
  `tslib` cluster — cannot be distinguished from the rootfs alone.
* `[UNKNOWN]` **Whether the `ft5x06` touchscreen exists on the Moog One's
  panel.** Its DTB node is present; no probe line and no evdev node appear.
  `quiet loglevel=0` weakens the negative.
* `[UNKNOWN]` **What `gpio-keys` carries.** The `linux,code` properties are in
  `boot/imx6dl-profili-som.dtb` but were not decoded; that needs a DTB
  decompile, which is a clean offline job for a follow-up.
* `[UNKNOWN]` **How many `/dev/fb*` nodes actually exist at runtime.** The DTB
  declares `fb@0`–`fb@3`; the boot log registers `fb@2`; the scripts use fb0
  and fb1. `/dev` in the rootfs image is empty (devtmpfs) so this cannot be
  answered offline.
* `[UNKNOWN]` **Whether `moog_splash*.bmp` is consumed by U-Boot.** Only
  `moog_splash.fb` is referenced from Linux userspace.
* `[UNKNOWN]` **Whether DirectFB was ever used during development at Moog.**
  Nothing in the shipped image records that either way.

---

## 16. Validation plan (READ-ONLY)

Every command below is non-destructive and read-only. **Do not run
`las-fb-config`, `dfbshow`, `dfbplay`, `dfbswitch`, `fbset`, or any `las-*`
binary** — several ignore their arguments and act anyway. Nothing here writes
to `/dev/fb*`, `/sys`, or a VT.

1. **Confirm the stack is present and matches these hashes.**
   `md5sum /usr/lib/libdirectfb-1.7.so.7.0.0 /usr/lib/lib++dfb-1.7.so.7.0.0 /usr/lib/libdirect-1.7.so.7.0.0 /usr/lib/libfusion-1.7.so.7.0.0`
   → expect `65757a08…`, `94f6ba68…`, `2bf67104…`, `596c0f44…`.

2. **Confirm nothing is running it.**
   `ps w | grep -E 'dfb(show|play|switch)'` → expect no match.

3. **Confirm no process has the library mapped.**
   `grep -l directfb /proc/[0-9]*/maps 2>/dev/null` → expect no output.

4. **Confirm no config file was created at runtime.**
   `ls -l /etc/directfbrc /root/.directfbrc ~/.directfbrc 2>&1` → expect three
   "No such file".

5. **Settle the evdev question — the most valuable single command.**
   `ls -l /dev/input/ ; cat /proc/bus/input/devices`
   → the report predicts exactly one event device, `gpio-keys`. If a
   touchscreen or anything else appears, [§8](#8-what-linux_input-would-actually-find)
   needs revising.

6. **Enumerate the framebuffers that really exist.**
   `ls -l /dev/fb* ; ls /sys/class/graphics/`
   and, per framebuffer, `cat /sys/class/graphics/fb0/{name,virtual_size,stride,bits_per_pixel,mode}`
   (repeat for `fb1`; these sysfs attributes are reads, unlike the `echo >`
   writes in `S12splash`).

7. **Confirm the module tree is intact on the instrument.**
   `find /usr/lib/directfb-1.7-7 -type f | wc -l` → expect **23**;
   `ls /usr/lib/directfb-1.7-7/` → expect exactly
   `inputdrivers interfaces systems wm` and **no `gfxdrivers`**.

8. **Confirm the missing tools really are missing.**
   `ls /usr/bin/dfb* ; ls /usr/bin/directfb-csource /usr/bin/dfbdump /usr/bin/dfbinfo 2>&1`
   → expect the three `dfbplay/dfbshow/dfbswitch` and three "No such file".

9. **Confirm the fusion kernel module is absent.**
   `lsmod ; ls /dev/fusion* 2>&1` → expect an empty module list and "No such
   file".

10. **Confirm the boot scripts on the device match the ones read here.**
    `md5sum /etc/init.d/S12splash /etc/init.d/S43gui /etc/X11/xorg.conf`
    and compare against the same files in
    `captures/firmware-1.8.2/rootfs-1.8.2`.

11. **Offline, no instrument needed — decode `gpio-keys`.**
    `dtc -I dtb -O dts -o /tmp/moog.dts "captures/firmware-1.8.2/rootfs-1.8.2/boot/imx6dl-profili-som.dtb"`
    then read the `gpio-keys` and `ft5x06_ts@38` nodes, including whether the
    latter carries `status = "disabled"`.

---

## 17. Appendix A — module tree md5 manifest

Paths relative to `/usr/lib/directfb-1.7-7/`. All `-rwxr-xr-x`, `elf32-littlearm`,
Cortex-A9, stripped **[READ]**.

```
c4034df9089aad540b36fffb88db080d    9176  inputdrivers/libdirectfb_keyboard.so
b26cf6ec8ab2258526b4ea5875fd78bc   20444  inputdrivers/libdirectfb_linux_input.so
76ea018818c587f8a6019d6d3d8ef130    9960  inputdrivers/libdirectfb_ps2mouse.so
04c40a92d7cbe47ef94848da0550168e    9252  inputdrivers/libdirectfb_serialmouse.so
f05c778453422d6037b2c386c27d3dcf    7252  inputdrivers/libdirectfb_tslib.so
6d55020be217c289a48a2758f1750aa9    6588  interfaces/ICoreResourceManager/libicoreresourcemanager_test.so
c7f494dcf90b9a8a3da2682363c394b0    8188  interfaces/IDirectFBFont/libidirectfbfont_dgiff.so
823386334ca3cb97f9bc83d4f675eaa3   15704  interfaces/IDirectFBFont/libidirectfbfont_ft2.so
86310e33a47be81db8aa393df55d46d0    8928  interfaces/IDirectFBImageProvider/libidirectfbimageprovider_bmp.so
e361c2d881020dd797091f8abe06f286    6916  interfaces/IDirectFBImageProvider/libidirectfbimageprovider_dfiff.so
3ab10b744d2c13a4c5910e72c8abf7e7   11464  interfaces/IDirectFBImageProvider/libidirectfbimageprovider_gif.so
19d73369b2d98418352e206eb1f9b9a6   10712  interfaces/IDirectFBImageProvider/libidirectfbimageprovider_jpeg.so
2d6ced1eeafd1402f846eaca0a63020a   38728  interfaces/IDirectFBImageProvider/libidirectfbimageprovider_mpeg2.so
a2f2163d0bfb27e1e42f7ef8815a7314   13348  interfaces/IDirectFBImageProvider/libidirectfbimageprovider_png.so
535786dec585527ba4a7d8ad2aceaa07   11140  interfaces/IDirectFBImageProvider/libidirectfbimageprovider_pnm.so
decb378ef8676a58474a6e64908d06ab   10320  interfaces/IDirectFBImageProvider/libidirectfbimageprovider_svg.so
97781706dec5154102fe910da73b7092   14156  interfaces/IDirectFBVideoProvider/libidirectfbvideoprovider_gif.so
d5ee29a4779d94e9b18bba98e9e37a7d    6948  interfaces/IDirectFBWindows/libidirectfbwindows_default.so
ff28976eec49051e21ca2e1214d28406   51640  interfaces/IWater/libiwater_default.so
92a3526f7a70eb2c373faa7b689e3ca7   12292  systems/libdirectfb_devmem.so
40d27e4e03cc730ec0f475539b45f104    8668  systems/libdirectfb_dummy.so
868ad771b26864c63d9d289c3650b463   47428  systems/libdirectfb_fbdev.so
686c00f2b22094a591d3fe99c5218374   35976  wm/libdirectfbwm_default.so
```

## 18. Appendix B — byte offsets for the load-bearing strings

All offsets are decimal, into the 1.8.2 file named.

**`/usr/lib/libdirectfb-1.7.so.7.0.0`**

| offset | string |
|---:|---|
| 141530, 141643 | `las-ci-builds` (the two `DT_RPATH` copies) |
| 850313 | `   ~~~~~~~~~~~~~~~~~~~~~~~~~\| DirectFB 1.7.7 \|~~~~~~~~~~~~~~~~~~~~~~~~~~` |
| 868365 | `DirectFB/Core: %s Application Core. (2025-09-15 18:34) %s%s` |
| 868390 | `Single` |
| 886505, 886564 | `/usr/share/directfb-1.7.7/cursor.dat` |
| 891527, 897883 | `/dev/fb0` |
| 897433, 897448 | `directfbrc` |
| 897858 | `  fbdev=<device>                 Open <device> instead of /dev/fb0` |

**`/usr/lib/directfb-1.7-7/inputdrivers/libdirectfb_linux_input.so`**

| offset | string |
|---:|---|
| 18006 | `/org/kernel/udev/monitor` |
| 18083 | `/dev/input/event%d` |
| 18207 | `Linux Input Driver` |
| 18239 | `TSLIB_TSDEVICE` |
| 18298 | `/dev/tty0` |

**`/usr/lib/directfb-1.7-7/systems/libdirectfb_fbdev.so`**

| offset | string |
|---:|---|
| 41418 | `FBDev Primary Layer` |
| 42798 | `FBIOPUT_CON2FBMAP failed!` |
| 42825 | `/dev/tty%d` |
| 43108 | `KD_GRAPHICS failed!` |
| 43206 | `VT Switcher` |
