package main

// Building a SynthDef graph without sclang.
//
// scsyndef.go proved we can read and rewrite compiled definitions byte for
// byte. This constructs one from nothing, which is a different problem and
// needs a different proof.
//
// **This does not try to match sclang's bytes, and it should not.** sclang runs
// a peephole optimiser: `a * 0.5 + b` becomes one MulAdd rather than a multiply
// and an add, and four summed signals become one Sum4. Reimplementing that
// would be a large pile of code whose only purpose is to make a diff look tidy.
// A graph built plainly is the same signal computed with a few more UGens, and
// the audio core has the headroom -- 35 points of it, measured.
//
// So the standard here is a NULL TEST, not byte equality: build a graph, build
// the same thing in sclang, render both offline, and subtract. If the residual
// is at the noise floor they compute the same signal. See graph_test.go.
//
// The rules below were read off sclang's own output rather than recalled:
//
//   - constants are deduplicated and ordered by FIRST APPEARANCE
//   - UGens appear in creation order; inputs may only reference earlier ones
//   - parameters become a single Control UGen with one output each, and it has
//     to be the first UGen, so the parameters are fixed when the graph is made
//   - a UGen's outputs all carry the UGen's own rate
//   - BinaryOpUGen's operator lives in specialIndex: + 0, - 1, * 2, / 4

import (
	"fmt"
	"math"
)

// Rates, as the format encodes them.
const (
	RateScalar  int8 = 0
	RateControl int8 = 1
	RateAudio   int8 = 2
)

// Binary operator indices, read from sclang's output.
const (
	OpAdd int16 = 0
	OpSub int16 = 1
	OpMul int16 = 2
	OpDiv int16 = 4
)

// Signal is a reference to something a UGen can read: another UGen's output,
// or a slot in the constant pool.
type Signal struct {
	ugen int32
	idx  int32

	// Set when the signal is a literal, so a caller can check what a bus
	// argument actually is. A computed bus cannot be checked, and graphapi.go
	// refuses those rather than guessing.
	isConst  bool
	constVal float32
}

// Param is one control the finished SynthDef will expose.
type Param struct {
	Name    string
	Default float32
}

// Graph accumulates UGens and constants.
type Graph struct {
	name      string
	constants []float32
	constAt   map[uint32]int32 // float bits -> index, so dedup handles -0 and NaN
	params    []Param
	ugens     []UGenSpec
	err       error
}

// NewGraph starts a definition.
//
// Parameters are fixed here rather than added later because sclang emits them
// as a single Control UGen that must come first, and inputs may only reference
// earlier UGens. Allowing a parameter to appear halfway through would mean
// renumbering every reference already made.
func NewGraph(name string, params ...Param) *Graph {
	g := &Graph{name: name, constAt: map[uint32]int32{}, params: params}
	if len(params) > 0 {
		outs := make([]int8, len(params))
		for i := range outs {
			outs[i] = RateControl
		}
		g.ugens = append(g.ugens, UGenSpec{
			Name: "Control", Rate: RateControl, SpecialIndex: 0,
			Inputs: nil, Outputs: outs,
		})
	}
	return g
}

// Const returns a reference to a constant, adding it to the pool if new.
func (g *Graph) Const(v float32) Signal {
	bits := math.Float32bits(v)
	if i, ok := g.constAt[bits]; ok {
		return Signal{ugen: -1, idx: i, isConst: true, constVal: v}
	}
	i := int32(len(g.constants))
	g.constants = append(g.constants, v)
	g.constAt[bits] = i
	return Signal{ugen: -1, idx: i, isConst: true, constVal: v}
}

// Param returns the n-th declared parameter as a signal.
func (g *Graph) Param(n int) Signal {
	if n < 0 || n >= len(g.params) {
		g.fail("parameter %d does not exist; %d were declared", n, len(g.params))
		return Signal{ugen: -1, idx: 0}
	}
	return Signal{ugen: 0, idx: int32(n)}
}

// ParamNamed returns a parameter by name.
func (g *Graph) ParamNamed(name string) Signal {
	for i, p := range g.params {
		if p.Name == name {
			return g.Param(i)
		}
	}
	g.fail("no parameter called %q", name)
	return Signal{ugen: -1, idx: 0}
}

// Add appends a UGen and returns its outputs.
func (g *Graph) Add(name string, rate int8, numOutputs int, inputs ...Signal) []Signal {
	return g.AddSpecial(name, rate, 0, numOutputs, inputs...)
}

// AddSpecial appends a UGen carrying a specialIndex -- the operator, for
// BinaryOpUGen and UnaryOpUGen.
func (g *Graph) AddSpecial(name string, rate int8, special int16, numOutputs int,
	inputs ...Signal) []Signal {
	if name == "" {
		g.fail("a UGen with no name")
		return nil
	}
	if numOutputs < 0 {
		g.fail("%s: negative output count", name)
		return nil
	}
	me := int32(len(g.ugens))
	for i, in := range inputs {
		// The format cannot express a forward reference, and scsynth will
		// happily read one and compute nonsense.
		if in.ugen >= me {
			g.fail("%s input %d refers to UGen %d, which is not earlier than %d",
				name, i, in.ugen, me)
			return nil
		}
		if in.ugen == -1 && int(in.idx) >= len(g.constants) {
			g.fail("%s input %d is constant %d, but only %d exist",
				name, i, in.idx, len(g.constants))
			return nil
		}
	}
	outs := make([]int8, numOutputs)
	for i := range outs {
		outs[i] = rate
	}
	ins := make([]UGenInput, len(inputs))
	for i, in := range inputs {
		ins[i] = UGenInput{UGenIndex: in.ugen, Index: in.idx}
	}
	g.ugens = append(g.ugens, UGenSpec{
		Name: name, Rate: rate, SpecialIndex: special, Inputs: ins, Outputs: outs,
	})
	res := make([]Signal, numOutputs)
	for i := range res {
		res[i] = Signal{ugen: me, idx: int32(i)}
	}
	return res
}

// BinOp is an arithmetic operation between two signals.
func (g *Graph) BinOp(op int16, rate int8, a, b Signal) Signal {
	out := g.AddSpecial("BinaryOpUGen", rate, op, 1, a, b)
	if len(out) == 0 {
		return Signal{ugen: -1, idx: 0}
	}
	return out[0]
}

func (g *Graph) Mul(rate int8, a, b Signal) Signal { return g.BinOp(OpMul, rate, a, b) }
func (g *Graph) AddSig(rate int8, a, b Signal) Signal {
	return g.BinOp(OpAdd, rate, a, b)
}

// Out writes signals to a bus. It has no outputs of its own.
func (g *Graph) Out(rate int8, bus Signal, chans ...Signal) {
	g.Add("Out", rate, 0, append([]Signal{bus}, chans...)...)
}

func (g *Graph) fail(format string, a ...any) {
	if g.err == nil {
		g.err = fmt.Errorf("%s: "+format, append([]any{g.name}, a...)...)
	}
}

// Def assembles the SynthDef.
func (g *Graph) Def() (SynthDef, error) {
	if g.err != nil {
		return SynthDef{}, g.err
	}
	if len(g.ugens) == 0 {
		return SynthDef{}, fmt.Errorf("%s: no UGens", g.name)
	}
	d := SynthDef{
		Name:      g.name,
		Constants: g.constants,
		UGens:     g.ugens,
	}
	for i, p := range g.params {
		d.ParamInits = append(d.ParamInits, p.Default)
		d.ParamNames = append(d.ParamNames, ParamName{Name: p.Name, Index: int32(i)})
	}
	return d, nil
}

// Bytes compiles the graph to a .scsyndef.
func (g *Graph) Bytes() ([]byte, error) {
	d, err := g.Def()
	if err != nil {
		return nil, err
	}
	return EncodeSynthDefs([]SynthDef{d})
}
