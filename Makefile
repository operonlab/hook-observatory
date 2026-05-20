.PHONY: build test vet fmt install clean bench

BIN := bin/hook-dispatcher
GIT_SHA := $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")
LDFLAGS := -s -w -X main.gitSHA=$(GIT_SHA)

build:
	@mkdir -p bin
	go build -ldflags="$(LDFLAGS)" -o $(BIN) ./cmd/hook-dispatcher

test:
	go test ./...

vet:
	go vet ./...

fmt:
	gofmt -d .

bench:
	go test -bench=. -benchmem ./...

install: build
	cp $(BIN) $(HOME)/.claude/hooks/hook-dispatcher
	@echo "Installed to $(HOME)/.claude/hooks/hook-dispatcher"

clean:
	rm -rf bin
