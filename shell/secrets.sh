# 載入私密金鑰（~/.secrets.sh，chmod 600，不進 git）
if [[ -f "$HOME/.secrets.sh" ]]; then
  . "$HOME/.secrets.sh"
fi
