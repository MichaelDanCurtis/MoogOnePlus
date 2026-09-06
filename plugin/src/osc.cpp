#include "osc.h"

#include <cstring>

namespace moogone {
namespace {

void push_be32(std::vector<std::uint8_t> &out, std::uint32_t v) {
    out.push_back(static_cast<std::uint8_t>(v >> 24));
    out.push_back(static_cast<std::uint8_t>(v >> 16));
    out.push_back(static_cast<std::uint8_t>(v >> 8));
    out.push_back(static_cast<std::uint8_t>(v));
}

// OSC strings are NUL-terminated and then padded to a four-byte boundary, so a
// four-character string occupies EIGHT bytes, not four: the terminator always
// exists. Getting this wrong produces a message the server silently ignores.
void push_string(std::vector<std::uint8_t> &out, const std::string &s) {
    out.insert(out.end(), s.begin(), s.end());
    out.push_back(0);
    while (out.size() % 4 != 0) out.push_back(0);
}

}  // namespace

OscMessage &OscMessage::i(std::int32_t v) {
    tags_ += 'i';
    push_be32(args_, static_cast<std::uint32_t>(v));
    return *this;
}

OscMessage &OscMessage::f(float v) {
    tags_ += 'f';
    std::uint32_t bits;
    static_assert(sizeof(bits) == sizeof(v));
    std::memcpy(&bits, &v, sizeof(bits));
    push_be32(args_, bits);
    return *this;
}

OscMessage &OscMessage::s(const std::string &v) {
    tags_ += 's';
    push_string(args_, v);
    return *this;
}

std::vector<std::uint8_t> OscMessage::encode() const {
    std::vector<std::uint8_t> out;
    push_string(out, address_);
    push_string(out, "," + tags_);
    out.insert(out.end(), args_.begin(), args_.end());
    return out;
}

std::vector<std::uint8_t> n_set(std::int32_t node, const std::string &control,
                                float value) {
    return OscMessage("/n_set").i(node).s(control).f(value).encode();
}

namespace {

bool read_string(const std::uint8_t *d, std::size_t len, std::size_t &off,
                 std::string &out) {
    const std::size_t start = off;
    while (off < len && d[off] != 0) ++off;
    if (off >= len) return false;
    out.assign(reinterpret_cast<const char *>(d + start), off - start);
    off = (off + 4) & ~static_cast<std::size_t>(3);   // past the NUL, then padded
    return off <= len;
}

bool read_be32(const std::uint8_t *d, std::size_t len, std::size_t &off,
               std::uint32_t &out) {
    if (off + 4 > len) return false;
    out = (static_cast<std::uint32_t>(d[off]) << 24) |
          (static_cast<std::uint32_t>(d[off + 1]) << 16) |
          (static_cast<std::uint32_t>(d[off + 2]) << 8) |
          static_cast<std::uint32_t>(d[off + 3]);
    off += 4;
    return true;
}

}  // namespace

bool decode(const std::uint8_t *data, std::size_t len, OscIncoming &out) {
    std::size_t off = 0;
    out.args.clear();
    if (!read_string(data, len, off, out.address)) return false;
    std::string tags;
    if (!read_string(data, len, off, tags)) return false;
    if (tags.empty() || tags[0] != ',') return false;
    for (std::size_t k = 1; k < tags.size(); ++k) {
        OscValue v;
        v.tag = tags[k];
        std::uint32_t bits = 0;
        switch (tags[k]) {
            case 'i':
                if (!read_be32(data, len, off, bits)) return false;
                v.i = static_cast<std::int32_t>(bits);
                break;
            case 'f':
                if (!read_be32(data, len, off, bits)) return false;
                std::memcpy(&v.f, &bits, sizeof(v.f));
                break;
            case 's':
                if (!read_string(data, len, off, v.s)) return false;
                break;
            default:
                return false;      // a tag we do not understand
        }
        out.args.push_back(std::move(v));
    }
    return true;
}

std::vector<std::uint8_t> b_setn(std::int32_t buffer, std::int32_t start,
                                 const float *samples, std::size_t count) {
    OscMessage m("/b_setn");
    m.i(buffer).i(start).i(static_cast<std::int32_t>(count));
    for (std::size_t i = 0; i < count; ++i) m.f(samples[i]);
    return m.encode();
}

std::vector<std::uint8_t> c_get(std::int32_t bus) {
    return OscMessage("/c_get").i(bus).encode();
}

}  // namespace moogone
