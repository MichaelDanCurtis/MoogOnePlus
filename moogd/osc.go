package main

// A complete-enough OSC decoder. /status.reply is fixed-shape and the hand-rolled
// reader in main.go handles it; /g_queryTree.reply is not -- it mixes ints, strings
// and floats, and its shape depends on its own contents -- so it needs real
// argument decoding.

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"net"
	"strings"
	"time"
)

type oscMsg struct {
	Addr string
	Args []any // int32, float32, float64 or string
}

func padded(n int) int { return n + (4-n%4)%4 }

func readOscString(b []byte, p int) (string, int, error) {
	i := p
	for i < len(b) && b[i] != 0 {
		i++
	}
	if i >= len(b) {
		return "", 0, errors.New("unterminated string")
	}
	s := string(b[p:i])
	return s, p + padded(i-p+1), nil
}

func decodeOSC(b []byte) (*oscMsg, error) {
	addr, p, err := readOscString(b, 0)
	if err != nil {
		return nil, err
	}
	m := &oscMsg{Addr: addr}
	if p >= len(b) {
		return m, nil
	}
	tags, p, err := readOscString(b, p)
	if err != nil {
		return nil, err
	}
	if !strings.HasPrefix(tags, ",") {
		return nil, fmt.Errorf("bad type tag %q", tags)
	}
	for _, t := range tags[1:] {
		switch t {
		case 'i':
			if p+4 > len(b) {
				return nil, errors.New("truncated int")
			}
			m.Args = append(m.Args, int32(binary.BigEndian.Uint32(b[p:])))
			p += 4
		case 'f':
			if p+4 > len(b) {
				return nil, errors.New("truncated float")
			}
			m.Args = append(m.Args, math.Float32frombits(binary.BigEndian.Uint32(b[p:])))
			p += 4
		case 'd':
			if p+8 > len(b) {
				return nil, errors.New("truncated double")
			}
			m.Args = append(m.Args, math.Float64frombits(binary.BigEndian.Uint64(b[p:])))
			p += 8
		case 's', 'S':
			var s string
			s, p, err = readOscString(b, p)
			if err != nil {
				return nil, err
			}
			m.Args = append(m.Args, s)
		case 'b':
			if p+4 > len(b) {
				return nil, errors.New("truncated blob")
			}
			n := int(binary.BigEndian.Uint32(b[p:]))
			p += 4 + padded(n)
		case 'T':
			m.Args = append(m.Args, int32(1))
		case 'F':
			m.Args = append(m.Args, int32(0))
		case 'N', 'I':
			m.Args = append(m.Args, int32(0))
		default:
			return nil, fmt.Errorf("unsupported type tag %q", t)
		}
	}
	return m, nil
}

// request sends one message and waits for a reply at `want`. Messages arriving in
// the meantime are discarded -- scsynth volunteers /done and /fail, and an
// unsolicited one would otherwise be mistaken for the answer to this question.
func request(port int, out []byte, want string, timeout time.Duration) (*oscMsg, error) {
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return nil, err
	}
	defer c.Close()
	if _, err := c.Write(out); err != nil {
		return nil, err
	}
	deadline := time.Now().Add(timeout)
	buf := make([]byte, 65536)
	for time.Now().Before(deadline) {
		_ = c.SetReadDeadline(deadline)
		n, err := c.Read(buf)
		if err != nil {
			return nil, err
		}
		m, err := decodeOSC(buf[:n])
		if err != nil {
			continue
		}
		if m.Addr == want {
			return m, nil
		}
	}
	return nil, fmt.Errorf("no %s within %s", want, timeout)
}

func send(port int, out []byte) error {
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return err
	}
	defer c.Close()
	_, err = c.Write(out)
	return err
}

func asInt(v any) (int32, bool) {
	switch x := v.(type) {
	case int32:
		return x, true
	case float32:
		return int32(x), true
	case float64:
		return int32(x), true
	}
	return 0, false
}

func asFloat(v any) (float64, bool) {
	switch x := v.(type) {
	case int32:
		return float64(x), true
	case float32:
		return float64(x), true
	case float64:
		return x, true
	}
	return 0, false
}
