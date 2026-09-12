package main

// A preset file, held as the lines it is made of.
//
// A `.m1p` is plain ASCII: one `<osc-address> <value>` per line, and a preset
// runs to about four thousand of them. Exactly three are modulation matrices --
// one per timbre. So the document model here is deliberately not "parse a
// preset": it keeps every line verbatim and re-renders only the matrix lines
// that are actually changed.
//
// That is a safety property rather than a shortcut. Editing one routing cannot
// perturb the other 3,901 lines of somebody's patch, because the code never
// looks at them. An untouched preset writes back byte-identical by
// construction, not by care.
//
// The instrument itself keeps presets in SQLite at /var/las-frontend, not as
// files -- `las-frontend --data-path=/var/las-frontend`, with `--usb-path`
// pointing at the thumbdrive for import and export. `.m1p` is the interchange
// format, which is exactly why this writes those and never the live library:
// the user's library is irreplaceable and the instrument owns it.

import (
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
)

// matrixSlotsLine matches the three lines that matter and captures the timbre index
// and the JSON array of tokens.
var matrixSlotsLine = regexp.MustCompile(
	`^(/p/part/t/(\d+)/p/modmatrix/matrix_expression_slots) \[(.*)\]$`)

// Preset is one .m1p document.
type Preset struct {
	lines   []string
	addr    map[int]string // timbre -> the address text, reused when re-rendering
	lineFor map[int]int    // timbre -> index into lines
}

// ParsePreset reads a preset without interpreting it.
func ParsePreset(text string) *Preset {
	p := &Preset{
		lines:   strings.Split(text, "\n"),
		addr:    map[int]string{},
		lineFor: map[int]int{},
	}
	for i, line := range p.lines {
		m := matrixSlotsLine.FindStringSubmatch(strings.TrimRight(line, "\r"))
		if m == nil {
			continue
		}
		t, err := strconv.Atoi(m[2])
		if err != nil {
			continue
		}
		p.addr[t], p.lineFor[t] = m[1], i
	}
	return p
}

// Timbres lists the timbres that carry a matrix, in order.
//
// A preset older than `/p/version 14` has none at all: the matrix predates the
// field, and most of the factory library is older than it.
func (p *Preset) Timbres() []int {
	var out []int
	for t := 1; t <= 3; t++ {
		if _, ok := p.lineFor[t]; ok {
			out = append(out, t)
		}
	}
	return out
}

// Version is the preset format version, or 0 if the file does not say.
//
// This matters more than it looks. On 2026-09-12 a version 14 preset from the
// 1.8.2 package was imported onto firmware 1.5.0, whose own library is 126
// presets at version 10. las-frontend accepted it without complaint and the
// effects engine then had to be restarted to stop a sound that would not stop
// -- MIDI all-sound-off did not touch it, because it was not notes. The cause
// was never proven, but a preset format four versions ahead of the firmware
// reading it is the obvious suspect and nothing warned about it.
func (p *Preset) Version() int {
	for _, line := range p.lines {
		if !strings.HasPrefix(line, "/p/version ") {
			continue
		}
		v, err := strconv.Atoi(strings.TrimSpace(strings.TrimRight(line[11:], "\r")))
		if err != nil {
			return 0
		}
		return v
	}
	return 0
}

// Meta returns a `/meta/...` value with its quotes stripped, or "".
func (p *Preset) Meta(key string) string {
	want := "/meta/" + key + " "
	for _, line := range p.lines {
		if !strings.HasPrefix(line, want) {
			continue
		}
		return strings.Trim(strings.TrimRight(line[len(want):], "\r"), `"`)
	}
	return ""
}

// Matrix returns one timbre's rows.
func (p *Preset) Matrix(timbre int) ([]Slot, error) {
	i, ok := p.lineFor[timbre]
	if !ok {
		return nil, fmt.Errorf("preset has no matrix for timbre %d", timbre)
	}
	m := matrixSlotsLine.FindStringSubmatch(strings.TrimRight(p.lines[i], "\r"))
	if m == nil {
		return nil, fmt.Errorf("timbre %d: matrix line no longer parses", timbre)
	}
	body := strings.TrimSpace(m[3])
	if body == "" {
		return nil, nil
	}
	fields := strings.Split(body, ",")
	toks := make([]float64, 0, len(fields))
	for _, f := range fields {
		v, err := strconv.ParseFloat(strings.TrimSpace(f), 64)
		if err != nil {
			return nil, fmt.Errorf("timbre %d: %q is not a number", timbre, f)
		}
		toks = append(toks, v)
	}
	return DecodeSlots(toks)
}

// SetMatrix replaces one timbre's rows, leaving every other byte alone.
func (p *Preset) SetMatrix(timbre int, slots []Slot) error {
	i, ok := p.lineFor[timbre]
	if !ok {
		return fmt.Errorf("preset has no matrix for timbre %d", timbre)
	}
	if err := Validate(slots); err != nil {
		return err
	}
	p.lines[i] = p.addr[timbre] + " [" + renderTokens(EncodeSlots(slots)) + "]"
	return nil
}

// String reassembles the document.
func (p *Preset) String() string { return strings.Join(p.lines, "\n") }

// renderTokens spells a matrix the way the instrument spells it.
//
// The rule was derived from the factory corpus rather than assumed, because a
// preset we write should be indistinguishable from one Moog wrote: ids are
// plain integers, whole amounts get one decimal place, and everything else gets
// **sixteen significant digits**. Not Go's shortest round-trip, which is
// shorter, and not seventeen, which is longer -- sixteen reproduces all 300
// factory matrices exactly and the other two do not.
func renderTokens(toks []float64) string {
	parts := make([]string, len(toks))
	for i, v := range toks {
		if i%SlotTokens == 1 || i%SlotTokens == 3 || i%SlotTokens == 5 {
			parts[i] = formatAmount(v)
			continue
		}
		parts[i] = strconv.FormatInt(int64(v), 10)
	}
	return strings.Join(parts, ", ")
}

// expZeros strips the padding from an exponent: Moog writes e-7 where Go and C
// both write e-07.
var expZeros = regexp.MustCompile(`e([+-])0*(\d)`)

func formatAmount(v float64) string {
	if v == math.Trunc(v) && math.Abs(v) < 1e15 {
		return strconv.FormatFloat(v, 'f', 1, 64)
	}
	return expZeros.ReplaceAllString(strconv.FormatFloat(v, 'g', 16, 64), "e$1$2")
}

// -- the other copy ------------------------------------------------------------
//
// A preset writes every matrix row TWICE: once as ids in
// `matrix_expression_slots`, and once in words in an `entry/N/...` block --
//
//	entry/1/src   "LFO 4"
//	entry/1/dst   "/p/part/t/1/p/p2/d"
//	entry/1/mute  false
//
// The entry block is the real one. Two things prove it. It carries `mute`,
// which the id array cannot express; and 1,606 rows in the factory corpus live
// in presets that have an entry block and no id array at all, because the array
// was added at `/p/version 14` and the entry block predates it. The ids are the
// compiled output -- the same bytes that go to the voice controller.
//
// So an editor that writes only the ids is editing a derived artifact. Whatever
// las-frontend recompiles from the entry block wins, and the edit evaporates.
// Both copies get written here, and they are written from the ids, because
// id->spelling is a function while spelling->id is not: "FUNCTION" is the
// display name of five different transform ids, and an unrouted destination is
// spelled either 137 or 141.
//
// Muting blanks the compiled copy -- ctl becomes 48 and dest becomes 137 or
// 141, while the entry block keeps the real routing. A muted row therefore
// reads as unrouted in the id array, and rewriting it from those ids would
// destroy the routing the mute is hiding. Muted rows are left exactly as found.

var entryLine = regexp.MustCompile(
	`^/p/part/t/(\d+)/p/modmatrix/entry/(\d+)/(\w+) (.*)$`)

// entryRef locates one field of one row.
type entryRef struct{ timbre, row int }

func (p *Preset) indexEntries() map[entryRef]map[string]int {
	out := map[entryRef]map[string]int{}
	for i, line := range p.lines {
		m := entryLine.FindStringSubmatch(strings.TrimRight(line, "\r"))
		if m == nil {
			continue
		}
		t, err1 := strconv.Atoi(m[1])
		row, err2 := strconv.Atoi(m[2])
		if err1 != nil || err2 != nil {
			continue
		}
		k := entryRef{t, row}
		if out[k] == nil {
			out[k] = map[string]int{}
		}
		out[k][m[3]] = i
	}
	return out
}

// Muted reports which rows of a timbre the entry block marks muted.
func (p *Preset) Muted(timbre int) map[int]bool {
	out := map[int]bool{}
	for k, fields := range p.indexEntries() {
		if k.timbre != timbre {
			continue
		}
		if i, ok := fields["mute"]; ok {
			out[k.row] = strings.TrimSpace(fieldValue(p.lines[i])) == "true"
		}
	}
	return out
}

// fieldValue is everything after the address on a preset line.
func fieldValue(line string) string {
	if sp := strings.IndexByte(line, ' '); sp >= 0 {
		return strings.TrimRight(line[sp+1:], "\r")
	}
	return ""
}

// spellingOf renders an id the way the entry block spells it.
func spellingOf(table []Entry, id int) (string, bool) {
	for _, e := range table {
		if e.ID == id {
			return e.Preset, e.Preset != ""
		}
	}
	return "", false
}

// compiledTransforms are the operators whose amount is not the number the entry
// block holds.
//
// For 888 of 987 factory rows the two copies carry the same transform amount.
// The 99 that differ are all SLEW, SLEW UP, SLEW DOWN, LOPASS, HIPASS, S&H or
// FUNCTION -- the time-shaped operators. eec's instruction reference explains
// it at entry 45, `tta`: "Calculate single-pole coefficient from a time in
// seconds." The entry block holds the seconds a musician set; the id array
// holds the coefficient the engine runs. 0.9 seconds becomes 7.289999, and 17.0
// becomes 0.0.
//
// Inverting that needs the sample rate and the exact curve, neither of which
// has been established, so changing one of these is refused rather than
// guessed.
var compiledTransforms = map[int]bool{
	4: true, 5: true, 6: true, 7: true, 8: true, 9: true, // LOPASS..S&H
	14: true, 23: true, 25: true, 28: true, 30: true, // the FUNCTION ids
}

// SetMatrixRows writes a timbre's rows to BOTH copies.
//
// Only rows that actually changed are touched, and within them only the fields
// that changed. That is not an optimisation: the two copies legitimately hold
// different numbers for the same row -- different precision for every amount,
// and an entirely different value for a compiled transform -- so rewriting a
// field that did not change would corrupt it.
//
// Rows the entry block marks muted are skipped whatever they contain, because
// their compiled ids are blanks and writing those back would erase the routing
// the mute is hiding.
func (p *Preset) SetMatrixRows(timbre int, slots []Slot) error {
	before, err := p.Matrix(timbre)
	if err != nil {
		return err
	}
	muted := p.Muted(timbre)
	idx := p.indexEntries()
	for row, s := range slots {
		if muted[row] {
			if row < len(before) && s != before[row] {
				return fmt.Errorf("row %d is muted; unmute it on the instrument "+
					"before editing it here, because a muted row's real routing "+
					"is not in the part of the preset this can read", row+1)
			}
			continue
		}
		was := Slot{}
		if row < len(before) {
			was = before[row]
		}
		if s == was {
			continue
		}
		if s.Transform != was.Transform || float32(s.TransAmt) != float32(was.TransAmt) {
			if compiledTransforms[s.Transform] || compiledTransforms[was.Transform] {
				return fmt.Errorf("row %d: this transform's amount is a time in "+
					"seconds that the instrument compiles into a coefficient, and "+
					"the conversion is not yet known, so it cannot be written from "+
					"here", row+1)
			}
		}
		fields, ok := idx[entryRef{timbre, row}]
		if !ok {
			continue // a row the entry block does not describe
		}
		if err := p.writeEntry(fields, s, was, row); err != nil {
			return err
		}
	}
	return p.SetMatrix(timbre, slots)
}

// writeEntry updates the words for one changed row.
func (p *Preset) writeEntry(fields map[string]int, s, was Slot, row int) error {
	spell := func(table []Entry, id int, none bool, what string) (string, error) {
		name, ok := spellingOf(table, id)
		if !ok && !none {
			// An id with no recorded spelling has never appeared in a factory
			// preset. Writing "" would silently unroute the row, so refuse the
			// save rather than half-apply it.
			return "", fmt.Errorf("row %d: this %s has never appeared in a factory "+
				"preset, so the spelling the entry block needs is unknown", row+1, what)
		}
		return name, nil
	}
	if s.Src != was.Src {
		name, err := spell(Sources, s.Src, s.Src == SrcNone, "source")
		if err != nil {
			return err
		}
		p.setSelector(fields, "src", name, s.Src == SrcNone)
	}
	if s.Ctl != was.Ctl {
		name, err := spell(Sources, s.Ctl, s.Ctl == SrcNone, "control")
		if err != nil {
			return err
		}
		p.setSelector(fields, "ctl", name, s.Ctl == SrcNone)
	}
	if s.Transform != was.Transform {
		name, err := spell(Transforms, s.Transform, s.Transform == TransformNone, "transform")
		if err != nil {
			return err
		}
		p.setSelector(fields, "tr", name, s.Transform == TransformNone)
	}
	if s.Dest != was.Dest {
		name, err := spell(Destinations, s.Dest, !s.Routed(), "destination")
		if err != nil {
			return err
		}
		p.setSelector(fields, "dst", name, !s.Routed())
	}
	if float32(s.SrcAmt) != float32(was.SrcAmt) {
		p.setAmount(fields, "src_a", s.SrcAmt)
	}
	if float32(s.CtlAmt) != float32(was.CtlAmt) {
		p.setAmount(fields, "ctl_a", s.CtlAmt)
	}
	if float32(s.TransAmt) != float32(was.TransAmt) {
		p.setAmount(fields, "tr_a", s.TransAmt)
	}
	return nil
}

// setAmount writes an amount field.
//
// The two copies hold the same number at DIFFERENT precision: the entry block
// carries the exact float32 promoted to double (0.0002000067033804953, bits
// 3f2a371c80000000) while the id array carries that value printed to fifteen
// digits and read back (0.000200006703380495, bits ...7ffffff5). A changed
// amount is therefore written the way the entry block spells one -- the exact
// float32 the instrument will use.
func (p *Preset) setAmount(fields map[string]int, name string, v float64) {
	p.setField(fields, name, formatAmount(float64(float32(v))))
}

// setSelector writes one of the four name fields.
//
// "Nothing selected" has two spellings in the corpus -- "" and "-" for a source
// or transform, "" and "/dummy" for a destination -- and both occur. Which one a
// given preset used is not recoverable from the id, so a field that already
// means none is left alone rather than rewritten to the other spelling.
func (p *Preset) setSelector(fields map[string]int, name, spelling string, isNone bool) {
	if isNone {
		if i, ok := fields[name]; ok && meansNone(strings.Trim(fieldValue(p.lines[i]), `"`)) {
			return
		}
	}
	p.setField(fields, name, quoted(spelling))
}

// meansNone reports whether a spelling in the entry block is an empty
// selection. All three forms appear in the factory library.
func meansNone(v string) bool {
	return v == "" || v == "-" || v == "/dummy"
}

func quoted(s string) string { return `"` + s + `"` }

// setField rewrites one entry line in place, keeping its address.
func (p *Preset) setField(fields map[string]int, name, value string) {
	i, ok := fields[name]
	if !ok {
		return
	}
	line := strings.TrimRight(p.lines[i], "\r")
	sp := strings.IndexByte(line, ' ')
	if sp < 0 {
		return
	}
	p.lines[i] = line[:sp+1] + value
}
