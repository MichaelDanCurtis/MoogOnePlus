package main

// A minimal RFC 6455 server: handshake, text frames, ping and close.
//
// Written rather than imported to keep this a zero-dependency static binary. The
// surface actually needed is small -- the UI sends short JSON text frames and
// receives them, on a local network -- and a dependency shipped inside a
// synthesiser is a thing to be sure about rather than convenient about.
//
// Not implemented, deliberately: extensions, continuation frames, and binary
// frames. A client frame arriving fragmented is closed rather than mishandled.

import (
	"bufio"
	"crypto/sha1"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
)

// The GUID RFC 6455 fixes for the accept hash.
const wsGUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

type wsConn struct {
	rw   *bufio.ReadWriter
	c    net.Conn
	mu   sync.Mutex // one writer at a time: the status and screen loops share this
	dead bool
}

func wsAccept(w http.ResponseWriter, r *http.Request) (*wsConn, error) {
	if !strings.EqualFold(r.Header.Get("Upgrade"), "websocket") {
		return nil, errors.New("not a websocket upgrade")
	}
	key := r.Header.Get("Sec-WebSocket-Key")
	if key == "" {
		return nil, errors.New("no Sec-WebSocket-Key")
	}
	h, ok := w.(http.Hijacker)
	if !ok {
		return nil, errors.New("connection cannot be hijacked")
	}
	sum := sha1.Sum([]byte(key + wsGUID))
	accept := base64.StdEncoding.EncodeToString(sum[:])

	conn, rw, err := h.Hijack()
	if err != nil {
		return nil, err
	}
	_, err = fmt.Fprintf(rw, "HTTP/1.1 101 Switching Protocols\r\n"+
		"Upgrade: websocket\r\nConnection: Upgrade\r\n"+
		"Sec-WebSocket-Accept: %s\r\n\r\n", accept)
	if err != nil {
		conn.Close()
		return nil, err
	}
	if err := rw.Flush(); err != nil {
		conn.Close()
		return nil, err
	}
	return &wsConn{rw: rw, c: conn}, nil
}

// WriteText sends one unmasked text frame. Server frames are never masked.
func (w *wsConn) WriteText(p []byte) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.dead {
		return errors.New("closed")
	}
	var head []byte
	n := len(p)
	switch {
	case n < 126:
		head = []byte{0x81, byte(n)}
	case n < 65536:
		head = []byte{0x81, 126, 0, 0}
		binary.BigEndian.PutUint16(head[2:], uint16(n))
	default:
		head = make([]byte, 10)
		head[0], head[1] = 0x81, 127
		binary.BigEndian.PutUint64(head[2:], uint64(n))
	}
	if _, err := w.rw.Write(head); err != nil {
		w.dead = true
		return err
	}
	if _, err := w.rw.Write(p); err != nil {
		w.dead = true
		return err
	}
	if err := w.rw.Flush(); err != nil {
		w.dead = true
		return err
	}
	return nil
}

// ReadText returns the next text frame's payload. Pings are answered inline; a
// close frame, a fragment or a binary frame ends the connection.
func (w *wsConn) ReadText() ([]byte, error) {
	for {
		var h [2]byte
		if _, err := io.ReadFull(w.rw, h[:]); err != nil {
			return nil, err
		}
		fin, opcode := h[0]&0x80 != 0, h[0]&0x0f
		masked, n := h[1]&0x80 != 0, int(h[1]&0x7f)
		switch n {
		case 126:
			var b [2]byte
			if _, err := io.ReadFull(w.rw, b[:]); err != nil {
				return nil, err
			}
			n = int(binary.BigEndian.Uint16(b[:]))
		case 127:
			var b [8]byte
			if _, err := io.ReadFull(w.rw, b[:]); err != nil {
				return nil, err
			}
			n = int(binary.BigEndian.Uint64(b[:]))
		}
		var mask [4]byte
		if masked {
			if _, err := io.ReadFull(w.rw, mask[:]); err != nil {
				return nil, err
			}
		}
		// A client sending us megabytes is a client we do not want.
		if n > 1<<20 {
			return nil, errors.New("frame too large")
		}
		payload := make([]byte, n)
		if _, err := io.ReadFull(w.rw, payload); err != nil {
			return nil, err
		}
		if masked {
			for i := range payload {
				payload[i] ^= mask[i%4]
			}
		}
		switch opcode {
		case 0x1: // text
			if !fin {
				return nil, errors.New("fragmented frames not supported")
			}
			return payload, nil
		case 0x8: // close
			return nil, io.EOF
		case 0x9: // ping -> pong, same payload
			w.mu.Lock()
			w.rw.Write(append([]byte{0x8a, byte(len(payload))}, payload...))
			w.rw.Flush()
			w.mu.Unlock()
		case 0xa: // pong, ignore
		default:
			return nil, fmt.Errorf("unsupported opcode %d", opcode)
		}
	}
}

func (w *wsConn) Close() {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.dead = true
	w.c.Close()
}
