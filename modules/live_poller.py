from modules.change_agent import ChangeAgent

"""Poll selected GitHub repositories for new commits."""

from modules import storage
from modules.github_client import GitHubClient


def check_repository_updates(student_id: str):
    """
    Check selected repositories for new commits.

    This function only detects changes.
    Reassessment will be connected in the next step.
    """
    client = GitHubClient()
    repositories = storage.get_repositories(
        student_id,
        selected_only=True,
    )

    updates = []

    for repo in repositories:
        repo_name = repo["full_name"]
        branch = repo.get("tracked_branch") or repo.get("default_branch") or "main"
        previous_sha = repo.get("last_analysed_sha")

        try:
            latest_sha = client.get_branch_head_sha(repo_name, branch)

            if not latest_sha:
                continue

            if not previous_sha:
                # No baseline yet: do not treat the entire history
                # as a newly detected commit.
                continue

            if latest_sha == previous_sha:
                continue

            updates.append({
                "repo_full_name": repo_name,
                "branch": branch,
                "before_sha": previous_sha,
                "after_sha": latest_sha,
            })

        except Exception as exc:
            print(f"Polling failed for {repo_name}: {exc}")

    return updates

def process_repository_updates(student_id: str):
    """
    Detect new commits and reassess affected skills.
    """
    client = GitHubClient()
    agent = ChangeAgent(github_client=client)

    updates = check_repository_updates(student_id)
    results = []

    for update in updates:
        repo_name = update["repo_full_name"]
        before_sha = update["before_sha"]
        after_sha = update["after_sha"]

        try:
            changed_files = client.get_changed_files_between_commits(
                repo_name,
                before_sha,
                after_sha,
            )

            # Stable event ID prevents duplicate processing.
            delivery_id = (
                f"poll:{repo_name}:"
                f"{before_sha}:{after_sha}"
            )

            result = agent.process_change_event(
                repo_full_name=repo_name,
                before_sha=before_sha,
                after_sha=after_sha,
                changed_files_info=changed_files,
                delivery_id=delivery_id,
                source="polling",
            )

            results.append({
                "repository": repo_name,
                "result": result,
            })

        except Exception as exc:
            results.append({
                "repository": repo_name,
                "status": "error",
                "error": str(exc),
            })

    return results