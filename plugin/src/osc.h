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

// `/n_set <node> <control> <value>` -- the one message this plugin sends.
std::vector<std::uint8_t> n_set(std::int32_t node, const std::string &control,
                                float value);


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
