package main

import (
	"strings"
	"testing"
)

func blocks(t *testing.T) *Blocks {
	t.Helper()
	b := LoadBlocks()
	if b.loadE != nil {
		t.Fatalf("catalogue: %v", b.loadE)
	}
	if len(b.List()) == 0 {
		t.Fatal("catalogue is empty")
	}
	return b
}

// Every block must expand, compile, and survive the graph builder's own checks.
// A block that only fails when somebody drags it onto a chain is a block that
// fails in front of a musician.
func TestEveryBlockExpandsAndCompiles(t *testing.T) {
	b := blocks(t)
	for _, blk := range b.List() {
		t.Run(blk.ID, func(t *testing.T) {
			spec, err := b.Expand(ChainSpec{Name: "t", Steps: []ChainStep{{Block: blk.ID}}})
			if err != nil {
				t.Fatalf("expand: %v", err)
			}
			g, err := spec.Build()
			if err != nil {
				t.Fatalf("build: %v", err)
			}
			raw, err := g.Bytes()
			if err != nil {
				t.Fatalf("encode: %v", err)
			}
			defs, _, err := DecodeSynthDefs(raw)
			if err != nil {
				t.Fatalf("the encoder produced something the decoder rejects: %v", err)
			}
			if !strings.Contains(string(raw), blk.UGens[0].Name) {
				t.Errorf("compiled bytes do not name %s", blk.UGens[0].Name)
			}
			// Two channels in, limited, and replaced on the way out.
			var ins, lims, outs int
			for _, u := range defs[0].UGens {
				switch u.Name {
				case "In":
					ins++
				case "Limiter":
					lims++
				case "ReplaceOut":
					outs++
				}
			}
			if ins != 2 || lims != 2 || outs != 2 {
				t.Errorf("got %d In, %d Limiter, %d ReplaceOut; want 2 of each", ins, lims, outs)
			}
		})
	}
}

// The limiter is the last thing before the converter and is not the user's to
// remove. A chain that could reach the output unlimited is a chain that can
// damage monitors.
func TestEveryChainIsLimited(t *testing.T) {
	b := blocks(t)
	spec, err := b.Expand(ChainSpec{Name: "loud", Steps: []ChainStep{
		{Block: "gain", Params: map[string]float64{"amt": 4}},
		{Block: "delay", Params: map[string]float64{"decay": 8}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	for i, u := range spec.UGens {
		if u.Name != "ReplaceOut" {
			continue
		}
		src := u.Inputs[1]
		if src.UGen == nil || spec.UGens[*src.UGen].Name != "Limiter" {
			t.Errorf("ReplaceOut at %d is not fed by a Limiter", i)
		}
	}
}

// A mono block is applied to both channels; a stereo one sees both at once.
func TestMonoBlocksAreAppliedPerChannel(t *testing.T) {
	b := blocks(t)
	mono, err := b.Expand(ChainSpec{Name: "m", Steps: []ChainStep{{Block: "lpf"}}})
	if err != nil {
		t.Fatal(err)
	}
	n := 0
	for _, u := range mono.UGens {
		if u.Name == "LPF" {
			n++
		}
	}
	if n != 2 {
		t.Errorf("a mono block produced %d LPF, want one per channel", n)
	}
	st, err := b.Expand(ChainSpec{Name: "s", Steps: []ChainStep{{Block: "freeverb"}}})
	if err != nil {
		t.Fatal(err)
	}
	n = 0
	for _, u := range st.UGens {
		if u.Name == "FreeVerb2" {
			n++
		}
	}
	if n != 1 {
		t.Errorf("a stereo block produced %d FreeVerb2, want one", n)
	}
}

// Parameters have to become controls, or a slider would mean rebuilding the
// patch -- which clicks.
func TestBlockParamsBecomeLiveControls(t *testing.T) {
	b := blocks(t)
	spec, err := b.Expand(ChainSpec{Name: "p", Steps: []ChainStep{
		{Block: "lpf", Params: map[string]float64{"freq": 900}},
		{Block: "lpf", Params: map[string]float64{"freq": 300}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]float32{"s0_freq": 900, "s1_freq": 300}
	got := map[string]float32{}
	for _, p := range spec.Params {
		got[p.Name] = p.Default
	}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s = %v, want %v (all: %v)", k, got[k], v, got)
		}
	}
	// and the name maps back for the UI
	if s, n, ok := stepParam("s1_freq"); !ok || s != 1 || n != "freq" {
		t.Errorf("stepParam gave %d %q %v", s, n, ok)
	}
}

func TestChainRejectsBadInput(t *testing.T) {
	b := blocks(t)
	for _, c := range []struct {
		name string
		spec ChainSpec
	}{
		{"empty", ChainSpec{Name: "x"}},
		{"unknown block", ChainSpec{Name: "x", Steps: []ChainStep{{Block: "nope"}}}},
		{"param out of range", ChainSpec{Name: "x", Steps: []ChainStep{
			{Block: "lpf", Params: map[string]float64{"freq": 99999}}}}},
	} {
		if _, err := b.Expand(c.spec); err == nil {
			t.Errorf("%s was accepted", c.name)
		}
	}
	long := make([]ChainStep, 40)
	for i := range long {
		long[i] = ChainStep{Block: "gain"}
	}
	if _, err := b.Expand(ChainSpec{Name: "x", Steps: long}); err == nil {
		t.Error("a 40-block chain was accepted")
	}
}

// The name reaches a SynthDef name and a filename, so it cannot carry anything
// that is not a plain identifier.
func TestPatchNamesAreMadeSafe(t *testing.T) {
	for _, c := range []struct{ in, want string }{
		{"my patch", "mypatch"},
		{"../../etc", "etc"},
		{"", "voxChain"},
		{"9lives", "p9lives"},
		{"!!!", "voxChain"},
	} {
		if got := safeName(c.in); got != c.want {
			t.Errorf("safeName(%q) = %q, want %q", c.in, got, c.want)
		}
	}
	if got := safeName(strings.Repeat("a", 100)); len(got) != 40 {
		t.Errorf("a 100-character name became %d characters", len(got))
	}
}
