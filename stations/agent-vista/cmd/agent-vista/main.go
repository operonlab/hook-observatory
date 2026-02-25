package main

import (
	"context"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/joneshong/agent-vista/internal/broker"
	"github.com/joneshong/agent-vista/internal/discovery"
	"github.com/joneshong/agent-vista/internal/parser"
	claudeparser "github.com/joneshong/agent-vista/internal/parser/claude"
	codexparser "github.com/joneshong/agent-vista/internal/parser/codex"
	geminiparser "github.com/joneshong/agent-vista/internal/parser/gemini"
	"github.com/joneshong/agent-vista/internal/protocol"
	"github.com/joneshong/agent-vista/internal/server"
	"github.com/joneshong/agent-vista/internal/watcher"
	"github.com/joneshong/agent-vista/web"
)

var (
	version = "0.1.0-dev"
)

func main() {
	configPath := flag.String("config", "", "TOML config file path (default: ~/.agent-vista/config.toml)")
	port := flag.Int("port", 0, "HTTP/WS listen port (overrides config)")
	noBrowser := flag.Bool("no-browser", false, "don't auto-open browser (overrides config)")
	watchFiles := flag.String("watch", "", "comma-separated transcript files to watch (for testing)")
	dbURL := flag.String("db", "", "PostgreSQL DSN for layout persistence (overrides config, e.g. postgres://user:pass@localhost/dbname?sslmode=disable)")
	verbose := flag.Bool("verbose", false, "verbose logging (overrides config)")
	showVersion := flag.Bool("version", false, "show version and exit")
	flag.Parse()

	if *showVersion {
		fmt.Println("agent-vista", version)
		os.Exit(0)
	}

	// Resolve config path
	if *configPath == "" {
		home, _ := os.UserHomeDir()
		*configPath = home + "/.agent-vista/config.toml"
	}

	// Load TOML config (falls back to defaults if file missing)
	cfg, err := server.LoadConfig(*configPath)
	if err != nil {
		log.Fatalf("failed to load config: %v", err)
	}

	// CLI flags override config values (only when explicitly set)
	flag.Visit(func(f *flag.Flag) {
		switch f.Name {
		case "port":
			cfg.Port = *port
		case "verbose":
			cfg.Verbose = *verbose
		case "no-browser":
			cfg.NoBrowser = *noBrowser
		case "db":
			cfg.DatabaseURL = *dbURL
		}
	})

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// Event broker: fan-out parsed events to all WS clients
	b := broker.New()

	// Resolve embedded frontend FS (nil if dist is empty / dev mode)
	var frontendFS fs.FS
	if sub, err := fs.Sub(web.DistFS, "dist"); err == nil {
		// Check if the embedded dist has an index.html (i.e., production build)
		if _, err := fs.Stat(sub, "index.html"); err == nil {
			frontendFS = sub
			log.Println("[server] embedded frontend detected")
		}
	}

	// HTTP/WS server (create early so tracker is available for event callback)
	addr := fmt.Sprintf(":%d", cfg.Port)
	srv := server.New(b, addr, cfg.Verbose, frontendFS)
	tracker := srv.Tracker()

	// Optional PostgreSQL layout persistence
	if cfg.DatabaseURL != "" {
		ldb, err := server.NewLayoutDB(cfg.DatabaseURL)
		if err != nil {
			log.Printf("[layoutdb] warning: failed to connect (%v) — running without DB", err)
		} else {
			srv.SetLayoutDB(ldb)
			defer ldb.Close()
			if cfg.Verbose {
				log.Printf("[layoutdb] layout persistence enabled")
			}
		}
	}

	// File watcher: monitors transcripts and feeds parsed events to broker + tracker
	eventCount := 0
	w, watcherErr := watcher.New(func(evt protocol.AgentEvent) {
		eventCount++
		if cfg.Verbose {
			log.Printf("[event #%d] %s %s/%s tool=%s",
				eventCount, evt.EventType, evt.CLIType, evt.SessionID, evt.ToolName)
		}
		newAgent := tracker.HandleEvent(evt)
		if newAgent != nil {
			b.Publish(protocol.WSMessage{
				Type:        protocol.WSTypeAgentOnline,
				AgentOnline: newAgent,
			})
		}
		b.PublishEvent(evt)
	}, cfg.Verbose)
	if watcherErr != nil {
		log.Fatalf("failed to create watcher: %v", watcherErr)
	}

	// Register parser factories for all three CLIs
	w.RegisterParserFactory(func() parser.TranscriptParser {
		return claudeparser.New()
	})
	w.RegisterParserFactory(func() parser.TranscriptParser {
		return codexparser.New()
	})
	w.RegisterParserFactory(func() parser.TranscriptParser {
		return geminiparser.New()
	})

	// Watch specified files (--watch flag for testing)
	if *watchFiles != "" {
		for _, path := range strings.Split(*watchFiles, ",") {
			path = strings.TrimSpace(path)
			if path == "" {
				continue
			}
			if err := w.WatchFile(path); err != nil {
				log.Fatalf("failed to watch %s: %v", path, err)
			}
		}
	}

	// Session discovery: auto-scan for active CLI transcripts
	discInterval := time.Duration(cfg.Discovery.IntervalSec) * time.Second
	if cfg.Discovery.Enabled {
		disc := discovery.New(discInterval, func(path string) {
			if err := w.WatchFile(path); err != nil {
				log.Printf("[discovery] failed to watch %s: %v", path, err)
			}
		}, cfg.Verbose)
		go func() {
			if err := disc.Start(ctx); err != nil && err != context.Canceled {
				log.Printf("[discovery] stopped: %v", err)
			}
		}()
	}

	// Start watcher goroutine
	go func() {
		if err := w.Start(ctx); err != nil && err != context.Canceled {
			log.Printf("[watcher] stopped: %v", err)
		}
	}()

	// Start process monitor: resource usage at configured interval
	if cfg.Monitor.Enabled {
		monInterval := time.Duration(cfg.Monitor.IntervalSec) * time.Second
		pm := server.NewProcessMonitor(b, monInterval, cfg.Verbose)
		srv.SetProcessMonitor(pm)
		go pm.Start(ctx)
	}

	// Stale agent sweep: mark idle agents as resting, then offline
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		const activeMs = 20 * 60 * 1000 // 20 min
		const restingMs = 60 * 60 * 1000 // 60 min
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				offlined := tracker.SweepStale(activeMs, restingMs)
				for _, id := range offlined {
					b.Publish(protocol.WSMessage{
						Type:           protocol.WSTypeAgentOffline,
						AgentOfflineID: id,
					})
				}
			}
		}
	}()

	log.Printf("agent-vista %s ready (port=%d, verbose=%v, watching=%d files)",
		version, cfg.Port, cfg.Verbose, len(w.WatchedFiles()))

	// Auto-open browser (after short delay to let server start)
	if !cfg.NoBrowser {
		go func() {
			time.Sleep(300 * time.Millisecond)
			url := fmt.Sprintf("http://localhost:%d", cfg.Port)
			openBrowser(url)
		}()
	}

	if err := srv.Start(ctx); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}

	log.Println("agent-vista stopped")
}

// openBrowser opens the given URL in the default system browser.
func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "linux":
		cmd = exec.Command("xdg-open", url)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	default:
		return
	}
	if err := cmd.Start(); err != nil {
		log.Printf("[browser] failed to open: %v", err)
	}
}
