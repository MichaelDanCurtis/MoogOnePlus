# The second JavaScript engine and the browser engine behind it: Qt5, QtWebKit and `usr/bin/jsc` (v1.8.2)

Scope: `usr/bin/jsc`, the twelve `libQt5*.so.5.5.1` libraries, and the twelve
plugins under `usr/lib/qt/plugins/` — about 44 MiB of the image that no prior
report mentions. Establish what they are, where they came from, whether anything
on the instrument uses them, and whether the JavaScript engine inside `jsc`
changes the security picture that `js-sandbox.md` drew for `las-frontend`.

Primary evidence is the decrypted v1.8.2 root filesystem at
`captures/firmware-1.8.2/rootfs-1.8.2`, with `captures/rootfs-1.5.0` for
comparison. Tools: `strings`, `xxd`, `cmp`, `md5`, Python for byte-level work, and
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf` / `-p` / `-h`. **No
instrument was touched, and no ARM binary was executed.**

For `jsc` the single r-x LOAD segment maps `file_offset = VMA − 0x10000`. String
offsets quoted below are **file** offsets unless stated otherwise.

Grading: **[READ]** = quoted directly out of a file at a stated offset or from a
stated command's output. **[INFERRED]** = reasoning from named evidence.
**[UNKNOWN]** = not established. **[EXTERNAL]** = background knowledge that is
*not* from these files and was *not* verified here — used twice, both times
flagged inline.

---

## 0. Summary

**The bottom line: this is a complete, loadable, and entirely unused Qt5 + QtWebKit
installation. `jsc` is a real second JavaScript engine, and it is buildroot
install residue from the `qt5webkit` package. Nothing on the instrument
references it, and it has not been meaningfully rebuilt since 2022.**

Six findings, in order of how much they should change anyone's mind:

1. **`js-sandbox.md` §1 is wrong as written.** It states "Only `las-frontend`
   contains a JS engine." There is a second, complete JavaScript engine in
   `usr/bin/jsc` (JavaScriptCore), and a *third* copy compiled into
   `libQt5WebKit.so.5.5.1`. The prior grep could not have found them because it
   searched for `JavascriptEngine|duk_|JerryScript|QuickJS|lua_State` — none of
   which JavaScriptCore uses. See §9 and Conflicts.
2. **Nothing uses any of it.** Zero files in the rootfs reference `usr/bin/jsc`.
   `libQt5WebKit` is referenced only by itself and by `libQt5WebKitWidgets`,
   which is itself referenced by nothing. No `.qml`, no `qt.conf`, no `QT_*`
   environment variable anywhere in `etc/`. §6.
3. **It is buildroot residue, and the binary proves it.** `jsc`'s `DT_RUNPATH`
   is `…/las-buildroot/output/build/qt5webkit-5.5.1/lib` — a path on Moog's CI
   machine, inside the buildroot package build directory. §5.
4. **It is frozen.** `jsc` in 1.8.2 is the same code as in 1.5.0 (May 2022),
   differing only because the baked-in CI path got 13 characters longer. §7.
5. **The security delta is close to zero, but not for the reason you would
   guess.** `jsc` has no `system`, `popen`, `fork`, `exec*`, `dlopen`, `socket`
   or `connect` in its PLT. More decisively, the image already ships `bash`,
   `sclang`, `gdb` and `strace`. `jsc` is a worse tool than what is already
   there. §8.
6. **This resolves an open `[UNKNOWN]` in `diff-files.md`.** That report could
   not explain why `libQt5WebKit.so.5.5.1` differs between versions at identical
   size with "zero string-set differences". The mechanism is non-deterministic
   ordering in WebKit's generated string tables: same strings, same count,
   different order. Proven in §7.3.

---

## 1. `usr/bin/jsc` — the ELF facts

**[READ]** `usr/bin/jsc`, 4,227,740 bytes, mode `0755` as extracted, MD5
`68ed15ee408d3766f1b7c7039618ff6e`.

**[READ]** ELF header (`xxd -l 64 usr/bin/jsc`):

| field | value | meaning |
|---|---|---|
| `e_type` | `0x0002` | **`ET_EXEC`** — a fixed-load executable, not PIE |
| `e_machine` | `0x0028` | `EM_ARM` |
| `e_entry` | `0x000155d4` | |
| `e_flags` | `0x05000402` | ARM EABI v5, `EF_ARM_ABI_FLOAT_HARD`, `HASENTRY` |
| `e_phnum` / `e_shnum` | 8 / 27 | |

`ET_EXEC` means the main image loads at a fixed address (`0x00010000`) with no
ASLR. This is unremarkable for buildroot-era ARM userspace and is true of other
binaries in this image; it is recorded here for completeness, not as a finding.

**[READ]** `DT_NEEDED`, in order: `librt.so.1`, `libpthread.so.0`, `libdl.so.2`,
`libicui18n.so.56`, `libicuuc.so.56`, `libicudata.so.56`, **`libQt5Core.so.5`**,
`libstdc++.so.6`, `libm.so.6`, `libgcc_s.so.1`, `libc.so.6`.

**`jsc` does not link `libQt5WebKit`.** JavaScriptCore is statically linked into
the executable — which is what makes a JavaScript shell 4.2 MB. **[INFERRED]**
from the combination of: the string `JavaScriptCore` appearing inside `jsc`
(§1.2), 59 `JSC_*` VM option names inside `jsc` (§2), and no WebKit/JSC shared
object among its `DT_NEEDED`.

**[READ]** Every one of those eleven libraries is present and resolvable:

```
librt.so.1  libpthread.so.0  libdl.so.2  libm.so.6  libgcc_s.so.1  libc.so.6   -> lib/
libicui18n.so.56  libicuuc.so.56  libicudata.so.56  libQt5Core.so.5
libstdc++.so.6                                                                 -> usr/lib/
```

**[READ]** There is no `etc/ld.so.conf`, no `etc/ld.so.conf.d/`, and no
`etc/ld.so.cache` in the image. **[INFERRED]** Resolution therefore falls to
glibc's built-in trusted directories `/lib` and `/usr/lib`, which is where all
eleven live. `DT_RUNPATH` is searched first but names a directory that does not
exist on the device (§5), so it contributes nothing and costs eleven failed
`stat` calls. **`jsc` would start.** Nothing about the filesystem prevents it.

### 1.2 It is the JavaScriptCore shell, not something Moog wrote

**[READ]** The usage banner, at file offset 4,000,920 and following:

```
Usage: jsc [options] [files] [-- arguments]
  -e         Evaluate argument as script code
  -h|--help  Prints this help message
  -i         Enables interactive mode (default if no files are specified)
  --options                  Dumps all JSC VM options and exits
  --dumpOptions              Dumps all JSC VM options before continuing
  --<jsc VM option>=<value>  Sets the specified JSC VM option
```

This is verbatim WebKit's `Source/JavaScriptCore/jsc.cpp` usage text. Note
`-i` — **interactive mode is the default when no file is given.**

**[READ]** Other identifying strings: `jsc exiting %d` (4,001,640),
`could not save profiler output.` (4,001,656), `--> %s` (4,001,116, the
interactive prompt echo), `--> Stack trace:` (4,001,356), `[Command Line]`
(4,001,576), `Exception: %s` (4,001,604), `Interpreter` (4,001,628).

---

## 2. What the shell exposes

**[READ]** 59 distinct `JSC_*` VM option names, including `JSC_useJIT`,
`JSC_useDFGJIT`, `JSC_useRegExpJIT`, `JSC_showDisassembly`,
`JSC_enableProfiler`, and the full `thresholdForJIT*` / inlining family. The
baseline JIT, the DFG optimising JIT and the RegExp JIT are all compiled in and
settable from the command line.

**[READ]** The builtin-name table is contiguous at file offsets 4,001,124 –
4,001,231. Raw bytes (`xxd -s 4001110 -l 160 usr/bin/jsc`):

```
003d0d66: 6275 6700 0000 6465 7363 7269 6265 0000  bug...describe..
003d0d76: 0000 7072 696e 7400 0000 7175 6974 0000  ..print...quit..
003d0d86: 0000 6763 0000 7665 7273 696f 6e00 7275  ..gc..version.ru
003d0d96: 6e00 6c6f 6164 0000 0000 6368 6563 6b53  n.load....checkS
003d0da6: 796e 7461 7800 6a73 6353 7461 636b 0000  yntax.jscStack..
003d0db6: 0000 7265 6164 6c69 6e65 0000 0000 7072  ..readline....pr
003d0dc6: 6563 6973 6554 696d 6500                 eciseTime.
```

Twelve names, in JSC's own registration order:

| offset | name | what it does in `jsc.cpp` |
|---|---|---|
| 4001124 | `debug` | write to stderr |
| 4001132 | `describe` | dump internal value representation |
| 4001144 | `print` | write to stdout |
| 4001152 | `quit` | exit |
| 4001160 | `gc` | force garbage collection |
| 4001164 | `version` | |
| 4001172 | **`run`** | **read a file, execute it, return elapsed ms** |
| 4001176 | **`load`** | **read a file and execute it** |
| 4001184 | `checkSyntax` | parse a file without running it |
| 4001196 | `jscStack` | stack trace |
| 4001208 | `readline` | **read a line from stdin** |
| 4001220 | `preciseTime` | |

> **Method note, because it nearly produced a false claim.** A first pass with
> `strings | grep -x` reported `gc` and `run` as *absent*. That was an artifact:
> `strings` defaults to a four-character minimum, so two- and three-character
> identifiers are never printed. The raw bytes above show both. Any short-name
> absence claim from `strings` is worthless without `-n 2` or a hex dump. The
> table is quoted from bytes for this reason.

**[READ]** `readFile` is genuinely absent — eight characters, well above the
`strings` floor, zero exact-line hits across the whole binary. **[INFERRED]**
This build predates or omits JSC's file-reading-without-executing helper, so the
only route from a filename to content is `load`/`run`, which *execute* it.

**[READ]** The typed-array constructors follow immediately (4,001,232 onward):
`Uint8Array`, `Uint8ClampedArray`, `Uint16Array`, `Uint32Array`, `Int8Array`,
`Int16Array`, `Int32Array`, `Float32Array`, `Float64Array`. Error strings
`Could not open file: %s` (4,001,392) and
`ArrayBuffer size is not a small enough positive integer.` (4,001,444).

**[UNKNOWN]** I did not prove the call sites that register these names. ARM
codegen here loads literals PC-relatively, so no absolute pointer to
`0x3e0d64` (`debug`) — or to any other `.rodata` string, including the usage
banner — exists anywhere in the file; searching for one returns zero, as it does
for strings that are certainly referenced. The identification rests on the byte
table, the usage banner and the `JSC_*` option set, which is ample, but the
registration code itself is unverified.

### 2.1 What it can reach: the import table

**[READ]** 186 PLT entries. Filtering for process, file and network primitives:

| present | absent |
|---|---|
| `fopen64`, `open64`, `read` | `system`, `popen` |
| `mmap64`, `mprotect` | `fork`, `vfork`, `execl*`, `execv*`, `posix_spawn` |
| `getenv` | `dlopen`, `dlsym` |
| | `socket`, `connect` |
| | `unlink`, `remove`, `chmod`, `chown` |

`mmap64` + `mprotect` are the JIT's W^X machinery. **[INFERRED]** `jsc` cannot
spawn a process, open a socket, load a shared object, or delete a file *through
its own imports*. That bound is real but soft: an enabled JIT means the process
can write and execute arbitrary native code, at which point the import table
stops being a boundary. §8 treats this properly.

**[READ]** 39 mangled C++ imports resolve against `libQt5Core`, including
`QCoreApplication` construct/destruct, `QCoreApplication::postEvent`,
`QEventLoop` construct/destruct, `QBasicTimer::start`/`stop`,
`QElapsedTimer::start`, `QMutex`, `QString::vsprintf`,
`QString::fromLatin1_helper`, `QString::toUtf8_helper`, and the `QObject`
virtual set.

**[INFERRED]** So the Qt dependency is not decorative — this build of `jsc` runs
a `QCoreApplication` and a `QEventLoop` and drives JSC's timers from Qt's event
loop. That is QtWebKit's variant of the shell, not upstream JSC's. It reinforces
the provenance in §5: this binary is an output of the `qt5webkit` package, not
something linked by hand.

---

## 3. The Qt5 inventory

**[READ]** Twelve shared libraries, twelve plugins, one executable —
**46,543,480 bytes (44.4 MiB)**:

| bytes | file |
|---:|---|
| 24,736,204 | `usr/lib/libQt5WebKit.so.5.5.1` |
| 5,681,368 | `usr/lib/libQt5Widgets.so.5.5.1` |
| 4,388,728 | `usr/lib/libQt5Core.so.5.5.1` |
| 4,227,740 | `usr/bin/jsc` |
| 3,849,056 | `usr/lib/libQt5Gui.so.5.5.1` |
| 1,398,108 | `usr/lib/libQt5Network.so.5.5.1` |
| 512,104 | `usr/lib/libQt5XcbQpa.so.5.5.1` |
| 340,576 | `usr/lib/libQt5PrintSupport.so.5.5.1` |
| 236,696 | `usr/lib/libQt5Sql.so.5.5.1` |
| 217,628 | `usr/lib/libQt5WebKitWidgets.so.5.5.1` |
| 201,492 | `usr/lib/libQt5Xml.so.5.5.1` |
| 193,892 | `usr/lib/libQt5Test.so.5.5.1` |
| 18,352 | `usr/lib/libQt5Concurrent.so.5.5.1` |
| 106,788 | `qt/plugins/platforms/libqoffscreen.so` |
| 64,336 | `qt/plugins/generic/libqevdevtouchplugin.so` |
| 55,936 | `qt/plugins/generic/libqevdevkeyboardplugin.so` |
| 51,396 | `qt/plugins/generic/libqtuiotouchplugin.so` |
| 43,940 | `qt/plugins/bearer/libqgenericbearer.so` |
| 43,476 | `qt/plugins/generic/libqlibinputplugin.so` |
| 41,220 | `qt/plugins/generic/libqevdevmouseplugin.so` |
| 40,200 | `qt/plugins/platforminputcontexts/libcomposeplatforminputcontextplugin.so` |
| 31,952 | `qt/plugins/generic/libqevdevtabletplugin.so` |
| 27,496 | `qt/plugins/platforms/libqminimal.so` |
| 27,216 | `qt/plugins/imageformats/libqico.so` |
| 7,580 | `qt/plugins/platforms/libqxcb.so` |

**[READ]** Image context: 496,847,459 bytes in 6,035 regular files.
`las-frontend` alone is 145,033,524 (29.2%). Qt is **9.4% of the whole image and
13.2% of everything that is not `las-frontend`**. `libQt5WebKit.so.5.5.1` is the
**third**-largest file, behind `las-frontend` and `libicudata.so.56.1`
(25,047,800) — the assignment's "second-largest" is off by one; ICU's data blob
edges it out. `libQt5Widgets` is the sixth-largest.

**[READ]** Build identity, from `libQt5Core`:

```
Qt 5.5.1 (arm-little_endian-ilp32-eabi-hardfloat shared (dynamic) release build; by GCC 4.8.5)
qt_lcnsuser=Open Source
qt_lcnsprod=OpenSource
qt_prfxpath=/usr
```

Open-source (LGPL) Qt 5.5.1, release build, GCC 4.8.5.

**[EXTERNAL]** — *not from these files, and not verified here:* Qt 5.5.1 dates
to October 2015, and QtWebKit was deprecated by the Qt Project around Qt 5.5 and
dropped from the default build in 5.6. I flag this separately because it is
background knowledge, not evidence off the disk; anyone relying on the
end-of-life argument should confirm it against Qt's own release records.
**[INFERRED]**, and only if that holds: this stack was already end-of-life when
the Moog One shipped in 2018.

**[READ]** `lib/qt/plugins` is compiled into `libQt5Core` alongside
`qt_prfxpath=/usr`, so the plugin search path resolves correctly to
`/usr/lib/qt/plugins`. There is no `qt.conf` anywhere in the image and none is
needed. (I initially expected the buildroot path patch to be missing and the
plugin path to be broken; it is not. Recorded so the correction is not silently
dropped.)

### 3.1 The whole stack is loadable

**[READ]** Every `DT_NEEDED` of `libQt5WebKit` resolves: `libXrender.so.1`,
`libXext.so.6`, `libX11.so.6`, `libsqlite3.so.0`, `libz.so.1`, `libQt5Gui.so.5`,
`libQt5Network.so.5`, `libQt5Sql.so.5`. So does every one of the 35 `DT_NEEDED`
of `libqxcb.so`, including `libxkbcommon-x11.so.0`, `libinput.so.10`,
`libmtdev.so.1`, `libEGL.so.1` and `libudev.so.1`.

**This is not a half-installed package.** Nothing is missing. It is a complete,
functional Qt5 + QtWebKit + X11 installation that is never invoked.

---

## 4. The evdev/libinput plugin question

The assignment asks why an embedded Qt was built with evdev and libinput input
plugins "as if it were meant to drive a panel." The evidence says it was not.

**[READ]** The platform plugins present are exactly three: `libqxcb.so`,
`libqminimal.so`, `libqoffscreen.so`. **`libqlinuxfb.so`, `libqeglfs.so` and
`libqdirectfb.so` are absent.**

**[INFERRED]** That is the signature of a Qt configured for **X11**, not for a
bare framebuffer or EGL panel. A Qt built to drive an embedded panel directly
would ship `linuxfb` or `eglfs`; this one ships only `xcb` plus the two
headless/degenerate platforms that Qt always builds.

**[INFERRED]** The `generic/` plugins — `libqevdevkeyboardplugin.so`,
`libqevdevmouseplugin.so`, `libqevdevtouchplugin.so`,
`libqevdevtabletplugin.so`, `libqtuiotouchplugin.so`, `libqlibinputplugin.so` —
are `qt5base`'s **defaults**. Qt 5.5's `qtbase` builds the generic evdev plugin
set whenever the host has the headers, independent of platform-plugin choice,
and buildroot installs whatever `qtbase` produced. Their presence indicates a
default-on build option, not a design intent to read the Moog One's panel.

**[READ]** Corroboration that Qt is not near the panel: `las-frontend`, the
process that *does* own the front panel, links `libX11.so.6`,
`libXinerama.so.1`, `libXext.so.6`, `libfreetype.so.6`, `libcurl.so.4`,
`libssl.so.1.0.0`, `libcrypto.so.1.0.0`, `libasound.so.2` and `libchicken.so.8`
— **and no Qt library at all.** `docs/arch/performance.md` (lines 676–680)
independently found zero `Qt5`/`QWidget`/`QApplication`/`QObject` symbols in
`las-frontend` against 870 `juce` symbols. The two findings agree.

**[UNKNOWN]** Why Qt was enabled in the buildroot configuration in the first
place. No buildroot `.config`, package manifest or `defconfig` survives in the
image, so the intent behind the build option is not recoverable from this
evidence. Candidate explanations — a developer convenience, a vendor BSP
default, an abandoned service-screen prototype — are all consistent with what is
here, and I can rank none of them.

---

## 5. Provenance: this came out of buildroot's `qt5webkit` package

**[READ]** `jsc` carries `DT_RUNPATH`:

```
/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/build/qt5webkit-5.5.1/lib
```

**[READ]** The only `output/build/…` package directory named anywhere in `jsc`
is `output/build/qt5webkit-5.5.1`.

Three things follow.

**[INFERRED]** `jsc` is an output of the buildroot **`qt5webkit`** package.
Buildroot builds `qt5webkit` from the Qt WebKit source tree, and that tree
builds `jsc` as a by-product of building JavaScriptCore. Buildroot's install
step copies what the package staged into `/usr/bin`. Nobody chose to ship a
JavaScript shell; the package brought one.

**[INFERRED]** `DT_RUNPATH` pointing into the *builder's* working tree is a
buildroot artifact, not a deployment decision — `/home/las-ci-builds/…` does not
exist on the instrument. It is inert (§1).

**[READ]** This is image-wide, not specific to `jsc`. The same
`/home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/build/…`
prefix appears in `alsa-lib-1.1.0`, `attr-2.4.47`, `avahi-0.6.32`,
`cairo-1.14.4`, `dbus-1.10.6`, `dbus-glib-0.106`, `directfb-1.7.7`,
`libglib2-2.46.2`, `libxcb-1.11.1` and others. **`jsc` should not be singled out
for leaking a build path — most of the image does.**

**[READ]** `glrt-` is the GitLab Runner authentication-token prefix; `glrt-t3_`
and the `0/` job-slot component are a GitLab CI runner working directory.
**[INFERRED]** Moog builds this firmware on self-hosted GitLab CI runners.

---

## 6. The reachability audit: nothing uses any of it

Each line below is **[READ]**, over the full rootfs unless noted.

| probe | result |
|---|---|
| `grep -rlsa "usr/bin/jsc" .` | **zero files** |
| `grep -rlsa -w "jsc"` over `*.sh *.scd *.conf *.cfg` | **zero files** |
| `grep -rlsa "JavaScriptCore" .` | `usr/bin/jsc`, `usr/lib/libQt5WebKit.so.5.5.1` — nothing else |
| `grep -rlsa "libQt5Core"` over `bin sbin usr/bin usr/sbin usr/lib lib` | `usr/bin/jsc` + Qt's own libraries and plugins — **no other executable** |
| `grep -rlsa "libQt5WebKit"` (same scope) | `libQt5WebKit.so.5.5.1`, `libQt5WebKitWidgets.so.5.5.1` — **itself and its own wrapper** |
| `find . -name "*.qml" -o -name "*.qrc" -o -name "qt.conf"` | **zero** |
| `find . -name "*.js"` | 5 files, all `usr/share/SuperCollider/HelpSource/` (`browse.js`, `prettify.js`, `lang-sc.js`, `scdoc.js`, `search.js`) — SuperCollider's HTML help assets, unrelated |
| `grep -rns "QT_" etc/` | **zero** |
| `etc/profile` | `export PATH=/bin:/sbin:/usr/bin:/usr/sbin` — `jsc` is *on* `PATH`, but nothing invokes it |

**[INFERRED]** `libQt5WebKitWidgets` is referenced only by nothing, and
`libQt5WebKit` only by `libQt5WebKitWidgets`. The 24.7 MB browser engine has no
consumer in the image, direct or transitive. The `libQt5Sql`, `libQt5Xml`,
`libQt5Test`, `libQt5Concurrent`, `libQt5PrintSupport` and `libQt5Network`
libraries exist solely to satisfy WebKit's and Widgets' link edges.

**[UNKNOWN]** A `dlopen` with a runtime-assembled library name would not appear
in these greps. I consider this unlikely — `jsc` has no `dlopen` at all, and
`las-frontend` links X11/JUCE with no Qt symbols — but I did not disassemble
every binary's `dlopen` call sites to exclude it.

---

## 7. v1.5.0 versus v1.8.2: frozen for three years

**[READ]** `usr/bin/jsc` exists in both: 4,227,724 bytes in 1.5.0 (dated May
2022), 4,227,740 in 1.8.2. MD5s differ (`caaf3fb5…` vs `68ed15ee…`).
`libQt5WebKit.so.5.5.1` is 24,736,204 bytes in both.

### 7.1 `jsc` differs only because the CI path grew

**[READ]** The two `DT_RUNPATH` values:

```
1.5.0: /home/las-ci-builds/6c53963c/0/moogmusic/las-buildroot/output/build/qt5webkit-5.5.1/lib   (87 chars)
1.8.2: /home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/output/build/qt5webkit-5.5.1/lib   (100 chars)
```

13 characters longer; the file is exactly **16 bytes** longer after alignment.

**[READ]** `cmp -l` reports 3,512,313 differing bytes — which is misleading. The
string lives in `.dynstr` at file offset `0x11cdc`, so a 16-byte insertion
shifts the remaining 4.2 MB. Re-comparing with the shift applied:

```
window @0x20000 : 1,046,719 / 1,048,576 bytes equal after +16 shift (99.82%)
window @0x100000: 1,047,949 / 1,048,576 bytes equal after +16 shift (99.94%)
window @0x300000: 1,046,248 / 1,048,576 bytes equal after +16 shift (99.78%)
```

**[INFERRED]** `jsc` was not modified between 1.5.0 and 1.8.2. It was relinked
against a longer build path; the residual ~0.1% is address fixups shifted by the
same 16 bytes. **The JavaScript engine on this instrument is the 2022 build,
which is itself a 2015 upstream.**

**[READ]** The 1.5.0 path also names the CI project differently: `moogmusic`
versus `moog/hardware/moog-one`, and the runner ID `6c53963c` versus the modern
`glrt-` token form. **[INFERRED]** Moog reorganised its GitLab group structure
and re-provisioned runners between the two releases.

### 7.2 Most of Qt was not rebuilt at all

**[READ]** Byte-identical across 1.5.0 and 1.8.2:

| file | MD5 (both) |
|---|---|
| `libQt5Core.so.5.5.1` | `1365fdc58db90676c9fc34b847500fb6` |
| `libQt5Widgets.so.5.5.1` | `9ec29cf1ba37d4a3809068cd78584cd2` |
| `libQt5WebKitWidgets.so.5.5.1` | `c2a8d681a70924863365d41856bc3682` |
| `qt/plugins/platforms/libqxcb.so` | `77cda52300a7252f62d816dc32e280bc` |

**[INFERRED]** `qt5base` was not rebuilt between releases, while `qt5webkit`
was. Consistent with buildroot's per-package incremental build and with nobody
touching this code.

### 7.3 Resolving `diff-files.md`'s `[UNKNOWN]` on `libQt5WebKit`

`docs/firmware/diff-files.md` records: *"`usr/lib/libQt5WebKit.so.5.5.1`
(24,736,204 B) differs with **zero** string-set differences and no embedded CI
path… consistent with a recompile, but I did not prove the mechanism."*

**[READ]** Neither version's `libQt5WebKit` has a `DT_RUNPATH` or `DT_RPATH`, so
the §7.1 mechanism does not apply. At identical total size, **12,219 bytes
differ, in 41 clusters**, landing in `.rel.dyn`, `.text`, `.rodata` and
`.data.rel.ro` (section bounds from `llvm-objdump -h`).

**[READ]** Reading the two largest `.rodata` clusters side by side shows the
same strings in a different order:

```
offset 0x1472cc8
  1.5.0: b'stretchy\0\0\0\0msub\0\0\0\0color\0\0\0linethickness\0\0\0mund'
  1.8.2: b'msub\0\0\0\0color\0\0\0linethickness\0\0\0munder\0\0depth\0\0\0'

offset 0x1498958
  1.5.0: b'role\0\0\0\0default\0http-equiv\0\0ontransitionend\0uiac'
  1.8.2: b'default\0http-equiv\0\0ontransitionend\0uiactions\0\0\0'
```

**[READ]** Tokenising both windows and comparing:

| window | count 1.5.0 | count 1.8.2 | same order? | same set? |
|---|---|---|---|---|
| `0x1472cc8–0x1473e14` | 379 | 379 | **no** | **yes** |
| `0x1498958–0x1499bd7` | 453 | 453 | **no** | **yes** |

These are WebKit's generated MathML/HTML tag-and-attribute and event-handler
atom tables (`stretchy`, `msub`, `linethickness`, `munder`; `http-equiv`,
`ontransitionend`).

**[READ]** The `.data.rel.ro` cluster at `0x17899a4` shows the corresponding
pointer fixups — e.g. `0x017a882c` → `0x017a8834`, an 8-byte move.

**[INFERRED]** **The mechanism is non-deterministic ordering in WebKit's
build-time code generators.** Those tables are emitted by Perl/Python scripts
whose output order depends on hash iteration order, which varies run to run.
Identical total size, identical string *sets*, different *order*, plus pointer
and relocation fixups following the moved strings — every observation
`diff-files.md` recorded, explained. **This is a non-reproducible build, not a
source change.** No WebKit source change is implied, and none is evidenced.

**[UNKNOWN]** Whether the same mechanism explains `diff-files.md`'s other open
item, `usr/bin/lassvc` (187,578 differing bytes at identical size). Plausible —
the signature is similar — but `lassvc` is Moog's own code and I did not test
it. Suggested as a lead, not a claim.

---

## 8. Security: what the second engine actually changes

The assignment's framing — a second, unreviewed JS engine on a device that
auto-mounts untrusted USB media as root — is the right question. The answer is
that **it changes very little, and the reasons are worth stating precisely so
this is not re-litigated.**

**[READ]** `etc/udev/rules.d/40-usb-thumbdrive.rules` does auto-mount:

```
KERNEL!="sd[a-z][0-9]", GOTO="thumbdrive_auto_mount_end"
 IMPORT{program}="/sbin/blkid -o udev -p %N"
 ACTION=="add", ENV{mount_options}="relatime"
 ACTION=="add", ENV{ID_FS_TYPE}=="vfat|ntfs", ENV{mount_options}="$env{mount_options},utf8,gid=100,umask=002"
 ACTION=="add", RUN+="/bin/mkdir -p /media/%k", RUN+="/bin/mount -o $env{mount_options} /dev/%k /media/%k"
 ACTION=="add", RUN+="/bin/bash /etc/udev/rules.d/sort-part.sh"
```

**[READ]** The mount options are `relatime` (plus `utf8,gid=100,umask=002` for
vfat/ntfs). **There is no `noexec` and no `nosuid`.** **[READ]** The rule does
not execute anything *from* the mounted volume; it runs
`/etc/udev/rules.d/sort-part.sh` from the rootfs. Whether that script reaches
back into the media is `init-boot.md`'s territory and I did not audit it.

Now the four reasons `jsc` is not the thing to worry about:

1. **[READ] Nothing invokes it.** §6. It is not a reachable surface. It is a
   tool that is already lying on the floor if you get in by other means.
2. **[READ] Its imports are narrow.** No `system`, `popen`, `fork`, `exec*`,
   `dlopen`, `socket`, `connect`, `unlink`. §2.1.
3. **[READ] The image already ships strictly better tools.** `bin/bash`,
   `bin/sh`, `bin/ash`, `bin/busybox`, `usr/bin/awk`, `bin/sed`, and —
   decisively — **`usr/bin/sclang`** (1,871,876 B, the SuperCollider language
   interpreter), **`usr/bin/gdb`** and **`usr/bin/strace`**.
   **[READ]** `sclang` imports `system@plt`, `fork@plt` and `execve@plt`, and
   exposes the primitive `_PipeOpen` — i.e. it has the process spawn and shell
   escape that `jsc` conspicuously lacks. Anyone who can run `jsc` can already
   run `bash`, `sclang` and `gdb`. A JavaScript interpreter with no sockets and
   no process spawn is the *least* capable thing in that list.
4. **[READ] The mount is not `noexec`,** so an attacker with physical access can
   bring their own ARM binary regardless. `jsc`'s presence saves them nothing.

**[INFERRED]** The honest characterisation: `jsc` is a **post-exploitation
convenience of negligible marginal value**, not an attack surface. The
qualification in §2.1 stands — an enabled JIT (`JSC_useJIT`, `JSC_useDFGJIT`)
means the process maps RWX memory and can execute arbitrary native code, so its
import table is not a real boundary — but that only matters once someone can
already run it, and by then they have `gdb`.

**[INFERRED]** The larger and more defensible finding is **`libQt5WebKit.so.5.5.1`**:
24.7 MB of a browser engine — **[READ]** version 5.5.1, **[READ]** byte-frozen
since at least the 2022 v1.5.0 image apart from generator reordering (§7.3), and
**[EXTERNAL, unverified here]** long past upstream end-of-life — shipping on a
networked device. It is
*currently* harmless because nothing loads it (§6). It would become a serious
liability the moment any future firmware links it — which is exactly the kind of
change nobody would flag, because the library is already "in the image."

**Recommendation, offered as opinion not finding:** `jsc` and the whole Qt5
tree are candidates for removal from the buildroot configuration. Removing them
would reclaim ~44 MiB and delete an unmaintained browser engine from a shipping
product, at zero functional cost — nothing references them (§6). This is a
build-configuration change, not a device modification, and I am not proposing
anyone touch an instrument.

---

## 9. There are three JavaScript engines in this image, not one

**[READ]**

| # | where | engine | evidence |
|---|---|---|---|
| 1 | `usr/bin/las-frontend` | JUCE `JavascriptEngine` | `js-sandbox.md` §1 (RTTI + builtin identifier table) |
| 2 | `usr/bin/jsc` | JavaScriptCore, statically linked | §1–2 above; 59 `JSC_*` options |
| 3 | `usr/lib/libQt5WebKit.so.5.5.1` | JavaScriptCore, compiled in | **59 `JSC_*` option names**, the same count as `jsc`; string `JavaScriptCore` present |

**[INFERRED]** Two independent copies of JavaScriptCore ship on disk — one in
the shell, one inside the browser engine. Neither is reachable from the running
system (§6). Engine #1 is the only one that is actually wired to anything, and
`js-sandbox.md` covers it correctly.

---

## 10. Conflicts with existing documentation

Reported, not fixed, per instruction.

1. **`docs/firmware/js-sandbox.md` §1** — *"Only `las-frontend` contains a JS
   engine. Grepping every ELF in `usr/bin`, `usr/lib`, `usr/sbin`, `bin`,
   `sbin`, `lib` for `JavascriptEngine|duk_|JerryScript|QuickJS|lua_State`
   returns `usr/bin/las-frontend` alone."*
   **The grep is accurate; the conclusion drawn from it is not.** JavaScriptCore
   matches none of those five patterns, so the search could not have found
   `usr/bin/jsc` or `libQt5WebKit.so.5.5.1`. There are three JS engines in the
   image (§9). The report's substantive findings about the JUCE engine and
   `LASScriptRunner` are unaffected — the scope statement is what is wrong.
   Suggested repair: add `JavaScriptCore|JSC_use|jsc exiting` to the pattern set
   and restate the claim as "only `las-frontend` contains a JS engine that
   anything invokes."

2. **`docs/firmware/diff-files.md`, `[UNKNOWN]` block** — *"`libQt5WebKit.so.5.5.1`
   … differs with zero string-set differences and no embedded CI path… I did not
   prove the mechanism."* §7.3 proves it: non-deterministic ordering in WebKit's
   generated string tables. The observation "zero string-set differences" was
   exactly right and is the key to the explanation — same set, different order.
   Not a contradiction; a resolution.

3. **`docs/firmware/diff-files.md`** — *"`usr/bin/scsynth`, `sclang` … Changed
   hash but only by rebuild markers; `scsynth` +16 B `[INFERRED]`."* The +16 B
   matches `jsc`'s CI-path mechanism exactly (§7.1) and I expected it to be the
   same cause, **but it is not**: **[READ]** neither the 1.5.0 nor the 1.8.2
   `scsynth` has a `DT_RUNPATH` or `DT_RPATH` at all. That inference in
   `diff-files.md` remains unproven, and the obvious explanation is now excluded.
   Flagged so it is not assumed settled.

4. **No conflict with `docs/arch/performance.md`** (lines 676–680): its finding
   that `las-frontend` has no Qt dependency is independently confirmed here (§4).

5. **No conflict with `docs/firmware/gap-x11-display-and-build-residue.md`.**
   That report covers X11 and build residue thoroughly and mentions Qt, WebKit
   and `jsc` **zero times** (verified by grep). The two reports are
   complementary: it establishes that a full X server and developer desktop
   ship unused; this one establishes that a full Qt5/WebKit stack does too. The
   Qt libraries link the same X11 stack it documents.

6. **Minor, in this assignment's own framing:** `libQt5WebKit.so.5.5.1` is the
   **third**-largest file in the rootfs, not the second — `libicudata.so.56.1`
   (25,047,800 B) is larger. And the Qt footprint is 13.2% of non-`las-frontend`
   userspace, not "about a tenth." Neither changes anything material.

---

## 11. What I did not get to

- **The registration call sites in `jsc`.** PC-relative literal loading defeated
  the pointer search (§2). Proving the twelve builtins are installed as globals
  needs a targeted disassembly of `GlobalObject::finishCreation`, located by
  walking back from the `.text` reference to the usage banner.
- **`libQt5WebKit`'s exported API surface.** I confirmed it embeds JavaScriptCore
  and identified its dependencies, but did not enumerate its symbols or check
  which WebKit features (WebSockets, XHR, plugins, local storage) are compiled
  in. Moot while nothing loads it; relevant if anything ever does.
- **`/etc/udev/rules.d/sort-part.sh`.** Read only as far as confirming the udev
  rule invokes it from the rootfs. Whether it touches attacker-controlled paths
  on the mounted volume is unexamined and belongs with the USB/boot work.
- **`usr/bin/lassvc`'s 187,578-byte same-size diff** (§7.3) — the generator-order
  hypothesis is untested against it.
- **`scsynth`'s +16 bytes** (Conflicts #3) — mechanism now unexplained.
- **`libQt5Test`, `libQt5Sql`, `libQt5Xml`, `libQt5Concurrent`, `libQt5PrintSupport`,
  `libQt5Network`** — inventoried and confirmed unreferenced, not otherwise examined.
- **The 1.5.0 Qt plugin set** — counted (12 files, same as 1.8.2) but not
  hashed file-by-file.
- **Whether `jsc` has ever executed on this or any instrument.** Not answerable
  from a filesystem image; see the validation plan.

---

## 12. Validation plan — READ-ONLY, for a human to run on the instrument

**I did not run any of these. Every command is read-only. Do not run any Moog
binary; nothing below invokes one. `jsc` itself is deliberately never executed —
its presence, not its behaviour, is what is claimed.**

Confirm the files exist and match the image:

```sh
ls -l /usr/bin/jsc /usr/lib/libQt5WebKit.so.5.5.1
md5sum /usr/bin/jsc                       # expect 68ed15ee408d3766f1b7c7039618ff6e
md5sum /usr/lib/libQt5Core.so.5.5.1       # expect 1365fdc58db90676c9fc34b847500fb6
```

Confirm real ownership and mode, which the extracted image cannot show
(everything extracted as `michaelcurtis:staff`, and **no setuid or setgid file
exists anywhere in the extraction**, so those bits are not trustworthy either):

```sh
stat -c '%A %U %G %s %n' /usr/bin/jsc /usr/lib/libQt5WebKit.so.5.5.1
find /usr/bin /usr/lib -perm /6000 -type f 2>/dev/null   # expect: nothing
```

Confirm nothing has it open or has ever mapped it — the direct test of §6:

```sh
grep -l jsc /proc/*/maps 2>/dev/null            # expect: no output
grep -l libQt5 /proc/*/maps 2>/dev/null         # expect: no output
grep -l libQt5WebKit /proc/*/maps 2>/dev/null   # expect: no output
ls -l /proc/*/exe 2>/dev/null | grep -c jsc     # expect: 0
```

Confirm the atime, which is the closest available evidence to "has this ever
run" (weak: the rootfs is mounted `relatime`, and a firmware update rewrites
timestamps — treat a recent atime as inconclusive, not as proof of execution):

```sh
stat -c '%n atime=%x mtime=%y' /usr/bin/jsc
mount | grep ' / '        # confirm relatime/noatime before trusting the above
```

Confirm the dynamic linker would resolve it, without running it:

```sh
ldd /usr/bin/jsc          # read-only; expect all 11 resolved, none from the RUNPATH
ls -d /home/las-ci-builds 2>&1   # expect: No such file or directory
```

Confirm the plugin path and that no Qt config overrides it:

```sh
ls /usr/lib/qt/plugins/platforms/    # expect exactly libqxcb.so libqminimal.so libqoffscreen.so
find / -name qt.conf -o -name '*.qml' 2>/dev/null | head   # expect: nothing
env | grep -i '^QT_'                 # expect: nothing
```

Confirm the mount options in §8:

```sh
cat /proc/mounts | grep -E '/media|/var/local/media'   # check for noexec/nosuid; expect neither
```
