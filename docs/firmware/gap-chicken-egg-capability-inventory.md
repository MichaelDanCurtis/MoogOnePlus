# The CHICKEN egg registry — the Scheme layer's real capability surface

**Scope.** Every installed CHICKEN extension ("egg") in the decrypted v1.8.2
rootfs, what each one *can* do, and — separately — which of them are actually
linked into a shipping Moog program and which of their procedures get called.
The existing reports cover the Moog-authored units (`csosc`, `eec`, `las-sc`,
`lassvc`, the `vx*` tools) and their OSC dispatch. They do **not** inventory the
third-party substrate those programs statically link for networking,
serialization, JSON, CSV, and text parsing. That substrate is this report.

**Evidence grading.** `[READ]` = read directly out of a file, offset or line
given. `[INFERRED]` = reasoning from stated evidence, evidence named.
`[UNKNOWN]` = not established. Nothing here is `[TESTED]`. **This pass touched no
instrument.**

**Paths.** `R182` = `captures/firmware-1.8.2/rootfs-1.8.2`,
`R150` = `captures/rootfs-1.5.0`. `REG` = `R182/usr/lib/chicken/8` (the egg
registry). All offsets are decimal file offsets unless marked otherwise.

**A naming note used throughout.** CHICKEN 4 compiles each unit's exported
bindings under a `module#binding` symbol — e.g. `socket#socket-connect`,
`medea#write-json`. A program that *calls* an egg's procedures therefore carries
that egg's `module#…` literals in its symbol/trace table. An egg that is only
*required* (pulled in for its macros, or linked but whose procedures are reached
through a shared unit) leaves its bare name as a `##sys#require` argument but no
`module#` call token. This report uses that distinction as its primary evidence,
and states where it is load-bearing.

> Reproduces egg names, version stamps, and exported-binding identifiers from a
> Moog firmware image, plus the third-party library identities they embed.
> Treated the same as other binary-derived inventories in `docs/firmware/`. See
> `docs/INTERNAL-DO-NOT-DISTRIBUTE.md`.

---

## 0. Headline

**The Scheme layer's third-party capability surface is: raw + connection TCP and
UDP sockets (`socket`, `udp6`), native binary serialization (`s11n`), JSON
*emission* (`medea`), RFC-4180 CSV (`csv`), CSP-style concurrency (`gochan`),
and a large text/parser toolkit (`comparse`, `abnf`, `lexgen`, `silex`,
`regex`, `numbers`, `utf8`, …).** But those capabilities split cleanly into two
populations, and the split is the main finding:

* **Wired in and used.** `socket`, `udp6`, `s11n`, `medea`, `csv`, `gochan`,
  `bitstring`, `fmt`, `ncurses`, `curses-readline`, `simple-exceptions`, `args`,
  `srfi-37`, `srfi-60`, `vector-lib`, plus the macro eggs `matchable` and
  `defstruct`, and the Moog `csosc`. Each has a named call site. `[READ]`
* **Present in the registry but linked into no shipping program.** `comparse`,
  `abnf`, `abnf-charlist`, `abnf-consumers`, `lexgen`, `silex`, `regex`,
  `numbers`, `trie`, `iset`, `lazy-seq`, `suffix-tree`, `typeclass`,
  `list-utils` (call-wise), `make`, `foreigners`, `easyffi`, the `check-errors`
  family, `datatype`, `datatypes`, `input-classes`, and the whole `utf8-*` set.
  These are build-time dependencies of the used eggs (e.g. `medea`→`comparse`,
  `csv`→`abnf`) that the static compiler did **not** carry into the final
  programs, plus general-purpose eggs never required at all. `[INFERRED]`

Two specific refinements of the task's hypothesis:

1. **JSON is emit-only.** `medea#write-json` and `medea#json->string` are
   referenced; `medea#read-json` / `medea#json-parsers` are referenced
   **nowhere**. The parser half of `medea` (and its `comparse` dependency) is not
   linked into any program. The firmware *produces* JSON; it does not *consume*
   it. `[READ]`
2. **JSON lives only in factory/service tooling, never the audio path.** Its two
   users are `vxtune` (converts its tuning-test log from s-expressions to JSON on
   request) and `vxreport` (builds Google-Charts DataTable JSON for an HTML
   temperature-calibration report). Neither runs during normal play. `[READ]`

The entire registry is **byte-for-byte functionally identical between v1.5.0 and
v1.8.2**: all 126 compiled `.so` objects have identical `.text` disassembly
across the two releases. `[READ]`

---

## 1. The registry, by the numbers

`REG` (`R182/usr/lib/chicken/8`) holds, counted directly `[READ]`:

| artifact | count |
|---|---|
| `*.setup-info` manifests (one per installed egg payload) | **75** |
| distinct `egg-name` values inside those manifests | **47** |
| compiled `.so` objects (`*.so`, incl. `*.import.so`) | **126** |
| runtime module `.so` (non-`import`) | 63 |

The 75-vs-47 gap is because several eggs install multiple named payloads that
share one `egg-name`. `[READ, grep of (egg-name …) across REG/*.setup-info]`
Examples: the `utf8` egg ships `utf8`, `utf8-lolevel`, `utf8-srfi-13`,
`utf8-srfi-14`, `utf8-case-map`, `unicode-char-sets` (6 manifests, one
`egg-name`); the `check-errors` egg ships `check-errors`, `srfi-4-checks`,
`srfi-4-errors`, `type-checks`, `type-errors` (5); the `fmt` egg ships `fmt`,
`fmt-c`, `fmt-color`, `fmt-js`, `fmt-unicode` (5); `csv` ships `csv`,
`csv-string`, `csv-char-list` (3). Critically, **the five `vx*` tools plus
`las_clock_demo` and `lassvc` all carry `egg-name "las-sc"`** — they are
sub-programs of one Moog build, not separate eggs. `[READ, e.g.
REG/vxtune.setup-info: (egg-name "las-sc")]`

The CHICKEN runtime itself is **4.13.0**. `[READ, R182/usr/lib/libchicken.so.8
offset 3208016 "4.13.0"]` The `/8` in the path is CHICKEN 4's
binary/repository version, not a release number. `libchicken.so.8` is identical
across the two firmwares (`md5 10b9da4e0f164b897d834e8f92d87df8`). `[READ]`

There is **no CHICKEN toolchain on the device**: `csi`, `csc`, `chicken`,
`chicken-install`, `chicken-status`, `chicken-uninstall` are all absent.
`[READ, find over R182]` Only the runtime library and the pre-compiled eggs are
shipped. The `.import.so` files (used by the compiler to resolve imports) and the
`.setup-info` manifests are present as installation residue but have no runtime
role on a device that cannot compile.

### 1.1 Full version table

Extracted from each `(version …)` field `[READ, grep over REG/*.setup-info]`.
`"unknown"` is the literal stored value, not a gap in this report. Versions are
identical in both firmwares.

| egg | version | egg | version | egg | version |
|---|---|---|---|---|---|
| abnf | 7.0 | gochan | 5.2.8 | s11n | unknown |
| ansi-escape-sequences | 0.4 | iset | 2.0 | setup-helper | 2.0.0 |
| args | 1.5.1 | las-sc | unknown | silex | 1.4 |
| binary-parse | 1.3 | las_clock_demo | unknown | simple-exceptions | 0.6 |
| bitstring | 1.34 | lassvc | unknown | socket | **0.2.6** |
| check-errors | 2.1.0 | lazy-seq | 0.0.7 | srfi-133 | 1.4 |
| chicken-dump | unknown | lexgen | 7.1 | srfi-34 | 0.6 |
| chicken-wrap | unknown | list-utils | 1.3.0 | srfi-37 | 1.3.1 |
| comparse | unknown | make | 1.8 | srfi-4-checks | 2.1.0 |
| csosc | 0.0.3 | matchable | 3.7 | srfi-4-errors | 2.1.0 |
| csv | 5.3 | medea | **unknown** | srfi-60 | 0.3 |
| csv-char-list | 5.3 | ncurses | 1.6 | suffix-tree | 2.0 |
| csv-string | 5.3 | numbers | 4.6.3 | trie | 0.0.1 |
| curses-readline | 0.0.2 | osclog | unknown | type-checks | 2.1.0 |
| datatype | 1.4 | oscterm | unknown | type-errors | 2.1.0 |
| datatypes | 1.3.3 | regex | 1.0 | typeclass | 1.3 |
| defstruct | 1.6 | setup-helper-mod | 2.0.0 | udp6 | **0.1** |
| easyffi | 1.99.7 | eec | unknown | unicode-char-sets | 3.4.4 |
| feature-test | 0.1 | foreigners | 1.4.1 | utf8 | 3.4.4 |
| fmt | 0.808 | input-classes | 1.0 | vector-lib | 1.2.2 |

`chicken-wrap.setup-info` carries a typo field `(verison "1.99.7")` alongside its
`(version "unknown")`. `[READ]` The only networking eggs with real version
stamps are `socket 0.2.6` and `udp6 0.1`; `medea` and `s11n` both stamp
`"unknown"`.

### 1.2 Build provenance is not an authorship signal

Every manifest's payload path is rooted at a buildroot sysroot:
`…/las-buildroot/output/…/usr/lib/chicken/8/…`. `[READ, REG/medea.setup-info]`
The CI prefix differs between releases — v1.8.2 uses
`las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot`, v1.5.0 uses
`las-ci-builds/6c53963c/0/moogmusic/las-buildroot` `[READ, compared
REG/medea.setup-info vs R150/usr/lib/chicken/8/medea.setup-info]` — so the
buildroot path is a build-fingerprint, **not** a way to tell Moog code from
upstream eggs. The real authorship discriminator is the payload location: the 13
eggs that install into `target/usr/bin/` rather than `…/chicken/8/` are the
programs — `chicken-dump`, `chicken-wrap`, `eec`, `las-sc`, `las_clock_demo`,
`lassvc`, `osclog`, `oscterm`, `vxmon`, `vxping`, `vxreport`, `vxtest`,
`vxtune`. `[READ, grep 'target/usr/bin/' REG/*.setup-info]` Of those, two are
upstream tools rebadged by their payload: `chicken-dump` has `egg-name "s11n"`
(it is the `s11n` egg's `chicken-dump` utility) and `chicken-wrap` has
`egg-name "easyffi"`. `[READ]`

---

## 2. v1.5.0 → v1.8.2: the registry did not change

**Every one of the 126 `.so` objects in `REG` has `.text` disassembly identical
to its v1.5.0 counterpart.** `[READ, llvm-objdump -d --section=.text over all
126 pairs; 126 identical, 0 differing, 0 missing]` The files are not bitwise
identical — `cmp -l` reports byte differences (e.g. `socket.so` 18,071 bytes,
`fmt.so` 31,383, `silex.so` 37,402) — but those differences are confined to the
`.rodata` region that stores CHICKEN's internal lambda-numbering debug strings.
For `udp6.so` the differing bytes decode as, e.g., `f_567:udp6-mod.scm` (1.8.2)
vs `f613:udp6-mod.scm` (1.5.0) — the compiler assigned different internal
function numbers, nothing more. `[READ, hexdump of udp6.so at offset ~18646 in
both releases]` The executable code of every egg is unchanged.

`matchable.so` is the one egg that is **bitwise** identical across releases
(`cmp` reports 0 differing bytes) `[READ]` — consistent with it being a
macro-only egg (§4.2) whose `.so` carries no lambda-numbered runtime code.

The practical consequence: a capability statement about the egg layer in 1.8.2 is
equally a statement about 1.5.0. The instrument the owner runs (1.5.0) has the
same Scheme capability surface as the decrypted 1.8.2 image.

---

## 3. Three tiers of usage

The 47 eggs are not uniform. Classified by how the 11 CHICKEN programs
(`las-sc`, `lassvc`, `vxmon`, `vxtune`, `vxtest`, `vxreport`, `vxping`, `osclog`,
`oscterm`, `las_clock_demo`, `eec`) relate to them `[READ, union of `module#`
call-token scan and `##sys#require` bare-name scan over all 11 binaries]`:

**Tier 1 — linked and called** (a `module#…` call token is present in ≥1
program): `csosc`, `socket`, `udp6`, `s11n`, `medea`, `csv`, `gochan`,
`bitstring`, `fmt`, `ncurses`, `curses-readline`, `simple-exceptions`, `args`,
`srfi-37`, `srfi-60`, `vector-lib`, `ansi-escape-sequences`, and (in
`chicken-wrap` only) `easyffi-base`.

**Tier 2 — compiled in for macros, no runtime call token** (bare name appears as
a `##sys#require` argument; these are syntax eggs whose forms expand at compile
time): `matchable`, `defstruct`, `srfi-133`, `list-utils`. `matchable` and
`defstruct` in particular export **zero** runtime bindings `[READ,
REG/matchable.import.so and REG/defstruct.import.so list no `module#` symbols]`
— their `match` and `defstruct` forms are macros.

**Tier 3 — in the registry, linked into no shipping program**: `abnf`,
`abnf-charlist`, `abnf-consumers`, `comparse`, `lexgen`, `silex`, `regex`,
`numbers`, `trie`, `iset`, `lazy-seq`, `suffix-tree`, `typeclass`, `make`,
`foreigners`, `easyffi`, `check-errors`, `srfi-4-checks`, `srfi-4-errors`,
`type-checks`, `type-errors`, `datatype`, `datatypes`, `input-classes`,
`feature-test`, `setup-helper`/`-mod`, and the `utf8-*`/`csv-string`/
`csv-char-list`/`fmt-*` sub-payloads. `[INFERRED from: no `module#` token and no
bare-name require in any of the 11 programs]` Several of these are genuine
dependencies of Tier-1 eggs at build time — `medea` declares `(require comparse)`
`[READ, comparse appears as `##sys#require` arg inside REG/medea.so]`, `csv`
declares `(require abnf-consumers abnf regex utf8-srfi-14 utf8-srfi-13 utf8
typeclass)` `[READ, inside REG/csv.so]` — but the static compiler did not carry
those transitive units into the final programs (see §7 and §9). The rest are
general-purpose eggs that nothing in the firmware uses.

### 3.1 Per-binary linkage matrix

`●` = procedures called (`module#…` token present). `○` = required/compiled-in
only (bare name present, no call token). `·` = absent. `[READ, NUL-delimited
token scan of each binary]`

| egg | las-sc | lassvc | vxmon | vxtune | vxtest | vxreport | vxping | osclog | oscterm | clock | eec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| csosc | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● |
| socket | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | · |
| udp6 | ● | ● | ○ | ○ | ○ | ○ | ○ | ● | ● | ○ | ● |
| s11n | ● | ● | ● | ● | ● | ● | · | · | · | · | · |
| medea | · | · | · | ● | · | ● | · | · | · | · | · |
| gochan | ● | ● | ● | ● | ● | ● | ● | · | · | ● | · |
| bitstring | ● | ● | ● | ● | ● | ● | ● | · | · | ● | · |
| fmt | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● |
| ncurses | ● | ● | ● | ● | ● | · | · | · | ● | · | · |
| curses-readline | ● | ● | ● | ● | ● | · | · | · | ● | · | · |
| simple-exceptions | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● |
| args | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● |
| srfi-37 | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● |
| srfi-60 | · | ● | · | · | · | · | · | · | · | · | · |
| vector-lib | ● | ● | ● | ● | ● | ● | · | · | · | · | · |
| csv | · | · | · | ● | · | · | · | ○ | · | · | · |
| srfi-133 | ○ | ○ | ○ | ○ | ○ | ○ | ○ | · | · | ○ | · |
| matchable | ○ | ○ | ○ | ○ | ○ | ○ | ○ | · | ○ | ○ | · |
| defstruct | ○ | ○ | ○ | ○ | ○ | ○ | ○ | · | ○ | ○ | · |
| ansi-escape-sequences | · | · | · | · | · | · | ● | · | · | · | · |
| eec | ○ | · | · | · | · | · | · | · | · | · | · |

The `udp6` ○/● split is an artifact of where the call sites sit: the direct
`udp6#…` calls live in `sc/sc.scm` (las-sc), `lassvc.scm`, `osclog.scm`,
`oscterm.scm`, `las_clock_demo`/`las-comm`, and `eec`; the other `vx*` tools link
the same `las-comm`/`sockutil` units but reach the socket through shared
helpers. `[READ, udp6# call-site lines §5.2]` `eec` requires `eec` in `las-sc`
(Tier-2 ○) but calls nothing from it — already documented in
`gap-eec-expression-compiler.md` §9.2; consistent here.

---

## 4. The concurrency and formatting core (brief — partly covered elsewhere)

These four eggs underpin everything and are noted for completeness; `csosc` and
`eec` have their own reports.

* **`csosc` 0.0.3** — Moog's OSC codec, linked into all 11 programs. 84 exported
  bindings `[READ, REG/csosc.import.so]`: message/bundle constructors
  (`make-osc-msg`, `make-osc-bundle`, `osc-bundle`), a full encode set
  (`osc-encode-int32`/`-float32`/`-string`/`-timetag`/`-u32vector`…), a decode
  set (`osc-decode-int32`/`-float32`/`-string`/`-blob*`…), a dispatcher
  (`osc-make-dispatcher`, `osc-match`, `osc-match-prefix?`), and
  `u32vector`↔message conversions. This is the serialization layer for the entire
  `/p`, `/cal`, `/vx`, `/info` plane. It `(require matchable)`. `[READ, `matchable`
  is a `##sys#require` arg inside REG/csosc.so]`
* **`gochan` 5.2.8** — Go-style CSP channels (`gochan`, `gochan-send`,
  `gochan-recv`, `gochan-select*`, `gochan-close`, `gochan-after`, `gotimer`).
  `[READ, REG/gochan.import.so]` Used for the async job runner (`cal/jobs.scm`),
  the tuning-DB server thread (`cal/vxtune-db.scm:212` `gochan#gochan`,
  `:218` `gochan-send`, `:204` `gochan-close`), and `las-comm`. `[READ, trace
  lines]` `(require matchable)`.
* **`fmt` 0.808** — the formatting combinator library, linked into all 11
  programs; by far the most-called egg (≈1,700 `fmt#…` call sites across the
  set). `[READ, trace-string count]` 79 bindings incl. `fmt`, `cat`, `dsp`,
  `num`, `pad`, columns/tabular helpers. `[READ, REG/fmt.import.so]`
* **`bitstring` 1.34** — bit-field packing/unpacking with IEEE-float
  conversions (`bitstring->double`/`->single`/`->half`, `integer->bitstring`,
  `bitstring-read`). `[READ, REG/bitstring.import.so]` Used in `las-comm` and
  `vxmon-lib` for wire framing (`bitstring#->bitstring` at `las-comm.scm:278`,
  `:280`). `[READ]`

---

## 5. Networking: `socket` + `udp6`

The Scheme layer has two distinct socket capabilities, both upstream eggs.

### 5.1 `socket` 0.2.6 — connection and name-resolution

The `socket` egg exports **179 bindings** `[READ, REG/socket.import.so]`,
covering the full BSD surface: address families (`af/inet`, `af/inet6`,
`af/unix`, `af/unspec`), socket types (`sock/stream`, `sock/dgram`,
`sock/raw`), protocols (`ipproto/tcp`, `ipproto/udp`), `getaddrinfo`
(`address-information` + the `ai/*` flag set), `getnameinfo`, and the full
`socket`/`bind`/`connect`/`send`/`receive`/`listen`/`accept` call set with
`setsockopt` accessors.

What Moog code **actually calls** is a 17-procedure subset `[READ, union of
`socket#…` trace tokens across all binaries]`:

```
address-information   addrinfo-address      sockaddr->string
sockaddr-address      sockaddr-family       sockaddr-port
socket                socket-bind           socket-connect
socket-connect/ai     socket-peer-name      socket-receive
socket-receive-ready? socket-receive-timeout socket-send
socket-send-buffer-size                     socket-type
```

The canonical use is `las/sockutil.scm`: `parse-host-port` →
`socket#address-information` (`:35`) → `socket#socket-connect/ai` (`:38`) for a
getaddrinfo-driven connection, with `socket#socket` + `socket#addrinfo-address`
(`:41`–`:43`) as the lower-level path. `[READ, trace lines
las/sockutil.scm:35/38/42/43]` This is the TCP/stream connector used to reach the
control plane.

**Capability vs use, and it is load-bearing:** the egg exposes `af/inet6` and
`sock/raw`, but **every binary references only `af/inet`, `sock/dgram`, and
`sock/stream`** `[READ, `socket#(af|sock)/…` token scan across all 10 programs
that link socket — only those three in each]`. The Scheme layer *could* open
IPv6 or raw sockets; as shipped it opens only IPv4 stream and datagram sockets.
`[INFERRED from the absence of `af/inet6`/`sock/raw` call tokens]`

### 5.2 `udp6` 0.1 — datagram I/O

A minimal UDP egg, 13 bindings `[READ, REG/udp6.import.so]`:

```
udp-open-socket  udp-open-socket*  udp-close-socket  udp-socket?
udp-bind!        udp-bound?        udp-bound-port
udp-connect!     udp-connected?
udp-send  udp-sendto  udp-recv  udp-recvfrom
```

Despite the `6`, this is the ordinary UDP egg (the name is the upstream egg's,
not an IPv6 marker). `[INFERRED — its source unit is `udp6-mod.scm` and it
exposes no v6-specific API; READ for the unit name from REG/udp6.so lambda
strings]` Call sites `[READ, trace lines]`: the `las-sc` OSC transport
(`sc/sc.scm:172` `udp-recv`, `:176` `udp-sendto`, a long run of `:182`–`:362`
`udp-send`, `:940` `udp-close-socket`), `osclog.scm:21/34`
(`udp-send`/`udp-recvfrom`), `oscterm.scm:720/736/772`
(`udp-recvfrom`/`udp-send`/`udp-open-socket`), and `lassvc.scm:2213`
(`udp-send`). The datagram path is how OSC messages move; the `socket` egg
handles the stream/connection side.

Both eggs are pure-Scheme wrappers over libc sockets — each needs only
`libchicken`, `libm`, `libdl`, `libc` (no extra native dep). `[READ,
llvm-objdump -p on socket.so/udp6.so: NEEDED lists those four only]`

---

## 6. Serialization: `s11n`

`s11n` (version `"unknown"`) exports exactly three bindings `[READ,
REG/s11n.import.so]`:

```
s11n#serialize   s11n#deserialize   s11n#serialization-mode
```

It is CHICKEN's native binary object serializer — it marshals arbitrary Scheme
data (pairs, vectors, hash tables, records) to a byte stream and back.
`chicken-dump` (§1.2) is the `s11n` egg's own utility for dumping such files
`[READ, chicken-dump's usage string + egg-name "s11n"]`.

The **only** Moog use is the `vxtune` tuning database, in
`cal/vxtune-db.scm`, linked into `las-sc`, `lassvc`, `vxmon`, `vxtune`,
`vxtest`, `vxreport`. The round trip `[READ, trace lines]`:

* write: `cal/vxtune-db.scm:154` `s11n#serialize` wrapped in
  `with-output-to-file` (`:154`). `[READ, las-sc offsets 2156213/2156256]`
* read: `cal/vxtune-db.scm:144` and `:147` `with-input-from-file`, feeding
  `s11n#deserialize`. `[READ, offsets 2156487/2156559; `s11n#deserialize`
  literal at 2155012]`

Neither `serialization-mode` appears as a call token, so the default (serialize
mode) is used. `[INFERRED from absence of a `serialization-mode` call token]`
This is the mechanism behind the `/var/tuning.vxtune/*` files and the
`s11n` encoding already documented in `docs/firmware/calibration.md` §5.2 — this
report confirms the egg identity, its three-binding surface, and the exact
read/write call sites, and does not contradict that section.

---

## 7. JSON: `medea` — and it is emit-only

`medea` (version `"unknown"`) exports five bindings `[READ,
REG/medea.import.so]`:

```
medea#read-json   medea#write-json   medea#json->string
medea#json-parsers   medea#json-unparsers
```

`medea` is the standard CHICKEN JSON egg. It `(require comparse)` — its parser is
built on the `comparse` parser-combinator library. `[READ, `comparse` is a
`##sys#require` arg inside REG/medea.so]`

**Only the emitter half is linked into any program.** `[READ]`

* `medea#write-json` — referenced **only** in `vxtune`. `[READ, offset 2449661
  "cal/vxtune.scm:3279: medea#write-json"]`
* `medea#json->string` — referenced **only** in `vxreport`. `[READ, offsets
  684440 and 684651 "mon/gchart.scm:58/32: medea#json->string"]`
* `medea#read-json`, `medea#json-parsers`, `medea#json-unparsers` — referenced in
  **no** binary. `[READ, grep across all binaries: zero hits]`
* `comparse` — referenced in **no** binary; `grep -c comparse vxtune` = 0,
  `vxreport` = 0. `[READ]` The parser dependency was dead-stripped by the static
  compiler because only the unparser path is reached.

So the firmware can *write* JSON but has no compiled-in path to *read* it. The
task's hypothesis ("an undocumented data format those tools produce or consume")
resolves to **produce only**.

### 7.1 The two JSON producers, precisely

1. **`vxtune` tuning-test log.** `vxtune` takes a `--log-format` option
   documented as `"Log Format (s-exp or json - default s-exp)"` `[READ, offset
   2431708]`. Its `sexp-file->json-file` routine `[READ, offset 2449517 +
   M-record 2956099 "M(sexp-file->json-file fname10421)"]` reads an s-expression
   log with `read` and writes JSON via `medea#write-json` inside
   `call-with-output-file` (`cal/vxtune.scm:3286`→`:3288`→`:3279`). `[READ,
   surrounding trace lines]` The default is s-exp; JSON is opt-in.
2. **`vxreport` HTML calibration report.** `mon/gchart.scm` builds a Google
   Charts `DataTable`: `gchart-DataTable-constructor` (`:56`) then
   `medea#json->string` (`:58`, and column data at `:32`) to emit the JS data
   literal. `[READ, trace lines 684912/684440/684651]` The surrounding HTML
   template embeds `https://www.gstatic.com/charts/loader.js`,
   `google.charts.load('current', {'packages':['corechart']})`, and a
   `ScatterChart`, producing a standalone "Temperature calibration report" HTML
   page (`report-tcal-html`). `[READ, string literals at offsets 686998, 687754,
   683979]` `vxreport` can alternatively emit `set term svg` gnuplot output.
   `[READ, offset 688348]`

Both are offline calibration/test artifacts. No JSON path exists in `las-sc`
(the boot/runtime process) — it links neither `medea` nor `comparse`. `[READ,
linkage matrix §3.1]`

---

## 8. CSV: one real egg plus hand-rolled writers

The `csv` egg (5.3) exports a small RFC-4180 surface — `make-parser`,
`make-format`, `csv-record->list`, `list->csv-record`, `csv-record?`,
`CoreABNF->CSV` `[READ, REG/csv.import.so]` — and is a heavyweight at build time:
it `(require abnf-consumers abnf regex utf8-srfi-14 utf8-srfi-13 utf8
typeclass)`. `[READ, inside REG/csv.so]`

**Only `vxtune` links it**, and only for the writer: `csv#list->csv-record` is
called in a dense run (`cal/vxtune.scm:2279`–`:2338`, dozens of rows) plus
`csv#make-format`. `[READ, trace lines]` The `abnf`/`regex`/`utf8` parser chain
`csv` declares was **not** carried into `vxtune` — no `abnf#`/`regex#`/`utf8#`
tokens appear. `[READ, token scan of vxtune]` As with `medea`, only the emitter
path survived static linking.

Elsewhere, CSV is produced **without** the egg. `vxmon`'s `mon/vxmon-lib.scm` has
`format-data-cells-csv`, `print-log-header-csv`, `print-log-line-csv` (`:181`,
`:275`, `:279`); `vxreport` has `print-temptbl-csv`/`print-codetbl-csv`/
`print-freqtbl-csv`; `osclog` has `write-header`/`write-result` to a
`csv-port`. `[READ, M-records / trace lines]` These are plain `fmt`-based
string assembly, not `csv`-egg calls. `osclog` carries a bare `csv` token
(Tier-2 ○ in the matrix) but no `csv#` call token `[READ]`; its CSV output is
hand-rolled.

---

## 9. The parser/text substrate — present, unused by shipping programs

The registry contains a substantial text-processing and parsing toolkit that the
task flagged (`comparse`, `abnf`, `lexgen`, `silex`, `binary-parse`), plus
general-purpose data-structure eggs. **None of them is linked into any of the 11
shipping programs** (no `module#` token, no bare-name require). `[READ, token
scan across all 11 binaries — zero hits for each name below]`

| egg | version | what it is | why it is here |
|---|---|---|---|
| `comparse` | unknown | parser combinators (`parse`, `satisfies`, `sequence`, `repeated`, `maybe`, `followed-by`, `as-string` — 35 bindings) | build-time dep of `medea` (§7). Dead-stripped. `[INFERRED]` |
| `abnf` / `abnf-charlist` / `abnf-consumers` | 7.0 | RFC-5234 ABNF grammar construction on top of `lexgen` | build-time dep of `csv` (§8). Dead-stripped. `[INFERRED]` |
| `lexgen` | 7.1 | lexer-generator combinators (`lex`, `tok`, `star`, `seq`, `bar`) | dep of `abnf`/`csv`. `[READ, abnf.so requires lexgen]` |
| `silex` | 1.4 | table-driven lexer generator (267 bindings) — the largest egg (669 KB) | required by nothing in the egg graph; general-purpose residue. `[READ, no egg `(require silex)`]` |
| `regex` | 1.0 | `string-search`/`-match`/`-substitute`, `glob->regexp` | thin wrapper; **redundant** — `libchicken` already provides `irregex` (`C_irregex_toplevel`). Dep of `csv`/`utf8`. `[READ, irregex in libchicken; regex unused by programs]` |
| `numbers` | 4.6.3 | full numeric tower (bignums, rationals, 157 bindings) | required by nothing; general-purpose residue. `[READ]` |
| `binary-parse` | 1.3 | `make-bit-reader` (1 binding) | unused by any program. `[READ]` |
| `trie` | 0.0.1 | prefix trees | unused. `[READ]` |
| `iset` | 2.0 | integer sets (82 bindings) | dep of `utf8-srfi-13`; unused by programs. `[READ]` |
| `lazy-seq` | 0.0.7 | lazy sequences (33 bindings) | unused. `[READ]` |
| `suffix-tree` | 2.0 | suffix trees | `(require matchable datatype)`; unused by programs. `[READ]` |
| `typeclass` / `datatype` / `datatypes` / `input-classes` | — | Haskell-style type classes / ADTs | deps of `abnf`/`csv`/`suffix-tree`; unused directly. `[READ]` |
| `utf8` family (`utf8`, `-lolevel`, `-srfi-13`, `-srfi-14`, `-case-map`, `unicode-char-sets`) | 3.4.4 | Unicode string ops, with `case-map-1.dat`/`case-map-2.dat` data files | deps of `csv`/`abnf`; not linked into programs. `[READ]` |
| `list-utils` | 1.3.0 | alist/plist helpers (`zip-alist`, `section`, `shift!`) | required by `sc/sc.scm` and `cal/cal.scm` (Tier-2 ○) but no `list-utils#` call token. `[READ]` |
| `make` | 1.8 | dependency-driven build rules | unused residue. `[READ]` |
| `foreigners` / `easyffi` / `easyffi-base` | 1.4.1 / 1.99.7 | compile-time FFI helpers | `easyffi-base` is used only by `chicken-wrap` (§1.2); `foreigners`/`easyffi` unused on device (no compiler). `[READ]` |
| `check-errors` / `srfi-4-checks` / `srfi-4-errors` / `type-checks` / `type-errors` | 2.1.0 | argument-checking macros | deps of `list-utils`; carry `.o`/`.types`/`.inline` files for the compiler. Unused at runtime. `[READ]` |

These are present because buildroot installed the full transitive dependency
closure of the eggs Moog's code `(require)`s, and because `silex`/`numbers`/
`make` etc. were in the egg set the build pulled. On a device with no compiler,
the `.import.so`, `.o`, `.types`, and `.inline` files among them can never be
used. `[INFERRED — no `csi`/`csc`/`chicken-install` present, §1]`

They still define the Scheme layer's *latent* capability: the code to do
parser-combinator grammars, lexing, a full numeric tower, and Unicode handling
is on the disk and loadable by any CHICKEN program built against this repository.
What is missing is a compiler to build such a program on-device.

---

## 10. `las-frontend` links `libchicken` but exposes no egg surface

`las-frontend` (the 145 MB UI binary) lists `libchicken.so.8` in its `NEEDED`
entries `[READ, llvm-objdump -p las-frontend]`, and contains the string
`CHICKEN_main` once `[READ]`. But it carries **no** `C_*_toplevel` unit symbols,
**no** `toplevel:` source markers, and **no** `module#…` egg call tokens for any
egg (`csosc#`, `socket#`, `medea#`, etc. all return 0). `[READ, token scans]`
Its undefined dynamic symbols are C++/GLIBCXX, not CHICKEN runtime entry points.
`[READ, llvm-nm -D -u las-frontend]`

So the egg capability surface in this report is the surface of the **CHICKEN
program family** (`las-sc`, `lassvc`, the `vx*`/`osc*` tools, `eec`). Whether
`las-frontend` uses CHICKEN's embedded evaluator for anything, and by what path
it reaches `libchicken`, is **[UNKNOWN]** from strings alone; it is a C++/Qt
application (see `docs/firmware/gap-qt5-webkit-jsc-runtime.md`) that links
`libchicken` as a dependency without the static-unit signature the other programs
show. This report does not attempt to resolve it.

---

## 11. Validation plan — READ-ONLY, for a human to run

All of these run on the **captures on disk**, not the instrument. No command
below contacts `192.168.1.x` or `203.0.113.x`, and none executes a Moog binary.

```sh
R182="captures/firmware-1.8.2/rootfs-1.8.2"
R150="captures/rootfs-1.5.0"
REG="$R182/usr/lib/chicken/8"
TC=/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin

# 1. Registry counts (§1): 75 setup-info, 47 egg-names, 126 .so.
ls "$REG"/*.setup-info | wc -l
grep -ho '(egg-name "[^"]*")' "$REG"/*.setup-info | sort -u | wc -l
ls "$REG"/*.so | wc -l

# 2. CHICKEN runtime version (§1): 4.13.0.
strings -a "$R182/usr/lib/libchicken.so.8" | grep -x '4\.13\.0'

# 3. Registry unchanged across releases (§2): all .text identical.
for f in "$REG"/*.so; do n=$(basename "$f");
  a=$("$TC/llvm-objdump" -d --section=.text "$f"      | sed 's/^[^\t]*\t//');
  b=$("$TC/llvm-objdump" -d --section=.text "$R150/usr/lib/chicken/8/$n" | sed 's/^[^\t]*\t//');
  [ "$a" = "$b" ] || echo "DIFFERS: $n"; done    # prints nothing if all identical

# 4. JSON is emit-only (§7): write-json/json->string present, read-json absent.
for b in las-sc lassvc vxmon vxtune vxtest vxreport vxping osclog oscterm las_clock_demo eec; do
  echo -n "$b: "; strings -a "$R182/usr/bin/$b" | grep -oE 'medea#[a-z>-]+' | sort -u | tr '\n' ' '; echo; done
#   expect write-json only in vxtune, json->string only in vxreport, read-json nowhere.

# 5. socket uses IPv4 stream+dgram only (§5.1): no af/inet6, no sock/raw.
strings -a "$R182/usr/bin/las-sc" | grep -oE 'socket#(af|sock|ipproto)/[a-z0-9-]+' | sort -u

# 6. s11n round-trip call sites (§6).
strings -a "$R182/usr/bin/las-sc" | grep -E 's11n#|cal/vxtune-db\.scm:(144|147|154):'

# 7. The parser substrate is unlinked (§9): zero hits in every program.
for e in comparse abnf lexgen silex numbers regex trie iset; do
  echo -n "$e: "; for b in "$R182"/usr/bin/{las-sc,lassvc,vxmon,vxtune,vxtest,vxreport,vxping,osclog,oscterm,las_clock_demo,eec}; do
    grep -aq "$e#" "$b" && echo -n "$(basename $b) "; done; echo; done   # all blank
```

---

## 12. What is still unknown

* **The on-wire shape of the s11n tuning records.** §6 fixes the egg and the call
  sites; the byte layout is `calibration.md` §5.2's subject and was not
  re-derived here. `[UNKNOWN in this report, by scope]`
* **Whether `las-frontend` invokes the CHICKEN evaluator at runtime** (§10), and
  if so for what. `[UNKNOWN]`
* **The exact JSON schema `vxtune --log-format json` emits.** The converter and
  its `medea#write-json` call are confirmed; the field set of the output log was
  not reconstructed (it mirrors the s-exp log, which is a separate target).
  `[UNKNOWN]`
* **Whether any egg is loaded dynamically at runtime.** On a device with no
  compiler the `.so` eggs could still in principle be `load`-ed by a program that
  calls `(load …)`, but no evidence of that path was sought here. `[UNKNOWN]`

---

## 13. Conflicts with existing docs

No contradictions found. Additive notes:

* **`docs/firmware/lassvc.md` line 47** lists `lassvc`'s linked eggs as `csosc`,
  `socket`, `udp6`, `gochan`, `ncurses`, `s11n`, `fmt`. That is correct but
  **incomplete**: `lassvc` also links `curses-readline`, `simple-exceptions`,
  `args`, `srfi-37`, **`srfi-60`** (the only program that uses it — `bit-field`,
  `bitwise-and`, `bitwise-ior` `[READ]`), `vector-lib`, `bitstring`, and the
  macro eggs `matchable`/`defstruct`/`srfi-133`/`list-utils` (§3.1). No edit made
  to that file; recorded here as an extension, not a correction.
* **`docs/firmware/calibration.md` §5.2** attributes the `/var/tuning.vxtune`
  files to CHICKEN `s11n`. §6 above independently confirms the egg identity
  (3-binding surface), that the default serialization mode is used, and the exact
  `serialize`/`deserialize` call sites. Consistent; no conflict.
* **`docs/firmware/gap-eec-expression-compiler.md` §9.2** notes `las-sc`
  `(require)`s `eec` but calls nothing from it. §3.1 reproduces that independently
  (`eec` is Tier-2 ○ in `las-sc` only). Consistent.
* No prior report mentions `medea`, `comparse`, `abnf`, `lexgen`, `silex`,
  `matchable`, `datatype`, `binary-parse`, `s11n` (as an egg, vs the encoding),
  `typeclass`, `iset`, `numbers`, `suffix-tree`, `lazy-seq`, `ncurses`, or
  `curses-readline` as capability-bearing eggs. This report is their first
  inventory.
