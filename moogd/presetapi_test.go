package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// a minimal but real preset: the matrix line is the shape the corpus uses.
const tinyPreset = `/meta/name "TEST PATCH"
/meta/category "TEST"
/p/version 14
/p/part/t/1/p/modmatrix/matrix_expression_slots [48, 1.0, 6, 0.009999999776482582, 43, 0.0, 52]
/p/part/t/1/p/osc/1/wave 0.5
`

func tempStore(t *testing.T) (*presetStore, string) {
	t.Helper()
	dir := t.TempDir()
	f := filepath.Join(dir, "TEST PATCH.m1p")
	if err := os.WriteFile(f, []byte(tinyPreset), 0o644); err != nil {
		t.Fatal(err)
	}
	return &presetStore{root: dir}, dir
}

// The filename arrives in a query string from a web page, so this is the
// boundary that matters. A drive is removable and its contents are not ours.
func TestResolveRefusesEscape(t *testing.T) {
	s, _ := tempStore(t)
	for _, bad := range []string{
		"../outside.m1p",
		"../../etc/passwd.m1p",
		"/etc/passwd.m1p",
		"subdir/../../escape.m1p",
		"",
		"notapreset.txt",
		"/var/las-frontend/MOOG ONE.db",
	} {
		if _, err := s.resolve(bad); err == nil {
			t.Errorf("resolve(%q) was allowed; it must not be", bad)
		}
	}
}

func TestResolveAcceptsPresetInRoot(t *testing.T) {
	s, dir := tempStore(t)
	got, err := s.resolve("TEST PATCH.m1p")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	real, err := filepath.EvalSymlinks(dir)
	if err != nil {
		t.Fatal(err)
	}
	if want := filepath.Join(real, "TEST PATCH.m1p"); got != want {
		t.Errorf("resolve = %q, want %q", got, want)
	}
}

func TestPresetGetAndSaveRoundTrip(t *testing.T) {
	s, dir := tempStore(t)
	h := presetHandler(s)

	r := httptest.NewRecorder()
	h(r, httptest.NewRequest("GET", "/api/preset?file=TEST+PATCH.m1p", nil))
	if r.Code != 200 {
		t.Fatalf("GET: %d %s", r.Code, r.Body)
	}
	var doc presetDoc
	if err := json.Unmarshal(r.Body.Bytes(), &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Name != "TEST PATCH" {
		t.Errorf("name = %q", doc.Name)
	}
	rows := doc.Timbres["1"]
	if len(rows) != 1 {
		t.Fatalf("got %d rows, want 1", len(rows))
	}
	if rows[0].Ctl != 6 {
		t.Errorf("ctl = %d, want 6 (MOD WHEEL)", rows[0].Ctl)
	}

	rows[0].CtlAmt = 0.75
	body, _ := json.Marshal(map[string]any{"timbre": 1, "slots": rows})
	r = httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/preset?file=TEST+PATCH.m1p", strings.NewReader(string(body)))
	h(r, req)
	if r.Code != 200 {
		t.Fatalf("POST: %d %s", r.Code, r.Body)
	}

	// The saved file must differ from the original in exactly one line.
	after, err := os.ReadFile(filepath.Join(dir, "TEST PATCH.m1p"))
	if err != nil {
		t.Fatal(err)
	}
	diff := 0
	for i, line := range strings.Split(tinyPreset, "\n") {
		if strings.Split(string(after), "\n")[i] != line {
			diff++
		}
	}
	if diff != 1 {
		t.Errorf("save changed %d lines, want 1\n%s", diff, after)
	}
	if !strings.Contains(string(after), "0.75") {
		t.Errorf("the edit is not in the file:\n%s", after)
	}
}

// A save that names a preset outside the directory must fail before anything is
// written, not after.
func TestSaveRefusesEscape(t *testing.T) {
	s, dir := tempStore(t)
	outside := filepath.Join(filepath.Dir(dir), "victim.m1p")
	if err := os.WriteFile(outside, []byte("untouched\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	pr := ParsePreset(tinyPreset)
	if err := s.save("../victim.m1p", pr); err == nil {
		t.Fatal("save escaped the preset directory")
	}
	b, _ := os.ReadFile(outside)
	if string(b) != "untouched\n" {
		t.Fatalf("a file outside the directory was modified: %q", b)
	}
}

// A failed save must not leave a temporary file behind on someone's drive.
func TestSaveLeavesNoLitter(t *testing.T) {
	s, dir := tempStore(t)
	if err := s.save("TEST PATCH.m1p", ParsePreset(tinyPreset)); err != nil {
		t.Fatal(err)
	}
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".m1p-") {
			t.Errorf("left a temporary file behind: %s", e.Name())
		}
	}
}

func TestPresetsList(t *testing.T) {
	s, _ := tempStore(t)
	r := httptest.NewRecorder()
	presetsHandler(s)(r, httptest.NewRequest("GET", "/api/presets", nil))
	if r.Code != 200 {
		t.Fatalf("%d %s", r.Code, r.Body)
	}
	var got struct {
		Presets []presetInfo `json:"presets"`
	}
	if err := json.Unmarshal(r.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if len(got.Presets) != 1 || got.Presets[0].Name != "TEST PATCH" {
		t.Fatalf("listing = %+v", got.Presets)
	}
	if got.Presets[0].Rows != 1 {
		t.Errorf("rows = %d, want 1", got.Presets[0].Rows)
	}
}

func TestPresetRejectsBadMethod(t *testing.T) {
	s, _ := tempStore(t)
	r := httptest.NewRecorder()
	presetHandler(s)(r, httptest.NewRequest("DELETE", "/api/preset?file=TEST+PATCH.m1p", nil))
	if r.Code != http.StatusMethodNotAllowed {
		t.Errorf("DELETE returned %d", r.Code)
	}
}
