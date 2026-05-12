package tmuxctl

// JSON tags match the wire shape produced by the Python implementation
// so the existing frontend (workbench/static/js/app.js) keeps working
// against the Go backend without modification.

type Session struct {
	Name     string `json:"name"`
	Windows  int    `json:"windows"`
	Attached int    `json:"attached"`
}

type Window struct {
	Index  int    `json:"index"`
	Name   string `json:"name"`
	Active int    `json:"active"`
	Panes  int    `json:"panes"`
}

type Pane struct {
	Window     int    `json:"window"`
	WindowName string `json:"window_name"`
	Pane       int    `json:"pane"`
	Active     int    `json:"active"`
	Width      int    `json:"width"`
	Height     int    `json:"height"`
	Command    string `json:"command"`
	Title      string `json:"title"`
	ID         string `json:"id"`
}
