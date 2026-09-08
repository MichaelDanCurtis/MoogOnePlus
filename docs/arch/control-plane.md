# Moog One — Control Plane Map

Reverse-engineering notes derived **entirely from local host binaries and captures** in
`captures/arch-harvest/` and `captures/`. Nothing here was read from a live instrument for
this document; where a fact was confirmed on hardware in an earlier session that is marked
**READ (live, prior)** and sourced to the capture file. Everything else is **READ (binary)**
— directly observed in a binary/script — or **INFERRED** — a reasoned conclusion.

Firmware baseline: SEC/host image `app_las` **v2.1.2**, voice-card image `app_vx_10M`
**v2.1.0** (`captures/arch-harvest/app_*.bin`; versions echoed at `las-sc` strings
`vc firmware file:` / `VX firmware file:`).

Tooling: Apple LLVM `objdump` disassembles these ELFs directly; a capstone annotator that
resolves ARM literal pools and `movw/movt` pairs to their target strings was used for the
control-flow reads (offsets below are file offsets from `strings -a -t x`, or VMAs where a
disassembly address is quoted).

---

## 0. Cast of processes (from `runtime-state.txt` `--- processes ---`)

| PID | Process | Role |
|---|---|---|
| 807 | `las-sc` | **Sound Engine Controller (SEC).** The bridge. Panel/preset ↔ voice controller ↔ effects. Primary target. Embeds a compiled Scheme (CHICKEN) interpreter. |
| 915 | `las-frontend` | Qt panel/display application (the UI). |
| 1257 | `sclang` | SuperCollider language, runs `init_sc_1.scd` — the **effects (EFX) engine** control layer. |
| 1294 | `scsynth` | SuperCollider audio server (the DSP graph, LADSPA rack). |
| 1212/1214 | `screen`/`launch-sc-1` | wrapper that launches the EFX server. |
| 1472 | `las-dwm` | dwm-derived X11 window manager for the panel display. |
| 217 | `X :0` | X server, framebuffer `/dev/fb1`. |
| (transient) | `las-watchdog -t=10000` | liveness monitor; started by `S99final` **only after** `las-sc` posts its cookie. |
| 2116 | `moogd` | **Not factory software.** The owner's own USB-hosted workbench (`/media/thumbdrive/moogd -addr :8080`), started by the added `S99moogd` init script. Serves the `vox` UI on TCP 8080. Called out here because it is live in the snapshot; it is outside the stock control plane. |
| 1644 | `avahi-daemon` | advertises `moog-one.local`. |
| 1652/2249 | `dropbear` | SSH — **present only because the USB dev-key was installed** (see §5). |

Kernel cmdline pins `isolcpus=1`: CPU1 is reserved. `las-frontend --affinity-mask=1`
and `moogd` (`taskset -c 0`) both live on CPU0; audio (`scsynth -a 129`) is steered by the
SC server. (READ, `runtime-state.txt`.)

---

## 1. The `las-sc` OSC namespace

`strings` on `las-sc` yields **810 address-like leaves** (`^/…` tokens). These are not all
served by `las-sc` itself — the large majority are the **address vocabulary of the voice
controller (VC)**, which `las-sc` speaks to over the voice bus (203.0.113.2:7770). This was
confirmed on hardware previously: `captures/sysmap/vx-api-map.md` records that bare addresses
(`/info/product` → `s:lasvc`) answer from the **controller board**, and `/vx/<0-15>/…`
addresses answer from **individual voice cards**. So this namespace is best read as *the
control surface `las-sc` exposes/relays*, keyed by prefix.

### Prefix census (deduplicated leaves)

```
/p       497   patch / voice parameters   <-- the big one, detailed below
/cal      62   calibration data           (DANGER, §5)
/a        32   voice allocation, routing, metering
/g        27   group / per-timbre global mix
/mix      25   voice mixer matrix
/in       21   external inputs (MIDI / CV / local / USB / rseq)
/info      8   identity & version
/fx0-2    19   the three effect-slot I/O routers (7+6+6)
/fa        7   dual analog filter (bandpass/hp/lp shortcuts)
/fxn       6   an effects-send bus
/t         6   timbre mixer enables
/lc        5   local-control (keyboard, XY pad, sustain)
/fw        3   VOICE-CARD FIRMWARE PUSH  (/fw/start,/fw/data,/fw/version)  (DANGER, §5)
/hw        3   hardware mute / hpf / auto-route
/testosc   3   built-in test oscillator  (DANGER-adjacent, §5)
/seq       3   sequencer network destination (/seq/dest/{mac,port}, /seq/direct-kbd)
/stat,/status,/statr,/sstat   metering / status reads
/therm     1   /therm/sys-temp
/sys       1   /sys/direct-kbd
/dbg       1   /dbg/oscl_ctl   (debug hook)
/mode      1   VC operating-mode setter
/ping      1   liveness
… plus ~60 singletons (mixer channel labels: /aux1-db, /line-db, /mic-db, /dir1-4, /main, /hph …)
```

(READ, binary. Full flat lists live in `captures/sysmap/osc-namespace.txt` and
`captures/sysmap/addrs-p.txt` from the prior pass; this document adds structure and meaning.)

### 1.1 `/p` — the patch tree (497 leaves)

`/p` is the **complete per-preset synthesis parameter tree** for a Moog One voice. Its
second segment is the module; depth runs 2–8. Structure recovered from the leaf set:

| Sub-tree | Count | Module (INFERRED from leaf names) |
|---|---|---|
| `/p/o1 /p/o2 /p/o3` | 25 ea | **3 oscillators.** leaves: `fo`(freq/octave) `oct` `pt`(fine) `po`(pulse/shape) `d`(duty) `ang` `tr`(?) `krst`(key-reset) `sync1-3` `fm1-3`(FM depth from src 1-3) `pbup/pbdn`(bend range) `m`(?) and `_m` mod-slot twins. |
| `/p/l1 /p/l2 /p/l3 /p/l4` | 24-25 ea | **4 LFOs.** `f`(rate) `w`(wave) `sym`(symmetry) `ph`(phase) `pol`(polarity) `d`(delay) `fidx/fmul`(freq mult) `one_shot` `rst/nrst/phr`(reset) `sh_noise`(S&H) `ta/td/tfin/tfout`(fade times) `var`(variation) + `_m` twins. |
| `/p/e1 /p/e2 /p/e3 /p/e4` | 15-21 ea | **4 envelopes.** `a d s r h`(AHDSR) `ak/dk/rk`(rate-key-scale) `delay` `key-follow` `tscale` `velmod` `latch` `loop` `sync` `multi-trig` `trig` + `_m` twins. |
| `/p/f` | 10 | **main filter routing:** `p`(cutoff) `r`(reso) `eg_p`(env→cutoff) `lfo_p` `fm/src` `fm/idx` + `_m`. |
| `/p/fa` | 38 | **filter A** (the dual-filter A path, per-pole `1/` `2/`): `lp/hp/bp` outs, `p/r/eg_p/lfo_p/fm` + `_m`. |
| `/p/fb` | 15 | **filter B** path: `p/r/eg_p/eg_r/lfo_p/hp/tap/v_p/p_p/p_fp` + `_m`. |
| `/p/mix` | 34 | **voice mixer:** `o1/o2/o3/{g,plsbal}` osc gains + pulse-balance, `n/{fa,fb,g}` noise routing, `ext/{ext0,ext1,fa,fb,g_m}` external-in routing, aux/line/mic sends + `_m`. |
| `/p/fx` | 26 | **per-voice insert FX:** `ins/{type,byp,dry,wet,g-in,g-out,control1,control2,p/0..15}` (16 generic params) + `pan`. |
| `/p/part` | 78 | **preset ("part") level:** `las-fx/{1,2}/…` = **two studio-effect slots**, each `type,en,byp,dry,wet,g-in,g-out,p/0..15`; `las-fx/{mode,par}`; `t/{1,2,3}/…` = **3 timbres** (`in,mix,p/{g,pan,fx}`); `rseq/0/in/{cv,midi,local,usb}` = **arpeggiator/sequencer input routing**; `midi/din-out/in`; `mix/ext-dir3-4`. |
| `/p/noise` | 9 | **noise source** envelope `a d s r ar mode` + `_m`. |
| `/p/m` | 7 | **mod-matrix cross-routes** (`e3_p`, `l1_p`, `l2_pan`, `l3_od/pd` …). |
| `/p/lc` | 16 | **local control** in-patch: `kbd/{curve,oct}`, `kbd/lhc/{modwheel,touch_x/y/z,pad_xyz,hold,load_saved_pos}` (left-hand controllers ×3), `xy/{hold,mode}`, `sus/type`. |
| `/p/clk` | 4 | **clock:** `rate,swing,nudge_mode,loadPresetTempo`. |
| singles | — | `/p/c /p/g`(glide) `/p/gc /p/pan /p/pbup /p/pbdn`(global bend) `/p/eg_g /p/fafb /p/fbal(_m)`(A/B filter balance) `/p/fm_m /p/ringsrc3`(ring-mod src) `/p/pre-expr /p/name /p/version`. |

**Key structural finding (READ + INFERRED):** **106 of the 497 `/p` leaves (21%) end in
`_m`** — a parameter's **modulation-slot assignment/amount** (e.g. `/p/o1/fo` = osc-1 pitch,
`/p/o1/fo_m` = the mod routing feeding it). So ~a fifth of the tree is modulation-routing
addresses. This is a high-value surface: the panel exposes only a few mod routes at a time,
but the address space lets you set **any** `_m` route directly — a much wider modulation
matrix than the UI presents.

**Count reconciliation:** the binary yields **497** distinct `/p` leaves; the prior on-device
sweep enumerated **~464–465** (`captures/sysmap/addrs-p.txt`, `vx-api-map.md`). The gap is
expected — some binary strings are templates or unused on this firmware, and some live
addresses (e.g. the `/p/lc/kbd/lhc/…` left-hand-controller leaves seen in
`captures/p-namespace-keys.txt`) are built at runtime rather than stored as literals. Treat
497 as the binary's vocabulary, ~464 as what answered live.

`/p/name` and `/p/version` are the preset's stored name and schema version (READ, binary,
`/p/version` at strings offset near `/p/clk/*`).

### 1.2 Other namespaces (meaning)

- **`/info`** — identity. `/info/product`(→`lasvc`), `/info/version`(→`v2.1.2`),
  `/info/versionb`(packed hex `33620735`=0x020102FF), `/info/fwrev`, `/info/git`,
  `/info/vc-version`, `/info/voice-count`. Prior live test: only `product/version/versionb`
  answer; the rest 404 on this firmware (READ live, `vx-api-map.md`).
- **`/a`** — voice **allocation & routing** engine: `max-voices`, `note-limit`, `note-steal`,
  `mono`, `mono-note-pri`, `pri`, `rnd`, `hold`, `chord/{en,ofs}`, `unison/{en,max-stack,
  pitch-spread}`, input inserts `in1-ins4`/`in2-ins3`, and the read-only meters
  `/a/stat/{mainl,mainr,send1,send2}` (two floats each — the summed analog output; per-card
  variants 404) (READ live, `vx-api-map.md`).
- **`/g`** — **group / per-timbre global mix**: `/g/{0,1,2}/t/…` for the 3 timbres, each with
  `mix/{main,sub,dir1-4,pan}-en` enables and `aux1/2` sends. Named twins like
  `timbre-1-aux1-en` sit alongside (the human-readable alias table).
- **`/mix`** — the **top mixer matrix**: osc→filterA/B routing (`o1/fa`,`o1/fb`…), `dir1-4`,
  `aux1/2`, `bal`, `g`, `mute`, external-in matrix `ext/…`.
- **`/in`** — **external control inputs**: `midi/{en,ch,tr,ccmap,note-min,note-max}`,
  `cv/0/{en,dest,in-min,in-max,out-min,out-max}` (CV-in scaling), `com/{tuning,tr,note-min,
  note-max}`, `local/{note-min,note-max}`, `usb`, `rseq/{en,id}`.
- **`/fx0 /fx1 /fx2 /fxn`** — the **three studio-effect slot I/O routers** plus a shared
  send bus: `in,out,dry,pan,sends,g-out,par`. These are the routing shell around the LADSPA
  effects; the *parameters* of each effect are the `/p/part/las-fx/N/p/0..15` block.
- **`/lc`, `/sys/direct-kbd`, `/seq/direct-kbd`** — local keyboard / direct-key modes.
- **`/mode`** — puts the VC into a named operating mode at startup (`--mode` / `initial-mode`,
  default value `normal`; the watchdog re-asserts `/mode normal` on recovery). Other legal
  mode strings were **not** found as literals in `las-sc` (only `normal`); INFERRED that
  calibration/test modes are selected by the separate `vxtune`/`--cal`/`--tune` tooling
  rather than by a `/mode` string. **Negative result:** could not enumerate the full mode set.
- **`/therm/sys-temp`, `/dbg/oscl_ctl`** — SOM temperature read; an oscillator-control debug
  hook (unmapped).

---

## 2. Topology

### 2.1 Interfaces (READ, `runtime-state.txt`)

- `lo` 127.0.0.1 — everything host-local.
- `usbint` **203.0.113.1/24** — USB-gadget link to the **voice controller at 203.0.113.2**.
  This is the private path to the VC/voice cards.
- `ethext` **192.168.1.136** (+ `.138` secondary) — the LAN.

`S95dhcpd` installs NAT so the LAN can reach the VC directly:
```
iptables -t nat -A PREROUTING -i ethext -p udp --dport 7770 -j DNAT --to 203.0.113.2:7770
                                              7771 → 203.0.113.2:7771
                                              9100 → 203.0.113.2:9100
                                              9300 → 203.0.113.2:9300
```
`ip_forward=1` is set in `S40network`. **INFERRED consequence:** any host on the LAN can send
OSC straight to the voice controller's 7770/7771/9100 and to `las-sc`'s 9300 — no tunnel
needed. `las-sc`'s own 9300 socket is bound to 127.0.0.1 (`0100007F:2454` in
`/proc/net/udp`), so the DNAT is what makes 9300 reachable from outside.

### 2.2 Listening sockets, reconciled with the binaries

From `runtime-state.txt` `--- listening udp ---` and the launch arguments:

| Port | Bound | Owner | Purpose (evidence) |
|---|---|---|---|
| **57110** | 0.0.0.0 | `scsynth` | SC audio server. `scsynth -u 57110`; `init_sc_1.scd` `Server.new(\server_main, NetAddr("127.0.0.1",57110))`. |
| **57120** | 0.0.0.0 | `sclang` | SC language default OSC-in. |
| **7775** | 0.0.0.0 | `sclang`/EFX | **EFX control input.** `efx_server.scd`: `thisProcess.openUDPPort(7775)`; `las-sc -f localhost:7775` names this as the "EFX Server address"; `launch-sc*` sets `SERVER_RECV_PORT=7775`. `las-sc` sends `/fx/…`,`/ping` here. |
| **9300** | 127.0.0.1 | `las-sc` | **`las-sc` OSC-in** (panel/preset commands). `-l localhost:9300`; `/proc/net/udp` `0100007F:2454`. Reachable from LAN via the DNAT above. |
| **9500** | 0.0.0.0 | `las-frontend` | **panel-state** query endpoint. `las-sc --panel-state=localhost:9500`; `las-sc` reads panel state from the frontend here. |
| **9600** | 0.0.0.0 | `las-sc` (2nd) | secondary `las-sc` socket (`:2580` in `/proc/net/udp`). Purpose not pinned; INFERRED preset/notify channel. |
| **7772** | 0.0.0.0 | `las-sc`/VC | voice-bus companion port (`:1E5C`). |
| **7770** | (VC, remote) | voice controller | **the voice bus.** `las-sc` on `203.0.113.1` connects out to `203.0.113.2:7770` (`/proc/net/udp` shows `017100CB:xxxx → 027100CB:1E5A`). Confirmed live in `vx-api-map.md`. |
| **9999** | — | — | `SERVER_SEND_PORT=9999` in `launch-sc*` (sclang's reply target). Not seen listening; INFERRED it is a send-only destination back toward `las-sc`/frontend. |
| **8080/tcp** | :: | `moogd` | owner's workbench UI (non-factory). |
| **22/tcp** | 0.0.0.0 | `dropbear` | SSH (dev-key gated). |
| **5353**, **68** | — | avahi, udhcpc | mDNS, DHCP client. |

The many high ephemeral UDP ports (`49967, 47680, 45818, …`) are SuperCollider/OSC client
sockets and the frontend's transient senders (INFERRED from count and 0.0.0.0 binding).

### 2.3 Data-flow (INFERRED from ports + args + init scripts)

```
                    ethext LAN 192.168.1.136
                          │  (DNAT 7770/7771/9100/9300 → VC)
   ┌──────────────────────┴───────────────────────────────────────────┐
   │                         Moog One SOM (CPU0/CPU1)                   │
   │                                                                   │
   │  las-frontend ──panel-state:9500◄── las-sc                        │
   │   (Qt UI)     ──host-oleds / host-paneloutput=203.0.113.2──┐      │
   │      │  --host-vc=vc  --host-performance=vc                │      │
   │      │  --host-systemclock=vc                              ▼      │
   │      └── OSC panel/preset ──► las-sc :9300 ──┐        voice bus    │
   │                                              │      203.0.113.2    │
   │  las-dwm (X11 WM, spawns via system())       │        :7770/:7771  │
   │                                              ├──► Voice Controller │
   │  las-sc  ──/fx/… :7775──►  sclang (EFX) ──► scsynth :57110         │
   │            │                (init_sc_1.scd)   (LADSPA rack, DSP)   │
   │            │  --vxfw/--vcfw/--vcfv                    │            │
   │            └── firmware: flashrom→XMOS(SPI)  &  /fw/* │            │
   │                                                       ▼            │
   │            SPI /dev/spidev0.0 (config-las-spi)   16 voice cards    │
   │                                                  /vx/0..15/…       │
   │  las-watchdog ──/ping,/vx/N/ping──► VC:7770  (binds :9666/:9799)   │
   └───────────────────────────────────────────────────────────────────┘
```

Meaning of the frontend `--host-*` args (INFERRED from names + who binds what):
`--host-vc=vc`, `--host-performance=vc`, `--host-systemclock=vc` all resolve the hostname
`vc` (= 203.0.113.2, the voice controller) as the source of performance/clock data;
`--host-oleds=203.0.113.2` and `--host-paneloutput=203.0.113.2` route the OLED strip and
panel-LED output through the VC board. So the VC is not only the audio brain — it also drives
the panel's OLEDs and reads the performance controls.

**Bus roles in one line each:**
- *panel/preset bus:* frontend → `las-sc:9300` (OSC).
- *panel-state bus:* `las-sc` → frontend `:9500` (reads knob/switch state).
- *OLED / panel-output bus:* frontend → VC `203.0.113.2` (`--host-oleds`,`--host-paneloutput`).
- *performance / systemclock bus:* frontend ← VC `vc` (`--host-performance`,`--host-systemclock`).
- *voice bus:* `las-sc` (203.0.113.1) ↔ VC/voice-cards `203.0.113.2:7770`.
- *effects bus:* `las-sc` → sclang `:7775` → scsynth `:57110`.
- *watchdog bus:* `las-watchdog` → VC `:7770` from local `:9666`/`:9799`.

---

## 3. `las-frontend` — exposed vs. present

145 MB stripped ARM ELF, **JUCE + Qt**. Offsets below are file offsets from `strings`; for
this binary **VMA = file_offset + 0x10000** (used to convert the disassembly VMAs cited).
The option table sits at file `0x7ea72ca`–`0x7ea75bb`, with a matching usage/help block at
`0x7ea5764` (`"Usage: "`, `" [ commands ]"`, `"Commands:"`). All items below are **READ**
unless marked INFERRED.

### 3.1 Command-line surface — the unused flags are the interesting part

The 11 boot flags (`--usb-path --data-path --host-paneloutput --host-performance --host-oleds
--affinity-mask --host-systemclock --cookie --affinity-panel --startup-coordination
--host-vc`) are the mundane subset. The flags present in the binary but **not** used at boot:

| Flag (offset) | Help text (verbatim) | Why it matters |
|---|---|---|
| `--test-fixture` (`0x7ea6477`) | *"Boot into HardwareTestPanel for use at CM"* | Jumps straight into the factory hardware-test harness (CM = contract manufacturer). **Danger, see D9.** |
| `--script=<path>` (`0x7ea635a`) | *"Runs the JavaScript at the provided file path."* | **Arbitrary JS execution** via JUCE's JS engine. **Danger, see D9.** |
| `--firmware-path=` (`0x7ea7476`) | *"Path for firmware updates (overrides USB path)"* | Point the flasher at any directory. |
| `--firmware-dry-run` (`0x7ea7487`) | *"…firmware update in dry-run mode"* | Maps to `lasfwu --dry-run`. |
| `--cal-data-path` (`0x7ea72e7`) | *"path to store the voice card calibration data database"* | Redirects the cal DB. |
| `--example-data` (`0x7ea730e`) | *"Populate a seperate DB with example data and use it"* | |
| `--enable-tests`/`--disable-tests` (`0x7ea72f7`/`0x7ea731d`) | force the internal unit-test suite on/off | |
| `--enable-feature=`/`--disable-feature=` (`0x7ea732d`/`0x7ea733f`) | runtime feature flags | flag names not enumerable from a table |
| `--enable-osc-sec` (`0x7ea755a`) | *"Send all sound engine messages through the old osc protocol"* | selects the legacy OSC transport |
| `--upside-down-ui` (`0x7ea758b`), `--touch-to-vco` (`0x7ea759c`), `--always-on-top` (`0x7ea75ab`) | UI toggles | |
| `--midi-in=`/`--midi-out=` (`0x7ea74a6`/`0x7ea74b1`), `--host-efx=`,`--host-panelinput=`,`--host-response=`, nine `--port-*` overrides, seven `--log-*` flags | routing/logging overrides | full observability + re-routing surface |

(The `vxtune --api` / `lasfwu --dry-run` and the Qt kdialog `--getopenfilename` clusters are
args to *child* processes, not frontend options — correctly excluded.)

### 3.2 OSC surface vs. las-sc

Namespaces **shared with las-sc** (the frontend drives these on the engine): `/p`, `/cal`,
`/a`, `/mix`, `/hw`, `/info`, `/fx*`. Namespaces **unique to the frontend** (UI/routing):
`/meta` (preset-browser metadata: `name,comment,mood,group,category,type…`), `/package` (FX
content packages), `/version`, `/p/panel_focus`, `/r` (OSC-tree responses), `/m` (`/m/settings`,
`/m/xyz`), `/therm`, `/testosc`, **`/mo`** (MIDI-out routing: `/mo/din0` `0x7ea56f9`, `/mo/usb0`
`0x7ea5702`), `/override1`,`/override2`. Two transport paths are stated in-binary:
`0x7ea7755` *"Synth parameters are sent over OSC through the Sound Engine Controller"* vs.
`0x7ea779c` *"…over xOSC directly to the Voice Controller"* — i.e. the frontend can talk to
the VC either **through `las-sc`** or **directly** (`--enable-osc-sec` selects the legacy
direct path). `--host-*` meanings (verbatim, usage block `0x7ea5d10`): paneloutput = *"panel
output messages"*, oleds = *"OLED messages"*, performance = *"performance messages"*,
systemclock = *"system clock messages"*, vc = *"VC messages"*, panelinput/response/efx as named.
Default endpoints seen as literals: `203.0.113.2:7770` (VC, `0x7e73fb3`), `localhost:7775` and
`localhost:9300` (las-sc, `0xa3e091`/`0xa3e0a3`).

### 3.3 Hidden / service screens (present in binary, not on the normal panel)

The frontend carries a **screen-router table** (`0x7ea3fe8`–`0x7ea43a6`) and ~120 `*Panel`
QMetaObject class names. Service/factory/diagnostic screens with no normal menu path:

- **`HardwareTestPanel`** (`0x7e695c0`, `--test-fixture`) — factory test sequence; sub-tests
  include `"BOOTLOADER"` (`0x7e6965f`), `"OSCILLATOR TUNING"`, VCA/filter, `runAllTests`,
  `SAVE LOG`.
- **Embedded JavaScript factory-test scripts** (`0x7f53d51`+): real JS compiled in —
  `"// Verify the LHC LEDS"`, `Display.drawText("Press a button and verify…")`,
  `Panel.monitor("Glide Amount", function(v){…})`, `"Visually inspect the B.U.T."` (Board
  Under Test). Driven by `ScriptPanel` + `--script=`.
- **`SerialMacWritePanel`** (`0x7e7d5e8`) — factory provisioning: `"SERIAL NUMBER AND MAC
  ADDRESS"`, `"SCAN BARCODE ON SERIAL LABEL"`, `"OVERWRITE SERIAL NUMBER AND MAC ADDRESS?"`.
- **`UpdateFirmwarePanel`** (`0x7e95ba4`) and **`FormatUSBDrivePanel`** (`0x7e68468`).
- **Calibration/tuning suite** (~20 panels): `SystemCalibrationPanel`,
  `VoiceCardCalibrationPanel`, `FrontPanel{High,Mid,Low}CalibrationPanel`,
  `CVIn/CVOut/PedalIn/MainOut/HeadphoneOut/NoiseSource/LHC/FanCalibrationPanel`,
  `OscillatorTuning/Stability/MonitorPanel`, `MasterTuningPanel`, class `FactoryCalSetterOperation`.
- **`DisplayCoreTempPanel`** — reads `/sys/class/thermal/thermal_zone0/temp` (diagnostic).
- **`SlotMachinePanel`** (`0x7e823c8`, route `slotMachine`, asset `slotmachine.png`) — an
  apparent **easter-egg** slot-machine screen (INFERRED: dedicated art, no normal menu path).

**Negative result (important):** there is **no keyword/PIN-gated "service mode."** Searches for
`service menu, factory menu, diagnostic, engineer, developer mode, burn-in, secret, unlock,
kiosk, demo, test mode, experimental, hidden` matched only an embedded English word-list, not
feature code. Service capability is delivered purely as the panels above, most reached via
`--test-fixture` or a settings-navigation path, not a secret code.

### 3.4 Update / media flow (`/media/thumbdrive`)

`UpdateFirmwarePanel` scans the USB path (`"Looking for firmware updates in "` `0x7ea76b9`,
`"CHECKING USB FOR NEW FIRMWARE"`, `"Searching firmware at "`), and on confirm launches
**`/usr/bin/lasfwu <file>`** (with `--dry-run` if `--firmware-dry-run`; `--firmware-path=`
overrides the search dir) — so the **frontend delegates the actual flashing to `lasfwu`**, a
separate binary not in this capture set. UI text: `"DON'T POWER OFF THE INSTRUMENT WHILE THE
UPDATE IS IN PROCESS"`, `"UPDATING VOICE CONTROLLER FIRMWARE…"`, `"UPDATING VOICE CARD
FIRMWARE…"`, `"POWER-CYCLE YOUR SYNTHESIZER…"`. The USB path is also used for preset DB
import/export (`MOOG ONE.db`, `MOOG ONE EXAMPLES.db`) and cal-DB export.

**Signature/checksum — NEGATIVE RESULT:** searched the frontend for `signature/.sig/sha256/
sha1/md5/checksum/verify/license/.key/manifest/.pkg/.tar/.zip` in an update context — **none**.
The only `verify` hits are the JS test scripts; `package` hits are FX *content* packages, not
update bundles. **INFERRED:** `las-frontend` performs no cryptographic or checksum validation
of firmware itself — it locates a file and hands it to `lasfwu`. Any authenticity/integrity
check lives in `lasfwu` (out of scope) or is absent. Worth flagging to the owner.

---

## 4. The watchdog

`las-watchdog` (15 KB, fully disassembled — small enough to read in whole). Started by
`S99final` **one second after** `las-sc` posts `/var/las-sc.cookie`, as:
`las-watchdog -t=10000 > /var/log/las-watchdog.log 2>&1 &`.

**Argument parsing (READ, `main` @ VMA 0x12958):** the loop walks every `argv[i]` and tests
its **first byte** against `'t'` and `'v'`, taking the value from the *following* token. A
`'t'` value is stored at `[fp,#-8]` (logged `"Poll time of %d"`, default **1,000,000** =
`0xF4240` @ 0x12988) and is carried as the integer payload/nonce in the `/ping` and
`/v/voices` probes; a `'v'` value is the **expected voice count** at `[fp,#-0x18]` (logged
`"Expecting %d voices"`, default **8** @ 0x12994). A one-second `usleep(1000000)` runs at
startup (0x1297c). **Observation (INFERRED):** because the match is on a bare leading
`t`/`v`, the `-t=10000` string `S99final` passes (first byte `'-'`) does not fit that shape,
so the defaults very likely stand — poll nonce 1,000,000, **expecting 8 voices on a 16-voice
instrument** (the voice-ping loop runs `i` up to `count/2`, 0x1293c). This is not a fault by
itself but explains why the watchdog is lenient about the upper voice cards.

### 4.1 What it monitors (READ, disassembly of `main` @ 0x12958 and helpers)

Each cycle, in order:

1. **Process liveness** via `system("… pidof X …")` (`0x12508`–`0x1263c`):
   `las-frontend`, `las-sc`, `sclang`, `scsynth`. Any `pidof` returning non-zero logs
   `"<X> IS DOWN!!"` and calls the **recovery routine** `0x12498`.
2. **VC liveness** — sends OSC `/ping` to the controller at 203.0.113.2 and to each voice
   `/vx/<n>/ping` (`checkVoices` @ 0x127bc). Expected voice count is the `v` arg
   (default **8**, `[fp,#-0x18]`; logged `"Expecting %d voices"`). Replies:
   - controller silent → `"!!!VC IS DOWN!!!"` → **XMOS recovery** (`vcRecover` @ 0x12644).
   - controller up but a card silent → `"VC IS STILL UP BUT A VOICE IS DOWN"` (logged only).
3. **XMOS/network reachability** (`vcRecover` @ 0x12644): pings 203.0.113.2 ten times; if
   >9 failures → `"-->!!SYS XMOS is down!!!"`.

Healthy pass logs `"successful check up..."` (`0x33dc`).

### 4.2 What it does on failure (READ — these are the exact embedded scripts, `system()`)

The **recovery routine** (`0x12498`) runs three shell scripts back-to-back:

```sh
# 1. bounce the sound engine + GUI
/etc/init.d/S42sc stop ; killall scsynth sclang screen ; /etc/init.d/S43gui stop ; killall X ; sleep 2
# 2. restart the sound engine
/etc/init.d/S42sc stop ; killall scsynth sclang screen ; /etc/init.d/S42sc start &
# 3. restart the GUI stack
/etc/init.d/S43gui stop ; killall X ; /etc/init.d/S12splash start ; /etc/init.d/S43gui start & ; sleep 5 ; killall las-dwm ; DISPLAY=:0 las-dwm &
```
Then it **blocks until `/var/las-sc.cookie` reappears** (polling `access()` every 1 s, removing
the cookie once seen) before returning — i.e. it waits for `las-sc` to come back up.

The **XMOS recovery** (`vcRecover`, on VC-down) additionally runs:
```sh
config-las-spi som ; sleep 1 ; config-las-spi xmos ; sleep 1     # power-cycle the XMOS/VC
kill -9 `fuser 9666/udp`                                         # drop & re-open its own sockets
```
A `sendto` failure on the ping socket triggers a lighter "cycle sockets":
`kill -9 \`fuser 9799/udp\`` then re-init (`0x122e8`).

### 4.3 Can it fire accidentally? (INFERRED — this is what the owner needs)

**Yes, and this is the mechanism behind "the instrument resets itself."** The watchdog treats
*any* of these as a fault and reacts by **killing and restarting the whole audio+GUI stack**:

- `las-sc`, `sclang`, `scsynth`, or `las-frontend` momentarily missing a `pidof` — including
  the transient window while **you** stop/restart one of them by hand for probing. Stopping
  `las-sc` to poke at it will make the watchdog tear down and rebuild everything within one
  poll cycle.
- The voice controller not answering `/ping` within the cycle — including if its UDP port is
  busy because something else (a sweep tool) is hammering 7770, or if the USB-gadget link
  hiccups. A VC miss escalates to a **hardware XMOS power-cycle** (`config-las-spi som/xmos`).
- Its own send socket erroring (`sendto failed`) → socket cycle.

There is **no debounce**: a single failed cycle triggers recovery. The `sleep 3` in `S42sc
start` and the cookie-wait give it some slack, but any tool that (a) restarts a monitored
process, (b) saturates the VC bus, or (c) disturbs `usbint` will provoke a full restart, and a
VC miss provokes a hardware power-cycle of the voice engine. **Mitigation:** `killall
las-watchdog` before doing invasive work (this is exactly what `S99final` itself does when the
dev-key is present — see §5).

---

## 5. Danger list — writes flash / calibration / hardware / persistent state

Ordered by blast radius. **Everything here is READ (binary/script) unless noted.** The owner
has already locked the instrument once by running an unknown routine; the top three are the
routines that can do that.

### D1 — Voice-controller (XMOS) firmware flash via `flashrom`  *(bricks the VC)*
`las-sc` reflashes the LAS voice controller over SPI at startup when a `--vcfw` file is given
and its version differs from `--vcfv`. Command (strings `0x1e5910`,`0x1e5936`,`0x1e5975`):
```
flashrom -l /usr/share/xmosfw/las_layout -i firmware -w <vcfw> -p linux_spi:dev=/dev/spidev0.0
```
Preceded by `config-las-spi som`/`config-las-spi xmos` power-cycling (`0x131e8`, and
`vxfw-lib.scm` CONFIG-LAS-SPI). **The stock boot line passes `--vcfw=…app_las_v2.1.2.bin
--vcfv=33620735`**, so this path is armed on every boot and only skipped because the installed
version matches. Danger: a wrong/corrupt `--vcfw`, a mismatched `--vcfv`, `--cli` mode
(`"updates firmware, then exits"`), or an interrupted flash writes bad firmware to the VC.
Log strings: `"Sound engine controller is updating VC firmware."`, `"Update Failed (Not
Enabling XMOS)"`, `"- Flashing VC Anyway"` (it will flash even on a network error).

### D2 — Voice-card firmware push over OSC  *(bricks voice cards)*
`las-sc`/`vxfw-lib.scm` streams `app_vx_10M_*.bin` to each of the 16 voice cards **over the
voice bus** (not SPI): `/fw/start` (begin), repeated `/fw/data` blocks (`block-size`,
`send-block`), `/fw/version` (verify). Strings `0x2321b9 /fw/data`, `0x23220f /fw/start`,
`0x2321cc "sent firmware to card "`, `0x2321e8 "cannot start fw download"`,
`0x2322a3 "invalid firmware file"`. Armed by `--vxfw=…app_vx_10M_v2.1.0.bin`; `--force-vx-update`
flashes **even if versions match** (`0x1e5eab "Update VX firmware even if versions match."`).
Because it is plain OSC to 7770, a hand-sent `/fw/start` + `/fw/data` to the VC is a
plausible way to corrupt a card — this is the "unproven whether a blob at a setter is inert"
worry from `vx-api-map.md`, made concrete.

### D3 — Calibration & tuning writes  *(needs re-cal to undo; can silence/ detune voices)*
- `/cal/*` (62 leaves): per-oscillator/filter/noise **cal constants** (`o1/{h,l,x}`,
  `ladf/ladr`, `svf1f/svf2f`, `biasfa/biasfb`, `noisecw/noiseccw`, `gsvf`, `mainl/mainr`, …).
  Writing these changes persistent voice calibration.
- `las-sc` shells out to the tuning writer (strings `0x1e52e9`, `0x1e5352`, `0x1e5395`):
  ```
  /usr/bin/vxtune write -c vc -f <file> --nvoices 1 -q -v          # write tuning+cal
  /usr/bin/vxtune write … --tune -v                                 # tuning only
  /usr/bin/vxtune write … --cal  -v                                 # cal only
  ```
  and drives `/load_cal` / `/load_tuning` (`0x1e53e5`,`0x1e53f3`) to make voices reload them.
- Persistent stores (from `vx-api-map.md`, backed up in `captures/backup/`): `/var/cal/vxcal.db`
  (241 KB) and `/var/tuning.vxtune`. `--vxdb=/var/tuning.vxtune` is on the boot line.
- **Owner note:** the auto-memory entry "never run unknown Moog scripts for --help" is exactly
  this class — the bash launch scripts and `vxtune`/`config-las-spi` ignore `--help` and run
  their real action (calibration/reset). `config-las-spi som`/`xmos` **power-cycles hardware**.

### D4 — Hardware power-cycle of the XMOS/VC
`config-las-spi som` then `config-las-spi xmos` (via `las-sc` `set-power-state`/`can-power-cycle?`
in `sc.scm`, and directly in `las-watchdog`'s XMOS-recovery). Cuts and restores power to the
voice engine. Invoked automatically by the watchdog on a VC-down; invoked at boot by
`S25xmosfw` (`config-las-spi xmos`). Not destructive by itself but interrupts audio and, if it
races a flash, is catastrophic.

### D5 — The watchdog's own restart cascade
See §4.2. `killall X / scsynth / sclang / las-dwm`, `S42sc stop/start`, `S43gui stop/start`.
Not flash, but it will **kill your session and any in-flight probe** on a single missed poll,
and escalate to D4 on a VC miss. Neutralise with `killall las-watchdog` before invasive work.

### D6 — Filesystem / persistent-state writes at boot (`S14fs`, run every boot)
`S14fs` **destroys** `/mnt/fwu/*`, removes all `*.cookie`, deletes old logs, and
`mv /var/log/las-watchdog.log …log.0`. `S99final` **remounts `/` read-only** at the end of a
normal boot (`mount -f -o remount,ro /`) *unless the dev-key is present*. Persistent partitions:
`/var` (mmcblk2p6), `/mnt/fwu` (p7, firmware staging), `/var/lib/sys` (p4, vfat).

### D7 — Test oscillator / direct hardware toggles
`/testosc/freq`, `/testosc/dac/{2,3}`, `/cal/testosch/*` inject a raw signal into the analog
path; `/hw/mute`, `/hw/hpf`, `/hw/autor` toggle hardware. `/hw/mute` answers live; `/hw/hpf`,
`/hw/autor` 404 on this firmware (READ live, prior brief). Loud-output / unexpected-routing
risk, not persistent.

### D8 — The developer key (persistent-state *enabler*)  *(READ, `S50dropbear`,`S99final`)*
A USB file `/media/thumbdrive/k` whose first bytes hexdump to **`23051934`** unlocks two
things: `S50dropbear` starts **SSH** (root), and `S99final` **skips the read-only remount and
skips killing the watchdog kill** — actually it *does* `killall las-watchdog` and exits early,
leaving `/` **read-write**, the xterms and `las-dwm` alive, and the box in a developer state.
So the key is what makes flash/cal writes *stick* across the session. If this key is installed,
the instrument boots into a mutable, SSH-open state — worth knowing it is present (dropbear is
running in the snapshot, so the key **is** installed on this unit).

### D9 — `las-frontend` factory/service entry points  *(READ, from the 145 MB binary, §3)*
- **`--test-fixture`** boots straight into `HardwareTestPanel` — the CM hardware-test harness
  (`"BOOTLOADER"`, `"OSCILLATOR TUNING"`, VCA/filter tests). Exercises hardware directly.
- **`--script=<path>`** runs **arbitrary JavaScript** through the embedded JUCE JS engine,
  with `Panel`/`Display` objects that drive hardware (the factory test scripts do exactly this).
  A hostile or wrong `.js` on the USB stick is a code-exec/hardware-poke vector.
- **`SerialMacWritePanel`** overwrites the unit's **serial number and MAC** (`"OVERWRITE SERIAL
  NUMBER AND MAC ADDRESS?"`) — persistent identity change.
- **`FormatUSBDrivePanel`** — `"THIS WILL ERASE ALL DATA ON THE USB STORAGE DEVICE."`
- **Calibration DB reset** — `"DATABASE CANNOT BE RECOVERED AFTER RESET."` (`0x7e970f6`).
- The cal-transfer routine shells `config-las-spi` + `las-sc --cli` and, like `vxtune write`,
  **kills the watchdog first** (frontend `system()` sites: `killall las-watchdog` at code VMAs
  `0x795eac`/`0x7a4c24`, then `/usr/bin/vxtune write -c vc -f /var/tuning.vxtune` at `0x795eb4`).
  This is the exact "watchdog dead + voice-card write in flight" wedge behind the lock-up.

### D10 — Firmware flashing is delegated to `/usr/bin/lasfwu` with **no signature check**
`las-frontend`'s `UpdateFirmwarePanel` only *locates* a firmware file on the USB stick and
hands it to `lasfwu <file>` (`--dry-run` optional; `--firmware-path=` overrides the dir). The
frontend performs **no cryptographic/checksum validation** (negative result, §3.4) — integrity
enforcement, if any, lives in `lasfwu`, which is not in this capture set. Worth confirming.

### Danger quick-reference

| Item | Trigger | Persistent? | Reversible |
|---|---|---|---|
| D1 VC flash (`flashrom`) | `las-sc --vcfw`+version mismatch / `--cli` | **yes (flash)** | reflash good image |
| D2 voice-card flash (`/fw/*`) | `las-sc --vxfw` / `--force-vx-update`; raw OSC to :7770 | **yes (flash)** | reflash |
| D3 cal/tune write (`vxtune`,`/cal/*`,`/load_*`) | OSC set / `vxtune write` | **yes** | restore `captures/backup/` |
| D4 XMOS power-cycle | `config-las-spi som/xmos`; watchdog | no | audio glitch |
| D5 watchdog cascade | any monitored proc down / VC ping miss | no | self-heals |
| D6 boot wipes | every boot (`S14fs`) | erases fwu/logs | n/a |
| D8 dev-key | `/media/thumbdrive/k` == 23051934 | enables RW+SSH | remove key |
| D9 frontend service screens | `--test-fixture`, `--script=`, SerialMac/FormatUSB/cal-reset panels | some (serial/MAC/cal-DB) | varies |
| D10 unsigned firmware path | `lasfwu` via UpdateFirmwarePanel / USB | **yes (flash)** | reflash |

**Safe-probing rule of thumb (INFERRED):** `killall las-watchdog` first; never send to `/fw/*`,
`/cal/*`, `/load_cal`, `/load_tuning`, `/testosc/*`; never launch `las-sc` with `--vcfw/--vxfw/
--cli/--force-vx-update`; treat any bare Moog script (`config-las-spi`, `vxtune`, `launch-*`)
as executing its action regardless of args.

---

## Appendix A — `las-sc` full command-line (READ, strings `0x1e5b66`–`0x1e638b`)

| Flag | Short | Help text (verbatim) | In boot line? |
|---|---|---|---|
| `--target` | `-t` | Xmos Target address | yes (`-t vc`) |
| `--listen` | `-l` | Listen address (default localhost:9300) | yes |
| (efx addr) | `-f` | EFX Server address (optional) | yes (`-f localhost:7775`) |
| `--vxfw` | | Voice card firmware file. If not given, voice cards are not checked or updated. | yes |
| `--vxdb` | | Voice Card Tuning Data | yes |
| `--vcfw` | | Voice control firmware file. If not given, VC is not checked or updated. | yes |
| `--vcfv` | | Expected voice control firmware version. | yes |
| `--panel-state` | | Panel state query address. | yes |
| `--expr-syms` | | File containing symbols for use in expressions. | yes |
| `--temp` | | Enable SOM temperature polling. | yes |
| `--quiet` | `-q` | Keep silent during operation | yes |
| `--mode` | | Put VC in given mode at startup | no |
| `--force-vx-update` | | **Update VX firmware even if versions match.** | **no (danger)** |
| `--cli` | | **Command-line interface mode - updates firmware, then exits without launching fx.** | **no (danger)** |
| `--manual-fx` | | fx booted manually, but las-sc should still connect | no |
| `--ofs-cache` | | Offset cache file (periodic VX offset gather/restore) | no |
| `--mod` | | Flag for VX HW Mod. | no |
| `--version` | | Display version information and exit. | no |
| `--help` | | Display usage text | no |

The **not-in-boot-line** flags are the interesting surface: `--cli` and `--force-vx-update`
turn `las-sc` into a firmware flasher; `--mode` selects a VC operating mode; `--ofs-cache`
periodically reads/writes per-voice offset data; `--mod` toggles a hardware-mod code path.

## Appendix B — smaller binaries

- **`las-fb-config <fb> [0,1] [alpha0-255]`** — sets framebuffer overlay alpha via `ioctl` on
  `/dev/fb%s` (default `/dev/fb1`). Used by splash/transition (`las-fb-config 1 0`). Harmless.
- **`las-frontpanel-poll`** — a bare OSC client (same decoder as the watchdog) that talks to
  `203.0.113.2` (VC). Polls the front panel over the voice bus. Harmless read utility.
- **`las-dwm`** — dwm-derived X11 WM (libX11). Imports `system`,`fork`,`waitpid`,`recvfrom`,
  `sendto`: it both spawns processes (dwm key-binding/`system()` spawn) and listens on UDP,
  so it can be commanded to launch programs. Not a flash/cal risk, but it is a code-exec
  surface if its UDP command port is reachable. (Command port not pinned; INFERRED among the
  ephemeral 0.0.0.0 UDP binds.)

## Appendix C — what could NOT be determined (negative results)

- Full set of legal `/mode` values — only `normal` appears as a literal in `las-sc`.
- Whether sending a zero-arg OSC message to a `/p/*` or `/cal/*` setter reads vs. writes —
  unproven; `vxping` sends a blob, and blob-at-setter behaviour is untested (per `vx-api-map.md`).
- Exact purpose of `las-sc` port **9600** and the `9999` send target — inferred, not confirmed.
- `las-dwm`'s UDP command port and message format — not extracted.
- Meaning of a handful of `/p` singletons (`/p/c`, `/p/gc`, `/p/eg_g`, `/p/fafb`) — named but
  semantics not certain.
