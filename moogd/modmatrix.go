package main

// The modulation matrix, as data.
//
// `/p/part/t/{1,2,3}/p/modmatrix/matrix_expression_slots` is a flat array of
// numbers, seven per row:
//
//	[src_id, src_amount, ctl_id, ctl_amount, transform_id, transform_amount, dest_id]
//
// A row multiplies a source by a controller, shapes the result with a
// transform, and adds it to a destination. The panel writes exactly this; there
// is no second, richer mechanism hiding behind the UI. What the panel does not
// give you is the *rest* of the table -- the factory library reaches 71 of 126
// destinations and none of the sixteen MIDI-mappable sources -- and reaching
// the rest is the entire point of this file.
//
// The engine runs on the XMOS voice controller, so a row costs nothing on
// either i.MX6 core. See docs/arch/expression-language.md.
//
// Ids come from tables.go, generated from the engine's own symbol table.

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"strconv"
)

// A Slot is one row of the matrix. Amounts are the coefficients; ids index the
// tables in tables.go.
type Slot struct {
	Src       int     `json:"src"`
	SrcAmt    float64 `json:"src_amt"`
	Ctl       int     `json:"ctl"`
	CtlAmt    float64 `json:"ctl_amt"`
	Transform int     `json:"transform"`
	TransAmt  float64 `json:"transform_amt"`
	Dest      int     `json:"dest"`
}

// Unrouted is the row the instrument writes for an empty slot. `Dest` uses the
// lower of the two "none" spellings seen in the corpus; both occur and both
// mean unrouted, so decoding accepts either and encoding picks one.
func Unrouted() Slot {
	return Slot{
		Src: SrcNone, SrcAmt: 1, Ctl: SrcNone, CtlAmt: 1,
		Transform: TransformNone, TransAmt: 0, Dest: DestNone[0],
	}
}

// Routed reports whether this row does anything.
func (s Slot) Routed() bool {
	for _, none := range DestNone {
		if s.Dest == none {
			return false
		}
	}
	return true
}

// DecodeSlots turns the wire array into rows. A trailing partial row is an
// error rather than something to round down, because silently dropping tokens
// would let a corrupt read look like a valid short matrix.
func DecodeSlots(tokens []float64) ([]Slot, error) {
	if len(tokens)%SlotTokens != 0 {
		return nil, fmt.Errorf("matrix has %d tokens, not a multiple of %d",
			len(tokens), SlotTokens)
	}
	out := make([]Slot, 0, len(tokens)/SlotTokens)
	for i := 0; i < len(tokens); i += SlotTokens {
		out = append(out, Slot{
			Src:       int(tokens[i]),
			SrcAmt:    tokens[i+1],
			Ctl:       int(tokens[i+2]),
			CtlAmt:    tokens[i+3],
			Transform: int(tokens[i+4]),
			TransAmt:  tokens[i+5],
			Dest:      int(tokens[i+6]),
		})
	}
	return out, nil
}

// EncodeSlots is the inverse. Ids go back as whole numbers so that a decoded
// matrix re-encodes to the bytes it came from.
func EncodeSlots(slots []Slot) []float64 {
	out := make([]float64, 0, len(slots)*SlotTokens)
	for _, s := range slots {
		out = append(out,
			float64(s.Src), s.SrcAmt,
			float64(s.Ctl), s.CtlAmt,
			float64(s.Transform), s.TransAmt,
			float64(s.Dest))
	}
	return out
}

// -- the wire to the voice controller -----------------------------------------

// SlotBytes is one row's size in the blob the voice controller receives.
//
// Read off the wire on 2026-09-10 rather than inferred from the preset schema:
// a capture on the i.MX6->XMOS link taken while the front panel's matrix was
// edited. The message is a single OSC blob -- type tag ",b" -- sent to
// `/g/<synth>/t/e/s` at 203.0.113.2:7770, and each row occupies exactly sixteen
// bytes:
//
//	[0]      src id            uint8
//	[1:5]    src amount        float32
//	[5]      ctl id            uint8
//	[6:10]   ctl amount        float32
//	[10]     transform id      uint8
//	[11:15]  transform amount  float32
//	[15]     dest id           uint8
//
// That is the same seven-tuple the preset file stores, so this is the binary
// spelling of EncodeSlots and not a second model of the same thing.
//
// **The amounts are LITTLE-endian.** This is the trap. OSC is a big-endian
// protocol and the blob's own length prefix obeys it, so a single packet
// carries both byte orders: big-endian framing around a little-endian payload.
// Read the wrong way a coefficient of 1.0 becomes 4.6e-41 -- a denormal, not a
// parse error -- so the mistake is audible long before it is visible.
//
// Unused rows are transmitted rather than omitted, filled with the sentinels in
// tables.go. An empty row on the wire is exactly Unrouted(), except that the
// instrument spells "no destination" 141 where Unrouted() picks 137; both occur
// in the corpus and both mean unrouted.
const SlotBytes = 16

// MarshalSlots renders rows as the voice controller receives them.
//
// The ids are re-checked against a byte here even though Validate has already
// matched them to the tables, because this is the last point at which they are
// still Go integers. Past it a wrong id is an anonymous byte in a blob bound for
// the processor that runs the analog voices.
func MarshalSlots(slots []Slot) ([]byte, error) {
	out := make([]byte, 0, len(slots)*SlotBytes)
	putID := func(id int, field string, i int) error {
		if id < 0 || id > 255 {
			return fmt.Errorf("slot %d: %s id %d does not fit in a byte", i, field, id)
		}
		out = append(out, byte(id))
		return nil
	}
	putAmt := func(amt float64) {
		var b [4]byte
		binary.LittleEndian.PutUint32(b[:], math.Float32bits(float32(amt)))
		out = append(out, b[:]...)
	}
	for i, s := range slots {
		for _, col := range []struct {
			id    int
			amt   float64
			field string
		}{
			{s.Src, s.SrcAmt, "src"},
			{s.Ctl, s.CtlAmt, "ctl"},
			{s.Transform, s.TransAmt, "transform"},
		} {
			if err := putID(col.id, col.field, i); err != nil {
				return nil, err
			}
			putAmt(col.amt)
		}
		if err := putID(s.Dest, "dest", i); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// UnmarshalSlots reads a blob captured from, or received on, that link.
//
// A trailing partial row is an error rather than something to round down: the
// voice controller echoes every blob it is sent, so a short read means the
// capture is wrong, and quietly dropping the remainder would hide that.
func UnmarshalSlots(b []byte) ([]Slot, error) {
	if len(b)%SlotBytes != 0 {
		return nil, fmt.Errorf("blob is %d bytes, not a multiple of %d", len(b), SlotBytes)
	}
	amt := func(p []byte) float64 {
		return float64(math.Float32frombits(binary.LittleEndian.Uint32(p)))
	}
	out := make([]Slot, 0, len(b)/SlotBytes)
	for o := 0; o < len(b); o += SlotBytes {
		r := b[o : o+SlotBytes]
		out = append(out, Slot{
			Src: int(r[0]), SrcAmt: amt(r[1:5]),
			Ctl: int(r[5]), CtlAmt: amt(r[6:10]),
			Transform: int(r[10]), TransAmt: amt(r[11:15]),
			Dest: int(r[15]),
		})
	}
	return out, nil
}

// lookup finds an id in a table.
func lookup(table []Entry, id int) (Entry, bool) {
	for _, e := range table {
		if e.ID == id {
			return e, true
		}
	}
	return Entry{}, false
}

// Validate rejects a matrix this code cannot vouch for.
//
// This is deliberately strict. Every id here ends up on a wire to the voice
// controller -- the processor that also runs the analog voices, on a card that
// cannot be replaced -- so an id we cannot name is an id we do not send. An
// unattested id is allowed (its position in the symbol table is the evidence)
// but an id outside the table is not.
func Validate(slots []Slot) error {
	for i, s := range slots {
		for _, f := range []float64{s.SrcAmt, s.CtlAmt, s.TransAmt} {
			if math.IsNaN(f) || math.IsInf(f, 0) {
				return fmt.Errorf("row %d: amount is not a finite number", i)
			}
		}
		if s.Src != SrcNone {
			if _, ok := lookup(Sources, s.Src); !ok {
				return fmt.Errorf("row %d: unknown source id %d", i, s.Src)
			}
		}
		if s.Ctl != SrcNone {
			if _, ok := lookup(Sources, s.Ctl); !ok {
				return fmt.Errorf("row %d: unknown controller id %d", i, s.Ctl)
			}
		}
		if s.Transform != TransformNone {
			if _, ok := lookup(Transforms, s.Transform); !ok {
				return fmt.Errorf("row %d: unknown transform id %d "+
					"(only ids seen in factory presets are accepted)", i, s.Transform)
			}
		}
		if s.Routed() {
			if _, ok := lookup(Destinations, s.Dest); !ok {
				return fmt.Errorf("row %d: unknown destination id %d", i, s.Dest)
			}
		}
	}
	return nil
}

// Describe renders a row in words, for the UI and for logs. Unattested ids are
// marked, because "this is what the symbol table says it is" and "we have seen
// the instrument do this" are different claims.
func Describe(s Slot) string {
	name := func(table []Entry, id int, none int, zero string) string {
		if id == none {
			return zero
		}
		e, ok := lookup(table, id)
		if !ok {
			return fmt.Sprintf("#%d?", id)
		}
		if !e.Attested {
			return e.Name + "*"
		}
		return e.Name
	}
	if !s.Routed() {
		return "(unrouted)"
	}
	out := name(Sources, s.Src, SrcNone, "1")
	if s.SrcAmt != 1 {
		out += fmt.Sprintf("×%g", s.SrcAmt)
	}
	if s.Ctl != SrcNone {
		out += " · " + name(Sources, s.Ctl, SrcNone, "1")
		if s.CtlAmt != 1 {
			out += fmt.Sprintf("×%g", s.CtlAmt)
		}
	}
	if s.Transform != TransformNone {
		out += " → " + name(Transforms, s.Transform, TransformNone, "")
		if s.TransAmt != 0 {
			out += fmt.Sprintf("(%g)", s.TransAmt)
		}
	}
	return out + " ⇒ " + name(Destinations, s.Dest, -1, "")
}

// -- HTTP --------------------------------------------------------------------

// tablesResponse is what the UI needs to render pickers.
type tablesResponse struct {
	Sources      []Entry `json:"sources"`
	Transforms   []Entry `json:"transforms"`
	Destinations []Entry `json:"destinations"`
	SrcNone      int     `json:"src_none"`
	TransNone    int     `json:"transform_none"`
	DestNone     []int   `json:"dest_none"`
	SlotTokens   int     `json:"slot_tokens"`
	Note         string  `json:"note"`
}

func modmatrixTablesHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(tablesResponse{
		Sources: Sources, Transforms: Transforms, Destinations: Destinations,
		SrcNone: SrcNone, TransNone: TransformNone, DestNone: DestNone,
		SlotTokens: SlotTokens,
		Note: "attested=false means the id follows from its position in the " +
			"engine's symbol table and no factory preset has ever used it",
	})
}

// writeRequest is a matrix to install on one timbre.
type writeRequest struct {
	Timbre int    `json:"timbre"` // 1, 2 or 3
	Slots  []Slot `json:"slots"`
	DryRun bool   `json:"dry_run"`
}

// modmatrixWriteHandler validates a matrix and, unless asked only to check it,
// sends it. The send path is gated by -allow-write for the reason given on
// writeSlots.
func modmatrixWriteHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"POST only"}`, http.StatusMethodNotAllowed)
		return
	}
	var req writeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf("{%q:%q}", "error", err.Error()),
			http.StatusBadRequest)
		return
	}
	if req.Timbre < 1 || req.Timbre > 3 {
		http.Error(w, `{"error":"timbre must be 1, 2 or 3"}`, http.StatusBadRequest)
		return
	}
	if err := Validate(req.Slots); err != nil {
		http.Error(w, fmt.Sprintf("{%q:%q}", "error", err.Error()),
			http.StatusBadRequest)
		return
	}

	lines := make([]string, len(req.Slots))
	for i, s := range req.Slots {
		lines[i] = Describe(s)
	}
	resp := map[string]any{
		"timbre":  req.Timbre,
		"rows":    len(req.Slots),
		"reads":   lines,
		"tokens":  EncodeSlots(req.Slots),
		"address": slotsAddress(req.Timbre),
	}

	if req.DryRun {
		resp["sent"] = false
		resp["why"] = "dry run"
	} else if err := writeSlots(req.Timbre, req.Slots); err != nil {
		resp["sent"] = false
		resp["why"] = err.Error()
	} else {
		resp["sent"] = true
	}
	_ = json.NewEncoder(w).Encode(resp)
}

func slotsAddress(timbre int) string {
	return "/p/part/t/" + strconv.Itoa(timbre) + "/p/modmatrix/matrix_expression_slots"
}
