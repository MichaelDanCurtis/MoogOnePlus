package main

// The patch designer's model: a signal chain.
//
// A node-graph editor is the obvious thing to build and the wrong thing to use.
// Drag-to-connect is fiddly on glass -- the same argument that kept it out of
// the matrix editor -- and an arbitrary graph can be wired into nonsense. A
// CHAIN cannot: it is ordered by construction, so there are no forward
// references and no unconnected inputs, and it is how a musician already thinks
// about a signal path.
//
// The expansion lives HERE rather than in the page, so the safety rules have
// one home. The tablet sends a list of block ids and parameter values; it
// cannot describe anything this file does not understand. /api/engine/graph is
// still there for arbitrary graphs, with its own bus checks.
//
// What a chain becomes:
//
//	In.ar(7) ─┐                                        ┌─ Limiter ─ ReplaceOut(7)
//	          ├─ block ─ block ─ block ─ ... ──────────┤
//	In.ar(0) ─┘                                        └─ Limiter ─ ReplaceOut(0)
//
// The limiter is not optional and is not exposed. A user-built chain can be
// pathological -- a delay with a long decay is one slider away from building
// without bound -- and the last thing before the converter should not be
// something somebody typed.

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
)

//go:embed chain/blocks.json
var blocksJSON []byte

// BlockInput is one input inside a block template.
type BlockInput struct {
	In    *int     `json:"in,omitempty"`    // the chain signal: 0 left, 1 right
	Param *string  `json:"param,omitempty"` // this block's own parameter
	UGen  *int     `json:"ugen,omitempty"`  // an earlier UGen within this block
	Out   int      `json:"out,omitempty"`
	Const *float32 `json:"const,omitempty"`
}

// BlockUGen is one UGen in a block template.
type BlockUGen struct {
	Name    string       `json:"name"`
	Rate    int8         `json:"rate"`
	Special int16        `json:"special,omitempty"`
	Outputs int          `json:"outputs"`
	Inputs  []BlockInput `json:"inputs"`
}

// Block is one thing you can put in a chain.
type Block struct {
	ID     string        `json:"id"`
	Title  string        `json:"title"`
	Blurb  string        `json:"blurb"`
	Cost   string        `json:"cost"`
	Stereo bool          `json:"stereo"`
	Params []EffectParam `json:"params"`
	UGens  []BlockUGen   `json:"ugens"`
}

type blockFile struct {
	Blocks []Block `json:"blocks"`
}

// ChainStep is one block as the client places it.
type ChainStep struct {
	Block  string             `json:"block"`
	Params map[string]float64 `json:"params,omitempty"`
}

// ChainSpec is a whole patch.
type ChainSpec struct {
	Name  string      `json:"name"`
	Steps []ChainStep `json:"steps"`
}

// Blocks is the loaded catalogue.
type Blocks struct {
	all   []Block
	byID  map[string]*Block
	loadE error
}

func LoadBlocks() *Blocks {
	var bf blockFile
	b := &Blocks{byID: map[string]*Block{}}
	if err := json.Unmarshal(blocksJSON, &bf); err != nil {
		b.loadE = err
		return b
	}
	b.all = bf.Blocks
	for i := range b.all {
		b.byID[b.all[i].ID] = &b.all[i]
	}
	return b
}

func (b *Blocks) List() []Block { return b.all }

// safeName keeps a client-supplied patch name usable as a SynthDef name.
func safeName(s string) string {
	out := make([]rune, 0, len(s))
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
			out = append(out, r)
		}
	}
	if len(out) == 0 {
		return "voxChain"
	}
	if out[0] >= '0' && out[0] <= '9' {
		out = append([]rune{'p'}, out...)
	}
	if len(out) > 40 {
		out = out[:40]
	}
	return string(out)
}

// Expand turns a chain into a graph description.
//
// Every block parameter becomes a SynthDef control named "s<step>_<param>", so
// a slider can move it on the running patch with /n_set rather than rebuilding
// and reloading -- which would click.
func (b *Blocks) Expand(c ChainSpec) (GraphSpec, error) {
	var g GraphSpec
	if b.loadE != nil {
		return g, b.loadE
	}
	if len(c.Steps) == 0 {
		return g, fmt.Errorf("a patch needs at least one block")
	}
	if len(c.Steps) > 16 {
		return g, fmt.Errorf("%d blocks; 16 is the limit, and the audio core is "+
			"the real one", len(c.Steps))
	}
	g.Name = safeName(c.Name)

	// Parameters first: NewGraph fixes them, and sclang emits them as a single
	// Control UGen that has to come before anything that reads it.
	type binding struct {
		step  int
		param string
	}
	var order []binding
	for i, s := range c.Steps {
		blk, ok := b.byID[s.Block]
		if !ok {
			return g, fmt.Errorf("step %d: no block called %q", i+1, s.Block)
		}
		for _, p := range blk.Params {
			v := p.Default
			if given, ok := s.Params[p.Name]; ok {
				if given < p.Min || given > p.Max {
					return g, fmt.Errorf("step %d (%s): %s is %g, outside %g..%g",
						i+1, blk.Title, p.Name, given, p.Min, p.Max)
				}
				v = given
			}
			g.Params = append(g.Params, Param{
				Name: fmt.Sprintf("s%d_%s", i, p.Name), Default: float32(v),
			})
			order = append(order, binding{i, p.Name})
		}
	}
	paramRef := func(step int, name string) BlockInput {
		s := fmt.Sprintf("s%d_%s", step, name)
		return BlockInput{Param: &s}
	}

	// The chain signal, one reference per channel.
	inL := len(g.UGens)
	g.UGens = append(g.UGens, GraphUGen{Name: "In", Rate: RateAudio, Outputs: 1,
		Inputs: []GraphInput{constIn(MainLeftBus)}})
	inR := len(g.UGens)
	g.UGens = append(g.UGens, GraphUGen{Name: "In", Rate: RateAudio, Outputs: 1,
		Inputs: []GraphInput{constIn(MainRightBus)}})
	sig := [2]GraphInput{ugenIn(inL, 0), ugenIn(inR, 0)}

	for i, s := range c.Steps {
		blk := b.byID[s.Block]
		var err error
		if blk.Stereo {
			sig, err = b.emit(&g, blk, i, sig, paramRef, true)
		} else {
			var l, r [2]GraphInput
			l, err = b.emit(&g, blk, i, [2]GraphInput{sig[0], sig[0]}, paramRef, false)
			if err == nil {
				r, err = b.emit(&g, blk, i, [2]GraphInput{sig[1], sig[1]}, paramRef, false)
			}
			sig = [2]GraphInput{l[0], r[0]}
		}
		if err != nil {
			return g, fmt.Errorf("step %d (%s): %w", i+1, blk.Title, err)
		}
	}

	// The limiter is mandatory. See the file comment.
	for ch, bus := range [2]float32{MainLeftBus, MainRightBus} {
		lim := len(g.UGens)
		g.UGens = append(g.UGens, GraphUGen{Name: "Limiter", Rate: RateAudio, Outputs: 1,
			Inputs: []GraphInput{sig[ch], constIn(0.95), constIn(0.005)}})
		g.UGens = append(g.UGens, GraphUGen{Name: "ReplaceOut", Rate: RateAudio, Outputs: 0,
			Inputs: []GraphInput{constIn(bus), ugenIn(lim, 0)}})
	}
	return g, nil
}

// emit instantiates one block and returns its outputs.
func (b *Blocks) emit(g *GraphSpec, blk *Block, step int, in [2]GraphInput,
	paramRef func(int, string) BlockInput, stereo bool) ([2]GraphInput, error) {
	base := len(g.UGens)
	var last []GraphInput
	for _, u := range blk.UGens {
		ins := make([]GraphInput, 0, len(u.Inputs))
		for _, bi := range u.Inputs {
			switch {
			case bi.Const != nil:
				ins = append(ins, constIn(*bi.Const))
			case bi.In != nil:
				if *bi.In < 0 || *bi.In > 1 {
					return in, fmt.Errorf("input %d is not a channel", *bi.In)
				}
				ins = append(ins, in[*bi.In])
			case bi.Param != nil:
				ins = append(ins, toGraph(paramRef(step, *bi.Param)))
			case bi.UGen != nil:
				ins = append(ins, ugenIn(base+*bi.UGen, bi.Out))
			default:
				return in, fmt.Errorf("a block input with nothing in it")
			}
		}
		idx := len(g.UGens)
		g.UGens = append(g.UGens, GraphUGen{Name: u.Name, Rate: u.Rate,
			Special: u.Special, Outputs: u.Outputs, Inputs: ins})
		last = nil
		for o := 0; o < u.Outputs; o++ {
			last = append(last, ugenIn(idx, o))
		}
	}
	if len(last) == 0 {
		return in, fmt.Errorf("block %s produced no signal", blk.ID)
	}
	if stereo {
		if len(last) < 2 {
			return in, fmt.Errorf("block %s is marked stereo but has one output", blk.ID)
		}
		return [2]GraphInput{last[0], last[1]}, nil
	}
	return [2]GraphInput{last[0], last[0]}, nil
}

func constIn(v float32) GraphInput { return GraphInput{Const: &v} }
func ugenIn(i, out int) GraphInput { return GraphInput{UGen: &i, Out: out} }
func toGraph(b BlockInput) GraphInput {
	return GraphInput{Const: b.Const, UGen: b.UGen, Out: b.Out, Param: b.Param}
}

// -- handlers -----------------------------------------------------------------

func blocksHandler(b *Blocks, r *Rack) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		if b.loadE != nil {
			httpError(w, http.StatusInternalServerError, b.loadE)
			return
		}
		writeJSON(w, map[string]any{
			"blocks": b.List(), "units": r.Units(),
			"headroom": r.Headroom(), "floor": headroomFloor,
		})
	}
}

func chainHandler(b *Blocks, r *Rack) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		var c ChainSpec
		if err := json.NewDecoder(req.Body).Decode(&c); err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		spec, err := b.Expand(c)
		if err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		if req.URL.Query().Get("dry") != "" {
			writeJSON(w, map[string]any{"graph": spec, "ugens": len(spec.UGens)})
			return
		}
		u, err := r.AddGraph(spec)
		if err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		writeJSON(w, map[string]any{"unit": u, "ugens": len(spec.UGens),
			"headroom": r.Headroom()})
	}
}

// stepParam splits "s3_freq" back into its step and name, for the UI.
func stepParam(s string) (int, string, bool) {
	if !strings.HasPrefix(s, "s") {
		return 0, "", false
	}
	i := strings.IndexByte(s, '_')
	if i < 2 {
		return 0, "", false
	}
	var n int
	if _, err := fmt.Sscanf(s[1:i], "%d", &n); err != nil {
		return 0, "", false
	}
	return n, s[i+1:], true
}
