package main

// The instrument's display, streamed the cheap way.
//
// The Python bridge does this over SSH: `dd` 1.6 MB out of /dev/fb0 every 0.4s,
// gzip it, ship it. That runs on cpu0 and saturates the audio core -- measured, with
// the bridge on, cpu0 sits at 1.00 against 0.67-0.87 with it off. On a machine where
// a reverb costs 23-33% against a 95% throttle, the screen mirror is the budget.
//
// Two measurements decided the design, both taken on the chip:
//
//	read /dev/fb0    331.0 ms      mmap + copy   12.8 ms     -- 26x
//	PNG whole frame  149.7 ms      bytes changed in 300ms: 0 of 1597440
//
// So: map the framebuffer once rather than reading it, and encode only the tiles
// that actually changed. A synthesiser's screen is static unless somebody is
// touching it, which makes the second one worth more than the first.

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"math"
	"image/png"
	"net/http"
	"os"
	"sync"
	"syscall"
	"time"
)

// 832 = 13x64 and 480 = 10x48, so the frame divides exactly and no tile is partial.
const (
	tileW, tileH = 64, 48
	cols, rows   = fbW / tileW, fbH / tileH
	numTiles     = cols * rows
)

type screener struct {
	mu     sync.Mutex
	mapped []byte
	prev   []byte // the last frame we sent, to diff against
	enc    png.Encoder
}

var screen = &screener{enc: png.Encoder{CompressionLevel: png.BestSpeed}}

// mapFB maps the framebuffer once and keeps it. Framebuffer memory is uncached, so
// the copy out of it is still the dominant cost -- but 12.8 ms rather than 331.
func (s *screener) mapFB() error {
	if s.mapped != nil {
		return nil
	}
	f, err := os.OpenFile("/dev/fb0", os.O_RDWR, 0)
	if err != nil {
		return err
	}
	defer f.Close()
	m, err := syscall.Mmap(int(f.Fd()), 0, fbStride*fbH, syscall.PROT_READ, syscall.MAP_SHARED)
	if err != nil {
		return err
	}
	s.mapped = m
	return nil
}

// tileChanged compares one tile row by row. Each row is a contiguous run, so this is
// a handful of memcmps rather than a per-pixel loop.
func tileChanged(a, b []byte, col, row int) bool {
	x0 := col * tileW * 4
	for y := row * tileH; y < (row+1)*tileH; y++ {
		off := y*fbStride + x0
		if !bytes.Equal(a[off:off+tileW*4], b[off:off+tileW*4]) {
			return true
		}
	}
	return false
}

// encodeAtlas packs every changed tile into ONE image and encodes it once.
//
// Encoding tiles individually is the obvious design and it is much worse: 130 tiles
// took 784 ms and 100 kB, against 150 ms and 52 kB for a single whole-frame PNG.
// Each PNG carries its own header and its own zlib stream, so per-image overhead
// dominates once the tiles are small. Packing them into one image pays that cost
// once and keeps the property that matters -- only changed pixels are sent at all.
//
// BGRA becomes RGBA on the way past, which is the same work either way.
func (s *screener) encodeAtlas(frame []byte, changed []int) (string, int, error) {
	if len(changed) == 0 {
		return "", 0, nil
	}
	acols := int(math.Ceil(math.Sqrt(float64(len(changed)))))
	arows := (len(changed) + acols - 1) / acols
	img := image.NewRGBA(image.Rect(0, 0, acols*tileW, arows*tileH))
	for n, idx := range changed {
		col, row := idx%cols, idx/cols
		ac, ar := n%acols, n/acols
		for y := 0; y < tileH; y++ {
			src := (row*tileH+y)*fbStride + col*tileW*4
			dst := (ar*tileH+y)*img.Stride + ac*tileW*4
			for x := 0; x < tileW; x++ {
				img.Pix[dst+x*4+0] = frame[src+x*4+2] // R <- B
				img.Pix[dst+x*4+1] = frame[src+x*4+1]
				img.Pix[dst+x*4+2] = frame[src+x*4+0] // B <- R
				img.Pix[dst+x*4+3] = 255
			}
		}
	}
	var buf bytes.Buffer
	if err := s.enc.Encode(&buf, img); err != nil {
		return "", 0, err
	}
	return base64.StdEncoding.EncodeToString(buf.Bytes()), acols, nil
}

// frame returns the tiles that changed since the last call, packed into one atlas.
// `full` forces all of them, which is what a newly connected viewer needs.
func (s *screener) frame(full bool) (atlas string, acols int, changed []int,
	grabMS, diffMS, encMS float64, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err = s.mapFB(); err != nil {
		return
	}

	t0 := time.Now()
	cur := make([]byte, len(s.mapped))
	copy(cur, s.mapped)
	t1 := time.Now()

	if s.prev == nil {
		full = true
	}
	changed = make([]int, 0, numTiles)
	for i := 0; i < numTiles; i++ {
		if full || tileChanged(cur, s.prev, i%cols, i/cols) {
			changed = append(changed, i)
		}
	}
	t2 := time.Now()

	atlas, acols, err = s.encodeAtlas(cur, changed)
	t3 := time.Now()
	if err != nil {
		return
	}

	s.prev = cur
	return atlas, acols, changed, ms(t1.Sub(t0)), ms(t2.Sub(t1)), ms(t3.Sub(t2)), nil
}

func ms(d time.Duration) float64 { return float64(d.Microseconds()) / 1000 }

func screenHandler(w http.ResponseWriter, r *http.Request) {
	full := r.URL.Query().Get("full") == "1"
	atlas, acols, changed, grabMS, diffMS, encMS, err := screen.frame(full)
	w.Header().Set("Content-Type", "application/json")
	if err != nil {
		fmt.Fprintf(w, "{\"error\": %q}\n", err.Error())
		return
	}
	fmt.Fprintf(w, "{\"w\":%d,\"h\":%d,\"tw\":%d,\"th\":%d,\"cols\":%d,",
		fbW, fbH, tileW, tileH, cols)
	fmt.Fprintf(w, "\"changed\":%d,\"of\":%d,\"atlas_cols\":%d,", len(changed), numTiles, acols)
	fmt.Fprintf(w, "\"ms\":{\"grab\":%.1f,\"diff\":%.1f,\"encode\":%.1f},", grabMS, diffMS, encMS)
	fmt.Fprint(w, "\"indices\":[")
	for i, idx := range changed {
		if i > 0 {
			fmt.Fprint(w, ",")
		}
		fmt.Fprint(w, idx)
	}
	fmt.Fprintf(w, "],\"png\":%q}\n", atlas)
}
