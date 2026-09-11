package main

// Diagnostics: what the instrument will not tell you about itself.
//
// The Moog One's own screen shows a firmware version and a temperature. This
// reads the things that actually decide whether the next thing you do works --
// and it can, because it runs on the instrument, where /proc and /sys are files.
//
// One number matters more than the rest. `scsynth`'s audio thread runs
// SCHED_FIFO on cpu1, and Linux throttles realtime tasks above
// sched_rt_runtime_us / sched_rt_period_us. Past that ceiling the kernel
// forcibly deschedules it, which is heard as the sound cutting out for about a
// tenth of a second. Everything else here is context for that one figure.
//
// Nothing in this file writes anything.

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// Thread is one of `scsynth`'s threads, as the kernel sees it.
//
// This exists because `taskset -p <pid>` shows only the MAIN thread's mask, and
// on this instrument the main thread is on cpu0 while a single audio thread is
// pinned to cpu1 at realtime priority 99. Reading only the process makes cpu1
// look idle, which is exactly the mistake this project made for months.
type Thread struct {
	TID      int    `json:"tid"`
	Policy   string `json:"policy"`
	RTPrio   int    `json:"rt_priority"`
	LastCPU  int    `json:"last_cpu"`
	Affinity string `json:"affinity"`
	Audio    bool   `json:"audio"`
}

// Filesystem is one mount's usage.
type Filesystem struct {
	Mount   string  `json:"mount"`
	TotalKB uint64  `json:"total_kb"`
	FreeKB  uint64  `json:"free_kb"`
	UsedPct float64 `json:"used_pct"`
	Note    string  `json:"note,omitempty"`
}

// Defect is something wrong with the instrument that it does not report.
type Defect struct {
	Title    string `json:"title"`
	Detail   string `json:"detail"`
	Severity string `json:"severity"` // "info" | "warn"
	Present  bool   `json:"present"`
}

// Diagnostics is the whole picture.
type Diagnostics struct {
	// The headline.
	AudioCoreBusy float64 `json:"audio_core_busy"` // 0..1, cpu1
	ThrottleAt    float64 `json:"throttle_at"`     // 0..1, the RT ceiling
	HeadroomPct   float64 `json:"headroom_pct"`    // points of a core to spare

	Cores map[string]float64 `json:"cores"`
	TempC float64            `json:"temp_c"`

	Engine  *Status      `json:"engine"`
	Threads []Thread     `json:"threads"`
	Disks   []Filesystem `json:"disks"`
	IRQs    []IRQ        `json:"irqs"`
	Defects []Defect     `json:"defects"`

	// How often the kernel has cut the audio engine off for overrunning its
	// realtime budget. Zero is the expected value; anything else is a dropout
	// that already happened.
	RTThrottled     int    `json:"rt_throttled"`
	RTThrottledLast string `json:"rt_throttled_last,omitempty"`

	Version string `json:"version"`
	Uptime  string `json:"uptime"`
	Cmdline string `json:"cmdline"`
}

// IRQ is one interrupt line and its per-core counts.
type IRQ struct {
	Name   string   `json:"name"`
	Counts []uint64 `json:"counts"`
}

// procStat pulls the scheduling fields out of /proc/<...>/stat.
//
// `comm` is in parentheses and may itself contain spaces and parentheses, so
// the fields are counted from the LAST ')' rather than by splitting the whole
// line -- splitting works for "scsynth" and breaks silently for anything else.
func procStat(path string) (policy, rtPrio, lastCPU int, ok bool) {
	raw := readFile(path)
	close := strings.LastIndexByte(raw, ')')
	if close < 0 {
		return 0, 0, 0, false
	}
	f := strings.Fields(raw[close+1:]) // f[0] is field 3 (state)
	at := func(n int) int {            // proc(5) field number, 1-based
		if n-3 >= len(f) {
			return 0
		}
		v, _ := strconv.Atoi(f[n-3])
		return v
	}
	// 39 processor, 40 rt_priority, 41 policy
	return at(41), at(40), at(39), len(f) > 38
}

func policyName(p int) string {
	switch p {
	case 0:
		return "OTHER"
	case 1:
		return "FIFO"
	case 2:
		return "RR"
	}
	return fmt.Sprintf("%d", p)
}

// scsynthThreads reads every thread of the audio server.
func scsynthThreads() []Thread {
	pid := pidOf("scsynth")
	if pid == 0 {
		return nil
	}
	dirs, err := filepath.Glob(fmt.Sprintf("/proc/%d/task/*", pid))
	if err != nil {
		return nil
	}
	var out []Thread
	for _, d := range dirs {
		tid, err := strconv.Atoi(filepath.Base(d))
		if err != nil {
			continue
		}
		pol, rt, cpu, ok := procStat(d + "/stat")
		if !ok {
			continue
		}
		aff := ""
		for _, line := range strings.Split(readFile(d+"/status"), "\n") {
			if strings.HasPrefix(line, "Cpus_allowed_list:") {
				aff = strings.TrimSpace(strings.TrimPrefix(line, "Cpus_allowed_list:"))
			}
		}
		out = append(out, Thread{
			TID: tid, Policy: policyName(pol), RTPrio: rt,
			LastCPU: cpu, Affinity: aff,
			// The audio thread is the one confined to the isolated core.
			Audio: aff == "1",
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].TID < out[j].TID })
	return out
}

// pidOf finds a process by name without pgrep, which busybox here does not have.
func pidOf(name string) int {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return 0
	}
	for _, e := range entries {
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		if strings.TrimSpace(readFile(fmt.Sprintf("/proc/%d/comm", pid))) == name {
			return pid
		}
	}
	return 0
}

// throttleCeiling is the fraction of a core a realtime task may use before the
// kernel deschedules it. Reading it rather than assuming 0.95 matters, because
// Moog tried to raise it and missed -- see defects().
func throttleCeiling() float64 {
	run, _ := strconv.ParseFloat(readFile("/proc/sys/kernel/sched_rt_runtime_us"), 64)
	per, _ := strconv.ParseFloat(readFile("/proc/sys/kernel/sched_rt_period_us"), 64)
	if per <= 0 || run <= 0 {
		return 0.95
	}
	return run / per
}

// rtThrottleEvents counts the times the kernel has forcibly descheduled the
// audio engine for exceeding its realtime budget, and when it last did so.
//
// Read from the syslog rather than assumed. The kernel ring buffer does not
// survive a reboot and the event is most interesting precisely when the
// instrument had to be restarted, so dmesg would report zero exactly when the
// answer matters most. /var/log/messages persists; messages.0 is the previous
// rotation and is scanned first so that "last" ends up chronological.
func rtThrottleEvents() (count int, last string) {
	for _, p := range []string{"/var/log/messages.0", "/var/log/messages"} {
		for _, line := range strings.Split(readFile(p), "\n") {
			if !strings.Contains(line, "RT throttling activated") {
				continue
			}
			count++
			// Busybox syslog writes "Sep 11 21:30:25 host ..." -- the first
			// three fields are the timestamp.
			if f := strings.Fields(line); len(f) >= 3 {
				last = strings.Join(f[:3], " ")
			}
		}
	}
	return count, last
}

func diskUsage(mount, note string) Filesystem {
	var st syscall.Statfs_t
	if err := syscall.Statfs(mount, &st); err != nil {
		return Filesystem{Mount: mount, Note: note}
	}
	bs := uint64(st.Bsize) / 1024
	if bs == 0 {
		bs = 1
	}
	total, free := st.Blocks*bs, st.Bavail*bs
	used := 0.0
	if total > 0 {
		used = float64(total-free) / float64(total) * 100
	}
	return Filesystem{Mount: mount, TotalKB: total, FreeKB: free, UsedPct: used, Note: note}
}

// readIRQs pulls the lines that matter for audio out of /proc/interrupts.
//
// `sdma` is the interrupt that actually runs the audio transfer; `esai` has
// never fired on this instrument, which is worth showing because a plausible
// theory about display activity interfering with audio rested on it.
func readIRQs() []IRQ {
	var out []IRQ
	for _, line := range strings.Split(readFile("/proc/interrupts"), "\n") {
		f := strings.Fields(line)
		if len(f) < 3 {
			continue
		}
		name := f[len(f)-1]
		if name != "esai" && name != "sdma" {
			continue
		}
		var counts []uint64
		for _, s := range f[1:] {
			v, err := strconv.ParseUint(s, 10, 64)
			if err != nil {
				break
			}
			counts = append(counts, v)
		}
		out = append(out, IRQ{Name: name, Counts: counts})
	}
	return out
}

// defects reports faults the instrument does not tell you about.
func defects() []Defect {
	var out []Defect

	// Moog meant to raise the realtime throttle from 95% to 99.995%. A missing
	// slash in the init script wrote 999950 into a FILE at the filesystem root
	// called /sched_rt_runtime_us instead of into the sysctl of that name, which
	// still reads the kernel default. Confirmed live on 2026-09-09; the file is
	// recreated every boot.
	//
	// This was graded "info" on the stated grounds that throttling had "fired
	// zero times on this instrument". That was asserted, never checked, and
	// never true: the syslog records three activations, the most recent six
	// minutes before a lockup that needed a power cycle. The severity is now
	// decided by the log rather than by assumption.
	stray := readFile("/sched_rt_runtime_us")
	throttles, lastThrottle := rtThrottleEvents()
	hit := ""
	if throttles > 0 {
		hit = fmt.Sprintf(" The kernel has descheduled the audio engine %d time(s), "+
			"most recently %s -- so this ceiling is being reached, and raising it as "+
			"Moog intended would give the engine more room before the sound cuts out.",
			throttles, lastThrottle)
	} else {
		hit = " Nothing in the retained logs has reached the ceiling."
	}
	out = append(out, Defect{
		Title:    "realtime throttle left at the kernel default",
		Severity: map[bool]string{true: "warn", false: "info"}[throttles > 0],
		Present:  stray != "",
		Detail: fmt.Sprintf(
			"A missing slash in Moog's init script created a file at /sched_rt_runtime_us "+
				"containing %q instead of writing the sysctl, which still reads %s of %s. "+
				"Moog intended 99.995%%; the engine runs at 95%%.%s",
			stray,
			readFile("/proc/sys/kernel/sched_rt_runtime_us"),
			readFile("/proc/sys/kernel/sched_rt_period_us"),
			hit),
	})

	// The staging partition the firmware updater unpacks into. Measured at
	// 12.2 MiB of margin against a 1.8.2 image, which is not much.
	fwu := diskUsage("/mnt/fwu", "")
	if fwu.TotalKB > 0 {
		need := uint64(788 * 1024) // decrypted image + still-packed copy
		out = append(out, Defect{
			Title:    "firmware update staging margin",
			Severity: map[bool]string{true: "warn", false: "info"}[fwu.FreeKB < need],
			Present:  true,
			Detail: fmt.Sprintf(
				"/mnt/fwu has %d MiB free; a 1.8.2 update stages about 788 MiB into it, "+
					"leaving roughly %d MiB spare.",
				fwu.FreeKB/1024, int64(fwu.FreeKB/1024)-int64(need/1024)),
		})
	}
	return out
}

func gather(scPort int) *Diagnostics {
	cores := perCore(300 * time.Millisecond)
	ceiling := throttleCeiling()
	audio := cores["cpu1"]

	d := &Diagnostics{
		AudioCoreBusy: audio,
		ThrottleAt:    ceiling,
		HeadroomPct:   (ceiling - audio) * 100,
		Cores:         cores,
		TempC:         tempC(),
		Threads:       scsynthThreads(),
		IRQs:          readIRQs(),
		Defects:       defects(),
		Version:       readFile("/etc/version"),
		Uptime:        strings.Fields(readFile("/proc/uptime") + " ")[0],
		Cmdline:       readFile("/proc/cmdline"),
		Disks: []Filesystem{
			diskUsage("/", "rootfs -- a firmware update replaces this entirely"),
			diskUsage("/var", "presets and calibration -- survives a firmware update"),
			diskUsage("/mnt/fwu", "firmware update staging"),
			diskUsage("/media/thumbdrive", "the USB drive this is running from"),
		},
	}
	d.RTThrottled, d.RTThrottledLast = rtThrottleEvents()
	if st, err := queryStatus(scPort, 2*time.Second); err == nil {
		d.Engine = st
	}
	return d
}

func diagHandler(scPort int) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		_ = enc.Encode(gather(scPort))
	}
}
