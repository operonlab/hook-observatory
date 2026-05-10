package network

import (
	"os"

	qrterminal "github.com/mdp/qrterminal/v3"
)

// PrintQR renders a QR code for url to stdout.
func PrintQR(url string) {
	config := qrterminal.Config{
		Level:     qrterminal.M,
		Writer:    os.Stdout,
		BlackChar: qrterminal.BLACK,
		WhiteChar: qrterminal.WHITE,
		QuietZone: 1,
	}
	qrterminal.GenerateWithConfig(url, config)
}
