// Receives the instrument's audio over TCP and fills the ring.
//
// TCP rather than UDP, and not only for reliability: TCP paces itself, and this
// instrument's USB network gadget wedges under unpaced bursts (see
// docs/MOOG-ONE-INTERNALS.md section 8c). The audio path being self-pacing is why
// streaming OUT was safe from the first attempt while OSC needed an interlock.
//
// The wire format is raw interleaved float32, little-endian, 48 kHz stereo --
// what `scsynth` writes when its DiskOut buffer is opened as "raw"/"float". Raw
// rather than WAV because a WAV header carries a length that must be seeked back
// and written at close, and a stream has no end to seek to.
#pragma once

#include <atomic>
#include <cstdint>
#include <thread>

#include "audio.h"

namespace moogone {

class Receiver {
public:
    explicit Receiver(AudioRing &ring) : ring_(ring) {}
    ~Receiver();

    // Listens on `port` for the instrument to connect. Non-blocking: the accept
    // happens on the worker thread.
    bool start(std::uint16_t port);
    void stop();

    bool connected() const { return connected_.load(std::memory_order_relaxed); }
    std::uint64_t frames() const { return frames_.load(std::memory_order_relaxed); }
    std::uint64_t overruns() const { return overruns_.load(std::memory_order_relaxed); }

private:
    void run();

    AudioRing &ring_;
    std::thread worker_{};
    std::atomic<bool> running_{false};
    std::atomic<bool> connected_{false};
    std::atomic<std::uint64_t> frames_{0};
    std::atomic<std::uint64_t> overruns_{0};
    int listen_fd_ = -1;
};

}  // namespace moogone
