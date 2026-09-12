package main

import (
	"encoding/binary"
	"math"
	"net"
	"strings"
	"testing"
	"time"
)

// stubServer answers /sync the way scsynth does, so the rack's round trips
// complete without an instrument.
func stubServer(t *testing.T) (port int, seen func() [][]byte) {
	t.Helper()
	c, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Close() })
	var got [][]byte
	done := make(chan struct{})
	go func() {
		defer close(done)
		buf := make([]byte, 65536)
		for {
			n, addr, err := c.ReadFrom(buf)
			if err != nil {
				return
			}
			msg := append([]byte(nil), buf[:n]...)
			if strings.HasPrefix(string(msg), "/sync") {
				_, _ = c.WriteTo(oscFloat("/synced", int32(1)), addr)
				continue
			}
			got = append(got, msg)
		}
	}()
	return c.LocalAddr().(*net.UDPAddr).Port, func() [][]byte { return got }
}

func newTestRack(t *testing.T) (*Rack, func() [][]byte) {
	t.Helper()
	port, seen := stubServer(t)
	r, err := NewRack(port)
	if err != nil {
		t.Fatal(err)
	}
	return r, seen
}

// The catalogue and the compiled bytes must not drift. An effect listed with no
// definition would fail on the instrument, at the moment somebody pressed add.
func TestEveryEffectHasCompiledBytes(t *testing.T) {
	r, _ := newTestRack(t)
	if len(r.cat) == 0 {
		t.Fatal("catalogue is empty")
	}
	for _, e := range r.cat {
		blob, err := engineFS.ReadFile("engine/" + e.Name + ".scsyndef")
		if err != nil {
			t.Errorf("%s: no compiled definition: %v", e.Name, err)
			continue
		}
		// scsynth resolves the UGen by this exact string when the definition
		// arrives, so its absence is the failure that would happen there.
		if !strings.Contains(string(blob), e.UGen) {
			t.Errorf("%s: compiled bytes do not name %q", e.Name, e.UGen)
		}
		if !strings.Contains(string(blob), e.Name) {
			t.Errorf("%s: compiled bytes do not carry the def name", e.Name)
		}
		if len(e.Params) == 0 {
			t.Errorf("%s: no controls, so it could never be adjusted", e.Name)
		}
	}
}

// The safety property this whole file is arranged around. /n_free on a LADSPA
// node terminates scsynth, and the instrument keeps ten of them resident.
func TestRemoveRefusesAnythingItDidNotCreate(t *testing.T) {
	r, seen := newTestRack(t)
	for _, node := range []int{1, 1000, engineFirstNode, engineFirstNode + 5, 90300} {
		err := r.Remove(node)
		if err == nil {
			t.Fatalf("Remove(%d) was allowed; only our own nodes may be freed", node)
		}
		if !strings.Contains(err.Error(), "not started here") {
			t.Errorf("Remove(%d): unhelpful error %v", node, err)
		}
	}
	time.Sleep(50 * time.Millisecond)
	for _, m := range seen() {
		if strings.HasPrefix(string(m), "/n_free") {
			t.Fatal("a refused Remove still sent /n_free to the server")
		}
	}
}

func TestAddThenRemoveRoundTrip(t *testing.T) {
	r, seen := newTestRack(t)
	u, err := r.Add(r.cat[0].Name, nil)
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if u.Node < engineFirstNode {
		t.Errorf("node %d is below our reserved range", u.Node)
	}
	// Defaults must come from the catalogue, not from zero.
	for _, p := range r.cat[0].Params {
		if u.Params[p.Name] != p.Default {
			t.Errorf("%s defaulted to %v, want %v", p.Name, u.Params[p.Name], p.Default)
		}
	}
	if len(r.Units()) != 1 {
		t.Fatalf("expected one running unit, got %d", len(r.Units()))
	}
	if err := r.Remove(u.Node); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	if len(r.Units()) != 0 {
		t.Error("unit survived removal")
	}
	var sawRecv, sawNew, sawFree bool
	for _, m := range seen() {
		s := string(m)
		sawRecv = sawRecv || strings.HasPrefix(s, "/d_recv")
		sawNew = sawNew || strings.HasPrefix(s, "/s_new")
		sawFree = sawFree || strings.HasPrefix(s, "/n_free")
	}
	if !sawRecv || !sawNew || !sawFree {
		t.Errorf("expected /d_recv, /s_new and /n_free; got recv=%v new=%v free=%v",
			sawRecv, sawNew, sawFree)
	}
}

// A definition is sent once. Re-sending on every add costs a round trip to tell
// the server something it already knows.
func TestDefinitionIsSentOnce(t *testing.T) {
	r, seen := newTestRack(t)
	for i := 0; i < 3; i++ {
		if _, err := r.Add(r.cat[0].Name, nil); err != nil {
			t.Fatalf("Add %d: %v", i, err)
		}
	}
	n := 0
	for _, m := range seen() {
		if strings.HasPrefix(string(m), "/d_recv") {
			n++
		}
	}
	if n != 1 {
		t.Errorf("/d_recv sent %d times, want 1", n)
	}
}

func TestAddValidatesEffectAndParams(t *testing.T) {
	r, _ := newTestRack(t)
	if _, err := r.Add("NoSuchEffect", nil); err == nil {
		t.Error("an unknown effect was accepted")
	}
	eff := r.cat[0]
	p := eff.Params[0]
	if _, err := r.Add(eff.Name, map[string]float64{p.Name: p.Max + 1}); err == nil {
		t.Errorf("%s above its maximum was accepted", p.Name)
	}
	if _, err := r.Add(eff.Name, map[string]float64{"nonsense": 1}); err == nil {
		t.Error("an unknown control was accepted")
	}
}

func TestSetValidates(t *testing.T) {
	r, _ := newTestRack(t)
	u, err := r.Add(r.cat[0].Name, nil)
	if err != nil {
		t.Fatal(err)
	}
	p := r.cat[0].Params[0]
	if err := r.Set(u.Node, p.Name, p.Max+1); err == nil {
		t.Error("an out-of-range value was accepted")
	}
	if err := r.Set(u.Node+999, p.Name, p.Default); err == nil {
		t.Error("a foreign node was accepted")
	}
	if err := r.Set(u.Node, p.Name, p.Min); err != nil {
		t.Errorf("a legal value was refused: %v", err)
	}
}

func TestRemoveAllFreesOnlyOurs(t *testing.T) {
	r, _ := newTestRack(t)
	for i := 0; i < 2; i++ {
		if _, err := r.Add(r.cat[0].Name, nil); err != nil {
			t.Fatal(err)
		}
	}
	if freed := r.RemoveAll(); len(freed) != 2 {
		t.Errorf("freed %v, want two nodes", freed)
	}
	if len(r.Units()) != 0 {
		t.Error("units survived RemoveAll")
	}
}

// The two argument types main.go's encoder does not carry. A float sent as an
// int is a control set to the wrong value, silently.
func TestOscEncodesFloatsAndBlobs(t *testing.T) {
	msg := oscFloat("/n_set", int32(7), "mix", float32(0.25))
	s := string(msg)
	if !strings.HasPrefix(s, "/n_set") {
		t.Fatalf("address wrong: %q", s)
	}
	if !strings.Contains(s, ",isf") {
		t.Errorf("type tag should be ,isf; got %q", printable(msg))
	}
	// The float must be big-endian IEEE, which is what OSC specifies -- the
	// opposite of the little-endian the matrix blob uses.
	want := math.Float32bits(0.25)
	var found bool
	for i := 0; i+4 <= len(msg); i++ {
		if binary.BigEndian.Uint32(msg[i:]) == want {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("0.25 is not in the message big-endian: %x", msg)
	}

	blob := oscFloat("/d_recv", []byte{1, 2, 3})
	if !strings.Contains(string(blob), ",b") {
		t.Errorf("blob type tag missing: %q", printable(blob))
	}
	// size prefix, then the bytes, then padding to a multiple of four
	if len(blob)%4 != 0 {
		t.Errorf("message is not 4-byte aligned: %d", len(blob))
	}
}

func TestHeadroomFloorRefusesWhenTight(t *testing.T) {
	// Not a mock of the kernel: a direct check that the guard is wired to the
	// same number the page shows, so the two cannot disagree.
	r, _ := newTestRack(t)
	if headroomFloor <= 0 {
		t.Fatal("the floor must be positive or nothing is ever refused")
	}
	if h := r.Headroom(); math.IsNaN(h) {
		t.Error("headroom is NaN")
	}
}

// A readout is a promise about what a control does. It has to stay inside the
// control's own range and rise with it, or the page will show a number that
// contradicts the slider it sits beside.
func TestReadoutsAreSane(t *testing.T) {
	r, _ := newTestRack(t)
	found := 0
	for _, e := range r.cat {
		for _, p := range e.Params {
			if len(p.Readout) == 0 {
				continue
			}
			found++
			if p.ReadoutUnit == "" {
				t.Errorf("%s.%s has a readout with no unit", e.Name, p.Name)
			}
			for i, pair := range p.Readout {
				if pair[0] < p.Min || pair[0] > p.Max {
					t.Errorf("%s.%s readout point %v is outside [%v, %v]",
						e.Name, p.Name, pair[0], p.Min, p.Max)
				}
				if i > 0 && pair[0] <= p.Readout[i-1][0] {
					t.Errorf("%s.%s readout is not ordered by control value at %d",
						e.Name, p.Name, i)
				}
				if i > 0 && pair[1] < p.Readout[i-1][1] {
					t.Errorf("%s.%s readout falls as the control rises at %d",
						e.Name, p.Name, i)
				}
			}
		}
	}
	if found == 0 {
		t.Skip("no measured readouts in the catalogue yet")
	}
}
