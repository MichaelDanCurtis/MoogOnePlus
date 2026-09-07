"""What scsynth actually costs, measured on the instrument's own kernel.

scsynth publishes its CPU in `/status.reply` and on this firmware both figures are
always exactly `0.000` while the process is plainly busy -- polled four times in a
row against a thread doing 82% of a core. The counters are dead, so the number that
decides whether an effect fits cannot come from the server.

Two other things had to be calibrated before this module could say anything true:

* busybox `top` on this box reports `%CPU` as a fraction of BOTH cores. It said 42%
  for a thread measured here at 82% of one. Any figure taken from `top` on this
  instrument is half the number that matters.
* There is no `getconf`, so `CLK_TCK` is unknown, and reading the wall clock from
  `/proc/uptime` put a single thread at 107% of a core -- the samples are not taken
  at the same instant as the thread's own counters, and the skew biases high. The
  clock here is `/proc/stat` instead: the kernel's own idle-plus-busy total over the
  same interval, divided by the core count, is exactly one core's worth of jiffies.
  Same file, same read, so nothing can drift between them, and `CLK_TCK` cancels.

The throttle is a per-thread phenomenon -- the kernel deschedules the SCHED_FIFO
thread that overruns its slice -- and scsynth does its DSP on one thread, so the
busiest thread is the figure, not the process total.

One warning about what this number can and cannot be used for. It is a true reading
of what the engine is costing NOW. It is not a way to measure what an added effect
costs, unless there is room for that effect: past the throttle the kernel caps the
thread, and a difference taken across the ceiling reports the ceiling. Measured
against a loaded patch, every Eventide reverb came back at half its real cost. See
`moogone.effect.CPU_COST`.
"""

from __future__ import annotations

import subprocess

SSH_OPTIONS = (
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=5",
)

#: Long enough that a block or two of jitter does not dominate, short enough that a
#: panel asking for state does not visibly wait on it.
SAMPLE_SECONDS = 2

#: Both samples are taken with two `cat`s and nothing else, then differenced by a
#: single awk at the end. An earlier version ran `awk` and `grep` per thread between
#: the samples and spent longer measuring than the interval it was measuring over,
#: which reported a single thread at 119% of a core. `/proc/uptime` is read inside
#: each sample so the elapsed time is the instrument's, not the round trip's.
_SCRIPT = r"""
pid=$(ps | grep '[s]csynth -u' | awk '{{print $1}}' | head -1)
[ -z "$pid" ] && {{ echo "NOPID"; exit 0; }}
{{ cat /proc/stat; cat /proc/$pid/task/*/stat; }} > /tmp/.voxload0
sleep {seconds}
{{ cat /proc/stat; cat /proc/$pid/task/*/stat; }} > /tmp/.voxload1
awk 'function total(  s,i){{ s=0; for(i=2;i<=NF;i++) s+=$i; return s }}
     NR==FNR{{ if($1=="cpu") t0=total(); else if($1 ~ /^cpu[0-9]/) n++;
               else if(NF>20) a[$1]=$14+$15; next }}
     $1=="cpu"{{ t1=total(); next }}
     $1 ~ /^cpu[0-9]/{{ next }}
     NF>20{{ d=($14+$15)-a[$1]; if(d>m) m=d }}
     END{{ if(n>0 && t1>t0) printf "%.4f\n", m/((t1-t0)/n) }}' /tmp/.voxload0 /tmp/.voxload1
rm -f /tmp/.voxload0 /tmp/.voxload1
"""


def script(seconds: int = SAMPLE_SECONDS) -> str:
    """busybox `sleep` takes whole seconds; a float here is a silent no-sample."""
    return _SCRIPT.format(seconds=int(seconds))


def parse(stdout: str) -> float | None:
    """The busiest thread's share of one core, or None if the box said nothing useful.

    None and 0.0 are different answers: None is "could not measure", which must leave
    the caller's previous figure alone, and 0.0 would be "measured, idle" -- which is
    what the dead `/status` counters claim and what this module exists to avoid
    repeating.
    """
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line == "NOPID" or not line:
            continue
        try:
            value = float(line)
        except ValueError:
            continue
        return value if value > 0.0 else None
    return None


def measure(host: str, seconds: int = SAMPLE_SECONDS) -> float | None:
    """Sample the instrument, or return None if it could not be asked."""
    try:
        proc = subprocess.run(
            ["ssh", *SSH_OPTIONS, f"root@{host}", "sh"],
            input=script(seconds),
            capture_output=True,
            text=True,
            check=False,
            timeout=seconds + 15.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return parse(proc.stdout)
