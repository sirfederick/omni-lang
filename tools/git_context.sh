#!/usr/bin/env bash
# Resolve Git consistently from native checkouts and Windows-created linked
# worktrees reached through WSL. The caller receives the OMNI_GIT argv array.

omni_git_context() {
  local repo="$1" marker="$1/.git" gitdir drive tail
  OMNI_GIT=(git -C "$repo")
  if [[ ! -f "$marker" ]]; then
    return 0
  fi
  gitdir="$(sed -n 's/^gitdir:[[:space:]]*//p' "$marker")"
  gitdir="${gitdir//\\//}"
  if [[ "$gitdir" =~ ^([A-Za-z]):/(.*)$ ]]; then
    drive="${BASH_REMATCH[1],,}"
    tail="${BASH_REMATCH[2]}"
    gitdir="/mnt/$drive/$tail"
  fi
  if [[ -z "$gitdir" || ! -d "$gitdir" ]]; then
    printf 'unable to resolve linked-worktree gitdir: %s\n' "$gitdir" >&2
    return 1
  fi
  OMNI_GIT=(git "--git-dir=$gitdir" "--work-tree=$repo")
}
