# las-frontend — UI architecture, panel map, and the modulation-matrix path

Region report. Static analysis only. **The instrument was not contacted at any point.**
Every command below was run on local disk against
`captures/firmware-1.8.2/rootfs-1.8.2/usr/bin/las-frontend` (the decrypted 1.8.2
image) and `captures/rootfs-1.5.0/usr/bin/las-frontend`.

## Grading

Every claim carries a grade. This is not decoration; the project has shipped
inference as fact before.

- **[READ]** — read directly out of a file. The file, and a byte offset or a
  virtual address, is quoted.
- **[INFERRED]** — reasoning from evidence. The evidence is named.
- **[UNKNOWN]** — not established. Said so.

Two coordinate systems appear below.
`fileoff` is a byte offset into `usr/bin/las-frontend`.
`vma` is the ELF virtual address. For this binary **`vma = fileoff + 0x10000`**
throughout (`.text` at vma `0x19700` = fileoff `0x9700`). **[READ]**
`llvm-objdump -h` section table.

Tooling used: `strings -a -t d`, `llvm-cxxfilt`, `llvm-objdump -d
--triple=armv7-none-linux-gnueabihf`, and small Python scripts that (a) find
32-bit little-endian words equal to a given address, (b) decode `LDR Rt,[pc,#imm]`
literal-pool loads, and (c) decode `BL` displacements. No Moog binary was executed. **[READ]**

---

## 1. Headline

**An edited modulation-matrix row does not travel to `las-sc` at all. It is
compiled into a flat binary blob and sent as a single OSC message to the XMOS
voice controller at `/g/<synth>/t/e/s`, host `vc` = `203.0.113.2`, UDP port
7770.** The frontend's own help text names the protocol: with
`--enable-osc-sec` absent — which is the shipped case — *"Synth parameters are
sent over xOSC directly to the Voice Controller"*. **[READ]**

That is why the wire capture during a real edit saw nothing on 9300: 9300 is the
`las-sc` link, and the matrix does not use it.

---

## 2. The binary

| fact | value | grade / evidence |
|---|---|---|
| format | ELF 32-bit LSB, ARM EABI5, dynamically linked, **stripped** | **[READ]** `file` |
| size (1.8.2) | 145,033,524 bytes | **[READ]** `ls` |
| `.text` | vma `0x19700`, 0x00a2bbd4 = 10,664,404 bytes (7.4 %) | **[READ]** `llvm-objdump -h` |
| `.rodata` | vma `0xa452e0`, 0x07f3c122 = 133,415,202 bytes (**92.0 %**) | **[READ]** same |
| `.data` / `.bss` | 9,952 / 43,336 bytes | **[READ]** same |
| dynamic symbols | 603, almost all undefined imports | **[READ]** `llvm-nm -D` |
| toolkit | **JUCE**, X11/Xlib + FreeType imports, zero Qt | **[READ]** `XCreateWindow`, `FT_New_Face` … in `.dynsym`; 546 distinct demangled `juce::` type names in `.rodata` |
| build stamp 1.8.2 | `091525-1457`, git `9144962cb` | **[READ]** fileoff 132646288, 132646663 |
| build stamp 1.5.0 | `051622-1116`, git `f77b0d82f` | **[READ]** fileoff 132644232, 132644607 (1.5.0 binary) |
| declared tag | `"LAS_FRONTEND_GIT_TAG" : "2.1.4"` | **[READ]** `rootfs-1.8.2/etc/git-tags` |

The binary is stripped, but it is **not** opaque: the C++ RTTI `typeinfo name`
strings survive in `.rodata`, and so do a few hundred lambda-closure type names
that embed their enclosing function's full mangled signature. Prefixing each with
`_ZTS` and running `llvm-cxxfilt` yields **1,135 distinct demangled type names**
(233 `las::`, 546 `juce::`, 311 global, rest `std::`). **[READ]** This is the
source for the whole class map in §9.

**1.5.0 and 1.8.2 have identical class inventories.** Extracting the same way
from the 1.5.0 binary gives 1,177 candidate names; the set difference in both
directions is two junk strings (`BlwD`, `BuwD` vs `ow<`, `q >`) that are not real
symbols. The CLI argument sets are byte-identical. **[READ]** So everything in
this document about UI structure and transport applies unchanged to the owner's
1.5.0 instrument.

---

## 3. How the process is actually launched

`rootfs-1.8.2/etc/init.d/S43gui:21` — **[READ]**, and byte-identical in
`rootfs-1.5.0/etc/init.d/S43gui:21` **[READ]**:

```
DISPLAY=:0 las-frontend \
  --usb-path=/media/thumbdrive \
  --data-path=/var/las-frontend \
  --host-paneloutput=203.0.113.2 \
  --host-performance=vc \
  --host-oleds=203.0.113.2 \
  --affinity-mask=1 \
  --host-systemclock=vc \
  --cookie=1 \
  --affinity-panel=1 \
  --startup-coordination \
  --host-vc=vc &
```

`rootfs-1.8.2/etc/hosts` **[READ]**:

```
127.0.0.1 localhost
203.0.113.2 vc
```

`rootfs-1.8.2/etc/network/interfaces` **[READ]**: `usbint` is static
`203.0.113.1/24`; `eth0` is static `192.168.1.1`; `usbext` and `ethext` are DHCP.

So **`vc` and `203.0.113.2` are the same address** — the XMOS end of the
`usbint` CDC-Ether link. Four of the frontend's eight host settings point at it;
the other four are left at their compiled default of `127.0.0.1`.

The sound-engine side, `rootfs-1.8.2/etc/init.d/S42sc:4` **[READ]**:

```
/usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300 \
  --vxfw=/usr/share/xmosfw/app_vx_10M_v2.2.1.bin --vxdb=/var/tuning.vxtune \
  --vcfw=/usr/share/xmosfw/app_las_v2.2.2.bin --vcfv=33686271 --temp \
  --expr-syms=/usr/share/vx_ee.scm --panel-state=localhost:9500 $1
```

`las-sc` **listens on `localhost:9300`** and **sends panel state to
`localhost:9500`**. Those two numbers are exactly the frontend's `--port-response`
and `--port-panelinput` defaults (§5). **[READ]**

---

## 4. Every command-line argument

The full `Commands:` block lives at fileoff 132800396–132803778 and the matching
parse literals at 132807416–132808183. **[READ]** Reproduced verbatim (the
`(dflt …)` values are filled in from §5):

| argument | help text |
|---|---|
| `--version` | Displays detailed version information |
| `--help` | (parsed at fileoff 132807426; no help line of its own) |
| `--data-path=<path>` | Configure which path to store the data files into |
| `--cal-data-path=<path>` | Configure path to store the voice card calibration data database |
| `--startup-coordination` | Coordinate the startup with the sound engine controller |
| `--enable-feature=<f>` | Enable a particular feature |
| `--disable-feature=<f>` | Disable a particular feature |
| `--example-data` | Populate a seperate DB with example data and use it *(sic)* |
| `--disable-tests` | Force the tests to not run, even for a debug build |
| `--enable-tests` | Force the tests to run, even for a release build |
| `--cookie=<string>` | Cookie value to write out once startup is fully completed |
| `--port-response=<p>` | Sets UDP port to send OSC tree responses to (dflt **9300**) |
| `--port-panelinput=<p>` | Sets UDP port to listen to for panel data (dflt **9500**) |
| `--port-paneloutput=<p>` | Sets UDP port to send panel messages to (dflt **9100**) |
| `--port-oleds=<p>` | Sets UDP port to send OSC OLED messages to (dflt **9876**) |
| `--port-perfinput=<p>` | Sets UDP port to receive OSC performance messages from (dflt **7772**) |
| `--port-perfoutput=<p>` | Sets UDP port to send OSC performance messages to (dflt **7771**) |
| `--port-systemclock=<p>` | Sets UDP port to send system clock messages to (dflt **9501**) |
| `--port-vc=<p>` | Sets UDP port to send OSC VC messages to (dflt **7770**) |
| `--port-efx=<p>` | Sets UDP port to send FX server messages to (dflt **7775**) |
| `--host-response=<h>` | Address for OSC tree response (dflt **127.0.0.1**) |
| `--host-panelinput=<h>` | Address for OSC panel input messages (dflt **127.0.0.1**) |
| `--host-paneloutput=<h>` | Address for OSC panel output messages (dflt **127.0.0.1**) |
| `--host-oleds=<h>` | Address for OSC OLED messages (dflt **127.0.0.1**) |
| `--host-performance=<h>` | Address for OSC performance messages (dflt **127.0.0.1**) |
| `--host-systemclock=<h>` | Address for system clock messages (dflt **127.0.0.1**) |
| `--host-efx=<h>` | Address for FX server messages (dflt **127.0.0.1**) |
| `--host-vc=<h>` | Address for OSC VC messages (dflt **127.0.0.1**) |
| `--usb-path=<path>` | Path for USB drive |
| `--firmware-path=<path>` | Path for firmware updates (overrides USB path) |
| `--firmware-dry-run` | Performs the firmware update in dry-run mode |
| `--midi-in=<name>` | Name of MIDI input device |
| `--midi-out=<name>` | Name of MIDI output device |
| `--affinity-mask=<m>` | Sets an affinity mask for the frontend threads |
| `--affinity-panel=<m>` | Sets an affinity mask for the panel messages threads |
| `--enable-osc-sec` | Send all sound engine messages through the old osc protocol |
| `--assume-auto-polling` | Assume that auto polling is active by default |
| `--log-perf-input` | Enable logging of received performance OSC messages |
| `--log-perf-output` | Enable logging of sent performance OSC messages |
| `--log-panel-osc` | Enable logging of received panel OSC messages |
| `--log-tree-osc` | Enable logging of sent OSC tree message |
| `--log-thread-heartbeat` | Enable logging of thread activity |
| `--log-xmos-dsptime` | Enable logging of DSP time spent on the XMOS voice cards |
| `--print-nrpns` | Print the NRPN numbers that are supported |
| `--script=<path>` | Runs the JavaScript at the provided file path |
| `--upside-down-ui` | Renders the entire UI upside down |
| `--touch-to-vco` | Generate VCO pitch offset messages for touch panel |
| `--always-on-top` | Keep application always at the front of other windows |
| `--test-fixture` | Boot into HardwareTestPanel for use at CM |

Unrecognised arguments produce `Unsupported argument: ` (fileoff 132808184) and
are not fatal. **[READ]**

### 4.1 `--host-vc` / `--port-vc`

Selects the destination of `las::VoiceControlSender`, the object that carries
**all synth-parameter traffic and the modulation matrix**. Shipped value:
`vc:7770` = `203.0.113.2:7770`. **[READ]**

The sender is a thin wrapper around `juce::OSCSender`. Its `connect(host,port)`
is at vma `0x1bf918`: it `new`s a 48-byte object, starts a thread named
`"Voice Control"`, calls `juce::OSCSender::connect` (vma `0xa42430`) and logs
either `VoiceControlSender connected to <host>:<port>` (rodata vma `0x07e599d0`,
fileoff 132422096) or `Couldn't connect to …`. **[READ]**

### 4.2 `--host-paneloutput`

Destination of `las::PanelOutputSender` — LEDs, panel-scan configuration, and the
front-panel calibration commands. Shipped `203.0.113.2:9100`. Its address
vocabulary (rodata fileoff 132419679–132420019, i.e. that translation unit's
string pool) is **[READ]**:

```
/cal/lk  /cal/rk  /cal/lhck/pitch  /cal/lhck/glide  /cal/lhck/mod  /cal/lhck/atouch
/cal:load  /cal:save  /cal:cal_default  /cal/lhck/xy:cal_ul  /cal/lhck/xy:cal_lr
/lfoleds  /seqleds  /clkleds  /lsleds  /auto  /r/midi  /m/xyz/hold  /m/xyz/pol  /m/at
```
plus the log strings `PanelOutputSender connected to `, `LED Flash`, `Send LEDs`,
and `Couldn't configure polling for <x> since the panel sender is not connected.`

### 4.3 `--host-oleds`

Destination of `las::OLEDSender`. Shipped `203.0.113.2:9876`. Vocabulary
(fileoff 132417096–132417200): `/od/0/fill`, `/od/s`, `/od/`, `/l8m`, log
`OLEDSender connected to `. **[READ]** So the OLED strips under the encoders are
driven by the i.MX6 pushing pixel/fill messages to the XMOS, not by a local
framebuffer.

### 4.4 `--affinity-mask` and `--affinity-panel`

`--affinity-mask=<m>` is parsed at vma `0x8cd7dc`; the value is taken through
`juce::String::getIntValue` (vma `0x8fc7a0`) and passed **immediately** to the
function at vma `0x904f0c`. **[READ]** That function builds a 128-byte
`cpu_set_t` by testing bits 0..31 of the argument, then calls `pthread_self()`,
`pthread_setaffinity_np(self, 128, &set)` and `sched_yield()` (vma
`0x904f10`–`0x904f60`). **[READ]** It is the only call site of
`pthread_setaffinity_np` reachable this way.

Consequences:

- `--affinity-mask=1` sets bit 0 → **CPU 0 only**. **[READ]**
- It is applied to the *calling* thread during argument parsing, i.e. the main
  thread, before the application's own threads exist. Linux threads inherit the
  creator's affinity, so the entire frontend — GUI, senders, receivers — lands on
  CPU 0. **[INFERRED]** from the placement of the call inside the argument loop
  and from POSIX inheritance semantics; not observed at runtime.
- `--affinity-panel=<m>` is parsed 84 bytes later (vma `0x8cd830`) and its value
  is **stored**, not applied, then handed to a different consumer; the second
  application site is the JUCE thread-startup wrapper at vma `0x919b08`.
  **[INFERRED]**
- With `isolcpus=1` reserving CPU 1 for `scsynth`, `--affinity-mask=1` is the
  matching half of that arrangement. **[INFERRED]**

`S99final` separately raises the IPU (display) kernel threads above the frontend:
`chrt -f -p 93 <ipu tasks>` and `chrt -f -p 80 <ipu irq>`, and pokes the AXI bus
priority register with `devmem 0x020e0018 w 0xffffffff`. **[READ]**
`rootfs-1.8.2/etc/init.d/S99final:9-17`. This confirms as **[READ]** what
`CORRECTIONS-2026-09-08.md §8` listed as **[AGENT]** ("display threads run
SCHED_FIFO 93/80").

### 4.5 `--startup-coordination` and `--cookie`

With the flag, the frontend logs `Beginning startup coordination` (fileoff
132807246) and blocks; without it, `No startup coordination, starting
immediately` (132807277). **[READ]** Coordination runs over `las::SystemClock`,
which logs `SystemClock created socket to coordinate with ` (fileoff 132421808)
and uses the token `LTRS` (fileoff 132421855). **[READ]** Destination
`--host-systemclock=vc`, `--port-systemclock` default **9501**.

`--cookie=1` makes the frontend write `/var/las-frontend/las-frontend.cookie`
(`Writing startup cookie`, fileoff 132800219; filename literal 132800199) once
startup completes; `S43gui:26-41` polls for that file with a 100-second timeout
before starting `las-dwm`. **[READ]**

### 4.6 `--enable-osc-sec` — the protocol switch

Parsed at vma `0x8cd9a8`; on match it executes `mov r3,#1 ; strb r3,[r4,#0x9c]`
(vma `0x8cd9b4`–`0x8cd9b8`). **[READ]** The byte at config offset `0x9c` is read
back at vma `0x8cef70` (`ldrb r3,[r4,#0x9c]`), and the branch at `0x8cef80`
selects the log line: **[READ]**

- byte ≠ 0 → rodata `0x07eb7f83` = *"Synth parameters are sent over OSC through
  the Sound Engine Controller"*
- byte = 0 (**the shipped default**) → rodata `0x07eb7fca` = *"Synth parameters
  are sent over xOSC directly to the Voice Controller"*

The same byte is the live branch at vma `0x8c726c`. See §7.

---

## 5. The transport map

Compiled defaults are literal immediates in the configuration constructor at vma
`0x8cbf28`–`0x8cbf6c`, stored at fixed offsets in the config object; the eight
host strings at offsets `+0x74`…`+0x90` are each initialised from one shared
static `juce::String` at vma `0x08a7a460`, itself constructed at vma `0x8bb3f4`
from the literal **`"127.0.0.1"`** (rodata vma `0x07e510b8`). **[READ]**

| channel | frontend role | default | shipped override | actual endpoint |
|---|---|---|---|---|
| OSC tree ("response") | **send** | 127.0.0.1:9300 | — | **`las-sc`** (`-l localhost:9300`) |
| panel input | **listen** | :9500 | — | from XMOS panel scan **and** `las-sc --panel-state=localhost:9500` |
| panel output | **send** | 127.0.0.1:9100 | `--host-paneloutput=203.0.113.2` | **XMOS** 203.0.113.2:9100 |
| OLEDs | **send** | 127.0.0.1:9876 | `--host-oleds=203.0.113.2` | **XMOS** 203.0.113.2:9876 |
| performance in | **listen** | :7772 | — | notes / keyboard / NRPN from XMOS |
| performance out | **send** | 127.0.0.1:7771 | `--host-performance=vc` | **XMOS** 203.0.113.2:7771 |
| system clock | **send** | 127.0.0.1:9501 | `--host-systemclock=vc` | **XMOS** 203.0.113.2:9501 |
| **voice control (xOSC)** | **send** | 127.0.0.1:7770 | `--host-vc=vc` | **XMOS** 203.0.113.2:7770 |
| FX server | **send** | 127.0.0.1:7775 | — | `las-sc -f localhost:7775` |

All grades **[READ]** except the "actual endpoint" column for panel input, which
is **[INFERRED]** (the frontend binds the port; two senders are documented to
target it, one in `S42sc`, one implied by the panel-scan traffic already observed
on the XMOS link).

**Caveat on panel input.** `las::PanelInputReceiver` owns *both* a
`juce::OSCReceiver` and a `juce::OSCSender` — its four diagnostics are
`PanelInputReceiver couldn't bind to port `, `PanelInputReceiver couldn't connect
OSC receiver to `, `PanelInputReceiver OSC sender couldn't connect to `, and
`PanelInputReceiver connected to ` (fileoff 132418640-132418777). **[READ]**
So `--host-panelinput` is the target of that outbound sender (the channel that
carries `/listen`, `/state/send` and the `/override*` commands), not merely a
bind address. Where its packets actually land when the default `127.0.0.1` is
left in place is **[UNKNOWN]** and is worth one line of `tcpdump -i lo` to
settle.

Struct layout of the port block, for anyone patching: `+0x50` response 9300,
`+0x54` panelinput 9500, `+0x58` paneloutput 9100, `+0x5c` oleds 9876, `+0x60`
perfinput 7772, `+0x64` perfoutput 7771, `+0x68` **vc 7770**, `+0x6c` efx 7775,
`+0x70` systemclock 9501. **[READ]** vma `0x8cbf28`–`0x8cbf6c`.

---

## 6. THE PRIORITY QUESTION — where an edited matrix row goes

### 6.1 The edit itself mutates the in-memory preset

`ModMatrixPanel`, `ModMatrixRow` and `ModMatrixSoftKnob` exist as RTTI names at
fileoff 132587120, 132782076, 132782388. **[READ]** The lambda-closure type names
in the same translation units preserve their enclosing method signatures
**[READ]**:

```
ModMatrixPanel::setVisible(bool)                    [5 closures]
ModMatrixPanel::toggleMute()                        -> Ptr<las::Preset>
ModMatrixPanel::createNewEntry()                    -> Ptr<las::Preset>
ModMatrixPanel::calculateDelta(int, int&, int&)     -> Ptr<las::Preset>
ModMatrixPanel::applyBrowsingOffsetAndRow(int,int)  -> Ptr<las::Preset>
ModMatrixPanel::updatePageTabs()                    -> Ptr<las::Preset>
ModMatrixPanel::deleteFocusedEntry()                -> Ptr<las::Preset>
ModMatrixPanel::browseToLastEntry()                 -> Ptr<las::Preset>
ModMatrixPanel::saveConfirmed()                     -> Ptr<las::Preset>
ModMatrixRow::setIndex(int, bool)                   -> Ptr<las::Preset>
ModMatrixRow::softKnobSelectionChanged(ModMatrixSoftKnob*) -> Ptr<las::Preset>
ModMatrixRow::applyState()
```

Every mutating method closes over a `juce::ReferenceCountedObjectPtr<las::Preset>`.
**The matrix editor writes into the shared `las::Preset` object and nothing
else.** **[READ]** (The panel's own UI strings are at fileoff 132587192–132587302:
`CONTROLLER`, `TRANSFORM`, `CLEAR SRC FILTER`, `CLEAR DEST FILTER`, `DISABLE`,
`ENABLE`, `/p/modmatrix`, `SAVE NEW MOD MATRIX PRESET`.)

### 6.2 The preset field is a flat array of 7-tuples

`las::Preset`'s field-name table (fileoff 132395669, 132395693) contains
`matrix_expression_slots` and `seq_expression_slots`. **[READ]** 580 complete
preset bodies are embedded in `.rodata`; a typical one reads **[READ]**
(fileoff 14009649):

```
/p/part/t/1/p/modmatrix/matrix_expression_slots [48, 1.0, 6, 0.009999999776482582, 43, 0.0, 52]
```

The 7-tuple is `[src, src_a, ctl, ctl_a, tr, tr_a, dst]` — the tuple order given
by `las::ModMatrix`'s own suffix table at fileoff 132392648–132392687:
`/src  /src_a  /ctl  /ctl_a  /tr_a  /dst`. **[READ]** (`/tr` is pooled elsewhere.)

### 6.3 `las::ExpressionSlotsUpdater` — six of them, one per (synth × kind)

Type name at fileoff 132796688. **[READ]** Its vtable is at vma `0x07eb5cd0`;
the single overriding virtual is at **vma `0x008bf910`**. **[READ]**

The constructor is at vma `0x008bded4`. It builds the object's OSC address into
a `juce::String` at `this+104` as **[READ]**:

```
address = "/g/" + <int arg>  +  "/t/"  +  <String arg>
```
(`"/g/"` = rodata `0x07e7c585`, a tail of the pooled string `"/r/g/"`;
`"/t/"` = rodata `0x07e53675`, a tail of `"/p/part/t/"`. Verified by reading the
raw bytes around each address.)

Six instances are constructed and registered in
`LASFrontEndApplication::Pimpl::initialise`, vma `0x8cefc0`–`0x8cf124`. **[READ]**

| registration key | ctor args | **resulting OSC address** |
|---|---|---|
| 946 (`0x3b2`) | `(0, "e/s")` | **`/g/0/t/e/s`** |
| 947 (`0x3b3`) | `(1, "e/s")` | **`/g/1/t/e/s`** |
| 948 | `(2, "e/s")` | **`/g/2/t/e/s`** |
| 949 (`0x3b5`) | `(0, "e/q")` | **`/g/0/t/e/q`** |
| 950 (`0x3b6`) | `(1, "e/q")` | **`/g/1/t/e/q`** |
| 951 (`0x3b7`) | `(2, "e/q")` | **`/g/2/t/e/q`** |

`"e/s"` and `"e/q"` are standalone NUL-terminated literals at rodata vma
`0x07eb800f` and `0x07eb8013` — checked by reading the surrounding bytes, they
are not suffixes of anything longer. **[READ]**
Mapping `e/s` → `matrix_expression_slots` and `e/q` → `seq_expression_slots` is
**[INFERRED]** — from the 3+3 split matching the two preset fields, and from the
fact that `s`/`q` are the only two expression-slot arrays that exist.

The key `946+n` / `949+n` values are the keys the updater is filed under in the
frontend's updater map (registrar at vma `0x8c99a4`: it calls the updater's
virtual slot 8 with the key, then hash-inserts it). **[READ]** Whether that index
space is the same as the "NRPN number" space printed by `--print-nrpns` is
**[UNKNOWN]** — `--print-nrpns` formats a number `n` plus `n+3840` and `n+7680`
as MSB/LSB pairs (vma `0x8be064`), and it prints 950 next to `Svf Cutoff`, which
would collide. Do not assume the two are the same enum.

### 6.4 The wire format — a raw binary blob, not OSC arguments

`ExpressionSlotsUpdater`'s override, vma `0x008bf910`–`0x008bfab8`, does exactly
this **[READ]**:

1. Construct an empty `juce::MemoryBlock` on the stack.
2. If the incoming `juce::var` is an array (`var::isArray`, vtable slot `0x4C`)
   and not void, walk it (`var::toArray`, slot `0x20`; element stride 16 bytes =
   `sizeof(juce::var)`).
3. For each element:
   - `var::isInt()` (slot `0x34`) → take `var::toInt()` (slot `0x08`), store it
     with **`strb`** and append **1 byte**;
   - else `var::isDouble()` (slot `0x40`) → take `var::toDouble()` (slot `0x10`),
     `vcvt.f32.f64` to single precision, `vstr s0` and append **4 bytes**;
   - else append nothing.
   (`MemoryBlock::append` is vma `0x908c74` — `ensureSize` then `memcpy`.)
4. Fetch the application singleton (vma `0x9c1698`), take `[+0x18]` (the Pimpl)
   and add **1200** — this is the `las::VoiceControlSender`.
5. Build a `juce::OSCMessage` whose address is `this+104` (the `/g/n/t/e/s`
   string), wrap the MemoryBlock as a single **OSC blob argument**, and call
   `VoiceControlSender::send` at **vma `0x1bf530`**, which is
   `ldr r0,[r0,#4] ; add r0,r0,#8 ; b juce::OSCSender::send`. **[READ]**

**Therefore one modulation slot occupies exactly 16 bytes on the wire:**

```
offset 0  : u8    src      (source id)
offset 1  : f32le src_a    (source amount)
offset 5  : u8    ctl      (controller id)
offset 6  : f32le ctl_a    (controller amount)
offset 10 : u8    tr       (transform id)
offset 11 : f32le tr_a     (transform amount)
offset 15 : u8    dst      (destination id)
```

with **no padding and no alignment**, N slots = 16 N bytes, sent as one OSC blob.
The 16-byte figure is **[INFERRED]** from the per-element rule (**[READ]**) plus
the observed 7-tuple element types in the preset corpus (**[READ]**); it has not
been checked against a live packet.

Two consequences worth stating plainly:

- **Source, controller, transform and destination ids are 8-bit.** The corpus
  contains destination ids up to 137 (fileoff 15107570). There is no room above
  255. This is a hard ceiling on the modulation namespace. **[INFERRED]**
- The encoding is **positional only by convention**. The updater does not know
  the tuple shape; it emits 1 byte for anything integral and 4 for anything
  floating. If a writer ever emits `1` where `1.0` is expected, the entire
  remaining blob shifts by three bytes and every subsequent slot is garbage.
  Anyone writing `matrix_expression_slots` from outside must keep the `_a`
  fields as JSON reals. **[INFERRED]**, but directly from the **[READ]** code.

### 6.5 Why the capture saw nothing

- Port **9300** carries the `/p/...` OSC tree to `las-sc`. The matrix slots do
  not go there. **[READ]** for the port role; **[INFERRED]** for the negative,
  since the only code that emits the slots is the updater above.
- On the XMOS link the traffic *is* present, but at **203.0.113.2:7770**, and it
  is an OSC message whose only argument is an opaque blob. A dissector that
  classifies by shape — "panel scan / clock / thermal / OLED" — has nothing to
  key on: `/g/0/t/e/s` is a three-level address that looks like nothing else, and
  the payload is 16 N bytes of packed bytes and floats. **[INFERRED]**
- The `las-sc` side has zero modmatrix code, which is consistent: the matrix is
  not its business. **(Existing project finding, restated, not re-verified here.)**

Note the `/p` tree *does* contain modmatrix addresses — `p-namespace-keys.txt`
lines 1322–1341 list `/p/part/t/1/p/modmatrix/{name,comment,matrix_expression_slots,
seq_expression_slots,entry/N/{src,src_a,ctl,ctl_a,tr,tr_a,dst,mute}}`. **[READ]**
Whether the frontend *transmits* those addresses to `las-sc` on an edit is
**[UNKNOWN]**; the capture showing nothing on 9300 during a live edit is
consistent with the individual `entry/N/*` parameters having no tree-emitting
updater at all.

### 6.6 The `mute` field has no wire representation

The preset carries `entry/N/mute` **[READ]** (namespace dump line 1329), and
`ModMatrixPanel::toggleMute()` exists **[READ]**, but the 7-tuple has no mute
slot. **[INFERRED]** conclusion: muting a row is implemented by *omitting* the
slot when the flat array is recompiled, not by a flag on the wire. Not verified.

---

## 7. The general parameter path — `/x`

This is the same mechanism, generalised, and it is where **all** ordinary synth
parameters go.

Function at **vma `0x008c7250`**, `(appPimpl, object)`. **[READ]**

```
  8c726c: ldrb r3,[r5,#0x9c]        ; the --enable-osc-sec byte
  8c7274: cmp  r3,#0
  8c7280: bne  0x8c7298             ; legacy: block = nullptr
  8c7284: mov  r0,#8
  8c7288: bl   operator new         ; default: allocate a las::SoundEngineBlock
  8c7290: bl   0xfb26c              ;   SoundEngineBlock::SoundEngineBlock()
  ...
  8c729c: ldr  r3,[r6] ; ldr r3,[r3,#0x30] ; blx r3
                                    ; object->virtual(&treeMessageList, block)
  8c72b4: ldr  r3,[sp,#0xc] ; cmp 0 ; bne -> append list to appPimpl+1164
  8c72dc: mov  r0,r4 ; bl 0xfb1cc   ; SoundEngineBlock::isEmpty()
  8c72e4: cmp  r0,#0 ; bne skip
  8c72ec: mov  r0,sp ; ldr r1,=0x07e7a4e1   ; the literal "/x"
  8c72f4: add  r5,r5,#1200          ; the VoiceControlSender
  8c7308: bl   0x1bf53c             ; VoiceControlSender::send(addressString, block)
```

So each parameter-bearing object produces **two** outputs from one virtual call:

- a list of `/p/...` OSC tree messages, queued at `appPimpl+1164` and delivered to
  `--host-response` = **`las-sc` on 127.0.0.1:9300**; and
- unless `--enable-osc-sec`, a `las::SoundEngineBlock` sent as OSC address
  **`/x`** to the **VoiceControlSender** at `vc:7770`.

`"/x"` is rodata vma `0x07e7a4e1` — verified by reading the raw bytes: it is the
two-character tail of the pooled string `"/cal/cv/0/x"`. **[READ]**

`VoiceControlSender::send(String&, SoundEngineBlock*)` at vma `0x1bf53c` tail-calls
the loop at **vma `0x000fb2f8`**, which walks the block's array of sub-buffers and,
for each non-empty one, builds `OSCMessage(address)`, wraps the buffer as a
**blob** argument, and calls `juce::OSCSender::send` (vma `0xa44104`). **[READ]**
`las::SoundEngineBlock`'s own diagnostics are `Data exceeds maximum size (`
(fileoff 132386968) and its unit-test names `Append single / Append multiple /
Append exceed max / Append exceed max not aligned` (132387010–132387094). **[READ]**

The two callers of `0x8c7250` are at vma `0x8c73b8` and `0x8c7518`, both inside
functions that first take a `juce::CriticalSection` and then dereference a
reference-counted pointer — the "apply whole preset" and "apply whole
master/settings" paths (`applyPresetData` / `applyMasterData` appear as lambda
signatures at fileoff 132798404 and 132798712). **[READ]**

**Summary of the control plane, corrected:** `las-frontend` is not a client of
`las-sc` for synthesis. It is a *peer* that owns the state, pushes the audio-side
subset (`/p/...`) to `las-sc` over 9300, and pushes the voice-side state to the
XMOS over 7770 in a compact binary form. `las-sc` never sees the modulation
matrix. **[INFERRED]** from the above, all of which is **[READ]**.

---

## 8. Everything else that goes to the voice controller

Thirty-two direct call sites of `VoiceControlSender::send` (vma `0x1bf530`) exist
in `.text`. **[READ]** Resolving the OSC-address literal nearest each one gives
the complete non-bulk VC vocabulary **[READ]** (address attribution per site is
**[INFERRED]** — it is the nearest preceding literal load, which is how the
compiler lays these out, but it was not proven register-by-register for all 32):

| address | context (nearest strings) | call sites |
|---|---|---|
| `/therm/t` | `lowVxTemp`, `VxTemp` | 0x3c5a58, 0x6d2960 |
| `/therm/min-som` | `SomTemp`, `overideMinSom`, `lowMinSom`, `MinSom` | 0x3c56ec, 0x3c5790, 0x3c5b34, 0x6d28d8 |
| `/therm/min-vx` | `overideMinVx`, `lowMinVx`, `MinVx` | 0x3d2874, 0x3d2918, 0x3c5bf4, 0x6d291c |
| `/therm/fan-normal-max` | `FanMax`, `overideFanMax`, `lowFanMax` | 0x3c5730, 0x3c57d4, 0x3c5cb0, 0x3d28b8, 0x3d295c, 0x6d2894 |
| `/ccmap` | MIDI CC map upload | 0x510e5c |
| `/g/<n>/en` | `"/g/"` + `"/en"` — synth enable | 0x5f41ac |
| `/cc-filter-enable` | | 0x620f4c |
| `/cvi` | CV inputs | 0x6d2d20 |
| `/cvo` | CV outputs | 0x6d2fbc |
| `/r/sys/local/en` | local control | 0x896748, 0x8cb2e4 |
| `/m/xyz/pol` | LHC XY polarity | 0x8b147c |
| `/patch/end` | preset-load transaction end | 0x8c5ecc |
| `/patch/begin` | preset-load transaction begin | 0x8ca600 |
| `/v/<n>/o<n>/hw/enable_pid` | per-oscillator PID | 0x8c65b8 |
| `/v/dis` | voice disable | 0x8c6894 |
| `/hw/mute` | | 0x8cb380 |
| `/a/in1`, `/a/in2` | analogue inputs | 0x8cb3c0, 0x8cb400 |
| `/g/<n>/t/e/s`, `/g/<n>/t/e/q` | **modulation matrix** | 0x8bfa08 |

`/patch/begin` … `/patch/end` bracketing a preset load is a real transaction
marker on the VC link and is the single most useful thing to trigger on when
capturing. **[READ]** for the literals and the call sites; **[INFERRED]** for
the bracketing semantics.

`las::VoiceControlSender`'s own translation unit also holds the literals
`/hw/cvo0`, `/hw/cvo1`, `/hw/cvo2`, `/hw/cvo3`, `/info/serial`,
`/stat/dsptime/ls` (fileoff 132422129–132422195), and the thread name
`Voice Control` (132422195). **[READ]**

A wider VC-side namespace appears in the statically linked calibration library at
the head of `.rodata` (fileoff 10703072 onward), driven by `las::OSCQuery` and a
family of `las::*CalOperation` / `*GetterOperation` classes: `/vx/`, `/stat`,
`/statr`, `/gate`, `/hw/ph`, `/hw/ph0`, `/hw/ph1`, `/o1/oct`…`/o3/oct`,
`/o1/hw/enable_pid_cal`…, `/therm/vx-temp-avg`, `/a/stat/mainl`, `/a/stat/mainr`,
`/a/stat/send1`, `/a/stat/send2`, `/stat/mix`, `/testosc/dac/`, `/fa/par`,
`/fafb`, `/cal/gsvf/x`, `/cal/svf1r/x`. **[READ]**

---

## 9. MIDI: the frontend *originates* outbound MIDI, over the performance link

This bears directly on the project's MIDI story.

`las::MidiControlOutputUpdater` (type name fileoff 132796732) and the routine at
**vma `0x008bf7b8`** do the following **[READ]**:

1. Build `OSCMessage("/mo/din0")` — the literal is rodata `0x07eb5f01`, fileoff
   132800257.
2. Walk a `juce::MidiMessage` (size at `[msg+0x10]`, data inline if ≤ 4 bytes else
   via `[msg]` — the exact JUCE layout) and append **each MIDI byte as a separate
   OSC int32** (`OSCMessage::addInt32`, vma `0xa4252c`).
3. Read a route setting from `this+1224` and branch on values 0 / 1 / 2; for one
   branch it re-addresses the message to **`/mo/usb0`** (rodata `0x07eb5f0a`,
   fileoff 132800266).
4. Send via the object at **`appPimpl+1192`**, function vma `0x1be570` — which is
   in the same translation unit as the literal `PerformanceSender connected to `
   (fileoff 132421432, referenced from vma `0x1be63c`). **[READ]**

So: **outbound MIDI is synthesised by `las-frontend` on the i.MX6, encoded as an
OSC message with one int32 per MIDI byte, addressed `/mo/din0` or `/mo/usb0`, and
handed to the XMOS on the performance channel (`vc:7771`), which serialises it to
the physical DIN or USB port.** **[READ]** for every step; the "XMOS serialises
it" clause is **[INFERRED]**.

The mirror image is `las::PerformanceReceiver`, bound to `--port-perfinput`
(7772), whose closures include
`PerformanceReceiver::Pimpl::handleNrpnQueue()` and
`PerformanceReceiver::Pimpl::updateKnobForParameter(int, float,
las::SoundEngineIndex, las::UpdaterIndex)` (fileoff 132420304–132420652).
**[READ]** Inbound MIDI therefore reaches Linux **already parsed into OSC
performance messages** — notes, keyboard events, NRPN — never as raw bytes. Its
test vectors are literal note/keyboard triples such as `64:1:1`, `120:0.5:3`,
`127:-1:2` (fileoff 132421192–132421324). **[READ]**

`--midi-in` / `--midi-out` open a real `juce::MidiInput`/`MidiOutput` by name
(`Couldn't find MIDI input port "`, `MIDI input connected to "`, fileoff
132800275/132800307). **[READ]** Neither flag is passed in `S43gui`, so **on the
instrument no ALSA MIDI device is ever opened by the frontend**. **[READ]** This
corroborates, from the frontend side, the established finding that no MIDI byte
from either physical port reaches Linux.

`las::FeatureFlags` (fileoff 132390136) has exactly three flag names, the
operands of `--enable-feature` / `--disable-feature`: **`nrpnInput`,
`nrpnOutput`, `midiLearn`** (fileoff 132390176–132390206). **[READ]**

---

## 10. UI architecture — the class map

All names below are **[READ]** from RTTI `typeinfo name` strings; the fileoff
given is where the name string lives, which also fixes the translation-unit order
in `.rodata`.

### 10.1 Application spine

| class | fileoff | role |
|---|---|---|
| `las::LASFrontEndApplication` | 132800084 | `juce::JUCEApplication` subclass |
| `las::LASFrontEndApplication::Pimpl` | 132796840 | the whole application state; holds the senders at `+1164` (tree queue), `+1192` (PerformanceSender), `+1200` (VoiceControlSender) |
| `las::MainWindow` | 132795764 | top-level window |
| `las::MainComponent` | 132794204 | root component and **panel registry** |
| `las::LASLookAndFeel` | 132792444 | JUCE LookAndFeel |
| `LowLevelGraphicsSVGRenderer` | 132792636 | an SVG-emitting `juce::LowLevelGraphicsContext` — used by `las::MakeScreenshot` (132795956) |
| `las::UIBookKeepingThread` | 132796648 | thread, name `UI BookKeeping` (132807341) |
| `las::OledAnimation` | 132795852 | |
| `las::GlobalMouseWheelListener` | 132795348 | |
| `las::LASLogger` | 132808748 | writes `las-frontend.log` (132808784) |

The `Pimpl::initialise` closures recovered from lambda type names give the app's
own method list **[READ]**: `initialise(const juce::String&)`,
`systemUpAndRunning()`, `updateNormalized(UpdaterIndex, uint16)`,
`updateValue(UpdaterIndex, juce::var)`, `paramValue(UpdaterIndex)`,
`paramNormalized(UpdaterIndex)`, `paramOrdinal(UpdaterIndex)`,
`applyMasterData(Ptr<Master>)`, `applySettingsData(Ptr<Settings>)`,
`applyPresetData(Ptr<Preset>, NotificationType)`,
`recallActivePresetFromSettings()`, `timerCallback(int)`,
`setCompareActive(bool)`, `setShiftActive(bool)`, `setSoloActive(bool)`,
`setScreenSaverActive(bool)`, `writeStartupCookie()`.

Also in that TU: `Forcibly shutting down application because it has been running
for too long in CI` (132806848) — a CI guard that ships in the release binary.
**[READ]**

### 10.2 Rendering

`Xorg` + `Xvfb` are present in the rootfs and the frontend imports ~90 Xlib
symbols. **[READ]** `Available Rendering Engines:` (fileoff 132795800) is the
JUCE renderer enumeration. The window manager is `las-dwm`, started only after
the frontend's cookie appears. `S43gui:72` runs `xrandr -o inverted`, which is
the counterpart of `--upside-down-ui`. **[READ]**

### 10.3 Panels — the full list (66)

Grouped by function. All **[READ]**.

**Performance / preset**
`PresetLandingPanel` · `BrowsePresetsPanel` · `BrowseSnapshotsPanel` ·
`BrowseSynthsPanel` · `SavePresetPanel` · `SaveItemPresetPanel` · `SaveTagPanel` ·
`SaveUserSpacePanel` · `EditNotesPanel` · `PerformanceSetPanel` ·
`PerformanceSetBrowsePanel` · `PerformanceSetOverviewPanel` ·
`PerformanceSetArrangePanel` · `SlotMachinePanel`

**Synth engine editing**
`OscillatorPanel` · `OscillatorModulationPanel` · `OscillatorTuningPanel` ·
`NoisePanel` · `MixerPanel` · `FilterPanel` · `EnvelopePanel` · `LFOPanel` ·
`VCAPanel` · `PolyphonyPanel` · `MasterPanel` · `MasterClockPanel` ·
`MasterTuningPanel` · `ArpeggiatorPanel` · `SequencerPanel` ·
`SequencerNotesPanel` · `SequencerModsPanel` · `LHCPanel` (left-hand controller)

**Modulation**
`ModMatrixPanel` · `LoadModMatrixPanel` · `QuickAssignPanel`

**Effects**
`SynthEffectTypePanel` · `SynthEffectParamsPanel` · `MasterEffectTypePanel` ·
`MasterEffectParamsPanel`

**MIDI**
`MidiMappingPanel` · `LoadMidiMapPanel` · `QuickMidiLearnPanel`

**Settings**
`SettingsGlobalPanel` · `SettingsLibraryPanel` · `SettingsTuningPanel` ·
`SettingsTuningEditorPanel` · `SettingsRenameTuningPanel` ·
`SettingsCopyTuningPanel` · `SettingsRenameDuplicatesPanel` ·
`SettingsExportPanel` · `DateAndTimePanel`

**Calibration / service** (the largest single group)
`SystemCalibrationPanel` · `VoiceCardCalibrationPanel` · `VoiceCardCalSelectPanel` ·
`VoiceCardCalProgressPanel` · `VoiceCardCalResultPanel` · `CVInCalibrationPanel` ·
`CVOutCalibrationPanel` · `PedalInCalibrationPanel` · `MainOutCalibrationPanel` ·
`HeadphoneOutCalibrationPanel` · `NoiseSourceCalibrationPanel` ·
`FrontPanelLowCalibrationPanel` · `FrontPanelMidCalibrationPanel` ·
`FrontPanelHighCalibrationPanel` · `LHCCalibrationPanel` · `FanCalibrationPanel` ·
`HardwareTestPanel` · `TestResultPanel` · `SerialMacWritePanel` ·
`DisplayCoreTempPanel` · `OscillatorMonitorPanel` · `OscillatorStabilityPanel` ·
`VoiceEnableDisablePanel`

**System / chrome**
`StartupPanel` · `CanvasPanel` · `ConfirmationPanel` · `WarningPanel` ·
`WarningConfirmPanel` · `WarningNotifyPanel` · `LoadSequencePanel` ·
`FormatUSBDrivePanel` · `UpdateFirmwarePanel`

Fourteen of these ship with a paired `*PanelTests` class compiled in
(`ArpeggiatorPanelTests`, `BrowsePresetsPanelTests`, `EnvelopePanelTests`,
`FilterPanelTests`, `LFOPanelTests`, `LHCPanelTests`, `LoadMidiMapPanelTests`,
`LoadModMatrixPanelTests`, `LoadSequencePanelTests`, `MasterClockPanelTests`,
`MasterEffectParamsPanelTests`, `MasterPanelTests`, `MixerPanelTests`,
`OscillatorPanelTests`, `OscillatorTuningPanelTests`,
`PerformanceSetArrangePanelTests`, `PerformanceSetBrowsePanelTests`,
`PerformanceSetCurrentPanelTests`, `PolyphonyPanelTests`, `PresetLandingPanelTests`,
`SequencerPanelTests`, `SettingsPanelTests`, `SynthEffectParamsPanelTests`,
`VcaPanelTests`). **[READ]**

### 10.4 Central areas, headers and tabs (the navigation chrome)

`BrowseCentralArea` · `DualBrowseCentralArea` · `ExportCentralArea` ·
`MoreCentralArea` · `PageHeader` · `PageTabs` · `Scroller` ·
`ObscuringRectangle` · `VerticalGradientTop` · `VerticalGradientBottom` ·
`CharacterKeyboard` · `PresetFilterKnobs` · `PerformanceSetBankButton` ·
`SquareToggleBox` · `TextToggleBox` · `EmptyRowItem` · `ArrowRight` ·
`MidiPlugIcon` · `EventideLogo` **[READ]**

### 10.5 Graphs (custom-drawn visualisations, 20 + 33 effect graphs)

`GraphComponent` is the base. **[READ]**
`ArpeggiatorNotesGraph` · `EffectsGraph` · `EnvelopeGraph` · `FanCalibrationGraph` ·
`FilterGraph` · `LFOGraph` · `LFOPolarityIndicator` · `LHCGraph` ·
`MasterClockGraph` · `MasterOutputGraph` · `MasterTuningGraph` · `MixerGraph` ·
`OscillatorGraph` · `OscillatorBottomArea` · `OscillatorTuningGraph` ·
`OscMonitoringGraph` · `OscMonitoringSingleBarGraph` · `OscStabilityGraph` ·
`PianoKeyRanges` · `PolyphonyGraph` · `ProgressBarGraph` · `QuickAssignGraph` ·
`QuickMidiLearnGraph` · `SequenceNotesGraph` · `SynthNoteRange` · `TuningNote` ·
`VcaGraph` · `VoiceActivity` · `VoiceEnableDisableGraph`

Per-effect graphs — one class per algorithm, which is a complete list of the
effect types the UI can draw **[READ]**:
`BBDDelay` `Bias` `BitCrush` `BlackHole` `Chorus` `Chorus2` `Chorus3`
`ConnectorLFO` `ConnectorLoop` `ConnectorStereo` `MonoConnector` `Crossover`
`Delay` `Diffusion` `EQ3` `Echo` `Flanger` `Harmonizer` `LFO` `Lowpass`
`NoEffect` `Phaser4` `Phaser6` `Phaser12` `PingPong` `Reflection` `Resonator`
`Reverb` `Spring` `StereoChorus` `StereoDelay` `StereoFlanger` `TapeDelay`
`Tremolo` `Vocoder10` `Vocoder16` `Vocoder21`

### 10.6 Rows, cells, knobs

`SoftKnob` · `las::SoftKnobComponent` · `las::SoftKnobRows` (+`::Pimpl`) ·
`las::SoftKnobMouseHandler` · `las::SoftKnobSelectionListener` ·
`SoftKnobValueFormatter` · `las::SoftKnobOscStatsRateFormatter` ·
`las::SoftKnobOscStatsDurationFormatter` · `ModMatrixRow` · `ModMatrixSoftKnob` ·
`MidiMappingRow` · `SequencerCell` · `SequencerNote` · `SequencerMod` ·
`SequencerNotesRow` · `SequencerModsRow` · `SequencerColumnFocus` **[READ]**

### 10.7 The Updater framework — how UI binds to state

This is the spine of the whole program. `las::ParamUpdater` (fileoff 132393964)
is the base; `las::Param` / `ParamBool` / `ParamInt` / `ParamFloat` /
`ParamString` / `ParamArray` (each with a `Pimpl` and a
`ParamPimplBase<T,ParamX>` template instantiation) hold the values. **[READ]**

Updater subclasses, all **[READ]**:

```
ParamFloatUpdater  ParamIntUpdater  ParamBoolUpdater  ParamStringUpdater
ParamArrayUpdater  DummyParamUpdater  SoftParameterUpdater  SoftKnobUpdater(+Pimpl)
SoftKnobRowsEncoderKnobUpdater  SoftButtonLambdaUpdater
EncoderKnobUpdater  EncoderButtonUpdater  DirectLEDUpdater  LEDUpdater
LabelHertzUpdater  LabelMillisecondsUpdater  LabelOnOffUpdater
LabelOrderedParameterUpdater  LabelPercentageUpdater  LabelSecondsUpdater
LabelTextUpdater
ComponentUpdater  DummyComponentUpdater  ScriptingComponentUpdater
VisibleComponentUpdater<juce::Component>  PanelVisibilityUpdater
MorePanelVisibilityUpdater  PanelFocusUpdater  SaveActionUpdater
ToggleParamTriggerUpdater  ToggleParamFocusedTriggerUpdater
OrderedParamFocusedTriggerUpdater
LambdaComponentUpdater  LambdaTriggerComponentUpdater  LambdaValueComponentUpdater
LambdaFullComponentUpdater  (and UI* variants of all four)
ExpressionSlotsUpdater  MidiControlOutputUpdater
OscStatsUpdater  OscStabilityUpdater
```
plus per-panel anonymous-namespace updaters
(`ModMatrixEncoderKnobUpdater`, `ModMatrixSoftKnobUpdater`,
`LoadModMatrixEncoderKnobUpdater`, `NoiseEnvelopeSustainUpdater`,
`StepModUpdater`, `CompareUpdater`, `ShiftUpdater`, `SynthButtonUpdater`,
`HardwareTestEncoderKnobUpdater`, `LHCCalibrationEncoderKnobUpdater`,
`VoiceCardCalibrationEncoderKnobUpdater`, `VXResultEncoderKnobUpdater`). **[READ]**

Every updater is filed in a hash map keyed by an integer index (registrar at vma
`0x8c99a4`, ~2,000 registrations in `Pimpl::initialise`). The application's
public verbs are `updateValue(index, var)` / `updateNormalized(index, uint16)` /
`paramValue(index)` / `paramNormalized(index)` / `paramOrdinal(index)`. **[READ]**

### 10.8 Listener framework

`las::*Listener` + `Managed*Listener` pairs, with a `broadcast()` helper per
family **[READ]**: `CompareChangeListener`, `FocusChangeListener`,
`KeyboardListener`, `KnobChangeListener`, `MasterTempoListener`,
`MidiClockListener`, `MidiMessageListener`, `NoteListener`,
`PresetChangeListener`, `PresetSaveListener`, `ShiftChangeListener`,
`SynthChangeListener`, `VoiceListener`, `SchedulerListener`, `QueueListener`.

### 10.9 Senders / receivers / queues

| class | fileoff | port |
|---|---|---|
| `las::OSCTreeSender` | 132417296 | → 9300 (`las-sc`) |
| `las::VoiceControlSender` (+Pimpl) | 132422056 | → 7770 (XMOS) |
| `las::PanelOutputSender` (+Pimpl, +`LedSenderBrightnessUpdater`) | 132419617 | → 9100 (XMOS) |
| `las::OLEDSender` | 132417096 | → 9876 (XMOS) |
| `las::PerformanceSender` | 132421392 | → 7771 (XMOS) |
| `las::PresetSender` (+Pimpl) | 132421568 | (bulk preset push) |
| `las::PanelInputReceiver` (+Pimpl) | 132418600 | ← 9500 |
| `las::PerformanceReceiver` (+Pimpl) | 132421104 | ← 7772 |
| `las::SystemClock` (+Pimpl) | 132421776 | → 9501, token `LTRS` |
| `las::QueueMessageHandler::Pimpl`, `QueuedMessage`, `QueuedMessageProcessor`, `BitPackedMessage`, `KeyboardMessage`, `NoteMessage`, `PerformanceMessage`, `SequencerMessage`, `SequencerNoteMessage`, `SequencerModMessage` | 132389048ff | low-contention queues |
| `las::BitPacked` | 132386448 | 1/4/8/16-bit (and reversed) packing — the **panel** codec |
| `las::SoundEngineBlock` | 132386935 | the **xOSC** batching container |

**[READ]** throughout.

`las::BitPacked`'s test names — `Pack 4-bit`, `Pack 8-bit`, `Pack 16-bit`,
`Pack Reverse 4/8/16-bit`, `Extract single bits`, `Extract 4/8/16-bit words`
(fileoff 132386535–132386707) — together with
`PanelInputReceiverTests::TestQueueProcessor{1Bit,4Bit,16Bit,Paths}` make it clear
`BitPacked` is the **panel-scan** codec, distinct from `SoundEngineBlock`.
**[READ]** for the names; **[INFERRED]** for the role split.

Panel-input vocabulary (fileoff 132418819–132419304) **[READ]**:
`Left panel buttons`, `Left panel circular knobs`, `Left panel knobs`,
`Right panel buttons`, `Right panel knobs`, `Center panel buttons`,
`Center panel knobs`, `LHC buttons` (`/lhcb`), `LHC knobs` (`/lhck`), `/cenc`,
`/cvin`, `/state/send`, `/listen`, `/override`, `/override1`, `/override2`,
`/override1:2`, `/override1:4`, `/override2:6`.

### 10.10 Model / persistence

`las::LASDatabase` (+`Pimpl::LowPriorityExecutor`) over SQLite; database files
`MOOG ONE.db` and `MOOG ONE EXAMPLES.db` (fileoff 132808390/132808411), settings
`las-frontend.properties` (132808261), `fan-calibration.properties` (132808298),
calibration DB `/var/cal/vxcal.db` (132807323). **[READ]**
Model classes: `las::Preset` (+Pimpl), `las::PresetMaker` (+Pimpl),
`las::PresetMakerCache`, `las::Master` (+Pimpl), `las::Settings` (+Pimpl),
`las::MidiMapping` (+Pimpl), `las::ModMatrix` (+Pimpl), `las::ModulationLane`,
`las::NoteLane`, `las::NoteStack`, `las::Sequence`, `las::Sequencer` (+Pimpl),
`las::Arpeggiator` (+Config, +Pimpl), `las::BeatTracker`, `las::ChordLearner`,
`las::MasterClock` (+Pimpl), `las::Scheduler` (+Pimpl), `las::Node` (+Pimpl),
`las::Root` (+Pimpl), `las::TreeComponent` (+Pimpl), `las::GraphData`,
`las::FeatureFlags`, `las::CalDB`, `las::CalLogger`, `las::FrontPanelCalibration`,
`las::TuningAnalyzer`, `las::OscStabilityAnalyzer`,
`las::ImportExportProcessor`, `las::CreateNewUserSpaceProcessor`,
`las::PopulateFactoryData`. **[READ]**

### 10.11 Scripting and test harness — the real extension surface

`--script=<path>` runs JavaScript through `las::LASScriptRunner` (+Pimpl), with
these host objects registered as JUCE `DynamicObject` classes **[READ]**:

| class | fileoff | exposed methods |
|---|---|---|
| `las::ScriptConsoleClass` | 132424600 | `debug`, `println` (object name `Console`) |
| `las::ScriptDisplayClass` | 132424824 | `clear`, `drawEllipse`, `drawLine`, `drawRect`, `drawRoundedRectangle`, `drawText`, `fillAll`, `fillEllipse`, `fillRect`, `fillRoundedRectangle`, `setColour`, `setFontSize`, `activateChineseFont`, `activateLatinFont`, `showOled`, `clearOled`, `fillOled`, `setOledColour` (object name `Display`) |
| `las::ScriptOscClass` / `las::ScriptOscSenderClass` | 132425236 / 132425192 | `sendMsg` (object name `OSCSender`) |
| `las::ScriptPanelClass` | 132425604 | `waitForChange`, `waitForChangeAndClearLED`, `waitForValue`, `waitForAtLeast`, `waitForAtMost`, `waitForReply`, `waitForFullTurn`, `waitForSpacebar`, `setLED`, `sendLEDs`, `sendAllLEDs`, `clearLEDs`, `unflashLED`, `monitor`, `monitorAndClearLED`, `readValue`, `unMonitor`, `calLoad`, `calSave`, `calDefaults`, `calSetLow`, `calSetMid`, `calSetHigh`, `calSetXYUpperLeft`, `calSetXYLowerRight` |
| `las::ScriptUtilsClass` | — | (methods not recovered) |

Support: `las::LASTestRunner` (+Pimpl), `las::GUITest` (+Pimpl, init/before/after
callbacks), `las::ScheduleScriptCallback`, `las::ScheduleTestsCallback`,
`las::ScriptFailedCallback`, `las::QuitScriptException`,
`las::ShuttingDownException`, `las::MakeScreenshot`. Errors:
`A script is already running`, `Failure while running script:`, `TEST EXITED!`.
**[READ]**

**This is a first-class, shipped scripting host with direct access to the OSC
senders and the OLEDs, reachable with one command-line flag and no firmware
modification.** It is the strongest extension point found in this region.
**[INFERRED]** as an assessment; the API surface itself is **[READ]**.

---

## 11. Navigation

`las::MainComponent`'s translation unit carries a registry of panel identifier
strings, fileoff 132794352–132795318. **[READ]** Verbatim, in order:

```
canvas  confirmation  browseSnapshots  browseSynths  saveItemPreset  savePreset
editNotes  AMPLIFIER  fanCalibration  formatUsbDrive  settingsTuning
settingsTuningEditor  settingsRenameDuplicates  settingsRenameTuning
settingsCopyTuning  settingsSaveTag  settingsSaveUserSpace  settingsExport
loadSequence  loadMidiMap  loadModMatrix  midiMapping  oscillatorTuning
systemCalibration  cvOutCalibration  cvInCalibration  pedalInCalibration
mainOutCalibration  headphoneOutCalibration  noiseSourceCalibration
frontPanelLowCalibration  frontPanelMidCalibration  frontPanelHighCalibration
lhcCalibration  performanceSetBrowse  performanceSetOverview  quickAssign
quickMidiLearn  synth1SequencerNotes  synth2SequencerNotes  synth3SequencerNotes
synth1SequencerMods  synth2SequencerMods  synth3SequencerMods  slotMachine
startup  testResult  upgradeFirmware  serialMacWrite  voiceCardCalibration
voiceCardCalResult  voiceCardCalSelect  voiceCardCalProgress  VoiceEnableDisable
warningNotify  warningConfirm  warning
```

Further identifiers live in their own panels' TUs — `presetLanding` (132519528),
`browsePresets` (132527696), `masterClock` (132572921),
`performanceSetArrange` (132619859), `settingsGlobal` (132648547),
`settingsLibrary` (132648590), `masterTuning` (132648631), and the per-synth mod
matrix keys `synth1ModMatrix` / `synth2ModMatrix` / `synth3ModMatrix`
(132619811–132619843). **[READ]**

The navigation graph itself (which panel opens which) is **[UNKNOWN]** — it is
built from `setVisible` closures and `PageTabs` state, and recovering the edges
would require following the `PanelVisibilityUpdater` /
`MorePanelVisibilityUpdater` registrations one by one. See §16.

What *is* established: `las::MainComponent` also owns the backlight, holding the
paths `/sys/class/backlight/backlight/max_brightness` and
`/sys/class/backlight/backlight/brightness` (fileoff 132794264/132794310).
**[READ]** And screen-saver entry/exit is logged as `Enter Screen saver mode` /
`Exit Screen saver mode` (132806619/132806643). **[READ]**

---

## 12. Modulation-matrix vocabulary as the UI knows it

From `las::ModMatrix`'s translation unit, fileoff 132392253–132393524, in the
order the tables appear in `.rodata` (which is reverse of source order for the
enumerated arrays). **[READ]**

**Sources** (partial list as laid out; these are the `src` ids):
`FILTER EG` `AMPLIFIER EG` `MODULATION EG` `NOISE EG` `MOD WHEEL` `PITCH WHEEL`
`PAD X` `PAD Y` `PAD PRESSURE` `PAD GATE` `VELOCITY` `VEL RELEASE` `AFTERTOUCH`
`KEY PITCH` `KB GATE` `ON/OFF GATE` `TRIGGER GATE` `EXP 1` `EXP 2` `CV IN 1`
`CV IN 2` `RANDOM` `RANDOM BIPOLAR` `RANDOM KEYED 1` `RANDOM KEYED 2`
`RANDOM KEYED 3` `CONSTANT`

**Transforms** — the panel selector list and the `FUNCTION` sub-list:
selectors `LIMIT LOW` `LIMIT HIGH` `SQUARED` `CUBED` `LOPASS` `HIPASS` `SLEW`
`SLEW UP` `SLEW DOWN` `BOUNCE` `FUNCTION`;
functions `S/(1-C)` `(S+C)^2` `SIN(S+C)` `TRI(S+C)` `SAW(S+C)` `|S+C|`
`MIN(S,C)` `MAX(S,C)` `S AND C` `S OR C` `QUANTIZE S BY C` `SAMPLE S ON C`
`SAMPLE S ON ~C` `TRACK S WHILE C` `TRACK S WHILE ~C` `SLEW S OVER C`
`LOPASS S OVER C` `HIPASS S OVER C` `C(S-V)` `CV+S` `(C+1)V+S` `V+C(V+S)`
`C|V|+S` `DIODE(S-C)` `DIODE(S-C+0.5)` `DIODE(S-C-0.5)` `DIODE(S-C+0.25)`
`DIODE(S-C-0.25)`

**Destinations** (the `dst` ids), including:
`ALL OSCS` `SVF FILTER` `LADDER FILTER` `EG 1` `EG 2` `LFO 4` `HEADPHONES`
`MASTER VOLUME` `SVF/LADDER MIX` `VCO1/2/3 LADDER` `VCO1/2/3 SVF` `RMOD LEVEL`
`BEAT` `FM ROUTE` `RING MOD SOURCES` `PULSE LFO 3 MOD` `ANGLE LFO 3 MOD`
`PITCH EG MOD` `PITCH LFO 1 MOD` `FM MOD` `PITCH OFFSET` `EXT LEVEL`
`TIME SCALE` `VAR 1`…`VAR 10` `CV OUT 1`…`CV OUT 4` `CV OUT` `VARS`

Note `VAR 1`…`VAR 10` and `CV OUT 1`…`CV OUT 4` as *destinations*: the UI can
route modulation into the 10 preset variables and the four CV outputs. Preset
field names `var0`…`var9` and `cvout1`…`cvout4` corroborate (fileoff
132395719–132395790). **[READ]**

The MIDI-learn side uses `7BIT` / `14BIT` resolution and a full `CC 0`…`CC 127`
name table (fileoff 132391462–132392240, with `CC 84` absent — the table skips
from `CC 83` at 132391950 to `CC 85` at 132391956). **[READ]** That gap is
either a genuine reservation or a build artefact; **[UNKNOWN]** which.

---

## 13. `--print-nrpns`

The output is a fixed table at fileoff 132803778 onward, with a header
`SYNTH 1  SYNTH 2  SYNTH 3  OPTIONS or CONTINUOUS`, and per-row a parameter name
plus, where the parameter is stepped, an explicit range legend. **[READ]**
Example rows:

```
Waveform     : TRI (0-4095) - PULSE (4096-8191) - SAW (8192-12287) - S&H (12288-16383)
Octave       : 32' (0-3276) - 16' (3277-6553) - 8' (6554-9829) - 4' (9830-13106) - 2' (13107-16383)
Svf Mode     : LP (0-4095) - HP(4096-8191) - BP (8192-12287) - NOTCH (12288-16383)
Ladder Slope : 6dB (0-4095) - 12dB(4096-8191) - 18dB (8192-12287) - 24dB (12288-16383)
Rate Synced  : 64 (0-1365) - 32 (1366-2730) - 16 (2731-4095) - 8 (4096-5460) - …
```

The formatter at vma `0x8be064` prints, for one base number `n`, the triple
`n`, `n+3840`, `n+7680` each as `value (MSB:LSB)` with `MSB=(v>>7)&0x7f`,
`LSB=v&0x7f`. **[READ]** So **synth 2 = synth 1 + 3840 and synth 3 = synth 1 +
7680** in NRPN number space. 3840 = 30 × 128.

The sections are 14-bit values 0–16383 throughout, i.e. NRPN data is 14-bit.
**[READ]**

---

## 14. Settings vocabulary (for anyone writing to `Settings`)

From `SettingsGlobalPanel`, fileoff 132646803–132648501, verbatim. **[READ]**

Sections: `LOCAL CONTROL` `HARDWARE SETTINGS` `MIDI CONTROL` `MIDI I/O`
`CV INPUTS` `CV OUTPUTS` `UTILITIES` `MAINTENANCE`.

Items: `KNOB MODE` · `KEYB. VELOCITY CURVE` · `AFTERTOUCH CURVE` · `CHORD MEMORY` ·
`DISPLAY ACTIVE VOICES` · `OSCILLATOR COMPENSATION` · `LCD BRIGHTNESS` ·
`LCD DIM AMOUNT` · `PANEL LED BRIGHTNESS` · `FAN MODE` · `SHOW BANK PREVIEW` ·
`PRESET AUTOLOAD` · `DUPL. ON IMPORT` · `DUPL. ON EXPORT` ·
`STEP EDIT AUTO-SCROLL` · `NOISE REDUCTION` · `CURRENT TIME` · `LEARN MIDI CC` ·
`EDIT MIDI MAPPING` · `MIDI CONTROL OUTPUT` · `ALWAYS SEND NRPN NUM.` ·
`RECEIVE MIDI CLOCK` · `RECEIVE MIDI START/STOP` · `LOAD FROM PRESET` ·
`MIDI IN PORTS` · `MIDI IN ROUTE` · `MIDI IN CHANNEL ALL` ·
`MIDI IN CHANNEL SYNTH 1/2/3` · `MIDI OUT PORTS` · `MIDI OUT ROUTE` ·
`MIDI OUT CHANNEL ALL` · `MIDI OUT CHANNEL SYNTH 1/2/3` · `NOTE 1` · `NOTE 2` ·
`EXP IN 1` · `EXP IN 2` · `SUSTAIN IN` · `SWITCH TYPE` · `OUT VOLTAGE MIN` ·
`OUT VOLTAGE MAX` · **`VOICE RULE`** · `LIGHT SHOW` · `RESTORE DEFAULT SETTINGS` ·
`FIRMWARE VERSION` · `UI VERSION` · `BUILD DATE` · `BUILD INFO` · `IP ADDRESS` ·
`EFFECTIVE UPTIME`.

CV-output source names: `EXPRESSION` `PITCH V/OCT` `ENV GATE` `SOSTENUTO PEDAL`
`NEXT PRESET` `PREVIOUS PRESET` `NEXT SET` `PREVIOUS SET` `SEQ RUN/STOP`
`SEQ RETURN TO ZERO` `CV 1 INPUT` `CV 2 INPUT` `PEDAL 1 INPUT (EXP 1)`
`PEDAL 2 INPUT (EXP 2)` `SUSTAIN PEDAL INPUT` `SEQUENCE PITCH (U)`
`SEQUENCE PITCH (B)` `SEQUENCE GATE` `SEQUENCER RTZ` `MODULATION OUTPUT`
`MIDI CC 2 (BREATH)` `MIDI CC 4 (FOOT PEDAL)` `MIDI CC 11 (EXPRESSION)`
`MIDI CC 74 (BRIGHTNESS)`. **[READ]**

Maintenance / CM items: `BRD-10-011-1204 SYS TEST`, `BRD-10-011-1207 RIGHT TEST`,
`BRD-10-011-1208 MIDDLE TEST`, `BRD-10-011-1209 LEFT TEST`,
`FRONT PANEL ASSEMBLY TEST`, `LHC SUBASSEMBLY TEST`, `REAL TIME CLOCK TEST`,
`CPU LOAD 100%` / `50%` / `OFF` (implemented by `killall` + `stress`, fileoff
132646216/132646224 — `stress` is invoked by name), `DISPLAY iMX CORE TEMP`,
`OSCILLATOR MONITORING`, `OSCILLATOR STABILITY`, `SERIAL AND MAC ADDRESS`,
`HARDWARE TEST`, `SYSTEM CALIBRATION`. **[READ]**

**`VOICE RULE` is present in the 1.8.2 UI.** This bears on
`CORRECTIONS-2026-09-08.md §9`, which lists `cv_output/N/voice_rule` as an open
question ("firmware difference, or a hole in the dump"). The setting exists in
this build's settings UI, and `voice_rule` is in `las::Preset`'s field-name table
(fileoff 132396631). **[READ]** It is also in the 1.5.0 binary's class/string
inventory (the two binaries' string sets are equivalent for this region).
**[INFERRED]** Conclusion: the gap is in the namespace dump, not the firmware —
but this has not been proven against a live query. See the validation plan.

---

## 15. 1.5.0 vs 1.8.2 — what actually changed in this region

- Class inventory: **identical**. **[READ]**
- CLI argument set: **identical**. **[READ]**
- `S43gui` launch line: **identical**. **[READ]**
- `xOSC` / `Sound Engine Controller` strings: present in both, same order.
  **[READ]**
- Build stamps differ (`051622-1116` / `f77b0d82f` → `091525-1457` / `9144962cb`)
  and the file sizes differ by 37,288 bytes (145,070,812 → 145,033,524), i.e.
  **1.8.2 is slightly smaller** — consistent with preset-content churn in
  `.rodata` rather than code growth. **[READ]** for the numbers, **[INFERRED]**
  for the cause.
- XMOS payloads shipped alongside: 1.8.2 carries `app_las_v2.2.2.bin` and
  `app_vx_10M_v2.2.1.bin` (`/usr/share/xmosfw/`), against `v2.1.2` / `v2.1.0` in
  the arch-harvest set from the 1.5.0 instrument. **[READ]**

So: **nothing about the UI architecture or the modulation path changed between
the owner's instrument and the newest firmware.** Anything built against this
document works on both. **[INFERRED]** from the three identity results above.

---

## 16. Conflicts with existing docs

Reported, not fixed, per instruction.

1. **`docs/ARCHITECTURE.md` / `MOOG-ONE-INTERNALS.md` — the control plane.**
   Wherever those files describe `las-sc` as the sound-engine controller that the
   frontend drives, that is true only for the `/p` tree and the FX/mixer slice.
   The synth voice state and the modulation matrix bypass `las-sc` entirely and
   go to the XMOS on port 7770 in a binary form. The frontend's own help text
   ("xOSC directly to the Voice Controller") should be quoted wherever this is
   described. **[READ]**

2. **`docs/arch/midi-stack.md` (not read in detail here) — outbound MIDI.**
   If it says the XMOS originates the instrument's outbound MIDI, that is wrong:
   `las-frontend` builds the MIDI bytes and ships them as `/mo/din0` /
   `/mo/usb0` OSC messages, one int32 per byte, on the performance channel to
   `vc:7771`. **[READ]** The XMOS is the serialiser, not the source.

3. **`CORRECTIONS-2026-09-08.md §8`** lists "Display threads run SCHED_FIFO
   93/80" as **[AGENT]**. It is now **[READ]**: `etc/init.d/S99final:14-15`,
   `chrt -f -p 93` on the IPU tasks and `chrt -f -p 80` on the IPU IRQ.

4. **`CORRECTIONS-2026-09-08.md §9`, `voice_rule`.** `VOICE RULE` is a live
   settings item in the 1.8.2 UI and `voice_rule` is a `las::Preset` field name.
   **[READ]** The "hole in the dump" hypothesis is now the better-supported one.

5. **The `_m` twins.** This report found no `_m` handling anywhere in
   `las-frontend`'s address vocabulary. The frontend's VC namespace is `/x`,
   `/g/n/…`, `/v/…`, `/hw/…`, `/therm/…`, `/a/…`, `/patch/…`, `/cvi`, `/cvo`,
   `/ccmap`, `/mo/…`. **[READ]** That is consistent with `_m` being purely
   `las-sc`'s computed output, but it is negative evidence only.

6. **Address count.** `captures/p-namespace-keys.txt` has **3,197** lines
   **[READ]**, whereas the working architecture note says "~536 `/p` addresses,
   115 `_m` twins". Those two numbers are describing different things (the full
   preset tree vs `las-sc`'s own namespace) and the docs do not say which is
   which. Worth a terminology pass.

7. **Service backdoor, outside this region but found in passing.**
   `etc/init.d/S99final:31-39`: if `/media/thumbdrive/k` exists and
   `hexdump | awk '{print $3 $2}'` equals **`23051934`**, the script kills
   `las-watchdog`, leaves the three `xterm`s and `las-dwm` running, and **skips
   the `mount -o remount,ro /`**, leaving the rootfs writable. **[READ]** If
   `docs/arch/extension-points.md` does not already record this, it should: it is
   a supported, firmware-signed way to get a writable root and a console with no
   modification whatsoever.

---

## 17. Validation plan (READ-ONLY, for a human to run on the instrument)

Nothing here writes to the instrument. Nothing here restarts a service. Each
command names the claim it tests.

**A. Confirm the process argv and affinity (tests §3, §4.4).**
```
cat /proc/$(pidof las-frontend)/cmdline | tr '\0' ' '; echo
grep Cpus_allowed_list /proc/$(pidof las-frontend)/status
for t in /proc/$(pidof las-frontend)/task/*; do
  printf '%s\t%s\t%s\n' "$(basename $t)" "$(cat $t/comm)" "$(grep -m1 Cpus_allowed_list $t/status)"
done
```
Expect: the S43gui argv verbatim; `Cpus_allowed_list: 0` on the process and on
every thread; thread names including `Voice Control`, `UI BookKeeping`,
`OSC Panel Input`, `OSC Perf. Input`, `Preset Sender`, `System Clock`,
`Send LEDs`, `LED Flash`, `Send OSC Tree`.

**B. Confirm the socket map (tests §5).**
```
cat /proc/net/udp
ls -l /proc/$(pidof las-frontend)/fd | grep socket
netstat -uanp 2>/dev/null | grep -E '7770|7771|7772|7775|9100|9300|9500|9501|9876'
```
Expect: `las-frontend` bound on 9500 and 7772; `las-sc` bound on 9300 and 7775;
connected sockets from `las-frontend` toward `203.0.113.2:7770`, `:7771`,
`:9100`, `:9501`, `:9876` and toward `127.0.0.1:9300`, `:7775`.
Note `/proc/net/udp` shows addresses in hex, little-endian: `203.0.113.2` is
`0271` `00CB` reversed → look for `02710BCB`; port 7770 = `1E5A`.

**C. Prove the mod-matrix path (the central claim, §6). Passive capture only.**
```
tcpdump -i usbint -s0 -w /tmp/vc7770.pcap 'udp port 7770'
```
Then, on the instrument's own front panel, open the mod matrix and change one
row's destination. Stop the capture. Expect **one UDP datagram to
203.0.113.2:7770** whose OSC address string is `/g/0/t/e/s` (or `/g/1/…`,
`/g/2/…` for synths 2 and 3), type tag `,b`, and a blob whose length is a
multiple of 16.

Decode with, e.g.:
```
tcpdump -r /tmp/vc7770.pcap -X | head -60
```
The first bytes of the OSC payload should read `2f 67 2f 30 2f 74 2f 65 2f 73 00 00`
(`/g/0/t/e/s` NUL-padded to 12), then `2c 62 00 00` (`,b`), then a 4-byte
big-endian blob length, then the slots. Byte 0 of each 16-byte group is `src`;
bytes 1–4 are `src_a` as a **little-endian** float (JUCE writes the blob body
verbatim; only the OSC framing is big-endian) — this endianness is the one thing
in §6.4 worth checking against the wire.

**D. Prove the bulk parameter path (§7).**
Same capture; turn any front-panel knob (say SVF Cutoff). Expect datagrams to
7770 with OSC address `/x` and a blob argument, and **no** corresponding traffic
on 9300.
```
tcpdump -i lo -s0 -c 200 'udp port 9300'
```
Run that during a knob turn: expect little or nothing for voice parameters, and
`/p/part/...` messages when an effect or mixer parameter changes.

**E. Confirm the `/patch/begin` … `/patch/end` bracket (§8).**
Capture 7770 while loading a preset from the panel. Expect `/patch/begin`, then a
burst including `/g/n/t/e/s` for all three synths and many `/x` messages, then
`/patch/end`.

**F. Confirm the outbound-MIDI path (§9).**
```
tcpdump -i usbint -s0 -c 50 'udp port 7771'
```
Turn a knob with `MIDI CONTROL OUTPUT` enabled. Expect OSC messages `/mo/din0`
or `/mo/usb0` with type tag `,iii` (or more `i`s) whose int32 values are the
MIDI bytes.

**G. Confirm no ALSA MIDI device is opened (§9).**
```
ls -l /proc/$(pidof las-frontend)/fd | grep -c snd
amidi -l
```
Expect zero `snd` file descriptors held by `las-frontend`.

**H. Confirm the build identity (§2).**
```
cat /etc/version ; cat /etc/git-tags
```
On the owner's 1.5.0 instrument expect `las-v1.5.0`; on 1.8.2, `las-v1.8.2` and
`"LAS_FRONTEND_GIT_TAG" : "2.1.4"`.

**I. Settle `voice_rule` (§14, §16.4).**
On the instrument, navigate Settings → CV OUTPUTS and read whether `VOICE RULE`
appears as an item. No command needed; this is a look-at-the-screen test.

**Explicitly NOT proposed:** running `las-frontend --print-nrpns` or
`--help` on the instrument. The running instance owns the sockets and the
database; a second instance would contend for both. If the NRPN table is wanted,
it is already fully present in `.rodata` at fileoff 132803778–132806620 and can
be read offline.

---

## 18. Unexplored

Named honestly, so the next pass knows where to start.

1. **The navigation graph.** Which panel opens which. Requires walking the
   ~2,000 updater registrations in `Pimpl::initialise` (vma ≈ `0x8c9000`–
   `0x8cf700`) and the `PanelVisibilityUpdater` / `MorePanelVisibilityUpdater`
   construction sites. Mechanical but large.

2. **The UpdaterIndex enum.** ~2,000 keys registered at vma `0x8c99a4`. Only six
   are named in this report. Recovering the full index→parameter map would give
   a complete remote-control surface for the frontend, and would settle whether
   UpdaterIndex and the `--print-nrpns` number space are the same enum (§6.3).
   The `las::MidiMapping::Pimpl::getPathForUpdaterIndex(UpdaterIndex)` and
   `getUpdaterIndexForPath(juce::String)` methods (fileoff 132390492, 132390756)
   are the two functions that hold the answer.

3. **`las::SoundEngineIndex`.** A second index space, seen only in
   `PerformanceReceiver::Pimpl::updateKnobForParameter(int, float,
   SoundEngineIndex, UpdaterIndex)`. Its relationship to `/x` blob record layout
   is the missing half of §7 — I documented the *container* but not the *record
   format inside a `SoundEngineBlock`*. That is the single highest-value
   remaining target in this region.

4. **`las::BitPacked` panel codec.** The 1/4/8/16-bit and reversed variants are
   named but the exact framing of a panel-scan message on 9500 was not decoded.

5. **The `/g/<n>/…` VC namespace generally.** Only `/g/n/en` and `/g/n/t/e/{s,q}`
   were resolved. There are almost certainly more leaves under `/g/n/t/`.

6. **`--assume-auto-polling` and `/auto`.** The panel auto-polling protocol was
   not traced.

7. **`las::Node` / `las::Root` / `las::TreeComponent`.** Presumably the `/p` tree
   model and the on-screen tree browser (`CanvasPanel`?). Not opened.

8. **`las::MidiMapping` sanitise/upgrade paths.** Four named methods
   (`sanitizeAndUpgradeMidiMap`, `sanitizeAndUpgradeSettingsMidiMap`) that run on
   settings-version bumps; relevant to anyone writing MIDI maps externally.

9. **The 580 embedded preset bodies.** Confirmed present (the `.rodata` text is
   full of complete `/p/...` preset dumps) but not inventoried here.

10. **`LowLevelGraphicsSVGRenderer` + `las::MakeScreenshot`.** A shipped
    SVG-export renderer. Not investigated as an extraction route for the UI's
    exact geometry.

11. **`--touch-to-vco`** ("Generate VCO pitch offset messages for touch panel")
    — not traced. Suggests a touch surface the shipped UI does not use.

12. **`las::Scheduler` / `las::Operation` hierarchy.** ~30 `*Operation` classes
    driving calibration through `las::OSCQuery`. Documented only by name.
