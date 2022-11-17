from python_graphql_client import GraphqlClient
from datetime import datetime, timezone, timedelta
from dateutil import parser
import feedparser
import httpx
import json
import pathlib
import re
import os

root = pathlib.Path(__file__).parent.resolve()
client = GraphqlClient(endpoint="https://api.github.com/graphql")


TOKEN = os.environ.get("COLINODELL_TOKEN", "")


def replace_chunk(content, marker, chunk, inline=False):
    r = re.compile(
        r"<!\-\- {} starts \-\->.*<!\-\- {} ends \-\->".format(marker, marker),
        re.DOTALL,
    )
    if not inline:
        chunk = "\n{}\n".format(chunk)
    chunk = "<!-- {} starts -->{}<!-- {} ends -->".format(marker, chunk, marker)
    return r.sub(chunk, content)


def make_release_query(after_cursor=None):
    return """
query {
  viewer {
    repositories(first: 100, privacy: PUBLIC, after:AFTER) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        nameWithOwner
        description
        url
        releases(first:2) {
          totalCount
          nodes {
            name
            publishedAt
            url
          }
        }
      }
    }
  }
}
""".replace(
        "AFTER", '"{}"'.format(after_cursor) if after_cursor else "null"
    )


def make_contributions_query():
    since = datetime.now() - timedelta(30)
    return """
query {
  viewer {
    topRepositories (first: 6, since: "SINCE", orderBy: { field: STARGAZERS, direction: DESC }) {
      nodes {
        nameWithOwner
        url
      }
    }
  }
}
""".replace(
        "SINCE", since.isoformat()
    )


def fetch_releases(oauth_token):
    repos = []
    releases = []
    repo_names = set()
    has_next_page = True
    after_cursor = None

    while has_next_page:
        data = client.execute(
            query=make_release_query(after_cursor),
            headers={"Authorization": "Bearer {}".format(oauth_token)},
        )
        print()
        print(json.dumps(data, indent=4))
        print()
        for repo in data["data"]["viewer"]["repositories"]["nodes"]:
            if repo["releases"]["totalCount"] and repo["nameWithOwner"] not in repo_names:
                repos.append(repo)
                repo_names.add(repo["nameWithOwner"])
                for release in repo["releases"]["nodes"]:
                    if release["publishedAt"] is None:
                        continue

                    release_date = parser.parse(release["publishedAt"])
                    releases.append(
                        {
                            "repo": repo["nameWithOwner"],
                            "repo_url": repo["url"],
                            "description": repo["description"],
                            "release": release["name"].replace(repo["name"], "").strip(),
                            "published_at": release_date.strftime("%Y-%m-%d"),
                            "published_at_ago": pretty_date(release_date),
                            "release_url": release["url"],
                        }
                    )
        has_next_page = data["data"]["viewer"]["repositories"]["pageInfo"][
            "hasNextPage"
        ]
        after_cursor = data["data"]["viewer"]["repositories"]["pageInfo"]["endCursor"]
    return releases


def fetch_contributions(oauth_token):
    data = client.execute(
        query=make_contributions_query(),
        headers = {"Authorization": "Bearer {}".format(oauth_token)},
    )
    print()
    print(json.dumps(data, indent=4))
    print()

    return data["data"]["viewer"]["topRepositories"]["nodes"]


def fetch_blog_entries():
    from time import strftime
    entries = feedparser.parse("https://www.colinodell.com/blog/rss.xml").entries
    return [
        {
            "title": entry["title"],
            "url": entry["link"].split("#")[0],
            "published": strftime("%Y-%m-%d", entry.published_parsed),
        }
        for entry in entries
    ]


def pretty_date(time=False):
    """
    Get a datetime object or a int() Epoch timestamp and return a
    pretty string like 'an hour ago', 'Yesterday', '3 months ago',
    'just now', etc

    Based on https://stackoverflow.com/a/1551394/158766
    """
    now = datetime.now(timezone.utc)
    if type(time) is int:
        diff = now - datetime.fromtimestamp(time)
    elif isinstance(time,datetime):
        diff = now - time
    elif not time:
        diff = now - now

    day_diff = diff.days

    if day_diff < 0:
        return ''

    if day_diff == 0:
        return "today"
    if day_diff == 1:
        return "yesterday"
    if day_diff < 7:
        return str(day_diff) + " days ago"
    if day_diff < 31:
        return str(round(day_diff / 7)) + " weeks ago"
    if day_diff < 365:
        return str(round(day_diff / 30)) + " months ago"
    return str(round(day_diff / 365)) + " years ago"


if __name__ == "__main__":
    readme = root / "README.md"
    project_releases = root / "releases.md"
    releases = fetch_releases(TOKEN)
    releases.sort(key=lambda r: r["published_at"], reverse=True)
    md = "\n".join(
        [
            "* **[{repo}]({repo_url})** ([{release}]({release_url}), {published_at_ago})<br>{description}".format(**release)
            for release in releases[:8]
        ]
    )
    readme_contents = readme.open().read()
    rewritten = replace_chunk(readme_contents, "recent_releases", md)

    # Write out full project-releases.md file
    project_releases_md = "\n".join(
        [
            "* **[{repo}]({repo_url})** ([{release}]({release_url}), {published_at_ago})<br>{description}".format(**release)
            for release in releases
        ]
    )
    project_releases_content = project_releases.open().read()
    project_releases_content = replace_chunk(
        project_releases_content, "recent_releases", project_releases_md
    )
    project_releases_content = replace_chunk(
        project_releases_content, "release_count", str(len(releases)), inline=True
    )
    project_releases.open("w").write(project_releases_content)

    contributions = fetch_contributions(TOKEN)
    contributions_md = "\n".join(
        [
            "* **[{nameWithOwner}]({url})**".format(**contribution)
            for contribution in contributions if contribution is not None
        ]
    )
    rewritten = replace_chunk(rewritten, "recent_contributions", contributions_md)

    entries = fetch_blog_entries()[:5]
    entries_md = "\n".join(
        ["* [{title}]({url}) - {published}".format(**entry) for entry in entries]
    )
    rewritten = replace_chunk(rewritten, "blog", entries_md)

    readme.open("w").write(rewritten)
