"""Stage only Lambda source and runtime manifests; no uploads, tokens or frontend files."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "infra" / ".lambda-src"


def prepare():
    if TARGET.resolve() != ROOT / "infra" / ".lambda-src":
        raise RuntimeError("Refusing to replace a redirected staging directory")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    (TARGET / "backend").mkdir(parents=True)
    for source in (ROOT / "backend").glob("*.py"):
        shutil.copy2(source, TARGET / "backend" / source.name)
    shutil.copy2(ROOT / "backend" / "requirements-aws.txt", TARGET / "requirements.txt")
    shutil.copy2(ROOT / "backend" / "requirements-runtime.txt", TARGET / "requirements-runtime.txt")
    print("Prepared infra/.lambda-src: backend Python source and runtime requirements only.")


if __name__ == "__main__":
    prepare()
