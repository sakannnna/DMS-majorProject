"""打包当前交付文件与清理后的历史基线，不纳入本机业务数据。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/delivery/2026_ECNU_PJ1_2_陈建宇.zip"
ROOT_FILES = ("README.md", "requirements.txt", "start.bat", ".gitignore",
              "大作业一第一阶段.docx", "大作业一：需求变更.docx")


def run_git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()


def public_files():
    files = [ROOT / name for name in ROOT_FILES]
    extensions = {"app": {".py", ".js", ".css", ".html"}, "scripts": {".py", ".ps1"},
                  "tests": {".py"}, "docs": {".md", ".json", ".xml", ".png", ".jpg", ".jpeg"}}
    for directory, allowed in extensions.items():
        files.extend(p for p in (ROOT / directory).rglob("*")
                     if p.is_file() and p.suffix.lower() in allowed
                     and not any(x.startswith(".") or x == "__pycache__" for x in p.relative_to(ROOT).parts))
    files.extend(ROOT / "output/pdf" / name for name in
                 ("2026_ECNU_PJ1_1_陈建宇.pdf", "2026_ECNU_PJ1_2_陈建宇.pdf"))
    for p in files:
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT) or not p.is_file():
            raise RuntimeError(f"Missing or unsafe delivery file: {p}")
    return sorted(set(files))


def main():
    files = public_files()
    # 源码、报告正文和 PDF 必须与最终验证时的哈希一致，避免打包过期产物。
    version_path = ROOT / "docs/evidence/stage2-delivery-version.json"
    version = json.loads(version_path.read_text(encoding="utf-8"))
    for name, expected in version["sourceSha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Source changed after final verification: {name}")
    report = ROOT / "docs/阶段二报告.md"
    if hashlib.sha256(report.read_bytes()).hexdigest() != version["reportSourceSha256"]:
        raise RuntimeError("Report changed: regenerate PDF and verification evidence first")
    if hashlib.sha256((ROOT / "output/pdf/2026_ECNU_PJ1_2_陈建宇.pdf").read_bytes()).hexdigest() != version["reportPdfSha256"]:
        raise RuntimeError("Report PDF differs from the reviewed artifact")
    (ROOT / ".local").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="delivery-", dir=ROOT / ".local") as directory:
        temporary = Path(directory).resolve()
        assert temporary.parent == ROOT / ".local"
        checkout = temporary / "history"
        subprocess.run(["git", "clone", "--no-local", "--no-checkout", "--single-branch",
                        str(ROOT), str(checkout)], check=True, capture_output=True)
        metadata = checkout / ".git"
        (metadata / "config").write_text("[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tlogallrefupdates = false\n", encoding="utf-8")
        candidate = temporary / "delivery.zip"
        with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
            for path in files:
                archive.write(path, path.relative_to(ROOT).as_posix())
            for path in metadata.rglob("*"):
                rel = path.relative_to(metadata)
                if path.is_file() and rel.parts[0] not in ("hooks", "logs") and path.name not in ("FETCH_HEAD", "ORIG_HEAD"):
                    archive.write(path, ".git/" + rel.as_posix())
            archive.comment = ("Delivery working tree; base " + run_git("rev-parse", "HEAD") +
                               "; exact sources in docs/evidence/stage2-delivery-version.json").encode()
        with zipfile.ZipFile(candidate) as archive:
            if archive.testzip():
                raise RuntimeError("ZIP CRC failed")
            for path in files:
                if archive.read(path.relative_to(ROOT).as_posix()) != path.read_bytes():
                    raise RuntimeError(f"ZIP content differs: {path}")
            extracted = temporary / "verify"
            archive.extractall(extracted)
        for spec in ("stage1-final:app/database.py", "cbaec6a:app/database.py"):
            subprocess.run(["git", "-C", str(extracted), "show", spec], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, str(extracted / "scripts/check-docs.py"), "README.md", "docs/阶段二报告.md",
                        "docs/需求与设计.md", "docs/API说明.md", "docs/测试记录.md"], check=True, cwd=extracted)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        candidate.replace(OUTPUT)
    print(f"Delivery verified: {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
    print("SHA256: " + hashlib.sha256(OUTPUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
