# Building a JACK-capable `scsynth` for the Moog One

The instrument's own `scsynth` is an **ALSA-only build**: `SC_AlsaDriver` is in it and
`SC_JackDriver` appears zero times. `SC_AlsaDriver` does not exist in upstream
SuperCollider at all — upstream offers `{default, coreaudio, jack, portaudio}` and
defaults to JACK on Linux — so Moog wrote or ported that driver themselves, presumably
to avoid running a `jackd` daemon.

That single choice is what pins the whole instrument to one core. `scsynth` is
single-threaded for DSP and is pinned to cpu0 (`affinity mask: 1`), while cpu1 sits
near idle. Two `scsynth` processes cannot share the card — one subdevice, already
held, `RW_INTERLEAVED` rather than `MMAP`, and no `dmix` plugin installed — so
without JACK there is no way to reach the second core.

**`jackd` is already on the device and works.** `jackdmp 1.9.12` takes the card at
48000/256/2 in realtime mode, negotiates 24-bit both directions to match it, publishes
all 8+8 ports, and runs with zero xruns. See `docs/MOOG-ONE-INTERNALS.md`.

So the only missing piece is a `scsynth` that can talk to it. This builds one.

    bash tools/build-scsynth-jack.sh          # inside the container below

    docker run --rm --platform linux/arm/v7 \
      -v "$PWD":/w -w /w debian:jessie bash /w/build-scsynth-jack.sh

## Why each choice is what it is

Every one of these was a failure first.

**Debian jessie**, not anything newer. The device is glibc **2.21**; jessie is 2.19,
and a binary built against a newer glibc will not load. Bullseye (2.31) is both too
new and now EOL — its security release file expired and `apt` refuses to run.

**All three suites in `sources.list`.** With only `jessie main`, `apt` cannot resolve
even `bzip2` and every install fails with "is not going to be installed", because the
base image's own packages come from updates and security.

**`trusted=yes`.** The archive signing key expired in 2020.

**`gcc-4.8`, not the default 4.9.** This is the one that would have bitten on the
instrument rather than in the container. gcc 4.9 emits `GLIBCXX_3.4.20`; the device's
`libstdc++.so.6` stops at **3.4.19**, so the binary loads fine in the build container
and fails on the target. Moog's own `scsynth` requires `GLIBCXX ≤ 3.4.19` and
`GLIBC ≤ 2.9` — check any new build against those two numbers before copying it over.

**Submodules over https.** `.gitmodules` uses `git://`, which GitHub disabled in 2022.
Only `nova-simd` and `nova-tt` are needed for `scsynth`; `hidapi` and `yaml-cpp` are
needed to configure, and `portaudio` is not needed at all with `AUDIOAPI=jack`.

**`libx11-dev`.** `server/plugins` wants X11 for `MouseX`/`KeyState` even though only
the `scsynth` target is being built.

## Verifying a build before it goes near the instrument

    objdump -T scsynth | grep -o 'GLIBC_[0-9.]*'   | sort -uV | tail -1   # must be <= 2.21
    objdump -T scsynth | grep -o 'GLIBCXX_[0-9.]*' | sort -uV | tail -1   # must be <= 3.4.19
    strings scsynth | grep -c SC_JackDriver                               # must be > 0
    objdump -p scsynth | grep NEEDED                                      # libjack.so.0 present

## Installing

**Alongside, never over.** The shipped binary is the instrument's only audio engine;
replacing it turns a build mistake into a synth that makes no sound.

    ssh root@<ip> 'cat > /var/scsynth-jack && chmod +x /var/scsynth-jack' < scsynth
    ssh root@<ip> '/var/scsynth-jack -v'      # loads and links, touches no device

`/var` is a separate partition with room, and removing the file undoes everything.
There is no `sftp-server` on the device, so `scp` does not work — pipe through `cat`.

## Status

Built and confirmed loading on the instrument: `scsynth 3.9.0`, ABI matching the
shipped binary. **Not yet run against `jackd`** — that needs the audio stack stopped
so the card is free, and is the next step.
