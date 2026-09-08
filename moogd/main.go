// Command moogd is a proof that the Moog One can host its own control surface.
//
// The instrument has no interpreter of any kind -- no python, perl, lua or node --
// so anything that runs on it has to be a native binary. Built with CGO_ENABLED=0
// this is fully static: no libc, no libstdc++, and none of the ABI matching that
// building scsynth for this machine required (see tools/README-scsynth-jack.md).
//
// Running on the instrument rather than beside it removes the SSH transport that
// every remote feature currently depends on, and with it a whole class of bug this
// project has already hit: a framebuffer capture loop leaked on every reconnect, a
// screen feed that never noticed it had died, a HUD push that blocked for 8.9
// seconds a frame, and a 115 ms OSC round trip that is sub-millisecond here.
//
// Run it on cpu0, with the rest of userspace:
//
//	taskset -c 0 ./moogd -addr :8080
//
// cpu1 is isolated by isolcpus=1, and earlier versions of this comment concluded
// that made it a free core to put a web server on. It is the opposite: cpu1 is
// where scsynth's audio thread runs, at SCHED_FIFO 99, and the isolation exists
// to keep everything else off it. cpu0 carries the UI, las-sc and the network,
// and is where the spare capacity actually is. See docs/CORRECTIONS-2026-09-08.md.
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"log"
	"math"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

// -- the smallest OSC that can ask scsynth a question -------------------------

func pad(n int) int { return (4 - n%4) % 4 } // already-aligned blocks get no padding

func oscMessage(addr string, args ...any) []byte {
	out := append([]byte(addr), 0)
	out = append(out, make([]byte, pad(len(out)))...)
	tags := ","
	var body []byte
	for _, a := range args {
		switch v := a.(type) {
		case int32:
			tags += "i"
			var b [4]byte
			binary.BigEndian.PutUint32(b[:], uint32(v))
			body = append(body, b[:]...)
		case string:
			tags += "s"
			s := append([]byte(v), 0)
			body = append(body, append(s, make([]byte, pad(len(s)))...)...)
		}
	}
	t := append([]byte(tags), 0)
	out = append(out, append(t, make([]byte, pad(len(t)))...)...)
	return append(out, body...)
}

// Status is what /status.reply carries. The two CPU fields are always 0.0 on this
// firmware -- see docs, finding 12 -- so the load figures here come from /proc.
type Status struct {
	Ugens, Synths, Groups, Defs int32
	SampleRate                  float64
}

func queryStatus(port int, timeout time.Duration) (*Status, error) {
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return nil, err
	}
	defer c.Close()
	if _, err := c.Write(oscMessage("/status")); err != nil {
		return nil, err
	}
	_ = c.SetReadDeadline(time.Now().Add(timeout))
	buf := make([]byte, 512)
	n, err := c.Read(buf)
	if err != nil {
		return nil, err
	}
	// /status.reply\0 then ,iiiiiffff\0 then the values.
	i := strings.IndexByte(string(buf[:n]), 0)
	if i < 0 {
		return nil, fmt.Errorf("malformed reply")
	}
	p := i + pad(i+1) + 1
	if p >= n || buf[p] != ',' {
		return nil, fmt.Errorf("no type tag")
	}
	tags := string(buf[p:n])
	tags = tags[:strings.IndexByte(tags, 0)]
	p += len(tags) + 1
	p += pad(p)
	read := func() uint32 { v := binary.BigEndian.Uint32(buf[p:]); p += 4; return v }
	read() // the leading unused int
	s := &Status{}
	s.Ugens, s.Synths = int32(read()), int32(read())
	s.Groups, s.Defs = int32(read()), int32(read())
	read() // avg_cpu, always 0.0 on this firmware
	read() // peak_cpu, likewise
	// The last two are DOUBLES, not floats: the type tag is ",iiiiiffdd". Reading
	// them as 4 bytes gives 0.0, which reads as "the server did not say".
	read64 := func() float64 { v := binary.BigEndian.Uint64(buf[p:]); p += 8; return math.Float64frombits(v) }
	read64() // nominal sample rate
	s.SampleRate = read64()
	return s, nil
}

// -- reading the instrument directly, no ssh ----------------------------------

func readFile(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

func tempC() float64 {
	v, err := strconv.ParseFloat(readFile("/sys/class/thermal/thermal_zone0/temp"), 64)
	if err != nil {
		return 0
	}
	return v / 1000
}

// perCore returns each core's busy fraction over d, from the kernel's own counters.
func perCore(d time.Duration) map[string]float64 {
	snap := func() map[string][2]uint64 {
		out := map[string][2]uint64{}
		for _, line := range strings.Split(readFile("/proc/stat"), "\n") {
			f := strings.Fields(line)
			if len(f) < 8 || !strings.HasPrefix(f[0], "cpu") || f[0] == "cpu" {
				continue
			}
			var total, idle uint64
			for i := 1; i < len(f); i++ {
				v, _ := strconv.ParseUint(f[i], 10, 64)
				total += v
				if i == 4 || i == 5 {
					idle += v
				}
			}
			out[f[0]] = [2]uint64{total, idle}
		}
		return out
	}
	a := snap()
	time.Sleep(d)
	b := snap()
	out := map[string]float64{}
	for k, v1 := range b {
		v0, ok := a[k]
		if !ok || v1[0] <= v0[0] {
			continue
		}
		dt, di := float64(v1[0]-v0[0]), float64(v1[1]-v0[1])
		out[k] = (dt - di) / dt
	}
	return out
}

func main() {
	addr := flag.String("addr", ":8080", "listen address")
	ui := flag.String("ui", "/media/thumbdrive/vox", "directory holding the Vox UI")
	scPort := flag.Int("sc", 57110, "scsynth UDP port on localhost")
	flag.BoolVar(&allowWrite, "allow-write", false,
		"permit sending to las-sc on 127.0.0.1:9300; off by default because the "+
			"matrix wire encoding is inferred rather than observed (see lassc.go)")
	flag.Parse()

	http.HandleFunc("/api/modmatrix", modmatrixTablesHandler)
	http.HandleFunc("/api/modmatrix/write", modmatrixWriteHandler)
	http.HandleFunc("/matrix", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, matrixPage)
	})

	http.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		st, err := queryStatus(*scPort, 2*time.Second)
		cores := perCore(300 * time.Millisecond)
		fmt.Fprintf(w, "{\n  \"temp_c\": %.1f,\n  \"uptime\": %q,\n", tempC(), readFile("/proc/uptime"))
		fmt.Fprint(w, "  \"cores\": {")
		first := true
		for k, v := range cores {
			if !first {
				fmt.Fprint(w, ", ")
			}
			fmt.Fprintf(w, "%q: %.3f", k, v)
			first = false
		}
		fmt.Fprint(w, "},\n")
		if err != nil {
			fmt.Fprintf(w, "  \"scsynth\": null,\n  \"scsynth_error\": %q\n}\n", err.Error())
			return
		}
		fmt.Fprintf(w, "  \"scsynth\": {\"ugens\": %d, \"synths\": %d, \"groups\": %d, \"defs\": %d, \"sample_rate\": %.1f}\n}\n",
			st.Ugens, st.Synths, st.Groups, st.Defs, st.SampleRate)
	})

	http.HandleFunc("/bench", benchHandler)
	http.HandleFunc("/api/screen", screenHandler)
	// The UI opens its socket on "/" -- the same path it fetched the page from -- so
	// the root has to decide by the Upgrade header rather than by path.
	ws := wsHandler(*scPort)
	files := serveUI(*ui)
	root := func(w http.ResponseWriter, r *http.Request) {
		if strings.EqualFold(r.Header.Get("Upgrade"), "websocket") {
			ws(w, r)
			return
		}
		files(w, r)
	}
	http.HandleFunc("/ws", ws)
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, page)
	})
	http.HandleFunc("/", root)

	go screenLoop(400 * time.Millisecond)
	go statusLoop(*scPort, 2*time.Second)

	log.Printf("moogd on %s, UI from %s, scsynth at 127.0.0.1:%d", *addr, *ui, *scPort)
	log.Fatal(http.ListenAndServe(*addr, nil))
}

const page = `<!doctype html><meta charset=utf-8><title>Moog One</title>
<style>body{background:#141414;color:#e8e2d5;font:14px/1.5 ui-monospace,monospace;margin:0;padding:32px}
h1{font-size:15px;letter-spacing:.18em;color:#d8a24a;font-weight:600;margin:0 0 24px}
table{border-collapse:collapse}td{padding:4px 24px 4px 0}td:first-child{color:#8a8578}
.v{color:#8fd48f}</style>
<h1>MOOG ONE &middot; SERVED BY THE INSTRUMENT</h1>
<table id=t></table>
<script>
async function tick(){
  try{
    const r = await fetch('/api/status'), d = await r.json();
    const rows = [['temperature', d.temp_c.toFixed(1)+' &deg;C']];
    for (const [k,v] of Object.entries(d.cores||{})) rows.push([k+' busy', (v*100).toFixed(0)+'%']);
    if (d.scsynth) {
      rows.push(['ugens', d.scsynth.ugens], ['synths', d.scsynth.synths],
                ['groups', d.scsynth.groups], ['synthdefs', d.scsynth.defs],
                ['sample rate', d.scsynth.sample_rate.toFixed(0)+' Hz']);
    } else rows.push(['scsynth', d.scsynth_error || 'not answering']);
    document.getElementById('t').innerHTML =
      rows.map(([k,v])=>'<tr><td>'+k+'</td><td class=v>'+v+'</td></tr>').join('');
  }catch(e){}
}
tick(); setInterval(tick, 2000);
</script>`
