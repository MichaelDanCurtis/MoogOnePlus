# Gap: the non-synth interactive userland — on-device editor, chess engine, and games

Scope: the cluster of full interactive desktop/terminal applications that ship in
the Moog One root filesystem but belong to no part of the synthesiser's signal or
control path: the `em` text editor, the `gnuchess` engine family, the `lbreakout2`
and `ltris` SDL games (plus `lbreakout2server`), and the `fluid` FLTK UI designer.
The governing questions are: *what are they*, *are they the same across firmware
versions*, *is the live `/var` high-score state evidence that they were played*,
and *is any of it reachable on a shipping instrument*.

Primary material:
- `captures/firmware-1.8.2/rootfs-1.8.2/` — decrypted v1.8.2 root filesystem.
- `captures/rootfs-1.5.0/` — v1.5.0 root filesystem from the owner's instrument.
- `captures/arch-harvest/`, `captures/sysmap/`, `captures/harvest/`,
  `captures/moog-recon/` — live/harvested captures (runtime-state.txt is
  contaminated; see `CAVEAT-runtime-state.md`).

Method: static only. No instrument was touched. ELF binaries were read with
`file`, `strings`, `md5`, and
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`; no Moog or ARM binary was
executed. Every factual claim below is graded **[READ]** (read directly from a
file — path and offset/line given), **[INFERRED]** (reasoning from stated
evidence), or **[UNKNOWN]**.

Paths are abbreviated with `A = captures/firmware-1.8.2/rootfs-1.8.2` and
`B = captures/rootfs-1.5.0`.

---

## 0. Headline

**The live `/var/lbreakout2.hscr` and `/var/ltris.hscr` files are NOT evidence
that anyone played these games on an instrument. They are the games' built-in
default score tables, written at image-build time.** Three independent proofs
converge on this (Section 5). The surrounding applications are real and complete,
but none is wired to any launcher, menu, init script, or window-manager binding;
the only interactive surface that actually starts on a shipping unit is a set of
`xterm`s, and one service-mode `xterm` behind a front-panel chord (Section 6).

---

## 1. Inventory — what ships, exact sizes, and identity

All six binaries are `ELF 32-bit LSB executable, ARM, EABI5 ... dynamically
linked, interpreter /lib/ld-linux-armhf.so.3, for GNU/Linux 2.6.32, stripped`.
**[READ]** `file(1)` on `A/usr/bin/{em,gnuchess,lbreakout2,ltris,fluid}`.

| binary | size (B) | identity | UI / transport |
|---|---:|---|---|
| `usr/bin/em` | 83,616 | uEmacs/PK (modal text editor) | ncurses terminal |
| `usr/bin/gnuchess` | 230,476 | GNU Chess **engine** | stdin/stdout (UCI / xboard / native) |
| `usr/bin/gnuchessu` | 787 | `/bin/sh` wrapper → `gnuchess --uci` | — |
| `usr/bin/gnuchessx` | 1,043 | `/bin/sh` wrapper → `gnuchess --xboard` | — |
| `usr/bin/lbreakout2` | 193,748 | LBreakout2 (ball-and-paddle) | SDL 1.2 |
| `usr/bin/lbreakout2server` | 3,640 | network-server **stub** (no-op) | none (see 4.4) |
| `usr/bin/ltris` | 80,072 | LTris (tetris clone) | SDL 1.2 |
| `usr/bin/fluid` | 322,764 | FLTK "Fast Light User Interface Designer" | X11 |

Sizes and ELF identity are **[READ]** from the `ls -la` and `file(1)` listings of
`A/usr/bin/`. A related buildroot toy, `usr/bin/sl` (13,960 B, the "steam
locomotive" `ls`-typo gag), is also present **[READ]** `ls A/usr/bin/sl`.

Supporting data directories that ship **[READ]** (`ls` of `A/usr/share/`):
- `usr/share/gnuchess/` → `gnuchess.ini` (336 B), `smallbook.bin` (38,673 B).
- `usr/share/lbreakout2/` → `gfx/`, `gui_theme/`, `levels/` (135 entries),
  `sounds/`.
- `usr/share/ltris/` → `figures` (4,620 B), `gfx/`, `sounds/`.
- `usr/share/games/plugins/xboard/gnuchess.eng`, `.../logos/gnuchess.png`.
- `usr/share/applications/{lbreakout2,ltris,htop}.desktop`,
  `usr/share/icons/{lbreakout48,ltris48}.gif`.

---

## 2. They are frozen buildroot packages, identical across 1.5.0 and 1.8.2

Every one of the six binaries is **byte-for-byte identical** between the owner's
v1.5.0 image and the decrypted v1.8.2 image. **[READ]** `md5 -q` of each
`A/usr/bin/X` vs `B/usr/bin/X`:

| binary | md5 (first 12 hex) | verdict |
|---|---|---|
| `em` | `1c9f3c2a6ba6` | identical |
| `gnuchess` | `63a9560a6d00` | identical |
| `lbreakout2` | `51c689868fbc` | identical |
| `lbreakout2server` | `a8f2c5d0a1b8` | identical |
| `ltris` | `2767877cd1d3` | identical |
| `fluid` | `c9d1f825bba7` | identical |

`usr/share/gnuchess/smallbook.bin` is likewise identical across versions
(`54b17593aff4955366b74c504b2ba5fd`) **[READ]** `md5`.

**[INFERRED]** These are stock buildroot package outputs baked once and carried
forward unchanged through at least three years of firmware releases (1.5.0 dated
2022-05-16, 1.8.2 built 2025-09-15 per mtimes in Section 5). Evidence: identical
hashes, generic upstream strings, and no Moog-specific symbols in any of them.

---

## 3. `em` — a real modal editor with shell-access primitives

`em` is **uEmacs/PK** (Daniel Lawrence's MicroEMACS, "PK" = Petri Kutvonen
fork). **[READ]** `A/usr/bin/em` strings: `uEmacs/Pk`, `%s version %s`,
`exit-emacs`, `suspend-emacs`, `.emacsrc`, `emacs.hlp`. The task-cited strings are
present verbatim: `Modified buffers exist. Leave anyway` and `Inserted %d line`
**[READ]**.

It links only `libncurses.so.5` and `libc.so.6` **[READ]** `llvm-objdump -p`
(DT_NEEDED). Both libraries are present: `A/usr/lib/libncurses.so.5.9` **[READ]**
`find`. It honours `HOME`, `SHELL`, `TERM` **[READ]** (those exact env-var strings
appear in the binary). Terminfo for `xterm`, `xterm-color`, `xterm-xfree86` ships
under `A/usr/share/terminfo/x/` **[READ]** `ls`, so a terminal session can set the
cursor-addressing `TERM` the editor needs.

### 3.1 Service-access relevance: the command table includes shell escapes

`em`'s bindable command table is compiled in and readable. It contains the full
editor command set **[READ]** (strings matching `^[a-z]+(-[a-z]+)+$`), including
these process/file-reaching commands:

- `i-shell` — spawn an interactive subshell (the binary carries `exec /bin/sh`
  and `SHELL` **[READ]**).
- `shell-command`, `pipe-command`, `filter-buffer` — run an external command,
  optionally piping buffer text through it (`? command too long` prompt string
  present **[READ]**).
- `execute-program`, `execute-file`, `execute-command-line`, `execute-buffer` —
  run programs / macro files.
- `find-file`, `read-file`, `write-file`, `view-file`, `insert-file` — arbitrary
  filesystem read/write.
- `set-encryption-key` — uEmacs's built-in buffer crypto.

**[INFERRED]** An on-device `em` session is a genuine service-access consideration:
from inside the editor an operator can read or write any file the process's uid can
reach and can drop to `/bin/sh`. This is the standard uEmacs feature set, not a
Moog addition (the binary is the stock package, Section 2), but it is live on the
device. `em`'s `HOME` resolves onto the writable partition: `A/root` and `A/home`
are symlinks to `/var/local/root` and `/var/local/home` **[READ]** `ls -la A`, and
`/var` is a read-write ext4 partition (Section 5.1), so `.emacsrc` and buffers are
persistable. No `.emacsrc` or `emacs.hlp` file is shipped in the image skeleton
**[READ]** `find A -iname .emacsrc -o -iname emacs.hlp` → empty.

---

## 4. The games and the UI designer

### 4.1 `gnuchess` is a chess *engine*, not a GUI

`A/usr/bin/gnuchess` is the GNU Chess command-line engine. **[READ]** strings:
`Thinking...`, `book add %s`, `addbook`, `book is now off/best/worst`,
`Command 'white'/'black' is currently not supported`. It links `libreadline.so.6`,
`libncurses.so.5`, `libstdc++.so.6`, `libm`, `libgcc_s`, `libpthread`, `libc`
**[READ]** `llvm-objdump -p`; all present in `A/usr/lib`.

Two `/bin/sh` wrappers select a protocol: `gnuchessu` → `gnuchess --uci`,
`gnuchessx` → `gnuchess --xboard` **[READ]** `cat` of each (they carry the FSF GPLv3
header and the single `exec` line). `gnuchess.ini` is a polyglot-adapter config
(`[Adapter]`/`[Engine]`, `BookFile = smallbook.bin`, `OwnBook = false`) **[READ]**
`cat A/usr/share/gnuchess/gnuchess.ini`. `smallbook.bin` is the opening book.

**No GUI front-end ships.** `xboard` is absent: `ls A/usr/bin/xboard*` → no match
**[READ]**. The only xboard-related files are metadata:
`usr/share/games/plugins/xboard/gnuchess.eng` (`plugin spec 0.0` / `gnuchess -x`)
**[READ]** `cat`. **[INFERRED]** gnuchess is therefore usable only as a
stdin/stdout engine inside a terminal, or driven by an xboard-protocol client that
is not on the device.

### 4.2 `lbreakout2` and `ltris` are SDL-1.2 framebuffer apps — and SDL has no X11 backend

Both link `libSDL-1.2.so.0` **[READ]** `llvm-objdump -p`
(`lbreakout2` also pulls `libpng16`, `libz`, `libm`; `ltris` only SDL/pthread/libc).
The shipped SDL is `A/usr/lib/libSDL-1.2.so.0.11.4` **[READ]** `find`.

The decisive launchability fact: **this SDL build contains only the `fbcon`
(direct Linux framebuffer) and `dummy` video backends — there is no `x11`
backend.** **[READ]** `strings libSDL-1.2.so.0.11.4` yields exactly
`SDL dummy video driver`, `fbcon`, `SDL_VIDEO_FBCON_ROTATION`, `SDL_FBCON_DONT_CLEAR`,
and no `x11`/`X11` video-driver token; `llvm-objdump -p` shows its DT_NEEDED is
`libm, libdl, libts-1.0.so.0, libpthread, libc` — it links tslib (touchscreen) but
**does not link libX11** (contrast `fluid` and `xterm`, which do). So the games
cannot render into the X server that the device runs; they would drive a raw
framebuffer.

SDL fbcon's device/input defaults, read from the same library **[READ]**:
- Framebuffer: `SDL_FBDEV` env, else `/dev/fb0` (also `/dev/fb/0`).
- Keyboard: `/dev/tty` — it sets the console keyboard to raw/graphics mode
  (`Unable to set keyboard in raw mode`, `Unable to set keyboard in graphics mode`).
- Mouse: `SDL_MOUSEDEV`, else `/dev/input/mice` / `/dev/mouse`.
- Touchscreen: tslib via `TSLIB_TSDEVICE` → `/dev/input/event%d`.

**[INFERRED]** On a shipping unit `/dev/fb0` is the X server's display (xorg.conf
binds the `vivante` driver to `/dev/fb0`, Section 6.1), so an SDL-fbcon game
started with defaults would contend with Xorg for the framebuffer; `/dev/fb1` is
the panel surface the splash/boot path configures. There is no ordinary console
keyboard in the product's user-facing state (front-panel input arrives via XMOS and
`las-frontpanel-poll`, not a Linux keyboard device), so even a successfully drawn
game would have no standard input path unless a USB keyboard/mouse were attached to
the i.MX6 USB host. Whether such a device is attached in any field scenario is
**[UNKNOWN]** from disk.

Their data is complete and would support a real session if run: `lbreakout2` has
135 `levels/` entries plus `gfx/`, `gui_theme/`, `sounds/`; `ltris` has `figures`,
`gfx/`, `sounds/` **[READ]** `ls`. `lbreakout2`'s data root `/usr/share/lbreakout2`
is a compiled-in constant **[READ]** (string at file offset `0x299a0`).

### 4.3 `fluid` is the FLTK UI designer — a build-time developer tool

`fluid` is FLTK's interface designer. It links the full FLTK + X11 + Cairo +
fontconfig + Xft stack **[READ]** `llvm-objdump -p`: `libfltk*.so.1.3`,
`libcairo`, `libpixman-1`, `libX11`, `libXft`, `libXext`, `libXcursor`,
`libXfixes`, `libXinerama`, `libfontconfig`, `libjpeg`, `libpng16`, etc.
**[INFERRED]** It is a developer authoring tool for `.fl` UI layouts with no role
at runtime; its presence is build-environment residue carried into the shipped
image (consistent with the X11/build-residue findings in the existing
`gap-x11-display-and-build-residue.md`, Section 7). No `.fl` source files were
searched for here (**[UNKNOWN]** whether any ship).

### 4.4 `lbreakout2server` is a non-functional stub

Despite the name, `lbreakout2server` is a 3,640-byte do-nothing binary. **[READ]**
its entire string table contains the networked-server's disabled message
`LBreakout2 has been compiled without network support.` and nothing resembling
socket setup; its dynamic symbol table imports only `printf`, `dcgettext`, `abort`,
`__libc_start_main` (GLIBC_2.4) — **no `socket`/`bind`/`listen`/`accept`**
**[READ]** `llvm-objdump -T`. **[INFERRED]** It prints the "no network support"
line and exits; it opens no listening port. This removes it as any kind of network
service.

---

## 5. The live `/var/*.hscr` files are default tables, not gameplay

Two high-score files sit in the writable partition:
`A/var/lbreakout2.hscr` (229 B) and `A/var/ltris.hscr` (223 B) **[READ]** `ls -la`.
This is the observation that makes the region look "run on a unit." It is not.
Three independent proofs:

### 5.1 They are byte-identical across two firmware versions three years apart

`md5` of both files matches exactly between 1.5.0 and 1.8.2 **[READ]**:
`lbreakout2.hscr = 17bc1949b9e6e401662580d59054fb07`,
`ltris.hscr = c8dcd85ee3c97c11f02f3ca114a99007`; `diff` reports both identical.
A genuinely played table would diverge between two different instruments/builds.

(`/var` is its own ext4 partition — `/dev/mmcblk2p6 /var ext4` **[READ]**
`A/etc/fstab` line, confirmed live as `rw,noatime` in
`arch-harvest/runtime-state.txt:181`, a mount-table line the caveat file marks as
valid. The files read here are in the image's `/var` skeleton.)

### 5.2 The contents exactly match the generator compiled into each binary

The on-disk tables are `>>>LBreakout2` / `>>>classic` headers, then ten records of
`............` (name), rank, score **[READ]** `xxd`. The lbreakout2 ladder is
`300000, 200000, 150000, 100000, 70000` then `50000, 40000, 30000, 20000, 10000`;
ltris is a flat `100000, 90000, … , 10000`.

Disassembly shows these are *generated*, not authored:

- **lbreakout2**, default-table routine at `.text` VMA `0x1f1a4` **[READ]**
  `llvm-objdump -d`: a loop (`0x1f1a4`–`0x1f1dc`) does
  `movw r6, #0x2710` (10000), then `mul r3, r6, r5` for ranks r5 = 1..10 —
  i.e. `score = 10000 × rank` — `memset`-ing a 440-byte-per-entry struct and
  storing the placeholder name. Then `0x1f1e0`–`0x1f204` overwrites the top five
  scores from a literal pool at `0x1f220`: the words are
  `0x3b0ac` (pointer to the `............` name string, which at file `0x2b0ac`
  reads `"............\x00>>>"` **[READ]**), `0x000493e0`=300000, `0x00030d40`=200000,
  `0x000249f0`=150000, `0x000186a0`=100000, `0x00011170`=70000. That reproduces the
  shipped file exactly.
- **ltris**, default-table routine at VMA `0x18abc` **[READ]**: same shape —
  `movw r6, #0x2710`, `mul r3, r6, r4` for ranks 1..10 (no top-five override), name
  pointer `0x224eb` → file `0x124eb` = `"............\x00>>>"` **[READ]**. That
  reproduces the flat `10000 × rank` ladder exactly.

The placeholder player name (`............`) and the section headers are literal
program constants, not user initials. **[INFERRED]** Both files are precisely what
each game writes the first time it finds no chart — the upstream "creating new one"
path (`Highscore chart doesn't exist in '%s'... creating new one.`,
`Saving highscore chart in: %s`, both **[READ]** in the binaries).

### 5.3 Build-time mtimes, in lockstep, 101 seconds apart, in both images

**[READ]** `stat` mtimes:

| file | v1.8.2 | v1.5.0 |
|---|---|---|
| `var/lbreakout2.hscr` | 2025-09-15 11:43:03 | 2022-05-16 08:00:20 |
| `var/ltris.hscr` | 2025-09-15 11:44:44 | 2022-05-16 08:02:01 |
| `usr/bin/{lbreakout2,ltris}` | 2025-09-15 12:19:03 | 2022-05-16 08:41:10 |

In both images the two `.hscr` files are stamped **101 seconds apart**
(11:43:03→11:44:44; 08:00:20→08:02:01) and **~36 minutes before** the game binaries
were installed into `usr/bin`. **[INFERRED]** That is a deterministic build step
(a target-filesystem skeleton staged ahead of package install), not interactive
play — play would have to occur *after* the binaries exist, would not reproduce the
same 101-second gap on two unrelated builds, and would not leave byte-identical
tables. The `.hscr` mtimes fall inside the dominant 2025-09-15 / 2022-05-16
build-day cohort (3,566 files each) **[READ]** mtime histogram.

**Conclusion:** the high-score files are build artifacts. They are not proof the
games were ever run on any instrument. (The task framing that `/var` state
"suggests these were actually run" does not survive the disassembly.)

---

## 6. Reachability — is any of this launchable on a shipping unit?

Short answer: **nothing launches these automatically, and no shipped launcher
offers them.** The evidence:

### 6.1 What the boot path actually starts

Init is BusyBox (`A/etc/inittab` → `::sysinit:/etc/init.d/rcS`) **[READ]**. The GUI
comes up through two scripts:
- `S12splash` configures `/dev/fb1` (832x480) and starts the X server:
  `X :0 -nocursor -s 0 &`, then `dd`s the splash image to `/dev/fb1` **[READ]**
  `cat A/etc/init.d/S12splash`. `X` is a symlink to `Xorg`; `xorg.conf` binds the
  `vivante` driver to `/dev/fb0` **[READ]** `cat A/etc/X11/xorg.conf`.
- `S43gui` launches, on `DISPLAY=:0`: three `xterm`s (named xterm1/2/3,
  `10x20`, white-on-black), then `las-frontend`, then the `las-dwm` window manager,
  then screen transforms; finally it backgrounds `detect-held-buttons` **[READ]**
  `cat A/etc/init.d/S43gui`.

None of `em`, `gnuchess`, `lbreakout2`, `ltris`, or `fluid` is referenced by any
init script: `grep -rIl` over `A/etc` for those names returns only two udev hwdb
files (coincidental substring matches), never a launch **[READ]**.

### 6.2 The window manager spawns only xterms (+ a dmenu that isn't installed)

`las-dwm` is a dwm-6.1 fork **[READ]** (`dwm-6.1`, `dwm: execvp %s` strings). Its
spawnable targets in the string table are `xterm`/`xterm1..xterm9` and the default
dwm launcher command `dmenu_run` **[READ]**; it names no game or editor. And
**`dmenu` is not installed**: `ls A/usr/bin/dmenu*` → no match **[READ]**, so the
`Mod+p` launcher path is dead. The WM also carries a `phonehome` reverse-SSH string
(out of scope here; relevant to the network/remote-access gap, not this one)
**[READ]**.

### 6.3 There is no menu system to consume the `.desktop` files

Three XDG desktop entries ship (`lbreakout2.desktop`, `ltris.desktop`,
`htop.desktop`) with `Exec=lbreakout2` / `Exec=ltris` and `Categories=Game;`
**[READ]** `cat`. But **no application-menu / launcher reads them**: there is no
`lxpanel`, `lxde`, `pcmanfm`, `rofi`, `dmenu`, `feh`, `nautilus`, or any `xdg-*`
menu binary in `A/usr/bin` **[READ]** `ls | grep`. **[INFERRED]** The `.desktop`
files and the `lbreakout48.gif`/`ltris48.gif` icons are orphaned buildroot package
residue with nothing to display or invoke them.

### 6.4 The one interactive back-door that *does* ship: service mode

`detect-held-buttons` (a bash script in `S43gui`'s tail) polls the front panel
via `las-frontpanel-poll /cb`; on button code `48` ("HOME+SETTINGS pressed at
startup, launching service mode") it kills `las-watchdog`, `las-frontend`,
`las-sc`, and the xterms, then opens a held `xterm` running
`lassvc -t vc:7770 -p vc:9100` and issues `xdotool key alt+2` **[READ]**
`cat A/usr/bin/detect-held-buttons`. **[INFERRED]** This is the sanctioned
interactive surface. It drops to a terminal (under X, via xterm) — and from a shell
in that terminal, `em`, `gnuchess`, `sl`, and anything else on
`PATH=/bin:/sbin:/usr/bin:/usr/sbin` **[READ]** `A/etc/profile` are directly
invocable, *given a keyboard attached to the i.MX6 USB host*. The SDL games remain
constrained by the framebuffer/X contention and no-X11-backend facts of Section 4.2.

### 6.5 Net assessment of reachability

- **`em`, `gnuchess` (+ `sl`)**: terminal programs; **[INFERRED]** runnable inside
  an xterm (the xterms exist, `xterm` terminfo ships) once a keyboard is present —
  i.e. reachable through service mode by someone with physical/console access. No
  product feature exposes them to an end user.
- **`lbreakout2`, `ltris`**: **[INFERRED]** not practically runnable in the product
  state — SDL has no X11 backend, so they bypass the running X server onto a raw
  framebuffer that X owns, and they need a console keyboard/mouse the product does
  not present. Executable in principle; not wired to anything.
- **`lbreakout2server`**: inert stub (Section 4.4).
- **`fluid`**: developer tool; no runtime role (Section 4.3).
- **Automatic launch of any of them: none.** **[READ]** (absence across all init
  scripts, WM, and menu systems).

---

## 7. Conflicts and overlaps with existing docs

Per the project rule I did not edit any existing doc. Noting overlaps/tensions:

1. **`docs/MOOG-ONE-INTERNALS.md` already names the games.** Its section "And,
   genuinely, games" (line ~1861) lists
   `gnuchess gnuchessu gnuchessx lbreakout2 ltris sl` and calls them "Buildroot
   default package selection, left in the production image" **[READ]**
   `sed -n` of that file; the same text is mirrored in
   `docs/site/moog-one-internals.html:1248`. So the gap brief's statement that
   "None are named in any report" is **partly incorrect**: the *games* are named
   there (one line, no analysis). What remains genuinely uncovered — and is
   documented here for the first time — is **`em` (the editor), `fluid`,
   `lbreakout2server`, the `/var/*.hscr` provenance, the SDL-backend/launchability
   analysis, and the cross-version identity diff.** That prior paragraph asserts
   only "installed ... left in the image"; it makes no launchability or
   default-table claim, so there is no factual contradiction to resolve, only a
   coverage overlap.

2. **`docs/firmware/gap-x11-display-and-build-residue.md`** (not read in full here)
   is the sibling region for the X11/build-residue story; `fluid`'s classification
   as a build-time developer tool (Section 4.3) belongs alongside it. No conflict
   observed; flagged for cross-reference.

3. No existing doc was found to mention `em`/uEmacs, `lbreakout2server`, or the
   `.hscr` files at all **[READ]** `grep -rIl` over `docs/`.

---

## 8. Validation plan (READ-ONLY; for a human to run on the instrument)

Do not run any of these as part of this analysis — they are proposed commands for
the owner to execute on the live unit if independent confirmation is wanted. All
are read-only and touch none of the synth processes.

1. Confirm the high-score files on the live `/var` (p6) match the build defaults:
   `md5sum /var/lbreakout2.hscr /var/ltris.hscr` — expect
   `17bc1949b9e6e401662580d59054fb07` and `c8dcd85ee3c97c11f02f3ca114a99007`.
   A different hash would mean a game *was* actually played post-build (it would
   refute Section 5 for that unit).
2. `cat /var/lbreakout2.hscr` — expect the `>>>LBreakout2` / `............` default
   ladder verbatim.
3. `strings /usr/lib/libSDL-1.2.so.0 | grep -iE 'x11|fbcon|dummy'` — expect
   `fbcon`/`dummy` only, confirming no X11 backend (Section 4.2).
4. `ls -l /usr/bin/dmenu; which dmenu` — expect absent, confirming the WM launcher
   path is dead (Section 6.2).
5. `ps | grep -E 'xterm|las-dwm|Xorg'` — confirm which interactive surfaces are
   actually running; expect the three xterms + las-dwm + X, no game/editor process.
6. `cat /proc/bus/input/devices` (or `ls /dev/input`) — enumerate whether any
   keyboard/mouse is attached, which bounds whether `em`/games could receive input.

---

## 9. Unexplored

- `fluid`'s `.fl` source inputs: not searched for across the image (**[UNKNOWN]**
  whether any ship); would confirm/deny active UI authoring on-device.
- `em`'s macro files (`execute-macro-1..10`, `.emacsrc`): none in the image
  skeleton, but `/var/local/root` (writable) was not inspected on a live unit.
- Whether a USB keyboard attached to the i.MX6 host enumerates in any field
  configuration (requires a live read; see validation plan item 6).
- `sl`, `htop.desktop`, and the `xboard` plugin metadata were inventoried but not
  disassembled.
- The `las-dwm` `phonehome` reverse-SSH string was noted in passing; it belongs to
  the network/remote-access region, not this gap.
