# The 96 UGen plugins and the 37 sc3-plugins packages — a complete inventory

**Scope.** Everything recoverable from `usr/lib/SuperCollider/plugins` (96 ARM
`.so`, 6,163,548 bytes) and `usr/share/SuperCollider/Extensions/SC3plugins`
(807 files, 38 directories) in the decrypted v1.8.2 rootfs, cross-checked against
the v1.5.0 rootfs, against the 195-file `las-fx/SCClassLibrary` that the running
`sclang` actually compiles, against the 340-file stock `SCClassLibrary`, and
against the 104 compiled `.scsyndef` the effects engine loads at boot.

Prior work went one way only: `las-fx.md` §9.4 censused the **61 UGen classes used**
by the shipped synthdefs and `:709` asserted that "every one resolves inside
`/usr/lib/SuperCollider/plugins` (96 `.so`)" with six mappings spot-checked. This
report goes the other way — **what do all 96 binaries define?** — and answers it
exhaustively.

**Evidence grading.** `[READ]` = read directly out of a file, address or line
given. `[INFERRED]` = reasoning from stated evidence, evidence named. `[UNKNOWN]`
= not established. Nothing here is `[TESTED]`. **This pass touched no instrument.**
No Moog binary was executed; the ARM `.so` files were disassembled with
`llvm-objdump --triple=armv7-none-linux-gnueabihf` and parsed as ELF32 by a
purpose-written reader.

**Paths.** `R182` = `captures/firmware-1.8.2/rootfs-1.8.2`, `R150` =
`captures/rootfs-1.5.0`. Addresses are ELF virtual addresses unless marked as file
offsets.

---

## 0. Headline

**The 96 plugin binaries register 795 UGens. The class library the running
`sclang` compiles has a class for 360 of them — so 435 are compiled, resident and
correctly-linked ARM DSP inside the audio server that the instrument's own client
cannot name. The 104 shipped synthdefs use 61, leaving 734 registered UGens that
nothing shipping on this machine instantiates.** Among the 435 unnameable: the
complete Synthesis ToolKit physical-modelling set, JPverb and Greyhole, the mda
piano, the Ambisonic Toolkit, 55 machine-listening UGens, and — less expected —
the stock SuperCollider reverbs, the whole granular family and all 22 stock
chaotic generators. `[READ]` for the counts, from the tables below.

Eighty-two of the ninety-six `.so` contribute nothing to any shipped synthdef.
Seventy-three of the ninety-six have **zero** coverage in the live class library:
not one of their UGens can be written down in `sclang` as it is configured.

Four secondary results:

1. **`Index` *is* registered.** `gap-las-fx-coefficient-archive.md` §10.4 left this
   `[UNKNOWN]` and §16 asked for exactly the disassembly done here. `OscUGens.so`
   calls `fDefineUnit` three times in a row at `0x1551c`, `0x1556c`, `0x15594` with
   name pointers `0x15b3c`, `0x15b38`, `0x15b44` — `Index`, `FoldIndex`,
   `WrapIndex`, allocation size 68 each. The linker tail-merged `Index\0` into the
   last five bytes of `FoldIndex\0` at `0x15b38+4`, which is why a `strings` search
   could not see it. `[READ]` `APFTable` and `BPFTable` are therefore not broken.
2. **All 96 `.so` are byte-identical between v1.5.0 and v1.8.2**, as is the entire
   `Extensions` tree and the entire `las-fx/SCClassLibrary`. `[READ]` — `cmp` over
   all 96 pairs, `diff -rq` over the two trees.
3. **`OscUGens.so` registers an eighth buffer-fill routine, `cantorFill`, that
   appears nowhere else in the image** — no class method, no help file, no caller.
   `[READ]` The other seven (`sine1`, `sine2`, `sine3`, `cheby`, `normalize`,
   `wnormalize`, `copy`) are all reachable from `Buffer.sc`. `[READ]`
4. **No plugin binary carries any Moog attribution.** No `.comment` section
   survives in any of the 96, and no build path, vendor string or SCM tag appears
   in any of them — in contrast to `usr/bin/scsynth`, which does carry
   `/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/build/supercollider-Version-3.9.0/…`.
   `[READ]` Which of the 96 (if any) came from Moog's own `LAS_SC_UGENS`
   repository rather than upstream sc3-plugins is **`[UNKNOWN]`** and cannot be
   settled from this image.

---

## 1. Why nothing here is reachable, mechanically

Three facts, each read directly, compose into the gap.

**1.1 `scsynth` loads all 96 from a compiled-in path.** `usr/bin/scsynth` contains
the literal `/usr/lib/SuperCollider/plugins`, the fallback name `plugins`, the
override env var `SC_PLUGIN_PATH`, and the flag text
`-U <ugen-plugins-path>    a colon-separated list of paths`. `[READ]`
`SC_PLUGIN_PATH` is set nowhere in the rootfs — the single hit across the whole
filesystem is `usr/share/SuperCollider/README_LINUX.md`, a document. `[READ]`
`init_sc_1.scd` sets no `ugenPluginsPath` and passes no `-U`. `[READ]`
`usr/share/SuperCollider/Extensions` contains **zero** `.so`. `[READ]` (confirms
`las-fx.md:715`.) So the resident set is exactly these 96 files, and nothing else.

**1.2 The client compiles a different, smaller library.** `launch-sc-1:23` reads:

    DISPLAY=:0 SCSYNTH_IP=$scip SERVER_SEND_PORT=9999 SERVER_RECV_PORT=7775 sclang -a -l sclang_config.yaml init_sc_1.scd

`[READ]` and `usr/bin/sclang`'s own usage text at string index 1793 reads
`-a  Standalone mode (exclude SCClassLibrary and user and system Extensions folders
from search path)`. `[READ]` `sclang_config.yaml` is two lines:
`includePaths:` / `- SCClassLibrary`, with no `excludePaths`. `[READ]` Because
`launch-sc-1:6` does `cd /usr/share/las-fx/`, that include path resolves to
`las-fx/SCClassLibrary` — 195 `.sc`. `[READ]` (This is `las-fx.md` §3's finding,
independently re-read here.)

**1.3 The server resolves UGens by name string, not by anything the client knows.**
`usr/bin/scsynth` carries the error string `UGen '%s' not installed.` alongside
`d_recv`, `/d_recv`, `15RecvSynthDefCmd`, `18LoadSynthDefDirCmd` and
`Loading synthdefs from path: %s`. `[READ]`

**The consequence.** `[INFERRED — firmly]` from 1.1–1.3: a UGen with no `sclang`
class is *fully present and functional in the running audio server* — its ctor is
registered in scsynth's unit-def table under its name — but there is no way to
write it into a `SynthDef` from the instrument's own client. It is reachable only
by (a) a synthdef graph assembled without that client, or (b) adding a class file.
§10 works through the routes.

---

## 2. Method, and the argument that this inventory is complete

**2.1 How the names were recovered.** Every plugin exports exactly three symbols
that scsynth looks up — `api_version`, `server_type`, `load` — and is otherwise
fully stripped (`llvm-nm` reports "no symbols" for `.symtab`; there is no
`.comment` section in any of the 96). `[READ]` `load(InterfaceTable*)` is the only
entry point, and the SuperCollider `DefineSimpleUnit`/`DefineDtorUnit` macros
expand to an indirect call through the interface table with the UGen name as a
string literal in `.rodata`.

The recovery was a linear ARM simulator over the disassembly of `load` and every
function it calls or tail-calls, tracking only what is needed: PC-relative literal
loads (`ldr rN, [pc, #imm]` followed by `add rN, pc, rN`), register moves, the
interface-table pointer and the global it is stashed in, and indirect calls
`blx rN` where `rN` came from `[ift, #off]`. The offset identifies which table slot
was called:

| offset | interface-table member | count found across all 96 |
|---:|---|---:|
| `0x18` | `fDefineUnit` | 795 |
| `0x1c` | `fDefinePlugInCmd` | 1 |
| `0x20` | `fDefineUnitCmd` | 0 (see §6.3) |
| `0x24` | `fDefineBufGen` | 10 |

The `0x18`/`0x1c`/`0x24` identifications are `[INFERRED — firmly]`, not assumed
from a header: slot `0x24` in `OscUGens.so` is called with the strings `sine1`,
`sine2`, `sine3`, `cheby`, `normalize`, `wnormalize`, `copy` — which
`las-fx/SCClassLibrary/Control/Buffer.sc:461,509` sends as `/b_gen` command names
`[READ]` — and slot `0x1c` in `UIUGens.so` is called with `pluginCmdDemo`, whose
handler string `cmdDemoFunc` sits beside it in `.rodata` `[READ]`. Slot `0x18` is
the only remaining slot called with a UGen-shaped name and a `sizeof` immediate in
`r1`.

A worked example, `DiodeRingMod.so` `load` at `0xa50`: `[READ]`

    a68: ldr r0, [pc, #0x28]      ; literal 0x28
    a78: add r0, pc, r0           ; r0 = 0xa80+0x28 = 0xaa8 -> "DiodeRingMod"
    a64: mov r1, #104             ; sizeof(DiodeRingMod)
    a7c: ldr r4, [r12, #0x18]     ; ft->fDefineUnit
    a88: blx r4

**2.2 The completeness argument.** A UGen's registered name must exist as a
NUL-terminated identifier string somewhere in the binary. So the inventory was
checked from the other end: every NUL-delimited token in every `.rodata` section of
all 96 files that looks like a C identifier was extracted, and the registered set
subtracted. **379 tokens remain, and every one is accounted for** `[READ]`:

* STK internals and RTTI names in `StkInst.so` / `StkUGens.so` (`N3stk8ClarinetE`
  …, `ahh`, `mand7.raw`, `RIFF`, `AIFF`);
* the Betablocker virtual-machine opcode mnemonics in `BetablockerUGens.so`
  (`psh`, `pop`, `jmpz`, `rol`, `vox`, `org`, …);
* FAUST metadata keys and parameter names in `Greyhole.so` / `JPverb.so`
  (`author`, `license`, `GRAME`, `damping`, `delayTime`, `t60`, …);
* the ten buffer-fill names of §6.1;
* `LADSPA_PATH` and `ladspa_descriptor` in `LadspaUGen.so`;
* `pluginCmdDemo` / `cmdDemoFunc` in `UIUGens.so`;
* `createfile` / `closefile` in `FeatureSave.so` — unit commands, §6.3;
* `NaN`, `denormal`, `infinity`, `normal`, `zero`, `unknown` — `CheckBadValues`
  diagnostic words in `TestUGens.so`;
* C++ typeinfo fragments (`NSt6thread10_Impl_baseE`, `St19_Sp_make_shared_tag`);
* six two-letter tokens in `JoshUGens.so` / `MdaUGens.so` (`HB`, `RC`, `aD`, `pC`,
  `zC`, `zD`, `RF`) that are not identifiers in any class or help file;
* and **`EnvFollow` in `SLUGens.so`**, which *is* a real registration the simulator
  first missed — see 2.3.

**2.3 The one known simulator miss, found and fixed.** `SLUGens.so` registers
`EnvFollow` through a shared epilogue: at `0x9570`–`0x9580` it loads the name
pointer and `ft->fDefineUnit`, then branches (`b 0x96b8`) to a trampoline shared
with other registrations, which performs the `blx`. `[READ]` A linear scan walks
past the branch. It was caught by the `.rodata` sweep and added by hand; the count
of 795 includes it. **No other file shows an unexplained `.rodata` identifier**, so
`[INFERRED — firmly]` there are no further misses of this kind.

**2.4 Two names that are correct but not statically provable.** `Greyhole.so` and
`JPverb.so` are FAUST-generated. Their `load` functions are 11,220 and 11,032 bytes
of `std::string` and `std::map` work that build the UGen name at run time; each
contains exactly **one** `ldr rN, [rM, #0x18]` and the argument in `r0` is a stack
`std::string`, not a literal. `[READ]` The registered names are taken to be
`GreyholeRaw` and `JPverbRaw` `[INFERRED — firmly]` on four independent grounds:
those are the only UGen-shaped strings in either `.rodata`; each sits immediately
before that plugin's parameter-name block (`damping`, `delayTime`, … /
`damp`, `earlyDiff`, `t60`, …); `DEINDUGens/Greyhole.sc` and `JPverb.sc` declare
`GreyholeRaw : MultiOutUGen` and `JPverbRaw : MultiOutUGen`; and
`HelpSource/Classes/GreyholeRaw.schelp` and `JPverbRaw.schelp` exist. `[READ]`

**2.5 Independent corroboration of the whole set.** Of the 795 recovered names,
**773 are corroborated** by a class declaration in one of the three `.sc` trees or
by a shipped help file of the same name. `[READ]` The 22 with binary-only evidence
are listed in §5.4. This is a cross-check, not a filter: no name was accepted or
rejected on the strength of a class file.

**2.6 Independent re-derivation of the 61-class synthdef census.** The 104
`.scsyndef` in `usr/share/las-fx/synthdefs/` were parsed from scratch (format
version 2, `SCgf` magic, one def per file). The distinct UGen-class census is
**exactly the 61 names printed at `las-fx.md:701-707`**, with no additions and no
omissions. `[READ]` That report's §9.4 stands.

---

## 3. The plugin directory, file by file

96 files, 6,163,548 bytes total, all `ELF 32-bit LSB shared object, ARM, EABI5,
dynamically linked, stripped`, all built for `Cortex-A9`. `[READ]`
Every one exports `api_version` returning **3**; 94 export `server_type` returning
**0**; `Greyhole.so` and `JPverb.so` export no `server_type` at all. `[READ]`
Dependencies are uniform — `libstdc++.so.6`, `libm.so.6`, `libgcc_s.so.1`,
`libc.so.6` in all 96 — except `libpthread.so.0` in five, `libsndfile.so.1` in
`DiskIO_UGens.so` alone, and `libdl.so.2` in one. `[READ]`

In the table, **bold** marks a UGen for which a class exists in
`las-fx/SCClassLibrary` — i.e. one you can name from the running `sclang` today.
A dagger † marks one used by a shipped `.scsyndef`. Plain text is resident DSP with
no name on this instrument. "origin" is the sc3-plugins package whose sources
declare the plugin's classes, `core` for the stock SuperCollider plugin set, `?`
where neither applies.

| `.so` | bytes | n | origin | UGen names — **bold** = a class exists in `las-fx/SCClassLibrary`, † = used by a shipped synthdef |
|---|---:|---:|---|---|
| `AY_UGen.so` | 10,120 | 1 | AYUGens | `AY` |
| `AmbisonicUGens.so` | 11,324 | 4 | **?** | `DistanceB` `Dominate` `ProximityB` `Push` |
| `AntiAliasingOscillators.so` | 6,120 | 6 | AntiAliasingOscillators | `BlitB3` `BlitB3Saw` `BlitB3Square` `BlitB3Tri` `DPW3Tri` `DPW4Saw` |
| `AtkUGens.so` | 82,408 | 27 | ATK | `FoaAsymmetry` `FoaDirectO` `FoaDirectX` `FoaDirectY` `FoaDirectZ` `FoaDominateX` `FoaDominateY` `FoaDominateZ` `FoaFocusX` `FoaFocusY` `FoaFocusZ` `FoaNFC` `FoaPanB` `FoaPressX` `FoaPressY` `FoaPressZ` `FoaProximity` `FoaPsychoShelf` `FoaPushX` `FoaPushY` `FoaPushZ` `FoaRotate` `FoaTilt` `FoaTumble` `FoaZoomX` `FoaZoomY` `FoaZoomZ` |
| `AttackSlope.so` | 5,708 | 1 | SCMIRUGens | `AttackSlope` |
| `AuditoryModeling.so` | 5,936 | 3 | AuditoryModeling | `Gammatone` `HairCell` `Meddis` |
| `BBCut2UGens.so` | 29,380 | 1 | BBCut2UGens | `AnalyseEvents2` |
| `BatPVUgens.so` | 6,060 | 1 | BatUGens | `FrameCompare` |
| `BatUGens.so` | 9,796 | 6 | BatUGens | `Coyote` `MarkovSynth` `NeedleRect` `SkipNeedle` `TrigAvg` `WAmp` |
| `BeatStatistics.so` | 12,484 | 1 | SCMIRUGens | `BeatStatistics` |
| `BerlachUGens.so` | 37,224 | 19 | BerlachUGens | `BLBufRd` `Clipper4` `Clipper8` `DriveNoise` `LPF1` `LPF18` `LPFVS6` `OSFold4` `OSFold8` `OSTrunc4` `OSTrunc8` `OSWrap4` `OSWrap8` `PeakEQ2` `PeakEQ4` `SoftClipAmp4` `SoftClipAmp8` `SoftClipper4` `SoftClipper8` |
| `BetablockerUGens.so` | 13,884 | 2 | BetablockerUGens | `BBlockerBuf` `DetaBlockerBuf` |
| `BhobChaos.so` | 25,176 | 24 | BhobUGens | `Fhn2DC` `Fhn2DL` `Fhn2DN` `FhnTrig` `Gbman2DC` `Gbman2DL` `Gbman2DN` `GbmanTrig` `Henon2DC` `Henon2DL` `Henon2DN` `HenonTrig` `Latoocarfian2DC` `Latoocarfian2DL` `Latoocarfian2DN` `LatoocarfianTrig` `Lorenz2DC` `Lorenz2DL` `Lorenz2DN` `LorenzTrig` `Standard2DC` `Standard2DL` `Standard2DN` `StandardTrig` |
| `BhobFFT.so` | 15,216 | 10 | BhobUGens | `PV_CommonMag` `PV_CommonMul` `PV_Compander` `PV_Cutoff` `PV_MagGate` `PV_MagMinus` `PV_MagScale` `PV_Morph` `PV_SoftWipe` `PV_XFade` |
| `BhobFilt.so` | 45,780 | 13 | BhobUGens | **`DoubleNestedAllpassC`** **`DoubleNestedAllpassL`** **`DoubleNestedAllpassN`**† **`MoogLadder`** `MultiFilt` **`NLFiltC`** **`NLFiltL`** **`NLFiltN`** **`NestedAllpassC`** **`NestedAllpassL`** **`NestedAllpassN`** **`RLPFD`** **`Streson`** |
| `BhobGrain.so` | 12,952 | 2 | BhobUGens | **`TGrains2`** **`TGrains3`** |
| `BhobNoise.so` | 21,712 | 11 | BhobUGens | **`Dbrown2`** **`Dgauss`** **`GaussTrig`** **`Gendy4`** **`Gendy5`** **`LFBrownNoise0`** **`LFBrownNoise1`** **`LFBrownNoise2`** **`TBetaRand`** **`TBrownRand`** **`TGaussRand`** |
| `BinaryOpUGens.so` | 283,660 | 1 | core | **`BinaryOpUGen`**† |
| `BlackrainUGens.so` | 9,936 | 4 | BlackrainUGens | `AmplitudeMod` `BMoog` `IIRFilter` `SVF` |
| `ChaosUGens.so` | 29,364 | 22 | core | `CuspL` `CuspN` `FBSineC` `FBSineL` `FBSineN` `GbmanL` `GbmanN` `HenonC` `HenonL` `HenonN` `LatoocarfianC` `LatoocarfianL` `LatoocarfianN` `LinCongC` `LinCongL` `LinCongN` `LorenzL` `QuadC` `QuadL` `QuadN` `StandardL` `StandardN` |
| `Chromagram.so` | 8,276 | 1 | SCMIRUGens | `Chromagram` |
| `Concat.so` | 20,204 | 2 | ConcatUGens | `Concat` `Concat2` |
| `DWGBowed.so` | 48,912 | 5 | DWGUGens | `DWGBowed` `DWGBowedSimple` `DWGBowedStk` `DWGBowedTor` `DWGSoundBoard` |
| `DWGPlucked.so` | 36,920 | 3 | DWGUGens | `DWGPlucked` `DWGPlucked2` `DWGPluckedStiff` |
| `DelayUGens.so` | 174,776 | 55 | core | **`AllpassC`** **`AllpassL`** **`AllpassN`**† **`BlockSize`** **`BufAllpassC`** **`BufAllpassL`** **`BufAllpassN`** **`BufChannels`** **`BufCombC`** **`BufCombL`** **`BufCombN`** **`BufDelayC`** **`BufDelayL`** **`BufDelayN`** **`BufDur`** **`BufFrames`** **`BufRateScale`** **`BufRd`**† **`BufSampleRate`** **`BufSamples`** **`BufWr`**† **`ClearBuf`**† **`CombC`** **`CombL`** **`CombN`** **`ControlDur`**† **`ControlRate`** **`DelTapRd`** **`DelTapWr`** **`DelayC`**† **`DelayL`**† **`DelayN`**† **`GrainTap`** **`LocalBuf`**† **`MaxLocalBufs`**† **`NodeID`** **`NumAudioBuses`** **`NumBuffers`** **`NumControlBuses`** **`NumInputBuses`** **`NumOutputBuses`**† **`NumRunningSynths`** **`Pitch`** `PitchShift` **`PlayBuf`** `Pluck` **`RadiansPerSample`** **`RecordBuf`** **`SampleDur`** **`SampleRate`** **`ScopeOut`** **`ScopeOut2`** **`SetBuf`**† **`SubsampleOffset`** **`TGrains`** |
| `DemandUGens.so` | 38,128 | 25 | core | **`Dbrown`** **`Dbufrd`** **`Dbufwr`** **`Dconst`** **`Demand`** **`DemandEnvGen`** **`Dgeom`** **`Dibrown`** **`Diwhite`** **`Donce`** **`Dpoll`** **`Drand`** **`Dreset`** **`Dseq`** **`Dser`** **`Dseries`** **`Dshuf`** **`Dstutter`** **`Dswitch`** **`Dswitch1`** **`Duty`** **`Dwhite`** **`Dwrand`** **`Dxrand`** **`TDuty`** |
| `DiodeRingMod.so` | 4,296 | 1 | DEINDUGens | `DiodeRingMod` |
| `DiskIO_UGens.so` | 22,424 | 3 | core | **`DiskIn`** **`DiskOut`** **`VDiskIn`** |
| `DistortionUGens.so` | 6,744 | 5 | DistortionUGens | **`CrossoverDistortion`** **`Decimator`**† **`Disintegrator`** **`SineShaper`** **`SmoothDecimator`** |
| `DrumTrack.so` | 21,468 | 1 | BBCut2UGens | `DrumTrack` |
| `DynNoiseUGens.so` | 8,072 | 4 | core | **`LFDClipNoise`** **`LFDNoise0`** **`LFDNoise1`** **`LFDNoise3`** |
| `FFT_UGens.so` | 50,916 | 35 | core | **`FFT`** **`FFTTrigger`** **`IFFT`** **`PV_Add`** **`PV_BinScramble`** **`PV_BinShift`** **`PV_BinWipe`** **`PV_BrickWall`** **`PV_Conj`** **`PV_Copy`** **`PV_CopyPhase`** **`PV_Diffuser`** **`PV_Div`** **`PV_LocalMax`** **`PV_MagAbove`** **`PV_MagBelow`** **`PV_MagClip`** **`PV_MagDiv`** **`PV_MagFreeze`** **`PV_MagMul`** **`PV_MagNoise`** **`PV_MagShift`** **`PV_MagSmear`** **`PV_MagSquared`** **`PV_Max`** **`PV_Min`** **`PV_Mul`** **`PV_PhaseShift`** **`PV_PhaseShift270`** **`PV_PhaseShift90`** **`PV_RandComb`** **`PV_RandWipe`** **`PV_RectComb`** **`PV_RectComb2`** **`PartConv`** |
| `FM7.so` | 10,060 | 1 | SkUGens | `FM7` |
| `FeatureSave.so` | 4,156 | 1 | SCMIRUGens | `FeatureSave` |
| `FilterUGens.so` | 138,888 | 57 | core | **`APF`** **`Amplitude`**† **`BAllPass`**† **`BBandPass`**† **`BBandStop`** **`BHiPass`**† **`BHiShelf`** **`BLowPass`**† **`BLowShelf`** **`BPF`**† **`BPZ2`** **`BPeakEQ`** **`BRF`** **`BRZ2`** **`Compander`**† **`Decay`** **`Decay2`** **`Delay1`** **`Delay2`** **`DetectSilence`**† **`FOS`** `Flip` **`Formlet`** `FreqShift` **`HPF`**† **`HPZ1`** **`HPZ2`** `Hilbert` **`Integrator`** **`LPF`**† **`LPZ1`** **`LPZ2`** **`Lag`**† **`Lag2`** **`Lag2UD`** **`Lag3`**† **`Lag3UD`** **`LagUD`** **`LeakDC`**† **`Limiter`** **`Median`** **`MidEQ`** `MoogFF` **`Normalizer`** **`OnePole`**† **`OneZero`** **`RHPF`**† **`RLPF`**† **`Ramp`** **`Resonz`** **`Ringz`** **`SOS`**† **`Slew`** **`Slope`** **`TwoPole`** **`TwoZero`** **`VarLag`** |
| `GendynUGens.so` | 10,260 | 3 | core | `Gendy1` `Gendy2` `Gendy3` |
| `GlitchUGens.so` | 14,332 | 4 | GlitchUGens | `GlitchBPF` `GlitchBRF` `GlitchHPF` `GlitchRHPF` |
| `GrainUGens.so` | 69,640 | 5 | core | `GrainBuf` `GrainFM` `GrainIn` `GrainSin` `Warp1` |
| `Greyhole.so` | 80,000 | 1 | DEINDUGens | `GreyholeRaw` |
| `IOUGens.so` | 31,300 | 16 | core | **`AudioControl`** **`Control`**† **`In`**† **`InFeedback`**† **`InTrig`** **`LagControl`**† **`LagIn`** **`LocalIn`**† **`LocalOut`**† **`OffsetOut`** **`Out`**† **`ReplaceOut`** **`SharedIn`** **`SharedOut`** **`TrigControl`** **`XOut`** |
| `JPverb.so` | 116,876 | 1 | DEINDUGens | `JPverbRaw` |
| `JoshAmbiUGens.so` | 37,688 | 14 | JoshUGens | `A2B` `B2A` `B2Ster` `B2UHJ` `BFDecode1` `BFEncode1` `BFEncode2` `BFEncodeSter` `BFManipulate` `FMHDecode1` `FMHEncode0` `FMHEncode1` `FMHEncode2` `UHJ2B` |
| `JoshGrainUGens.so` | 196,672 | 30 | JoshUGens | `BufGrain` `BufGrainB` `BufGrainBBF` `BufGrainBF` `BufGrainI` `BufGrainIBF` `FMGrain` `FMGrainB` `FMGrainBBF` `FMGrainBF` `FMGrainI` `FMGrainIBF` `GrainBufJ` `GrainFMJ` `GrainInJ` `GrainSinJ` `InGrain` `InGrainB` `InGrainBBF` `InGrainBF` `InGrainI` `InGrainIBF` `MonoGrain` `MonoGrainBF` `SinGrain` `SinGrainB` `SinGrainBBF` `SinGrainBF` `SinGrainI` `SinGrainIBF` |
| `JoshPVUGens.so` | 53,848 | 24 | JoshUGens | `BinData` `PV_BinBufRd` `PV_BinDelay` `PV_BinFilter` `PV_BinPlayBuf` `PV_BufRd` `PV_EvenBin` `PV_Freeze` `PV_FreqBuffer` `PV_Invert` `PV_MagBuffer` `PV_MagMap` `PV_MaxMagN` `PV_MinMagN` `PV_NoiseSynthF` `PV_NoiseSynthP` `PV_OddBin` `PV_PartialSynthF` `PV_PartialSynthP` `PV_PitchShift` `PV_PlayBuf` `PV_RecordBuf` `PV_SpectralEnhance` `PV_SpectralMap` |
| `JoshUGens.so` | 81,300 | 30 | JoshUGens | `ATSSynth` `AtsAmp` `AtsBand` `AtsFreq` `AtsNoiSynth` `AtsNoise` `AtsParInfo` `AtsPartial` `AtsSynth` `AudioMSG` `Balance` `CombLP` `CubicDelay` `LPCSynth` `LPCVals` `Maxamp` `Metro` `MoogVCF` `NFC` `PMHPF` `PMLPF` `PVInfo` `PVSynth` `PanX` `PosRatio` `SinTone` `TALReverb` `TTendency` `WarpZ` `Xover2` |
| `KeyClarity.so` | 21,308 | 1 | SCMIRUGens | `KeyClarity` |
| `KeyMode.so` | 21,308 | 1 | SCMIRUGens | `KeyMode` |
| `LFUGens.so` | 76,184 | 30 | core | **`A2K`** **`AmpComp`** **`AmpCompA`** **`Clip`**† **`DC`**† **`EnvGen`**† **`Fold`** **`IEnvGen`** **`Impulse`** **`InRange`** **`InRect`** **`K2A`**† **`LFCub`**† **`LFGauss`** **`LFPar`** **`LFPulse`** **`LFSaw`** **`LFTri`** **`LinExp`** **`Line`**† **`Linen`** **`ModDif`** **`SyncSaw`** **`T2A`** **`T2K`** `Unwrap` **`VarSaw`** **`Vibrato`** **`Wrap`** **`XLine`** |
| `LadspaUGen.so` | 6,668 | 1 | LadspaUGen | **`LADSPA`**† |
| `LoopBuf.so` | 9,324 | 2 | LoopBufUGens | `FLoopBuf` `LoopBuf` |
| `MCLDBufferUGens.so` | 11,892 | 8 | MCLDUGens | `ArrayMax` `ArrayMin` `BufMax` `BufMin` `GaussClass` `ListTrig` `ListTrig2` `Logger` |
| `MCLDCepstrumUGens.so` | 9,124 | 2 | MCLDUGens | `Cepstrum` `ICepstrum` |
| `MCLDChaosUGens.so` | 13,820 | 5 | MCLDUGens | `FincoSprottL` `FincoSprottM` `FincoSprottS` `Perlin3` `RosslerL` |
| `MCLDDistortionUGens.so` | 5,108 | 3 | MCLDUGens | `InsideOut` `Squiz` `WaveLoss` |
| `MCLDFFTUGens.so` | 34,388 | 20 | MCLDUGens | `FFTComplexDev` `FFTCrest` `FFTDiffMags` `FFTFlux` `FFTFluxPos` `FFTMKL` `FFTPeak` `FFTPhaseDev` `FFTPower` `FFTSlope` `FFTSpread` `FFTSubbandFlatness` `FFTSubbandPower` `PV_ExtractRepeat` `PV_MagExp` `PV_MagLog` `PV_MagMulAdd` `PV_MagSmooth` `PV_MagSubtract` `PV_Whiten` |
| `MCLDFilterUGens.so` | 6,596 | 3 | MCLDUGens | `Crest` `Friction` `Goertzel` |
| `MCLDGetenvUGen.so` | 4,332 | 2 | MCLDUGens | `Clockmus` `Getenv` |
| `MCLDOscUGens.so` | 4,016 | 1 | MCLDUGens | `SawDPW` |
| `MCLDPollUGens.so` | 4,500 | 1 | MCLDUGens | `TextVU` |
| `MCLDSOMUGens.so` | 21,228 | 4 | MCLDUGens | `KMeansRT` `SOMAreaWr` `SOMRd` `SOMTrain` |
| `MCLDSparseUGens.so` | 9,776 | 2 | MCLDUGens | `MatchingP` `MatchingPResynth` |
| `MCLDTreeUGens.so` | 10,172 | 2 | MCLDUGens | `NearestN` `PlaneTree` |
| `MCLDTriggeredStatsUgens.so` | 7,592 | 2 | MCLDUGens | `MeanTriggered` `MedianTriggered` |
| `ML_UGens.so` | 72,032 | 9 | core | `BeatTrack` `BeatTrack2` `KeyTrack` `Loudness` `MFCC` `Onsets` `SpecCentroid` `SpecFlatness` `SpecPcile` |
| `MdaUGens.so` | 1,182,480 | 1 | MdaUGens | `MdaPiano` |
| `MembraneUGens.so` | 6,664 | 2 | MembraneUGens | `MembraneCircle` `MembraneHexagon` |
| `MulAddUGens.so` | 81,700 | 3 | core | **`MulAdd`**† **`Sum3`**† **`Sum4`**† |
| `NCAnalysisUGens.so` | 48,252 | 6 | NCAnalysisUGens | `LPCAnalyzer` `MedianSeparation` `SMS` `TPV` `WalshHadamard` `WaveletDaub` |
| `Neuromodules.so` | 5,816 | 1 | Neuromodules | `Dneuromodule` |
| `NoiseRing.so` | 4,992 | 1 | DEINDUGens | `DNoiseRing` |
| `NoiseUGens.so` | 21,188 | 26 | core | **`BrownNoise`** **`ClipNoise`** **`CoinGate`** **`Crackle`** **`Dust`** **`Dust2`** **`ExpRand`** **`GrayNoise`** **`Hasher`** **`IRand`** **`LFClipNoise`** **`LFNoise0`**† **`LFNoise1`**† **`LFNoise2`** **`LinRand`** **`Logistic`** **`MantissaMask`** **`NRand`** **`PinkNoise`** **`Rand`** **`RandID`** **`RandSeed`** **`TExpRand`** **`TIRand`** **`TRand`** **`WhiteNoise`**† |
| `OnsetStatistics.so` | 6,752 | 1 | SCMIRUGens | `OnsetStatistics` |
| `OscUGens.so` | 91,748 | 25 | core | **`Blip`** **`COsc`** **`DegreeToKey`** **`DetectIndex`** **`FSinOsc`** `FoldIndex` **`Formant`** **`Index`** **`IndexInBetween`** **`IndexL`**† **`Klang`** **`Klank`** **`Osc`** **`OscN`** `PSinGrain` **`Pulse`** **`Saw`** **`Select`**† **`Shaper`** **`SinOsc`** **`SinOscFB`** **`TWindex`** **`VOsc`** **`VOsc3`** **`WrapIndex`** |
| `OteyPianoUGens.so` | 51,220 | 3 | OteyPianoUGens | `OteyPiano` `OteyPianoStrings` `OteySoundBoard` |
| `PV_ThirdParty.so` | 38,612 | 9 | core | **`Convolution`** **`Convolution2`** **`Convolution2L`** **`Convolution3`** **`PV_ConformalMap`** **`PV_HainsworthFoote`** **`PV_JensenAndersen`** **`RunningSum`** **`StereoConvolution2L`** |
| `PanUGens.so` | 44,972 | 12 | core | **`Balance2`**† **`BiPanB2`** **`DecodeB2`** **`LinPan2`**† **`LinXFade2`**† **`Pan2`**† **`Pan4`** **`PanAz`** **`PanB`** **`PanB2`** **`Rotate2`** **`XFade2`**† |
| `PhysicalModelingUGens.so` | 5,840 | 3 | core | `Ball` `Spring` `TBall` |
| `PitchDetection.so` | 16,040 | 2 | PitchDetection | `Qitch` `Tartini` |
| `RFWUGens.so` | 4,996 | 2 | RFWUGens | `AverageOutput` `SwitchDelay` |
| `RMEQSuite.so` | 20,652 | 6 | RMEQSuiteUGens | `Allpass1` `Allpass2` `RMEQ` `RMShelf` `RMShelf2` `Spreader` |
| `ReverbUGens.so` | 19,860 | 3 | core | `FreeVerb` `FreeVerb2` `GVerb` |
| `SLUGens.so` | 42,600 | 30 | SLUGens | `Breakcore` `Brusselator` `DoubleWell` `DoubleWell2` `DoubleWell3` `EnvDetect` `EnvFollow` `FitzHughNagumo` `GravityGrid` `GravityGrid2` `Instruction` `KmeansToBPSet1` `LPCError` `LTI` `Max` `NL` `NL2` `NTube` `Oregonator` `PrintVal` `SLOnset` `Sieve1` `SortBuf` `SpruceBudworm` `TermanWang` `TwoTube` `VMScan2D` `WaveTerrain` `WeaklyNonlinear` `WeaklyNonlinear2` |
| `SensoryDissonance.so` | 7,716 | 2 | SCMIRUGens | `SensoryDissonance` `SpectralEntropy` |
| `StkInst.so` | 1,486,036 | 3 | StkInst | `StkGlobals` `StkInst` `StkMesh2D` |
| `StkUGens.so` | 432,980 | 17 | StkUGens | `Sflute` `StkBandedWG` `StkBeeThree` `StkBlowHole` `StkBowed` `StkClarinet` `StkFlute` `StkMandolin` `StkModalBar` `StkMoog` `StkPluck` `StkSaxofony` `StkShakers` `StkSitar` `StkStifKarp` `StkTubeBell` `StkVoicForm` |
| `SummerUGens.so` | 7,212 | 2 | SummerUGens | `Summer` `WrapSummer` |
| `TJUGens.so` | 28,308 | 1 | TJUGens | `DFM1` |
| `TagSystemUgens.so` | 12,760 | 3 | TagSystemUGens | `DbufTag` `Dfsm` `Dtag` |
| `TestUGens.so` | 6,468 | 2 | core | **`CheckBadValues`** `Sanitize` |
| `TriggerUGens.so` | 44,536 | 33 | core | **`Done`** **`Free`** **`FreeSelf`** **`FreeSelfWhenDone`** **`Gate`** **`LastValue`** **`Latch`** **`LeastChange`** **`MostChange`** **`Pause`** **`PauseSelf`** **`PauseSelfWhenDone`** **`Peak`** **`PeakFollower`** **`Phasor`**† **`Poll`** **`PulseCount`** **`PulseDivider`** **`RunningMax`** **`RunningMin`** **`Schmidt`** **`SendPeakRMS`** **`SendReply`** **`SendTrig`** **`SetResetFF`** **`Stepper`** **`Sweep`** **`TDelay`** **`Timer`** **`ToggleFF`** **`Trig`** **`Trig1`** **`ZeroCrossing`** |
| `UIUGens.so` | 16,320 | 4 | core | `KeyState` `MouseButton` `MouseX` `MouseY` |
| `UnaryOpUGens.so` | 69,748 | 1 | core | **`UnaryOpUGen`**† |
| `UnpackFFTUGens.so` | 8,424 | 2 | core | **`PackFFT`** **`Unpack1FFT`** |
| `VBAP.so` | 24,956 | 2 | VBAPUGens | `CircleRamp` `VBAP` |
| `VOSIM.so` | 7,364 | 1 | VOSIMUGens | `VOSIM` |
| `complexRes.so` | 6,572 | 1 | DEINDUGens | `ComplexRes` |

**Totals.** 795 registrations, 795 distinct names — no name is registered by two
different files. `[READ]` Two files register the same name twice internally
(`BerlachUGens.so` calls `fDefineUnit("LPF1", …)` twice, `JoshUGens.so` calls it
twice for `Xover2`); scsynth's unit-def table is keyed by name, so the second call
overwrites the first. `[INFERRED]` from the table being a name-keyed map — the
consequence, if any, is `[UNKNOWN]` and almost certainly nil, since in both cases
the two calls carry the same allocation size.

---

## 4. The 96 in shape

| bucket | files | UGens |
|---|---:|---:|
| stock SuperCollider 3.9 core plugin set | 25 | 388 |
| sc3-plugins packages present in `Extensions/` | 70 | 403 |
| neither — `AmbisonicUGens.so` | 1 | 4 |
| **total** | **96** | **795** |

`[READ]` (§7 gives the package→binary mapping.)

**`AmbisonicUGens.so` is unattributed.** 11,324 bytes, registering `Dominate`,
`Push`, `DistanceB`, `ProximityB`. `[READ]` No class of any of those four names
exists in the stock library, in `las-fx`, or anywhere in `Extensions/SC3plugins`;
no help file mentions them; `grep -ra` over the entire rootfs returns hits only
inside the binary itself. `[READ]` Its `.rodata` holds nothing but those four
strings. `[READ]` Where it came from is `[UNKNOWN]`.

**Ten `.so` account for 353 of the 795 registrations**: `FilterUGens` (57),
`DelayUGens` (55), `FFT_UGens` (35), `TriggerUGens` (33), `JoshGrainUGens` (30),
`JoshUGens` (30), `LFUGens` (30), `SLUGens` (30), `AtkUGens` (27), `NoiseUGens`
(26). `[READ]`

**The two largest binaries are physical modelling.** `StkInst.so` is 1,486,036
bytes for three UGens; `MdaUGens.so` is 1,182,480 bytes for one. `[READ]` §8
explains why.

---

## 5. The reachability question, settled

### 5.1 The numbers

| | UGens |
|---|---:|
| registered by the 96 `.so` | **795** |
| of those, a class exists in `las-fx/SCClassLibrary` (the library the running `sclang` compiles) | **360** |
| of those, **no** class in that library — unnameable from the instrument's own client | **435** |
| of the 795, used by at least one of the 104 shipped `.scsyndef` | **61** |
| resident, registered, and used by nothing that ships | **734** |

`[READ]` for all five rows.

### 5.2 Which files are wholly out of reach

**73 of the 96 have zero coverage** in the live class library. `[READ]` Complete
list:

`AY_UGen` `AmbisonicUGens` `AntiAliasingOscillators` `AtkUGens` `AttackSlope`
`AuditoryModeling` `BBCut2UGens` `BatPVUgens` `BatUGens` `BeatStatistics`
`BerlachUGens` `BetablockerUGens` `BhobChaos` `BhobFFT` `BlackrainUGens`
`ChaosUGens` `Chromagram` `Concat` `DWGBowed` `DWGPlucked` `DiodeRingMod`
`DrumTrack` `FM7` `FeatureSave` `GendynUGens` `GlitchUGens` `GrainUGens`
`Greyhole` `JPverb` `JoshAmbiUGens` `JoshGrainUGens` `JoshPVUGens` `JoshUGens`
`KeyClarity` `KeyMode` `LoopBuf` `MCLDBufferUGens` `MCLDCepstrumUGens`
`MCLDChaosUGens` `MCLDDistortionUGens` `MCLDFFTUGens` `MCLDFilterUGens`
`MCLDGetenvUGen` `MCLDOscUGens` `MCLDPollUGens` `MCLDSOMUGens` `MCLDSparseUGens`
`MCLDTreeUGens` `MCLDTriggeredStatsUgens` `ML_UGens` `MdaUGens` `MembraneUGens`
`NCAnalysisUGens` `Neuromodules` `NoiseRing` `OnsetStatistics` `OteyPianoUGens`
`PhysicalModelingUGens` `PitchDetection` `RFWUGens` `RMEQSuite` `ReverbUGens`
`SLUGens` `SensoryDissonance` `StkInst` `StkUGens` `SummerUGens` `TJUGens`
`TagSystemUgens` `UIUGens` `VBAP` `VOSIM` `complexRes`

Note what is on that list: **`ReverbUGens.so`** — `FreeVerb`, `FreeVerb2`, `GVerb`
are all resident and all unnameable. **`GrainUGens.so`** — `GrainIn`, `GrainSin`,
`GrainFM`, `GrainBuf`, `Warp1`, the whole granular family, likewise.
**`ChaosUGens.so`** — 22 stock chaotic generators, likewise.
**`PhysicalModelingUGens.so`** — `Spring`, `Ball`, `TBall`, likewise. These are not
exotic third-party additions; they are part of the standard SuperCollider
distribution that the fork simply did not carry over.

### 5.3 What Moog *did* fork

`las-fx/SCClassLibrary` carries three non-core directories — `BhobUGens/`,
`LadspaUGen/`, `LookupFilters/`. `[READ]` Only two of them contain bindings:
`BhobUGens/classes/` holds a single file, `bhobGens.sc`, and `LadspaUGen/` holds
`LadspaUGen.sc` plus a copy of `ladspalist`. `LookupFilters/` (`APFTable.sc`,
`BPFTable.sc`, `HPFTable.sc`, `LPFTable.sc`, `Crossover.sc`) binds nothing native —
those are pure-`sclang` composites, as `las-fx.md` §3 established. The third
binding file is `Audio/DistortionPlugins.sc`. `[READ]` Exactly those three files —
`bhobGens.sc`, `DistortionPlugins.sc`, `LadspaUGen.sc` — name **31** of the 403
sc3-plugins-derived UGens, and nothing else in the live library does: `[READ]`

| binary | reachable names |
|---|---|
| `BhobFilt.so` | `MoogLadder` `RLPFD` `NestedAllpassN/L/C` `DoubleNestedAllpassN/L/C` `Streson` `NLFiltN/L/C` — 12 of 13 (`MultiFilt` is not classed) |
| `BhobNoise.so` | all 11 |
| `BhobGrain.so` | `TGrains2` `TGrains3` |
| `DistortionUGens.so` | all 5 |
| `LadspaUGen.so` | `LADSPA` |

`[READ]` Of these, only two are used by anything that ships:
`DoubleNestedAllpassN` and `Decimator` (plus `LADSPA` for the six Eventide
reverbs). `[READ]` So the fork carried 31 third-party UGens and shipped 3.

`BhobUGens` is by a wide margin the best-supported third-party family on the
instrument: five binaries, 59 UGens, 120 files of source and help in `Extensions/`,
and a partial class fork already in place. `[READ]` `BhobChaos.so` (24 UGens) and
`BhobFFT.so` (10) are the two members of that family with no forked classes.

### 5.4 The 22 names with no class and no help anywhere

These exist only as registrations in the binaries. `[READ]`

| name | binary | note |
|---|---|---|
| `Dominate` `Push` `DistanceB` `ProximityB` | `AmbisonicUGens.so` | the whole unattributed plugin, §4 |
| `StkSitar` `StkStifKarp` `StkTubeBell` `Sflute` | `StkUGens.so` | 4 of its 17; `StkUGens.sc` classes only 13 |
| `StkMesh2D` | `StkInst.so` | `StkInst.sc` classes `StkInst` and `StkGlobals` only |
| `ATSSynth` `CubicDelay` `NFC` `PMHPF` `PMLPF` `TALReverb` `Xover2` | `JoshUGens.so` | 7 of its 30 |
| `DWGBowedStk` | `DWGBowed.so` | |
| `FLoopBuf` | `LoopBuf.so` | |
| `MultiFilt` | `BhobFilt.so` | |
| `Flip` | `FilterUGens.so` | stock plugin, undocumented UGen |
| `FoldIndex` | `OscUGens.so` | stock plugin, undocumented UGen |
| `Unwrap` | `LFUGens.so` | stock plugin, undocumented UGen |

The last three are the interesting ones: three UGens compiled into the **stock
SuperCollider 3.9 core** plugin binaries with no class and no help page in the
3.9 distribution shipped beside them. `[READ]` Whether upstream SuperCollider
also lacks classes for them is `[UNKNOWN]` from this image — see §12.

---

## 6. Everything else the plugins register

### 6.1 Buffer-fill routines (`/b_gen`)

Ten across the whole set. `[READ]`

| binary | `/b_gen` name | reachable from the shipped class library? |
|---|---|---|
| `OscUGens.so` | `sine1` `sine2` `sine3` `cheby` `normalize` `wnormalize` `copy` | yes — `Buffer.sc:461,509` and `EventTypesWithCleanup.sc:25-36` `[READ]` |
| `OscUGens.so` | **`cantorFill`** | **no caller anywhere in the image** `[READ]` |
| `LFUGens.so` | `env` | used by `Env`-to-`Signal` conversion `[INFERRED]` |
| `FFT_UGens.so` | `PreparePartConv` | needed by `PartConv`; `PartConv.sc` is present in `las-fx/SCClassLibrary/Audio/` `[READ]` |

**`cantorFill`.** `grep -ra cantorFill` over the entire rootfs returns exactly one
file, `usr/lib/SuperCollider/plugins/OscUGens.so`, where the string sits at
`0x15c08` immediately after `copy` at `0x15c00`, in the same contiguous run as the
other seven bufgen names. `[READ]` It is present identically in v1.5.0. `[READ]`
The `Server-Command-Reference.schelp` shipped in the image documents `sine1`,
`sine2`, `sine3` and `cheby` and does not mention it. `[READ]` Whether it is an
undocumented upstream routine or something `LAS_SC_UGENS` added is `[UNKNOWN]`.

### 6.2 Plugin commands (`/cmd`)

One, in the whole set: `pluginCmdDemo` in `UIUGens.so`, the stock SuperCollider
example handler. `[READ]`

### 6.3 Unit commands (`/u_cmd`)

The simulator found **no** `fDefineUnitCmd` call in any `load` function, but that
is a limitation of walking only from `load`: sc3-plugins registers unit commands
from a UGen's *constructor*. The `.rodata` sweep of §2.2 finds exactly one
plugin carrying unit-command-shaped strings — `FeatureSave.so`, with `createfile`
and `closefile`. `[READ]` The shipped help confirms the calling convention:
`SCMIRUGens/HelpSource/Classes/FeatureSave.schelp:33` reads
`s.sendMsg("/u_cmd", a.nodeID, ~featuresave.synthIndex, "createfile", "testfile2.data")`
and `:35` the matching `"closefile"`. `[READ]` `[INFERRED — firmly]` those are the
only unit commands in the resident plugin set, since any other would need its name
as an identifier string in some `.rodata`, and §2.2 accounts for all of them.

---

## 7. The source tree: `Extensions/SC3plugins`

807 files, 38 directories — **37 packages plus an empty `local/`**. `[READ]`
145 `.sc`, 272 `.schelp`, 193 `.html`, 77 `.rtf`, 41 `.raw`, 20 `.png`, 16 `.scd`,
16 `.htm`, 6 `.wav`, 4 `.c`, 3 `.jpg`, 2 `.pdf`, 2 `.txt`, 1 `.m`, plus 9
extensionless: `ATK/LICENSE`, `ATK/README`, `ATK/README_RECORDINGS`,
`LadspaUGen/README`, `LadspaUGen/ladspalist`, `MembraneUGens/README`,
`MembraneUGens/CHANGES`, and two files literally named `delete_me` in
`JoshUGens/classes/` and `JoshUGens/help/`. `[READ]`

Every one of the 37 packages has at least one corresponding `.so` in the plugin
directory. `[READ]` There is no package whose binary is missing, and no binary
outside the 25-file stock core and `AmbisonicUGens.so` whose package is missing.

| package | files | `.sc` | doc | `.so` | UGens | plugin binaries |
|---|---:|---:|---:|---:|---:|---|
| `ATK` | 74 | 3 | 54 | 1 | 27 | `AtkUGens.so` |
| `AYUGens` | 4 | 1 | 3 | 1 | 1 | `AY_UGen.so` |
| `AntiAliasingOscillators` | 13 | 1 | 12 | 1 | 6 | `AntiAliasingOscillators.so` |
| `AuditoryModeling` | 7 | 1 | 6 | 1 | 3 | `AuditoryModeling.so` |
| `BBCut2UGens` | 8 | 3 | 5 | 2 | 2 | `BBCut2UGens.so`, `DrumTrack.so` |
| `BatUGens` | 12 | 1 | 11 | 2 | 7 | `BatPVUgens.so`, `BatUGens.so` |
| `BerlachUGens` | 8 | 4 | 1 | 1 | 19 | `BerlachUGens.so` |
| `BetablockerUGens` | 9 | 2 | 2 | 1 | 2 | `BetablockerUGens.so` |
| `BhobUGens` | 120 | 6 | 114 | 5 | 59 | `BhobChaos.so`, `BhobFFT.so`, `BhobFilt.so`, `BhobGrain.so`, `BhobNoise.so` |
| `BlackrainUGens` | 10 | 1 | 9 | 1 | 4 | `BlackrainUGens.so` |
| `ConcatUGens` | 4 | 1 | 3 | 1 | 2 | `Concat.so` |
| `DEINDUGens` | 25 | 5 | 8 | 5 | 5 | `DiodeRingMod.so`, `Greyhole.so`, `JPverb.so`, `NoiseRing.so`, `complexRes.so` |
| `DWGUGens` | 8 | 2 | 6 | 2 | 7 | `DWGBowed.so`, `DWGPlucked.so` |
| `DistortionUGens` | 7 | 1 | 6 | 1 | 5 | `DistortionUGens.so` |
| `GlitchUGens` | 5 | 1 | 4 | 1 | 4 | `GlitchUGens.so` |
| `JoshUGens` | 124 | 48 | 74 | 4 | 103 | `JoshAmbiUGens.so`, `JoshGrainUGens.so`, `JoshPVUGens.so`, `JoshUGens.so` |
| `LadspaUGen` | 5 | 1 | 1 | 1 | 1 | `LadspaUGen.so` |
| `LoopBufUGens` | 21 | 13 | 8 | 1 | 1 | `LoopBuf.so` |
| `MCLDUGens` | 124 | 15 | 106 | 13 | 55 | `MCLDBufferUGens.so`, `MCLDCepstrumUGens.so`, `MCLDChaosUGens.so`, `MCLDDistortionUGens.so`, `MCLDFFTUGens.so`, `MCLDFilterUGens.so`, `MCLDGetenvUGen.so`, `MCLDOscUGens.so`, `MCLDPollUGens.so`, `MCLDSOMUGens.so`, `MCLDSparseUGens.so`, `MCLDTreeUGens.so`, `MCLDTriggeredStatsUgens.so` |
| `MdaUGens` | 4 | 1 | 3 | 1 | 1 | `MdaUGens.so` |
| `MembraneUGens` | 7 | 1 | 4 | 1 | 2 | `MembraneUGens.so` |
| `NCAnalysisUGens` | 18 | 6 | 12 | 1 | 6 | `NCAnalysisUGens.so` |
| `Neuromodules` | 4 | 1 | 1 | 1 | 1 | `Neuromodules.so` |
| `OteyPianoUGens` | 3 | 1 | 2 | 1 | 3 | `OteyPianoUGens.so` |
| `PitchDetection` | 13 | 2 | 4 | 1 | 2 | `PitchDetection.so` |
| `RFWUGens` | 8 | 2 | 5 | 1 | 2 | `RFWUGens.so` |
| `RMEQSuiteUGens` | 3 | 1 | 2 | 1 | 6 | `RMEQSuite.so` |
| `SCMIRUGens` | 18 | 9 | 9 | 8 | 10 | `AttackSlope.so`, `BeatStatistics.so`, `Chromagram.so`, `FeatureSave.so`, `KeyClarity.so`, `KeyMode.so`, `OnsetStatistics.so`, `SensoryDissonance.so` |
| `SLUGens` | 61 | 1 | 60 | 1 | 30 | `SLUGens.so` |
| `SkUGens` | 2 | 1 | 1 | 1 | 1 | `FM7.so` |
| `StkInst` | 49 | 1 | 3 | 1 | 2 | `StkInst.so` |
| `StkUGens` | 4 | 1 | 2 | 1 | 13 | `StkUGens.so` |
| `SummerUGens` | 3 | 1 | 2 | 1 | 2 | `SummerUGens.so` |
| `TJUGens` | 3 | 1 | 1 | 1 | 1 | `TJUGens.so` |
| `TagSystemUGens` | 11 | 2 | 9 | 1 | 3 | `TagSystemUgens.so` |
| `VBAPUGens` | 6 | 2 | 4 | 1 | 2 | `VBAP.so` |
| `VOSIMUGens` | 2 | 1 | 1 | 1 | 1 | `VOSIM.so` |
| `local` | 0 | 0 | 0 | 0 | 0 | — |

Note the shape of the tree. Three packages carry more than a hundred files each
(`JoshUGens` 124, `MCLDUGens` 124, `BhobUGens` 120) and are overwhelmingly
documentation: `BhobUGens` is 6 `.sc` and 114 help files. `[READ]` `SLUGens` is a
single 1-file class source and 60 help files for 30 UGens. `[READ]` The
documentation for every third-party UGen on this instrument is already sitting on
the flash, in `.schelp` and pre-rendered `.html`.

`local/` is empty — zero files. `[READ]` In a normal SuperCollider installation
that is the drop point for user extensions; here it is both empty and, because of
`sclang -a`, not on any search path.

### 7.1 Runtime data corpora shipped with the sources

Two packages carry binary data their UGens load at run time. `[READ]`

**`StkInst/rawwaves/` — 45 entries, 41 `.raw`.** The Synthesis ToolKit excitation
and wavetable corpus: `marmstk1.raw` (marimba strike), `mandpluk.raw` and
`mand1.raw`…`mand12.raw` (mandolin), `snardrum.raw`, `bassdrum.raw`, `tomhidrm`,
`tommiddr`, `tomlowdr`, `hihatcym`, `crashcym`, `ridecymb`, `cowbell1`,
`tambourn`, `britestk`, `dope`, `ahh.raw`, `eee.raw`, `ooo.raw`, `fwavblnk`,
`halfwave`, `sinewave`, `sineblnk`, `peksblnk`, `ppksblnk`, `snglpeak`,
`twopeaks`, `impuls10/20/40.raw`, `silence.raw`, plus four `.c` generators
(`makefunc.c`, `makemidi.c`, `makewavs.c`, `sine.c`). `[READ]`

**`PitchDetection/extraqitchfiles/` — six spectral kernels.**
`QspeckernN1024SR44100.wav`, `QspeckernN2048SR44100/48000.wav`,
`QspeckernN4096SR44100/48000.wav`, `QspeckernN8192SR44100.wav`, plus
`source/speckernels.m`. `[READ]` The `Qitch` UGen needs one of these in a buffer.
Note the instrument runs at 48 kHz (`init_sc_1.scd:18`) `[READ]`, and only the
N2048 and N4096 kernels exist at 48 kHz.

**`ATK` ships no kernel data.** 74 files, of which 3 are `.sc`
(`ATK.sc`, `ATKMatrix.sc`, `extPathName.sc`) and 54 are `.schelp`; there is no
matrix or decoder-kernel payload anywhere in the tree. `[READ]` The 27 registered
`Foa*` UGens are the matrix-free DSP ones; anything in `ATKMatrix.sc` that wants a
kernel file would have nothing to load. `[INFERRED]` from the absence of any
non-text file in the package.

---

## 8. The two big physical-modelling binaries

### 8.1 `StkInst.so` — 1.49 MB, three UGens, 28 instruments

`StkInst.so` statically links the whole Synthesis ToolKit: 86 distinct
`stk::` classes carry RTTI in the binary. `[READ]` The instrument classes present
are `BandedWG`, `BeeThree`, `BlowBotl`, `BlowHole`, `Bowed`, `Brass`, `Clarinet`,
`Drummer`, `FMVoices`, `Flute`, `Guitar`, `HevyMetl`, `Mandolin`, `Mesh2D`,
`ModalBar`, `Moog`, `PercFlut`, `Plucked`, `Resonate`, `Rhodey`, `Sampler`,
`Saxofony`, `Shakers`, `Simple`, `Sitar`, `StifKarp`, `TubeBell`, `VoicForm`,
`Whistle`, `Wurley`; alongside the toolkit's generators, filters, effects
(`NRev`, `JCRev`, `PRCRev`, `FreeVerb`, `Chorus`, `Echo`, `PitShift`,
`LentPitShift`), file I/O (`FileRead`, `FileWrite`, `FileWvIn`, `FileWvOut`,
`WvIn`, `WvOut`) and `MidiFileIn`/`Skini`. `[READ]`

**Only three UGens are exposed, and one of them is a dispatcher.**
`StkInst.sc` shows the design: `[READ]`

    Stk{ classvar names; ... names = Array.with("Clarinet", "BlowHole", "Saxofony",
      "Flute", "Brass", "BlowBotl", "Bowed", "Plucked", "StifKarp", "Sitar",
      "Mandolin", "Rhodey", "Wurley", "TubeBell", "HevyMetl", "PercFlut",
      "BeeThree", "FMVoices", "VoicForm", "Moog", "Simple", "Drummer",
      "BandedWG", "Shakers", "ModalBar", "Mesh2D", "Resonate", "Whistle"); ... }

    StkInst : UGen { *ar { arg instNumber=6,freq=220,gate=1,onamp=1,offamp=0.5,args;
        ^this.multiNewList(['audio', freq,gate,onamp,offamp,instNumber]++ args.asArray); } }

So all 28 instruments are reachable through the single UGen `StkInst`, selected by
an integer index 0–27, with per-instrument controller pairs passed as trailing
arguments. `[READ]` **This is the single highest-leverage fact in this report for
anyone extending the instrument**: 28 physical-modelling voices behind one
name-string registration.

`StkGlobals` is the configuration UGen: `[READ]`

    StkGlobals : UGen { *ar { arg showWarnings, printErrors, rawfilepath;
        var ascii = rawfilepath.ascii;
        ^this.multiNewList(['audio', showWarnings, printErrors].addAll(ascii)); } }

— the rawwave directory is passed as a run of ASCII codes in the UGen's inputs.

**The compiled-in default rawwave path is `../../rawwaves/`** `[READ]` (string at
index 501 in `StkInst.so`). Resolved against `scsynth`'s working directory, which
inherits `launch-sc-1`'s `cd /usr/share/las-fx/` `[READ]`, that is
`/usr/rawwaves/` — which **does not exist**; the only `rawwaves` directory on the
image is
`usr/share/SuperCollider/Extensions/SC3plugins/StkInst/rawwaves`. `[READ]`
`[INFERRED — firmly]` any STK instrument that reads an excitation table
(`Mandolin`, `Shakers`, `ModalBar`, `Plucked`, `VoicForm`, `Sampler`, …) will fail
to find its file unless `StkGlobals` is used first to point the toolkit at the
Extensions path. The oscillator-only instruments (`BeeThree`, `Rhodey`, `Wurley`,
`HevyMetl`, `FMVoices`, `Simple`, `Moog`, `Clarinet`, `Flute`, `Brass`, `Bowed`,
`BlowHole`, `BlowBotl`, `Saxofony`, `Whistle`, `Mesh2D`) do not. `[INFERRED]` from
which STK classes reference `.raw` filenames in the binary.

`StkUGens.so` (433 KB) links the same toolkit again and exposes 17 instruments as
individual UGens — `StkBandedWG`, `StkBeeThree`, `StkBlowHole`, `StkBowed`,
`StkClarinet`, `StkFlute`, `StkModalBar`, `StkMoog`, `StkPluck`, `StkSaxofony`,
`StkShakers`, `StkVoicForm`, `StkMandolin`, `StkSitar`, `StkStifKarp`,
`StkTubeBell`, `Sflute`. `[READ]` So the same DSP is resident twice, under two
different interfaces.

### 8.2 `MdaUGens.so` — 1.18 MB, one UGen

`MdaUGens.so` registers exactly one UGen, `MdaPiano`, with a unit-struct
allocation of 188 bytes. `[READ]` The 1.18 MB is the mda ePiano's sample and
coefficient tables compiled in. Every other mda plugin the sc3-plugins package
family carries upstream is absent from this build. `[READ]`

---

## 9. Classes without code, code without classes

### 9.1 Classes in the *live* library with no resident UGen

Beyond the pseudo-UGens SuperCollider has always shipped (`DynKlank`, `Splay`,
`Tap`, `Changed`, `CompanderD`, `UnpackFFT`, `InBus`, `Dunique`, `SimpleLoopBuf`
— all of which compose other UGens rather than needing a primitive), the live
library declares eight `PV_*` classes with no registration anywhere in the 96:
`PV_LoBitEncoder`, `PV_MagAllTimeAverage`, `PV_MagOnePole`, `PV_MagPeakDecay`,
`PV_OscBank`, `PV_TimeSmear`, `PV_Scope`, `PV_TimeAverageScope`, all in
`las-fx/SCClassLibrary/Audio/FFT.sc`. `[READ]` **All eight are present in the
stock 3.9 `SCClassLibrary` too** `[READ]`, so this is an upstream SuperCollider
condition and not something Moog did. Do not report it as a firmware defect.

Moog's own additions in that category are the `Fb` family —
`Fb`, `FbC`, `FbK`, `FbL`, `FbNode` in `las-fx/SCClassLibrary/Audio/Fb.sc`, none
of which exists in the stock library and none of which has a registration `[READ]`
— and `M_Delay` (`Effects/M_Delay.sc`), whose `.so` sits beside it outside the
plugin search path, already covered by `las-fx.md` §3.1.

### 9.2 sc3-plugins classes shipped with no resident implementation

Twelve classes in `Extensions/SC3plugins` call `multiNew` — i.e. are genuine
UGens, not composites — and have **no** registration in any of the 96 binaries:
`[READ]`

| class | package | file |
|---|---|---|
| `ChuaL` `RMAFoodChainL` `RosslerResL` | MCLDUGens | `MCLDChaosUGens.sc` |
| `FFTSubbandFlux` | MCLDUGens | `MCLDFFTUGens.sc` |
| `CQ_Diff` | MCLDUGens | `MCLD_CQ_UGens.sc` |
| `MIDelay` | MCLDUGens | `MCLDBufferUGens.sc` |
| `Clipper32` | BerlachUGens | `OSNonlinear.sc` |
| `EnvFollow` | SLUGens | `SLUGens.sc` — **see below** |
| `PV_MaxSortF` `PV_MaxSortM` | JoshUGens | `JoshPV.sc` |
| `LPCSynth2` `LPCVals2` | JoshUGens | `LPCSynth.sc` |
| `DetaBlocker01` | BetablockerUGens | `BetablockerUGens.sc` |

`EnvFollow` is the exception that proves the method: it *is* registered (§2.3), and
it was the `.rodata` sweep rather than the class tree that settled it. The other
eleven have no string in any `.rodata`. `[READ]`

`[INFERRED]` The shipped source tree is at a different revision from the binaries.
The practical consequence for extension work: **copying an sc3-plugins `.sc` file
into `las-fx/SCClassLibrary` does not guarantee the UGen exists.** A class that
compiles will still fail at `/d_recv` time with scsynth's
`UGen '%s' not installed.` `[READ]` Check the name against the tables in §3 first.

---

## 10. What this means for extension

Four routes to a resident-but-classless UGen. All are `[INFERRED]` from the read
facts in §1; none has been tried.

1. **Add the class file.** Drop the package's `.sc` into
   `las-fx/SCClassLibrary/` and restart. `sclang -a` compiles that directory and
   nothing else, so this is the only place a new class can go. The sources and
   help are already on the flash for all 37 packages. Cost: a filesystem write to
   the rootfs (`/dev/root` is `ext4 rw` per `etc/fstab` `[READ]`) and an `sclang`
   recompile. Risk: a class-library compile error takes down the whole effects
   client, and §9.2 lists twelve classes that will compile but not run.
2. **Ship a pre-compiled `.scsyndef`.** `init_sc_1.scd:36` calls
   `Server…loadDirectory("/usr/share/las-fx/synthdefs/")` at boot `[READ]`, so a
   graph built on a workstation (with a full SuperCollider that *does* have the
   classes) and copied into that directory will be loaded. This needs no class
   library change at all, and it is how the 434 unnameable UGens become usable
   without touching `sclang`.
3. **`/d_recv` a graph over OSC.** scsynth resolves UGens by name at graph-build
   time `[READ]`, so hand-assembled synthdef bytes work with no client-side
   knowledge whatsoever.
4. **A second `sclang` without `-a`.** Would pick up
   `usr/share/SuperCollider/SCClassLibrary` (340 `.sc`) *and*
   `Extensions/SC3plugins` (145 `.sc`), giving classes for most of the 795 in one
   step. But `usr/bin/sclang` carries the message `duplicate Class found: '%s'`
   `[READ]`, and the two class libraries overlap heavily, so a non-standalone
   `sclang` would have to exclude one tree. On a two-core, 512 MB machine whose
   cpu1 is the SCHED_FIFO 99 audio core, a second `sclang` is a real cost — this
   is the least attractive of the four.

**Which of the 795 is worth reaching first**, on the evidence of what is resident
and complete: `StkInst` (28 physical-modelling instruments behind one name, §8.1);
`GreyholeRaw` and `JPverbRaw` (two high-quality algorithmic reverbs, already
FAUST-compiled, already parameter-documented in their `.schelp`);
`ReverbUGens.so`'s `GVerb`/`FreeVerb2`; `GrainUGens.so`'s five granular UGens;
`MdaPiano`; `BhobChaos.so`'s 24 chaotic generators, whose sibling `BhobFilt`/
`BhobNoise` classes Moog has already forked so the idiom is established; and the
`AtkUGens.so` first-order-Ambisonic set for spatialisation. Every one of these has
its help page already on the flash.

---

## 11. Provenance

`etc/git-tags` reads, verbatim and including its malformed JSON — there is no
comma after `"vxdsp-v1.0.0rc1"`: `[READ]`

    {
     "LAS_FRONTEND_GIT_TAG" : "2.1.4",
    "LAS_VX_GIT_TAG" : "lasvx-v2.2.1",
    "LAS_FW_GIT_TAG" : "lasvc-v2.2.2",
    "LAS_SC_GIT_TAG" : "1.1.0r2",
    "LAS_FX_GIT_TAG" : "v1.1.1r4",
    "LAS_SC_UGENS_GIT_TAG" : "master",
    "LAS_FWU_GIT_TAG" : "v0.9.1",
    "LAS_WATCHDOG_GIT_TAG" : "v0.2.0",
    "LAS_DWM_GIT_TAG" : "v0.3.0",
    "LAS_VX_DSP_GIT_TAG" : "vxdsp-v1.0.0rc1"
    "LAS_BUILDROOT_GIT_TAG" : "v1.8.2"
    }

`LAS_SC_UGENS` is the only component pinned to `master` rather than a tag. `[READ]`
What is in that repository is `[UNKNOWN]`. What can be said:

* **All 96 `.so` are byte-identical between v1.5.0 and v1.8.2.** `[READ]` So
  whatever `master` was at each build, it produced the same 96 binaries — or the
  build was cached. The `Extensions/SC3plugins` tree and `las-fx/SCClassLibrary`
  are likewise `diff -rq` clean across the two versions. `[READ]`
* **No binary carries a build path, a vendor string or an SCM identifier.** No
  `.comment` section exists in any of the 96; the ELF section set is uniform
  (`.hash .dynsym .dynstr .gnu.version .gnu.version_r .rel.dyn .rel.plt .init .plt
  .text .fini .rodata .ARM.exidx .eh_frame .init_array .fini_array .jcr .dynamic
  .got .data .bss .ARM.attributes .shstrtab`, plus `.ARM.extab` in 69 and
  `.data.rel.ro` in 17). `[READ]` The only Moog-shaped string in any of them is
  `MoogFF`, `MoogLadder`, `BMoog`, `MoogVCF`, `StkMoog` and `N3stk4MoogE` — all
  pre-existing upstream UGen names for Moog-*ladder* emulations, nothing to do
  with the company's build. `[READ]` **Do not read those as attribution.**
* By contrast `usr/bin/scsynth` *does* carry
  `/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/build/supercollider-Version-3.9.0/external_libraries/boost_sync/…`
  `[READ]`, which fixes the server at **SuperCollider 3.9.0** built under
  Buildroot on a GitLab runner.

`[INFERRED]` The most economical reading is that `LAS_SC_UGENS` is a mirror or
light fork of upstream sc3-plugins built for `Cortex-A9`, and that its 96 outputs
match the `Extensions/SC3plugins` sources shipped beside them. The twelve classes
of §9.2 and `cantorFill` of §6.1 are the visible tension in that reading. Settling
it needs an upstream sc3-plugins checkout, not this image — §12.

---

## 12. Conflicts with existing docs

1. **`docs/firmware/gap-las-fx-coefficient-archive.md:896` (§17, "Unexplored")**
   says *"200-plus plugins under `usr/lib/SuperCollider/plugins/`"*. There are
   **96**. `[READ]` — `ls -1 …/plugins/*.so | wc -l` on both rootfs versions.
   `las-fx.md:709` and `arch/extension-points.md:754,1226` already say 96; this one
   line is the outlier.
2. **`docs/firmware/gap-las-fx-coefficient-archive.md` §10.4** leaves it
   `[UNKNOWN]` whether the plain `Index` UGen is registered, and reasons that if it
   is not, *"`APFTable` and `BPFTable` … could never have worked on this build at
   all."* **It is registered.** §0 item 1 above gives the three call sites and the
   tail-merge that hid it. That section's §16 item 5 — the requested read-only
   check — is hereby discharged, on a copy, with no device access.
3. **`docs/arch/extension-points.md:755`** says `Extensions/SC3plugins` *"holds
   sources and help only, zero `.so`"*. The zero-`.so` half is confirmed `[READ]`;
   the "sources and help only" half understates it — the tree also holds 41 STK
   `.raw` excitation tables and 6 Qitch `.wav` spectral kernels that are runtime
   data, not documentation (§7.1).
4. No conflict, but a sharpening: **`las-fx.md:709`**'s "every one resolves inside
   `/usr/lib/SuperCollider/plugins` (96 `.so`)" is now exhaustive rather than
   spot-checked. All 61 resolve, across 14 files: `FilterUGens` 17, `DelayUGens`
   12, `IOUGens` 7, `LFUGens` 6, `PanUGens` 5, `NoiseUGens` 3, `MulAddUGens` 3,
   `OscUGens` 2, and one each from `BinaryOpUGens`, `UnaryOpUGens`,
   `TriggerUGens`, `DistortionUGens`, `BhobFilt`, `LadspaUGen`. `[READ]` None of
   the 61 is a pseudo-UGen; every one has a native registration.

Per this report's brief, none of the above was edited in place.

---

## 13. Validation plan — read-only, for a human to run

Every check below is a read on a **copy** of the firmware on a workstation, except
where marked. Nothing here touches the instrument.

1. Re-derive the registration count independently of this report's simulator, on a
   workstation copy:

       for f in plugins/*.so; do echo -n "$f "; \
         llvm-objdump -d --triple=armv7-none-linux-gnueabihf "$f" \
         | grep -c 'ldr.*\[r[0-9]*, #0x18\]'; done

   Expect the per-file counts of §3 for files that use the simple idiom; files with
   a shared epilogue (`SLUGens.so`) will read low by one. This is a coarse check,
   not a proof.

2. Confirm the `Index` finding by hand:

       xxd -s 0x15b30 -l 48 plugins/OscUGens.so

   Expect `IndexL\0FoldIndex\0WrapIndex\0Index...` with `Index\0` beginning at
   `0x15b3c`, i.e. four bytes into `FoldIndex`.

3. Settle `cantorFill` and the three undocumented core UGens (`Flip`, `FoldIndex`,
   `Unwrap`) against upstream — **the one item that needs something not in this
   image**: check `OscUGens.cpp`, `FilterUGens.cpp` and `LFUGens.cpp` in the
   SuperCollider 3.9.0 source tree, and `sc3-plugins` at the matching era. If
   `cantorFill` is absent upstream it is a `LAS_SC_UGENS` addition and the first
   hard evidence of Moog work in the plugin set.

4. Confirm the resident set on the instrument **without writing anything**. The
   honest read-only test is a directory listing over the existing management path:

       ls -la /usr/lib/SuperCollider/plugins | wc -l
       md5sum /usr/lib/SuperCollider/plugins/OscUGens.so

   Expect 96 `.so` and a digest matching the workstation copy. Do **not** send OSC
   to scsynth to enumerate UGens — there is no read-only OSC command that lists the
   unit-def table, and `/d_recv` is a write.

5. Confirm the STK rawwave path problem, read-only, before anyone builds on it:

       ls -d /usr/rawwaves 2>&1
       ls /usr/share/SuperCollider/Extensions/SC3plugins/StkInst/rawwaves | wc -l

   Expect "No such file or directory" and 45.

6. Confirm the v1.5.0 byte-identity claim against the owner's own instrument, if a
   1.5.0 unit is reachable:

       md5sum /usr/lib/SuperCollider/plugins/StkInst.so

   Expect the same digest as the 1.8.2 copy.

---

## 14. Unexplored

* **Per-UGen input/output arity and rate constraints.** The unit-struct
  allocation size in `r1` was captured for every registration and is in the
  extraction data, but it says nothing about how many inputs a UGen wants. That
  information lives in the `.sc` class files (present for 773 of 795) and in the
  `.schelp`, neither of which was tabulated here.
* **Which of the 96 scsynth actually finishes loading.** `Greyhole.so` and
  `JPverb.so` export no `server_type`. scsynth's only plugin-rejection message is
  `API version not found: … This file may not be a SuperCollider plugin.`, which
  keys on `api_version`, not `server_type` `[READ]`, so `[INFERRED]` a missing
  `server_type` is tolerated as an older-header build. Not proven. If it is *not*
  tolerated, the two reverbs are not resident at all and §10's shortlist loses its
  two most attractive entries.
* **The `las-fx/SCClassLibrary` vs stock 340-file diff, per file.** `las-fx.md` §3
  reports 78 identical / 97 differing / 20 las-fx-only by basename and flags the 97
  as `[UNKNOWN]` cause. This report used only class *declarations* from those
  trees, so it neither confirms nor refutes that.
* **`AmbisonicUGens.so`.** Four UGens, no source, no help, no attribution anywhere.
  Not identified.
* **The 77 `.rtf` and 193 `.html`** in `Extensions/` were counted, not read. Some
  are pre-rendered help for UGens whose `.schelp` is missing (`JoshUGens` has 60
  `.html` and 0 `.schelp`), so they are the only documentation for that family.
* **`BBCut2UGens`.** The package ships 3 `.sc` and two binaries registering just
  `AnalyseEvents2` and `DrumTrack`; BBCut2 upstream is a large sequencing library
  whose bulk is `sclang`-side. Whether the missing class side is elsewhere on the
  image was not checked.
