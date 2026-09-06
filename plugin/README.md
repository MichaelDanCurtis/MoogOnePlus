# MoogOne.clap — control surface, capture, and effect

A CLAP plugin covering all three shapes in `docs/PLUGIN.md`: DAW automation of the
instrument's effects engine, its audio captured over the network, and audio sent
**into** it, through one of its own effects, and back — so an insert on a DAW track
runs through the Moog's digital rack, the five Eventide reverbs among them.

Proven against the instrument, with the control that makes it mean something:

```
tone in    peak 0.85627 over 70400 frames, 61144 non-silent
silence in peak 0.00000 over 70400 frames,     0 non-silent
```

The second run is the same path with nothing fed in. Everything that came back in
the first had been through the instrument.

## Arming is not done here, and cannot be

The ingress ring is played by a synthdef that has to be compiled by `sclang` and
sent with `/d_recv`, which this plugin has no way to do:

```python
from moogone import ingress
armed = ingress.arm(client, effect="et_plate_1")
```

Once done, the definition lives on the instrument until `scsynth` restarts. Without
it the effect ports are silent and everything else still works.

## Building

```
cmake -B build -S . -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
```

CLAP headers are fetched at configure time rather than vendored.

## The three rules this code exists to honour

**Never send from the audio thread.** Parameter changes arrive in `process()`, go
into a lock-free queue, and a worker thread does the sending. Network I/O in an
audio callback is a dropout.

**Never burst.** The instrument's LAN and its internal voice-controller link are
two functions of one USB gadget, and an unpaced burst wedges it past the host's
ability to reset — only a power cycle recovers it. The sender paces every datagram.
See `docs/MOOG-ONE-INTERNALS.md` §8c.

**Never `/n_free` one of the instrument's effects.** It terminates `scsynth`, and
the instrument then has no audio engine at all until `/etc/init.d/S42sc restart`.
Moog create their effects once at boot and never free them, so the free path is the
part of their lifecycle their own firmware never exercises. Stop one with
`enable = 0`, which releases an envelope whose `doneAction` is *pause*. §8e.

## Addressing parameters

By `(defname, nth occurrence, control)` — **never by node id**. Node ids change
when the instrument reloads its graph, and a stored node id silently addresses
whatever took its place.
