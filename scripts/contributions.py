#!/usr/bin/env python3
"""Render merged pull requests to other people's public repositories into README.md.

The list is written between the CONTRIBUTIONS:START and CONTRIBUTIONS:END markers.
Uses only the standard library, so it runs locally and in GitHub Actions as-is.

Environment:
  GITHUB_TOKEN    token for the GitHub API (falls back to `gh auth token`)
  GITHUB_USER     whose contributions to list (default: owner of the token)
  EXCLUDE_OWNERS  comma-separated owners/orgs to skip (e.g. your own orgs)
  README          file to update (default: README.md)
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

API = "https://api.github.com"
START, END = "<!-- CONTRIBUTIONS:START -->", "<!-- CONTRIBUTIONS:END -->"


def token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


def get(path, tok, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def merged_prs(user, tok):
    """Yield merged PRs authored by `user` in public repos owned by someone else."""
    query = f"type:pr author:{user} is:merged is:public -user:{user}"
    page = 1
    while True:
        data = get("/search/issues", tok, {"q": query, "per_page": 100, "page": page})
        yield from data["items"]
        # The search API returns at most 1000 results.
        if len(data["items"]) < 100 or page * 100 >= min(data["total_count"], 1000):
            return
        page += 1


def render(user, tok, exclude):
    repos = {}
    for pr in merged_prs(user, tok):
        name = pr["repository_url"].split("/repos/", 1)[1]
        if name.split("/")[0].lower() in exclude:
            continue
        repos.setdefault(name, []).append(pr)

    if not repos:
        return "_No contributions yet._"

    stars = {name: get(f"/repos/{name}", tok)["stargazers_count"] for name in repos}
    lines = []
    for name in sorted(repos, key=lambda n: (-stars[n], n.lower())):
        prs = sorted(repos[name], key=lambda p: p["closed_at"], reverse=True)
        lines.append(f"- **[{name}](https://github.com/{name})** ★{stars[name]}")
        for pr in prs:
            title = pr["title"].replace("[", "\\[").replace("]", "\\]")
            lines.append(f"  - [{title}]({pr['html_url']}) ({pr['closed_at'][:10]})")
    return "\n".join(lines)


def main():
    tok = token()
    user = os.environ.get("GITHUB_USER") or get("/user", tok)["login"]
    exclude = {o.strip().lower() for o in os.environ.get("EXCLUDE_OWNERS", "").split(",") if o.strip()}
    readme = os.environ.get("README", "README.md")

    with open(readme, encoding="utf-8") as f:
        content = f.read()
    if START not in content or END not in content:
        sys.exit(f"{readme} must contain {START} and {END}")

    block = f"{START}\n{render(user, tok, exclude)}\n{END}"
    updated = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, content, flags=re.S)

    if updated != content:
        with open(readme, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"Updated {readme}")
    else:
        print("No changes")


if __name__ == "__main__":
    main()
