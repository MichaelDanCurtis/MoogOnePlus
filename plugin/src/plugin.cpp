// MoogOne.clap -- the control surface.
//
// Exposes the instrument's effects engine as DAW-automatable parameters. There is
// deliberately NO audio path in this shape: no clock drift to solve, no real-time
// audio risk, and therefore the right place to prove the OSC path, the parameter
// map, and the pacing interlock under a real host. See docs/PLUGIN.md.
//
// The two rules the structure exists to honour:
//
//   process() NEVER sends. It drains the host's parameter events into a lock-free
//   queue and returns. Network I/O in an audio callback is a dropout.
//
//   Nothing bursts. The sender paces every datagram, because the instrument's LAN
//   and its internal voice-controller link are two functions of one USB gadget,
//   and an unpaced burst wedges it past the host's ability to reset.
#include <clap/clap.h>

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "audio.h"
#include "receiver.h"
#include "sender.h"

namespace {

// Addressed by (defname, nth, control) -- never by node id. The instrument's
// effects graph was read from the hardware to build this: two delays, a chorus,
// and a family of reverbs.
std::vector<moogone::Target> default_targets() {
    return {
        {"delay_0",        0, "mix",      "Delay 1 Mix",       0.0f, 1.0f, 0.25f},
        {"delay_0",        0, "time",     "Delay 1 Time",      0.0f, 1.0f, 0.35f},
        {"delay_0",        0, "feedback", "Delay 1 Feedback",  0.0f, 1.0f, 0.40f},
        {"delay_0",        1, "mix",      "Delay 2 Mix",       0.0f, 1.0f, 0.25f},
        {"delay_0",        1, "time",     "Delay 2 Time",      0.0f, 1.0f, 0.35f},
        {"delay_0",        1, "feedback", "Delay 2 Feedback",  0.0f, 1.0f, 0.40f},
        {"stereoChorus_0", 0, "mix",      "Chorus Mix",        0.0f, 1.0f, 0.30f},
        {"et_room_1",      0, "mix",      "Room Mix",          0.0f, 1.0f, 0.30f},
        {"et_room_1",      0, "size",     "Room Size",         0.0f, 1.0f, 0.75f},
        {"et_room_1",      0, "decay",    "Room Decay",        0.0f, 1.0f, 0.17f},
        {"et_hall_1",      0, "mix",      "Hall Mix",          0.0f, 1.0f, 0.30f},
        {"et_hall_1",      0, "size",     "Hall Size",         0.0f, 1.0f, 0.75f},
        {"et_plate_1",     0, "mix",      "Plate Mix",         0.0f, 1.0f, 0.30f},
        {"et_shimmer_1",   0, "mix",      "Shimmer Mix",       0.0f, 1.0f, 0.30f},
        {"et_blackhole_1", 0, "mix",      "Blackhole Mix",     0.0f, 1.0f, 0.30f},
    };
}

const char *const kFeatures[] = {CLAP_PLUGIN_FEATURE_INSTRUMENT,
                                 CLAP_PLUGIN_FEATURE_STEREO, nullptr};

// Ring depth, in frames at 48 kHz. The measured jitter on this path is 9.8 ms,
// so 20 ms is a floor; 40 ms is the comfortable number and what the reader aims
// to hold. The ring itself is a second, so a stall has somewhere to go.
constexpr std::size_t kRingFrames = 48000;
constexpr std::size_t kTargetFrames = 1920;      // 40 ms

// What the host should compensate for: the measured 22.9 ms from trigger to
// sound, plus the ring the reader holds. Reporting this wrong makes everything
// recorded through the plugin land late, silently.
constexpr double kInstrumentLatencySeconds = 0.0229;

const clap_plugin_descriptor_t kDescriptor = {
    CLAP_VERSION_INIT,
    "dev.moogoneplus.control-surface",
    "Moog One Control Surface",
    "MoogOnePlus",
    "https://github.com/",
    "",
    "",
    "0.1.0",
    "Play the Moog One, capture its audio, automate its effects.",
    kFeatures,
};

struct Plugin {
    clap_plugin_t plugin{};
    const clap_host_t *host = nullptr;

    moogone::Sender sender;
    moogone::AudioRing ring{kRingFrames};
    moogone::DriftReader reader{ring, kTargetFrames};
    moogone::Receiver receiver{ring};
    std::uint16_t audio_port = 14150;
    double sample_rate = 48000.0;
    std::vector<moogone::Target> targets = default_targets();
    std::vector<float> values;
    std::string host_addr = "192.168.1.138";
    std::uint16_t port = 57110;
    bool resolved = false;

    Plugin() {
        values.reserve(targets.size());
        for (const auto &t : targets) values.push_back(t.initial);
    }
};

Plugin *self(const clap_plugin_t *p) { return static_cast<Plugin *>(p->plugin_data); }

// -- params ------------------------------------------------------------------

std::uint32_t params_count(const clap_plugin_t *p) {
    return static_cast<std::uint32_t>(self(p)->targets.size());
}

bool params_get_info(const clap_plugin_t *p, std::uint32_t index,
                     clap_param_info_t *info) {
    auto *s = self(p);
    if (index >= s->targets.size()) return false;
    const auto &t = s->targets[index];
    std::memset(info, 0, sizeof(*info));
    info->id = index;
    info->flags = CLAP_PARAM_IS_AUTOMATABLE;
    info->min_value = t.min;
    info->max_value = t.max;
    info->default_value = t.initial;
    std::snprintf(info->name, sizeof(info->name), "%s", t.label);
    std::snprintf(info->module, sizeof(info->module), "%s", t.defname);
    return true;
}

bool params_get_value(const clap_plugin_t *p, clap_id id, double *out) {
    auto *s = self(p);
    if (id >= s->values.size()) return false;
    *out = s->values[id];
    return true;
}

bool params_value_to_text(const clap_plugin_t *p, clap_id id, double value,
                          char *out, std::uint32_t size) {
    auto *s = self(p);
    if (id >= s->targets.size()) return false;
    // An unresolved target is inert, and saying so beats showing a number that
    // goes nowhere.
    if (s->targets[id].node == 0) {
        std::snprintf(out, size, "%.3f (not connected)", value);
    } else {
        std::snprintf(out, size, "%.3f", value);
    }
    return true;
}

bool params_text_to_value(const clap_plugin_t *, clap_id, const char *text,
                          double *out) {
    try {
        *out = std::stod(text);
    } catch (...) {
        return false;
    }
    return true;
}

void params_flush(const clap_plugin_t *p, const clap_input_events_t *in,
                  const clap_output_events_t *) {
    auto *s = self(p);
    const std::uint32_t n = in ? in->size(in) : 0;
    for (std::uint32_t i = 0; i < n; ++i) {
        const auto *e = in->get(in, i);
        if (e->type != CLAP_EVENT_PARAM_VALUE) continue;
        const auto *pv = reinterpret_cast<const clap_event_param_value_t *>(e);
        if (pv->param_id >= s->values.size()) continue;
        s->values[pv->param_id] = static_cast<float>(pv->value);
        const auto &t = s->targets[pv->param_id];
        if (t.node != 0) s->sender.queue(t.node, t.control, static_cast<float>(pv->value));
    }
}

const clap_plugin_params_t kParams = {
    params_count, params_get_info, params_get_value,
    params_value_to_text, params_text_to_value, params_flush,
};

// -- audio ports --------------------------------------------------------------

std::uint32_t ports_count(const clap_plugin_t *, bool is_input) {
    return is_input ? 0 : 1;      // no inputs: this shape captures, it does not process
}

bool ports_get(const clap_plugin_t *, std::uint32_t index, bool is_input,
               clap_audio_port_info_t *info) {
    if (is_input || index != 0) return false;
    std::memset(info, 0, sizeof(*info));
    info->id = 0;
    std::snprintf(info->name, sizeof(info->name), "Moog One");
    info->channel_count = 2;
    info->flags = CLAP_AUDIO_PORT_IS_MAIN;
    info->port_type = CLAP_PORT_STEREO;
    info->in_place_pair = CLAP_INVALID_ID;
    return true;
}

const clap_plugin_audio_ports_t kAudioPorts = {ports_count, ports_get};

// -- latency ------------------------------------------------------------------

std::uint32_t latency_get(const clap_plugin_t *p) {
    auto *s = self(p);
    return static_cast<std::uint32_t>(kInstrumentLatencySeconds * s->sample_rate) +
           static_cast<std::uint32_t>(kTargetFrames);
}

const clap_plugin_latency_t kLatency = {latency_get};

// -- plugin ------------------------------------------------------------------

bool plugin_init(const clap_plugin_t *p) {
    auto *s = self(p);
    if (const char *env = std::getenv("MOOGONE_HOST")) s->host_addr = env;
    if (const char *env = std::getenv("MOOGONE_AUDIO_PORT")) {
        s->audio_port = static_cast<std::uint16_t>(std::atoi(env));
    }
    // The listener comes up FIRST. Resolving blocks for up to a second and a half,
    // and anything already trying to connect during that window is refused and
    // gives up -- which reads as "the plugin produces no audio" and is really
    // "the audio path waited on the control path for no reason".
    s->receiver.start(s->audio_port);
    s->sender.start(s->host_addr, s->port);
    s->resolved = s->sender.resolve(s->targets, std::chrono::milliseconds(1500));
    return true;
}

void plugin_destroy(const clap_plugin_t *p) {
    auto *s = self(p);
    s->receiver.stop();
    s->sender.stop();
    delete s;
}

bool plugin_activate(const clap_plugin_t *p, double sample_rate, std::uint32_t,
                     std::uint32_t) {
    auto *s = self(p);
    s->sample_rate = sample_rate;
    if (!s->resolved) {
        s->resolved = s->sender.resolve(s->targets, std::chrono::milliseconds(1500));
    }
    return true;
}

void plugin_deactivate(const clap_plugin_t *) {}
bool plugin_start_processing(const clap_plugin_t *) { return true; }
void plugin_stop_processing(const clap_plugin_t *) {}
void plugin_reset(const clap_plugin_t *) {}

clap_process_status plugin_process(const clap_plugin_t *p,
                                   const clap_process_t *process) {
    auto *s = self(p);
    // Parameter events are QUEUED, never sent: this function must not do network
    // I/O, allocate, or block.
    params_flush(p, process->in_events, process->out_events);

    if (process->audio_outputs_count > 0 &&
        process->audio_outputs[0].channel_count >= 2) {
        auto **out = process->audio_outputs[0].data32;
        // Varispeed read. The instrument's clock is not the host's, and the
        // reader tracks the difference; see audio.h.
        s->reader.read(out[0], out[1], process->frames_count);
    }
    return CLAP_PROCESS_CONTINUE;
}

const void *plugin_get_extension(const clap_plugin_t *, const char *id) {
    if (std::strcmp(id, CLAP_EXT_PARAMS) == 0) return &kParams;
    if (std::strcmp(id, CLAP_EXT_AUDIO_PORTS) == 0) return &kAudioPorts;
    if (std::strcmp(id, CLAP_EXT_LATENCY) == 0) return &kLatency;
    return nullptr;
}

void plugin_on_main_thread(const clap_plugin_t *) {}

const clap_plugin_t *create(const clap_host_t *host) {
    auto *s = new Plugin();
    s->host = host;
    s->plugin.desc = &kDescriptor;
    s->plugin.plugin_data = s;
    s->plugin.init = plugin_init;
    s->plugin.destroy = plugin_destroy;
    s->plugin.activate = plugin_activate;
    s->plugin.deactivate = plugin_deactivate;
    s->plugin.start_processing = plugin_start_processing;
    s->plugin.stop_processing = plugin_stop_processing;
    s->plugin.reset = plugin_reset;
    s->plugin.process = plugin_process;
    s->plugin.get_extension = plugin_get_extension;
    s->plugin.on_main_thread = plugin_on_main_thread;
    return &s->plugin;
}

// -- factory -----------------------------------------------------------------

std::uint32_t factory_count(const clap_plugin_factory_t *) { return 1; }

const clap_plugin_descriptor_t *factory_descriptor(const clap_plugin_factory_t *,
                                                   std::uint32_t index) {
    return index == 0 ? &kDescriptor : nullptr;
}

const clap_plugin_t *factory_create(const clap_plugin_factory_t *,
                                    const clap_host_t *host, const char *id) {
    if (!id || std::strcmp(id, kDescriptor.id) != 0) return nullptr;
    return create(host);
}

const clap_plugin_factory_t kFactory = {factory_count, factory_descriptor,
                                        factory_create};

bool entry_init(const char *) { return true; }
void entry_deinit() {}

const void *entry_get_factory(const char *id) {
    if (std::strcmp(id, CLAP_PLUGIN_FACTORY_ID) == 0) return &kFactory;
    return nullptr;
}

}  // namespace

extern "C" CLAP_EXPORT const clap_plugin_entry_t clap_entry = {
    CLAP_VERSION_INIT, entry_init, entry_deinit, entry_get_factory,
};
