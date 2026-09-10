# `las-sc` — the complete OSC surface and dispatch

Static analysis of `usr/bin/las-sc` from the decrypted **firmware 1.8.2** root
filesystem, cross-checked against the **1.5.0** rootfs and the harvested binary.
No part of this was obtained from the instrument. Two on-disk packet captures
taken previously by this project are cited where they settle a wire fact.

**Every claim is graded.** `[READ]` = taken directly out of a file, with the file
and offset; `[INFERRED]` = reasoning, with the evidence named; `[UNKNOWN]` = not
established.

---

## 0. Headline

**`/p/pre-expr`, `/p/post-expr` and all 115 `_m` addresses are dead code in
`las-sc`.** They exist in exactly one place in the binary: a 117-element quoted
list that the module top-level decodes and assigns to the global
`expression-nodes`. That global is **read exactly once in the whole program — at
its own definition.** Nothing dispatches on it, nothing iterates it, nothing
builds a table from it. `las-sc` therefore has no handler for `/p/pre-expr`, and
an incoming `/p/pre-expr` falls off the end of `part-dispatch`'s prefix `cond`
and is silently discarded. That is exactly the behaviour observed on the wire.

Three further findings fall out of the same reading:

* The `--expr-syms=` command-line option is **parsed and then never retrieved.**
  `las-sc` never opens `/usr/share/vx_ee.scm`; the only file it opens at runtime
  is `/sys/class/thermal/thermal_zone0/temp`.
* **18 of the 115 `_m` entries name expression-engine symbols that do not exist
  in `/usr/share/vx_ee.scm`** (`l1d`, `l1ta`, `l1td`, `l1ph` and the same four
  for LFOs 2–4, plus `e3h` and `fmidx`). The table is stale as well as unused.
* `las-sc` does **not** own the flat `/p/…` voice namespace. It knows a list of
  372 parameter *suffixes*, but it uses them only to build the **hierarchical**
  `/p/part/t/N/…` keys of a startup lookup table, and it only ever *acts* on the
  effects/mixer subset. The flat namespace lives in `las-frontend`, which talks
  to the voice controller directly (`--host-vc=vc`).

---

## 1. How this was read (method, so it can be repeated)

`las-sc` is CHICKEN Scheme compiled to C and then to ARM. It is `strip`ped, but
three CHICKEN artefacts survive and together give near-source-level visibility:

1. **A procedure table in `.data`.** Pairs of `{char *name, void *fn}` where the
   name is `f_<n>:<mangled source file>`. 7,351 entries across 14 compilation
   units. `[READ]` first entry at file offset `0x24BC18`:
   `4a 9e 21 00 | 34 c0 0d 00` → name VMA `0x00219E4A` = `"f_3028:las_2flas_2doscl_2escm"`, code VMA `0x000DC034`.
   This yields a **complete function-name map for every address in `.text`**.
2. **Call-site trace strings.** Every non-inlined call is preceded by
   `C_trace("<file>:<line>: <callee>")`. 4,126 distinct strings, 5,299
   references. This yields a **source-file/line map over `.text`**, and by
   inversion a partial reconstruction of each source file's structure.
3. **The literal frame (`lf[]`) initialiser.** The module top-level calls
   `C_h_intern(&lf[i], len, "name")` for every global symbol and
   `C_decode_literal(C_heaptop, "<encoded>")` for every quoted constant, storing
   each into `lf[i]`. Decoding these gives **every global's name and every
   quoted constant, keyed by `lf` slot**; scanning `.text` for
   `ldr rX,[lfbase,#off]` then gives **exact use counts per global**.

Address arithmetic used throughout: for `.text`/`.rodata`, *file offset =
VMA − 0x10000*; for `.data`/`.bss`, *file offset = VMA − 0x20000* (there is a
0x10000 page gap between the RO and RW segments). `[READ]` section table:
`.text` VMA `0x11650` size `0x1DEF3C`; `.rodata` VMA `0x1F0594` size `0x5E898`;
`.data` VMA `0x25F088` size `0x22E20`; `.bss` VMA `0x281EA8` size `0x4090`.

**CHICKEN literal encoding** (needed to read the tables below), recovered
empirically and consistent across the whole `.rodata`: every item is prefixed
`FE`; then a type byte — `42` string, `01` symbol, `03` pair, `00` vector,
`FF` immediate — then for string/symbol/pair/vector a 3-byte big-endian count,
then the payload. `FE FF 0E` is the empty list. `[READ]`

The `sc` module's literal frame base is `0x281EC8` `[READ]`, established because
the first `C_h_intern` in the top-level stores to `lf+0` and its name string is
`"DEBUG"`, and every later store is at `lf+4·i` (`0x12138`…).

---

## 2. Binary identity and how it is launched

| fact | value | grade |
|---|---|---|
| path | `usr/bin/las-sc` | `[READ]` |
| size, 1.8.2 | 2,499,540 bytes | `[READ]` |
| size, 1.5.0 | 2,498,948 bytes | `[READ]` |
| type | ELF 32-bit LSB, ARM EABI5, dynamically linked, `/lib/ld-linux-armhf.so.3`, **stripped** | `[READ]` |
| self-reported version | `/info/version` and `/info/git` both answer the string `"0.2.6"` | `[READ]` lf `0x282B38`, `0x282B40`; sc/sc.scm:333, :336 |
| compilation units | `sc/sc.scm` (with `sc/fx.scm`, `sc/routing.scm`, `sc/timbre-tree.scm` textually included), `las/las-comm.scm`, `las/las-oscl.scm`, `las/las-measure.scm`, `las/las-vox.scm`, `las/las-math.scm`, `las/sockutil.scm`, `cal/cal.scm`, `cal/search.scm`, `cal/jobs.scm`, `cal/vxtune-db.scm`, `mon/vxmon-lib.scm`, `mon/table.scm`, `vxfw-lib.scm` | `[READ]` procedure table + trace strings |

Observed invocation `[READ]` (`captures/arch-harvest/runtime-state.txt:103`; the
caveat file explicitly says the `las-sc` argv in that snapshot is uncontaminated):

```
/usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300
  --vxfw=/usr/share/xmosfw/app_vx_10M_v2.1.0.bin --vxdb=/var/tuning.vxtune
  --vcfw=/usr/share/xmosfw/app_las_v2.1.2.bin --vcfv=33620735 --temp
  --expr-syms=/usr/share/vx_ee.scm --panel-state=localhost:9500 -q
```

### 2.1 The full option grammar

`[READ]` — help strings at file offsets 1989628…1991540, option name lists as
decoded `lf` literals, retrieval sites as `alist-ref*` call sites in
`sc/sc.scm:826` and `:854`–`:884`.

| long option | help text (verbatim from `.rodata`) | value retrieved at runtime? |
|---|---|---|
| `--target` (`-t`) | "Xmos Target address" | yes, `sc.scm:854`, default `"vc"` |
| `--fx` | "FX Server address (optional)" | yes, `sc.scm:855` |
| `--manual-fx` | "Flag to indicate that fx will be booted manually, but that las-sc should still attempt to connect." | yes, `sc.scm:856` |
| `--listen` (`-l`) | "Listen address (default localhost:9300" *(sic — unbalanced paren in the firmware string)* | yes, `sc.scm:857`, default `"localhost:9300"` |
| `--vcfw` | "Voice control firmware file. If not given, VC is not not checked or updated." *(sic — doubled "not")* | yes, `sc.scm:858` |
| `--vcfv` | "Expected voice control firmware version." | yes, `sc.scm:859`, default `"0"` |
| `--vxfw` | "Voice card firmware file. If not given, voice cards are not checked or updated." | yes, `sc.scm:860` |
| `--mod` | "Flag for VX HW Mod." | yes, `sc.scm:861` |
| `--vxdb` | "Voice Card Tuning Data" | yes, `sc.scm:862` |
| `--force-vx-update` | "Update VX firmware even if versions match." | yes, `sc.scm:863` |
| `--panel-state` | "Panel state query address." | yes, `sc.scm:864` |
| `--temp` | "Enable SOM temperature polling." | yes, `sc.scm:870` |
| `--mode` | "Put VC in given mode at startup" | yes, `sc.scm:871`, default `"normal"` |
| `--cli` | "Command-line interface mode - updates firmware, then exits without launching fx." | yes, `sc.scm:884` |
| `--quiet` (`-q`) | "Keep silent during operation" | yes |
| `--help` (`-h`) | "Display usage text" | yes, `sc.scm:826` |
| **`--expr-syms`** | **"File containing symbols for use in expressions."** | **NO — see §6** |
| `--ofs-cache` (`-o`) | "Offset cache file. If given, offset data are periodically gathered from the VX and written to this file. At startup, offsets are transmitted back to the cards." | **NO** |
| `--version` (`-v`) | "Display version information and exit." | **NO** |

"Retrieved at runtime" means: an `alist-ref*` call site exists whose key symbol
is that option. `[READ]` — the 16 `alist-ref*` sites at `0x6DDE8`…`0x6EF80` and
`0x8D4D8`, each paired with the symbol loaded immediately after it. The three
options marked **NO** appear only in the grammar-construction literals
(`lf[0x28314C] = ('expr-syms)`, `lf[0x2831B0] = ('o 'ofs-cache)`,
`lf[0x28319C] = ('v 'version)`), each read exactly once, at
`0x91984` / `0x905BC` / `0x90910`, all inside `srfi-37#option` construction.

---

## 3. The four links `las-sc` sits between

```
                    UDP 127.0.0.1:9300  (bound; -l)
  las-frontend ───────────────────────► las-sc
   (and others)                          │  │  │
                                         │  │  └─► UDP <fx>:57120   "send-fx"      → sclang / efx_server.scd
                                         │  └────► UDP vc:7770      "send-target"  → XMOS voice controller
                                         │         and "las-send"/"las-query"
                                         └───────► UDP localhost:7775 (-f, frontend)
                                                   and localhost:9500 (--panel-state)
```

| link | evidence | grade |
|---|---|---|
| listen socket is **UDP, bound to 127.0.0.1:9300** | `netstat -lnu` in `runtime-state.txt:136` shows `udp 127.0.0.1:9300`; the caveat file lists network state as uncontaminated. Code: `sc.scm:941` `string->bound-socket` with `socket#sock/dgram`; `sc.scm:172` `(osc-decode (udp6#udp-recv sock))` | `[READ]` |
| `vc` resolves to **203.0.113.2** over `usbint` (host side 203.0.113.1) | `etc/hosts` line 2: `203.0.113.2 vc`; `etc/network/interfaces` `iface usbint inet static / address 203.0.113.1` | `[READ]` |
| `las-sc` ↔ voice controller is **UDP port 7770** | `captures/voicebus-midi-20260903-183251.pcap`: 10 packets `203.0.113.1:59892 → 203.0.113.2:7770` and 10 back, payload OSC address `/therm/sys-temp`. `/therm/sys-temp` is emitted only by `las-sc` (`sc.scm:229`, `las-send`) | `[READ]` wire + `[READ]` code |
| the VC's **9100** port is the front-panel/LED/keyboard service used by `las-frontend`, not by `las-sc` | same pcap: `/lfoleds`, `/clkleds`, `/lb /lk /cb /ck /cenc /rb /rk /lhcb /lhck`, `/seqleds`, `/lsleds`, sources 9500/9600/ephemeral | `[READ]` |
| FX server default port **57120** | literal `":57120"` at `lf[0x282C68]`, read at `sc.scm:425` next to `string-index`/`string-take` — i.e. "append `:57120` if the address has no colon" | `[READ]` |
| panel-state default port **9500** | literal `":9500"` at `lf[0x282C70]`, read at `sc.scm:445`, same idiom | `[READ]` |
| the FX server is sclang running `efx_server.scd`, and it implements the `/fxN/...` responders `las-sc` emits | `arch-harvest/efx_server.scd`, 31 `OSCdef` definitions: `ping`, `fx<N>`, `fx<N>_ctl/_dry/_dig_dry/_wet/_en/_g-in/_g-out/_in/_out/_mix/_pan/_par/_sends`, `fx_bus-mode`, `fx_hardware-rev`, `fx_stereo_spread`, `fxstart`, `fxstate`, `send1Gain`… | `[READ]` |
| `las-sc` writes a cookie file `…/las-sc.cookie` at startup | literal `"/las-sc.cookie"` `lf[0x282C30]`, read at `sc.scm:419`, alongside `create-directory` (`:417`) and `with-output-to-file` (`:420`) | `[READ]` |

`send-fx` (`sc/sc.scm:180–185`) and `send-target` (`sc/sc.scm:188–194`) are both
`(udp6#udp-send <sock> (csosc#osc-encode msg))` followed by an optional log
`[READ]` (trace strings `sc/sc.scm:182: udp6#udp-send`,
`sc/sc.scm:191: udp6#udp-send`; globals defined at `0x8D0F4` and `0x8D118`).
`osc-udp-sendto` (`sc.scm:176`) is the address-carrying variant. Which `sec`
field each closure captures is `[INFERRED]` from the names plus
`sc.scm:921` `(set-sec! … target-sock (las-port-sock port))` `[READ]`.

---

## 4. The address inventory

`las-sc` holds exactly **three** address tables, all as CHICKEN quoted literals
decoded once at module start-up. Every `/p/…` string in the binary belongs to
one of them.

| table | `lf` slot | file offset of the encoded blob | entries | what it is |
|---|---|---|---|---|
| **A** per-timbre parameter suffixes | `0x2826A0` | 1,970,101 (`0x1E0FB5`, VMA `0x1F0FB5`) | **372** | suffixes appended to `/p/part/t/N` by `make-timbre` |
| **B** global / non-timbre addresses | `0x2832A8` | 1,991,553 (`0x1E6381`, VMA `0x1F6381`) | **90** (85 plain strings + 5 explicit `(in out)` pairs) | appended to the same database by `append` at `timbre-tree.scm:570` |
| **C** `expression-nodes` | `0x2826A8` | 1,977,648 (`0x1E2D30`, VMA `0x1F2D30`) | **117** (`/p/pre-expr`, `/p/post-expr`, 115 `_m` twins) | **never read — see §6** |

`[READ]` for all three: the encoded blob VMA appears exactly once in the whole
file, in the top-level literal pool (`0x464C`, `0x9230`, `0x4658` respectively),
and each is stored into the `lf` slot shown.

Counts that follow directly:

* A + B is the whole "preset database": 3 × 372 + 90 = **1,206 keys**. `[INFERRED]`
  from `make-timbre` being called three times (`timbre-tree.scm:680,681,682`,
  with the literal fixnum arguments 1, 2, 3 `[READ]`) and the `append` at
  `timbre-tree.scm:570`.
* `strings` shows **500** lines beginning `/p/` (498 unique) and 116 ending in
  `_m`. `[READ]` These counts are approximate: because the literals are stored
  in CHICKEN's length-prefixed encoding with no NUL terminators, 9 of the 115
  `_m` addresses merge with adjacent bytes and never appear as standalone lines,
  while `/mix_m` (a different, live literal, `sc/fx.scm:724,883`) adds two.
  **The authoritative counts are the decoded literals: 372 / 90 / 117.**
* Of the 372 suffixes, only **76** are rewritten to an outgoing address by
  `make-outgoing-address`: 27 `/p/fx/…`, 22 `/in/…`, 15 `/a/…`, 12 `/mix/…`.
  The remaining 296 (`/en` and 295 `/p/…` voice-parameter suffixes) fall through
  and are not rewritten. `[READ]` — see §5.5 for the rewriter, §A for the table.

The word "`/p/part/t/`" is the literal used to build the hierarchical form:
`lf[0x28269C] = "/p/part/t/"`, read at `timbre-tree.scm:8` in the body of the
`make-timbre` loop (`(fmt #f "/p/part/t/" n <suffix>)`). `[READ]`

---

## 5. Dispatch — what actually runs

### 5.1 Receive

`sc/sc.scm:172` `(csosc#osc-decode (udp6#udp-recv sock))`. `[READ]`
Messages arrive on three `gochan` channels selected in `server-loop`
(`sc.scm:281`, `gochan#gochan-select*`) and in the startup loop (`sc.scm:378`).
`[READ]`

### 5.2 `part-dispatch` — the only handler for inbound `/p/…`

Defined at `0x8D1E8` as `f_19056`, whose body starts at `sc/sc.scm:234` with
`csosc#osc-adr`. `[READ]` It is a flat `cond` of `string-prefix?` tests, in this
exact order `[READ]` (literal + trace-line pairs):

| line | prefix tested | handler |
|---|---|---|
| 237 | `/p/part/t/1/p/fx` | `insert-fx-parse` |
| 237 | `/p/part/t/2/p/fx` | `insert-fx-parse` |
| 238 | `/p/part/t/3/p/fx` | `insert-fx-parse` |
| 239 | `/p/part/t/1/mix` | `mix-message-parse` |
| 240 | `/p/part/t/2/mix` | `mix-message-parse` |
| 241 | `/p/part/t/3/mix` | `mix-message-parse` |
| 242 | `/p/part/las-fx` | `master-fx-parse` |
| 243 | `/p/part/mix` | `main-mix-parse` |
| 245–247 | `/p/part/t/{1,2,3}/p/pan` (exact) | `pan-message-parse` |
| 248–250 | `/p/part/t/{1,2,3}/p/g` (exact) | `gain-message-parse` |
| 251 | `/status` | `handle-status-messages` |
| 252 | `/info` | `handle-status-messages` |
| — | anything else | **falls through and is discarded** |

The fall-through is visible in the machine code. `[READ]` At `0x38F78`:

```
38f78: e3570006   cmp  r7, #6          ; r7 = result of (string-prefix? "/info" adr); #6 = C_SCHEME_FALSE
38f7c: 0a000011   beq  0x38fc8         ; if false -> skip the handler
38f80..38fc4:     C_trace("sc/sc.scm:252: handle-status-messages"); call handle-status-messages
38fc8: e5953014   ldr  r3, [r5, #0x14] ; the continuation
38fcc: e3a00002   mov  r0, #2          ; argc = 2  (k + one value)
38fd4..38fe4:     invoke k with [r5,#0xc] -- no message is sent anywhere
```

**This is the code path an unmatched `/p/pre-expr` takes.** `[READ]`

So the *dispatched* inbound surface of `las-sc` is:

* `/p/part/t/{1,2,3}/p/fx/…` — 27 suffixes each (the `/p/fx/…` block of table A)
* `/p/part/t/{1,2,3}/mix/…` — 12 suffixes each
* `/p/part/t/{1,2,3}/p/pan`, `/p/part/t/{1,2,3}/p/g`
* `/p/part/las-fx/…` — 49 addresses in table B
* `/p/part/mix/…` — the `/p/mix/*-db`-shaped and `ext-dir3/4` entries reached
  through `main-mix-parse`
* `/status`, `/info…`

= **123 per-timbre addresses + the master-FX and main-mix blocks + status/info.**
`[INFERRED]` — counted from tables A and B against the prefix list above.

### 5.3 `handle-status-messages` (`sc/sc.scm:325–362`)

`[READ]` literals and trace lines:

| in | behaviour |
|---|---|
| `/info/version` | replies `("/info/version" "0.2.6")` |
| `/info/git` | replies `("/info/git" "0.2.6")` |
| `/info/vc-version` | `las-query` the VC with `/info/version`, relay the value back as `/info/version` |
| `/info/vc-git` | `las-query` the VC with `/info/git`, relay back as `/info/git` |
| `/info/voice-count` | `las-query` the VC with `/v/voices`, relay back as `/info/voice-count` |
| `/status` | replies `("/status" <one of the twelve strings below>)` |

Reply routing: `sc.scm:329` tests `udp6#udp-socket?`; if the reply target is not
already a socket it is created with `connect-to-socket*` (`:330`). `[READ]`

The twelve status strings, verbatim `[READ]` (`sc.scm:351`–`:362`,
`lf[0x282B64…0x282BBC]`):

```
Sound engine is started and operating normally.
Sound engine is started, but no patch data has been received.
Sound engine is starting.
Sound engine controller is updating VC firmware.
Sound engine controller is updating VX firmware.
Failed to enumerate VX.
Sound engine controller is updating tuning data.
Sound engine controller is verifying tuning data.
Sound engine is started, but voices may not be in tune.
Sound engine is running, but effects are not running. 
Sound engine is unavailable.
Voices are not tuned.
```

(The tenth has a trailing space in the firmware.)

### 5.4 `dispatch` and `startup-dispatch`

* `dispatch` = `f_19230`, body from `sc/sc.scm:256` (`csosc#osc-bundle?`). For a
  bundle it applies `set-insert!` (`:261`–`:267`) and `set-master!`
  (`:269`–`:273`) per message, then logs. `[READ]`
* `startup-dispatch` = `f_19884`, body from `sc/sc.scm:365`; same bundle test,
  then `handle-status-messages` at `:375`. `[READ]`
* After a bundle, `server-loop` calls `update-busses` (`:290`),
  `update-insert-fx` ×3 (`:291`–`:293`) and `update-master-fx` ×2 (`:295`,
  `:296`) — i.e. the effects graph is recomputed once per bundle rather than per
  message. `[READ]`

### 5.5 `make-outgoing-address` / `handle-t-prefix` — the rewriter

`make-outgoing-address` = `f_15856`, body at `sc/timbre-tree.scm:711`.
`handle-t-prefix` = `f_15858`, body at `sc/timbre-tree.scm:690`. `[READ]`
Reconstructed from the `string-prefix?` literals and the `fmt` format literals
at each trace line `[READ]`:

```
make-outgoing-address(adr):
  711 if adr starts "/p"
  712   r = cdr(adr)                       ; drop "/p"
  713   if r starts "/part"
  714     r2 = cdr(r)                      ; drop "/part"
  715     if r2 starts "/t/"
  716       r3 = cdr(r2)                   ; drop "/t"
  717/719/721  if r3 starts "/1" | "/2" | "/3"  -> handle-t-prefix(cdr(r3), N)
  724     elif r2 starts "/mix"  -> 725 cdr, 728 "/midi", 730 drop, 731 "/las-fx"
  735     elif ... "/mix"        -> 736 cdr
  752   else (non-/part)  754 "/r/din-out" via drop
                          757 "/r/g/0", "/sys/direct-kbd"
                          760 "/a" -> 761 cdr
                          766 "/m" -> 767 cdr

handle-t-prefix(rest, N):
  691 if rest starts "/mix"                 -> 693  "/g/" N "/t"  rest
  694 elif rest starts "/p"
  695   r = cdr(rest)
  696   if r starts "/fx"                    -> 699  "/g/" N "/t" + drop("/p/part/t/1/p")
  700 elif rest starts "/in"                 -> 701  "/r/g/" N ...
  702 elif rest == "/a/unspecified_mono"     -> 703  "/g/" N "/a/mono"
  704 elif rest starts "/a"                  -> 705  "/g/" N "/a" cdr(rest)
```

The literal `"/p/part/t/1/p"` at `lf[0x2826C4]`, read at
`timbre-tree.scm:699` next to `string-drop`, is used as a *fixed-length* prefix
to strip — 13 characters — which works for all three timbres because the
timbre digit is at a fixed position. `[READ]` (This is a fragile idiom but it is
what the firmware does.)

So the outgoing namespaces `las-sc` synthesises are `/g/N/t/…`, `/g/N/a/…`,
`/r/g/N/…`, `/r/din-out`, `/sys/direct-kbd`. `[READ]`

### 5.6 `sec-table` — the startup lookup table

At `sc/sc.scm:449` the program iterates `preset-dbase` and at `:472` does
`(hash-table-set! <table> <adr> (list <make-outgoing-address adr> <x>))`
— the value is built by `C_a_i_list` with count 2 immediately before the call.
`[READ]` (`0x5DF74`: `mov r1,#2 ; bl C_a_i_list`). At `:480`–`:482` a second loop
inserts the five explicit `(in out)` pairs from table B verbatim. `[READ]`

There is exactly **one** `make-hash-table` call in the `sc` module
(`f_16679` at `0x4267C`, `sc/sc.scm:165`, inside `make-sec`) `[READ]`, so that
one table is `sec`'s `table` field and is the one both loops populate.

It is read from **24 sites** `[READ]`:

* `sc/routing.scm:11,12,13,24–35,47–50,71` — 20 sites, the mixer/insert routing
  state machine, using `sub-tnum` (`sc/sc.scm:213–218`, `number->string` +
  `string-replace`) to substitute the timbre number into key templates such as
  `"/p/part/t/n/p/fx/ins/en"` (`lf[0x282660]`), `"timbre-n-dir1-en"`,
  `"timbre-n-dir4-en"`. `[READ]`
* `sc/fx.scm:856,857` — 2 sites.
* `sc/sc.scm:30` — inside `key->osc`, **which is never called** (§6.3).
* `sc/sc.scm:209` — inside `is-value-new?`, **which is never called** (§6.3).

---
## 6. The priority question: `/p/pre-expr` and `/p/post-expr`

### 6.1 What the table actually is

`lf[0x2826A8]` holds a 117-element list of two-element lists. The first and last
entries are the odd ones out: they pair an address with the **empty list**
instead of a symbol.

Raw bytes `[READ]` at file offset `0x1E2D30` (VMA `0x1F2D30`):

```
001e2d30:  FE 03 00 00 02              ; cons cell of the outer list
           FE 03 00 00 02              ; cons cell of the entry
           FE 42 00 00 0B "/p/pre-expr"; string, 11 bytes
           FE 03 00 00 02              ; cons
           FE FF 0E                    ; '()   <- second element
           FE FF 0E                    ; '()   <- list terminator
001e2d5b:  FE 03 00 00 02              ; next outer cons
           FE 03 00 00 02
           FE 42 00 00 0A "/p/o1/po_m"
           FE 03 00 00 02
           FE 01 00 00 04 "o1po"       ; symbol
           FE FF 0E
```

i.e. the list is

```scheme
(("/p/pre-expr" ())
 ("/p/o1/po_m"  o1po)
 ("/p/o1/d_m"   o1d)
 …
 ("/p/pan_m"    pan)
 ("/p/post-expr" ()))
```

`/p/post-expr` is the last entry, at file offset 1,982,629 (`0x1E40A5`), with the
same `()` shape. `[READ]`

The 115 middle entries map an `_m` address to a **name in the VX expression
engine's `results` section** — i.e. these are addresses whose intended meaning is
"modulation contribution to expression-engine destination *X*". The pairing is
one-way and lossy: `/p/o1/fm1_m`, `/p/o1/fm2_m` and `/p/o1/fm3_m` all map to the
single symbol `o1fm`, and `/p/noise/{am,dm,s,rm}_m` map to the **EG 1** symbols
`e1am`/`e1dm`/`e1s`/`e1rm`. `[READ]`

### 6.2 The dispatch code does not exist

This is the load-bearing finding, so here is the whole chain of evidence.

1. The encoded blob's VMA `0x1F2D30` appears **exactly once** in the entire
   2.5 MB file, at file offset `0x4658` — a literal-pool slot in the module
   top-level. `[READ]` (byte search for `30 2D 1F 00`.)
2. That pool slot feeds one `C_decode_literal` whose result is stored into
   `lf[0x2826A8]` (`lf` base `0x281EC8` + `0x7E0`). `[READ]`
3. `lf[0x2826A8]` is loaded **once**, at `0x8C530`, and `lf[0x2826A4]` — the
   interned symbol `expression-nodes` — is loaded **once**, at `0x8C528`,
   four instructions earlier. `[READ]`
4. Those two loads are the two halves of one global definition:

```
8c528: e59807dc   ldr r0, [r8, #0x7dc]   ; r8 = 0x281EC8 -> lf[0x2826A4] = symbol expression-nodes
8c52c: e286600c   add r6, r6, #12
8c530: e59817e0   ldr r1, [r8, #0x7e0]   ; lf[0x2826A8] = the 117-element list
8c534: e2800004   add r0, r0, #4         ; &symbol->value
8c538: ebfff89f   bl  0x8a7bc            ; C_mutate  ==  (define expression-nodes '(...))
```
   `[READ]`

5. A full scan of `.text` for every `ldr rX,[rY,#imm]` and `ldr rX,[rY,rZ]`
   whose base register was loaded from a literal pool holding a known `lf` base
   finds **no other read of either slot**. `[READ]` Cross-checked by a plain
   textual grep of the disassembly: `#0x7dc]` occurs twice and `#0x7e0]` five
   times in the whole binary, and in every case but the two above the base
   register is a different module's `lf` array or a closure pointer.
6. The method is not blind to live globals: run against `part-dispatch`
   (`lf+0xC08`) it finds 4 call sites plus the define; against `sub-tnum`
   (`lf+0x5A8`) 17 plus the define. `[READ]`
7. The strings `pre-expr`, `post-expr` and `_m`-suffixed addresses occur
   **nowhere else in the entire 1.8.2 root filesystem** — not in
   `las-frontend` (145 MB), not in `lassvc`, not in any script.
   `[READ]` `grep -rl` over the whole rootfs returns only `usr/bin/las-sc`.
8. There is no dynamic construction either: `las-sc` contains no literal `"_m"`
   suffix string and no `string-append`-style site that would build one.
   `[READ]`
9. **The same is true in 1.5.0.** In `captures/rootfs-1.5.0/usr/bin/las-sc` the
   `expression-nodes` symbol interns to `lf` slot `0x282454` at `0x14E74`, the
   blob sits at the same file offset 1,977,648, its VMA is referenced once at
   `0x4658`, and the slot is read once, at `0x8C528`. `[READ]`

**Conclusion (`[READ]`, not inference):** `las-sc` 1.5.0 and 1.8.2 both compile
in the `expression-nodes` table and neither ever consults it. There is no
argument type it would accept, no timbre or voice selector that would unlock it,
no deferred compile-and-store. It is not "waiting for a note event"; the code
that would look at it does not exist.

**Therefore:** an OSC message to `/p/pre-expr` on `127.0.0.1:9300` is decoded by
`osc-udp-receive`, handed to `part-dispatch`, tested against twelve prefixes,
matches none, and the `cond` returns without sending anything. `las-sc` survives
because nothing throws. Exactly the observed behaviour. The string argument
`"1 0 * pan sto"` was never parsed, because nothing in `las-sc` parses
expression source — the binary contains no tokeniser, no RPN evaluator, and the
words `matrix` and `modmatrix` occur zero times. `[READ]`

### 6.3 Two more dead globals in the same neighbourhood

Established by the same scan `[READ]`:

* **`key->osc`** (`sc/sc.scm:29–30`, `(hash-table-ref …)`) — `lf[0x281EE4]`,
  read once, at its own `define` (`0x8A888`). The documented accessor for the
  address map is never called; `routing.scm` and `fx.scm` inline the
  `hash-table-ref` instead.
* **`is-value-new?`** (`sc/sc.scm:207–210`) — `lf[0x282AAC]`, read once, at its
  own `define` (`0x8D17C`). Whatever change-detection it implements is not
  wired up.

### 6.4 `--expr-syms` is accepted and ignored

* The option is declared: help text at file offset 1,989,628, long-name literal
  `("expr-syms")` at `lf[0x283150]`, keyword `('expr-syms)` at `lf[0x28314C]`.
  `[READ]`
* Each of those two literals is read exactly once — at `0x28698` and `0x91984`,
  both inside `srfi-37#option` grammar construction. `[READ]`
* No `alist-ref*` site retrieves it. The 16 retrieval sites are enumerated in
  §2.1. `[READ]`
* `las-sc` never opens the file. The only `open-input-file` in the binary is
  `sc/sc.scm:223`, whose literal argument is
  `"/sys/class/thermal/thermal_zone0/temp"` (`lf[0x282ACC]`) — the SOM
  temperature poller that emits `/therm/sys-temp` every cycle. `[READ]`
* The string `vx_ee` does not occur in `las-sc`. `[READ]`

**So `--expr-syms=/usr/share/vx_ee.scm` on the running instrument does nothing.**
The file is real and is the authoritative symbol list for the *voice
controller's* expression engine, but `las-sc` is not its consumer.

### 6.5 The table is stale, independently of being unused

18 of the 115 `_m` entries name symbols that are **not present** in
`/usr/share/vx_ee.scm` (which is byte-identical across 1.5.0, 1.8.2 and the live
harvest — md5 `5e5c02c1e5a95c79e4e7c52843eb4408`). `[READ]`

| `_m` address | symbol in table | nearest symbol that exists in `vx_ee.scm` |
|---|---|---|
| `/p/l{1,2,3,4}/d_m` | `l{1,2,3,4}d` | `l1dm` … `l4dm` (delay time multiplier) |
| `/p/l{1,2,3,4}/ta_m` | `l{1,2,3,4}ta` | `l1fim` … (fade-in time multiplier) |
| `/p/l{1,2,3,4}/td_m` | `l{1,2,3,4}td` | `l1fom` … (fade-out time multiplier) |
| `/p/l{1,2,3,4}/ph_m` | `l{1,2,3,4}ph` | — no phase destination exists |
| `/p/e3/hm_m` | `e3h` | `e3hm` |
| `/p/fm_m` | `fmidx` | `ofm` |

`[READ]` — set difference between the 115 symbols in the table and the
identifier set of `vx_ee.scm` with comments stripped.

That the table names destinations the engine does not have, and has never been
corrected across at least two firmware generations, is consistent with it never
having been executed. `[INFERRED]`

---

## 7. What the 115 `_m` twins are for, and who writes them

**Nobody, on this instrument.** `[READ]` §6.2 items 7–9.

What can be said about their *intended* meaning `[INFERRED]`, from the table's
own shape and from `vx_ee.scm`'s prose:

* Each `_m` address is the flat parameter address plus `_m`, paired with an
  expression-engine **`results`** symbol. `vx_ee.scm` says of `results`:
  "variables applied to the hardware. Most of the LAS expression addresses
  result in a storage to one of these." So an `_m` address is the *modulation
  sum* landing on that destination — the value the expression program `sto`res.
* Consistent with the previously observed live behaviour that `_m` addresses are
  "delivered and ignored": they are not writable inputs anywhere in `las-sc`.
  Whether the **voice controller** implements them is `[UNKNOWN]` — see §7.1.
* `/p/pre-expr` and `/p/post-expr` sit at the two ends of the same list with a
  `()` where the destination symbol would be, which reads as "these two are
  addresses in the same family but are not per-destination". `[INFERRED]`

### 7.1 Could the voice controller still implement `/p/pre-expr`?

`[UNKNOWN]`, and it cannot be settled from the files on disk.
`usr/share/xmosfw/app_las_v2.2.2.bin` (the VC image shipped in 1.8.2) contains
**no printable OSC address strings at all** — not `/ping`, not `/mode`, not
`/p/`, not the `/lb`/`/cb` panel addresses that are demonstrably live on the
wire. Only 110 printable runs of ≥6 characters in a 2 MB image, and 246,218
non-zero bytes. `[READ]` The image is compressed or otherwise encoded, so
absence of the string is not evidence of absence of the endpoint.

What *is* established: if the VC does implement `/p/pre-expr`, **`las-sc` is not
the route to it.** Anything addressed to `las-sc`'s 9300 socket is dropped. The
only components that speak to the VC's `/p/…` namespace are `las-frontend`
(which contains 1,832 occurrences of `/p/o1/po` and 672 of
`/p/part/t/1/p/o1/po`, and is invoked with `--host-vc=vc`) `[READ]` and
`las-sc`'s own `send-target`/`las-send` for the narrow set in §8.2.

---

## 8. The `las-sc` → voice-controller protocol

| property | value | grade |
|---|---|---|
| transport | UDP, **connected** datagram socket | `[READ]` `las/sockutil.scm:35–38` `socket#address-information` + `socket#socket-connect/ai`, and `las/las-comm.scm:100,112` passing `socket#sock/dgram` |
| peer | host from `-t` (default `"vc"`) = 203.0.113.2, **port 7770** | `[READ]` `etc/hosts`; pcap `/therm/sys-temp` on 7770 |
| framing | plain OSC 1.0 messages, no bundles, one message per datagram | `[READ]` `csosc#osc-encode` at `las-comm.scm:184`; observed payloads in the pcap begin with the address string, no `#bundle` |
| host→VC address parsing | `parse-host-port` splits on `":"`; if no port is given the port slot is `#f` and a default is applied downstream | `[READ]` `sockutil.scm:23` `string-split` with literal `":"`; `sockutil.scm:28–30` two `values` returns |
| request/response | `las-query` sends, then polls `socket#socket-receive-ready?`, `socket#socket-receive`, `csosc#osc-decode`, and matches `csosc#osc-adr` against the request address | `[READ]` `las-comm.scm:193–204` |
| retry | on exception: log `"Exception on socket send: … -- reconnect & retry"`, `pause-for`, `las-reconnect-socket`, loop; after N tries raise `"Unable to connect to socket after <n> tries"` | `[READ]` `las-comm.scm:170–175,215` |
| concurrency | one RX thread per port plus two `gochan`s (`cmd-chan`, `query-chan`); `las-port-call` serialises through them | `[READ]` `las-comm.scm:118,119,127–150,154–158` |
| open handshake | `string->connected-socket` → `(las-query port (osc "/ping"))` → `(osc "/mode" <mode>)` → `las-voice-count` | `[READ]` `las-comm.scm:100,101,120,121` |
| failure text | `"Unable to determine voice count"` | `[READ]` `lf[0x28345C]`, `las-comm.scm:152` |

### 8.1 Sub-ports

`las-comm.scm` defines a family of port objects, each with its own socket and
reply channel: `las-port` (the VC), `las-card-port` (`las-card-open`,
`las-card-send`, `las-card-query`, `las-card-query-string`,
`las-card-query-uint`), `las-vox-port` (`las-vox-open`, `las-vox-send`,
`las-vox-query`), `las-oscl-port` (`las-oscl-open`, oscillator measurement) and
`las-open-clock-socket` / `las-query-clock`. `[READ]` — struct accessor symbol
names in the `lf` frame at `0x283338`…`0x283C14`. Their port numbers are
`[UNKNOWN]` from static reading.

### 8.2 Everything `las-sc` sends to the voice controller

`[READ]` — literal + trace-line pairs.

| address | site | note |
|---|---|---|
| `/ping` | `las-comm.scm:101` | link check on open |
| `/mode` | `sc.scm:933` via `las-send`, and `las-comm.scm:120` on open | argument is the `--mode` string, default `"normal"`; log line `"setting mode to "` |
| `/therm/sys-temp` | `sc.scm:229` via `las-send` | SOM die temperature, polled in a loop with `pause-for`; enabled by `--temp` |
| `/info/version`, `/info/git` | `sc.scm:336,339` via `las-query` | relayed to the caller as `/info/vc-version` / `/info/vc-git` |
| `/info/versionb` | `sc.scm:775` | VC bootloader/secondary version |
| `/v/voices` | `sc.scm:346` via `las-query` | voice count |
| `/v/<n>/load_tuning` | `sc.scm:601` | built with `fmt` from literal `"/v/"` + `"/load_tuning"` |
| `/v/<n>/load_cal` | `sc.scm:602` | ditto with `"/load_cal"` |
| `/vx/0/info/hwrev` | `sc.scm:953` | log line `"found VX with gain mods"` nearby |
| `/g/N/t/mix/…`, `/g/N/t/fx/…`, `/g/N/a/…`, `/r/g/N/in/…` | via `send-target`, from `make-outgoing-address` | the rewritten preset addresses |
| `/a/in1-ins4`, `/a/in2-ins3` | `routing.scm:61,63` via `send-target` | analogue input→insert routing |
| `/a/dir{1,2,3,4}-aux{1,2,3,4}`, `/a/subl-en`, `/a/subr-en`, `/t/mix/*-en`, `/out`, `/in` | `fx.scm:235–339, 449–508` via `send-target` | analogue bus matrix |
| `/cal/…` (large family) | `cal/cal.scm` via `las-send` | calibration; out of scope here, see `docs/arch/cal-dispatch.md` |
| `/fw/version`, `/info/versionb` | `vxfw-lib.scm` | firmware update path |

### 8.3 Everything `las-sc` sends to the FX server (sclang, UDP `<fx>:57120`)

`[READ]` — `send-fx` call sites in `sc/fx.scm` and `sc/sc.scm:442`.

`/ping`, `/fx/hw-rev`, `/fx/bus-mode`, `/fx/spread`, `/fx{0,1,2}/in`,
`/fx{0,1,2}/out`, `/fx{0,1,2}/par`, `/fx{0,1,2}/sends`, `/fx{0,1,2}/pan`,
`/fx{0,1,2}/dry`, `/fx{0,1,2}/dig-dry`, `/fx{0,1,2}/g-out`, and the
runtime-numbered `/fxN`, `/fxN/en`, `/fxN/pan`, `/fxN/mix`, `/fxN/g-in`,
`/fxN/g-out`, `/fxN/p/<i>` — where `N` is substituted at run time (the literal
`"/fxn/p/"` at `lf[0x282474]`/`lf[0x282528]` is a template).
Every one of these has a matching `OSCdef` in `arch-harvest/efx_server.scd`.
`[READ]`

Also `/g/{0,1,2}/t/aux1`, `/g/{0,1,2}/t/aux2`, `/g/{0,1,2}/t/mix/pan`,
`/g/{0,1,2}/t/mix/g`, `/g/{0,1,2}/t/mix/{main,sub,dir1,dir2,dir3,dir4}-en`
appear as literals at `sc.scm:92,110,128` (the three `make-insert` calls) —
these are the *keys* under which insert state is held, not necessarily
transmitted. `[INFERRED]`

---

## 9. Flat namespace vs `/p/part/t/N/p/…`

The relationship is mechanical and is worth stating precisely, because the
existing documentation gets it backwards.

* Table A is a list of **suffixes**, not of live flat addresses. `[READ]`
* `make-timbre(N)` maps over it and produces, for each suffix `s`, the string
  `(fmt #f "/p/part/t/" N s)`. `[READ]` — `timbre-tree.scm:8`, literal
  `"/p/part/t/"`, inside the loop body `g2482` at `timbre-tree.scm:5`.
* So `"/p/o1/m"` → `/p/part/t/1/p/o1/m`; `"/mix/g"` → `/p/part/t/1/mix/g`;
  `"/en"` → `/p/part/t/1/en`; `"/a/mono"` → `/p/part/t/1/a/mono`.
  The leading `/p` that some suffixes carry is *part of the suffix*, which is
  why the preset form has two `p` components (`…/t/1/p/o1/m`) and the mixer form
  has one (`…/t/1/mix/g`). `[READ]`
* `las-sc` never listens on the bare flat form. `part-dispatch` tests only
  `/p/part/…`, `/status` and `/info`. `[READ]`
* The flat form is `las-frontend`'s and the VC's. `las-frontend` contains both
  spellings (1,832 × `/p/o1/po`, 672 × `/p/part/t/1/p/o1/po`) and is launched
  with `--host-vc=vc --host-performance=vc --host-systemclock=vc`.
  `[READ]` — binary grep and `runtime-state.txt:107`.
* The live namespace dump the project already holds
  (`captures/p-namespace-keys.txt`, 3,197 keys, 792 under `/p/part/t/1/`) is a
  **different and larger** namespace than `las-sc`'s: it has
  `/p/part/t/1/in/cv/cv1/…` where `las-sc` has `/in/cv/0/…`, and
  `/p/part/t/1/a/note-pri` where `las-sc` has `/a/pri`. `[READ]` That file
  therefore does not describe `las-sc`.

---

## 10. Argument types

`las-sc` uses the `csosc` egg. The globals it imports are `osc`, `osc*`,
`osc-adr`, `osc-set-adr`, `osc-value`, `osc-value-int`, `osc-values`,
`osc-arg-count`, `osc-arg-types`, `osc-cdr`, `osc-encode`, `osc-decode`,
`osc-decode-args`, `osc-decode-int32`, `osc-decode-uint32`, `osc-format`,
`osc?`, `osc-bundle?`, `osc-bundle-msgs`. `[READ]` — `lf` symbol names.

* Inbound handlers take the **first** argument via `csosc#osc-value`
  (`sc.scm:340,344,348`, `routing.scm:59,66,74,90,…`). `[READ]`
  `csosc#osc-value-int` is used where an integer is required
  (`lf[0x283854]`, `lf[0x284E90]`). `[READ]`
* Type tags observed on the wire from this instrument's own OSC traffic:
  `,i` (int32), `,b` (blob), `,iiiiiib`. `[READ]`
  `captures/voicebus-midi-20260903-183251.pcap`.
* Per-address type declarations do **not** exist in `las-sc`. There is no table
  of type tags; whatever `csosc#osc-decode` produces is what the handler sees,
  and the handler coerces. `[READ]` — no such literal table in `.rodata`.
* Consequence for `/p/pre-expr`: **no argument type would have worked.** The
  address is not tested for. `[READ]`

---

## 11. Conflicts with existing documentation

Reported, not fixed, per instruction.

| document | claim | what this reading found |
|---|---|---|
| `docs/arch/extension-points.md:211` | "The live engine-side endpoints on the voice controller are `/p/pre-expr`, …" | `las-sc` has no handler and forwards nothing. Whether the VC implements them is `[UNKNOWN]` and cannot be read out of the encoded XMOS image. The word "live" is not supported by anything on disk. |
| `docs/arch/extension-points.md:421` | "`/p/pre-expr` / `/p/post-expr` accept a program. Both are **unknown**" | The *`las-sc` half* is now known: it accepts nothing. |
| `docs/arch/xmos-deep.md:613` | "`las-sc` prepends a `pre-expr` and appends a `post-expr` of its own." | No code in `las-sc` reads the table, builds a program, or sends either address. This claim should be retracted. |
| `docs/arch/xmos-deep.md:926,976` | "`/p/pre-expr` and `/p/post-expr` — the host wraps the preset's program" | Same. |
| `docs/arch/capability-survey.md:57,612` | "Both exist in `las-sc`'s vocabulary (`0x1e2d3f`, …)" | Offsets confirmed exactly (`0x1E2D3F` and `0x1E40A5`). "Vocabulary" is right; "implemented" would not be. |
| `docs/arch/expression-language.md:1372` | describes the `_m` alias table and the CHICKEN literal encoding | Confirmed in full, including the encoding bytes. Adds: 18 of the 115 symbols do not exist in `vx_ee.scm`, and the table is never read. |
| `docs/arch/control-plane.md:103` | lists `/p/pre-expr` among "singles" alongside `/p/name /p/version` | `/p/name` is in table A; **`/p/version` is not in `las-sc` at all** — the only `/p/version`-shaped string in the binary is absent. Table A's entry is `/p/name` only. |
| task brief (architecture as established) | "las-sc owns a FLAT OSC namespace (~536 `/p` addresses …)" | `las-sc` holds 500 distinct `/p/…` strings, of which 115 are `_m` and 2 are `pre`/`post-expr`; the live inbound surface is hierarchical `/p/part/…`, not flat. The flat namespace belongs to `las-frontend` / the VC. |
| task brief | "an 80-address `/p/part` slice covering effects and mixer ONLY" | The "effects and mixer only" half is confirmed. The count measured here is 76 rewritable suffixes per timbre (27 fx + 22 in + 15 a + 12 mix) and 41 dispatched per timbre (27 fx + 12 mix + pan + g), plus 49 `/p/part/las-fx/…` and the `/p/part/mix/…` block. Whatever "80" counted, it is not one of these. |
| task brief | "`_m` addresses are las-sc's computed OUTPUT (modulation sums)" | `las-sc` never emits an `_m` address; it cannot, the strings exist only inside one unread constant. The *semantics* (modulation sums) is supported by the symbol pairing; the *producer* is not `las-sc`. |
| `runtime-state.txt` caveat | "`las-sc` argv … remains valid evidence" | Used on that basis; independently corroborated by `netstat` in the same file for 9300, and by the pcaps for 7770. |

---

## 12. Validation plan (READ-ONLY, for a human to run on the instrument)

None of these write anything. Every one of them either reads a file, reads
`/proc`, or sends an OSC message that this analysis shows is already a no-op.
Run them from the instrument's own shell.

**Group 1 — confirm the argv and the sockets (no OSC at all).**

```sh
cat /proc/$(pidof las-sc)/cmdline | tr '\0' ' '; echo
ls -l /proc/$(pidof las-sc)/fd | wc -l
cat /proc/net/udp | head -40          # local_address 0100007F:2454 == 127.0.0.1:9300
netstat -lnup 2>/dev/null | grep las-sc
```
Confirms: bound to 127.0.0.1:9300 only; the number of open sockets.

**Group 2 — confirm `--expr-syms` is never opened.**

```sh
ls -l /proc/$(pidof las-sc)/fd | grep -i vx_ee     # expect: no match, ever
wc -l /usr/share/vx_ee.scm                          # file exists, 281 lines
md5sum /usr/share/vx_ee.scm                         # expect 5e5c02c1e5a95c79e4e7c52843eb4408
```

**Group 3 — confirm the VC peer and port without sending anything.**

```sh
cat /proc/net/udp | awk 'NR==1 || /027100CB/'      # 203.0.113.2 == 027100CB in /proc byte order; rem_port 1E5A == 7770
getent hosts vc
```

**Group 4 — observe, do not inject.** (Requires `tcpdump`; capture only.)

```sh
tcpdump -i usbint -n -s0 -c 200 -w /tmp/vc.pcap 'udp port 7770'
```
Then, from the *host* side of the analysis, confirm that no `_m` address and no
`pre-expr`/`post-expr` ever appears in that capture during normal play — which
is what the static reading predicts.

**Group 5 — the negative control, if the owner wants it on the record.**
This one does send an OSC message, but only to `las-sc`'s own loopback socket,
and the analysis says it is discarded before anything is transmitted. It is the
same message the project already sent once.

```sh
# send /p/pre-expr with a string argument to las-sc, while capturing the VC link
tcpdump -i usbint -n -s0 -w /tmp/preexpr.pcap 'udp port 7770' &
oscsend 127.0.0.1 9300 /p/pre-expr s "1 0 * pan sto"    # or the project's existing sender
sleep 2; kill %1
```
Expected result if this report is right: `/tmp/preexpr.pcap` contains no packet
carrying `pre-expr`, and `las-sc` stays up. **Do not run the same experiment
against `vc:7770` directly** — the VC's behaviour on an unknown address is
`[UNKNOWN]` and that is a write to the sound engine, not a read.

**Group 6 — confirm the address inventory against the live process.**

```sh
tr -c '[:print:]' '\n' < /usr/bin/las-sc | grep -c '^/p/'          # expect 500
tr -c "[:print:]" "\\n" < /usr/bin/las-sc | grep -c "_m$"           # expect 116 (the encoding hides 9 of the 115; /mix_m adds 2)
tr -c '[:print:]' '\n' < /usr/bin/las-sc | grep -x '/p/pre-expr'   # expect exactly one line
grep -rl 'pre-expr' /usr/bin /usr/share 2>/dev/null                # expect only /usr/bin/las-sc
```

---

## 13. Unexplored

* **`sc/fx.scm`** (899 lines, ~450 traced call sites). I mapped its outgoing
  address vocabulary and its `send-fx`/`send-target` call sites but did not
  reconstruct `insert-fx-parse`, `master-fx-parse`, `update-insert-fx`,
  `update-master-fx` or `update-busses` line by line. The insert/master/bus
  state machine and the LADSPA parameter plumbing (`/fxN/p/<i>`, `insert-params`)
  are the biggest remaining gap in this region.
* **`sc/routing.scm`** lines 11–50 (the `get-all-routings` state read) — I have
  the key names and the hash-table sites but not the exact bus-allocation logic.
* **Which `sec` field each of `send-fx` / `send-target` / `osc-udp-sendto`
  captures.** I read the sender bodies and the `set-sec!` sites but did not
  prove the binding. The `udp6#udp-send`-on-a-`socket#`-socket question in §3 is
  unresolved and may indicate I have mis-paired one define.
* **`las-comm` sub-port numbers** for `las-card-*`, `las-vox-*`, `las-oscl-*`,
  `las-open-clock-socket`. The pcaps show 9100, 9500, 9600, 9876 and 7770 in
  use; I attributed only 7770 to `las-sc` with direct evidence.
* **`csosc`'s encoder.** Its procedures are interned but its own compilation
  unit does not appear in the procedure table, so I could not confirm the exact
  set of type tags it emits beyond what the pcaps show.
* **The 90-entry table B's dispatch for `/p/part/rseq/…`, `/seq/…`, `/tq`.**
  These are in `preset-dbase` but match none of `part-dispatch`'s prefixes; I
  did not find another consumer. They may be dead in the same way
  `expression-nodes` is, but I did not run the full read-count check on them.
* **Whether the voice controller implements `/p/pre-expr`.** Blocked: the XMOS
  image is encoded and contains no readable address strings.
* **`cal/*`, `mon/*`, `vxfw-lib`, `las-measure`, `las-oscl`, `las-vox`,
  `las-math`** — ~2,300 functions, out of this region's scope.
* **1.5.0 → 1.8.2 diff.** I verified the `expression-nodes` finding holds in
  both, and that `.text` differs in 62,099 of 1,961,788 bytes (3.2%, consistent
  with literal-pool relocation), but I did not enumerate the behavioural
  changes.

---
## Appendix — the three tables in full

Decoded directly from the CHICKEN literal blobs. `[READ]` throughout.

In table A, "make-outgoing-address →" is what `handle-t-prefix` rewrites the
address to when the address is `/p/part/t/N` + that suffix; `-` means the
rewriter has no branch for it and returns nothing useful. "part-dispatch
handler" is which of the twelve prefix tests in `sc/sc.scm:237–252` the resulting
address hits; `-` means it hits none and is discarded.

## A. per-timbre suffix table (372 entries, las-sc 1.8.2 lf[0x2826a8-8]=0x2826a0)

| # | suffix | full address (N=1..3) | make-outgoing-address -> | part-dispatch handler |
|---|---|---|---|---|
| 1 | `/en` | `/p/part/t/N/en` | `-` | - |
| 2 | `/in/local/en` | `/p/part/t/N/in/local/en` | `/r/g/N/in/local/en` | - |
| 3 | `/in/local/note-min` | `/p/part/t/N/in/local/note-min` | `/r/g/N/in/local/note-min` | - |
| 4 | `/in/local/note-max` | `/p/part/t/N/in/local/note-max` | `/r/g/N/in/local/note-max` | - |
| 5 | `/in/midi/en` | `/p/part/t/N/in/midi/en` | `/r/g/N/in/midi/en` | - |
| 6 | `/in/midi/ch` | `/p/part/t/N/in/midi/ch` | `/r/g/N/in/midi/ch` | - |
| 7 | `/in/midi/note-min` | `/p/part/t/N/in/midi/note-min` | `/r/g/N/in/midi/note-min` | - |
| 8 | `/in/midi/note-max` | `/p/part/t/N/in/midi/note-max` | `/r/g/N/in/midi/note-max` | - |
| 9 | `/in/midi/tr` | `/p/part/t/N/in/midi/tr` | `/r/g/N/in/midi/tr` | - |
| 10 | `/in/midi/ccmap` | `/p/part/t/N/in/midi/ccmap` | `/r/g/N/in/midi/ccmap` | - |
| 11 | `/in/usb` | `/p/part/t/N/in/usb` | `/r/g/N/in/usb` | - |
| 12 | `/in/cv/0/en` | `/p/part/t/N/in/cv/0/en` | `/r/g/N/in/cv/0/en` | - |
| 13 | `/in/cv/0/dest` | `/p/part/t/N/in/cv/0/dest` | `/r/g/N/in/cv/0/dest` | - |
| 14 | `/in/cv/0/in-max` | `/p/part/t/N/in/cv/0/in-max` | `/r/g/N/in/cv/0/in-max` | - |
| 15 | `/in/cv/0/in-min` | `/p/part/t/N/in/cv/0/in-min` | `/r/g/N/in/cv/0/in-min` | - |
| 16 | `/in/cv/0/out-min` | `/p/part/t/N/in/cv/0/out-min` | `/r/g/N/in/cv/0/out-min` | - |
| 17 | `/in/cv/0/out-max` | `/p/part/t/N/in/cv/0/out-max` | `/r/g/N/in/cv/0/out-max` | - |
| 18 | `/in/rseq/id` | `/p/part/t/N/in/rseq/id` | `/r/g/N/in/rseq/id` | - |
| 19 | `/in/rseq/en` | `/p/part/t/N/in/rseq/en` | `/r/g/N/in/rseq/en` | - |
| 20 | `/in/com/note-min` | `/p/part/t/N/in/com/note-min` | `/r/g/N/in/com/note-min` | - |
| 21 | `/in/com/note-max` | `/p/part/t/N/in/com/note-max` | `/r/g/N/in/com/note-max` | - |
| 22 | `/in/com/tr` | `/p/part/t/N/in/com/tr` | `/r/g/N/in/com/tr` | - |
| 23 | `/in/com/tuning` | `/p/part/t/N/in/com/tuning` | `/r/g/N/in/com/tuning` | - |
| 24 | `/a/unspecified_mono` | `/p/part/t/N/a/unspecified_mono` | `/g/N/a/mono` | - |
| 25 | `/a/mono` | `/p/part/t/N/a/mono` | `/g/N/a/mono` | - |
| 26 | `/a/max-voices` | `/p/part/t/N/a/max-voices` | `/g/N/a/max-voices` | - |
| 27 | `/a/note-steal` | `/p/part/t/N/a/note-steal` | `/g/N/a/note-steal` | - |
| 28 | `/a/note-limit` | `/p/part/t/N/a/note-limit` | `/g/N/a/note-limit` | - |
| 29 | `/a/unison/en` | `/p/part/t/N/a/unison/en` | `/g/N/a/unison/en` | - |
| 30 | `/a/unison/pitch-spread` | `/p/part/t/N/a/unison/pitch-spread` | `/g/N/a/unison/pitch-spread` | - |
| 31 | `/a/unison/max-stack` | `/p/part/t/N/a/unison/max-stack` | `/g/N/a/unison/max-stack` | - |
| 32 | `/a/max-stack` | `/p/part/t/N/a/max-stack` | `/g/N/a/max-stack` | - |
| 33 | `/a/chord/en` | `/p/part/t/N/a/chord/en` | `/g/N/a/chord/en` | - |
| 34 | `/a/chord/ofs` | `/p/part/t/N/a/chord/ofs` | `/g/N/a/chord/ofs` | - |
| 35 | `/a/hold` | `/p/part/t/N/a/hold` | `/g/N/a/hold` | - |
| 36 | `/a/pri` | `/p/part/t/N/a/pri` | `/g/N/a/pri` | - |
| 37 | `/a/mono-note-pri` | `/p/part/t/N/a/mono-note-pri` | `/g/N/a/mono-note-pri` | - |
| 38 | `/a/rnd` | `/p/part/t/N/a/rnd` | `/g/N/a/rnd` | - |
| 39 | `/mix/g` | `/p/part/t/N/mix/g` | `/g/N/t/mix/g` | mix-message-parse |
| 40 | `/mix/bal` | `/p/part/t/N/mix/bal` | `/g/N/t/mix/bal` | mix-message-parse |
| 41 | `/mix/mute` | `/p/part/t/N/mix/mute` | `/g/N/t/mix/mute` | mix-message-parse |
| 42 | `/mix/main-en` | `/p/part/t/N/mix/main-en` | `/g/N/t/mix/main-en` | mix-message-parse |
| 43 | `/mix/sub-en` | `/p/part/t/N/mix/sub-en` | `/g/N/t/mix/sub-en` | mix-message-parse |
| 44 | `/mix/aux1` | `/p/part/t/N/mix/aux1` | `/g/N/t/mix/aux1` | mix-message-parse |
| 45 | `/mix/aux2` | `/p/part/t/N/mix/aux2` | `/g/N/t/mix/aux2` | mix-message-parse |
| 46 | `/mix/aux-bal` | `/p/part/t/N/mix/aux-bal` | `/g/N/t/mix/aux-bal` | mix-message-parse |
| 47 | `/mix/dir1` | `/p/part/t/N/mix/dir1` | `/g/N/t/mix/dir1` | mix-message-parse |
| 48 | `/mix/dir2` | `/p/part/t/N/mix/dir2` | `/g/N/t/mix/dir2` | mix-message-parse |
| 49 | `/mix/dir3` | `/p/part/t/N/mix/dir3` | `/g/N/t/mix/dir3` | mix-message-parse |
| 50 | `/mix/dir4` | `/p/part/t/N/mix/dir4` | `/g/N/t/mix/dir4` | mix-message-parse |
| 51 | `/p/name` | `/p/part/t/N/p/name` | `-` | - |
| 52 | `/p/pbup` | `/p/part/t/N/p/pbup` | `-` | - |
| 53 | `/p/pbdn` | `/p/part/t/N/p/pbdn` | `-` | - |
| 54 | `/p/sus/mode` | `/p/part/t/N/p/sus/mode` | `-` | - |
| 55 | `/p/sus/src` | `/p/part/t/N/p/sus/src` | `-` | - |
| 56 | `/p/o1/m` | `/p/part/t/N/p/o1/m` | `-` | - |
| 57 | `/p/o1/po` | `/p/part/t/N/p/o1/po` | `-` | - |
| 58 | `/p/o1/oct` | `/p/part/t/N/p/o1/oct` | `-` | - |
| 59 | `/p/o1/pt` | `/p/part/t/N/p/o1/pt` | `-` | - |
| 60 | `/p/o1/fo` | `/p/part/t/N/p/o1/fo` | `-` | - |
| 61 | `/p/o1/d` | `/p/part/t/N/p/o1/d` | `-` | - |
| 62 | `/p/o1/fm1` | `/p/part/t/N/p/o1/fm1` | `-` | - |
| 63 | `/p/o1/fm2` | `/p/part/t/N/p/o1/fm2` | `-` | - |
| 64 | `/p/o1/fm3` | `/p/part/t/N/p/o1/fm3` | `-` | - |
| 65 | `/p/o1/sync1` | `/p/part/t/N/p/o1/sync1` | `-` | - |
| 66 | `/p/o1/sync2` | `/p/part/t/N/p/o1/sync2` | `-` | - |
| 67 | `/p/o1/sync3` | `/p/part/t/N/p/o1/sync3` | `-` | - |
| 68 | `/p/o1/krst` | `/p/part/t/N/p/o1/krst` | `-` | - |
| 69 | `/p/o1/tr` | `/p/part/t/N/p/o1/tr` | `-` | - |
| 70 | `/p/o1/ang` | `/p/part/t/N/p/o1/ang` | `-` | - |
| 71 | `/p/o1/pbup` | `/p/part/t/N/p/o1/pbup` | `-` | - |
| 72 | `/p/o1/pbdn` | `/p/part/t/N/p/o1/pbdn` | `-` | - |
| 73 | `/p/o2/m` | `/p/part/t/N/p/o2/m` | `-` | - |
| 74 | `/p/o2/po` | `/p/part/t/N/p/o2/po` | `-` | - |
| 75 | `/p/o2/oct` | `/p/part/t/N/p/o2/oct` | `-` | - |
| 76 | `/p/o2/pt` | `/p/part/t/N/p/o2/pt` | `-` | - |
| 77 | `/p/o2/fo` | `/p/part/t/N/p/o2/fo` | `-` | - |
| 78 | `/p/o2/d` | `/p/part/t/N/p/o2/d` | `-` | - |
| 79 | `/p/o2/fm1` | `/p/part/t/N/p/o2/fm1` | `-` | - |
| 80 | `/p/o2/fm2` | `/p/part/t/N/p/o2/fm2` | `-` | - |
| 81 | `/p/o2/fm3` | `/p/part/t/N/p/o2/fm3` | `-` | - |
| 82 | `/p/o2/sync1` | `/p/part/t/N/p/o2/sync1` | `-` | - |
| 83 | `/p/o2/sync2` | `/p/part/t/N/p/o2/sync2` | `-` | - |
| 84 | `/p/o2/sync3` | `/p/part/t/N/p/o2/sync3` | `-` | - |
| 85 | `/p/o2/krst` | `/p/part/t/N/p/o2/krst` | `-` | - |
| 86 | `/p/o2/tr` | `/p/part/t/N/p/o2/tr` | `-` | - |
| 87 | `/p/o2/ang` | `/p/part/t/N/p/o2/ang` | `-` | - |
| 88 | `/p/o2/pbup` | `/p/part/t/N/p/o2/pbup` | `-` | - |
| 89 | `/p/o2/pbdn` | `/p/part/t/N/p/o2/pbdn` | `-` | - |
| 90 | `/p/o3/m` | `/p/part/t/N/p/o3/m` | `-` | - |
| 91 | `/p/o3/po` | `/p/part/t/N/p/o3/po` | `-` | - |
| 92 | `/p/o3/oct` | `/p/part/t/N/p/o3/oct` | `-` | - |
| 93 | `/p/o3/pt` | `/p/part/t/N/p/o3/pt` | `-` | - |
| 94 | `/p/o3/fo` | `/p/part/t/N/p/o3/fo` | `-` | - |
| 95 | `/p/o3/d` | `/p/part/t/N/p/o3/d` | `-` | - |
| 96 | `/p/o3/fm1` | `/p/part/t/N/p/o3/fm1` | `-` | - |
| 97 | `/p/o3/fm2` | `/p/part/t/N/p/o3/fm2` | `-` | - |
| 98 | `/p/o3/fm3` | `/p/part/t/N/p/o3/fm3` | `-` | - |
| 99 | `/p/o3/sync1` | `/p/part/t/N/p/o3/sync1` | `-` | - |
| 100 | `/p/o3/sync2` | `/p/part/t/N/p/o3/sync2` | `-` | - |
| 101 | `/p/o3/sync3` | `/p/part/t/N/p/o3/sync3` | `-` | - |
| 102 | `/p/o3/krst` | `/p/part/t/N/p/o3/krst` | `-` | - |
| 103 | `/p/o3/tr` | `/p/part/t/N/p/o3/tr` | `-` | - |
| 104 | `/p/o3/ang` | `/p/part/t/N/p/o3/ang` | `-` | - |
| 105 | `/p/o3/pbup` | `/p/part/t/N/p/o3/pbup` | `-` | - |
| 106 | `/p/o3/pbdn` | `/p/part/t/N/p/o3/pbdn` | `-` | - |
| 107 | `/p/p1/d` | `/p/part/t/N/p/p1/d` | `-` | - |
| 108 | `/p/p2/d` | `/p/part/t/N/p/p2/d` | `-` | - |
| 109 | `/p/p3/d` | `/p/part/t/N/p/p3/d` | `-` | - |
| 110 | `/p/l1/f` | `/p/part/t/N/p/l1/f` | `-` | - |
| 111 | `/p/l1/w` | `/p/part/t/N/p/l1/w` | `-` | - |
| 112 | `/p/l1/td` | `/p/part/t/N/p/l1/td` | `-` | - |
| 113 | `/p/l1/ta` | `/p/part/t/N/p/l1/ta` | `-` | - |
| 114 | `/p/l1/sym` | `/p/part/t/N/p/l1/sym` | `-` | - |
| 115 | `/p/l1/d` | `/p/part/t/N/p/l1/d` | `-` | - |
| 116 | `/p/l1/nrst` | `/p/part/t/N/p/l1/nrst` | `-` | - |
| 117 | `/p/l1/rst` | `/p/part/t/N/p/l1/rst` | `-` | - |
| 118 | `/p/l1/ph` | `/p/part/t/N/p/l1/ph` | `-` | - |
| 119 | `/p/l1/fmul` | `/p/part/t/N/p/l1/fmul` | `-` | - |
| 120 | `/p/l1/fidx` | `/p/part/t/N/p/l1/fidx` | `-` | - |
| 121 | `/p/l1/phr` | `/p/part/t/N/p/l1/phr` | `-` | - |
| 122 | `/p/l1/sm` | `/p/part/t/N/p/l1/sm` | `-` | - |
| 123 | `/p/l1/tfin` | `/p/part/t/N/p/l1/tfin` | `-` | - |
| 124 | `/p/l1/tfout` | `/p/part/t/N/p/l1/tfout` | `-` | - |
| 125 | `/p/l1/one_shot` | `/p/part/t/N/p/l1/one_shot` | `-` | - |
| 126 | `/p/l1/sh_noise` | `/p/part/t/N/p/l1/sh_noise` | `-` | - |
| 127 | `/p/l1/pol` | `/p/part/t/N/p/l1/pol` | `-` | - |
| 128 | `/p/l1/var` | `/p/part/t/N/p/l1/var` | `-` | - |
| 129 | `/p/l2/f` | `/p/part/t/N/p/l2/f` | `-` | - |
| 130 | `/p/l2/w` | `/p/part/t/N/p/l2/w` | `-` | - |
| 131 | `/p/l2/td` | `/p/part/t/N/p/l2/td` | `-` | - |
| 132 | `/p/l2/ta` | `/p/part/t/N/p/l2/ta` | `-` | - |
| 133 | `/p/l2/sym` | `/p/part/t/N/p/l2/sym` | `-` | - |
| 134 | `/p/l2/d` | `/p/part/t/N/p/l2/d` | `-` | - |
| 135 | `/p/l2/nrst` | `/p/part/t/N/p/l2/nrst` | `-` | - |
| 136 | `/p/l2/rst` | `/p/part/t/N/p/l2/rst` | `-` | - |
| 137 | `/p/l2/ph` | `/p/part/t/N/p/l2/ph` | `-` | - |
| 138 | `/p/l2/fmul` | `/p/part/t/N/p/l2/fmul` | `-` | - |
| 139 | `/p/l2/fidx` | `/p/part/t/N/p/l2/fidx` | `-` | - |
| 140 | `/p/l2/phr` | `/p/part/t/N/p/l2/phr` | `-` | - |
| 141 | `/p/l2/sm` | `/p/part/t/N/p/l2/sm` | `-` | - |
| 142 | `/p/l2/tfin` | `/p/part/t/N/p/l2/tfin` | `-` | - |
| 143 | `/p/l2/tfout` | `/p/part/t/N/p/l2/tfout` | `-` | - |
| 144 | `/p/l2/one_shot` | `/p/part/t/N/p/l2/one_shot` | `-` | - |
| 145 | `/p/l2/sh_noise` | `/p/part/t/N/p/l2/sh_noise` | `-` | - |
| 146 | `/p/l2/pol` | `/p/part/t/N/p/l2/pol` | `-` | - |
| 147 | `/p/l2/var` | `/p/part/t/N/p/l2/var` | `-` | - |
| 148 | `/p/l3/f` | `/p/part/t/N/p/l3/f` | `-` | - |
| 149 | `/p/l3/w` | `/p/part/t/N/p/l3/w` | `-` | - |
| 150 | `/p/l3/td` | `/p/part/t/N/p/l3/td` | `-` | - |
| 151 | `/p/l3/ta` | `/p/part/t/N/p/l3/ta` | `-` | - |
| 152 | `/p/l3/sym` | `/p/part/t/N/p/l3/sym` | `-` | - |
| 153 | `/p/l3/d` | `/p/part/t/N/p/l3/d` | `-` | - |
| 154 | `/p/l3/nrst` | `/p/part/t/N/p/l3/nrst` | `-` | - |
| 155 | `/p/l3/rst` | `/p/part/t/N/p/l3/rst` | `-` | - |
| 156 | `/p/l3/ph` | `/p/part/t/N/p/l3/ph` | `-` | - |
| 157 | `/p/l3/fmul` | `/p/part/t/N/p/l3/fmul` | `-` | - |
| 158 | `/p/l3/fidx` | `/p/part/t/N/p/l3/fidx` | `-` | - |
| 159 | `/p/l3/phr` | `/p/part/t/N/p/l3/phr` | `-` | - |
| 160 | `/p/l3/sm` | `/p/part/t/N/p/l3/sm` | `-` | - |
| 161 | `/p/l3/tfin` | `/p/part/t/N/p/l3/tfin` | `-` | - |
| 162 | `/p/l3/tfout` | `/p/part/t/N/p/l3/tfout` | `-` | - |
| 163 | `/p/l3/one_shot` | `/p/part/t/N/p/l3/one_shot` | `-` | - |
| 164 | `/p/l3/sh_noise` | `/p/part/t/N/p/l3/sh_noise` | `-` | - |
| 165 | `/p/l3/pol` | `/p/part/t/N/p/l3/pol` | `-` | - |
| 166 | `/p/l3/var` | `/p/part/t/N/p/l3/var` | `-` | - |
| 167 | `/p/l4/f` | `/p/part/t/N/p/l4/f` | `-` | - |
| 168 | `/p/l4/w` | `/p/part/t/N/p/l4/w` | `-` | - |
| 169 | `/p/l4/td` | `/p/part/t/N/p/l4/td` | `-` | - |
| 170 | `/p/l4/ta` | `/p/part/t/N/p/l4/ta` | `-` | - |
| 171 | `/p/l4/var` | `/p/part/t/N/p/l4/var` | `-` | - |
| 172 | `/p/l4/d` | `/p/part/t/N/p/l4/d` | `-` | - |
| 173 | `/p/l4/nrst` | `/p/part/t/N/p/l4/nrst` | `-` | - |
| 174 | `/p/l4/rst` | `/p/part/t/N/p/l4/rst` | `-` | - |
| 175 | `/p/l4/ph` | `/p/part/t/N/p/l4/ph` | `-` | - |
| 176 | `/p/l4/fmul` | `/p/part/t/N/p/l4/fmul` | `-` | - |
| 177 | `/p/l4/fidx` | `/p/part/t/N/p/l4/fidx` | `-` | - |
| 178 | `/p/l4/phr` | `/p/part/t/N/p/l4/phr` | `-` | - |
| 179 | `/p/l4/sm` | `/p/part/t/N/p/l4/sm` | `-` | - |
| 180 | `/p/l4/tfin` | `/p/part/t/N/p/l4/tfin` | `-` | - |
| 181 | `/p/l4/tfout` | `/p/part/t/N/p/l4/tfout` | `-` | - |
| 182 | `/p/l4/one_shot` | `/p/part/t/N/p/l4/one_shot` | `-` | - |
| 183 | `/p/l4/sh_noise` | `/p/part/t/N/p/l4/sh_noise` | `-` | - |
| 184 | `/p/l4/pol` | `/p/part/t/N/p/l4/pol` | `-` | - |
| 185 | `/p/l4/var` | `/p/part/t/N/p/l4/var` | `-` | - |
| 186 | `/p/e1/a` | `/p/part/t/N/p/e1/a` | `-` | - |
| 187 | `/p/e1/d` | `/p/part/t/N/p/e1/d` | `-` | - |
| 188 | `/p/e1/s` | `/p/part/t/N/p/e1/s` | `-` | - |
| 189 | `/p/e1/h` | `/p/part/t/N/p/e1/h` | `-` | - |
| 190 | `/p/e1/r` | `/p/part/t/N/p/e1/r` | `-` | - |
| 191 | `/p/e1/ak` | `/p/part/t/N/p/e1/ak` | `-` | - |
| 192 | `/p/e1/dk` | `/p/part/t/N/p/e1/dk` | `-` | - |
| 193 | `/p/e1/rk` | `/p/part/t/N/p/e1/rk` | `-` | - |
| 194 | `/p/e1/multi-trig` | `/p/part/t/N/p/e1/multi-trig` | `-` | - |
| 195 | `/p/e1/sync` | `/p/part/t/N/p/e1/sync` | `-` | - |
| 196 | `/p/e1/loop` | `/p/part/t/N/p/e1/loop` | `-` | - |
| 197 | `/p/e1/latch` | `/p/part/t/N/p/e1/latch` | `-` | - |
| 198 | `/p/e1/delay` | `/p/part/t/N/p/e1/delay` | `-` | - |
| 199 | `/p/e1/velmod` | `/p/part/t/N/p/e1/velmod` | `-` | - |
| 200 | `/p/e1/key-follow` | `/p/part/t/N/p/e1/key-follow` | `-` | - |
| 201 | `/p/e1/trig` | `/p/part/t/N/p/e1/trig` | `-` | - |
| 202 | `/p/e1/tscale` | `/p/part/t/N/p/e1/tscale` | `-` | - |
| 203 | `/p/e2/a` | `/p/part/t/N/p/e2/a` | `-` | - |
| 204 | `/p/e2/d` | `/p/part/t/N/p/e2/d` | `-` | - |
| 205 | `/p/e2/s` | `/p/part/t/N/p/e2/s` | `-` | - |
| 206 | `/p/e2/h` | `/p/part/t/N/p/e2/h` | `-` | - |
| 207 | `/p/e2/r` | `/p/part/t/N/p/e2/r` | `-` | - |
| 208 | `/p/e2/ak` | `/p/part/t/N/p/e2/ak` | `-` | - |
| 209 | `/p/e2/dk` | `/p/part/t/N/p/e2/dk` | `-` | - |
| 210 | `/p/e2/rk` | `/p/part/t/N/p/e2/rk` | `-` | - |
| 211 | `/p/e2/multi-trig` | `/p/part/t/N/p/e2/multi-trig` | `-` | - |
| 212 | `/p/e2/sync` | `/p/part/t/N/p/e2/sync` | `-` | - |
| 213 | `/p/e2/loop` | `/p/part/t/N/p/e2/loop` | `-` | - |
| 214 | `/p/e2/latch` | `/p/part/t/N/p/e2/latch` | `-` | - |
| 215 | `/p/e2/delay` | `/p/part/t/N/p/e2/delay` | `-` | - |
| 216 | `/p/e2/velmod` | `/p/part/t/N/p/e2/velmod` | `-` | - |
| 217 | `/p/e2/key-follow` | `/p/part/t/N/p/e2/key-follow` | `-` | - |
| 218 | `/p/e2/trig` | `/p/part/t/N/p/e2/trig` | `-` | - |
| 219 | `/p/e2/tscale` | `/p/part/t/N/p/e2/tscale` | `-` | - |
| 220 | `/p/e3/a` | `/p/part/t/N/p/e3/a` | `-` | - |
| 221 | `/p/e3/d` | `/p/part/t/N/p/e3/d` | `-` | - |
| 222 | `/p/e3/s` | `/p/part/t/N/p/e3/s` | `-` | - |
| 223 | `/p/e3/h` | `/p/part/t/N/p/e3/h` | `-` | - |
| 224 | `/p/e3/r` | `/p/part/t/N/p/e3/r` | `-` | - |
| 225 | `/p/e3/ak` | `/p/part/t/N/p/e3/ak` | `-` | - |
| 226 | `/p/e3/dk` | `/p/part/t/N/p/e3/dk` | `-` | - |
| 227 | `/p/e3/rk` | `/p/part/t/N/p/e3/rk` | `-` | - |
| 228 | `/p/e3/multi-trig` | `/p/part/t/N/p/e3/multi-trig` | `-` | - |
| 229 | `/p/e3/sync` | `/p/part/t/N/p/e3/sync` | `-` | - |
| 230 | `/p/e3/loop` | `/p/part/t/N/p/e3/loop` | `-` | - |
| 231 | `/p/e3/latch` | `/p/part/t/N/p/e3/latch` | `-` | - |
| 232 | `/p/e3/delay` | `/p/part/t/N/p/e3/delay` | `-` | - |
| 233 | `/p/e3/velmod` | `/p/part/t/N/p/e3/velmod` | `-` | - |
| 234 | `/p/e3/key-follow` | `/p/part/t/N/p/e3/key-follow` | `-` | - |
| 235 | `/p/e3/trig` | `/p/part/t/N/p/e3/trig` | `-` | - |
| 236 | `/p/e3/tscale` | `/p/part/t/N/p/e3/tscale` | `-` | - |
| 237 | `/p/e4/a` | `/p/part/t/N/p/e4/a` | `-` | - |
| 238 | `/p/e4/d` | `/p/part/t/N/p/e4/d` | `-` | - |
| 239 | `/p/e4/s` | `/p/part/t/N/p/e4/s` | `-` | - |
| 240 | `/p/e4/h` | `/p/part/t/N/p/e4/h` | `-` | - |
| 241 | `/p/e4/r` | `/p/part/t/N/p/e4/r` | `-` | - |
| 242 | `/p/e4/ak` | `/p/part/t/N/p/e4/ak` | `-` | - |
| 243 | `/p/e4/dk` | `/p/part/t/N/p/e4/dk` | `-` | - |
| 244 | `/p/e4/rk` | `/p/part/t/N/p/e4/rk` | `-` | - |
| 245 | `/p/e4/multi-trig` | `/p/part/t/N/p/e4/multi-trig` | `-` | - |
| 246 | `/p/e4/sync` | `/p/part/t/N/p/e4/sync` | `-` | - |
| 247 | `/p/e4/loop` | `/p/part/t/N/p/e4/loop` | `-` | - |
| 248 | `/p/e4/latch` | `/p/part/t/N/p/e4/latch` | `-` | - |
| 249 | `/p/e4/delay` | `/p/part/t/N/p/e4/delay` | `-` | - |
| 250 | `/p/e4/velmod` | `/p/part/t/N/p/e4/velmod` | `-` | - |
| 251 | `/p/e4/key-follow` | `/p/part/t/N/p/e4/key-follow` | `-` | - |
| 252 | `/p/e4/trig` | `/p/part/t/N/p/e4/trig` | `-` | - |
| 253 | `/p/e4/tscale` | `/p/part/t/N/p/e4/tscale` | `-` | - |
| 254 | `/p/ringsrc3` | `/p/part/t/N/p/ringsrc3` | `-` | - |
| 255 | `/p/noise/mode` | `/p/part/t/N/p/noise/mode` | `-` | - |
| 256 | `/p/noise/mix` | `/p/part/t/N/p/noise/mix` | `-` | - |
| 257 | `/p/noise/a` | `/p/part/t/N/p/noise/a` | `-` | - |
| 258 | `/p/noise/d` | `/p/part/t/N/p/noise/d` | `-` | - |
| 259 | `/p/noise/s` | `/p/part/t/N/p/noise/s` | `-` | - |
| 260 | `/p/noise/r` | `/p/part/t/N/p/noise/r` | `-` | - |
| 261 | `/p/noise/ar` | `/p/part/t/N/p/noise/ar` | `-` | - |
| 262 | `/p/m/l1_p` | `/p/part/t/N/p/m/l1_p` | `-` | - |
| 263 | `/p/m/e3_p` | `/p/part/t/N/p/m/e3_p` | `-` | - |
| 264 | `/p/m/l3_od` | `/p/part/t/N/p/m/l3_od` | `-` | - |
| 265 | `/p/m/l3_pd` | `/p/part/t/N/p/m/l3_pd` | `-` | - |
| 266 | `/p/m/l2_pan` | `/p/part/t/N/p/m/l2_pan` | `-` | - |
| 267 | `/p/c` | `/p/part/t/N/p/c` | `-` | - |
| 268 | `/p/mix/o1/plsbal` | `/p/part/t/N/p/mix/o1/plsbal` | `-` | - |
| 269 | `/p/mix/o1/g` | `/p/part/t/N/p/mix/o1/g` | `-` | - |
| 270 | `/p/mix/o1/fa` | `/p/part/t/N/p/mix/o1/fa` | `-` | - |
| 271 | `/p/mix/o1/fb` | `/p/part/t/N/p/mix/o1/fb` | `-` | - |
| 272 | `/p/mix/o2/plsbal` | `/p/part/t/N/p/mix/o2/plsbal` | `-` | - |
| 273 | `/p/mix/o2/g` | `/p/part/t/N/p/mix/o2/g` | `-` | - |
| 274 | `/p/mix/o2/fa` | `/p/part/t/N/p/mix/o2/fa` | `-` | - |
| 275 | `/p/mix/o2/fb` | `/p/part/t/N/p/mix/o2/fb` | `-` | - |
| 276 | `/p/mix/o3/plsbal` | `/p/part/t/N/p/mix/o3/plsbal` | `-` | - |
| 277 | `/p/mix/o3/g` | `/p/part/t/N/p/mix/o3/g` | `-` | - |
| 278 | `/p/mix/o3/fa` | `/p/part/t/N/p/mix/o3/fa` | `-` | - |
| 279 | `/p/mix/o3/fb` | `/p/part/t/N/p/mix/o3/fb` | `-` | - |
| 280 | `/p/mix/rm/g` | `/p/part/t/N/p/mix/rm/g` | `-` | - |
| 281 | `/p/mix/rm/fa` | `/p/part/t/N/p/mix/rm/fa` | `-` | - |
| 282 | `/p/mix/rm/fb` | `/p/part/t/N/p/mix/rm/fb` | `-` | - |
| 283 | `/p/mix/n/g` | `/p/part/t/N/p/mix/n/g` | `-` | - |
| 284 | `/p/mix/n/fa` | `/p/part/t/N/p/mix/n/fa` | `-` | - |
| 285 | `/p/mix/n/fb` | `/p/part/t/N/p/mix/n/fb` | `-` | - |
| 286 | `/p/mix/ext/ext0` | `/p/part/t/N/p/mix/ext/ext0` | `-` | - |
| 287 | `/p/mix/ext/ext1` | `/p/part/t/N/p/mix/ext/ext1` | `-` | - |
| 288 | `/p/mix/ext/g` | `/p/part/t/N/p/mix/ext/g` | `-` | - |
| 289 | `/p/mix/ext/fa` | `/p/part/t/N/p/mix/ext/fa` | `-` | - |
| 290 | `/p/mix/ext/fb` | `/p/part/t/N/p/mix/ext/fb` | `-` | - |
| 291 | `/p/f/p` | `/p/part/t/N/p/f/p` | `-` | - |
| 292 | `/p/f/eg_p` | `/p/part/t/N/p/f/eg_p` | `-` | - |
| 293 | `/p/f/r` | `/p/part/t/N/p/f/r` | `-` | - |
| 294 | `/p/f/lfo_p` | `/p/part/t/N/p/f/lfo_p` | `-` | - |
| 295 | `/p/f/fm/src` | `/p/part/t/N/p/f/fm/src` | `-` | - |
| 296 | `/p/f/fm/idx` | `/p/part/t/N/p/f/fm/idx` | `-` | - |
| 297 | `/p/fa/m` | `/p/part/t/N/p/fa/m` | `-` | - |
| 298 | `/p/fa/par` | `/p/part/t/N/p/fa/par` | `-` | - |
| 299 | `/p/fa/p_fp` | `/p/part/t/N/p/fa/p_fp` | `-` | - |
| 300 | `/p/fa/p` | `/p/part/t/N/p/fa/p` | `-` | - |
| 301 | `/p/fa/eg_p` | `/p/part/t/N/p/fa/eg_p` | `-` | - |
| 302 | `/p/fa/r` | `/p/part/t/N/p/fa/r` | `-` | - |
| 303 | `/p/fa/lfo_p` | `/p/part/t/N/p/fa/lfo_p` | `-` | - |
| 304 | `/p/fa/lp` | `/p/part/t/N/p/fa/lp` | `-` | - |
| 305 | `/p/fa/hp` | `/p/part/t/N/p/fa/hp` | `-` | - |
| 306 | `/p/fa/bp` | `/p/part/t/N/p/fa/bp` | `-` | - |
| 307 | `/p/fa/fm/src` | `/p/part/t/N/p/fa/fm/src` | `-` | - |
| 308 | `/p/fa/fm/idx` | `/p/part/t/N/p/fa/fm/idx` | `-` | - |
| 309 | `/p/fa/1/p` | `/p/part/t/N/p/fa/1/p` | `-` | - |
| 310 | `/p/fa/1/eg_p` | `/p/part/t/N/p/fa/1/eg_p` | `-` | - |
| 311 | `/p/fa/1/r` | `/p/part/t/N/p/fa/1/r` | `-` | - |
| 312 | `/p/fa/1/lfo_p` | `/p/part/t/N/p/fa/1/lfo_p` | `-` | - |
| 313 | `/p/fa/1/lp` | `/p/part/t/N/p/fa/1/lp` | `-` | - |
| 314 | `/p/fa/1/hp` | `/p/part/t/N/p/fa/1/hp` | `-` | - |
| 315 | `/p/fa/1/bp` | `/p/part/t/N/p/fa/1/bp` | `-` | - |
| 316 | `/p/fa/1/fm/src` | `/p/part/t/N/p/fa/1/fm/src` | `-` | - |
| 317 | `/p/fa/1/fm/idx` | `/p/part/t/N/p/fa/1/fm/idx` | `-` | - |
| 318 | `/p/fa/2/p` | `/p/part/t/N/p/fa/2/p` | `-` | - |
| 319 | `/p/fa/2/eg_p` | `/p/part/t/N/p/fa/2/eg_p` | `-` | - |
| 320 | `/p/fa/2/r` | `/p/part/t/N/p/fa/2/r` | `-` | - |
| 321 | `/p/fa/2/lfo_p` | `/p/part/t/N/p/fa/2/lfo_p` | `-` | - |
| 322 | `/p/fa/2/lp` | `/p/part/t/N/p/fa/2/lp` | `-` | - |
| 323 | `/p/fa/2/hp` | `/p/part/t/N/p/fa/2/hp` | `-` | - |
| 324 | `/p/fa/2/bp` | `/p/part/t/N/p/fa/2/bp` | `-` | - |
| 325 | `/p/fa/2/fm/src` | `/p/part/t/N/p/fa/2/fm/src` | `-` | - |
| 326 | `/p/fa/2/fm/idx` | `/p/part/t/N/p/fa/2/fm/idx` | `-` | - |
| 327 | `/p/fafb` | `/p/part/t/N/p/fafb` | `-` | - |
| 328 | `/p/fb/p` | `/p/part/t/N/p/fb/p` | `-` | - |
| 329 | `/p/fb/p_fp` | `/p/part/t/N/p/fb/p_fp` | `-` | - |
| 330 | `/p/fb/r` | `/p/part/t/N/p/fb/r` | `-` | - |
| 331 | `/p/fb/v_p` | `/p/part/t/N/p/fb/v_p` | `-` | - |
| 332 | `/p/fb/p_p` | `/p/part/t/N/p/fb/p_p` | `-` | - |
| 333 | `/p/fb/p_p_ofs` | `/p/part/t/N/p/fb/p_p_ofs` | `-` | - |
| 334 | `/p/fb/eg_p` | `/p/part/t/N/p/fb/eg_p` | `-` | - |
| 335 | `/p/fb/eg_r` | `/p/part/t/N/p/fb/eg_r` | `-` | - |
| 336 | `/p/fb/lfo_p` | `/p/part/t/N/p/fb/lfo_p` | `-` | - |
| 337 | `/p/fb/hp` | `/p/part/t/N/p/fb/hp` | `-` | - |
| 338 | `/p/fb/tap` | `/p/part/t/N/p/fb/tap` | `-` | - |
| 339 | `/p/fb/fm/src` | `/p/part/t/N/p/fb/fm/src` | `-` | - |
| 340 | `/p/fb/fm/idx` | `/p/part/t/N/p/fb/fm/idx` | `-` | - |
| 341 | `/p/fx/pan` | `/p/part/t/N/p/fx/pan` | `/g/N/t/fx/pan` | insert-fx-parse |
| 342 | `/p/fx/ins/en` | `/p/part/t/N/p/fx/ins/en` | `/g/N/t/fx/ins/en` | insert-fx-parse |
| 343 | `/p/fx/ins/type` | `/p/part/t/N/p/fx/ins/type` | `/g/N/t/fx/ins/type` | insert-fx-parse |
| 344 | `/p/fx/ins/byp` | `/p/part/t/N/p/fx/ins/byp` | `/g/N/t/fx/ins/byp` | insert-fx-parse |
| 345 | `/p/fx/ins/dry` | `/p/part/t/N/p/fx/ins/dry` | `/g/N/t/fx/ins/dry` | insert-fx-parse |
| 346 | `/p/fx/ins/wet` | `/p/part/t/N/p/fx/ins/wet` | `/g/N/t/fx/ins/wet` | insert-fx-parse |
| 347 | `/p/fx/ins/g-in` | `/p/part/t/N/p/fx/ins/g-in` | `/g/N/t/fx/ins/g-in` | insert-fx-parse |
| 348 | `/p/fx/ins/g-out` | `/p/part/t/N/p/fx/ins/g-out` | `/g/N/t/fx/ins/g-out` | insert-fx-parse |
| 349 | `/p/fx/ins/p` | `/p/part/t/N/p/fx/ins/p` | `/g/N/t/fx/ins/p` | insert-fx-parse |
| 350 | `/p/fx/ins/p/0` | `/p/part/t/N/p/fx/ins/p/0` | `/g/N/t/fx/ins/p/0` | insert-fx-parse |
| 351 | `/p/fx/ins/p/1` | `/p/part/t/N/p/fx/ins/p/1` | `/g/N/t/fx/ins/p/1` | insert-fx-parse |
| 352 | `/p/fx/ins/p/2` | `/p/part/t/N/p/fx/ins/p/2` | `/g/N/t/fx/ins/p/2` | insert-fx-parse |
| 353 | `/p/fx/ins/p/3` | `/p/part/t/N/p/fx/ins/p/3` | `/g/N/t/fx/ins/p/3` | insert-fx-parse |
| 354 | `/p/fx/ins/p/4` | `/p/part/t/N/p/fx/ins/p/4` | `/g/N/t/fx/ins/p/4` | insert-fx-parse |
| 355 | `/p/fx/ins/p/5` | `/p/part/t/N/p/fx/ins/p/5` | `/g/N/t/fx/ins/p/5` | insert-fx-parse |
| 356 | `/p/fx/ins/p/6` | `/p/part/t/N/p/fx/ins/p/6` | `/g/N/t/fx/ins/p/6` | insert-fx-parse |
| 357 | `/p/fx/ins/p/7` | `/p/part/t/N/p/fx/ins/p/7` | `/g/N/t/fx/ins/p/7` | insert-fx-parse |
| 358 | `/p/fx/ins/p/8` | `/p/part/t/N/p/fx/ins/p/8` | `/g/N/t/fx/ins/p/8` | insert-fx-parse |
| 359 | `/p/fx/ins/p/9` | `/p/part/t/N/p/fx/ins/p/9` | `/g/N/t/fx/ins/p/9` | insert-fx-parse |
| 360 | `/p/fx/ins/p/10` | `/p/part/t/N/p/fx/ins/p/10` | `/g/N/t/fx/ins/p/10` | insert-fx-parse |
| 361 | `/p/fx/ins/p/11` | `/p/part/t/N/p/fx/ins/p/11` | `/g/N/t/fx/ins/p/11` | insert-fx-parse |
| 362 | `/p/fx/ins/p/12` | `/p/part/t/N/p/fx/ins/p/12` | `/g/N/t/fx/ins/p/12` | insert-fx-parse |
| 363 | `/p/fx/ins/p/13` | `/p/part/t/N/p/fx/ins/p/13` | `/g/N/t/fx/ins/p/13` | insert-fx-parse |
| 364 | `/p/fx/ins/p/14` | `/p/part/t/N/p/fx/ins/p/14` | `/g/N/t/fx/ins/p/14` | insert-fx-parse |
| 365 | `/p/fx/ins/p/15` | `/p/part/t/N/p/fx/ins/p/15` | `/g/N/t/fx/ins/p/15` | insert-fx-parse |
| 366 | `/p/fx/ins/control1` | `/p/part/t/N/p/fx/ins/control1` | `/g/N/t/fx/ins/control1` | insert-fx-parse |
| 367 | `/p/fx/ins/control2` | `/p/part/t/N/p/fx/ins/control2` | `/g/N/t/fx/ins/control2` | insert-fx-parse |
| 368 | `/p/fbal` | `/p/part/t/N/p/fbal` | `-` | - |
| 369 | `/p/gc` | `/p/part/t/N/p/gc` | `-` | - |
| 370 | `/p/eg_g` | `/p/part/t/N/p/eg_g` | `-` | - |
| 371 | `/p/g` | `/p/part/t/N/p/g` | `-` | gain-message-parse |
| 372 | `/p/pan` | `/p/part/t/N/p/pan` | `-` | pan-message-parse |

## B. global address table (90 entries, lf[0x2832a8])

| # | entry |
|---|---|
| 1 | `/a/main` |
| 2 | `/a/main_mute` |
| 3 | `/a/hph` |
| 4 | `/a/hph_mute` |
| 5 | `/m/main` |
| 6 | `/m/main_mute` |
| 7 | `/m/hph` |
| 8 | `/m/hph_mute` |
| 9 | `/p/mix/aux1-db` |
| 10 | `/p/mix/aux2-db` |
| 11 | `/p/mix/aux3-db` |
| 12 | `/p/mix/aux4-db` |
| 13 | `/p/mix/aux3-send1` |
| 14 | `/p/mix/aux4-send2` |
| 15 | `/p/mix/mic-db` |
| 16 | `/p/mix/line-db` |
| 17 | `/p/mix/mic-aux3` |
| 18 | `/p/mix/line-aux4` |
| 19 | `/p/mix/sub-db` |
| 20 | `/p/mix/sub-bal` |
| 21 | `/p/part/mix/ext-dir3` |
| 22 | `/p/part/mix/ext-dir4` |
| 23 | `/tq` |
| 24 | `/seq/direct-kbd` |
| 25 | `/seq/dest/ip` |
| 26 | `/seq/dest/port` |
| 27 | `/seq/dest/mac` |
| 28 | `/p/part/rseq/0/in/local/en` |
| 29 | `/p/part/rseq/0/in/midi/en` |
| 30 | `/p/part/rseq/0/in/midi/ch` |
| 31 | `/p/part/rseq/0/in/midi/note-min` |
| 32 | `/p/part/rseq/0/in/midi/note-max` |
| 33 | `/p/part/rseq/0/in/usb` |
| 34 | `/p/part/rseq/0/in/cv/0/en` |
| 35 | `/p/part/rseq/0/in/cv/1/en` |
| 36 | `/p/part/las-fx/mode` |
| 37 | `/p/part/las-fx/par` |
| 38 | `/p/part/las-fx/1/en` |
| 39 | `/p/part/las-fx/1/type` |
| 40 | `/p/part/las-fx/1/byp` |
| 41 | `/p/part/las-fx/1/dry` |
| 42 | `/p/part/las-fx/1/wet` |
| 43 | `/p/part/las-fx/1/g-in` |
| 44 | `/p/part/las-fx/1/g-out` |
| 45 | `/p/part/las-fx/1/p` |
| 46 | `/p/part/las-fx/1/p/0` |
| 47 | `/p/part/las-fx/1/p/1` |
| 48 | `/p/part/las-fx/1/p/2` |
| 49 | `/p/part/las-fx/1/p/3` |
| 50 | `/p/part/las-fx/1/p/4` |
| 51 | `/p/part/las-fx/1/p/5` |
| 52 | `/p/part/las-fx/1/p/6` |
| 53 | `/p/part/las-fx/1/p/7` |
| 54 | `/p/part/las-fx/1/p/8` |
| 55 | `/p/part/las-fx/1/p/9` |
| 56 | `/p/part/las-fx/1/p/10` |
| 57 | `/p/part/las-fx/1/p/11` |
| 58 | `/p/part/las-fx/1/p/12` |
| 59 | `/p/part/las-fx/1/p/13` |
| 60 | `/p/part/las-fx/1/p/14` |
| 61 | `/p/part/las-fx/1/p/15` |
| 62 | `/p/part/las-fx/2/en` |
| 63 | `/p/part/las-fx/2/type` |
| 64 | `/p/part/las-fx/2/byp` |
| 65 | `/p/part/las-fx/2/dry` |
| 66 | `/p/part/las-fx/2/wet` |
| 67 | `/p/part/las-fx/2/g-in` |
| 68 | `/p/part/las-fx/2/g-out` |
| 69 | `/p/part/las-fx/2/p` |
| 70 | `/p/part/las-fx/2/p/0` |
| 71 | `/p/part/las-fx/2/p/1` |
| 72 | `/p/part/las-fx/2/p/2` |
| 73 | `/p/part/las-fx/2/p/3` |
| 74 | `/p/part/las-fx/2/p/4` |
| 75 | `/p/part/las-fx/2/p/5` |
| 76 | `/p/part/las-fx/2/p/6` |
| 77 | `/p/part/las-fx/2/p/7` |
| 78 | `/p/part/las-fx/2/p/8` |
| 79 | `/p/part/las-fx/2/p/9` |
| 80 | `/p/part/las-fx/2/p/10` |
| 81 | `/p/part/las-fx/2/p/11` |
| 82 | `/p/part/las-fx/2/p/12` |
| 83 | `/p/part/las-fx/2/p/13` |
| 84 | `/p/part/las-fx/2/p/14` |
| 85 | `/p/part/las-fx/2/p/15` |
| 86 | `/p/lc/kbd/oct` -> `/lc/kbd/oct` (explicit pair) |
| 87 | `/p/lc/kbd/tr` -> `/lc/kbd/tr` (explicit pair) |
| 88 | `/p/lc/kbd/curve` -> `/lc/kbd/curve` (explicit pair) |
| 89 | `/p/lc/xy/mode` -> `/lc/xy/mode` (explicit pair) |
| 90 | `/p/lc/xy/hold` -> `/lc/xy/hold` (explicit pair) |

## C. expression-nodes table (117 entries, lf[0x2826a8]) - DEAD

| # | address | expression-engine symbol | in vx_ee.scm? |
|---|---|---|---|
| 1 | `/p/pre-expr` | (none - empty list) | n/a |
| 2 | `/p/o1/po_m` | `o1po` | yes |
| 3 | `/p/o1/d_m` | `o1d` | yes |
| 4 | `/p/o1/fo_m` | `o1fo` | yes |
| 5 | `/p/o1/tr_m` | `o1tr` | yes |
| 6 | `/p/o1/ang_m` | `o1ang` | yes |
| 7 | `/p/o1/fm1_m` | `o1fm` | yes |
| 8 | `/p/o1/fm2_m` | `o1fm` | yes |
| 9 | `/p/o1/fm3_m` | `o1fm` | yes |
| 10 | `/p/o2/po_m` | `o2po` | yes |
| 11 | `/p/o2/d_m` | `o2d` | yes |
| 12 | `/p/o2/fo_m` | `o2fo` | yes |
| 13 | `/p/o2/tr_m` | `o2tr` | yes |
| 14 | `/p/o2/ang_m` | `o2ang` | yes |
| 15 | `/p/o2/fm1_m` | `o2fm` | yes |
| 16 | `/p/o2/fm2_m` | `o2fm` | yes |
| 17 | `/p/o2/fm3_m` | `o2fm` | yes |
| 18 | `/p/o3/po_m` | `o3po` | yes |
| 19 | `/p/o3/d_m` | `o3d` | yes |
| 20 | `/p/o3/fo_m` | `o3fo` | yes |
| 21 | `/p/o3/tr_m` | `o3tr` | yes |
| 22 | `/p/o3/ang_m` | `o3ang` | yes |
| 23 | `/p/o3/fm1_m` | `o3fm` | yes |
| 24 | `/p/o3/fm2_m` | `o3fm` | yes |
| 25 | `/p/o3/fm3_m` | `o3fm` | yes |
| 26 | `/p/p1/d_m` | `p1d` | yes |
| 27 | `/p/p2/d_m` | `p2d` | yes |
| 28 | `/p/p3/d_m` | `p3d` | yes |
| 29 | `/p/l1/f_m` | `l1f` | yes |
| 30 | `/p/l1/var_m` | `l1v` | yes |
| 31 | `/p/l1/d_m` | `l1d` | **NO** |
| 32 | `/p/l1/ta_m` | `l1ta` | **NO** |
| 33 | `/p/l1/td_m` | `l1td` | **NO** |
| 34 | `/p/l1/ph_m` | `l1ph` | **NO** |
| 35 | `/p/l2/f_m` | `l2f` | yes |
| 36 | `/p/l2/var_m` | `l2v` | yes |
| 37 | `/p/l2/d_m` | `l2d` | **NO** |
| 38 | `/p/l2/ta_m` | `l2ta` | **NO** |
| 39 | `/p/l2/td_m` | `l2td` | **NO** |
| 40 | `/p/l2/ph_m` | `l2ph` | **NO** |
| 41 | `/p/l3/f_m` | `l3f` | yes |
| 42 | `/p/l3/var_m` | `l3v` | yes |
| 43 | `/p/l3/d_m` | `l3d` | **NO** |
| 44 | `/p/l3/ta_m` | `l3ta` | **NO** |
| 45 | `/p/l3/td_m` | `l3td` | **NO** |
| 46 | `/p/l3/ph_m` | `l3ph` | **NO** |
| 47 | `/p/l4/f_m` | `l4f` | yes |
| 48 | `/p/l4/var_m` | `l4v` | yes |
| 49 | `/p/l4/d_m` | `l4d` | **NO** |
| 50 | `/p/l4/ta_m` | `l4ta` | **NO** |
| 51 | `/p/l4/td_m` | `l4td` | **NO** |
| 52 | `/p/l4/ph_m` | `l4ph` | **NO** |
| 53 | `/p/e1/delaym_m` | `e1dlm` | yes |
| 54 | `/p/e1/am_m` | `e1am` | yes |
| 55 | `/p/e1/dm_m` | `e1dm` | yes |
| 56 | `/p/e1/s_m` | `e1s` | yes |
| 57 | `/p/e1/hm_m` | `e1hm` | yes |
| 58 | `/p/e1/rm_m` | `e1rm` | yes |
| 59 | `/p/e2/delaym_m` | `e2dlm` | yes |
| 60 | `/p/e2/am_m` | `e2am` | yes |
| 61 | `/p/e2/dm_m` | `e2dm` | yes |
| 62 | `/p/e2/s_m` | `e2s` | yes |
| 63 | `/p/e2/hm_m` | `e2hm` | yes |
| 64 | `/p/e2/rm_m` | `e2rm` | yes |
| 65 | `/p/e3/delaym_m` | `e3dlm` | yes |
| 66 | `/p/e3/am_m` | `e3am` | yes |
| 67 | `/p/e3/dm_m` | `e3dm` | yes |
| 68 | `/p/e3/s_m` | `e3s` | yes |
| 69 | `/p/e3/hm_m` | `e3h` | **NO** |
| 70 | `/p/e3/rm_m` | `e3rm` | yes |
| 71 | `/p/noise/am_m` | `e1am` | yes |
| 72 | `/p/noise/dm_m` | `e1dm` | yes |
| 73 | `/p/noise/s_m` | `e1s` | yes |
| 74 | `/p/noise/rm_m` | `e1rm` | yes |
| 75 | `/p/fm_m` | `fmidx` | **NO** |
| 76 | `/p/m/e3_p_m` | `e3po` | yes |
| 77 | `/p/m/l1_p_m` | `l1po` | yes |
| 78 | `/p/m/l3_pd_m` | `l3pd` | yes |
| 79 | `/p/m/l3_od_m` | `l3od` | yes |
| 80 | `/p/mix/o1/g_m` | `mixo1` | yes |
| 81 | `/p/mix/o1/plsbal_m` | `o1bal` | yes |
| 82 | `/p/mix/o2/g_m` | `mixo2` | yes |
| 83 | `/p/mix/o2/plsbal_m` | `o2bal` | yes |
| 84 | `/p/mix/o3/g_m` | `mixo3` | yes |
| 85 | `/p/mix/o3/plsbal_m` | `o3bal` | yes |
| 86 | `/p/mix/rm/g_m` | `mixrm` | yes |
| 87 | `/p/mix/n/g_m` | `mixn` | yes |
| 88 | `/p/mix/ext/g_m` | `mixext` | yes |
| 89 | `/p/f/p_m` | `fpn` | yes |
| 90 | `/p/f/r_m` | `fr` | yes |
| 91 | `/p/f/eg_p_m` | `fegpn` | yes |
| 92 | `/p/f/lfo_p_m` | `flpn` | yes |
| 93 | `/p/f/fm_m` | `ffm` | yes |
| 94 | `/p/fa/p_m` | `fapn` | yes |
| 95 | `/p/fa/r_m` | `far` | yes |
| 96 | `/p/fa/eg_p_m` | `faegpn` | yes |
| 97 | `/p/fa/lfo_p_m` | `falpn` | yes |
| 98 | `/p/fa/fm/idx_m` | `fafm` | yes |
| 99 | `/p/fa/1/p_m` | `fa1pn` | yes |
| 100 | `/p/fa/1/r_m` | `fa1r` | yes |
| 101 | `/p/fa/1/eg_p_m` | `fa1egpn` | yes |
| 102 | `/p/fa/1/lfo_p_m` | `fa1lpn` | yes |
| 103 | `/p/fa/1/fm_m` | `fa1fm` | yes |
| 104 | `/p/fa/2/p_m` | `fa2pn` | yes |
| 105 | `/p/fa/2/r_m` | `fa2r` | yes |
| 106 | `/p/fa/2/eg_p_m` | `fa2egpn` | yes |
| 107 | `/p/fa/2/lfo_p_m` | `fa2lpn` | yes |
| 108 | `/p/fa/2/fm_m` | `fa2fm` | yes |
| 109 | `/p/fb/p_m` | `fbpn` | yes |
| 110 | `/p/fb/r_m` | `fbr` | yes |
| 111 | `/p/fb/eg_p_m` | `fbegpn` | yes |
| 112 | `/p/fb/fm_m` | `fbfm` | yes |
| 113 | `/p/fb/lfo_p_m` | `fblpn` | yes |
| 114 | `/p/fbal_m` | `fbal` | yes |
| 115 | `/p/g_m` | `vca` | yes |
| 116 | `/p/pan_m` | `pan` | yes |
| 117 | `/p/post-expr` | (none - empty list) | n/a |
