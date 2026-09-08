# Network MIDI 2.0 and the UMP transport family

Web research, 2026-09-08. **Nothing in this document touched the instrument.**
No instrument contact, no repository code changed. Everything here comes from
public specifications, vendor documentation and source repositories, plus — for
the closing section only — the existing findings in `docs/arch/`.

This document exists because `docs/arch/midi-stack.md` §9 answers the question
"can this instrument speak MIDI 2.0 over **USB**?" (no, and the reasoning is
sound) but does not consider the **network** transport, which was ratified after
that analysis was framed. The network path changes the answer materially. See
§9.

## Grading

Every claim is graded:

* **[PRIMARY]** — a standards document, a vendor's own documentation, or a source
  repository read directly.
* **[SECONDARY]** — credible reporting that I could not confirm against a primary
  source.
* **[UNVERIFIED]** — asserted somewhere, not confirmed.
* **unknown** — said plainly where that is the honest answer.

Dates and version numbers are given throughout. This field moved fast between
2023 and 2026; treat anything undated as suspect.

---

## 0. The short version

| question | answer |
|---|---|
| Is there a ratified UMP-over-UDP spec? | **Yes.** M2-124-UM, published 2024-11-20. Carries both MIDI 1.0 and MIDI 2.0 messages in UMP format |
| macOS | **Ships and is user-visible.** Audio MIDI Setup, **macOS 26.4** |
| iPadOS / iOS | **No implementation found.** Zero MIDI mentions across all iOS 26.x release notes. See §2.2 — this is a real gap |
| Windows | **Not yet in retail.** Dev preview as of 2026-09-07; targeted for in-box Windows 11 from late Nov 2026 |
| Linux | **No network UMP transport in the kernel.** USB UMP yes (6.5/6.6); network is userspace-only |
| Discovery | mDNS + DNS-SD, service type `_midi2._udp` |
| Pairing | Three modes: open, shared-secret, username+password. All SHA-256 digest over a nonce. Not encrypted |
| Implementations to build on | **Two**: Zephyr's in-tree `netmidi2` (Apache-2.0) and NetUMP+jacknetumpd (MIT). The most official-*looking* one is proprietary — see §4.1 |
| MIDI-CI over SysEx? | **Confirmed, normatively.** Property Exchange rides on MIDI-CI, so no SysEx means no Property Exchange |
| UMP over 5-pin DIN? | **No such transport exists at any status.** DIN remains MIDI 1.0 |
| USB MIDI 2.0 | Descriptor-level change: firmware, not configuration |
| Can a no-SysEx device be MIDI 2.0? | **Yes** — the spec's Minimum Compatibility path B needs no MIDI-CI at all (§5.2) |

The one line that matters for this instrument: **a Network MIDI 2.0 endpoint is a
userspace UDP daemon plus an mDNS record.** It needs no kernel support, no USB
stack, and no XMOS firmware change. See §9.

---

## 1. Network MIDI 2.0 — the specification

### 1.1 Identity

| field | value |
|---|---|
| Title | **User Datagram Protocol for Universal MIDI Packets** — "Network MIDI 2.0 (UDP) Transport Specification" |
| Document number | **M2-124-UM** |
| Version of the text I read | **1.0** |
| Draft date | 2024-11-06 |
| **Published** | **2024-11-20** |
| Publishers | The MIDI Association (MMA) and AMEI (Japan), jointly |
| Current revision on midi.org | **v1.0.1** |

**[PRIMARY]** — read out of the specification PDF itself (title page and the
Version History table, which lists exactly one row: `2024-11-20 | 1.0 | Initial
release`). The freely mirrored copy is at
`https://amei-music.github.io/midi2.0-docs/amei-pdf/M2-124-UM_v1-0_Network-MIDI-2-0-UDP.pdf`.

**On the revision.** midi.org's download is named
`M2-124-UM_v1-0-1_Network-MIDI-2-0-UDP`, so **v1.0.1 is the current revision**
**[PRIMARY]**, but the v1.0.1 document is behind midi.org registration and is not
on the AMEI mirror (I tried both plausible URLs; both 404). **What changed
between 1.0 and 1.0.1 is unknown.** Given the naming convention it is most likely
errata, but I did not confirm that and will not assert it.

Adoption was confirmed independently by the MIDI Association in February 2026:
*"The MIDI Association and AMEI have already adopted the USB MIDI 2.0 and UDP
Network transports."* **[PRIMARY]** — midi.org, "The State of MIDI 2.0", Feb 2026.

### 1.2 Is it MIDI 2.0-only?

**No — it carries both.** The specification's own words: it defines methods where
devices *"discover and connect across an IP based Network and exchange MIDI 1.0
and MIDI 2.0 messages in UMP Format."* **[PRIMARY]**

This is worth being precise about, because it is a common confusion. The
transport carries **Universal MIDI Packets**. UMP is a container format, and it
has message types for both protocols:

* MIDI 1.0 Channel Voice messages travel as UMP Message Type `0x2` — 7-bit
  values, 32-bit packet.
* MIDI 2.0 Channel Voice messages travel as UMP Message Type `0x4` — 16/32-bit
  values, 64-bit packet.

So a device that only has 7-bit data to send is still a perfectly legitimate
Network MIDI 2.0 endpoint. It sends MT `0x2` packets. **This matters a great deal
for §9** — an instrument with nothing but MIDI 1.0 semantics internally can be a
completely conformant Network MIDI 2.0 device. It is not lying about anything.

### 1.3 Scope and what the spec explicitly does not do

*"This network protocol is targeted to run on Local Area Networks with a focus on
Ethernet and wireless LAN (IEEE802.11). Other IP transports like UDP over
Bluetooth or the Internet are not supported by this specification."* **[PRIMARY]**

Two mechanisms for data integrity, both **optional**, both riding on an
incrementing sequence number carried in UMP data packets **[PRIMARY]**:

1. **Forward Error Correction** — resends recently sent data alongside any new
   message. Cheap, no receiver feedback needed.
2. **Retransmit** — receiver asks for missing sequence numbers (`0x80 Retransmit
   Request`), sender replies or errors (`0x81 Retransmit Error`).

The specification is candid about security, and this deserves quoting because it
is the kind of thing that gets glossed over in vendor marketing:

> the defined protocol is not encrypted or secure, so an attacker can easily
> eavesdrop on UMP streams

**[PRIMARY]** — §2.5 Network Security. It goes on to say that even with the
authentication mechanisms, man-in-the-middle and replay attacks can fake a
session. Treat Network MIDI 2.0 as a trusted-LAN protocol.

### 1.4 The command set

Every UDP packet contains one or more Commands. **[PRIMARY]** — Table 10:

| code | command | payload | direction |
|---|---|---|---|
| `0xFF` | UMP Data | sequence number + UMP words | both |
| `0x01` | Invitation | capabilities, endpoint name, product instance id | C → H |
| `0x02` | Invitation with Authentication | SHA-256 digest | C → H |
| `0x03` | Invitation with User Authentication | SHA-256 digest + username | C → H |
| `0x10` | Invitation Reply: Accepted | endpoint name + product instance id | H → C |
| `0x11` | Invitation Reply: Pending | endpoint name + product instance id | H → C |
| `0x12` | Invitation Reply: Authentication Required | crypto nonce | H → C |
| `0x13` | Invitation Reply: User Authentication Required | crypto nonce | H → C |
| `0x20` / `0x21` | Ping / Ping Reply | ping id | both |
| `0x80` / `0x81` | Retransmit Request / Retransmit Error | sequence number | both |
| `0x82` / `0x83` | Session Reset / Session Reset Reply | — | both |
| `0x8F` | NAK | NAK code, command code | both |
| `0xF0` / `0xF1` | Bye / Bye Reply | bye code | both |

Sixteen commands. This is a small protocol — that is the headline for anyone
considering implementing it. Compare RTP-MIDI, which drags in RTP, RTCP and a
journalling recovery scheme.

### 1.5 Roles: Host and Client

**[PRIMARY]** — §2.1, §2.2:

* A **Host** *"is any MIDI 2.0 Device that exposes a UMP Endpoint to the
  Network."* It listens on a UDP port, is advertised via DNS-SD, handles its own
  authentication, and may serve *"any number of MIDI 2.0 UDP Clients as it has
  resources for."* A device may expose several Host endpoints by reserving a
  different UDP port for each.
* A **Client** initiates a session. It uses a unique UDP port per session and
  does **not** advertise itself via DNS-SD.
* *"Devices may implement both Host role and Client role at the same time."*

**A hardware instrument on a network is a Host.** That is the role to build. It
is also the easier role: the Host is the passive side, and does not need to
implement mDNS *browsing*, only mDNS *advertising*.

---

## 2. Host support, per platform, as of 2026-09-08

### 2.1 macOS — ships, user-visible

**Yes.** Audio MIDI Setup on **macOS 26 (Tahoe)** creates and connects Network
MIDI 2.0 sessions, with no third-party software.

Apple's own words: *"You can create different types of sessions, including
Network MIDI 2.0 sessions and RTP sessions."* **[PRIMARY]** — Apple Support,
"Share MIDI information over a network in Audio MIDI Setup on Mac".

I pinned the version with a differential test against Apple's versioned
documentation URLs **[PRIMARY]**:

| Audio MIDI Setup guide version | macOS | mentions "Network MIDI 2.0" |
|---|---|---|
| 3.5 | 12.0 Monterey | **0** |
| 3.6 | 15.0 Sequoia | **0** |
| 3.7 | 26.0 Tahoe | **2** |

So the feature appears in the macOS 26 documentation set and not before.

**The exact point release is macOS Tahoe 26.4**, and this is now confirmed
against Apple's own release notes rather than reporting. **[PRIMARY]** —
`developer.apple.com/documentation/macos-release-notes/macos-26_4-release-notes`,
issue 118728162, quoted in full:

> Audio MIDI Setup now supports Network MIDI 2.0 sessions in the redesigned MIDI
> Network Setup panel. You can create MIDI 2.0 connections over your local
> network using UDP transport for Universal MIDI Packets, enabling both Legacy
> MIDI and MIDI 2.0 protocol communication. Network MIDI 2.0 sessions appear
> alongside existing RTP MIDI sessions and support automatic device discovery
> through mDNS and data integrity features for reliable wireless performance.

Three things worth extracting from that sentence: it is **mDNS** discovery as
specified (§3.1); it explicitly carries **"both Legacy MIDI and MIDI 2.0
protocol"**, matching §1.2; and it implements the **data integrity** features,
i.e. the optional FEC/retransmit mechanisms of §1.3. It coexists with RTP-MIDI
rather than replacing it.

Release notes for macOS 26.5 and 26.6 exist and mention no further MIDI changes
**[PRIMARY]**, so 26.4 is the introduction and nothing has amended it since.

**The user flow** **[PRIMARY]** — Apple Support, same page:

1. Audio MIDI Setup → Window → Show MIDI Studio
2. Click **Configure Network Driver** in the toolbar
3. Click **+** below *My Sessions*
4. **Select the session type — Network MIDI 2.0 or RTP**
5. Set local name, port, network name
6. Turn **Enabled** on to publish the session on the network
7. Discovered devices appear in a directory; click **Connect**

There is a *"Who may connect to me"* connection policy popup governing inbound
connections. **[PRIMARY]**

**A caveat on the API surface.** Apple's *public* CoreMIDI networking API —
`MIDINetworkSession`, `MIDINetworkHost`, `MIDINetworkConnection` — is **RTP-MIDI**,
and Apple's Core MIDI release notes list only MIDI-CI v1.2, UMP/MIDI 2.0 Protocol
v1.1.1 and DriverKit drivers as recent additions. **[PRIMARY]** — developer.apple.com
documentation JSON for `coremidi/midi-networking` and `updates/coremidi`. I found
**no public CoreMIDI API for creating a Network MIDI 2.0 session
programmatically.** It appears to be an OS/Audio-MIDI-Setup-level feature whose
endpoints then surface as ordinary CoreMIDI UMP endpoints to applications. For
our purposes that is fine — the user drives it from Audio MIDI Setup and every
DAW sees a normal MIDI endpoint — but an app developer wanting to automate it may
be stuck. **Whether a private or newer public API exists is unknown.**

### 2.2 iPadOS / iOS — no implementation found, and this is a real gap

**No user-visible Network MIDI 2.0 implementation on iPadOS or iOS, and I am not
going to infer one from the macOS result.**

The strongest evidence is a differential test against Apple's own release notes,
run the same way as the macOS one above **[PRIMARY]**:

| release notes | mentions of "MIDI" |
|---|---|
| **macOS 26.4** | **9** — including the Network MIDI 2.0 paragraph quoted above |
| iOS/iPadOS 26 | **0** |
| iOS/iPadOS 26.4 | **0** |
| iOS/iPadOS 26.5 | **0** |
| iOS/iPadOS 26.6 | **0** |

Apple documented the feature explicitly for macOS in the very release where it
landed, and said nothing whatsoever about MIDI on iOS/iPadOS across the whole 26
cycle. Release notes are not exhaustive, so this is not absolute proof — but it
is a strong, specific negative rather than an absence of searching.

What else is true:

* CoreMIDI on iOS/iPadOS has had MIDI 2.0 / UMP support for years **[PRIMARY]** —
  Apple's "Incorporating MIDI 2 into your apps" and the MIDI Services
  documentation are shared across platforms.
* iOS has **never shipped an Audio MIDI Setup app** — the app Apple's own
  instructions route every network-MIDI setup through is macOS-only. Historically
  RTP-MIDI on iOS is configured *from the Mac side*, or via third-party apps.
  **[PRIMARY]** — Apple Support, Logic Pro for iPad MIDI documentation, which
  instructs the user to create the network session in Audio MIDI Setup **on the
  Mac**.
* A third-party App Store utility exists for configuring **RTP-MIDI** entirely on
  iOS/iPadOS. **[PRIMARY]** — App Store listing. That is RTP, a different
  protocol, not Network MIDI 2.0.

**A warning about secondary sources on this point.** Several search results and
articles blur RTP-MIDI and Network MIDI 2.0 together, producing statements like
"iPads can participate in Network MIDI 2.0 sessions once configured on a Mac."
That claim is about **RTP-MIDI** and does not transfer. Do not let it into the
reasoning.

So: **does an iPad see a Network MIDI 2.0 endpoint without third-party software?
The evidence says no, and there is no positive evidence that it can.** If the
iPad matters, settle it empirically — see §9.4. It is the single most important
open question in this document.

### 2.3 Windows — dev preview, targeted for late 2026

**Windows MIDI Services** — Microsoft's ground-up replacement for the WinMM MIDI
stack, developed in the open at `github.com/microsoft/MIDI` — reached general
availability for MIDI 1.0 and MIDI 2.0 in **February 2026**, rolling out to
in-support retail Windows 11 releases. **[SECONDARY]** — Windows Experience Blog,
2026-02-17; corroborated by the MIDI Association.

**Network MIDI 2.0 is not in retail Windows as of today.** Microsoft's own
release notes, In-box Dev Preview 7, dated **2026-09-07** — yesterday:

> Network MIDI 2.0 implementation is feature complete for our first in-box
> release. Note that it does not yet support any sort of authentication, and will
> not in our first in-box release.

**[PRIMARY]** — github.com/microsoft/MIDI releases. The stated plan is for the
Network MIDI components and the WinRT API to be **included in Windows 11 25H2
starting the last week of November 2026**, after a September cutoff for fixes.
**[PRIMARY]**

Preview 5 (2026-08-25) noted the implementation *"passes all the protocol spec
tests"* **[PRIMARY]**.

Design details, from Microsoft's documentation **[PRIMARY]** —
`microsoft.github.io/MIDI`:

* Windows MIDI Services acts as a **Host** that other clients connect to, and
  also supports **Client** entries that auto-connect to external hosts found via
  mDNS. Both roles.
* *"Network MIDI 2.0 discovery uses the established standard mDNS with DNS-SD,
  also known as 'ZeroConf networking' and 'Apple Bonjour'. Windows MIDI Services
  uses mDNS natively on Windows in user-mode code."*
* Transports are **plugins** — *"enabling support for new transports like Network
  MIDI 2.0 without creating kernel device drivers."* This is architecturally the
  same insight as §9 below: network UMP is a userspace problem.
* **Firewall caveat, and it will bite people:** by default the Windows MIDI
  Service is not permitted to accept inbound connections, so *"external Network
  MIDI 2.0 devices will see the service advertised but connection requests will
  be blocked."* Connection requests *"will be ignored, because they are blocked
  before the service sees them."* The fix is to allow **`midisrv.exe`** through
  Windows Firewall for the appropriate network profile. Microsoft publishes a
  dedicated knowledge-base page for this. **[PRIMARY]** —
  `microsoft.github.io/MIDI/kb/network-midi-firewall/`

  Note *why* the guidance is per-application rather than per-port: because there
  is no fixed port to open (§3.1). The Host picks one and publishes it in its SRV
  record. Any firewall guidance you write for your own device's users will have
  the same shape — and if you pick a **stable** port rather than an ephemeral one,
  you make their lives considerably easier.

Note the asymmetry with authentication: Microsoft ships **no authentication at
all** in the first in-box release. A device requiring authentication will not
work with Windows initially. Design accordingly — see §3.3.

### 2.4 Linux — USB yes, network no

Split this carefully, because the two are routinely conflated.

**UMP and USB MIDI 2.0: in-tree and mature.** **[PRIMARY]**

| what | kernel | evidence |
|---|---|---|
| ALSA UMP core, sequencer UMP, USB MIDI 2.0 host (`snd-ump`, `CONFIG_SND_UMP`, `snd-usb-audio` MIDI 2.0) | **6.5** | kernelnewbies.org/Linux_6.5, §1.7 Prominent Features: *"This release adds support for the 2.0 version of the popular MIDI format… Universal MIDI Packet (UMP)"* |
| `f_midi2` USB MIDI 2.0 **gadget** function driver | **6.6** | Phoronix, "USB MIDI 2.0 Gadget Function Driver Merged For Linux 6.6"; LWN 939185 **[SECONDARY→PRIMARY]** the patch series itself is on lore |
| UMP 1.1 catch-up (Function Blocks etc.) | 6.6 cycle | LWN 934414 |

Devices appear as `/dev/snd/umpC*D*` alongside the legacy `/dev/snd/midiC*D*`
nodes, and the kernel converts transparently between UMP and MIDI 1.0 byte
streams so existing applications keep working. **[PRIMARY]** — docs.kernel.org
"MIDI 2.0 on Linux".

**Network UMP: not in the kernel.** I read the current kernel MIDI 2.0
documentation page (rendered against 7.3.0-rc2) and searched it for
network/UDP/Ethernet references: **the only hits are site navigation chrome, not
content.** **[PRIMARY]** — docs.kernel.org/sound/designs/midi-2.0.html. I also
searched lore/LWN/Phoronix for a network UMP patch series and found none; all the
Iwai work is USB and sequencer.

**This is the correct architecture, not a deficiency.** Network MIDI 2.0 is UDP
plus mDNS. There is no reason for it to be in the kernel, and Microsoft
independently reached the same conclusion (transport plugins in user mode, §2.3).
A Linux Network MIDI 2.0 endpoint is an ordinary userspace daemon. If you also
want local ALSA clients to see it, you bridge it into the sequencer — and *that*
would want `snd-ump`, i.e. kernel ≥ 6.5. If you only want to be reachable from
the network, you need nothing from the kernel at all.

PipeWire can transport UMP **[SECONDARY]**; DAW and controller support on Linux
lags the kernel considerably **[SECONDARY]**.

---

## 3. Discovery and pairing

### 3.1 Advertisement

**mDNS + DNS-SD** (RFC 6762 / RFC 6763). *"The use of mDNS is optional but
recommended and it is the only mechanism defined in this specification for
automated discovery."* **[PRIMARY]** — §2. Manual entry of IP and port is the
alternative.

**The service type is `_midi2._udp`.** **[PRIMARY]** — §4, Table 5. Three record
types, all standard DNS-SD:

**PTR** — one record per service instance:
```
_midi2._udp.local.  PTR  173ACE-MIDIWorkbench._midi2._udp.local.
```

**SRV** — the UDP port and hostname:
```
173ACE-MIDIWorkbench._midi2._udp.local. 60 IN SRV 0 0 5673 desktop.local.
```

**There is no fixed or IANA-registered port.** The port is a plain 16-bit number
chosen by the Host and published in the SRV record; `5673` above is the
specification's *example*, not an assignment. **[PRIMARY]** — §3, Table 8. Clients
do not advertise ports at all; they allocate a free one per session.

**TXT** — exactly two keys are defined **[PRIMARY]** — Table 6:

| key | content |
|---|---|
| `UMPEndpointName` | the name shown to the user. UTF-8, ≤ 98 bytes. Must match the UMP Endpoint Name Notification message |
| `ProductInstanceId` | unique per physical device. ASCII 32–126, ≤ 42 bytes. Must match the Product Instance Id Notification message |

```
173ACE-MIDIWorkbench._midi2._udp.local. TXT
    UMPEndpointName=MIDI Workbench
    ProductInstanceId=173ACEHDI3nVAUiFH
```

Two details that will save an implementer a day each:

* **The Service Instance Name is not the display name.** *"The Service Instance
  Name should not be displayed to the user. The UMP Endpoint Name provided in the
  TXT record"* is. The spec suggests constructing the instance name from the
  Product Instance Id plus the model name. **[PRIMARY]**
* **Persistence matters.** Service Instance Names and hostnames *should* be
  persistent across power cycles, and operating systems *"may use the
  UMPEndpointName and ProductInstanceId to recall Device properties when
  reconnecting."* **[PRIMARY]** Get this wrong and the host re-adds your device as
  a new one after every reboot.

### 3.2 What the user does

On a Mac: Audio MIDI Setup → Configure Network Driver. Discovered `_midi2._udp`
hosts appear in a directory; select and **Connect**. **[PRIMARY]** — §2.1 above.

On Windows (once shipped): the device is found via mDNS and can be configured to
auto-connect, subject to the firewall rule. **[PRIMARY]** — §2.3.

On an iPad: **unknown.** See §2.2.

### 3.3 Authentication — three modes, and they are weak by design

The Host chooses. **[PRIMARY]** — §6:

1. **Open.** Client sends `0x01 Invitation`; Host replies `0x10 Accepted`. No
   secret.
2. **Shared secret / password.** Host replies `0x12 Authentication Required`
   carrying a **CryptoNonce**. Client re-invites with `0x02`, carrying a
   **SHA-256 digest** over the nonce and the shared secret.
3. **User authentication.** Same, but `0x13` / `0x03`, and the client also sends a
   **username**.

A fourth, orthogonal mechanism: `0x11 Invitation Reply: Pending`, which lets the
Host stall while it asks a human. The spec's own example: *"this might occur when
the Host asks the user for permission and is waiting for user acknowledgment."*
**[PRIMARY]** This is the "a dialog appears on the instrument's screen" flow.

Negotiation is explicit. The Invitation's **Capabilities** byte has two defined
bits **[PRIMARY]** — Table 11:

| bit | meaning |
|---|---|
| D0 | Client supports sending Invitation with Authentication |
| D1 | Client supports sending Invitation with User Authentication |

If the Client cannot do what the Host wants, the Host *"may use a fallback, for
example by asking the user for manual confirmation"*; if it has no fallback it
sends `Bye` with reason `0x45` (No Matching Authentication Method). **[PRIMARY]**

**The practical guidance is: accept mode 1, and do not *require* anything more.**

The platform picture is asymmetric:

* **Windows ships no authentication at all** in its first in-box release, and
  Microsoft's credential storage is literally `E_NOTIMPL` (§2.3, §4.3). A device
  that *requires* authentication will simply not connect from Windows.
* **Apple's client does support it.** A symbol diff across macOS 26.3 → 26.4
  shows `NetMIDI2AuthorizationData` with both `initWithSharedSecret:` and
  `initWithUsername:password:` (§4.6). **[SECONDARY]**

So a Host that demands a password is reachable from a Mac and unreachable from
Windows, for no security benefit that survives §1.3 — the session is unencrypted
and replayable regardless. **Access control belongs at the network layer here,
not in the MIDI protocol.**

But do not *ignore* authentication: because Apple's client may offer it, a Host
should at minimum parse `0x02`/`0x03` invitations and, if it cannot satisfy them,
respond cleanly with `Bye` reason **`0x45`** (No Matching Authentication Method)
rather than timing out. A silent timeout is the failure mode users report as
"it just doesn't work."

---

## 4. Implementations available to build on

### 4.0 The one thing to read first

**Distinguish a UMP *message* library from a Network MIDI 2.0 *transport*
implementation.** Most things that come up in a search for "MIDI 2.0 library" are
the former: they encode and parse UMP words. They contain no UDP, no session
protocol, no mDNS. They are useful *alongside* a transport, never instead of one.
`sauloverissimo/midi2` states this in its own README: the transport *"lives
somewhere else, by design."*

### 4.1 The trap

**`midi2-dev/NetworkMIDI2` is proprietary, binary-only, and forbids commercial
use without a paid AmeNote licence.** **[PRIMARY]** — its LICENSE file:

> Source code for the Software is proprietary and is not included in this
> distribution.

Free for education, evaluation and **non-commercial** development only;
"COMMERCIAL USE REQUIRES A LICENSE", explicitly including *internal business
tooling*; redistribution and reverse engineering prohibited.

This matters because it is the repo that looks most official: it sits in the
**MIDI Association's own GitHub organisation**, it is listed on midi2.dev
alongside genuinely open-source projects with no licensing distinction drawn, and
GitHub reports its licence as `NOASSERTION`. It ships headers plus prebuilt
`libnetworkmidi2.a` for macOS/Linux/Pico/NXP. It is also 0.x software: **v0.2.1
(Aug 2026) fixed a bug where a Host could only ever accept one session** — after
the first client disconnected, no further client could connect.

Related AmeNote items, so they are not confused with it:

* **`AM_MIDI2.0Lib`** — MIT, ★71, active. **UMP and MIDI-CI message encoding
  only.** Zero network/UDP/mDNS files. **[PRIMARY]**
* **`AmeNote_Protozoa`** — ProtoZOA firmware, conditional MIT. Its network bridge
  *links the proprietary blob above*; the glue is open, the stack is not.
* **Mitosys** — AmeNote's **commercial hardware** line (M-2U, M-2U22, M-5U). Not
  a library, not open source.

### 4.2 What is actually usable

Licences read from the LICENSE files; dates from the GitHub API on 2026-09-08.
**[PRIMARY]**

| project | lang | licence | Host? | mDNS | maturity |
|---|---|---|---|---|---|
| **Zephyr `subsys/net/lib/midi2/`** | C | **Apache-2.0** | **yes** | yes | **upstream**, merged 2025-10-08 |
| **bbouchez/NetUMP** | C++ | **MIT** | **yes** | **no** | active; no tags; "major bugs corrected" 2026-09-05 |
| bbouchez/jacknetumpd | C++ | MIT | yes | **yes** (`UMP_mDNS.cpp`) | ships in Zynthian |
| tiwai/amidi2net | C | MIT | yes | yes | v0.4, **dormant** — no commits since 2025-05-22 |
| DatanoiseTV/…-esp-idf | C | MIT | yes | yes | v0.3.0, quiet since June 2026 |
| microsoft/MIDI | C++/WinRT | MIT | yes | yes | active daily; **all 40 releases prerelease** |
| midi2-dev/MIDI2.0Workbench | JS/Node | MIT | yes | yes | the MA's own tool |
| titouanc/pymidi2 | Python | MIT | client-focused | yes | author: *"currently incomplete"* |

**The two worth building on:**

**Zephyr `netmidi2`** — the cleanest licence and the only one genuinely upstream
in a maintained OS. An 833-line core plus `include/zephyr/net/midi2.h` and a
sample, merged as PR #93933 on **2025-10-08** (author Titouan Christophe),
Apache-2.0. Implements the full session state machine, `NETMIDI2_HOST_AUTH` with
both shared-secret and user/password, and `NETMIDI2_HOST_MAX_CLIENTS`. The
downside is real: **you inherit Zephyr**, which is not a fit for an existing
Linux userspace.

**NetUMP + BEBSDK + jacknetumpd** — all MIT, and **the combination that actually
ships in a real open-source hardware synth**: `zynthian/zynthian-ui` wires
`jacknetumpd:netump_in/out` into its JACK graph and reads the `UMPEndpointName`
JACK property to label ports. **[PRIMARY]** For an instrument-side endpoint this
is the closest existing analogue to the job.

**Two caveats on NetUMP.** It contains **no mDNS at all** — a source grep for
`mdns|dns.sd|bonjour|avahi|_midi2|multicast` returns nothing — so without adding
discovery **a Mac cannot find your device in Audio MIDI Setup**. The fix is to
lift `UMP_mDNS.cpp` (11.5 KB, MIT) from `jacknetumpd`, or use Avahi as in §9.2.
And it requires the host application to call `RunSession()` about every 1 ms from
a realtime thread — a real scheduling constraint on a loaded embedded box.

**For Linux userspace specifically: `tiwai/amidi2net`** deserves a mention out of
proportion to its activity — MIT, C, *"Copyright (c) 2025 Takashi Iwai"*, i.e.
written by the ALSA maintainer, but deliberately **outside** the kernel as example
programs. `amidi2net-server` exposes a UMP Endpoint over UDP, advertises via
mDNS, and bridges to the ALSA sequencer or rawmidi UMP. It has retransmit timeout
handling, IPv6, and both auth methods. **But it is dormant** — v0.4, no commits in
over a year. Treat it as high-quality reference code, not a maintained
dependency. Its very existence is also the clearest possible signal about §2.4:
the ALSA maintainer implemented network UMP in *userspace*, on purpose.

### 4.3 Read this before writing code

**`microsoft/MIDI` → `src/in-box/Transport/UdpNetworkMidi2Transport/SPEC_REVIEW.md`**
(13.7 KB, MIT). A clause-by-clause conformance review of M2-124-UM v1.0 —
which clauses are `shall` versus `should`, exact byte limits and the reasoning
behind them, and documented deviations. **[PRIMARY]** It is the best free
engineering write-up on implementing this specification.

The surrounding transport (~15,700 lines) is **not** portable — its networking is
WinRT (`DatagramSocket`, `HostName`, `DataWriter`) rather than sockets, with COM,
WIL and TraceLogging throughout, and no abstraction seam. **Port the reasoning,
not the code.** Note also that Microsoft's authentication is *not* implemented:
`ResolveSharedSecret()` and `ResolveUserCredential()` both `return E_NOTIMPL`
(open issue #733). The digest itself is implemented and passes the spec's worked
examples; what is missing is credential storage.

### 4.4 Language-by-language, including the negatives

* **Go — none.** A definitive negative: a code search for `"_midi2._udp"
  language:go` returns zero results. **Two repos advertise Go Network MIDI 2.0
  and do not implement it** — `Phoenixai36/midi2-hub` and a near-identical clone
  are a **WebSocket + JSON room-broadcast server** (`nhooyr.io/websocket`, message
  types `join`/`clock`/`clip`), with no UDP, no UMP, no invitation and no mDNS.
  The descriptions are marketing. **[PRIMARY]** Partial building blocks only:
  `gomidi/midi` is MIDI 1.0 (no UMP); `laenzlinger/go-midi-rtp` is RTP-MIDI,
  GPL-3.0, last touched 2024-02-13.
* **Rust — no network implementation.** The `midi2` crate (crates.io v0.11.1,
  2026-04-09, MIT OR Apache-2.0) is *"strong types wrapping MIDI 2.0 message
  data"* — message layer only. Nothing on crates.io implements the transport.
  Note `ni-midi2` is **C++, not Rust**, despite the name.
* **C/C++ frameworks — none have network UMP.** JUCE has UMP *messages* but no
  `_midi2._udp`; the existence of `gregogiudici/Networked_JUCE_Template`, which
  vendors NetUMP as a submodule, is the proof. **libremidi** (BSD-2-Clause, ★705,
  very active) has UMP via OS APIs — ALSA, JACK, PipeWire, WinMIDI — but **no
  network backend**. **RtMidi** is MIDI 1.0 only.
* **Python** — `pymidi2` only, and self-described as incomplete. Nothing on PyPI.
* **JavaScript** — MIDI 2.0 Workbench genuinely implements both roles
  (`libs/UMPudp.js`, 52 KB, `bonjour-service`) with an interactive host-approval
  flow. Its own README cautions it *"should not be seen as reference code"*.
* **Embedded** — Zephyr, and DatanoiseTV's ESP-IDF component.

### 4.5 Conformance testing — there is none published

**The specification defines no conformance test suite and no reference
implementation** — confirmed by grepping the full text; it contains only
RFC2119-style conformance wording. **[PRIMARY]**

Microsoft's *"passes all the protocol spec tests"* (§2.3) is a **self-report**
against their own suite, `src/in-box/Test/Midi2.Transport.NetworkMidi2.unittests/`
(MIT, ~152 test methods). Methodologically it is strong — the test harness is an
independent reimplementation of the wire format sharing no code with the
transport under test — **but the framework is TAEF/WEX: Windows-only, and it
needs a running Windows MIDI service. You cannot point it at your device from a
Mac or a Linux box.** **[PRIMARY]**

So **conformance today means interop testing against real peers.** The practical
kit:

* **MIDI 2.0 Workbench** — the MA's own tool; acts as Host *or* Client, so it is
  a usable peer from any desktop. Whether it emits an M2-124-UM conformance report
  specifically is **unknown**.
* **KissBox NetworkUMP Wireshark plugin** (`midi2.lua`, 38 KB) — decodes the
  protocol in Wireshark 4.4+. Probably the single most valuable debugging asset
  for endpoint work. **Warning: this repo has no LICENSE file at all**, so its
  reuse terms are undefined.
* A real **macOS 26.4** machine.

### 4.6 Interop evidence

* **DatanoiseTV's ESP-IDF component README:** *"macOS interop: confirmed working
  — discovered, connects over Ethernet (IPv4/IPv6) via MIDI Network Setup, and
  exchanges UMP as a bidirectional MIDI port."* **[PRIMARY, vendor claim]** This
  is the most directly encouraging data point for an embedded endpoint.
* **Counterpoint, recorded rather than dismissed:** `erickampman/netmidi2`'s
  README states *"Apple's macOS/iPadOS 'UMP Network' support is still beta and its
  handshake does not reliably complete with third parties."* **[PRIMARY as a
  developer's claim, uncorroborated]** — it may predate the 26.4 release.
* **Apple's client can request authentication.** A third-party dylib symbol diff
  across the 26.3 → 26.4 boundary shows CoreAudioKit gaining ~50 `NetMIDI2`
  symbols, including **`NetMIDI2AuthorizationData` with `initWithSharedSecret:`
  and `initWithUsername:password:`**. **[SECONDARY — symbol diff, not Apple
  documentation]** See the consequence in §3.3.
* **A port to avoid:** AmeNote's samples use UDP **5004**, which collides with
  RTP-MIDI — the KissBox Wireshark plugin documents exactly this dissector
  conflict. Pick something else.
* **No evidence of iPadOS support surfaced from any implementer**, which is
  independent corroboration of §2.2.

**Confidence note:** the exhaustive negatives above (no Go implementation, no Rust
network crate, no published conformance suite) rest on GitHub code search,
crates.io, PyPI and web search. Strong, but not provably exhaustive — GitHub code
search indexes only default branches.

---

## 5. MIDI-CI and Property Exchange

### 5.1 Is MIDI-CI carried over System Exclusive? — Confirmed

**Yes. Unambiguously, in the specification's own words.**

| field | value |
|---|---|
| Title | **MIDI Capability Inquiry (MIDI-CI)** — "Bidirectional Negotiations for MIDI Devices" |
| Document | **M2-101-UM** |
| Version | **1.2** |
| Draft date | 2023-05-11 |
| Published | **2023-06-15** |

**[PRIMARY]** — read out of the specification PDF. The load-bearing sentences:

> MIDI-CI Transactions are accomplished using Universal System Exclusive
> messages.

> All MIDI-CI messages use 0x0D as value for Universal System Exclusive Sub-ID#1.

The message frame is exactly as expected **[PRIMARY]** — §6, message layout table:

```
F0            SysEx Start
7E            Universal System Exclusive (Non-Real Time)
<Device ID>   addressing; 0x00–0x0F map to channels, 0x7F = whole port
0D            Sub-ID#1: MIDI-CI
<Sub-ID#2>    Category and type of MIDI-CI message (e.g. 0x70 = Discovery)
...           Source MUID (4 bytes), Destination MUID (4 bytes), payload
F7            SysEx End
```

Device ID addressing: `0x00`–`0x0F` = MIDI channels 1–16, `0x7E` = Group,
`0x7F` = Function Block. **[PRIMARY]**

**MUID** is a **28-bit random number**, range `0x00000000`–`0x0FFFFFFF`, with
`0x0FFFFFFF` reserved as the Broadcast MUID. It is regenerated on every power-up
and a device **shall not** reuse one across restarts. It is 28 bits rather than
32 precisely because it travels as four 7-bit SysEx data bytes. **[PRIMARY]** —
§3.3. That detail is a neat illustration of how deeply MIDI-CI is shaped by its
SysEx carrier.

**Is there any way to do MIDI-CI without SysEx? No.** On a UMP transport MIDI-CI
travels as **SysEx7, Message Type `0x3`** — M2-104-UM Table 35 lists the row
literally as *"MIDI-CI - System Exclusive Messages (MT 0x3)"*. **[PRIMARY]** The
`F0`/`F7` framing bytes are dropped by the container, but the Sub-ID#1 = `0x0D`
structure, the MUIDs and the entire transaction model are unchanged. (I found no
spec text authorising SysEx8 / MT `0x5` as a carrier for MIDI-CI *negotiation*;
SysEx8 appears in the Profiles spec only as a data type a Profile's own payload
may use. **Whether MT `0x5` is permitted as a MIDI-CI carrier: unknown.**)

**And SysEx support is a normative minimum requirement of MIDI-CI itself** —
M2-101-UM Appendix E **[PRIMARY]**:

> Support System Exclusive message lengths of at least 128 bytes. Support System
> Exclusive message lengths of at least 512 bytes if either Profile Configuration
> or Property Exchange is supported.

The Discovery message carries a mandatory 4-byte *Receivable Maximum SysEx
Message Size* field to enforce it.

**So: a device that implements no SysEx at all cannot do MIDI-CI, cannot do
Profiles, cannot do Property Exchange, and cannot do Process Inquiry.** There is
no alternative binding. This is not an implementation convention that a clever
device might route around — it is written into the specification's minimum
requirements. It is the finding that governs §8.4.

### 5.2 The crucial nuance: UMP Stream messages are *not* SysEx

This is the distinction that makes §9 possible, and it is routinely missed.

**UMP Stream Messages are Message Type `0xF`** — native 128-bit UMP messages
addressed to the UMP Endpoint as a whole, with no Group or Channel assignment.
They are **not SysEx** and have nothing to do with MIDI-CI. **[PRIMARY]** —
M2-104-UM v1.1.1 §7.1, and Table 33 "128 bit UMP Formats for Message Type 0xF".

The full set **[PRIMARY]** — §7.1.1–7.1.11:

| message | what it conveys |
|---|---|
| Endpoint Discovery | request for the below |
| Endpoint Info Notification | UMP version, number of Function Blocks, protocol support |
| Device Identity Notification | manufacturer / family / model / revision |
| **Endpoint Name Notification** | the human-readable endpoint name |
| **Product Instance Id Notification** | unique per-unit id |
| Stream Configuration Request / Notification | negotiate MIDI protocol and JR timestamps |
| Function Block Discovery / Info / Name Notification | up to **32** Function Blocks, each spanning 1–16 Groups |
| Start of Clip / End of Clip | file/stream framing |

Status values are `0x00` Endpoint Discovery, `0x01` Endpoint Info, `0x02` Device
Identity, `0x03` Endpoint Name, `0x04` Product Instance Id, `0x05`/`0x06` Stream
Configuration Request/Notification, `0x10`–`0x12` Function Block
Discovery/Info/Name, `0x20`/`0x21` Start/End of Clip. **[PRIMARY]**

Function Block Info is richer than one might expect: active flag, direction
(input / output / bidirectional), a **MIDI 1.0 port flag with bandwidth
restriction**, a **UI Hint** (sender / receiver / both), first Group, Groups
spanned (1–16), and *which MIDI-CI version the block supports, where `0x00` means
none or unknown.* **[PRIMARY]** A device can therefore say "I support no MIDI-CI"
in a structured way, natively, without SysEx.

**What this means practically:** a device with **zero SysEx** can still identify
itself by name, publish a stable product instance id, report
manufacturer/family/model/revision, describe its port structure via Function
Blocks with names and directions, and negotiate protocol. Note that the Network
MIDI 2.0 transport *requires* the endpoint name and product instance id to match
these notifications (§3.1) — so the network spec is built on the assumption that
a device implements UMP Stream messages, **not** that it implements MIDI-CI.

**And this is enough to be a compliant MIDI 2.0 device.** M2-100-U §5, *Minimum
Compatibility Requirements*, offers two independent paths (see also §6.4):

* **path A** — MIDI-CI plus Profiles / Property Exchange / Process Inquiry. All
  SysEx.
* **path B** — the **UMP data format including UMP Endpoint discovery**, plus at
  least one of: MIDI 2.0 Channel Voice Messages, JR Timestamps, SysEx8, Mixed
  Data Set.

**Path B contains no MIDI-CI and requires none.** **[PRIMARY]** A device can be a
fully legitimate MIDI 2.0 device without implementing a single SysEx byte. This
is the specification's own sanction for the architecture proposed in §9.

**What UMP Stream messages cannot do: enumerate parameters.** Confirmed by
exhaustion of the message list above — there is no UMP Stream message carrying a
parameter list, controller enumeration, program list, ranges, defaults or units.
They describe *identity and structure*, not *controls*. For a parameter list you
need Property Exchange, and therefore SysEx.

**One discrepancy to flag for implementers.** The Network MIDI 2.0 spec states
`ProductInstanceId` is *"up to 42 bytes"* (§3.1, TXT record), while the UMP
Stream Product Instance Id Notification is reported as **≤16 bytes**. These two
readings do not agree. I did not resolve it. **Verify against both specs before
choosing a length** — 16 is the safe choice.

### 5.3 Property Exchange

| field | value |
|---|---|
| Title | **Common Rules for MIDI-CI Property Exchange** |
| Document | **M2-103-UM** |
| Version | **1.2** |
| Draft / published | 2024-11-12 / **2024-11-20** |

**[PRIMARY]** Note the version history, because it is itself evidence: v1.0
2020-02-20, **v1.1 2020-12-08, then nothing until v1.2 in November 2024.** The
specification sat frozen for **nearly four years**. v1.2 added flow control,
`simpleAction`/`selectorAction` roles, and expanded `cacheTime`.

Every PE resource specification opens with the same sentence **[PRIMARY]**:

> Property Exchange is a method for **sending JSON over SysEx** between two
> devices to get and set device properties.

**Does it offer a machine-readable parameter list? Yes — and the design is
genuinely good.** `ResourceList` is **mandatory** for any device supporting PE,
and returns entries carrying `resource`, `canGet`, `canSet`, `canSubscribe`,
`mediaTypes`, `encodings`, `schema` (JSON Schema), `canPaginate` and `columns`.

The parameter enumeration lives in **M2-117-UM v1.0 (published 2023-06-15)**:
`AllCtrlList`, `ChCtrlList`, `CtrlMapList`. Each controller entry carries
**[PRIMARY]**:

| key | meaning |
|---|---|
| `title` (required) | human-readable name |
| `description` | CommonMark |
| `channel` (required) | 1–256, numbered across Groups |
| `ctrlType` (required) | `cc`, `chPress`, `pPress`, `nrpn`, `rpn`, `pBend`, plus MIDI-2.0-only `pnrc`, `pnac`, `pnp` |
| `ctrlIndex` | CC number, or (N)RPN bank + index |
| `priority` | 1 Essential → 5 Hidden — *"a hardware controller with a limited number of sliders and knobs can use the `priority` Property to easily auto assign"* |
| `default` | **unsigned 32-bit** |
| `transmit` / `recognize` | `absolute` / `relative` / `both` / `none` |
| `numSigBits` | significant bits of the 32-bit value |
| `paramPath` | JSON Pointer, e.g. `/Oscillator/A/Envelope/Attack` |
| `typeHint` | `continuous`, `momentary`, `toggle`, `relative`, `valueSelect` |
| `ctrlMapId` | reference into `CtrlMapList` for labelled points (`{"value":…,"title":"-70dB"}`) |
| `stepCount`, `minMax` | discrete steps; recognized range |

Hierarchical parameter paths, auto-mapping priorities, transmit/recognize
asymmetry, unit labels, declared significant bits. **The design is not the
problem.**

**Transport.** JSON, chunked over SysEx, framed with a Request ID for
correlation, chunk counts, and separate header and property byte counts.
Encodings: `ASCII`, `Mcoded7` (8-bit → 7-bit, a **14.3% size penalty**), or
`zlib+Mcoded7` (RFC 1950 then Mcoded7; Mcoded7 is mandatory for zlib data). Chunk
size is bounded by the *Receivable Maximum SysEx Message Size* discovered during
MIDI-CI Discovery. PE sub-IDs are `0x30`–`0x3F`, and PE is **only legal at Device
ID `0x7F`** (whole Function Block). **[PRIMARY]**

**Does it ride on SysEx? Yes** — M2-103-UM §3.1: *"Property Exchange is sent via
MIDI-CI Universal System Exclusive messages."* **A device with no SysEx cannot do
Property Exchange. This is normative in three separate documents; refutation is
not possible.**

### 5.4 Adoption — thin, uneven, and marketing outpaces shipping

This is where the case for Property Exchange weakens considerably, and it is
worth being blunt about it.

**The platform APIs are the clearest structural evidence.**

* **Apple ships Profiles APIs and no Property Exchange API.** CoreMIDI exposes
  `MIDICIDevice`, `MIDICIDiscoveredNode` (with `supportsProfiles`,
  `supportsProperties`, `maximumSysExSize`), `MIDICIProfile`, `MIDICISession`.
  There is no PE surface. **[SECONDARY]**
* **Microsoft's `Windows.Devices.Midi2.CapabilityInquiry` namespace contains
  exactly one type** — `MidiUniqueId`, a MUID formatter. Meanwhile the **UMP
  Stream** surface is fully built out: endpoint discovery, function blocks,
  direction and UI hints, stream configuration. **[PRIMARY — direct enumeration
  of the SDK reference tree.]** The contrast is the whole story: **the platform
  vendors are building §5.2, not §5.3.**

**Products:**

* **Korg Keystage** is the one unambiguous consumer success — Korg publishes a
  user-facing article on using PE to retrieve a connected device's CC parameters
  and their display names. **[PRIMARY]**
* **Yamaha Montage M** runs a "MIDI 2.0 for MONTAGE" campaign, while its own OS
  3.0 Data List reportedly states *"Profile Configuration Not Supported — Property
  Exchange Not Supported — Process Inquiry Not Supported."* Its "MIDI 2.0" means
  UMP / high-resolution transport only. **[SECONDARY]**
* **Roland A-88MKII** ships Piano Profile support labelled **"(Preview)"** by
  Roland itself. **[PRIMARY]**
* **Ableton Live, Bitwig, Reaper, Studio One, Pro Tools** — no evidence of PE.
* And the item that should give anyone pause: a documented **Cubase + A-88MKII
  interop bug** in which MIDI-CI enters a never-ending SysEx exchange and renders
  the keyboard unresponsive. Steinberg staff confirmed it (2025-11-17); **the
  official workaround is to disable MIDI-CI.** **[PRIMARY — vendor staff reply]**

**Open-source tooling is well ahead of the market** — JUCE's `juce_midi_ci`
(added 7.0.9, Oct 2023) implements full PE and Profiles; `ktmidi` and `cmidi2`
are comprehensive. The good implementations are **libraries and conformance
tools, not products.**

**Why it is thin:** Windows had no native MIDI 2.0 stack until 2026; the spec sat
frozen 2020–2024; PE is bidirectional, stateful and chunked (deadlocks, timeouts,
request-ID correlation, and zlib interop that a leading implementer says he
*"could not verify"*) against MIDI 1.0's fire-and-forget; real interop bugs exist
between flagship products; MPE over MIDI 1.0 already satisfies most power users;
and **vendors can brand UMP high-resolution transport as "MIDI 2.0" without doing
the PE work at all** — see the two compliance paths in §6.4.

### 5.5 Profiles — more published than commonly believed, none applicable here

**M2-102-U, *Common Rules for MIDI-CI Profiles*, v1.1, published 2023-06-15.**
Carried over MIDI-CI, sub-ID#2 range `0x20`–`0x2F`; a Profile ID is 5 bytes.
**[PRIMARY]**

The published set is **larger than the Feb 2026 summary article suggests** —
correcting an impression I initially formed from that article alone
**[PRIMARY, cover pages read directly]**:

| document | profile | version | published |
|---|---|---|---|
| M2-113-UM | Default Control Change Mapping | 1.0 | 2020-11-26 |
| M2-118-UM | **General MIDI 2 — Function Block** | 1.0.0 | 2024-01-24 |
| M2-119-UM | **General MIDI 2 — Single Channel** | 1.0.0 | ~2024-01 |
| M2-120-UM | **MIDI Polyphonic Expression (MPE)** | 2.0.3 | 2024-02-16 |
| M2-121-UM | **Drawbar Organs (Single Channel)** | 1.0.2 | ~2024-04 |
| M2-122-UM | Rotary Speaker | 1.0.2 | ~2024-04 |
| M2-123-UM | Orchestral Articulation | 1.0 | 2024-04-05 |
| M2-125-UM | Default Drum Note Map | 1.0 | 2025-01-31 |
| M2-126-UM | Piano (+ M2-126-IG guide) | 1.0 | date **unknown** |

**Camera Control does not exist as a specification** — it is a working group with
no document number, an announced intention only. Also unpublished: the Drum
Performance Profile (targeted Q2 2026) and the DAW Control Profiles.

Note the timeline: one Profile in 2020, **a three-year gap**, then six around
NAMM 2024, then Drum Note Map and Piano.

**There is still no Profile applicable to an analog polysynth.** The nearest
neighbours — Drawbar Organs, MPE — describe instruments this one is not. The
conclusion in §8.5 is therefore unchanged, but the honest reason is "no matching
Profile exists", not "Profiles barely exist".

---

## 6. DIN / 5-pin transport

**Confirmed: MIDI 2.0 / UMP defines no transport over classic 5-pin DIN at
31.25 kbaud. None exists. DIN remains MIDI 1.0.**

### 6.1 The decisive citation

The UMP specification said so explicitly, in as many words. **M2-104-UM v1.0
(2020-02-20)**, in the terminology entry for "Non-UMP MIDI 1.0 System", records
that there is **no plan** to use the UMP Format on the 5-pin DIN transport, and
that unless that changes:

> 5-pin DIN will only support the MIDI 1.0 byte stream data format

**[PRIMARY]**

That note was dropped when the spec was revised, but the position was not
softened — it was replaced by structural provisions saying the same thing more
thoroughly. In **v1.1.2** **[PRIMARY]**:

* **§1.3** — UMP is a *transport-independent payload format*, and MMA/AMEI expect
  **a separate specification to exist for every standardized transport** carrying
  UMP. The illustrative list is USB, UDP, Bluetooth, Wi-Fi. Serial/DIN is absent.
* **§2.1.1** — converting UMP words to a byte stream, **including byte order, is
  explicitly out of scope** and delegated to transport specs. So "just send UMP
  bytes down a UART" is not merely unspecified; it is undefined by construction.
* **§6.2** — a DIN port is **proxied into the UMP stream as a Function Block**,
  with a MIDI 1.0 ↔ MIDI 2.0 translator inside the device. The UMP representation
  exists in the device and the host; **the DIN wire still carries a MIDI 1.0 byte
  stream.**
* The **Function Block Info "MIDI 1.0" field** encodes `0x02` = *yes, restrict
  bandwidth to 31.25 kbps*, and a MIDI 1.0 Function Block shall span exactly one
  Group. DIN is modelled as a bandwidth-limited MIDI 1.0 port **inside** UMP,
  never as a UMP carrier.

### 6.2 Three independent negative checks

1. **A machine grep across the full text of all 24 MIDI 2.0 family PDFs plus the
   USB MIDI 2.0 spec**, for `5[ -]?pin`, `\bDIN\b`, `baud` and `UART`, returns
   **exactly two hits** — both describing DIN as a MIDI 1.0 construct (the v1.0
   "no plan" note and v1.1.2 §6.2). **Zero hits for "baud" or "UART" anywhere in
   the family.** **[PRIMARY]**
2. **AMEI's own download page groups exactly two documents under 「トランスポート
   仕様」 (Transport Specifications):** Network MIDI 2.0 (UDP) and USB MIDI 2.0.
   That is the standards body's own transport register, and it is **a closed list
   of two.** **[PRIMARY]**
3. **M2-124-UM's normative references** — the newest transport spec, listing the
   whole family it depends on — cite M2-100-U, M2-101-UM, M2-102-U, M2-103-UM,
   M2-104-UM and the two USB-IF class specs. **No serial or DIN transport document
   appears.** **[PRIMARY]**

Supporting: every midi.org post matching "transport" (30 results, 2023-06 →
2026-07) was scanned, and no serial/DIN transport announcement exists. The
Transport Working Group's NAMM 2026 session (2026-01-23) covers BLE, Web MIDI and
Network remote management — DIN is not on the agenda. And
`midi.org/5-pin-din-electrical-specs` serves **CA-033, "MIDI 1.0 Electrical
Specification Update [2014]"**, filed under *Addenda*: **the DIN electrical spec
was last touched in 2014**, for 3.3 V signalling and ferrite beads. MIDI 2.0 has
never touched it. **[PRIMARY]**

**Vendor and hobbyist survey: negative.** No project claiming UMP over
31.25 kbaud DIN was found. Everything that surfaced — ESP32_Host_MIDI, midi2.diy,
Zynthian, AmeNote's `tusb_ump`, the midi2-dev libraries, Adafruit's portable UMP
library — runs UMP over USB and/or UDP while keeping classic 31250-baud DIN as a
**separate MIDI 1.0 path**, exactly the architecture M2-104-UM §6.2 describes (§6.1 above). Exhaustiveness
**[UNVERIFIED]**; anything you do encounter would be non-standard by definition,
since there is no specification for it to conform to.

### 6.3 The adopted transport register, complete

| transport | document | version | date | status |
|---|---|---|---|---|
| **USB** | USB-IF, *Device Class Definition for MIDI Devices* | Release 2.0 | 2020-05-05 | **adopted** |
| **Network (UDP)** | **M2-124-UM** | 1.0 / 1.0.1 | published 2024-11-20 | **adopted** |
| Bluetooth LE (UMP) | — | — | — | **in development, not adopted** |
| Web MIDI 2.0 | — | — | — | not adopted; MA wants W3C to take it up |
| **Serial / 5-pin DIN** | **none** | — | — | **does not exist** |

**[PRIMARY]** BLE's document number and target date are **unknown**.

**Do not confuse the two Bluetooth things.** *BLE-MIDI*, "MIDI over Bluetooth Low
Energy", is an existing **MIDI 1.0** transport listed under MIDI 1.0 transports.
*BLE MIDI 2.0* — UMP over BLE — is the unadopted one.

**Why this is unlikely to change**, stated as reasoning rather than fact: DIN
runs at 31 250 baud. A single MIDI 2.0 Channel Voice message is 64 bits, versus
16–24 bits for its MIDI 1.0 equivalent — before any UMP Stream or Jitter
Reduction overhead. UMP over DIN would be several times slower than MIDI 1.0 over
DIN for the same musical content. **[INFERRED]** — from the packet sizes in §8.1
and the DIN baud rate.

### 6.4 What *does* exist over DIN — and why it is routinely misread

MIDI-CI — including Profiles and Property Exchange — runs over MIDI 1.0
transports, DIN included, because MIDI-CI is carried in SysEx and SysEx runs over
DIN (§5.1). So a device really can negotiate Profiles over a DIN cable. **It is
still sending MIDI 1.0 Channel Voice messages.**

Three points of precision that matter:

**It needs two cables.** M2-101-UM §2.1 requires bidirectional MIDI
communications: every MIDI-CI-capable Input shall be paired with a matching
Output. In DIN terms that is device A Out → B In *and* B Out → A In. Appendix C
adds an operational warning: using **MIDI Thru ports or a MIDI merger with
MIDI-CI leaves behaviour undefined.** So the topology that works is a clean
In+Out pair between exactly two devices — not a Thru chain. **[PRIMARY]**

**Protocol upgrade over DIN was withdrawn, not merely unimplemented.** MIDI-CI
**Protocol Negotiation was deprecated in MIDI-CI v1.2 (2023)**, and the UMP v1.1
changelog records it as replaced by **UMP Stream Configuration messages** — which
are themselves UMP messages (§5.2). The one mechanism that could ever have
negotiated a MIDI 1.0 link *up* to the MIDI 2.0 protocol has been removed, and
its replacement cannot travel over DIN. **[PRIMARY]**

**And this is how a device can honestly advertise "MIDI 2.0" while carrying no
UMP at all.** M2-100-U §5, *Minimum Compatibility Requirements*, allows a device
to claim MIDI 2.0 compatibility by implementing **either**:

* **(A)** MIDI-CI plus at least one of Profiles / Property Exchange / Process
  Inquiry — **achievable over 5-pin DIN**; or
* **(B)** the UMP data format plus at least one MIDI 2.0 feature.

**[PRIMARY]** So a synth advertising "MIDI 2.0" on a DIN-only product may be
claiming path A. That is legitimate and it is *not* high-resolution MIDI. When
evaluating anyone's MIDI 2.0 claim — including one you might make yourself — ask
which path.

Do not let "MIDI 2.0 features over DIN" (true, of MIDI-CI) be heard as "MIDI 2.0
protocol over DIN" (false).

### 6.5 The backward-compatibility position, stated properly

MIDI 2.0 does not replace MIDI 1.0, and the DIN transport is unchanged. The
modern (UMP v1.1+) framing is not merely "DIN is left alone" but: **a DIN port is
represented inside the UMP world as a MIDI 1.0 Function Block, bandwidth-flagged
to 31.25 kbps, spanning exactly one Group, with a translator between MIDI 1.0 and
MIDI 2.0 messages.** The abstraction reaches down to the DIN jack; the UMP bytes
never do.

**Why this is unlikely to change**, as reasoning rather than fact: DIN runs at
31 250 baud. A MIDI 2.0 Channel Voice message is 64 bits against 16–24 for its
MIDI 1.0 equivalent, before UMP Stream or Jitter Reduction overhead. UMP over DIN
would be several times *slower* than MIDI 1.0 over DIN for the same musical
content. **[INFERRED]**

---

## 7. USB MIDI 2.0 descriptors

Included for completeness and because it is the sharpest available contrast with
§9: the network transport needs no descriptor work at all, whereas USB needs a
firmware change. This section is sourced primarily from the **Linux kernel's USB
MIDI 2.0 implementation** — `include/linux/usb/midi-v2.h` and `sound/usb/midi2.c`
— which is a working, shipping consumer of the descriptors and therefore
authoritative about what a host actually looks for. **[PRIMARY]**

### 7.0 The governing document

| field | value |
|---|---|
| Title | **Universal Serial Bus Device Class Definition for MIDI Devices** |
| Release | **2.0** |
| Date | **2020-05-05** (posted to the usb.org library 2020-06-22) |
| Publisher | **USB Implementers Forum** — © 1996–2020 USB-IF |
| Predecessor | Release 1.0, 1999-11-01 |
| Errata | **none** — the usb.org library holds exactly two MIDI class documents, `midi10.pdf` and `USB MIDI v2_0.pdf`, with no ECN rollup |

**[PRIMARY]** — read from the specification PDF at usb.org.

**Who owns it matters:** this is a **USB-IF** document, not a MIDI Association
one, though it was co-developed inside a USB-IF working group staffed by MMA/AMEI
member companies (Roland — Mike Kent as project chair — Yamaha, Apple, Native
Instruments, Knowles). The Network MIDI 2.0 spec cites it as an *external*
reference. So the MIDI 2.0 transport family has two different standards bodies
behind it, which is why the documents look and are numbered so differently.

**Release 2.0 is explicitly not backward compatible with Release 1.0.** That
incompatibility is exactly what forces the alternate-setting mechanism in §7.2.

Section numbers below are from that document, as cited in the kernel headers.

### 7.1 The version field — one 16-bit number

The Class-Specific MS Interface Header Descriptor (Table 5-2, **7 bytes**)
carries a revision field, **`bcdMSC`** — the MIDIStreaming SubClass Specification
Release Number, in BCD:

| offset | field | size | value |
|---|---|---|---|
| 0 | `bLength` | 1 | 7 |
| 1 | `bDescriptorType` | 1 | `CS_INTERFACE` = `0x24` |
| 2 | `bDescriptorSubtype` | 1 | `MS_HEADER` = `0x01` |
| 3 | **`bcdMSC`** | 2 | **`0x0100`** MIDI 1.0 / **`0x0200`** MIDI 2.0 |
| 5 | `wTotalLength` | 2 | `7` in MIDI 2.0 — vestigial |

**[PRIMARY]** — spec Table 5-2 and Appendix A.4, which names the constants
`MS_MIDI_1_0` and `MS_MIDI_2_0`; independently mirrored in the kernel as
`USB_MS_REV_MIDI_1_0` / `USB_MS_REV_MIDI_2_0`.

`wTotalLength` is load-bearing in MIDI 1.0, where it covers the concatenated
jack and element descriptors. In MIDI 2.0 it is set equal to `bLength` and means
nothing, **because the jacks are gone and the Group Terminal Blocks live outside
the configuration descriptor entirely** (§7.3).

The kernel's entire MIDI 2.0 detection test **[PRIMARY]** — `midi2.c:1027`:

```c
return le16_to_cpu(ms_header->bcdMSC) == USB_MS_REV_MIDI_2_0;
```

guarded by checks that the descriptor is `USB_DT_CS_INTERFACE`, subtype
`UAC_HEADER`, and at least 7 bytes long.

### 7.2 Alternate settings — MIDI 1.0 and MIDI 2.0 coexist on one interface

A USB MIDI 2.0 device presents **two alternate settings** on a single
MIDIStreaming interface (`bInterfaceClass` `0x01` AUDIO, `bInterfaceSubClass`
`0x03` MIDISTREAMING), distinguished only by `bAlternateSetting`:

* **Alternate setting 0** — MIDI 1.0, `bcdMSC` = `0x0100`. Legacy hosts see only
  this and work unchanged.
* **Alternate setting 1** — MIDI 2.0, `bcdMSC` = `0x0200`.
* **Alternate setting 2+** — *may* carry further MIDI 2.0 settings, e.g. bulk vs
  interrupt endpoint variants or different bandwidths.

**Correction to the common assumption: providing these is "should", not
"shall".** **[PRIMARY]** The spec uses *should* — defined in its Table 1-1 as
"recommended but not mandatory" — for providing each alternate setting. A device
is conformant without a MIDI 1.0 alt setting. What *is* mandatory is that **if**
you provide them, `bcdMSC` **shall** be `0x0100` / `0x0200` respectively. Host
behaviour is explicitly out of scope; the spec imposes no rules on host software.

**In practice, hosts hard-code the convention anyway**, so treat alt 1 as
binding:

* Linux: the USB-audio driver uses the MIDI 2.0 interface *"that is found always
  at the altset 1"*, overridable with `midi2_enable=0`. The code is explicit
  **[PRIMARY]** — `midi2.c:1102-1112`: if `iface->num_altsetting < 2` it logs
  *"Quirk or no altset; falling back to MIDI 1.0"*; otherwise it takes
  `iface->altsetting[1]`, checks `bcdMSC == 0x0200`, and falls back again if that
  fails or if the altsetting has no endpoints.
* Zephyr's device-side stack defines `MIDI1_ALTERNATE 0x00` / `MIDI2_ALTERNATE
  0x01`. **[PRIMARY]**

This is why USB MIDI 2.0 is backward compatible at all — and why it cannot be
retrofitted by a setting. The host **chooses** an alternate setting during
enumeration, from a menu the device presents in its descriptors.

### 7.3 Group Terminal Blocks — and they are fetched separately

Group Terminal Blocks (GTBs) describe how the device's UMP **Groups** map onto
physical or logical ports. They are the MIDI 2.0 analogue of MIDI 1.0's Embedded
Jacks and Elements, though not a one-for-one replacement.

**The detail that surprises people: GTB descriptors are not in the configuration
descriptor.** They are retrieved by a **separate control transfer** — a standard
`GET_DESCRIPTOR` request directed at the interface, with a class-specific
descriptor type `0x26` (`USB_DT_CS_GR_TRM_BLOCK`). **[PRIMARY]** —
`midi2.c:528-551`. The kernel does it in two steps: fetch the 5-byte header to
learn `wTotalLength`, then fetch the whole block.

```
bmRequestType = 0x81  = USB_DIR_IN | USB_TYPE_STANDARD | USB_RECIP_INTERFACE
bRequest      = 0x06  = GET_DESCRIPTOR
wValue        = (0x26 << 8) | bAlternateSetting     // typically 0x2601
wIndex        = bInterfaceNumber
wLength       = 0x05 first, then wTotalLength
```

**Implementer's trap:** despite the spec presenting this in a section on
*class-specific* commands, `bmRequestType` is **Standard, not Class**. This is
got wrong routinely. The Linux driver matches the spec exactly. **[PRIMARY]**

Putting the alternate setting in the low byte of `wValue` is deliberate: it lets
different alternate settings advertise **different bandwidths**.

Each **Group Terminal Block Descriptor** is 13 bytes **[PRIMARY]** —
`midi-v2.h`:

| field | meaning |
|---|---|
| `bGrpTrmBlkID` | id of this block |
| `bGrpTrmBlkType` | `0x00` bidirectional, `0x01` input only, `0x02` output only |
| `nGroupTrm` | first member Group |
| `nNumGroupTrm` | number of Groups spanned |
| `iBlockItem` | **string descriptor id** — the block's user-visible name |
| `bMIDIProtocol` | default protocol (below) |
| `wMaxInputBandwidth` | max input bandwidth, in units of 4 kB/s |
| `wMaxOutputBandwidth` | max output bandwidth, in units of 4 kB/s |

`bMIDIProtocol` values **[PRIMARY]**:

| value | meaning |
|---|---|
| `0x00` | unknown — *use MIDI-CI to negotiate* |
| `0x01` / `0x02` | MIDI 1.0, UMP up to 64 bits (`_JRTS` = with Jitter Reduction Timestamps) |
| `0x03` / `0x04` | MIDI 1.0, UMP up to 128 bits (± JRTS) |
| `0x11` / `0x12` | **MIDI 2.0** (± JRTS) |

Note `0x00`: the USB transport can decline to state a protocol and defer to
MIDI-CI — which is SysEx (§5.1). Declaring `0x11` avoids that dependency.

Two further semantics **[PRIMARY]**: `bGrpTrmBlkID` `0x00` is reserved, so a
device may declare at most **255** blocks; and for a *bidirectional* block
`nNumGroupTrm` counts **Group Terminal Numbers**, so the actual terminal count is
**twice** that value — each number carries a paired IN and OUT. `0x0001` in the
bandwidth fields is the encoding for roughly **31.25 kb/s**, i.e. how a USB
interface describes the classic DIN gear hanging off it so that host software can
pace itself. That is a *hint about downstream MIDI 1.0 hardware*, not a DIN
transport — see §6.

### 7.4 Endpoints and what is on the wire

**Transfer type.** MIDI 1.0 was **bulk only**. MIDI 2.0 permits **bulk *or*
interrupt**, added for deterministic jitter and throughput. **[PRIMARY]**

**The standard endpoint descriptor shrank** from 9 bytes to **7** — `bRefresh`
and `bSynchAddress` were removed. **[PRIMARY]**

The class-specific **MS Data Endpoint Descriptor** changes subtype from
`MS_GENERAL` (`0x01`) to **`MS_GENERAL_2_0` (`0x02`)** and swaps its payload from
`bNumEmbMIDIJack` + `baAssocJackID[]` to `bNumGrpTrmBlock` +
`baAssoGrpTrmBlkID[]`, associating the endpoint with its Group Terminal Blocks.
At most one IN and one OUT endpoint may associate with a given block — both
sharing one block is exactly how a MIDI-CI IN/OUT pair is expressed. **[PRIMARY]**
— `midi-v2.h`, spec §5.3.2.

**A myth worth killing: MIDI 2.0 mandates no particular `wMaxPacketSize`.**
**[PRIMARY]** Table 5-3 leaves it as the ordinary USB field with no class-imposed
value or constraint — not even "a multiple of 4". The spec's own Appendix B
example uses 64 bytes at full speed on **both** alternate settings, and Zephyr
uses 64 (full-speed) / 512 (high-speed), again identical across both. **Packet
size tracks the USB speed, not the MIDI version.**

The payload changes fundamentally:

* **MIDI 1.0**: 4-byte *USB-MIDI Event Packets*, each with a Cable Number and a
  Code Index Number nibble, wrapping 1–3 MIDI bytes.
* **MIDI 2.0**: **raw Universal MIDI Packets** — 32-bit words, 1 to 4 of them per
  message depending on Message Type (§9.1).

**Endianness, and the reason it is a trap.** USB MIDI 2.0 §3.2.2: each 32-bit UMP
word is transmitted **least-significant byte first**, and for multi-word packets
**word order is retained**. A full UMP should be kept within a single transaction
where possible. **[PRIMARY]**

Critically, **this is a USB rule, not a UMP rule.** M2-104-UM §2.1.1 declares byte
order explicitly **out of scope** and delegates it to each transport
specification (§6.1). So you **cannot** assume the Network transport matches USB:
an implementer must read M2-124-UM's own byte-order clause. I did not verify it
— **unknown**. The Linux kernel's approach is instructive: it keeps UMP words in
CPU-native endianness internally and converts in the *transport* driver.

**USB Audio Class dependency.** MIDI is a subclass of the Audio Interface Class
(`bInterfaceClass` `0x01` AUDIO, `bInterfaceSubClass` `0x03` MIDISTREAMING), and
the spec is blunt that this survives **only for legacy compatibility**.
Section 5.1 makes the AudioControl interface **conditional**: *if* the device
contains a USB MIDI 1.0 alternate setting, it **shall** also include Standard and
Class-Specific AC Interface Descriptors. Since alt 0 is only "should" (§7.2), a
pure MIDI-2.0-only device is in principle conformant with no AC interface —
though I found no real implementation doing that. **No UAC version is mandated**;
the spec's own Appendix B example and Zephyr both emit `bcdADC` = `0x0100`
(Audio Class 1.0). **Whether UAC 2.0/3.0 is permitted or tested: unknown.**
The USB MIDI 2.0 spec never mentions Interface Association Descriptors, though
midi.org's implementation guidance recommends one. **[PRIMARY / SECONDARY]**

### 7.5 Why this is firmware, not configuration

Every item above — `bcdMSC`, the second alternate setting, the GTB descriptors
and the control-request handler that serves them, the endpoint descriptor
subtype, and the UMP-vs-event-packet framing on the bulk endpoints — is **returned
by the device during enumeration, before any application code on either side
runs.** Descriptors are compiled into the device's USB stack. The GTB fetch is a
*control request the device firmware must answer*; there is no filesystem, no
configuration file, and no host-side override involved.

There is no host-side setting, driver flag, or firmware-adjacent config that can
add an alternate setting to a device that does not declare one. **A device that
enumerates as MIDI 1.0 is MIDI 1.0 until its firmware is rebuilt** — which for
this instrument means rebuilding a signed, encrypted XMOS image, per
`midi-stack.md` §9.

**This is precisely the constraint that the network transport routes around.**

---

## 8. The honest comparison

The framing: an instrument whose control parameters are already reachable as
32-bit floats over OSC on Ethernet, and whose control voltages are generated by
24-bit DACs. What does MIDI 2.0 actually add?

The useful distinction is **capability** — the instrument can do something it
could not do before — versus **interoperability** — other people's gear and
software work with it without anyone writing custom code. They are not the same
thing, and conflating them is how MIDI 2.0 gets oversold.

### 8.1 What MIDI 2.0 actually specifies

All **[PRIMARY]** — M2-104-UM, *UMP Format & MIDI 2.0 Protocol*, current revision
**v1.1.2, published 2023-11-10**. Every MIDI 2.0 Channel Voice message is 64 bits:
4-bit Message Type `0x4`, 4-bit Group, 8-bit Status, **16-bit Index, 32-bit
Data**.

| feature | MIDI 1.0 | MIDI 2.0 |
|---|---|---|
| Note On/Off velocity | 7 bits | **16 bits** |
| Note On/Off attribute | — | 8-bit attribute *type* + **16-bit** attribute *value* |
| Control Change | 7 bits | **32 bits** |
| Poly Pressure | 7 bits | **32 bits** |
| Channel Pressure | 7 bits | **32 bits** |
| Pitch Bend | 14 bits | **32 bits**, unsigned bipolar, centred `0x80000000` |
| RPN / NRPN ("Registered / Assignable Controllers") | 14-bit value, 4-message compound | **32-bit data in a single message**; **16,384 of each** (128 banks × 128) |
| Relative Registered / Assignable Controller | — | **32-bit two's complement**; *cannot* be translated to MIDI 1.0 |
| Per-Note Pitch Bend | — | **32 bits**, per note, centred `0x80000000` |
| Registered / Assignable **Per-Note** Controllers | — | **256 registered + 256 assignable per note**, 32-bit each |
| Per-Note Management | — | detach / reset per-note controllers |
| Program Change | PC + 2 bank-select CCs = 3 messages | **single message** with a Bank Valid bit |
| Addressing | 16 channels | **16 Groups × 16 Channels = 256** |
| Endpoint structure | — | up to **32 Function Blocks** |

Note-On Attribute types: `0x00` none, `0x01` manufacturer specific, `0x02`
**profile specific**, `0x03` **Pitch 7.9** — a Q7.9 fixed-point pitch giving
1/512 semitone ≈ **0.2 cents**. A companion Registered Per-Note Controller #3
carries Pitch 7.25, of which *"at least 9 bits should be supported"*.

One constraint worth knowing: **MT `0x4` and MT `0x2` must not be mixed within
the same Group.** A Group is either running the MIDI 1.0 protocol or the MIDI 2.0
protocol, not both. **[PRIMARY]**

The Association's own summary: *"over 32,000 controllers, including controls for
individual notes. Enhanced, 32-bit resolution gives controls a smooth,
continuous, 'analog' feel."* **[PRIMARY]**

### 8.2 32-bit resolution — no capability win, and it is not close

The instrument's DACs are 24-bit. A 32-bit float carries a 24-bit mantissa. So
the existing OSC `/p` float path **already saturates the converters**; MIDI 2.0's
extra 8 bits would be discarded at the DAC. This is argued in
`docs/arch/midi-stack.md` §7.1 and I have nothing to add except that the research
confirms the MIDI 2.0 side of the comparison exactly: CC really is 32-bit, and it
really would be truncated.

**Capability win: none.** Strictly negative, in fact — you would be adding a
quantisation step that does not currently exist.

**Interoperability win: real, and it is the whole point.** A DAW cannot send OSC
floats to an arbitrary synth. It can send MIDI CC. Today a user who wants
better-than-7-bit control must either use the 14-bit NRPN map (which exists —
`midi-stack.md` §4.2, 120 parameters) or write OSC tooling themselves. The value
of MIDI 2.0 here is not more bits; it is **that the bits arrive through a socket
every piece of music software already has.**

That said, be honest about the size of the gap being closed: 14-bit NRPN gives
16 384 steps and already works today from any sequencer. The audible difference
between 16 384 steps and 16.7 million steps on a filter cutoff is, for most
parameters, nothing. The real complaint 7-bit CC generates — zipper noise — is
already solved by the existing NRPN path.

### 8.3 Per-note controllers — a genuine capability gap, but not one MIDI 2.0 fills

This is where MIDI 2.0 offers something the OSC tree does not: per-note pitch
bend, per-note controllers, and per-note management, all addressed to a specific
note rather than a channel.

But the instrument cannot use them. Its expression model is **three timbres on
three MIDI channels sharing a voice pool** — MPE-shaped, not MPE. There is no
per-note pressure and no per-note pitch bend in the voice engine, and the
allocator has no per-note controller concept to route such messages to
(`midi-stack.md` §7.2).

**Capability win: none, without voice-engine changes that live in the XMOS
firmware — which is encrypted and signed.** MIDI 2.0 would deliver per-note
messages that the instrument would then have to discard.

Worth stating plainly because it is the most oversold item in the MIDI 2.0
pitch: **per-note control is a synth-architecture feature, not a transport
feature.** A transport that can express it does not create it.

### 8.4 Property Exchange — the one real gap, and it is blocked

A standard, machine-readable way for a device to tell a host what its parameters
are is the one thing MIDI 2.0 offers that the instrument genuinely lacks in
standardised form. See §5 for the detail.

Two findings sharpen this considerably:

1. **Property Exchange runs on MIDI-CI, which runs on SysEx** (§5). The
   instrument has **no SysEx implementation at all** — confirmed in
   `midi-stack.md` §4.4, where the strings `SYSEX`, `SysEx` and `System
   Exclusive` occur **zero** times in the 145 MB frontend binary and the only
   trace is an orphaned `sysex_device_id` setting with no UI. So Property
   Exchange is not merely unimplemented on this instrument; it is **structurally
   unavailable** without building a SysEx stack that does not exist.
2. **What the instrument already has is richer.** The OSC `/p` tree is ~35 000
   concrete addresses collapsing to ~3 000 families (`xmos-firmware.md`). Property
   Exchange's `AllCtrlList`/`ChCtrlList` would describe *less*, in a format more
   tools understand.

**Capability win: none — negative, on information content.**
**Interoperability win: real, and the largest of the four.** "The DAW draws a
control surface for this synth automatically" is a thing users want. But see §5
for how thin actual host support for Property Exchange is; this is the item most
likely to be a standard nobody consumes.

### 8.5 Profiles — not applicable

Profiles let a device declare "I behave as a drawbar organ" so a controller can
map itself sensibly. **Nine are published** — more than the summary coverage
suggests — including General MIDI 2 (two variants), MPE, Drawbar Organs, Rotary
Speaker, Orchestral Articulation, Default Drum Note Map and Piano. The full table
with dates is in §5.5.

**But there is no analog-polysynth Profile**, and the nearest neighbours describe
instruments this one is not. Nothing in the published set fits. And Profiles are
negotiated over MIDI-CI, hence over SysEx (§5.1) — the same structural blocker as
Property Exchange.

**Capability win: none. Interoperability win: none today** — not because Profiles
are vapour, but because none of the nine describes this instrument.

### 8.6 The summary judgement

| MIDI 2.0 feature | capability win | interoperability win |
|---|---|---|
| 32-bit resolution | **none** (24-bit DACs; OSC float already saturates them) | **real** — every DAW speaks it; no custom tooling |
| Per-note controllers | **none** (voice engine has no per-note concept) | none — nothing to interoperate about |
| Property Exchange | **none** (OSC tree is richer) | **real but thin** — and blocked by no-SysEx |
| Profiles | none | none — no applicable Profile exists |
| **Network transport itself** | **none** | **real — and this is the one that is actually reachable** |

**The honest position: MIDI 2.0 adds no capability to this instrument.
Everything it offers, the instrument either already does better or cannot use.
What it adds is interoperability — and interoperability is a real thing to want,
not a consolation prize.** A user with a MIDI 2.0 DAW should not have to write
OSC tooling to get high-resolution control of a synth sitting on the same
Ethernet segment.

The critical observation, and the reason this document exists: **of the five rows
above, the last one is the only one that does not require touching the XMOS
firmware.** The network transport is pure interoperability, needs no new
instrument capability, and — unlike USB — is not gated on a signed binary. That
makes it the only row worth acting on.

---

## 9. If you wanted to make an existing MIDI-1.0-only instrument appear as a MIDI 2.0 device on a network

### 9.1 The minimum you would have to build

**A userspace UDP daemon and one mDNS service record.** That is the whole
mandatory surface. Specifically:

1. **An mDNS/DNS-SD advertisement** of `_midi2._udp` with a PTR, an SRV (any free
   port), and a TXT carrying `UMPEndpointName` and `ProductInstanceId` (§3.1).
2. **A UDP socket** implementing the Host side of the session protocol: accept
   `0x01 Invitation`, reply `0x10 Accepted`, handle `0x20 Ping` / `0xF0 Bye`,
   and send/receive `0xFF UMP Data` with a sequence number (§1.4). Authentication
   is optional and should be omitted (§3.3). Retransmit and FEC are optional; on
   wired Ethernet you can ship without them and add FEC later.
3. **A UMP codec.** For a MIDI-1.0-only instrument this is small: emit and parse
   Message Type `0x2` (MIDI 1.0 Channel Voice in UMP) — 32 bits per message, a
   nearly mechanical repacking of existing MIDI 1.0 bytes. Message Type `0x4` is
   only needed if you want to *offer* MIDI 2.0 resolution, and the two must not
   be mixed within one Group (§8.1). Be precise about the claim this implies: a
   device emitting MT `0x2` is a **UMP endpoint running the MIDI 1.0 protocol**,
   which is a defined and legitimate configuration — not a MIDI 2.0 Protocol
   device.
4. **UMP Stream messages, Message Type `0xF`** — and this is the part people
   miss. Endpoint Discovery, Endpoint Info Notification, Endpoint Name
   Notification, Product Instance Id Notification, Function Block
   Discovery/Info/Name, and Stream Configuration Request/Notification are
   **native 128-bit UMP messages, not SysEx.** **[PRIMARY]** — M2-104-UM v1.1.1
   §7.1. A device with **no SysEx implementation whatsoever** can still identify
   itself properly, name its ports, and negotiate protocol. This is what makes
   the whole idea viable for an instrument that has no SysEx stack (§8.4).

**What you do *not* need:** any kernel support (§2.4), any USB stack, any change
to USB descriptors (§7), any SysEx implementation, MIDI-CI, Property Exchange, or
any MIDI 2.0 Channel Voice message at all. A Network MIDI 2.0 Host that only ever
emits MT `0x2` MIDI 1.0 packets is legitimate, not a fudge — the transport is
explicitly specified to carry both protocols (§1.2).

**And the specification says so directly.** M2-100-U §5's *Minimum Compatibility
Requirements* offer **path B**: the UMP data format including UMP Endpoint
discovery, plus one MIDI 2.0 feature — **with no MIDI-CI and therefore no SysEx
anywhere** (§5.2). A device built exactly as described above is a compliant MIDI
2.0 device by the standard's own definition, not by a generous reading of it.
That is worth stating plainly because the instinct, on learning the instrument
has no SysEx, is to assume MIDI 2.0 is closed off. It is not; only the MIDI-CI
half is.

Realistically: **a few hundred lines for the session protocol, plus an mDNS
dependency and a UMP codec.** The 16-command protocol in §1.4 is the entire wire
format. See §4 for what can be reused rather than written.

### 9.2 On this instrument specifically

The existing analysis (`midi-stack.md` §9) concludes "possible on the host side
only", and for **USB** that is correct and unchanged. But it was reasoning about
USB, and the network transport changes the arithmetic. Four facts from
`docs/arch/` line up unusually well:

| requirement | already present? | evidence |
|---|---|---|
| A LAN IP address on the Linux board | **yes** — `ethext` 192.168.1.136 via DHCP | `control-plane.md:162` |
| An mDNS responder | **yes** — `avahi-daemon` already advertises `moog-one.local` | `control-plane.md:33`, `system-and-failure-modes.md:386` |
| A way to reach the parameters | **yes** — OSC `/p` tree, plus DNAT for 7770/7771/9100/9300 | `control-plane.md:164-174` |
| A way to reach note/CC events | **yes** — the OSC performance stream on `usbint` | `midi-stack.md` §1.4 |

So the daemon would run on the **i.MX6**, not the XMOS, and would translate
between UMP on the LAN and OSC on `usbint`. **No XMOS firmware change. No kernel
change** — the 4.1.15-rt18 kernel's lack of `snd-ump` does not matter, because
nothing here needs ALSA; it is a UDP socket and an Avahi service file.

The advertisement in §3.1 maps onto Avahi's static service files directly — a
file dropped in `/etc/avahi/services/` with the service type and the two required
TXT keys, which avahi-daemon then publishes with no code at all:

```xml
<service-group>
  <name replace-wildcards="yes">Moog One</name>
  <service>
    <type>_midi2._udp</type>
    <port>5673</port>
    <txt-record>UMPEndpointName=Moog One</txt-record>
    <txt-record>ProductInstanceId=...</txt-record>
  </service>
</service-group>
```

**[INFERRED]** — the *content* is [PRIMARY] from §3.1; that Avahi's static service
file format accepts an arbitrary service type and TXT records is standard Avahi
behaviour but **I have not tested it on this instrument's Avahi build**, and the
version there is unexamined. Treat the XML as illustrative of the shape, not as a
tested artefact. The alternative is Avahi's D-Bus API — `dbus-daemon` is also
already running (`control-plane.md:33`).

**Caveats I will not paper over:**

* `midi-stack.md` §1.5 flags that the **CC opcode on port 7772 was never
  captured**. Note on/off is decoded; controller input is not. Inbound CC → OSC
  is therefore **unverified**, and it is the same open question that document
  already names. Settle it with the passive tcpdump listed there as option 6
  before committing to a design.
* Cross-compiling for armv7/i.MX6 against whatever libc the v1.5.0 rootfs
  carries is unexamined here. **unknown.**
* Adding a daemon to the boot sequence means editing init scripts, which
  `system-and-failure-modes.md` treats as a real risk surface. A **sidecar on a
  Raspberry Pi on the same LAN** achieves the identical user-visible result with
  zero instrument modification, and is the honest first move. The instrument
  would be reached over OSC exactly as it is today.

The correct framing: this is **not** an alternative to `midi-stack.md`'s
host-side bridge recommendation (option 4). It is the *same idea, relocated* —
and relocating it off the Mac is what buys the interoperability, because the
endpoint then appears to **every** machine on the network rather than only to the
one Mac running the bridge.

### 9.3 What a user on a Mac would see

**[PRIMARY]** — §2.1, §3.1:

1. Audio MIDI Setup → Window → Show MIDI Studio → **Configure Network Driver**.
2. The instrument appears in the directory of discovered network devices, listed
   by its `UMPEndpointName` TXT value — so whatever string you put there is what
   the user reads. Give it the instrument's name, not a hostname.
3. Click **Connect**. If the daemon implements open authentication, that is the
   entire interaction — no password, no pairing code.
4. The endpoint then appears **as an ordinary MIDI device throughout macOS** — in
   Logic, Ableton, Bitwig, anything using CoreMIDI. Not as a special "network
   MIDI 2.0" thing the user has to think about again.

Requires **macOS 26 (Tahoe)** (§2.1). On earlier macOS the device would be
invisible — there is no Network MIDI 2.0 client, and RTP-MIDI is a different
protocol that would not see it.

### 9.4 What a user on an iPad would see

**On present evidence: nothing.** See §2.2. CoreMIDI on iPadOS has UMP support,
but Apple's iOS/iPadOS 26.x release notes mention MIDI **zero** times while the
macOS 26.4 notes name Network MIDI 2.0 explicitly, and iOS has never had an Audio
MIDI Setup app — the very tool every Apple instruction for network MIDI routes
through.

**Do not plan an iPad-facing feature on this without testing it first.** If the
iPad is the actual target, that single test is the highest-value next step in
this entire document, and it costs an afternoon: stand up any existing Network
MIDI 2.0 host on the LAN (§4), and look at the iPad. That test also tells you
whether a third-party iOS app can bridge the gap, which is the likely fallback.

Note the asymmetry this creates. A **Mac** can be a Client and connect out to
your instrument-as-Host. If iPadOS has no Network MIDI 2.0 client at all, no
choice you make on the device side changes that — it is not a matter of picking
the right role or authentication mode.

### 9.5 And on Windows

Not until the Network MIDI 2.0 components ship in Windows 11 25H2, targeted from
**late November 2026** (§2.3). When they do: discovery via mDNS, optional
auto-connect, **no authentication support in the first release** — which is
another reason to implement open authentication — and the user will likely need
to add a **firewall rule** for `midisrv.exe`, which Microsoft documents separately
and which will be the first support question you receive.

---

## 10. Sources

Specifications (all read directly; the AMEI mirror hosts free PDFs of documents
that are otherwise behind midi.org registration):

| document | title | current version | notes |
|---|---|---|---|
| **M2-124-UM** | Network MIDI 2.0 (UDP) Transport | **1.0.1** | v1.0 published 2024-11-20; **1.0.1 is login-gated, its date and changelog unknown** |
| **M2-104-UM** | UMP Format & MIDI 2.0 Protocol | **1.1.2**, published 2023-11-10 | I read v1.1.1 (2023-07-19) in full; the cited clauses are identical |
| **M2-101-UM** | MIDI Capability Inquiry (MIDI-CI) | **1.2.1**, updated 2025-12-18 | I read v1.2 (published 2023-06-15) in full |
| **M2-103-UM** | Common Rules for MIDI-CI Property Exchange | **1.2**, published 2024-11-20 | note: M2-124-UM's own reference list cites the stale v1.1 |
| **M2-102-U** | Common Rules for MIDI-CI Profiles | 1.1, published 2023-06-15 | |
| **M2-100-U** | MIDI 2.0 Specification Overview | 1.1, published 2023-06-15 | source of the Minimum Compatibility paths |
| **M2-117-UM** | Property Exchange Controller Resources | 1.0, published 2023-06-15 | `AllCtrlList` / `ChCtrlList` |
| USB-IF | Device Class Definition for MIDI Devices | Release 2.0, 2020-05-05 | published by USB-IF, not the MA |

Current core bundle: `MIDI_2-0_Core-Specifications_20251218.zip`.
RFC 6762 (mDNS) and RFC 6763 (DNS-SD) are referenced normatively by M2-124-UM.

**Where the free PDFs actually are**, since this is non-obvious and cost real
time: **midi.org gates every spec PDF behind "Login to Download"**; the AMEI
mirror is the only free primary route. Files live at
`amei-music.github.io/midi2.0-docs/amei-pdf/<name>.pdf` (25 documents) and at
`amei.or.jp/midistandardcommittee/MIDI2.0/MIDI2.0-DOCS/` (individual files
fetchable; directory listing 403). Two traps: `midi.org/specifications` is a
**404** — the working path is **`midi.org/specs`**; and the AMEI translation site
uses a path segment `M2-100-U_v1.1.3/` which is the *translation's* revision, not
a spec version. Do not cite "M2-100-U v1.1.3".

MIDI Association:

* `midi.org/network-midi-2-0` — spec landing page; current revision **v1.0.1**
* `midi.org/network-midi-2-0-udp-overview` — overview, latency figures,
  implementation list
* `midi.org/the-state-of-midi-2-0-…-update-feb-2026` — adopted transports,
  Profile status

Apple:

* `developer.apple.com/documentation/macos-release-notes/macos-26_4-release-notes`
  — **the Network MIDI 2.0 introduction**, issue 118728162
* iOS/iPadOS 26, 26.4, 26.5, 26.6 release notes — checked; zero MIDI mentions
* `support.apple.com/guide/audio-midi-setup/…/ams1012/` versions 3.5 / 3.6 / 3.7
  — the differential test in §2.1
* `developer.apple.com/documentation/coremidi/midi-networking` and
  `/updates/coremidi` — public API surface

Microsoft:

* `github.com/microsoft/MIDI/releases` — In-box Dev Preview 7, **2026-09-07**
* `microsoft.github.io/MIDI/` and `/kb/network-midi-firewall/`
* `blogs.windows.com/windowsexperience/2026/02/17/…` — GA announcement
  **[SECONDARY]**

Linux:

* `docs.kernel.org/sound/designs/midi-2.0.html` — checked for network references
* `kernelnewbies.org/Linux_6.5` — UMP/ALSA MIDI 2.0
* Phoronix / LWN 932437, 934414, 939185 — patch series reporting **[SECONDARY]**

Repository cross-references (not web sources): `docs/arch/midi-stack.md`,
`docs/arch/control-plane.md`, `docs/arch/system-and-failure-modes.md`,
`docs/arch/xmos-firmware.md`, `docs/arch/hardware-external.md`.
