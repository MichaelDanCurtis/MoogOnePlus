# `recv_image`: the multicast, FEC-coded, raw-MTD image receiver nobody opened

**Gap report.** `usr/sbin/recv_image` is a complete over-the-network flash-image
receiver present in both firmware filesystems and referenced by **zero** prior
reports. This document reads it out of the binary, places it against the
documented `lasfwu` update path, and settles what it can and cannot do **on this
hardware**.

Scope rule for this file: I wrote only this file. Nothing was run against the
instrument. Every binary claim is read on macOS with `strings`, `xxd`,
`shasum`, `cmp`, `file`, and
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`. Each claim is graded
`[READ]` (quoted from a file, with offset/line), `[INFERRED]` (reasoning, with
the evidence named), or `[UNKNOWN]`.

Paths are relative to
`captures/firmware-1.8.2/rootfs-1.8.2/` (the decrypted v1.8.2 rootfs) unless the
text says `rootfs-1.5.0/` (the owner's v1.5.0) or `captures/`.

---

## 0. Headline

`recv_image` is the stock **mtd-utils `recv_image`** (the companion to
`serve_image` / `mcast_image`): a UDP-multicast, forward-error-corrected bulk
**flash writer** that joins a multicast group, reassembles an MTD image from
FEC-coded packets, and erases-and-writes it block-by-block to a raw MTD
character device. It is a **second, entirely distinct image-deployment path**
from the documented one (`lasfwu`: local gpg-decrypt + `dd` of an ext4 image to
an eMMC partition). [READ strings + disassembly]

Three facts bound its real-world relevance on the Moog One:

1. **It is unwired.** No init script, cron entry, `inetd.conf` line, or other
   binary in either filesystem references it; its companion sender `serve_image`
   is not present. It is a dormant factory/provisioning tool, not part of the
   running system. [READ — greps below]
2. **Its primary target does not exist on this board.** The boot log reports
   *no* MTD device: NAND absent, GPMI-NAND probe failed `-ENODEV`, and the SPI
   bus is bound to `spidev` (raw userspace SPI), not an `spi-nor`/MTD. Storage is
   eMMC (`mmcblk2`). With no `/dev/mtd*`, `recv_image`'s MTD path has nothing to
   open; only its fallback "write to a plain file" mode could run. [READ dmesg +
   INFERRED]
3. **It is byte-identical in 1.5.0 and 1.8.2** (same SHA-256), so nothing about
   it changed across the window this project studies. [READ — `shasum`/`cmp`]

It still matters, and this report is worth its length, because it is a
ready-made raw-flash writer that **joins a multicast group and writes whatever
arrives** — a different trust surface from `lasfwu`'s gpg-gated path — and
because it is the only place in the firmware that performs FEC-coded network
reception. A reviewer auditing the update/provisioning story needs it on the
map.

---

## 1. Provenance and identity

### 1.1 File facts **[READ]**

| | v1.8.2 | v1.5.0 |
|---|---|---|
| path | `usr/sbin/recv_image` | `rootfs-1.5.0/usr/sbin/recv_image` |
| size | 15,232 B | 15,232 B |
| SHA-256 | `18aee28e…b0b11df` | `18aee28e…b0b11df` (identical) |
| `file` | ELF 32-bit LSB, ARM EABI5, dynamically linked, interp `/lib/ld-linux-armhf.so.3`, for GNU/Linux 2.6.32, **stripped** | same |

`cmp -l` between the two reports **0 differing bytes** — the two binaries are the
same file; only the archive mtime differs (2022-05-16 vs 2025-09-15, an artifact
of repackaging). [READ]

### 1.2 Toolchain / platform fingerprint **[READ]**

- `.note.ABI-tag` → `GNU`, minimum kernel `2.6.32` (file offset `0x150`).
- `.ARM.attributes` → `aeabi`, CPU name **`Cortex-A9`** (file offset `0x3654`:
  `…aeabi…\x05Cortex-A9…`). The i.MX6 DualLite is a Cortex-A9, so the build
  target is consistent with this board. [READ + INFERRED]
- Single `DT_NEEDED`: `libc.so.6`, versioned `GLIBC_2.4`. No other shared libs —
  no OpenSSL, no libmtd, no gpg. FEC and CRC are **statically compiled in**.
  [READ — `llvm-objdump -p`]

### 1.3 It is part of a coherent mtd-utils 1.5.2 drop **[READ / INFERRED]**

`usr/sbin` ships the whole mtd-utils suite built at version `1.5.2`
(`mtdinfo`, `flash_erase`, `nandwrite`, `ubiformat`, … all print `1.5.2`).
`recv_image` is the mtd-utils program of the same name, shipped in the same
package set. [READ version strings in the siblings; INFERRED that `recv_image`
came from the same 1.5.2 package because it is the mtd-utils program by that
name and lives beside them.]

### 1.4 Dynamic-symbol surface **[READ — `llvm-objdump -T`]**

`socket, bind, setsockopt, getaddrinfo, gai_strerror` (network);
`open64, pread64, pwrite64, read, close, ioctl` (device I/O);
`malloc, free, memset, memcpy, memcmp` (buffers);
`printf, fprintf, fputs, puts, putchar, perror, fflush, gettimeofday` (progress);
`raise, abort, exit, __libc_start_main`. That is the complete external contract:
**sockets in, raw device/file I/O out, no crypto, no TLS, no signature check.**
[READ]

---

## 2. What it does — the capability, read out of the binary

### 2.1 Usage and argument contract **[READ]**

`.rodata` (file offset `0x2a2c`): `usage: %s <host> <port> <mtddev>`.
`_start` at vaddr `0x10818` compares `argc` to **4** (`cmp r0, #4` at `0x1082c`);
on mismatch it prints the usage string and exits. So the invocation is:

    recv_image <host/group> <port> <mtddev>

- `argv[1]` — the address to `bind()` to (a multicast group address to join, or
  any local address for unicast). [READ + INFERRED from the bind/join logic in
  §2.3]
- `argv[2]` — UDP port. [READ — `getaddrinfo(host, port, …)`]
- `argv[3]` — the MTD character device (e.g. `/dev/mtd3`) **or**, if that open
  fails, a path to create as a plain output file. [READ — §2.2]

### 2.2 Target open: MTD device first, plain file as fallback **[READ]**

At `0x10854` it calls `open64(argv[3], 2)` — `O_RDWR` on the existing path.

- **If open succeeds** (fd ≥ 0): it issues `ioctl(fd, MEMGETINFO, …)` at
  `0x10870`. MEMGETINFO is the MTD "get device info" ioctl; the `MEMGETINFO`
  string is at `.rodata 0x2a59`. On success it prints
  `Receive to MTD device %s with erasesize %d` (`0x2a64`) and takes the **MTD
  path** — the erasesize comes from the device. On ioctl failure it `perror`s
  `open` and `abort()`s. [READ]
- **If the initial open fails** (fd < 0): at `0x108b4` it re-opens with
  `open64(argv[3], 0x242, 0644)` — `O_RDWR|O_CREAT|O_TRUNC`, mode `0644` — i.e.
  it **creates a regular file**, prints
  `Receive to file %s with (assumed) erasesize %d` (`0x2a95`), and uses an
  **assumed erasesize of 131072 (128 KiB)** (`mov r2, #131072` at `0x108dc`,
  stored as the working block size). [READ — flag/mode decode: `0x242 =
  O_RDWR|O_CREAT|O_TRUNC`, `420 = 0o644`]

Consequence: pointed at a device node it flashes; pointed at a non-existent
path it lands a reconstructed image file on disk. This fallback is what makes it
still *runnable* on a board that has no MTD (see §5).

### 2.3 Socket setup: it actually joins a multicast group **[READ]**

`getaddrinfo(argv[1], argv[2], &hints)` with `ai_socktype` set (hints built on
the stack at `0x10984`–`0x1099c`); on error it prints `getaddrinfo: %s`
(`0x2b0c`) via `gai_strerror`. It then walks the addrinfo list, `socket()`s, and:

- **IPv4 branch** (`ai_family == 2`, `AF_INET`, at `0x10a04`): it byte-swaps the
  bound address and tests the **top nibble**: `and r2, r2, #0xF0000000`
  (`0x10a14`) then `cmp r2, #0xE0000000` (`0x10a18`). `224.0.0.0/4` is the IPv4
  multicast range, so it only does the next step for a multicast address. It
  then `setsockopt(fd, level 0 (IPPROTO_IP), optname 35, …)` at `0x10a3c` —
  **optname 35 is `IP_ADD_MEMBERSHIP`** (the `IP_ADD_MEMBERSHIP` string is at
  `0x2b1d`), i.e. it **joins the multicast group**. On failure it prints that
  string and aborts. [READ]
- **IPv6 branch** (`ai_family == 10`, `AF_INET6`, at `0x10a50`): checks the first
  address byte `== 0xFF` (IPv6 multicast prefix) and
  `setsockopt(fd, level 41 (IPPROTO_IPV6), optname 20, …)` at `0x10a8c` —
  **optname 20 is `IPV6_ADD_MEMBERSHIP`** (string at `0x2b2f`). [READ]
- Then `bind(fd, ai_addr, ai_addrlen)` at `0x10aa8`; on failure, `perror("bind")`
  (`0x2b43`) and abort. [READ]

So it genuinely supports group membership for IPv4 and IPv6 multicast, and falls
through to a plain unicast `bind` when the address is not multicast. [READ +
INFERRED]

### 2.4 Packet format: a 40-byte header + 2820-byte payload **[READ offsets / INFERRED layout]**

The receive buffer is at `sp+0x104`. Each `read(fd, buf, 0xb2c)` expects exactly
**`0xb2c` = 2860 bytes**; a short/long read prints
`Wrong length %zd bytes (expected %zu)` (`0x2b54`) and is discarded. [READ —
length compare at `0x10af4`/`0x10b38`, message at `0x11558` region]

2860 − **2820** (`0xb04`, the payload `memcpy` size used throughout, e.g.
`0x10e18`, `0x11720`) = **40 bytes of header = 10 × `uint32_t`**, all in network
byte order (every field is passed through `rev` before use). [READ sizes +
INFERRED that the 40-byte remainder is a 10-word header]

Two header words are pinned **directly from the code** (buffer base `sp+0x104` =
word 0):

- **word 3** (`sp+0x110`, byte offset 12) = **erasesize / blocksize.** At
  `0x10b48` it is `rev`-swapped and compared to the working block size
  (`sp+0xcc`, from MEMGETINFO or the 128 KiB assumption); mismatch prints
  `Erasesize mismatch (0x%x not 0x%x)` (`0x2b7b`) and aborts. [READ]
- **word 2** (`sp+0x10c`, byte offset 8) = **total number of eraseblocks.** At
  `0x10b74` it is `rev`-swapped and stored (`sp+0x30`), then used to `malloc`
  `nr_blocks × 0x1014` bytes of per-block bookkeeping (`0x10bac`) and as the
  bound behind `Erroneous block_nr %d (> %d)` (`0x2c48`). [READ + INFERRED that
  this word is the total block count]

The remaining header words carry the resend flag, the whole-image CRC
(`totcrc`), the per-block CRC, the block number, the packet-within-block index,
and the FEC group/packet counts. I read the **bytes they occupy and the
byte-swaps**, but I mark the *field meanings* `[INFERRED]`: they match the
upstream mtd-utils `mcast_image.h` `image_pkt_hdr`, and the code's use of them
(see §2.5–2.6) is consistent with that layout, but I did not prove each name from
this stripped binary alone. [INFERRED]

### 2.5 Reassembly, CRC, and the FEC decoder **[READ]**

- **CRC-32 (IEEE, zlib polynomial).** A 256-entry table sits at `0x12f6c`; its
  first entries are `00000000, 77073096, ee0e612c, 990951ba` and `t[255] =
  2d02ef8d` — the standard zlib/PNG CRC-32 table. The routine at `0x11a88` is the
  classic table-driven `crc32(crc, buf, len)`. [READ constants]
- It tracks a per-image `totcrc`; if a later packet reports a different image
  CRC it prints `Image CRC changed from 0x%x to 0x%x. Aborting` (`0x2c18`) and
  stops. Per-packet CRC failures print `Discard %08x pkt %d with bad CRC (%08x
  not %08x)` (`0x2c67`) and drop the packet. Per-block CRC failure after decode
  prints `CRC mismatch for block #%d: want %08x got %08x` (`0x2ddc`). [READ]
- **Forward error correction = Reed–Solomon over GF(2⁸), Luigi Rizzo's `fec.c`.**
  `fec_new(k, n)` is at `0x11e50`: it validates `k ≤ 256 && n ≤ 256 && k ≤ n`,
  else prints `Invalid parameters k %d n %d GF_SIZE %d` (`0x133c4`) with
  GF_SIZE 255; it builds `gf_exp`/`gf_log` tables from the primitive polynomial
  whose bit-string literal **`"101110001"`** is at `0x133ba` (x⁸+x⁴+x³+x²+1, the
  standard GF(256) generator). The Gaussian-elimination decoder at `0x121fc`
  carries Rizzo's exact diagnostic strings: `singular matrix`, `XXX pivot not
  found!`, `AARGH, indxr[col] %d`, `indxc`, `indxr`, `ipiv`. On decoder failure
  the receiver prints `The world is broken. fec_decode() returned error`
  (`0x2dab`) and aborts. [READ — these strings and the `101110001` literal are
  the fingerprint of Rizzo FEC as used in mtd-utils]

### 2.6 Writing to flash: erase, write, read-back verify, bad-block handling **[READ]**

Once a block's packets are present it is FEC-decoded and committed to the target
via raw MTD ioctls and `pwrite64`:

- Before writing, the block is erased: `ioctl(fd, MEMERASE, &erase_info)` —
  `MEMERASE` string at `0x2d42`, used at `0x10f60`/`0x113a8`/`0x11424`. Progress
  prints `Erasing block at %08x...` (`0x2e0d`). [READ]
- The decoded data is written with `pwrite64` (e.g. `0x11054`); a short write
  prints `short write of decoded data` (`0x2e70`) / `packet write` errors
  (`0x2ce2`, `0x2cf0`). [READ]
- It **reads the data back** with `pread64` (`0x111c0`) and re-CRCs it; if what
  was written is unreadable it prints `Packets we wrote to flash seem to be
  unreadable. Aborting` (`0x2d70`). [READ]
- **Bad-block avoidance:** on a failed write/erase it advances past the bad
  block — `Skipping flash bad block at %08x` (`0x2bf6`), `Will erase at %08x len
  %08x (bad write was at %08x)` (`0x2d0d`), `Erasing failed block at %08x`
  (`0x2e8e`), `Block #%d will now be at %08lx` (`0x2d4b`), `Will try again at
  %08lx...` (`0x2eac`). If it runs past the end it prints `Run out of space on
  flash` (`0x2bdb`). [READ]
- It also erases stale FEC scratch: `Erase to clean FEC data from flash failed.
  Aborting` (`0x2e27`). [READ]

### 2.7 Progress and timing accounting **[READ]**

Live line: `Received %d/%d (%d%%) in %lds @%ldKiB/s, %d lost (%d%%), %d dup/xs`
(`0x2c9a`). Final per-phase timing: `Net rx`, `flash rd`, `FEC time`, `CRC time`,
`flash wr`, `flash er`, each `%ld.%03lds` (`0x2eec`–`0x2f55`), computed from
`gettimeofday` deltas. This is a faithful mtd-utils `recv_image` with no Moog
customization visible in strings or control flow. [READ + INFERRED]

---

## 3. How it is (not) wired into the system

Every search below is over both filesystems and all prior docs.

- **No script or service references it.** Grepping the whole 1.8.2 rootfs for
  `recv_image` (text + binary) matches **only the binary itself**. Nothing in
  `etc/init.d/*` (`S01…S99`), `etc/inittab`, `etc/crontab/{root,cron.update}`,
  `etc/inetd.conf` (empty), or any `S*`/`rc*` script invokes it. The
  flash/MTD-tool greps over `etc/`, `usr/bin`, `usr/sbin`, `sbin` find only the
  splash `dd` and the urandom-seed `dd` — never `recv_image`. [READ]
- **No other binary references it.** `las-sc`, `las-frontend`, `lasfwu` (the
  33,940-byte bash updater) contain no `recv_image` / `serve_image` / `mcast`
  string. [READ — `strings | grep`]
- **Its sender is absent.** `serve_image` (the mtd-utils multicast *sender*) is
  not present in either filesystem. The only hits for `serve_image`-like strings
  are inside `tcpdump` and `busybox` (unrelated generic substrings). [READ]
- **No multicast listener at runtime.** The (contaminated, but valid for
  sockets) `runtime-state.txt` netstat shows the expected LAS ports
  (57110/57120 scsynth, 9300 loopback control, 9500/9600, avahi 5353, dropbear
  22, the 8080 HTTP surface) — **no `recv_image` process and no group-membership
  socket bound to its port.** [READ — `captures/arch-harvest/runtime-state.txt`;
  see `captures/arch-harvest/CAVEAT-runtime-state.md` — sockets/interfaces are in
  the caveat's "still valid" list]

**Conclusion.** `recv_image` is a dormant, manually-invoked tool. For it to do
anything, a root operator (or a root-capable automation — e.g. the `las-dwm`
reverse-SSH phone-home documented in `small-binaries.md §2.2`, or `lassvc`'s
dropbear) would have to launch it by hand and a `serve_image` host would have to
be multicasting a matching image. [INFERRED — from the total absence of any
autostart wiring and the missing sender]

---

## 4. Where it sits relative to the documented update path

The firmware's **documented** update mechanism is `usr/bin/lasfwu` (see
`docs/firmware/init-boot.md §8` and `docs/firmware/lassvc.md`): a bash script
that extracts a gpg key steganographically from `/etc/bob.bmp` (`str … 4`),
`gpg --import`s it, `gpg --decrypt`s the uploaded image with passphrase `bob`
to `…ext4`, `gpg --verify`s a detached signature, and `dd`s the verified ext4
image onto the **inactive eMMC A/B slot** (`/dev/mmcblk2p2` or `p3`). [READ —
`usr/bin/lasfwu:49,637-686,396-398,473-528`; corroborated by `init-boot.md`]

`recv_image` is **orthogonal** to that in every dimension:

| | `lasfwu` (documented) | `recv_image` (this report) |
|---|---|---|
| transport | local file staged to `/mnt/fwu` | **UDP multicast over the network** |
| coding | none (whole ext4 image) | **FEC (Reed–Solomon GF(256)) + CRC-32** |
| authentication | **gpg decrypt + detached-signature verify** | **none** — writes whatever arrives that passes CRC/FEC |
| target | eMMC partition via `dd` (`/dev/mmcblk2p{2,3}`) | **raw MTD char device** via MEMERASE/`pwrite` (or a plain file) |
| A/B awareness | yes (writes the inactive slot) | no — writes the device it is told to |
| wiring | invoked by the update UI flow | **nothing invokes it** |

They are not two implementations of one feature; they are two different
capabilities. `lasfwu` is the product update path. `recv_image` is a
**factory/line-provisioning-shaped** bulk flasher: the mtd-utils mcast pair is
designed to image many devices at once from one sender over a LAN segment.
[INFERRED — from the capability shape and the missing local sender]

This is the sense in which it "touches the trust story": it is an **unsigned**,
network-fed raw-flash writer sitting on disk next to a carefully signed update
path. It is neutered on the running system by §3 (nothing starts it) and §5 (no
MTD target), but a reviewer weighing the provisioning/trust surface should know
it exists, because its own code performs **no authentication of the image
source** — only integrity (CRC) and erasure (FEC) checks. [INFERRED — the
dynamic-symbol table has no crypto/TLS; the control flow verifies CRC and FEC
only]

---

## 5. Does its primary path even have a target on this board? No.

`recv_image`'s headline behavior is writing to a raw **MTD** device. The Moog
One's i.MX6 DualLite has **no MTD device** in the boot this project captured:

- `nand: No NAND device found` and `gpmi-nand 112000.gpmi-nand: driver
  registration failed: -19` (`-ENODEV`) — no NAND. [READ —
  `captures/dmesg-before-reboot.txt:154-155`]
- The SPI controller comes up, but `spidev spi0.0: buggy DT: spidev listed
  directly in DT` — the device tree exposes the SPI device as **`spidev`**
  (raw userspace SPI), **not** as an `spi-nor`/`m25p80` MTD. So no MTD is
  registered from SPI either. [READ — `dmesg…:156-158`]
- Storage is **eMMC**: `mmcblk2` (7.21 GiB) with partitions `p1..p7`, rootfs on
  `mmcblk2p3`, no MTD partitions anywhere in the log. [READ — `dmesg…:241-245`,
  and `root=/dev/mmcblk2p3` on the kernel cmdline]

**Therefore:** pointed at any `/dev/mtd*` on this instrument, `recv_image`'s
`open64(argv[3], O_RDWR)` has nothing to open; it would fall through to its
**file-create** branch (§2.2) and write a reconstructed image to a file at that
path, using the assumed 128 KiB erasesize. The genuine raw-flash-write capability
is real in the binary but has **no device to act on** here. [INFERRED — from the
dmesg MTD-absence plus the open/fallback logic I read in §2.2]

(Static `/dev/` in the extracted rootfs is only a 3-entry skeleton — `log`,
`pts`, `shm` — because real `/dev` is devtmpfs at runtime, so the *absence of
`mtd` nodes in the tarball* is not itself evidence; the **dmesg** is the
authority, and it shows no MTD subsystem came up. [READ + INFERRED])

---

## 6. Summary of graded claims

| # | claim | grade | evidence | load-bearing |
|---|---|---|---|---|
| 1 | `recv_image` is the mtd-utils multicast FEC MTD-image receiver | READ | usage/strings `0x2a2c`+; Rizzo FEC `101110001` `0x133ba`; MEMERASE/MEMGETINFO | yes |
| 2 | present & byte-identical in 1.5.0 and 1.8.2 (same SHA-256, `cmp`=0) | READ | `shasum`/`cmp` §1.1 | yes |
| 3 | absent from all 32 prior docs and from every script/binary/service | READ | greps §3 | yes |
| 4 | no authentication of image source — CRC/FEC integrity only, no crypto libs | READ+INFERRED | `llvm-objdump -T` (no TLS/crypto); control flow §2.5–2.6 | yes |
| 5 | joins IPv4/IPv6 multicast groups (IP_ADD_MEMBERSHIP / IPV6_ADD_MEMBERSHIP) | READ | setsockopt optname 35/20, nibble test `0xE0000000` §2.3 | yes |
| 6 | opens MTD device first, falls back to creating a plain file (128 KiB assumed) | READ | `0x10854`/`0x108b4`, flags decode §2.2 | yes |
| 7 | this board has no MTD device; eMMC only → MTD path has no target here | READ+INFERRED | dmesg §5 | yes |
| 8 | orthogonal to `lasfwu` (transport/coding/auth/target all differ) | READ+INFERRED | §4 table vs `lasfwu` reads | yes |
| 9 | its sender `serve_image` is not present in either filesystem | READ | grep §3 | medium |
| 10 | packet = 40-byte (10-word) header + 2820-byte payload; word3=erasesize, word2=nr_blocks | READ offsets / INFERRED field names | §2.4 | medium |
| 11 | part of a coherent mtd-utils 1.5.2 package drop | READ+INFERRED | sibling version strings §1.3 | low |

---

## 7. Validation plan (READ-ONLY; for a human to run on the instrument)

I did not and must not touch the instrument. These are **read-only** checks a
human could run to confirm the load-bearing claims. None writes, flashes, joins a
group, or launches `recv_image`.

1. **Confirm no MTD subsystem (claim 7):**
   `cat /proc/mtd` → expect "No such file or directory" or empty.
   `ls -l /dev/mtd*` → expect none.
   `dmesg | grep -iE 'mtd|nand|gpmi|spi-nor'` → expect the NAND-absent / GPMI
   `-19` lines seen in the capture.
2. **Confirm it is not running and no group is joined (claim 3):**
   `ps w | grep -i recv_image` → expect none.
   `netstat -g` (or `ip maddr show`) → expect only link-local/mDNS groups, none
   on `recv_image`'s port.
3. **Confirm on-disk identity (claims 1–2):**
   `sha256sum /usr/sbin/recv_image` → expect
   `18aee28efa9116f642059c989e1dcd474607d49b496a52ae968c490af90b11df`.
   `strings /usr/sbin/recv_image | grep -E 'usage|MEMERASE|fec_decode|101110001'`.
4. **Confirm nothing references it (claim 3):**
   `grep -rIl recv_image /etc /usr/sbin /usr/bin /sbin 2>/dev/null` → expect only
   `/usr/sbin/recv_image`.

Do **not** execute `/usr/sbin/recv_image` with any arguments — per this project's
standing rule about Moog binaries ignoring/overloading their arguments, and
because its very purpose is to erase-and-write flash.

---

## 8. Conflicts with existing docs

No contradictions found. `recv_image` is simply **uncovered** by the existing
corpus:

- `docs/firmware/small-binaries.md` documents the `usr/bin` helpers ("ten helpers
  never read") and does not cover the `usr/sbin` mtd-utils suite; it never
  mentions `recv_image`. No conflict — this report is complementary. [READ]
- `docs/firmware/init-boot.md §8` and `docs/firmware/lassvc.md` describe `lasfwu`
  as the update path; nothing there claims it is the *only* image-writer, so §4
  here adds a path rather than overturning a claim. [READ]
- `docs/firmware/network.md`, `docs/arch/doc-audit.md`, and
  `docs/firmware/diff-binaries.md` contain no `recv_image` / `mcast` /
  `serve_image` / `mtd-utils` mention. [READ — greps returned nothing]

The one thing a reader might *expect* and not find: this report does **not**
change any existing claim about `lasfwu`, the A/B scheme, or the eMMC layout. It
sits beside them.

---

## 9. Still open / unexplored

- **Exact meaning of header words 0,1,4–9** (`totcrc`, resend flag, per-block
  CRC, block/packet indices, FEC group counts). I read their byte positions and
  the byte-swaps but graded the field *names* `[INFERRED]` against upstream
  mtd-utils `mcast_image.h`. Proving each from this stripped binary would need
  fuller dataflow tracing. [UNKNOWN at READ grade]
- **Whether Moog ever shipped a `serve_image`** on a factory provisioning host.
  Not answerable from these filesystems — the sender is absent. [UNKNOWN]
- **The FEC group geometry `(k, n)` the sender uses.** `fec_new` accepts any
  `k ≤ n ≤ 256`; the values arrive in the packet header, so they are
  sender-defined and not fixed in this binary. [UNKNOWN — sender-side]
- **The other mtd-utils siblings** (`ubiformat`, `nandwrite`, `flash_erase`,
  `mkfs.jffs2`, `sumtool`, the `ubi*` family) are present and equally unwired;
  this report covered only `recv_image`. A short companion note on why a
  NAND/UBI/JFFS2 toolchain ships on an MTD-less eMMC board would be worth doing.
  [unexplored]
