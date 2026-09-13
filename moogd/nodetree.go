package main

// Reading the audio graph as it actually is.
//
// docs/firmware/las-fx.md derives the node topology from init_sc_1.scd and
// marks it [INFERRED - firmly]. It also predicts a specific defect -- an
// eleventh Eventide node, orphaned by ~initEffect taking the insert branch the
// first time a bus slot changes -- and says plainly what would settle it:
// "confirming it needs a live /g_queryTree". This is that.
//
// It matters beyond tidiness. The same document works out that an Eventide
// running outside ~eventideGroup keeps its SynthDef defaults, inBus = 0 and
// outBus = 0, so it reads hardware output bus 0 and writes it again: an
// immediate feedback loop on the main output. That is a real mechanism with an
// audible signature, and until now there was no way to look for it.
//
// The reply format, from the SuperCollider server command reference:
//
//	/g_queryTree.reply
//	  int   flag: 1 if control values are included
//	  int   the group asked about
//	  int   how many children it has
//	  then, depth first, per node:
//	    int   node id
//	    int   number of children, or -1 for a synth
//	    if a synth:
//	      sym   the SynthDef name
//	      if flag: int number of controls, then name/value pairs

import (
	"encoding/binary"
	"fmt"
	"math"
	"net"
	"net/http"
	"time"
)

// TreeNode is one entry in the graph.
type TreeNode struct {
	ID       int         `json:"id"`
	Def      string      `json:"def,omitempty"` // synths only
	Depth    int         `json:"depth"`
	Group    bool        `json:"group"`
	Children []*TreeNode `json:"children,omitempty"`
}

// QueryTree asks scsynth for the contents of a group.
func QueryTree(scPort, group int) (*TreeNode, error) {
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", scPort))
	if err != nil {
		return nil, err
	}
	defer c.Close()
	// flag 0: names only. Control values would multiply the reply size by the
	// number of parameters in the graph and none of it is needed to see shape.
	if _, err := c.Write(oscFloat("/g_queryTree", int32(group), int32(0))); err != nil {
		return nil, err
	}
	_ = c.SetReadDeadline(time.Now().Add(4 * time.Second))
	buf := make([]byte, 65536)
	for {
		n, err := c.Read(buf)
		if err != nil {
			return nil, fmt.Errorf("scsynth did not answer /g_queryTree: %w", err)
		}
		addr, rest, ok := oscString(buf[:n])
		if !ok || addr != "/g_queryTree.reply" {
			continue // /done and friends may be queued ahead of the answer
		}
		return parseTree(rest)
	}
}

// oscArgs walks a type-tag string and returns the arguments as ints and strings.
// Floats are read and discarded: with flag 0 none should appear, and a float
// where an int belongs would desynchronise the walk silently.
func oscArgs(b []byte) ([]any, error) {
	tags, rest, ok := oscString(b)
	if !ok || len(tags) == 0 || tags[0] != ',' {
		return nil, fmt.Errorf("no type tag")
	}
	out := make([]any, 0, len(tags)-1)
	for _, t := range tags[1:] {
		switch t {
		case 'i':
			if len(rest) < 4 {
				return out, fmt.Errorf("truncated int")
			}
			out = append(out, int(int32(binary.BigEndian.Uint32(rest))))
			rest = rest[4:]
		case 'f':
			if len(rest) < 4 {
				return out, fmt.Errorf("truncated float")
			}
			out = append(out, float64(math.Float32frombits(binary.BigEndian.Uint32(rest))))
			rest = rest[4:]
		case 's':
			s, r, ok := oscString(rest)
			if !ok {
				return out, fmt.Errorf("truncated string")
			}
			out, rest = append(out, s), r
		default:
			return out, fmt.Errorf("unexpected type tag %q", t)
		}
	}
	return out, nil
}

func parseTree(b []byte) (*TreeNode, error) {
	args, err := oscArgs(b)
	if err != nil {
		return nil, err
	}
	if len(args) < 3 {
		return nil, fmt.Errorf("reply has %d arguments, want at least 3", len(args))
	}
	flag, _ := args[0].(int)
	rootID, _ := args[1].(int)
	nKids, _ := args[2].(int)
	i := 3
	root := &TreeNode{ID: rootID, Group: true}
	var walk func(parent *TreeNode, count, depth int) error
	walk = func(parent *TreeNode, count, depth int) error {
		for k := 0; k < count; k++ {
			if i+1 >= len(args) {
				return fmt.Errorf("reply ended inside the tree")
			}
			id, _ := args[i].(int)
			kids, _ := args[i+1].(int)
			i += 2
			n := &TreeNode{ID: id, Depth: depth, Group: kids >= 0}
			if kids < 0 {
				if i >= len(args) {
					return fmt.Errorf("a synth with no SynthDef name")
				}
				n.Def, _ = args[i].(string)
				i++
				if flag == 1 && i < len(args) {
					nc, _ := args[i].(int)
					i += 1 + nc*2
				}
			}
			parent.Children = append(parent.Children, n)
			if kids > 0 {
				if err := walk(n, kids, depth+1); err != nil {
					return err
				}
			}
		}
		return nil
	}
	if err := walk(root, nKids, 1); err != nil {
		return nil, err
	}
	return root, nil
}

// Flatten returns every node, depth first.
func (n *TreeNode) Flatten() []*TreeNode {
	out := []*TreeNode{n}
	for _, c := range n.Children {
		out = append(out, c.Flatten()...)
	}
	return out
}

// Eventides reports every et_* synth and where it sits.
//
// Ten of them live parked in ~eventideGroup by design. An eleventh, or one in a
// different group, is the orphan las-fx.md predicts -- and an orphan running
// with its SynthDef defaults reads and writes hardware output bus 0.
func (n *TreeNode) Eventides() []*TreeNode {
	var out []*TreeNode
	for _, x := range n.Flatten() {
		if len(x.Def) > 3 && x.Def[:3] == "et_" {
			out = append(out, x)
		}
	}
	return out
}

func treeHandler(scPort int) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		t, err := QueryTree(scPort, 0)
		if err != nil {
			httpError(w, http.StatusInternalServerError, err)
			return
		}
		all := t.Flatten()
		ev := t.Eventides()
		writeJSON(w, map[string]any{
			"tree": t, "nodes": len(all), "eventides": len(ev),
			"note": fmt.Sprintf("%d et_* nodes; ten parked in the Eventide group is "+
				"the designed state, and an eleventh is the orphan las-fx.md 7.4 "+
				"predicts", len(ev)),
		})
	}
}
