# Operonlab — Open Source Release

## Organization
- GitHub org: `operonlab`
- Owner: JonesHong

## Subtree Pattern (monorepo → standalone repo)
```bash
git subtree split --prefix=stations/<name> -b operonlab-temp
git push <remote> operonlab-temp:main
git branch -D operonlab-temp
```

## Remote Registry
| Repo | Subtree Prefix | Remote Name |
|------|---------------|-------------|
| hook-observatory | stations/hook-observatory | operonlab-hook |
