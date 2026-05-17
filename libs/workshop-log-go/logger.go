package workshoplog

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// Rotation policy (matches Python RotatingFileHandler).
const (
	rotateMaxSize    int64 = 10 * 1024 * 1024 // 10 MB per file
	rotateMaxBackups       = 5                // keep general.log.1 ... general.log.5
)

// rotatingFile is a tiny size-based rotating writer (stdlib only, no external deps).
// Rotates by renaming: general.log -> general.log.1, .1 -> .2, ... oldest dropped.
type rotatingFile struct {
	mu      sync.Mutex
	path    string
	maxSize int64
	backups int
	file    *os.File
	size    int64
}

func newRotatingFile(path string, maxSize int64, backups int) (*rotatingFile, error) {
	rf := &rotatingFile{path: path, maxSize: maxSize, backups: backups}
	if err := rf.open(); err != nil {
		return nil, err
	}
	return rf, nil
}

func (rf *rotatingFile) open() error {
	f, err := os.OpenFile(rf.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	info, err := f.Stat()
	if err != nil {
		f.Close()
		return err
	}
	rf.file = f
	rf.size = info.Size()
	return nil
}

func (rf *rotatingFile) Write(p []byte) (int, error) {
	rf.mu.Lock()
	defer rf.mu.Unlock()
	if rf.file != nil && rf.size+int64(len(p)) > rf.maxSize {
		rf.rotateLocked()
	}
	if rf.file == nil {
		return len(p), nil // dropped — better than crash
	}
	n, err := rf.file.Write(p)
	rf.size += int64(n)
	return n, err
}

func (rf *rotatingFile) rotateLocked() {
	if rf.file != nil {
		_ = rf.file.Close()
		rf.file = nil
	}
	// Shift backups: .{n-1} -> .{n}, oldest dropped.
	oldest := fmt.Sprintf("%s.%d", rf.path, rf.backups)
	_ = os.Remove(oldest)
	for i := rf.backups - 1; i >= 1; i-- {
		from := fmt.Sprintf("%s.%d", rf.path, i)
		to := fmt.Sprintf("%s.%d", rf.path, i+1)
		_ = os.Rename(from, to)
	}
	_ = os.Rename(rf.path, rf.path+".1")
	// Reopen.
	_ = rf.open()
}

type ctxKey string

const (
	requestIDKey ctxKey = "request_id"
	userIDKey    ctxKey = "user_id"
	spaceIDKey   ctxKey = "space_id"
)

// Init creates a slog.Logger writing JSON to /opt/homebrew/var/log/workshop/<service>/general.log
// with size-based rotation (10 MB / 5 backups, matches Python RotatingFileHandler).
// Mirrors text to stderr for launchd capture.
func Init(service string) *slog.Logger {
	logDir := filepath.Join("/opt/homebrew/var/log/workshop", service)
	_ = os.MkdirAll(logDir, 0o755)

	logPath := filepath.Join(logDir, "general.log")
	rotating, err := newRotatingFile(logPath, rotateMaxSize, rotateMaxBackups)
	var fileWriter io.Writer
	if err == nil {
		fileWriter = rotating
	}

	handlerOpts := &slog.HandlerOptions{
		Level: slog.LevelInfo,
		ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
			switch a.Key {
			case slog.TimeKey:
				return slog.String("ts", a.Value.Time().Format(time.RFC3339Nano))
			case slog.LevelKey:
				return slog.String("level", a.Value.String())
			case slog.MessageKey:
				return slog.String("msg", a.Value.String())
			case slog.SourceKey:
				return slog.Attr{}
			}
			return a
		},
	}

	stderrHandler := slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo})

	var baseHandler slog.Handler
	if fileWriter != nil {
		fileHandler := slog.NewJSONHandler(fileWriter, handlerOpts)
		baseHandler = &multiHandler{handlers: []slog.Handler{fileHandler, stderrHandler}}
	} else {
		baseHandler = stderrHandler
	}

	contextual := &contextHandler{Handler: baseHandler}
	logger := slog.New(contextual).With(slog.String("service", service))
	slog.SetDefault(logger)
	return logger
}

type multiHandler struct {
	handlers []slog.Handler
}

func (m *multiHandler) Enabled(ctx context.Context, level slog.Level) bool {
	for _, h := range m.handlers {
		if h.Enabled(ctx, level) {
			return true
		}
	}
	return false
}

func (m *multiHandler) Handle(ctx context.Context, r slog.Record) error {
	for _, h := range m.handlers {
		_ = h.Handle(ctx, r)
	}
	return nil
}

func (m *multiHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	hs := make([]slog.Handler, len(m.handlers))
	for i, h := range m.handlers {
		hs[i] = h.WithAttrs(attrs)
	}
	return &multiHandler{handlers: hs}
}

func (m *multiHandler) WithGroup(name string) slog.Handler {
	hs := make([]slog.Handler, len(m.handlers))
	for i, h := range m.handlers {
		hs[i] = h.WithGroup(name)
	}
	return &multiHandler{handlers: hs}
}

type contextHandler struct {
	slog.Handler
}

func (c *contextHandler) Handle(ctx context.Context, r slog.Record) error {
	if rid, ok := ctx.Value(requestIDKey).(string); ok && rid != "" {
		r.AddAttrs(slog.String("request_id", rid))
	}
	if uid, ok := ctx.Value(userIDKey).(string); ok && uid != "" {
		r.AddAttrs(slog.String("user_id", uid))
	}
	if sid, ok := ctx.Value(spaceIDKey).(string); ok && sid != "" {
		r.AddAttrs(slog.String("space_id", sid))
	}
	return c.Handler.Handle(ctx, r)
}

func (c *contextHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &contextHandler{Handler: c.Handler.WithAttrs(attrs)}
}

func (c *contextHandler) WithGroup(name string) slog.Handler {
	return &contextHandler{Handler: c.Handler.WithGroup(name)}
}
