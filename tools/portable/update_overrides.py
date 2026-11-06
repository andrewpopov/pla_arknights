"""Regenerate custom resource policy against a reviewed upstream baseline."""

import argparse
import base64
import json
import subprocess
from pathlib import Path


def difference(before, after):
    if before == after:
        return None
    if isinstance(before, dict) and isinstance(after, dict):
        properties = {}
        for name, value in after.items():
            patch = (
                difference(before[name], value)
                if name in before
                else {"replace": value}
            )
            if patch is not None:
                properties[name] = patch
        return {
            "properties": properties,
            "remove": sorted(before.keys() - after.keys()),
        }
    return {"replace": after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    a = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args])

    files = {}
    names = set(
        git("diff", "--name-only", "-z", a.base, "--", "resource")
        .decode()
        .strip("\0")
        .split("\0")
    )
    names.update(
        git("ls-files", "--others", "--exclude-standard", "-z", "--", "resource")
        .decode()
        .strip("\0")
        .split("\0")
    )
    for name in sorted(names - {""}):
        path = root / name
        relative = name[len("resource/") :]
        if not path.is_file():
            files[relative] = {"delete_file": True}
            continue
        before = subprocess.run(
            ["git", "-C", str(root), "show", a.base + ":" + name], capture_output=True
        )
        data = path.read_bytes()
        if before.returncode == 0 and before.stdout == data:
            continue
        if name.endswith(".json"):
            local = json.loads(data.decode("utf-8-sig"))
            delta = (
                difference(json.loads(before.stdout.decode("utf-8-sig")), local)
                if before.returncode == 0
                else {"replace": local}
            )
            files[relative] = {"json": delta}
        else:
            files[relative] = {"content_base64": base64.b64encode(data).decode("ascii")}
    target = root / "modules/strategy/local-resource-overrides.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"schema_version": 1, "upstream_base": a.base, "files": files},
            ensure_ascii=False,
            indent=4,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Protected {len(files)} custom resource files")


if __name__ == "__main__":
    main()
