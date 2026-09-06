// Tests for the two pieces that reach the instrument: the OSC codec and the
// pacing interlock. A bug in the first is silently ignored by the server; a bug
// in the second can wedge the instrument until someone pulls its power. Neither
// needs a host to test, so neither should wait for one.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "osc.h"
#include "sender.h"

static int failures = 0;

static void check(bool ok, const char *what) {
    std::printf("  %-64s %s\n", what, ok ? "ok" : "FAILED");
    if (!ok) ++failures;
}

static std::string hex(const std::vector<std::uint8_t> &b) {
    std::string out;
    char tmp[4];
    for (auto c : b) { std::snprintf(tmp, sizeof(tmp), "%02x", c); out += tmp; }
    return out;
}

int main() {
    using namespace moogone;

    std::printf("osc\n");
    {
        // "/n_set" is six characters, so with its terminator and padding it
        // occupies eight bytes. A four-character address would occupy eight too:
        // the NUL always exists. This is the classic OSC off-by-one.
        auto p = n_set(1024, "mix", 0.5f);
        check(p.size() % 4 == 0, "every datagram is a multiple of four bytes");
        check(std::memcmp(p.data(), "/n_set\0\0", 8) == 0,
              "address is padded past its terminator");
        check(hex(p).find("2c697366") != std::string::npos,
              "type tags are ',isf'");
        // 0.5f is 0x3f000000 big-endian; 1024 is 0x00000400.
        check(hex(p).find("00000400") != std::string::npos, "node id is big-endian");
        check(hex(p).find("3f000000") != std::string::npos, "float is big-endian");
    }
    {
        OscMessage m("/abcd");           // 5 chars -> 8 bytes with padding
        auto b = m.i(1).encode();
        check(b.size() == 8 + 4 + 4, "a five-character address pads to eight");
    }

    std::printf("write queue\n");
    {
        WriteQueue q;
        Write w{};
        check(!q.pop(w), "an empty queue pops nothing");
        Write in{};
        in.node = 7;
        std::strncpy(in.control.data(), "size", in.control.size() - 1);
        in.value = 0.25f;
        check(q.push(in), "a push succeeds");
        check(q.pop(w) && w.node == 7 && w.value == 0.25f &&
              std::strcmp(w.control.data(), "size") == 0, "what went in comes out");

        std::size_t pushed = 0;
        while (q.push(in)) ++pushed;
        check(pushed == WriteQueue::kCapacity - 1,
              "the queue fills to capacity and then refuses");
        // Refusing rather than blocking is the point: the producer is an audio
        // callback, and a newer automation frame supersedes an older one.
    }

    std::printf("pacing interlock\n");
    {
        Sender s;
        // Port 9 (discard) on loopback: exercises the real socket path without
        // touching the instrument.
        check(s.start("127.0.0.1", 9), "sender starts");
        const int n = 20;
        const auto t0 = std::chrono::steady_clock::now();
        for (int i = 0; i < n; ++i) s.queue(1024, "mix", 0.1f * i);
        while (s.sent() < static_cast<std::uint64_t>(n)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        const auto elapsed = std::chrono::steady_clock::now() - t0;
        const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count();
        // 20 datagrams at a 1 ms floor cannot complete in under ~19 ms. Without
        // the interlock this finishes in microseconds -- which is the shape of
        // traffic that took the instrument off the network three times.
        std::printf("      %d datagrams took %lld ms\n", n, static_cast<long long>(ms));
        check(ms >= 15, "sends are paced, not blasted");
        check(s.dropped() == 0, "nothing was dropped at this rate");
        s.stop();
    }
    {
        Sender s;
        check(!s.start("not-an-address", 9) || true, "a bad host does not crash");
        s.stop();
    }

    std::printf("\n%s\n", failures ? "FAILURES" : "all passed");
    return failures ? 1 : 0;
}
