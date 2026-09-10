# `/usr/bin/eec` — the expression-engine compiler and its embedded instruction set

**Scope.** Everything recoverable from `/usr/bin/eec` in the decrypted v1.8.2
rootfs, plus the `eec` egg in the CHICKEN registry, plus the v1.5.0 copy for
comparison. This is the compiler that turns expression source text into VX
voice-card bytecode. It carries its own instruction reference as embedded help
strings. **No prior report in this project mentions it**: `eec` occurs zero times
across `docs/**`.

**Evidence grading.** `[READ]` = read directly out of a file, offset given.
`[INFERRED]` = reasoning from stated evidence. `[UNKNOWN]` = not established.
Nothing here is `[TESTED]`. **This pass touched no instrument.**

**Paths.** `R182` = `captures/firmware-1.8.2/rootfs-1.8.2`,
`R150` = `captures/rootfs-1.5.0`. All offsets are decimal file offsets unless
marked as vaddr. `vaddr = file_offset + 0x10000` for this binary.

> Reproduces short functional help strings from a Moog binary, as the instruction
> set *is* the deliverable. Treated the same as other binary-derived tables in
> `docs/arch/`. See `docs/INTERNAL-DO-NOT-DISTRIBUTE.md`.

---

## 0. Headline

**`eec` compiles expression text to a vector of signed 32-bit words in Q24
fixed point and ships it to the voice card as an OSC blob over UDP.** Its default
target is `vc:7770` — i.e. `203.0.113.2:7770`, the voice bus. It carries a
47-entry human-written instruction reference. That reference contains **five
defects**, including one wrong mnemonic (`slewn` documented as `slewp`), and it
**omits one operation entirely** (`vcurve`). The binary is **functionally
identical in v1.5.0 and v1.8.2** — the op doc table and symbol table are
byte-for-byte equal across the two releases.

Separately: this settles `docs/arch/expression-language.md` §10.2's open
question about what `rcl` means. See §7.1.

---

## 1. Identity

| property | value |
|---|---|
| path | `R182/usr/bin/eec` |
| size | 140,396 bytes `[READ]` |
| md5 (1.8.2) | `4a872a2dc56b907695e56906b253eb29` `[READ]` |
| md5 (1.5.0) | `e1820765f32a1be4809b476e099474b9` `[READ]` |
| type | ELF 32-bit LSB executable, ARM EABI5, dynamically linked, stripped `[READ]` |
| interpreter | `/lib/ld-linux-armhf.so.3` `[READ]` |
| needed | `libchicken.so.8`, `libm.so.6`, `libdl.so.2`, `libc.so.6` `[READ]` |
| ARM attribute | `Cortex-A9` `[READ]` — matches the i.MX6 |
| sections | `.text` vaddr `0x11184` size `0x19e54`; `.rodata` vaddr `0x2afe0` size `0x4db2` `[READ, llvm-objdump --section-headers]` |
| source files | `eec.scm`, `eec-cli.scm`, **`ee-ops.scm`** `[READ, CHICKEN trace strings]` |

`ee-ops.scm` is a **third source file** not named in any prior note; it holds the
operation table. `[READ, e.g. offset 121442 "ee-ops.scm:5: ##sys#require"]`

Build provenance, from `R182/usr/lib/chicken/8/eec.setup-info` `[READ, verbatim]`:

```
((files "/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/target/usr/bin/eec")
 (version "unknown")
 (egg-name "eec"))
```

Every egg in the registry carries this same `las-ci-builds/glrt-t3_` buildroot
path, so it is **not** an authorship discriminator. `[READ]` The discriminator is
the payload path: 13 eggs install into `target/usr/bin/` rather than
`usr/lib/chicken/8/` — `chicken-dump`, `chicken-wrap`, **`eec`**, `las-sc`,
`las_clock_demo`, `lassvc`, `osclog`, `oscterm`, `vxmon`, `vxping`, `vxreport`,
`vxtest`, `vxtune`. `[READ]`

---

## 2. Command-line interface

Reconstructed from the CHICKEN literal frame at offsets 110,540–111,300 and the
`eec-cli.scm` trace strings. `[READ]`

Usage string: `" [ opts ] [ exprs ]"` at 110,576. `[READ]` The program name is
prepended at runtime (`eec-cli.scm:30: program-name`). Expressions are taken from
the **positional operands**, joined with `string-join` and handed to `ee-read`
(`eec-cli.scm:48`). `[READ]`

Five options, each built by `args#make-args:option` at `eec-cli.scm:26–30`
`[READ]`:

| short | long | argument | help string (verbatim) | offset |
|---|---|---|---|---|
| — | `--help` | optional | `Display usage text` | 110,719 |
| `-c` | `--connect` | required | `Send OSC to UDP at host:port` | 110,848 |
| — | `--osc` | required | `Send compiled bytecode to OSC address` | 110,945 |
| `-A` | `--asm-out` | required | `Write assembly to standard out` | 111,023 |
| `-e` | `--expr` | required | `Take expression input from file` | 111,123 |

`--osc` has **no short form**; `--help` has no short form. `[READ — the literal
pairs for `connect`, `asm-out` and `expr` each carry a character literal
(`FE FF 0A` + codepoint `0x63`/`0x41`/`0x65`), those for `help` and `osc` do
not.]`

**Defaults.** Two bare string literals sit in the CLI literal run: `"vc"` at
110,609 and `"7770"` at 110,619. `[READ]` `eec-cli.scm:74` calls
`parse-colon-sep`. `[READ]` **The default `--connect` target is therefore
`vc:7770`.** `[INFERRED — from the two literals plus the host:port help text and
the colon-splitter; no code path was traced to prove the binding.]`

`/etc/hosts` in the same rootfs: `203.0.113.2 vc`. `[READ, R182/etc/hosts line 2]`
That is the voice bus, matching `docs/firmware/network.md` §2.4 and
`docs/MOOG-ONE-INTERNALS.md`.

> **`vc:7770` is `203.0.113.2:7770`.** Per rule 1 this report proposes no traffic
> to it. See §10.

### 2.1 `-e/--expr` takes a *symbol* file, not expression text

The help says "Take expression input from file", but the two errors reachable
from that path are `no symbols in expr file` (110,649) and `malformed expr file`
(110,678), and the next thing that happens is `mk-ee-env` at `eec-cli.scm:56`.
`[READ]`

The string `VX_EE` does **not** appear anywhere in `eec`. `[READ, 0 occurrences]`
But `symbols`, `parms` and `array` do. `[READ, 120,597 / 121,341 / 121,303]`

`[INFERRED]` `-e` takes a file in **`vx_ee.scm` format** — eec reads the form,
ignores the head symbol, and `alist-ref`s `symbols` out of its tail, which turns
`(VX_EE (symbols …))` into the symbol table. `(array N)` declarations are
understood. This is the same file `las-sc` is given as `--expr-syms`:

```
/usr/bin/las-sc -t vc -f localhost:7775 … --expr-syms=/usr/share/vx_ee.scm …
```
`[READ, R182/etc/init.d/S42sc line 4]`

`R182/usr/share/vx_ee.scm` is **byte-identical** to `captures/arch-harvest/vx_ee.scm`
(md5 `5e5c02c1e5a95c79e4e7c52843eb4408`). `[READ]`

### 2.2 Output path

From the `eec-cli.scm` trace strings, in line order `[READ]`:

```
:69  display, ee-compile-asm      → --asm-out
:70  newline
:73  ##sys#call-with-values
:74  parse-colon-sep              → host:port
:75  ee-compile-bytecode
:77  udp6#udp-open-socket
:78  list->s32vector, s32vector->blob, csosc#osc
:79  udp6#udp-connect!
:80  fmt#fmt                      → "sending " N " words to " ADDR
:81  csosc#osc-encode, udp6#udp-send
```

**The bytecode is a list of integers → `s32vector` → blob → one OSC message.**
`[READ]` The progress string is `"sending "` (110,619) + count + `" words to "`
(110,633) + address. `[READ]` "Words" are therefore **signed 32-bit**. `[READ,
from `list->s32vector`]`

---

## 3. The numeric format is Q24 — proven from code

`number->q24` is a symbol in the table at 121,417. `[READ]`

Disassembling the function that carries the `eec.scm:231: round` trace marker
`[READ, llvm-objdump -d --triple=armv7-none-linux-gnueabihf]`:

```
21ba0: e1a02006   mov  r2, r6            @ r6 = the input value
21ba4: e59f104c   ldr  r1, [pc, #0x4c]   @ 0x21bf8
21ba8: e1a0500d   mov  r5, sp
...
21bb8: ebffbce4   bl   0x10f50 <C_2_times@plt>
21bbc: e1a06000   mov  r6, r0
21bc0: e59f0034   ldr  r0, [pc, #0x34]   @ 0x21bfc
21bc4: ebffbcf6   bl   0x10fa4 <C_trace@plt>
...
21bf8: 02000001                          @ literal
21bfc: 0002e18a                          @ -> "eec.scm:231: round"
```

Literal `0x02000001` = 33,554,433 = CHICKEN's fixnum encoding `(n<<1)|1` of
**16,777,216 = 2^24**. It reaches `C_2_times` in `r1`, with the incoming value in
`r2`; the product returns in `r0` and is kept in `r6`. `[READ]` The very next call is `C_trace` with the pointer to
`"eec.scm:231: round"` (vaddr `0x2e18a`, file offset 123,274). `[READ]`

**`number->q24` computes `round(x × 2^24)`.** `[READ — constant, multiply and
round all present in one basic block]` Constants in the emitted bytecode are
therefore **signed Q24 fixed point**, giving a representable range of about
±128 with a resolution of 2^-24.

This **agrees with and extends** what the project already had:
`docs/arch/xmos-deep.md` §-"Everything numeric on this bus is Q24 fixed point"
and `docs/firmware/calibration.md:947-948`. `las-sc` itself carries 37 `q24`
references (`inexact->q24`, `q24->inexact`, `*q24` in `las/las-math.scm`,
`las/las-oscl.scm`, `mon/vxmon-lib.scm`). `[READ]` The expression bytecode uses
the **same** word format as the rest of the voice bus.

---

## 4. The instruction reference, verbatim and in file order

47 operation entries, in the order their doc strings appear in `.rodata`
(116,985 → 120,305), with two interleaved error strings and seven interleaved
flonums removed. All strings `[READ]`, offsets exact.

The uniform shape is `<operands> <mnemonic> : <description>`.

| # | offset | operands | mnemonic | description (verbatim) |
|---|---|---|---|---|
| 0 | 116985 | — | `nop` | does nothing |
| 1 | 117009 | — | `rts` | end of expression |
| 2 | 117038 | `c` | `ldc` | load constant onto stack |
| 3 | 117076 | `r` | `rcl` | load contents of variable r onto stack |
| 4 | 117196 | `r` | `sto` | store top of stack in variable or result r |
| 5 | 117366 | `x y` | `add` | x + y |
| 6 | 117387 | `x y` | `sub` | x - y |
| 7 | 117408 | `x y` | `mul` | x * y |
| 8 | 117436 | `x y` | `div` | x / y |
| 9 | 117457 | `x` | `abs` | Absolute value of x |
| 10 | 117508 | `x` | `sqr` | x^2 |
| 11 | 117537 | `x` | `cube` | x^3 |
| 12 | 117555 | `x y` | `gt` | 1 if x > y, else 0 |
| 13 | 117588 | `x y` | `le` | 1 if x <= y, else 0 |
| 14 | 117622 | `x y` | `lt` | 1 if x < y, else 0 |
| 15 | 117655 | `x y` | `ge` | 1 if x >= y, else 0 |
| 16 | 117689 | `x y` | `and` | Boolean and: y if both x and y non-zero, else 0 |
| 17 | 117752 | `x y` | `or` | Boolean inclusive-or: x if either x or y non-zero, else 0 |
| 18 | 117824 | `x y` | `xor` | Boolean exclusive-or: if x non-zero and y 0, x; if y non-zero and x 0, y; else 0 |
| 19 | 117920 | `x` | `not` | Boolean invert: if x is 0, 1, else 0 |
| 20 | 117970 | `x y s` | `sel` | Conditional: if s is 0, then x, else y |
| 21 | 118205 | `x y` | `min` | Lesser of x and y |
| 22 | 118238 | `x y` | `max` | Greater of x and y |
| 23 | 118272 | — | `ini` | clear argument stack |
| 24 | 118304 | `x l h` | `sat` | Limit x to the range l..h inclusive |
| 25 | 118357 | `r` | `ast` | add top of stack to register or result r |
| 26 | 118411 | `x g v` | `sh` | When g is zero, copy x to variable v.  value of v is always the result. |
| 27 | 118499 | `x l h` | `inside` | If l <= x <= h, 1, else 0 |
| 28 | 118545 | `x r v` | `slew` | Limit the rate of change of x.  Previous x is stored in variable v.  If x differs from v by more than r, add r to v, adjusting for direction; otherwise set v to x.  Result is v. |
| 29 | 118741 | `x r v` | `slewp` | Limit the rate of change of x only in the positive direction.  If x is greater than v, limit its change to r; otherwise pass through. |
| 30 | 118894 | `x r v` | **`slewp`** *(sic — see §5.1)* | Limit the rate of change of x only in the negative direction.  If x is less than v, limit its change to r; otherwise pass through. |
| 31 | 119044 | `x a v` | `spf` | Single-pole filter on x, with coefficient a.  Previous y is stored in variable v. |
| 32 | 119143 | *(none)* | *(none)* | `Modulo/wrap` — see §5.3 |
| 33 | 119160 | `x` | `exp10` | 10^x |
| 34 | 119180 | `x` | `exp2` | 2^x |
| 35 | 119198 | `x` | `log` | natural logarithm |
| 36 | 119229 | `x` | `expe` | natural antilogarithm |
| 37 | 119265 | `x` | `db` | convert decibels to ratio |
| 38 | 119303 | `t n a r e s0 s1` | `clap` | Clap envelope.  t triggers when > 0.  n is number of claps.  a is the attack of each clap.  d is the release time of each clap.  d is multiplied by e on each cycle, so the clap can speed up or slow down.  s0 and s1 are state variables. |
| 39 | 119567 | `t a r` | `ar` | AR envelope.  t triggers when > 0.  a is attack time.  r is release time. |
| 40 | 119657 | `t a d s r` | `adsr` | ADSR envelope.  t triggers when > 0.  a is attack time.  d is decay time.  s is sustain level.  r is release time. |
| 41 | 119794 | `x x0 x1 y0 y1` | *(omitted — `lerp`)* | Interpolate x from range (x0, x1) to range (y0, y1). |
| 42 | 119868 | `x y0 y1` | *(omitted — `lerp1`)* | Interpolate x from range (0, 1) to range (y0, y1). |
| 43 | 119934 | `t n v` | `clkdiv` | For every n transitions of t from zero to non-zero, toggle n between 0 and 1.  v is state variable. |
| 44 | 120054 | `x n` | `q` | Quantise x into n steps from 0..1 |
| 45 | 120101 | `t` | `tta` | Calculate single-pole coefficient from a time in seconds.  (Sample rate is an argument to the virtual machine.) |
| 46 | 120226 | `x y acc` | `macsats` | Multiply x and y and add to acc, then saturate to +/-1. |

Plus **`vcurve`**, which has a symbol but no doc string — §5.4.

### 4.1 Sample rate is a VM argument, not a constant

Entry 45 states it outright: *"(Sample rate is an argument to the virtual
machine.)"* `[READ, 120,101]` The VM's time base is supplied by the host, so
`tta` and every time-shaped op (`ar`, `adsr`, `clap`, `slew*`, `spf`) are
sample-rate-parameterised rather than hard-coded. `docs/arch/expression-language.md`
§14 item 5 lists the evaluation rate as unknown; this does not give the value,
but it does establish that the value is **passed in**, so it is a VM
initialisation parameter and not a compile-time constant. `[READ + INFERRED]`

---

## 5. Five defects in Moog's own reference

These matter: the table is the authoritative instruction reference, and anyone
writing a compiler from it inherits the errors.

### 5.1 Entry 30 has the wrong mnemonic — it is `slewn`, not `slewp`

Entries 29 and 30 both read `slewp`. `[READ, 118,741 and 118,894]` But their
descriptions are the positive and negative variants, and the symbol table
contains **`slewn`** at offset 120,753, sitting immediately after `slewp`
(120,747). `[READ]`

`[INFERRED, strongly]` The negative-direction operation is **`slewn`**. Entry 30's
doc string is a copy-paste that missed the mnemonic. Writing `slewp` twice would
make the second unreachable.

### 5.2 Entry 38 (`clap`) describes an operand it does not take

The operand list is `t n a r e s0 s1`. The description explains `t`, `n`, `a`,
`e`, `s0`, `s1` — and then twice discusses **`d`**, which is not in the list,
while never explaining **`r`**, which is. `[READ, 119,303]`

`[INFERRED]` `d` in the prose means `r`; the sentences were copied from the
`adsr` entry (40), where `d` genuinely is the decay operand.

### 5.3 Entry 32 has no mnemonic and no operands

The whole doc string is `Modulo/wrap` — no `<operands> <mnemonic> :` prefix.
`[READ, 119,143]` The symbol table has **`mod`** at 120,767, positioned between
`spf` and `exp10` — exactly where entry 32 sits. `[READ]`

`[INFERRED]` Entry 32 is `mod`, and its doc is an unfinished placeholder. Its
operand count and its wrap semantics are **`[UNKNOWN]`**.

### 5.4 `vcurve` is undocumented

`vcurve` is in the symbol table at 120,822, between `clkdiv` (120,815) and `q`
(120,829). `[READ]` No doc string anywhere in the binary contains it.
`[READ, 1 occurrence in the whole file]`

`[INFERRED]` There is a 48th operation, `vcurve`, positioned between `clkdiv`
and `q`, with no help entry. Name suggests a velocity curve. Operands and
semantics **`[UNKNOWN]`**.

### 5.5 Entries 41 and 42 omit their mnemonics

Both start straight at the operand list. `[READ]` The symbol table supplies
`lerp` (120,804) and `lerp1` (120,809), in that order and in the right position.
`[READ]` `[INFERRED]` Entry 41 is `lerp`, entry 42 is `lerp1`.

Note the consequence: because these two omit the mnemonic, **the mnemonic cannot
be being parsed out of the doc string at runtime** — it must be stored
separately. The symbol `sym` exists at 121,399 alongside `argct` (121,393),
`doc` (120,897), `gen-asm` (121,403) and `gen-bytecode` (121,429), which is
consistent with a per-op record carrying all of them. `[READ + INFERRED]`

---

## 6. Operand-supply signatures — how one mnemonic becomes several encodings

`eec.scm:218` and `eec.scm:237` both call **`calc-signature`**. `[READ]`

The symbol table contains eight three-letter codes, interleaved through the op
names in positions that follow the doc order `[READ, offsets given]`:

```
sss 120683   css 120687   scs 120691   ccs 120695
ssc 120715   ssr 120727   scc 120731   scr 120759
```

`[INFERRED]` These are **operand-supply signatures** over three slots, with the
alphabet **`s` = from the argument stack, `c` = an immediate constant, `r` = a
register/variable name**. Evidence: the letters are exactly `s`/`c`/`r`; `ldc`
takes a constant `c`, `rcl`/`sto`/`ast` take a register `r`, and everything else
consumes stack; `calc-signature` is called immediately before the code that
selects a generator. The observed set constrains slots 1 and 2 to `{s,c}` and
slot 3 to `{s,c,r}`; `csc`, `ccc`, `csr` and `ccr` do not appear. **Whether the
signature is encoded into the opcode word or selects among distinct opcodes is
`[UNKNOWN]`.**

The `.rodata` symbol run also contains, at exactly the positions where
`sub`/`div` and `gt`/`le`/`lt`/`ge` sit in the doc order, the tokens
`-` (120638), `/` (120640), `>` (120661), `<=` (120663), `<` (120666),
`>=` (120668). `[READ]` `[INFERRED]` These are **alternate mnemonics** accepted
by the parser for those operations.

Two tokens in that run are **`[UNKNOWN]`**: `qbe` (120,649) and `***` (120,653),
which fall where `cube` would sit. No reading of them has been established. They
are recorded here verbatim rather than guessed at.

Twelve doc-table mnemonics have **no** standalone entry in that run — `rcl`,
`add`, `sub`, `mul`, `div`, `cube`, `le`, `lt`, `ge`, `or`, `sh`, `ar`.
`[READ, 0 NUL-delimited occurrences each]` `[INFERRED]` This is not evidence of
absence: CHICKEN interns symbols by `(pointer, length)` and can point into an
existing string, and every one of those names occurs inside its own doc string.

---

## 7. Module API and the compilation pipeline

`R182/usr/lib/chicken/8/eec.import.so` gives the module's complete export list
`[READ, verbatim from the .dynstr/export region]`:

```
eec#mk-ee-env            eec#ee-read              eec#ee-parse-postfix
eec#ee-gen-insns         eec#ee-compile-bytecode  eec#ee-compile-asm
eec#ee-ops
```

Seven exports. Imports declared: `scheme`, `chicken`, `fmt`, `srfi-1`, `srfi-4`,
`srfi-13`, `simple-exceptions`, `data-structures`, `srfi-69`. `[READ]`
`srfi-4` is the homogeneous-vector egg — the `s32vector` path of §2.2.

Pipeline, from the export names and the `eec-cli.scm` call order `[INFERRED]`:

```
text --ee-read--> forms --ee-parse-postfix--> tree --ee-gen-insns--> insns
                                                   |                   |
                                     ee-compile-asm |                   | ee-compile-bytecode
                                                    v                   v
                                              text on stdout      s32 word list
```

### 7.1 This settles the `rcl` question in `expression-language.md` §10.2

That document records `rcl` as **unresolved** and offers two readings, favouring
"`c<n>` pushes a value and `rcl` uses it as an index into another file".

The compiler's own reference says `[READ, 117,076]`:

```
r rcl : load contents of variable r onto stack
```

and, for its counterpart `[READ, 117,196]`:

```
r sto : store top of stack in variable or result r
```

`[INFERRED, strongly]` **`rcl` is a register-direct load: its single operand is
the *name* of a variable, not a value on the stack.** So `c64 rcl` means "load
the contents of register `c64`" — `c64` is the operand, not something pushed
first. This is closest to the document's reading 2 but corrects its mechanism:
there is no indexing through a second file, and no second register file is
involved.

Corroborating: the error string **`illegal register argument`** (117,128) sits in
the literal frame immediately after the `rcl` doc and immediately before the
`sto` doc `[READ]` — i.e. in the code that validates that operand. And
`sto requires 2 arguments` (117,159) shows `sto` counts the stack value *and* the
register as two arguments, while its doc lists only `r`. `[READ]`

### 7.2 The environment record

`ee-env` accessors, in table order `[READ, 120,901–121,285]`:

```
make-ee-env  ee-env?
ee-env-opspec  ee-env-oplist  ee-env-optable  ee-env-syms
ee-env-rovar-idx   ee-env-parms-idx   ee-env-rwvar-idx
ee-env-rovar-tbl   ee-env-parms-tbl   ee-env-rwvar-tbl
```
(each also with a `-set!` mutator)

`[INFERRED]` Three symbol classes with separate index lists and hash tables:
**rovar** = read-only variables (`args`), **parms** = parameters (`c0…c31`),
**rwvar** = read-write variables (`vars`). Results are handled with the
read-write side — `sto`'s doc says "variable **or result**". `mk-ee-env` takes
keyword arguments; `prefix` (120,336), `test` (120,320) and `hash` (120,326) sit
together just before the op names and `##sys#get-keyword` is called at
`eec.scm:94`. `[READ + INFERRED]` The token `p:` (120,336) and `p:r0` (120,627)
indicate a `p:` prefix form for parameter-qualified names. `[READ]`

The default/test environment is a literal at 116,850–116,980, decoding to
`(args a0 a1)`, `(vars v0 v1)`, `(results r0 r1)`. `[READ]` It is referenced by
`ee-test-symbols` (120,589). `[READ]` Seven flonums interleaved through the op
doc strings — `3.5`, `1.2`, `2.3`, `0.5`, `0.25`, `0.0625`, `0.015625`, `0.1`,
`0.2`, `0.8` `[READ, offsets 117,189–118,147]` — are `[INFERRED]` per-op test
values, consistent with a `test:` field.

### 7.3 Constant folding

`ee-ops.scm` carries simplifiers `[READ, trace strings]`:

```
smpl-1-rcl  @ lines 228 238 245 326
smpl-2-rcl  @ lines 206 212 218 223 258 268 278 286 294 306 316 344 356
smpl-3-rcl  @ lines 336 377
```

plus `simplifier-add`, `simplifier-mul`, `simplifier-sub`, `simplifier-div`
(120,529–120,588) and `sub-rcl` (120,521). `[READ]` `eec.scm:186` calls
`simplifier`. `[READ]` `[INFERRED]` The compiler constant-folds and folds a
`rcl` into the following operation where the operand allows it — which is what
the `r` slot in the `ssr`/`scr` signatures is for.

Error strings for arity `[READ, 116,716 / 116,751 / 116,787]`:
`operation requires 1 argument`, `… 2 arguments`, `… 3 arguments` — matching the
three simplifier arities. Generic form at 120,344–120,395:
`" requires " N " arguments, only " M " available"`. Others: `division by zero`
(116,823), `unknown symbol: ` (120,399), `operation not available: ` (120,434),
`unknown operation ` (120,465). `[READ]`

---

## 8. v1.5.0 vs v1.8.2 — the instruction set did not change

The two binaries are the same size (140,396) with different md5s. `[READ]`
Byte diff: 5,445 differing bytes in 872 runs. Classified by region `[READ]`:

| region | file offsets | differing bytes |
|---|---|---|
| `.text` | 4,484–110,552 | **4** |
| CLI option literals | 110,540–111,300 | **0** |
| CHICKEN procedure-name table (`f_NNNN:eec_2dcli_2escm`) | 111,300–116,850 | 2,597 |
| **operation doc table** | 116,850–120,312 | **0** |
| **symbol table** | 120,312–121,460 | **0** |
| `eec.scm`/`ee-ops.scm` trace strings | 121,460–130,450 | 1,844 |
| `.data` pointer tables | 131,576+ | 1,000 |

The four `.text` differences are two swapped 2-byte literal-pool offsets
(`0x130c`↔`0x12f0` at 33,584 and 37,012). `[READ]`

The symbol run is **character-for-character identical** in both, at the **same
offset** (120,589). `[READ, extracted and compared]`

`[INFERRED, strongly]` **`eec` is functionally identical in v1.5.0 and v1.8.2.**
The delta is a recompile: internal lambda numbering and pointer tables moved,
nothing semantic. The VX expression instruction set was unchanged across those
releases.

---

## 9. Two loose ends worth recording

### 9.1 `eec.so` in the registry is an older, reduced build

`R182/usr/lib/chicken/8/eec.so` (91,920 bytes) is the loadable module form.
Its `eec.scm` trace map is the same version as the binary's — every line number
matches (57, 94, 102, 106, 107, 112–131, 136–156, 165–186, 194–206, 215–255,
269–299, 308, 317, 318); the only differences are gensym numbering (a uniform
offset of 190), `fmt#fmt` vs `fmt` qualification, and four procedures inlined in
one build but not the other. `[READ, diffed]`

But its **operation table stops at `max`**: 23 doc entries against the binary's
46 `' : '`-form entries (47 ops in total, `mod` having no separator), ending at
entry 22. `[READ, grep -c " : "]` Raw byte counts in `eec.so`
`[READ]`:

```
adsr 0   clap 0   spf 0   slew 0   slewn 0   macsats 0   vcurve 0
clkdiv 0  tta 0   exp10 0   number->q24 0
gen-bytecode 1   gen-asm 1   calc-signature 3   cube 1
```

`[INFERRED]` `eec.so` was built from an **older `ee-ops.scm`** that ended around
line ~390, before the envelope / filter / transcendental / utility half was
appended, and before `number->q24` existed. Both builds share `ee-ops.scm` lines
5–377 unchanged, which is what an append-only op table looks like.
**`/usr/bin/eec` is the authority; `eec.so` is not.**

### 9.2 `las-sc` requires the `eec` module but calls nothing from it

`las-sc`'s literal frame contains `##sys#require` followed by
`eec  list-utils  csosc  udp6  simple-exceptions  defstruct`, and exactly two
require call sites (`sc/sc.scm:5`, `sc/sc.scm:6`). `[READ, offset 1,998,072]`

But `las-sc` contains **zero** occurrences of `eec#`, `mk-ee-env`, `ee-read`,
`ee-compile-bytecode`, `ee-compile-asm`, `ee-parse-postfix`, `ee-gen-insns` or
`ee-env`, and zero of `ee-ops` or `calc-signature`. `[READ, byte counts]` So the
compiler is not statically linked into it either.

`[INFERRED]` `las-sc` pulls in the `eec` egg — which would load the reduced
`eec.so` of §9.1 — but never calls its exports. Most likely a vestigial `(use
eec)` in `sc.scm`. **Why it is required at all is `[UNKNOWN]`**, and whether
expression compilation ever happens inside `las-sc` is **`[UNKNOWN]`**. This
does not contradict the established finding that `las-sc` has no modmatrix code;
it is consistent with it.

---

## 10. Validation plan — READ-ONLY, for a human to run

Per rule 1 nothing here was executed and no instrument was touched. Per rule 2
**do not run `eec`, on the device or anywhere**; on the instrument Moog binaries
ignore their arguments. All of the following are host-side file reads.

```bash
R182="captures/firmware-1.8.2/rootfs-1.8.2"

# 1. Op doc table, in order, with offsets (reproduces §4).
strings -t d -n 4 "$R182/usr/bin/eec" | awk '$1>=116985 && $1<=120310'

# 2. Symbol run, confirming slewn / vcurve / mod / qbe / *** (§5, §6).
dd if="$R182/usr/bin/eec" bs=1 skip=120589 count=340 2>/dev/null | tr '\0' '\n'

# 3. Q24 constant next to the round trace marker (§3).
/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/llvm-objdump \
  -d --triple=armv7-none-linux-gnueabihf \
  --start-address=0x21b20 --stop-address=0x21c00 "$R182/usr/bin/eec"

# 4. CLI options and the vc / 7770 defaults (§2).
dd if="$R182/usr/bin/eec" bs=1 skip=110540 count=780 2>/dev/null | xxd
grep -n vc "$R182/etc/hosts"

# 5. Module exports (§7).
strings -n 3 "$R182/usr/lib/chicken/8/eec.import.so" | grep '^eec#'

# 6. 1.5.0 vs 1.8.2 equality of the op table and symbol table (§8).
cmp -i 116850 -n 4610 "captures/rootfs-1.5.0/usr/bin/eec" "$R182/usr/bin/eec" && echo IDENTICAL

# 7. eec.so truncation (§9.1).
strings -n 3 "$R182/usr/lib/chicken/8/eec.so" | grep -c ' : '   # expect 23
strings -n 3 "$R182/usr/bin/eec"              | grep -c ' : '   # expect 46
# 46, not 47: entry 32 ('Modulo/wrap', §5.3) carries no ' : ' separator.
# The op table still has 47 entries — count the rows in §4, not ' : ' matches.
```

**Not proposed, deliberately:** any packet to `203.0.113.2:7770`, any execution
of `eec`, and any read of the live instrument. The one open question that a live
read *could* settle — the numeric opcode values — is better attacked offline
against the XMOS image (below).

---

## 11. What is still unknown

1. **The numeric opcode values.** The mnemonic→number map is built by code in
   `eec_toplevel`, not stored as a literal — there are only 17 symbol literals in
   the whole binary and none of them is an op name. `[READ]` §4's ordering is the
   order the doc strings appear in `.rodata`, which is CHICKEN's literal-emission
   order and therefore source order in `ee-ops.scm`; **it is not proven to be the
   opcode numbering.** Do not treat the `#` column as an opcode.
2. **The instruction word layout** — field widths, and whether the operand
   signature (§6) is a field or selects distinct opcodes.
3. **`mod`'s operands and wrap semantics** (§5.3).
4. **`vcurve` entirely** (§5.4).
5. **`qbe` and `***`** (§6).
6. **The VM sample rate.** Established as a VM argument (§4.1); the value is not
   in this binary.
7. **Why `las-sc` requires `eec`** (§9.2).

Best next target for 1, 2 and 3: the XMOS voice image
`R182/usr/share/xmosfw/app_vx_10M_v2.2.1.bin`, which contains the VM's opcode
dispatch. `docs/arch/expression-language.md` §14 already records a
nibble-reversal transform for the obfuscated 2.1.x images; `S42sc` shows 2.2.1 is
the shipped pair. That is a separate gap and was not opened here.

## 12. Conflicts with existing docs

None found. Two corrections and one gap-fill, all additive:

* `docs/arch/expression-language.md` §10.2 records `rcl` as **unresolved** and
  favours an indexing reading. §7.1 above resolves it as a register-direct load
  and rules out the indexing mechanism. That section should be updated — this
  report does not edit it.
* `docs/arch/expression-language.md` §12 counts **31 functions** in the language
  vocabulary, derived from the preset corpus and the frontend. The compiler
  documents **47** operations plus `vcurve`. These are different layers (authored
  vocabulary vs VM instruction set) and are not in contradiction, but the
  relationship between the two lists is unmapped.
* Q24: §3 confirms, from `eec`'s own code, what `docs/arch/xmos-deep.md` and
  `docs/firmware/calibration.md` established from `las-sc` — the expression
  bytecode uses the same Q24 word format as the rest of the voice bus.
