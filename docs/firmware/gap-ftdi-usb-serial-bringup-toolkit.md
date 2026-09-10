# Gap report: the libftdi USB-serial / FT2232 bring-up toolkit

Target of this pass: the nine `libftdi-0.20` programs in `usr/bin` —
`find_all`, `find_all_pp`, `simple`, `bitbang`, `bitbang2`, `bitbang_cbus`,
`bitbang_ft2232`, `baud_test`, `serial_test` — the three shared libraries they
sit on (`libftdi.so.1.20.0`, `libftdipp.so.1.20.0`, `libusb-0.1.so.4.4.4`), and
the one non-example consumer of that library stack in the image,
`usr/sbin/flashrom`.

The question the gap assignment poses is a hardware-topology question: **does an
FTDI USB-serial / FT2232 bridge exist on or beside the Moog One, and if so what
is it wired to?** This report answers it, and then answers the prior question it
turns out to depend on — *why is libftdi in the image at all*.

## Sources

Everything below is static analysis of files on local disk. **The instrument was
not contacted.** No binary from either root filesystem was executed anywhere.

| source | what it gave |
|---|---|
| `captures/firmware-1.8.2/rootfs-1.8.2/` | decrypted v1.8.2 root filesystem |
| `captures/rootfs-1.5.0/` | v1.5.0 root filesystem from the owner's instrument |
| `captures/dmesg-before-reboot.txt` | boot log, incl. the complete USB enumeration |
| `captures/arch-harvest/runtime-state.txt` | see caveat below |
| `docs/` | existing reports, for cross-reference and the Conflicts section |

Tools: `file`, `md5`, `strings -a -t d`, `xxd`, `grep -a`, a purpose-written
Python ELF reader and DTB parser, and
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`.

**On `runtime-state.txt`:** `captures/arch-harvest/CAVEAT-runtime-state.md` was
read first. This report cites it for exactly one thing — and in fact it turned
out to be worthless even for that. Its `--- usb ---` section is **empty**
**[READ]**: the capture command was
`cat /sys/kernel/debug/usb/devices 2>/dev/null | head -40 || lsusb 2>/dev/null`
and it produced no output, because `debugfs` was not mounted and the `||`
fallback never fired inside the pipeline. Its `--- modules ---` section shows
only the `lsmod` header, i.e. no loadable module was loaded. **There is
therefore no USB device inventory in the snapshot at all**; the boot log is the
sole evidence for what enumerates. Any prior report that cites
`runtime-state.txt` for a USB device list is citing a blank.

## Grading key

* **[READ]** — read directly out of a named file at a named offset, line or
  address, and reproduced here.
* **[INFERRED]** — reasoning from stated evidence; the evidence is named so the
  step can be checked or rejected.
* **[UNKNOWN]** — not established. Said so instead of guessing.

## Address convention

All nine programs are `ET_EXEC` ARM binaries whose first `PT_LOAD` is
`off=0x0 -> vaddr=0x10000` **[READ, verified individually for all nine in both
firmware versions]**. So for every citation below,

> `virtual address = 0x10000 + file offset`

and a citation of the form `0x109e8 (file offset 2536)` can be checked with
`xxd -s 2536 -l 4`. Decimal string offsets are as printed by `strings -a -t d`.

---

## 1. Headline

**[INFERRED]** There is no FTDI device inside the Moog One, and nothing in
either firmware version expects one. The nine programs are the unmodified
upstream `libftdi-0.20` example suite, copied out of the Buildroot build tree
into `/usr/bin`, referenced by nothing, and — as shipped — mostly incapable of
talking to an FT2232 even if one were attached.

**[INFERRED]** libftdi is in the image because `usr/sbin/flashrom` links it.
flashrom's compiled-in programmer table includes **two** FTDI-backed programmers,
`ft2232_spi` and `usbblaster_spi` **[READ]**, alongside the one the instrument
actually uses, `linux_spi` **[READ]**. The flash those FTDI backends would
program is the same SPI-NOR that `las-sc` writes in-system with
`flashrom -l /usr/share/xmosfw/las_layout -i firmware -w <fw> -p linux_spi:dev=/dev/spidev0.0`
**[READ]** — the XMOS boot flash, on a bus the i.MX6 and the XMOS take turns
owning.

**[INFERRED]** That makes `ft2232_spi` the *bench-side, board-is-dead* half of a
two-sided flash-programming story whose in-system half is already documented in
`xmos.md`, `calibration.md` and `gap-uboot-env-and-flash-fuse-tooling.md`. But
see §7: the competing explanation — that the whole cluster is incidental fallout
from a kitchen-sink Buildroot configuration — is better supported by the
evidence, and this report comes down on that side.

**[READ]** The libftdi stack is *byte-identical* between v1.5.0 (May 2022) and
v1.8.2 (September 2025) except for the CI build path embedded in `DT_RPATH` and
the relocations that path's changed length forces. Nothing was touched in three
years and one major firmware generation. §8 proves this exhaustively.

---

## 2. Inventory

### 2.1 The nine programs

All in `usr/bin`, mode `0755`, present in **both** firmware versions **[READ]**.
ELF 32-bit LSB ARM EABI5, `interpreter /lib/ld-linux-armhf.so.3`, "for GNU/Linux
2.6.32", **stripped** **[READ, `file`]**.

| program | 1.8.2 bytes | 1.5.0 bytes | 1.8.2 md5 |
|---|---:|---:|---|
| `find_all` | 4616 | 4592 | `d6cc1c8a222dcaa14682a61e02559260` |
| `find_all_pp` | 6424 | 6384 | `8875537b5d328c8d6dd924f430c59845` |
| `simple` | 4480 | 4456 | `d4546cfee6aadbf0246dc650b0878c25` |
| `bitbang` | 5340 | 5312 | `1c4eaf0c761a6e32ba9c2e87b4859ef2` |
| `bitbang2` | 5012 | 4984 | `0dc4bd52255c145f11720a9e8d5a93f2` |
| `bitbang_cbus` | 5112 | 5084 | `8514a7fb10fd48adaf5093f1ae88d7e5` |
| `bitbang_ft2232` | 5820 | 5820 | `1412dfb8ee03e8f1dc77b6aa4fc62690` |
| `baud_test` | 6084 | 6060 | `3fd0c607bdb955b54fc2499936274f56` |
| `serial_test` | 6604 | 6580 | `90605e6c1445108ad0f97faadf0a6e30` |

File timestamps: 1.8.2 = 2025-09-15, 1.5.0 = 2022-05-16 **[READ]**.

**Every one carries a `DT_RPATH` pointing into Moog's own CI build tree**
**[READ]**. v1.8.2, e.g. `find_all`:

```
/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/build/libftdi-0.20/src/.libs:
/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/host/usr/arm-buildroot-linux-gnueabihf/sysroot/usr/lib
```

v1.5.0, same file:

```
/home/las-ci-builds/6c53963c/0/moogmusic/las-buildroot/output/build/libftdi-0.20/src/.libs:
/home/las-ci-builds/6c53963c/0/moogmusic/las-buildroot/output/host/usr/arm-buildroot-linux-gnueabihf/sysroot/usr/lib
```

`find_all_pp` has a third leading component, `.../libftdi-0.20/ftdipp/.libs`
**[READ]**.

**[INFERRED] — and this is the single most diagnostic fact in the inventory.**
The tag is `DT_RPATH` (tag 15), not `DT_RUNPATH`, and it names the *build tree*
`.libs` directory. That is libtool's signature for an **uninstalled** binary.
When libtool installs a program it relinks it and strips the build-tree rpath.
These were never installed by the package's own install rules — they were
**copied out of `libftdi-0.20/examples/` into `/usr/bin` verbatim**. By contrast
`usr/sbin/flashrom` has **no `DT_RPATH` at all** **[READ]**, which is what a
properly installed binary looks like. The nine got into the image by a copy, not
by `make install`.

### 2.2 Link graph

`find_all` **[READ, `DT_NEEDED`]**:

```
libftdi.so.1  libusb-0.1.so.4  libusb-1.0.so.0  libudev.so.1
librt.so.1    libpthread.so.0  libc.so.6
```

Seven of the nine are identical in this respect. `find_all_pp` adds
`libftdipp.so.1`, `libstdc++.so.6`, `libm.so.6`, `libgcc_s.so.1` **[READ]**.

The chain is **[READ, `DT_NEEDED` of each library]**:

```
program -> libftdi.so.1 (0.20)
             -> libusb-0.1.so.4  (libusb-compat shim, SONAME libusb-0.1.so.4)
                  -> libusb-1.0.so.0 -> libudev.so.1
```

libftdi 0.20 predates libusb-1.0 and is written against the old `usb_*` API;
`libusb-0.1.so.4.4.4` here is the **compat shim** over libusb-1.0, not the
original libusb-0.1 — proven by its own `DT_NEEDED` on `libusb-1.0.so.0` and
`libudev.so.1` **[READ]**. libftdi's dynsym still imports `usb_init`,
`usb_find_busses`, `usb_find_devices`, `usb_claim_interface`,
`usb_detach_kernel_driver_np`, `usb_control_msg` **[READ]**.

`usr/lib/libusb.so` is a symlink to `libusb-0.1.so.4.4.4` **[READ]** — i.e. the
image's `-lusb` development link points at the 0.1 shim.

### 2.3 Everything in the image that touches libftdi

Whole-rootfs scan for the literal `libftdi.so` **[READ]** (note: this requires
`grep -a`; without it, GNU/BSD grep silently reports nothing on these binaries —
a NUL-byte trap that will make a careless sweep conclude "no consumers"):

```
usr/bin/{baud_test,bitbang,bitbang2,bitbang_cbus,bitbang_ft2232,
         find_all,find_all_pp,serial_test,simple}
usr/lib/libftdi.so.1.20.0
usr/lib/libftdipp.so.1.20.0
usr/sbin/flashrom            <-- the only non-example consumer
```

Identical list in v1.5.0 **[READ]**.

`libusb-1.0.so.0` additionally has two unrelated consumers, `usr/bin/sclang` and
`usr/lib/libpcap.so.1.7.4` **[READ]** — neither goes near libftdi.

### 2.4 What is *not* present

All **[READ]** unless noted.

* **No `ftdi_sio` kernel driver.** `lib/modules/4.1.15-rt18/modules.builtin`
  lists `kernel/drivers/usb/serial/usbserial.ko` and nothing else under
  `usb/serial`. The only two loadable modules in the whole image are
  `imx_rpmsg_pingpong.ko` and `imx_rpmsg_tty.ko`. Same in v1.5.0.
  The boot log agrees: `usbserial: USB Serial support registered for generic`
  and no FTDI line.
* **No `ftdi_eeprom`** program, and no `.conf` for one, though
  `libftdi.so.1.20.0` does export the whole `ftdi_eeprom_*` /
  `ftdi_{read,write,erase}_eeprom*` family.
* **No udev rule** anywhere matching FTDI. The only `0403` hits in the whole
  rootfs are inside `etc/udev/hwdb.d/20-usb-vendor-model.hwdb`, which is the
  stock upstream USB vendor/product database — data, not a rule.
* **No script, init file, crontab or config** in either rootfs names any of the
  nine. Cross-checked both versions, whole-tree, with `grep -arl`.
* **No other USB-serial bridge family** — `cp210`, `pl2303`, `ch340`, `ch341` —
  appears anywhere in the rootfs outside `usr/sbin/flashrom` and the stock
  hwdb/usb-id data files.
* **No `xflash`, `xrun`, `xgdb` or xTAG tooling** of any kind. The only `usr/bin`
  entries starting with `x` are X11 clients (`xeyes`, `xclock`, `xterm`, …).

---

## 3. What each program actually does

Every one was disassembled. The defaults matter more than the code, because they
determine whether the program can see real hardware at all.

### 3.0 Defaults at a glance

| program | opens VID:PID | interface | bitmode | other defaults |
|---|---|---|---|---|
| `find_all` | `0403:6001` (fixed) | — | — | not configurable |
| `find_all_pp` | **`0403:6010`** | — | — | `-v` / `-p` override, base 16 |
| `simple` | `0403:6001` (fixed) | — | — | chip-id only if `type == TYPE_R` |
| `bitbang` | `0403:6001` (fixed) | — | `0xFF`, BITBANG | 32-step walk, ≈134 s |
| `bitbang2` | `0403:6001` (fixed) | — | `0xFF`, BITBANG | `-d` delay, default 100000 µs |
| `bitbang_cbus` | `0403:6001` (fixed) | — | mask from stdin, **CBUS** | interactive |
| `bitbang_ft2232` | `0403:6001` ×2 | **A and B** | `0xFF`, BITBANG | 23 steps × 4 s ≈ 92 s |
| `baud_test` | `i:0x0403:0x6001` | — | BITBANG (`-m`) | `-b 9600 -c 256 -d 100000` |
| `serial_test` | **`0403:0000`** | `INTERFACE_ANY` | — | 115200 8N1 |

Read that table twice. **Only `find_all_pp` defaults to an FT2232's product ID
(`0x6010`).** Seven of the nine default to `0x6001`, which is an FT232BM/FT232R —
a *single-channel* part. And `serial_test` defaults to product `0x0000`, which
matches nothing.

### 3.1 `find_all` — enumerate FTDI devices

`ftdi_init` → `ftdi_usb_find_all(ctx, &list, 0x0403, 0x6001)` →
`ftdi_usb_get_strings` per device → `ftdi_list_free` → `ftdi_deinit`.

**[READ]** `0x107e8` (file offset 2024) `e3002403` = `movw r2, #0x403`;
`0x107ec` (2028) `e3063001` = `movw r3, #0x6001`. Those are arguments 3 and 4 of
`ftdi_usb_find_all(struct ftdi_context*, struct ftdi_device_list**, int vendor,
int product)`.

Strings **[READ]**: 2724 `ftdi_init failed`, 2742
`ftdi_usb_find_all failed: %d (%s)`, 2777 `Number of FTDI devices found: %d`,
2811 `Checking device: %d`, 2832 `ftdi_usb_get_strings failed: %d (%s)`, 2870
`Manufacturer: %s, Description: %s`.

**[INFERRED] The name is a lie and it matters.** `find_all` does not find all
FTDI devices. It finds devices whose VID:PID is exactly `0403:6001`, and the
constants are immediate operands with no command-line path to change them.
Pointed at an FT2232H (`0403:6010`), an FT4232H (`6011`) or an FT232H (`6014`)
it prints `Number of FTDI devices found: 0`. Any conclusion drawn from running
this program — including a negative one — is a conclusion about FT232R/BM parts
only.

### 3.2 `find_all_pp` — the same idea through the C++ wrapper

The only one of the nine with a real command line, and the only one that
defaults to an FT2232.

**[READ]** `0x10d28` (3368) `e3066010` = `movw r6, #0x6010`; `0x10d2c` (3372)
`e3007403` = `movw r7, #0x403`. Options parsed by `strcmp` against literals in
`.rodata` at file offsets 4436 `-h`, 4439 `--help`, 4486 `-v`, 4489 `-p`, each
converted with `strtol(..., 16)` **[READ, `mov r2, #16` at `0x10d78` and
`0x10dac`]**.

Usage string, assembled from 4446 and 4454 **[READ]**:

```
Usage: <argv0> [-v VENDOR_ID] [-p PRODUCT_ID]
```

Output strings **[READ]**: 4492 `Found devices ( VID: `, 4514 `, PID: `, 4522
` )`, 4525 a 48-dash rule, 4574 `FTDI (`, 4581 `): `, 4585 `, `, 4588
` (Open OK)`, 4599 ` (Open FAILED)`.

Calls `Ftdi::List::find_all(int,int)`, then per entry `Ftdi::Context::open`,
`vendor()`, `description()`, `serial()`, `close()` **[READ, `.dynsym`:
`_ZN4Ftdi4List8find_allEii`, `_ZN4Ftdi7Context4openEP10usb_device`,
`_ZN4Ftdi7Context6vendorEv`, `_ZN4Ftdi7Context11descriptionEv`,
`_ZN4Ftdi7Context6serialEv`, `_ZN4Ftdi7Context5closeEv`]**.

**[INFERRED]** If anyone ever wanted to answer "is an FTDI attached to this
instrument", `find_all_pp -v 0x0403 -p 0x6010` is the only one of the nine that
does the job without editing source. It is also the only one that is *safe* in
the sense of §9 — it opens and closes, and drives nothing.

### 3.3 `simple` — open a device and read its chip ID

`ftdi_init` → `ftdi_usb_open(ctx, 0x0403, 0x6001)` → *if* `ctx->type == 3` →
`ftdi_read_chipid` → `ftdi_usb_close` → `ftdi_deinit`.

**[READ]** `0x107dc` (2012) `e3001403` = `movw r1, #0x403`; `0x107e0` (2016)
`e3062001` = `movw r2, #0x6001`; `0x10820` (2080) `e3530003` = `cmp r3, #3`
where `r3` was loaded from `[sp,#0x14]`, i.e. context base `sp+8` plus **12** —
the `enum ftdi_chip_type type` field of `struct ftdi_context`.

**[INFERRED]** `3` is `TYPE_R` in libftdi's chip-type enum
(`AM=0, BM=1, 2232C=2, R=3, 2232H=4, 4232H=5, 232H=6`). So `simple` reads a chip
ID **only on an FT232R**; on any 2232/4232/232H it opens the device, prints
nothing, and exits 0. Strings **[READ]**: 2695 `ftdi_read_chipid: %d`, 2717
`FTDI chipid: %X`.

### 3.4 `bitbang` — drive all eight data pins, for about two and a quarter minutes

`ftdi_usb_open(0x0403, 0x6001)` **[READ, `0x1096c`/`0x10970`, offsets
2412/2416]** → `ftdi_set_bitmode(ctx, 0xFF, 1)` **[READ, `0x109d0` (2512)
`e3a010ff` = `mov r1, #255`; `0x109d4` (2516) `e3a02001` = `mov r2, #1` =
`BITMODE_BITBANG`]** — all eight pins outputs.

Then, in order **[READ]**: `sleep(3)`; write `0x00` under the message at 3490
`turning everything on`; `sleep(3)`; write `0xFF` under 3550
`turning everything off`; then a 32-iteration loop, each iteration
`sleep(3)`, compute `buf = ~(1 << (i & 7))` **[READ, `mvn r2, r6, lsl r3` at
`0x10ab4` with `r6 = 1`, `r3 = i & 7`]**, `printf("%02hhx ")`, `fflush(stdout)`,
`ftdi_write_data`, `sleep(1)`; terminating on `cmp r4, #32` **[READ, `0x10b30`
(2864) `e3540020`]**. Finally `ftdi_disable_bitbang`, close, deinit.

**[INFERRED]** Total run time ≈ 6 s + 32 × 4 s = **134 seconds**, and it drives a
walking-zero pattern across all eight pins the whole time. The `0x00` first and
`0xFF` second, against the labels "on" then "off", says the reference hardware
had active-low LEDs on the eight data pins.

### 3.5 `bitbang2` — write bytes you supply

The only one of the nine with a `getopt` string *and* positional arguments.

**[READ]** `getopt(argc, argv, "d:")` — the optstring lives at file offset 3188
(three bytes `d:\0`, below `strings`' default minimum length, which is why it
does not appear in a plain `strings` dump; the literal pool word at `0x10a6c`
points at `0x00010c74` = 3188, and the next visible string is 3191
`ftdi_init failed`).

Default delay **[READ, literal at `0x10a64` = `0x000186a0`]** = **100000 µs**
(100 ms), overridden by `-d` via `atoi`.

Then `ftdi_usb_open(0x0403, 0x6001)` **[READ, offsets 2424/2432]** and
`ftdi_set_bitmode(0xFF, BITMODE_BITBANG)` **[READ, offsets 2456/2460]**, then for
each remaining argument: `sscanf(argv[i], "%x", &v)` **[READ, format string at
file offset 3253, also sub-4-byte]**, `ftdi_write_data(ctx, &v, 1)`,
`usleep(delay)`.

Usage, reconstructed **[INFERRED from the above]**:
`bitbang2 [-d delay_us] <hexbyte> [<hexbyte> …]`.

**[READ]** Unlike `bitbang`, it never calls `ftdi_disable_bitbang` — it closes
with the pins still driven.

### 3.6 `bitbang_cbus` — drive and read the CBUS pins, interactively

`ftdi_usb_open(0x0403, 0x6001)` **[READ, offsets 2360/2364]**, then a loop:
`fgets(buf, 9, stdin)`; stop on a bare newline **[READ, `cmp r3, #10` at
`0x1099c`]**; `strtol(buf, NULL, 0)`; truncate to 8 bits **[READ, `uxtb r4, r0`
at `0x109b4`]**; `ftdi_set_bitmode(ctx, mask, 0x20)` **[READ, `0x109cc` (2508)
`e3a02020` = `mov r2, #32`]** — `0x20` is `BITMODE_CBUS`; then `ftdi_read_pins`.

Strings **[READ]**: 3236 `Using bitmask 0x%02x`, 3258
`set_bitmode failed for 0x%x, error %d (%s)`, 3302
`read_pins failed, error %d (%s)`, 3335 `Read returned 0x%01x`.

**[INFERRED]** In libftdi's CBUS bitbang encoding the low nibble of the mask is
the output data and the high nibble is the direction, which is why the read-back
is printed as a single hex digit. CBUS bitbang is an **FT232R/FT232H** feature;
on an FT2232 it does not exist.

### 3.7 `bitbang_ft2232` — the only dual-channel program

This is the one the gap assignment singled out for "sets a specific interface".
It sets two.

Channel A **[READ]**: `ftdi_init(ctx1)`; `0x10938` (2360) `e3a01001` =
`mov r1, #1` → `ftdi_set_interface(ctx1, 1)` = `INTERFACE_A`; `0x10948` (2376)
`e3001403` and `0x1094c` (2380) `e3062001` → `ftdi_usb_open(ctx1, 0x0403,
0x6001)`; `ftdi_set_bitmode(ctx1, 0xFF, 1)`.

Channel B **[READ]**: a *second, independent* `struct ftdi_context` at `sp+104`;
`0x109d8` (2520) `e3a01002` = `mov r1, #2` → `ftdi_set_interface(ctx2, 2)` =
`INTERFACE_B`; `0x109e8`/`0x109ec` (2536/2540) → `ftdi_usb_open(ctx2, 0x0403,
0x6001)`; `ftdi_set_bitmode(ctx2, 0xFF, 1)`.

Then `puts("startloop")` (3798) and a loop terminating on `cmp r4, #23`
**[READ, `0x10bdc` (3036) `e3540017`]**, so **23 iterations**, `r4` running
0…22. Each iteration does four write-then-`sleep(1)` steps **[READ]**:

```
printf("porta: %02i: 0x%02x ", i, 1) ; write 0x01 to ctx1 ; sleep(1)
printf("porta: %02i: 0x%02x ", i, 2) ; write 0x02 to ctx1 ; sleep(1)
printf("portb: %02i: 0x%02x ", i, 1) ; write 0x01 to ctx2 ; sleep(1)
printf("portb: %02i: 0x%02x ", i, 2) ; write 0x02 to ctx2 ; sleep(1)
```

**[INFERRED]** Run time ≈ 23 × 4 = **92 seconds**, toggling bit 0 and bit 1 of
each of the two 8-bit ports.

**[READ] and this is the decisive detail:** the program asks for `INTERFACE_B` on
a device whose product ID it hard-codes as **`0x6001`**. `0x6001` is an
FT232BM/FT232R. Those parts have exactly one channel.

**[INFERRED]** As shipped, `bitbang_ft2232` cannot work. It will either fail to
find a device at all (nothing on the instrument is `0403:6001`) or, on a genuine
single-channel FT232R, fail when it asks for channel B. To use it against a real
FT2232H you must edit the product ID to `0x6010` and rebuild — which nobody can
do on the instrument, since there is no compiler in the image. Whether the
`0x6001` is an upstream quirk or a Moog edit is **[UNKNOWN]**: no upstream
libftdi-0.20 source tree is on disk to diff against. §8 does establish that the
constant is the same in v1.5.0 and v1.8.2, and that nothing else in the nine
shows any sign of Moog editing.

### 3.8 `baud_test` — measure achieved throughput

**[READ]** `getopt(argc, argv, "b:d:p:m:c:")` — optstring at file offset 4060.
Dispatch is a jump table indexed by `opt - 'b'` **[READ, `sub r0, r0, #98` at
`0x10a80`, `ldrls pc, [pc, r0, lsl #2]` at `0x10a88`, table at `0x10a90`…
`0x10ac8`]**, giving:

| option | effect | default |
|---|---|---|
| `-b` | baud rate, `atoi` | **9600** **[READ, `0x10a64` (2660) `e3a06d96` = `mov r6, #9600`]** |
| `-c` | buffer / chunk size, `atoi` | **256** **[READ, `0x10a60` (2656) `e3a05c01` = `mov r5, #256`]** |
| `-d` | total bytes to transfer, `atoi` | **100000** **[READ, literal `0x000186a0` at `0x10dc0`]** |
| `-m` | mode: `r`→0, `s`→4, `a`→1 | **1** = `BITMODE_BITBANG` **[READ, `0x10a58` (2648) `e3a04001`]** |
| `-p` | device description string | **`i:0x0403:0x6001`** **[READ, file offset 4317]** |

The default description is materialised by copying 16 bytes from `.rodata` onto
the stack before the option loop **[READ, the `ldm`/`stm` pair at
`0x10a34`–`0x10a50`]**, then passed to `ftdi_usb_open_string(ctx, desc)`
**[READ, `0x10b88`]**. `i:` is libftdi's "first device with this VID:PID" form.

Body **[READ]**: if mode ≠ 0, the requested baud rate is divided by 16 before
`ftdi_set_baudrate` **[READ, `asr r6, r6, #4` at `0x10bc8`]** — libftdi's bitbang
convention — and multiplied back by 16 for the `real baudrate used: %d` report
(4131) **[READ, `lslne r1, r1, #4` at `0x10be4`]**. `ftdi_set_bitmode(ctx, 0xFF,
mode)`. Buffer fill: `0xAA` if mode is `BITMODE_RESET` **[READ, `mvn r2, #85` at
`0x10c54`]**, else alternating `0x00`/`0xFF`. Then
`ftdi_write_data_set_chunksize(size)` and `ftdi_read_data_set_chunksize(size)`;
in `BITMODE_SYNCBB` (4) it also drains the read side. Timing by `gettimeofday`.

Reports **[READ]**: 4175 `this test should take %.2f seconds`, 4260
`and took %.4f seconds, this is %.0f baud or factor %.3f`.

**[INFERRED]** With stock defaults, `this test should take` prints
100000 / 9600 = **10.4 s**, and the program drives all eight data pins with an
alternating pattern at 600 baud for that period.

### 3.9 `serial_test` — the only real UART program, and it cannot start

**[READ]** `getopt(argc, argv, "i:v:p:b:w::")` — optstring at file offset 4529.
Usage at 4456:

```
usage: %s [-i interface] [-v vid] [-p pid] [-b baudrate] [-w [pattern]]
```

Defaults **[READ]**: interface `r10 = 0`, pid `r9 = 0`, pattern `0xFFFF`
(sentinel for "unset"), baud `r5` = literal `0x0001c200` at `0x10f44` (file
offset 3908) = **115200**, and vid `r7` = `0x403` **[READ, `0x10b3c` (2876)
`e3007403` = `movw r7, #0x403`]**, set *before* the option loop.

Branch selection **[READ, `0x10c7c`–`0x10c84`]**:

```
orr  r11, r9, r10        ; pid | interface
orrs r11, r11, r7        ; | vid
bne  0x10d40             ; -> explicit-open path
```

The fall-through (`0x10c88`) is the `ftdi_usb_find_all(ctx, &list, 0, 0)`
enumeration path that owns all four of the "default VID/PID" messages — 4558
`No FTDI with default VID/PID found`, 4625
`%d Devices found, please select Device with VID/PID`, 4678
`No Devices found with default VID/PID`.

**[INFERRED]** Because `vid` defaults to `0x0403`, that `orrs` is never zero
unless the operator passes `-v 0`. **The enumeration path is unreachable by
default and all four of its messages are dead strings.** The default path is
`ftdi_set_interface(ctx, 0 = INTERFACE_ANY)` then
`ftdi_usb_open(ctx, 0x0403, 0x0000)` **[READ, `0x10d40`–`0x10d54`]** — product
ID **zero**, which matches no FTDI part ever made. **`serial_test` with no
arguments always fails.**

If it did open: `ftdi_set_baudrate(115200)`, then
`ftdi_set_line_property(ctx, 8, 0, 0)` **[READ, `0x10dc0` (3520) `e3a01008` =
`mov r1, #8`; `r2 = r3 = 0`]** = **8 data bits, 1 stop bit, no parity**. Then
either a read loop — `ftdi_read_data(ctx, buf, 1024)`, `fprintf(stderr,
"read %d bytes\n", n)` (4827), `fwrite` to stdout, `fflush` both — or, with `-w`,
a write loop over a 1024-byte buffer filled with the pattern byte, rate-limited
by `baudrate >> 9` **[READ, `asr r5, r5, #9` at `0x10e28`]**. `SIGINT` is trapped
to break the loop cleanly **[READ, `signal(2, handler)` at `0x10e14`, restored to
`SIG_DFL` at `0x10f20`]**. Pattern values above 255 are rejected with 4424
`Please provide a 8 bit pattern` **[READ, `cmp r1, #255` at `0x10c18`]**.

---

## 4. Is there an FTDI device on or beside the instrument?

Six independent lines of evidence. All negative.

**4.1 The kernel cannot make an FTDI into a serial port.** **[READ]**
`modules.builtin` contains `kernel/drivers/usb/serial/usbserial.ko` and no
`ftdi_sio`. The boot log's driver registrations are, in full:

```
usbfs  hub  asix  cdc_ether  cdc_eem  cdc_ncm  cdc_acm
usb-storage  usbserial  usbserial_generic  usbhid
```

`usbserial_generic` binds only devices named by its `vendor=`/`product=` module
parameters, and the kernel command line sets none **[READ,
`Kernel command line: console=ttymxc1,115200{smp} root=/dev/mmcblk2p3 rootwait
isolcpus=1 quiet loglevel=0 galcore.contiguousSize=67108864 gpumem=128M dmfc=3
nohz=off skew_tick=1`]**. **[INFERRED]** An FTDI plugged into this machine gets
no `/dev/ttyUSB*`. It is reachable only through libusb — which is exactly the
arrangement libftdi wants, so this is not itself evidence against an FTDI, but
it does mean nothing else in the system could ever use one.

**4.2 Nothing consumes `/dev/ttyUSB*`.** **[READ]** Whole-rootfs scan for
`ttyUSB`: `usr/sbin/flashrom` (its own `buspirate_spi` and `serprog` help text),
`usr/share/SuperCollider/HelpSource/Classes/SerialPort.schelp` (upstream
documentation), and `lib/udev/rules.d/60-serial.rules` (stock udev). No Moog
code.

**4.3 The complete USB enumeration contains no FTDI.** **[READ,
`dmesg-before-reboot.txt`]** Two root hubs, one port each:

```
ci_hdrc ci_hdrc.0: new USB bus registered, assigned bus number 1
hub 1-0:1.0: 1 port detected
ci_hdrc ci_hdrc.1: new USB bus registered, assigned bus number 2
hub 2-0:1.0: 1 port detected
```

and exactly two devices across the whole boot:

```
[ 1.703623] usb 1-1: new high-speed USB device number 2 using ci_hdrc
[ 1.856355] usb-storage 1-1:1.0: USB Mass Storage device detected
[ 2.864598] scsi 0:0:0:0: Direct-Access  VendorC  ProductCode  3.20
[ 2.866322] sd 0:0:0:0: [sda] 491520000 512-byte logical blocks: (251 GB/234 GiB)

[11.903573] usb 2-1: new high-speed USB device number 2 using ci_hdrc
[12.057691] cdc_ether 2-1:1.0 usb0:  ... 02:00:00:00:00:00
[12.060044] cdc_ether 2-1:1.2 eth0:  ... a4:11:63:b0:28:9b
[12.106790] cdc_ether 2-1:1.0 usbint: renamed from usb0
[12.169539] cdc_ether 2-1:1.2 ethext: renamed from eth0
```

Bus 1 = the panel USB-A socket, holding the owner's 251 GB stick. Bus 2 = the
XMOS, presenting *two* CDC Ethernet functions on one device (interfaces `1.0`
and `1.2` → `usbint` and `ethext`). **[INFERRED]** There is no spare USB port. To
attach an FTDI you would displace the thumb drive or add a hub.

**4.4 The only USB accessory Moog wrote a rule for is an Ethernet dongle.**
**[READ]** `etc/udev/rules.d/30-usb-nic.rules`:

```
SUBSYSTEM=="net", ATTR{address}=="8c:ae:4c:*", ACTION=="add", RUN+="/etc/udev/rules.d/usb-ext.sh %k"
```

`8c:ae:4c` is the Plugable Technologies OUI. **[INFERRED]** Moog anticipated
users plugging a USB-Ethernet adapter into the host port and wrote a rule for
it. They wrote no such rule for an FTDI, and there are only four Moog udev rules
in total (`20-xmos-nic`, `30-usb-nic`, `40-usb-thumbdrive`, `50-eth-ext-nic`)
**[READ]**.

**4.5 Nothing invokes the tools.** **[READ]** Whole-tree `grep -arl` for each of
`find_all_pp`, `bitbang2`, `bitbang_cbus`, `bitbang_ft2232`, `baud_test`,
`serial_test` in **both** rootfs versions returns only the binaries themselves.
(`find_all` also matches `libftdi.so`, `libftdipp.so`, `serial_test` and
`libdirectfb-1.7.so.7.0.0` — the first three legitimately, the last a coincidental
symbol substring.) Nothing in `etc/init.d/*`, `etc/crontab*`, or `/var`.

**4.6 No FTDI VID appears in any Moog-authored file.** **[READ]** Every `0403`
match in the rootfs is inside the stock `etc/udev/hwdb.d/20-usb-vendor-model.hwdb`.

**Conclusion [INFERRED, high confidence]: no FTDI device is present in the Moog
One, and none is expected by any software in either firmware version.** The
correct read of the nine binaries is *not* "a bring-up toolkit for an FTDI
bridge on the instrument".

---

## 5. Why libftdi is in the image: `flashrom`

`usr/sbin/flashrom`, 334,416 bytes, **byte-identical in v1.5.0 and v1.8.2**
(md5 `46eaf6560ed9b9873b899da498a4b3d3`) **[READ]**. Version string
`0.9.9-unknown` **[READ]**; `DT_NEEDED` = `libpci.so.3`, **`libftdi.so.1`**,
`libusb-0.1.so.4`, `libusb-1.0.so.0`, `libc.so.6`; **no `DT_RPATH`** **[READ]**.

### 5.1 The compiled-in programmer table

Extracted by exact NUL-delimited string match, in file order **[READ]**:

| offset | name |
|---:|---|
| 327465 | `internal` |
| 329923 | `dummy` |
| 329979 | `gfxnvidia` |
| 329989 | `drkaiser` |
| 329998 | `satasii` |
| 330006 | `atavia` |
| 330013 | `it8212` |
| 330020 | **`ft2232_spi`** |
| 330031 | `serprog` |
| 330093 | `buspirate_spi` |
| 330140 | `dediprog` |
| 330149 | `pony_spi` |
| 330213 | `nicintel` |
| 330222 | `nicintel_spi` |
| 330235 | `nicintel_eeprom` |
| 330251 | `ogp_spi` |
| 330259 | **`linux_spi`** |
| 330298 | **`usbblaster_spi`** |
| 330313 | `pickit2_spi` |
| 330325 | `ch341a_spi` |

**Two** of these are libftdi-backed: `ft2232_spi` and `usbblaster_spi`. Absent:
`nic3com`, `nicrealtek`, `nicnatsemi`, `atahpt`, `atapromise`, `rayer_spi`,
`satamv`, `mstarddc_spi`, `digilent_spi` **[READ, exact-match scan]**.

### 5.2 The `ft2232_spi` back end in detail

**[READ]** Its device-type table, at file offsets 307635–308744:

```
jtagkey  picotap  tumpa  tumpalite  busblaster  openmoko
arm-usb-ocd  arm-usb-tiny  arm-usb-ocd-h  arm-usb-tiny-h
google-servo  google-servo-v2  google-servo-v2-legacy
```

with the vendor/product display names `FTDI` / `FT2232H` / `FT4232H` /
`FT232H`, `TIAO` / `USB Multi-Protocol Adapter` (+ ` Lite`), `Amontec` /
`JTAGkey`, `GOEPEL` / `PicoTAP`, `Google` / `Servo`, `Servo V2 Legacy`,
`Servo V2`, `OpenMoko Neo1973 Debug board (V2+)`, `Olimex` / `ARM-USB-OCD`,
`ARM-USB-TINY`, `ARM-USB-OCD-H`, `ARM-USB-TINY-H`.

Parameters **[READ]**: `port` (307832, error at 307837
`Error: Invalid channel/port/interface specified: "%s".`) and `divisor` (307893,
`Valid are even values between 2 and 131072.` at 307955). Operational messages
**[READ]**: 308000 `Using device type %s %s `, 308025 `channel %s.`, 308134
`FTDI chip type %d is not high-speed.`, 308274 `Unable to set bitmode to SPI (%s).`,
308310 `Disable divide-by-5 front stage`, 308343 `Set clock divisor`, 308362
`MPSSE clock: %f MHz, divisor: %u, SPI clock: %f MHz`, 308415
`No loopback of TDI/DO TDO/DI`, 308445 `Set data bits`.

**[INFERRED]** That is a stock, unmodified flashrom MPSSE back end: nothing in
it is Moog-specific, and the device list is the upstream list of commodity
FTDI-based JTAG/SPI dongles.

### 5.3 What that back end would be programming

The instrument's own SPI flash path is fully documented in the rootfs.

**[READ]** `usr/bin/las-sc`, two adjacent Scheme string constants at file offsets
1988880 and 1988918 (verified with `xxd -s 1988820`, which shows them separated
by the interpreter's `fe 42 00 00` string header and a length byte):

```
  -p linux_spi:dev=/dev/spidev0.0
flashrom -l /usr/share/xmosfw/las_layout -i firmware -w 
```

with 1988981 `Upgrading XMOS firmware:` and 1988841
`Update Failed (Not Enabling XMOS)` in the same neighbourhood.

**[READ]** `usr/share/xmosfw/las_layout`, 29 bytes, identical in both versions:

```
00000000:0x001BFFFF firmware
```

So the written region is `0x000000`–`0x1BFFFF` = 1,835,008 bytes (1792 KiB),
named `firmware`. The images beside it are `app_las_v2.2.2.bin` (2,097,152 bytes
= exactly 2 MiB) and `app_vx_10M_v2.2.1.bin` (164,352 bytes) in v1.8.2, and
`app_las_v2.1.2.bin` (2,097,152) / `app_vx_10M_v2.1.0.bin` (164,096) in v1.5.0
**[READ]**.

**[INFERRED]** The `-l`/`-i` pair means flashrom is given a full-chip image and
told to write only the named region, so the final 256 KiB of the 2 MiB image
(`0x1C0000`–`0x1FFFFF`) is deliberately **not** written. What lives there is
**[UNKNOWN]** to this pass; per-unit XMOS data is the obvious hypothesis and
`calibration.md` is the place to check it.

**[READ]** `usr/bin/las-sc` and `usr/sbin/flashrom` are the *only* two files in
the rootfs containing the string `flashrom`, and the only two containing
`spidev` besides `boot/imx6dl-profili-som.dtb` and `modules.builtin`.

### 5.4 The bus has two masters, and a socket for a third

This is the part that makes the FTDI back end coherent rather than random.

**[READ, `boot/imx6dl-profili-som.dtb`]** ECSPI1 is the only enabled SPI bus:

```
ecspi@02008000 {                       /* alias spi0 */
    compatible = "fsl,imx6q-ecspi","fsl,imx51-ecspi";
    status = "okay";
    fsl,spi-num-chipselects = <1>;
    cs-gpios = <phandle 0xa, 9, 0>;    /* 0xa = gpio@020a8000 = GPIO4 */
    pinctrl-0 = <phandle 0xb>;         /* ecspi1grp-2 */
  spidev@0 { compatible = "spidev"; spi-max-frequency = <0x00b71b00>; reg = <0>; };
};
```

`0x00b71b00` = 12,000,000 Hz. ECSPI2, ECSPI3 and ECSPI4 are all
`status = "disabled"` **[READ]**.

**[READ]** `ecspi1grp-2` contains exactly three pin entries, with IOMUXC mux
register offsets **0x0248, 0x0258, 0x0244** (all `mux_mode = 0`, i.e. ALT0), and
IOMUXC input-select registers 0x07dc, 0x07e0, 0x07d8. Three pins, not four —
because the chip select is the separate GPIO named in `cs-gpios`.

**[READ]** The boot log confirms the binding, warning and all:

```
spidev spi0.0: buggy DT: spidev listed directly in DT
WARNING: CPU: 0 PID: 1 at drivers/spi/spidev.c:731 spidev_probe+0x1e0/0x1fc()
...
spi_imx 2008000.ecspi: probed
```

**[READ]** `usr/bin/config-las-spi`, 1047 bytes, POSIX shell, in full-relevant
part:

```sh
# forces SPI1 pins to be GPIO inputs so that XMOS may control the bus
config_spi_xmos() {
  devmem 0x20e0244 32 5     # KEY_COL0
  devmem 0x20e0248 32 5     # KEY_COL1
  devmem 0x20e0258 32 5     # KEY_ROW0
  devmem 0x20e025c 32 5     # KEY_ROW1
  devmem 0x20a8004 32 0x40008020        # GPIO4_GDIR
  echo 0 > /sys/class/leds/XMOS_RESET_N/brightness
  echo 1 > /sys/class/leds/XMOS_RESET_N/brightness
}
config_spi_som() {
  echo 0 > /sys/class/leds/XMOS_RESET_N/brightness   # hold XMOS in reset
  devmem 0x20e0244 32 0 ; devmem 0x20e0248 32 0
  devmem 0x20e0258 32 0 ; devmem 0x20e025c 32 5
  devmem 0x20a8004 32 0x40008220        # GPIO4_GDIR
}
```

**[READ]** `etc/init.d/S25xmosfw` — despite its comment "Writes XMOS firmware to
the system as needed" — runs exactly one command: `config-las-spi xmos`.

**The cross-check closes completely, and it is worth stating explicitly because
it is the sort of thing that is usually asserted rather than proved
[INFERRED, from four READ facts]:**

* The three pads `config_spi_som` sets to ALT0 — 0x20e0244, 0x20e0248,
  0x20e0258 — are **exactly** the three `mux_reg` offsets in the DTB's
  `ecspi1grp-2`. Same three pads, same ALT0.
* The fourth pad, 0x20e025c (KEY_ROW1), stays at ALT5 (GPIO) in **both** modes —
  which is why the DTB's pin group has only three entries and the chip select is
  a GPIO instead.
* `devmem 0x20a8004` is `GPIO4_GDIR` (GPIO4 base 0x020a8000, GDIR at +4), and
  GPIO4 is the controller behind the DTB's `cs-gpios` phandle `0xa`.
* The two GDIR masks differ by exactly **0x200 = bit 9**, and the DTB's
  `cs-gpios` names **GPIO 9**. SOM mode drives the chip select as an output;
  XMOS mode releases it as an input.

**[INFERRED]** So the XMOS boot flash sits on a bus with two software-arbitrated
masters — the XMOS (normal boot, which is what `S25xmosfw` sets up) and the
i.MX6 via ECSPI1/`spidev0.0` (firmware update, after `config-las-spi som`). A
third master is possible only physically: clip an external SPI programmer onto
the flash. **`flashrom -p ft2232_spi` is precisely the tool for that third
case**, and it is the standard way to recover a board whose flash is blank —
i.e. a board that has never been programmed, or one that was bricked. That is a
coherent manufacturing story and it fits the assignment's hypothesis.

**[UNKNOWN]** Whether Moog ever actually used it. Nothing in either rootfs
records an FT2232 being used, and running `flashrom -p ft2232_spi` *on the
instrument* would be a strange arrangement (it would need the FT2232 on the
i.MX6's own USB host port *and* clipped to the flash the i.MX6 can already
reach through `spidev0.0`). The natural place for that command is a bench PC.

---

## 6. What it would take to make the nine useful

Recorded because it is the practical answer to "we found a toolkit, can we use
it", and the answer is mostly no. All **[INFERRED]** from §3.

| want | works as shipped? |
|---|---|
| Detect an FT2232H / FT232H attached to the instrument | **`find_all_pp -p 6010`** (or `-p 6014`) — yes, this is the one that works |
| Detect an FT232R | `find_all`, `find_all_pp`, `simple` — yes |
| Read an FT232R chip ID | `simple` — yes, and only on an FT232R |
| Bitbang an FT232R's 8 data pins | `bitbang`, `bitbang2` — yes |
| Bitbang an FT232R's CBUS pins | `bitbang_cbus` — yes |
| Bitbang both channels of an FT2232 | **`bitbang_ft2232` — no.** Hard-coded `0x6001`; needs a source edit, and there is no compiler on the instrument (§9) |
| Throughput-test a link | `baud_test -p i:0x0403:0x6010` — yes, `-p` reaches it |
| Use an FTDI as a UART | **`serial_test` — not with defaults.** Needs `-p 6001` or similar; the bare default opens product `0x0000` |
| Read or write an FTDI's EEPROM | **no program ships for it**, though `libftdi.so` exports the whole API |

---

## 7. The counter-thesis, which this report accepts: kitchen-sink Buildroot

Everything in §5 makes an elegant story. §7 is the reason not to believe the
strong form of it.

**[READ]** `usr/bin` holds **433** entries. Among them:

```
xeyes  xclock  xload  xconsole  xterm  oclock  xvidtune   (X11 demo clients)
gnuchess  gnuchessu  gnuchessx  lbreakout2  lbreakout2server  ltris  sl
apitrace  glretrace  eglretrace  memtester  stress  flashbench
gdb  gdbserver  gcore  strace  ltrace  blktrace  btrace  btreplay  btt
jack_metro  jack_midisine  jack_simple_client  jack_thru  jack_zombie
jack_test  jack_simdtests  jack_iodelay  jack_latent_client   (+ ~20 more)
mtdev-test  ts_test  captest  speaker-test  find_all  bitbang  serial_test
```

**[READ]** `usr/share/examples/` contains Freescale and Vivante GPU demo trees:
`fsl-samples/g2d/{multiblit,g2d_test,overlay_test}`,
`viv_samples/{es20,tiger,vdk,cl11}` with tutorial binaries, `.tga`/`.bmp`
textures and shader sources.

**[READ]** And the closing argument: `/var/lbreakout2.hscr` (229 bytes,
beginning `>>>LBreakout2`) and `/var/ltris.hscr` (223 bytes) are shipped **in the
firmware image**. Moog's production root filesystem carries Breakout and Tetris
high-score tables.

**[INFERRED]** This is a Buildroot configuration with a very large number of
packages enabled and no post-build pruning. Demo, example and test programs from
many packages are present because their packages are present. The nine libftdi
examples sit on the same shelf as `sl`, `xeyes` and `gnuchess`. They are not a
curated bring-up toolkit; they are the by-product of enabling `libftdi`, and
`libftdi` was enabled because `flashrom` can use it.

**[INFERRED, and this is the load-bearing judgement of the report]** The
`ft2232_spi` back end is therefore best read as *available*, not as *evidence of
use*. It is what you get when you build flashrom in a tree where libftdi exists.
The presence of `usbblaster_spi`, `pickit2_spi`, `ch341a_spi`, `dediprog`,
`pony_spi`, `nicintel_eeprom`, `gfxnvidia` and `drkaiser` in the same table —
programmers for Altera JTAG cables, Microchip PICkit2s, WCH dongles, and NVIDIA
graphics-card ROMs — settles it. **Nobody chose that list.** It is the default
build.

**[UNKNOWN]** Whether upstream Buildroot's `libftdi` package installs the
examples by default, or whether a Moog `.mk` override copied them. Both are
consistent with the `DT_RPATH` evidence in §2.1, which proves only that they
came from the build tree rather than from `make install`. Resolving this needs
the Buildroot tree, which is not on disk.

---

## 8. v1.5.0 vs v1.8.2: a complete, closed diff

The two firmware versions are three years and one major generation apart. The
libftdi stack did not change at all. This is proved, not asserted.

**[READ]** For all nine programs, `.rodata` is **byte-identical** between
versions, and `.text` has **identical length**. `.text` bytes differ only
because the section moved:

| program | `.text` address delta | differing 32-bit words | words *not* explained by the shift |
|---|---:|---:|---:|
| `find_all` | 0x18 | 16 | 0 |
| `find_all_pp` | 0x28 | 30 | 0 |
| `simple` | 0x18 | 15 | 0 |
| `bitbang` | 0x1c | 20 | 3 |
| `bitbang2` | 0x1c | 20 | 5 |
| `bitbang_cbus` | 0x1c | 19 | 3 |
| `bitbang_ft2232` | 0x1c | 19 | 3 |
| `baud_test` | 0x18 | 70 | 33 |
| `serial_test` | 0x18 | 27 | 0 |

**[READ]** Every "not explained" word was inspected. In `bitbang`, `bitbang2`,
`bitbang_cbus` and `bitbang_ft2232` they are all literal-pool pointers into
`.data`/`.bss`/`.got` (addresses `0x0002xxxx` and `0x0001xxxx`), which moved by a
*different* delta than `.text` because the data segment shifted independently.
In `baud_test` all 33 are `bl` instructions whose 24-bit displacement changed by
exactly `+1` word (`0xebffffc3 -> 0xebffffc4` and 32 more of the same shape) —
the PLT moved four bytes relative to `.text`.

**[READ]** The one section that genuinely grew is `.dynstr`, by **26 bytes** in
every case except `find_all_pp`, where it grew by **39**.

**[INFERRED] And 26 and 39 are exactly right.** The v1.5.0 build-path prefix
`/home/las-ci-builds/6c53963c/0/moogmusic/las-buildroot` is 54 characters; the
v1.8.2 prefix `/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot`
is 67. A difference of **13** per occurrence. `DT_RPATH` contains the prefix
twice in eight of the nine programs (2 × 13 = 26) and **three times** in
`find_all_pp`, which has the extra `ftdipp/.libs` component (3 × 13 = 39).

The libraries close the same way **[READ]**:

| library | `.text` | `.rodata` | `.dynstr` |
|---|---|---|---|
| `libftdi.so.1.20.0` | **identical** | **identical** | +13 |
| `libusb-0.1.so.4.4.4` | **identical** | **identical** | +13 |
| `libftdipp.so.1.20.0` | differs (relocation only) | +13 | +26 |

**[READ]** `libftdipp`'s `.rodata` difference is one string and one string only —
a `__FILE__` from a Boost assertion:

```
1.5.0: /home/las-ci-builds/6c53963c/0/moogmusic/las-buildroot/output/host/usr/
       arm-buildroot-linux-gnueabihf/sysroot/usr/include/boost/smart_ptr/shared_ptr.hpp
1.8.2: /home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/host/usr/
       arm-buildroot-linux-gnueabihf/sysroot/usr/include/boost/smart_ptr/shared_ptr.hpp
```

Same 13-byte delta.

**[READ]** `usr/sbin/flashrom` is byte-identical between versions
(`46eaf6560ed9b9873b899da498a4b3d3`) — it has no `DT_RPATH`, so nothing in it
carries the build path and nothing changed. `usr/lib/libusb-1.0.so.0.1.0` is
also byte-identical (`d279c652de6c67451edd35e32dd88a97`).

**Conclusion [INFERRED, and about as firm as static analysis gets]:** between
v1.5.0 and v1.8.2 the *only* change to the entire libftdi/libusb/flashrom stack
is that Moog's CI job moved from `.../6c53963c/0/moogmusic/...` to
`.../glrt-t3_/0/moog/hardware/moog-one/...`. Not one instruction of behaviour
changed. The stack was compiled by the same frozen toolchain and nobody has looked at it
since 2022. **[READ]** flashrom's version banner, at file offsets 327266-327281,
reads `3.4.1` / ` GCC` / `4.8.5` — libpci 3.4.1 and **GCC 4.8.5**, verified with
`xxd -s 327250`.

---

## 9. Safety notes

For whoever picks this up next. All **[INFERRED]** from §3 unless marked.

* **`config-las-spi som` without the matching `xmos` leaves the XMOS in reset**
  — no audio, no MIDI, no network on `usbint`/`ethext`. `DANGER.md:158` already
  documents this; it is repeated here because §5.4 is the section that makes
  somebody want to try it.
* **`bitbang`, `bitbang2`, `bitbang_cbus` and `bitbang_ft2232` are output
  drivers.** They call `ftdi_set_bitmode(ctx, 0xFF, BITMODE_BITBANG)`, which
  makes all eight data pins push-pull outputs, and then drive them. Run against
  a device wired to something that is also driving those lines, that is a
  contention fault. `bitbang2` additionally **never disables bitbang mode before
  closing** **[READ]** — it leaves the pins driven.
* **`bitbang` runs for ≈134 s and `bitbang_ft2232` for ≈92 s** with no way to
  shorten them; only `serial_test` traps `SIGINT` **[READ]**.
* **`find_all`, `find_all_pp` and `simple` are read-only** — enumerate, open,
  query, close. These are the safe three.
* Project rule 2 stands regardless: do not execute Moog binaries. These nine are
  not Moog binaries, but they are on the instrument and they touch hardware.
* **[READ]** There is no compiler, assembler, linker, `make`, `perl` or `python`
  anywhere in `bin` or `usr/bin`. Anything that needs a source change to these
  programs — `bitbang_ft2232` above all — has to be cross-built off the
  instrument.

---

## 10. Conflicts with existing docs

Reported, not fixed, per project rule 4.

**10.1 `gap-observability-toolkit.md:457` — no conflict, but incomplete.** It
lists `baud_test` and `serial_test` in a bare "adjacent tooling" sweep. Both are
correctly placed. The other seven of the nine — `find_all`, `find_all_pp`,
`simple`, `bitbang`, `bitbang2`, `bitbang_cbus`, `bitbang_ft2232` — are in the
same `usr/bin` and were missed. Suggest the list be extended rather than
corrected.

**10.2 `gap-uboot-env-and-flash-fuse-tooling.md:846` — incomplete and slightly
misnamed.** It gives flashrom's programmer list as "`internal`, `dummy`,
`nicintel`, `nicintel_eeprom`, `gfxnvidia`, `drkaiser`, `ft2232_spi`,
`buspirate_spi`, `dediprog`, `ch341a_spi`, `pony`, `ogp`, and … `linux_spi`".
Against the exact-match scan in §5.1: the actual names are **`pony_spi`** and
**`ogp_spi`**, and the list omits `satasii`, `atavia`, `it8212`, `serprog`,
`nicintel_spi`, `pickit2_spi` and — most relevant here — **`usbblaster_spi`**,
which is the *second* libftdi-backed programmer in the binary. That omission
matters because a reader could conclude `ft2232_spi` is the sole reason libftdi
is linked, and therefore that Moog specifically wanted FT2232 support.

**10.3 A caution about `runtime-state.txt`, for the caveat file's row list.**
`captures/arch-harvest/CAVEAT-runtime-state.md` states that the snapshot
"remains valid evidence for … the USB device tree". **[READ]** It is not: the
`--- usb ---` section of `runtime-state.txt` is empty, and so is
`--- modules ---` apart from the `lsmod` header. The capture command's
`cat … | head -40 || lsusb` construction meant the fallback never ran. The
snapshot contains no USB device inventory at all. Suggest the caveat file drop
"the USB device tree" and "`lsmod`" from its list of things the snapshot can
still be trusted for, and that anything relying on it be re-sourced to
`dmesg-before-reboot.txt`.

**10.4 No conflict** with `DANGER.md:57`, `MOOG-ONE-INTERNALS.md:166/1458`,
`firmware/kernel.md:815`, `firmware/init-boot.md:524/539` or
`firmware/calibration.md:1247` — every claim they make about `config-las-spi`,
`spidev0.0`, the ECSPI1 device-tree node and the flashrom `linux_spi` command
line was independently re-derived in §5.3 and §5.4 and matches.

---

## 11. Validation plan

**READ-ONLY commands, proposed, NOT run.** The instrument was not contacted.
None of these writes anything, opens a USB device, or touches SPI. A human may
run them.

Confirm the nine are present and unchanged from the 1.8.2 image:

```sh
ls -l /usr/bin/{find_all,find_all_pp,simple,bitbang,bitbang2,bitbang_cbus,bitbang_ft2232,baud_test,serial_test}
md5sum /usr/bin/{find_all,find_all_pp,simple,bitbang,bitbang2,bitbang_cbus,bitbang_ft2232,baud_test,serial_test}
```

Expected on a v1.5.0 instrument, the md5s in §8's 1.5.0 column
(`2fe227c73f050964c8c54dc0b98fee0d` for `find_all`, and so on). If they match,
§8's diff analysis is confirmed against the live machine.

Confirm no FTDI is or ever was attached, and no serial driver could claim one:

```sh
cat /sys/kernel/debug/usb/devices 2>/dev/null || echo "debugfs not mounted"
lsusb
ls -l /sys/bus/usb/devices/
ls -l /dev/ttyUSB* 2>&1
ls /sys/bus/usb-serial/drivers/ 2>&1
grep -c ftdi /lib/modules/$(uname -r)/modules.builtin
dmesg | grep -iE 'usb (serial|[0-9]-[0-9])|ftdi'
```

Expected **[INFERRED]**: no `0403:` line; no `/dev/ttyUSB*`; `usb-serial/drivers`
containing only `generic`; `grep -c ftdi` returning `0`. Note that this
instrument's `lsusb` is a busybox applet **[READ]** and there is no `usb.ids` in
the image **[READ]**, so it prints IDs without names — which is fine, the ID is
what matters. Note also that mounting debugfs is a *write* to the mount table;
if it is not already mounted, skip the first command rather than mounting it.

Confirm the SPI bus arbitration state without changing it:

```sh
ls -l /dev/spidev*
cat /sys/class/leds/XMOS_RESET_N/brightness
devmem 0x20e0244 32 ; devmem 0x20e0248 32 ; devmem 0x20e0258 32 ; devmem 0x20e025c 32
devmem 0x20a8004 32
```

Expected in normal operation **[INFERRED from `S25xmosfw` running
`config-las-spi xmos` at boot]**: brightness `1`, the four IOMUXC registers
reading `5`, and `GPIO4_GDIR` = `0x40008020`. **`devmem` with one argument is a
read**; do not add a third argument. (See `docs/arch/cal-dispatch.md` and
`d9c2d3d` — the project has already settled that a one-argument `devmem` reads.)

Confirm nothing invokes the nine:

```sh
grep -rl -e find_all -e bitbang -e baud_test -e serial_test /etc /var 2>/dev/null
```

Expected: no output.

---

## 12. Not covered by this pass

* **The upstream diff.** No `libftdi-0.20` source tree is on disk, so "these are
  unmodified upstream examples" rests on the absence of Moog strings, the
  build-tree `DT_RPATH`, and the v1.5.0/v1.8.2 identity — not on a line-by-line
  comparison. Fetching libftdi 0.20 and rebuilding for `armv7-none-linux-gnueabihf`
  would settle it, and would in particular settle whether `bitbang_ft2232`'s
  `0x6001` is upstream's bug or Moog's.
* **Whether Buildroot's `libftdi` package installs examples by default.** Needs
  the Buildroot tree. Determines whether §7's thesis is complete or whether a
  Moog `.mk` override deliberately placed them.
* **The last 256 KiB of the XMOS flash** (`0x1C0000`–`0x1FFFFF`), excluded by
  `las_layout` and therefore never rewritten by the in-system update path.
  Contents **[UNKNOWN]**; `calibration.md` is the right place.
* **The physical flash part** — manufacturer, capacity, package, and whether it
  is on a clip-accessible SOIC-8 or a bare BGA. This determines whether the
  `ft2232_spi` bench path is even physically available. Not answerable from the
  rootfs; needs the board.
* **`usbblaster_spi`.** Noted as a second libftdi consumer, not analysed.
* **The `serprog`, `buspirate_spi` and `ch341a_spi` back ends**, which give
  flashrom three more external-programmer routes to the same flash and were not
  examined.
* **`usr/bin/lasfwu`** (33,940 bytes) and the `/mnt/fwu` partition, which are the
  *other* firmware-update path and were out of scope here.
* **The two enabled-but-unclaimed UARTs.** `serial@02020000` (ttymxc0) and
  `serial@021ec000` (ttymxc2) are `status = "okay"` in the DTB with pin groups
  assigned **[READ]**, `ttymxc1` is the console **[READ, kernel cmdline]**, and the
  string `ttymxc` appears **zero** times anywhere in the root filesystem
  **[READ, `grep -arc` over the whole tree, no non-zero count]**, so nothing in
  userland opens any of them. Two muxed, powered, unused UARTs on a board with no FTDI is a more
  interesting bring-up-header lead than the nine binaries this report was sent
  to examine, and nothing has looked at them.
