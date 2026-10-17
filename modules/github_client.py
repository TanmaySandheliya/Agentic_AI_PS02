"""
GitHub Client Module for SkillTrace.
Handles PyGithub integration, tree fetching, commit comparisons, rate limits, and permalinks.
Adheres to SRS Section 4.1 (FR-01 to FR-05), FR-15, FR-23, and Section 7.2 D.
"""
from typing import List, Dict, Any, Optional, Tuple
import requests
import base64
from github import Github, GithubException, RateLimitExceededException
from pathlib import Path

from config import settings


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token if token is not None else settings.github_token
        self.gh = Github(self.token) if self.token else Github()
        self._etags: Dict[str, str] = {}

    def get_rate_limit(self) -> Dict[str, Any]:
        """Returns the current GitHub API rate limit status."""
        try:
            rate = self.gh.get_rate_limit().core
            return {
                "limit": rate.limit,
                "remaining": rate.remaining,
                "reset_time": rate.reset.isoformat() if rate.reset else None
            }
        except Exception:
            return {"limit": 60, "remaining": 60, "reset_time": None}

    def list_user_repositories(self, username: str, include_forks: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieves public repositories for a GitHub user.
        Excludes forked repositories by default (SRS Section 4.3 FR-15).
        """
        try:
            user = self.gh.get_user(username)
            repos = []
            for repo in user.get_repos(type="owner"):
                if repo.fork and not include_forks:
                    continue
                repos.append({
                    "full_name": repo.full_name,
                    "name": repo.name,
                    "default_branch": repo.default_branch or "main",
                    "description": repo.description or "",
                    "html_url": repo.html_url,
                    "fork": repo.fork,
                    "language": repo.language or "Unknown"
                })
            return repos
        except RateLimitExceededException:
            raise RuntimeError("GitHub API rate limit exceeded. Please configure a GITHUB_TOKEN in your environment.")
        except GithubException as e:
            raise RuntimeError(f"GitHub API Error for user '{username}': {e.data.get('message', str(e))}")

    def get_branch_head_sha(self, repo_full_name: str, branch: str = "main") -> str:
        """Gets the latest commit SHA of the specified branch."""
        try:
            repo = self.gh.get_repo(repo_full_name)
            br = repo.get_branch(branch)
            return br.commit.sha
        except Exception as e:
            raise RuntimeError(f"Failed to fetch head commit for {repo_full_name}@{branch}: {str(e)}")

    def get_changed_files_between_commits(
        self, repo_full_name: str, base_sha: str, head_sha: str
    ) -> List[Dict[str, Any]]:
        """
        Compares two commits and returns added, modified, removed, or renamed files (FR-24).
        """
        try:
            repo = self.gh.get_repo(repo_full_name)
            comparison = repo.compare(base_sha, head_sha)
            changed = []
            for f in comparison.files:
                changed.append({
                    "filename": f.filename,
                    "status": f.status,  # 'added', 'modified', 'removed', 'renamed'
                    "previous_filename": getattr(f, "previous_filename", None),
                    "patch": f.patch
                })
            return changed
        except Exception as e:
            # Fallback or force-push rewrite detection (FR-24)
            raise RuntimeError(f"Commit comparison failed between {base_sha} and {head_sha}: {str(e)}")

    def get_repository_tree(self, repo_full_name: str, commit_sha: str) -> List[Dict[str, Any]]:
        """
        Fetches the recursive file tree for a repository at a specific commit SHA.
        Excludes vendored, generated, or hidden files.
        """
        try:
            repo = self.gh.get_repo(repo_full_name)
            git_tree = repo.get_git_tree(commit_sha, recursive=True)
            files = []
            for element in git_tree.tree:
                if element.type == "blob":
                    # Check exclusions
                    if not self._is_excluded(element.path):
                        files.append({
                            "path": element.path,
                            "sha": element.sha,
                            "size": element.size or 0
                        })
            return files
        except Exception as e:
            raise RuntimeError(f"Failed to fetch file tree for {repo_full_name} at {commit_sha}: {str(e)}")

    def get_file_content(self, repo_full_name: str, file_path: str, commit_sha: str) -> Optional[str]:
        """
        Fetches the raw text content of a file at a specific commit SHA.
        Respects max file size settings.
        """
        try:
            repo = self.gh.get_repo(repo_full_name)
            content_file = repo.get_contents(file_path, ref=commit_sha)
            if content_file.size and content_file.size > settings.max_file_size_bytes:
                return None  # File too large
            if content_file.encoding == "base64" and content_file.content:
                return base64.b64decode(content_file.content).decode("utf-8", errors="replace")
            elif content_file.decoded_content:
                return content_file.decoded_content.decode("utf-8", errors="replace")
            return None
        except Exception:
            return None

    def poll_head_with_etag(self, repo_full_name: str, branch: str = "main") -> Tuple[Optional[str], bool]:
        """
        Polls the repository's branch using conditional HTTP request with ETag (SRS FR-23).
        Returns (new_sha, changed).
        """
        url = f"https://api.github.com/repos/{repo_full_name}/branches/{branch}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "SkillTrace-Poller/1.0"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        cached_etag = self._etags.get(f"{repo_full_name}:{branch}")
        if cached_etag:
            headers["If-None-Match"] = cached_etag

        try:
            resp = requests.get(url, headers=headers, timeout=settings.request_timeout_seconds)
            if resp.status_code == 304:
                # Not modified
                return None, False
            if resp.status_code == 200:
                new_etag = resp.headers.get("ETag")
                if new_etag:
                    self._etags[f"{repo_full_name}:{branch}"] = new_etag
                data = resp.json()
                sha = data.get("commit", {}).get("sha")
                return sha, True
            return None, False
        except Exception:
            return None, False

    def build_permalink(
        self, repo_full_name: str, commit_sha: str, file_path: str, line_start: int = 1, line_end: int = 1
    ) -> str:
        """
        Generates a commit-pinned permalink to GitHub (SRS Section 9.2).
        Format: https://github.com/<owner>/<repo>/blob/<sha>/<path>#L<start>-L<end>
        """
        line_ref = f"#L{line_start}-L{line_end}" if line_start != line_end else f"#L{line_start}"
        return f"https://github.com/{repo_full_name}/blob/{commit_sha}/{file_path}{line_ref}"

    def _is_excluded(self, file_path: str) -> bool:
        """Checks if a file path belongs to vendored directories or generated lockfiles."""
        parts = file_path.lower().replace("\\", "/").split("/")
        # Check directories
        for part in parts[:-1]:
            if part in settings.vendor_directories or part.startswith("."):
                return True
        # Check filename
        filename = parts[-1]
        for pattern in settings.generated_file_patterns:
            if filename == pattern or filename.endswith(pattern):
                return True
        return False
