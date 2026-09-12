package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// The instrument's own compiled definitions: 104 files written by Moog's
// toolchain, nothing to do with this code. They are the corpus that makes the
// encoder verifiable rather than merely plausible.
const firmwareDefs = "../captures/rootfs-1.5.0/usr/share/las-fx/synthdefs"

func synthdefFiles(t *testing.T, dir string) []string {
	t.Helper()
	files, err := filepath.Glob(filepath.Join(dir, "*.scsyndef"))
	if err != nil || len(files) == 0 {
		t.Skipf("no .scsyndef in %s (captures/ is gitignored)", dir)
	}
	return files
}

// Decode every definition the firmware ships. A parser that cannot read Moog's
// own output has no business writing anything scsynth will be asked to run.
func TestDecodeTheFirmwaresOwnSynthDefs(t *testing.T) {
	files := synthdefFiles(t, firmwareDefs)
	ugens, defs := 0, 0
	for _, f := range files {
		raw, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		got, version, err := DecodeSynthDefs(raw)
		if err != nil {
			t.Errorf("%s: %v", filepath.Base(f), err)
			continue
		}
		if version != 2 {
			t.Errorf("%s: version %d", filepath.Base(f), version)
		}
		for _, d := range got {
			defs++
			ugens += len(d.UGens)
			if d.Name == "" {
				t.Errorf("%s: a definition with no name", filepath.Base(f))
			}
			// Every input must address something that exists: a real UGen
			// output, or a slot in the constant pool. An index past the end is
			// how a decoder that "works" produces a definition that crashes the
			// audio server.
			for ui, u := range d.UGens {
				for ii, in := range u.Inputs {
					if in.IsConstant() {
						if int(in.Index) >= len(d.Constants) {
							t.Errorf("%s ugen %d input %d: constant %d of %d",
								filepath.Base(f), ui, ii, in.Index, len(d.Constants))
						}
						continue
					}
					if int(in.UGenIndex) >= ui {
						t.Errorf("%s ugen %d input %d: refers to ugen %d, which is not earlier",
							filepath.Base(f), ui, ii, in.UGenIndex)
					}
				}
			}
		}
	}
	t.Logf("%d files, %d definitions, %d ugens decoded", len(files), defs, ugens)
}

// The test that earns the encoder: read what Moog wrote, write it back, and
// require the bytes unchanged. Not "equivalent" -- identical.
func TestReEncodeTheFirmwareByteForByte(t *testing.T) {
	files := synthdefFiles(t, firmwareDefs)
	for _, f := range files {
		raw, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		defs, _, err := DecodeSynthDefs(raw)
		if err != nil {
			t.Errorf("%s: %v", filepath.Base(f), err)
			continue
		}
		back, err := EncodeSynthDefs(defs)
		if err != nil {
			t.Errorf("%s: encode: %v", filepath.Base(f), err)
			continue
		}
		if !bytes.Equal(raw, back) {
			at := -1
			for i := 0; i < len(raw) && i < len(back); i++ {
				if raw[i] != back[i] {
					at = i
					break
				}
			}
			t.Errorf("%s: %d bytes in, %d out, first difference at %d",
				filepath.Base(f), len(raw), len(back), at)
		}
	}
	t.Logf("%d files re-encoded byte-for-byte", len(files))
}

// Our own definitions, compiled by a real sclang, must round-trip too. They use
// UGens the firmware's own defs never touch.
func TestReEncodeOurCompiledDefs(t *testing.T) {
	files := synthdefFiles(t, "engine")
	for _, f := range files {
		raw, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		defs, _, err := DecodeSynthDefs(raw)
		if err != nil {
			t.Fatalf("%s: %v", filepath.Base(f), err)
		}
		back, err := EncodeSynthDefs(defs)
		if err != nil {
			t.Fatalf("%s: %v", filepath.Base(f), err)
		}
		if !bytes.Equal(raw, back) {
			t.Errorf("%s did not round-trip", filepath.Base(f))
		}
	}
	t.Logf("%d of our own definitions re-encoded byte-for-byte", len(files))
}

func TestDecodeRejectsRubbish(t *testing.T) {
	for _, c := range []struct {
		name string
		b    []byte
	}{
		{"empty", nil},
		{"wrong magic", []byte("NOPEnope")},
		{"truncated header", []byte("SCgf\x00\x00")},
		{"bad version", append([]byte("SCgf"), 0, 0, 0, 99)},
	} {
		if _, _, err := DecodeSynthDefs(c.b); err == nil {
			t.Errorf("%s was accepted", c.name)
		}
	}
}

// A truncated file must be an error, not a panic and not a huge allocation.
func TestDecodeSurvivesTruncation(t *testing.T) {
	files := synthdefFiles(t, firmwareDefs)
	raw, err := os.ReadFile(files[0])
	if err != nil {
		t.Fatal(err)
	}
	for n := 0; n < len(raw); n += 7 {
		func() {
			defer func() {
				if p := recover(); p != nil {
					t.Fatalf("panic decoding the first %d bytes: %v", n, p)
				}
			}()
			_, _, _ = DecodeSynthDefs(raw[:n])
		}()
	}
}

func TestEncodeRefusesAnOverlongName(t *testing.T) {
	long := make([]byte, 300)
	for i := range long {
		long[i] = 'a'
	}
	_, err := EncodeSynthDefs([]SynthDef{{Name: string(long)}})
	if err == nil {
		t.Error("a 300-byte name was accepted; the format allows 255")
	}
}
