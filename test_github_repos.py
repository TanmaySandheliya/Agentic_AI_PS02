from modules.github_client import GitHubClient

client = GitHubClient()

username = "Veerpratapsan"

try:
    repositories = client.list_user_repositories(
        username,
        include_forks=True
    )

    print(f"\nTotal repositories found: {len(repositories)}\n")

    for index, repo in enumerate(repositories, start=1):
        print(f"{index}. {repo['full_name']}")
        print(f"   Language: {repo['language']}")
        print(f"   URL: {repo['html_url']}")
        print()

except Exception as e:
    print(f"Error: {e}")