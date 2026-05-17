package workshoplog

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"
	"time"
)

type ctxKey string

const (
	requestIDKey ctxKey = "request_id"
	userIDKey    ctxKey = "user_id"
	spaceIDKey   ctxKey = "space_id"
)

// Init creates a slog.Logger writing JSON to /opt/homebrew/var/log/workshop/<service>/general.log
// (O_APPEND|O_CREATE|O_WRONLY; no rotation yet — TODO: add lumberjack rotation later)
// and mirrors text to stderr for launchd capture.
func Init(service string) *slog.Logger {
	logDir := filepath.Join("/opt/homebrew/var/log/workshop", service)
	_ = os.MkdirAll(logDir, 0o755)

	// TODO: replace with lumberjack for log rotation (MaxSize=10MB, MaxBackups=5)
	logPath := filepath.Join(logDir, "general.log")
	fileWriter, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		fileWriter = nil
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
