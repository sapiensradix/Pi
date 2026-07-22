# Pi Maintainer Guide

This guide defines the working process for maintainers, contributors, Codex, and other AI systems participating in the Pi repository. It does not replace the [Pi Project Constitution](PROJECT_CONSTITUTION.md). If this guide conflicts with the Constitution, the Constitution takes precedence.

## Read the Constitution Before Every Patch

Before performing any patch:

1. Read `/docs/PROJECT_CONSTITUTION.md` in full.
2. Confirm that the Constitution is understood.
3. Classify the patch as one of:
   - Bug Fix
   - Maintenance
   - Feature
4. Classify its behavior as:
   - Behavior-preserving
   - Behavior-changing
5. Identify whether the patch touches consensus, protocol, wallet behavior, mining behavior, network behavior, or a public API.
6. If the patch conflicts with the Constitution, stop, report evidence, and wait for a maintainer decision.

Do not begin coding until this process is complete.

## Patch Workflow

Each patch must have exactly one objective.

1. State the patch name and exact objective.
2. State its classification and behavior classification.
3. Define the files and systems that are in scope.
4. Define the files and systems that are explicitly out of scope.
5. Audit the current code and provide file, line, commit, log, or test evidence.
6. If a finding is not proven, label it: `Đây chỉ là giả thuyết.`
7. Make only the minimum changes required for the stated objective.
8. Do not fix unrelated findings. Report them separately.
9. Build and test in proportion to the patch.
10. Review the complete diff before staging.
11. Stage only the explicitly approved files.
12. Commit only after review and maintainer approval.
13. Push only after explicit maintainer approval.

## Commit Rules

- One commit must represent one patch objective.
- Do not use `git add .` when unrelated or untracked files exist.
- Stage files by an explicit file list or by reviewed hunks.
- Do not commit binaries, object files, `.deps`, build directories, backups, release archives, checksums generated from local builds, or other build artifacts.
- Do not commit from an unreviewed or dirty index.
- Run `git diff --cached --check` before committing.
- Review `git diff --cached --name-only` and the complete cached diff.
- Do not force-push.
- Do not rewrite shared history without explicit maintainer approval.
- Do not merge or backport Bitcoin Core commits without the required maintainer review defined by the Constitution.
- Never stage, commit, or push a Whitepaper file.

## Review Checklist

Every completed patch must report:

```text
Patch: <patch name>

Classification:
Behavior-preserving

Consensus touched:
NO

Protocol touched:
NO

Wallet behavior changed:
NO

Mining behavior changed:
NO

Network behavior changed:
NO

Public API changed:
NO

Tests:
PASS

Build:
PASS

Ready for Review:
YES
```

The reviewer must also confirm:

- The patch contains only its stated objective.
- Consensus and monetary policy are unchanged.
- PoW, difficulty, subsidy, halving, supply, validation, script, UTXO, mempool, transaction, block, relay, and network rules are unchanged.
- No unapproved RPC, CLI, config, wallet-format, file-format, or protocol change is present.
- No refactor, cleanup, modernization, renaming, style-only rewrite, or unrelated optimization is included.
- Test evidence is reproducible and failures are not hidden.
- The staged file list contains no artifacts or unrelated files.
- No Whitepaper file is changed or staged.

If Consensus, Protocol, Mining, Network, or Public API is `YES`, stop and wait for a maintainer decision.

## Release Checklist

Before declaring a release ready:

- The release is built from a clean, committed Git tree.
- The source tag identifies the exact release commit.
- Genesis hash verified.
- Total supply verified.
- Halving schedule verified.
- Coinbase maturity verified.
- Difficulty adjustment verified.
- Release binaries are produced directly by the build system and are not manually renamed.
- Required Linux, macOS Intel, macOS Apple Silicon, and Windows builds are verified.
- Applicable unit, RPC, functional, wallet, mining, and P2P tests pass or every unsupported test is explicitly classified and documented.
- A clean-machine installation and startup test is completed.
- Mainnet genesis, monetary policy, PoW, mining, wallet startup, RPC, shutdown, restart, and peer synchronization are verified without changing protocol behavior.
- Bootstrap and peer-discovery strategy does not depend on one developer node.
- Runtime branding, application bundles, installers, resources, man pages, and configuration examples use Pi identity.
- Required README, build, mining, node, technical, and security documentation is present.
- Reproducible build instructions, release notes, source archives, binaries, and `SHA256SUMS` are provided.
- Repository source is clean and contains no generated binaries or build artifacts.
- License, copyright, and inherited Bitcoin Core attribution are reviewed accurately.
- The Whitepaper is unchanged.

## Git Flow

1. Start from the reviewed repository head.
2. Use a dedicated branch for the patch when isolation or recovery is required.
3. Preserve unrelated working-tree changes and untracked files.
4. Inspect local and remote history before rebasing, merging, or pushing.
5. Rebase only when the exact commit range and target are known and the operation is approved.
6. Never use force-push as a substitute for understanding diverged history.
7. Push a normal fast-forward update only after local verification and maintainer approval.
8. Never push directly to main without review.
9. Verify the remote commit hash after pushing.
10. Keep recovery branches until remote verification succeeds.

## Coding Conventions

- Preserve Bitcoin Core behavior and architecture unless the maintainer explicitly approves a required exception.
- Prefer the approach already used by the Bitcoin Core version on which Pi is based.
- Do not independently synchronize with a newer Bitcoin Core version.
- Do not rename classes, functions, internal architecture, or public interfaces for aesthetics.
- Do not modernize, clean up, refactor, optimize, or restyle working code outside the patch objective.
- Use the smallest reviewable diff that fixes the proven issue.
- Preserve public RPC, CLI, config, wallet, and file-format compatibility unless an approved patch explicitly requires otherwise.
- Keep wallet and GUI code separate from blockchain consensus behavior.
- Mining must remain real SHA-256d proof of work on computers.
- Do not add staking, PoS, smart contracts, tokens, NFTs, DAO, governance, KYC, new rewards, or new fees without explicit maintainer approval.

## Whitepaper Handling

The Whitepaper is immutable and is governed by Article 21 of the Constitution.

It may be read, searched, cited, and compared with source code. It must never be edited, renamed, moved, reformatted, generated, replaced, staged, committed, pushed, or included in a patch.

If `Code ≠ Whitepaper`, report the code file and line, the relevant Whitepaper section, and the evidence, then stop. Do not modify either the code or the Whitepaper.
