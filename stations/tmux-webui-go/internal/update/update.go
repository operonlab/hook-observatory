// Package update implements self-update via GitHub Releases using minio/selfupdate.
package update

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"runtime"
	"strings"
	"time"

	"github.com/minio/selfupdate"
)

const ghReleasesURL = "https://api.github.com/repos/operonlab/tmux-webui/releases/latest"

type ghRelease struct {
	TagName string    `json:"tag_name"`
	Assets  []ghAsset `json:"assets"`
}

type ghAsset struct {
	Name               string `json:"name"`
	BrowserDownloadURL string `json:"browser_download_url"`
}

// LatestVersion fetches the latest release tag from GitHub without downloading.
func LatestVersion() (string, error) {
	rel, err := fetchRelease()
	if err != nil {
		return "", err
	}
	return strings.TrimPrefix(rel.TagName, "v"), nil
}

// Apply downloads the release binary for the current OS/arch and replaces the running binary.
func Apply() error {
	rel, err := fetchRelease()
	if err != nil {
		return err
	}

	tarName := fmt.Sprintf("tmux-webui_%s_%s.tar.gz", runtime.GOOS, runtime.GOARCH)
	checksumName := tarName + ".sha256"

	tarURL, checksumURL := "", ""
	for _, a := range rel.Assets {
		switch a.Name {
		case tarName:
			tarURL = a.BrowserDownloadURL
		case checksumName:
			checksumURL = a.BrowserDownloadURL
		}
	}
	if tarURL == "" {
		return fmt.Errorf("no release asset found for %s/%s (looking for %s)", runtime.GOOS, runtime.GOARCH, tarName)
	}

	fmt.Printf("Downloading %s ...\n", tarURL)
	tarData, err := httpGet(tarURL)
	if err != nil {
		return fmt.Errorf("download tarball: %w", err)
	}

	// Verify checksum if available.
	if checksumURL != "" {
		checksumData, err := httpGet(checksumURL)
		if err == nil {
			fields := strings.Fields(string(checksumData))
			if len(fields) > 0 {
				expected := fields[0]
				actual := fmt.Sprintf("%x", sha256.Sum256(tarData))
				if actual != expected {
					return fmt.Errorf("checksum mismatch: got %s, expected %s", actual, expected)
				}
				fmt.Println("Checksum verified.")
			}
		}
	}

	// Extract binary from tarball.
	binary, err := extractBinary(tarData)
	if err != nil {
		return fmt.Errorf("extract binary: %w", err)
	}

	fmt.Println("Applying update...")
	if err := selfupdate.Apply(bytes.NewReader(binary), selfupdate.Options{}); err != nil {
		return fmt.Errorf("selfupdate apply: %w", err)
	}
	fmt.Printf("Updated to %s. Restart tmux-webui to use the new version.\n", rel.TagName)
	return nil
}

func fetchRelease() (*ghRelease, error) {
	client := &http.Client{Timeout: 15 * time.Second}
	req, err := http.NewRequest("GET", ghReleasesURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github.v3+json")
	req.Header.Set("User-Agent", "tmux-webui-updater")

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetch release: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GitHub API returned %d", resp.StatusCode)
	}

	var rel ghRelease
	if err := json.NewDecoder(resp.Body).Decode(&rel); err != nil {
		return nil, fmt.Errorf("parse release JSON: %w", err)
	}
	return &rel, nil
}

func httpGet(url string) ([]byte, error) {
	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d from %s", resp.StatusCode, url)
	}
	return io.ReadAll(resp.Body)
}

func extractBinary(tarData []byte) ([]byte, error) {
	gr, err := gzip.NewReader(bytes.NewReader(tarData))
	if err != nil {
		return nil, err
	}
	defer gr.Close()

	tr := tar.NewReader(gr)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		// The binary is named "tmux-webui" (no extension) inside the tarball.
		if hdr.Name == "tmux-webui" || strings.HasSuffix(hdr.Name, "/tmux-webui") {
			return io.ReadAll(tr)
		}
	}
	return nil, fmt.Errorf("tmux-webui binary not found in tarball")
}
