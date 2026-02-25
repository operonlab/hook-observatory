// Package web embeds the frontend build output for single-binary distribution.
package web

import "embed"

// DistFS holds the embedded frontend dist/ files.
// During development, dist/ contains only .gitkeep; in production builds,
// the Makefile copies the Vite build output here before `go build`.
//
//go:embed all:dist
var DistFS embed.FS
