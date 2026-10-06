# Publication handover — push blocked by the local pre-push guard

Status: **PUSH NOT PERFORMED.** Everything up to the push is done and verified.
The blocker is local and needs Frank's decision; it is not an auth, permission
or conflict problem.

## What is ready

| Field | Value |
|---|---|
| Repository | `/home/favl/retrace-ai` |
| Branch | `build/retrace-t0-t2` |
| Local HEAD | `c181c8f` at the time of writing; this handover commit is now HEAD |
| Working tree | clean |
| Commits to publish | **23**: `f92bcc7` … this handover commit. The hook audited 22 before it was written |
| Tracked files | 312 |
| Remote configured | `origin` → `git@github.com:FAVL-AI/RetraceAi.git` (added; no prior remote existed, so nothing was replaced) |

## Verification already completed

**Publication safety — clean.**

- `.env` has **never** been committed (checked across all history).
- Both real local secret values (`POSTGRES_PASSWORD`, `RETRACE_SVC_PASSWORD`)
  appear **0 times** in the full history. Checked by value, without printing them.
- No private-key headers, cloud access keys, `gh*`/`sk-`/`xox*` tokens, bearer
  tokens, or password-bearing connection strings anywhere in history.
- No packaged third-party material: no `.claude/` tree, no skills, no agent
  definitions, no `MASTER_PROMPT`, no blueprint files copied into the repository.
  The recovered archive stays outside it at `/home/favl/retrace-blueprint-staging/`.
- No agent transcripts, logs, database dumps, research corpora, model weights or
  pickles tracked.
- Only one email address appears anywhere: Frank's own configured git identity.

**Quality — green at `c181c8f`.**

- `./scripts/test.sh` → **1601 passed, 5 skipped, 0 failed**, exit **0**, 50.9 s.
- `ruff check packages services tests apps` → clean.
- `mypy packages services` → no issues in 101 source files.
- PostgreSQL 17.11 healthy during the run, so integration tests genuinely ran.

**Destination and permission — verified.**

- `git@github.com:FAVL-AI/RetraceAi.git` resolves to the intended repository.
- SSH to GitHub authenticates as **`FAVL-AI`**.
- API as `FAVL-AI`: `{"admin": true, "maintain": true, "push": true}` on
  `FAVL-AI/RetraceAi`, which is public with `default_branch: main` and **no
  branches yet**.
- The earlier `push: false` reading came from the other authenticated account
  (`FrankAsanteVanLaarhoven`), which holds `pull` only on this repository. The
  push route is the SSH one, and it has permission.

## The blocker

The global pre-push hook audited all 22 outgoing commits and refused:

```
Blocked push: forbidden attribution/tool branding found in commit messages.
569:The recovered project invariants in the archive's ----------.md state that imported
722:The archive's ----------.md invariants are closer to this build than the prose was,
error: failed to push some refs to 'github.com:FAVL-AI/RetraceAi.git'
```

Its pattern is `claude|anthropic|chatgpt|openai|copilot|gemini`, applied
case-insensitively to commit messages. It matches a **filename** in Frank's own
recovered blueprint archive — the project-instructions file at the archive root —
which two commit messages cite as the source of a project invariant. The affected
commits are:

| Commit | Line | Context |
|---|---|---|
| `cf8221d` | 3 | cites the archive's project-instructions file for the invariant that imported code must never execute on the developer host — the finding that moved the triad into the runner's isolation boundary |
| `eebab1d` | 31 | notes that the archive's invariants are closer to the build than the pasted prose was |

Neither is an attribution or a branding claim. Both are factual citations of a
file in Frank's own package. But the guard scans message text, and there is no
message-level allowlist: the hook's only allowlist is for author identities.

## Why I stopped instead of resolving it

Every route out is closed by an explicit instruction in force:

| Route | Why not |
|---|---|
| `git push --no-verify` | The directive forbids disabling the required checks |
| Reword the two commit messages | Requires rewriting history, which the directive forbids |
| Adjust the guard's pattern or add a message allowlist | Lives in `FAVL-Engineering-OS`, which the directive forbids changing in this task |

So this is a decision for Frank, not a problem to engineer around. Reporting the
exact blocker is what the instruction asks for in this situation.

## To complete the push

Any one of these, at Frank's choice:

1. **Approve a message-level exemption in the guard** (in `FAVL-Engineering-OS`,
   by Frank): treat a bare filename reference as a functional identifier, the
   way `.attribution-allow` already does for file contents. This is the option
   consistent with the existing design, since the guard already distinguishes
   naming a thing from claiming authorship of it.
2. **Authorise rewriting those two commit messages** to cite the file
   descriptively rather than by name. This changes two SHAs and every SHA after
   them, so the 22-commit range and the local HEAD in this document become stale.
   Nothing has been pushed, so no published history would be rewritten.
3. **Authorise a single `--no-verify` push** for this checkpoint. Least
   preferable: it bypasses the control for all 22 commits rather than resolving
   the one pattern that misfired.

After the choice is made, the remaining steps are:

```bash
cd /home/favl/retrace-ai
git push --set-upstream origin build/retrace-t0-t2
git ls-remote origin refs/heads/build/retrace-t0-t2   # verify the remote SHA
```

and then verify the returned SHA equals the local commit SHA.

## Not done, and not claimed

No push. No deployment. No release. No change to repository visibility. No gate
marked passed. `FAVL-Engineering-OS` unmodified. The release decision stays
**REVISE** (`RELEASE_DECISION.md`).
