#include "receiver.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cstring>
#include <vector>

namespace moogone {

Receiver::~Receiver() { stop(); }

bool Receiver::start(std::uint16_t port) {
    stop();
    listen_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd_ < 0) return false;
    int yes = 1;
    ::setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);
    if (::bind(listen_fd_, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0 ||
        ::listen(listen_fd_, 1) < 0) {
        ::close(listen_fd_);
        listen_fd_ = -1;
        return false;
    }
    running_.store(true, std::memory_order_release);
    worker_ = std::thread(&Receiver::run, this);
    return true;
}

void Receiver::stop() {
    running_.store(false, std::memory_order_release);
    if (listen_fd_ >= 0) {
        ::shutdown(listen_fd_, SHUT_RDWR);
        ::close(listen_fd_);
        listen_fd_ = -1;
    }
    if (worker_.joinable()) worker_.join();
    connected_.store(false, std::memory_order_release);
}

void Receiver::run() {
    constexpr std::size_t kChunkFrames = 512;
    std::vector<float> chunk(kChunkFrames * 2);
    std::vector<std::uint8_t> spill;   // a partial frame across a recv boundary

    while (running_.load(std::memory_order_acquire)) {
        timeval tv{1, 0};
        ::setsockopt(listen_fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        const int fd = ::accept(listen_fd_, nullptr, nullptr);
        if (fd < 0) continue;
        connected_.store(true, std::memory_order_release);
        // The stream is continuous; Nagle would add latency for nothing.
        int yes = 1;
        ::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
        ::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        std::vector<std::uint8_t> buf(kChunkFrames * 2 * sizeof(float));
        while (running_.load(std::memory_order_acquire)) {
            const auto n = ::recv(fd, buf.data(), buf.size(), 0);
            if (n == 0) break;                       // the instrument hung up
            if (n < 0) continue;                     // timeout; check running_

            // A recv can split a stereo frame down the middle. Carrying the
            // remainder is not fussiness: dropping it swaps left and right for
            // the rest of the stream.
            spill.insert(spill.end(), buf.begin(), buf.begin() + n);
            const std::size_t frame_bytes = 2 * sizeof(float);
            const std::size_t whole = spill.size() / frame_bytes;
            if (whole) {
                std::size_t done = 0;
                while (done < whole) {
                    const std::size_t batch = std::min(whole - done, kChunkFrames);
                    std::memcpy(chunk.data(), spill.data() + done * frame_bytes,
                                batch * frame_bytes);
                    const auto wrote = ring_.write(chunk.data(), batch);
                    if (wrote < batch) {
                        overruns_.fetch_add(batch - wrote, std::memory_order_relaxed);
                    }
                    frames_.fetch_add(wrote, std::memory_order_relaxed);
                    done += batch;
                }
                spill.erase(spill.begin(),
                            spill.begin() + static_cast<long>(whole * frame_bytes));
            }
        }
        ::close(fd);
        connected_.store(false, std::memory_order_release);
    }
}

}  // namespace moogone
