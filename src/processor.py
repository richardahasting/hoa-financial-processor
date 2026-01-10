"""Main orchestrator for HOA financial processing."""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import json

from .checkpoint import CheckpointManager
from .claude_client import ClaudeClient, TokenLimitError
from .image_extractor import ImageExtractor
from .excel_writer import ExcelWriter
from .markdown_writer import MarkdownWriter
from .parsers import (
    BalanceSheetParser, DisbursementsParser, InvoiceParser,
    BankReconciliationParser, AccountsReceivableParser, IncomeStatementParser,
    ExpenseTrendParser
)

logger = logging.getLogger(__name__)


class FinancialProcessor:
    """Orchestrates the processing of HOA financial PDF packages."""

    def __init__(
        self,
        pdf_path: Path,
        output_dir: Optional[Path] = None,
        checkpoint_dir: Optional[Path] = None,
        max_pages_per_chunk: int = 30
    ):
        """
        Initialize the processor.

        Args:
            pdf_path: Path to input PDF file
            output_dir: Directory for output files (default: data/output)
            checkpoint_dir: Directory for checkpoints (default: data/checkpoints)
            max_pages_per_chunk: Max pages per chunk when splitting
        """
        self.pdf_path = Path(pdf_path).resolve()
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")

        self.job_id = self.pdf_path.stem
        self.max_pages = max_pages_per_chunk

        # Set up directories
        project_root = Path(__file__).parent.parent
        self.output_dir = Path(output_dir) if output_dir else project_root / "data" / "output"
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else project_root / "data" / "checkpoints"

        # Split output goes next to input PDF
        self.split_dir = self.pdf_path.parent / f"{self.pdf_path.stem}-split"

        # Initialize components
        self.checkpoint = CheckpointManager(self.checkpoint_dir, self.job_id)
        self.claude = None  # Initialized on demand
        self.image_extractor = None

        # Parsed data storage
        self.balance_sheet_data = []
        self.disbursement_data = []
        self.invoice_data = []
        self.investment_data = []
        self.bank_reconciliation_data = []
        self.accounts_receivable_data = []
        self.income_statement_data = []
        self.expense_trend_data = []

    def _init_claude(self):
        """Initialize Claude client on demand."""
        if self.claude is None:
            self.claude = ClaudeClient()

    def _init_image_extractor(self):
        """Initialize image extractor on demand."""
        if self.image_extractor is None:
            images_dir = self.split_dir / "images"
            self.image_extractor = ImageExtractor(images_dir)

    def run(self, resume: bool = False):
        """
        Run the full processing pipeline.

        Args:
            resume: If True, resume from checkpoint
        """
        logger.info(f"Processing: {self.pdf_path}")
        logger.info(f"Job ID: {self.job_id}")

        if resume and self.checkpoint.can_resume():
            logger.info(f"Resuming from checkpoint:\n{self.checkpoint.summary()}")
        elif not resume:
            self.checkpoint.clear()

        try:
            # Step 1: Split PDF
            if not self.checkpoint.is_step_completed('split'):
                self._step_split()

            # Step 2: Detect report types in each chunk
            if not self.checkpoint.is_step_completed('detect'):
                self._step_detect_types()

            # Step 3: Parse each chunk based on type
            if not self.checkpoint.is_step_completed('parse'):
                self._step_parse()

            # Step 4: Process scanned images (OCR)
            if not self.checkpoint.is_step_completed('ocr'):
                self._step_ocr()

            # Step 5: Categorize transactions
            if not self.checkpoint.is_step_completed('categorize'):
                self._step_categorize()

            # Step 6: Generate Excel output
            if not self.checkpoint.is_step_completed('excel'):
                self._step_excel()

            self.checkpoint.mark_complete()
            logger.info("Processing complete!")

        except TokenLimitError as e:
            logger.warning(f"Token limit reached: {e}")
            self.checkpoint.mark_token_limit()
            logger.info("Progress saved. Resume later with --resume flag.")
            raise

        except Exception as e:
            logger.error(f"Processing failed: {e}")
            self.checkpoint.fail_step(
                self.checkpoint.state.get('current_step', 'unknown'),
                str(e)
            )
            raise

    def _step_split(self):
        """Step 1: Split PDF into chunks."""
        self.checkpoint.start_step('split')
        logger.info("Step 1: Splitting PDF...")

        # Find the split script
        split_script = Path.home() / "bin" / "split-hoa-financials.sh"
        if not split_script.exists():
            raise FileNotFoundError(f"Split script not found: {split_script}")

        # Run the split script
        result = subprocess.run(
            [str(split_script), str(self.pdf_path), str(self.max_pages)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Split failed: {result.stderr}")

        # Find markdown files
        md_files = sorted(self.split_dir.glob("markdown/*.md"))
        if not md_files:
            raise RuntimeError("No markdown files generated from split")

        self.checkpoint.set_data('markdown_files', [str(f) for f in md_files])
        self.checkpoint.complete_step('split', {'chunks': len(md_files)})
        logger.info(f"Split into {len(md_files)} chunks")

    def _step_detect_types(self):
        """Step 2: Detect report types per-page with batching."""
        self.checkpoint.start_step('detect')
        logger.info("Step 2: Detecting report types (per-page with batching)...")

        self._init_claude()

        # Read per-page text samples from /text/ directory
        text_dir = self.split_dir / "text"
        if not text_dir.exists():
            raise RuntimeError(f"Text directory not found: {text_dir}. Re-run split.")

        text_files = sorted(text_dir.glob("page-*.txt"))
        logger.info(f"  Found {len(text_files)} page text files")

        # Build page samples dict (page_id -> first 600 chars)
        page_samples = {}
        for txt_file in text_files:
            page_id = txt_file.stem.replace('-', '_')  # page-001 -> page_001
            with open(txt_file, 'r') as f:
                page_samples[page_id] = f.read(800)  # First 800 chars

        # Batch classify all pages
        page_types = self.claude.batch_detect_page_types(page_samples, batch_size=20)

        # Group consecutive pages of same type
        page_groups = self.claude.group_consecutive_pages(page_types)

        logger.info(f"  Detected {len(page_groups)} logical document groups:")
        for group in page_groups:
            page_range = f"{group['pages'][0]}-{group['pages'][-1]}" if len(group['pages']) > 1 else group['pages'][0]
            logger.info(f"    {group['type']}: {page_range} ({len(group['pages'])} pages)")

        # Save results
        self.checkpoint.set_data('page_types', page_types)
        self.checkpoint.set_data('page_groups', page_groups)

        # Save for inspection
        detect_dir = self.split_dir / "detected"
        detect_dir.mkdir(exist_ok=True)

        with open(detect_dir / "page_types.json", 'w') as f:
            json.dump(page_types, f, indent=2)

        with open(detect_dir / "page_groups.json", 'w') as f:
            json.dump(page_groups, f, indent=2)

        logger.info(f"Saved detection results to {detect_dir}/")
        self.checkpoint.complete_step('detect', {'groups': len(page_groups)})

    def _step_parse(self):
        """Step 3: Parse each page group based on detected type."""
        self.checkpoint.start_step('parse')
        logger.info("Step 3: Parsing page groups...")

        self._init_claude()

        # Load page groups from detection step
        page_groups = self.checkpoint.get_data('page_groups', [])
        text_dir = self.split_dir / "text"

        if not page_groups:
            raise RuntimeError("No page groups found. Re-run detection step.")

        # Initialize parsers
        balance_parser = BalanceSheetParser(self.claude)
        disb_parser = DisbursementsParser(self.claude)
        invoice_parser = InvoiceParser(self.claude)
        bank_recon_parser = BankReconciliationParser(self.claude)
        ar_parser = AccountsReceivableParser(self.claude)
        income_parser = IncomeStatementParser(self.claude)
        expense_trend_parser = ExpenseTrendParser(self.claude)

        for group_idx, group in enumerate(page_groups):
            report_type = group['type']
            pages = group['pages']
            group_id = f"group_{group_idx:02d}_{report_type}"

            # Check if already parsed
            parsed_key = f'parsed_{group_id}'
            if self.checkpoint.get_data(parsed_key):
                logger.info(f"  {group_id}: already parsed, skipping")
                continue

            page_range = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else pages[0]
            logger.info(f"  Parsing {group_id} ({page_range}, {len(pages)} pages)...")

            # Combine text from all pages in this group
            combined_text = ""
            for page_id in pages:
                # Convert page_001 back to page-001 for filename
                txt_file = text_dir / f"{page_id.replace('_', '-')}.txt"
                if txt_file.exists():
                    with open(txt_file, 'r') as f:
                        combined_text += f"\n\n--- {page_id} ---\n\n"
                        combined_text += f.read()

            try:
                records = []

                if report_type == 'balance_sheet':
                    records = balance_parser.parse(combined_text)
                    self.balance_sheet_data.extend(records)

                elif report_type == 'disbursements':
                    records = disb_parser.parse(combined_text)
                    self.disbursement_data.extend(records)

                elif report_type == 'invoice':
                    records = invoice_parser.parse_text_invoice(combined_text)
                    self.invoice_data.extend(records)

                elif report_type == 'investment_listing':
                    # Use balance sheet parser for now
                    records = balance_parser.parse(combined_text)
                    self.investment_data.extend(records)

                elif report_type == 'bank_reconciliation':
                    records = bank_recon_parser.parse(combined_text)
                    self.bank_reconciliation_data.extend(records)

                elif report_type == 'accounts_receivable':
                    records = ar_parser.parse(combined_text)
                    self.accounts_receivable_data.extend(records)

                elif report_type == 'income_statement':
                    records = income_parser.parse(combined_text)
                    self.income_statement_data.extend(records)

                elif report_type == 'expense_trend':
                    records = expense_trend_parser.parse(combined_text)
                    self.expense_trend_data.extend(records)

                elif report_type == 'scanned_image':
                    # Mark for OCR processing
                    logger.info(f"    Scanned pages - will process in OCR step")
                    records = [{'page_id': p, 'needs_ocr': True} for p in pages]

                else:
                    logger.warning(f"    Unknown type, skipping")

                # Save per-group results for debugging
                group_results_dir = self.split_dir / "parsed" / "per_group"
                group_results_dir.mkdir(parents=True, exist_ok=True)
                group_json = group_results_dir / f"{group_id}.json"
                with open(group_json, 'w') as f:
                    json.dump({
                        'group_id': group_id,
                        'detected_type': report_type,
                        'record_count': len(records),
                        'records': records
                    }, f, indent=2, default=str)
                logger.info(f"    Saved {len(records)} records to {group_json.name}")

                self.checkpoint.set_data(parsed_key, True)

            except TokenLimitError:
                # Save progress and re-raise
                self._save_parsed_data()
                raise

        self._save_parsed_data()
        self.checkpoint.complete_step('parse')

    def _save_parsed_data(self):
        """Save parsed data to checkpoint and intermediate JSON files."""
        self.checkpoint.set_data('balance_sheet_data', self.balance_sheet_data)
        self.checkpoint.set_data('disbursement_data', self.disbursement_data)
        self.checkpoint.set_data('invoice_data', self.invoice_data)
        self.checkpoint.set_data('investment_data', self.investment_data)
        self.checkpoint.set_data('bank_reconciliation_data', self.bank_reconciliation_data)
        self.checkpoint.set_data('accounts_receivable_data', self.accounts_receivable_data)
        self.checkpoint.set_data('income_statement_data', self.income_statement_data)
        self.checkpoint.set_data('expense_trend_data', self.expense_trend_data)

        # Also save as JSON files for easy inspection
        intermediate_dir = self.split_dir / "parsed"
        intermediate_dir.mkdir(exist_ok=True)

        for name, data in [
            ('balance_sheet', self.balance_sheet_data),
            ('disbursements', self.disbursement_data),
            ('invoices', self.invoice_data),
            ('investments', self.investment_data),
            ('bank_reconciliation', self.bank_reconciliation_data),
            ('accounts_receivable', self.accounts_receivable_data),
            ('income_statement', self.income_statement_data),
            ('expense_trend', self.expense_trend_data),
        ]:
            json_file = intermediate_dir / f"{name}.json"
            with open(json_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            logger.debug(f"Saved {len(data)} {name} records to {json_file}")

    def _load_parsed_data(self):
        """Load parsed data from checkpoint."""
        self.balance_sheet_data = self.checkpoint.get_data('balance_sheet_data', [])
        self.disbursement_data = self.checkpoint.get_data('disbursement_data', [])
        self.invoice_data = self.checkpoint.get_data('invoice_data', [])
        self.investment_data = self.checkpoint.get_data('investment_data', [])
        self.bank_reconciliation_data = self.checkpoint.get_data('bank_reconciliation_data', [])
        self.accounts_receivable_data = self.checkpoint.get_data('accounts_receivable_data', [])
        self.income_statement_data = self.checkpoint.get_data('income_statement_data', [])
        self.expense_trend_data = self.checkpoint.get_data('expense_trend_data', [])

    def _step_ocr(self):
        """Step 4: OCR scanned invoice pages."""
        self.checkpoint.start_step('ocr')
        logger.info("Step 4: OCR for scanned pages...")

        self._init_claude()
        self._init_image_extractor()
        self._load_parsed_data()

        # Get scanned pages from detection step
        page_groups = self.checkpoint.get_data('page_groups', [])
        scanned_groups = [g for g in page_groups if g['type'] == 'scanned_image']

        if not scanned_groups:
            logger.info("  No scanned pages detected, skipping OCR")
            self.checkpoint.complete_step('ocr')
            return

        # Count total scanned pages
        scanned_pages = []
        for group in scanned_groups:
            scanned_pages.extend(group['pages'])

        logger.info(f"  Found {len(scanned_pages)} scanned pages to OCR")

        # Individual page PDFs directory
        pages_dir = self.split_dir / "pages"
        images_dir = self.split_dir / "images" / "ocr"
        images_dir.mkdir(parents=True, exist_ok=True)

        invoice_parser = InvoiceParser(self.claude)
        ocr_results = []

        for page_id in scanned_pages:
            # Convert page_045 to page number 45
            page_num = int(page_id.replace('page_', ''))
            ocr_key = f'ocr_{page_id}'

            if self.checkpoint.get_data(ocr_key):
                logger.debug(f"    {page_id}: already processed, skipping")
                continue

            # Find the individual page PDF
            page_pdf = pages_dir / f"page-{page_num:03d}.pdf"
            if not page_pdf.exists():
                logger.warning(f"    {page_id}: PDF not found at {page_pdf}")
                continue

            logger.info(f"  OCR {page_id}...")

            try:
                # Convert page PDF to image
                image_path = images_dir / f"page-{page_num:03d}.png"

                if not image_path.exists():
                    # Use pdftoppm to convert single-page PDF to PNG
                    import subprocess
                    result = subprocess.run(
                        ['pdftoppm', '-png', '-r', '200', '-singlefile',
                         str(page_pdf), str(images_dir / f"page-{page_num:03d}")],
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        logger.error(f"    pdftoppm failed: {result.stderr}")
                        continue

                if image_path.exists():
                    # Use Tesseract for fast OCR
                    ocr_text = self.image_extractor.ocr_image(image_path)

                    if ocr_text:
                        # Parse OCR text into invoice structure
                        invoice = invoice_parser._extract_invoice_fields(ocr_text)
                        invoice['source_page'] = page_num
                        invoice['source_image'] = str(image_path)
                        invoice['ocr_text'] = ocr_text

                        # Add to invoice data if we got meaningful content
                        if invoice.get('amount') or invoice.get('vendor') or invoice.get('invoice_id'):
                            self.invoice_data.append(invoice)
                            logger.info(f"    Extracted: {invoice.get('vendor', 'Unknown')} - ${invoice.get('amount', 0):.2f}")
                        else:
                            # Store raw OCR text for review
                            ocr_results.append({
                                'page_id': page_id,
                                'page_num': page_num,
                                'ocr_text': ocr_text[:500],  # First 500 chars for review
                                'image_path': str(image_path)
                            })
                            logger.info(f"    OCR'd {len(ocr_text)} chars - no structured data extracted")
                    else:
                        logger.info(f"    No text extracted from image")

                self.checkpoint.set_data(ocr_key, True)

            except TokenLimitError:
                self._save_parsed_data()
                raise
            except Exception as e:
                logger.error(f"    OCR failed for {page_id}: {e}")
                continue

        # Save OCR results for manual review
        if ocr_results:
            ocr_results_file = self.split_dir / "parsed" / "ocr_raw_results.json"
            with open(ocr_results_file, 'w') as f:
                json.dump(ocr_results, f, indent=2, default=str)
            logger.info(f"  Saved {len(ocr_results)} raw OCR results to {ocr_results_file.name}")

        self._save_parsed_data()
        self.checkpoint.complete_step('ocr')
        logger.info(f"  OCR complete: {len(self.invoice_data)} invoices extracted")

    def _step_categorize(self):
        """Step 5: Categorize transactions."""
        self.checkpoint.start_step('categorize')
        logger.info("Step 5: Categorizing transactions...")

        self._init_claude()
        self._load_parsed_data()

        # Categorize disbursements that don't have categories
        for i, disb in enumerate(self.disbursement_data):
            if disb.get('category'):
                continue

            cat_key = f'cat_disb_{i}'
            if self.checkpoint.get_data(cat_key):
                continue

            try:
                category = self.claude.categorize_transaction(
                    disb.get('description', ''),
                    disb.get('amount', 0),
                    disb.get('vendor', '')
                )
                disb['category'] = category.get('category', '')
                disb['subcategory'] = category.get('subcategory', '')
                self.checkpoint.set_data(cat_key, True)

            except TokenLimitError:
                self._save_parsed_data()
                raise

        self._save_parsed_data()
        self.checkpoint.complete_step('categorize')

    def _step_excel(self):
        """Step 6: Generate Excel output."""
        self.checkpoint.start_step('excel')
        logger.info("Step 6: Generating Excel output...")

        self._load_parsed_data()

        # Generate output filename with date
        output_file = self.output_dir / f"{self.job_id}.xlsx"

        excel = ExcelWriter(output_file)

        # Add summary sheet
        summary = self._generate_summary()
        excel.add_summary(summary)

        # Add data sheets
        if self.balance_sheet_data:
            excel.add_balance_sheet(self.balance_sheet_data)

        if self.disbursement_data:
            excel.add_disbursements(self.disbursement_data)

        if self.invoice_data:
            excel.add_invoices(self.invoice_data)

        if self.investment_data:
            excel.add_investments(self.investment_data)

        if self.bank_reconciliation_data:
            excel.add_bank_reconciliation(self.bank_reconciliation_data)

        if self.accounts_receivable_data:
            excel.add_accounts_receivable(self.accounts_receivable_data)

        if self.income_statement_data:
            excel.add_income_statement(self.income_statement_data)

        if self.expense_trend_data:
            excel.add_expense_trend(self.expense_trend_data)

        excel.save()
        excel.close()

        # Generate LLM-optimized markdown summary
        md_file = self.output_dir / f"{self.job_id}_SUMMARY.md"
        markdown = MarkdownWriter(md_file)
        markdown.generate(
            summary=summary,
            balance_sheet_data=self.balance_sheet_data,
            disbursement_data=self.disbursement_data,
            expense_trend_data=self.expense_trend_data,
            income_statement_data=self.income_statement_data,
            accounts_receivable_data=self.accounts_receivable_data,
            bank_reconciliation_data=self.bank_reconciliation_data,
            report_date=summary.get('report_date')
        )

        self.checkpoint.complete_step('excel', {
            'output_file': str(output_file),
            'markdown_file': str(md_file)
        })
        logger.info(f"Excel output: {output_file}")
        logger.info(f"Markdown summary: {md_file}")

    def _generate_summary(self) -> Dict[str, Any]:
        """Generate summary statistics."""
        summary = {
            'report_date': datetime.now().strftime('%B %d, %Y'),
            'source_file': self.pdf_path.name,
            'checks_written': len(set(d.get('check_number') for d in self.disbursement_data if d.get('check_number'))),
        }

        # Calculate totals from balance sheet by summing categories
        total_assets = 0.0
        total_liabilities = 0.0
        total_equity = 0.0
        operating_funds = 0.0
        reserve_funds = 0.0

        for record in self.balance_sheet_data:
            category = record.get('category', '').lower()
            subcategory = record.get('subcategory', '').lower()
            balance = record.get('current_balance', 0) or 0

            if 'asset' in category:
                total_assets += balance
                # Check for operating vs reserve funds
                if 'operating' in subcategory or 'operating' in record.get('account_name', '').lower():
                    operating_funds += balance
                elif 'reserve' in subcategory or 'reserve' in record.get('account_name', '').lower():
                    reserve_funds += balance
            elif 'liabilit' in category:
                total_liabilities += abs(balance)  # Liabilities often stored as negative
            elif 'equity' in category:
                total_equity += balance

        summary['total_assets'] = total_assets
        summary['total_liabilities'] = total_liabilities
        summary['net_equity'] = total_assets - total_liabilities
        summary['operating_funds'] = operating_funds
        summary['reserve_funds'] = reserve_funds

        # Sum accounts receivable
        summary['accounts_receivable'] = sum(
            r.get('total_balance', 0) or 0 for r in self.accounts_receivable_data
        )

        # Sum disbursements
        summary['monthly_expenses'] = sum(d.get('amount', 0) or 0 for d in self.disbursement_data)

        return summary


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
