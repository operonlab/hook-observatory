// Package server — LayoutDB provides PostgreSQL-backed layout version persistence.
package server

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"time"

	_ "github.com/lib/pq" // PostgreSQL driver
)

// LayoutData holds the pixel-office grid configuration persisted per version.
type LayoutData struct {
	GridWidth  int             `json:"grid_width"`
	GridHeight int             `json:"grid_height"`
	Furniture  []FurnitureItem `json:"furniture"`
	Seats      []SeatItem      `json:"seats"`
	RestZone   RestZoneData    `json:"rest_zone"`
	DoorX      int             `json:"door_x"`
	DoorY      int             `json:"door_y"`
}

// FurnitureItem represents a single piece of furniture on the pixel grid.
type FurnitureItem struct {
	Type     string `json:"type"`
	TileX    int    `json:"tileX"`
	TileY    int    `json:"tileY"`
	W        int    `json:"w"`
	H        int    `json:"h"`
	Rotation int    `json:"rotation,omitempty"`
}

// SeatItem represents an agent seat on the pixel grid.
type SeatItem struct {
	TileX     int    `json:"tileX"`
	TileY     int    `json:"tileY"`
	Direction string `json:"direction"`
}

// RestZoneData holds the rest area seat positions.
type RestZoneData struct {
	Seats []struct {
		X int `json:"x"`
		Y int `json:"y"`
	} `json:"seats"`
}

// LayoutVersionRow is a single row returned from the layout_versions table.
type LayoutVersionRow struct {
	ID         int        `json:"id"`
	LayoutName string     `json:"layout_name"`
	Version    int        `json:"version"`
	Data       LayoutData `json:"data"`
	CreatedAt  time.Time  `json:"created_at"`
}

// LayoutDB manages PostgreSQL-backed layout version storage.
type LayoutDB struct {
	db *sql.DB
}

// NewLayoutDB opens a PostgreSQL connection, runs the embedded migration,
// and returns a ready-to-use LayoutDB.
func NewLayoutDB(connStr string) (*LayoutDB, error) {
	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("layoutdb: open connection: %w", err)
	}

	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("layoutdb: ping: %w", err)
	}

	ldb := &LayoutDB{db: db}
	if err := ldb.migrate(); err != nil {
		db.Close()
		return nil, fmt.Errorf("layoutdb: migrate: %w", err)
	}

	log.Println("[layoutdb] connected and migrated")
	return ldb, nil
}

// migrate runs the embedded DDL to create tables and indices if they do not exist.
func (ldb *LayoutDB) migrate() error {
	const ddl = `
CREATE TABLE IF NOT EXISTS layout_versions (
  id SERIAL PRIMARY KEY,
  layout_name VARCHAR(100) NOT NULL DEFAULT 'default',
  version INT NOT NULL,
  grid_width INT NOT NULL,
  grid_height INT NOT NULL,
  furniture JSONB NOT NULL,
  seats JSONB NOT NULL,
  rest_zone JSONB NOT NULL,
  door_x INT NOT NULL,
  door_y INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(layout_name, version)
);

CREATE INDEX IF NOT EXISTS idx_layout_versions_latest
  ON layout_versions(layout_name, version DESC);
`
	_, err := ldb.db.Exec(ddl)
	return err
}

// GetLatest returns the most recent layout version for the given name,
// or (nil, nil) when no version exists yet.
func (ldb *LayoutDB) GetLatest(layoutName string) (*LayoutVersionRow, error) {
	const q = `
SELECT id, layout_name, version, grid_width, grid_height,
       furniture, seats, rest_zone, door_x, door_y, created_at
FROM layout_versions
WHERE layout_name = $1
ORDER BY version DESC
LIMIT 1`

	row := ldb.db.QueryRow(q, layoutName)
	return scanLayoutRow(row)
}

// SaveVersion inserts a new version row (auto-incrementing the version number)
// and returns the inserted row.
func (ldb *LayoutDB) SaveVersion(layoutName string, data LayoutData) (*LayoutVersionRow, error) {
	furnitureJSON, err := json.Marshal(data.Furniture)
	if err != nil {
		return nil, fmt.Errorf("layoutdb: marshal furniture: %w", err)
	}
	seatsJSON, err := json.Marshal(data.Seats)
	if err != nil {
		return nil, fmt.Errorf("layoutdb: marshal seats: %w", err)
	}
	restZoneJSON, err := json.Marshal(data.RestZone)
	if err != nil {
		return nil, fmt.Errorf("layoutdb: marshal rest_zone: %w", err)
	}

	const q = `
INSERT INTO layout_versions
  (layout_name, version, grid_width, grid_height, furniture, seats, rest_zone, door_x, door_y)
VALUES
  ($1,
   COALESCE((SELECT MAX(version) FROM layout_versions WHERE layout_name = $1), 0) + 1,
   $2, $3, $4, $5, $6, $7, $8)
RETURNING id, layout_name, version, grid_width, grid_height,
          furniture, seats, rest_zone, door_x, door_y, created_at`

	row := ldb.db.QueryRow(q,
		layoutName,
		data.GridWidth, data.GridHeight,
		string(furnitureJSON), string(seatsJSON), string(restZoneJSON),
		data.DoorX, data.DoorY,
	)
	return scanLayoutRow(row)
}

// ListVersions returns up to limit recent versions for the given layout name,
// ordered newest first.
func (ldb *LayoutDB) ListVersions(layoutName string, limit int) ([]LayoutVersionRow, error) {
	const q = `
SELECT id, layout_name, version, grid_width, grid_height,
       furniture, seats, rest_zone, door_x, door_y, created_at
FROM layout_versions
WHERE layout_name = $1
ORDER BY version DESC
LIMIT $2`

	rows, err := ldb.db.Query(q, layoutName, limit)
	if err != nil {
		return nil, fmt.Errorf("layoutdb: list versions: %w", err)
	}
	defer rows.Close()

	var result []LayoutVersionRow
	for rows.Next() {
		row, err := scanLayoutRowFromRows(rows)
		if err != nil {
			return nil, fmt.Errorf("layoutdb: scan row: %w", err)
		}
		result = append(result, *row)
	}
	return result, rows.Err()
}

// GetVersion returns a specific version of the named layout.
func (ldb *LayoutDB) GetVersion(layoutName string, version int) (*LayoutVersionRow, error) {
	const q = `
SELECT id, layout_name, version, grid_width, grid_height,
       furniture, seats, rest_zone, door_x, door_y, created_at
FROM layout_versions
WHERE layout_name = $1 AND version = $2`

	row := ldb.db.QueryRow(q, layoutName, version)
	return scanLayoutRow(row)
}

// Close releases the underlying database connection pool.
func (ldb *LayoutDB) Close() error {
	return ldb.db.Close()
}

// scanLayoutRow scans a single *sql.Row into a LayoutVersionRow.
// Returns (nil, nil) when the row is not found (sql.ErrNoRows).
func scanLayoutRow(row *sql.Row) (*LayoutVersionRow, error) {
	var r LayoutVersionRow
	var furnitureJSON, seatsJSON, restZoneJSON string

	err := row.Scan(
		&r.ID, &r.LayoutName, &r.Version,
		&r.Data.GridWidth, &r.Data.GridHeight,
		&furnitureJSON, &seatsJSON, &restZoneJSON,
		&r.Data.DoorX, &r.Data.DoorY,
		&r.CreatedAt,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	if err := json.Unmarshal([]byte(furnitureJSON), &r.Data.Furniture); err != nil {
		return nil, fmt.Errorf("layoutdb: unmarshal furniture: %w", err)
	}
	if err := json.Unmarshal([]byte(seatsJSON), &r.Data.Seats); err != nil {
		return nil, fmt.Errorf("layoutdb: unmarshal seats: %w", err)
	}
	if err := json.Unmarshal([]byte(restZoneJSON), &r.Data.RestZone); err != nil {
		return nil, fmt.Errorf("layoutdb: unmarshal rest_zone: %w", err)
	}

	return &r, nil
}

// scanLayoutRowFromRows scans a single row from *sql.Rows into a LayoutVersionRow.
func scanLayoutRowFromRows(rows *sql.Rows) (*LayoutVersionRow, error) {
	var r LayoutVersionRow
	var furnitureJSON, seatsJSON, restZoneJSON string

	err := rows.Scan(
		&r.ID, &r.LayoutName, &r.Version,
		&r.Data.GridWidth, &r.Data.GridHeight,
		&furnitureJSON, &seatsJSON, &restZoneJSON,
		&r.Data.DoorX, &r.Data.DoorY,
		&r.CreatedAt,
	)
	if err != nil {
		return nil, err
	}

	if err := json.Unmarshal([]byte(furnitureJSON), &r.Data.Furniture); err != nil {
		return nil, fmt.Errorf("layoutdb: unmarshal furniture: %w", err)
	}
	if err := json.Unmarshal([]byte(seatsJSON), &r.Data.Seats); err != nil {
		return nil, fmt.Errorf("layoutdb: unmarshal seats: %w", err)
	}
	if err := json.Unmarshal([]byte(restZoneJSON), &r.Data.RestZone); err != nil {
		return nil, fmt.Errorf("layoutdb: unmarshal rest_zone: %w", err)
	}

	return &r, nil
}
