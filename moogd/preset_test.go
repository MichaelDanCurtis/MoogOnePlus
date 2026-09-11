package main

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// presetFiles walks the factory corpus. It lives under captures/, which is
// gitignored, so these skip rather than fail when it is absent.
func presetFiles(t *testing.T) []string {
	t.Helper()
	if _, err := os.Stat(corpusDir); err != nil {
		t.Skipf("preset corpus not present at %s (it is gitignored)", corpusDir)
	}
	var out []string
	err := filepath.WalkDir(corpusDir, func(p string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() && strings.HasSuffix(p, ".m1p") {
			out = append(out, p)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walking corpus: %v", err)
	}
	if len(out) == 0 {
		t.Skip("corpus present but holds no .m1p")
	}
	return out
}

// The property the whole design rests on: reading a preset and writing it back
// changes nothing at all. Not "nothing important" -- nothing. A preset is
// someone's patch, and this code has no business touching 3,901 lines it does
// not understand in order to edit three that it does.
func TestPresetReadWriteIsByteIdentical(t *testing.T) {
	for _, f := range presetFiles(t) {
		raw, err := os.ReadFile(f)
		if err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		if got := ParsePreset(string(raw)).String(); got != string(raw) {
			t.Errorf("%s: round trip changed the file (%d bytes -> %d)",
				filepath.Base(f), len(raw), len(got))
		}
	}
}

// Re-rendering a matrix from its own decoded rows must reproduce Moog's exact
// spelling -- sixteen significant digits, e-7 not e-07, "1.0" not "1". This is
// the test that earns the claim that a file we write is indistinguishable from
// one Moog wrote.
func TestMatrixRendersExactlyAsMoogSpellsIt(t *testing.T) {
	checked := 0
	for _, f := range presetFiles(t) {
		raw, err := os.ReadFile(f)
		if err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		before := string(raw)
		p := ParsePreset(before)
		for _, timbre := range p.Timbres() {
			slots, err := p.Matrix(timbre)
			if err != nil {
				t.Errorf("%s timbre %d: %v", filepath.Base(f), timbre, err)
				continue
			}
			if err := p.SetMatrix(timbre, slots); err != nil {
				t.Errorf("%s timbre %d: %v", filepath.Base(f), timbre, err)
				continue
			}
			checked++
		}
		if got := p.String(); got != before {
			for i, line := range strings.Split(got, "\n") {
				orig := strings.Split(before, "\n")[i]
				if line != orig {
					t.Errorf("%s: rewriting the matrix changed it\n orig %.120s\n ours %.120s",
						filepath.Base(f), orig, line)
					break
				}
			}
		}
	}
	t.Logf("%d matrices re-rendered byte-for-byte", checked)
}

// An edit must land, and must land only where it was aimed.
func TestSetMatrixTouchesOneLine(t *testing.T) {
	for _, f := range presetFiles(t) {
		raw, _ := os.ReadFile(f)
		p := ParsePreset(string(raw))
		timbres := p.Timbres()
		if len(timbres) == 0 {
			continue
		}
		slots, err := p.Matrix(timbres[0])
		if err != nil || len(slots) == 0 {
			continue
		}
		slots[0].CtlAmt = 0.25
		if err := p.SetMatrix(timbres[0], slots); err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		diff := 0
		after := strings.Split(p.String(), "\n")
		for i, line := range strings.Split(string(raw), "\n") {
			if after[i] != line {
				diff++
			}
		}
		if diff != 1 {
			t.Fatalf("%s: an edit changed %d lines, want exactly 1", filepath.Base(f), diff)
		}
		got, err := p.Matrix(timbres[0])
		if err != nil {
			t.Fatalf("%s: re-reading the edit: %v", f, err)
		}
		if float32(got[0].CtlAmt) != 0.25 {
			t.Fatalf("%s: edit did not survive the write: %v", f, got[0].CtlAmt)
		}
		return // one preset proves it; the corpus is large
	}
	t.Skip("no preset in the corpus carries a matrix")
}

// A preset older than /p/version 14 has no matrix at all. Asking for one should
// say so rather than hand back an empty matrix that would then be saved over
// something that was never there.
func TestPresetWithoutMatrixSaysSo(t *testing.T) {
	p := ParsePreset("/meta/name \"OLD\"\n/p/version 8\n")
	if got := p.Timbres(); len(got) != 0 {
		t.Fatalf("expected no timbres, got %v", got)
	}
	if _, err := p.Matrix(1); err == nil {
		t.Error("expected an error asking for a matrix that is not there")
	}
	if err := p.SetMatrix(1, []Slot{Unrouted()}); err == nil {
		t.Error("expected an error writing a matrix that is not there")
	}
}

func TestPresetMeta(t *testing.T) {
	p := ParsePreset("/meta/name \"SWEET DREAMS\"\n/meta/category \"CLASSIC\"\n")
	if got := p.Meta("name"); got != "SWEET DREAMS" {
		t.Errorf("name = %q", got)
	}
	if got := p.Meta("nope"); got != "" {
		t.Errorf("missing key = %q, want empty", got)
	}
}

// The corpus cannot exercise an exponent-formatted amount in isolation, so this
// pins the two spellings that differ from Go's defaults.
func TestAmountSpelling(t *testing.T) {
	for _, c := range []struct {
		in   float64
		want string
	}{
		{1, "1.0"},
		{0, "0.0"},
		{-6.705522537231445e-7, "-6.705522537231445e-7"}, // not e-07
		{0.009999999776482582, "0.009999999776482582"},   // 16 significant digits
		{0.5036774873733521, "0.5036774873733521"},       // not Go's shorter form
	} {
		if got := formatAmount(c.in); got != c.want {
			t.Errorf("formatAmount(%v) = %q, want %q", c.in, got, c.want)
		}
	}
}
