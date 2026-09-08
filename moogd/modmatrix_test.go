package main

// The factory library is the test oracle.
//
// Every one of these tests reads real `matrix_expression_slots` arrays out of
// Moog's own presets and requires this code to handle them. If our tables
// reject a matrix the instrument ships with, the tables are wrong -- not the
// preset.
//
// The corpus lives under captures/, which is gitignored, so these skip when it
// is absent rather than failing. It comes from the official 1.8.2 download; see
// docs/CORRECTIONS-2026-09-08.md.

import (
	"bufio"
	"encoding/json"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const corpusDir = "../captures/firmware-1.8.2/corpus"

// matrixLine is one address and its decoded token array.
type matrixLine struct {
	file   string
	addr   string
	tokens []float64
}

// loadCorpus pulls every matrix_expression_slots line out of every preset.
func loadCorpus(t *testing.T) []matrixLine {
	t.Helper()
	if _, err := os.Stat(corpusDir); err != nil {
		t.Skipf("preset corpus not present at %s (it is gitignored); "+
			"see docs/CORRECTIONS-2026-09-08.md", corpusDir)
	}
	var out []matrixLine
	err := filepath.WalkDir(corpusDir, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(p, ".m1p") {
			return nil
		}
		f, err := os.Open(p)
		if err != nil {
			return err
		}
		defer f.Close()
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 0, 1<<20), 1<<22) // preset lines get long
		for sc.Scan() {
			line := sc.Text()
			if !strings.Contains(line, "matrix_expression_slots") {
				continue
			}
			sp := strings.IndexByte(line, ' ')
			if sp < 0 {
				continue
			}
			addr, rest := line[:sp], strings.TrimSpace(line[sp+1:])
			var toks []float64
			if err := json.Unmarshal([]byte(rest), &toks); err != nil {
				t.Errorf("%s: matrix is not a JSON array: %v", p, err)
				continue
			}
			out = append(out, matrixLine{file: p, addr: addr, tokens: toks})
		}
		return sc.Err()
	})
	if err != nil {
		t.Fatalf("walking corpus: %v", err)
	}
	if len(out) == 0 {
		t.Skip("corpus present but holds no matrix_expression_slots (all pre-v14)")
	}
	return out
}

// Every factory matrix is a whole number of rows, and decoding then re-encoding
// must reproduce it exactly. Any drift here would silently rewrite a patch.
func TestCorpusRoundTrips(t *testing.T) {
	corpus := loadCorpus(t)
	rows := 0
	for _, m := range corpus {
		slots, err := DecodeSlots(m.tokens)
		if err != nil {
			t.Errorf("%s %s: %v", m.file, m.addr, err)
			continue
		}
		rows += len(slots)
		back := EncodeSlots(slots)
		if len(back) != len(m.tokens) {
			t.Errorf("%s: re-encoded to %d tokens, was %d",
				m.file, len(back), len(m.tokens))
			continue
		}
		for i := range back {
			// Ids must be identical. Amounts are float32 on the instrument, so
			// compare at float32 precision rather than demanding bit equality
			// of the float64 the JSON parsed into.
			if float32(back[i]) != float32(m.tokens[i]) {
				t.Errorf("%s token %d: %v became %v", m.file, i, m.tokens[i], back[i])
				break
			}
		}
	}
	t.Logf("%d matrices, %d rows, all round-tripped", len(corpus), rows)
}

// Validate must accept everything Moog ships. This is the test that catches a
// wrong or short id table.
func TestCorpusValidates(t *testing.T) {
	corpus := loadCorpus(t)
	bad := 0
	for _, m := range corpus {
		slots, err := DecodeSlots(m.tokens)
		if err != nil {
			continue
		}
		if err := Validate(slots); err != nil {
			bad++
			if bad <= 10 {
				t.Errorf("%s: factory preset rejected: %v", filepath.Base(m.file), err)
			}
		}
	}
	if bad > 10 {
		t.Errorf("... and %d more rejected factory matrices", bad-10)
	}
}

// Every id the factory actually uses must be in our tables and marked attested,
// in *every* column. An earlier version of this test checked only destinations,
// and that gap let a wrong Sources table ship: it had been generated from
// vx_ee's `args`, which is a different id space, so source id 6 rendered as
// "m6" when the corpus plainly shows it is MOD WHEEL. Check all four columns.
func TestCorpusIdsAreAttested(t *testing.T) {
	corpus := loadCorpus(t)
	check := func(what string, table []Entry, id int, file string) {
		e, ok := lookup(table, id)
		if !ok {
			t.Fatalf("%s id %d used by %s is missing from the table",
				what, id, filepath.Base(file))
		}
		if !e.Attested {
			t.Errorf("%s id %d (%s) is used by %s but marked unattested",
				what, id, e.Name, filepath.Base(file))
		}
	}
	for _, m := range corpus {
		slots, err := DecodeSlots(m.tokens)
		if err != nil {
			continue
		}
		for _, s := range slots {
			if s.Src != SrcNone {
				check("source", Sources, s.Src, m.file)
			}
			if s.Ctl != SrcNone {
				check("controller", Sources, s.Ctl, m.file)
			}
			if s.Transform != TransformNone {
				check("transform", Transforms, s.Transform, m.file)
			}
			if s.Routed() {
				check("destination", Destinations, s.Dest, m.file)
			}
		}
	}
}

// Describe must never invent a name. Rendering a factory matrix should produce
// only names that are in the tables -- the "#id?" form means we are guessing,
// and we should never be guessing about a preset Moog shipped.
func TestDescribeNamesEverythingInTheCorpus(t *testing.T) {
	corpus := loadCorpus(t)
	for _, m := range corpus {
		slots, err := DecodeSlots(m.tokens)
		if err != nil {
			continue
		}
		for i, s := range slots {
			if got := Describe(s); strings.Contains(got, "?") {
				t.Errorf("%s row %d: unnamed id in %q",
					filepath.Base(m.file), i, got)
			}
		}
	}
}

// The sentinels have to survive a round trip as sentinels, or an unrouted row
// would come back routed somewhere.
func TestUnroutedStaysUnrouted(t *testing.T) {
	for _, none := range DestNone {
		s := Unrouted()
		s.Dest = none
		if s.Routed() {
			t.Errorf("dest %d should read as unrouted", none)
		}
		got, err := DecodeSlots(EncodeSlots([]Slot{s}))
		if err != nil {
			t.Fatal(err)
		}
		if got[0].Routed() {
			t.Errorf("dest %d became routed through a round trip", none)
		}
	}
}

// A partial row is an error, not something to round down.
func TestShortMatrixRejected(t *testing.T) {
	if _, err := DecodeSlots(make([]float64, SlotTokens+1)); err == nil {
		t.Error("a matrix with a trailing partial row should not decode")
	}
}

// Validate must refuse values that cannot go on a wire to the voice controller.
func TestNonFiniteRejected(t *testing.T) {
	for _, bad := range []float64{math.NaN(), math.Inf(1), math.Inf(-1)} {
		s := Unrouted()
		s.Dest = 0
		s.SrcAmt = bad
		if err := Validate([]Slot{s}); err == nil {
			t.Errorf("Validate accepted %v as an amount", bad)
		}
	}
}

// An id outside the symbol table must be refused even though it would encode
// perfectly well.
func TestUnknownIdRejected(t *testing.T) {
	s := Unrouted()
	s.Dest = 9999
	if err := Validate([]Slot{s}); err == nil {
		t.Error("Validate accepted a destination id outside the table")
	}
}

// The tables must have the shape the symbol table declares. These numbers are
// derived independently in docs/arch/expression-language.md and
// docs/CORRECTIONS-2026-09-08.md; if the generator drifts, this catches it.
func TestTableShape(t *testing.T) {
	if got, want := len(Destinations), 126+16; got != want {
		t.Errorf("Destinations has %d entries, want %d (126 results + 16 vars)",
			got, want)
	}
	// EngineInputs is vx_ee's `args`, which really is 46 and really does open
	// with the sixteen MIDI-mappable slots. Sources is a different id space and
	// gets no length assertion, because we only know the part of it the factory
	// library happens to exercise.
	if got, want := len(EngineInputs), 46; got != want {
		t.Errorf("EngineInputs has %d entries, want %d", got, want)
	}
	var midi int
	for _, e := range EngineInputs {
		if len(e.Name) >= 2 && e.Name[0] == 'm' &&
			e.Name[1] >= '0' && e.Name[1] <= '9' {
			midi++
		}
	}
	if midi != 16 {
		t.Errorf("expected 16 MIDI-mappable engine inputs m0..m15, found %d", midi)
	}
	// Every Sources entry is attested by construction; if one is not, the
	// generator has started inventing.
	for _, e := range Sources {
		if !e.Attested {
			t.Errorf("Sources holds unattested entry %d (%s); it should contain "+
				"only ids observed in factory presets", e.ID, e.Name)
		}
	}
}
