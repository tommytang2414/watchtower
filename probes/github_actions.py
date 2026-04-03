"""GitHub Actions workflow status probe."""
import asyncio
from github import Github
from config import GITHUB_TOKEN


async def run_github_actions_probe(
    owner: str,
    repo: str,
    workflow_filename: str,
) -> dict:
    """
    Poll GitHub Actions for the latest workflow run conclusion.

    Returns:
        {
            "up": bool,        # True if conclusion == "success" or "skipped"
            "conclusion": str,
            "run_url": str,
            "run_created_at": str,
            "error_message": str | None,
        }
    """
    result = {
        "up": False,
        "conclusion": None,
        "run_url": None,
        "run_created_at": None,
        "error_message": None,
    }

    if not GITHUB_TOKEN:
        result["error_message"] = "GITHUB_TOKEN not configured"
        return result

    def _fetch():
        g = Github(GITHUB_TOKEN)
        repo_obj = g.get_repo(f"{owner}/{repo}")

        # Get the workflow file id
        workflows = repo_obj.get_workflows()
        workflow = None
        for w in workflows:
            if w.path == f".github/workflows/{workflow_filename}":
                workflow = w
                break

        if not workflow:
            result["error_message"] = f"Workflow {workflow_filename} not found"
            return

        # Try master first, then main
        runs = workflow.get_runs(branch="master")
        runs_list = list(runs)[:1]
        if not runs_list:
            runs = workflow.get_runs(branch="main")
            runs_list = list(runs)[:1]

        if not runs_list:
            result["error_message"] = "No workflow runs found"
            return

        latest = runs_list[0]
        result["conclusion"] = latest.conclusion
        result["run_url"] = latest.html_url
        result["run_created_at"] = str(latest.created_at)

        if latest.conclusion in ("success", "skipped"):
            result["up"] = True

    try:
        await asyncio.to_thread(_fetch)
    except Exception as e:
        result["error_message"] = str(e)
        result["up"] = False

    return result
