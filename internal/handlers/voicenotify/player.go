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

// Play synthesises and plays a single TTS entry.
//
// Three-layer fallback with stations/tts as the primary entry point:
//
//  1. stations/tts `/synthesize`     — default engine=edge (zh-CN-YunjianNeural)
//  2. edge-tts CLI (local fallback)  — used only if the station is down
//  3. macOS `say` → afplay           — last resort if edge-tts CLI missing
//
// The station wraps edge-tts internally (stations/tts/engines/edge.py), so
// Go stays thin: one HTTP call, parse `{audio_path}`, afplay locally.
// Operators switch engines centrally via CLAUDE_TTS_ENGINE (default "edge")
// or CLAUDE_TTS_VOICE — the Go binary doesn't need to know anything about
// the engine catalogue.
func Play(e QueueEntry) {
	vol := e.Vol
	if vol == "" {
		vol = "0.3"
	}

	// 1) Workshop stations/tts (default: edge engine)
	if playStation(e.Text, vol) {
		return
	}

	// 2) Local edge-tts CLI fallback (used when the station is unreachable)
	voice := e.Voice
	if voice == "" {
		voice = Voice
	}
	rate := e.Rate
	if rate == "" {
		rate = Rate
	}
	if playEdgeTTS(e.Text, voice, rate, vol) {
		return
	}

	// 3) macOS `say` — truly offline fallback
	playSay(e.Text, vol)
}

// playEdgeTTS runs `edge-tts --voice ... --rate ... --text ... --write-media
// /tmp/claude-tts-play.mp3` then afplay. Returns true on success.
func playEdgeTTS(text, voice, rate, vol string) bool {
	if !which("edge-tts") {
		return false
	}
	tmp := "/tmp/claude-tts-play.mp3"
	_ = os.Remove(tmp)
	runCmd(15*time.Second, "edge-tts", "--voice", voice, "--rate", rate, "--text", text, "--write-media", tmp)
	info, err := os.Stat(tmp)
	if err != nil || info.Size() == 0 {
		return false
	}
	runCmd(30*time.Second, "afplay", "-v", vol, tmp)
	pushToWebui(tmp, text)
	return true
}

// playStation calls stations/tts `/synthesize` and afplay the returned
// audio_path. Honours CLAUDE_TTS_ENGINE / CLAUDE_TTS_VOICE env vars.
func playStation(text, vol string) bool {
	audioPath, ok := playViaService(text)
	if !ok || audioPath == "" {
		return false
	}
	runCmd(30*time.Second, "afplay", "-v", vol, audioPath)
	pushToWebui(audioPath, text)
	return true
}

// playSay is the last-resort `say -v Meijia` → afplay path. macOS-only.
func playSay(text, vol string) {
	if !which("say") {
		return
	}
	tmp := "/tmp/claude-tts-play.aiff"
	_ = os.Remove(tmp)
	runCmd(15*time.Second, "say", "-v", "Meijia", "-r", "320", "-o", tmp, text)
	info, err := os.Stat(tmp)
	if err != nil || info.Size() == 0 {
		return
	}
	runCmd(30*time.Second, "afplay", "-v", vol, tmp)
	pushToWebui(tmp, text)
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
