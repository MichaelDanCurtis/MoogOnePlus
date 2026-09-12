package main

// Reading and writing SuperCollider's compiled SynthDef format.
//
// `scsynth` will only accept a definition as bytes. Until now this project has
// produced those bytes by shelling out to a real `sclang` on a workstation --
// deliberately, because src/moogone/synthdef.py says why: "an unverifiable
// encoder is the confident-looking wrong answer this codebase keeps finding."
//
// That reasoning held while there was nothing to check an encoder against. It
// no longer does. The instrument's own firmware ships **104 compiled
// SynthDefs**, written by Moog's toolchain and nothing to do with us, and a
// real sclang is available to generate more. So the encoder is verifiable in
// the only way that counts: decode the corpus, re-encode it, and require the
// bytes back unchanged.
//
// Why it matters: the iPad cannot run sclang, and the instrument's own sclang
// is crippled -- 195 classes, no FreeVerb2, no anything. Without a native
// encoder, a user cannot build a patch without a Mac in the loop. With one,
// moogd compiles on the instrument and all 734 idle UGens become reachable
// from a tablet.
//
// Format, version 2, in order:
//
//	"SCgf"  int32 version  int16 numDefs
//	per def:
//	  pstring name
//	  int32 nConstants   float32 * n
//	  int32 nParams      float32 * n        -- initial values
//	  int32 nParamNames  (pstring, int32 index) * n
//	  int32 nUGens       per ugen:
//	                       pstring className  int8 rate
//	                       int32 nIn  int32 nOut  int16 specialIndex
//	                       (int32 ugenIndex, int32 outputOrConstIndex) * nIn
//	                       int8 rate * nOut
//	  int16 nVariants    (pstring, float32 * nParams) * n
//
// Version 1 is the same shape with int16 where version 2 has int32. It is
// decoded so old files can be read, and never written: everything in the wild
// here is version 2.

import (
	"encoding/binary"
	"fmt"
	"math"
)

const scgfMagic = "SCgf"

// UGenInput is one input to a UGen: either another UGen's output, or a
// constant. UGenIndex == -1 means Index points into the constant pool.
type UGenInput struct {
	UGenIndex int32 `json:"ugen"`
	Index     int32 `json:"index"`
}

func (i UGenInput) IsConstant() bool { return i.UGenIndex == -1 }

// UGenSpec is one node of the graph.
type UGenSpec struct {
	Name         string      `json:"name"`
	Rate         int8        `json:"rate"` // 0 scalar, 1 control, 2 audio
	SpecialIndex int16       `json:"special_index"`
	Inputs       []UGenInput `json:"inputs"`
	Outputs      []int8      `json:"outputs"` // rate per output
}

// ParamName maps a control name to its index in the parameter array.
type ParamName struct {
	Name  string `json:"name"`
	Index int32  `json:"index"`
}

// Variant is a named set of alternative parameter defaults.
type Variant struct {
	Name   string    `json:"name"`
	Values []float32 `json:"values"`
}

// SynthDef is one compiled definition.
type SynthDef struct {
	Name       string      `json:"name"`
	Constants  []float32   `json:"constants"`
	ParamInits []float32   `json:"param_inits"`
	ParamNames []ParamName `json:"param_names"`
	UGens      []UGenSpec  `json:"ugens"`
	Variants   []Variant   `json:"variants"`
}

// -- decoding -----------------------------------------------------------------

type reader struct {
	b   []byte
	i   int
	v   int32
	err error
}

func (r *reader) fail(format string, a ...any) {
	if r.err == nil {
		r.err = fmt.Errorf(format+" (at byte %d)", append(a, r.i)...)
	}
}

func (r *reader) need(n int) bool {
	if r.err != nil {
		return false
	}
	if r.i+n > len(r.b) {
		r.fail("truncated: wanted %d more bytes", n)
		return false
	}
	return true
}

func (r *reader) u8() int8 {
	if !r.need(1) {
		return 0
	}
	v := int8(r.b[r.i])
	r.i++
	return v
}

func (r *reader) i16() int16 {
	if !r.need(2) {
		return 0
	}
	v := int16(binary.BigEndian.Uint16(r.b[r.i:]))
	r.i += 2
	return v
}

func (r *reader) i32() int32 {
	if !r.need(4) {
		return 0
	}
	v := int32(binary.BigEndian.Uint32(r.b[r.i:]))
	r.i += 4
	return v
}

// count reads a length that is int16 in version 1 and int32 in version 2.
func (r *reader) count() int32 {
	if r.v == 1 {
		return int32(r.i16())
	}
	return r.i32()
}

func (r *reader) f32() float32 {
	if !r.need(4) {
		return 0
	}
	v := math.Float32frombits(binary.BigEndian.Uint32(r.b[r.i:]))
	r.i += 4
	return v
}

// pstring is a length-prefixed string: one byte of length, then the bytes.
// There is no terminator and no padding -- unlike OSC, which pads to four.
func (r *reader) pstring() string {
	if !r.need(1) {
		return ""
	}
	n := int(r.b[r.i])
	r.i++
	if !r.need(n) {
		return ""
	}
	s := string(r.b[r.i : r.i+n])
	r.i += n
	return s
}

// DecodeSynthDefs reads a .scsyndef file.
func DecodeSynthDefs(b []byte) ([]SynthDef, int32, error) {
	r := &reader{b: b}
	if len(b) < 8 || string(b[:4]) != scgfMagic {
		return nil, 0, fmt.Errorf("not a SynthDef file: missing %q magic", scgfMagic)
	}
	r.i = 4
	version := r.i32()
	if version != 1 && version != 2 {
		return nil, version, fmt.Errorf("unsupported SynthDef version %d", version)
	}
	r.v = version
	n := int(r.i16())
	if n < 0 {
		return nil, version, fmt.Errorf("negative definition count %d", n)
	}
	defs := make([]SynthDef, 0, n)
	for d := 0; d < n && r.err == nil; d++ {
		defs = append(defs, r.def())
	}
	return defs, version, r.err
}

func (r *reader) def() SynthDef {
	var d SynthDef
	d.Name = r.pstring()

	d.Constants = make([]float32, max32(r.count()))
	for i := range d.Constants {
		d.Constants[i] = r.f32()
	}
	d.ParamInits = make([]float32, max32(r.count()))
	for i := range d.ParamInits {
		d.ParamInits[i] = r.f32()
	}
	d.ParamNames = make([]ParamName, max32(r.count()))
	for i := range d.ParamNames {
		d.ParamNames[i] = ParamName{Name: r.pstring(), Index: r.count()}
	}
	d.UGens = make([]UGenSpec, max32(r.count()))
	for i := range d.UGens {
		u := UGenSpec{Name: r.pstring(), Rate: r.u8()}
		nIn, nOut := r.count(), r.count()
		u.SpecialIndex = r.i16()
		u.Inputs = make([]UGenInput, max32(nIn))
		for j := range u.Inputs {
			u.Inputs[j] = UGenInput{UGenIndex: r.count(), Index: r.count()}
		}
		u.Outputs = make([]int8, max32(nOut))
		for j := range u.Outputs {
			u.Outputs[j] = r.u8()
		}
		d.UGens[i] = u
	}
	nVar := int(r.i16())
	d.Variants = make([]Variant, max0(nVar))
	for i := range d.Variants {
		v := Variant{Name: r.pstring(), Values: make([]float32, len(d.ParamInits))}
		for j := range v.Values {
			v.Values[j] = r.f32()
		}
		d.Variants[i] = v
	}
	return d
}

// A corrupt length must not become a giant allocation.
func max32(n int32) int32 {
	if n < 0 {
		return 0
	}
	return n
}
func max0(n int) int {
	if n < 0 {
		return 0
	}
	return n
}

// -- encoding -----------------------------------------------------------------

type writer struct {
	b   []byte
	err error
}

func (w *writer) u8(v int8) { w.b = append(w.b, byte(v)) }
func (w *writer) i16(v int16) {
	w.b = binary.BigEndian.AppendUint16(w.b, uint16(v))
}
func (w *writer) i32(v int32) {
	w.b = binary.BigEndian.AppendUint32(w.b, uint32(v))
}
func (w *writer) f32(v float32) {
	w.b = binary.BigEndian.AppendUint32(w.b, math.Float32bits(v))
}

// pstring writes a length-prefixed string. The length is a single byte, so a
// name over 255 bytes cannot be represented -- caught here rather than written
// as a silently truncated definition scsynth would reject or, worse, accept.
func (w *writer) pstring(s string) {
	if len(s) > 255 {
		if w.err == nil {
			w.err = fmt.Errorf("name %q is %d bytes; the format allows 255", s, len(s))
		}
		return
	}
	w.b = append(w.b, byte(len(s)))
	w.b = append(w.b, s...)
}

// EncodeSynthDefs writes a version 2 .scsyndef.
func EncodeSynthDefs(defs []SynthDef) ([]byte, error) {
	w := &writer{}
	w.b = append(w.b, scgfMagic...)
	w.i32(2)
	if len(defs) > math.MaxInt16 {
		return nil, fmt.Errorf("%d definitions; the format allows %d", len(defs), math.MaxInt16)
	}
	w.i16(int16(len(defs)))
	for _, d := range defs {
		if err := w.def(d); err != nil {
			return nil, err
		}
	}
	return w.b, w.err
}

func (w *writer) def(d SynthDef) error {
	w.pstring(d.Name)
	w.i32(int32(len(d.Constants)))
	for _, c := range d.Constants {
		w.f32(c)
	}
	w.i32(int32(len(d.ParamInits)))
	for _, p := range d.ParamInits {
		w.f32(p)
	}
	w.i32(int32(len(d.ParamNames)))
	for _, p := range d.ParamNames {
		w.pstring(p.Name)
		w.i32(p.Index)
	}
	w.i32(int32(len(d.UGens)))
	for _, u := range d.UGens {
		w.pstring(u.Name)
		w.u8(u.Rate)
		w.i32(int32(len(u.Inputs)))
		w.i32(int32(len(u.Outputs)))
		w.i16(u.SpecialIndex)
		for _, in := range u.Inputs {
			w.i32(in.UGenIndex)
			w.i32(in.Index)
		}
		for _, o := range u.Outputs {
			w.u8(o)
		}
	}
	w.i16(int16(len(d.Variants)))
	for _, v := range d.Variants {
		if len(v.Values) != len(d.ParamInits) {
			return fmt.Errorf("variant %q has %d values, but the def has %d parameters",
				v.Name, len(v.Values), len(d.ParamInits))
		}
		w.pstring(v.Name)
		for _, f := range v.Values {
			w.f32(f)
		}
	}
	return w.err
}
