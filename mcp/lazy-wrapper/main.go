// mcp-lazy-wrapper: On-demand MCP server lifecycle manager.
//
// Sits between mcpproxy and a real MCP server (stdio JSON-RPC).
// The wrapper stays alive (~2MB) while the real server is only spawned
// on first tools/call and killed after an idle timeout.
//
// Usage:
//
//	mcp-lazy-wrapper --name my-server --idle-timeout 1800 \
//	  --tools-cache tools_cache.json -- python3 server.py
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"
)

// State represents the server lifecycle state.
type State int

const (
	Dormant  State = iota // No subprocess
	Starting              // Spawning + initializing
	Active                // Proxying requests
)

func (s State) String() string {
	switch s {
	case Dormant:
		return "DORMANT"
	case Starting:
		return "STARTING"
	case Active:
		return "ACTIVE"
	default:
		return "UNKNOWN"
	}
}

// jsonRPCMsg is a minimal JSON-RPC 2.0 message.
type jsonRPCMsg struct {
	JSONRPC string           `json:"jsonrpc"`
	ID      *json.RawMessage `json:"id,omitempty"`
	Method  string           `json:"method,omitempty"`
	Params  json.RawMessage  `json:"params,omitempty"`
	Result  json.RawMessage  `json:"result,omitempty"`
	Error   json.RawMessage  `json:"error,omitempty"`
}

// isResponse returns true if the message is a response (has result or error, no method).
func (m *jsonRPCMsg) isResponse() bool {
	return m.Method == "" && m.ID != nil
}

// idString returns the ID as a comparable string.
func (m *jsonRPCMsg) idString() string {
	if m.ID == nil {
		return ""
	}
	return string(*m.ID)
}

// LazyWrapper manages the lifecycle of an MCP server.
type LazyWrapper struct {
	serverCmd   []string
	serverName  string
	idleTimeout time.Duration
	toolsCache  json.RawMessage // Cached tools/list result

	mu          sync.Mutex
	state       State
	proc        *exec.Cmd
	procStdin   io.WriteCloser
	lastActive  time.Time
	idCounter   int
	initParams  json.RawMessage

	// pending tracks internal request IDs waiting for server responses.
	pending   map[string]chan json.RawMessage
	pendingMu sync.Mutex

	// startupDone is closed when server initialization completes.
	startupDone chan struct{}

	// stdout writer (to mcpproxy)
	outMu sync.Mutex
}

func newLazyWrapper(cmd []string, name string, timeout time.Duration, cachePath string) *LazyWrapper {
	w := &LazyWrapper{
		serverCmd:   cmd,
		serverName:  name,
		idleTimeout: timeout,
		lastActive:  time.Now(),
		pending:     make(map[string]chan json.RawMessage),
		startupDone: make(chan struct{}),
	}

	if cachePath != "" {
		data, err := os.ReadFile(cachePath)
		if err == nil {
			w.toolsCache = data
			w.logf("Loaded tools cache from %s", cachePath)
		} else {
			w.logf("No tools cache: %v", err)
		}
	}

	return w
}

func (w *LazyWrapper) logf(format string, args ...any) {
	ts := time.Now().Format("15:04:05")
	msg := fmt.Sprintf(format, args...)
	fmt.Fprintf(os.Stderr, "[lazy:%s] [%s] %s\n", w.serverName, ts, msg)
}

func (w *LazyWrapper) writeStdout(msg any) {
	w.outMu.Lock()
	defer w.outMu.Unlock()
	data, err := json.Marshal(msg)
	if err != nil {
		w.logf("Marshal error: %v", err)
		return
	}
	os.Stdout.Write(data)
	os.Stdout.Write([]byte("\n"))
}

func (w *LazyWrapper) writeToServer(msg any) error {
	w.mu.Lock()
	stdin := w.procStdin
	w.mu.Unlock()

	if stdin == nil {
		return fmt.Errorf("server stdin not available")
	}

	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}
	_, err = stdin.Write(append(data, '\n'))
	return err
}

func (w *LazyWrapper) nextInternalID() string {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.idCounter++
	return fmt.Sprintf("\"__lazy_%d\"", w.idCounter)
}

// spawnServer starts the real MCP server and performs initialization.
func (w *LazyWrapper) spawnServer() error {
	w.mu.Lock()
	if w.state != Dormant {
		w.mu.Unlock()
		return nil
	}
	w.state = Starting
	w.startupDone = make(chan struct{})
	w.mu.Unlock()

	w.logf("Spawning: %s", strings.Join(w.serverCmd, " "))

	cmd := exec.Command(w.serverCmd[0], w.serverCmd[1:]...)
	cmd.Stderr = os.Stderr // Pass through stderr

	stdin, err := cmd.StdinPipe()
	if err != nil {
		w.setState(Dormant)
		return fmt.Errorf("stdin pipe: %w", err)
	}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		w.setState(Dormant)
		return fmt.Errorf("stdout pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		w.setState(Dormant)
		return fmt.Errorf("start: %w", err)
	}

	w.mu.Lock()
	w.proc = cmd
	w.procStdin = stdin
	w.mu.Unlock()

	// Start reading server stdout
	go w.readServerStdout(stdout)

	// Send initialize
	initID := w.nextInternalID()
	initParams := w.initParams
	if initParams == nil {
		initParams = json.RawMessage(`{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"mcp-lazy-wrapper","version":"1.0.0"}}`)
	}

	respCh := make(chan json.RawMessage, 1)
	w.pendingMu.Lock()
	w.pending[initID] = respCh
	w.pendingMu.Unlock()

	initReq := map[string]any{
		"jsonrpc": "2.0",
		"id":      json.RawMessage(initID),
		"method":  "initialize",
		"params":  json.RawMessage(initParams),
	}
	if err := w.writeToServer(initReq); err != nil {
		w.killServer()
		return fmt.Errorf("send initialize: %w", err)
	}

	// Wait for response
	select {
	case <-respCh:
		// OK
	case <-time.After(30 * time.Second):
		w.killServer()
		return fmt.Errorf("initialize timeout (30s)")
	}

	// Send initialized notification
	w.writeToServer(map[string]any{
		"jsonrpc": "2.0",
		"method":  "notifications/initialized",
	})

	w.mu.Lock()
	w.state = Active
	w.lastActive = time.Now()
	close(w.startupDone)
	w.mu.Unlock()

	w.logf("Server initialized and ACTIVE")
	return nil
}

func (w *LazyWrapper) setState(s State) {
	w.mu.Lock()
	w.state = s
	w.mu.Unlock()
}

func (w *LazyWrapper) killServer() {
	w.mu.Lock()
	proc := w.proc
	w.proc = nil
	w.procStdin = nil
	w.state = Dormant
	w.mu.Unlock()

	if proc != nil && proc.Process != nil {
		w.logf("Killing server")
		proc.Process.Signal(syscall.SIGTERM)
		done := make(chan error, 1)
		go func() { done <- proc.Wait() }()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			proc.Process.Kill()
			<-done
		}
	}

	// Cancel all pending
	w.pendingMu.Lock()
	for id, ch := range w.pending {
		close(ch)
		delete(w.pending, id)
	}
	w.pendingMu.Unlock()
}

func (w *LazyWrapper) readServerStdout(stdout io.ReadCloser) {
	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 1024*1024), 10*1024*1024) // 10MB max line

	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}

		var msg jsonRPCMsg
		if err := json.Unmarshal(line, &msg); err != nil {
			w.logf("Bad JSON from server: %s", string(line[:min(len(line), 100)]))
			continue
		}

		// Check if this is a response to an internal request
		if msg.isResponse() {
			idStr := msg.idString()
			w.pendingMu.Lock()
			ch, ok := w.pending[idStr]
			if ok {
				delete(w.pending, idStr)
			}
			w.pendingMu.Unlock()

			if ok {
				// Copy the raw line for the pending handler
				raw := make(json.RawMessage, len(line))
				copy(raw, line)
				select {
				case ch <- raw:
				default:
				}
				continue
			}
		}

		// Forward to mcpproxy
		w.outMu.Lock()
		os.Stdout.Write(line)
		os.Stdout.Write([]byte("\n"))
		w.outMu.Unlock()
	}

	// Server exited
	w.mu.Lock()
	if w.state == Active {
		w.logf("Server process exited")
		w.state = Dormant
	}
	w.mu.Unlock()
}

func (w *LazyWrapper) idleMonitor() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		w.mu.Lock()
		state := w.state
		elapsed := time.Since(w.lastActive)
		w.mu.Unlock()

		if state == Active && elapsed > w.idleTimeout {
			w.logf("Idle timeout (%v > %v)", elapsed.Round(time.Second), w.idleTimeout)
			w.killServer()
		}
	}
}

// makeToolsListResponse builds a tools/list response from cache.
func (w *LazyWrapper) makeToolsListResponse(id *json.RawMessage) map[string]any {
	tools := w.toolsCache
	if tools == nil {
		tools = json.RawMessage("[]")
	}
	return map[string]any{
		"jsonrpc": "2.0",
		"id":      id,
		"result":  json.RawMessage(fmt.Sprintf(`{"tools":%s}`, tools)),
	}
}

// makeErrorResponse builds a JSON-RPC error response.
func makeErrorResponse(id *json.RawMessage, code int, message string) map[string]any {
	return map[string]any{
		"jsonrpc": "2.0",
		"id":      id,
		"result":  nil,
		"error":   map[string]any{"code": code, "message": message},
	}
}

// forwardAndWait sends a message to the server and waits for the response.
func (w *LazyWrapper) forwardAndWait(raw json.RawMessage, id *json.RawMessage, timeout time.Duration) {
	if id == nil {
		// Notification — just forward
		w.writeToServer(json.RawMessage(raw))
		return
	}

	idStr := string(*id)
	respCh := make(chan json.RawMessage, 1)
	w.pendingMu.Lock()
	w.pending[idStr] = respCh
	w.pendingMu.Unlock()

	if err := w.writeToServer(json.RawMessage(raw)); err != nil {
		w.pendingMu.Lock()
		delete(w.pending, idStr)
		w.pendingMu.Unlock()
		w.writeStdout(makeErrorResponse(id, -32603, fmt.Sprintf("Failed to forward: %v", err)))
		return
	}

	select {
	case resp, ok := <-respCh:
		if ok {
			w.outMu.Lock()
			os.Stdout.Write(resp)
			os.Stdout.Write([]byte("\n"))
			w.outMu.Unlock()
		} else {
			w.writeStdout(makeErrorResponse(id, -32603, "Server disconnected"))
		}
	case <-time.After(timeout):
		w.pendingMu.Lock()
		delete(w.pending, idStr)
		w.pendingMu.Unlock()
		w.writeStdout(makeErrorResponse(id, -32603, fmt.Sprintf("Timeout (%v)", timeout)))
	}
}

func (w *LazyWrapper) handleMessage(raw json.RawMessage) {
	var msg jsonRPCMsg
	if err := json.Unmarshal(raw, &msg); err != nil {
		w.logf("Bad JSON from mcpproxy: %s", string(raw[:min(len(raw), 100)]))
		return
	}

	switch msg.Method {
	case "initialize":
		w.initParams = msg.Params
		w.writeStdout(map[string]any{
			"jsonrpc": "2.0",
			"id":      msg.ID,
			"result": map[string]any{
				"protocolVersion": "2024-11-05",
				"capabilities":    map[string]any{"tools": map[string]any{"listChanged": false}},
				"serverInfo":      map[string]any{"name": "lazy-" + w.serverName, "version": "1.0.0"},
			},
		})

	case "notifications/initialized":
		// Acknowledge silently

	case "ping":
		w.writeStdout(map[string]any{
			"jsonrpc": "2.0",
			"id":      msg.ID,
			"result":  map[string]any{},
		})

	case "tools/list":
		w.mu.Lock()
		state := w.state
		w.mu.Unlock()

		if state == Active {
			// Forward to real server, update cache
			w.forwardAndWait(raw, msg.ID, 10*time.Second)
		} else {
			// Return from cache (no spawn for polling)
			w.writeStdout(w.makeToolsListResponse(msg.ID))
		}

	case "tools/call":
		w.mu.Lock()
		w.lastActive = time.Now()
		state := w.state
		w.mu.Unlock()

		if state == Dormant {
			toolName := ""
			if msg.Params != nil {
				var p struct{ Name string }
				json.Unmarshal(msg.Params, &p)
				toolName = p.Name
			}
			w.logf("tools/call triggered spawn for: %s", toolName)

			if err := w.spawnServer(); err != nil {
				w.writeStdout(makeErrorResponse(msg.ID, -32603,
					fmt.Sprintf("Server %s failed to start: %v", w.serverName, err)))
				return
			}
		}

		if state == Starting {
			w.mu.Lock()
			done := w.startupDone
			w.mu.Unlock()
			select {
			case <-done:
			case <-time.After(30 * time.Second):
				w.writeStdout(makeErrorResponse(msg.ID, -32603,
					fmt.Sprintf("Server %s startup timeout", w.serverName)))
				return
			}
		}

		w.mu.Lock()
		state = w.state
		w.mu.Unlock()
		if state != Active {
			w.writeStdout(makeErrorResponse(msg.ID, -32603,
				fmt.Sprintf("Server %s not available", w.serverName)))
			return
		}

		w.forwardAndWait(raw, msg.ID, 120*time.Second)

	default:
		// Other methods: forward if active
		w.mu.Lock()
		state := w.state
		if state == Active {
			w.lastActive = time.Now()
		}
		w.mu.Unlock()

		if state == Active && msg.ID != nil {
			w.forwardAndWait(raw, msg.ID, 30*time.Second)
		} else if msg.ID != nil {
			w.writeStdout(makeErrorResponse(msg.ID, -32601,
				fmt.Sprintf("Method not available in dormant state: %s", msg.Method)))
		}
	}
}

func (w *LazyWrapper) run() {
	w.logf("Started (idle_timeout=%v, cache=%v)", w.idleTimeout, w.toolsCache != nil)

	go w.idleMonitor()

	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 0, 1024*1024), 10*1024*1024)

	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		raw := make(json.RawMessage, len(line))
		copy(raw, line)
		w.handleMessage(raw)
	}

	w.logf("stdin closed, shutting down")
	w.killServer()
}

func main() {
	name := flag.String("name", "unknown", "Server name for logging")
	idleTimeout := flag.Int("idle-timeout", 1800, "Idle timeout in seconds")
	toolsCache := flag.String("tools-cache", "", "Path to tools_cache.json")
	flag.Parse()

	// Everything after -- is the server command
	args := flag.Args()
	if len(args) == 0 {
		log.Fatal("No server command specified. Use: mcp-lazy-wrapper [flags] -- command args...")
	}
	// Strip leading --
	if args[0] == "--" {
		args = args[1:]
	}
	if len(args) == 0 {
		log.Fatal("No server command after --")
	}

	wrapper := newLazyWrapper(args, *name, time.Duration(*idleTimeout)*time.Second, *toolsCache)

	// Handle signals
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		sig := <-sigCh
		wrapper.logf("Received %v, shutting down", sig)
		wrapper.killServer()
		os.Exit(0)
	}()

	wrapper.run()
}
