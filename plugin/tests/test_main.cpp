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

#include "audio.h"
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

    std::printf("audio ring\n");
    {
        AudioRing ring(8);
        float in[8] = {1, -1, 2, -2, 3, -3, 4, -4};    // four stereo frames
        check(ring.write(in, 4) == 4, "four frames go in");
        check(ring.available() == 4, "and four are available");
        float l, r;
        ring.peek(0, l, r);
        check(l == 1.0f && r == -1.0f, "the first frame reads back");
        ring.peek(3, l, r);
        check(l == 4.0f && r == -4.0f, "and so does the fourth");
        ring.consume(4);
        check(ring.available() == 0, "consuming empties it");
        // One frame is held back so full and empty stay distinguishable.
        check(ring.write(in, 8) == 7, "a full ring writes short rather than wrapping");
    }

    std::printf("drift reader\n");
    {
        AudioRing ring(48000);
        DriftReader reader(ring, 1920);            // 40 ms target
        float l[512], r[512];
        check(!reader.read(l, r, 512), "an empty ring starves");
        check(l[0] == 0.0f && r[511] == 0.0f,
              "starvation yields SILENCE, not stale samples");
        check(reader.starved() == 1, "and is counted");
    }
    {
        // The point of the whole file. Two clocks that differ by a realistic
        // amount, run for minutes of audio. Without compensation the ring either
        // overflows or starves; with it, fill stays bounded and nothing is lost.
        for (double skew : {1.003, 0.997}) {
            AudioRing ring(48000);
            DriftReader reader(ring, 1920);
            std::vector<float> block(4096 * 2, 0.25f);
            float l[512], r[512];
            double owed = 1920;                    // prime the ring to target
            std::size_t dropped = 0;
            std::size_t minFill = ring.capacity(), maxFill = 0;

            for (int b = 0; b < 12000; ++b) {      // ~2 minutes of audio
                owed += 512.0 * skew;
                const auto give = static_cast<std::size_t>(owed);
                owed -= static_cast<double>(give);
                dropped += give - ring.write(block.data(), std::min<std::size_t>(give, 4096));
                reader.read(l, r, 512);
                const auto fill = ring.available();
                minFill = std::min(minFill, fill);
                maxFill = std::max(maxFill, fill);
            }
            std::printf("      skew %.3f: fill %zu..%zu, ratio %.5f, starved %llu, dropped %zu\n",
                        skew, minFill, maxFill, reader.ratio(),
                        static_cast<unsigned long long>(reader.starved()), dropped);
            check(reader.starved() == 0, "two minutes of clock skew without starving");
            check(dropped == 0, "and without dropping a producer write");
            // The controller must actually have moved, in the right direction.
            check(skew > 1.0 ? reader.ratio() > 1.0 : reader.ratio() < 1.0,
                  "the reader tracked the producer's clock");
        }
    }
    {
        // A hiccup must not become a pitch slide.
        AudioRing ring(48000);
        DriftReader reader(ring, 1920);
        std::vector<float> block(40000 * 2, 0.1f);
        ring.write(block.data(), 40000);           // wildly over target
        float l[512], r[512];
        for (int i = 0; i < 200; ++i) reader.read(l, r, 512);
        check(reader.ratio() <= 1.0 + DriftReader::kMaxCorrection + 1e-9,
              "the correction stays clamped when the ring is far from target");
    }

    std::printf("\n%s\n", failures ? "FAILURES" : "all passed");
    return failures ? 1 : 0;
}
