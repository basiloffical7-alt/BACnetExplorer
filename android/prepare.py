"""Collect everything the APK needs into android_build/ (shared code + Android app)."""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "android_build")


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def main():
    keep = os.path.join(OUT, ".buildozer")          # keep the (big) build cache between runs
    if os.path.isdir(OUT):
        for name in os.listdir(OUT):
            if name not in (".buildozer", "bin"):
                p = os.path.join(OUT, name)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    os.makedirs(OUT, exist_ok=True)
    for name in ("main.py", "core.py", "graphics_core.py", "kivy_graphics.py", "platform_android.py",
                 "buildozer.spec"):
        copy(os.path.join(HERE, name), os.path.join(OUT, name))
    for name in os.listdir(os.path.join(HERE, "assets")):
        copy(os.path.join(HERE, "assets", name), os.path.join(OUT, "assets", name))
    for name in ("authcore.py", "xlsx_export.py"):
        copy(os.path.join(ROOT, name), os.path.join(OUT, name))
    for pkg, skip in (("bacnet", set()), ("graphics", {"panel.py"})):
        for name in os.listdir(os.path.join(ROOT, pkg)):
            if name.endswith(".py") and name not in skip:
                copy(os.path.join(ROOT, pkg, name), os.path.join(OUT, pkg, name))
    print("prepared", OUT, "(cache kept)" if os.path.isdir(keep) else "")


if __name__ == "__main__":
    main()
