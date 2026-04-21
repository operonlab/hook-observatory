package voicenotify

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"mime"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
)

// QueueEntry mirrors the JSON line written to /tmp/claude-tts-queue.jsonl.
type QueueEntry struct {
	Text  string `json:"text"`
	Voice string `json:"voice"`
	Rate  string `json:"rate"`
	Vol   string `json:"vol"`
}

// Play synthesises and plays a single TTS entry. Three-layer fallback:
//  1. Workshop stations/tts HTTP POST (server handles playback)
//  2. edge-tts CLI → afplay
//  3. macOS say → afplay
func Play(e QueueEntry) {
	voice := e.Voice
	if voice == "" {
		voice = Voice
	}
	rate := e.Rate
	if rate == "" {
		rate = Rate
	}
	// Python consumer defaults to "0.3" when the queue entry omits vol,
	// so match that fallback here even though EnqueueTTS always populates
	// Vol from PlaybackVol ("0.4" by default).
	vol := e.Vol
	if vol == "" {
		vol = "0.3"
	}

	// 1) Workshop TTS service
	if playViaService(e.Text, voice, rate, vol) {
		pushToWebui("/tmp/claude-tts-play.mp3", e.Text)
		return
	}

	// 2) edge-tts → afplay
	if which("edge-tts") {
		tmp := "/tmp/claude-tts-play.mp3"
		runCmd(15*time.Second, "edge-tts", "--voice", voice, "--rate", rate, "--text", e.Text, "--write-media", tmp)
		runCmd(30*time.Second, "afplay", "-v", vol, tmp)
		pushToWebui(tmp, e.Text)
		return
	}

	// 3) macOS say → afplay
	if which("say") {
		tmp := "/tmp/claude-tts-play.aiff"
		runCmd(15*time.Second, "say", "-v", "Meijia", "-r", "320", "-o", tmp, e.Text)
		runCmd(30*time.Second, "afplay", "-v", vol, tmp)
		pushToWebui(tmp, e.Text)
	}
}

func playViaService(text, voice, rate, vol string) bool {
	payloadBytes, err := json.Marshal(map[string]any{
		"text":            text,
		"voice":           voice,
		"rate":            rate,
		"wait":            true,
		"playback_volume": parseFloatOr(vol, 0.3),
	})
	if err != nil {
		return false
	}
	req, err := http.NewRequest(http.MethodPost, TTSURL, bytes.NewReader(payloadBytes))
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	// Parity with Python: only count as success if Content-Type includes "json".
	mediaType, _, _ := mime.ParseMediaType(resp.Header.Get("Content-Type"))
	return strings.Contains(strings.ToLower(mediaType), "json")
}

func pushToWebui(path, text string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	b64 := base64.StdEncoding.EncodeToString(data)
	payload, err := json.Marshal(map[string]any{"audio": b64, "text": text})
	if err != nil {
		return
	}
	req, err := http.NewRequest(http.MethodPost, strings.TrimRight(WebuiURL, "/")+"/api/tts/push", bytes.NewReader(payload))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return
	}
	_ = resp.Body.Close()
}

// runCmd runs a command with a timeout, discarding stdout/stderr. Errors are
// silent — TTS never blocks or crashes the hook.
func runCmd(timeout time.Duration, name string, args ...string) {
	cmd := exec.Command(name, args...)
	cmd.Stdout = nil
	cmd.Stderr = nil
	if err := cmd.Start(); err != nil {
		return
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case <-time.After(timeout):
		_ = cmd.Process.Kill()
		<-done
	case <-done:
	}
}

func which(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}

func parseFloatOr(s string, fallback float64) float64 {
	var v float64
	if _, err := jsonUnmarshalFloat(s, &v); err == nil {
		return v
	}
	return fallback
}

// jsonUnmarshalFloat is a tiny helper to reuse the JSON number parser so we
// don't pull in strconv for every call path.
func jsonUnmarshalFloat(s string, out *float64) (bool, error) {
	b := append([]byte(nil), []byte(s)...)
	if err := json.Unmarshal(b, out); err != nil {
		return false, err
	}
	return true, nil
}
