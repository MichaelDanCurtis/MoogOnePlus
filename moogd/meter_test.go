package main

import (
	"encoding/binary"
	"math"
	"strings"
	"testing"
)

// The reply parser is the part that can be silently wrong: a misread float is a
// level that looks plausible and is not. OSC is big-endian, which is worth
// pinning in a repository where the other wire format is little-endian.
func TestParseCSetn(t *testing.T) {
	want := []float32{0.5, 0.25, 0.125, 0.0625}
	args := []any{int32(meterBus), int32(len(want))}
	for _, v := range want {
		args = append(args, v)
	}
	got, err := parseCSetn(oscFloat("/c_setn", args...))
	if err != nil {
		t.Fatalf("parseCSetn: %v", err)
	}
	if len(got) != len(want) {
		t.Fatalf("got %d values, want %d", len(got), len(want))
	}
	for i := range want {
		if float32(got[i]) != want[i] {
			t.Errorf("value %d = %v, want %v", i, got[i], want[i])
		}
	}
}

func TestParseCSetnRejectsWrongReply(t *testing.T) {
	if _, err := parseCSetn(oscFloat("/status.reply", int32(1))); err == nil {
		t.Error("a reply to a different question was accepted")
	}
	if _, err := parseCSetn([]byte{1, 2, 3}); err == nil {
		t.Error("malformed bytes were accepted")
	}
}

// Reading a big-endian float as little-endian gives a number, not an error --
// which is exactly how a meter lies. This pins the byte order explicitly.
func TestCSetnIsBigEndian(t *testing.T) {
	msg := oscFloat("/c_setn", int32(meterBus), int32(1), float32(0.5))
	swapped := append([]byte(nil), msg...)
	// flip the last four bytes
	n := len(swapped)
	swapped[n-4], swapped[n-1] = swapped[n-1], swapped[n-4]
	swapped[n-3], swapped[n-2] = swapped[n-2], swapped[n-3]
	got, err := parseCSetn(swapped)
	if err != nil {
		t.Fatalf("parseCSetn: %v", err)
	}
	if len(got) == 1 && float32(got[0]) == 0.5 {
		t.Error("byte order is not being respected: a swapped payload read the same")
	}
}

func TestAmpToDB(t *testing.T) {
	for _, c := range []struct {
		amp  float64
		want float64
	}{
		{1.0, 0}, {0.5, -6.02}, {0.1, -20}, {0, -120}, {1e-12, -120},
	} {
		got := amp2db(c.amp)
		if math.Abs(got-c.want) > 0.05 {
			t.Errorf("amp2db(%v) = %.2f, want %.2f", c.amp, got, c.want)
		}
	}
}

// The main pair is not consecutive. Three modules in this repository once read
// buses 0 and 1 -- main-right and sub-right -- and this is the constant that
// stops a fourth doing it.
func TestMainBusesAreTheNonAdjacentPair(t *testing.T) {
	if MainLeftBus != 7 || MainRightBus != 0 {
		t.Fatalf("main pair is %d/%d, want 7/0 per synthdefs.scd:564-565",
			MainLeftBus, MainRightBus)
	}
}

func TestOscStringRoundTrip(t *testing.T) {
	for _, s := range []string{"/c_setn", "/a", "/longer/address/here", ""} {
		buf := append([]byte(s), 0)
		buf = append(buf, make([]byte, pad(len(buf)))...)
		buf = append(buf, 0xde, 0xad, 0xbe, 0xef)
		got, rest, ok := oscString(buf)
		if !ok {
			t.Fatalf("%q: not parsed", s)
		}
		if got != s {
			t.Errorf("got %q, want %q", got, s)
		}
		if len(rest) != 4 || binary.BigEndian.Uint32(rest) != 0xdeadbeef {
			t.Errorf("%q: remainder wrong: %x", s, rest)
		}
	}
}

// The meter is not an effect and must never appear as one.
func TestMeterIsNotInTheCatalogue(t *testing.T) {
	r, _ := newTestRack(t)
	for _, e := range r.cat {
		if strings.Contains(strings.ToLower(e.Name), "meter") {
			t.Errorf("the meter is listed as a user-addable effect: %s", e.Name)
		}
	}
	if _, err := engineFS.ReadFile("engine/voxMeter.scsyndef"); err != nil {
		t.Errorf("the meter has no compiled definition: %v", err)
	}
}
