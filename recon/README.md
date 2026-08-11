<!-- recon/README.md -->
# Recon

One pass, in front of hardware that then goes away again. Read this before running it.

## Order of operations

1. **Verify access first.** USB drive with the `k` file, ethernet connected, boot, then
   `ssh root@<ip>`. Nothing else matters until this holds. If it fails, the firmware
   closed the gate and the whole plan needs rethinking.
2. **Copy the script over and run it passive.**
   ```sh
   scp recon/moog-recon.sh root@<ip>:/tmp/
   ssh root@<ip> 'sh /tmp/moog-recon.sh --out /tmp/moog-recon'
   scp -r root@<ip>:/tmp/moog-recon ./captures/
   ```
3. **Read `03-sockets.txt` before sending anything.** It tells you the real port and
   whether the sound engine binds loopback. It checks both TCP and UDP -- the 2021
   writeup says UDP on 9300, but by now that is a claim to verify here, not assume.
4. **Then, and only then, run the active pass** to get the runbook, and follow it in
   order (status, tree, dumpOSC):
   ```sh
   ssh root@<ip> 'sh /tmp/moog-recon.sh --out /tmp/moog-recon --active'
   scp -r root@<ip>:/tmp/moog-recon ./captures/
   cat ./captures/moog-recon/07-active-probes.txt
   ```
   `--active` only *writes instructions* -- the script never transmits OSC itself, in
   either mode. See the header comment in `moog-recon.sh` for why: this repo already has
   a tested Python OSC client (`src/moogone`), and reusing it from the Mac (or on-box, if
   `python3` turns out to be present -- check `06-toolchain.txt`) is a better bet than
   reimplementing UDP framing in shell under time pressure.

## The dumpOSC capture

This is the highest-value artifact in the project. Set mode 1, spend a full 30 seconds
moving *every* FX-related front-panel control, then set mode 0 and grab the log. Play a
few chords while it is running too -- that capture is what the per-voice pressure project
needs to learn how notes map to voices. `07-active-probes.txt` has the exact commands to
run and where to capture the log from.

Do it once, do it thoroughly. You are not back in front of this instrument tomorrow.

## What the output files are

| File | Contents |
| --- | --- |
| `00-summary.txt` | Timestamp, host, whether `--active` was used, and the file list. |
| `01-system.txt` | Kernel/arch, OS release, CPU info, memory, disk, uptime. |
| `02-processes.txt` | Full process table (twice -- plain and wide), `/proc/*/cmdline` for every PID (ps often truncates argv; this doesn't), the `/etc/init.d` listing, and any `screen` sessions. This is where the sound engine's *actual* current name and invocation live -- don't assume it is still called `las-sc`. |
| `03-sockets.txt` | Listening sockets (TCP and UDP) and firewall rules. Read this before `--active`. |
| `04-fx.txt` | `/usr/share/las-fx` tree, plus a bounded search for `*.scsyndef`/`*.scd`/`*.sc`/`las-*` files anywhere on the device. |
| `05-midi-audio.txt` | ALSA MIDI clients/devices, `/proc/asound`, USB devices -- the S88 path for the per-voice project. |
| `06-toolchain.txt` | What's installed (`socat`, `python3`, etc. -- tunnel and on-box-Python feasibility), writable locations, free space where the results themselves are being written. |
| `07-active-probes.txt` | Only with `--active`. The dumpOSC runbook. |

## Bounded search, not blind trust

`04-fx.txt`'s filesystem search is deliberately bounded: it stays on one filesystem
(`-xdev`, so it won't wander onto a network mount), stops at a depth limit, and is killed
after a wall-clock ceiling regardless of what the first two do (`MOOG_RECON_FIND_MAXDEPTH`
/ `MOOG_RECON_FIND_TIMEOUT` in the script header, defaults 10 / 15s). On the target's
small eMMC this finishes in a fraction of a second either way -- the bounds exist so a
slow filesystem or, worse, an unresponsive network mount, can't take the rest of the
recon down with it.

## What not to do

- Do not update the firmware. Development continued past discontinuation (v1.8.2,
  September 2025), and an update could close the `k` gate.
- Do not write to `/etc` or replace system binaries. Nothing here needs to.
- Do not skip the passive pass because the active one looks more interesting.
- Do not trust a path, port, or process name from this README or from the 2021 teardown
  writeups over what the script actually reports. Six firmware releases separate them.
