# hook-observatory Release

## Remote
- GitHub: `operonlab/hook-observatory`
- Workshop remote: `operonlab-hook`
- Subtree prefix: `stations/hook-observatory`

## Push & Tag
```bash
git subtree split --prefix=stations/hook-observatory -b operonlab-temp
git push operonlab-hook operonlab-temp:main
git branch -D operonlab-temp

# Tag triggers CI
MAIN_SHA=$(gh api /repos/operonlab/hook-observatory/git/ref/heads/main --jq '.object.sha')
gh api /repos/operonlab/hook-observatory/git/refs -X POST \
  -f ref="refs/tags/v<VERSION>" -f sha="$MAIN_SHA"
gh release edit v<VERSION> --repo operonlab/hook-observatory --draft=false --latest
```
