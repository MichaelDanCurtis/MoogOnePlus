# The embedded JavaScript surface in `las-frontend` (v1.8.2)

Scope: verify or refute the prior claim (`docs/arch/extension-points.md` §10 and
`docs/arch/capability-survey.md` §B5) that `las-frontend` contains a JavaScript
sandbox with a calibration-write API. Establish precisely: what engine, what is
exposed, how a script is loaded, what it can reach, and the security implications
for a device that also accepts a USB drive.

Primary evidence is the decrypted v1.8.2 root filesystem at
`captures/firmware-1.8.2/rootfs-1.8.2`. The subject binary is
`usr/bin/las-frontend` (ELF 32-bit ARM, EABI5, dynamically linked, stripped;
145,033,524 bytes; MD5 `3aa501cfcf1bfc5f5694997e28fb690d`). All VMAs below assume
the single r-x LOAD segment, where `file_offset = VMA − 0x10000` (`.text`
0x19700–0xa452d4, `.rodata` begins 0xa452e0). Disassembly is
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`. No instrument was touched.

Bottom line: **the claim is CONFIRMED, with one material correction.** The
sandbox is real, it is JUCE's `JavascriptEngine`, and `Panel` does expose `cal*`
methods. But those `cal*` methods are **not** direct voice-card / `vxcal.db`
writes. They emit OSC messages (`/cal:save`, `<target>:cal_low|mid|high`, …) to the
panel-output host, and every `/cal` target in the binary is a **front-panel / LHC /
keybed** control (pitch wheel, glide, mod, aftertouch, X/Y pad, left+right keybeds),
not a voice card. This narrows — and partly relocates — the Tier-1 danger the prior
reports attached to it. See §7 and Conflicts.

---

## 1. There is a JavaScript engine, and it is JUCE's `JavascriptEngine`

**[READ]** The engine is `juce::JavascriptEngine`, not Duktape, QuickJS,
JerryScript, V8, mujs, or Lua. Two independent lines of evidence:

* Mangled RTTI names for the interpreter's AST node classes, all under
  `N4juce16JavascriptEngine10RootObject…E`, run contiguously from file offset
  **143,990,840** (VMA 0x896xxxx in `.rodata`): `StatementE`, `ExpressionE`,
  `BlockStatementE`, `IfStatementE`, `VarStatementE`, `LoopStatementE`,
  `ReturnStatementE`, `BreakStatementE`, `ContinueStatementE`, `LiteralValueE`,
  `UnqualifiedNameE`, `DotOperatorE`, `ArraySubscriptE`, `BinaryOperatorE` and every
  operator subclass, `FunctionCallE`, `NewOperatorE`, `ObjectDeclarationE`,
  `ArrayDeclarationE`, `FunctionObjectE`, `ObjectClassE`, `ArrayClassE`,
  `StringClassE`, `MathClassE`, `JSONClassE`, `IntegerClassE`. This is the exact
  class layout of JUCE's `juce_JavascriptEngine.cpp`.
* The interpreter's built-in identifier table at file offset **144,018,940–144,019,415**
  (verbatim): `this`, `prototype`, `Unknown function '`, `exec`, `eval`, `trace`,
  `charToInt`, `parseInt`, `parseFloat`, `dump`, `clone`, `contains`, `remove`,
  `splice`, `indexOf`, `substring`, `charAt`, `charCodeAt`, `fromCharCode`, `split`,
  `randInt`, `toDegrees`, `toRadians`, `asin`/`acos`/`atan`(+`h`), `log10`, `pow`,
  `sqrt`, `ceil`, `floor`, `PI`, `SQRT2`, `SQRT1_2`, `LN2`, `LN10`, `LOG2E`,
  `LOG10E`, `stringify`, `Math`, `JSON`. These are the JUCE JS built-ins.

**[READ]** The runner that hosts the engine is `las::LASScriptRunner` (typeinfo
`N3las15LASScriptRunnerE` at file offset 132,424,208; `Pimpl` at 132,423,876).
Supporting types: `las::QuitScriptException` (132,423,836),
`las::ScheduleScriptCallback` (132,424,240), `las::ScriptFailedCallback`
(132,424,284). Operator/status strings: `"A script is already running"`
(132,424,352), `"Script Runner"` (132,424,380), `"Failure while running script:"`
(132,424,394), `"Quitting script"` (132,430,923), `"Shutting down application"`
(132,425,672).

**[READ]** Only `las-frontend` contains a JS engine. Grepping every ELF in
`usr/bin`, `usr/lib`, `usr/sbin`, `bin`, `sbin`, `lib` for
`JavascriptEngine|duk_|JerryScript|QuickJS|lua_State` returns `usr/bin/las-frontend`
alone. `las-sc`, `las-dwm`, `lassvc`, `lasfwu`, `las-watchdog`, `last` all report
zero matches for `javascript|JavascriptEngine|ScriptRunner`. The scripting surface
lives entirely in the front-panel process on cpu0. It has no presence in the audio
engine (`las-sc`/scsynth on cpu1) or the updater.

**[READ]** The engine caps a script's run time. `LASScriptRunner::Pimpl` constructs
the engine and stores a `RelativeTime` of **365.0 seconds** as its
`maximumExecutionTime` (IEEE-754 double `0x4076d00000000000` at VMA 0x1cf238, loaded
via `vldr d0,[pc,#992]` at 0x1cee50 and passed to the seconds→`RelativeTime`
constructor at 0x8fd060). This is a runaway-script guard, not a security boundary —
it bounds wall-clock, not what host calls a script may make. A separate 5000 ms
(`movw r1,#0x1388` at 0x1ced44) governs thread teardown on quit.

---

## 2. How a script is invoked

There are three entry points, all **[READ]**:

### (a) `--script=<path>` on the command line

**[READ]** Help text at file offset 132,803,426:
`"  --script=<path>        Runs the JavaScript at the provided file path"`.
Flag literal `"--script="` at 132,808,111 (VMA 0x7eb7daf).

**[READ]** Argument handling (disassembly at 0x8cd9dc): the parser compares each
argv token against `"--script="` (`String::startsWith`, `bl 0x9155b0`); on a match
it extracts the substring after `=` and stores it into the application object at
member offset **+0x40**.

**[READ]** Execution of that stored path (disassembly at 0x8cb4d0, reached from the
startup routine at 0x8cf308): the routine loads the `std::string` at object+0x40,
tests its first byte, and **iff non-empty** builds a `juce::File` from it (via
`File::getCurrentWorkingDirectory().getChildFile(...)` at 0x920c5c / 0x9128f8 — so a
relative path is resolved against the cwd, an absolute path is taken as-is;
`isAbsolutePath` at 0x8f9840 tests a leading `/`) and calls the script launcher at
0x8c51b8, which drives `LASScriptRunner::runScript` (0x1c4088→0x1ceca4). So: a path
supplied on the command line is read from the local filesystem and executed at
startup. There is no PIN, prompt, allow-list, or signature check anywhere on this
path.

### (b) `--test-fixture` — the factory hardware-test panel

**[READ]** Help text at 132,803,711:
`"  --test-fixture         Boot into HardwareTestPanel for use at CM"` ("CM" =
contract manufacturer). Flag literal at 132,808,169. The flag sets a bool at object
offset +0x6a8 (disassembly at 0x8cdac4; read back at 0x8cb07c). `HardwareTestPanel`
(typeinfo `17HardwareTestPanel` at 132,554,088; methods `runAllTests`, `confirm`,
`setVisible` visible as lambda thunks at 132,553,xxx) runs the six built-in scripts
(§3) through the same `runScript` launcher (six call sites at 0x6d1d74…0x6d1e8c, all
→ 0x8b15ec).

### (c) Built-in resources, run by (b)

Six factory scripts are compiled into the binary as JUCE `BinaryData` resources
(§3), addressed by a name/data/size table at VMA 0x8a70070 (data pointers),
0x8a7008c (mangled names), 0x8a700f0 (original filenames).

**Not an entry point:** the stock boot does **not** pass `--script=`.
`etc/init.d/S43gui:21` launches `las-frontend` with `--usb-path=/media/thumbdrive
--data-path=/var/las-frontend --host-paneloutput=203.0.113.2 --host-performance=vc
--host-oleds=203.0.113.2 --affinity-mask=1 --host-systemclock=vc --cookie=1
--affinity-panel=1 --startup-coordination --host-vc=vc` — no `--script`, no
`--test-fixture`. **[READ]** To reach the CLI script surface you must either edit
`S43gui` (rootfs = Red in `docs/DANGER.md`) or already have a shell (see §8).

---

## 3. The five host objects and their full method vocabulary

**[READ]** Five JS globals are registered, read directly from the class
constructors and their native-method registration pools. (`OSC` and `OSCSender`
are two registered names for one class, so the prior report's "five host objects"
is correct as a count of globals.)

| Global | JS class | native methods (verbatim from the binary) |
|---|---|---|
| `Console` | `las::ScriptConsoleClass` (ti @132,424,600) | `debug`, `println` (registration pool @0x1cf408; `info`/`log` strings present nearby but only `debug`/`println` are wired) |
| `Display` | `las::ScriptDisplayClass` (ti @132,424,824) | `clear drawEllipse drawLine drawRect drawRoundedRectangle drawText fillAll fillEllipse fillRect fillRoundedRectangle setColour setFontSize activateChineseFont activateLatinFont showOled clearOled fillOled setOledColour` plus getters `width`,`height` and `show` (pool @0x1dab48) |
| `OSC` / `OSCSender` | `las::ScriptOscClass` / `las::ScriptOscSenderClass` (ti @132,425,236 / 132,425,192) | `sendMsg` (pool @0x1dad68); the class also exposes `connect(host,port)` (native fn @0x1dad78, string `"connect"` @0xa45d88) |
| `Panel` | `las::ScriptPanelClass` (ti @132,425,604) | `waitForChange waitForChangeAndClearLED waitForValue waitForAtLeast waitForAtMost waitForReply waitForFullTurn waitForSpacebar setLED sendLEDs sendAllLEDs clearLEDs flashLED unflashLED monitor monitorAndClearLED readValue unMonitor` **and the eight `cal*` methods** `calLoad calSave calDefaults calSetLow calSetMid calSetHigh calSetXYUpperLeft calSetXYLowerRight` (pool @0x1dc0d0–0x1dc19c) |
| `Utils` | `las::ScriptUtilsClass` (ti @132,430,992) | `sleep` (pool @0x1ee870) |

**[READ]** `Display` targets the physical panel/OLEDs/LCD, not a virtual canvas:
its `width`/`height` getters read the panel geometry from the owning component
(`ldr r1,[r5,#0x18]`/`[r5,#0x1c]` in the ctor at 0x1da530/0x1da570), and the factory
LCD test (§3.1) uses `Display.fillAll(0xff,0x00,0x00)` to flood the screen red. So
`Display` draws to the instrument's screens.

**[READ]** `Panel.monitor(name, …)` / `readValue(name)` / `waitForValue(name,…)` are
keyed by the human-readable control names — there is a table of **326** NUL-separated
control-name strings at file offset 132,426,016–132,430,923 (`"LFO 1 Type"`,
`"OSC 1 Frequency"`, `"Sequencer Step 16"`, `"X Pad"`, `"Y Pad"`, `"Z Pad"`,
`"Pitch Wheel"`, `"Glide"`, …). A script addresses panel controls by these names.

### 3.1 What the six built-in scripts actually are

**[READ]** Extracted verbatim from the binary (six contiguous ASCII/UTF-8 blobs in
`.rodata`, sizes 20,394 / 60,073 / 37,064 / 30,411 / 30,704 / 47,336 bytes at file
offsets 133,514,613 / 133,535,008 / 133,595,083 / 133,632,149 / 133,662,561 /
133,693,266). Filenames, from the BinaryData table at 0x8a700f0:

* `BRD-10-011-1204_SYS_TEST.js`
* `BRD-10-011-1207_RIGHT_TEST.js`
* `BRD-10-011-1208_MIDDLE_TEST.js`
* `BRD-10-011-1209_LEFT_TEST.js`
* `FRONT_PANEL_ASSEMBLY_TEST.js`
* `LHC_SUBASSEMBLY_TEST.js`

They are bilingual (English + Simplified Chinese) manufacturing test scripts: press
each switch and confirm its LED, sweep each pot and read min/max, flood each OLED
and the LCD with R/G/B/black/white and confirm by eye, monitor the X/Y/Z pad
ranges. They use only `Display.*`, `Panel.setLED/sendLEDs/sendAllLEDs/waitFor*/
monitor/readValue`, `Console.println`. **None of the six calls any `cal*` method,
and none uses `OSC.sendMsg`.** (Verified by enumerating every `Object.method` token
in each blob.) Representative line from `LHC_SUBASSEMBLY_TEST.js`:
`["Press OCTAVE ->", "请按下开关 OCTAVE ->", "Octave Positive", "Octave +2", "Is OCTAVE +2 LED off?", …, "LED5, SW2"]`.

**[READ]** The six scripts are **byte-identical** between v1.5.0 (frontend 2.0.8) and
v1.8.2 (frontend 2.1.4) — matching MD5s for all six blobs. The scripting surface is
old and stable, not a 1.8.2 addition.

---

## 4. What a script can reach — the real capability

Ranked by reach, all **[READ]** for the mechanism:

1. **`OSC.sendMsg` / `OSC.connect(host, port)` — arbitrary OSC to an arbitrary
   endpoint.** This is the widest capability. `ScriptOscClass::sendMsg` (0x1dae9c)
   takes an address string plus a varargs list, builds a `juce::OSCMessage`
   (appending int/float/string args by JS type), and hands it to a stored
   `juce::OSCSender` (`sender->send(msg)` at 0x1daf5c). `connect` (0x1dad78) opens
   that sender to a caller-supplied host and port. A script can therefore address
   anything on the network the frontend can: `las-sc` on `localhost:9300`, the FX
   server, the panel host, and the voice controller `vc` = **203.0.113.2**
   (`/etc/hosts`). Where the frontend's own OSC namespace can write, so can a script.
   The prior report's instinct ("the OSC object is the interesting part") is correct.

2. **`Panel.cal*` — panel/LHC/keybed calibration commands, emitted as OSC.** See §7.

3. **`Panel.setLED/sendLEDs/sendAllLEDs/clearLEDs/flashLED` and
   `Display.*`** — full control of the front-panel LEDs and all screens. Cosmetic,
   but total.

4. **`Panel.monitor/readValue/waitFor*`** — read live panel control values and block
   on user input. A script can observe every knob, wheel, pad and switch.

5. **`Utils.sleep`, `Console.debug/println`** — timing and logging to the frontend's
   log/stderr.

**Not exposed:** there is **no** file-system object, no `System`/`exec`/`Process`
host object, no network object beyond the OSC sender, and no direct memory access.
`exec`/`eval`/`trace` in §1's identifier list are JUCE's in-language built-ins
(string-eval within the same sandbox), not OS process execution. The reach is
"whatever OSC can do" plus "the front panel," which is still very large — but it is
not a general shell.

---

## 5. The `Panel.cal*` methods, traced to the wire

**[READ]** Each `cal*` method is a thin native function that sends a fixed OSC
message through the application's `PanelOutputSender` (typeinfo
`las::PanelOutputSender` @132,419,617; the sender pointer is fetched via
`getPanelOutputSender`, disassembled at 0x8b0d90 = `ldr r0,[r3,#0x494]`). The
target addresses, read from the literal pools the `cal*` handlers load:

| JS method | OSC address emitted | file offset of the string |
|---|---|---|
| `Panel.calLoad()` | `/cal:load` | 132,419,758 |
| `Panel.calSave()` | `/cal:save` | 132,419,768 |
| `Panel.calDefaults()` | `/cal:cal_default` | 132,419,778 |
| `Panel.calSetLow(target)` | `<target>:cal_low` | suffix `:cal_low` @132,551,810 |
| `Panel.calSetMid(target)` | `<target>:cal_mid` | suffix `:cal_mid` @132,552,594 |
| `Panel.calSetHigh(target)` | `<target>:cal_high` | suffix `:cal_high` @132,551,024 |
| `Panel.calSetXYUpperLeft()` | `/cal/lhck/xy:cal_ul` | 132,419,795 |
| `Panel.calSetXYLowerRight()` | `/cal/lhck/xy:cal_lr` | 132,419,835 |

**[READ]** `calSetLow/Mid/High` take a target argument that selects a base address
from a small table the handler indexes (`0x1ab5a0` maps an id → one of the strings
below), then appends the `:cal_low|mid|high` suffix. Every base address in that
table, and every other `/cal` address in the binary, is a **panel / LHC / keybed**
control:

* `/cal/lk` (132,419,679) — left keybed
* `/cal/rk` (132,419,687) — right keybed
* `/cal/lhck/pitch` (132,419,695) — LHC pitch wheel
* `/cal/lhck/glide` (132,419,711) — LHC glide
* `/cal/lhck/mod` (132,419,727) — LHC mod wheel
* `/cal/lhck/atouch` (132,419,741) — LHC aftertouch
* `/cal/lhck/xy` (in the two XY addresses above) — the X/Y pad

`cal_low`/`cal_mid`/`cal_high` are the three-point range calibration of those analog
controls; the XY pad gets corner calibration (`cal_ul`/`cal_lr`). `calSave` then
persists the set, `calLoad` reloads it, `calDefaults` resets it. These messages go
to `--host-paneloutput` = **203.0.113.2** (`S43gui:21`), i.e. the voice-controller /
panel side, which owns and stores this LHC/keybed calibration. **[INFERRED]** The
persistence therefore happens on the VC/panel side, not inside `las-frontend`; the
frontend only emits the command.

**This is the correction to the prior reports.** The `cal*` API is real and
unauthenticated, but it calibrates the **playing surface** (wheels, X/Y pad,
keybeds), not the **voice cards' analog DAC/ADC calibration** that `docs/DANGER.md`
Tier 1 protects (`/var/cal/vxcal.db`, per-card, factory-equipment-only to regenerate).
No `cal*` method in the JS surface, and no `/cal` address in the frontend binary,
targets a voice card. See Conflicts.

Damage assessment for the JS `cal*` surface, **[INFERRED]** from the above:
mis-calibrating a pitch wheel / mod wheel / X-Y pad / keybed is user-recoverable —
the same calibration exists in the instrument's own SETTINGS → CALIBRATION menu, and
`calDefaults` plus a re-run restores it. It is a genuine footgun (a wrong script
makes the wheels and pads read wrong until re-calibrated) but it is **not** the
"no backup covers it" voice-card damage the prior text implied. The truly
irrecoverable Tier-1 path (voice-card flash / `vxcal.db`) is reached by other means
(hand-sent `/fw/*` to `203.0.113.2:7770`, `config-las-spi`, `las-sc --cli`; see
`docs/DANGER.md`), not by these JS methods — though note that `OSC.sendMsg` /
`OSC.connect` (§4 item 1) could construct those other messages directly, which is
the real Tier-1 exposure of the scripting surface.

---

## 6. Version and provenance

**[READ]** `etc/git-tags`: v1.8.2 ships `LAS_FRONTEND 2.1.4`
(`LAS_BUILDROOT v1.8.2`, `/etc/version` = `las-v1.8.2`). The v1.5.0 comparison
tree ships `LAS_FRONTEND 2.0.8`. The scripting surface — the `--script=` flag, the
five host globals, the full `Panel.cal*` vocabulary, and the six embedded scripts —
is present and identical in both. Nothing about this surface is new in 1.8.2; it has
been in the shipping frontend since at least 2.0.8.

---

## 7. Security implications, especially with a USB drive attached

**What is true:**

* **[READ]** A `.js` file executed via `--script=` runs with the full §4 capability
  set — most importantly `OSC.sendMsg`/`OSC.connect` to any host:port, which reaches
  `las-sc`, the FX server, the panel host, and the voice controller at
  `203.0.113.2`. There is no PIN, prompt, signature, or allow-list on the script
  path (`docs/DANGER.md` D10 already notes no signature check in the update path;
  the script path has none either).
* **[READ]** `Panel.cal*` lets a script issue panel/LHC/keybed calibration commands
  (§5) with no confirmation.

**What blunts it — the USB question specifically:**

* **[READ] A USB drive does not auto-run JavaScript.** The frontend's USB scan
  (`--usb-path=/media/thumbdrive`) looks for databases: the only file-glob the USB
  ingest code loads is **`*.db`** (string `"*.db"` @132,640,057; "Looking for USB
  files in " @132,808,500), plus firmware packages via the updater. There is **no**
  `*.js` glob and no code path that runs a script off the USB drive. Dropping a
  `.js` on a thumb drive does nothing on its own. **[INFERRED, strong]** the USB
  drive is therefore not a direct script-injection vector.
* **[READ]** To actually run a `.js`, an attacker needs one of: (a) edit
  `S43gui` to add `--script=` (requires write access to the rootfs, which
  `S99final` remounts read-only at end of boot unless the magic key file is present
  — Red partition, reverted by any firmware update); or (b) a shell.
* **[READ]** The shell itself is what the USB drive gates. `etc/init.d/S50dropbear`
  starts dropbear (SSH) **only if** `/media/thumbdrive/k` exists and
  `hexdump`s to the constant `23051934`. The same key file makes `S99final:36` kill
  `las-watchdog` and skip the read-only remount. So the realistic chain is: **USB
  key file → SSH → root shell → `las-frontend --script=/path/to.js` (or edit
  S43gui)**, at which point the JS surface is one of many capabilities an already-root
  attacker holds. The scripting engine is not the privilege-escalation step; the USB
  key file is.
* **[INFERRED]** Consequence: the JS sandbox is best understood as a **post-access**
  capability, not an initial attack surface. Its danger is realized by someone who
  can already start the process with an argument (root via the SSH backdoor, or a
  rootfs edit). For such an actor the notable powers are (1) arbitrary OSC to the VC
  — which can reach the genuine Tier-1 voice-card paths — and (2) panel/keybed
  mis-calibration.

**Net risk rating** (consistent with the prior reports' own placement): low
likelihood (no auto-run, needs prior access), high-but-recoverable impact for the
`cal*` methods specifically, and high impact via `OSC.sendMsg` if used to reach the
Tier-1 voice-card endpoints. Any script harness for this instrument should refuse
to emit `cal*` and should refuse `OSC` messages to `203.0.113.2:7770` (the voice-card
firmware/`/fw` path) unless the operator explicitly opts in.

---

## Conflicts with existing docs

1. **`docs/arch/capability-survey.md` §B5** and **`docs/arch/extension-points.md`
   §10** classify `Panel.calSave`/`calSetLow/Mid/High` as **voice-card calibration
   writes** and call the surface "Tier-1-adjacent … the one category of damage that
   no backup in this repo covers if it lands on a voice card rather than `vxcal.db`."
   The binary evidence (§5) shows these methods emit OSC to **panel / LHC / keybed**
   `/cal` targets (`/cal/lk`, `/cal/rk`, `/cal/lhck/{pitch,glide,mod,atouch,xy}`),
   sent to the panel-output host. No `cal*` method, and no `/cal` address in
   `las-frontend`, targets a voice card. The voice-card / `vxcal.db` framing is a
   mis-attribution; the JS `cal*` methods calibrate the playing surface, which is
   user-recoverable. (The Tier-1 voice-card exposure of the scripting surface is real
   but comes from generic `OSC.sendMsg`/`connect`, not from `cal*`.) I did not edit
   those docs.

2. **`docs/arch/extension-points.md` §10** says the engine is "JUCE's engine" and
   lists "five host objects." Both are correct; §1/§3 here add the specific class
   (`juce::JavascriptEngine`) and the note that `OSC`/`OSCSender` are one class under
   two names. No contradiction, only refinement.

3. **`docs/DANGER.md`** lists `--script=<path>` as "arbitrary JS with hardware
   access," with no PIN — consistent with this report. No conflict; §7 adds that a
   USB drive does not auto-run scripts and that the realistic prerequisite is the
   SSH key file.

---

## Validation plan (READ-ONLY commands for the real instrument)

These are proposed for a human to run; I did not run them. All are read-only.

1. Confirm the flag and its help text on the live binary:
   `strings -a /usr/bin/las-frontend | grep -F -- '--script='`
   (expect the flag literal and the `Runs the JavaScript at the provided file path`
   help line).
2. Confirm the host-object method vocabulary on the live binary (offsets may shift
   if the on-device build differs; match by content):
   `strings -a /usr/bin/las-frontend | grep -E '^(calSave|calSetLow|calSetMid|calSetHigh|calSetXYUpperLeft|showOled|sendMsg|waitForReply|activateChineseFont)$'`.
3. Confirm the `/cal` OSC address strings are panel/LHC only:
   `strings -a /usr/bin/las-frontend | grep -E '^/cal(/|:)'`
   (expect `/cal/lk`, `/cal/rk`, `/cal/lhck/pitch|glide|mod|atouch`,
   `/cal/lhck/xy:cal_ul|cal_lr`, `/cal:load|save|cal_default`; expect **no** voice-card
   address).
4. Confirm the six embedded script names:
   `strings -a /usr/bin/las-frontend | grep -F '_TEST.js'`.
5. Confirm the stock launch line does not use `--script`:
   `grep -n script /etc/init.d/S43gui` (expect no match).
6. Confirm the USB scan globs `*.db`, not `*.js`:
   `strings -a /usr/bin/las-frontend | grep -F 'Looking for USB files'` and
   `strings -a /usr/bin/las-frontend | grep -F '*.db'`.
7. Confirm the SSH gate constant:
   `grep -n 23051934 /etc/init.d/S50dropbear /etc/init.d/S99final`.
8. Confirm no other binary embeds a JS engine:
   `grep -l JavascriptEngine /usr/bin/*` (expect only `las-frontend`).

Do **not** run any `las-frontend --script=…`, `--test-fixture`, or any command that
emits `/cal*` OSC — those are writes, not reads.

---

## Unexplored

* The exact wire encoding/order of `OSC.sendMsg` varargs beyond
  "int/float/string appended by JS type" — I confirmed the append loop
  (0x1daf04–0x1dafb8) but did not enumerate every type branch.
* What the VC / panel side actually does with `/cal:save` — whether it commits to
  flash, to `/var`, or to volatile state. That lives on the XMOS/VC side, outside
  `las-frontend`; `docs/arch/cal-dispatch.md` may already bear on it and should be
  cross-checked, but I did not open the VC firmware for this.
* Whether `HardwareTestPanel` (`--test-fixture`) exposes any script beyond the six
  built-ins (e.g. loading one off USB or `/var`) — I traced it running the six
  embedded resources; I did not exhaustively rule out an additional load path inside
  `HardwareTestPanel`.
* The `Panel.monitor` callback plumbing (it accepts a JS function; the six factory
  scripts only use it commented-out) — I confirmed registration and the value path
  but did not trace the callback invocation back into the JS engine.
* `Console.info`/`Console.log`: the strings exist in the Console pool but I did not
  confirm whether they are wired as methods or are dead JUCE defaults (only `debug`
  and `println` are clearly registered).
* Any `FormatUSBDrivePanel` interaction with scripts (mentioned in `docs/DANGER.md`
  as another hidden entry point) — out of scope here.
