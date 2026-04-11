
---
name: git-pr
description: Use this prompt to generate a pull request description based on the changes made in a GitHub repository. The AI will analyze the code changes and provide a concise and informative description for the pull request.
---

Generate a git pull request based on the commits in the code. User will specify the `<base branch>` (`main` if not specified) and the `<feature branch>` (current branch if not specified).

Steps:

1. Use `git branch --show-current` to identify the current branch (feature branch).

2. Run `git fetch origin` to ensure the base branch ref is up to date.

3. Use `git log <base_branch>..<feature_branch>` to see the commit history and identify the relevant commits for the pull request. If there are no commits between the branches, inform the user and stop.

4. Check if a PR already exists for this branch:
```
   gh pr list --head <feature_branch> --base <base_branch>
```
   If a PR already exists, inform the user and ask if they want to update it instead.

5. Analyze the commit messages and code changes to understand the purpose and scope of the pull request.

6. Write the PR description to a temp file and execute the command to submit the pull request. The description should include a summary of the changes, the reason for the changes, and any relevant details.

```
   gh pr create --base <base_branch> --head <feature_branch> --title "<pull_request_title>" --body-file /tmp/pr_body.md -a \"@me\"
```

   Then clean up:
```
   rm /tmp/pr_body.md
```

Where:
- `<base_branch>`: the branch you want to merge into (default: develop)
- `<feature_branch>`: the branch you want to merge from (default: current branch)
- `<pull_request_title>`: a concise title for the pull request (max 50 characters)
- IMPORTANT: include the \ symbol before the " character in the -a flag to avoid issues with the command execution.

Instructions:
- If there are any changes in the .github folder, don't mention them in the PR description unless the user explicitly asks for it.
- If `gh pr create` fails, show the error to the user and suggest possible fixes (e.g., authentication, missing remote branch).