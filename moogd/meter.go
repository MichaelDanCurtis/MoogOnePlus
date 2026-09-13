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

	// A FRESH node id each time it is started.
	//
	// Reusing one id means a free followed immediately by a create races: if
	// the /n_free has not been processed, the /s_new is refused as a duplicate,
	// the meter silently does not exist, and it reads the floor while something
	// is playing. That happened, and it read -86 dB against an expected -6.
	node int32
}

func NewMeter(scPort int) *Meter { return &Meter{scPort: scPort, node: meterNode} }

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
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", m.scPort))
	if err != nil {
		return err
	}
	defer c.Close()
	// Ask, do not remember. `running` is this process's belief; the node is the
	// fact. An engine reset, an S42sc restart, or an /n_free from anywhere else
	// removes the synth and leaves the flag set -- and then Read() returns the
	// control bus's last value as a live measurement, because a control bus
	// holds what it held. That is worse than an error: it reported the main
	// output frozen at -82.8 dB while /api/scan showed those same buses moving
	// between -37 and -50, and a whole evening was spent on a dead audio path
	// that was really a dead meter.
	if m.running && m.alive(c) {
		return nil
	}
	m.running = false
	blob, err := engineFS.ReadFile("engine/voxMeter.scsyndef")
	if err != nil {
		return err
	}
	if _, err := c.Write(oscFloat("/d_recv", blob)); err != nil {
		return err
	}
	// /d_recv is an ASYNCHRONOUS command: scsynth parses the definition on a
	// background thread and the /s_new below can otherwise arrive before the
	// name is registered, in which case it fails and the meter silently does
	// not exist. That produced a meter reading the floor while a 440 Hz tone at
	// -6 dBFS was playing -- intermittently, which is worse than never.
	if _, err := c.Write(oscFloat("/sync", int32(1))); err != nil {
		return err
	}
	_ = c.SetReadDeadline(time.Now().Add(3 * time.Second))
	ack := make([]byte, 512)
	for {
		n, err := c.Read(ack)
		if err != nil {
			return fmt.Errorf("scsynth did not acknowledge the meter definition: %w", err)
		}
		if n >= 7 && string(ack[:7]) == "/synced" {
			break
		}
	}
	// Tail of the root group: after everything, including anything the Engine
	// tab has added, so the meter reads what actually leaves.
	m.node++
	if _, err := c.Write(oscFloat("/s_new", "voxMeter", m.node, int32(1), int32(0),
		"left", float32(MainLeftBus), "right", float32(MainRightBus),
		"out", float32(meterBus))); err != nil {
		return err
	}
	m.running = true
	// Let it run before anybody reads it. The control buses hold whatever they
	// held before the synth existed, so a read taken in the same breath as the
	// /s_new returns the PREVIOUS state -- silence, usually, which reads as a
	// working meter reporting a quiet instrument. At 48 kHz with a block of 128
	// a control period is 2.7 ms; Amplitude.kr's 10 ms attack is the real wait.
	time.Sleep(200 * time.Millisecond)
	return nil
}

// alive asks scsynth whether the metering node still exists. No /n_info back
// within the deadline means it is gone, whatever this process believes.
func (m *Meter) alive(c net.Conn) bool {
	if _, err := c.Write(oscFloat("/n_query", m.node)); err != nil {
		return false
	}
	_ = c.SetReadDeadline(time.Now().Add(300 * time.Millisecond))
	buf := make([]byte, 1024)
	for {
		n, err := c.Read(buf)
		if err != nil {
			return false // deadline, or /fail: either way there is no node
		}
		if n >= 7 && string(buf[:7]) == "/n_info" {
			return true
		}
		// Anything else in the socket is somebody else's reply -- /done from an
		// earlier /d_recv sits here routinely. Keep reading until the deadline.
	}
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
// Invalidate forgets the running meter so the next read re-creates it.
//
// Nodes run in group order, and a meter that was started before a synth is
// computed BEFORE it -- so it reads the bus as it stood a block earlier. On
// 2026-09-13 that showed -90 dB while a synth added seconds before was writing
// a 440 Hz tone to the very bus being metered.
//
// /n_order with addAction 1 onto the root group looked like the tidy fix and
// silently did not move the node; re-creating it does, measurably (-26.7 dB
// against an expected peak of -26.02). So the rack calls this after any change
// and the meter rebuilds itself at the tail, where a meter has to be.
func (m *Meter) Invalidate() {
	// It has to be FREED, not merely forgotten. ensure() re-sends /s_new with
	// the same node id, and scsynth refuses a duplicate -- so simply clearing
	// the flag leaves the old node exactly where it was, still ahead of the
	// synth it is supposed to be measuring. That was the first attempt at this
	// fix and it read the floor while a 440 Hz tone was playing.
	_ = m.Stop()
}

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
	_, err = c.Write(oscFloat("/n_free", m.node))
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

// -- scanning every output bus -------------------------------------------------

const (
	scanNode = 96901
	scanBus  = 14100
	scanN    = 16
)

// Scan reports the level on the first sixteen audio buses.
//
// The main pair is 7 and 0, and a meter on those is what this file was built
// for. But a level of -86 dB there, at a moment the instrument was audibly
// making a noise, means the assumption needs checking rather than defending.
// Sixteen buses is cheap and answers it outright.
func (m *Meter) Scan() ([]float64, error) {
	blob, err := engineFS.ReadFile("engine/voxScan.scsyndef")
	if err != nil {
		return nil, err
	}
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", m.scPort))
	if err != nil {
		return nil, err
	}
	defer c.Close()
	if _, err := c.Write(oscFloat("/d_recv", blob)); err != nil {
		return nil, err
	}
	time.Sleep(120 * time.Millisecond)
	if _, err := c.Write(oscFloat("/s_new", "voxScan", int32(scanNode), int32(1), int32(0),
		"out", float32(scanBus))); err != nil {
		return nil, err
	}
	time.Sleep(500 * time.Millisecond) // let the envelopes settle
	if _, err := c.Write(oscFloat("/c_getn", int32(scanBus), int32(scanN))); err != nil {
		return nil, err
	}
	// /d_recv answers with /done, and that datagram is still in the socket when
	// the next reply is read -- the trap src/moogone/record.py documents. Read
	// until the answer to the question actually asked turns up.
	_ = c.SetReadDeadline(time.Now().Add(3 * time.Second))
	buf := make([]byte, 2048)
	var vals []float64
	for {
		n, err := c.Read(buf)
		if err != nil {
			return nil, fmt.Errorf("no /c_setn from scsynth: %w", err)
		}
		vals, err = parseCSetn(buf[:n])
		if err == nil {
			break
		}
	}
	// Free it. A scan is a one-off question and the synth has no reason to
	// outlive the answer -- the first version left one running on every call,
	// which /api/tree then showed sitting in the root group forever.
	_, _ = c.Write(oscFloat("/n_free", int32(scanNode)))
	out := make([]float64, len(vals))
	for i, v := range vals {
		out[i] = amp2db(v)
	}
	return out, nil
}

func scanHandler(m *Meter) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		v, err := m.Scan()
		if err != nil {
			httpError(w, http.StatusInternalServerError, err)
			return
		}
		writeJSON(w, map[string]any{"buses_db": v})
	}
}
