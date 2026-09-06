#include "sender.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cstring>

#include "osc.h"

namespace moogone {

bool WriteQueue::push(const Write &w) {
    const auto tail = tail_.load(std::memory_order_relaxed);
    const auto next = (tail + 1) % kCapacity;
    if (next == head_.load(std::memory_order_acquire)) {
        return false;                       // full
    }
    buf_[tail] = w;
    tail_.store(next, std::memory_order_release);
    return true;
}

bool WriteQueue::pop(Write &out) {
    const auto head = head_.load(std::memory_order_relaxed);
    if (head == tail_.load(std::memory_order_acquire)) {
        return false;                       // empty
    }
    out = buf_[head];
    head_.store((head + 1) % kCapacity, std::memory_order_release);
    return true;
}

Sender::~Sender() { stop(); }

bool Sender::start(const std::string &host, std::uint16_t port) {
    stop();
    host_ = host;
    port_ = port;
    fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd_ < 0) return false;
    running_.store(true, std::memory_order_release);
    worker_ = std::thread(&Sender::run, this);
    return true;
}

void Sender::stop() {
    if (running_.exchange(false, std::memory_order_acq_rel)) {
        if (worker_.joinable()) worker_.join();
    }
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
}

bool Sender::queue(std::int32_t node, const char *control, float value) {
    Write w;
    w.node = node;
    // Bounded copy: the audio thread must not touch a heap or a std::string.
    std::strncpy(w.control.data(), control, w.control.size() - 1);
    w.value = value;
    if (!queue_.push(w)) {
        // Full. Dropping is correct -- a newer automation frame supersedes this
        // one, and blocking an audio callback to make room never is.
        dropped_.fetch_add(1, std::memory_order_relaxed);
        return false;
    }
    return true;
}

namespace {

// Walk a /g_queryTree.reply, recording the node id of every synth by defname and
// occurrence. The reply is a flat run: for each node, its id and its child count
// (-1 marks a synth), then for a synth its defname, its control count, and that
// many name/value pairs.
void collect(const std::vector<OscValue> &a, std::size_t &i,
             std::vector<std::pair<std::string, std::int32_t>> &found) {
    if (i + 1 >= a.size()) return;
    const std::int32_t id = a[i].i;
    const std::int32_t children = a[i + 1].i;
    i += 2;
    if (children == -1) {
        if (i >= a.size()) return;
        const std::string defname = a[i].s;
        ++i;
        if (i >= a.size()) return;
        const std::int32_t ncontrols = a[i].i;
        ++i;
        i += static_cast<std::size_t>(ncontrols) * 2;   // name/value pairs
        found.emplace_back(defname, id);
        return;
    }
    for (std::int32_t k = 0; k < children; ++k) collect(a, i, found);
}

}  // namespace

bool Sender::resolve(std::vector<Target> &targets,
                     std::chrono::milliseconds timeout) {
    if (fd_ < 0) return false;
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port_);
    if (::inet_pton(AF_INET, host_.c_str(), &addr.sin_addr) != 1) return false;

    const auto query = OscMessage("/g_queryTree").i(0).i(1).encode();
    if (::sendto(fd_, query.data(), query.size(), 0,
                 reinterpret_cast<const sockaddr *>(&addr), sizeof(addr)) < 0) {
        return false;
    }

    timeval tv{};
    tv.tv_sec = timeout.count() / 1000;
    tv.tv_usec = (timeout.count() % 1000) * 1000;
    ::setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    std::vector<std::uint8_t> buf(65536);
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        const auto n = ::recv(fd_, buf.data(), buf.size(), 0);
        if (n <= 0) break;
        OscIncoming in;
        if (!decode(buf.data(), static_cast<std::size_t>(n), in)) continue;
        if (in.address != "/g_queryTree.reply") continue;   // not ours; keep waiting

        std::vector<std::pair<std::string, std::int32_t>> found;
        std::size_t i = 1;                                  // arg 0 is the flag
        collect(in.args, i, found);

        for (auto &t : targets) {
            t.node = 0;
            int seen = 0;
            for (const auto &[name, id] : found) {
                if (name == t.defname && seen++ == t.nth) {
                    t.node = id;
                    break;
                }
            }
        }
        return true;
    }
    return false;
}

void Sender::run() {
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port_);
    if (::inet_pton(AF_INET, host_.c_str(), &addr.sin_addr) != 1) {
        running_.store(false, std::memory_order_release);
        return;
    }

    auto last = std::chrono::steady_clock::now() - kMinSendInterval;
    Write w;
    while (running_.load(std::memory_order_acquire)) {
        if (!queue_.pop(w)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }
        // The interlock. A steady clock, because a wall clock stepping backwards
        // would hand out an unbounded wait -- and the wait is clamped to one
        // interval for the same reason.
        const auto now = std::chrono::steady_clock::now();
        auto wait = (last + kMinSendInterval) - now;
        if (wait > kMinSendInterval) wait = kMinSendInterval;
        if (wait.count() > 0) std::this_thread::sleep_for(wait);
        last = std::chrono::steady_clock::now();

        const auto packet = n_set(w.node, w.control.data(), w.value);
        ::sendto(fd_, packet.data(), packet.size(), 0,
                 reinterpret_cast<const sockaddr *>(&addr), sizeof(addr));
        sent_.fetch_add(1, std::memory_order_relaxed);
    }
}

}  // namespace moogone
