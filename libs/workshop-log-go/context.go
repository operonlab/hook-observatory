package workshoplog

import "context"

// WithRequestID injects a request ID into context.
func WithRequestID(ctx context.Context, rid string) context.Context {
	return context.WithValue(ctx, requestIDKey, rid)
}

// RequestID retrieves the request ID from context.
func RequestID(ctx context.Context) string {
	if rid, ok := ctx.Value(requestIDKey).(string); ok {
		return rid
	}
	return ""
}

// WithUserID injects a user ID into context.
func WithUserID(ctx context.Context, uid string) context.Context {
	return context.WithValue(ctx, userIDKey, uid)
}

// WithSpaceID injects a space ID into context.
func WithSpaceID(ctx context.Context, sid string) context.Context {
	return context.WithValue(ctx, spaceIDKey, sid)
}
