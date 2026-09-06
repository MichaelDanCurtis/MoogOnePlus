// A minimal CLAP host, just enough to prove the plugin works against the real
// instrument: load the bundle, create the plugin, let it resolve its targets, and
// push one parameter change through process() the way a DAW would.
//
// Not a test of CLAP. A test that THIS plugin talks to THAT instrument.
#include <dlfcn.h>

#include <clap/clap.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

namespace {

std::vector<clap_event_param_value_t> g_events;

std::uint32_t ev_size(const clap_input_events_t *) {
    return static_cast<std::uint32_t>(g_events.size());
}
const clap_event_header_t *ev_get(const clap_input_events_t *, std::uint32_t i) {
    return &g_events[i].header;
}

}  // namespace

int main(int argc, char **argv) {
    const char *bundle = argc > 1 ? argv[1]
                                  : "build/MoogOne.clap/Contents/MacOS/MoogOne";
    const int param = argc > 2 ? std::atoi(argv[2]) : 0;
    const double value = argc > 3 ? std::atof(argv[3]) : 0.9;

    void *lib = dlopen(bundle, RTLD_NOW | RTLD_LOCAL);
    if (!lib) {
        std::printf("could not load %s: %s\n", bundle, dlerror());
        return 1;
    }
    auto *entry = static_cast<const clap_plugin_entry_t *>(dlsym(lib, "clap_entry"));
    if (!entry) { std::printf("no clap_entry\n"); return 1; }
    if (!entry->init(bundle)) { std::printf("entry init failed\n"); return 1; }

    auto *factory = static_cast<const clap_plugin_factory_t *>(
        entry->get_factory(CLAP_PLUGIN_FACTORY_ID));
    const auto *desc = factory->get_plugin_descriptor(factory, 0);
    std::printf("plugin: %s %s\n", desc->name, desc->version);

    clap_host_t host{};
    host.clap_version = CLAP_VERSION_INIT;
    host.name = "moogone-harness";
    host.version = "0.1.0";
    host.get_extension = [](const clap_host_t *, const char *) -> const void * {
        return nullptr;
    };
    host.request_restart = [](const clap_host_t *) {};
    host.request_process = [](const clap_host_t *) {};
    host.request_callback = [](const clap_host_t *) {};

    const clap_plugin_t *p = factory->create_plugin(factory, &host, desc->id);
    if (!p) { std::printf("create failed\n"); return 1; }
    if (!p->init(p)) { std::printf("init failed\n"); return 1; }

    const auto *params = static_cast<const clap_plugin_params_t *>(
        p->get_extension(p, CLAP_EXT_PARAMS));
    const std::uint32_t n = params->count(p);
    std::printf("\n%u parameters:\n", n);
    int resolved = 0;
    for (std::uint32_t i = 0; i < n; ++i) {
        clap_param_info_t info{};
        params->get_info(p, i, &info);
        double v = 0;
        params->get_value(p, info.id, &v);
        char text[64];
        params->value_to_text(p, info.id, v, text, sizeof(text));
        const bool ok = std::strstr(text, "not connected") == nullptr;
        if (ok) ++resolved;
        std::printf("  %2u  %-20s %-16s %s\n", i, info.name, info.module, text);
    }
    std::printf("\n%d of %u resolved to live nodes\n", resolved, n);

    p->activate(p, 48000.0, 32, 512);
    p->start_processing(p);

    clap_event_param_value_t e{};
    e.header.size = sizeof(e);
    e.header.type = CLAP_EVENT_PARAM_VALUE;
    e.header.time = 0;
    e.header.space_id = CLAP_CORE_EVENT_SPACE_ID;
    e.param_id = static_cast<clap_id>(param);
    e.value = value;
    e.note_id = -1;
    e.port_index = -1;
    e.channel = -1;
    e.key = -1;
    g_events.assign(1, e);

    clap_input_events_t in{};
    in.size = ev_size;
    in.get = ev_get;
    clap_output_events_t out{};
    out.try_push = [](const clap_output_events_t *, const clap_event_header_t *) {
        return true;
    };

    clap_process_t proc{};
    proc.frames_count = 32;
    proc.in_events = &in;
    proc.out_events = &out;
    std::printf("\nsetting parameter %d to %.3f through process()\n", param, value);
    p->process(p, &proc);
    g_events.clear();

    // Now pull audio the way a host would: 32-frame blocks, in real time, and
    // report what actually arrived.
    const auto *lat = static_cast<const clap_plugin_latency_t *>(
        p->get_extension(p, CLAP_EXT_LATENCY));
    if (lat) std::printf("reported latency: %u frames\n", lat->get(p));

    // Give whoever arms the instrument time to connect to our listener.
    const int wait_s = std::getenv("MOOGONE_WAIT") ? std::atoi(std::getenv("MOOGONE_WAIT")) : 0;
    if (wait_s > 0) {
        std::printf("waiting %ds for the instrument to connect...\n", wait_s);
        std::this_thread::sleep_for(std::chrono::seconds(wait_s));
    }

    std::vector<float> l(32), r(32);
    float *chans[2] = {l.data(), r.data()};
    clap_audio_buffer_t outbuf{};
    outbuf.data32 = chans;
    outbuf.channel_count = 2;
    proc.audio_outputs = &outbuf;
    proc.audio_outputs_count = 1;

    // Audio INTO the plugin, so the effect shape can be proved end to end: a tone
    // goes out through the instrument's own effect and whatever comes back is what
    // the output port reports. MOOGONE_TONE=0 leaves the input silent, which is
    // the capture shape and a useful control -- if audio still comes back with a
    // silent input, it is not this tone that made the round trip.
    std::vector<float> il(32), ir(32);
    float *inchans[2] = {il.data(), ir.data()};
    clap_audio_buffer_t inbuf{};
    inbuf.data32 = inchans;
    inbuf.channel_count = 2;
    proc.audio_inputs = &inbuf;
    proc.audio_inputs_count = 1;
    const double tone_hz = std::getenv("MOOGONE_TONE")
                              ? std::atof(std::getenv("MOOGONE_TONE")) : 440.0;
    double phase = 0.0;

    double peak = 0.0;
    std::size_t nonsilent = 0;
    const int blocks = std::getenv("MOOGONE_BLOCKS")
                          ? std::atoi(std::getenv("MOOGONE_BLOCKS")) : 300;
    std::printf("pulling %d blocks of audio...\n", blocks);
    for (int b = 0; b < blocks; ++b) {
        for (int i = 0; i < 32; ++i) {
            const auto v = static_cast<float>(0.3 * std::sin(phase));
            il[i] = ir[i] = tone_hz > 0.0 ? v : 0.0f;
            phase += 2.0 * M_PI * tone_hz / 48000.0;
        }
        p->process(p, &proc);
        for (int i = 0; i < 32; ++i) {
            peak = std::max(peak, static_cast<double>(std::fabs(l[i])));
            if (std::fabs(l[i]) > 1e-6) ++nonsilent;
        }
        std::this_thread::sleep_for(std::chrono::microseconds(666));
    }
    std::printf("peak %.5f over %d frames, %zu non-silent\n",
                peak, blocks * 32, nonsilent);
    std::printf("%s\n", nonsilent > 0 ? "AUDIO ARRIVED FROM THE INSTRUMENT"
                                       : "no audio (was the stream armed?)");

    p->stop_processing(p);
    p->deactivate(p);
    p->destroy(p);
    entry->deinit();
    dlclose(lib);
    std::printf("done\n");
    return 0;
}
