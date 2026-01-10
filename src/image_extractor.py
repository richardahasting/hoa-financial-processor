"""Extract images from PDF files for OCR processing."""

import subprocess
from pathlib import Path
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


class ImageExtractor:
    """Extract images from PDF files using poppler-utils or PyMuPDF."""

    def __init__(self, output_dir: Path):
        """
        Initialize image extractor.

        Args:
            output_dir: Directory to store extracted images
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._check_tools()

    def _check_tools(self):
        """Check which extraction tools are available."""
        self.has_pdfimages = self._command_exists('pdfimages')
        self.has_pdftoppm = self._command_exists('pdftoppm')

        try:
            import fitz
            self.has_pymupdf = True
        except ImportError:
            self.has_pymupdf = False

        if not any([self.has_pdfimages, self.has_pdftoppm, self.has_pymupdf]):
            raise RuntimeError(
                "No PDF image extraction tool available. "
                "Install poppler-utils or PyMuPDF."
            )

        logger.info(
            f"Image extraction tools: pdfimages={self.has_pdfimages}, "
            f"pdftoppm={self.has_pdftoppm}, pymupdf={self.has_pymupdf}"
        )

    def _command_exists(self, cmd: str) -> bool:
        """Check if a command exists."""
        try:
            subprocess.run(
                ['which', cmd],
                capture_output=True,
                check=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def extract_images_from_pdf(
        self,
        pdf_path: Path,
        prefix: str = "img",
        pages: Optional[tuple] = None
    ) -> List[Path]:
        """
        Extract all images from a PDF file.

        Args:
            pdf_path: Path to PDF file
            prefix: Prefix for output filenames
            pages: Optional (start, end) page range (1-indexed)

        Returns:
            List of paths to extracted images
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Create subdirectory for this PDF's images
        pdf_images_dir = self.output_dir / pdf_path.stem
        pdf_images_dir.mkdir(exist_ok=True)

        if self.has_pdfimages:
            return self._extract_with_pdfimages(pdf_path, pdf_images_dir, prefix, pages)
        elif self.has_pymupdf:
            return self._extract_with_pymupdf(pdf_path, pdf_images_dir, prefix, pages)
        elif self.has_pdftoppm:
            return self._extract_with_pdftoppm(pdf_path, pdf_images_dir, prefix, pages)

        return []

    def _extract_with_pdfimages(
        self,
        pdf_path: Path,
        output_dir: Path,
        prefix: str,
        pages: Optional[tuple]
    ) -> List[Path]:
        """Extract images using pdfimages (poppler-utils)."""
        cmd = ['pdfimages', '-png', '-j']  # Extract as PNG and JPEG

        if pages:
            cmd.extend(['-f', str(pages[0]), '-l', str(pages[1])])

        cmd.extend([str(pdf_path), str(output_dir / prefix)])

        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"pdfimages failed: {e.stderr}")
            return []

        # Find all extracted images
        images = list(output_dir.glob(f"{prefix}*"))
        logger.info(f"Extracted {len(images)} images with pdfimages")
        return sorted(images)

    def _extract_with_pymupdf(
        self,
        pdf_path: Path,
        output_dir: Path,
        prefix: str,
        pages: Optional[tuple]
    ) -> List[Path]:
        """Extract images using PyMuPDF (fitz)."""
        import fitz

        doc = fitz.open(pdf_path)
        images = []

        start_page = (pages[0] - 1) if pages else 0
        end_page = pages[1] if pages else len(doc)

        for page_num in range(start_page, end_page):
            page = doc[page_num]
            image_list = page.get_images(full=True)

            for img_idx, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]

                image_path = output_dir / f"{prefix}-p{page_num + 1}-{img_idx}.{image_ext}"
                with open(image_path, "wb") as f:
                    f.write(image_bytes)
                images.append(image_path)

        doc.close()
        logger.info(f"Extracted {len(images)} images with PyMuPDF")
        return images

    def _extract_with_pdftoppm(
        self,
        pdf_path: Path,
        output_dir: Path,
        prefix: str,
        pages: Optional[tuple]
    ) -> List[Path]:
        """Convert PDF pages to images using pdftoppm (for scanned PDFs)."""
        cmd = ['pdftoppm', '-png', '-r', '150']  # 150 DPI

        if pages:
            cmd.extend(['-f', str(pages[0]), '-l', str(pages[1])])

        cmd.extend([str(pdf_path), str(output_dir / prefix)])

        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"pdftoppm failed: {e.stderr}")
            return []

        # Find all converted images
        images = list(output_dir.glob(f"{prefix}*.png"))
        logger.info(f"Converted {len(images)} pages to images with pdftoppm")
        return sorted(images)

    def page_to_image(
        self,
        pdf_path: Path,
        page_num: int,
        dpi: int = 150
    ) -> Optional[Path]:
        """
        Convert a single PDF page to an image.

        Args:
            pdf_path: Path to PDF file
            page_num: Page number (1-indexed)
            dpi: Resolution for conversion

        Returns:
            Path to generated image or None
        """
        pdf_path = Path(pdf_path)
        output_dir = self.output_dir / pdf_path.stem
        output_dir.mkdir(exist_ok=True)

        output_prefix = output_dir / f"page-{page_num:03d}"

        if self.has_pdftoppm:
            cmd = [
                'pdftoppm', '-png', '-r', str(dpi),
                '-f', str(page_num), '-l', str(page_num),
                str(pdf_path), str(output_prefix)
            ]
            try:
                subprocess.run(cmd, capture_output=True, check=True)
                # pdftoppm adds page number suffix
                images = list(output_dir.glob(f"page-{page_num:03d}*.png"))
                if images:
                    return images[0]
            except subprocess.CalledProcessError as e:
                logger.error(f"pdftoppm failed: {e.stderr}")

        elif self.has_pymupdf:
            import fitz
            doc = fitz.open(pdf_path)
            page = doc[page_num - 1]
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            output_path = output_dir / f"page-{page_num:03d}.png"
            pix.save(str(output_path))
            doc.close()
            return output_path

        return None

    def is_page_scanned(
        self,
        pdf_path: Path,
        page_num: int,
        text_threshold: int = 50
    ) -> bool:
        """
        Detect if a PDF page is likely a scanned image (needs OCR).

        Args:
            pdf_path: Path to PDF file
            page_num: Page number (1-indexed)
            text_threshold: Minimum chars to consider as text PDF

        Returns:
            True if page appears to be scanned (little extractable text)
        """
        try:
            result = subprocess.run(
                ['pdftotext', '-f', str(page_num), '-l', str(page_num),
                 str(pdf_path), '-'],
                capture_output=True,
                text=True
            )
            text = result.stdout.strip()
            # If very little text extracted, likely scanned
            return len(text) < text_threshold
        except subprocess.CalledProcessError:
            return True  # Assume scanned if extraction fails

    def ocr_image(self, image_path: Path) -> str:
        """
        Run OCR on an image using Tesseract.

        Args:
            image_path: Path to image file

        Returns:
            Extracted text
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        try:
            result = subprocess.run(
                ['tesseract', str(image_path), 'stdout', '-l', 'eng'],
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.warning(f"Tesseract error: {result.stderr}")
                return ""
        except subprocess.TimeoutExpired:
            logger.warning(f"Tesseract timeout for {image_path}")
            return ""
        except FileNotFoundError:
            logger.error("Tesseract not installed")
            return ""
