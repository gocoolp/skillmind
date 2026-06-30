---
name: gh-api-workflow
triggers: ["gh api", "github api", "query github", "check PR status"]
---

## When to use
When you need to query or update GitHub resources directly — PR status,
issue metadata, workflow runs, or repo settings — without opening the browser.

## Steps
1. Authenticate once: `gh auth login`
2. Query a resource: `gh api repos/{owner}/{repo}/pulls --jq '.[].title'`
3. Pipe through `jq` to extract specific fields
4. For mutations, add `-X POST` or `-X PATCH` with `--field key=value`

## Example

```bash
# List open PRs with their review status
gh api repos/{owner}/{repo}/pulls \
  --jq '.[] | {title: .title, state: .draft, reviews: .requested_reviewers}'

# Trigger a workflow manually
gh api repos/{owner}/{repo}/actions/workflows/ci.yml/dispatches \
  -X POST --field ref=main
```

## Notes
- `gh api` uses your existing `gh auth` token — no separate API key needed
- Prefer `--jq` over piping to a separate `jq` call for single-field extractions
- For paginated results add `--paginate`
