package main

import (
	workshoplog "github.com/joneshong/workshop/libs/workshop-log"

	"github.com/operonlab/tmux-webui/cmd/tmux-webui/cmd"
)

func main() {
	_ = workshoplog.Init("tmux-webui")
	cmd.Execute()
}
