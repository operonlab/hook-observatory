package handlers

import (
	"strings"
	"testing"
)

func TestMemorySyncParseFrontmatter(t *testing.T) {
	content := `---
name: test memory
type: user
description: "quoted desc"
---

Body line 1
Body line 2
`
	meta, body := memorySyncParseFrontmatter(content)
	if meta["name"] != "test memory" {
		t.Errorf("name: got %q", meta["name"])
	}
	if meta["type"] != "user" {
		t.Errorf("type: got %q", meta["type"])
	}
	if meta["description"] != "quoted desc" {
		t.Errorf("description: got %q", meta["description"])
	}
	if !strings.HasPrefix(body, "Body line 1") {
		t.Errorf("body: got %q", body)
	}
}

func TestMemorySyncParseFrontmatterNoHeader(t *testing.T) {
	content := "just body text\nno frontmatter"
	meta, body := memorySyncParseFrontmatter(content)
	if len(meta) != 0 {
		t.Errorf("expected empty meta, got %v", meta)
	}
	if !strings.HasPrefix(body, "just body") {
		t.Errorf("body: got %q", body)
	}
}

func TestMemorySyncIsMemoryFile(t *testing.T) {
	// Valid memory file
	cases := []struct {
		path string
		want bool
	}{
		{"/tmp/random.md", false},
		{"/nonexistent/path.md", false},
	}
	for _, c := range cases {
		if got := memorySyncIsMemoryFile(c.path); got != c.want {
			t.Errorf("%s: got %v, want %v", c.path, got, c.want)
		}
	}
}
