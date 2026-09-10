# The small binaries: watchdog, dwm, fb-config, frontpanel-poll, clock-demo, config-las-spi, flashbench, psplash, str, lasfwu

Region owner document. Covers the ten small helper programs in
`usr/bin/` of the decrypted v1.8.2 rootfs that had not been read before.

Scope of evidence, and how to read the grades:

- **[READ]** — read directly out of a file on local disk. The file, and a byte
  offset or line number, are quoted. Disassembly was produced with
  `llvm-objdump -d --triple=armv7-none-linux-gnueabihf` (macOS Xcode toolchain);
  strings/ELF facts with `strings`, `file`, `shasum`, and `llvm-objdump
  -T/-R/-s`. No ARM binary was executed — this host is x86/arm64 macOS and the
  targets are 32-bit ARM Linux, and per project rule they self-run
  calibration/reset actions on the real device regardless of arguments.
- **[INFERRED]** — a conclusion reasoned from evidence. The evidence is named.
- **[UNKNOWN]** — not determined from the material at hand.

Paths are relative to
`captures/firmware-1.8.2/rootfs-1.8.2/` unless written absolute.

---

## 0. Summary table

| binary | kind | runs at boot? | talks to | worst hazard |
|---|---|---|---|---|
| `las-watchdog` | ARM ELF, stripped | **yes** (S99final) | OSC/UDP to XMOS `203.0.113.2:7770`; `system()` shell recovery | supervisor; its death mid-SPI-write is the brick window; recovers by power-cycling XMOS and restarting the whole SC+GUI stack |
| `las-dwm` | ARM ELF (dwm-6.1 fork) | **yes** (S43gui) | X11; OSC/UDP listener; `system()`/`popen()` | **contains an OSC-triggered reverse-SSH phone-home to `remote.moogmusic.com`** |
| `las-fb-config` | ARM ELF, stripped | **yes** (S12splash, S43gui) | `ioctl` on `/dev/fb1` | sets global alpha on the overlay plane; first arg is a no-op |
| `las-frontpanel-poll` | ARM ELF, stripped | indirectly (via `detect-held-buttons`, launched by S43gui) | OSC/UDP to XMOS `203.0.113.2:9100` | read-only front-panel query tool |
| `las_clock_demo` | CHICKEN-Scheme ELF | no (manual diag) | OSC to `localhost:9501` (las-sc) | read-only voice-clock/sample-counter poller |
| `config-las-spi` | `/bin/sh` script | **yes** (S25xmosfw) | `devmem` on IOMUXC, XMOS reset GPIO | re-muxes SPI1 pins and resets/holds the XMOS |
| `flashbench` | ARM ELF (Arnd Bergmann's flashbench) | no (manual) | block device via `pread64`/**`pwrite64`** | destructive if pointed at a live partition with a write test |
| `psplash` | ARM ELF (Yocto psplash) | **no — unreferenced anywhere** | `/dev/fb0`, FIFO in `/tmp` | dead code in this build |
| `str` | ARM ELF, stripped | no (called by `lasfwu`) | reads a file | LSB-steganography extractor; pulls a **GPG private key** out of `bob.bmp` |
| `lasfwu` | Bash script | no (invoked on firmware update) | `str`,`gpg`,`dd`,`sgdisk`,`tar`,`jq` | writes decrypted firmware images to `/dev/mmcblk2p2/p3` |

Cross-version note **[READ]**: comparing SHA-256 across
`rootfs-1.5.0`, `rootfs-1.8.2`, and `arch-harvest`, **nine of the ten are
byte-identical between 1.5.0 and 1.8.2**. Only `las_clock_demo` differs
(1.5.0 `1c9854f79e149d42…`, 1.8.2 `fa84ccaf76b3f873…`), and that difference is
pure recompilation (see §5). So everything documented here for 1.8.2 is equally
true of the owner's 1.5.0 instrument, except where §5 says otherwise.

---

## 1. `las-watchdog` — the supervisor (priority target)

**File:** `usr/bin/las-watchdog`, 15048 bytes, ELF 32-bit ARM EABI5, dynamically
linked, stripped. SHA-256 `08d8c27c43bb9420cd81c497561186cfa6747aeb…`
**[READ]**. Identical in 1.5.0, 1.8.2, and the harvest **[READ]**.

### 1.1 What it is

An OSC/UDP client plus shell-driven process supervisor. `main` is at `0x12958`
**[READ]**. Its imports include `socket/bind/sendto/recvfrom/select`, `system`,
`time/localtime`, `atoi` **[READ, `llvm-objdump -T`]**. It links only `libc`.

### 1.2 Sockets and endpoints **[READ]**

Socket setup is `sub_11c10` (init A):

- `socket(AF_INET=2, SOCK_DGRAM=2, 0)` → fd stored at global `0x235a8` (`0x11c24`).
- **Destination** sockaddr (global `0x35dc`): `inet_addr("203.0.113.2")`
  (string at `.rodata 0x12dac`) and `htons(0x1e5a)` = **port 7770** (`0x11c98`).
- **Local bind** sockaddr (global `0x35cc`): `htonl(0)` (INADDR_ANY) and
  `htons(0x25c2)` = **port 9666**; `bind()` at `0x11d28`.

So the watchdog talks OSC to the **XMOS voice controller at 203.0.113.2:7770**
and listens on **UDP 9666** locally. 7770 is the same XMOS control port that
`S95dhcpd`/`usb-ext.sh`/`eth-ext.sh` DNAT external traffic to
(`iptables … --dport 7770 -j DNAT --to 203.0.113.2:7770`) **[READ,
`etc/init.d/S95dhcpd:11`]**, and the same port `lassvc`/`start_tune` use
(`-t 203.0.113.2:7770`) **[READ, `usr/bin/start_tune:17`]**.

`sub_11d50` (init B) sends the first OSC message and then `select()`s for a
reply; `sub_12140` is the reusable "send OSC address, wait for typed reply"
routine (an OSC argument parser handling `i`/`s`/`f` tags — the same
tag-dispatch, byte-for-byte, as `las-frontpanel-poll`; see §4) **[READ]**. Both
end with `usleep(poll_time)` **[READ, `0x1247c`]**.

### 1.3 Argument parsing — **and the `-t=10000` it is launched with is silently ignored** **[READ]**

`main` loops over `argv` (`0x129b8`). For each token it loads the **first byte**
(`ldrb r3,[argv[i]]`) and:

- if it is `'t'` (0x74): `atoi(argv[i+1])` → poll interval (stored `[r11,-0x8]`),
  printed with `"Poll time of %d\n"` (`.rodata 0x13328`).
- if it is `'v'` (0x76): `atoi(argv[i+1])` → expected voice count
  (`[r11,-0x18]`, `"Expecting %d voices\n"`, `0x13310`); then falls through and
  also consumes `argv[i+1]` as the poll interval.
- anything else: skipped.

The boot invocation is **`las-watchdog -t=10000`** **[READ,
`etc/init.d/S99final:24`]**. `argv[1]` is the single token `"-t=10000"`, whose
first byte is `'-'` (0x2d), not `'t'`. **Neither branch matches, so the value
never reaches `atoi`.** The poll interval keeps its default, set at `0x12988`:
`0xf4240` = **1,000,000 µs = 1 s** **[READ]**. Expected-voices default is `8`
(`0x12994`).

Consequence **[INFERRED, from the parse + the default]**: the watchdog polls at
its 1-second default, not the ~10 ms the `-t=10000` token appears to request —
roughly 100× slower than the flag implies. To make the flag take effect it would
have to be passed as two tokens beginning with the letter itself, e.g.
`las-watchdog t 10000` (and `v 8`). No script in the rootfs does that **[READ,
grep of `etc/`]**. A side effect useful for validation: because no `t`/`v` token
matches, the strings `"Poll time of"` and `"Expecting … voices"` are **never
printed** to the log — their absence in `las-watchdog.log` is the on-device
fingerprint of the ignored argument (see §11).

> This is a genuine "what it really accepts vs. what its launcher passes"
> defect, and it is load-bearing: it changes how fast the supervisor reacts.

### 1.4 The supervision loop **[READ]**

The loop body (`0x12a88`, running while the byte at global `0x2359c` is non-zero
— never cleared, so effectively `while(1)`) does, each pass:

1. Print an `LAS-WATCHDOG : h:m:s` timestamp (`localtime`, `0x1333c`).
2. OSC `/v/voices` (`0x13358`) → voice count; print
   `"VC REPORTING %d VOICES"` (`0x13364`).
3. Inner check: OSC `/ping` (`0x132b0`). If the reply is not exactly `1`
   (`cmp #1` at `0x12b30`), it immediately `close()`s the socket, writes
   `"LAS-WATCHDOG :  !!!VC IS DOWN!!!"` (`0x132b8`, 33 bytes) and runs the XMOS
   recovery `sub_12644` — **no retry/debounce on this path** (`0x12b38`–`0x12b70`).
4. If `/v/voices` returned `≤ 0`, a **30-attempt** counter runs
   (`"VC ENUM ATTEMPT %d"`, `0x1338c`; `cmp #30` at `0x12bc4`); on the 31st it
   writes `"VX INIT PROCESS TIMEOUT!!"` (`0x133b0`, 42 bytes) and recovers. This
   30× debounce applies **only** to voice enumeration, not to the `/ping` above.
5. When voices `> 0`: per-voice `/vx/<n>/ping` checks (`sub_127bc`, addresses
   built by `strcpy("/vx/")`+`strcat`), then process-liveness checks (§1.5),
   then `"LAS-WATCHDOG : successful check up..."` (`0x133dc`).

### 1.5 Recovery actions — every one is a `system()` shell string **[READ]**

There are eleven `system()` call sites (`llvm-objdump` shows `bl 0x10790
<system@plt>`). The literal shell strings (`.rodata`) are:

Process-liveness checks (each: `pidof X`; on failure print and re-init):

- `sub_12508`: `#!/bin/bash \n pidof las-frontend &> /dev/null` (`0x12ff0`);
  on non-zero → `"FRONTEND IS DOWN!!"` (`0x13020`) → `sub_12498`.
- `sub_1255c`: `pidof las-sc` (`0x13058`) → `"SOUND ENGINE CONTROLLER IS DOWN"`
  (`0x13080`) → `sub_12498`.
- `sub_125b0`: `pidof sclang` (`0x130c0`) → `"SCLANG IS DOWN"` (`0x130e8`) →
  `sub_12498`; then `pidof scsynth` (`0x13118`) → `"SCSYNTH IS DOWN"` (`0x13144`)
  → `sub_12498`.

These have **no debounce**: a single failed `pidof` triggers a full re-init.

Re-init sequence `sub_12498` — restarts the whole audio + GUI stack **[READ]**:

- `0x12e5c`: `S42sc stop ; killall scsynth sclang screen ; S43gui stop ;
  killall X ; sleep 2`
- `0x12ed4`: `S42sc stop ; killall scsynth sclang screen ; S42sc start &`
- `0x12f38`: `S43gui stop ; killall X ; S12splash start ; S43gui start & ;
  sleep 5 ; killall las-dwm ; DISPLAY=:0 las-dwm &`
- then spin on `access("/var/las-sc.cookie")` (`0x12fdc`), `remove()` it, until
  las-sc re-announces.

XMOS recovery `sub_12644` (called when VC/a voice is down) **[READ]**:

- 10× ICMP `ping -c1 -W1 203.0.113.2` (`0x13174`), counting successes.
- if `≤ 9` succeed → write `"-->!!SYS XMOS is down!!!"` (`0x131cc`) and
  **`config-las-spi som ; sleep 1 ; config-las-spi xmos ; sleep 1`** (`0x131e8`)
  — i.e. it hands the SPI bus to the SoM and back, resetting the XMOS (§6).
- always then: `"----> Cycling Sockets"` (`0x13234`), `close()` the OSC socket,
  **`kill -9 \`fuser 9666/udp\`** (`0x1324c`), `sleep 2`, `sub_12498` (the full
  stack restart above), `sleep 2`, and rebuild both sockets (`sub_11c10`,
  `sub_11d50`).

The OSC-send error path (`sub_12140`, `0x122e8`) additionally runs
`kill -9 \`fuser 9799/udp\`` (`0x12e34`) before rebuilding the socket
**[READ]** — 9799 is a different UDP port it frees during recovery (**[INFERRED]**
another las-sc control socket; not otherwise pinned in this region).

> Disassembler-label caveat **[READ]**: `llvm-objdump` prints the recovery's
> `close()` calls (PLT stub `0x10868`) as `<abort@plt+0xc>`, because symbol
> resolution stops at `abort`. The relocation table (`llvm-objdump -R`) shows
> `close` is the 32nd and last `R_ARM_JUMP_SLOT` (GOT `0x2358c`), and the 12-byte
> PLT stride puts its stub at exactly `0x10868`. These are `close(fd)`, not
> `abort()`. Getting this wrong would wrongly say the watchdog aborts where it
> actually just closes a socket.

### 1.6 Why its death is the brick window **[INFERRED, corroborates `docs/DANGER.md`]**

`S99final` launches it as
`(sleep 1; las-watchdog -t=10000 > /var/log/las-watchdog.log 2>&1) &` **only
after** `/var/las-sc.cookie` appears **[READ, `S99final:20-28`]**, and kills it on
shutdown and in service mode (`S99final:36,50`; `detect-held-buttons:14`;
`start_tune:58`) **[READ]**. Because its sole recovery vocabulary is
`config-las-spi` (which re-muxes the SPI1 pins and toggles `XMOS_RESET_N`, §6)
and full-stack restarts, the danger is not the watchdog acting — it is the
watchdog **not** acting: if it is killed while an SPI/voice-card write is in
flight, nothing power-cycles the half-written XMOS, matching the brick scenario
in `docs/DANGER.md:88-92`. Deliberately `killall las-watchdog` before invasive
work removes the net (as that doc already says).

---

## 2. `las-dwm` — the window manager, with an OSC-triggered phone-home

**File:** `usr/bin/las-dwm`, 61272 bytes, ELF 32-bit ARM, stripped, SHA-256
`0a3561a0dff20e85…`, identical across all three trees **[READ]**. Links
`libX11`, `libXtst`, `libXft`, `libXinerama`, `libfontconfig`, `libxkbcommon`,
`libpthread` **[READ, NEEDED]**. Self-identifies as **`dwm-6.1`** (suckless
dynamic window manager) with `usage: dwm [-v]` **[READ, `.rodata`]**. Launched at
boot by `S43gui` (`DISPLAY=:0 las-dwm &`, `S43gui:46`) after a cookie handshake
on `/var/las-dwm.cookie` **[READ]**.

It is a Moog fork of dwm with three additions: an **embedded `xdotool`/libXtst**
build (workspace switching), an **OSC/UDP listener**, and a **phone-home**.

### 2.1 The OSC listener **[READ]**

Socket setup at `0x17fb0`: `socket(AF_INET, …)`; a destination sockaddr for
`inet_addr("203.0.113.2")` (`.rodata 0x1c482`) with port halfword `0x8c23`
(network order → **9100**, `0x18058`); and a bound sockaddr with
family `AF_INET`, `INADDR_ANY`, port halfword `0x8025` (network order →
**9600**, `0x18060`), `bind()` at `0x18024`. The receive loop `recvfrom()`s at
`0x1429c` and parses OSC with the same `i`/`s`/`f` tag dispatch as the other
tools **[READ]**.

The handled OSC address is **`/cb`** (`.rodata 0x1c09c`) — "control buttons".
The integer argument is compared (`0x14304`–`0x14344`) against:

| `/cb` int value | action | shell it runs |
|---|---|---|
| `49` | switch workspace | `DISPLAY=:0 xdotool key "alt+1"` (`0x1c0ac`) |
| `50` | switch workspace | `… "alt+2"` (`0x1c0e0`) |
| `52` | switch workspace | `… "alt+3"` (`0x1c148`) |
| `56` | switch workspace | `… "alt+4"` (`0x1c0e0`-family) |
| **`0x02000030` (33554480)** | **phone-home** | see §2.2 |

The trigger value `0x02000030` is loaded from the literal pool at `0x1446c` and
compared with `cmp r0, r8` at `0x14344` **[READ]**. That `/cb` carries
front-panel button state is corroborated by `detect-held-buttons`, which reads
the same idea via `las-frontpanel-poll /cb` and treats `48` as HOME+SETTINGS
**[READ, `detect-held-buttons:8-11`]**; so `0x02000030` is **[INFERRED]** a
specific front-panel button chord/state word. The exact physical buttons are
**[UNKNOWN]** from this region (the XMOS assigns the code).

### 2.2 The phone-home reverse-SSH tunnel **[READ]**

When `/cb == 0x02000030`, `las-dwm` runs, in order (`0x1434c`–`0x143bc`):

1. `system("#!/bin/bash \n rm -rf /var/log/phonehome.log")` (`0x1c176`)
2. `system("#!/bin/bash \n echo \`date\` > /var/log/phonehome.log")` (`0x1c1a2`)
3. builds three scripts on the stack via `memcpy` and runs the first two with
   `popen(…, "r")` (mode string `"r"` at `0x1d558`) and the third with
   `system()`:
   - **`(sshpass -plas ssh -N -T -y -R22222:localhost:22 -p4448
     las@remote.moogmusic.com &) >> /var/log/phonehome.log 2>&1`** (`0x1c1d9`,
     129 bytes)
   - a monitor loop: `pid=\`ps | grep sshpass | awk … \` ; echo $pid >>
     phonehome.log ; while kill -0 $pid; do printf "." ; sleep 1 ; done`
     (`0x1c25a`, 287 bytes)
   - `killall las-frontend ; fbv /usr/share/splash/phonehome.png` (`0x1c379`,
     73 bytes) — kills the UI and shows a full-screen "phone home" splash.

The splash it displays, `/usr/share/splash/phonehome.png`, **exists** in the
rootfs (2,154,663 bytes) **[READ, `ls`]**.

Meaning **[INFERRED, direct reading of the strings]**: a front-panel chord makes
the instrument open a **reverse SSH tunnel to `remote.moogmusic.com` port 4448**,
authenticating with the **hardcoded password `las`** (`sshpass -plas`), and
forward remote port **22222 back to the instrument's own `localhost:22`** — i.e.
it exposes the device's SSH server to whoever controls that remote host.

Relationship to prior docs **[READ]**: `docs/DANGER.md:196-206` already records
that "`las-dwm` embeds a reverse SSH tunnel"; and `docs/firmware/lassvc.md:314`
documents a **separate** phone-home in `lassvc` (the service-mode tool) reached
through its "phone home (alpha)" menu. These are two independent
implementations of the same tunnel. **This document adds the exact trigger for
the `las-dwm` copy**: OSC `/cb` = `0x02000030` on UDP 9600. No conflict with
those docs; it extends them. See §10.

---

## 3. `las-fb-config` — overlay-plane alpha, first argument is dead

**File:** `usr/bin/las-fb-config`, 3804 bytes, ELF 32-bit ARM, stripped,
`a0b97096024e4498…`, identical across trees **[READ]**. Imports
`open/ioctl/atoi/sprintf/strerror` **[READ]**.

Behaviour, from `main` at `0x10640` **[READ]**:

- If `argc ≤ 1`: print
  `"Usage: %s framebuffer [0,1] [ alpha_val[0-255] ] \n"` (`0x107f4`) and return
  `-1`.
- Otherwise it `sprintf`s into a stack buffer with format `"/dev/fb%s"`
  (`0x1082c`) and `argv[1]` (`0x106b4`) — **and then discards that buffer.** The
  `open()` at `0x106c4` is given the *literal* pointer `0x10838`, which is the
  hardcoded string **`"/dev/fb1"`** (`.rodata 0x10838`), `O_RDWR` (`mode=2`).
- `argv[2]` → `atoi` → alpha (`0x10730`, stored `[r11,-0x14]`); a 2-word struct
  `{enable=1, alpha}` is built (`enable` set to `1` at `0x1071c`) and passed to
  `ioctl(fd, 0x40084621, &struct)` (`0x10744`/`0x10750`).

`0x40084621` is the i.MX `MXCFB_SET_GBL_ALPHA` ioctl **[INFERRED, standard i.MX6
mxc_fb value; struct shape `{enable,alpha}` matches `mxcfb_gbl_alpha`]**.

So **`las-fb-config`'s first argument ("framebuffer [0,1]") does nothing** — the
program always operates on `/dev/fb1` (the UI overlay plane) — and its real
effect is to set that plane's global alpha 0–255 from the second argument. This
matches its callers: `S12splash` fades it in (`las-fb-config 1 0` then a
`las-fb-config 1 $i` loop, `S12splash:9,26`) and `S43gui` blanks it
(`las-fb-config 1 0`, `S43gui:69`) **[READ]**. A "help claims vs. reality"
discrepancy: the usage text advertises a framebuffer selector the code ignores.
No hazard.

---

## 4. `las-frontpanel-poll` — read-only OSC query to the XMOS

**File:** `usr/bin/las-frontpanel-poll`, 9864 bytes, ELF 32-bit ARM, stripped,
`3599501c203eed08…`, identical across trees **[READ]**.

It is a one-shot OSC client. Socket build (`0x11abc`+): destination
`inet_addr("203.0.113.2")` (`.rodata 0x11eb8`) with `htons(0x238c)` = **port
9100**; local bind `htons(0x26ac)` = **port 9900** **[READ]**. `main` takes
`argv[1]` as the OSC address to send (e.g. `/cb`), `sendto`s it (`0x11be4`),
`recvfrom`s the reply (`0x11ca8`), and prints the typed arguments — the same
`i`/`s`/`f`/blob tag parser (`" %d"`, `" %g"`, `" %s"`, `"0x%02X%02X%02X%02X"`,
`" nil/true/false/inf"`, `"Unknown format: '%c'"`) shared verbatim with
`las-watchdog` and `las-dwm` **[READ]**. On error it prints `"cannot create
socket"` / `"bind failed"` / `"sendto failed"`.

It is **not** started at boot directly, but it runs on every boot indirectly:
`S43gui` launches `detect-held-buttons &` (`S43gui:76`), which calls
`las-frontpanel-poll /cb` and, if the result equals `48`, drops the instrument
into service mode (kills the watchdog/frontend/las-sc, opens an xterm running
`lassvc -t vc:7770 -p vc:9100`) **[READ, `detect-held-buttons`]**. The tool
itself is read-only — it sends the OSC address you give it and prints the answer;
it writes nothing. 9100 is the port `lassvc`/`start_tune` use as the panel port
(`-p vc:9100`) **[READ]**.

---

## 5. `las_clock_demo` — CHICKEN-Scheme voice-clock poller

**File:** `usr/bin/las_clock_demo`, 240100 bytes, ELF 32-bit ARM, stripped,
links `libchicken.so.8`, `libm`, `libdl`, `libc` **[READ, NEEDED]**. It is a
compiled **CHICKEN Scheme** program (symbols `CHICKEN_main`,
`C_chicken_2dsyntax_toplevel`) from the `las-sc` egg — its setup-info says
`(egg-name "las-sc")` and the build path
`/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/…`
**[READ, `usr/lib/chicken/8/las_clock_demo.setup-info`]**.

Behaviour, from retained Scheme metadata strings **[READ]**:

- Default target address **`localhost:9501`** (`"localhost:9501"`,
  `"'Target address (default localhost:9501)"`, `"Display usage text"`) — i.e. it
  connects to **las-sc on the SoM**, not to the XMOS. `--help` prints usage.
- It builds a `las-port` (records `las-port-sock/voice-count/query-chan/…`),
  runs a `poll` with a `poll-interval`, and reads `voice-clock`,
  `sample-counter`, and voice count — printing `" voice clock "` and
  `" sample counter "`; on failure `"failed to query "` /
  `"Unable to determine voice count -- reconnect & retry"`. Source files
  compiled in: `las/sockutil.scm`, `cal/jobs.scm` **[READ]**.

It is a **read-only diagnostic** — it queries las-sc's clock/counter and prints
them. The only conceivable hazard is query volume against las-sc if the poll
interval is set very low; there is no write path in the retained strings.
**[INFERRED, from the string set; the compiled Scheme control flow was not
traced instruction-by-instruction]**.

**Version change (the only binary that differs 1.5.0 → 1.8.2)** **[READ]**:
`cmp -l` reports 14,138 differing bytes, but a sorted `strings` diff of the two
versions is **empty** — every string, source-file name, default address, and
usage line is identical. The change is therefore a **recompilation** (CHICKEN
codegen / address layout), not a behavioural change. Nothing this tool does
differs between the owner's 1.5.0 and 1.8.2.

---

## 6. `config-las-spi` — the SPI/XMOS mux switch

**File:** `usr/bin/config-las-spi`, 1047 bytes, **`/bin/sh` script**,
`175292491fcc9c6c…`, identical across trees **[READ]**. Read in full; not
compiled.

Two functions, selected by `$1` **[READ, whole file]**:

- `config_spi_xmos` (arg `xmos`): pokes IOMUXC registers via `devmem` to set the
  KEY_COL0/COL1/ROW0/ROW1 pads to ALT5 (`devmem 0x20e0244 32 5`, …) and
  `GPIO4_GDIR` to `0x40008020`, making SPI1 GPIOs inputs so the **XMOS drives the
  bus**, then pulses `XMOS_RESET_N` low→high via
  `/sys/class/leds/XMOS_RESET_N/brightness` (0 then 1) — a reset that releases
  the XMOS.
- `config_spi_som` (arg `som`): holds `XMOS_RESET_N` **low** (keeps XMOS in
  reset), and returns the pads to ALT0 / `GPIO4_GDIR = 0x40008220` so the **SoM
  drives the bus**.
- No argument → prints `"Please pass {xmos} or {som}"` and exits 1. Any other
  argument → same message, exit 0.

Hazard **[INFERRED, from the register writes]**: this is the primitive the
watchdog and `start_tune` use to reset/reclaim the XMOS. Running `config-las-spi
som` **leaves the XMOS held in reset** (no audio, no MIDI) until something runs
`xmos` again; running it during an in-flight SPI transaction is exactly the
half-write hazard the watchdog exists to avoid. It is a real boot participant:
`S25xmosfw` calls `config-las-spi xmos` ("Cycle XMOS Power") on every boot
**[READ, `S25xmosfw:11`]**. `S42sc` contains a commented-out `config-las-spi
xmos` "HACK … workaround for startup problems with the VC firmware" **[READ,
`S42sc:19-21`]**.

Devmem addresses match i.MX6 IOMUXC (`0x20e0xxx`) and GPIO4 (`0x20a8004`)
**[INFERRED, standard i.MX6 memory map]**.

---

## 7. `flashbench` — flash-timing benchmark (can write)

**File:** `usr/bin/flashbench`, 23532 bytes, ELF 32-bit ARM, stripped, links
`librt` + `libc`, `e36eb8bd8f458395…`, identical across trees **[READ]**.

This is **Arnd Bergmann's open-source `flashbench`** — the strings are its
verbatim option set: `--scatter`, `--find-fat`, `--open-au`, `--blocksize`,
`--erasesize`, `--count`, `--random`, `--out`, and the getopt string
`"o:siafF:Ovrc:b:e:p"` **[READ, `.rodata`]**. It measures flash erase-block and
page timing by timed reads and writes.

Import set includes `pread64`, **`pwrite64`**, `open64`, `posix_memalign`,
`clock_gettime`, and `sched_setscheduler` **[READ, `llvm-objdump -T`]**.

Hazard **[INFERRED, from the imports + the tool's known semantics]**: `flashbench`
takes a `[DEVICE]` argument and, in its write-based tests (`time_write`,
`time_erase`), **calls `pwrite64` against that device** — destructive if aimed at
a live eMMC partition (`/dev/mmcblk*`). It also calls `sched_setscheduler`, so it
can raise its own real-time priority and starve the audio core if run on a live
system. It is **not** referenced by any boot script or other program in the
rootfs (grep of `etc/`, `usr/bin`, `sbin`) **[READ]** — it ships as a bring-up /
factory tool. Read-only analysis modes (`--scatter`, `--find-fat`, `--open-au`)
exist, but the safe/destructive line is the presence of a write test flag, which
must be chosen deliberately. It was never examined before; nothing Moog-specific
was found in it.

---

## 8. `psplash` — unused Yocto splash

**File:** `usr/bin/psplash`, 47564 bytes, ELF 32-bit ARM, stripped,
`3c1fe06798869a01…`, identical across trees **[READ]**. It is the standard
**Yocto/OpenedHand psplash**: `mkfifo`, `psplash_fifo` in `/tmp`, commands
`QUIT`/`PROGRESS`, `Usage: %s [-n|--no-console-switch][-a|--angle
<0|90|180|270>]`, opens `/dev/fb0` and `/dev/tty0` **[READ, `.rodata`]**.

Finding **[READ, grep across `etc/`, `usr/bin`, `usr/sbin`, `sbin`, `bin`]**:
**nothing in the rootfs references `psplash`, `psplash_fifo`, or `PSPLASH*`.**
The Moog boot splash is done differently — `S12splash` sets up `/dev/fb1` with
`fbset`, starts `X`, and `dd`s `/boot/moog_splash.fb` to the framebuffer
(`S12splash:14-21`) **[READ]**. So `psplash` is **dead code** in this build:
present because it is in the Yocto image recipe, but never invoked. No hazard.

---

## 9. `str` — LSB-steganography extractor (pulls a private key out of `bob.bmp`)

**File:** `usr/bin/str`, 4056 bytes, ELF 32-bit ARM, stripped,
`4762f196455c9e54…`, identical across trees **[READ]**.

Usage string: `"usage: %s <in file> <n last bits> > <out file>"`; errors
`"error opening file: %s"`, `"error: number of last bits can only be 1, 2 or 4"`,
status `"msg size: %d bytes"` (to stderr) **[READ, `.rodata`]**. Imports
`fopen/fseek/fread/fputc/malloc/strtol` **[READ]**.

Algorithm, from `main` (`0x104f4`) and `bmp_read` (`0x10784`) **[READ,
full disassembly]**:

- `argv[2]` = `n` ∈ {1,2,4}; else print the "1, 2 or 4" error and exit 4.
- `fseek(fp, 54, SEEK_SET)` — skip the 54-byte BMP header (`0x10588`).
- Read a **7-byte ASCII decimal length header** out of the low `n` bits of each
  file byte, MSB-first within a byte (shift `8-n`, accumulate) — `bmp_read(fp,
  buf, 7, n)`.
- `strtol` that header → message size; print `"msg size: %d bytes"`; `malloc`
  it; `bmp_read` that many bytes; write them to `stdout` byte by byte.

I reproduced this algorithm in Python (no ARM execution) against
`etc/bob.bmp` **[READ, replicated]**. With `n = 4` the 7-byte header decodes to
`"3581"` and the extracted 3581-byte payload begins:

```
-----BEGIN PGP PRIVATE KEY BLOCK-----
Version: GnuPG v1
```

So `str /etc/bob.bmp 4` extracts a **3581-byte GnuPG private key block** that is
LSB-steganographed at 4 bits/byte, MSB-first, behind a decimal length header —
exactly matching `docs/CORRECTIONS-2026-09-08.md:104-105` (which also records the
passphrase is `bob`). This corroborates that doc independently. `n=1` and `n=2`
do not yield a valid length header (they are the wrong bit depth for this file)
**[READ]**.

`etc/bob.bmp` (741,056 bytes, `PC bitmap 500×741×16`) is byte-identical in
1.5.0, 1.8.2, and the harvest (`67ceca27bf6df086…`) **[READ]**.

`str` writes nothing to any device — it reads a file and writes to stdout. Its
hazard is purely disclosure: it is the extractor that turns a bitmap in `/etc`
into a usable private key (see §9 of `lasfwu`, next).

---

## 10. `lasfwu` — the firmware-update script

**File:** `usr/bin/lasfwu`, 33940 bytes, **Bash script**, 1209 lines,
`12409bc781e9e1c2…`, identical across trees. Header: `# Created by Chris Howe on
6/26/17.` Read in full **[READ]**.

### 10.1 Operations and options **[READ]**

`checkoperation` dispatches `$1`:

- `search` — find/validate `.tar` firmware packages in a directory.
- `verify-file` — validate a package (tar integrity; presence of `MOOGFW` and
  `MANIFEST`; manifest/jq cross-checks; `packed_size`).
- `load` — decrypt, verify, and flash a package (§10.2).
- `verify-fs` — **an empty stub**: the `case` arm is present but does nothing
  (`lasfwu:1150-1151`). The `--help` text (`lasfwu:1051`) advertises
  `verify-fs /device/ /sig-file/`; the implementation is a no-op.

`checkoptions` handles `--version`, `--temp` (no-op), `--api`, `--verbose`/`-v`,
`-r`/`--recurse`, `--dry-run`/`-n`, `-q`. Notable "help vs reality" gap:
**`--accept-unsigned` is documented in `--help` (`lasfwu:1009`) but has no
handler** in `checkoptions` — it falls through the `*)` catch-all and is ignored
**[READ]**. (In practice the `load` path always runs `gpg --verify` and returns
on failure, so it cannot be bypassed by that flag anyway; see §10.2.)

### 10.2 The `load` path — key, decrypt, verify, flash **[READ]**

1. `getkey`-style step: **`str /etc/bob.bmp 4 > "$MOUNTDIR/mmepk"`** then
   `gpg --import … "$MOUNTDIR/mmepk"` (`lasfwu:49-50, 637-638`) — imports the
   private key extracted in §9.
2. Decrypt the image: `pv "$imagename" | gpg --always-trust
   --ignore-time-conflict --ignore-valid-from **--passphrase bob** --output
   "$imagename.ext4" --decrypt -` (`lasfwu:642`) — the **hardcoded passphrase
   `bob`**. On non-zero exit it emits a `550` status JSON and returns 1.
3. Verify the signature: `gpg … --verify "$imagesigname" -` against the
   decrypted `.ext4` (`lasfwu:686`); failure → `550` and return 1.
4. Erase the secret key again (`gpg --delete-secret-keys …`, `lasfwu:729`).
5. Choose the target partition (`lasfwu:455-540`): read the booted root from
   `/proc/cmdline` (`…root=/dev/mmcblk2p<N>…`); the two upgrade slots are
   `/dev/mmcblk2p2` (U1) and `/dev/mmcblk2p3` (U2), `p1` is factory. If booted
   from factory it replaces the **older** of U1/U2 (compares versions mounted
   from each); if booted from U1 it replaces U2 and vice-versa.
6. Flash: `dd if="$upgradefs" bs=2048 | pv … | dd bs=2048
   of="/dev/mmcblk2p$replacepart"` (`lasfwu:742/745`) — **raw `dd` of the
   decrypted ext4 image onto the chosen eMMC partition.**
7. Book-keeping: clear the slot's sentinel
   (`echo 0 > /var/lib/sys/sentinelu$part`) and write
   `/var/lib/sys/bootversion` from the manifest version (`lasfwu:564-568`).

Non-load paths also flash in dry-run mode: with `--dry-run`, `load` `dd`s the
raw input file straight to `$dest` (`lasfwu:396/398`) — where `$dest` defaults to
`${PWD}/dd_image` unless `--dest` is given (`lasfwu:365, 377-388`).

### 10.3 Hazards **[INFERRED, from the script]**

- `load` writes decrypted images to `/dev/mmcblk2p2` or `/dev/mmcblk2p3` with raw
  `dd`. An interrupted `load` leaves a half-written upgrade partition (mitigated
  by the A/B slot design — it never overwrites the running slot or factory `p1`).
- The confidentiality of the whole update chain rests on a **private key hidden
  in `/etc/bob.bmp`** plus the **passphrase `bob`**, both present in the shipped
  rootfs. This is a disclosure finding, already noted in
  `docs/CORRECTIONS-2026-09-08.md`; recorded here because `str` + `lasfwu` are the
  two programs that actually use it.
- `verify-fs` and `--accept-unsigned` are advertised but unimplemented — do not
  rely on either.

---

## 11. Validation plan (READ-ONLY commands for the real instrument)

Every command below is read-only. **Do not run** the Moog binaries with
arguments; the ones here are either inspection of files/logs or the tools'
genuinely-read-only query paths. The human runs these; the agent must not touch
the instrument.

1. **Confirm `las-watchdog`'s poll interval is the default (the `-t=10000` bug).**
   `cat /var/log/las-watchdog.log` — expect timestamps and `LAS-WATCHDOG : VC
   REPORTING <n> VOICES`, and **no** `Poll time of …` or `Expecting … voices`
   lines. Their absence confirms the `-t=10000` token was not parsed and the
   1-second default is in effect. (`grep -c 'Poll time of'
   /var/log/las-watchdog.log` should be `0`.)
2. **Confirm the watchdog's own listen socket.** `fuser 9666/udp` or
   `ss -lun | grep 9666` — expect the `las-watchdog` PID (matches the
   `kill -9 \`fuser 9666/udp\`` recovery). `cat /proc/$(pidof
   las-watchdog)/cmdline | tr '\0' ' '` should show `las-watchdog -t=10000`.
3. **Confirm `las-fb-config` targets `/dev/fb1` regardless of arg 1.**
   `ls -l /dev/fb0 /dev/fb1` and read `S12splash`/`S43gui` on the device to see
   the `las-fb-config 1 …` calls; do **not** invoke `las-fb-config` (it writes
   the overlay alpha). Static confirmation only.
4. **Confirm the phone-home artefacts exist.** `ls -l
   /usr/share/splash/phonehome.png` and `ls -l /var/log/phonehome.log`
   (the log exists only after a phone-home has run). Do **not** trigger `/cb`.
5. **Confirm the hidden key round-trips (off the instrument preferred).** On a
   *copy* of `/etc/bob.bmp`, `str <copy> 4 | head -c 40` should print
   `-----BEGIN PGP PRIVATE KEY BLOCK-----`. `str` is read-only, but run it on a
   copy to be safe. `sha256sum /etc/bob.bmp` should be
   `67ceca27bf6df086d16d00351faa25d22ddb5804b6904c9bd6bb85abd3fca604`.
6. **Confirm `psplash` is genuinely idle.** `pidof psplash` (expect nothing) and
   `grep -rl psplash /etc` (expect nothing).
7. **Confirm boot membership.** `grep -RIn 'las-watchdog\|las-dwm\|las-fb-config\|
   config-las-spi' /etc/init.d` on the device should reproduce the mapping in §0.
8. **Do NOT** run `flashbench`, `config-las-spi`, `las_clock_demo` against live
   devices, and do not send OSC to UDP 9600 (`/cb`), 7770, 9100, or 9666. These
   have side effects (device writes, XMOS reset, phone-home, socket churn).

---

## 12. Conflicts with existing docs

Reported, not fixed, per the region rules.

1. **`docs/DANGER.md:237-239`** states of `las-watchdog`: "There is no debounce
   on the watchdog either: a single missed poll restarts the whole audio and GUI
   stack." This is **correct for the `/ping` liveness check and the `pidof`
   process checks** (both trigger recovery on a single failure — §1.4/§1.5), but
   **imprecise as a blanket claim**: the `/v/voices` enumeration path has a
   30-attempt counter before it declares the VC down (`cmp #30` at `0x12bc4`,
   §1.4). Suggest narrowing the statement to "the ping and process checks have no
   debounce; only voice-count enumeration retries 30×."

2. **`docs/DANGER.md:196-206`** and **`docs/firmware/lassvc.md:314+`** both
   document the reverse-SSH phone-home but as two separate stories (dwm vs.
   lassvc). Neither records the **OSC trigger for the `las-dwm` copy**. This
   document supplies it: `las-dwm` fires the tunnel when it receives OSC `/cb`
   with integer value `0x02000030` on its UDP bind port (§2.1/§2.2). Not a
   contradiction — a gap now filled. No edit made to those files.

3. No conflict, but a corroboration worth noting: `docs/CORRECTIONS-2026-09-08.md`
   already states the `bob.bmp` key is "4 bits per byte, MSB-first, behind a
   decimal length header (`3581`), passphrase `bob`." My independent replication
   of `str`'s algorithm (§9) reproduces exactly that (`n=4`, header `3581`, PGP
   private-key block). No change needed.

---

## 13. Unexplored

- **`las-dwm`'s dwm core.** I documented the OSC/phone-home additions and the
  window-manager identity (dwm-6.1) but did not trace the full dwm event loop,
  its tag/layout config, or the `xdotool`/libXtst key-injection internals. The
  `/cb` values `49/50/52/56` map to `alt+1..4` (workspace switches); whether
  other OSC addresses beyond `/cb` are handled was not exhaustively checked (the
  dispatch I read only branched on `/cb`).
- **Exact physical buttons behind `/cb == 0x02000030`.** The code compares
  against the value; the mapping from the 32-bit word to front-panel keys lives
  in the XMOS, which is out of this region. `48` = HOME+SETTINGS is the only
  documented anchor (`detect-held-buttons`).
- **`las_clock_demo` compiled control flow.** Read at the level of retained
  Scheme strings/records and its default endpoint; the CHICKEN-compiled bytecode
  path (poll interval bounds, exact OSC verbs on `localhost:9501`) was not
  disassembled instruction-by-instruction. `las/sockutil.scm` and `cal/jobs.scm`
  source is referenced but not present in the rootfs.
- **`flashbench` write-test specifics.** Confirmed it is upstream flashbench and
  that it links `pwrite64`; I did not map which flag combinations reach a write
  vs. read-only test in this exact build (upstream: scatter/find-fat/open-au are
  read-oriented; `time_write`/`time_erase` write). Treat any DEVICE argument as
  potentially destructive.
- **Port 9799.** `las-watchdog` frees `9799/udp` during its OSC-error recovery;
  I did not pin which process owns 9799 (inferred: a las-sc control socket).
- **`lasfwu` `search`/`verify-file` details** beyond the tar/manifest/jq checks
  summarised — the full manifest schema and version-comparison arithmetic were
  read at a summary level, not line-by-line for every branch.
- **The GPG key's fingerprint/identity** inside `bob.bmp` (uid
  `encrypt@moogmusic.com` appears in `lasfwu`); I extracted the block header but
  did not import/parse the key (that would require gpg and is out of scope for a
  read-only pass).
