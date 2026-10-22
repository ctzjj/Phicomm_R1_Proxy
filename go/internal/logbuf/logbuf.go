// Package logbuf keeps the last N log lines and lets HTTP clients follow the
// log in real time (used by the embedded web console).
package logbuf

import (
	"strings"
	"sync"
)

const maxLines = 500

// Buffer is an io.Writer that keeps a ring of log lines.
type Buffer struct {
	mu    sync.Mutex
	lines []string
	subs  map[chan string]struct{}
	line  strings.Builder
}

// New returns an empty buffer.
func New() *Buffer {
	return &Buffer{subs: map[chan string]struct{}{}}
}

// Write implements io.Writer. Partial lines are assembled until a newline.
func (b *Buffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for _, c := range p {
		if c == '\n' {
			line := b.line.String()
			b.line.Reset()
			b.appendLocked(line)
			continue
		}
		b.line.WriteByte(c)
	}
	return len(p), nil
}

func (b *Buffer) appendLocked(line string) {
	b.lines = append(b.lines, line)
	if len(b.lines) > maxLines {
		b.lines = b.lines[len(b.lines)-maxLines:]
	}
	for ch := range b.subs {
		select {
		case ch <- line:
		default: // drop for slow clients
		}
	}
}

// Lines returns a copy of the current buffer.
func (b *Buffer) Lines() []string {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make([]string, len(b.lines))
	copy(out, b.lines)
	return out
}

// Subscribe returns a channel of new lines and an unsubscribe function.
func (b *Buffer) Subscribe() (<-chan string, func()) {
	ch := make(chan string, 64)
	b.mu.Lock()
	b.subs[ch] = struct{}{}
	b.mu.Unlock()
	return ch, func() {
		b.mu.Lock()
		if _, ok := b.subs[ch]; ok {
			delete(b.subs, ch)
			close(ch)
		}
		b.mu.Unlock()
	}
}
