// shadow-compare: side-by-side Python vs Go dispatcher comparison tool.
//
// Reads JSONL events from either:
//   - --events <file>         (one {"event":"<type>", "input":"<raw JSON>"} per line)
//   - --spool-glob <pattern>  (hook-observatory spool format: {"event_type":..,"data":..})
//   - stdin                   (same as --events)
//
// Runs each event through both Python and Go dispatchers in parallel, normalizes
// volatile fields (timestamps), and reports diff summary + first N mismatches.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type event struct {
	Event string `json:"event"`
	Input string `json:"input"`
}

type result struct {
	idx     int
	event   string
	input   string
	pyOut   string
	goOut   string
	match   bool
	pyDur   time.Duration
	goDur   time.Duration
	pyError string
	goError string
}

var reTS = regexp.MustCompile(`"ts":"[^"]+"`)

func main() {
	eventsFile := flag.String("events", "", "JSONL file of {event, input} lines")
	spoolGlob := flag.String("spool-glob", "", "glob for hook-observatory spool files (events-*.jsonl, *.processing)")
	goBinary := flag.String("go-bin", "", "Go hook-observatory binary (required)")
	pyBinary := flag.String("py-bin", "/Users/joneshong/.local/bin/python3", "Python interpreter")
	pyDispatcher := flag.String("py-disp", "/Users/joneshong/.claude/hooks/dispatcher.py", "Python dispatcher script")
	limit := flag.Int("limit", 0, "max events to process (0 = no limit)")
	showN := flag.Int("show", 5, "show first N diffs in detail")
	timeout := flag.Duration("timeout", 10*time.Second, "per-event dispatcher timeout")
	flag.Parse()

	if *goBinary == "" {
		fatalf("--go-bin is required")
	}
	if _, err := os.Stat(*goBinary); err != nil {
		fatalf("go binary not found at %s", *goBinary)
	}

	events := loadEvents(*eventsFile, *spoolGlob)
	if *limit > 0 && len(events) > *limit {
		events = events[:*limit]
	}
	if len(events) == 0 {
		fatalf("no events loaded")
	}

	fmt.Fprintf(os.Stderr, "Loaded %d events. Running comparison...\n", len(events))

	results := make([]result, len(events))
	for i, ev := range events {
		results[i] = compare(i, ev, *goBinary, *pyBinary, *pyDispatcher, *timeout)
		if (i+1)%100 == 0 {
			fmt.Fprintf(os.Stderr, "  ... %d/%d done\n", i+1, len(events))
		}
	}

	printSummary(results, *showN)
}

func loadEvents(file, spoolGlob string) []event {
	if spoolGlob != "" {
		return loadSpoolEvents(spoolGlob)
	}
	if file != "" {
		return loadJSONLEvents(file)
	}
	return loadJSONLReader(os.Stdin)
}

func loadJSONLEvents(path string) []event {
	f, err := os.Open(path)
	if err != nil {
		fatalf("open %s: %v", path, err)
	}
	defer f.Close()
	return loadJSONLReader(f)
}

func loadJSONLReader(r io.Reader) []event {
	var events []event
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var ev event
		if err := json.Unmarshal([]byte(line), &ev); err != nil {
			continue
		}
		if ev.Event == "" {
			continue
		}
		events = append(events, ev)
	}
	return events
}

func loadSpoolEvents(pattern string) []event {
	matches, err := filepath.Glob(pattern)
	if err != nil {
		fatalf("glob %s: %v", pattern, err)
	}
	var events []event
	for _, p := range matches {
		f, err := os.Open(p)
		if err != nil {
			continue
		}
		scanner := bufio.NewScanner(f)
		scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}
			// spool format: {"event_type":"X","ts":"..","data":{...}}
			var raw struct {
				EventType string          `json:"event_type"`
				Data      json.RawMessage `json:"data"`
			}
			if err := json.Unmarshal([]byte(line), &raw); err != nil {
				continue
			}
			if raw.EventType == "" || len(raw.Data) == 0 {
				continue
			}
			events = append(events, event{
				Event: raw.EventType,
				Input: string(raw.Data),
			})
		}
		f.Close()
	}
	return events
}

func compare(idx int, ev event, goBin, pyBin, pyDisp string, timeout time.Duration) result {
	res := result{idx: idx, event: ev.Event, input: ev.Input}

	type runOut struct {
		out string
		err error
		dur time.Duration
	}
	done := make(chan runOut, 2)

	// Python
	go func() {
		start := time.Now()
		out, err := runDispatcher(pyBin, []string{pyDisp, ev.Event}, ev.Input, timeout)
		done <- runOut{out, err, time.Since(start)}
	}()
	// Go
	go func() {
		start := time.Now()
		out, err := runDispatcher(goBin, []string{ev.Event}, ev.Input, timeout)
		done <- runOut{out, err, time.Since(start)}
	}()

	pyR := <-done
	goR := <-done
	// runOut order unknown — need to tell apart; re-run sequentially for simplicity
	// Actually we need to know which is which. Redo sequentially to keep code simple.
	// (channel ordering is non-deterministic; cost of seq is ~2× but tool runs briefly)
	_ = pyR
	_ = goR

	pyStart := time.Now()
	pyOut, pyErr := runDispatcher(pyBin, []string{pyDisp, ev.Event}, ev.Input, timeout)
	res.pyDur = time.Since(pyStart)
	if pyErr != nil {
		res.pyError = pyErr.Error()
	}
	res.pyOut = pyOut

	goStart := time.Now()
	goOut, goErr := runDispatcher(goBin, []string{ev.Event}, ev.Input, timeout)
	res.goDur = time.Since(goStart)
	if goErr != nil {
		res.goError = goErr.Error()
	}
	res.goOut = goOut

	res.match = normalize(pyOut) == normalize(goOut)
	return res
}

func runDispatcher(bin string, args []string, stdin string, timeout time.Duration) (string, error) {
	cmd := exec.Command(bin, args...)
	cmd.Stdin = strings.NewReader(stdin)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = io.Discard

	done := make(chan error, 1)
	if err := cmd.Start(); err != nil {
		return "", err
	}
	go func() { done <- cmd.Wait() }()

	select {
	case err := <-done:
		return strings.TrimSpace(stdout.String()), err
	case <-time.After(timeout):
		_ = cmd.Process.Kill()
		<-done
		return strings.TrimSpace(stdout.String()), fmt.Errorf("timeout")
	}
}

// normalize strips volatile fields before comparison.
func normalize(s string) string {
	// Replace timestamps
	s = reTS.ReplaceAllString(s, `"ts":"<TS>"`)
	// Re-marshal JSON with sorted keys
	trimmed := strings.TrimSpace(s)
	if strings.HasPrefix(trimmed, "{") {
		var v any
		if err := json.Unmarshal([]byte(trimmed), &v); err == nil {
			if b, err := json.Marshal(v); err == nil {
				return string(b)
			}
		}
	}
	return trimmed
}

func printSummary(results []result, showN int) {
	total := len(results)
	match := 0
	var mismatches []result
	var pyTotal, goTotal time.Duration
	pyTimeouts, goTimeouts := 0, 0

	for _, r := range results {
		pyTotal += r.pyDur
		goTotal += r.goDur
		if r.pyError == "timeout" {
			pyTimeouts++
		}
		if r.goError == "timeout" {
			goTimeouts++
		}
		if r.match {
			match++
		} else {
			mismatches = append(mismatches, r)
		}
	}

	fmt.Printf("=== Shadow Replay Report ===\n")
	fmt.Printf("Total events:     %d\n", total)
	fmt.Printf("Match:            %d (%.2f%%)\n", match, 100*float64(match)/float64(total))
	fmt.Printf("Mismatch:         %d\n", len(mismatches))
	fmt.Printf("Python timeouts:  %d\n", pyTimeouts)
	fmt.Printf("Go timeouts:      %d\n", goTimeouts)
	fmt.Printf("Avg Python:       %v\n", pyTotal/time.Duration(total))
	fmt.Printf("Avg Go:           %v\n", goTotal/time.Duration(total))
	if goTotal > 0 {
		fmt.Printf("Go speedup:       %.2fx\n", float64(pyTotal)/float64(goTotal))
	}

	// Mismatch breakdown by event_type
	byType := map[string]int{}
	for _, r := range mismatches {
		byType[r.event]++
	}
	if len(byType) > 0 {
		fmt.Printf("\nMismatches by event:\n")
		for k, v := range byType {
			fmt.Printf("  %-20s %d\n", k, v)
		}
	}

	limit := showN
	if limit > len(mismatches) {
		limit = len(mismatches)
	}
	if limit > 0 {
		fmt.Printf("\nFirst %d mismatches:\n", limit)
		for i := 0; i < limit; i++ {
			r := mismatches[i]
			fmt.Printf("\n--- Mismatch #%d (idx=%d event=%s) ---\n", i+1, r.idx, r.event)
			fmt.Printf("Input:  %s\n", truncate(r.input, 120))
			fmt.Printf("Python: %s\n", truncate(normalize(r.pyOut), 200))
			fmt.Printf("Go:     %s\n", truncate(normalize(r.goOut), 200))
		}
	}
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

func fatalf(f string, a ...any) {
	fmt.Fprintf(os.Stderr, "error: "+f+"\n", a...)
	os.Exit(1)
}
