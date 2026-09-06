// Audio INTO the instrument, so its own effects can process it.
//
// The mirror of capture, and not built like it. Capture is a TCP stream the
// instrument pushes; ingress cannot be a stream the instrument pulls, because the
// obvious way to do that -- a FIFO read by DiskIn -- does not work on this
// firmware and puts the scsynth thread that loads the instrument's own presets
// behind a read that may never return. See docs/MOOG-ONE-INTERNALS.md section 8e.
//
// So: /b_setn writes samples straight into a ring buffer on the instrument, and a
// Phasor and BufRd read them back. No disk thread, and the traffic rides the same
// 1 ms pacing interlock as every other datagram this plugin sends.
//
// TWO CLOCKS, TWO LOOPS, AND THEY ARE NOT FIGHTING.
//
//   The instrument's Phasor advances at exactly its own 48 kHz, so the rate at
//   which we must PUSH frames is the instrument's clock. That is loop one: watch
//   the gap between our write pointer and its read pointer, and pace the wall
//   clock to hold it.
//
//   The DAW fills our local ring at the host's 48 kHz, which is a different
//   number. That is loop two: step through the local ring at a fractional rate
//   set by how full it is, interpolating, so the difference between the two
//   clocks lands in a resampler rather than in an overflow.
//
// Loop one controls when a block is sent. Loop two controls what is in it.
//
// Mono, and that is arithmetic rather than taste: stereo ingress is ~420 kB/s,
// which alongside the 384 kB/s of capture exceeds the 719 kB/s section 8c
// measured as untroubled. Mono halves it and puts the pair inside what was
// measured. A mono send into a stereo effect is what a send is.
#pragma once

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <string>
#include <thread>
#include <vector>

namespace moogone {

// Samples per /b_setn. 256 keeps the datagram sub-MTU and, at 48 kHz, means 188
// messages a second against the 1000/s the interlock allows.
inline constexpr std::size_t kIngressBlock = 256;

// How far behind its own schedule the sender carries a deficit before giving up
// on it. Twenty milliseconds is four blocks: enough to absorb a slow send,
// short enough that making it up stays far below the interlock.
inline constexpr std::chrono::microseconds kMaxLag{20000};

// The same interlock sender.h enforces, restated here because this file has its
// own socket: two datagrams for one block must not go out back to back.
inline constexpr std::chrono::microseconds kMinIngressInterval{1000};

// Widest deviation from realtime the gap controller may ask for. Half a percent
// is above the ~0.3 % measured between two clocks and small enough that the pitch
// shift it implies is inaudible. More than this is a fault, not drift.
inline constexpr double kMaxIngressCorrection = 0.005;

// Mono, single producer (audio thread) / single consumer (sender thread).
// Fixed capacity and no allocation past construction: the producer is a callback.
class MonoRing {
public:
    explicit MonoRing(std::size_t frames);

    // Producer. Returns frames written; a short write means full, and dropping is
    // correct because blocking an audio callback never is.
    std::size_t write(const float *samples, std::size_t frames);

    std::size_t available() const;
    std::size_t capacity() const { return capacity_; }

    // Consumer, for the fractional reader.
    float peek(std::size_t offset) const;
    void consume(std::size_t frames);

private:
    std::vector<float> buf_;
    std::size_t capacity_;
    std::atomic<std::size_t> head_{0};   // consumer
    std::atomic<std::size_t> tail_{0};   // producer
};

// How far the writer is ahead of the reader, around the instrument's ring.
//
// Wrapped deliberately. The two pointers chase each other forever and their
// absolute values mean nothing; the distance is the only thing that says whether
// the next block lands on audio already played or audio not yet played.
std::size_t gapAhead(std::size_t write_pos, std::size_t read_pos, std::size_t frames);

// Rate multiplier that walks the gap back to `target`: proportional, slow, and
// clamped. The correction needed is permanent and tiny; what must not happen is a
// fast controller hunting, because every adjustment is a change of playback rate.
double rateCorrection(std::size_t gap, std::size_t target, std::size_t frames);

// Fills one block from the local ring at a fractional step, so the host's clock
// and the instrument's meet in a resampler instead of in an overflow.
//
// Linear interpolation on purpose: at steps within a fraction of a percent of
// unity the error is far below the instrument's noise floor. Starvation produces
// SILENCE rather than stale samples -- a repeated buffer is far more audible than
// a gap, and it also hides the fault.
class MonoReader {
public:
    MonoReader(MonoRing &ring, std::size_t target) : ring_(ring), target_(target) {}

    // Returns false if the ring starved and silence was written instead.
    bool read(float *out, std::size_t frames);

    double step() const { return step_; }
    std::uint64_t starved() const { return starved_; }

private:
    MonoRing &ring_;
    std::size_t target_;
    double position_ = 0.0;
    double step_ = 1.0;
    std::uint64_t starved_ = 0;
};

// Paces blocks at an absolute schedule, carrying a bounded deficit.
//
// THE BUG THIS EXISTS TO NOT REPEAT. Resetting the schedule whenever a block ran
// long looks like the safe choice -- catching up means sending faster and a burst
// is what costs a power cycle -- but it throws the overshoot away for good. On
// hardware that came to 0.982x realtime, and since the instrument reads at exactly
// 1.000x the lead drained at 864 frames a second: the round trip fell from 149 ms
// to 89 ms over five hits while the rate controller sat pinned at its clamp.
//
// Carrying the deficit is not a burst, because the caller sends exactly one block
// per pass: catching up only means not sleeping, and the 1 ms interlock still
// caps the rate. Only a stall longer than kMaxLag is given up on.
class Pacer {
public:
    using clock = std::chrono::steady_clock;

    void start(clock::time_point now) { next_ = now; }

    // How long to wait before the next block. Zero means "already due".
    // `rate` is the multiplier from the gap controller.
    std::chrono::nanoseconds tick(clock::time_point now, double rate, std::size_t block,
                                  double sample_rate);

    std::uint64_t resets() const { return resets_; }

private:
    clock::time_point next_{};
    std::uint64_t resets_ = 0;
};

// Owns the socket and the thread that feeds the instrument.
//
// The audio thread only ever calls feed(), which writes into a lock-free ring and
// returns. Everything else -- pacing, resampling, the gap poll, the sending --
// happens here, off the callback, for the reason sender.h states: this plugin must
// never do network I/O from the audio thread, and must never burst.
class IngressSender {
public:
    ~IngressSender();

    // `buffer` is the instrument's ring buffer id, `position_bus` the control bus
    // carrying its read pointer, `ring_frames` its length, `lead` the distance to
    // hold ahead of the reader. The lead is the latency and it is also the entire
    // margin against the reader catching up.
    bool start(const std::string &host, std::uint16_t port, std::int32_t buffer,
               std::int32_t position_bus, std::size_t ring_frames, std::size_t lead);
    void stop();

    // Audio thread. Never blocks, never allocates, never sends.
    void feed(const float *mono, std::size_t frames);

    std::uint64_t sent() const { return sent_.load(std::memory_order_relaxed); }
    std::uint64_t starved() const { return starved_.load(std::memory_order_relaxed); }
    std::size_t lead() const { return lead_; }
    double rate() const { return rate_.load(std::memory_order_relaxed); }

private:
    void run();
    // Returns false if the instrument did not answer; the caller keeps the last
    // rate rather than lurching, because a missed poll is not new information.
    bool pollPosition(std::size_t &out);

    MonoRing ring_{48000};
    std::thread worker_{};
    std::atomic<bool> running_{false};
    int fd_ = -1;
    std::string host_{};
    std::uint16_t port_ = 0;
    std::int32_t buffer_ = 0;
    std::int32_t position_bus_ = 0;
    std::size_t ring_frames_ = 0;
    std::size_t lead_ = 0;
    std::size_t write_pos_ = 0;
    std::atomic<double> rate_{1.0};
    std::atomic<std::uint64_t> sent_{0};
    std::atomic<std::uint64_t> starved_{0};
};

}  // namespace moogone
