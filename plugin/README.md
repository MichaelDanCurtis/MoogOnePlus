# MoogOne.clap — the control surface

A CLAP plugin that exposes the instrument's effects engine as DAW-automatable
parameters. First of the three shapes in `docs/PLUGIN.md`, and deliberately the one
with **no audio path**: no clock drift to solve and no real-time audio risk, which
makes it the right place to prove the OSC path, the parameter map and — above all —
the pacing interlock under a real host.

## Building

```
cmake -B build -S . -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
```

CLAP headers are fetched at configure time rather than vendored.

## The two rules this code exists to honour

**Never send from the audio thread.** Parameter changes arrive in `process()`, go
into a lock-free queue, and a worker thread does the sending. Network I/O in an
audio callback is a dropout.

**Never burst.** The instrument's LAN and its internal voice-controller link are
two functions of one USB gadget, and an unpaced burst wedges it past the host's
ability to reset — only a power cycle recovers it. The sender paces every datagram.
See `docs/MOOG-ONE-INTERNALS.md` §8c.

## Addressing parameters

By `(defname, nth occurrence, control)` — **never by node id**. Node ids change
when the instrument reloads its graph, and a stored node id silently addresses
whatever took its place.
