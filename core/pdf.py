import asyncio
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

import io
from PIL import Image
import pymupdf

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


class PDF2ImageConverter:
    def __init__(self, dpi=150, quality=85, mode='balanced'):
        """
        初始化转换器

        Args:
            dpi: 基础分辨率
            quality: 图片质量 (1-100)
            mode: 压缩模式，可选:
                - 'max_compression': 最大压缩，保持可读性
                - 'balanced': 平衡压缩和质量 (默认)
                - 'ocr_optimized': 为OCR优化的压缩
                - 'fast': 快速转换，较少压缩
        """
        self.dpi = dpi
        self.quality = quality
        self.mode = mode

        # 根据模式调整参数
        self._apply_mode_settings()

    def _apply_mode_settings(self):
        """根据模式调整参数"""
        mode_settings = {
            'max_compression': {'dpi': 100, 'quality': 75, 'color_mode': 'grayscale'},
            'balanced': {'dpi': self.dpi, 'quality': 85, 'color_mode': 'color'},
            'ocr_optimized': {'dpi': 200, 'quality': 90, 'color_mode': 'grayscale'},
            'fast': {'dpi': 120, 'quality': 80, 'color_mode': 'color'}
        }

        settings = mode_settings.get(self.mode, mode_settings['balanced'])
        self.effective_dpi = settings['dpi']
        self.effective_quality = settings['quality']
        self.color_mode = settings['color_mode']

    def pdf_to_single_compressed_image(self, pdf_path, output_format='JPEG') -> io.BytesIO:
        """
        将PDF转换为单张压缩图片

        Args:
            pdf_path: PDF文件路径
            output_format: 输出格式，'JPEG' 或 'PNG'

        Returns:
            PIL.Image.Image对象，包含压缩后的图片数据
        """
        # 打开PDF
        doc = pymupdf.open(pdf_path)

        # 获取所有页面的图片
        images = self._extract_pdf_pages(doc)

        # 合并图片
        merged_image = self._merge_images(images)

        # 应用压缩优化
        compressed_image = self._compress_image(merged_image, output_format)

        # 清理内存
        doc.close()
        del images
        del merged_image

        return compressed_image

    def _extract_pdf_pages(self, doc):
        """提取PDF页面并优化"""
        images = []

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)

            # 根据模式选择矩阵
            zoom = self.effective_dpi / 72
            mat = pymupdf.Matrix(zoom, zoom)

            # 选择色彩空间
            if self.color_mode == 'grayscale':
                # 灰度模式，减少文件大小，提高OCR准确性
                colorspace = pymupdf.csGRAY
            else:
                colorspace = pymupdf.csRGB

            # 获取pixmap
            pix = page.get_pixmap(
                matrix=mat,
                colorspace=colorspace,
                alpha=False
            )

            # 转换为PIL Image
            img = Image.frombytes(
                "RGB" if colorspace == pymupdf.csRGB else "L",
                [pix.width, pix.height],
                pix.samples
            )

            images.append(img)

            # 及时清理
            del pix

        return images

    def _merge_images(self, images):
        """合并多张图片为一张长图"""
        if not images:
            raise ValueError("没有图片可合并")

        # 计算总尺寸
        total_height = sum(img.height for img in images)
        max_width = max(img.width for img in images)

        # 根据颜色模式创建新图片
        if self.color_mode == 'grayscale':
            merged_image = Image.new('L', (max_width, total_height), color=255)
        else:
            merged_image = Image.new('RGB', (max_width, total_height), color='white')

        # 拼接图片
        y_offset = 0
        for img in images:
            # 如果图片模式与合并图片模式不匹配，进行转换
            if self.color_mode == 'grayscale' and img.mode != 'L':
                img = img.convert('L')
            elif self.color_mode != 'grayscale' and img.mode != 'RGB':
                img = img.convert('RGB')

            merged_image.paste(img, (0, y_offset))
            y_offset += img.height

        return merged_image

    def _compress_image(self, image, output_format='JPEG'):
        """
        应用智能压缩策略

        压缩策略优先级:
        1. 减小尺寸（如果过大）
        2. 降低颜色深度
        3. 优化压缩参数
        4. 渐进式/交错编码
        """
        # 复制图片以避免修改原始
        img = image.copy()

        # 策略1: 如果图片过大，适当缩小尺寸
        max_pixels = 2000 * 2000  # 最大400万像素
        if img.width * img.height > max_pixels:
            scale_factor = (max_pixels / (img.width * img.height)) ** 0.5
            new_width = int(img.width * scale_factor)
            new_height = int(img.height * scale_factor)

            # 使用高质量缩放保持可读性
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # 策略2: 增强对比度（提高OCR准确性）
        if self.mode == 'ocr_optimized':
            img = self._enhance_for_ocr(img)

        # 策略3: 转换为8位颜色（减少文件大小）
        if img.mode == 'RGB':
            # 对于JPEG，可以进一步优化
            img = img.convert('RGB')  # 确保是RGB模式

        # 准备压缩参数
        save_kwargs = self._get_compression_params(output_format)

        # 保存到内存缓冲区
        buffer = io.BytesIO()
        img.save(buffer, format=output_format, **save_kwargs)
        buffer.seek(0)

        # 如果需要进一步压缩且格式允许
        if output_format == 'PNG' and buffer.getbuffer().nbytes > 1024 * 1024:  # 如果大于1MB
            buffer = self._further_compress_png(img, buffer)

        return buffer

    def _enhance_for_ocr(self, img):
        """为OCR优化图片"""
        from PIL import ImageEnhance, ImageFilter

        # 转换为灰度（如果还不是）
        if img.mode != 'L':
            img = img.convert('L')

        # 增强对比度
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.3)  # 增加30%对比度

        # 锐化边缘
        img = img.filter(ImageFilter.SHARPEN)

        # 轻微降噪
        img = img.filter(ImageFilter.MedianFilter(size=1))

        return img

    def _get_compression_params(self, format):
        """获取特定格式的压缩参数"""
        format = format.upper()

        if format == 'JPEG':
            return {
                'quality': self.effective_quality,
                'optimize': True,
                'progressive': True,  # 渐进式JPEG
                'subsampling': 0,  # 保持色度分辨率，有助于文字清晰度
                'qtables': 'web_low'  # 使用Web优化的量化表
            }
        elif format == 'PNG':
            return {
                'optimize': True,
                'compress_level': 9,  # 最高压缩级别
                'pnginfo': None
            }
        elif format == 'WEBP':
            return {
                'quality': self.effective_quality,
                'method': 6,  # 最高压缩效率
                'lossless': False
            }
        else:
            return {'quality': self.effective_quality, 'optimize': True}

    def _further_compress_png(self, img, original_buffer):
        """进一步压缩PNG图片"""
        try:
            # 尝试使用更激进的压缩
            buffer = io.BytesIO()

            # 如果图片颜色较少，尝试使用调色板模式
            if len(img.getcolors(256)) is not None:  # 颜色数小于256
                img_palette = img.convert('P', palette=Image.Palette.ADAPTIVE, colors=128)
                img_palette.save(buffer, format='PNG', optimize=True, compress_level=9)
            else:
                # 使用默认压缩
                img.save(buffer, format='PNG', optimize=True, compress_level=9)

            buffer.seek(0)

            # 如果新缓冲区更小，返回它
            if buffer.getbuffer().nbytes < original_buffer.getbuffer().nbytes:
                return buffer
            else:
                return original_buffer
        except:
            # 如果压缩失败，返回原始缓冲区
            return original_buffer

    def get_compression_report(self, original_size, compressed_buffer):
        """获取压缩报告"""
        compressed_size = compressed_buffer.getbuffer().nbytes

        return {
            'original_size_bytes': original_size,
            'compressed_size_bytes': compressed_size,
            'compression_ratio': compressed_size / original_size if original_size > 0 else 0,
            'size_reduction_percent': (1 - compressed_size / original_size) * 100 if original_size > 0 else 0,
            'compressed_size_mb': compressed_size / (1024 * 1024)
        }