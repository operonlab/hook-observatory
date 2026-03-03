# Memvault CLI

Command-line interface for the Memvault memory system.

## Install

```bash
# Symlink to PATH
ln -sf ~/workshop/stations/memvault-cli/memvault.py ~/.local/bin/memvault
chmod +x ~/workshop/stations/memvault-cli/memvault.py
```

## Usage

```bash
memvault health              # API health check
memvault recall "Python"     # Semantic search
memvault stats               # Memory statistics
memvault profile             # KAS profile
memvault cascade "learning"  # KG cascade recall
memvault wisdom              # Wisdom nodes
memvault attitude            # Current attitudes
memvault extract "fact" --type knowledge --tags "python,dev"
```

## Global Flags

```bash
memvault --json recall "Python"    # Raw JSON output
memvault --quiet stats             # Minimal output
memvault --api-url http://host:8801 health  # Override API URL
```

## Environment

- `MEMVAULT_API_URL` — Core API URL (default: http://localhost:8801)
- `MEMVAULT_SPACE_ID` — Space ID (default: default)
