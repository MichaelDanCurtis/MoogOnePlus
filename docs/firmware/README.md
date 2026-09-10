# The decrypted firmware, documented

Eighteen reports over the **decrypted v1.8.2 root filesystem** — the first time
this project has been able to read Moog's shipping firmware as plain files — each
cross-checked against the owner's own **v1.5.0** filesystem.

20,069 lines. Every claim in every report is graded `[READ]` (quoted from a file,
with offset or line), `[INFERRED]` (reasoning, with its evidence named), or
`[UNKNOWN]`. No agent contacted the instrument.

## Read this before you trust a number in here

The documentation pass finished. **The adversarial verification pass did not.**

208 of 381 agents died partway through on an account rate limit. The workflow
reported "91 claims survived, 29 refuted", and **the 91 is not a clean bill of
health** — a claim whose three verifiers all failed to run scores zero votes
against it and lands in the "survived" bucket looking identical to one that was
checked and held. Treat "survived" as *unexamined*.

**The 29 refutations are real**, and they are the most valuable output here. The
gap-finding critics and this index's automated version never ran at all.

To finish it (agents replay from cache, only the failed ones re-run):

    Workflow({
      scriptPath: "…/workflows/scripts/moog-firmware-exhaustive-wf_1bf488f8-f48.js",
      resumeFromRunId: "wf_1bf488f8-f48"
    })

## The reports

### The subsystems

| report | region |
|---|---|
| [`lassvc.md`](lassvc.md) | **The 3.4 MB binary nobody had ever opened.** Service-mode tool: `/cal`, `/info`, `/fw`, `/hw`, `/mix`, `/testosc` — a hardware bring-up plane, and identity writes for serial/MAC/UUID |
| [`las-sc-namespace.md`](las-sc-namespace.md) | The complete OSC surface and dispatch, including what `/p/pre-expr` and `/p/post-expr` really want |
| [`las-frontend-ui.md`](las-frontend-ui.md) | UI architecture, the panel map, and where an edited mod-matrix row actually goes |
| [`las-frontend-data.md`](las-frontend-data.md) | Preset storage, the SQLite schema, the 580 embedded `.m1p` resources, `/p/version` migration |
| [`las-fx.md`](las-fx.md) | The SuperCollider engine: SynthDefs, bus map, the effect rack, the LADSPA set |
| [`init-boot.md`](init-boot.md) | The boot sequence, the A/B partition scheme, the updater, the watchdog, the shutdown path |
| [`kernel.md`](kernel.md) | Kernel, modules, device tree, ALSA and the ESAI/TDM path, CPU isolation, thermal |
| [`network.md`](network.md) | Every listening service, dropbear and the `k`-file root hook, avahi, the two DHCP clients |
| [`xmos.md`](xmos.md) | The voice-controller images and the `xmosfw` metadata never harvested before |
| [`calibration.md`](calibration.md) | The `/cal` namespace, the seventeen calibrations, `vxcal.db`, `tuning.vxtune` |
| [`small-binaries.md`](small-binaries.md) | Ten helpers never read: watchdog, dwm, fb-config, frontpanel-poll, `las_clock_demo`, `config-las-spi`, `flashbench`, `psplash`, `str`, `lasfwu` |
| [`presets-content.md`](presets-content.md) | The factory library as shipped, on-device vs the download |
| [`audio-io.md`](audio-io.md) | The audio path and the physical back panel as the firmware understands it |
| [`js-sandbox.md`](js-sandbox.md) | Verifying the prior claim that `las-frontend` embeds a JS sandbox with a calibration-write API |

### The 1.5.0 → 1.8.2 diffs

| report | question |
|---|---|
| [`diff-files.md`](diff-files.md) | What files changed, grouped by subsystem |
| [`diff-binaries.md`](diff-binaries.md) | Symbol- and string-level changes in `las-sc`, `las-frontend`, `lassvc`, `las-watchdog` |
| [`diff-osc.md`](diff-osc.md) | Which OSC addresses were added, removed, renamed |
| [`diff-upgrade.md`](diff-upgrade.md) | **Should the owner install 1.8.2?** Gained, risked, irreversible |

## What the refutations caught

The verifiers overturned real errors, and the pattern is instructive — every one
is a survey agent over-reaching from a name or a string:

- **"`lassvc` is the only Linux-side voice-card firmware flasher."** Wrong.
  `vxfw` is a shared CHICKEN library statically linked into at least five
  binaries. `lassvc` links it but has **no call site**. The live call sites are
  in **`las-sc`** (`sc/sc.scm:659` and `:708`) — the process that runs at boot.
- **"`lassvc`'s namespace is wholly disjoint from `las-sc`'s."** Wrong twice: the
  offered evidence ("none begin with `/p`") is false — `/p1/d`, `/p2/d`,
  `/p3/d`, `/ping` all do — and **155 of `lassvc`'s 245 address literals are
  byte-identical to ones in `las-sc`**. They are two clients of the *same*
  hardware plane; `las-sc` additionally serves `/p` on top of it.
- **"A phone-home would expose passwordless root."** Wrong, and worth knowing
  precisely: `lassvc` starts dropbear with `-R` via a direct `exec` that never
  reads `/etc/default/dropbear`, and under `-R` alone an empty root password is a
  **lockout, not a bypass** — the blank-password path is gated on a flag only
  `-B` sets.
- **`/info/write` and `/info/protect` graded `[READ]`.** Downgraded to
  `[INFERRED]`: the strings exist, but there is no handler symbol and no evidence
  the identity menu items invoke them.
- **"`lassvc` always runs inside an `xterm`."** It needs a controlling terminal,
  not X — `llvm-objdump -p` shows zero `libX11`. Any root shell can invoke it.

## Still open

- **`/p/pre-expr` / `/p/post-expr`.** Sent live with an OSC string; `las-sc`
  received it, survived, and forwarded nothing. `las-sc-namespace.md` should
  settle whether that is syntax, a missing voice selector, deferred compilation,
  or dead code — but the claim is unverified until the resume runs.
- **Where an edited mod-matrix row goes.** Not on 9300, not on the XMOS link
  outside the housekeeping channels. `las-frontend-ui.md` has the reading.
- **The gap sweep.** Never ran. Nobody has asked what these fourteen lanes missed.

## Provenance

The v1.8.2 filesystem was obtained by decrypting the official update package with
the key Moog ships on every instrument (`/etc/bob.bmp`, 4-bit LSB steganography,
passphrase `bob`, per `lasfwu`). It is Moog's copyrighted firmware: it lives under
`captures/`, which is gitignored, and it does not leave this machine.
