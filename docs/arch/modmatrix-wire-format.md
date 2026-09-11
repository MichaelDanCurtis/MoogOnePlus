# The modulation matrix on the wire

Read on 2026-09-10 from the i.MX6↔XMOS link of this instrument, firmware
1.5.0. Everything marked `[READ]` here came off a packet capture; the few
remaining guesses are marked and kept separate.

This supersedes the `[INFERRED]` wire format in
`docs/PLAN-MoogOnePlus-app.md` §1, which was substantially right.

## How it was taken

`203.0.113.0/24` is a point-to-point link on `usbint`, a `cdc_ether` interface:
`203.0.113.1` is Linux, `203.0.113.2` is the voice controller. It carries no
LAN traffic, so it can be captured cleanly — but it is *busy*, and that is why
three earlier attempts drowned. At rest it streams the entire front-panel LED
state to the XMOS at roughly 100 Hz: `/lfoleds`, `/clkleds`, `/seqleds`,
`/lsleds`, all to port **9100**, plus a `/cb` heartbeat and `/therm` polling.

The filter that works is not a port match on the matrix, it is an exclusion:

```
tcpdump -i usbint -s 0 -n -w out.pcap \
  'udp and not port 9100 and udp[8:4] != 0x2f746865'
```

That is silent at rest — verified, 0 packets in 8 seconds — so anything it
catches is a consequence of what the operator just did. Excluding rather than
selecting also means the capture can *falsify* the expected address instead of
assuming it.

### Getting the file off the instrument

`scp` does not work here: the rootfs has no `/usr/libexec/sftp-server`, and this
busybox has no `base64`. The capture comes back as a hex dump instead --

```
ssh root@<instrument> 'od -An -tx1 -v /tmp/out.pcap' > out.hex
```

-- reassembled locally, with `md5sum` on both ends compared before anything is
decoded. There is also no `timeout`, no `ip`, and `tcpdump` is not on the
non-interactive `PATH`; it lives at `/usr/sbin/tcpdump`. A capture is bounded by
backgrounding it and killing the pid.

Four captures, in `captures/modmatrix-wire/`:

| file | action at the panel | result |
|---|---|---|
| `01-amount-sweep.pcap` | a row's amount dialled to 100% | 142 datagrams |
| `02-source-change.pcap` | source changed | 6 blobs, amount jitter only |
| `03-wheel-moved-negative-control.pcap` | **mod wheel moved, nothing edited** | **0 blobs** |
| `04-row-edited.pcap` | a row's source/ctl/transform changed | 9 blobs |

## The message

`[READ]` One OSC message per edit, UDP `203.0.113.1:38786 → 203.0.113.2:7770`:

```
2f 67 2f 31 2f 74 2f 65 2f 73 00 00   "/g/1/t/e/s" padded to 12
2c 62 00 00                           type tag ",b"  -- ONE BLOB
00 00 00 20                           blob length, 32, big-endian
<32 bytes>                            the matrix
```

The address is `/g/<synth>/t/e/s` with synth index **1**. It is assembled at
runtime from `(synth_index, "e/s")`, which is why grepping the firmware for it
finds nothing and why days of captures on port 9300 found nothing either: port
9300 was never the matrix's business.

## The slot

`[READ]` **Sixteen bytes per row**, in the same seven-tuple order the preset
file stores:

| offset | width | field |
|---|---|---|
| 0 | 1 | src id |
| 1 | 4 | src amount, float32 |
| 5 | 1 | ctl id |
| 6 | 4 | ctl amount, float32 |
| 10 | 1 | transform id |
| 11 | 4 | transform amount, float32 |
| 15 | 1 | dest id |

**The amounts are little-endian.** This is the one detail that will ruin a
writer. OSC is big-endian and the blob's own length prefix obeys that, so a
single packet carries both byte orders — big-endian framing wrapped around a
little-endian payload. Read the wrong way, a coefficient of `1.0` becomes
`4.6e-41`: a denormal, not a parse error. The mistake is audible before it is
visible.

`[READ]` Unused rows are transmitted, not omitted, filled with the sentinels
already in `tables.go` — `src 48`, `transform 43`, `dest 141`. An empty row on
the wire is byte-for-byte what `Unrouted()` builds, except that the instrument
spells "no destination" **141** where `Unrouted()` picks 137. Both appear in the
factory corpus; both mean unrouted.

## How the ids were confirmed

Not by matching names. The amount field was identified by *watching it move*:
as the encoder turned, bytes 6–9 walked `0.01 → 0.4 → 1.0` across 71 packets.

The id tables were confirmed the same way. Turning the source encoder produced
one packet per detent, and the byte stepped:

```
48 → 6 → 7 → 8 → 9
(none) MOD WHEEL  PITCH WHEEL  PAD X  PAD Y
```

A contiguous walk through `src_ctl_ids` in table order, captured one step at a
time. The tables generated from `vx_ee.scm` describe the hardware. `Validate()`
accepts a matrix the instrument itself transmitted — `TestObservedIdsAreNameable`.

## It defines modulation; it does not carry it

`[READ]` Moving the physical mod wheel produced **zero** of these messages.
That negative control matters: it rules out the reading that these bytes are a
live modulation stream, which the amount sweep alone could not distinguish.
The message is sent when the *definition* changes. Modulation values never
cross this link — they are resolved on the voice controller.

## The voice controller answers

`[READ]` Every blob comes back. 71 sent, 71 echoed, byte-identical and in
order. The replies are genuinely generated by the XMOS rather than being a
capture artifact: Linux increments its IP IDs (71 distinct values), while every
reply carries **IP ID 0**, the same signature as the `/cb` heartbeat reply.

This contradicts a line in the plan. "Reading instrument state back" is listed
as ruled out, and for `las-sc` on 9300 that still holds — it answers the front
panel, never us. But the voice controller answers everything, and `moogd` runs
on the instrument, on the near end of that link. **A read-back path exists.**

## What is still not known

Enumerated because the gap between this list and the one above is the reason
live audition is still off.

1. **Whether 32 bytes is the whole matrix.** Only two slots were ever seen, and
   the panel offers far more rows. If a write replaces the entire set, sending
   a two-slot blob would silently delete every other routing. This is the
   blocker.
2. **Which UI row maps to which slot index.** The row edited at the panel was
   not obviously the slot that changed.
3. **Transform id 0**, which appeared mid-scroll and has no name in the tables.
4. `/x` (a 4-byte blob) and `/r/sys/local/en` (`,i` 0), both to 7770 alongside
   the matrix, both unexplained.
5. Whether a blob we originate is accepted at all — nothing has been written.

## Why nothing is written yet

The format is now observed rather than inferred, and `MarshalSlots` round-trips
the captured bytes exactly. That closes the encoding question and leaves the
semantic one: item 1 above. A patch that sounds subtly wrong is a bad outcome;
a patch that silently loses the player's other nineteen routings is a worse one.

The next capture that settles it is a preset load with a known, full matrix —
that shows the blob at its real length, with no panel edit needed.
