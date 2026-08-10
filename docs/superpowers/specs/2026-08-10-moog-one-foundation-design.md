# Moog One — Foundation

**Date:** 2026-08-10
**Status:** Approved, not yet implemented
**Depends on:** nothing
**Depended on by:** [FX gain-staging diagnostic](2026-08-10-moog-one-fx-gain-staging-design.md), [Per-voice pressure](2026-08-10-moog-one-per-voice-pressure-design.md)

## Context

The Moog One is a 16-voice analog polysynth with a digital control layer running Linux on an
ARMv7 system-on-module. Its onboard effects run on **SuperCollider**, and OSC is the internal
transport between the front panel, voice cards, and effects.

This matters more than it might appear. It means there is no proprietary control protocol to
reverse-engineer. SuperCollider's server command set is public and fully documented, so the
client can be written and tested before it ever contacts the hardware.

Hardware is unavailable until September 2026. Everything in this spec is designed to be built
and validated without it.

### Verified findings

From Ryan Zachry's teardown series (see Sources). **These were observed on 2021-era firmware,
around v1.2/v1.3.** The Moog One was discontinued but firmware development continued: v1.8.2
shipped in September 2025. Treat everything below as a strong starting hypothesis rather than
current fact — the recon script reads actual values instead of trusting this table.

| Item | Detail |
|---|---|
| Sound engine | `las-sc`, listens on `localhost:9300` by default |
| Frontend | `las-frontend` |
| Launch | `/etc/init.d/S42sc` starts `las-sc`, opens a `screen` session for `launch-sc-1` |
| Effects home | `/usr/share/las-fx/` |
| FX CPU notes | `/usr/share/las-fx/util/cpu.rtf` |
| Effects engine | SuperCollider |
| SSH gate | `/etc/init.d/S50dropbear` starts dropbear if `/media/thumbdrive/k` opens with bytes `\x34\x19\x05\x23` |
| Login | `root`, no password, over ethernet |
| Architecture | ARMv7, ordinary Linux userland, X11 GUI at `/etc/init.d/S43gui` |
| Memory / storage | 2GB DDR3 (H5TQ2G63FFR), 8GB eMMC (NCEMASD9-08G) |
| Voice tuning data | `/var/tuning.vxtune` |
| Frontend data | `/var/las-frontend` |
| Other binaries | `lasfwu` (firmware update), `str` (key extraction), `las-fb-config` |

The magic bytes read `23 05 1934` in hexdump — Bob Moog's birthday. There is also an
`/etc/bob.bmp` holding GPG keys.

### Assumptions to verify on contact

These are **unverified** and each has a probe defined in the recon script:

1. `las-sc` speaks stock SuperCollider server protocol (may be trimmed or extended).
2. The OSC port is 9300 on this unit's firmware.
3. The listening socket is UDP (SuperCollider's default).
4. The `k`-file access path still works on this unit's current firmware. Roughly six firmware
   releases separate Zachry's findings from v1.8.2, and the gate could have been closed in any
   of them. Mitigating this: access has been established on *this* unit before, which is
   stronger evidence than any published version number. **This is the first thing to verify in
   September — everything else is moot until it holds.**

Zachry reported that remote OSC and replayed `tcpdump` captures both failed, and speculated
about iptables filtering. A loopback-bound socket explains this without any filtering, and is
the more likely cause. The recon script confirms the bind address rather than assuming either.

## Goals

- A tested OSC/SuperCollider client that works on first contact with the hardware.
- A single recon pass that gathers what **both** downstream projects need, because the
  September hardware window is finite and a second pass is expensive.
- Audio analysis that reports numbers, validated before it is needed.
- No dependency on hardware for anything that can be avoided.

## Non-goals

- No firmware modification. Nothing here writes to `/etc`, replaces system binaries, or
  touches anything signed.
- No distribution. This is personal tooling for hardware the author owns.
- No abstraction layer over other studio gear. That is a real temptation and a bad idea until
  two or three concrete integrations exist to generalize from.

## Architecture

```
                    ┌──────────────────┐
                    │  OSC codec       │
                    │  + SC client (1) │
                    └────────┬─────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
        ┌───────▼────────┐       ┌────────▼────────┐
        │ Transport (6)  │       │ Mock scsynth(2) │
        │ udp | tunnel   │       │ (dev + test)    │
        └───────┬────────┘       └─────────────────┘
                │
        ┌───────▼────────┐   ┌─────────────┐   ┌──────────────┐
        │ Recon (3)      │   │ Analysis (4)│   │ SC harness(5)│
        └────────────────┘   └─────────────┘   └──────────────┘
```

Components 1, 2, 4 and 6 are fully buildable now. Component 3 is fully writable now and runs
in September. Component 5 is scaffolded now and finalized after recon.

## Components

### 1. OSC codec + SuperCollider client

**OSC 1.0 encoding.** Address pattern and type-tag string as null-terminated ASCII padded to
4-byte boundaries; type tags `i` (int32), `f` (float32), `s` (string), `b` (blob); bundles as
`#bundle` + 8-byte timetag + size-prefixed elements. Big-endian throughout.

**Server commands.** The client wraps these, with typed replies:

| Command | Reply | Use |
|---|---|---|
| `/status` | `/status.reply` | First probe. Confirms SC-compatibility, gives CPU and sample rate. |
| `/g_queryTree` | `/g_queryTree.reply` | Full live node graph with control names and values. |
| `/dumpOSC` | — | Server logs every received message. Recon's most valuable single call. |
| `/n_set` | — | Set controls on a live node. |
| `/n_query` | `/n_info` | Inspect one node. |
| `/s_new` | — | Instantiate a synth. |
| `/d_recv` | `/done` | Load a SynthDef at runtime. |
| `/sync` | `/synced` | Barrier for async completion. |
| `/notify` | `/done` | Subscribe to node lifecycle notifications. |

Errors arrive as `/fail` with the offending command and a message. The client surfaces these
as raised errors rather than swallowing them — a silent no-op during recon would be worse
than a crash.

**Testing.** Codec round-trip tests against byte fixtures taken from the OSC spec. Client
tests against the mock (component 2). No hardware.

### 2. Mock scsynth

A local process answering enough of the protocol to develop against:

- `/status` → plausible `/status.reply`
- `/g_queryTree` → a synthetic node tree with named controls, shaped like a plausible FX chain
- `/n_set` → mutates mock state, observable by re-querying
- `/d_recv` → `/done`
- `/dumpOSC` → echoes received messages to a log the tests can read
- `/sync` → `/synced`
- Unknown commands → `/fail`, so the client's error path is exercised

**This is the linchpin of the four-week plan.** Without it the client is untested speculation;
with it the whole stack reaches green before hardware exists. It also encodes our assumptions
explicitly, which means September's first surprise is a *test failure* rather than a mystery.

### 3. Recon script

POSIX shell, no bashisms, no assumed interpreter beyond busybox. Runs on the Moog One, writes
an artifact bundle to a directory we then copy off. Two modes, hard-separated:

**Passive (default).** Read-only. Nothing that changes device state.

- OS, kernel, arch, firmware version markers
- Process table; init scripts under `/etc/init.d/`
- Listening sockets with bind addresses and protocol — resolves the UDP/TCP and
  loopback questions in one shot
- Full `/usr/share/las-fx/` tree with file sizes and types; `launch-sc-1` verbatim;
  `util/cpu.rtf`
- Any `.scsyndef` / `.sc` / `.scd` files, located and inventoried
- ALSA topology: `aconnect -l`, `/proc/asound/`, card and device list — this is the S88 path
- USB host controller state and whether class-compliant MIDI enumerates
- Presence of `socat`, `python`, `perl`, `screen`, `tcpdump`
- Free space on `/` and writable locations for our own files

**Active (explicit opt-in).** Sends OSC. Asks before each class of probe.

- `/status` — the compatibility check, first and cheapest
- `/g_queryTree` on the root group — full node graph snapshot
- `/dumpOSC 1`, then a prompt to move front-panel FX knobs, then `/dumpOSC 0` and capture the
  screen session log

That last capture is the highest-value artifact in the entire project. It hands us Moog's
actual OSC namespace by observation instead of guesswork, and it serves both downstream specs
at once.

### 4. Measurement / analysis rig

WAV in; noise floor (dBFS RMS and A-weighted), SNR, peak, and a spectrum showing *where* the
noise sits. Runs on the Mac.

**Validated now** against synthetic WAVs with known noise injected at known levels — if the
rig reports −60 dBFS for a file we built with a −60 dBFS floor, it is trustworthy. This
removes all analysis uncertainty from September, when the only question should be what the
synth is doing.

### 5. SuperCollider test harness

A SynthDef that generates a test tone *inside* SC, routes it through the target FX chain, and
records to a file on the box. The signal never passes through the ADC, which is precisely what
makes it diagnostic — see the FX spec for why.

Scaffolded against the mock now. Final wiring needs the real SynthDef structure and bus layout,
which only recon can supply. This is the one component that is deliberately incomplete until
September, and that is a consequence of the problem rather than a gap in planning.

### 6. Transport

One interface, two backends.

**`udp` (primary).** Direct UDP to `localhost:9300`, used when running on the box. This is the
per-voice pressure project's only viable path and the cleanest path for FX work.

**`tunnel` (development convenience).** `ssh -L` forwards **TCP**, while scsynth listens on
**UDP**. A plain `-L` forward therefore carries nothing. A working tunnel needs a `socat`
UDP↔TCP bridge at both ends, which requires `socat` on the device — recon checks. If it is
absent, we run on-box and lose nothing that matters.

The runtime for any on-box code is deliberately undecided. Recon reports what is installed;
we choose afterward. Committing now would be guessing.

## Testing strategy

| Component | How it is proven |
|---|---|
| OSC codec | Byte-level round-trip against spec fixtures |
| SC client | Integration against the mock, including `/fail` paths |
| Mock | Unit tests on its own state transitions |
| Recon | Shellcheck; dry run against a local Linux container |
| Analysis | Synthetic WAVs with known, injected noise floors |
| Harness | Structure tested against mock; behavior deferred to hardware |
| Transport | UDP against mock; tunnel path tested against a local socat bridge |

The standard for "done" in August is: the full stack runs green against the mock, and the
recon script executes cleanly against a container. Nothing claims hardware validation until
hardware validates it.

## Risks

| Risk | Blocks | Mitigation |
|---|---|---|
| **`k`-file access closed by a firmware update** | **Everything** | Do not update firmware. Development continued past discontinuation (v1.8.2, Sept 2025), so this is a live risk rather than a theoretical one. Access has worked on this unit before. |
| `las-sc` is not stock scsynth | Both projects | `/status` is the first and cheapest probe; a trimmed command set shows up immediately |
| Port is not 9300 | Both projects | Recon reads `launch-sc-1` rather than assuming |
| Socket is TCP, not UDP | Transport choice | Recon reports the bind; transport supports both |
| `socat` absent | Tunnel only | Run on-box; never blocks real work |
| Insufficient free space for our files | On-box code | Recon reports free space; fall back to running from a thumbdrive |

## Hardware-blocked items

Explicitly deferred to September, and not to be guessed at before then:

- Actual OSC namespace used by Moog's own components
- Whether voice cards are individually addressable
- SynthDef internal structure and available control names
- Whether the USB host enumerates a class-compliant MIDI controller
- Real measurements of anything

## Sources

- [Moog One — Initial Findings](https://www.ryanzachry.com/2021/09/07/moog-one-initial-findings.html)
- [Moog One — SSH Access](https://www.ryanzachry.com/2021/09/05/moog-one-ssh.html)
- [Moog One — A Look Inside](https://www.ryanzachry.com/2020/05/01/moog-one-inside.html)
- [Moog One — Doom](https://ryanzachry.com/2021/09/06/moog-one-doom.html)
- [SuperCollider Server Command Reference](https://doc.sccode.org/Reference/Server-Command-Reference.html)
