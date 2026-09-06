#include "ingress.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <algorithm>
#include <cmath>

#include "osc.h"

namespace moogone {

MonoRing::MonoRing(std::size_t frames) : buf_(frames, 0.0f), capacity_(frames) {}

std::size_t MonoRing::write(const float *samples, std::size_t frames) {
    const auto tail = tail_.load(std::memory_order_relaxed);
    const auto head = head_.load(std::memory_order_acquire);
    // One slot is left empty so full and empty are distinguishable without a
    // separate count, which a single-producer/single-consumer ring cannot keep
    // consistent across two threads without a lock.
    const std::size_t room = capacity_ - 1 - (tail - head) % capacity_;
    const std::size_t n = std::min(frames, room);
    for (std::size_t i = 0; i < n; ++i) buf_[(tail + i) % capacity_] = samples[i];
    tail_.store((tail + n) % capacity_, std::memory_order_release);
    return n;
}

std::size_t MonoRing::available() const {
    const auto tail = tail_.load(std::memory_order_acquire);
    const auto head = head_.load(std::memory_order_relaxed);
    return (tail - head + capacity_) % capacity_;
}

float MonoRing::peek(std::size_t offset) const {
    const auto head = head_.load(std::memory_order_relaxed);
    return buf_[(head + offset) % capacity_];
}

void MonoRing::consume(std::size_t frames) {
    const auto head = head_.load(std::memory_order_relaxed);
    head_.store((head + frames) % capacity_, std::memory_order_release);
}

std::size_t gapAhead(std::size_t write_pos, std::size_t read_pos, std::size_t frames) {
    if (frames == 0) return 0;
    return (write_pos + frames - read_pos % frames) % frames;
}

double rateCorrection(std::size_t gap, std::size_t target, std::size_t frames) {
    if (frames == 0) return 1.0;
    const double error = (static_cast<double>(gap) - static_cast<double>(target)) /
                         static_cast<double>(frames);
    const double wanted = -error * 0.5;
    return 1.0 + std::clamp(wanted, -kMaxIngressCorrection, kMaxIngressCorrection);
}

bool MonoReader::read(float *out, std::size_t frames) {
    // The step tracks the local ring's fill, which is where the host's clock and
    // the instrument's differ. Same shape as DriftReader in audio.h, and clamped
    // for the same reason: an unclamped correction turns a hiccup into a slide.
    const double fill = static_cast<double>(ring_.available());
    const double error = (fill - static_cast<double>(target_)) /
                         std::max<double>(1.0, static_cast<double>(ring_.capacity()));
    step_ = 1.0 + std::clamp(error * 0.5, -kMaxIngressCorrection, kMaxIngressCorrection);

    // Interpolating at `position_ + 1` needs one sample past the last one read,
    // so the check is for the frames consumed PLUS the interpolation partner.
    const double needed = position_ + step_ * static_cast<double>(frames) + 1.0;
    if (static_cast<double>(ring_.available()) < needed) {
        ++starved_;
        for (std::size_t i = 0; i < frames; ++i) out[i] = 0.0f;
        return false;
    }

    for (std::size_t i = 0; i < frames; ++i) {
        const auto index = static_cast<std::size_t>(position_);
        const double frac = position_ - static_cast<double>(index);
        const float a = ring_.peek(index);
        const float b = ring_.peek(index + 1);
        out[i] = static_cast<float>(a + (b - a) * frac);
        position_ += step_;
    }

    const auto whole = static_cast<std::size_t>(position_);
    ring_.consume(whole);
    position_ -= static_cast<double>(whole);
    return true;
}

std::chrono::nanoseconds Pacer::tick(clock::time_point now, double rate, std::size_t block,
                                     double sample_rate) {
    const double seconds = static_cast<double>(block) / (sample_rate * rate);
    next_ += std::chrono::duration_cast<clock::duration>(
        std::chrono::duration<double>(seconds));
    const auto delay = next_ - now;
    if (delay > clock::duration::zero()) {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(delay);
    }
    if (-delay > std::chrono::duration_cast<clock::duration>(kMaxLag)) {
        // A real stall. Chasing it would mean sending the whole backlog as fast as
        // the interlock allows, which is the shape that wedges the gadget.
        ++resets_;
        next_ = now;
    }
    return std::chrono::nanoseconds::zero();
}

IngressSender::~IngressSender() { stop(); }

bool IngressSender::start(const std::string &host, std::uint16_t port, std::int32_t buffer,
                          std::int32_t position_bus, std::size_t ring_frames,
                          std::size_t lead) {
    if (running_.load()) return true;
    fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd_ < 0) return false;
    // A read timeout, not a blocking read: the gap poll must not hang the sender
    // thread when the instrument does not answer, because the sender thread is
    // what keeps the instrument's ring fed.
    timeval tv{};
    tv.tv_usec = 200000;
    ::setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    host_ = host;
    port_ = port;
    buffer_ = buffer;
    position_bus_ = position_bus;
    ring_frames_ = ring_frames;
    lead_ = lead;
    write_pos_ = 0;
    running_.store(true);
    worker_ = std::thread([this] { run(); });
    return true;
}

void IngressSender::stop() {
    if (!running_.exchange(false)) return;
    if (worker_.joinable()) worker_.join();
    if (fd_ >= 0) { ::close(fd_); fd_ = -1; }
}

void IngressSender::feed(const float *mono, std::size_t frames) {
    ring_.write(mono, frames);
}

bool IngressSender::pollPosition(std::size_t &out) {
    sockaddr_in to{};
    to.sin_family = AF_INET;
    to.sin_port = htons(port_);
    if (::inet_pton(AF_INET, host_.c_str(), &to.sin_addr) != 1) return false;
    const auto ask = c_get(position_bus_);
    if (::sendto(fd_, ask.data(), ask.size(), 0, reinterpret_cast<sockaddr *>(&to),
                 sizeof(to)) < 0) {
        return false;
    }
    std::uint8_t buf[1024];
    const auto n = ::recv(fd_, buf, sizeof(buf), 0);
    if (n <= 0) return false;
    OscIncoming in;
    if (!decode(buf, static_cast<std::size_t>(n), in)) return false;
    if (in.address != "/c_set" || in.args.size() < 2) return false;
    const auto &v = in.args[1];
    const double value = v.tag == 'f' ? v.f : static_cast<double>(v.i);
    if (value < 0.0) return false;
    out = static_cast<std::size_t>(value);
    return true;
}

void IngressSender::run() {
    MonoReader reader(ring_, ring_.capacity() / 4);
    Pacer pacer;
    auto now = Pacer::clock::now();
    pacer.start(now);
    auto polled_at = now;

    sockaddr_in to{};
    to.sin_family = AF_INET;
    to.sin_port = htons(port_);
    ::inet_pton(AF_INET, host_.c_str(), &to.sin_addr);

    std::vector<float> block(kIngressBlock);
    while (running_.load(std::memory_order_relaxed)) {
        if (!reader.read(block.data(), block.size())) {
            starved_.fetch_add(1, std::memory_order_relaxed);
        }

        // A buffer write does not wrap, so a block that would run off the end goes
        // as two messages. Sending it as one is rejected with a /fail nothing is
        // waiting for, which means the audio simply goes missing.
        const std::size_t room = ring_frames_ - write_pos_;
        const std::size_t head = std::min(room, block.size());
        auto first = b_setn(buffer_, static_cast<std::int32_t>(write_pos_), block.data(), head);
        ::sendto(fd_, first.data(), first.size(), 0, reinterpret_cast<sockaddr *>(&to),
                 sizeof(to));
        sent_.fetch_add(1, std::memory_order_relaxed);
        if (head < block.size()) {
            std::this_thread::sleep_for(kMinIngressInterval);
            auto rest = b_setn(buffer_, 0, block.data() + head, block.size() - head);
            ::sendto(fd_, rest.data(), rest.size(), 0, reinterpret_cast<sockaddr *>(&to),
                     sizeof(to));
            sent_.fetch_add(1, std::memory_order_relaxed);
        }
        write_pos_ = (write_pos_ + block.size()) % ring_frames_;

        now = Pacer::clock::now();
        if (now - polled_at > std::chrono::milliseconds(250)) {
            polled_at = now;
            std::size_t where = 0;
            if (pollPosition(where)) {
                rate_.store(rateCorrection(gapAhead(write_pos_, where, ring_frames_), lead_,
                                           ring_frames_),
                            std::memory_order_relaxed);
            }
            now = Pacer::clock::now();
        }

        const auto wait = pacer.tick(now, rate_.load(std::memory_order_relaxed), block.size(),
                                     48000.0);
        if (wait > std::chrono::nanoseconds::zero()) std::this_thread::sleep_for(wait);
    }
}

}  // namespace moogone
