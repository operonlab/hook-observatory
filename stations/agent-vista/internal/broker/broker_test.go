package broker

import (
	"sync"
	"testing"
	"time"

	"github.com/joneshong/agent-vista/internal/protocol"
)

func TestSubscribeAndPublish(t *testing.T) {
	b := New()
	_, ch := b.Subscribe(16)

	msg := protocol.WSMessage{
		Type:           protocol.WSTypeAgentOnline,
		AgentOfflineID: "test-agent",
	}
	b.Publish(msg)

	select {
	case got := <-ch:
		if got.Type != protocol.WSTypeAgentOnline {
			t.Errorf("want type %q, got %q", protocol.WSTypeAgentOnline, got.Type)
		}
		if got.AgentOfflineID != "test-agent" {
			t.Errorf("want AgentOfflineID %q, got %q", "test-agent", got.AgentOfflineID)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for message")
	}
}

func TestMultipleSubscribers(t *testing.T) {
	b := New()

	const numSubs = 3
	channels := make([]<-chan protocol.WSMessage, numSubs)
	for i := range numSubs {
		_, channels[i] = b.Subscribe(16)
	}

	msg := protocol.WSMessage{
		Type:           protocol.WSTypeAgentOffline,
		AgentOfflineID: "agent-42",
	}
	b.Publish(msg)

	for i, ch := range channels {
		select {
		case got := <-ch:
			if got.Type != protocol.WSTypeAgentOffline {
				t.Errorf("subscriber %d: want type %q, got %q", i, protocol.WSTypeAgentOffline, got.Type)
			}
			if got.AgentOfflineID != "agent-42" {
				t.Errorf("subscriber %d: want AgentOfflineID %q, got %q", i, "agent-42", got.AgentOfflineID)
			}
		case <-time.After(time.Second):
			t.Fatalf("subscriber %d: timed out waiting for message", i)
		}
	}
}

func TestUnsubscribe(t *testing.T) {
	b := New()
	id, ch := b.Subscribe(16)

	b.Unsubscribe(id)

	// Channel should be closed after unsubscribe.
	_, ok := <-ch
	if ok {
		t.Fatal("expected channel to be closed after unsubscribe")
	}

	// Publishing after unsubscribe must not panic.
	b.Publish(protocol.WSMessage{Type: protocol.WSTypeInit})
}

func TestPublishEventWrapsMessage(t *testing.T) {
	b := New()
	_, ch := b.Subscribe(16)

	evt := protocol.AgentEvent{
		CLIType:   protocol.CLIClaude,
		SessionID: "sess-1",
		AgentID:   "agent-1",
		Timestamp: time.Now(),
		EventType: protocol.EventToolStart,
		ToolName:  "Read",
	}
	b.PublishEvent(evt)

	select {
	case got := <-ch:
		if got.Type != protocol.WSTypeEvent {
			t.Errorf("want type %q, got %q", protocol.WSTypeEvent, got.Type)
		}
		if got.Event == nil {
			t.Fatal("expected Event field to be non-nil")
		}
		if got.Event.CLIType != protocol.CLIClaude {
			t.Errorf("want CLIType %q, got %q", protocol.CLIClaude, got.Event.CLIType)
		}
		if got.Event.SessionID != "sess-1" {
			t.Errorf("want SessionID %q, got %q", "sess-1", got.Event.SessionID)
		}
		if got.Event.ToolName != "Read" {
			t.Errorf("want ToolName %q, got %q", "Read", got.Event.ToolName)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for event message")
	}
}

func TestSlowSubscriberDropped(t *testing.T) {
	b := New()
	// Buffer size of 1: only 1 message can be buffered before drops.
	_, ch := b.Subscribe(1)

	// Publish 5 messages rapidly. The publisher must not block.
	done := make(chan struct{})
	go func() {
		for i := range 5 {
			b.Publish(protocol.WSMessage{
				Type:           protocol.WSTypeAgentOnline,
				AgentOfflineID: string(rune('0' + i)),
			})
		}
		close(done)
	}()

	select {
	case <-done:
		// Publisher did not block -- correct behavior.
	case <-time.After(time.Second):
		t.Fatal("publisher blocked on slow subscriber")
	}

	// Drain whatever is in the buffer (at least 1, at most 1).
	count := 0
	for {
		select {
		case <-ch:
			count++
		default:
			goto drained
		}
	}
drained:
	if count < 1 {
		t.Errorf("expected at least 1 buffered message, got %d", count)
	}
	if count > 1 {
		t.Errorf("expected at most 1 buffered message (bufSize=1), got %d", count)
	}
}

func TestSubscriberCount(t *testing.T) {
	b := New()

	if got := b.SubscriberCount(); got != 0 {
		t.Fatalf("initial count: want 0, got %d", got)
	}

	id1, _ := b.Subscribe(4)
	id2, _ := b.Subscribe(4)
	_, _ = b.Subscribe(4)

	if got := b.SubscriberCount(); got != 3 {
		t.Fatalf("after 3 subscribes: want 3, got %d", got)
	}

	b.Unsubscribe(id1)
	if got := b.SubscriberCount(); got != 2 {
		t.Fatalf("after 1 unsubscribe: want 2, got %d", got)
	}

	b.Unsubscribe(id2)
	if got := b.SubscriberCount(); got != 1 {
		t.Fatalf("after 2 unsubscribes: want 1, got %d", got)
	}

	// Unsubscribing a non-existent ID is a no-op.
	b.Unsubscribe(999)
	if got := b.SubscriberCount(); got != 1 {
		t.Fatalf("after no-op unsubscribe: want 1, got %d", got)
	}
}

func TestConcurrentPublish(t *testing.T) {
	b := New()
	const numGoroutines = 10
	const msgsPerGoroutine = 50
	_, ch := b.Subscribe(numGoroutines * msgsPerGoroutine)

	var wg sync.WaitGroup
	wg.Add(numGoroutines)

	for g := range numGoroutines {
		go func(id int) {
			defer wg.Done()
			for i := range msgsPerGoroutine {
				b.Publish(protocol.WSMessage{
					Type:           protocol.WSTypeEvent,
					AgentOfflineID: string(rune(id*1000 + i)),
				})
			}
		}(g)
	}

	wg.Wait()

	// Drain all received messages.
	received := 0
	for {
		select {
		case <-ch:
			received++
		default:
			goto done
		}
	}
done:
	expected := numGoroutines * msgsPerGoroutine
	if received != expected {
		t.Errorf("want %d messages, got %d", expected, received)
	}
}
