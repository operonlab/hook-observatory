package workshoplog

import (
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"time"
)

// RequestIDMiddleware extracts X-Request-ID from the incoming request (or generates a 12-hex one)
// and injects it into the request context. It also sets X-Request-ID on the response and
// logs request_start / request_end events via the supplied logger.
func RequestIDMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			rid := r.Header.Get("X-Request-ID")
			if !isValidRID(rid) {
				rid = newRID()
			}

			ctx := WithRequestID(r.Context(), rid)
			r = r.WithContext(ctx)
			w.Header().Set("X-Request-ID", rid)

			start := time.Now()
			logger.InfoContext(ctx, "request_start",
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
			)

			ww := &statusWriter{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(ww, r)

			logger.InfoContext(ctx, "request_end",
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
				slog.Int("status_code", ww.status),
				slog.Float64("duration_ms", float64(time.Since(start).Microseconds())/1000.0),
			)
		})
	}
}

func newRID() string {
	b := make([]byte, 6)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func isValidRID(rid string) bool {
	if len(rid) < 8 || len(rid) > 64 {
		return false
	}
	for _, c := range rid {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F') || c == '-' || c == '_') {
			return false
		}
	}
	return true
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(code int) {
	w.status = code
	w.ResponseWriter.WriteHeader(code)
}
