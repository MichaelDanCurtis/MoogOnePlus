package main

// Recording the main pair to a file on the instrument.
//
// The meter answers "how loud, now". It cannot answer "what IS that" -- a
// pitch, a filter self-oscillating, a tremolo, an envelope that never closes.
// Polled over HTTP it tops out around 5 Hz, which on 2026-09-13 produced two
// contradictory pictures of the same fault: one trace showing a level holding
// flat for seven seconds, another showing it decaying to the floor in seven.
// Both were undersampled. This captures the actual audio instead.
//
// It also fixes a bug it inherits. src/moogone/synthdef.py's recorder is
// `In.ar(bus, 2)` -- two CONSECUTIVE buses -- and the main pair is 7 and 0.
// Every "main output" recording this project has taken has actually captured
// main-right and SUB-right. Commit 9c62c1d fixed exactly this in sampler.py,
// fm.py and makeup.py and missed the recorder. voxRecorder reads the two buses
// separately, because a single In.ar cannot express a non-adjacent pair.

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	recordNode = 96800
	// scsynth on this instrument runs with `-b 1026`, so valid buffer numbers
	// are 0..1025 and anything above that is simply refused. 1000 is the number
	// src/moogone/record.py has used successfully on this machine.
	recordBuffer = 1000
	recordRing   = 65536
)

type Recorder struct {
	mu     sync.Mutex
	scPort int
	dir    string
	active string
	bufnum int
}

func NewRecorder(scPort int, dir string) *Recorder {
	return &Recorder{scPort: scPort, dir: dir, bufnum: recordBuffer}
}

func (r *Recorder) send(msgs ...[]byte) error {
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", r.scPort))
	if err != nil {
		return err
	}
	defer c.Close()
	for _, m := range msgs {
		if _, err := c.Write(m); err != nil {
			return err
		}
		time.Sleep(30 * time.Millisecond) // let the server keep up with allocation
	}
	return nil
}

// Start opens a file and begins writing the main pair into it.
func (r *Recorder) Start(name string) (string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.active != "" {
		return "", fmt.Errorf("already recording to %s", r.active)
	}
	if strings.ContainsAny(name, "/\\") || !strings.HasSuffix(name, ".wav") {
		return "", fmt.Errorf("name must be a bare *.wav filename")
	}
	path := filepath.Join(r.dir, name)
	blob, err := engineFS.ReadFile("engine/voxRecorder.scsyndef")
	if err != nil {
		return "", err
	}
	err = r.send(
		oscFloat("/d_recv", blob),
		// A disk-writing buffer is a ring the server drains, not the whole take.
		oscFloat("/b_alloc", int32(r.bufnum), int32(recordRing), int32(2)),
		// leaveOpen = 1: the header is finished by /b_close, not by this call.
		oscFloat("/b_write", int32(r.bufnum), path, "wav", "float",
			int32(0), int32(0), int32(1)),
		oscFloat("/s_new", "voxRecorder", int32(recordNode), int32(1), int32(0),
			"buf", float32(r.bufnum),
			"left", float32(MainLeftBus), "right", float32(MainRightBus)),
	)
	if err != nil {
		return "", err
	}
	r.active = path
	return path, nil
}

// Stop closes the file. The order matters: the writer has to go before the
// buffer, or the last blocks are written into a buffer that is being freed.
func (r *Recorder) Stop() (string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.active == "" {
		return "", fmt.Errorf("not recording")
	}
	path := r.active
	err := r.send(
		oscFloat("/n_free", int32(recordNode)),
		oscFloat("/b_close", int32(r.bufnum)),
		oscFloat("/b_free", int32(r.bufnum)),
	)
	r.active = ""
	if err != nil {
		return path, err
	}
	return path, nil
}

func recordHandler(r *Recorder) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		q := req.URL.Query()
		switch {
		case q.Get("stop") != "":
			path, err := r.Stop()
			if err != nil {
				httpError(w, http.StatusBadRequest, err)
				return
			}
			var size int64
			if fi, err := os.Stat(path); err == nil {
				size = fi.Size()
			}
			writeJSON(w, map[string]any{"path": path, "bytes": size})
		default:
			name := q.Get("name")
			if name == "" {
				name = "take-" + strconv.FormatInt(time.Now().Unix(), 10) + ".wav"
			}
			path, err := r.Start(name)
			if err != nil {
				httpError(w, http.StatusBadRequest, err)
				return
			}
			writeJSON(w, map[string]any{"recording": path})
		}
	}
}
