package main

// Asking las-sc a question.
//
// The voice allocator lives behind the XMOS and Linux cannot see MIDI, so how
// many voices are sounding has been unobservable all session -- every stuck-note
// finding so far has been inferred from a level meter. But las-sc's own OSC
// surface carries `/info/voice-count` and `/v/voices`, and it listens on
// 127.0.0.1:9300, which moogd can reach.
//
// READ ONLY, and enforced rather than intended. Only addresses under a small
// allowlist of prefixes may be sent, because this is one UDP write away from
// the process that owns the voice cards, and docs/DANGER.md is a list of what
// happens when something writes there by accident.

import (
	"fmt"
	"net"
	"net/http"
	"strings"
	"time"
)

// readOnlyPrefixes are the only addresses this will send. `/info/` and `/v/`
// are queries; nothing here sets anything.
var readOnlyPrefixes = []string{"/info/", "/v/"}

func lasscAllowed(addr string) bool {
	for _, p := range readOnlyPrefixes {
		if strings.HasPrefix(addr, p) {
			return true
		}
	}
	return false
}

// askLassc sends one query and returns whatever comes back, if anything.
//
// las-sc is documented as replying to the front panel rather than to us, so a
// silent answer is an expected outcome and not an error worth shouting about.
func askLassc(addr string, timeout time.Duration) (string, []byte, error) {
	if !lasscAllowed(addr) {
		return "", nil, fmt.Errorf("%q is not one of the read-only prefixes %v",
			addr, readOnlyPrefixes)
	}
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", lasscPort))
	if err != nil {
		return "", nil, err
	}
	defer c.Close()
	if _, err := c.Write(oscFloat(addr)); err != nil {
		return "", nil, err
	}
	_ = c.SetReadDeadline(time.Now().Add(timeout))
	buf := make([]byte, 8192)
	n, err := c.Read(buf)
	if err != nil {
		return "", nil, fmt.Errorf("no reply: %w", err)
	}
	reply, _, _ := oscString(buf[:n])
	return reply, buf[:n], nil
}

func lasscHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		addr := r.URL.Query().Get("addr")
		if addr == "" {
			addr = "/info/voice-count"
		}
		reply, raw, err := askLassc(addr, 2*time.Second)
		if err != nil {
			writeJSON(w, map[string]any{"asked": addr, "answered": false,
				"why": err.Error()})
			return
		}
		args, aerr := oscArgs(raw[len(reply)+pad(len(reply)+1)+1:])
		out := map[string]any{"asked": addr, "answered": true, "reply": reply,
			"printable": printable(raw)}
		if aerr == nil {
			out["args"] = args
		}
		writeJSON(w, out)
	}
}
