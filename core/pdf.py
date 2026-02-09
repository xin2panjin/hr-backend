import asyncio
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

# 在Ubuntu上安装libreoffice： sudo apt install -y libreoffice

# 在windows上执行这个代码，要有两个必要条件
# 1. 要安装Office软件
# 2. 在项目中要安装pywin32这个库：uv add pywin32


class WordToPdfError(RuntimeError):
    pass


@dataclass(frozen=True)
class WordToPdfResult:
    pdf_path: str
    backend: str


class WordToPdfConverter:
    def __init__(
        self,
        word_path: str,
        *,
        output_pdf_path: Optional[str] = None,
        prefer_backend: str = "auto",
        soffice_path: Optional[str] = None,
        timeout_seconds: int = 300,
    ) -> None:
        self.word_path = str(word_path)
        self.output_pdf_path = str(output_pdf_path) if output_pdf_path else None
        self.prefer_backend = prefer_backend
        self.soffice_path = soffice_path
        self.timeout_seconds = int(timeout_seconds)

    async def convert(self) -> WordToPdfResult:
        word = Path(self.word_path)
        if not word.exists() or not word.is_file():
            raise WordToPdfError(f"Word file not found: {self.word_path}")

        suffix = word.suffix.lower()
        if suffix not in {".doc", ".docx"}:
            raise WordToPdfError(f"Unsupported file type: {suffix}")

        out_pdf = (
            Path(self.output_pdf_path)
            if self.output_pdf_path
            else word.with_suffix(".pdf")
        )
        out_pdf.parent.mkdir(parents=True, exist_ok=True)

        backend = self._select_backend()
        if backend == "office_com":
            await self._convert_via_office_com(word, out_pdf)
        elif backend == "libreoffice":
            await self._convert_via_libreoffice(word, out_pdf)
        else:
            raise WordToPdfError(f"Unknown backend selected: {backend}")

        if not out_pdf.exists() or out_pdf.stat().st_size == 0:
            raise WordToPdfError("Conversion finished but output PDF is missing/empty")

        return WordToPdfResult(pdf_path=str(out_pdf), backend=backend)

    def _select_backend(self) -> str:
        prefer = (self.prefer_backend or "auto").lower()
        if prefer not in {"auto", "office_com", "libreoffice"}:
            raise WordToPdfError(
                "prefer_backend must be one of: auto, office_com, libreoffice"
            )

        if prefer != "auto":
            if prefer == "office_com" and not self._is_windows():
                raise WordToPdfError("office_com backend requires Windows")
            return prefer

        if self._is_windows() and self._can_import_win32com():
            return "office_com"

        if self._find_soffice() is not None:
            return "libreoffice"

        if self._is_windows():
            raise WordToPdfError(
                "No available backend. Install pywin32 + Microsoft Word, "
                "or install LibreOffice and ensure soffice is in PATH."
            )

        raise WordToPdfError(
            "No available backend. Install LibreOffice and ensure soffice is in PATH."
        )

    @staticmethod
    def _is_windows() -> bool:
        return platform.system().lower() == "windows"

    @staticmethod
    def _can_import_win32com() -> bool:
        try:
            __import__("win32com.client")
            return True
        except Exception:
            return False

    def _find_soffice(self) -> Optional[str]:
        if self.soffice_path:
            p = Path(self.soffice_path)
            return str(p) if p.exists() else None

        which = shutil.which("soffice") or shutil.which("soffice.exe")
        return which

    async def _convert_via_libreoffice(self, word: Path, out_pdf: Path) -> None:
        soffice = self._find_soffice()
        if not soffice:
            raise WordToPdfError(
                "LibreOffice backend selected but soffice was not found"
            )

        with tempfile.TemporaryDirectory(prefix="word2pdf_") as tmpdir:
            tmpdir_p = Path(tmpdir)

            cmd = [
                soffice,
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--nodefault",
                "--norestore",
                "--invisible",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmpdir_p),
                str(word),
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError as e:
                proc.kill()
                raise WordToPdfError(
                    f"LibreOffice conversion timed out after {self.timeout_seconds}s"
                ) from e

            if proc.returncode != 0:
                raise WordToPdfError(
                    "LibreOffice conversion failed. "
                    f"stdout={stdout.decode(errors='ignore')}; "
                    f"stderr={stderr.decode(errors='ignore')}"
                )

            produced = tmpdir_p / f"{word.stem}.pdf"
            if not produced.exists():
                candidates = list(tmpdir_p.glob("*.pdf"))
                if len(candidates) == 1:
                    produced = candidates[0]
                else:
                    raise WordToPdfError(
                        "LibreOffice reported success but produced PDF was not found"
                    )

            if out_pdf.exists():
                out_pdf.unlink()
            shutil.move(str(produced), str(out_pdf))

    async def _convert_via_office_com(self, word: Path, out_pdf: Path) -> None:
        if not self._is_windows():
            raise WordToPdfError("Office COM conversion requires Windows")
        if not self._can_import_win32com():
            raise WordToPdfError("pywin32 (win32com) is required for Office COM backend")

        # Word COM automation is blocking and must run in a worker thread.
        await asyncio.wait_for(
            asyncio.to_thread(self._office_com_export_pdf_sync, word, out_pdf),
            timeout=self.timeout_seconds,
        )

    @staticmethod
    def _office_com_export_pdf_sync(word: Path, out_pdf: Path) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        word_app = None
        doc = None
        try:
            word_app = win32com.client.DispatchEx("Word.Application")
            word_app.Visible = False
            word_app.DisplayAlerts = 0

            # Open read-only to avoid modifying the source file.
            doc = word_app.Documents.Open(str(word), ReadOnly=True)

            # wdExportFormatPDF = 17
            doc.ExportAsFixedFormat(
                OutputFileName=str(out_pdf),
                ExportFormat=17,
                OpenAfterExport=False,
                OptimizeFor=0,
                CreateBookmarks=1,
            )
        except Exception as e:
            raise WordToPdfError(f"Office COM conversion failed: {e}")
        finally:
            try:
                if doc is not None:
                    doc.Close(False)
            except Exception:
                pass
            try:
                if word_app is not None:
                    word_app.Quit()
            except Exception:
                pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
