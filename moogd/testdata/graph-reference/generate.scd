(
var out = ".";
var cases = [
    ["one",      { Out.ar(0, SinOsc.ar(440)) }],
    ["mul",      { Out.ar(0, SinOsc.ar(440) * 0.5) }],
    ["dupconst", { Out.ar(0, SinOsc.ar(440) * 0.5 + SinOsc.ar(440)) }],
    ["args",     { |freq = 220, amp = 0.25| Out.ar(0, SinOsc.ar(freq) * amp) }],
    ["ops",      { |a = 1, b = 2| Out.ar(0, DC.ar(a + b) + DC.ar(a - b) + DC.ar(a * b) + DC.ar(a / b)) }],
    ["order",    { var c = SinOsc.ar(100); var d = SinOsc.ar(200); Out.ar(0, d + c) }],
    ["twoout",   { Out.ar(0, Pan2.ar(SinOsc.ar(440), 0.3)) }],
    ["neg",      { Out.ar(0, SinOsc.ar(440).neg) }],
];
cases.do { |c|
    var name = c[0], fn = c[1];
    SynthDef(name.asSymbol, fn).writeDefFile(out);
    ("wrote " ++ name).postln;
};
0.exit;
)
