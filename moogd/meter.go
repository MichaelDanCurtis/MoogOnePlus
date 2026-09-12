package main

// A meter on the main pair, inside the audio server.
//
// This exists because of docs/INCIDENT-2026-09-12-runaway.md. A sound on the
// instrument would not stop; it was chased through four theories, three of them
// wrong, over an evening -- while the signal itself sat observable inside
// `scsynth` the whole time and nothing looked at it.
//
// Every voice on this machine passes through the server on its way out. The
// analog voices arrive on bus 12 from the ADC, the digital effects are already
// there, and buses 7 and 0 are the main pair after all of it. So this one
// measurement sees everything the instrument makes.
//
// The reading is taken through CONTROL BUSES rather than SendReply, and that is
// deliberate. SendReply pushes to whichever clients have registered for
// notifications, which means a socket that must stay open and a registration
// that must survive a server restart. `/c_getn` is a question with an answer,
// exactly like `/status`, and it works the moment it is asked -- including
// after the engine has been restarted underneath it.
//
// Two time constants are reported. The fast pair is a meter. The slow pair has
// a three-second release, so a level that is *growing* separates from one that
// is merely loud -- which is precisely the question that took an evening.

import (
	"encoding/binary"
	"fmt"
	"math"
	"net"
	"net/http"
	"sync"
	"time"
)

// meterNode and meterBus sit clear of everything: the instrument's own nodes are
// in the low thousands, this project's other synths run 90210..96000, and
// scsynth's default 16384 control buses leave the high end untouched.
const (
	meterNode = 96900
	meterBus  = 14000
	meterVals = 4
)

// The main output pair, which is NOT a consecutive pair.
//
// synthdefs.scd:564-565 writes Out.ar(7, main[0]) and Out.ar(0, main[1]), so
// left is bus 7 and right is bus 0. Three modules in this repository had it as
// buses 0 and 1 -- main-right and SUB-right -- and commit 9c62c1d fixed them.
// They are named here so a fourth cannot quietly repeat it.
const (
	MainLeftBus  = 7
	MainRightBus = 0
)

type Meter struct {
	mu      sync.Mutex
	scPort  int
	running bool
}

func NewMeter(scPort int) *Meter { return &Meter{scPort: scPort} }

// Levels is one reading of the main pair.
type Levels struct {
	LeftDB      float64 `json:"left_db"`
	RightDB     float64 `json:"right_db"`
	LeftSlowDB  float64 `json:"left_slow_db"`
	RightSlowDB float64 `json:"right_slow_db"`
	// Rising is the slow envelope above the fast one: a signal still building
	// rather than one already decaying.
	Rising bool      `json:"rising"`
	At     time.Time `json:"at"`
}

// ensure starts the metering synth, and restarts it if the engine has been
// restarted underneath us.
//
// Cheap to call repeatedly: a duplicate /s_new on the same node id is answered
// by scsynth with a failure that costs nothing, so correctness here does not
// depend on this process's memory of what it did.
func (m *Meter) ensure() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.running {
		return nil
	}
	blob, err := engineFS.ReadFile("engine/voxMeter.scsyndef")
	if err != nil {
		return err
	}
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", m.scPort))
	if err != nil {
		return err
	}
	defer c.Close()
	if _, err := c.Write(oscFloat("/d_recv", blob)); err != nil {
		return err
	}
	// Tail of the root group: after everything, including anything the Engine
	// tab has added, so the meter reads what actually leaves.
	if _, err := c.Write(oscFloat("/s_new", "voxMeter", int32(meterNode), int32(1), int32(0),
		"left", float32(MainLeftBus), "right", float32(MainRightBus),
		"out", float32(meterBus))); err != nil {
		return err
	}
	m.running = true
	return nil
}

// Read asks the server for the four control buses the meter writes.
func (m *Meter) Read() (*Levels, error) {
	if err := m.ensure(); err != nil {
		return nil, err
	}
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", m.scPort))
	if err != nil {
		return nil, err
	}
	defer c.Close()
	if _, err := c.Write(oscFloat("/c_getn", int32(meterBus), int32(meterVals))); err != nil {
		return nil, err
	}
	_ = c.SetReadDeadline(time.Now().Add(2 * time.Second))
	buf := make([]byte, 512)
	n, err := c.Read(buf)
	if err != nil {
		// A silent server is usually a restarted one; forget the synth so the
		// next call puts it back rather than reading a bus nobody writes.
		m.mu.Lock()
		m.running = false
		m.mu.Unlock()
		return nil, fmt.Errorf("scsynth did not answer the meter: %w", err)
	}
	vals, err := parseCSetn(buf[:n])
	if err != nil {
		return nil, err
	}
	if len(vals) < meterVals {
		return nil, fmt.Errorf("meter returned %d values, want %d", len(vals), meterVals)
	}
	l := &Levels{
		LeftDB: amp2db(vals[0]), RightDB: amp2db(vals[1]),
		LeftSlowDB: amp2db(vals[2]), RightSlowDB: amp2db(vals[3]),
		At: time.Now(),
	}
	// Growing, not merely loud. The slow envelope lags the fast one on the way
	// up and leads it on the way down, so slow < fast means still building.
	l.Rising = math.Max(vals[0], vals[1]) > math.Max(vals[2], vals[3])*1.05
	return l, nil
}

// Stop frees the metering synth.
func (m *Meter) Stop() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.running {
		return nil
	}
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", m.scPort))
	if err != nil {
		return err
	}
	defer c.Close()
	_, err = c.Write(oscFloat("/n_free", int32(meterNode)))
	m.running = false
	return err
}

// parseCSetn pulls the floats out of scsynth's answer to /c_getn.
//
// The reply is /c_setn with the bus index, the count, then that many floats.
// OSC is big-endian throughout, which is worth saying out loud in this
// repository: the modulation matrix blob on the other wire is little-endian.
func parseCSetn(b []byte) ([]float64, error) {
	addr, rest, ok := oscString(b)
	if !ok {
		return nil, fmt.Errorf("malformed reply")
	}
	if addr != "/c_setn" {
		return nil, fmt.Errorf("expected /c_setn, got %q", addr)
	}
	tags, rest, ok := oscString(rest)
	if !ok || len(tags) < 1 || tags[0] != ',' {
		return nil, fmt.Errorf("no type tag in reply")
	}
	var out []float64
	for _, t := range tags[1:] {
		if len(rest) < 4 {
			break
		}
		switch t {
		case 'i':
			rest = rest[4:] // bus index, then count
		case 'f':
			out = append(out, float64(math.Float32frombits(binary.BigEndian.Uint32(rest))))
			rest = rest[4:]
		default:
			return out, nil
		}
	}
	return out, nil
}

// oscString reads one padded OSC string and returns the remainder.
func oscString(b []byte) (string, []byte, bool) {
	for i := 0; i < len(b); i++ {
		if b[i] != 0 {
			continue
		}
		end := i + pad(i+1) + 1
		if end > len(b) {
			return "", nil, false
		}
		return string(b[:i]), b[end:], true
	}
	return "", nil, false
}

func amp2db(a float64) float64 {
	if a <= 1e-9 {
		return -120
	}
	return 20 * math.Log10(a)
}

func meterHandler(m *Meter) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("stop") != "" {
			if err := m.Stop(); err != nil {
				httpError(w, http.StatusInternalServerError, err)
				return
			}
			writeJSON(w, map[string]any{"stopped": true})
			return
		}
		l, err := m.Read()
		if err != nil {
			httpError(w, http.StatusInternalServerError, err)
			return
		}
		writeJSON(w, l)
	}
}
