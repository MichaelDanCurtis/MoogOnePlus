#!/bin/sh
# Moog One reconnaissance -- single pass, read-only by default.
#
# This runs once, in front of hardware that then goes away for months.
# Whatever it fails to capture is either a second trip or a guess later
# work gets built on. Two consequences follow:
#
#   1. It must not abort. Every external command is guarded: if a binary
#      isn't there, a path moved, or a permission differs, that fact is
#      recorded and the script moves on. It must exit 0 and produce
#      output even on a host where none of the target paths exist.
#   2. It gathers for two downstream projects in this one pass: effects
#      diagnosis needs the SuperCollider layout, a separate per-voice
#      control project needs the MIDI/USB topology.
#
# It reads actual values rather than trusting the 2021 teardown writeups.
# The current release (v1.8.2, September 2025) is roughly six firmware
# versions past what those writeups describe -- paths, ports, and process
# names may all have moved. Where a comment below names a specific file,
# port, or process from those writeups, treat it as a hypothesis to check
# against the output, never as something already established.
#
# Usage:
#   sh moog-recon.sh [--out DIR] [--active]
#
#   --out DIR   where to write results (default /tmp/moog-recon)
#   --active    also write the active-probe runbook. Off by default.
#
# ACTIVE MODE, AND WHY THIS SCRIPT NEVER TRANSMITS EITHER WAY
#   The highest-value single artifact this project can produce is a
#   dumpOSC capture: set mode 1 on the sound engine, move every
#   front-panel FX control for a full 30 seconds (play some chords too),
#   set mode 0, and grab the resulting log. That turns guesswork about
#   Moog's own OSC namespace into fact, for both downstream projects at
#   once. --active writes step-by-step instructions for that into
#   07-active-probes.txt. It does not run them.
#
#   This script does not send OSC itself, in either mode. Implementing
#   UDP framing correctly in busybox-compatible POSIX sh, under a
#   one-shot time limit, in front of hardware that then disappears, is a
#   bad trade against the alternative: this repo already has a tested
#   Python OSC client (src/moogone). --active exists so the instructions
#   for using it do not get missed -- not to replace it with something
#   riskier and unrehearsed.
#
# Every external command is guarded except `mkdir -p "$OUT"`: if there is
# nowhere to write results, there is nothing further this script can do.
#
# Testing hooks (production runs never set these; each defaults to the
# real filesystem and real timings):
#   MOOG_RECON_FSROOT         prefix prepended to every absolute path this
#                              script reads, so tests can point it at a
#                              throwaway fixture tree instead of the real
#                              /etc, /usr, or /proc. Default: empty (the
#                              real root).
#   MOOG_RECON_FIND_MAXDEPTH  passed to find -maxdepth. Default: 10.
#   MOOG_RECON_FIND_TIMEOUT   wall-clock seconds before the synthdef/
#                              binary search is killed. Default: 15.

set -u

OUT=/tmp/moog-recon
ACTIVE=0
FSROOT="${MOOG_RECON_FSROOT:-}"
FSROOT="${FSROOT%/}"
FIND_MAXDEPTH="${MOOG_RECON_FIND_MAXDEPTH:-10}"
FIND_TIMEOUT="${MOOG_RECON_FIND_TIMEOUT:-15}"

usage() {
    cat <<'EOF'
Usage: moog-recon.sh [--out DIR] [--active]

  --out DIR   where to write results (default /tmp/moog-recon)
  --active    also write the active-probe runbook (07-active-probes.txt).
              Off by default. Read 03-sockets.txt before ever running
              those probes.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --out)
            OUT="${2:-}"
            if [ -z "$OUT" ]; then
                echo "--out requires a directory argument" >&2
                exit 2
            fi
            shift 2
            ;;
        --active)
            ACTIVE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown option: $1" >&2
            exit 2
            ;;
    esac
done

mkdir -p "$OUT" || exit 1

# Run a command if it exists, capturing both streams. Never fails the script.
try() {
    _label="$1"
    shift
    printf '\n===== %s =====\n' "$_label"
    if command -v "$1" >/dev/null 2>&1; then
        "$@" 2>&1 || printf '(exited %s)\n' "$?"
    else
        printf '(command not available: %s)\n' "$1"
    fi
}

# Show a file if it exists.
show() {
    printf '\n===== %s =====\n' "$1"
    if [ -r "$1" ]; then
        cat "$1" 2>&1
    else
        printf '(not readable)\n'
    fi
}

# Run "$@" with a hard wall-clock ceiling, without depending on the
# `timeout` command (not guaranteed present on busybox or macOS). Kills
# the command's own pid directly -- not a pipeline or a subshell wrapping
# it -- so there is no process-group ambiguity about what "kill" reaches.
# stderr is discarded rather than merged into the capture: hunt() below
# caps its output at 200 lines, and on a filesystem with protected
# directories (true of every dev machine, false of a root shell on the
# target) permission-denied noise would otherwise compete with genuine
# matches for that budget.
#
# This is real protection against a slow tree (a huge dev filesystem, a
# large but responsive vendor partition) and against `find` simply taking
# too long. It is not a guarantee against every hang: a process stuck in
# uninterruptible sleep on a wedged network mount cannot be killed by any
# signal, from this or any other tool, until the kernel gives up on the
# I/O. -xdev in hunt() below is the actual defense for that case, by
# never walking onto another mount to begin with.
bounded() {
    _bsecs="$1"
    _boutfile="$2"
    shift 2
    "$@" >"$_boutfile" 2>/dev/null &
    _bpid=$!
    ( sleep "$_bsecs"; kill "$_bpid" 2>/dev/null ) &
    _bwatch=$!
    wait "$_bpid" 2>/dev/null
    kill "$_bwatch" 2>/dev/null
    wait "$_bwatch" 2>/dev/null
}

# Search FSROOT for synthdefs, SuperCollider sources, and las-* binaries,
# bounded three ways: -xdev keeps it off other mounts (a network mount
# included), -maxdepth bounds the walk within one filesystem, and the
# wall-clock cap above bounds it regardless of what the first two do. On
# the target's small eMMC this finishes in a fraction of a second -- these
# bounds exist for the test machine's much larger filesystem and for a
# bad day in September, not because the real search needs limiting.
hunt() {
    printf '\n===== synthdef / SuperCollider source / las-* binaries under %s (bounded: -xdev, maxdepth %s, %ss cap; permission-denied noise suppressed, not an error) =====\n' \
        "${FSROOT:-/}" "$FIND_MAXDEPTH" "$FIND_TIMEOUT"
    if ! command -v find >/dev/null 2>&1; then
        printf '(command not available: find)\n'
        return
    fi
    _hout="$OUT/.hunt.tmp"
    bounded "$FIND_TIMEOUT" "$_hout" \
        find "${FSROOT:-/}" -xdev -maxdepth "$FIND_MAXDEPTH" \
            \( -name '*.scsyndef' -o -name '*.scd' -o -name '*.sc' \
               -o -name 'las-*' -o -name 'lasfwu' \)
    head -200 "$_hout" 2>/dev/null
    rm -f "$_hout"
}

# ---------------------------------------------------------------- system
{
    try "kernel and architecture" uname -a
    show "${FSROOT}/etc/os-release"
    show "${FSROOT}/etc/version"
    show "${FSROOT}/proc/cpuinfo"
    try "memory" free
    try "disk free (all mounts)" df -h
    try "uptime" uptime
} > "$OUT/01-system.txt" 2>&1

# ------------------------------------------------------------- processes
{
    try "process table" ps
    try "process table (wide, if supported)" ps -ef
    printf '\n===== full command lines via /proc (ps often truncates argv) =====\n'
    if [ -d "${FSROOT}/proc" ]; then
        _found_any=0
        for _cmdline in "${FSROOT}"/proc/[0-9]*/cmdline; do
            [ -r "$_cmdline" ] || continue
            _found_any=1
            _piddir="${_cmdline%/cmdline}"
            _pid="${_piddir##*/}"
            _args=$(tr '\0' ' ' < "$_cmdline" 2>/dev/null)
            [ -n "$_args" ] && printf '%s: %s\n' "$_pid" "$_args"
        done
        [ "$_found_any" -eq 1 ] || printf '(no readable /proc/*/cmdline)\n'
    else
        printf '(no /proc)\n'
    fi
    printf '\n===== init scripts =====\n'
    ls -la "${FSROOT}/etc/init.d" 2>&1 || printf '(no /etc/init.d)\n'
    show "${FSROOT}/etc/init.d/S42sc"
    show "${FSROOT}/etc/init.d/S43gui"
    show "${FSROOT}/etc/init.d/S50dropbear"
    try "screen sessions" screen -ls
} > "$OUT/02-processes.txt" 2>&1

# --------------------------------------------------------------- sockets
# Resolves the two questions the writeup leaves open: which port the
# sound engine actually uses, and whether it binds loopback (which would
# explain why remote OSC failed for earlier explorers without invoking
# iptables). Checked as both TCP and UDP -- the 2021 writeup says UDP,
# but that too is a claim to verify here, not assume.
{
    try "listening sockets (ss)" ss -tulpn
    try "listening sockets (netstat)" netstat -tulpn
    try "firewall rules" iptables -L -n
} > "$OUT/03-sockets.txt" 2>&1

# ------------------------------------------------------------------- fx
{
    printf '\n===== %s/usr/share/las-fx tree =====\n' "${FSROOT}"
    ls -laR "${FSROOT}/usr/share/las-fx" 2>&1 || printf '(not present)\n'
    show "${FSROOT}/usr/share/las-fx/launch-sc-1"
    show "${FSROOT}/usr/share/las-fx/util/cpu.rtf"
    hunt
} > "$OUT/04-fx.txt" 2>&1

# ------------------------------------------------------------------ midi
# The S88 path for the per-voice pressure project: can this box see a
# class-compliant controller, and on which ALSA device?
{
    try "alsa midi clients" aconnect -l
    try "alsa midi devices" amidi -l
    try "playback devices" aplay -l
    try "capture devices" arecord -l
    printf '\n===== %s/proc/asound =====\n' "${FSROOT}"
    ls -la "${FSROOT}/proc/asound" 2>&1 || printf '(not present)\n'
    show "${FSROOT}/proc/asound/cards"
    try "usb devices" lsusb
    printf '\n===== usb host controllers =====\n'
    ls -la "${FSROOT}/sys/bus/usb/devices" 2>&1 || printf '(not present)\n'
} > "$OUT/05-midi-audio.txt" 2>&1

# ------------------------------------------------------------- toolchain
# Decides the on-box runtime and whether the tunnel is even possible.
{
    for tool in socat python python3 perl screen tcpdump nc scsynth sclang; do
        printf '%s: ' "$tool"
        command -v "$tool" 2>/dev/null || printf '(absent)\n'
    done
    printf '\n===== writable locations =====\n'
    for dir in /tmp /var/tmp /media /home /root; do
        if [ -w "$dir" ]; then printf '%s: writable\n' "$dir"; fi
    done
    try "disk free (where results are being written)" df -h "$OUT"
} > "$OUT/06-toolchain.txt" 2>&1

# ---------------------------------------------------------------- active
# This writes a runbook; it never transmits anything itself. See the
# ACTIVE MODE header comment for why.
if [ "$ACTIVE" -eq 1 ]; then
    cat > "$OUT/07-active-probes.txt" <<EOF
This is a runbook, not something this shell script runs for you.

It uses the OSC client already built and tested in this repo (src/moogone).
Run these from the Mac, or on-box if python3 is present (see 06-toolchain.txt).

READ 03-sockets.txt FIRST. Use the real port and bind address it reports --
the 127.0.0.1:9300 below is only the 2021 writeup's claim, six firmware
releases stale by now.

1. status -- confirms the engine speaks the SuperCollider protocol at all.
   Cheapest possible check; run it first.

     python3 -c "
     from moogone.transport.udp import UdpTransport
     from moogone.sc.client import ScClient
     t = UdpTransport('127.0.0.1', 9300)  # host/port from 03-sockets.txt
     print(ScClient(t).status())
     "

2. tree -- /g_queryTree, the full live node graph with every control name.
   The single most valuable automated call here.

     python3 -c "
     from moogone.transport.udp import UdpTransport
     from moogone.sc.client import ScClient
     t = UdpTransport('127.0.0.1', 9300)
     root = ScClient(t).query_tree()
     for n in root.walk():
         print(n)
     "

3. dumpOSC -- THE HIGHEST-VALUE CAPTURE IN THE WHOLE PROJECT.
   Set mode 1, then spend a FULL 30 SECONDS moving every front panel FX
   control (play some chords too -- the per-voice pressure project needs
   that part), then set mode 0. This hands over Moog's own OSC namespace
   by observation instead of guesswork, for both downstream projects at
   once. Do it once, thoroughly -- there is no coming back tomorrow.

     python3 -c "
     from moogone.transport.udp import UdpTransport
     from moogone.sc.client import ScClient
     t = UdpTransport('127.0.0.1', 9300)
     ScClient(t).dump_osc(1)
     input('mode 1 set -- move every front panel FX control now, then press enter: ')
     ScClient(t).dump_osc(0)
     "

   Then capture the screen session log for whatever the sound engine is
   actually running as (see 02-processes.txt -- the 2021 writeup calls it
   las-sc, but do not assume that still holds):

     screen -ls
     screen -r <session> -X hardcopy -h $OUT/08-dumposc.txt

   If a tunnel is needed to reach the engine from the Mac (check socat in
   06-toolchain.txt), see the two-terminal setup documented in
   src/moogone/transport/tunnel.py.
EOF
fi

# --------------------------------------------------------------- summary
{
    printf 'Moog One recon\n'
    printf 'date: %s\n' "$(date 2>/dev/null || printf unknown)"
    printf 'host: %s\n' "$(hostname 2>/dev/null || printf unknown)"
    printf 'active probes written: %s\n' "$ACTIVE"
    printf '\nfiles written:\n'
    ls -la "$OUT" 2>&1
} > "$OUT/00-summary.txt" 2>&1

printf 'recon complete: %s\n' "$OUT"
ls "$OUT"

if [ "$ACTIVE" -eq 0 ]; then
    printf '\nPassive pass done. Read %s/03-sockets.txt before transmitting anything.\n' "$OUT"
    printf 'The highest-value capture in this project is still ahead of you: re-run\n'
    printf 'with --active and follow the dumpOSC steps in %s/07-active-probes.txt --\n' "$OUT"
    printf 'move every front panel FX control and capture Moog'"'"'s own OSC namespace by\n'
    printf 'observation. Do not skip it because this passive pass looked complete.\n'
fi

exit 0
