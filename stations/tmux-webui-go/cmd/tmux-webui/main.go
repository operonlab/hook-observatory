package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/operonlab/tmux-webui/internal/buildinfo"
	"github.com/operonlab/tmux-webui/internal/config"
	"github.com/operonlab/tmux-webui/internal/server"
	"github.com/operonlab/tmux-webui/internal/tmuxctl"
)

func main() {
	var (
		showVersion bool
		host        string
		port        int
		cfgPath     string
	)
	flag.BoolVar(&showVersion, "version", false, "print version and exit")
	flag.StringVar(&host, "host", "", "override config host")
	flag.IntVar(&port, "port", 0, "override config port")
	flag.StringVar(&cfgPath, "config", "", "config file path (default: ~/.config/tmux-webui/config.json)")
	flag.Parse()

	if showVersion {
		fmt.Println(buildinfo.String())
		return
	}

	cfg, err := config.Load(cfgPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "tmux-webui: config error:", err)
		os.Exit(1)
	}
	if host != "" {
		cfg.Host = host
	}
	if port != 0 {
		cfg.Port = port
	}

	tx := tmuxctl.New()
	srv := server.New(cfg, tx)

	addr := fmt.Sprintf("%s:%d", cfg.Host, cfg.Port)
	httpSrv := &http.Server{
		Addr:              addr,
		Handler:           srv.Mux(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	fmt.Printf("%s\n", buildinfo.String())
	fmt.Printf("→ http://%s\n", addr)
	fmt.Println("(Ctrl+C to stop)")

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	errCh := make(chan error, 1)
	go func() { errCh <- httpSrv.ListenAndServe() }()

	select {
	case <-ctx.Done():
		fmt.Println("\nshutting down...")
		shutdownCtx, sc := context.WithTimeout(context.Background(), 5*time.Second)
		defer sc()
		_ = httpSrv.Shutdown(shutdownCtx)
	case err := <-errCh:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			fmt.Fprintln(os.Stderr, "server error:", err)
			os.Exit(1)
		}
	}
}
