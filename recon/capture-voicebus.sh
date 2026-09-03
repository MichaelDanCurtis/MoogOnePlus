#!/bin/sh
# Capture the Moog One's internal voice/panel bus and dissect it.
#
# The interesting capture is the one taken WHILE THE INSTRUMENT IS BEING PLAYED.
# An idle capture shows the displays redrawing and nothing else on port 7770; a
# capture taken while a control moves is what shows a parameter write, which is the
# open question this exists to answer.
#
# Read-only on the device: it starts tcpdump, waits, kills it by PID, and copies the
# file off. Nothing is sent to the instrument.
#
# Usage:  sh recon/capture-voicebus.sh [host] [seconds]
set -e

HOST="${1:-192.168.1.138}"
SECS="${2:-30}"
OUT="captures/voice-bus-$(date +%Y%m%d-%H%M%S).pcap"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15"

mkdir -p captures

echo "capturing ${SECS}s from ${HOST} ..."
echo ">>> PLAY THE INSTRUMENT NOW — hold a chord, move the filter cutoff,"
echo ">>> turn a delay or reverb knob, use the wheels. Keep moving for the whole window."

# tcpdump backgrounded with \$! and killed by PID. Not job control: %1 inside a
# command substitution silently discards output, which once produced a sweep that
# reported 37 addresses as silent when two of them were known to answer.
$SSH "root@${HOST}" "
export PATH=/usr/sbin:/sbin:/usr/bin:/bin
rm -f /tmp/vb.pcap
tcpdump -i usbint -n -s 0 -w /tmp/vb.pcap udp >/dev/null 2>/tmp/vb.err &
echo \$! > /tmp/vb.pid
sleep ${SECS}
kill \$(cat /tmp/vb.pid) 2>/dev/null
sleep 1
tail -3 /tmp/vb.err
"

# -O: the device has no sftp-server, so scp must use the legacy protocol.
scp -O -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "root@${HOST}:/tmp/vb.pcap" "$OUT"

echo
echo "saved $OUT"
echo
uv run python3 -c "
import sys
from moogone.pcap import render
print(render(open(sys.argv[1],'rb').read()))
" "$OUT"

echo
echo "--- anything on the voice bus (7770) besides temperature? ---"
uv run python3 -c "
import sys
from moogone.pcap import summarise
_f, sig, _s = summarise(open(sys.argv[1],'rb').read())
rows = [(p,a,t,n) for (p,a,t),n in sig.items() if p in (7770, 7775)]
if not rows:
    print('  nothing at all on 7770/7775')
for p,a,t,n in sorted(rows, key=lambda r: -r[3]):
    flag = '' if a.startswith('/therm') else '   <-- NEW'
    print(f'  :{p} {a:<28} ,{t:<8} n={n}{flag}')
" "$OUT"
