// Minimal OSC 1.0 encoding: enough to set a control on a running synth, and
// nothing more. Big-endian on the wire, every block padded to four bytes.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace moogone {

class OscMessage {
public:
    explicit OscMessage(std::string address) : address_(std::move(address)) {}

    OscMessage &i(std::int32_t v);
    OscMessage &f(float v);
    OscMessage &s(const std::string &v);

    // The datagram, ready to send.
    std::vector<std::uint8_t> encode() const;

private:
    std::string address_;
    std::string tags_;
    std::vector<std::uint8_t> args_;
};

// `/n_set <node> <control> <value>` -- automation.
std::vector<std::uint8_t> n_set(std::int32_t node, const std::string &control,
                                float value);

// `/b_setn <buffer> <start> <count> <samples...>` -- audio into the instrument.
// This is the whole ingress path: samples go straight into a buffer that a Phasor
// and BufRd read back as a ring. It does not touch scsynth's disk thread, which
// is why it is this and not DiskIn on a FIFO -- see docs section 8e.
std::vector<std::uint8_t> b_setn(std::int32_t buffer, std::int32_t start,
                                 const float *samples, std::size_t count);

// `/c_get <bus>` -- asks where the instrument's read pointer has got to. The only
// feedback there is: two clocks that are not the same clock need it.
std::vector<std::uint8_t> c_get(std::int32_t bus);


// Just enough decoding to read a /g_queryTree.reply: its arguments are a flat
// run of ints, floats and strings, and the node ids are what we came for.
struct OscValue {
    char tag = 0;              // 'i', 'f' or 's'
    std::int32_t i = 0;
    float f = 0.0f;
    std::string s;
};

struct OscIncoming {
    std::string address;
    std::vector<OscValue> args;
};

// Returns false if this is not a well-formed OSC message.
bool decode(const std::uint8_t *data, std::size_t len, OscIncoming &out);

}  // namespace moogone
