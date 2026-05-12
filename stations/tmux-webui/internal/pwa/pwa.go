// Package pwa serves the static frontend bundle (index.html, sw.js, manifest,
// icons, /static/*) from the embedded asset FS.
//
// The only Jinja directive in the original index.html is "{{ git_hash }}",
// used 4 times as a cache-busting query string. We replace at startup once
// and reuse the rendered bytes per request.
package pwa

import (
	"bytes"
	"io/fs"
	"net/http"
	"strings"

	"github.com/operonlab/tmux-webui/internal/assets"
	"github.com/operonlab/tmux-webui/internal/buildinfo"
)

// IndexHandler serves "/" with {{ git_hash }} replaced.
func IndexHandler() http.Handler {
	raw, err := fs.ReadFile(assets.FS, "templates/index.html")
	if err != nil {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			http.Error(w, "index.html missing from embed FS: "+err.Error(), http.StatusInternalServerError)
		})
	}
	body := []byte(strings.ReplaceAll(string(raw), "{{ git_hash }}", buildinfo.GitHash))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		_, _ = w.Write(body)
	})
}

// SwjsHandler serves "/sw.js" with __GIT_HASH__ replaced.
// Cache-Control: no-cache so iOS Safari notices SW updates.
func SwjsHandler() http.Handler {
	raw, err := fs.ReadFile(assets.FS, "sw.js")
	if err != nil {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			http.Error(w, "sw.js missing: "+err.Error(), http.StatusInternalServerError)
		})
	}
	body := bytes.ReplaceAll(raw, []byte("__GIT_HASH__"), []byte(buildinfo.GitHash))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/javascript")
		w.Header().Set("Cache-Control", "no-cache")
		_, _ = w.Write(body)
	})
}

// AssetFile serves a single embedded file with the given Content-Type.
func AssetFile(filename, contentType string) http.Handler {
	raw, err := fs.ReadFile(assets.FS, filename)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err != nil {
			http.Error(w, filename+" missing: "+err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", contentType)
		_, _ = w.Write(raw)
	})
}

// StaticFS serves "/static/..." from the embedded `static/` subtree.
func StaticFS() http.Handler {
	sub, err := fs.Sub(assets.FS, "static")
	if err != nil {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			http.Error(w, "static FS unavailable: "+err.Error(), http.StatusInternalServerError)
		})
	}
	return http.StripPrefix("/static/", http.FileServer(http.FS(sub)))
}
