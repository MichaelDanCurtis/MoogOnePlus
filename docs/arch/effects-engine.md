# Moog One effects engine — state machine, slot model, and failure modes

Reverse-engineering notes derived **only** from the harvested SuperCollider source in
`captures/arch-harvest/`. No instrument was contacted.

## Sources and conventions

| File | Role |
| --- | --- |
| `captures/arch-harvest/efx_server.scd` (1087 lines) | The effects state machine and OSC API. Primary target. |
| `captures/arch-harvest/init_sc_1.scd` (117 lines) | **The live boot script.** Referenced by `launch-sc-1`, which `las-sc` spawns under `screen`. |
| `captures/arch-harvest/synthdefs.scd` (3875 lines) | SynthDef *source*. Not executed on the device — the device loads pre-compiled `.scsyndef` from `/usr/share/las-fx/synthdefs/`. Use `synthdef-names.txt` for what actually exists at runtime. |
| `captures/arch-harvest/init.scd`, `init_sn.scd`, `init_sc_2.scd` | Dead variants (jackd / supernova / two-server). Not loaded by `launch-sc-1`. Useful only as design archaeology. |
| `captures/arch-harvest/init.d/S42sc`, `launch-sc-1`, `las-watchdog`, `las-sc` | Process supervision. Needed to explain the restart bug. |

Throughout:

- **READ** = literally present in the harvested source, with a line citation.
- **INFERRED** = a conclusion from SuperCollider/scsynth semantics or from cross-file
  consistency. Flagged inline.
- Line numbers are 1-based into the harvested file named.

---

## 0. Executive summary of corrections to the prior model

Your existing four bullets are broadly right, but three need adjustment:

1. **"Slots 0-2 are category `\ins`, slots 3-4 are bus/master"** — half right. What is
   *hard-wired* per slot index is **group membership** (`init_sc_1.scd:53-59`), not
   category. `~initUnit` sets `category = \ins` for **all five** slots
   (`efx_server.scd:310`), and the category is thereafter overwritten from the incoming
   message field `msg[2]` (`efx_server.scd:515`). So category is *per-message state
   supplied by the controller*, and at cold boot slots 3 and 4 are also `\ins` until the
   first effect-change message arrives. This matters: the eventide code path is gated on
   category, not on slot index.

2. **"All ten Eventide instances are created at boot then `.run(false)`"** — correct, and
   the reason is confirmed: every `et_*` SynthDef uses `EnvGen ... doneAction: 1` (pause)
   while every other effect uses `doneAction: 2` (free) — `synthdefs.scd:3407, 3492,
   3576, 3657, 3735, 3817` vs. 26 occurrences of `doneAction: 2`. The `doneAction: 1` is
   the load-bearing invariant, not just the `.run(false)`.

3. **"`~initEffect` swaps one into a slot by MOVING the node"** — correct, but
   `~initEffect` does **not** un-pause it. `run(true)` happens later and elsewhere
   (`efx_server.scd:380` and `:620`), inside a routine that can fail to run at all. See
   §6.4.

Two things you did not have:

- **The Eventide reverbs are not restricted to slots 3-4 by any check in this file.** The
  restriction is emergent. See §2.4.
- **`~efxServer[\state]` does not exist.** `init_sc_1.scd:43` calls
  `~efxServer[\state].value` — a no-op, since `Environment.at(\state)` is nil and
  `Object:value` returns the receiver. The real state machine is `~fxStateThread`, which
  self-starts at file-load time (`efx_server.scd:1033-1081`, `.play` on line 1081).
  Likewise `~state` in the `/fx/run` handler (`efx_server.scd:773, 775`) is never bound
  anywhere in the codebase — `/fx/run` is dead. (Verified by grep across `efx_server.scd`;
  only `~statereturn`, an unrelated variable, matches.)

---

## 1. Boot order and the live object graph

From `init_sc_1.scd`, in order:

| Line | Action |
| --- | --- |
| 7-18 | `Server.new(\server_main, 127.0.0.1:57110)`; blockSize 128, hwBufSize 128, 8 out / 9 in, 128 wire bufs, memSize 100000, latency 0.05, SR 48000. |
| 21 | `waitForBoot({ ... })` — everything below runs inside a Routine, so `.sync` is legal. |
| 23-24 | `LADSPA_PATH=/usr/share/las-fx/ladspa` (via `systemCmd` — see note below), `SynthDef.synthDefDir`. |
| 36-38 | `loadDirectory` of pre-compiled synthdefs; `SynthDescLib.global.read`; `sync`. |
| 40 | `"efx_server.scd".loadRelative` — **this both registers every OSCdef and starts `~fxStateThread` running.** |
| 43 | `~efxServer[\state].value` — no-op (see §0). |
| 45-48 | `~efxGroups = []`; `~insertGroup = Group.new`; `~busGroup = Group.new`. |
| 51-60 | The five-slot loop: `initUnit(i)`, then a per-slot `Group` (in `~insertGroup` for `i<3`, `~busGroup` otherwise), then `initEffect(\none_1, i)`. |
| 65-66 | `~dspInputWrapper = Synth(\inputRouter, ~busGroup, addToHead)`; `~dspOutputWrapper = Synth(\outputRouter, ~busGroup, addToTail)`. |
| 68 | `~busGroup.moveAfter(~insertGroup)` — redundant, it already is. |
| 73-104 | `~eventideGroup = Group.after(~busGroup)`; ten `et_*` Synths created and immediately `.run(false)`. |
| 109 | **`stopAliveThread`** — sclang stops polling scsynth's status forever. |
| 111 | writes `/var/local/tmp/scsynth.cookie`, which unblocks `launch-sc-1`'s `assign-pids`. |

Resulting node tree (READ from the above plus the `addAction`s in `~initEffect`):

```
RootNode (0)
└── default group (1)
    ├── ~insertGroup
    │   ├── ~efxGroups[0]        slot 0  (insert 1)
    │   ├── ~efxGroups[1]        slot 1  (insert 2)
    │   └── ~efxGroups[2]        slot 2  (insert 3)
    ├── ~busGroup
    │   ├── ~dspInputWrapper     Synth(\inputRouter)      <- head
    │   ├── ~efxGroups[3]        slot 3  (master / bus 1)
    │   ├── ~efxGroups[4]        slot 4  (master / bus 2)
    │   └── ~dspOutputWrapper    Synth(\outputRouter)     <- tail
    └── ~eventideGroup           parking lot, 10 paused LADSPA synths
```

Notes:

- `~efxGroups[3]` and `[4]` are created (`init_sc_1.scd:57`) *before* the two router
  synths (`:65-66`). `addToHead`/`addToTail` then place the routers correctly around them.
  `~initEffect` re-asserts this with `~dspOutputWrapper.moveToTail(~busGroup)` on every
  bus-slot change (`efx_server.scd:269`).
- `~eventideGroup` sits **after** `~busGroup`, i.e. downstream of `~outputRouter`. A parked
  eventide that were ever accidentally un-paused would run after the output router with
  whatever `inBus`/`outBus` it last held. On a *never-adopted* eventide those default to
  `0`/`0` (`synthdefs.scd:3388` region: `inBus = 0, outBus=0`), i.e. it would read and
  write hardware output bus 0. **INFERRED consequence: instant feedback on the main
  output.** Nothing in the code can cause this on its own, but it makes `run(true)` on
  anything in `~eventideGroup` a dangerous manual command.
- `("export LADSPA_PATH=...").systemCmd` (`init_sc_1.scd:23`) spawns a subshell, sets the
  variable there and exits. **It cannot affect sclang's or scsynth's environment.**
  scsynth must therefore be finding the plugins some other way (a compiled-in default, or
  an env var set by `launch-sc-1`/`las-sc`). Not resolvable from this harvest — flagged
  as an open question, not a bug to "fix".

### 1.1 Discrepancy between the harvested boot script and the running server

`runtime-state.txt` shows the live process as:

```
scsynth -u 57110 -a 129 -i 9 -b 1026 -z 256 -Z 256 -m 100000 -w 128 -S 48000 -R 0 -C 0 -l 1
```

`-a 129` is consistent with 8 out + 9 in + 112 private (SC's default
`numPrivateAudioBusChannels`), `-i 9`, `-w 128`, `-m 100000`, `-S 48000` all match
`init_sc_1.scd`. But **`-z 256 -Z 256` contradicts `init_sc_1.scd:9-10`, which asks for
128/128.** The ALSA side (`/proc/asound`, `period_size: 256`) agrees with the *running*
value. So either the on-device `init_sc_1.scd` differs from the harvested copy (its mtime,
"Sep 8 2026", is also anomalous relative to the rest of the harvest), or something
overrides the options. **Treat block size as 256 when reasoning about the live machine,
and re-harvest `init_sc_1.scd` before trusting it.**

Bus layout follows from `-a 129 -i 9` (out=8): busses **0-7 = hardware out**, **8-16 =
hardware in**, **17-128 = private**. Every internal bus the routers touch (50-63) is
private. INFERRED but firmly.

---

## 2. The slot model

### 2.1 What `~initUnit` establishes per slot (`efx_server.scd:289-317`)

| Key | Value at init | Line |
| --- | --- | --- |
| `fxN_en_prev` | `1` | 294 |
| `fxN_prev_effect` | `0` (Integer, not a Symbol) | 295 |
| `fxN` | `\none_1` — the *requested* effect name | 298 |
| `efx_active` | `unitNum` appended | 300 |
| `fxN_inBus` | `"1,2"` — **a String** | 304 |
| `fxN_outBus` | `"1"` — a String | 305 |
| `fxN_ctlInBus` / `fxN_ctlOutBus` | `"2"` / `"3"` — Strings, never read anywhere | 306-307 |
| `fxN_bus1` / `fxN_bus2` | `"100"` / `"101"` — Strings, never read anywhere | 308-309 |
| `fxN_category` | `\ins` — **for all five slots** | 310 |
| `fxN_send1_bus` / `fxN_send2_bus` | `102` / `103` — never read anywhere | 311-312 |
| `fxN_g-in` / `fxN_g-out` | `1` / `1` | 313-314 |
| `fxN_change_needed` | **`true`** | 317 |

Then 20 OSCdefs are registered for that slot (see §3).

`~efxServer[\efx_active]` is `List.new(1)` (`efx_server.scd:184`) and is grown by
`.add(unitNum, ~efxServer[\efx_i].value)` (`:300`). `List:add` takes one argument; the
second is superfluous. The result is the identity list `[0,1,2,3,4]`, so every
`~efxServer[\efx_active].at(i)` in the file (lines 359, 642, 1061, 1066, 1070) is an
identity map. It is dead indirection **that would become a real bug if the list ever
stopped being the identity** — see §6.7.

### 2.2 Per-slot facts

| Slot | Group at boot | Category at boot | Category thereafter | Router return channel | `insert_N_g` / `timbre_N_dry` exist? |
| --- | --- | --- | --- | --- | --- |
| 0 | `~efxGroups[0]` in `~insertGroup` | `\ins` | from `msg[2]` | `insert1` = busses **50, 51** | yes (`insert_1_g`, `timbre_1_dry`, `dry_dir1_r`, `synth1_in_ch`) |
| 1 | `~efxGroups[1]` in `~insertGroup` | `\ins` | from `msg[2]` | `insert2` = busses **52, 53** | yes (`_2`) |
| 2 | `~efxGroups[2]` in `~insertGroup` | `\ins` | from `msg[2]` | `insert3` = busses **54, 55** | yes (`_3`) |
| 3 | `~efxGroups[3]` in `~busGroup` | `\ins` (!) | from `msg[2]` | `master1` = busses **60, 61** | **no** — `insert_4_g`, `timbre_4_dry`, `dry_dir4_r`… mostly absent |
| 4 | `~efxGroups[4]` in `~busGroup` | `\ins` (!) | from `msg[2]` | `master2` = busses **62, 63** | **no** |

Group membership is READ from `init_sc_1.scd:53-59`. Router channel numbers are READ from
`synthdefs.scd:294-296` (`inputRouter`: `In.ar([50,51])`, `[52,53]`, `[54,55]`) and
`synthdefs.scd:460-465` (`outputRouter`: same three plus `master1 = In.ar([60,61])`,
`master2 = In.ar([62,63])`).

The *frontend supplies* the bus numbers; `efx_server.scd` only transforms them:

- **Insert slots** (`msg[2] == "ins"`, `efx_server.scd:507-509`):
  `inBus := msg[3] + 8`. The `+8` converts a hardware input index to an absolute bus
  (numOutputBusChannels = 8). Same `+8` in the `/fxN/in` handler (`:813`).
- **Bus slots** (`efx_server.scd:511`): `inBus := [msg[3], msg[3]+1]` — **no `+8`.** These
  are already absolute private bus numbers.
- Both: `outBus := msg[4]` (`:514`), untransformed.

**This asymmetry is undocumented in the source and is a trap.** INFERRED from the router
constants, the controller must be sending: slot 0/1/2 `outBus` = 50 / 52 / 54; slot 3
`inBus`=56, `outBus`=60; slot 4 `inBus`=58, `outBus`=62. (`inputRouter` writes 56-59:
`synthdefs.scd:380-385`.)

### 2.3 Signal flow (READ from `inputRouter` / `outputRouter`)

```
hw in 2 ──► send1 ─┐ (noise gate: DetectSilence + Lag + clip)
hw in 3 ──► send2 ─┤
                   ├─► inputRouter (send1_r / send2_r / insert1_r..insert3_r matrices)
busses 50-55 ──────┘         │
  (insert returns)           ├─► bus 56,57  ──► slot 3 ──► bus 60,61 ─┐
                             └─► bus 58,59  ──► slot 4 ──► bus 62,63 ─┤
                                                                       │
   also: InFeedback.ar(60,61) * par_amount folded back into master2 ────┘  (parallel mode)

outputRouter reads 50-55 (inserts), 60-63 (masters), plus 3 analog dry taps
  (In.ar(synth1_in_ch .. synth3_in_ch), panned, scaled by timbre_N_dry * digDryGain)
  → main (StereoSpread) → hw out 7 / 0, inverted
  → sub  (StereoSpread) → hw out 2 / 1
  → aux1..aux4 (mono sums)→ hw out 5, 6, 3, 4
```

`/fx/bus-mode` (`efx_server.scd:132-142`) switches the send matrix:

- mode 0 (dual mono): `send1_r=[1,1,0,0]`, `send2_r=[0,0,1,1]` — send1 doubled into
  master1 L+R, send2 doubled into master2 L+R. Both masters see a mono source.
- mode 1 (stereo): `send1_r=[0,0,1,0]`, `send2_r=[0,0,0,1]` — **master1 receives nothing
  from the sends**; master2 receives a genuine stereo pair (send1→L, send2→R).

### 2.4 Why the Eventide reverbs are effectively confined to slots 3-4

There is **no explicit slot check anywhere in `efx_server.scd`**. The confinement is the
product of five separate mechanisms. Correcting your premise: it is emergent, not enforced,
and that is exactly why it is fragile.

1. **The eventide code path is gated on category, not on slot.** `~initEffect`
   (`efx_server.scd:236-271`) has two branches. The `\ins` branch is three lines
   (`:236-240`) and does nothing but `Synth(effect, target: ~efxGroups[unitNum],
   addAction: 'addToHead')`. Only the `else` branch (`:241-271`) knows about `~eventides`
   at all. **If a slot whose category is `\ins` were asked for `et_hall_1`, the code would
   instantiate a *second* live LADSPA node of that plugin while the first sits parked in
   `~eventideGroup` — and would then leak it, because the `\ins` branch never frees or
   parks anything.** That second node's only exit is `enable → 0 → doneAction 1 → pause`,
   i.e. it never leaves the graph. This is the single most dangerous latent path in the
   file.

2. **Only slots 3 and 4 are in `~busGroup`.** The bus branch ends with
   `~dspOutputWrapper.moveToTail(~busGroup)` (`:269`) to keep the output router last. That
   re-ordering only makes sense for a node inside `~busGroup`. An eventide moved into
   `~efxGroups[0..2]` would sit in `~insertGroup`, i.e. *upstream* of `inputRouter` —
   wrong topology for a reverb fed from the master sends.

3. **The routers only have two master return paths.** `outputRouter` exposes `master1_r`
   and `master2_r` and reads `[60,61]` / `[62,63]` (`synthdefs.scd:460-465`). There is no
   `master3_r`. Conversely there are only three insert returns (50-55). The five slots
   are 3 inserts + 2 masters at the DSP level, and that is fixed in the compiled synthdefs.

4. **The eventides are inherently stereo-in.** Every `et_*` does `In.ar(inBus, 2)`
   (`synthdefs.scd:3411`, `3494`, …) with a **scalar** `inBus` control. The insert branch
   sets `inBus` to a scalar hardware channel, so `In.ar(inBus,2)` would read that channel
   *and its neighbour* — i.e. a different voice's audio. Only the bus branch supplies a
   proper adjacent pair.

5. **Insert-category effects use the `_0`.. `_3` family; there is no `et_*_0`.**
   `synthdef-names.txt` shows every normal effect built in four variants `_0`.. `_3` and
   the eventides only as `_1` / `_2`.

**Correcting a likely misreading of the `_1`/`_2` suffix:** it is *not* "one per slot". It
is the input topology. `n==1` feeds the LADSPA plugin `input.sum * 0.45` (or `*0.5`) into
**both** plugin inputs — a mono sum; `n==2` feeds `input[0], input[1]` — true stereo
(`synthdefs.scd:3417` vs `:3419` for blackhole, `:3501` vs `:3503` for room, and the same pattern in
hall/plate/shimmer). That maps onto the `/fx/bus-mode` dual-mono/stereo switch, **not**
onto slot 3 vs slot 4. Consequence: in a given bus mode the controller will tend to pick
the *same* variant for both master slots — which trips the aliasing bug in §6.3.

`et_spring` is defined at `synthdefs.scd:3632-3698`, but the whole block is inside a
`/* ... */` comment (opened at `synthdefs.scd:3629`, closed at `:3700`), and it is absent
from `synthdef-names.txt`. The LADSPA library `eventide_spring.so` **is** present
(`table-and-ladspa-listing.txt`). So Spring is a shipped-but-unbuilt reverb. Requesting
`\et_spring` today would produce a client-side `Synth` object with an allocated node ID and
no server node (scsynth: "SynthDef not found"), after which every `.set` silently vanishes
and `~fxEnableCheckRoutine` spins forever (§6.2).

---

## 3. Every entry point — the effects API

All handlers live in `efx_server.scd` and listen on **UDP 7775**
(`thisProcess.openUDPPort(7775)`, line 3), which `netstat` shows bound to `0.0.0.0`.

### 3.1 Global handlers (registered once, at file load)

| Path | Line | Args | Effect |
| --- | --- | --- | --- |
| `/ping` | 9-13 | — | Replies `/ping` to sender. |
| `/fx/send1Gain` | 18-21 | float | `~dspInputWrapper.set(\send1Gain, v)` |
| `/fx/send2Gain` | 23-26 | float | `\send2Gain` |
| `/fx/send1Thresh` | 28-31 | float | `\send1Thresh` (DetectSilence threshold) |
| `/fx/send2Thresh` | 33-36 | float | `\send2Thresh` |
| `/fx/sendClampTime` | 38-41 | float | `\clampTime` (gate attack) |
| `/fx/sendRelaxTime` | 43-46 | float | `\relaxTime` (gate release) |
| `/fx/sendGainFactorMin` | 48-51 | float | `\gainFactorMin` (gate floor) |
| `/fx/start` | 55-90 | `1`/`0` | `1`: if `~fxStateThread` is **not** playing, `reset` + `play` it; then `kill -0 <scsynth pid>` and, **if that fails, `"init_sc_1.scd".loadRelative`** (line 71). `0`: `~fxStateThread.stop`. Note: when the thread *is* already playing, the whole body including the server check is skipped (line 62). |
| `/fx/state` | 93-127 | — | Replies `/fx/state` to the sender's port with `1` (thread alive), `0` (thread stopped/paused), or `-1` (scsynth dead per `kill -0`). |
| `/fx/bus-mode` | 132-142 | `0`/`1` | Sets `inputRouter`'s `mode` plus the `send1_r`/`send2_r` matrices — dual mono vs stereo (§2.3). |
| `/fx/hw-rev` | 147-163 | `0`/`1` | `outputRouter.digDryGain := 1.9` (old hw) or `0.9` (new hw). |
| `fx/spread` | 167-174 | float | `outputRouter.stereoSpread`. |
| `/fx/run` | 769-778 | bool | **Dead.** Calls `~state.play` / `~state.pause`; `~state` is never bound. Also registered five times under the same OSCdef key `fx_server_thread` (once per `initUnit` call), so only one survives. |

### 3.2 Per-slot handlers (registered five times by `~initUnit`, N = 0..4)

| Path | Line | Payload | Effect |
| --- | --- | --- | --- |
| **`/fxN`** | 322-653 | see §4.1 | **The effect-change / preset-recall message.** Full trace in §4. |
| `/fxN/en` | 657-694 | float | Bypass-by-gain. Sets `g_in := v`; and `g_out := v` for N>2, `g_out := v * fxN_g-out` for N<=2 (lines 666-671). **Guarded by `if(fxN_change_needed == false)`** — so enable messages arriving during a pending change are dropped for the synth but still stored in `fxN_en` / `fxN_en_prev` (687-688). Does **not** touch `\enable`. |
| `fxN/mix` | 698-705 | float | `fxN_effect.set(\mix, v)`; stores `fxN_mix`. |
| `fxN/g-in` | 709-716 | float | `fxN_effect.set(\g_in, v)`; stores. |
| `fxN/g-out` | 720-739 | float | Stores `fxN_g-out`; sets `outputRouter.insert_(N+1)_g` **and** `fxN_effect.set(\g_out, v)`. (The old `if(unitNum >= 3)` guard is commented out at 725/727.) |
| `/fxN/ctl` | 746-750 | float | `fxN_effect.set(\ctl, v)`; stores. |
| `/fxN/pan` | 754-765 | float | `fxN_effect.set(\pan, v)`; stores; **and** `outputRouter.dry_(N+1)_p := -1 * (1 + (2 * (v - 1)))`. |
| `fxN/wet` | 782-798 | float array | **No-op.** The only write is commented out (line 793). Debug print only. |
| `fxN/in` | 805-830 | int array | Each element `+ 8`; stores `fxN_inBus`; `fxN_effect.set(\inBus, arr)` — **twice** (818 unconditionally, 821 again inside a `change_needed == false` guard); also `outputRouter.set("synthN+1_in_ch", arr)`. |
| `fxN/out` | 836-860 | array of 6 | `outputRouter.insert(N+1)_r := arr` (main, sub, aux1-4) and `dry_dir(N+1)_r := arr[2..]` (the four aux toggles). Note `~efxServer` is **not** updated — line 847 is commented out. |
| `fxN/sends` | 866-886 | array | Stores `fxN_sends`; `inputRouter.insert(N+1)_r := arr`. |
| `fxN/par` | 892-913 | float | Stores `fxN_par`; `inputRouter.par_amount := arr` (the `InFeedback` parallel tap). |
| `fxN/dry` | 917-933 | array | `outputRouter.timbre_(N+1)_dry := arr`. |
| `fxN/dig-dry` | 938-958 | array | Stores `fxN_dig_dry`; `outputRouter.timbre_(N+1)_dry_main := arr`. |
| `/fxN/p/0` … `/fxN/p/14` | 198-214 (via `~initEffectParamHandlers`) | float | Sets the effect's k-th non-generic control. See §5. |
| `/fxN/pl` | 964-969 | — | **Dead.** Builds a string and never prints or sends it. |
| `/fxN/ph` | 972-989 | int | Broken under `init_sc_1`: uses `~scIP` (never assigned in this boot path — only `init.scd`/`init_sn.scd`/`init_sc_2.scd` read the env vars) and hard-codes the reply address `'/fx0/ph'` regardless of N. Also assigns to bare `i`, a global interpreter variable. |

### 3.3 Environment functions on `~efxServer`

| Key | Signature | Line | Purpose |
| --- | --- | --- | --- |
| `\initEffectParamHandlers` | `{ arg unitNum }` | 193-217 | (Re)registers the 15 `/fxN/p/k` OSCdefs. Called **only** from line 626. |
| `\initEffect` | `{ arg effect=\none_1, unitNum=0, server=Server.default }` | 225-282 | Creates or adopts the slot's synth. `server` is used only in a debug print (276) — dead parameter. |
| `\initUnit` | `{ arg unitNum=0 }` | 289-994 | Per-slot state + 20 OSCdefs. |
| `\efx_active` | `List` | 184 | Identity list of active slot numbers. |
| `\efx_i` | Integer | 185, 301 | Registration counter; ends at 5. |
| `\efx_type` | String | 186, 360 | Set to `"symbol"`, never read. |
| `\state` | — | — | **Does not exist**, despite `init_sc_1.scd:43`. |

### 3.4 Outbound messages

| Message | Line | Destination |
| --- | --- | --- |
| `/ping` | 11 | reply to sender |
| `/fx/state <int>` | 124 | `NetAddr("localhost", sender.port)` |
| `/fxN <original msg>` | 646 | `NetAddr("localhost", sender.port)` — the ack, sent **only** on the `msg[9].notNil` path |
| `/fx0/ph ...` | 985-988 | `NetAddr(~scIP, 7777)` — broken, see above |

**There is no "tell me your current state" or "resend everything" message in either
direction.** The engine can never ask the controller to re-push. This is central to §6.1.

### 3.5 Remote code execution surface

`efx_server.scd:338-345`:

```
if( msg[2].isNil == true, {
    ...
    msg[1].asString.interpret;
```

Any UDP packet to port 7775 whose address is `/fx0`..`/fx4` and which has **only one
argument** is compiled and executed as sclang source, as root. Port 7775 is bound to
`0.0.0.0` (`runtime-state.txt`, listening UDP), and the device is on `192.168.1.136`. This
is presumably the intended debug/expression hook, but it means **anything on the LAN can
run arbitrary code on the instrument.** Do not expose the instrument's network interface.

---

## 4. Full lifecycle of an effect change

### 4.1 Message format

Documented in the source at `efx_server.scd:335`:

```
[0]=address, [1]=effect symbol, [2]="ins"|<bus>, [3]=inBus, [4]=outBus,
[5]=(unused), [6]=pan, [7]=en, [8]=g-out(VCA), [9..]=(pIndex, pValue) x 12
```

`preset_param_offset = 8+1 = 9` (`:326`), `num_generic_params = 11` (`:325`).

Two gates before anything happens:

- `msg[2].isNil` → treat `msg[1]` as sclang source and `interpret` it (`:338-345`).
- `msg[9].isNil` → **silently discard the entire message** (`:350-353`, with the comment
  "this is here to catch the bogus shit the frontend put out"). So a preset with **zero
  parameters carries no `msg[9]` and is dropped entirely — including the ack.** Since
  `none_N` has no parameters (see §5.1), **a "no effect" selection cannot be delivered
  through `/fxN` unless the controller pads the message.** READ; the consequence is
  INFERRED but direct.

### 4.2 `~initEffect` line by line (`efx_server.scd:225-282`)

```
225  ~initEffect = {arg effect=\none_1, unitNum=0, server = Server.default;
231-233   debug print of the OUTGOING effect
236   if (fxN_category == \ins) {
239       fxN_effect := Synth(effect, target: ~efxGroups[unitNum], addAction: 'addToHead')
          -- no free, no park, no check of ~eventides. The previous node is simply
             dropped from the dictionary and left to its own doneAction:2.
241   } else {                              // bus / master
245       if (~eventides.keys.includesEqual(fxN_effect.defName.asSymbol)) {
248           fxN_effect.moveToTail(~eventideGroup)   // park the OLD eventide
249           fxN_effect.run(false)
251       }
          -- The comment on 247 says "wait for it to fade (and taper fdbk / decay params)".
             No wait and no taper is performed. The park is immediate.
257       if (~eventides.keys.includesEqual(effect)) {
259           fxN_effect := ~eventides.at(effect)      // ADOPT the parked instance
260           fxN_effect.moveToTail(~efxGroups[unitNum])
              -- NOTE: no run(true) here. See §6.4.
263       } else {
265           fxN_effect := Synth(effect, target: ~efxGroups[unitNum], addAction:'addToTail')
266       }
269       ~dspOutputWrapper.moveToTail(~busGroup)
271   }
280   Server.named.at(\server_main).sync    // the only sync point; yields the thread
282  }
```

Two structural observations:

- `~initEffect` **never frees anything.** Teardown is entirely delegated to
  `EnvGen(..., doneAction: 2)` on the outgoing synth, which is triggered by whoever set
  `\enable` to 0 *before* calling `~initEffect`. If that did not happen, the outgoing
  synth stays alive forever with no handle.
- `sync` at 280 is a real yield point. It is the only one in `~initEffect`, and it means
  `~initEffect` must be called from inside a Routine. All three call sites are
  (`init_sc_1.scd:55/58` inside `waitForBoot`; `efx_server.scd:373` inside a `.fork`;
  `efx_server.scd:1066` inside `~fxStateThread`). Anything added later that calls it
  outside a Routine will throw.

### 4.3 `~fxStateThread` (`efx_server.scd:1033-1081`)

```
1042  loop {
1044      0.10.wait                                        // 10 Hz poll
1047      size = ~efxServer[\efx_active].size
1049      size.do { arg i;
1050          if (fx{i}_change_needed == true) {
1053              fx{i}_effect.set(\enable, 0)             // start the fade-out
1055              ~fxEnableCheckRoutine.value(fx{i}_effect) // spawn confirmation routine
1057              0.125.wait                               // release time is 0.1 s
1066              ~initEffect(effect: ~efxServer[fx{i}], unitNum: efx_active.at(i))
1070              fx{...}_en_prev := 1
1073              fx{i}_change_needed := false
          }
      }
  }
```

Note that line 1066 uses `~efxServer[fxN]` — **the most recently *requested* effect** — not
anything carried by the message that raised the flag. The flag and its payload are
decoupled. That is the root of most of §6.

`~fxEnableCheckRoutine` (`efx_server.scd:1005-1028`):

```
1006  var id = 0, enable = 1;
1009  loop {
1010      id = synth.nodeID.asInt
1011      if (id == 0) { break }
1015      synth.get(\enable, { arg val; enable = val.asInt })   // ASYNCHRONOUS
1018      if (enable == 0) { break } else { synth.set(\enable, 0) }
1024      0.02.wait
      }
```

`.get` is asynchronous: the `if` on line 1018 always tests the *previous* iteration's
reply. For a live node this converges in two iterations (~20 ms). **For a node that no
longer exists there is no reply, `enable` stays at its initial `1`, and the routine spins
at 50 Hz forever** — no timeout, no cancellation, no handle kept. See §6.2.

### 4.4 The change path in the `/fxN` handler (`efx_server.scd:478-639`)

Triggered when `prevEffect != effect`:

```
481  ~change = true                                     // global; never read anywhere
482  fxN_change_needed := true
483  prevEffect = effect                                // local, written back at 642
486  fxN_param_vals := []
489  Routine({                                          // "the waiter"
491    block { arg break;
493      loop {
495        0.01.wait                                     // 100 Hz busy-poll
498        if (fxN_effect.defName == msg[1]) {           // the ONLY exit condition
500          0.1.wait
502          Server...sync
507-512      inBus := (ins ? msg[3]+8 : [msg[3], msg[3]+1])
514-515      outBus := msg[4];  category := msg[2]
518-522      g-out := msg[7]*msg[8] -> set \g_out;  g-in := msg[7] -> set \g_in
525          controlNames := SynthDescLib.global.at(~efxServer[fxN]).controlNames
527-531      param_vals := Array.fill(controlNames.size - 11, 0)
540-571      12.do { read (pIndex, pValue) pairs from msg[9..]; set by name }
575-576      set \pan := msg[6];  store fxN_pan
579-581      set \inBus, set \outBus
583          outputRouter.insert_(N+1)_g := msg[8]
612-613      fxN_en := msg[7];  fxN_en_prev := msg[7]
616-623      if effect is an eventide: 0.1.wait; moveToTail(~efxGroups[N]);
                                      run(true); set(\enable, 1)
626          ~initEffectParamHandlers(unitNum)          // register /fxN/p/k
629          break.value(0)
           }
         }
       }
     }).play
642  fxN_prev_effect := prevEffect                       // executes IMMEDIATELY
645-647  ack /fxN back to sender
```

### 4.5 The "no change" path (`efx_server.scd:364-476`)

Triggered when `prevEffect == effect` — i.e. a different preset within the same effect
type. It does **not** go through the state machine at all:

```
367  ~change = false                                    // dead
369  {                                                  // .fork at 475
371    fxN_effect.set(\enable, 0)                       // fade out (0.1 s release)
372    0.2.wait
373    ~initEffect(effect, unitNum)                      // rebuild the synth
376-383 if eventide: 0.1.wait; moveToTail; run(true); set(\enable,1)
387    psize := controlNames.size - 11                   // reuses the CACHED names
391-426 12.do { same (pIndex, pValue) loop }
429-434 set \pan, \inBus, \outBus
437-441 g-out := msg[7]*msg[8]; g-in := msg[7]
443    outputRouter.insert_(N+1)_g := msg[8]
446-447 fxN_en, fxN_en_prev := msg[7]
475  }.fork
```

Three problems here, all READ:

- **It never clears `fxN_change_needed`.** Only line 1073 does. So if this path runs while
  a change is pending, the state machine will *also* rebuild the slot ~100-225 ms later.
- **It destroys and recreates the synth for every preset recall within the same effect
  type.** For non-eventides that is a `doneAction: 2` free followed by a fresh `Synth` —
  a guaranteed ≥200 ms silence and a re-zeroed delay line / reverb tail on every preset
  change. (For eventides it is a park-and-readopt of the same node, which preserves the
  LADSPA plugin's internal state — a nice side effect of the parking design.)
- **It does not call `~initEffectParamHandlers`** and does not refresh `controlNames`. It
  relies entirely on cache from a previous change.

### 4.6 Timeline of a clean effect change

```
t=0.000  /fxN arrives.  fxN := A;  change_needed := true;  waiter W_A spawned (100 Hz).
                        fxN_prev_effect := A  (immediately — before anything is applied)
                        ack /fxN sent
t≤0.100  ~fxStateThread wakes.  old synth .set(\enable, 0)  → 0.1 s release begins
                        ~fxEnableCheckRoutine spawned (50 Hz)
t≈0.020  fxEnableCheckRoutine confirms enable==0, breaks (usually)
t≈0.100  old synth's EnvGen completes → doneAction 2 → node frees itself
                                       (or doneAction 1 → pauses, if eventide)
t≈0.225  state thread's 0.125 wait ends → ~initEffect(A, N)
                        new Synth created / eventide adopted (still PAUSED if eventide)
                        Server.sync
                        change_needed := false
t≈0.235  W_A sees defName == A → 0.1 wait
t≈0.335  W_A: sync, then apply buses, 12 params, pan, gains
t≈0.435  W_A: if eventide → moveToTail, run(true), set(\enable,1)
                        register /fxN/p/0..14
                        break
```

**Total 0.33-0.44 s of silence in that slot per effect change**, of which 0.125 s is the
fade and the rest is polling latency. The fade (0.125 s wait vs. a 0.1 s `Env.asr` release)
has only 25 ms of margin.

---

## 5. The parameter path

### 5.1 Control layout

Every effect SynthDef begins with the same generic block. `num_generic_params = 11`
(`efx_server.scd:325, 201`), and the mapping is `panel index k → controlNames[k + 11]`:

| controlNames index | name | notes |
| --- | --- | --- |
| 0 | `enable` | the fade gate — **engine-owned, not the panel's bypass** |
| 1 | `inBus` | |
| 2 | `outBus` | |
| 3 | `ctlIn` | never used |
| 4 | `ctlOut` | never used |
| 5 | `ctl` | front-panel assignable pot (`/fxN/ctl`) |
| 6 | `g_in` | |
| 7 | `g_out` | |
| 8 | `wet` | declared in the synthdefs, never driven (`/fxN/wet` is a no-op) |
| 9 | `dry` | declared, never driven |
| 10 | `pan` | |
| **11** | `mix` | **panel parameter 0** |
| 12.. | effect-specific | panel parameters 1..n |
| last | `gain` | the final panel parameter on most effects |

Verified against `delay_n` (`synthdefs.scd:644-660`): controls are
`enable, inBus, outBus, ctlIn, ctlOut, ctl, g_in, g_out, wet, dry, pan, mix, feedback,
time, gain` → `psize = 15 - 11 = 4`, and the metadata `description` block lists exactly
Mix / Feedback / Time. And against `et_blackhole_n` (`synthdefs.scd:3381-3404`): 22
controls → `psize = 11`, metadata lists Mix + 9 = 10, plus `gain`. Consistent.

**`none_N` is the exception** (`synthdefs.scd:33-53`): its controls are
`enable, inBus, outBus, ctlIn, ctlOut, ctl, mix, volume` — 8 total, and **no `g_in`,
`g_out`, `pan`, `wet` or `dry` at all**. So `psize = 8 - 11 = -3`, every
`if(pindex < psize)` is false, and every `.set(\pan/\g_in/\g_out, …)` aimed at a `none_N`
slot is a "Control not found" no-op on the server. That is fine, but it means **a
`none_N` slot silently swallows every gain and pan message**, which is worth knowing when
debugging the post-restart state (§6.1).

### 5.2 Path A — live knob turns: `/fxN/p/k`

`~initEffectParamHandlers` (`efx_server.scd:193-217`):

```
195  15.do { |p|
198    OSCdef("fx{N}_parameter_{p}", { |msg|
201      var num_generic_params = 11;
203      if (~efxServer[fx{N}_controlNames][p + 11].notNil) {
205        var pval = msg[1];
206        ~efxServer[fx{N}_effect].set( controlNames[p+11], pval )
       }
     }, "/fx{N}/p/{p}")
   }
```

- The control name is looked up **at message time**, so the handler automatically follows
  whatever effect is currently in the slot. Good design.
- `pval = msg[1]` is passed **completely raw** to `/n_set`. No scaling, no clamping, no
  ControlSpec lookup, even though every SynthDef carries a `metadata.specs` ControlSpec
  for exactly this purpose (`synthdefs.scd:3430-3439` etc.). **The `specs` metadata is
  never consulted anywhere in `efx_server.scd`.** All range discipline is either inside
  the SynthDef graph (`ControlSpec.new(0.01, 24.0, \lin, …).map(time)` in `delay_n`,
  `synthdefs.scd:677`; `ControlSpec.new(0.01,2.25,\exp,0.01).map(gain)` in the eventides,
  `synthdefs.scd:3422`) or in the controller.
- **These handlers do not exist after a cold boot.** `~initEffectParamHandlers` is called
  from exactly one place: `efx_server.scd:626`, inside the change-path waiter. So
  `/fx0/p/0` … `/fx4/p/14` are unregistered until each slot has successfully completed one
  effect *change*. Parameter messages sent before that are dropped by SuperCollider with
  no error. **This is a direct contributor to the restart bug** (§6.1).
- 15 handlers are always created but only `controlNames.size - 11` of them can ever match;
  the rest short-circuit on the `notNil` check.

### 5.3 Path B — preset recall: the 12 (index, value) pairs inside `/fxN`

Both the change path (`:540-571`) and the no-change path (`:391-426`) run the same loop:

```
pindex = msg[i + 9]
if (pindex.isNil) { pindex = 0 }         // nil→0 means a short message writes param 0
if (pindex < psize) {
    pval  = msg[i + 9 + 1]
    pname = controlNames[pindex + 11]
    fxN_effect.set(pname, pval)
}
i = i + 2
```

- 12 pairs maximum, but 15 live handlers — a preset can carry at most 12 of the 15
  addressable parameters.
- `pindex.isNil → 0` (`:545`, `:396`) means a truncated message will repeatedly write
  `msg[10]`'s value into parameter 0 (`mix`). If `msg[10]` is also nil, `.set(\mix, nil)`
  — INFERRED: sclang will fail to encode a nil OSC argument and the whole `/n_set` is
  dropped or throws.
- `pindex` is bounds-checked **upward only** (`pindex < psize`). A negative `pindex` would
  index `controlNames[pindex + 11]` backwards into the generic block — e.g. `pindex = -1`
  → `pan`, `-3` → `g_out`, `-11` → `enable`. **A negative parameter index can set
  `\enable` directly and free the synth** (doneAction 2). No guard anywhere.
- The change path additionally records `fxN_param_vals[pindex] = pval` (`:566`); the
  no-change path does not, so that cache goes stale after the first preset recall. Nothing
  reads it back, so this is currently inert.

### 5.4 Values that *are* transformed

| Where | Line | Transform |
| --- | --- | --- |
| `g_out` from a preset | 437, 518 | `msg[7] * msg[8]` — enable flag × VCA gain |
| `g_out` from `/fxN/en`, inserts | 670 | `msg[1] * fxN_g-out` |
| `g_out` from `/fxN/en`, slots 3-4 | 667 | `msg[1]` alone — deliberately different |
| dry-path pan | 759 | `-1 * (1 + (2 * (pan - 1)))` — maps `[0,1] → [+1,-1]` |
| wet-path pan | `synthdefs.scd:24` | `~panScale = ControlSpec.new(1, -1, …)` — also `[0,1] → [+1,-1]` |
| insert input bus | 508, 813 | `+ 8` (hardware channel → absolute bus) |
| bus-slot input bus | 511 | `[msg[3], msg[3]+1]` — **no offset** |
| aux routing | 854 | `arr[2..]` — drop main/sub, keep the four aux toggles |
| digital dry gain | 158, 161 | `1.9` (old hw) / `0.9` (new hw) |

The pan inversion is consistent between the dry and wet paths — do not "fix" one without
the other.

**Unclamped hazard worth naming:** `g_out := msg[7] * msg[8]` is the product of two
unvalidated floats, and in `delay_n` it lands in
`Out.ar(outBus, out * env * g_out * g_comp(=3) * ((gain*1)+0.1))` (`synthdefs.scd:698`)
with **no `softclip`**. The eventides do `.softclip` (`synthdefs.scd:3422`); the insert
effects mostly do not. A controller bug in `msg[7]`/`msg[8]` produces full-scale hard
clipping on the inserts.

### 5.5 A latent type bug in the no-change path

`~initUnit` seeds `fxN_inBus` with the **String** `"1,2"` and `fxN_outBus` with `"1"`
(`efx_server.scd:304-305`). The no-change path sets the synth's buses from those cached
values (`:432`, `:434`). If a no-change message ever reached a slot before any change
message had rewritten those keys, sclang would send `/n_set <node> "inBus" "1,2"` —
INFERRED: scsynth reads the value slot as a number, gets 0, and the effect would read
**hardware output bus 0**. Today this is unreachable because `fxN_prev_effect` starts as
the Integer `0` (`:295`) so the first message always takes the change path. It becomes
reachable the moment anyone changes that initial value to a Symbol.

---

## 6. State, persistence, and the restart bug

### 6.0 Where state lives

Everything is in-memory in the sclang process:

- `~efxServer` — an `Environment` (`efx_server.scd:182`) holding ~18 flat keys per slot,
  namespaced by string concatenation (`"fx" ++ unitNum ++ "_xxx"`). No nesting, no
  schema.
- Interpreter globals: `~efxGroups`, `~insertGroup`, `~busGroup`, `~eventideGroup`,
  `~eventides`, `~dspInputWrapper`, `~dspOutputWrapper`, `~fxStateThread`,
  `~fxEnableCheckRoutine`, `~debug`, `~netAddr`, `~serverPID`, `~serverState`,
  `~statereturn`, `~change`, `~incomingPort`.
- Server-side: node IDs, control values, and the LADSPA plugins' internal DSP state.

**Nothing is written to disk. Nothing is read from disk.** There is no persistence layer
in the effects engine at all. Every byte of preset state lives in `las-frontend`
(`--data-path=/var/las-frontend`) and is pushed down through `las-sc`.

What survives a *patch* change: nothing, by design — the controller re-pushes `/fxN` for
each slot, and each of those either rebuilds the synth (change path) or tears down and
rebuilds it (no-change path). What survives a *sclang* restart: nothing.

### 6.1 The `S42sc restart` → five `none_1` slots bug

The source does explain it, in three layers.

**Layer 1 — the restart really does reset the engine.** `init.d/S42sc`'s `stop()` runs
`killall sclang; killall jackd; killall scsynth; killall las-sc` (lines 28-32) and
`start()` runs only `las-sc` (line 23). `las-sc` in turn spawns
`screen -d -m /usr/share/las-fx/launch-sc-1 &` (READ from the `las-sc` binary's string
table), which runs `sclang ... init_sc_1.scd`. So the SC stack does come back — from
scratch. `init_sc_1.scd:55/58` puts `\none_1` in all five slots. That part is expected.

**Layer 2 — `las-frontend` is not restarted and is never asked to re-push.** `S42sc` does
not touch `las-frontend` (PID 915 in `runtime-state.txt`, started by `S43gui`). The
frontend keeps its idea of the current preset. And, as established in §3.4, **the effects
engine has no message that requests a state dump, and the controller has no way to learn
that the engine restarted** — `/fx/state` is *pull-only from the controller's side*, and
`stopAliveThread` (`init_sc_1.scd:109`) means sclang itself will never notice anything
either. If the frontend's change-detection concludes "the preset is already loaded", it
sends nothing and the slots stay `none_1` forever.

**Layer 3 — even a re-push is only half sufficient.** Two mechanisms in
`efx_server.scd` will swallow a partial re-push:

- Parameter messages alone go nowhere: `/fxN/p/k` is not registered until a slot completes
  its first effect *change* (§5.2). So "reload the same preset" that re-sends only
  parameters is a complete no-op.
- A `/fxN` message with fewer than 10 elements is dropped in silence, ack included
  (`:350-353`). Any slot whose preset selects a parameter-less effect (`none_N`) cannot be
  set this way.

There is also a fourth, subtler contributor: `none_N`'s control list omits `g_in`, `g_out`
and `pan` entirely (§5.1). So while the slots sit at `none_1`, **every gain, enable and pan
message the controller sends is accepted by the handler, stored in `~efxServer`, and
discarded by the server.** From the outside this looks like "the engine is receiving
things but nothing happens", which is easy to misdiagnose as a dead OSC path.

**Recovery levers that exist in the source:**

- `/fx/start 1` will `reset` + `play` `~fxStateThread` if it has stopped or died
  (`:62-64`) — the only supported way to revive a dead state machine.
- Setting `fxN_change_needed := true` on a slot (from an interpreted expression, §3.5)
  makes the state machine rebuild that slot from `~efxServer[fxN]`. **But `~efxServer[fxN]`
  is `\none_1` after a restart**, so this alone will not restore a preset.
- Nothing in the source can make the frontend re-push. INFERRED: the reliable fix is to
  restart `las-frontend` too, or to select a *different* preset and then reselect the
  wanted one so the frontend's change detection fires.

### 6.2 Immortal `~fxEnableCheckRoutine`s

As shown in §4.3, a `~fxEnableCheckRoutine` whose target node no longer exists never
terminates: `synth.get` gets no reply, the captured `enable` stays `1`, and the routine
loops at 50 Hz forever. Nothing holds a handle to it, so it cannot be stopped.

Reachable whenever the node frees itself (`doneAction: 2`) before the second poll — a
20 ms race that the boot sequence in particular exercises (see §6.6). Each occurrence
leaks one Routine plus a permanent 100 msg/s of `/n_set` + `/s_get` to a nonexistent node
ID, plus scsynth "Node not found" log spam. **INFERRED long-tail risk:** SuperCollider's
client-side node-ID allocator wraps; if an ID is ever reused, a zombie routine will
silently drive `\enable → 0` on a live, unrelated effect and free it.

### 6.3 Eventide dictionary aliasing — the same reverb in both master slots

`~eventides` holds exactly **one** Synth per defName (`init_sc_1.scd:74-104`), and
`~initEffect` hands out that same object by reference (`efx_server.scd:259`).

If slot 3 and slot 4 are both given the same eventide defName (which §2.4 argues is the
*normal* case in a given bus mode, since `_1`/`_2` selects mono-vs-stereo rather than
slot):

```
initEffect(et_hall_1, 3):  fx3_effect := X;  X.moveToTail(~efxGroups[3])
initEffect(et_hall_1, 4):  fx4_effect := X;  X.moveToTail(~efxGroups[4])   // X LEAVES slot 3
```

Result: `~efxGroups[3]` is empty (slot 3 is silent), both slots' handles point at the same
node, both slots' parameter handlers write to it, and **the next effect change on slot 3
will park node X — killing slot 4's reverb.** Also, X's `inBus`/`outBus` will be whichever
slot configured it last, so one of the two masters is reading the other's send bus.

There is no guard: no "is this instance already in use" check, no per-slot pool. If the
controller happens to allocate `_1` to slot 3 and `_2` to slot 4 by convention, this never
fires; the moment that convention is broken it fires silently.

### 6.4 An eventide can be adopted but never un-paused

`~initEffect` moves an adopted eventide into the slot's group (`:260`) but does **not**
call `run(true)`. The un-pause happens only at `:620` (change path) or `:380` (no-change
path). Both are inside routines whose progress is not guaranteed. Specifically, the
change-path waiter's only exit is `fxN_effect.defName == msg[1]` — if that never becomes
true (§6.5), **the slot ends up holding a correctly-placed, correctly-routed, permanently
paused reverb.** Symptom: the slot shows the right effect on the panel and produces
silence, and no amount of parameter twiddling fixes it. Only another effect change does.

### 6.5 Effect change requested while a fade is in flight — the specific answer

This is the worst case in the file. Take a change to A at t=0, then a change to B at
t=50 ms (well inside the 0.1 s poll + 0.125 s fade window).

```
t=0     handler(A): change_needed := true; fx3 := A; prev_effect := A
                    spawn W_A  (polls for defName == A, 100 Hz, no timeout)
t=0.05  handler(B): prev_effect(A) != B → change path again
                    change_needed := true (already true — the second request is
                                           indistinguishable from the first)
                    fx3 := B; prev_effect := B
                    spawn W_B
t=0.10  state thread: sees ONE flag, does ONE teardown, then
                    initEffect(~efxServer[fx3] = B)     ← A is never instantiated
                    change_needed := false
t≈0.24  W_B matches → configures with B's message. Correct.
        W_A never matches. It spins at 100 Hz. FOREVER.
```

Consequences, in order of severity:

1. **W_A leaks permanently** — one immortal 100 Hz Routine per superseded change. Sweeping
   the effect encoder through ten effects leaves nine of them behind.
2. **W_A is a time bomb.** If the user later selects effect A again on that slot, the stale
   W_A wakes up and replays its *original* message — old bus assignments, old pan, old
   `g_in`/`g_out`, and all 12 old parameter values — concurrently with the fresh waiter,
   and calls `~initEffectParamHandlers` a second time. The slot ends up with a
   non-deterministic mix of the old and new presets depending on interleaving.
3. **The intermediate effect is skipped entirely**, which is arguably correct behaviour but
   means the ack sent at `:646` for effect A is a lie — the engine acked a change it never
   performed.
4. If the second message happens to select the *same* effect A (a duplicated preset push
   arriving inside the window), `prevEffect == effect` and the **no-change path** runs
   instead. That path calls `~initEffect` directly (`:373`) while `change_needed` is still
   `true`, so the state thread calls `~initEffect` again ~100 ms later. **Two synths are
   created for one slot and only the second handle is kept.** The orphan is a
   `doneAction: 2` effect whose `\enable` nobody will ever set to 0 — it runs forever,
   reading the slot's input bus and adding to the slot's output bus. Audible symptom:
   the effect is permanently doubled, and it cannot be cleared without a restart.

There is no mutex, no generation counter, no cancellation token, and no timeout anywhere
in this path.

### 6.6 A double allocation at boot

`~initUnit` sets `fxN_change_needed := true` (`:317`) **before** any effect synth exists,
and `~fxStateThread` is already running by then (started at `efx_server.scd:1081`, i.e.
during `init_sc_1.scd:40`, well before the slot loop at `:51`). The state thread's 10 Hz
poll and `~initEffect`'s `Server.sync` yield (`efx_server.scd:280`) interleave. INFERRED
from SuperCollider's cooperative scheduling: for each slot the state thread will typically
observe `change_needed == true` shortly after `initEffect(\none_1, i)` has created the
synth, and will then set `\enable := 0` on that brand-new `none_1` and build a second one.
The first frees itself (`none_N` is `doneAction: 2`, `synthdefs.scd:49`), so nothing leaks
— but it does spawn a `~fxEnableCheckRoutine` against a node that is about to disappear,
which is precisely the §6.2 zombie condition. **Expect up to five immortal routines from a
clean boot.**

The genuinely dangerous variant is the same race with `~efxServer[fxN_effect]` still nil:
`nil.set(\enable, 0)` at `:1053` would throw `doesNotUnderstand` **inside the state
machine's Routine, killing it permanently** with no restart and no log beyond the sclang
error. Today there is no yield point between `initUnit`'s flag-setting (`:317`) and
`initEffect`'s `Synth` creation (`:239`), so it is unreachable — but it is one added
`.wait`, `.sync` or `.fork` away from being reachable, and the symptom would be exactly
"the engine accepts messages and never changes anything".

### 6.7 Reloading `init_sc_1.scd` at runtime is catastrophic

`/fx/start 1` will call `"init_sc_1.scd".loadRelative` if `kill -0 <scsynth pid>` fails
(`efx_server.scd:67-72`). Re-running that file:

- re-runs `Environment.make` → a **new** `~efxServer` with `efx_active` empty and
  `efx_i = 0`;
- re-runs `~fxStateThread = Routine(...).play` — **without stopping the old one**. Two
  state machines now poll the same slots and will race each other's `change_needed` flags
  and `~initEffect` calls;
- re-creates `~insertGroup`, `~busGroup`, `~efxGroups`, `~eventideGroup` — **the old
  groups and everything in them are orphaned**, still running, never freed;
- creates **ten more** `et_*` Synths, i.e. ten more live LADSPA reverb instances on top of
  the ten already parked. `runtime-state.txt` shows `MemFree: 11 MB` of 508 MB and
  `scsynth -m 100000`. INFERRED: this will exhaust real-time memory or CPU.
- calls `Server.new(\server_main, ...)` on a name that already exists. INFERRED: SC will
  either error out mid-file (leaving the engine half-initialised) or replace the entry.

Also note that `~serverPID = Server.named.at(\server_main).pid` (`:58`) is only populated
for a server this sclang instance actually booted. After any path that leaves it nil,
`("kill -0" + nil.asString).systemCmd` runs `kill -0 nil`, which returns non-zero, which
reports the server as dead and triggers the reload above. **That is a self-sustaining
reload loop.**

`las-watchdog` has its own recovery for this (`/etc/init.d/S42sc stop; killall scsynth
sclang screen; /etc/init.d/S42sc start &`, READ from the binary's strings) which is the
sane path. The in-band reload at `efx_server.scd:71` should be considered dead code that
must never fire.

### 6.8 Smaller defects

| # | Line(s) | Defect |
| --- | --- | --- |
| 1 | 782-798 | `/fxN/wet` does nothing; the write is commented out. |
| 2 | 964-969 | `/fxN/pl` builds a string and discards it. |
| 3 | 972-989 | `/fxN/ph` uses unset `~scIP` and hard-codes the reply address `/fx0/ph`. |
| 4 | 769-778 | `/fx/run` targets the unbound `~state`; registered 5× under one key. |
| 5 | 443, 583, 723 | `outputRouter.insert_(N+1)_g` for N=3,4 targets `insert_4_g`/`insert_5_g`, which do not exist (`synthdefs.scd:433-435` defines 1-3 only). Silent no-op. Same for `timbre_4/5_dry`, `dry_dir5_r`, `synth4/5_in_ch`. |
| 6 | 818 & 821 | `/fxN/in` sets `\inBus` unconditionally at 818, then again inside a `change_needed == false` guard at 821. The guard is defeated by the line above it. |
| 7 | 367, 481 | `~change` is a *global*, shared by all five slots, written and never read. `var change` (line 324) is declared and never used. |
| 8 | 413, 557 | Debug `.get(name, {|v| pval = v})` is async; the value printed on the next line is the previous parameter's. Same misuse as §4.3, but debug-only. |
| 9 | 1050 vs 1066/1070 | The state thread tests `fx{i}_change_needed` using `i` but acts on `efx_active.at(i)`. Identical today because `efx_active` is the identity list; a divergence would make slot *i*'s flag rebuild a different slot. |
| 10 | 645-647, 105 | `~netAddr` is a single global reused by `/fx/state` and by all five `/fxN` acks. A new `NetAddr` is allocated per message and `.disconnect`ed (a TCP operation on a UDP address). |
| 11 | 174, 705, 716, 739, 798, 830, 860, 886, 913, 933, 958 | These OSCdef paths are registered **without** a leading slash while the rest have one. This works only because `OSCFunc` normalises a missing leading `/` (INFERRED from SC's implementation; corroborated by the fact that `las-sc` demonstrably drives `/fx0/sends`, `/fx0/in` etc. successfully on the live instrument). Do not "tidy" these — verify against the SC version on the device first. |
| 12 | 545, 396 | `pindex` is bounds-checked upward only; a negative index reaches backwards into the generic control block, including `\enable` (§5.3). |
| 13 | 225 / 276 | `~initEffect`'s `server` argument is dead — the function always syncs `Server.named.at(\server_main)` explicitly. |

---

## 7. Things that will break the instrument if touched

Ordered by blast radius.

1. **`doneAction: 1` on the ten `et_*` SynthDefs** (`synthdefs.scd:3407, 3492, 3576, 3657,
   3735, 3817`). Changing any of these to `2` — for consistency with the other 26 effects,
   which is exactly the "cleanup" someone would attempt — causes the LADSPA node to be
   **freed**, which terminates scsynth. The whole parking architecture exists to prevent
   this.

2. **`.run(false)` on anything in `~eventideGroup`, and the group's position after
   `~busGroup`.** A parked, never-adopted eventide has `inBus = 0, outBus = 0`, i.e. the
   main hardware output. Un-pausing one by hand creates an output-to-output feedback path
   downstream of the output router.

3. **The in-band `"init_sc_1.scd".loadRelative` at `efx_server.scd:71`.** §6.7. Doubles
   every group, every state machine and every LADSPA instance on a box with 11 MB free.
   Do not exercise `/fx/start 1` while scsynth's PID is unknown.

4. **`msg[1].asString.interpret` at `efx_server.scd:344`.** Root-level RCE from any host on
   the LAN, on a UDP port bound to `0.0.0.0`. It is also the only debugging back door into
   the engine, so removing it costs you your primary diagnostic tool — but the instrument
   must never be on an untrusted network.

5. **Sending two `/fxN` messages for the same slot inside ~250 ms.** §6.5: leaks an
   immortal routine, and if the two messages name the same effect, permanently duplicates
   the effect synth in that slot. Any tooling that scripts effect changes must rate-limit
   to <4 changes/second per slot, and must not re-send an identical selection.

6. **Assigning the same eventide defName to both slot 3 and slot 4.** §6.3: silently steals
   the node from slot 3, and the next change on slot 3 kills slot 4's reverb.

7. **The 0.125 s wait at `efx_server.scd:1057` vs. the 0.1 s `Env.asr` release.** 25 ms of
   margin. Lengthening the release in any SynthDef without lengthening this wait means the
   outgoing synth is still audible (and still holding its output bus) when the incoming one
   starts.

8. **`~fxStateThread` dying.** Any exception inside the loop (`efx_server.scd:1042-1079`)
   kills the effects engine permanently, with the only symptom being that effect changes
   stop applying. `/fx/start 1` is the documented revival; nothing does it automatically.
   `stopAliveThread` (`init_sc_1.scd:109`) guarantees sclang will not notice on its own.

9. **The insert/bus `inBus` offset asymmetry** (`+8` for `\ins`, none for bus slots,
   `efx_server.scd:508` vs `:511`). Normalising one without the other points an effect at
   the wrong bus — potentially a hardware output bus, i.e. feedback.

---

## 8. Open questions this harvest cannot answer

1. Does the on-device `init_sc_1.scd` really request blockSize 128 when the running scsynth
   has 256? Re-harvest before trusting §1.
2. How does scsynth actually find `/usr/share/las-fx/ladspa`, given that
   `("export LADSPA_PATH=…").systemCmd` cannot possibly work (§1)?
3. Which component emits the bare `/fx0`..`/fx4` change message? `las-sc`'s string table
   contains the `/fxn/...` templates and literal `/fx0/in`, `/fx0/out`, `/fx0/sends`,
   `/fx0/dry`, `/fx0/dig-dry`, `/fx0/g-out`, `/fx0/pan`, `/fx0/par` (slots 0-2 only), plus
   `/fx/hw-rev`, `/fx/spread`, `/fx/bus-mode` — but the bare `/fxN` address is built
   dynamically and was not recoverable from strings.
4. Does the controller assign `et_*_1` to slot 3 and `et_*_2` to slot 4 (which would make
   §6.3 unreachable), or does it select the variant purely from the bus mode (which would
   make §6.3 routine)? This determines whether §6.3 is a latent bug or an active one.
5. Does `SynthDescLib.global.read` restore the `metadata` dictionaries from the
   pre-compiled `.scsyndef` files? If not, `/fxN/ph` is broken for a second reason and the
   `specs` ControlSpecs are unavailable at runtime even if someone wanted to use them for
   clamping.
