package main

// Accepting a graph over the wire, compiling it here, and running it.
//
// This is the piece the patch designer rests on. An iPad cannot run sclang, and
// the instrument's own sclang is crippled to 195 classes -- no FreeVerb2, no
// anything. So the tablet sends a description of a graph, moogd builds the
// SynthDef with graph.go (verified byte-for-byte against sclang), and loads it.
// No workstation in the path, and all 734 idle UGens become reachable.
//
// A graph that arrives over HTTP is not a graph somebody reviewed. The same
// three rules the Engine keeps apply, and one more:
//
//   - it runs at the TAIL of the root group, never in Moog's five effect slots
//   - only node ids this process allocated are ever freed
//   - it is refused if the audio core lacks headroom
//   - it may only write to buses this server is willing to have written
//
// That last rule is the new one. A curated effect is trusted because we wrote
// it; an arriving graph is not, and `Out.ar` to an arbitrary bus can overwrite
// something the instrument needs.

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// GraphInput is one input: exactly one of the three.
type GraphInput struct {
	Const *float32 `json:"const,omitempty"`
	UGen  *int     `json:"ugen,omitempty"`
	Out   int      `json:"out,omitempty"`
	Param *string  `json:"param,omitempty"`
}

// GraphUGen is one node.
type GraphUGen struct {
	Name    string       `json:"name"`
	Rate    int8         `json:"rate"`
	Special int16        `json:"special,omitempty"`
	Outputs int          `json:"outputs"`
	Inputs  []GraphInput `json:"inputs,omitempty"`
}

// GraphSpec is a whole definition as the client describes it.
type GraphSpec struct {
	Name   string      `json:"name"`
	Params []Param     `json:"params,omitempty"`
	UGens  []GraphUGen `json:"ugens"`
}

// writableBuses are the only buses an arriving graph may Out to.
//
// The main pair, and the two sub outputs beside them. Not 12 (the ADC feed
// carrying the analog voices in), not the effect send/return buses at 50-63
// that Moog's rack uses, and not the control buses the meter writes.
var writableBuses = map[float32]bool{
	MainLeftBus: true, MainRightBus: true, 1: true, 2: true, 3: true,
}

// Build turns a description into a SynthDef.
func (s GraphSpec) Build() (*Graph, error) {
	if s.Name == "" {
		return nil, fmt.Errorf("a graph needs a name")
	}
	if len(s.UGens) == 0 {
		return nil, fmt.Errorf("%s: no UGens", s.Name)
	}
	g := NewGraph(s.Name, s.Params...)
	made := make([][]Signal, 0, len(s.UGens))
	for i, u := range s.UGens {
		ins := make([]Signal, 0, len(u.Inputs))
		for j, in := range u.Inputs {
			sig, err := resolve(g, made, in)
			if err != nil {
				return nil, fmt.Errorf("%s ugen %d (%s) input %d: %w", s.Name, i, u.Name, j, err)
			}
			ins = append(ins, sig)
		}
		if u.Name == "Out" || u.Name == "ReplaceOut" || u.Name == "OffsetOut" {
			if err := checkOutBus(u, ins); err != nil {
				return nil, fmt.Errorf("%s ugen %d: %w", s.Name, i, err)
			}
		}
		made = append(made, g.AddSpecial(u.Name, u.Rate, u.Special, u.Outputs, ins...))
	}
	if _, err := g.Def(); err != nil {
		return nil, err
	}
	return g, nil
}

// checkOutBus refuses a write to a bus that is not ours to write.
//
// Only a constant bus can be checked. A bus computed at runtime could be
// anything, so it is refused outright rather than hoped about -- this is the
// one place where "we cannot tell" has to mean "no".
func checkOutBus(u GraphUGen, ins []Signal) error {
	if len(ins) == 0 {
		return fmt.Errorf("%s with no bus", u.Name)
	}
	if !ins[0].isConst {
		return fmt.Errorf("%s to a computed bus; only a literal bus can be checked, "+
			"and an unchecked one could overwrite something the instrument needs", u.Name)
	}
	if !writableBuses[ins[0].constVal] {
		return fmt.Errorf("%s to bus %g, which is not writable from here; allowed: "+
			"the main pair (7, 0) and the sub outputs (1, 2, 3)", u.Name, ins[0].constVal)
	}
	return nil
}

func resolve(g *Graph, made [][]Signal, in GraphInput) (Signal, error) {
	switch {
	case in.Const != nil:
		s := g.Const(*in.Const)
		s.isConst, s.constVal = true, *in.Const
		return s, nil
	case in.Param != nil:
		return g.ParamNamed(*in.Param), nil
	case in.UGen != nil:
		i := *in.UGen
		if i < 0 || i >= len(made) {
			return Signal{}, fmt.Errorf("refers to ugen %d, which is not an earlier one", i)
		}
		if in.Out < 0 || in.Out >= len(made[i]) {
			return Signal{}, fmt.Errorf("ugen %d has %d outputs, wanted %d",
				i, len(made[i]), in.Out)
		}
		return made[i][in.Out], nil
	}
	return Signal{}, fmt.Errorf("must be one of const, param or ugen")
}

// AddGraph compiles a described graph and runs it at the tail of the root group.
func (r *Rack) AddGraph(s GraphSpec) (*Unit, error) {
	g, err := s.Build()
	if err != nil {
		return nil, err
	}
	blob, err := g.Bytes()
	if err != nil {
		return nil, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if head := r.Headroom(); head < headroomFloor {
		return nil, fmt.Errorf("the audio core has %.0f points free and the floor is %.0f",
			head, headroomFloor)
	}
	if err := r.call(oscFloat("/d_recv", blob), true); err != nil {
		return nil, fmt.Errorf("loading %s: %w", s.Name, err)
	}
	r.ourDefs[s.Name] = true
	node := r.nextID
	r.nextID++
	args := []any{s.Name, int32(node), int32(1), int32(0)}
	params := map[string]float64{}
	for _, p := range s.Params {
		args = append(args, p.Name, p.Default)
		params[p.Name] = float64(p.Default)
	}
	if err := r.call(oscFloat("/s_new", args...), true); err != nil {
		return nil, fmt.Errorf("starting %s: %w", s.Name, err)
	}
	u := &Unit{Node: node, Effect: s.Name, Title: s.Name, Params: params}
	r.units[node] = u
	r.changed()
	return u, nil
}

func engineGraphHandler(r *Rack) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		var s GraphSpec
		if err := json.NewDecoder(req.Body).Decode(&s); err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		u, err := r.AddGraph(s)
		if err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		writeJSON(w, map[string]any{"unit": u, "headroom": r.Headroom()})
	}
}
