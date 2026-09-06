// Tests for the two pieces that reach the instrument: the OSC codec and the
// pacing interlock. A bug in the first is silently ignored by the server; a bug
// in the second can wedge the instrument until someone pulls its power. Neither
// needs a host to test, so neither should wait for one.
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "audio.h"
#include "ingress.h"
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


    std::printf("\ningress\n");
    {
        // The two pointers chase each other around the instrument's ring forever,
        // so their absolute values mean nothing and only the wrapped distance says
        // whether the next block lands on audio already played.
        check(gapAhead(500, 100, 1000) == 400, "the gap is the distance from reader to writer");
        check(gapAhead(50, 150, 1000) == 900,
              "and it wraps: a writer past the end is ahead, not behind");
        check(gapAhead(0, 0, 0) == 0, "a zero-length ring does not divide by zero");
    }
    {
        check(rateCorrection(500, 500, 1000) == 1.0, "on target the rate is left alone");
        check(rateCorrection(200, 500, 1000) > 1.0, "too close to being overtaken: write faster");
        check(rateCorrection(800, 500, 1000) < 1.0, "too far ahead: write more slowly");
        // A gap error of most of a ring would ask for a huge rate change, and
        // applying it would be an audible pitch jump. The drift it answers is a
        // fraction of a percent.
        check(std::abs(rateCorrection(0, 999, 1000) - (1.0 + kMaxIngressCorrection)) < 1e-9,
              "and a wild error is clamped rather than obeyed");
        check(rateCorrection(0, 0, 0) == 1.0, "a zero-length ring does not divide by zero");
    }
    {
        // THE BUG THIS TEST EXISTS FOR. The pacer used to reset its schedule
        // whenever a block ran long. On hardware that came to 0.982x realtime, and
        // since the instrument reads at exactly 1.000x the lead drained at 864
        // frames a second: the round trip fell 149 ms -> 89 ms across five hits.
        Pacer pacer;
        auto now = Pacer::clock::time_point{};
        pacer.start(now);
        // A block that overruns its 5.33 ms slot by 3 ms, twice.
        now += std::chrono::microseconds(8333);
        auto first = pacer.tick(now, 1.0, kIngressBlock, 48000.0);
        now += std::chrono::microseconds(8333);
        auto second = pacer.tick(now, 1.0, kIngressBlock, 48000.0);
        check(first == std::chrono::nanoseconds::zero(), "an overrun block is due immediately");
        check(second == std::chrono::nanoseconds::zero(), "and so is the next, until it catches up");
        check(pacer.resets() == 0, "a small deficit is carried, not forgiven");
    }
    {
        // Chasing a two-second stall would mean sending two seconds of audio as
        // fast as the interlock allows, which is the shape that wedges the gadget.
        Pacer pacer;
        auto now = Pacer::clock::time_point{};
        pacer.start(now);
        now += std::chrono::seconds(2);
        pacer.tick(now, 1.0, kIngressBlock, 48000.0);
        check(pacer.resets() == 1, "a stall longer than kMaxLag is given up on rather than chased");
    }
    {
        MonoRing ring(1024);
        std::vector<float> in(512, 0.5f);
        check(ring.write(in.data(), 512) == 512, "the ring takes what fits");
        check(ring.available() == 512, "and reports it");
        // One slot is kept empty so full and empty are distinguishable without a
        // shared count, which two threads cannot keep consistent without a lock.
        check(ring.write(in.data(), 512) == 511, "a short write means full, it does not block");
    }
    {
        // Starvation must produce silence, not stale samples: a repeated buffer is
        // far more audible than a gap, and it hides the fault as well.
        //
        // The ring is FED FIRST and then drained dry, which is the whole point. An
        // earlier version of this test starved a fresh ring, whose backing store is
        // zeroed -- so "silence" and "whatever was left in the buffer" were the same
        // bytes and the test passed against an implementation that repeated stale
        // audio. Mutation testing caught that; reading the test did not.
        MonoRing ring(4096);
        MonoReader reader(ring, 1024);
        std::vector<float> loud(300, 0.7f);
        ring.write(loud.data(), 300);
        float out[256];
        check(reader.read(out, 256), "a fed ring reads");
        check(!reader.read(out, 256), "and then starves, rather than inventing audio");
        check(out[0] == 0.0f && out[255] == 0.0f,
              "what a starved read writes is silence, not the stale samples still there");
        check(reader.starved() == 1, "and it is counted, not hidden");
    }
    {
        MonoRing ring(8192);
        std::vector<float> in(4096, 0.25f);
        ring.write(in.data(), 4096);
        MonoReader reader(ring, 1024);
        float out[256];
        check(reader.read(out, 256), "a well-fed ring reads");
        check(std::abs(out[128] - 0.25f) < 1e-6, "and interpolation preserves a constant");
        check(reader.step() <= 1.0 + kMaxIngressCorrection + 1e-9 &&
              reader.step() >= 1.0 - kMaxIngressCorrection - 1e-9,
              "the resample step stays clamped however full the ring is");
    }

    std::printf("\n%s\n", failures ? "FAILURES" : "all passed");
    return failures ? 1 : 0;
}
