# The 802.11 orphan stack

A complete Wi-Fi userspace and eleven Realtek firmware images ship on a kernel that
has no wireless subsystem of any kind.

**Scope of this report.** Everything below is read from local disk. No command was run
against the instrument. Proposed live checks are collected in §13 as read-only commands
for the owner to run.

**Evidence base.**

| short name | absolute path |
|---|---|
| `R/` | `/Volumes/Main External/Development/MoogOnePlus/captures/firmware-1.8.2/rootfs-1.8.2` (decrypted v1.8.2 rootfs) |
| `R150/` | `/Volumes/Main External/Development/MoogOnePlus/captures/rootfs-1.5.0` (v1.5.0 rootfs from the owner's instrument) |
| `H/` | `/Volumes/Main External/Development/MoogOnePlus/captures/arch-harvest` |
| `dmesg` | `/Volumes/Main External/Development/MoogOnePlus/captures/dmesg-before-reboot.txt` |
| `vmlinux` | `R/boot/uImage`, U-Boot header stripped and the gzip payload at offset 18200 inflated to 10,214,816 bytes (see §5.4 for method) |

Grading convention: **[READ]** = read directly out of a named file at a named offset or
line. **[INFERRED]** = reasoning from stated evidence. **[UNKNOWN]** = not established.

---

## 1. The finding in one paragraph

`R/` ships wpa_supplicant 2.5 with `wpa_cli`, `wpa_passphrase`, the full wireless-tools
multicall binary (`iwconfig`/`iwlist`/`iwspy`/`iwpriv`/`iwgetid`), a WPA-PSK config
template, a D-Bus system-bus policy for the supplicant, a dhcpcd hook that starts it,
and eleven Realtek 802.11 firmware images totalling 248,388 bytes **[READ]**. Against
that, the kernel contains no `cfg80211`, no `mac80211`, no `lib80211`, no wireless
extensions, no `rfkill`, and no Realtek driver — not as a builtin, not as a loadable
module, and not as a string anywhere in the decompressed kernel image **[READ]**. The
whole tree contains exactly two loadable `.ko`, both rpmsg, and the live instrument's
`lsmod` is empty **[READ]**. The correct statement is therefore not "hardware is not
fitted" but *the driver layer does not exist*: attaching a supported USB Wi-Fi dongle
would enumerate a USB device and produce no network interface, because there is no
driver to claim it and no firmware-loading path to reach the blobs **[INFERRED, §7]**.
Adding wireless to this instrument requires building a new kernel, not buying a dongle.

Two further things fall out of the same evidence, and neither is in any existing doc:

* The board's *own* Wi-Fi option is not Realtek at all. `R/boot/imx6dl-profili-som.dtb`
  carries a `/wlan` node with `compatible = "ti,wilink8"` and `status = "disabled"`, plus
  a `/wlan_bt_rfkill` node also disabled **[READ, §6]**. The eleven Realtek blobs
  correspond to no hardware this device tree describes.
* The `wlan-en-regulator` rail has been **repurposed as the eMMC's `vmmc-supply`**
  **[READ, §6.3]**. The GPIO that would enable a Wi-Fi module is now the rail that powers
  the instrument's flash. That is a hardware-level commitment away from wireless, not an
  oversight.

---

## 2. Why this question is worth closing properly

Any "can the Moog One be given network capability X" conversation eventually reaches
"can it do Wi-Fi". The existing answer in `docs/MOOG-ONE-INTERNALS.md:1812-1820` is
*"Wi-Fi is supported but not fitted … A supported Realtek USB dongle is plausibly all
that stands between this instrument and wireless networking. **Untested.**"* **[READ]**.
That reading is wrong in a way that would cost someone a dongle and an afternoon, and it
is wrong for a reason worth writing down: presence of firmware blobs and a supplicant is
evidence about the *distribution build*, not about the *kernel*. §11 records the conflict
without editing that file.

---

## 3. The userspace half — what is actually installed

### 3.1 The wpa_supplicant suite

| path | bytes | notes |
|---|---:|---|
| `R/usr/sbin/wpa_supplicant` | 1,342,956 | ELF 32-bit LSB, ARM EABI5, dynamically linked, stripped **[READ, `file`]** |
| `R/usr/sbin/wpa_cli` | 71,708 | control-interface client |
| `R/usr/sbin/wpa_passphrase` | 30,940 | PSK generator |

Version and provenance, from `strings R/usr/sbin/wpa_supplicant` **[READ]**:

```
wpa_supplicant v2.5
Copyright (c) 2003-2015, Jouni Malinen <j@w1.fi> and contributors
```

Shared-library dependencies, from `llvm-objdump -p` **[READ]**:

```
NEEDED  librt.so.1        NEEDED  libnl-3.so.200      NEEDED  libnl-genl-3.so.200
NEEDED  libdl.so.2        NEEDED  libssl.so.1.0.0     NEEDED  libcrypto.so.1.0.0
NEEDED  libc.so.6
```

All are present: `R/usr/lib/libnl-3.so.200.22.0` (94,808 B), `libnl-genl-3.so.200.22.0`
(15,400 B), `libssl.so.1.0.0` (335,676 B), `libcrypto.so.1.0.0` (1,362,524 B) **[READ]**.
So the binary will *load and run*; nothing about the failure is a missing library.

**Driver back-ends compiled in** — the binary carries all three driver description
strings **[READ]**:

```
Linux nl80211/cfg80211
Linux wireless extensions (generic)
Wired Ethernet driver
```

and the `-D` help text **[READ, strings offset ~line 8343 of the extracted string list]**:

```
  -D = driver name (can be multiple drivers: nl80211,wext)
```

with `wpa_driver_wext_*` symbol names retained (`wpa_driver_wext_associate`,
`wpa_driver_wext_set_key_ext`, `wpa_driver_wext_scan`, …) **[READ]**. This is a
full-featured build, not a stub.

**It is also an AP-capable build.** The binary contains hostapd internals —
`hostapd_setup_interface_complete`, `hostapd_add_iface`, `hostapd_new_assoc_sta`,
`hostapd_config_alloc` **[READ]** — i.e. `CONFIG_AP=y`. EAP methods present:
`PEAP`, `TTLS`, `MSCHAPV2` **[READ]**. Whoever configured this Buildroot target enabled
more of wpa_supplicant than a bare station build needs.

### 3.2 wireless-tools

`R/sbin/iwconfig` is a single 61,352-byte ELF; `iwlist`, `iwspy`, `iwpriv`, `iwgetid` are
symlinks to it **[READ, `ls -la`]** — a multicall build. Its strings include the exact
failure message every interface on this machine would produce **[READ]**:

```
%-8.16s  no wireless extensions.
```

and the version-negotiation string **[READ]**:

```
of Wireless Extension, while this program support version 11 and later.
```

It links only `libm.so.6` and `libc.so.6` **[READ, objdump]** — it talks to the kernel
purely through `SIOC*IW*` ioctls, which is precisely the interface that does not exist
here (§5).

### 3.3 Configuration files

`R/etc/wpa_supplicant.conf`, verbatim, all 11 lines **[READ]**:

```
ctrl_interface=/var/run/wpa_supplicant
ap_scan=1

network={
ssid="<put desired ssid here>"
scan_ssid=1
proto=WPA RSN
key_mgmt=WPA-PSK
pairwise=CCMP TKIP
psk=<put result of wpa_passphrase here>
}
```

An unmodified upstream/Buildroot template. No SSID, no PSK, no `network` block that would
associate with anything **[READ]**. This corroborates `network.md:563-565`.

### 3.4 The D-Bus policy — and the missing half of it

`R/etc/dbus-1/system.d/wpa_supplicant.conf` grants root `own`/`send` on both
`fi.epitest.hostap.WPASupplicant` and `fi.w1.wpa_supplicant1`, and denies both to the
default context **[READ, 27 lines]**.

The detail that matters: `R/usr/share/dbus-1/system-services/` is **empty** **[READ,
`ls -la`]**. There is no `.service` activation file, so wpa_supplicant **cannot be
D-Bus-activated**. The policy file grants a permission that nothing can exercise. Anyone
reading the policy file alone might conclude the supplicant is bus-startable; it is not.

### 3.5 The dhcpcd hook — live plumbing that never fires, for two independent reasons

`R/usr/share/dhcpcd/hooks/10-wpa_supplicant` is a 2,866-byte script that starts,
reconfigures and stops wpa_supplicant per wireless interface **[READ]**. Its trigger, at
lines 110-119 **[READ]**:

```sh
if [ "$ifwireless" = "1" ] && \
    type wpa_supplicant >/dev/null 2>&1 && \
    type wpa_cli >/dev/null 2>&1
then
	case "$reason" in
	PREINIT)	wpa_supplicant_start;;
	RECONFIGURE)	wpa_supplicant_reconfigure;;
	DEPARTED)	wpa_supplicant_stop;;
	esac
fi
```

and it would launch (lines 63-64) **[READ]**:

```sh
	err=$(wpa_supplicant -B -c"$wpa_supplicant_conf" -i"$interface" \
	    "$driver" 2>&1)
```

This is *not* dead code in the sense that dhcpcd is unused. `R/etc/init.d/S95dhcpd:9`
starts it at boot **[READ]**:

```sh
     /sbin/dhcpcd start ethext &
```

`R/sbin/dhcpcd` is dhcpcd 6.10.1 (`dhcpcd-6.10.1 starting` **[READ, strings]**) and does
compute the hook variable — `ifwireless=%d` and `ifwireless` both appear in its strings
**[READ]**.

Two independent breaks, each sufficient:

1. **The hook is not installed.** `R/sbin/dhcpcd` hardcodes `/lib/dhcpcd/dhcpcd-run-hooks`
   **[READ, strings]**, and that script iterates only `/lib/dhcpcd/dhcpcd-hooks/*`
   (`R/lib/dhcpcd/dhcpcd-run-hooks:366-368`) **[READ]**:

   ```sh
   for hook in \
   	/etc/dhcpcd.enter-hook \
   	/lib/dhcpcd/dhcpcd-hooks/* \
   	/etc/dhcpcd.exit-hook
   ```

   `R/lib/dhcpcd/dhcpcd-hooks/` contains exactly `01-test`, `02-dump`, `20-resolv.conf`,
   `30-hostname` **[READ, `ls`]**. `10-wpa_supplicant` sits in the *available* directory
   `R/usr/share/dhcpcd/hooks/`, unlinked. dhcpcd never sources it.

2. **`ifwireless` can never be 1.** dhcpcd determines it by a wireless-extensions ioctl,
   which returns `-EOPNOTSUPP` on a kernel with no wext **[INFERRED, from §5]**.

For completeness, the *other* DHCP path is also non-wireless: `R/etc/init.d/S40network`
runs `/sbin/ifup -a` **[READ]**, `R/sbin/ifup` is a busybox symlink **[READ]**, and
busybox ifupdown uses `udhcpc`, not dhcpcd — its embedded command template is **[READ,
strings `R/sbin/ifup`]**:

```
udhcpc -R -n -p /var/run/udhcpc.%iface%.pid -i %iface%[[ -H %hostname%]]...
```

udhcpc has no wpa_supplicant hook at all.

### 3.6 Nothing else in the image references any of it

`grep -rn -aiE 'wpa_supplicant|wpa_cli|iwconfig|iwlist|ifwireless|wlan[0-9]' R/etc/`
returns exactly one hit outside the two config files themselves: the `ctrl_interface=`
line of `wpa_supplicant.conf` **[READ]**. `R/etc/inittab` (35 lines) and the 18 scripts
in `R/etc/init.d/` contain no reference **[READ]**. `grep -rl -a 'rtlwifi'` and
`grep -rl -a 'rtl8192'` across `R/bin`, `R/sbin`, `R/usr/bin`, `R/usr/sbin`, `R/usr/lib`,
`R/lib`, `R/etc` return **nothing** — no binary on the system names the firmware
directory **[READ]**.

---

## 4. The eleven firmware blobs

`R/lib/firmware/rtlwifi/`, all mtime `Dec 6 2015`, 248,388 bytes total **[READ, `ls -la`]**.
The header of each was parsed as `struct rtlwifi_firmware_header`
(`__le16 signature; u8 category; u8 function; __le16 version; u8 subversion; u8 rsvd1; …`)
**[READ, python struct unpack of the first 20 bytes]**:

| file | bytes | hdr signature | md5 (first 10) | driver that requests it |
|---|---:|---|---|---|
| `rtl8188efw.bin` | 11,216 | `0x88E1` | `3aed09e638` | `rtl8188ee` (PCIe) |
| `rtl8188eufw.bin` | 13,904 | `0x88E1` | `aaef52a478` | `rtl8188eu` / `rtl8xxxu` (USB) |
| `rtl8192cfw.bin` | 16,192 | `0x88C1` | `fd118c183a` | `rtl8192ce` (PCIe) |
| `rtl8192cfwU.bin` | 14,818 | `0x88C1` | `660d5d7e1e` | `rtl8192ce` (PCIe) |
| `rtl8192cfwU_B.bin` | 16,332 | `0x88C2` | `22d58a35a1` | `rtl8192ce` (PCIe) |
| `rtl8192cufw.bin` | 16,014 | `0x88C1` | `943e9b714a` | `rtl8192cu` (USB) |
| `rtl8192cufw_A.bin` | 16,116 | `0x88C1` | `7e15572f80` | `rtl8192cu` (USB) |
| `rtl8192cufw_B.bin` | 16,096 | `0x88C2` | `d0cdaf2531` | `rtl8192cu` (USB) |
| `rtl8192cufw_TMSC.bin` | 16,116 | `0x88C1` | `b64bd0e053` | `rtl8192cu` (USB) |
| `rtl8192defw.bin` | 31,376 | `0x92D3` | `01c66e417f` | `rtl8192de` (PCIe) |
| `rtl8192sefw.bin` | 80,208 | `0x8192` | `2faf6915a0` | `rtl8192se` (PCIe) |

The signature column is the load-bearing part: `0x88Ex`, `0x88Cx`, `0x92Dx` are the values
the `rtlwifi` core checks, so these are genuine, unmodified upstream images **[READ for the
bytes; INFERRED for "genuine upstream", from signature validity plus the uniform 2015-12-06
mtime]**. `rtl8192sefw.bin` uses the older RTL8192S header layout, so its version/date
fields do not decode under the same struct; only its first two bytes are cited **[READ]**.

The driver column is **[INFERRED]**, from the stable rtlwifi naming convention
(`…ce`/`…de`/`…se`/`…ee` = PCI/PCIe parts, `…cu`/`…eu` = USB parts). On that reading,
**seven of the eleven are for PCIe-only chips**; only five files target USB parts, and
those five cover just two chips — `rtl8188eufw.bin` (RTL8188EU) and the four
`rtl8192cufw{,_A,_B,_TMSC}.bin` variants (RTL8192CU). That matters because §6.4 shows the PCIe controller on this board fails to link.

**Provenance.** This exact set is the Buildroot `linux-firmware` "rtl-81xx" grouping
**[INFERRED]** — it is not a hand-picked Moog selection, and its presence carries no
information about Moog's intent. Supporting evidence: nothing in the rootfs references it
(§3.6); the mtimes are all one upstream release date, not a build date; the rest of
`R/lib/firmware/` is likewise generic BSP content — `imx/epdc/` holds five e-paper display
firmwares (plus a stray makefile fragment) for a panel this instrument does not have **[READ, `find R/lib/firmware -type f`]**.

Full firmware inventory — 30 files total **[READ, `find R/lib/firmware -type f`]**:
`vpu/` 6, `sdma/` 7, `rtlwifi/` 11, `imx/epdc/` 6 (the sixth being `fsl-epdc.mk`, a makefile
fragment rather than a firmware image). **There is no TI WiLink firmware** — no `wl18xx-fw-*.bin`, no
`wl127x-*`, nothing — even though the device tree names a WiLink8 (§6.1).

---

## 5. The kernel half — the negative, established four ways

The instrument runs `Linux version 4.1.15-rt18 … #1 SMP PREEMPT RT Mon May 16 10:55:36
EDT 2022`, gcc 4.8.5, Buildroot 2016.02-rc2-dirty, on a
`Variscite i.MX6 DL/Solo SOM-SOLO SOM-DUAL SoloCustomBoard` **[READ, `dmesg:5,8`]**.

### 5.1 `modules.builtin` — 344 entries, zero wireless

`R/lib/modules/4.1.15-rt18/modules.builtin` is 344 lines / 11,762 bytes **[READ]**.

```
grep -iE '80211|wireless|rtl|rfkill|lib80211|wext|wifi|wlan|ieee802'  →  no match (exit 1)
```

**[READ]**. `modules.builtin` enumerates every tristate Kconfig symbol set to `=y`, so a
built-in `cfg80211`/`mac80211`/`rtlwifi` would appear here. It does not.

The complete networking content of that file, lines 188-196 and 301-330 **[READ]**:

```
kernel/drivers/net/mii.ko                       kernel/net/dns_resolver/dns_resolver.ko
kernel/drivers/net/ethernet/freescale/fec.ko    kernel/net/ipv4/{inet,tcp,udp}_diag.ko
kernel/drivers/net/phy/libphy.ko                kernel/net/ipv4/tcp_cubic.ko
kernel/drivers/net/phy/micrel.ko                kernel/net/ipv4/netfilter/… (9 entries)
kernel/drivers/net/usb/asix.ko                  kernel/net/ipv6/{ipv6,mip6,inet6_hashtables}.ko
kernel/drivers/net/usb/cdc_ether.ko             kernel/net/ipv6/netfilter/ip6_tables.ko
kernel/drivers/net/usb/cdc_eem.ko               kernel/net/netfilter/… (8 entries)
kernel/drivers/net/usb/usbnet.ko                kernel/net/packet/af_packet.ko
kernel/drivers/net/usb/cdc_ncm.ko               kernel/net/sunrpc/…, kernel/net/unix/unix.ko
```

Nine wired-networking drivers — four of them USB-Ethernet — and not one wireless object.

### 5.2 The loadable-module census — two `.ko`, both rpmsg

`find R/ -name '*.ko'` returns **exactly two files** **[READ]**:

```
R/lib/modules/4.1.15-rt18/kernel/drivers/rpmsg/imx_rpmsg_tty.ko
R/lib/modules/4.1.15-rt18/kernel/drivers/rpmsg/imx_rpmsg_pingpong.ko
```

There are no compressed variants (`find` for `*.ko.*` returns the same two) **[READ]**.
The supporting metadata is correspondingly empty **[READ, full file contents]**:

```
modules.alias    : 1 line   — "# Aliases extracted from modules themselves."
modules.symbols  : 1 line   — "# Aliases for symbols, used by symbol_request()."
modules.softdep  : 1 line   — comment only
modules.devname  : 1 line   — comment only
modules.dep      : 2 lines  — the two rpmsg modules, no dependencies
modules.order    : 2 lines  — the two rpmsg modules
```

Zero `rtl8*` aliases, zero `80211` aliases **[READ]**. Even if a driver existed, udev/mdev
has no alias table to match a USB vendor/product ID against.

### 5.3 The live instrument agrees

`H/runtime-state.txt`, `--- modules ---` section **[READ]**:

```
Module                  Size  Used by    Tainted: G
```

Header only — **no modules loaded**. `H/CAVEAT-runtime-state.md` explicitly lists `lsmod`,
network interfaces and the USB device tree among the things this capture remains valid
for **[READ]**, so this is citable despite the contamination affecting scsynth's block
size.

Interfaces on the running machine **[READ, `H/runtime-state.txt`, `--- interfaces ---` section]**:

```
1: lo      127.0.0.1/8
2: usbint  203.0.113.1/24
3: ethext  192.168.1.136/24  (+ .138 secondary)
```

No `wlan*`, no `wlp*`. And `dmesg:302-305` shows both of those are `cdc_ether` over the
XMOS link **[READ]**:

```
[   12.057691] cdc_ether 2-1:1.0 usb0: register 'cdc_ether' at usb-ci_hdrc.1-1, …
[   12.106790] cdc_ether 2-1:1.0 usbint: renamed from usb0
[   12.169539] cdc_ether 2-1:1.2 ethext: renamed from eth0
```

The dmesg contains no line matching `80211|wireless|rtl|wlan|rfkill`; the only `firmware`
line in the whole boot log is `imx-sdma 20ec000.sdma: loaded firmware 3.3` (`dmesg:143`)
**[READ]**. The `rtlwifi/` directory is never touched at boot.

### 5.4 The kernel image itself

**Method.** `R/boot/uImage` is 5,060,456 bytes with a valid U-Boot header
(`27 05 19 56`, name field `Linux-4.1.15-rt18`) **[READ, `xxd -l 96`]**. Stripping the
64-byte header gives a `Linux kernel ARM boot executable zImage (little-endian)`
**[READ, `file`]** containing a single gzip stream at offset 18200, which inflates to
10,214,816 bytes **[READ]**. `strings -n 5` over that yields 43,021 lines.

**Method limitation, stated up front:** ARM `kallsyms` symbol names are token-compressed,
so a symbol's mere existence is *not* guaranteed to appear as a plain string. What does
appear reliably is `printk` format strings, `module_param` prefixes, sysctl names, and
`.rodata` literals. Every wireless subsystem in Linux 4.1 emits many of those
(`cfg80211: Calling CRDA…`, `Regulatory domain…`, and so on). Positive controls confirm
the method resolves subsystems of comparable size **[READ]**:

```
usbnet 46 hits   nf_conntrack 83 hits   ip_tables 5 hits
asix 3 hits      cdc_ether 1 hit        firmware_class 2 hits
```

**Result** — counts over the 43,021-line string list **[READ]**:

| pattern | hits |
|---|---:|
| `cfg80211` | 0 |
| `mac80211` | 0 |
| `lib80211` | 0 |
| `ieee80211` | 0 |
| `80211` (bare) | 0 |
| `nl80211` | 0 |
| `rtlwifi`, `rtl8192`, `rtl8188` | 0 |
| `rfkill` | 0 |
| `SIOC[SG]IW…` (any wext ioctl name) | 0 |
| `wireless_send_event`, `iw_handler` | 0 |
| `regulatory`, `CRDA`, `802.11` | 0 |
| `wilink`, `wl18xx`, `wl12xx`, `wlcore` | 0 |
| `iwlwifi`, `brcmfmac`, `ath9k`, `ath10k`, `mt76`, `rt2800`, `zd1211` | 0 |

**Four near-misses, each run down and excluded** — these are the strings that would
mislead a casual grep, so they are recorded explicitly:

1. `wlan%d` (one hit). Its neighbours in the string table are
   `&dev->phy_mutex`, `usb%d`, `eth%d`, `wlan%d`, `wwan%d`,
   `register '%s' at usb-%s-%s, %s, %pM` **[READ, extracted-strings lines 27604-27612]**.
   That is `drivers/net/usb/usbnet.c`'s `FLAG_WLAN` device-naming literal, not
   `net/wireless/core.c`. Present because `usbnet` is builtin.
2. `wifi-host`, `assigned as wifi host`, `no board data!`, immediately preceding
   `drivers/mmc/host/sdhci-esdhc-imx.c` **[READ, lines 29961-29966]**, plus
   `wifi_card_detect` amid `sdhci_pltfm_*` symbols **[READ, line 40371]**. NXP's SDHCI
   driver has optional SDIO-Wi-Fi-slot plumbing. It is inert here: **no node in
   `R/boot/imx6dl-profili-som.dtb` carries a `wifi-host` property** — `strings` on the
   DTB returns zero matches for `wifi` **[READ]**.
3. `__sock_recv_wifi_status`, `skb_complete_wifi_ack` **[READ, lines 41131, 41227]** —
   `net/socket.c` / `net/core/skbuff.c`, always compiled, `SO_WIFI_STATUS` socket option.
   No 802.11 code implied.
4. `michael_mic` and `arc4` (one hit each) **[READ, line 42896 and the crypto block]**,
   and `kernel/crypto/{michael_mic,arc4}.ko` in `modules.builtin` **[READ]**. These are
   the TKIP cipher primitives, normally pulled in by `lib80211`/`mac80211`. Their presence
   with no 802.11 code is consistent with a broad "enable the generic crypto algorithms"
   kernel config **[INFERRED]**; they are also selected by unrelated users (CIFS, PPP MPPE)
   in mainline. They are **not** evidence of a wireless stack.

There is no embedded `IKCFG_ST` blob in this kernel (`grep -ac 'IKCFG_ST'` → 0)
**[READ]**, so `/proc/config.gz` will not exist on the instrument and the Kconfig cannot
be recovered directly. `modules.builtin` is the best available proxy.

### 5.5 v1.5.0 is identical

Everything above holds equally for the owner's own instrument's firmware:

* `R150/lib/modules/4.1.15-rt18/modules.builtin` is **byte-identical** to the 1.8.2 file
  (`diff` reports no differences; 344 lines each) **[READ]**.
* `R150/` contains the same two `.ko` and no others **[READ]**.
* `R150/boot/uImage` differs from 1.8.2's (`6847177b…` vs `0187e5b8…`) **[READ, md5]**,
  but its decompressed image also returns **zero** hits for `cfg80211`, `mac80211`,
  `ieee80211`, `rtlwifi`, `rfkill`, `nl80211`, `SIOCGIWNAME`, `802.11`, `regulatory`,
  with the same positive controls (`usbnet` 46, `nf_conntrack` 83) **[READ]**.

---

## 6. The device tree — the board's real Wi-Fi story

Parsed from `R/boot/imx6dl-profili-som.dtb` (42,345 bytes, valid `d00dfeed` magic) with a
direct FDT walk **[READ, python `struct` unpack of the structure block]**.

### 6.1 A TI WiLink8, disabled

```
/wlan
    compatible       = "ti,wilink8"
    interrupt-parent = <0x36>            → /soc/aips-bus@02000000/gpio@020b0000  (GPIO6)
    interrupts       = <0x11 …>          → GPIO6_IO17
    clocks           = <0x3a>            → /wlan/refclock
    clock-names      = "refclock"
    status           = "disabled"
/wlan/refclock
    compatible       = "ti,wilink-clock"
    #clock-cells     = <0>
    clock-frequency  = 0x0249f000        = 38,400,000 Hz
```

**[READ]**, phandles resolved from the DTB's own `phandle` properties **[READ]**.

### 6.2 An rfkill node, also disabled

```
/wlan_bt_rfkill
    compatible = "net,rfkill-gpio"
    type       = <0x2>
    gpios      = <0x36 0x12 …>           → GPIO6_IO18
    status     = "disabled"
```

**[READ]**. `net,rfkill-gpio` needs `CONFIG_RFKILL_GPIO`; `rfkill` appears nowhere in
`modules.builtin` and has zero hits in the kernel strings (§5.1, §5.4). Even were this node
enabled, nothing would bind to it **[INFERRED]**.

**Consequence worth stating plainly:** the eleven Realtek blobs and the device tree
describe *different vendors on different buses*. The SOM's designed-in Wi-Fi option is a
TI WiLink8 on SDIO; the firmware shipped is Realtek on USB/PCIe; and there is no TI
firmware on disk at all (§4). Neither path is complete.

### 6.3 The `wlan-en` rail now powers the eMMC

```
/fixedregulator@2
    compatible              = "regulator-fixed"
    regulator-name          = "wlan-en-regulator"
    regulator-min-microvolt = 0x1b7740   = 1,800,000 µV   (1.8 V)
    regulator-max-microvolt = 0x1b7740   = 1,800,000 µV
    gpio                    = <0x37 0x08 0x00>  → GPIO7_IO08, active-high
    startup-delay-us        = 0x11170    = 70,000 µs      (70 ms)
    enable-active-high
    phandle                 = 0x2b
```

**[READ]**. And:

```
/soc/aips-bus@02100000/usdhc@02198000
    status        = "okay"
    non-removable
    vmmc-supply   = <0x2b>      → /fixedregulator@2, i.e. wlan-en-regulator
    cap-power-off-card
```

**[READ]**. `usdhc@02198000` is usdhc3, the eMMC controller — corroborated by
`dmesg` showing `mmc2: new DDR MMC card`, `mmcblk2: mmc2:0001 NCard 7.21 GiB`,
`mmcblk2: p1 p2 p3 p4 p5 p6 p7` and `/dev/mmcblk2p6 on /var` in the live mount table
**[READ]**.

This confirms and extends `kernel.md:749`, which flagged the same reuse as "a Variscite
SOM artefact". It is more than an artefact: the rail that would enable a Wi-Fi module is
the rail that keeps root and `/var` alive. Re-enabling `/wlan` would put the WiLink8's
enable line and the eMMC's power rail on one GPIO **[INFERRED, from the two `[READ]`
properties above]**. That is a real hardware constraint on any wireless retrofit, not a
software one.

### 6.4 SDIO slot disabled; PCIe link dead; USB host live

`status` for every relevant node **[READ, full DTB walk]**:

| node | status | what it is |
|---|---|---|
| `/soc/aips-bus@02100000/usdhc@02190000` | **disabled** | usdhc1 — `non-removable`, `enable-sdio-wakeup`; the SDIO slot a WiLink8 would use |
| `/soc/aips-bus@02100000/usdhc@02194000` | okay | usdhc2 — SD card, `cd-gpios`, `cd-inverted`, `no-1-8-v` |
| `/soc/aips-bus@02100000/usdhc@02198000` | okay | usdhc3 — eMMC (§6.3) |
| `/soc/aips-bus@02100000/usdhc@0219c000` | disabled | usdhc4 |
| `/soc/aips-bus@02100000/usb@02184000` | okay | OTG |
| `/soc/aips-bus@02100000/usb@02184200` | okay | host 1 |
| `/soc/aips-bus@02100000/usb@02184400` | disabled | |
| `/soc/aips-bus@02100000/usb@02184600` | disabled | |
| `/soc/aips-bus@02100000/ethernet@02188000` | **disabled** | the i.MX6 FEC — the on-SoC Ethernet MAC is not used at all |
| `/soc/pcie@0x01000000` | okay | `fsl,imx6q-pcie`, `snps,dw-pcie` |
| `/wlan` | disabled | §6.1 |
| `/wlan_bt_rfkill` | disabled | §6.2 |

The PCIe node is enabled in the DT but **fails at runtime** — `dmesg:263-265` **[READ]**:

```
[    1.303652] imx6q-pcie 1ffc000.pcie: phy link never came up
[    1.303678] imx6q-pcie 1ffc000.pcie: failed to initialize host
[    1.303814] imx6q-pcie: probe of 1ffc000.pcie failed with error -22
```

So the seven PCIe-only Realtek images in §4 have no bus to reach even in principle
**[INFERRED, from the probe failure]**.

USB, by contrast, is live and physically accessible: `/dev/sda1` is mounted at
`/var/local/media/sda1` in the live capture **[READ, `H/runtime-state.txt` mounts]**, i.e.
a USB mass-storage device enumerates and mounts. A USB Wi-Fi dongle can therefore be
*plugged in*; §7 is about what happens next.

---

## 7. Why nothing can attach — the chain, break by break

Consider the best case: a Realtek RTL8192CU dongle, one of the four USB parts whose
firmware is on disk, inserted into the front USB port.

| # | stage | outcome | grade |
|---|---|---|---|
| 1 | Physical + electrical | Works. USB host controllers are `okay` (§6.4); mass storage enumerates today. | **[READ]** |
| 2 | `usbcore` enumeration | Works. `usbcore.ko`, `ehci-hcd.ko`, `ci_hdrc*.ko` are builtin (`modules.builtin:229-245`). A `usb N-M: new high-speed USB device` line would appear in dmesg. | **[READ]** |
| 3 | Driver match | **BREAK.** No `rtl8192cu` driver exists — not builtin (§5.1), not as a `.ko` (§5.2), not as a string in the kernel (§5.4). `modules.alias` is empty, so no autoload can be triggered (§5.2). No `usb_driver` claims the interface. | **[READ] for each absence; [INFERRED] for "no driver claims it"** |
| 4 | Firmware request | Never reached. `firmware_class` *is* builtin and its search paths *are* correct — `/lib/firmware/updates/4.1.15-rt18`, `/lib/firmware/updates`, `/lib/firmware/4.1.15-rt18`, `/lib/firmware` **[READ, kernel strings lines 24146-24149]** — so the blobs are reachable in principle. But `request_firmware()` is called *by a driver*, and there is no driver. The blobs are unreferenced by construction. | **[READ] + [INFERRED]** |
| 5 | `cfg80211` registration | **BREAK.** No `wiphy` can be registered; `cfg80211` does not exist. No `wlan0` netdev appears. | **[READ]** |
| 6 | `nl80211` generic-netlink family | **BREAK.** Registered by `cfg80211`. wpa_supplicant's own error string for this case is present in the binary: `nl80211: 'nl80211' generic netlink not found` **[READ]**. `-Dnl80211` will fail at init. | **[READ]** |
| 7 | Wireless extensions | **BREAK.** Zero `SIOC*IW*` handlers (§5.4). `iwconfig` prints `no wireless extensions.` for every interface; `-Dwext` fails; dhcpcd's `ifwireless` stays 0. | **[READ]** |
| 8 | Autostart | **BREAK** (independently). No init script references wpa_supplicant (§3.6); the dhcpcd hook is not installed in the run directory (§3.5); there is no D-Bus activation file (§3.4). | **[READ]** |

Four independent, individually sufficient breaks. **The answer to "can this instrument be
given wireless without a new kernel?" is no** — and it is no on kernel-side evidence, not
on the weaker "no Wi-Fi hardware is enumerated in dmesg" inference that `network.md:566`
currently rests on **[INFERRED, from the eight rows above]**.

### 7.1 The one thing that *would* work

`wpa_supplicant`'s `wired` back-end is compiled in (§3.1) and needs no 802.11 anything —
it does IEEE 802.1X EAPOL over a plain Ethernet interface, using `af_packet` (builtin,
`modules.builtin:327`) **[READ]**. So `wpa_supplicant -Dwired -i ethext -c …` is the one
invocation on this box that could actually run, if a studio network demanded 802.1X port
authentication. Whether it ever has is **[UNKNOWN]**; nothing on disk configures it, and
`R/etc/wpa_supplicant.conf` has no `key_mgmt=IEEE8021X` block **[READ]**.

Note also that with no `-D` flag wpa_supplicant selects a driver from its internal list
rather than probing all of them; the help text `-D = driver name (can be multiple
drivers: nl80211,wext)` **[READ]** implies the caller is expected to name them. The
precise default-selection behaviour of this build was not verified from the binary —
**[UNKNOWN]**, and it does not affect the conclusion, since the dhcpcd hook that would
invoke it never runs (§3.5).

---

## 8. What adding wireless would actually cost

Not a dongle. **[INFERRED throughout this section, from §5 and §6.]**

1. **A kernel rebuild.** `CONFIG_CFG80211`, `CONFIG_MAC80211`, `CONFIG_RTL8192CU` (or
   `CONFIG_RTL8XXXU`), plus `CONFIG_RFKILL` and the `lib80211` crypto selects. There is
   no `/proc/config.gz` (§5.4), so the config must be reconstructed from
   `modules.builtin` or obtained from Moog/Variscite. The toolchain is gcc 4.8.5 under
   Buildroot 2016.02-rc2 **[READ, `dmesg:5`]** — reproducing it is a project in itself.
2. **A rebuilt/replaced `uImage` in the boot partition,** which puts the instrument's
   only boot image at risk. See `docs/DANGER.md` before contemplating this.
3. **The `-rt18` PREEMPT_RT constraint.** The audio core is `isolcpus=1` running scsynth
   at SCHED_FIFO 99 **[established architecture; `R/boot/cmdline.txt` reads
   `setenv add_args isolcpus=1 quiet loglevel=0 galcore.contiguousSize=67108864 gpumem=128M
   dmfc=3 nohz=off skew_tick=1` **[READ]**]**. `mac80211` softirq work and USB URB
   completion on cpu0 would land alongside the control plane. Any wireless retrofit is an
   audio-glitch risk that would have to be measured, not assumed.
4. **512 MB of RAM.** `cfg80211` + `mac80211` + a driver is a few hundred KB of text plus
   per-station state; not decisive, but not free.
5. **If the SDIO/WiLink8 path is chosen instead:** re-enable `/wlan`, `/wlan_bt_rfkill`
   and `usdhc@02190000` in the DT, add `CONFIG_WL18XX`/`CONFIG_WLCORE_SDIO`, obtain
   `wl18xx-fw-4.bin` (absent from `R/lib/firmware`, §4) — **and resolve the GPIO7_IO08
   conflict in §6.3, where the wlan-enable rail is the eMMC's power supply.** That last
   item is the hard one.

---

## 9. Frozen since at least 2022

Every file in the wireless stack is byte-identical between v1.5.0 (May 2022) and
v1.8.2 (Sep 2025) **[READ, md5]**:

| file | md5 (first 12) | 1.5.0 = 1.8.2 |
|---|---|---|
| `usr/sbin/wpa_supplicant` | `13a5f9d41222` | same |
| `usr/sbin/wpa_cli` | `43df69ac7f63` | same |
| `usr/sbin/wpa_passphrase` | `9f3ad3e09eca` | same |
| `sbin/iwconfig` | `929a78cd1673` | same |
| `etc/wpa_supplicant.conf` | `6e53e61bcc86` | same |
| `etc/dbus-1/system.d/wpa_supplicant.conf` | `5422c3e52a2f` | same |
| `usr/share/dhcpcd/hooks/10-wpa_supplicant` | `3f86c5aa687d` | same |
| all 11 `lib/firmware/rtlwifi/*.bin` | — | `diff -rq` reports **identical** |
| `lib/modules/4.1.15-rt18/modules.builtin` | — | `diff` reports **identical** |

Three years and at least three firmware releases with no change on either side of the
gap. This is inert distribution ballast, carried forward untouched **[INFERRED, from the
identity above plus §3.6's finding that nothing references it]**.

---

## 10. Adjacent orphans and adjacent live code

Paired here because the same "userspace tool, no kernel support" pattern recurs, and
because the netfilter side is the counter-example where the support *is* present.

### 10.1 `vconfig` / 802.1Q — the same orphan pattern, smaller

`R/sbin/vconfig` is a symlink to `../bin/busybox` **[READ]**, and `vconfig` *is* in this
busybox's applet table (`BusyBox v1.24.1 (2025-09-15 14:21:08 EDT)`) **[READ, applet
string list]**. But `8021q` appears **nowhere** in `modules.builtin` **[READ, grep for
`8021q|vlan` → no match]**, and there is no `8021q.ko` (§5.2).

The kernel image does contain the string `8021q` **[READ, line 33032]** — and this is a
second near-miss worth recording, because it looks like VLAN support and is not. Its
neighbours are `net-pf-%d`, `NET: Unregistered protocol family %d`, `bridge`, `8021q`,
`sockets: used %d`, `sockfs`, `net/core/sock.c` **[READ, lines 33023-33036]**. Those are
the `request_module()` names in `net/socket.c`'s `sock_ioctl`, which the kernel tries when
`SIOCGIFVLAN`/`SIOCSIFVLAN` arrives and no handler is registered; the error path returns
`-ENOPKG`. The adjacent symbols `vlan_ioctl_set`, `brioctl_set`, `dlci_ioctl_set`
**[READ, lines 41126-41128]** are the always-compiled hook pointers. `busybox vconfig` on
this instrument would fail **[INFERRED]**. Other `vlan`/`bridge` strings in the image
(`tx-vlan-hw-insert`, `rx-vlan-filter`, `Buggy VLAN acceleration in driver!`,
`PF_BRIDGE: RTM_NEWNEIGH with invalid vlan`) are `net/core/dev.c` and
`net/core/rtnetlink.c` literals, likewise always compiled **[READ, lines 3025-3056,
33155, 33201-33204]**.

### 10.2 `usr/lib/xtables` — 112 extensions, 18 kernel-side objects

`R/usr/lib/xtables/` holds **112** `.so` files **[READ, `ls | wc -l`]** — the full
iptables 1.x extension set: `libxt_conntrack.so`, `libxt_string.so`, `libxt_recent.so`,
`libxt_hashlimit.so`, `libxt_TPROXY.so`, `libxt_bpf.so`, `libipt_CLUSTERIP.so`,
`libebt_*.so`, and so on. Supporting libraries: `libxtables.so.11.0.0` (39,224 B),
`libip4tc.so.0.1.0`, `libip6tc.so.0.1.0`, `libiptc.so.0.0.0` **[READ]**. Binaries:
`R/usr/sbin/{iptables,iptables-save,iptables-restore,ip6tables,ip6tables-save,ip6tables-restore}`
and `R/usr/bin/iptables-xml` **[READ]**.

The kernel side is exactly **18** netfilter objects **[READ, `modules.builtin:306-314,
318-326`]**:

```
ipv4/netfilter:  nf_conntrack_ipv4  nf_nat_ipv4  nf_defrag_ipv4  nf_nat_masquerade_ipv4
                 ip_tables  iptable_filter  iptable_mangle  iptable_nat  ipt_MASQUERADE
ipv6/netfilter:  ip6_tables
netfilter:       nfnetlink  nf_conntrack  nf_conntrack_netlink  nfnetlink_cttimeout
                 nf_nat  x_tables  xt_tcpudp  xt_nat
```

The match/target set is *minimal*: `xt_tcpudp` (the `-p tcp/udp --dport` match) and
`xt_nat` (the `SNAT`/`DNAT` targets), plus `ipt_MASQUERADE`. Notably **`xt_conntrack` and
`xt_state` are absent** — `iptables -m conntrack` or `-m state` would fail to load its
kernel counterpart even though `libxt_conntrack.so` is on disk and `nf_conntrack` itself
is builtin **[READ for the absence; INFERRED for the runtime failure]**.

That minimal set is exactly, and only, what `R/etc/init.d/S95dhcpd:11-14` uses **[READ]**:

```sh
iptables -t nat -A PREROUTING -i ethext -p udp --dport 7770 -j DNAT --to 203.0.113.2:7770
iptables -t nat -A PREROUTING -i ethext -p udp --dport 7771 -j DNAT --to 203.0.113.2:7771
iptables -t nat -A PREROUTING -i ethext -p udp --dport 9100 -j DNAT --to 203.0.113.2:9100
iptables -t nat -A PREROUTING -i ethext -p udp --dport 9300 -j DNAT --to 203.0.113.2:9300
```

`iptable_nat` + `xt_tcpudp` + `xt_nat`. The kernel was configured for these four rules and
essentially nothing else **[INFERRED]**. So the netfilter capability `network.md`'s DNAT
section depends on is genuinely present — this is the case where userspace and kernel
*do* line up — but the 112 `.so` files are 90-odd% as orphaned as the Wi-Fi stack, and
anyone planning to extend the firewall should check `modules.builtin` before writing a
rule **[INFERRED]**.

### 10.3 Also present, also unreferenced

`R/sbin/dhcpcd` (200,960 B, dhcpcd 6.10.1) is genuinely used (§3.5), but its optional
hooks in `R/usr/share/dhcpcd/hooks/` — `10-wpa_supplicant`, `15-timezone`,
`29-lookup-hostname` — are all uninstalled; only `01-test`, `02-dump`, `20-resolv.conf`,
`30-hostname` are in the active directory **[READ]**. `R/usr/sbin/dhcpd` (547,740 B, ISC
DHCP server) and the `S80dhcp-server` / `S80dhcp-relay` init scripts exist with empty
`INTERFACES=""` defaults **[READ]** — a separate dormancy question, out of scope here.

---

## 11. Conflicts with existing docs

Reported, not fixed, per the brief. Four items.

### C1 — `docs/MOOG-ONE-INTERNALS.md:1812-1820` is wrong and should be retracted

Current text **[READ]**:

> ### Wi-Fi is supported but not fitted
> ```
> wpa_supplicant   wpa_cli   wpa_passphrase
> /lib/firmware/rtlwifi/   rtl8188/8192 firmware blobs present
> ```
> The driver firmware and supplicant are both installed. A supported Realtek USB dongle is
> plausibly all that stands between this instrument and wireless networking. **Untested.**

Three defects. (a) "**Wi-Fi is supported**" is false: there is no wireless subsystem in the
kernel at all (§5). (b) "**The driver firmware … installed**" conflates *firmware* with
*driver*; the firmware is present, the driver is absent, and firmware without a driver is
unreachable (§7 row 4). (c) "**a supported Realtek USB dongle is plausibly all that
stands between**" is the specific inference this report closes: what stands between is a
kernel rebuild (§8). The heading's second half — "not fitted" — is true but incidental.

Suggested replacement, for whoever owns that file: *"Wi-Fi userspace ships; the kernel has
no wireless support. See `gap-wireless-802-11-orphan-stack.md`."*

### C2 — `docs/firmware/network.md:563-566` is correct but under-powered

Current text **[READ]**:

> - **wpa_supplicant** — binary + `R/etc/wpa_supplicant.conf` present, but the config is
>   a **placeholder template** … **[READ]** and no init script starts it;
>   no Wi-Fi hardware is enumerated in `dmesg` **[INFERRED]**. Dormant.

Everything asserted is confirmed here (§3.3, §3.6, §5.3). The issue is the *grade of the
conclusion*: resting on "no Wi-Fi hardware is enumerated in `dmesg`" leaves open — and
readers have taken — the reading that attaching hardware would work. §5.1/§5.2/§5.4
replace that inference with a direct **[READ]** negative on the kernel side. Also, the
clause "no init script starts it" is true but incomplete: there *is* a live dhcpcd
(`S95dhcpd:9`) and a wpa hook shipped for it; the hook is simply not installed in the
directory dhcpcd reads (§3.5). Worth adding, because "no init script" invites the reply
"so I'll add one".

### C3 — `docs/firmware/kernel.md:749` is right and can be strengthened

Current text **[READ]**: *"the eMMC's `vmmc-supply` points at the `wlan-en-regulator`
fixed regulator (1.8 V, 70 ms startup delay, GPIO7_IO08) — a Variscite SOM artefact,
since Wi-Fi is disabled on this board."*

Every number is confirmed from the DTB (§6.3): 1,800,000 µV, 70,000 µs, GPIO7_IO08 via
phandle `0x37` = `gpio@020b4000`. Two additions: the phrase "since Wi-Fi is disabled on
this board" understates it — `/wlan` is `status = "disabled"` **and** the kernel has no
driver for it either way; and the reuse is a *forward constraint*, since the GPIO conflict
blocks the SDIO retrofit path (§8 item 5).

### C4 — the gap brief's own premise is inaccurate; recorded so it is not repeated

The assignment stated that grep across the docs returns **zero** hits for `rtlwifi`,
`wifi`, `802.11`, `iwconfig`, `iwlist`. Re-run against `/Volumes/Main External/Development/MoogOnePlus/docs`
**[READ]**: `rtlwifi` → `MOOG-ONE-INTERNALS.md:1816` and `site/moog-one-internals.html:1219`;
`wifi` → the same two lines; `802.11` → `arch/midi2-transport-research.md:106`;
`iwconfig`/`iwlist` → zero (those two terms only are as described). The doc count is also
not 28: `docs/*.md` = 9, `docs/arch/*.md` = 17, `docs/firmware/*.md` = 30 before this report was written, 31 with it. The gap is real — nobody had looked at the kernel side — but it was a gap
*next to a wrong claim*, not a gap next to silence, which is why §11 C1 matters more than
the discovery itself.

---

## 12. Claim ledger

Every load-bearing claim, graded, with its evidence.

| # | claim | grade | evidence |
|---|---|---|---|
| 1 | 11 Realtek firmware images, 248,388 B total, all mtime 2015-12-06 | READ | `ls -la R/lib/firmware/rtlwifi/`; per-file sizes in §4 |
| 2 | Their headers carry valid rtlwifi signatures (`0x88E1`/`0x88C1`/`0x88C2`/`0x92D3`) | READ | struct unpack of first 20 B, §4 |
| 3 | Seven of the eleven are for PCIe-only parts | INFERRED | rtlwifi `ce`/`de`/`se`/`ee` vs `cu`/`eu` naming convention, §4 |
| 4 | `modules.builtin` has 344 entries, none matching `80211\|wireless\|rtl\|rfkill\|lib80211` | READ | `wc -l` + `grep -iE … → exit 1`, §5.1 |
| 5 | The entire tree holds exactly two `.ko`, both rpmsg | READ | `find R/ -name '*.ko'`, §5.2 |
| 6 | `modules.alias` / `.symbols` / `.softdep` / `.devname` are comment-only | READ | full file contents, §5.2 |
| 7 | The decompressed kernel has zero hits for `cfg80211`, `mac80211`, `ieee80211`, `80211`, `nl80211`, `rfkill`, `SIOC*IW*`, `regulatory`, `802.11`, `rtl8*`, `wilink`, `wlcore` | READ | strings over 10,214,816-byte inflated image; positive controls `usbnet` 46 / `nf_conntrack` 83, §5.4 |
| 8 | `wlan%d` in the kernel is `usbnet.c`'s FLAG_WLAN literal, not `cfg80211` | READ | string neighbours `usb%d`/`eth%d`/`wwan%d`/`&dev->phy_mutex`, §5.4 |
| 9 | `wifi-host` / `wifi_card_detect` are `sdhci-esdhc-imx.c`, and no DT node uses them | READ | string neighbours + `strings` on DTB → zero `wifi`, §5.4 |
| 10 | The live instrument has zero modules loaded | READ | `H/runtime-state.txt` `--- modules ---` (header only); CAVEAT permits citing `lsmod` |
| 11 | Live interfaces are `lo`, `usbint`, `ethext` only, both cdc_ether | READ | `H/runtime-state.txt` interfaces; `dmesg:302-305` |
| 12 | v1.5.0's `modules.builtin` is byte-identical; its kernel has the same zero hits | READ | `diff` + strings over the 1.5.0 uImage, §5.5 |
| 13 | wpa_supplicant is v2.5, with nl80211 + wext + wired back-ends and hostapd/AP support | READ | version string, driver description strings, `hostapd_*` symbols, §3.1 |
| 14 | `R/etc/wpa_supplicant.conf` is an unedited placeholder | READ | 11-line verbatim quote, §3.3 |
| 15 | `R/usr/share/dbus-1/system-services/` is empty → no D-Bus activation | READ | `ls -la`, §3.4 |
| 16 | The wpa dhcpcd hook is not in the directory dhcpcd reads | READ | `dhcpcd-run-hooks:366-368` + `ls R/lib/dhcpcd/dhcpcd-hooks/`, §3.5 |
| 17 | dhcpcd *is* started at boot on `ethext` | READ | `R/etc/init.d/S95dhcpd:9`, §3.5 |
| 18 | busybox `ifup` uses `udhcpc`, so the ifupdown path bypasses dhcpcd hooks entirely | READ | `S40network:13` + strings of `R/sbin/ifup`, §3.5 |
| 19 | Nothing in `R/etc`, `R/bin`, `R/sbin`, `R/usr/*`, `R/lib` references `rtlwifi` or `rtl8192` | READ | `grep -rl -a`, §3.6 |
| 20 | The DT's `/wlan` is `ti,wilink8`, `status = "disabled"` | READ | FDT walk, §6.1 |
| 21 | `/wlan_bt_rfkill` is `net,rfkill-gpio`, `status = "disabled"` | READ | FDT walk, §6.2 |
| 22 | No TI WiLink firmware exists anywhere in `R/lib/firmware` | READ | `find R/lib/firmware -type f` (30 files, inventory in §4) |
| 23 | `wlan-en-regulator` (1.8 V, 70 ms, GPIO7_IO08) is the eMMC's `vmmc-supply` | READ | phandle `0x2b` on both nodes, §6.3 |
| 24 | usdhc1 (the SDIO slot) is disabled; the FEC is disabled; PCIe probe fails `-22` | READ | FDT `status` walk + `dmesg:263-265`, §6.4 |
| 25 | A USB Wi-Fi dongle would enumerate but bind no driver and create no netdev | INFERRED | claims 4-8, 10, plus empty `modules.alias`; §7 |
| 26 | Wireless cannot be added without rebuilding the kernel | INFERRED | claims 4-8, 12; §8 |
| 27 | `busybox vconfig` is present but 802.1Q is not in the kernel; the `8021q` string is `sock_ioctl`'s `request_module()` name | READ | applet list; `grep 8021q modules.builtin` → none; string neighbours `bridge`/`net-pf-%d`/`net/core/sock.c`, §10.1 |
| 28 | 112 xtables `.so` against 18 builtin netfilter objects; `xt_conntrack`/`xt_state` absent | READ | `ls \| wc -l`; `modules.builtin:306-314,318-326`, §10.2 |
| 29 | The builtin netfilter set is exactly what `S95dhcpd`'s four DNAT rules need | INFERRED | `S95dhcpd:11-14` vs the 18-object list, §10.2 |
| 30 | The whole wireless stack is byte-identical between 1.5.0 and 1.8.2 | READ | md5 table, §9 |
| 31 | wpa_supplicant `-Dwired` (802.1X on `ethext`) is the one path that could function | INFERRED | `wired` back-end present §3.1 + `af_packet` builtin `modules.builtin:327` |
| 32 | Whether `-Dwired` 802.1X has ever been used | UNKNOWN | nothing on disk configures it |
| 33 | Whether Moog ever intended Wi-Fi, or whether this is pure Buildroot default | UNKNOWN | see §4 provenance — evidence favours default, but is circumstantial |
| 34 | The default driver wpa_supplicant selects with no `-D` in *this* build | UNKNOWN | not verified from the binary; does not affect any conclusion |

---

## 13. Validation plan — read-only commands for the owner

**Not run.** Every command below is read-only; none writes, loads, or configures anything.
Run them on the instrument only if independent confirmation is wanted.

```sh
# 1. Is any 802.11 subsystem present at runtime?  Expect: all absent.
ls -d /sys/class/ieee80211 /sys/class/rfkill 2>&1        # expect: No such file or directory
ls /sys/module | grep -iE '80211|rtl|rfkill|wl'          # expect: no output

# 2. Is the nl80211 generic-netlink family registered?  Expect: not listed.
cat /proc/net/netlink                                     # informational
ls /sys/class/net                                         # expect: lo usbint ethext (no wlan*)

# 3. Loaded modules.  Expect: header line only.
cat /proc/modules

# 4. Wireless extensions.  Expect: file absent (it exists only if CONFIG_WEXT is on).
cat /proc/net/wireless 2>&1                               # expect: No such file or directory

# 5. What wireless-tools reports for every interface.  Expect: "no wireless extensions."
/sbin/iwconfig 2>&1

# 6. Confirm the firmware blobs are untouched and unread.
ls -la --time-style=full-iso /lib/firmware/rtlwifi/ 2>/dev/null || ls -l /lib/firmware/rtlwifi/
md5sum /lib/firmware/rtlwifi/*.bin        # compare against the md5 column in §4

# 7. Confirm the dhcpcd hook directory really lacks the wpa hook.
ls /lib/dhcpcd/dhcpcd-hooks/ /usr/share/dhcpcd/hooks/

# 8. Confirm no D-Bus activation file for the supplicant.
ls -la /usr/share/dbus-1/system-services/

# 9. Confirm the wpa suite is not running.
ps | grep -i wpa | grep -v grep         # expect: no output

# 10. Kernel config, if the build happened to enable IKCONFIG (this one did not — §5.4).
zcat /proc/config.gz 2>&1 | grep -iE 'CFG80211|MAC80211|RTL|RFKILL|VLAN_8021Q'
#     expect: /proc/config.gz: No such file or directory

# 11. VLAN, for §10.1.  Expect: absent.
ls /proc/net/vlan 2>&1

# 12. Which netfilter matches the kernel actually offers, for §10.2.
cat /proc/net/ip_tables_matches /proc/net/ip_tables_targets 2>&1
```

Expected results are stated so a *surprise* is informative. Commands 1-5 and 10-11 returning
anything other than "absent" would falsify §5 and should be reported immediately.

---

## 14. Not covered

* **Bluetooth.** `/wlan_bt_rfkill` names it, and the WiLink8 is a combo part, but no
  Bluetooth stack survey was done (`bluez`, `hciconfig`, `CONFIG_BT`). The kernel
  `modules.builtin` grep for `bluetooth` returned nothing **[READ]**, but the userspace
  side was not inventoried.
* **The `linux-firmware` provenance claim (§4) was not verified against a Buildroot tree.**
  It is graded INFERRED and stays that way until someone diffs against
  `package/linux-firmware/linux-firmware.mk` for Buildroot 2016.02.
* **`R/usr/sbin/dhcpd` (ISC DHCP server, 547,740 B) and the `S80dhcp-*` init scripts.**
  Present, `INTERFACES=""`, apparently dormant — a separate gap.
* **The 112 xtables extensions were counted, not individually cross-referenced** against
  the 18 builtin objects. §10.2 names the one clearly-broken case (`conntrack`/`state`);
  a full match/target audit was not done.
* **`R/boot/imx6dl-profili-som.dtb` was walked only for wireless/mmc/usb/pcie/regulator
  nodes.** A full DT decompile would likely surface other disabled-peripheral stories.
* **Whether any Moog service ever probes for a `wlan*` interface.** `las-frontend` is
  145 MB and was not searched for interface-name literals.
* **`R/lib32/`** was not examined at all.
