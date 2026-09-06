// usb-configs.c -- print EVERY USB configuration descriptor, not just the active one.
//
//   clang -o recon/usb-configs recon/usb-configs.c \
//         -framework CoreFoundation -framework IOKit
//   ./recon/usb-configs            # defaults to the Moog One
//   ./recon/usb-configs 0x2662 0xd
//
// Why this exists rather than a dozen lines of pyusb: libusb's darwin backend
// returns the ACTIVE configuration for every index. That was proven by asking for
// index 4 -- which no device has -- and getting byte-identical data back, so its
// "second configuration" was never read at all. IOUSBLib indexes the cache macOS
// built at enumeration, and reports kIOReturnNotFound past the end, which is how
// you can tell it is answering honestly.
//
// It calls no USBDeviceOpen, so a device claimed exclusively by MIDIServer stays
// claimed and its MIDI is not interrupted while this runs.
//
// Result for the Moog One (0x2662:0x000d): bNumConfigurations = 2, and both
// descriptors are byte-identical, 143 bytes, both bConfigurationValue = 1. The
// second configuration is a duplicate of the first, not a hidden audio mode.

#include <stdio.h>
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>

int main(int argc, char **argv) {
    long wantVendor = 0x2662, wantProduct = 0x000D;
    if (argc >= 3) { wantVendor = strtol(argv[1],0,0); wantProduct = strtol(argv[2],0,0); }

    CFMutableDictionaryRef match = IOServiceMatching(kIOUSBDeviceClassName);
    if (!match) { fprintf(stderr, "no matching dict\n"); return 1; }

    io_iterator_t iter;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, match, &iter) != KERN_SUCCESS) {
        fprintf(stderr, "IOServiceGetMatchingServices failed\n"); return 1;
    }

    io_service_t dev;
    int found = 0;
    while ((dev = IOIteratorNext(iter))) {
        IOCFPlugInInterface **plugin = NULL;
        SInt32 score = 0;
        if (IOCreatePlugInInterfaceForService(dev, kIOUSBDeviceUserClientTypeID,
                kIOCFPlugInInterfaceID, &plugin, &score) != KERN_SUCCESS || !plugin) {
            IOObjectRelease(dev); continue;
        }
        IOUSBDeviceInterface **usb = NULL;
        (*plugin)->QueryInterface(plugin,
            CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID), (LPVOID *)&usb);
        (*plugin)->Release(plugin);
        if (!usb) { IOObjectRelease(dev); continue; }

        UInt16 vid = 0, pid = 0;
        (*usb)->GetDeviceVendor(usb, &vid);
        (*usb)->GetDeviceProduct(usb, &pid);
        if (vid != wantVendor || pid != wantProduct) {
            (*usb)->Release(usb); IOObjectRelease(dev); continue;
        }
        found = 1;

        UInt8 nconf = 0;
        (*usb)->GetNumberOfConfigurations(usb, &nconf);
        printf("device %04x:%04x  %u configurations\n\n", vid, pid, nconf);

        // Deliberately walk PAST the last configuration. If an out-of-range
        // index errors, this API indexes the cache properly and any duplicate
        // at index 1 is the device's own doing, not the API's.
        for (UInt8 i = 0; i < nconf + 3; i++) {
            IOUSBConfigurationDescriptorPtr cfg = NULL;
            IOReturn r = (*usb)->GetConfigurationDescriptorPtr(usb, i, &cfg);
            if (r != kIOReturnSuccess || !cfg) {
                printf("config index %u: unavailable (0x%08x)%s\n", i, r,
                       i >= nconf ? "   <- past the end, as it should be" : "");
                continue;
            }
            UInt16 total = USBToHostWord(cfg->wTotalLength);
            printf("=== config index %u: bConfigurationValue=%u, %u interfaces, %u bytes ===\n",
                   i, cfg->bConfigurationValue, cfg->bNumInterfaces, total);
            const UInt8 *p = (const UInt8 *)cfg;
            for (UInt16 off = 0; off < total; ) {
                UInt8 blen = p[off], btype = p[off+1];
                if (blen == 0) break;
                if (btype == 0x04) {
                    printf("  if#%u alt%u  class=%u subclass=%u proto=%u endpoints=%u\n",
                           p[off+2], p[off+3], p[off+5], p[off+6], p[off+7], p[off+4]);
                } else if (btype == 0x05) {
                    UInt8 addr = p[off+2], attr = p[off+3];
                    UInt16 mps = p[off+4] | (p[off+5] << 8);
                    const char *k[] = {"control","iso","bulk","interrupt"};
                    printf("        ep 0x%02x %s %-9s maxpkt=%u\n",
                           addr, (addr & 0x80) ? "IN " : "OUT", k[attr & 3], mps);
                } else if (btype == 0x0B) {
                    printf("    [IAD: first if#%u, %u interfaces, class=%u subclass=%u]\n",
                           p[off+2], p[off+3], p[off+4], p[off+5]);
                }
                off += blen;
            }
            printf("RAW %u ", i);
            for (UInt16 j = 0; j < total; j++) printf("%02x", p[j]);
            printf("\n\n");
        }
        (*usb)->Release(usb);
        IOObjectRelease(dev);
    }
    IOObjectRelease(iter);
    if (!found) { fprintf(stderr, "device %04lx:%04lx not found\n", wantVendor, wantProduct); return 2; }
    return 0;
}
