package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// Graphs built here, and the same graphs written in SuperCollider and compiled
// by a real sclang. testdata/graph-reference/generate.scd produces the .scsyndef
// files; the source of each is quoted beside the builder call.
//
// Six of these must match sclang BYTE FOR BYTE. Two must not, and that is the
// point of including them: sclang runs a peephole optimiser -- `a * 0.5 + b`
// folds to one MulAdd, four summed signals fold to one Sum4 -- and this builder
// deliberately does not reimplement it. The unfolded graph computes the same
// signal with a few more UGens. Asserting the difference keeps that a decision
// rather than a surprise.
const refDir = "testdata/graph-reference"

func reference(t *testing.T, name string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(refDir, name+".scsyndef"))
	if err != nil {
		t.Skipf("no reference for %s: %v", name, err)
	}
	return b
}

func mustBytes(t *testing.T, g *Graph) []byte {
	t.Helper()
	b, err := g.Bytes()
	if err != nil {
		t.Fatalf("building %s: %v", g.name, err)
	}
	return b
}

// { Out.ar(0, SinOsc.ar(440)) }
func buildOne() *Graph {
	g := NewGraph("one")
	sin := g.Add("SinOsc", RateAudio, 1, g.Const(440), g.Const(0))
	g.Out(RateAudio, g.Const(0), sin[0])
	return g
}

// { Out.ar(0, SinOsc.ar(440) * 0.5) }
func buildMul() *Graph {
	g := NewGraph("mul")
	sin := g.Add("SinOsc", RateAudio, 1, g.Const(440), g.Const(0))
	out := g.Mul(RateAudio, sin[0], g.Const(0.5))
	g.Out(RateAudio, g.Const(0), out)
	return g
}

// { var c = SinOsc.ar(100); var d = SinOsc.ar(200); Out.ar(0, d + c) }
func buildOrder() *Graph {
	g := NewGraph("order")
	c := g.Add("SinOsc", RateAudio, 1, g.Const(100), g.Const(0))
	d := g.Add("SinOsc", RateAudio, 1, g.Const(200), g.Const(0))
	g.Out(RateAudio, g.Const(0), g.AddSig(RateAudio, d[0], c[0]))
	return g
}

// { Out.ar(0, SinOsc.ar(440).neg) }
func buildNeg() *Graph {
	g := NewGraph("neg")
	sin := g.Add("SinOsc", RateAudio, 1, g.Const(440), g.Const(0))
	neg := g.AddSpecial("UnaryOpUGen", RateAudio, 0, 1, sin[0])
	g.Out(RateAudio, g.Const(0), neg[0])
	return g
}

// { Out.ar(0, Pan2.ar(SinOsc.ar(440), 0.3)) }
func buildTwoOut() *Graph {
	g := NewGraph("twoout")
	sin := g.Add("SinOsc", RateAudio, 1, g.Const(440), g.Const(0))
	pan := g.Add("Pan2", RateAudio, 2, sin[0], g.Const(0.3), g.Const(1))
	g.Out(RateAudio, g.Const(0), pan[0], pan[1])
	return g
}

// { |freq = 220, amp = 0.25| Out.ar(0, SinOsc.ar(freq) * amp) }
func buildArgs() *Graph {
	g := NewGraph("args", Param{"freq", 220}, Param{"amp", 0.25})
	sin := g.Add("SinOsc", RateAudio, 1, g.ParamNamed("freq"), g.Const(0))
	out := g.Mul(RateAudio, sin[0], g.ParamNamed("amp"))
	g.Out(RateAudio, g.Const(0), out)
	return g
}

// The real test: what this builds is what sclang builds, to the byte.
func TestBuiltGraphsMatchSclangExactly(t *testing.T) {
	for _, c := range []struct {
		name  string
		build func() *Graph
	}{
		{"one", buildOne},
		{"mul", buildMul},
		{"order", buildOrder},
		{"neg", buildNeg},
		{"twoout", buildTwoOut},
		{"args", buildArgs},
	} {
		t.Run(c.name, func(t *testing.T) {
			want := reference(t, c.name)
			got := mustBytes(t, c.build())
			if !bytes.Equal(want, got) {
				at := -1
				for i := 0; i < len(want) && i < len(got); i++ {
					if want[i] != got[i] {
						at = i
						break
					}
				}
				t.Errorf("differs from sclang: %d bytes want, %d got, first at %d\n"+
					"want %x\n got %x", len(want), len(got), at, want, got)
			}
		})
	}
}

// Anything this builds must survive its own decoder, and every reference it is
// checked against must too.
func TestBuiltGraphsDecodeAndRoundTrip(t *testing.T) {
	for _, build := range []func() *Graph{
		buildOne, buildMul, buildOrder, buildNeg, buildTwoOut, buildArgs,
	} {
		g := build()
		raw := mustBytes(t, g)
		defs, version, err := DecodeSynthDefs(raw)
		if err != nil {
			t.Fatalf("%s: %v", g.name, err)
		}
		if version != 2 || len(defs) != 1 || defs[0].Name != g.name {
			t.Fatalf("%s: decoded to %d defs, version %d", g.name, len(defs), version)
		}
		back, err := EncodeSynthDefs(defs)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(raw, back) {
			t.Errorf("%s did not round-trip through its own codec", g.name)
		}
	}
}

// A forward reference cannot be expressed in the format, and scsynth will read
// one without complaint and compute nonsense. It has to be refused here.
func TestGraphRefusesAForwardReference(t *testing.T) {
	g := NewGraph("bad")
	future := Signal{ugen: 5, idx: 0}
	g.Add("SinOsc", RateAudio, 1, future, g.Const(0))
	if _, err := g.Bytes(); err == nil {
		t.Error("a reference to a later UGen was accepted")
	}
}

func TestGraphRefusesAnUnknownParameter(t *testing.T) {
	g := NewGraph("bad", Param{"freq", 100})
	g.ParamNamed("nope")
	if _, err := g.Bytes(); err == nil {
		t.Error("an undeclared parameter was accepted")
	}
}

// Constants are pooled by value, in order of first appearance -- sclang's rule,
// and the reason `one` has two constants rather than three.
func TestConstantsAreDeduplicatedInFirstAppearanceOrder(t *testing.T) {
	g := NewGraph("c")
	a, b, c := g.Const(440), g.Const(0), g.Const(440)
	if a != c {
		t.Error("the same value produced two constants")
	}
	if b.idx != 1 {
		t.Errorf("second distinct constant landed at %d, want 1", b.idx)
	}
	def, err := g.Def()
	if err == nil && len(def.Constants) != 2 {
		t.Errorf("pool holds %v, want two entries", def.Constants)
	}
}

// The optimiser this deliberately does not have. If a future change starts
// folding, these will fail and the decision should be revisited on purpose.
func TestSclangFoldsWhereThisDoesNot(t *testing.T) {
	for _, name := range []string{"dupconst", "ops"} {
		raw := reference(t, name)
		defs, _, err := DecodeSynthDefs(raw)
		if err != nil {
			t.Fatal(err)
		}
		var folded bool
		for _, u := range defs[0].UGens {
			if u.Name == "MulAdd" || u.Name == "Sum3" || u.Name == "Sum4" {
				folded = true
			}
		}
		if !folded {
			t.Errorf("%s was expected to contain a folded UGen; sclang's optimiser "+
				"may have changed, and the note in graph.go with it", name)
		}
	}
}

// -- graphs arriving over the wire ---------------------------------------------

func TestGraphSpecRefusesAnUnwritableBus(t *testing.T) {
	bus := func(v float32) *float32 { return &v }
	for _, b := range []float32{12, 50, 60, 100, 14000, 128} {
		s := GraphSpec{Name: "t", UGens: []GraphUGen{
			{Name: "DC", Rate: RateAudio, Outputs: 1,
				Inputs: []GraphInput{{Const: bus(0.1)}}},
			{Name: "Out", Rate: RateAudio, Outputs: 0,
				Inputs: []GraphInput{{Const: bus(b)}, {UGen: intp(0)}}},
		}}
		if _, err := s.Build(); err == nil {
			t.Errorf("Out to bus %g was allowed", b)
		}
	}
	// and the main pair is allowed
	s := GraphSpec{Name: "t", UGens: []GraphUGen{
		{Name: "DC", Rate: RateAudio, Outputs: 1, Inputs: []GraphInput{{Const: bus(0.1)}}},
		{Name: "Out", Rate: RateAudio, Outputs: 0,
			Inputs: []GraphInput{{Const: bus(MainLeftBus)}, {UGen: intp(0)}}},
	}}
	if _, err := s.Build(); err != nil {
		t.Errorf("Out to the main pair was refused: %v", err)
	}
}

// A bus computed at runtime cannot be checked, so it must be refused rather
// than hoped about.
func TestGraphSpecRefusesAComputedBus(t *testing.T) {
	v := func(f float32) *float32 { return &f }
	s := GraphSpec{Name: "t", Params: []Param{{"bus", 7}}, UGens: []GraphUGen{
		{Name: "DC", Rate: RateAudio, Outputs: 1, Inputs: []GraphInput{{Const: v(0.1)}}},
		{Name: "Out", Rate: RateAudio, Outputs: 0,
			Inputs: []GraphInput{{Param: strp("bus")}, {UGen: intp(0)}}},
	}}
	if _, err := s.Build(); err == nil {
		t.Error("Out to a parameter-controlled bus was allowed")
	}
}

func TestGraphSpecRejectsMalformedInputs(t *testing.T) {
	for _, c := range []struct {
		name string
		spec GraphSpec
	}{
		{"no name", GraphSpec{UGens: []GraphUGen{{Name: "DC", Outputs: 1}}}},
		{"no ugens", GraphSpec{Name: "t"}},
		{"empty input", GraphSpec{Name: "t", UGens: []GraphUGen{
			{Name: "DC", Rate: RateAudio, Outputs: 1, Inputs: []GraphInput{{}}}}}},
		{"forward ref", GraphSpec{Name: "t", UGens: []GraphUGen{
			{Name: "DC", Rate: RateAudio, Outputs: 1, Inputs: []GraphInput{{UGen: intp(3)}}}}}},
		{"bad output", GraphSpec{Name: "t", UGens: []GraphUGen{
			{Name: "DC", Rate: RateAudio, Outputs: 1, Inputs: []GraphInput{{Const: f32p(1)}}},
			{Name: "DC", Rate: RateAudio, Outputs: 1,
				Inputs: []GraphInput{{UGen: intp(0), Out: 4}}}}}},
	} {
		if _, err := c.spec.Build(); err == nil {
			t.Errorf("%s was accepted", c.name)
		}
	}
}

func intp(i int) *int         { return &i }
func strp(s string) *string   { return &s }
func f32p(f float32) *float32 { return &f }
