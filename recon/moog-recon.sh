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
# "Guarded" means try()/show()/command -v, and covers commands and paths
# specific to the target device -- anything that could legitimately be
# absent on a given firmware, missing from a test container, or moved
# between versions. It does not extend to the baseline POSIX utilities
# this script is itself built from (cat, ls, mkdir, printf, rm, sed,
# head, tr, kill, sleep, wc): if those are missing, nothing here runs
# regardless of how defensively anything else is written, so "guarding"
# them would only be guarding the assumption every guard already depends
# on. Two exceptions, both deliberate: `mkdir -p "$OUT"` at the top exits
# the script outright, because there is nowhere to write results without
# it; and the two `ls "$OUT"` directory listings near the end (summary
# and stdout) carry their own fallback text despite `ls` being in the
# assumed-present category above, because they are the operator's own
# confirmation that the run produced anything at all, and going silently
# blank there specifically is worse than everywhere else that assumption
# holds.
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
HUNT_TRUNCATED=0
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
            case "$OUT" in
                "")
                    echo "--out requires a directory argument" >&2
                    exit 2
                    ;;
                -*)
                    echo "--out requires a directory argument, got '$OUT' (looks like another flag -- missing the value?)" >&2
                    exit 2
                    ;;
            esac
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
#
# Returns the backgrounded command's own wait status, so a caller can
# tell "finished on its own" from "we killed it" -- see hunt() below.
# This matters: a killed search and a search that legitimately found
# nothing produce byte-identical stdout otherwise, and the difference
# between "empty" and "cut short" is exactly the thing a one-shot capture
# cannot afford to blur.
bounded() {
    _bsecs="$1"
    _boutfile="$2"
    shift 2
    "$@" >"$_boutfile" 2>/dev/null &
    _bpid=$!
    ( sleep "$_bsecs"; kill "$_bpid" 2>/dev/null ) &
    _bwatch=$!
    wait "$_bpid" 2>/dev/null
    _bstatus=$?
    kill "$_bwatch" 2>/dev/null
    wait "$_bwatch" 2>/dev/null
    return "$_bstatus"
}

# Search FSROOT for synthdefs, SuperCollider sources, and las-* binaries,
# bounded three ways: -xdev keeps it off other mounts (a network mount
# included), -maxdepth bounds the walk within one filesystem, and the
# wall-clock cap above bounds it regardless of what the first two do. On
# the target's small eMMC this finishes in a fraction of a second -- these
# bounds exist for the test machine's much larger filesystem and for a
# bad day in September, not because the real search needs limiting.
#
# Two different things can make this section's results incomplete without
# making it look incomplete: the watchdog killing find before it finished,
# and there being more than the 200-line display cap. Both are detected
# and both set HUNT_TRUNCATED, which propagates a warning into the
# summary and onto stdout -- see the end of the script. A capture an
# operator can't get a second copy of must never claim completeness it
# doesn't have.
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
               -o -name 'las-*' -o -name 'lasfwu' \) ! -type d
    _hstatus=$?
    # kill (no signal name given) sends SIGTERM, signal 15. A background
    # job reaped after dying to a signal reports 128+signal as its wait
    # status -- 143 here specifically means "the watchdog killed this",
    # not "find exited with an odd code of its own": find only ever exits
    # 0 (nothing wrong) or 1 (some path was unreadable, which is normal
    # and already handled by discarding stderr above).
    if [ "$_hstatus" -eq 143 ]; then
        HUNT_TRUNCATED=1
        printf '\n***** TRUNCATED: this search was still running when the %ss timeout *****\n' "$FIND_TIMEOUT"
        printf '***** (MOOG_RECON_FIND_TIMEOUT) killed it. Results below, if any, are   *****\n'
        printf '***** INCOMPLETE -- absence of a match here is NOT evidence of absence  *****\n'
        printf '***** on the device.                                                    *****\n'
    fi
    _hlines=$(wc -l < "$_hout" 2>/dev/null | tr -d ' ')
    head -200 "$_hout" 2>/dev/null
    if [ -n "$_hlines" ] && [ "$_hlines" -gt 200 ]; then
        HUNT_TRUNCATED=1
        printf '\n***** TRUNCATED: %s matches found; only the first 200 are shown above. *****\n' "$_hlines"
        printf '***** Narrow MOOG_RECON_FSROOT and re-run, or read the rest directly on *****\n'
        printf '***** the device, to see what was cut.                                  *****\n'
    fi
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
#
# ss and netstat are both OPTIONAL. On a stripped buildroot ARM device ss
# is frequently absent outright, and busybox netstat only reports the
# owning process with a build flag that is often off -- so this whole file
# can legitimately come back as two "(command not available)" lines and
# one iptables error, answering neither open question. /proc/net/udp and
# /proc/net/tcp are always readable on any Linux kernel, need no binary at
# all, and their local_address column answers both questions directly.
# udp6/tcp6 cost nothing extra and cover an engine bound to an IPv6
# socket, which nothing has ruled out.
{
    try "listening sockets (ss)" ss -tulpn
    try "listening sockets (netstat)" netstat -tulpn
    printf '\n===== reading /proc/net/{udp,tcp} (no binaries needed) =====\n'
    printf 'local_address is HEX and BYTE-REVERSED: 0100007F:2454 is\n'
    printf '127.0.0.1 port 9300 (0x2454 = 9300; 01.00.00.7F read backwards\n'
    printf 'is 7F.00.00.01 = 127.0.0.1). A local_address of 00000000:2454\n'
    printf 'means 0.0.0.0 -- bound to every interface, reachable from the\n'
    printf 'Mac without a tunnel. That distinction is the reason this\n'
    printf 'section exists; do not guess it from the ss output above if\n'
    printf 'ss was unavailable.\n'
    show "${FSROOT}/proc/net/udp"
    show "${FSROOT}/proc/net/tcp"
    show "${FSROOT}/proc/net/udp6"
    show "${FSROOT}/proc/net/tcp6"
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

Every step uses the \`moogone\` CLI already built and tested in this repo.
Use the CLI, NOT hand-written python3 -c snippets: the CLI is where this
project's protections live, and each one exists because the raw call
reports success in a case where it should not.

  - \`set\` refuses a node that does not exist, and refuses a node that is
    a GROUP rather than a synth. /n_set silently no-ops on a group with no
    error of any kind, so a raw n_set() call prints nothing wrong while
    changing nothing -- which reads as "voices are not individually
    addressable, project dead".
  - \`set\` also distinguishes "sent and confirmed" from "sent, delivery
    unconfirmed" instead of reporting a missing /sync as a failed write.
  - \`dump\` follows the fire-and-forget /dumpOSC with a /sync, so a server
    that rejects the command is caught. A raw dump_osc() call cannot see
    the /fail and reports success over it -- and this is the one capture
    you cannot repeat.
  - \`tree\` refuses a reply that came back without the control values it
    asked for, instead of showing every effect as having no controls.

Getting moogone onto the device (it has NO third-party dependencies -- see
pyproject.toml -- so this is a copy, not an install):

    scp -r src/moogone root@<device-ip>:/tmp/
    ssh root@<device-ip>
    cd /tmp && python3 -m moogone.cli status

If python3 is absent on the device (check 06-toolchain.txt), run from the
Mac instead: either directly over the network if 03-sockets.txt shows the
socket bound to 0.0.0.0, or via --tunnel if it is bound to 127.0.0.1. See
\`moogone --help\` for the three-port tunnel topology.

READ 03-sockets.txt FIRST. Use the real port and bind address it reports --
the 9300 below is only the 2021 writeup's claim, six firmware releases
stale by now. Add --port <real-port> to every command if it differs.

1. status -- confirms the engine speaks the SuperCollider protocol at all.
   Cheapest possible check; run it first. If this fails, everything
   downstream needs rethinking.

     moogone status

2. tree -- /g_queryTree, the full live node graph with every control name.
   The single most valuable automated call here, and the source of truth
   for the FX SynthDef's real control names.

     moogone tree --json > $OUT/09-tree.json
     moogone tree

3. dumpOSC -- THE HIGHEST-VALUE CAPTURE IN THE WHOLE PROJECT.

   Read all of step 3 before starting any of it. The knob sweep happens
   once.

   3a. Start LOGGING TO DISK before enabling dump mode. Do not rely on
       \`screen -X hardcopy\`: hardcopy dumps the scrollback buffer, which
       defaults to 100 lines, and 30 seconds of knob motion is plausibly
       thousands. It would hand you a file that looks complete and holds
       only the tail.

       Find the sound engine's session name (02-processes.txt -- the 2021
       writeup calls it las-sc, do not assume that still holds):

         screen -ls

       Then, using -S <session> (the documented selector for sending
       commands to a session; -r is the "reattach" flag and takes a
       different code path):

         screen -S <session> -X logfile $OUT/08-dumposc.log
         screen -S <session> -X logfile flush 1
         screen -S <session> -X log on

   3b. Enable dump mode. This will FAIL LOUDLY if the engine does not
       implement /dumpOSC, rather than reporting success over a rejection:

         moogone dump 1

   3c. Now spend a FULL 30 SECONDS moving every front panel FX control --
       and play some chords too, the per-voice pressure project needs that
       part. This hands over Moog's own OSC namespace by observation
       instead of guesswork, for both downstream projects at once. Do it
       once, thoroughly. There is no coming back tomorrow.

   3d. Stop:

         moogone dump 0
         screen -S <session> -X log off

   3e. Confirm you actually got something before moving on:

         wc -l $OUT/08-dumposc.log

       A file of ~100 lines is a warning sign that logging never started
       and you are looking at a hardcopy-sized tail. If \`screen -X log\`
       is unsupported by this build, fall back to
       \`screen -S <session> -X hardcopy -h $OUT/08-dumposc.txt\` -- but
       treat that capture as TRUNCATED, because it almost certainly is.

4. Per-voice go/no-go. Hold a note, then set a control on that voice's
   node (node ids come from step 2) and listen. One voice changes, or the
   per-voice pressure project is dead.

     moogone set <voice-node-id> <param>=<value>

   Read the output carefully; it distinguishes three outcomes:
     "sent to node N (synth): {...}"              write went out, confirmed
     "sent to node N (synth), UNCONFIRMED: {...}" write went out, no /sync
     "error: ..."                                 nothing was sent

5. FX probe. Render the harness script with the real defname and control
   names from step 2, paste it into the sound engine's sclang session, and
   copy both resulting WAVs off:

     python3 -c "from moogone.harness import render_probe_script; \\
       print(render_probe_script('<fx-defname>', '/tmp/probe-before.wav'))"

   It writes TWO files -- a silence probe and a tone probe. The silence
   probe is the one that answers the noise question. See harness/README.md.

If a tunnel is needed to reach the engine from the Mac (check socat in
06-toolchain.txt), see the two-terminal setup in \`moogone --help\` and in
src/moogone/transport/tunnel.py.
EOF
fi

# --------------------------------------------------------------- summary
{
    printf 'Moog One recon\n'
    printf 'date: %s\n' "$(date 2>/dev/null || printf unknown)"
    printf 'host: %s\n' "$(hostname 2>/dev/null || printf unknown)"
    printf 'active probes written: %s\n' "$ACTIVE"
    if [ "$HUNT_TRUNCATED" -eq 1 ]; then
        printf '\nWARNING: the synthdef/binary search in 04-fx.txt may be INCOMPLETE.\n'
        printf 'Read its ***** TRUNCATED ***** marker(s) before trusting an absence there.\n'
    fi
    printf '\nfiles written:\n'
    ls -la "$OUT" 2>&1 || printf '(unable to list %s -- ls failed or is unavailable)\n' "$OUT"
} > "$OUT/00-summary.txt" 2>&1

printf 'recon complete: %s\n' "$OUT"
ls "$OUT" || printf '(unable to list %s -- ls failed or is unavailable)\n' "$OUT"

if [ "$HUNT_TRUNCATED" -eq 1 ]; then
    printf '\nWARNING: the synthdef/binary search in 04-fx.txt may be INCOMPLETE -- read\n'
    printf 'its ***** TRUNCATED ***** marker(s) before trusting an absence of results.\n'
fi

if [ "$ACTIVE" -eq 0 ]; then
    printf '\nPassive pass done. Read %s/03-sockets.txt before transmitting anything.\n' "$OUT"
    printf 'The highest-value capture in this project is still ahead of you: re-run\n'
    printf 'with --active and follow the dumpOSC steps in %s/07-active-probes.txt --\n' "$OUT"
    printf 'move every front panel FX control and capture Moog'"'"'s own OSC namespace by\n'
    printf 'observation. Do not skip it because this passive pass looked complete.\n'
fi

exit 0
