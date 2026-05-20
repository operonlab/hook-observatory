// Package portregistry exposes the Workshop port registry to Go consumers.
//
// This package was vendored from the Workshop monorepo's
// libs/go-port-registry/ into hook-observatory's internal tree so the
// external operonlab/hook-observatory repo can build self-contained
// without depending on the monorepo. Keep ports.go in lock-step manually
// when upstream re-runs `go generate ./...`.
//
// Usage:
//
//	import portregistry "github.com/joneshong/hook-observatory/internal/portregistry"
//
//	if svc, ok := portregistry.Get("core"); ok {
//	    fmt.Println(svc.URL())                  // "http://127.0.0.1:10000"
//	    fmt.Println(svc.HealthURL())            // "http://127.0.0.1:10000/health"
//	}
//
//	// Convenience: build a URL with a path, falling back to a literal port
//	// if the service is absent (e.g. yaml lookup races during early boot).
//	base := portregistry.URL("tts", "/synthesize", 10201)
//	// "http://127.0.0.1:10201/synthesize"
package portregistry

import "fmt"

//go:generate go run ./cmd/gen

// ServicePort mirrors libs/sdk-client/sdk_client/port_registry.py:ServicePort
// and libs/port-registry/src/lib.rs:ServicePort. Keep the three definitions
// in lock-step.
type ServicePort struct {
	Name       string
	Port       uint16
	Group      string
	HealthPath string
	EnvVar     string
	NginxPath  string
	Optional   bool
}

// URL returns the service base URL: "http://{HOST}:{port}".
func (s ServicePort) URL() string {
	return fmt.Sprintf("http://%s:%d", Host, s.Port)
}

// HealthURL returns ("http://{HOST}:{port}{health_path}", true) or
// ("", false) when health_path is empty.
func (s ServicePort) HealthURL() (string, bool) {
	if s.HealthPath == "" {
		return "", false
	}
	return s.URL() + s.HealthPath, true
}

// Get looks up a service by registry name. Returns (nil, false) when the
// service is not present in the generated table.
func Get(name string) (*ServicePort, bool) {
	for i := range Ports {
		if Ports[i].Name == name {
			return &Ports[i], true
		}
	}
	return nil, false
}

// ByGroup returns all services in the given group, preserving registry order.
func ByGroup(group string) []ServicePort {
	out := make([]ServicePort, 0, 4)
	for _, p := range Ports {
		if p.Group == group {
			out = append(out, p)
		}
	}
	return out
}

// URL is a convenience helper for building a full URL. If `name` is in the
// registry, it uses the registered port (path is appended literally — caller
// supplies leading slash). If `name` is missing, it falls back to
// "http://{Host}:{fallbackPort}{path}" so the caller never panics on a
// registry miss — useful for ports not yet captured in yaml.
//
//	URL("tts", "/synthesize", 10201) → "http://127.0.0.1:10201/synthesize"
//	URL("unknown", "/x", 9999)       → "http://127.0.0.1:9999/x"
//
// path may be empty.
func URL(name, path string, fallbackPort uint16) string {
	port := fallbackPort
	if s, ok := Get(name); ok {
		port = s.Port
	}
	return fmt.Sprintf("http://%s:%d%s", Host, port, path)
}
