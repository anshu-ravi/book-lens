---
name: git-commit
description: Use this prompt whenever you want to generate a git commit message based on the changes made in the code. Provide a summary of the changes, the reason for the changes, and any relevant details that should be included in the commit message.
---

Add and commit the changes in the code with a generated commit message. The commit message should follow the conventional commit format: <type>(<scope>): <subject>

Where:
- type: the type of change (e.g., feat, fix, docs, style, refactor, test, chore)
- scope: the area of the code that was changed (e.g., api, ui, database)
- subject: a brief description of the change (max 50 characters)
- body (optional): a longer explanation of "why" if the subject alone is not sufficient


Steps:

1. Use `git branch --show-current` to identify the current branch (feature branch).

2. Execute the following git commands to analyze the changes in the code:

   1. `git status --porcelain` to see the staged and unstaged changes. If empty, inform the user there is nothing to commit and stop.

   2. For untracked files, preview content with `head -50 <path/to/untracked/file>` (skip binary files).

   3. `git diff` to see the differences for the tracked files that have unstaged changes.

3. Identify the relevant changes and understand the purpose and scope of the commit. Create a plan listing each commit to be made, including the files, type, scope, and subject for each commit message. Group related changes together into a single commit. Never push all changes in a single commit if they are not related to each other. Always create separate commits for unrelated changes.

4. For every block of changes:

   - Add the changes to the staging area

```
   git add <path/to/changed/files>
```

   - Commit the changes with the generated commit message. If the change needs more context, add a body.

```
   git commit -m "<type>(<scope>): <subject>" -m "<optional body explaining why>"
```

   - If a commit fails, diagnose the error and inform the user before proceeding.

5. Finally, ask the user if they want to push the changes to the remote repository. If yes, execute the command:

```
git push origin <current_branch>
```