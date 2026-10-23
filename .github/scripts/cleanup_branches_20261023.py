"""Execute the user's one-time obsolete-branch cleanup with atomic ref leases."""

import argparse
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / ".github/maintenance/branch-cleanup-2026-10-23.json"


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def api(path, payload=None):
    raw = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        os.environ["GITHUB_API_URL"] + "/repos/" + os.environ["GITHUB_REPOSITORY"] + path,
        data=raw, method="GET" if payload is None else "PATCH",
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def refs(kind):
    return {ref: sha for sha, ref in (
        line.split() for line in git("ls-remote", kind, "origin").splitlines()
    )}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    apply = parser.parse_args().apply
    plan = json.loads(PLAN.read_text())
    git("fetch", "origin", "--prune", "--tags")
    target = git("rev-parse", "origin/main")
    heads, tags = refs("--heads"), refs("--tags")
    changes, leases, decisions, closings = [], [], [], []
    for item in plan["branches"]:
        name, sha = item["name"], item["sha"]
        if not name.startswith("codex/") or not re.fullmatch("[0-9a-f]{40}", sha):
            raise ValueError("invalid fixed cleanup entry")
        ref = "refs/heads/" + name
        current = heads.get(ref)
        if current is None:
            decisions.append({"branch": name, "status": "already_absent"})
            continue
        if current != sha:
            raise ValueError("branch moved; refusing deletion: " + name)
        pr = api("/pulls/" + str(item["pr"]))
        if pr["head"]["sha"] != sha or pr["head"]["ref"] != name:
            raise ValueError("pull request no longer matches fixed cleanup plan")
        if item["mode"] == "merged":
            if not pr["merged_at"]:
                raise ValueError("expected merged PR")
            subprocess.run(["git", "merge-base", "--is-ancestor", sha, target], check=True)
        elif item["mode"] == "superseded":
            # Code, tests and focused docs match main byte-for-byte; only the older
            # roadmap differs. Archive the complete tip to retain that history too.
            base = git("merge-base", sha, target)
            paths = git("diff", "--name-only", base, sha).splitlines()
            covered = set(plan["superseded_covered_paths"])
            if set(paths) - covered - {"docs/roadmap.md"}:
                raise ValueError("unreviewed unique file on superseded branch")
            for path in set(paths).intersection(covered):
                if git("rev-parse", sha + ":" + path) != git("rev-parse", target + ":" + path):
                    raise ValueError("superseded content no longer matches main: " + path)
            tag = "refs/tags/" + item["archive"]
            if tag in tags and tags[tag] != sha:
                raise ValueError("archive tag already points elsewhere")
            if tag not in tags:
                changes.append(sha + ":" + tag)
            if pr["state"] == "open":
                closings.append(item["pr"])
        else:
            raise ValueError("unknown cleanup mode")
        leases.append("--force-with-lease=" + ref + ":" + sha)
        changes.append(":" + ref)
        decisions.append({"branch": name, "sha": sha, "status": "delete",
                          "reason": item["mode"], "archive": item.get("archive")})

    # On main after the documentation merge, remove the temporary work branch
    # only if its actual tip is already in main. The lease guards concurrent pushes.
    work = "refs/heads/" + plan["maintenance_branch"]
    if work in heads:
        sha = heads[work]
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, target], check=False
        ).returncode == 0
        if ancestor:
            leases.append("--force-with-lease=" + work + ":" + sha)
            changes.append(":" + work)
            decisions.append({"branch": plan["maintenance_branch"], "sha": sha,
                              "status": "delete", "reason": "merged maintenance"})
    if apply and changes:
        # Tags and deletions succeed as a single transaction; an old SHA cannot
        # delete a concurrently updated branch. Never delete main or unrelated refs.
        subprocess.run(["git", "push", "--atomic", *leases, "origin", *changes], check=True)
    if apply:
        for number in closings:
            api("/pulls/" + str(number), {"state": "closed"})
        after = refs("--heads")
        for entry in decisions:
            if entry["status"] == "delete" and "refs/heads/" + entry["branch"] in after:
                raise AssertionError("branch deletion was not observed")
    else:
        after = heads
    report = {"applied": apply, "main_sha": target, "decisions": decisions,
              "closed_superseded_prs": closings if apply else [],
              "remaining_branches": sorted(ref.removeprefix("refs/heads/") for ref in after)}
    out = ROOT / "outputs/maintenance"
    out.mkdir(parents=True, exist_ok=True)
    (out / ("cleanup-applied.json" if apply else "cleanup-preview.json")).write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
