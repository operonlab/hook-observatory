.PHONY: build dev-backend dev-frontend test clean install-frontend build-frontend build-all

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "0.1.0-dev")
LDFLAGS := -ldflags "-X main.version=$(VERSION)"

# Build the Go binary (dev mode, no embedded frontend)
build:
	go build $(LDFLAGS) -o bin/agent-vista ./cmd/agent-vista

# Run Go backend in dev mode
dev-backend:
	go run ./cmd/agent-vista --verbose --no-browser

# Run React frontend dev server
dev-frontend:
	cd frontend && npm run dev

# Run all tests
test: test-backend test-frontend

test-backend:
	go test ./...

test-frontend:
	cd frontend && npm test

# Install frontend dependencies
install-frontend:
	cd frontend && npm install

# Build frontend for production
build-frontend:
	cd frontend && npm run build

# Build everything: frontend → embed → single Go binary
build-all: build-frontend
	rm -rf web/dist
	cp -r frontend/dist web/dist
	go build $(LDFLAGS) -o bin/agent-vista ./cmd/agent-vista
	@echo "Built bin/agent-vista ($(VERSION)) with embedded frontend"

# Clean build artifacts
clean:
	rm -rf bin/
	rm -rf frontend/dist/
	rm -rf web/dist
	mkdir -p web/dist && touch web/dist/.gitkeep
