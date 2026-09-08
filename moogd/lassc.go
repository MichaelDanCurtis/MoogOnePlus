package main

// Talking to las-sc, the control brain.
//
// las-sc owns the `/p` namespace -- the patch state the panel edits -- and it
// listens on 127.0.0.1:9300, **loopback only**. That is the whole reason this
// daemon runs on the instrument instead of beside it: from another machine
// there is no route to that port without an SSH tunnel, and from here it is a
// datagram to localhost.
//
// It is write-only. las-sc sends its replies to las-frontend on :7775 and never
// to whoever asked, so nothing here can read a parameter back. The UI therefore
// shows what *it* set, not what the instrument holds, and says so.
//
// See docs/arch/control-plane.md and lassc_send.py, which does the same thing
// over SSH and much more slowly.

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"net"
)

// lasscPort is where las-sc listens. Loopback only.
const lasscPort = 9300

// allowWrite gates every send. Off unless -allow-write is given.
//
// Not paranoia about `/p` in general -- setting a `/p` address is what turning
// a knob does, and reloading the preset undoes it. It is about this specific
// message, whose wire encoding is inferred rather than observed. See
// writeSlots.
var allowWrite bool

// oscFloatMessage builds a message whose arguments alternate as the matrix
// does: ids as int32, amounts as float32.
func oscMixedMessage(addr string, tokens []float64, isInt func(i int) bool) []byte {
	out := append([]byte(addr), 0)
	out = append(out, make([]byte, pad(len(out)))...)

	tags := make([]byte, 0, len(tokens)+1)
	tags = append(tags, ',')
	body := make([]byte, 0, len(tokens)*4)
	var b [4]byte
	for i, t := range tokens {
		if isInt(i) {
			tags = append(tags, 'i')
			binary.BigEndian.PutUint32(b[:], uint32(int32(t)))
		} else {
			tags = append(tags, 'f')
			binary.BigEndian.PutUint32(b[:], math.Float32bits(float32(t)))
		}
		body = append(body, b[:]...)
	}
	tags = append(tags, 0)
	out = append(out, tags...)
	out = append(out, make([]byte, pad(len(tags)))...)
	return append(out, body...)
}

// sendToLasSC puts one datagram on the loopback. There is no acknowledgement to
// wait for, so a nil error means "the kernel accepted it", not "it worked".
func sendToLasSC(pkt []byte) error {
	c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", lasscPort))
	if err != nil {
		return err
	}
	defer c.Close()
	_, err = c.Write(pkt)
	return err
}

// writeSlots installs a modulation matrix on one timbre.
//
// # The encoding here is inferred and has not been observed on the wire
//
// What is known: the preset file stores this address as a flat array whose id
// columns print as integers and whose amount columns print with a decimal
// point, e.g. `[48, 1.0, 6, 0.0099999998, 43, 0.0, 52]`. From that, and from
// las-sc being CHICKEN Scheme (whose OSC layer hands a message's arguments over
// as a list), the natural encoding is one OSC message carrying 7N arguments,
// typed `i` for the four id columns and `f` for the three amount columns. That
// is what this sends.
//
// What is *not* known: whether las-sc wants exactly that, or a single string
// holding the JSON text, or a blob, or one message per row. No capture of the
// panel writing a matrix row exists, so this is reasoning from the file format
// rather than from the protocol.
//
// Settling it costs one passive observation and no risk: on the instrument,
//
//	tcpdump -i lo -s0 -A udp port 9300
//
// then move any mod-matrix row on the panel. las-frontend will send las-sc the
// real thing and the format stops being a question. Until then this is gated
// behind -allow-write, and the UI's dry run shows the exact bytes it would put
// on the wire.
//
// A wrong guess here is very unlikely to be dangerous -- a malformed OSC
// message to a Scheme process is a parse failure, and `/p` is patch state that
// reloading a preset restores -- but "very unlikely" is not "verified", and
// this instrument's voice cards cannot be replaced.
func writeSlots(timbre int, slots []Slot) error {
	if !allowWrite {
		return errors.New("writes are disabled; start moogd with -allow-write " +
			"(and see writeSlots on why the encoding is not yet confirmed)")
	}
	if err := Validate(slots); err != nil {
		return err
	}
	tokens := EncodeSlots(slots)
	// Columns 0, 2, 4, 6 of each row are ids; 1, 3, 5 are amounts.
	isInt := func(i int) bool { return i%SlotTokens%2 == 0 }
	return sendToLasSC(oscMixedMessage(slotsAddress(timbre), tokens, isInt))
}

// writeScalar sets a single `/p` address -- the ordinary case, and the one the
// repository has exercised before: an address plus one number, exactly what the
// panel emits when a knob moves.
func writeScalar(addr string, value float64, asInt bool) error {
	if !allowWrite {
		return errors.New("writes are disabled; start moogd with -allow-write")
	}
	return sendToLasSC(oscMixedMessage(addr, []float64{value},
		func(int) bool { return asInt }))
}
