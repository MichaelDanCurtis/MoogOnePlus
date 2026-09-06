#include "audio.h"

#include <algorithm>
#include <cmath>

namespace moogone {

AudioRing::AudioRing(std::size_t frames)
    : buf_(frames * 2, 0.0f), capacity_(frames) {}

std::size_t AudioRing::write(const float *interleaved, std::size_t frames) {
    const auto tail = tail_.load(std::memory_order_relaxed);
    const auto head = head_.load(std::memory_order_acquire);
    // One frame is left unused so full and empty stay distinguishable.
    const std::size_t used = (tail + capacity_ - head) % capacity_;
    const std::size_t room = capacity_ - used - 1;
    const std::size_t n = std::min(frames, room);
    for (std::size_t i = 0; i < n; ++i) {
        const std::size_t slot = ((tail + i) % capacity_) * 2;
        buf_[slot] = interleaved[i * 2];
        buf_[slot + 1] = interleaved[i * 2 + 1];
    }
    tail_.store((tail + n) % capacity_, std::memory_order_release);
    return n;
}

std::size_t AudioRing::available() const {
    const auto tail = tail_.load(std::memory_order_acquire);
    const auto head = head_.load(std::memory_order_relaxed);
    return (tail + capacity_ - head) % capacity_;
}

void AudioRing::peek(std::size_t offset, float &left, float &right) const {
    const auto head = head_.load(std::memory_order_relaxed);
    const std::size_t slot = ((head + offset) % capacity_) * 2;
    left = buf_[slot];
    right = buf_[slot + 1];
}

void AudioRing::consume(std::size_t frames) {
    const auto head = head_.load(std::memory_order_relaxed);
    head_.store((head + frames) % capacity_, std::memory_order_release);
}

DriftReader::DriftReader(AudioRing &ring, std::size_t target)
    : ring_(ring), target_(target) {}

bool DriftReader::read(float *left, float *right, std::size_t frames) {
    const std::size_t have = ring_.available();

    // The controller. Deliberately slow: it corrects a clock difference measured
    // in fractions of a percent, not a buffer glitch. A fast loop here would
    // chase jitter and modulate pitch at the jitter's rate, which is worse than
    // the drift it is fixing.
    const double error = (static_cast<double>(have) - static_cast<double>(target_)) /
                         static_cast<double>(target_ ? target_ : 1);
    const double wanted = 1.0 + std::clamp(error * 0.05, -kMaxCorrection, kMaxCorrection);
    ratio_ += (wanted - ratio_) * 0.01;      // smooth towards it

    // Frames needed at this ratio, plus one for the interpolation partner.
    const std::size_t needed =
        static_cast<std::size_t>(std::ceil(position_ + ratio_ * frames)) + 2;
    if (have < needed) {
        // Starved. Silence rather than stale samples: a repeated buffer is a much
        // more audible artefact than a gap, and it hides the problem.
        for (std::size_t i = 0; i < frames; ++i) left[i] = right[i] = 0.0f;
        ++starved_;
        return false;
    }

    for (std::size_t i = 0; i < frames; ++i) {
        const auto index = static_cast<std::size_t>(position_);
        const double frac = position_ - static_cast<double>(index);
        float l0, r0, l1, r1;
        ring_.peek(index, l0, r0);
        ring_.peek(index + 1, l1, r1);
        left[i] = static_cast<float>(l0 + (l1 - l0) * frac);
        right[i] = static_cast<float>(r0 + (r1 - r0) * frac);
        position_ += ratio_;
    }

    const auto whole = static_cast<std::size_t>(position_);
    ring_.consume(whole);
    position_ -= static_cast<double>(whole);
    return true;
}

}  // namespace moogone
