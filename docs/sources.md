# Where estimates come from

`fibo` reads one file: `.fibo.json` in the root of the repository.
Without it nothing leaves the machine. Estimates then come from the text of
your commits and from the local ledger, and that is enough to run.

Sources in order of trust. When a task has estimates in several places, the
highest one wins, and `fibo doctor` lists the disagreements.

| | Source | Where the estimate lives | Where its time comes from |
|---|---|---|---|
| A | Jira | `timeoriginalestimate` | the changelog entry that set it |
| A | Linear | `estimate` (points) | issue history |
| A | GitHub | `est: 2d` labels, an estimate field in Projects, PR bodies | the `labeled` event; the field's last update; PR creation |
| A | GitLab | `time_estimate` | the system note "changed time estimate to …" |
| B | commit text | `Estimate: 2d` · `Est: 4h` · `/estimate 1w` | the commit |
| C | ledger | `fibo say PROJ-412 2d` | the moment you said it |

Tokens are read-only, used for GET requests and GraphQL queries only. A
GraphQL mutation is refused before it leaves the process.

## You

```json
{ "emails": ["me@work.com", "1234+me@users.noreply.github.com"] }
```

`git config user.email` is always included and `.mailmap` is respected. These
addresses are the only subject the tool has: `--whose` accepts nothing else.

## Jira

```json
{
  "jira": {
    "url": "https://acme.atlassian.net",
    "email": "me@acme.com",
    "token_env": "JIRA_API_TOKEN",
    "jql": "project = PROJ"
  }
}
```

The query always starts with `assignee = currentUser()`; `jql` can only
narrow it. On Cloud, give `email` with an API token (basic auth). On Server
or Data Center, omit `email` and use a personal access token (bearer). The
first move into a status named in `in_progress` (default: In Progress,
In Development, Doing, Started, В работе) serves as the start when history
cannot say. Jira's own hours per day are respected, so a "1d" typed into a
six-hour-day Jira is still one day.

## Linear

```json
{ "linear": { "token_env": "LINEAR_API_KEY" } }
```

Linear estimates are points, and points are not time. They are refused unless
you run with `--points-as-hours=N` (or set `points_as_hours`), and then the
output says the number rests on your assumption.

## GitHub

```json
{
  "github": {
    "repo": "acme/app",
    "token_env": "GITHUB_TOKEN",
    "project_field": "Estimate",
    "project_field_unit": "h"
  }
}
```

`repo` defaults to the `origin` remote. Labels look like `est: 2d` or
`estimate: 4h`; every label ever applied is kept in order, so relabelling after
the first commit shows up in `doctor`. Projects keep no history for a field,
only its last update, so that time is used, which is the conservative choice.

## GitLab

```json
{ "gitlab": { "url": "https://gitlab.com", "project": "acme/app", "token_env": "GITLAB_TOKEN" } }
```

## In the text

Put the estimate in the first commit of the branch. An empty commit is fine:

```sh
git switch -c PROJ-412-fix-auth
git commit --allow-empty -m "PROJ-412 fix auth" -m "Estimate: 2d"
```

A trailer that first appears in a later commit was written after the work
began, and is refused as such. Someone else's trailer is someone else's
promise and is ignored.

## The ledger

```sh
fibo say PROJ-412 2d
```

It writes to `.fibo/ledger.jsonl`. Every line holds the SHA-256 of the line
before it, and `.fibo/ledger.head` holds the hash of the last line.
`say` refuses a task that already has commits, a task that has already
landed, and a second estimate for the same task. Commit the ledger if you want
git to vouch for it too.

## Everything else

```json
{
  "main_branch": "main",
  "calendar": { "workdays": ["mon", "tue", "wed", "thu", "fri"], "start": "09:00", "end": "18:00", "hours_per_day": 8 },
  "points_as_hours": null,
  "cache_ttl": 3600,
  "in_progress": ["In Progress", "Doing"]
}
```

| Flag | |
|---|---|
| `-C PATH` | run as if started in PATH |
| `--calendar` | raw calendar time instead of working hours |
| `--points-as-hours N` | convert points, and say so in the output |
| `--whose EMAIL` | must be one of your addresses; anything else is refused |
| `--offline` / `--refresh` | tracker cache: only the cache / ignore the cache |
| `-v` | geometric mean, active time, how long tasks sat idle |
| `--lang en\|ru` | output language; by default it follows the environment |
| `--no-color` | plain text (`NO_COLOR` is respected too) |

## Matching work to tasks

The task key is found in the branch name (`PROJ-412-fix-auth`,
`feature/PROJ-412`, `me/proj-412-fix` for keys your tracker knows, `412-fix`
for GitHub and GitLab issue numbers) or in the commit messages. It covers the
usual merge subjects: GitHub, GitLab, Bitbucket, Azure DevOps and plain
`git merge`. Rebased and squashed landings work too. A squash leaves no trace
of when the work began, so the tracker's "In Progress" is used, or the
branch if it still exists. Without either, the task is excluded as "no branch".

A follow-up that starts more than three working days after the last landing
is treated as new work and does not stretch the task.
