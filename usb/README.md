# The USB payload

What goes on the drive, and the one file that goes on the instrument.

```
/media/thumbdrive/
  moogd                 the server: static ARM binary, no libc, ~6 MB
  moogd.autostart       the opt-in marker -- an empty file
  vox/                  the UI it serves (2.2 MB)
    index.html  hotspots.json  icon-192.png  icon-512.png
    manifest.webmanifest  moog_one_01_3.webp
```

**The drive must be FAT32/MBR.** exFAT is invisible to this instrument's 4.1
kernel — see `docs/MOOG-ONE-INTERNALS.md`. That also rules out preparing a blank
drive on an iPad, which formats external media as exFAT.

## Installing

```sh
tar cf - -C src/moogone/vox/static . | ssh root@<ip> 'mkdir -p /media/thumbdrive/vox && tar xf - -C /media/thumbdrive/vox'
ssh root@<ip> 'cat > /media/thumbdrive/moogd && chmod +x /media/thumbdrive/moogd' < moogd/moogd
ssh root@<ip> 'touch /media/thumbdrive/moogd.autostart'
scp usb/S99moogd root@<ip>:/etc/init.d/ || ssh root@<ip> 'cat > /etc/init.d/S99moogd && chmod +x /etc/init.d/S99moogd' < usb/S99moogd
```

There is no `sftp-server` on the device, so `scp` does not work — pipe through `cat`.

## What touches the instrument

**One new file: `/etc/init.d/S99moogd`.** Nothing existing is modified, nothing is
replaced, and deleting that file undoes everything. Boot-time execution has to live
on the root filesystem — there is no generic USB autorun hook to borrow — so this is
the smallest possible footprint rather than none at all.

It is fail-safe by construction:

* **Opt-in.** No `moogd.autostart` on the drive, no server. A drive carrying the
  binary as cargo does not run it. This follows the convention the instrument
  already uses — `S50dropbear` enables SSH only when `/media/thumbdrive/k` exists —
  so carrying something and choosing to run it stay separate.
* **Never blocks the boot.** Doubly backgrounded, and it waits for the drive rather
  than assuming it: the USB is mounted by hotplug, asynchronously, and is often not
  there yet when an S99 script runs. Bounded at 30 seconds, then it gives up quietly.
* **Never fails the boot.** `exit 0` unconditionally. A workbench that could not
  start must never be why an instrument does not finish booting.
* **On cpu0, the shared core.** Not cpu1 — that looks free and is not. `isolcpus=1`
  reserves it for `scsynth`'s audio thread, which Moog's own ALSA driver pins there
  at `SCHED_FIFO` 99. `taskset -p <pid>` shows only a process's *main* thread, which
  is how that was missed here at first.

## Uninstalling

```sh
ssh root@<ip> '/etc/init.d/S99moogd stop; rm -f /etc/init.d/S99moogd'
rm /media/thumbdrive/moogd.autostart        # or just this, to keep it installed but off
```

## Two things that bit, recorded

`busybox killall` does not match a process started by absolute path, so `stop` kills
by PID from `ps` instead.

Matching `moogd` in `ps` also matches *this script* and its own subshells, which
makes every count wrong — the first test read "3 running" when the answer was 0. The
script matches the full path `[/]media/thumbdrive/moogd`.

## Testing a cold boot

**Do not use `reboot`.** It wedges the USB gadget and the instrument needs its power
removed — see `docs/MOOG-ONE-INTERNALS.md` §8b-bis, which was written because this
is how that was discovered. A cold boot means the power switch.

## Not done

**A cold boot is tested and works.** From power-on, with nothing typed:

```
uptime 386s
running: 1703   affinity=1  last-cpu=0  ppid=1
--- moogd starting Tue Sep  8 19:12:49 UTC 2026 ---
moogd on :8080, UI from /media/thumbdrive/vox, scsynth at 127.0.0.1:57110
```

*(That cold boot predated the discovery that cpu1 is the audio core; the script
now uses `taskset -c 0` and a running instance reads `Cpus_allowed_list: 0`.)*

`ppid=1` is the proof it came from the boot script and detached rather than
inheriting a login shell. The UI answered on the network immediately, `connected`,
with the scsynth dot lit from a real `/status`. The 30-second wait for the USB mount
was ample — the drive was ready well before it.

**The instrument may change address across a cold boot.** It came back on a new DHCP
lease, so the address in any notes will be stale. `moog-one.local` resolves
correctly and is what to use. The OSC quirk is unchanged and independent of this:
`scsynth` still answers from the *secondary* address on `ethext`, so that is the one
to send OSC to (`docs/MOOG-ONE-INTERNALS.md`).

There is no respawn. If `moogd` dies it stays dead until the next boot or a manual
`/etc/init.d/S99moogd start`. A restart loop was considered and left out: a crash
loop on a synthesiser is worse than a stopped web server.
