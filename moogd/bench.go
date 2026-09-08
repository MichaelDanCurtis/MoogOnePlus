package main

// A benchmark of the one hot path this server has: turning a framebuffer into
// something a browser can show. Everything else here -- OSC, /proc, HTTP -- is
// microseconds and does not depend on the language.
//
// The current Python bridge does this on cpu0 over SSH, at 0.4s intervals, and
// saturates the audio core doing it.

import (
	"bytes"
	"fmt"
	"image"
	"image/png"
	"net/http"
	"os"
	"syscall"
	"time"
)

const (
	fbW, fbH = 832, 480
	fbStride = fbW * 4
)

func grabFrame() ([]byte, error) {
	f, err := os.Open("/dev/fb0")
	if err != nil {
		return nil, err
	}
	defer f.Close()
	buf := make([]byte, fbStride*fbH)
	if _, err := f.Read(buf); err != nil {
		return nil, err
	}
	return buf, nil
}

// bgraToRGBA converts in place into an image the PNG encoder can take.
func bgraToRGBA(raw []byte) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, fbW, fbH))
	for i := 0; i < fbW*fbH; i++ {
		s, d := i*4, i*4
		img.Pix[d+0] = raw[s+2] // R <- B
		img.Pix[d+1] = raw[s+1]
		img.Pix[d+2] = raw[s+0] // B <- R
		img.Pix[d+3] = 255
	}
	return img
}

// grabMmap maps the framebuffer once and copies out of it, rather than asking the
// kernel to read it each time. Framebuffer memory is uncached on ARM, so the copy is
// still not free -- the question is how much of the 330 ms was the syscall path.
var mapped []byte

func grabMmap() ([]byte, error) {
	if mapped == nil {
		f, err := os.OpenFile("/dev/fb0", os.O_RDWR, 0)
		if err != nil {
			return nil, err
		}
		defer f.Close()
		m, err := syscall.Mmap(int(f.Fd()), 0, fbStride*fbH,
			syscall.PROT_READ, syscall.MAP_SHARED)
		if err != nil {
			return nil, err
		}
		mapped = m
	}
	out := make([]byte, len(mapped))
	copy(out, mapped)
	return out, nil
}

func benchHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain")
	const rounds = 5
	var tRead, tConv, tPNG time.Duration
	var size int
	for i := 0; i < rounds; i++ {
		t0 := time.Now()
		raw, err := grabFrame()
		if err != nil {
			fmt.Fprintf(w, "framebuffer: %v\n", err)
			return
		}
		t1 := time.Now()
		img := bgraToRGBA(raw)
		t2 := time.Now()
		var b bytes.Buffer
		enc := png.Encoder{CompressionLevel: png.BestSpeed}
		if err := enc.Encode(&b, img); err != nil {
			fmt.Fprintf(w, "png: %v\n", err)
			return
		}
		t3 := time.Now()
		tRead += t1.Sub(t0)
		tConv += t2.Sub(t1)
		tPNG += t3.Sub(t2)
		size = b.Len()
	}
	fmt.Fprintf(w, "frame %dx%d, %d bytes raw\n", fbW, fbH, fbStride*fbH)
	fmt.Fprintf(w, "  read  /dev/fb0   %7.1f ms\n", float64(tRead.Microseconds())/rounds/1000)
	fmt.Fprintf(w, "  BGRA -> RGBA     %7.1f ms\n", float64(tConv.Microseconds())/rounds/1000)
	fmt.Fprintf(w, "  PNG (BestSpeed)  %7.1f ms   -> %d bytes\n", float64(tPNG.Microseconds())/rounds/1000, size)
	total := float64((tRead + tConv + tPNG).Microseconds()) / rounds / 1000
	fmt.Fprintf(w, "  TOTAL            %7.1f ms   = %.1f fps sustained on one core\n", total, 1000/total)

	// The same frame via mmap, to separate the syscall path from the memory itself.
	var tMmap time.Duration
	for i := 0; i < rounds; i++ {
		t0 := time.Now()
		if _, err := grabMmap(); err != nil {
			fmt.Fprintf(w, "\nmmap: %v\n", err)
			return
		}
		tMmap += time.Since(t0)
	}
	fmt.Fprintf(w, "\n  mmap + copy      %7.1f ms   (vs %7.1f ms for read)\n",
		float64(tMmap.Microseconds())/rounds/1000, float64(tRead.Microseconds())/rounds/1000)

	// And what a static screen actually needs: how many bytes changed since last time.
	a, _ := grabMmap()
	time.Sleep(300 * time.Millisecond)
	b2, _ := grabMmap()
	diff := 0
	for i := range a {
		if a[i] != b2[i] {
			diff++
		}
	}
	fmt.Fprintf(w, "  bytes changed in 300ms: %d of %d (%.2f%%)\n", diff, len(a), 100*float64(diff)/float64(len(a)))
}
