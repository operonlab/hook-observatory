package voicenotify

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"strconv"
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
//  1. Workshop stations/tts HTTP POST /synthesize (query params → audio_path,
//     then afplay locally)
//  2. edge-tts CLI → afplay
//  3. macOS say → afplay
//
// Layer 1 is the intended path — stations/tts is the single entry point that
// multiplexes across engines (apple / qwen3-tts / kokoro / f5-tts / ...).
// Layers 2 and 3 only kick in when the station is unreachable.
func Play(e QueueEntry) {
	// Python consumer defaults to "0.3" when the queue entry omits vol,
	// so match that fallback here even though EnqueueTTS always populates
	// Vol from PlaybackVol ("0.4" by default).
	vol := e.Vol
	if vol == "" {
		vol = "0.3"
	}

	// 1) Workshop TTS station — returns a server-side audio_path we afplay.
	if audioPath, ok := playViaService(e.Text); ok && audioPath != "" {
		runCmd(30*time.Second, "afplay", "-v", vol, audioPath)
		pushToWebui(audioPath, e.Text)
		return
	}

	// 2) edge-tts → afplay (uses edge-tts voice + rate strings from env)
	voice := e.Voice
	if voice == "" {
		voice = Voice
	}
	rate := e.Rate
	if rate == "" {
		rate = Rate
	}
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

// playViaService POSTs /synthesize?text=...&voice=...&speed=...&engine=...
// and returns (audio_path, true) on success. Empty string + false on any
// failure so the caller can fall through to edge-tts / say.
func playViaService(text string) (string, bool) {
	if strings.TrimSpace(text) == "" {
		return "", false
	}

	// Rate strings ("+20%", "-10%") are an edge-tts convention; stations/tts
	// takes `speed` as a float multiplier. Convert when recognisable.
	speed := rateToSpeed(Rate)

	q := url.Values{}
	q.Set("text", text)
	q.Set("voice", TTSVoice)
	q.Set("speed", strconv.FormatFloat(speed, 'f', 3, 64))
	q.Set("engine", TTSEngine)
	q.Set("format", "wav")

	endpoint := TTSURL
	if strings.Contains(endpoint, "?") {
		endpoint += "&" + q.Encode()
	} else {
		endpoint += "?" + q.Encode()
	}

	req, err := http.NewRequest(http.MethodPost, endpoint, nil)
	if err != nil {
		return "", false
	}
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, resp.Body)
		return "", false
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", false
	}
	var parsed struct {
		AudioPath string `json:"audio_path"`
		Error     string `json:"error"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
		return "", false
	}
	if parsed.Error != "" || parsed.AudioPath == "" {
		return "", false
	}
	if _, err := os.Stat(parsed.AudioPath); err != nil {
		return "", false
	}
	return parsed.AudioPath, true
}

// rateToSpeed maps edge-tts rate strings ("+20%", "-10%") onto the float
// speed multiplier stations/tts expects. Unrecognised formats default to 1.0.
func rateToSpeed(rate string) float64 {
	s := strings.TrimSpace(rate)
	if s == "" {
		return 1.0
	}
	neg := false
	if strings.HasPrefix(s, "+") {
		s = s[1:]
	} else if strings.HasPrefix(s, "-") {
		neg = true
		s = s[1:]
	}
	s = strings.TrimSuffix(s, "%")
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 1.0
	}
	if neg {
		return 1.0 - v/100.0
	}
	return 1.0 + v/100.0
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

// parseFloatOr is kept for back-compat with any remaining callers that parse
// the vol string. Uses strconv directly now that we import it for rateToSpeed.
func parseFloatOr(s string, fallback float64) float64 {
	if v, err := strconv.ParseFloat(s, 64); err == nil {
		return v
	}
	return fallback
}
