package main

// Getting back to a known state.
//
// Two levels, because they carry very different consequences and collapsing
// them into one button would hide that.
//
// SOFT frees every node this process created and rebuilds the meter. It is the
// one to reach for, it is instant, and it cannot hurt anything: nothing is
// freed that we did not create, which matters because /n_free on a LADSPA node
// terminates scsynth and the instrument keeps ten of them resident at all
// times.
//
// ENGINE runs /etc/init.d/S42sc restart, which is what actually cleared the
// stuck note on 2026-09-13 when nothing else would. It is not hidden, because
// the operator already does it over SSH and pretending otherwise helps nobody.
// But it is not the default either, for two reasons that the UI states rather
// than buries:
//
//  1. It re-runs the BOOT-TIME FIRMWARE CHECK. las-sc is restarted with
//     --vcfw and --vxfw, and its own help says: "Voice card firmware file. If
//     not given, voice cards are not checked or updated." So this checks, and
//     would update on a mismatch. The versions match and nothing is written --
//     and this is exactly what happens at every power-on -- but a bricked voice
//     card has no software recovery and the boards are unobtainable, so it is
//     said out loud.
//
//  2. Audio stops until a preset is loaded. las-frontend does not re-push its
//     state to the new engine: measured on 2026-09-13, ugens came back 726 ->
//     496 and the keyboard was silent until a preset was selected.
//
// There is no safe middle. A mass /g_freeAll would take Moog's own nodes with
// it, and freeing a LADSPA node kills the server.

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"time"
)

// FreeDefs removes the SynthDefs this server loaded.
//
// Safe in a way that freeing a NODE is not: /d_free only removes the recipe,
// and a synth already running from it carries on untroubled. Doing this for
// nodes would be fatal -- see engine.go.
func (r *Rack) FreeDefs() int {
	r.mu.Lock()
	names := make([]string, 0, len(r.ourDefs))
	for n := range r.ourDefs {
		names = append(names, n)
	}
	r.ourDefs = map[string]bool{}
	r.loaded = map[string]bool{}
	r.mu.Unlock()
	sort.Strings(names)
	freed := 0
	for _, n := range names {
		if err := r.call(oscFloat("/d_free", n), false); err == nil {
			freed++
		}
	}
	return freed
}

// Forget drops our record of what is running, after something external has
// removed it.
func (r *Rack) Forget() int {
	r.mu.Lock()
	n := len(r.units)
	r.units = map[int]*Unit{}
	r.mu.Unlock()
	r.changed()
	return n
}

type resetResult struct {
	Level    string  `json:"level"`
	Freed    []int   `json:"freed,omitempty"`
	Defs     int     `json:"defs_freed,omitempty"`
	Forgot   int     `json:"forgot,omitempty"`
	Output   string  `json:"output,omitempty"`
	Headroom float64 `json:"headroom"`
	Note     string  `json:"note"`
}

func resetHandler(r *Rack, m *Meter) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		var body struct {
			Level string `json:"level"`
		}
		_ = json.NewDecoder(req.Body).Decode(&body)

		switch body.Level {
		case "", "soft":
			freed := r.RemoveAll()
			defs := r.FreeDefs()
			m.Invalidate()
			writeJSON(w, resetResult{
				Level: "soft", Freed: freed, Defs: defs, Headroom: r.Headroom(),
				Note: "everything this server started has been freed. Moog's own " +
					"effects and voices are untouched.",
			})

		case "engine":
			// NOT CombinedOutput. The init script backgrounds las-sc with `&`,
			// and a backgrounded child inherits the pipes -- so CombinedOutput
			// waits for las-sc to exit, which is never. The first version of
			// this hung the request for good and left the script parented to a
			// blocked handler. Output goes to a file instead, so the command has
			// no pipe to outlive, and a context bounds it either way.
			ctx, cancel := context.WithTimeout(req.Context(), 90*time.Second)
			defer cancel()
			logPath := filepath.Join(os.TempDir(), "moogd-engine-restart.log")
			lf, ferr := os.Create(logPath)
			cmd := exec.CommandContext(ctx, "/etc/init.d/S42sc", "restart")
			if ferr == nil {
				cmd.Stdout, cmd.Stderr = lf, lf
			}
			err := cmd.Run()
			if lf != nil {
				_ = lf.Close()
			}
			var out []byte
			if b, rerr := os.ReadFile(logPath); rerr == nil {
				out = b
			}
			forgot := r.Forget()
			m.Invalidate()
			if err != nil {
				httpError(w, http.StatusInternalServerError,
					fmt.Errorf("S42sc restart: %w (%s)", err, printable(out)))
				return
			}
			// Let it finish coming up before anybody reads a meter off it.
			time.Sleep(2 * time.Second)
			writeJSON(w, resetResult{
				Level: "engine", Forgot: forgot, Output: printable(out),
				Headroom: r.Headroom(),
				Note: "the audio engine was restarted. Sound will not return until " +
					"you load a preset on the instrument: las-frontend does not " +
					"re-push its state to a new engine.",
			})

		default:
			httpError(w, http.StatusBadRequest,
				fmt.Errorf("level must be \"soft\" or \"engine\", not %q", body.Level))
		}
	}
}
