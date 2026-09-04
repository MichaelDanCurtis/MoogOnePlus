#!/bin/sh
# Capture the Moog One's internal buses while the instrument is played, and dissect.
#
# Two interfaces, because they answer different questions:
#
#   lo       las-frontend <-> las-sc, the CONTROL path. Measured completely SILENT at
#            idle -- zero packets in twelve seconds. So everything this captures was
#            caused by you, with no display refresh to filter out. This is the good one.
#   usbint   las-sc <-> the voice/panel controller. Busy at idle (~528 packets/sec),
#            two thirds of it redrawing the OLEDs, so the signal here needs digging for.
#
# Read-only on the device: starts tcpdump, waits, kills it by PID, copies the files off.
# Nothing is transmitted to the instrument.
#
# Usage:  sh recon/capture-voicebus.sh [host] [seconds]
set -e

HOST="${1:-192.168.1.138}"
SECS="${2:-30}"
STAMP="$(date +%Y%m%d-%H%M%S)"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15"

mkdir -p captures

echo "capturing ${SECS}s on lo and usbint from ${HOST}"
echo
echo "  >>> PLAY NOW, and keep going for the whole ${SECS} seconds:"
echo "  >>>   hold a chord and move the filter cutoff"
echo "  >>>   turn a delay or reverb knob"
echo "  >>>   push the mod wheel and use the XY pad"
echo "  >>> Everything lo records was caused by you -- it hears nothing on its own."
echo

# tcpdump backgrounded with $! and killed by PID, never job control: %1 inside a
# command substitution silently discards output, which once produced a sweep that
# called 37 addresses silent when two of them were known to answer.
$SSH "root@${HOST}" "
export PATH=/usr/sbin:/sbin:/usr/bin:/bin
rm -f /tmp/lo.pcap /tmp/vb.pcap
tcpdump -i lo     -n -s 0 -w /tmp/lo.pcap udp >/dev/null 2>/tmp/lo.err &
echo \$! > /tmp/lo.pid
tcpdump -i usbint -n -s 0 -w /tmp/vb.pcap udp >/dev/null 2>/tmp/vb.err &
echo \$! > /tmp/vb.pid
sleep ${SECS}
kill \$(cat /tmp/lo.pid) \$(cat /tmp/vb.pid) 2>/dev/null
sleep 1
echo '  lo:     ' \$(grep -o '[0-9]* packets captured' /tmp/lo.err)
echo '  usbint: ' \$(grep -o '[0-9]* packets captured' /tmp/vb.err)
"

# -O: the device has no sftp-server, so scp must use the legacy protocol.
scp -O -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "root@${HOST}:/tmp/lo.pcap" "captures/control-${STAMP}.pcap"
scp -O -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "root@${HOST}:/tmp/vb.pcap" "captures/voicebus-${STAMP}.pcap"

echo
echo "=============================================================="
echo " THE CONTROL PATH  (captures/control-${STAMP}.pcap)"
echo " Silent at idle, so all of this is you."
echo "=============================================================="
uv run python3 -c "
import sys
from moogone.pcap import render
d = open(sys.argv[1],'rb').read()
out = render(d)
print(out if '0 OSC messages' not in out else
      'nothing at all -- was the instrument actually played during the window?')
" "captures/control-${STAMP}.pcap"

echo
echo "=============================================================="
echo " THE VOICE BUS  (captures/voicebus-${STAMP}.pcap)"
echo " Did port 7770 carry anything but temperature this time?"
echo "=============================================================="
uv run python3 -c "
import sys
from moogone.pcap import summarise
_f, sig, sample = summarise(open(sys.argv[1],'rb').read())
rows = [(p,a,t,n) for (p,a,t),n in sig.items() if p in (7770, 7775)]
new = [r for r in rows if not r[1].startswith('/therm')]
for p,a,t,n in sorted(rows, key=lambda r: -r[3]):
    mark = '' if a.startswith('/therm') else '   <-- NOT TEMPERATURE'
    print(f'  :{p} {a:<30} ,{t:<10} n={n}{mark}')
print()
print('  ' + ('VOICE WRITES EXIST ON 7770 -- %d new address(es).' % len(new) if new
      else 'Still only /therm. Voice parameters do not travel port 7770.'))
" "captures/voicebus-${STAMP}.pcap"
