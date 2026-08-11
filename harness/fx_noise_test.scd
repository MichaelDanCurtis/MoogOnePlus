// Moog One FX noise probe — generated, do not edit by hand.
//
// Signal path: tone -> moog_fx_reverb -> recorder, all inside SuperCollider.
// The tone is generated IN-BOX and routed THROUGH moog_fx_reverb before it is
// recorded -- the signal never touches the ADC, which is what makes this
// diagnostic decisive (see harness/README.md). Hissy probe recording ->
// noise is DSP-side and fixable. Clean probe recording but hissy real
// playing -> noise enters at the converters, a hardware ceiling.
//
// Node order below is EXPLICIT (tone -> Synth.after -> fx -> Synth.after ->
// rec), not incidental, because SuperCollider synths execute once per audio
// block in their group's node order, and a node that READS a bus must run
// AFTER the node that WROTE it in that same block, or it reads stale or
// silent data. Creation order alone would not guarantee this: Synth.new's
// default addAction is \addToHead, which puts each newly-created synth
// AHEAD of the ones already running -- the opposite of tone-then-fx-then-
// record. Synth.after(target, ...) sidesteps that default entirely by
// naming the dependency directly.
//
// Paste into the running sclang session, or feed it via the screen session.

(
SynthDef(\moog_probe_tone, { |out = 0, freq = 1000.0, amp = 0.5|
    Out.ar(out, SinOsc.ar(freq) * amp ! 2);
}).add;

SynthDef(\moog_probe_record, { |in = 0, bufnum = 0|
    DiskOut.ar(bufnum, In.ar(in, 2));
}).add;
);

(
~toneBus  = Bus.audio(s, 2);   // tone's output -- fx's input
~probeBus = Bus.audio(s, 2);   // fx's output -- the signal actually probed
~buf = Buffer.alloc(s, 65536, 2);
~buf.write("/tmp/probe.wav", "wav", "float", 0, 0, true);

~tone = Synth(\moog_probe_tone, [\out, ~toneBus]);

// TODO-ON-HARDWARE: this fx instantiation is complete in structure and
// wrong only in these specific, narrow values -- fill them in from the
// recon /g_queryTree capture, nothing else in this file should need to
// change:
//   1. \in / \out below are PLACEHOLDER control names. moog_fx_reverb may not
//      call its audio ports "in"/"out" at all -- use its real control
//      names from the query-tree capture.
//   2. Confirm a freshly-instantiated moog_fx_reverb behaves like the instance
//      already running in Moog's own signal chain. If the effect depends
//      on a fixed bus wired in by firmware rather than a control arg,
//      delete this instantiation and route ~toneBus into the ALREADY
//      RUNNING node's real node ID instead (e.g. via /n_map).
~fx = Synth.after(~tone, \moog_fx_reverb, [\in, ~toneBus, \out, ~probeBus]);

~rec  = Synth.after(~fx, \moog_probe_record, [\in, ~probeBus, \bufnum, ~buf]);

{
    5.0.wait;
    ~rec.free; ~fx.free; ~tone.free;
    ~buf.close; ~buf.free; ~toneBus.free; ~probeBus.free;
    "probe written to /tmp/probe.wav".postln;
}.fork;
);
