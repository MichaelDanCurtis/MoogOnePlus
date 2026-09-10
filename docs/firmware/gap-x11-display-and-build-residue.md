# The X11 / display / GPU configuration, and the build residue shipped with it

Firmware v1.8.2 (`captures/firmware-1.8.2/rootfs-1.8.2`), compared throughout
against v1.5.0 (`captures/rootfs-1.5.0`).

**Grading.** `[READ]` = quoted directly out of a file on local disk, with the path
and the line/offset. `[INFERRED]` = reasoning, with the evidence named.
`[UNKNOWN]` = not established. Nothing here was obtained from the instrument.
No Moog binary was executed; ARM binaries were read with `strings`, `xxd`, a
hand-written ELF/DTB/FDT parser, and `llvm-objdump -d --triple=armv7-none-linux-gnueabihf`.

**Headline.** The 832-pixel width that other reports have observed only at the
`fbset` level is not a stride, a pan, or an alignment artefact: the kernel's own
`CLAA-WVGA` panel entry reads **832×480 @ 41 Hz**, under a name that is standard
Freescale and beside an untouched stock neighbour, and that entry is
byte-identical in the v1.5.0 and v1.8.2 kernels. The entire X11/display/GPU
configuration is byte-identical between the two releases.

---

## 0. Summary of what is here

| | |
|---|---|
| Who starts X | `etc/init.d/S12splash:19`, as `X :0 -nocursor -s 0 &` — **not** `xinit`, **not** `startx` |
| Config it reads | `/etc/X11/xorg.conf`, by Xorg's compiled-in default search path |
| Real screen mode | 832×480×32 @ 41 Hz, from the **kernel's own `CLAA-WVGA` modedb entry** (not from `xorg.conf`) |
| Window manager | `las-dwm` (dwm 6.1), started by `S43gui:46` |
| Dead developer path | `xinitrc` → `startfluxbox` (absent); `default.sh` → `scide` (absent) |
| Dead GPU payload | 39 MB of Vivante/FSL samples, 44 executables, referenced by nothing |
| Dead DRI module | `usr/lib/dri/vivante_dri.so` exports the DRI1 entry point that this Mesa cannot call |
| Build residue | one Vim swap file naming a **second, undocumented source tree**; five `.gitignore` files; a malformed `/etc/git-tags` |
| v1.5.0 vs v1.8.2 | every file in this report is byte-identical except `boot/uImage`, which differs in **138 bytes** |

---

# Part I — The display

## 1. Who starts X, and when

`[READ]` `etc/init.d/S12splash` in full (45 lines; reproduced here because no
prior report quotes lines 14–21 together):

```
 9	    las-fb-config 1 0
10	    echo 0 > /sys/class/backlight/backlight/brightness
11	    echo 0 > /sys/class/graphics/fb0/blank
12	    echo 0 > /sys/class/graphics/fb1/blank
13	
14	    fbset --geometry 10 10 832 5022 32 --timings 54000 40 28 3 3 20 10 -vsync high -fb /dev/fb1
15	    fbset --geometry 832 480 832 5022 32 --timings 54000 40 28 3 3 20 10 -vsync high -fb /dev/fb1
16	    echo "U:832x480p-40" > /sys/class/graphics/fb1/mode
17	
18	    rm -f /tmp/.X0-lock
19	    X :0 -nocursor -s 0 &
20	
21	    dd if=/boot/moog_splash.fb of=/dev/fb1
22
23	    echo 99 > /sys/class/backlight/backlight/brightness
24	    
25	    for i in $(seq 255 $END); do
26		las-fb-config 1 $i; usleep 1000;
27	    done;
```

`[READ]` The X server is invoked bare: `X :0 -nocursor -s 0 &`. There is no
`-config`, no `-configdir`, no `-logfile`.

`[READ]` `usr/bin/X` is a symlink to `Xorg` (1,629,672 B, ARM EABI5, stripped).

`[READ]` `usr/bin/Xorg` contains its compiled-in config search path:

```
/etc/X11/%S,%P/etc/X11/%S,/etc/X11/%G,%P/etc/X11/%G,/etc/X11/%X,/etc/%X,
%P/etc/X11/%X.%H,%P/etc/X11/%X,%P/lib/X11/%X.%H,%P/lib/X11/%X
```

together with the literals `xorg.conf`, `xorg.conf.d`, and
`Using default xorg.conf search path.`

`[INFERRED]` `%X` expands to `xorg.conf`, so the fifth element of that path is
`/etc/X11/xorg.conf`. With no `-config` argument on the command line, that is
the file the server reads. Evidence: the search-path string and the absence of
any `-config` in `S12splash:19`.

`[READ]` `etc/init.d/rcS` is `for i in /etc/init.d/S??* ; do … $i start ; done`
with the comment "executing them in numerical order". `[READ]` `etc/inittab`
runs only `/etc/init.d/rcS` at `sysinit` plus a `getty` on the console — it has
no X entry at all.

`[INFERRED]` **X therefore starts very early, well before the GUI exists.**
Glob order puts `S12splash` (which starts X) ahead of `S25xmosfw`, `S40network`,
`S42sc` (`las-sc`) and `S43gui` (`las-frontend`, `las-dwm`). Evidence: the
numeric prefixes and `rcS`'s single sorted loop.

`[READ]` `usr/bin/startx` and `usr/bin/xinit` both exist but nothing in
`etc/init.d/`, `etc/inittab`, `bin/`, `sbin/`, `usr/bin/*` (scripts) or `var/`
invokes either. The only matches for `startx`/`xinit` outside `etc/X11/` are
inside `usr/bin/startx`'s own text.

`[INFERRED]` Therefore `/etc/X11/xinit/xinitrc` is never executed on this
device. Evidence: `xinitrc` is reached only via `xinit`, which nothing runs.

## 2. `etc/X11/xorg.conf`, read line by line

`[READ]` 1,085 bytes, mtime 2025-03-11, md5 `d9d746e442515007358815b7b825253f`.
Byte-identical in v1.5.0. Complete, with original line numbers:

```
 1	Section "Device"
 2	    Identifier  "i.MX Accelerated Framebuffer Device"
 3	    Driver      "vivante"
 4	    Option      "fbdev"  "/dev/fb0"
 5	    Option      "vivante_fbdev" "/dev/fb0"
 6	    Option      "HWcursor"  "false"
 7	     Option      "mode_settings" "false"
 8	#    Option 	"ShadowFB"  "false"
 9	#    Option 	"Rotate"    "UD"
10	     Option 	"debug"  "true"
11	#     Option      "AccelMethod"  "EXA"
12	#    Option      "SyncDraw" "false"
13	#    Option      "NoTearing"   "false"
14	EndSection
15	
16	Section "Monitor"
17		Identifier "LCD_Monitor"
18	#	HorizSync 20.0 - 30.0
19	#	VertRefresh 10.0 - 60.0
20	#	DisplaySize 212 127
21	#	Mode "800x480 LCD"
22	#		DotClock 27
23	#		HTimings 832 860 880 920
24	#		VTimings 480 483 493 496
25	#		Flags "-Hsync" "+Vsync"
26	#	EndMode
27	
28	EndSection
29	
30	Section "Screen"
31		Identifier "LCD"
32		Monitor "LCD_Monitor"
33		Device "i.MX Accelerated Framebuffer Device"
34		SubSection "Display"
35			Depth 24
36			Virtual 832 480
37			Modes "800x480 LCD"
38		EndSubSection
39	EndSection
40	
41	Section "ServerFlags"
42	    Option  "BlankTime"  "0"
43	    Option  "StandbyTime"  "0"
44	    Option  "SuspendTime"  "0"
45	    Option  "OffTime"  "0"
46	EndSection
```

Points not previously recorded anywhere in `docs/`:

* `[READ]` Line 5, `Option "vivante_fbdev" "/dev/fb0"`, is a **second** fbdev
  option alongside line 4. Both name `/dev/fb0`.
* `[READ]` Lines 7 and 10 are indented with a leading space before `Option`,
  where lines 4–6 are not. `[INFERRED]` hand editing: someone uncommented
  lines 7 and 10 from the commented block and left the comment character's
  column as whitespace. Evidence: the commented lines 8, 9, 11–13 have exactly
  the same `#` + 4-space shape, and removing the `#` leaves 5 leading columns.
* `[READ]` **The `Monitor` section is empty.** Every line except the
  `Identifier` is commented out. The `Mode "800x480 LCD"` block — lines 21–26 —
  is inside that comment.
* `[READ]` Line 37 selects `Modes "800x480 LCD"`, **a mode name that is not
  defined anywhere in this file**, because its only definition is the commented
  block at lines 21–26.
* `[READ]` `ServerFlags` zeroes all four DPMS/blanking timers, and
  `S12splash:19` additionally passes `-s 0`. `[INFERRED]` the screen-blank
  suppression is applied twice, by two independent mechanisms.

`[INFERRED]` Because the named mode does not exist, X cannot honour line 37 and
must fall back to the framebuffer's own current mode. Evidence for the fallback
mechanism is in the driver itself — see §4.

### The commented-out modeline is the same panel, faster

`[READ]` Lines 22–24 give `DotClock 27`, `HTimings 832 860 880 920`,
`VTimings 480 483 493 496`.

`[INFERRED]` Converting to porches: hfront = 860−832 = 28, hsync = 880−860 = 20,
hback = 920−880 = 40; vfront = 483−480 = 3, vsync = 493−483 = 10,
vback = 496−493 = 3.

`[READ]` `S12splash:15` passes `--timings 54000 40 28 3 3 20 10`, which in
`fbset` order is pixclock, left(hback), right(hfront), upper(vback),
lower(vfront), hslen, vslen = 40, 28, 3, 3, 20, 10.

`[INFERRED]` **All six porch values match exactly.** The commented xorg modeline
and the live `fbset` call describe the same panel geometry; they differ only in
dot clock — 27 MHz (→ 27e6/(920×496) = 59.2 Hz) versus 54000 ps = 18.52 MHz
(→ 40.6 Hz, which is where the `p-40` in the `U:832x480p-40` mode string comes
from). Evidence: the six-value match plus the two clock figures.

`[READ]` Note that the mode *named* `"800x480 LCD"` has `HTimings` beginning
**832**, not 800. The name and the geometry disagree in the file as shipped.

## 3. The real mode comes from the kernel, not from `xorg.conf`

This is the load-bearing new result, and it settles the 800-vs-832 question.

`[READ]` `boot/cmdline.txt` (117 B, identical in both releases):

```
setenv add_args isolcpus=1 quiet loglevel=0  galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1
```

`[READ]` There is **no `video=` argument**. `boot/cmdline.img` is the same string
wrapped in a u-boot image header (`Additional Kernel Args`).

`[INFERRED]` The framebuffer mode therefore comes from the device tree and the
kernel, not the command line.

`[READ]` `boot/imx6dl-profili-som.dtb` (42,345 B, **byte-identical in v1.5.0**),
parsed with a hand-written FDT reader:

```
/model      = "Variscite i.MX6 DL/Solo SOM-SOLO SOM-DUAL SoloCustomBoard"
/compatible = "fsl,imx6q-var-som", "fsl,imx6q"
/aliases/mxcfb0 = "/fb@0"   mxcfb1 = "/fb@1"   mxcfb2 = "/fb@2"   mxcfb3 = "/fb@3"
```

| node | `disp_dev` | `mode_str` | `interface_pix_fmt` | `default_bpp` | status |
|---|---|---|---|---|---|
| `fb@0` | `ldb` | — | `RGB24` | 24 | **disabled** |
| `fb@1` | `hdmi` | `1920x1080M@60` | `RGB24` | 24 | **disabled** |
| `fb@2` | **`lcd`** | **`CLAA-WVGA`** | `RGB24` | 24 | **okay** |
| `fb@3` | `ldb` | — | `RGB666` | 16 | **disabled** |

`[READ]` `hdmi_core@00120000`, `hdmi_video@020e0000`, `hdmi_audio@00120000` and
`hdmi_cec@00120000` are all `status = "disabled"`; so are `ldb@020e0008` and
both `lvds-channel@0` / `lvds-channel@1`.

`[READ]` `lvds-channel@0` carries two full `display-timings` sets, both named
`hsd100pxn1`, both `hactive = 800`, `vactive = 480`, at 30 MHz and 32 MHz.
Both are on a disabled node.

Now the kernel. `[READ]` `boot/uImage` is a u-boot image, `Linux-4.1.15-rt18`,
payload 5,060,392 B, containing a gzip stream at payload offset `0x4718` which
decompresses to 10,214,816 bytes. In that image:

`[READ]` the string `CLAA-WVGA\0` occurs exactly once, at file offset `0x856050`.
With the ARM text base `0x80008000` that is virtual address `0x8085e050`, and a
little-endian pointer to it occurs exactly once, at file offset `0x991488`.

`[READ]` Decoding the 56-byte `struct fb_videomode` at `0x991488`
(`const char *name` + 13 × `u32`):

```
name          "CLAA-WVGA"
refresh       41
xres          832          <-- the whole point: not 800
yres          480
pixclock      51313        ps  = 19.4882 MHz
left_margin   20
right_margin  60
upper_margin  10
lower_margin  10
hsync_len     20
vsync_len     10
sync          0x40000000   (FB_SYNC_CLK_LAT_FALL)
vmode         0
flag          0
```

`[INFERRED]` htotal = 832+20+60+20 = **932**; vtotal = 480+10+10+10 = **510**;
refresh = 19.4882e6 / (932 × 510) = **41.00 Hz**, which matches the `refresh`
field exactly. The internal consistency of the seven independent numbers is the
evidence that the struct offset and layout are right.

`[READ]` The immediately following entry in the same table is
`"SEIKO-WVGA"`, 60 Hz, **800**×480, pixclock 29850, left/right/upper/lower/hs/vs
= 89/164/23/10/10/10.

`[INFERRED]` **The table is the standard Freescale `lcd_modedb` and `CLAA-WVGA`
has been modified in place.** The evidence, all in-file: the entries carry stock
Freescale panel names; the neighbouring `SEIKO-WVGA` is an ordinary 800×480
WVGA entry; and `CLAA-WVGA` — a name whose panel family is 800×480 — is the one
entry in the table whose `xres` is not 800. `[UNKNOWN]` **How much** it was
changed. I did not have an upstream `mxc_lcdif.c` on disk to diff against, so the
*precise* delta from stock is unestablished; only the shipped values above are
`[READ]`. Do not quote a "stock was X" figure from this document — there isn't
one.

`[READ]` **The v1.5.0 kernel has the identical entry** — same string offset
`0x856050`, same pointer offset `0x991488`, same thirteen values.

### The three timing sets in one image

`[INFERRED]` The shipped image contains three different descriptions of the same
832×480 panel, and they do not agree:

| source | pixclock | htotal | vtotal | refresh | status |
|---|---|---|---|---|---|
| kernel `CLAA-WVGA` (`uImage`) | 19.488 MHz | 932 | 510 | 41.00 Hz | **live — this drives fb0** |
| `S12splash:14-15` `fbset` on fb1 | 18.518 MHz | 920 | 496 | 40.58 Hz | live, applied to the overlay |
| `xorg.conf:22-24` modeline | 27 MHz | 920 | 496 | 59.17 Hz | commented out |

`[UNKNOWN]` Why the overlay is given porches that differ from the background
plane's, and whether the mxc overlay path uses them at all. See §5 for the
reading that the `fbset`/`mode` writes on fb1 are being used to size the overlay
rather than to set timing.

### Confirmation from the instrument's own dmesg

`captures/dmesg-before-reboot.txt` is a previously captured log, not a live read.

`[READ]` line 139: `mxc_sdc_fb fb@2: registered mxc display driver lcd` — and no
other `mxc_sdc_fb` registration line. `[INFERRED]` only one display node
probes, consistent with the DTB table above.

`[READ]` line 140: `Console: switching to colour frame buffer device 104x30`.

`[INFERRED]` **832 × 480.** 104 columns × 8 px = 832 and 30 rows × 16 px = 480,
i.e. the standard 8×16 console font. Evidence: both dimensions divide exactly,
and no other common font size (8×8 would give 60 rows) fits. This is independent
confirmation, from the running instrument, that the visible framebuffer is 832
pixels wide — not 800 padded to 832.

`[READ]` line 21 of the same log shows the command line as
`console=ttymxc1,115200{smp} root=/dev/mmcblk2p3 rootwait isolcpus=1 quiet loglevel=0 galcore.contiguousSize=67108864 gpumem=128M dmfc=3 nohz=off skew_tick=1`
— `boot/cmdline.txt`'s `add_args` with the u-boot-supplied console/root prefix.

`[READ]` line 105: `imx-ipuv3 2400000.ipu: IPU DMFC CUSTOM MOOG HIGH RESOLUTION: 5B(0~3), 5F(4~7)`.

`[READ]` The kernel image contains three sibling strings at file offset
`0x88cb60`ff:

```
IPU DMFC DP HIGH RESOLUTION: 1(0,1), 5B(2~5), 5F(6,7)
IPU DMFC CUSTOM MOOG HIGH RESOLUTION: 5B(0~3), 5F(4~7)
IPU DMFC NORMAL mode: 1(0~1), 5B(4,5), 5F(6,7)
```

`[INFERRED]` `dmfc=3` on the command line selects the middle one. Evidence: it
is the branch the instrument's dmesg actually printed, with that command line.
The `CUSTOM MOOG` wording is a Moog-authored kernel modification, giving a
second independent Moog patch in the display path alongside `CLAA-WVGA`.

`[READ]` line 237–238: `galcore: clk_get vg clock failed, disable vg!` and
`Galcore version 5.0.11.41671`. `[INFERRED]` the GPU's vector-graphics core is
not brought up on this SoC.

`[READ]` line 331: `[12844.843490] imx-ipuv3 2400000.ipu: IPU Warning - IPU_INT_STAT_10 = 0x00080000`,
i.e. an IPU fault ~3.5 hours into a run, long after boot. See §5.

## 4. What the X server actually does with all this

`[READ]` `usr/lib/xorg/modules/drivers/` contains exactly three drivers:
`vivante_drv.so`, `fbdev_drv.so`, `modesetting_drv.so`. Input: `evdev_drv.so`,
`kbd_drv.so`. Extensions: `libglx.so`. Plus `libexa`, `libfb`, `libfbdevhw`,
`libint10`, `libshadow`, `libshadowfb`, `libvbe`, `libvgahw`, `libwfb`.

`[READ]` `vivante_drv.so` contains, among others:

```
FBDevPreInit: adjust display width %d
fbdevHWGetBuildinMode
Shadow buffer enabled, 2D GPU acceleration disabled.
"%s" is not a valid value for Option "Rotate"
VivanteGC2100   VivanteGC500   VivanteGCCORE
[dri] vivante.o kernel module version is %d.%d.%d but version 1.0.x is needed.
```

`[READ]` Resolving the PC-relative string references at each `fopen64` call
site in `vivante_drv.so` (via `llvm-objdump` plus literal-pool arithmetic;
`add rX, pc, rX` at address A with literal L gives target `A + 8 + *L`):

| call site | path | mode |
|---|---|---|
| `0x7dbc` | `/proc/cpuinfo` | `r` |
| `0xacec` | **`/home/linaro/share/exa_log.txt`** | **`w`** |
| `0xc444` | `/sys/class/graphics/%s/modes` (via `sprintf` at `0xc434`) | `r` |
| `0xcbb4` | `/sys/class/graphics/%s/mode` (via `sprintf` at `0xcba4`) | `r` |
| `0xcd7c` | `/sys/class/graphics/%s/modes` (via `sprintf` at `0xcd6c`) | `r` |

`[INFERRED]` **This is the mechanism by which X ends up at 832×480 despite
`xorg.conf` naming an undefined mode.** The driver reads the framebuffer's mode
directly from `/sys/class/graphics/<fb>/mode` and `/modes` — i.e. from the
kernel's `CLAA-WVGA` entry — rather than from a modeline. Evidence: the three
sysfs `fopen64` sites, the `fbdevHWGetBuildinMode` import, and the empty
`Monitor` section.

### The stray vendor debug path

`[READ]` `xorg.conf:10` sets `Option "debug" "true"`, and `debug` appears as a
literal in `vivante_drv.so`'s option table.

`[READ]` The `0xacec` site opens `/home/linaro/share/exa_log.txt` for writing,
caching the `FILE*` in a global that resolves to `0x1f174`, and returns early if
that global is already non-NULL (`ldr r3,[r4]; cmp r3,#0; popne {r4,pc}` at
`0xacd0`–`0xacd8`) — an open-once singleton.

`[READ]` `/home` in this rootfs is a symlink to `/var/local/home`, and
`var/local` does not exist in the rootfs at all.

`[READ]` The two functions that consume that global (at `0xad38` and `0xad98`)
each begin by loading it and returning immediately if it is zero
(`cmp r6,#0; popeq` at `0xad4c`–`0xad50`; `cmp r3,#0; beq 0xadd4` at
`0xadac`–`0xadb0`).

`[INFERRED]` The hardcoded `linaro` path is dead on this device — `/home/linaro`
almost certainly does not exist — but it is **harmless**, because every writer
NULL-checks the cached handle before use. No crash, no log, no disk churn.
`[UNKNOWN]` whether the opener at `0xacc4` is reached at all: no `bl 0xacc4`
appears anywhere in the disassembly, and the library is stripped of local
symbols, so it is either called through a pointer or is dead code.

`[INFERRED]` `linaro` is the Vivante/Linaro vendor build user, not a Moog one —
it is the only `/home/...` path in the X11 or GPU binaries other than the Moog
CI root (§13).

## 5. Two planes: how the splash and X share the screen

`[INFERRED]` `/dev/fb0` is the background plane of the single enabled display
and `/dev/fb1` is the IPU overlay on that same display. Evidence, all `[READ]`:
only `fb@2` probes (dmesg line 139) yet the scripts drive both `fb0` and `fb1`;
`S12splash` unblanks both (lines 11–12) but sets geometry only on `fb1`;
`xorg.conf` binds X to `fb0` while the splash is `dd`'d to `fb1`; and the two are
composited by a global-alpha call, below.

### `las-fb-config`, decoded

`[READ]` `usr/bin/las-fb-config`, 3,804 B, ARM EABI5, stripped, links only
`libc`. Its usage string:

```
Usage: %s framebuffer [0,1] [ alpha_val[0-255] ] 
```

and the literals `/dev/fb%s`, `/dev/fb1`, `open %s: %s`, `ioctl`.

`[READ]` Disassembling `main` at `0x10640`: it `sprintf`s `argv[1]` into
`/dev/fb%s`, `open`s it `O_RDWR`, stores the constant `1` at `[r11,#-0x18]`,
stores `atoi(argv[2])` at `[r11,#-0x14]`, and issues one ioctl with

```
10744: e3041621   movw r1, #0x4621
10748: e3441008   movt r1, #0x4008      ; r1 = 0x40084621
10750: bl 0x10470 <ioctl@plt>
```

`[INFERRED]` `0x40084621` decodes as `_IOW('F', 0x21, 8)`: direction bits
`0x40>>30 = 1` = write, size `(x>>16)&0x3fff = 8`, type `(x>>8)&0xff = 0x46 = 'F'`,
nr `0x21`. The 8-byte argument is `{ int enable; int alpha; }` at `r11-0x18`
and `r11-0x14`. `[INFERRED]` This is the Freescale `MXCFB_SET_GBL_ALPHA` on the
overlay: enable is hardcoded to 1 and alpha is `argv[2]`.

`[INFERRED]` A latent defect: the argument check at `0x10658` is
`cmp r3,#1 / bgt`, i.e. it only requires `argc > 1`, but `0x10720`–`0x10730`
then loads `argv[2]` unconditionally and passes it to `atoi`. Invoking
`las-fb-config 1` with no alpha passes `NULL` to `atoi` and faults. Both callers
in the shipped scripts always pass two arguments, so this is never hit in the
boot path.

### The boot sequence as a compositing operation

`[INFERRED]`, from `S12splash` and `S43gui` read together:

1. `S12splash:9` sets overlay alpha to 0 — fb1 present but fully transparent.
2. `:10` backlight to 0; `:11-12` unblank both planes.
3. `:14-15` two `fbset` calls on fb1: first 10×10 visible, then 832×480 visible,
   both with virtual 832×5022 at 32 bpp. `[UNKNOWN]` why two calls; the
   plausible readings are forcing a buffer reallocation at the larger virtual
   size before opening the visible window, or avoiding a large IPU fetch during
   the resize.
4. `:18-19` remove a stale `.X0-lock` and start X, which comes up on fb0 —
   invisible, because the backlight is off and the opaque-capable overlay is
   above it.
5. `:21` `dd` the splash raster into fb1. Still invisible: alpha is 0.
6. `:23` backlight to 99.
7. `:25-27` ramp the overlay alpha up. `[INFERRED]` `$END` is unset, so
   `seq 255 $END` is `seq 255` = 1…255; with `usleep 1000` per step the splash
   fades in over roughly a quarter-second plus process overhead.

Then `S43gui`, `[READ]` lines 64–81:

```
64	#save brightness config to file for correct bring up
65	cat /sys/class/backlight/backlight/brightness > /var/lcd_brightness
67	#bring brightness/opacity down for final transition
68	echo 0 > /sys/class/backlight/backlight/brightness
69	las-fb-config 1 0
71	#invert using GPU and wait a bit for it to take effect to avoid a visible flip
72	DISPLAY=:0 xrandr -o inverted
73	usleep 1000000
78	cat /var/lcd_brightness  > /sys/class/backlight/backlight/brightness
80	#set fb1 back to smaller size to avoid ipu overruns
81	echo "U:10x10p-40" > /sys/class/graphics/fb1/mode
```

`[INFERRED]` the handover is: black the panel, drop the overlay to alpha 0
(revealing X), rotate 180°, wait a full second for the rotation to land, restore
the saved brightness, then shrink the overlay to 10×10 so it stops consuming IPU
bandwidth. The comment on line 71 — "to avoid a visible flip" — and the 1 s
sleep say the rotation is not atomic.

`[INFERRED]` **The panel is physically mounted upside down.** Evidence:
`xrandr -o inverted` on line 72 is unconditional and permanent, and
`xorg.conf:9` carries a commented-out `Option "Rotate" "UD"` — a first,
abandoned attempt at the same correction in the driver instead of the RandR
layer.

`[INFERRED]` Line 81 uses the sysfs `mode` string as a **sizing** control, not a
timing control: `U:10x10p-40` is not a video mode any panel could display, and
the comment says "set fb1 back to smaller size". This retroactively explains
line 16 of `S12splash` (`U:832x480p-40`) as sizing the overlay to full screen.

`[INFERRED]` The "ipu overruns" the comment guards against are real and observed:
`dmesg-before-reboot.txt:331` records `IPU_INT_STAT_10 = 0x00080000` at
t≈12,845 s. `[UNKNOWN]` whether that particular fault was caused by overlay
bandwidth; the connection is the comment's own claim plus the warning's
existence, not a proven causal chain.

## 6. The splash rasters

`[READ]` `boot/` contents and sizes (all byte-identical in v1.5.0 except
`uImage` and the two `.bmp.gz`):

| file | bytes | |
|---|---|---|
| `moog_logo.fb` | 16,713,216 | = 832 × **5022** × 4, exactly the fb1 virtual geometry |
| `moog_splash.fb` | 16,716,544 | = 832 × **5023** × 4, exactly one row larger |
| `moog_splash.bmp` | 1,152,056 | 800×480, 24 bpp, 40-byte DIB header |
| `moog_splash_ver.bmp` | 1,152,138 | 800×480, 24 bpp, 124-byte (V5) DIB header |
| `moog_splash_version.bmp` | 1,536,138 | 800×480, **32 bpp**, V5 header, `comp=3` (BI_BITFIELDS) |
| `moog_splash.bmp.gz`, `moog_splash_ver.bmp.gz` | 8,202 / 8,202 | v1.5.0 has 8,171 / 8,171 |

`[INFERRED]` `moog_splash.fb` is one scanline (3,328 B) longer than the
framebuffer it is `dd`'d into. `[READ]` that trailing row is entirely zero.
`[INFERRED]` the `dd` at `S12splash:21` therefore short-writes with ENOSPC after
delivering the full image; the excess is blank padding and the splash is
unaffected.

`[READ]` Scanning both `.fb` files at 832 px × 4 B stride, the non-blank rows fall
in exactly two bands in each file:

```
moog_splash.fb   CONTENT rows     0- 479   blank 480-2510
                 CONTENT rows  2511-2990   blank 2991-5022
moog_logo.fb     identical band structure
```

`[INFERRED]` 2511 = 5022 / 2 exactly. The 832×5022 virtual buffer is **two pages
of 2511 rows**, each holding one 480-row image at its head; panning `yoffset`
between 0 and 2511 flips between them. `[READ]` The two pages hold *different*
images (differing md5), in both files, so this is a genuine two-image buffer and
not a duplicated double-buffer.

`[READ]` In every content row of both files, the leftmost non-zero column is
**16** and the rightmost is **815**.

`[INFERRED]` 815 − 16 + 1 = **800**. The artwork is exactly 800 pixels wide,
centred in the 832-pixel framebuffer with a 16-pixel black margin on each side —
which is also why all three `.bmp` sources are 800×480. `[UNKNOWN]` whether the
panel's physical active area is 800 or 832 columns, i.e. whether those 16-pixel
margins are visible to the player or fall outside the glass. The kernel scans
out 832 (§3) and the console occupies all 832 (§3), but the shipped artwork
commits to only the middle 800.

---

# Part II — The developer desktop that does not run

## 7. `xinitrc` and the missing window manager

`[READ]` `etc/X11/xinit/xinitrc`, 764 B, md5 `21b833f6da8204bc32a6e881d53de87d`,
byte-identical in v1.5.0. It is the stock X.Org `xinitrc` — merges
`.Xresources`/`.Xmodmap`, sources `xinitrc.d/?*.sh` — with the usual
`twm`/`xclock`/`xterm` block commented out at lines 52–56, and ends:

```
58	exec startfluxbox
```

`[READ]` **No `startfluxbox` and no `fluxbox` binary exists anywhere in the
rootfs.** (`find` across the whole tree returns nothing for either name.)

`[INFERRED]` This line could not succeed even if `xinitrc` were reached. Combined
with §1 — nothing runs `xinit` or `startx` — the file is doubly dead: never
invoked, and terminating in a call to an absent binary.

`[INFERRED]` `startfluxbox` is what the developer desktop used *before*
`las-dwm` existed. Evidence: `las-dwm` is a Moog-versioned component
(`/etc/git-tags`: `"LAS_DWM_GIT_TAG" : "v0.3.0"`) started explicitly by
`S43gui:46`, on a path that bypasses `xinitrc` entirely; the `xinitrc` was left
at its earlier terminus and its package dropped from the build.

## 8. `xinitrc.d/default.sh`

`[READ]` `etc/X11/xinit/xinitrc.d/default.sh`, 142 B, mode 0755, md5
`6690f58c6e7d5b3182fc7a430fe20268`, byte-identical in v1.5.0, in full:

```
1	xterm &
2	scide &
3	#Below is somewhat of a hack. Kernel doesn't want to see HDMI as primary and unblank
4	echo 0 > /sys/class/graphics/fb0/blank
5	
6	
```

Three separate findings:

**(a) `scide` is absent.** `[READ]` No `scide` binary exists anywhere in the
rootfs. `[READ]` `usr/bin/sclang` and `usr/bin/scsynth` *do* exist. `[INFERRED]`
the SuperCollider **IDE** was dropped from the build while the language and
server — which `las-sc` depends on — were kept. This is the only reference to
`scide` in the whole image.

**(b) The HDMI comment describes hardware this device tree switches off.**
`[READ]` The comment is a first-person engineer's note about HDMI being seen as
primary. `[READ]` In the shipping DTB, `fb@1` — the `hdmi` node, with
`mode_str = "1920x1080M@60"` — is `status = "disabled"`, as are `hdmi_core`,
`hdmi_video`, `hdmi_audio` and `hdmi_cec` (§3). `[INFERRED]` the comment is a
survival from a development configuration (or a Variscite reference board) in
which HDMI *was* enabled and did claim `fb0`; on the shipping device it cannot
apply, because only `fb@2` probes.

**(c) The "hack" survived into the production path.** `[READ]` `default.sh:4` is
`echo 0 > /sys/class/graphics/fb0/blank`. `[READ]` `S12splash:11-12` is
`echo 0 > /sys/class/graphics/fb0/blank` followed by the same for `fb1`.
`[INFERRED]` the unblank workaround was copied out of the dead developer script
into the live boot script and extended to cover the overlay — so the *technique*
ships even though the file it is written in does not run.

## 9. The X developer surface that *does* run

The desktop path is dead, but X terminals are not.

`[READ]` `S43gui:11-13` starts **three** xterms on every boot:

```
DISPLAY=:0 xterm -name xterm1 -fn 10x20 -fg white -bg black  -b 50 &
DISPLAY=:0 xterm -name xterm2 ...
DISPLAY=:0 xterm -name xterm3 ...
```

`[READ]` `usr/bin/las-dwm`, 61,272 B, ARM EABI5, stripped, identifies itself as
`dwm-6.1` and contains the literals `xterm1` … `xterm6`, `/var/las-dwm.cookie`,
`alt+1` … `alt+4`, and the corresponding
`DISPLAY=:0 xdotool key "alt+1"` … `"alt+4"` command strings, plus
`killall las-frontend`.

`[INFERRED]` `las-dwm` names up to six xterm slots and four dwm tags; the shipped
boot fills three of them.

`[READ]` `usr/bin/detect-held-buttons`, started by `S43gui:76`, in full:

```
 3	while true; do
 4	ping vc -c1 -q
 5	if [ $? -eq 0 ]; then
 8	        button_pressed=`las-frontpanel-poll /cb`
11	                if [ $button_pressed = 48 ]; then
12	                        echo HOME+SETTINGS pressed at startup, launching service mode.
13				sleep 5
14				killall las-watchdog 
15	                        killall las-frontend
16	                        killall `pidof las-sc`
17				killall xterm
19				DISPLAY=:0 xterm -name xterm1 -fn 10x20 -fg white -bg black  -b 50  -hold -e 'lassvc -t vc:7770 -p vc:9100' &
20				DISPLAY=:0 xdotool key "alt+2"
```

`[INFERRED]` **The X developer surface is reachable on production hardware by a
front-panel chord.** Holding HOME+SETTINGS at boot (`/cb` == 48) tears down the
watchdog, the front end and the audio engine, replaces the xterms with one
running `lassvc`, and switches `las-dwm` to tag 2 via `xdotool`. `[INFERRED]`
the ordinary boot therefore leaves the three xterms parked on a tag the player
never sees, and this chord is what surfaces them. (`detect-held-buttons` and
`lassvc` are already covered in `firmware/lassvc.md` and elsewhere; the X-side
reading — dwm tags, xterm slots, `xdotool` — is what is new here.)

## 10. `etc/drirc`

`[READ]` 3,980 B, byte-identical in v1.5.0. `[READ]` It is the **stock upstream
Mesa `drirc`**, containing nothing but application workarounds for Unigine
Sanctuary/Tropics/Heaven/Valley/OilRush, Savage 2, Topogun, Dead Island and
Second Life, plus the header comment `TODO: document the other workarounds.`

`[INFERRED]` Zero Moog content, zero relevance to this device — none of those
applications exists in the image. It is packaging default. Recorded here so
that nobody reads it again.

## 11. `usr/share/examples` — 39 MB of GPU demos

`[READ]` 39 MB across 157 files and 15 directories, in a rootfs whose total is
488 MB — i.e. **8.0 % of the image**. Byte-identical tree in v1.5.0
(`diff -rq` reports no differences).

`[READ]` Layout:

```
fsl-samples/g2d/{g2d_test, multiblit/, overlay_test/}
viv_samples/cl11/{UnitTest/{clinfo,loadstore,math,threadwalker,test_vivante/*}, fft/}
viv_samples/es20/vv_launcher/
viv_samples/tiger/
viv_samples/vdk/{tutorial1-7, tutorial1-7_es20, cover_flow, samples_es20/vdksample1-10_es20, …}
```

`[READ]` By `file`: **43 ARM EABI5 dynamically-linked executables** plus one
POSIX shell script — 44 files with the execute bit — and the rest textures and
meshes: 14 Targa images (including a 1920×720 RGBA `background.tga`, 5.5 MB),
13 Windows BMPs (six 1 MB `Mars_*_MIPMAP_LEVEL_0.bmp` cube faces), 9 `.pkm`
ETC textures, a 2 MB `.dds`, `.gsd` models, and ~4 MB of ASCII vertex/index
tables (`terrain_triangles.txt` alone is 1,037,600 B).

`[READ]` **Nothing in the rootfs references any of it.** A content search for
`viv_samples`, `share/examples`, `fsl-samples` and `vv_launcher` across all 488 MB
returns exactly one hit, and it is inside the sample tree itself:
`viv_samples/es20/vv_launcher/cover_flow.sh`.

`[READ]` That script, in full:

```
1	#!/bin/sh
2	# script to launch application for vv_launcher
5	echo run cover_flow
6	SDK_ROOT=
8	cd ../../..
9	SDK_ROOT=`pwd`
10	export LD_LIBRARY_PATH=$SDK_ROOT/drivers
12	cd $SDK_ROOT/samples/vdk
13	./cover_flow
14	cd $SDK_ROOT/samples/es20/vv_launcher
```

`[INFERRED]` It cannot work where it sits. From
`usr/share/examples/viv_samples/es20/vv_launcher`, `cd ../../..` lands in
`usr/share/examples`, and the script then expects `./drivers` and `./samples/vdk`.
`[READ]` `usr/share/examples` contains only `fsl-samples` and `viv_samples` —
no `drivers`, no `samples`. `[INFERRED]` the Vivante SDK's original directory
layout (`<sdk>/drivers`, `<sdk>/samples/...`) was flattened when the package was
integrated, and the launcher script was not adjusted.

`[INFERRED]` The whole tree is unreferenced vendor SDK payload — the largest
single block of dead weight found in the image, and the easiest 39 MB to
reclaim. `[UNKNOWN]` whether any of the 43 binaries would run correctly against
the shipped `libGAL`/`libVIVANTE`; they were not executed and must not be
(§ ground rules — several are calibration-agnostic GPU tests, but they are ARM
binaries and this is a real instrument).

## 12. The GL / DRI stack, and one module that cannot load

`[READ]` `usr/lib/` carries **two parallel GL stacks**.

Vivante's proprietary one, each in an X11 and a raw-framebuffer flavour:

```
libGAL-x11.so (928,540)      libGAL.fb.so (899,544)       libGAL.so     -> libGAL-x11.so
libVIVANTE-x11.so (4,058,316) libVIVANTE.fb.so (4,029,932) libVIVANTE.so -> libVIVANTE-x11.so
libEGL-x11.so (93,592)       libEGL.so/.1/.1.0            -> libEGL-x11.so
libGLESv2-x11.so (882,124)   libGLESv2.so/.2/.2.0.0      -> libGLESv2-x11.so
libGLES_CL, libGLES_CM, libGLESv1_CL, libGLESv1_CM, libOpenVG{,.2d,.3d}
libVivanteOpenCL.so, libCLC.so (3,062,116), libGLSLC.so
```

`[INFERRED]` Every `.so` symlink points at the **`-x11`** variant, so the whole
EGL/GLES/OpenVG stack is bound to the X11 backend. The `.fb` variants — nearly
5 MB of direct-framebuffer GL — are shipped but unreferenced by any symlink.

And Mesa's:

```
libGL.so.1.2.0 (486,432)   <- libGL.so, libGL.so.1
libGL.so.1.2   (314,492)   <- nothing points at it
libglapi.so.0.0.0, libdrm.so.2.4.0
usr/lib/dri/swrast_dri.so  (2,762,780)
usr/lib/dri/vivante_dri.so (1,056,344)
```

`[READ]` `swrast_dri.so` contains the version string `Mesa 11.1.1`.

`[READ]` `libGL.so.1.2.0` contains `/usr/lib/dri`, the format `%.*s/%s_dri.so`,
the error `unable to load driver: %s_dri.so`, and the two entry-point names it
looks up: `__driDriverGetExtensions` and `__driDriverExtensions`.

`[READ]` Parsing `.dynsym` for defined symbols:

| module | defined dynamic symbols | `__dri*` exports |
|---|---|---|
| `swrast_dri.so` | 11 | `__driDriverExtensions`, `__driDriverGetExtensions_swrast` |
| `vivante_dri.so` | **2** | **`__driCreateNewScreen`** (plus `VERSION`) |

`[INFERRED]` **`vivante_dri.so` cannot be loaded by the `libGL` shipped beside
it.** It exports `__driCreateNewScreen` — the old DRI1 screen constructor —
and exports neither of the two symbols `libGL.so.1.2.0` actually looks up.
1,056,344 bytes of driver that this stack has no way to reach. Evidence is
entirely in-image: the loader's own two symbol strings versus the module's own
two exported symbols. `[READ]` It is byte-identical in v1.5.0, whereas
`swrast_dri.so` differs between the releases.

`[READ]` `usr/lib/xorg/modules/extensions/libglx.so` exports/imports
`__glXDRISWRastProvider`, `DRI2Connect`, `DRI2GetBuffers`, `DRI2SwapBuffers`.
`[UNKNOWN]` whether GLX is ever initialised on this server — `xorg.conf` loads
no `Module` section at all, and nothing in the boot path runs a GL client.

`[READ]` `dmesg-before-reboot.txt:151`: `[drm] Initialized vivante 1.0.0 20120216 on minor 0`.
`[INFERRED]` a `vivante` DRM node does come up, and its `1.0.0` version matches
the `vivante_drv.so` string `[dri] vivante.o kernel module version is %d.%d.%d
but version 1.0.x is needed` — so the *X driver's* DRI path has a live kernel
counterpart even though the *Mesa* `vivante_dri.so` does not.

---

# Part III — The build residue

## 13. The Vim swap file: a second source tree

`[READ]` `etc/udev/rules.d/.sort-part.sh.swp`, 12,288 B, mtime 2025-03-11.
**Byte-identical in v1.5.0** (where its mtime is 2021-11-15).

`[READ]` Decoding Vim's `block0` (page 0 of 3, page size 4,096):

| field | offset | value |
|---|---|---|
| `b0_id` | 0 | `b0` |
| `b0_version` | 2 | `VIM 8.0` |
| `b0_page_size` | 12 | 4096 |
| `b0_mtime` | 16 | `0x59f9cd1e` = 1,509,543,198 = **2017-11-01T13:33:18Z** |
| `b0_ino` | 20 | 729,354 |
| `b0_pid` | 24 | **26,149** |
| `b0_uname` | 28 | **`chris`** |
| `b0_hname` | 68 | **`terry`** |
| `b0_fname` | 108 | **`~chris/fe-buildroot/board/moog/las-profili-prod/rootfs_overlay/etc/udev/rules.d/sort-part.sh`** |
| `b0_flags` | 1006 | `0x0d` |
| `b0_dirty` | 1007 | `0x55` |
| magics | 1008 | `33323130 00000000 | 23222120 | 1312 | 55` |

`[INFERRED]` from the fields:

* `b0_dirty == 0x55` is Vim's `B0_DIRTY` constant: **the buffer had unsaved
  changes** when the editor died.
* `b0_flags == 0x0d` = `B0_HAS_FENC | B0_SAME_DIR | 1`. The low bits give
  fileformat `unix`; `B0_SAME_DIR` means the swap file was written **into the
  same directory as the file being edited** — which is precisely how it came to
  be inside `rootfs_overlay/etc/udev/rules.d/` and thence into shipping firmware.
* `b0_magic_long` occupies 8 bytes (`33 32 31 30 00 00 00 00` = `0x30313233`),
  so `sizeof(long) == 8`: **`terry` is a 64-bit machine.**
* `b0_mtime` is the mtime of `sort-part.sh` at the moment Vim opened it, so the
  script already existed on **2017-11-01** — about a year before the Moog One
  shipped.

### The recovered buffer

`[READ]` Page 2 is the data block (`db_free=3911`, `db_txt_start=3971`,
`db_txt_end=4096`, `db_line_count=8`, `db_index = [4085, 4084, 4067, 4066, 3993,
3992, 3973, 3971]`). All 125 text bytes are accounted for. The complete
unsaved buffer, eight lines:

```
1  #!bin/bash
2  
3  declare -A array
4  
5  PARTS=`ls /media/ | tr " " "\n" | awk -F "s" '{print "\"dev/s" $2"\""}'`
6  
7  for PART in $PARTS
8  <TAB>
```

`[INFERRED]` Line 8 is a single tab character: the author was typing the body of
the `for` loop when the session was lost. This is a first draft, abandoned
mid-statement.

`[READ]` The shipped `etc/udev/rules.d/sort-part.sh` (607 B, 33 lines, also
byte-identical in v1.5.0) is a later, working version. Diffing the recovered
draft against it, four substantive differences:

| draft | shipped |
|---|---|
| `#!bin/bash` (**missing leading slash**) | `#!/bin/bash` |
| `PARTS=` | `MOUNTS=` |
| `declare -A array` | `declare -A LIST` |
| `awk … '{print "\"dev/s" $2"\""}'` (quotes the paths) | `awk … '{print "dev/s"$2}'` (unquoted) |

`[INFERRED]` The draft predates the shipped script — it has a shebang typo the
shipped file fixes and a quoting approach the shipped file abandons. The
swap file preserves a stage of authorship that exists nowhere else, and it has
been shipped in at least two firmware releases.

`[READ]` What the finished script does: enumerate `/media/*`, size each with
`df`, and `ln -sf` the largest onto `/media/thumbdrive` — the symlink
`S43gui:21` passes to `las-frontend` as `--usb-path=/media/thumbdrive`.

### The second source tree

`[READ]` A content search for each path token across all 488 MB:

| token | files containing it |
|---|---|
| `fe-buildroot` | **only** `etc/udev/rules.d/.sort-part.sh.swp` |
| `rootfs_overlay` | **only** `etc/udev/rules.d/.sort-part.sh.swp` |
| `las-profili-prod` | **only** `etc/udev/rules.d/.sort-part.sh.swp` |
| `las-buildroot` | ~hundreds of binaries in `usr/bin`, `usr/lib` |
| `las-ci-builds` | the same set |

`[READ]` The build root embedded in the binaries is
`/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/…`
(recovered from `usr/bin/xterm`, `usr/bin/Xorg`, `usr/lib/xorg/modules/drivers/*.so`,
`usr/lib/dri/*.so`).

`[INFERRED]` These are **two different trees**, and only one of them is otherwise
documented:

```
CI, in every binary:  /home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/
Swap file, nowhere else:  ~chris/fe-buildroot/board/moog/las-profili-prod/rootfs_overlay/
```

`[INFERRED]` The swap-file path has buildroot's canonical
`board/<vendor>/<board>/rootfs_overlay/` shape, so `las-profili-prod` is a
**buildroot board name** — "profili" being the same SoM identifier that appears
in `boot/imx6dl-profili-som.dtb`, and `-prod` distinguishing a production board
config from presumably a development one. `[UNKNOWN]` whether `fe-buildroot`
("fe" = front end?) is a fork, a predecessor, or a developer's personal clone of
`las-buildroot`; the single surviving reference cannot settle it.

`[INFERRED]` **`terry` is the build machine, and it is the same machine three
years later.** `[READ]` The kernel banner in v1.8.2 is
`Linux version 4.1.15-rt18 (root@terry) (gcc version 4.8.5 (Buildroot 2016.02-rc2-dirty)) #1 SMP PREEMPT RT Mon Sep 15 14:38:28 EDT 2025`
and in v1.5.0 the identical string but `Mon May 16 10:55:36 EDT 2022`. The swap
file's `b0_hname` is `terry`. `[INFERRED]` the host that ran `chris`'s Vim in
2017 is the host that still built the kernel in 2025 — and it builds as `root`.

## 14. The `.gitignore` files, and `etc/unit`

`[READ]` Five `.gitignore` files survive from the overlay repository. Four are
byte-identical (71 B, md5 `aab39e92ffe254319a73ebf43158c256`):

```
# Ignore everything in this directory
*
# Except this file
!.gitignore
```

at `etc/vxtune/`, `mnt/fwu/`, `mnt/u1/`, `mnt/u2/`. The fifth,
`etc/unit/.gitignore`, is 70 B (md5 `ce4123060e5e3693197b057f3708f846`) and
differs in exactly two characters on line 1:

```
#ignore everything in this directory
```

— no space after `#`, lowercase `i`.

`[INFERRED]` This is the standard git idiom for **committing an empty
directory**: ignore all contents, keep the marker. `[INFERRED]` The four
identical files were copy-pasted from one another; `etc/unit`'s was typed
separately, which suggests it was added at a different time by a different hand.

`[READ]` `etc/unit/` contains **nothing but that `.gitignore`** — it is a
completely empty directory in the shipped image. Same in v1.5.0.

`[READ]` `etc/vxtune/` is the one that is *not* empty: it holds
`cal-limits.scm` (4,026 B) and `mod-cal-limits.scm` (1,791 B).

`[INFERRED]` Those two `.scm` files are therefore **not tracked in the overlay
repository** — the `.gitignore` excludes them — so they are installed into
`/etc/vxtune/` by some other build step or package, not carried in the overlay.
`[UNKNOWN]` which step.

`[INFERRED]` What these five markers actually tell us is the set of directories
the overlay repo needed to *exist* at boot but never to *contain* anything at
build time: a units directory, a tuning directory, the firmware-update mount and
two USB mounts. They do **not** declare what runtime state each will hold — the
text is generic and identical across four of the five.

## 15. `/etc/git-tags` is not valid JSON

`[READ]` `etc/git-tags` in v1.8.2:

```json
{
 "LAS_FRONTEND_GIT_TAG" : "2.1.4",
"LAS_VX_GIT_TAG" : "lasvx-v2.2.1",
"LAS_FW_GIT_TAG" : "lasvc-v2.2.2",
"LAS_SC_GIT_TAG" : "1.1.0r2",
"LAS_FX_GIT_TAG" : "v1.1.1r4",
"LAS_SC_UGENS_GIT_TAG" : "master",
"LAS_FWU_GIT_TAG" : "v0.9.1",
"LAS_WATCHDOG_GIT_TAG" : "v0.2.0",
"LAS_DWM_GIT_TAG" : "v0.3.0",
"LAS_VX_DSP_GIT_TAG" : "vxdsp-v1.0.0rc1" 
"LAS_BUILDROOT_GIT_TAG" : "v1.8.2"
}
```

`[READ]` **There is no comma after `"vxdsp-v1.0.0rc1"`.** `json.loads` rejects
it: `Expecting ',' delimiter: line 12 column 1 (char 340)`.

`[READ]` v1.5.0's copy has the **same missing comma**, at the same place, with
`v1.5.0` as the buildroot tag.

`[READ]` The only binary in the image that references `git-tags` is
`usr/bin/las-frontend`.

`[INFERRED]` A defect in the build template that has survived at least from
v1.5.0 to v1.8.2 — the file is generated with a hardcoded trailing entry and the
separator was omitted. `[UNKNOWN]` how `las-frontend` copes: whether its parser
is lenient, whether it reads the file with a regex rather than a JSON parser, or
whether the `LAS_BUILDROOT_GIT_TAG` value is simply never displayed. Determining
that requires reading `las-frontend`'s parser, which I did not do.

`[READ]` `etc/version` is `las-v1.8.2`; `etc/versionb` is 8 bytes of non-text.

---

## 16. v1.5.0 versus v1.8.2, for everything in this report

`[READ]`, by `cmp`/`diff -rq`:

| file | result |
|---|---|
| `etc/X11/xorg.conf` | **identical** |
| `etc/X11/xinit/xinitrc` | **identical** |
| `etc/X11/xinit/xinitrc.d/default.sh` | **identical** |
| `etc/drirc` | **identical** |
| `etc/init.d/S12splash` | **identical** |
| `etc/init.d/S43gui` | **identical** |
| `etc/udev/rules.d/sort-part.sh` | **identical** |
| `etc/udev/rules.d/.sort-part.sh.swp` | **identical** |
| all five `.gitignore` | **identical** |
| `boot/cmdline.txt`, `cmdline.img` | **identical** |
| `boot/imx6dl-profili-som.dtb` | **identical** |
| `boot/moog_logo.fb`, `moog_splash.fb`, `moog_splash.bmp` | **identical** |
| `usr/share/examples/` (157 files, 39 MB) | **identical tree** |
| `usr/lib/dri/vivante_dri.so` | **identical** |
| `usr/lib/dri/swrast_dri.so` | differs |
| `boot/uImage` | differs — see below |

`[READ]` Both `uImage` files are 5,060,456 B with a 5,060,392 B payload, both
named `Linux-4.1.15-rt18`, and both decompress to exactly **10,214,816 bytes**.

`[READ]` The two decompressed kernels differ in **138 bytes**, in five runs:

1. `0x006b70d4` (24 B) — the build banner date, `Mon Sep 15 14:38:28 EDT 2025`
   vs `Mon May 16 10:55:36 EDT 2022`
2. `0x0075fb84` (1 B) — one byte of an adjacent pointer table
3. `0x009181b0` (20 B) — the GNU build-id
4. `0x009654c7` (106 B) — inside the embedded compressed initramfs
5. `0x0097b6c9` (24 B) — the same banner date, second copy

`[INFERRED]` **The display side of the kernel did not change between v1.5.0 and
v1.8.2.** The `CLAA-WVGA` string sits at the identical file offset `0x856050` in
both, and its pointer at the identical offset `0x991488` in both — meaning
identical link layout — and the thirteen timing values are identical. Same
source, same config, rebuilt on the same host with the same
`gcc 4.8.5 / Buildroot 2016.02-rc2-dirty` toolchain three years apart.

`[INFERRED]` Everything in Parts I–III is therefore a **stable, long-lived**
property of this product, not a v1.8.2 artefact. The dead `fluxbox` line, the
absent `scide`, the 39 MB of samples, the unloadable DRI module, the swap file,
and the malformed JSON have all shipped in at least two releases.

---

## 17. Conflicts with existing documentation

Reported, not fixed, per the ground rules.

**(a) `docs/arch/extension-points.md:1231` mislabels `moog_splash.fb`.**
It reads:

> `/boot/moog_splash.fb` | 16,716,544 B | `dd` in `S12splash:21` | the boot splash, raw framebuffer for the 832×5022×32 fb1

`[READ]` 832 × 5022 × 4 = 16,713,216, which is the size of **`moog_logo.fb`**.
`moog_splash.fb` is 16,716,544 = 832 × **5023** × 4. The byte count and the
geometry in that one table cell describe two different files. §6 gives the
detail: the splash file is one scanline longer than the framebuffer it is
written into, and that extra row is blank.

**(b) `docs/firmware/kernel.md:944-947` leaves two DTB rows as `?`.**
It records `fb@1` and `fb@3` with `disp_dev` unknown. `[READ]` They are
`hdmi` (with `mode_str = "1920x1080M@60"`, `RGB24`, `default_bpp 24`) and `ldb`
(`RGB666`, `default_bpp 16`) respectively. Not a contradiction — a fillable gap.
It matters for §8(b): `fb@1` being the *HDMI* node is what ties the
`default.sh` HDMI comment to a specific, disabled device-tree node.

**(c) No existing document decodes the kernel's `CLAA-WVGA` timing.**
`docs/firmware/kernel.md:946` records the DTB's `mode_str = "CLAA-WVGA"` — which
is correct and is a `[READ]` — but treats it as an opaque name. Several
documents then observe 832×480 only where `S12splash` writes it onto **fb1**
(`kernel.md:248`, `kernel.md:1693`, `arch/system-and-failure-modes.md:174`,
`firmware/init-boot.md:414`). §3 shows the 832 originates in the *kernel's own
`CLAA-WVGA` modedb entry* and applies to **fb0** as well; the `fbset` calls on
fb1 are matching a width the kernel already set, not establishing it. The
instrument's own dmesg confirms it independently: `Console: switching to colour
frame buffer device 104x30` = 832×480 at an 8×16 font, printed the moment `fb@2`
registers and long before any userspace `fbset` runs.

**(d) The gap brief's hypothesis about `Virtual 832 480` is not supported.**
The brief proposed that "the virtual framebuffer is 32 pixels wider than the
mode, which is a panning/stride arrangement rather than a visible resolution".
`[READ]` The kernel mode is 832 wide (§3); the console occupies all 832 columns
(§3); and `Virtual 832 480` equals the mode exactly, with no room to pan in
either axis. `[INFERRED]` It is not a panning or stride arrangement. What *is*
800 wide is the shipped **artwork**, centred with 16-pixel margins (§6) — which
is probably the observation the 800/832 discrepancy was pointing at.

**(e) The gap brief's reading of the `.gitignore` files is not supported.**
The brief describes them as "each declaring what runtime state its directory is
expected to hold". `[READ]` Four of the five are byte-identical and the fifth
differs only in the capitalisation and spacing of a comment; all five say only
"ignore everything, keep this file" (§14). They declare nothing about content.

## 18. What I did not get to

* `usr/bin/las-dwm` beyond its strings — the tag/xterm mapping, how it decides
  which client goes on which tag, and its phone-home path
  (`sshpass -plas ssh -N -T -y -R22222:localhost:22 -p4448 las@remote.moogmusic.com`)
  are visible as literals but not traced. The phone-home is already covered in
  `DANGER.md`, `firmware/network.md`, `firmware/lassvc.md` and elsewhere.
* Whether GLX is ever initialised, and whether any process on the device opens
  an EGL or GLES context. `xorg.conf` has no `Module` section; `las-frontend`
  was not examined for GL usage.
* `las-frontend`'s `/etc/git-tags` parser (§15) — the actual behaviour against
  the malformed JSON.
* `usr/lib/xorg/modules/drivers/modesetting_drv.so` and `fbdev_drv.so`: present,
  unused by this `xorg.conf`, not examined.
* `usr/bin/Xvfb` (1,358,196 B) — shipped, referenced by nothing I found, not
  examined.
* The exact upstream Freescale `CLAA-WVGA` values, which would quantify the
  modification in §3 precisely. No upstream `mxc_lcdif.c` was available on local
  disk to diff against, so §3 reports only the shipped values and infers that the
  entry was modified from the shape of the table around it.
* `boot/moog_splash_version.bmp` vs `moog_splash_ver.bmp` — which one the
  updater renders the version string into, and by what tool.
* The second page of `moog_splash.fb`/`moog_logo.fb` (rows 2511–2990) — I
  established that it differs from page 1 but did not render either to see what
  they depict.

## 19. Validation plan — READ-ONLY, for a human to run

**Do not run these from this session.** They are proposals for the owner, on the
instrument, and every one is read-only.

Settle the panel geometry (§3, §6):

```sh
cat /sys/class/graphics/fb0/virtual_size    # expect 832,480
cat /sys/class/graphics/fb0/mode
cat /sys/class/graphics/fb0/bits_per_pixel
cat /sys/class/graphics/fb0/stride
cat /sys/class/graphics/fb1/virtual_size    # expect 832,5022
cat /sys/class/graphics/fb1/mode            # expect the 10x10 from S43gui:81
fbset -i -fb /dev/fb0                       # -i is info-only
fbset -i -fb /dev/fb1
```

Confirm what X believes (§2, §4):

```sh
DISPLAY=:0 xdpyinfo | head -40
DISPLAY=:0 xrandr --query
grep -iE 'adjust display width|Virtual|Modes|vivante|EXA|debug' /var/log/Xorg.0.log
```

Confirm the dead paths (§7, §8, §12):

```sh
ls -la /home/linaro/share/exa_log.txt   ; echo "exit=$?"
which startfluxbox fluxbox scide        ; echo "exit=$?"
ls -la /usr/share/examples
du -sh /usr/share/examples
```

Confirm the residue (§13, §15):

```sh
ls -la /etc/unit /etc/vxtune /mnt/u1 /mnt/u2 /mnt/fwu
cat /etc/git-tags
head -c 200 /etc/udev/rules.d/.sort-part.sh.swp | strings
cat /proc/cmdline
```

Cross-check the DMFC patch and the IPU warning (§3, §5):

```sh
dmesg | grep -iE 'DMFC|mxc_sdc_fb|Console: switching|IPU Warning|galcore|vivante'
```
