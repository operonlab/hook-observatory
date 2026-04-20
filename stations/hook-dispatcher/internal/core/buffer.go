package core

import (
	"bytes"
	"io"
	"strings"
)

// boundedBuffer caps the amount of data captured from a subprocess to avoid OOM.
type boundedBuffer struct {
	buf     bytes.Buffer
	limit   int
	dropped bool
}

func newBoundedBuffer(limit int) *boundedBuffer {
	return &boundedBuffer{limit: limit}
}

func (b *boundedBuffer) Write(p []byte) (int, error) {
	if b.dropped {
		return len(p), nil
	}
	remaining := b.limit - b.buf.Len()
	if remaining <= 0 {
		b.dropped = true
		return len(p), nil
	}
	if len(p) > remaining {
		b.buf.Write(p[:remaining])
		b.dropped = true
		return len(p), nil
	}
	return b.buf.Write(p)
}

func (b *boundedBuffer) String() string { return b.buf.String() }

func readerFromString(s string) io.Reader { return strings.NewReader(s) }
