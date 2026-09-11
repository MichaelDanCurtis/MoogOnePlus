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
