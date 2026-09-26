# Safe local merge workflow — NO PUSH

This workflow merges the feature branch into your **local** `main` only.

It intentionally contains **no `git push` command**.

## 1. Test the feature branch first

```powershell
git branch --show-current
py -m screen_behavior.run_tests
py -m screen_behavior.demo_v04 --scenarios
git status
```

Commit the feature work on the feature branch if needed:

```powershell
git add screen_behavior
git commit -m "Add screen awareness and behavior V0.4"
```

## 2. Refresh knowledge of remote main without modifying it

```powershell
git fetch origin
```

## 3. Switch to local main

```powershell
git checkout main
```

If local main has no uncommitted work, bring it up to date with the team's remote
main using a fast-forward-only pull:

```powershell
git pull --ff-only origin main
```

This downloads teammates' changes. It does **not** upload yours.

## 4. Start a local merge but DO NOT commit it yet

```powershell
git merge --no-ff --no-commit feature/screen-behavior
```

If Git reports merge conflicts, do not guess. Resolve them carefully with the
team or abort:

```powershell
git merge --abort
```

## 5. Test the merged tree BEFORE committing

```powershell
py -m screen_behavior.run_tests
py -m screen_behavior.demo_v04 --scenarios
git status
```

If anything is broken:

```powershell
git merge --abort
```

If everything passes:

```powershell
git commit -m "Merge screen awareness and behavior V0.4"
```

STOP HERE.

Do **not** push `main` unless the team explicitly agrees to publish the merge.

Your local `main` now contains the merge, while `origin/main` remains unchanged.
