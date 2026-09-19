#!/usr/bin/env python3
# Adds a "latest Kotlin Gradle plugin" step to the GitHub Actions workflow.
# Run from the folder you pushed to GitHub (the one that contains .github).
import re, sys
from pathlib import Path

STEP = r"""- name: Use the latest Kotlin Gradle plugin
  run: |
    KV=$(curl -fsSL https://repo1.maven.org/maven2/org/jetbrains/kotlin/kotlin-gradle-plugin/maven-metadata.xml | grep -oE '<version>[0-9]+\.[0-9]+\.[0-9]+</version>' | sed -E 's/<[^>]+>//g' | sort -V | tail -1)
    F=$(find . -path '*/android/settings.gradle*' | head -1)
    echo "Kotlin $KV -> $F"
    sed -i -E "s/(org\.jetbrains\.kotlin\.android\"\)? version \")[^\"]+\"/\1${KV}\"/" "$F"
    grep -n kotlin "$F"
"""

done = False
for wf in Path(".github/workflows").glob("*.yml"):
    text = wf.read_text()
    if "flutter build apk" not in text:
        continue
    if "latest Kotlin Gradle plugin" in text:
        print(f"{wf}: already patched")
        done = True
        continue
    m = re.search(r"^([ \t]*)- run: flutter pub get", text, re.M)
    if not m:
        sys.exit(f"Could not find the 'flutter pub get' step in {wf}")
    ind = m.group(1)
    block = "\n".join((ind + line) if line else line for line in STEP.splitlines()) + "\n"
    wf.write_text(text[:m.start()] + block + text[m.start():])
    print(f"Patched {wf}")
    done = True
if not done:
    sys.exit("No workflow with 'flutter build apk' found. Run this from the folder that contains .github")
print("Now run: git add -A && git commit -m 'Use latest Kotlin plugin' && git push")
