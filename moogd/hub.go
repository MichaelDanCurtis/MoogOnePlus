package main

// Serving the real Vox UI from the instrument.
//
// The UI is unchanged. It speaks a JSON-over-WebSocket protocol with 101 message
// types, and its `handle` is a switch that ignores anything it does not know -- so a
// server can implement a useful subset and the page degrades rather than breaks.
// This implements the always-on ones: `status`, and `panel.screen` for the display.
//
// `panel.screen` carries a whole-frame PNG, which is the shape the UI already
// understands. The tile diffing is still doing the work that matters: it decides
// WHETHER to send. A screen nobody is touching costs one mmap copy and a row-wise
// compare -- about 25 ms on the idle core, and no traffic at all. Sending only the
// changed tiles would be better still, and needs a change to the UI, so it is not
// what this does.

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type hub struct {
	mu      sync.Mutex
	clients map[*wsConn]bool
}

var clients = &hub{clients: map[*wsConn]bool{}}

func (h *hub) add(c *wsConn) {
	h.mu.Lock()
	h.clients[c] = true
	h.mu.Unlock()
}

func (h *hub) drop(c *wsConn) {
	h.mu.Lock()
	delete(h.clients, c)
	h.mu.Unlock()
	c.Close()
}

func (h *hub) broadcast(v any) {
	b, err := json.Marshal(v)
	if err != nil {
		return
	}
	h.mu.Lock()
	targets := make([]*wsConn, 0, len(h.clients))
	for c := range h.clients {
		targets = append(targets, c)
	}
	h.mu.Unlock()
	for _, c := range targets {
		if err := c.WriteText(b); err != nil {
			h.drop(c)
		}
	}
}

func (h *hub) count() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return len(h.clients)
}

// statusMessage is what lights the connection dots at the top of the page.
func statusMessage(scPort int) map[string]any {
	_, err := queryStatus(scPort, 1500*time.Millisecond)
	return map[string]any{
		"type":     "status",
		"sc":       err == nil,
		"midi_in":  false,
		"midi_out": false,
		"meters": map[string]any{
			"state": "untested",
			"note":  "served by the instrument; meters not yet wired on-box",
		},
	}
}

func wsHandler(scPort int) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		c, err := wsAccept(w, r)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		clients.add(c)
		log.Printf("client connected (%d now)", clients.count())
		defer func() {
			clients.drop(c)
			log.Printf("client gone (%d left)", clients.count())
		}()

		// Greet with status, and a full screen so the display appears at once.
		if b, err := json.Marshal(statusMessage(scPort)); err == nil {
			_ = c.WriteText(b)
		}
		pushScreen(c, true)

		for {
			raw, err := c.ReadText()
			if err != nil {
				return
			}
			var msg map[string]any
			if json.Unmarshal(raw, &msg) != nil {
				continue
			}
			// The page asks for fx.list, route.list and controls.list on open. None
			// is implemented on-box yet; answering status keeps the header honest
			// and the switch in the UI ignores what it does not get.
			if t, _ := msg["type"].(string); t == "status" || t == "" {
				if b, err := json.Marshal(statusMessage(scPort)); err == nil {
					_ = c.WriteText(b)
				}
			}
		}
	}
}

// pushScreen sends a whole-frame PNG, but only when the tile diff says something
// moved -- or when `full` is set, which a newly connected client needs.
func pushScreen(c *wsConn, full bool) {
	png, changed, err := screen.framePNG(full)
	if err != nil || (changed == 0 && !full) {
		return
	}
	b, err := json.Marshal(map[string]any{
		"type": "panel.screen", "png": png, "width": fbW, "height": fbH,
	})
	if err != nil {
		return
	}
	if c != nil {
		_ = c.WriteText(b)
		return
	}
	clients.mu.Lock()
	targets := make([]*wsConn, 0, len(clients.clients))
	for cc := range clients.clients {
		targets = append(targets, cc)
	}
	clients.mu.Unlock()
	for _, cc := range targets {
		if err := cc.WriteText(b); err != nil {
			clients.drop(cc)
		}
	}
}

func serveUI(dir string) http.HandlerFunc {
	fs := http.FileServer(http.Dir(dir))
	return func(w http.ResponseWriter, r *http.Request) {
		if _, err := os.Stat(filepath.Join(dir, "index.html")); err != nil {
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			fmt.Fprintf(w, "<pre>No UI found at %s.\n\nCopy the Vox static files there:\n"+
				"  ssh root@&lt;ip&gt; 'mkdir -p %s'\n"+
				"  tar cf - -C src/moogone/vox/static . | ssh root@&lt;ip&gt; 'tar xf - -C %s'\n\n"+
				"The status API is up regardless: <a href=\"/api/status\">/api/status</a>"+
				"  <a href=\"/bench\">/bench</a></pre>", dir, dir, dir)
			return
		}
		fs.ServeHTTP(w, r)
	}
}

// screenLoop pushes the display when it changes, and never when it does not.
func screenLoop(period time.Duration) {
	for {
		time.Sleep(period)
		if clients.count() == 0 {
			continue // nobody watching: do not even read the framebuffer
		}
		pushScreen(nil, false)
	}
}

func statusLoop(scPort int, period time.Duration) {
	for {
		time.Sleep(period)
		if clients.count() > 0 {
			clients.broadcast(statusMessage(scPort))
		}
	}
}
