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

// ErrNoLiveMatrix explains why a modulation matrix cannot be installed over OSC.
//
// # This is settled, not suspected
//
// An earlier version of this file sent the matrix to
// /p/part/t/N/p/modmatrix/matrix_expression_slots and worried about whether the
// argument encoding was right. The encoding was never the problem. The address
// does not exist.
//
//	las-sc, occurrences of "modmatrix"          0
//	las-sc, occurrences of "matrix_expression"  0
//
// las-sc -- the only process listening on 127.0.0.1:9300, and the owner of the
// `/p` namespace -- has no modulation-matrix code at all. Every occurrence of
// that address string in the firmware is inside las-frontend, and every one of
// those is an embedded .m1p preset body: data, not protocol.
//
// The wire agrees. A capture of a real panel edit showed nothing to 9300, and
// the only /p traffic las-frontend ever sends las-sc is the effects and mixer
// slice -- exactly the 80 /p/part addresses las-sc implements. The panel
// reaches the voice controller by its own protocol, which does not pass through
// here.
//
// Two further live probes closed the remaining doors. Writing an _m address
// (both /p/pan_m and /p/part/t/1/p/pan_m) was delivered and ignored: _m is
// las-sc's computed OUTPUT, the modulation sum it pushes to the voice
// controller, not a settable input. And /p/pre-expr with an RPN string was
// likewise delivered and ignored -- unresolved as to why, but not a working
// path today.
//
// So `matrix_expression_slots` is a PRESET FILE FIELD. The way to install a
// matrix is to write it into a preset and load that, which is what the encoder
// in modmatrix.go is genuinely for -- and it round-trips all 300 factory
// matrices byte-for-byte.
var ErrNoLiveMatrix = errors.New(
	"the modulation matrix has no live OSC endpoint: las-sc contains zero " +
		"modmatrix code, and matrix_expression_slots is a preset-file field. " +
		"Compose the matrix here, then write it into a preset. See lassc.go.")

// writeSlots refuses, and says why.
//
// It is kept rather than deleted so that the reasoning survives next to the
// code that would otherwise be rewritten by the next person who assumes, as
// this file once did, that a preset address is an OSC address.
func writeSlots(timbre int, slots []Slot) error {
	if err := Validate(slots); err != nil {
		return err
	}
	return ErrNoLiveMatrix
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
