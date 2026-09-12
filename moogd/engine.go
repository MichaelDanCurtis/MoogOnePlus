package main

// The Engine: DSP that is already in the instrument and that the instrument
// cannot reach.
//
// `scsynth` loads 96 plugin binaries at boot, registering 795 UGens. The client
// beside it runs `sclang -a` against a 195-file class library, and 435 of those
// UGens have no class in it -- so the machine cannot write them into a SynthDef
// and never has. `ReverbUGens.so` is on that list in full: FreeVerb, FreeVerb2
// and GVerb are resident, registered, and unnameable from the instrument.
//
// The way in is that `scsynth` resolves a UGen by NAME when a definition
// arrives over `/d_recv`. A SynthDef compiled elsewhere -- by a real sclang,
// with the real classes -- works, because the server only ever sees the string.
// So the definitions are compiled on a workstation by
// tools/build-engine-synthdefs.py and embedded here as bytes.
//
// Three rules this file exists to keep:
//
//  1. **Nothing is freed that we did not create.** `/n_free` on a LADSPA node
//     terminates `scsynth`, and the instrument has ten of them permanently
//     resident (the Eventide reverbs, moved between groups rather than created,
//     precisely because freeing them is fatal). Only node ids this process
//     allocated are ever freed, and they live in a range nothing else uses.
//
//  2. **Moog's rack is not touched.** The five effect slots and their groups are
//     left exactly alone. Everything here goes at the TAIL of the root group,
//     after all of it, and replaces the main pair on its way out.
//
//  3. **The audio core decides.** An effect is refused if the realtime thread
//     does not have room for it, because a dropout is worse than a missing
//     reverb -- and this instrument's throttle has fired three times already.

import (
	"embed"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"net"
	"net/http"
	"sort"
	"sync"
	"time"
)

//go:embed engine/catalogue.json engine/*.scsyndef
var engineFS embed.FS

// Node ids start here. Everything else this project puts on the server lives
// between 90210 and 95500, and Moog's own nodes are far below that.
const engineFirstNode = 96000

// headroomFloor is the margin, in points of the audio core, below which an
// effect is refused.
//
// Not a guess at what a reverb costs: a refusal to spend the last of what is
// there. The kernel deschedules the engine above 95% of cpu1 and that has
// already happened on this instrument, so the last few points are not available
// to be spent on anything.
const headroomFloor = 12.0

type EffectParam struct {
	Name    string  `json:"name"`
	Label   string  `json:"label"`
	Min     float64 `json:"min"`
	Max     float64 `json:"max"`
	Default float64 `json:"default"`
	Step    float64 `json:"step"`

	// Readout turns the raw control value into something a musician can act
	// on. "0.80" says nothing; "2.4 s" says what the reverb will do. The pairs
	// are measured rather than modelled -- an impulse rendered through this
	// exact UGen at each value, decay to -60 dB -- and the page interpolates
	// between them. Empty where no measurement has been taken, which is most
	// controls, and saying nothing is better than saying something invented.
	Readout     [][2]float64 `json:"readout,omitempty"`
	ReadoutUnit string       `json:"readout_unit,omitempty"`
	ReadoutNote string       `json:"readout_note,omitempty"`
}

type Effect struct {
	Name   string        `json:"name"`
	Title  string        `json:"title"`
	UGen   string        `json:"ugen"`
	Plugin string        `json:"plugin"`
	Blurb  string        `json:"blurb"`
	Cost   string        `json:"cost"`
	Graph  string        `json:"-"`
	Params []EffectParam `json:"params"`
}

type catalogueFile struct {
	Effects []Effect `json:"effects"`
}

// Unit is one running effect.
type Unit struct {
	Node   int                `json:"node"`
	Effect string             `json:"effect"`
	Title  string             `json:"title"`
	Params map[string]float64 `json:"params"`
}

// Rack holds what we have put on the server. It is the only record of which
// nodes are ours, and therefore the only thing standing between a remove and a
// node that must never be freed.
type Rack struct {
	mu      sync.Mutex
	units   map[int]*Unit
	loaded  map[string]bool
	nextID  int
	cat     []Effect
	scPort  int
	byName  map[string]*Effect
	lastErr string

	// Told after any change so it can rebuild itself at the tail of the group.
	// A meter that runs before the thing it is metering reads the previous
	// block -- see Meter.Invalidate.
	meter *Meter
}

// WatchWith attaches the meter that must stay last in the chain.
func (r *Rack) WatchWith(m *Meter) { r.meter = m }

// changed is called after anything is added to or removed from the group.
func (r *Rack) changed() {
	if r.meter != nil {
		r.meter.Invalidate()
	}
}

func NewRack(scPort int) (*Rack, error) {
	raw, err := engineFS.ReadFile("engine/catalogue.json")
	if err != nil {
		return nil, err
	}
	var cf catalogueFile
	if err := json.Unmarshal(raw, &cf); err != nil {
		return nil, fmt.Errorf("engine catalogue: %w", err)
	}
	r := &Rack{
		units: map[int]*Unit{}, loaded: map[string]bool{},
		nextID: engineFirstNode, cat: cf.Effects, scPort: scPort,
		byName: map[string]*Effect{},
	}
	for i := range r.cat {
		r.byName[r.cat[i].Name] = &r.cat[i]
	}
	return r, nil
}

// -- OSC, with the two argument types main.go's encoder does not carry --------

func oscFloat(addr string, args ...any) []byte {
	out := append([]byte(addr), 0)
	out = append(out, make([]byte, pad(len(out)))...)
	tags := ","
	var body []byte
	for _, a := range args {
		switch v := a.(type) {
		case int32:
			tags += "i"
			var b [4]byte
			binary.BigEndian.PutUint32(b[:], uint32(v))
			body = append(body, b[:]...)
		case float32:
			tags += "f"
			var b [4]byte
			binary.BigEndian.PutUint32(b[:], math.Float32bits(v))
			body = append(body, b[:]...)
		case string:
			tags += "s"
			s := append([]byte(v), 0)
			body = append(body, append(s, make([]byte, pad(len(s)))...)...)
		case []byte:
			tags += "b"
			var n [4]byte
			binary.BigEndian.PutUint32(n[:], uint32(len(v)))
			body = append(body, n[:]...)
			body = append(body, v...)
			body = append(body, make([]byte, pad(len(v)))...)
		}
	}
	t := append([]byte(tags), 0)
	out = append(out, append(t, make([]byte, pad(len(t)))...)...)
	return append(out, body...)
}

// call sends one message and, when wantReply, waits for the server to answer.
//
// `/sync` is used rather than trusting `/done`, because a busy server answers
// `/d_recv` late and the reply then lands in the NEXT request's socket -- which
// is how a tidy-up once turned into "server rejected /n_free" somewhere else in
// this project.
func (r *Rack) call(msg []byte, wantSync bool) error {
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", r.scPort))
	if err != nil {
		return err
	}
	defer c.Close()
	if _, err := c.Write(msg); err != nil {
		return err
	}
	if !wantSync {
		return nil
	}
	if _, err := c.Write(oscFloat("/sync", int32(1))); err != nil {
		return err
	}
	_ = c.SetReadDeadline(time.Now().Add(4 * time.Second))
	buf := make([]byte, 1024)
	for {
		n, err := c.Read(buf)
		if err != nil {
			return fmt.Errorf("scsynth did not answer: %w", err)
		}
		if n > 7 && string(buf[:7]) == "/synced" {
			return nil
		}
		if n > 5 && string(buf[:5]) == "/fail" {
			return fmt.Errorf("scsynth rejected the request: %s", printable(buf[:n]))
		}
	}
}

func printable(b []byte) string {
	out := make([]byte, 0, len(b))
	for _, c := range b {
		if c >= 32 && c < 127 {
			out = append(out, c)
		} else if len(out) > 0 && out[len(out)-1] != ' ' {
			out = append(out, ' ')
		}
	}
	return string(out)
}

// -- operations ---------------------------------------------------------------

// Headroom is the points of the audio core currently unspent.
func (r *Rack) Headroom() float64 {
	cores := perCore(250 * time.Millisecond)
	return (throttleCeiling() - cores["cpu1"]) * 100
}

// Add puts an effect at the tail of the root group.
func (r *Rack) Add(name string, params map[string]float64) (*Unit, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	eff, ok := r.byName[name]
	if !ok {
		return nil, fmt.Errorf("no effect called %q", name)
	}
	if head := r.Headroom(); head < headroomFloor {
		return nil, fmt.Errorf("the audio core has %.0f points free and the floor "+
			"is %.0f; this instrument's realtime throttle has already fired three "+
			"times, so the last of it is not available to spend", head, headroomFloor)
	}
	if !r.loaded[name] {
		blob, err := engineFS.ReadFile("engine/" + name + ".scsyndef")
		if err != nil {
			return nil, fmt.Errorf("%s has no compiled definition: %w", name, err)
		}
		if err := r.call(oscFloat("/d_recv", blob), true); err != nil {
			return nil, fmt.Errorf("loading %s: %w", name, err)
		}
		r.loaded[name] = true
	}
	// Start from the catalogue's defaults so an omitted control is the
	// documented value rather than zero -- zero room size is not a quiet
	// reverb, it is a different and worse one.
	use := map[string]float64{}
	for _, p := range eff.Params {
		use[p.Name] = p.Default
	}
	for k, v := range params {
		p := paramOf(eff, k)
		if p == nil {
			return nil, fmt.Errorf("%s has no control called %q", name, k)
		}
		if v < p.Min || v > p.Max {
			return nil, fmt.Errorf("%s: %s must be between %g and %g", name, k, p.Min, p.Max)
		}
		use[k] = v
	}
	node := r.nextID
	r.nextID++
	// addAction 1, target 0: the tail of the root group, after everything the
	// instrument does -- including all five of Moog's effect slots.
	args := []any{eff.Name, int32(node), int32(1), int32(0)}
	for _, p := range eff.Params {
		args = append(args, p.Name, float32(use[p.Name]))
	}
	if err := r.call(oscFloat("/s_new", args...), true); err != nil {
		return nil, fmt.Errorf("starting %s: %w", name, err)
	}
	u := &Unit{Node: node, Effect: eff.Name, Title: eff.Title, Params: use}
	r.units[node] = u
	r.changed()
	return u, nil
}

func paramOf(e *Effect, name string) *EffectParam {
	for i := range e.Params {
		if e.Params[i].Name == name {
			return &e.Params[i]
		}
	}
	return nil
}

// Remove frees one of OUR nodes.
//
// The check against r.units is the safety property, not bookkeeping: `/n_free`
// on a LADSPA node terminates the audio server, and the instrument keeps ten of
// them alive at all times. A node id that is not in this map is not ours and is
// not freed, whatever the caller says.
func (r *Rack) Remove(node int) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.units[node]; !ok {
		return fmt.Errorf("node %d was not started here, so it will not be freed "+
			"-- freeing a node this did not create can terminate the audio server", node)
	}
	if err := r.call(oscFloat("/n_free", int32(node)), true); err != nil {
		return err
	}
	delete(r.units, node)
	r.changed()
	return nil
}

// Set changes one control on a running unit.
func (r *Rack) Set(node int, name string, v float64) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	u, ok := r.units[node]
	if !ok {
		return fmt.Errorf("node %d is not one of ours", node)
	}
	eff := r.byName[u.Effect]
	p := paramOf(eff, name)
	if p == nil {
		return fmt.Errorf("%s has no control called %q", u.Effect, name)
	}
	if v < p.Min || v > p.Max {
		return fmt.Errorf("%s must be between %g and %g", name, p.Min, p.Max)
	}
	if err := r.call(oscFloat("/n_set", int32(node), name, float32(v)), false); err != nil {
		return err
	}
	u.Params[name] = v
	return nil
}

// RemoveAll frees everything this process started.
func (r *Rack) RemoveAll() []int {
	r.mu.Lock()
	nodes := make([]int, 0, len(r.units))
	for n := range r.units {
		nodes = append(nodes, n)
	}
	r.mu.Unlock()
	sort.Ints(nodes)
	var freed []int
	for _, n := range nodes {
		if err := r.Remove(n); err == nil {
			freed = append(freed, n)
		}
	}
	return freed
}

func (r *Rack) Units() []*Unit {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]*Unit, 0, len(r.units))
	for _, u := range r.units {
		out = append(out, u)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Node < out[j].Node })
	return out
}

// -- handlers -----------------------------------------------------------------

func engineHandler(r *Rack) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		writeJSON(w, map[string]any{
			"catalogue": r.cat,
			"units":     r.Units(),
			"headroom":  r.Headroom(),
			"floor":     headroomFloor,
		})
	}
}

func engineAddHandler(r *Rack) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		var body struct {
			Effect string             `json:"effect"`
			Params map[string]float64 `json:"params"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		u, err := r.Add(body.Effect, body.Params)
		if err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		writeJSON(w, map[string]any{"unit": u, "headroom": r.Headroom()})
	}
}

func engineRemoveHandler(r *Rack) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		var body struct {
			Node int  `json:"node"`
			All  bool `json:"all"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		if body.All {
			writeJSON(w, map[string]any{"freed": r.RemoveAll(), "headroom": r.Headroom()})
			return
		}
		if err := r.Remove(body.Node); err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		writeJSON(w, map[string]any{"freed": []int{body.Node}, "headroom": r.Headroom()})
	}
}

func engineSetHandler(r *Rack) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		var body struct {
			Node  int     `json:"node"`
			Param string  `json:"param"`
			Value float64 `json:"value"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		if err := r.Set(body.Node, body.Param, body.Value); err != nil {
			httpError(w, http.StatusBadRequest, err)
			return
		}
		writeJSON(w, map[string]any{"ok": true})
	}
}
