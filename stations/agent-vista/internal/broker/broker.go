// Package broker implements event fan-out from parsers to WebSocket clients.
package broker

import (
	"sync"

	"github.com/joneshong/agent-vista/internal/protocol"
)

// Broker fans out WSMessages to all registered subscribers.
// Thread-safe for concurrent Publish and Subscribe/Unsubscribe.
type Broker struct {
	mu     sync.RWMutex
	subs   map[uint64]chan protocol.WSMessage
	nextID uint64
}

// New creates a new event broker.
func New() *Broker {
	return &Broker{
		subs: make(map[uint64]chan protocol.WSMessage),
	}
}

// Subscribe registers a new subscriber and returns its ID + receive channel.
// bufSize controls the channel buffer; slow subscribers will have messages dropped.
func (b *Broker) Subscribe(bufSize int) (uint64, <-chan protocol.WSMessage) {
	b.mu.Lock()
	defer b.mu.Unlock()

	id := b.nextID
	b.nextID++
	ch := make(chan protocol.WSMessage, bufSize)
	b.subs[id] = ch
	return id, ch
}

// Unsubscribe removes a subscriber and closes its channel.
func (b *Broker) Unsubscribe(id uint64) {
	b.mu.Lock()
	defer b.mu.Unlock()

	if ch, ok := b.subs[id]; ok {
		close(ch)
		delete(b.subs, id)
	}
}

// Publish sends a WSMessage to all subscribers (non-blocking).
// If a subscriber's buffer is full, the message is dropped for that subscriber.
func (b *Broker) Publish(msg protocol.WSMessage) {
	b.mu.RLock()
	defer b.mu.RUnlock()

	for _, ch := range b.subs {
		select {
		case ch <- msg:
		default:
			// Drop — don't block the publisher for slow subscribers
		}
	}
}

// PublishEvent wraps an AgentEvent in a WSMessage and publishes it.
func (b *Broker) PublishEvent(evt protocol.AgentEvent) {
	b.Publish(protocol.WSMessage{
		Type:  protocol.WSTypeEvent,
		Event: &evt,
	})
}

// SubscriberCount returns the current number of active subscribers.
func (b *Broker) SubscriberCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.subs)
}
