// A minimal CLAP host, just enough to prove the plugin works against the real
// instrument: load the bundle, create the plugin, let it resolve its targets, and
// push one parameter change through process() the way a DAW would.
//
// Not a test of CLAP. A test that THIS plugin talks to THAT instrument.
#include <dlfcn.h>

#include <clap/clap.h>

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

    // The sender paces, so give it a moment to drain before tearing down.
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    p->stop_processing(p);
    p->deactivate(p);
    p->destroy(p);
    entry->deinit();
    dlclose(lib);
    std::printf("done\n");
    return 0;
}
