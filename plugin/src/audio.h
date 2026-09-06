// The audio path: a lock-free ring, and a reader that survives two clocks.
//
// THE PROBLEM THIS FILE EXISTS FOR. The instrument samples at 48 kHz on its own
// crystal. The DAW samples at 48 kHz on its interface's. They are not the same
// clock and they diverge: a measured stream delivered 5.03 s of audio in 5.00 s of
// wall clock. Small, and over a five-minute take it is seconds.
//
// Ignoring it works perfectly in a demo. In a session the ring fills until it
// overflows or empties until it starves, and either way you hear it.
//
// So the reader runs VARISPEED: it advances a fractional position through the ring
// at a ratio nudged by how full the ring is, and interpolates between samples. The
// correction is slow and clamped, because a fast correction is a pitch artefact and
// an unclamped one turns a network hiccup into a glissando.
//
// Linear interpolation is the deliberate simplification. At ratios within a
// fraction of a percent of unity its error is far below the instrument's own noise
// floor; it would be the wrong choice for pitch-shifting and is the right one here.
#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace moogone {

// Stereo frames, single producer (network thread) / single consumer (audio thread).
class AudioRing {
public:
    explicit AudioRing(std::size_t frames);

    // Producer side. Returns frames actually written; short writes mean full.
    std::size_t write(const float *interleaved, std::size_t frames);

    // Consumer side, for the varispeed reader.
    std::size_t available() const;
    std::size_t capacity() const { return capacity_; }

    // Read one frame at an absolute frame position without consuming it.
    // Positions are relative to the consumer's cursor.
    void peek(std::size_t offset, float &left, float &right) const;
    void consume(std::size_t frames);

private:
    std::vector<float> buf_;      // interleaved stereo
    std::size_t capacity_;        // in frames
    std::atomic<std::size_t> head_{0};   // consumer, in frames
    std::atomic<std::size_t> tail_{0};   // producer, in frames
};

// Reads from the ring at a rate that tracks the producer, so neither clock wins.
class DriftReader {
public:
    // `target` is the ring fill the controller aims to hold, in frames. It must
    // absorb the measured 9.8 ms of jitter, so 20 ms is a floor and 40 ms is
    // comfortable.
    DriftReader(AudioRing &ring, std::size_t target);

    // Fill `left`/`right` with `frames`. Returns false if the ring starved and
    // silence was produced instead -- silence, not stale samples, because a
    // repeated buffer is a far more audible artefact than a gap.
    bool read(float *left, float *right, std::size_t frames);

    double ratio() const { return ratio_; }
    std::uint64_t starved() const { return starved_; }

    // Widest correction allowed, as a fraction. Clamped so that a network hiccup
    // cannot become an audible pitch slide.
    static constexpr double kMaxCorrection = 0.005;   // 0.5%

private:
    AudioRing &ring_;
    std::size_t target_;
    double position_ = 0.0;    // fractional frames past the consumer cursor
    double ratio_ = 1.0;
    std::uint64_t starved_ = 0;
};

}  // namespace moogone
