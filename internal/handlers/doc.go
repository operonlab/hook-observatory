// Package handlers hosts the Go implementations of hook handlers.
//
// Each handler lives in its own file and self-registers via init() by calling
// core.Register. The package-level blank import in cmd/hook-observatory/main.go
// triggers these init functions at binary startup.
package handlers
