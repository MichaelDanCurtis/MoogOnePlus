// The pacing interlock, and the thread that owns the socket.
//
// Two rules this file exists to enforce, both learned expensively:
//
//   Never send from the audio thread. Parameter changes are queued lock-free and
//   a worker drains them.
//
//   Never burst. The instrument's LAN and its internal link to the voice
//   controller are two CDC-Ether functions of ONE USB gadget. Paced traffic at
//   1.47x the realtime audio rate is untroubled; 2000 datagrams sent back to back
//   wedge it below the level the host can reset, and only removing power clears
//   it. See docs/MOOG-ONE-INTERNALS.md section 8c.
#pragma once

#include <atomic>
#include <array>
#include <chrono>
#include <cstdint>
#include <string>
#include <thread>
#include <vector>

namespace moogone {

// Smallest gap between datagrams. 1 ms caps this at 1000/s, which is far more
// than parameter automation needs and two orders of magnitude below the burst
// that wedges the gadget.
inline constexpr std::chrono::microseconds kMinSendInterval{1000};

// One queued parameter write. Plain data so it can cross threads trivially.
struct Write {
    std::int32_t node = 0;
    std::array<char, 24> control{};
    float value = 0.0f;
};

// Single-producer (audio thread) / single-consumer (sender thread) ring.
// Fixed capacity and no allocation, because the producer is the audio callback.
class WriteQueue {
public:
    static constexpr std::size_t kCapacity = 1024;

    // Returns false when full. Dropping the oldest automation frame is correct:
    // a later one supersedes it, and blocking an audio callback never is.
    bool push(const Write &w);
    bool pop(Write &out);

private:
    std::array<Write, kCapacity> buf_{};
    std::atomic<std::size_t> head_{0};   // consumer
    std::atomic<std::size_t> tail_{0};   // producer
};

// A parameter's address on the instrument. Held as (defname, nth occurrence,
// control) and NEVER as a bare node id: node ids change when the instrument
// reloads its graph, and a stored one then silently addresses whatever took its
// place. `node` is filled in by resolve() and is only valid until the graph moves.
struct Target {
    const char *defname;
    int nth;                 // 0-based occurrence of that defname
    const char *control;
    const char *label;
    float min = 0.0f;
    float max = 1.0f;
    float initial = 0.0f;
    std::int32_t node = 0;   // resolved; 0 means "not found, inert"
};

class Sender {
public:
    Sender() = default;
    ~Sender();

    bool start(const std::string &host, std::uint16_t port);
    void stop();

    // Called from the audio thread. Never blocks, never allocates, never sends.
    bool queue(std::int32_t node, const char *control, float value);

    // Ask the instrument which node ids its synths currently have, and fill in
    // `targets`. Blocking, and called off the audio thread only.
    bool resolve(std::vector<Target> &targets, std::chrono::milliseconds timeout);

    std::uint64_t sent() const { return sent_.load(std::memory_order_relaxed); }
    std::uint64_t dropped() const { return dropped_.load(std::memory_order_relaxed); }

private:
    void run();

    WriteQueue queue_{};
    std::thread worker_{};
    std::atomic<bool> running_{false};
    int fd_ = -1;
    std::string host_{};
    std::uint16_t port_ = 0;
    std::atomic<std::uint64_t> sent_{0};
    std::atomic<std::uint64_t> dropped_{0};
};

}  // namespace moogone
