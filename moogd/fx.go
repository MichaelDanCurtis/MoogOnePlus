package main

// The FX tab: the instrument's own node tree, read from scsynth and made editable.
//
// Ported from src/moogone/vox/fx.py and src/moogone/sc/tree.py, including the
// safety rules, which are the part of this worth being careful about.

import (
	"fmt"
	"math"
	"strings"
	"time"
)

type ctlSpec struct {
	Name  string  `json:"-"`
	Value float64 `json:"value"`
	Lo    float64 `json:"lo"`
	Hi    float64 `json:"hi"`
	Kind  string  `json:"kind"` // range | switch | readonly
}

type fxNode struct {
	ID       int32              `json:"id"`
	Defname  string             `json:"defname"`
	Controls map[string]ctlSpec `json:"controls"`
	Order    []string           `json:"order"`
}

var (
	switchNames = map[string]bool{
		"enable": true, "bypass": true, "on": true, "off": true,
		"mute": true, "active": true, "gate": true,
	}
	unitNames = map[string]bool{
		"mix": true, "wet": true, "dry": true, "level": true, "amount": true,
		"amt": true, "depth": true, "feedback": true, "fb": true, "pan": true,
	}
	gainNames = map[string]bool{"gain": true, "volume": true, "vol": true}
	// Bus and routing indices are not for turning. Matched by exact name or a "bus"
	// suffix -- NOT by an "in"/"out" suffix, which would also catch "gain",
	// "sustain" and "out_gain".
	readonlyNames = map[string]bool{"in": true, "out": true, "ctlin": true, "ctlout": true}
)

// inferRange decides what a control may be shown as and whether it may be written.
//
// The named-vs-unnamed distinction is the important one. scsynth sends a control's
// INDEX, as an int, when the SynthDef gave it no name -- the real instrument does
// this 53 times in one synth (`inputRouter`), and a mock server never does, so it
// only ever appears on hardware. There is nothing to reason from, so this does not
// pretend to a range: it shows the value and refuses the write. Guessing at an
// unnamed control on a live audio router is how this project locked the synth up.
func inferRange(name string, named bool, v float64) (lo, hi float64, kind string) {
	if !named {
		return v, v, "readonly"
	}
	n := strings.ToLower(name)
	switch {
	case switchNames[n]:
		return 0, 1, "switch"
	case unitNames[n]:
		return 0, 1, "range"
	case gainNames[n] || strings.Contains(n, "gain"):
		return 0, 2, "range"
	case strings.HasPrefix(n, "time"):
		return 0, 2, "range"
	case readonlyNames[n] || strings.HasSuffix(n, "bus"):
		return v, v, "readonly"
	}
	// Unknown: bracket the current value with room above it, never zero-width.
	return math.Min(0, v), math.Max(1, 2*math.Abs(v)), "range"
}

// parseQueryTree walks the flattened depth-first reply. Each entry is
// (node_id, num_children); num_children == -1 marks a synth, which is followed by
// its defname and, when controls were requested, its control pairs.
func parseQueryTree(args []any) ([]fxNode, error) {
	if len(args) == 0 {
		return nil, fmt.Errorf("empty reply")
	}
	withControls, _ := asInt(args[0])
	pos := 1
	var out []fxNode

	var read func() error
	read = func() error {
		if pos+1 >= len(args) {
			return fmt.Errorf("truncated at %d", pos)
		}
		nodeID, _ := asInt(args[pos])
		numChildren, _ := asInt(args[pos+1])
		pos += 2

		if numChildren == -1 {
			if pos >= len(args) {
				return fmt.Errorf("node %d: no defname", nodeID)
			}
			defname, _ := args[pos].(string)
			pos++
			n := fxNode{ID: nodeID, Defname: defname, Controls: map[string]ctlSpec{}}
			if withControls != 0 {
				if pos >= len(args) {
					return fmt.Errorf("node %d: no control count", nodeID)
				}
				numControls, _ := asInt(args[pos])
				pos++
				for i := int32(0); i < numControls; i++ {
					if pos+1 >= len(args) {
						return fmt.Errorf("node %d: truncated controls", nodeID)
					}
					raw, val := args[pos], args[pos+1]
					pos += 2
					f, _ := asFloat(val)
					name, named := raw.(string)
					if !named {
						// Unnamed: scsynth gave an index. Keep it addressable in
						// the UI but not writable.
						if idx, ok := asInt(raw); ok {
							name = fmt.Sprintf("%d", idx)
						}
					}
					lo, hi, kind := inferRange(name, named, f)
					n.Controls[name] = ctlSpec{Name: name, Value: f, Lo: lo, Hi: hi, Kind: kind}
					n.Order = append(n.Order, name)
				}
			}
			out = append(out, n)
			return nil
		}
		if numChildren < 0 {
			// -1 is the only negative value with meaning. Anything else is a
			// malformed reply, and falling through to the group branch would
			// yield zero children -- a plausible-looking empty group instead of
			// a surfaced error.
			return fmt.Errorf("node %d: invalid child count %d (only -1 marks a synth)",
				nodeID, numChildren)
		}
		for i := int32(0); i < numChildren; i++ {
			if err := read(); err != nil {
				return err
			}
		}
		return nil
	}
	if err := read(); err != nil {
		return nil, err
	}
	return out, nil
}

// fxTree asks scsynth for the whole tree, with controls.
func fxTree(scPort int) ([]fxNode, error) {
	m, err := request(scPort, oscMessage("/g_queryTree", int32(0), int32(1)),
		"/g_queryTree.reply", 4*time.Second)
	if err != nil {
		return nil, err
	}
	return parseQueryTree(m.Args)
}

func fxTreeMessage(scPort int) map[string]any {
	nodes, err := fxTree(scPort)
	if err != nil {
		return map[string]any{
			"type": "error", "where": "scsynth",
			"what": "cannot read node tree: " + err.Error(),
		}
	}
	list := make([]map[string]any, 0, len(nodes))
	for _, n := range nodes {
		ctrls := map[string]any{}
		for k, c := range n.Controls {
			ctrls[k] = map[string]any{"value": c.Value, "lo": c.Lo, "hi": c.Hi, "kind": c.Kind}
		}
		list = append(list, map[string]any{
			"id": n.ID, "defname": n.Defname, "controls": ctrls, "order": n.Order,
		})
	}
	return map[string]any{"type": "fx.tree", "nodes": list}
}

// fxSet writes one control, then reads the tree back to confirm it took. scsynth
// acknowledges nothing for /n_set, so a write that silently did nothing is
// indistinguishable from one that worked unless it is read back.
func fxSet(scPort int, node int32, ctl string, value float64) map[string]any {
	if err := send(scPort, oscMessage("/n_set", node, ctl, float32(value))); err != nil {
		return map[string]any{"type": "error", "where": "scsynth", "what": err.Error()}
	}
	nodes, err := fxTree(scPort)
	if err != nil {
		return map[string]any{"type": "fx.value", "node": node, "ctl": ctl,
			"value": value, "confirmed": false}
	}
	for _, n := range nodes {
		if n.ID != node {
			continue
		}
		if c, ok := n.Controls[ctl]; ok {
			return map[string]any{"type": "fx.value", "node": node, "ctl": ctl,
				"value": c.Value, "confirmed": math.Abs(c.Value-value) < 1e-4}
		}
	}
	return map[string]any{"type": "fx.value", "node": node, "ctl": ctl,
		"value": value, "confirmed": false}
}
