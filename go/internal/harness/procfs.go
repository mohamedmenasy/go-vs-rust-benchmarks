package harness

import (
	"bufio"
	"os"
	"strconv"
	"strings"
	"syscall"
)

// memStatus reads VmRSS and VmHWM (in KiB) from /proc/self/status.
func memStatus() (rssKB, hwmKB int64) {
	f, err := os.Open("/proc/self/status")
	if err != nil {
		return -1, -1
	}
	defer f.Close()
	rssKB, hwmKB = -1, -1
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := sc.Text()
		switch {
		case strings.HasPrefix(line, "VmRSS:"):
			rssKB = parseKB(line)
		case strings.HasPrefix(line, "VmHWM:"):
			hwmKB = parseKB(line)
		}
	}
	return rssKB, hwmKB
}

func parseKB(line string) int64 {
	fields := strings.Fields(line)
	if len(fields) < 2 {
		return -1
	}
	n, err := strconv.ParseInt(fields[1], 10, 64)
	if err != nil {
		return -1
	}
	return n
}

// ThreadCount returns the number of OS threads of this process.
func ThreadCount() int64 {
	b, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return -1
	}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "Threads:") {
			return parseKB(line)
		}
	}
	return -1
}

type rusage struct {
	utimeNs, stimeNs, minflt, majflt, nvcsw, nivcsw int64
}

func getRusage() rusage {
	var ru syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &ru); err != nil {
		return rusage{}
	}
	return rusage{
		utimeNs: ru.Utime.Nano(),
		stimeNs: ru.Stime.Nano(),
		minflt:  ru.Minflt,
		majflt:  ru.Majflt,
		nvcsw:   ru.Nvcsw,
		nivcsw:  ru.Nivcsw,
	}
}

func (a rusage) delta(b rusage) map[string]int64 {
	return map[string]int64{
		"utime_ns": b.utimeNs - a.utimeNs,
		"stime_ns": b.stimeNs - a.stimeNs,
		"minflt":   b.minflt - a.minflt,
		"majflt":   b.majflt - a.majflt,
		"nvcsw":    b.nvcsw - a.nvcsw,
		"nivcsw":   b.nivcsw - a.nivcsw,
	}
}
