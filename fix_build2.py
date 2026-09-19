#!/usr/bin/env python3
# 1) Replaces flutter_secure_storage (old Kotlin, likely cause of the build failure)
#    with shared_preferences.  2) Makes the workflow print the real build errors
#    at the end of the run.  Run from the folder that contains .github.
import re, sys
from pathlib import Path

root = Path.cwd()
notes = []


def edit(path, pairs):
    s = path.read_text()
    for old, new in pairs:
        if old in s:
            s = s.replace(old, new)
        else:
            notes.append(f"  (skipped, not found in {path.name}: {old[:45]!r})")
    path.write_text(s)
    print("Patched", path.relative_to(root))


found = {"pubspec": False, "api": False, "settings": False, "wf": False}

for p in root.rglob("pubspec.yaml"):
    if "venv" in p.parts or "node_modules" in p.parts:
        continue
    if "name: trade_companion" in p.read_text():
        edit(p, [("  flutter_secure_storage: ^9.2.2", "  shared_preferences: ^2.3.2")])
        found["pubspec"] = True

for p in root.rglob("api.dart"):
    if "FlutterSecureStorage" in p.read_text():
        edit(p, [
            ("import 'package:flutter_secure_storage/flutter_secure_storage.dart';",
             "import 'package:shared_preferences/shared_preferences.dart';"),
            ("  static const _store = FlutterSecureStorage();\n", ""),
            ("    host = await _store.read(key: 'host') ?? host;\n"
             "    token = await _store.read(key: 'token') ?? '';",
             "    final p = await SharedPreferences.getInstance();\n"
             "    host = p.getString('host') ?? host;\n"
             "    token = p.getString('token') ?? '';"),
            ("    await _store.write(key: 'host', value: host);\n"
             "    await _store.write(key: 'token', value: token);",
             "    final p = await SharedPreferences.getInstance();\n"
             "    await p.setString('host', host);\n"
             "    await p.setString('token', token);"),
        ])
        found["api"] = True
    elif "SharedPreferences" in p.read_text():
        found["api"] = True

for p in root.rglob("settings.dart"):
    if "kept in Android encrypted storage" in p.read_text():
        edit(p, [("kept in Android encrypted storage", "stored privately inside this app")])
        found["settings"] = True
    elif "stored privately inside this app" in p.read_text():
        found["settings"] = True

BUILD_STEP = r"""- name: Build APK
  run: |
    set -o pipefail
    flutter build apk --release 2>&1 | tee build.log
- name: Explain failure
  if: failure()
  run: |
    L=$(find . -name build.log | head -1)
    grep -n -E "^e: |What went wrong|Execution failed|incompatible version|Could not (resolve|find|get)|FAILURE:|error:" "$L" | cut -c1-300 | head -30 > /tmp/errs.txt
    cat /tmp/errs.txt
    { echo "### Build errors"; echo '```'; cat /tmp/errs.txt; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
"""

for wf in (root / ".github" / "workflows").glob("*.yml"):
    text = wf.read_text()
    if "flutter build apk" not in text:
        continue
    if "Explain failure" in text:
        print(wf.name, "already has the error summary step")
        found["wf"] = True
        continue
    m = re.search(r"^([ \t]*)- run: flutter build apk --release[ \t]*$", text, re.M)
    if not m:
        notes.append(f"  (could not find the plain 'flutter build apk --release' step in {wf.name})")
        continue
    ind = m.group(1)
    block = "\n".join((ind + l) if l else l for l in BUILD_STEP.splitlines())
    wf.write_text(text[:m.start()] + block + text[m.end():])
    print("Patched", wf.relative_to(root))
    found["wf"] = True

missing = [k for k, v in found.items() if not v]
for n in notes:
    print(n)
if missing:
    sys.exit("Not patched: " + ", ".join(missing) + ". Run this from the folder that contains .github")
print("\nNow run: git add -A && git commit -m 'Swap secure storage, add error summary' && git push")
