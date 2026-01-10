"""Parser for Invoice documents (text and OCR)."""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class InvoiceParser:
    """Parse invoice documents into structured data."""

    def __init__(self, claude_client=None, image_extractor=None):
        """
        Initialize parser.

        Args:
            claude_client: ClaudeClient for AI-assisted parsing and OCR
            image_extractor: ImageExtractor for scanned invoice images
        """
        self.claude = claude_client
        self.image_extractor = image_extractor

    def parse_text_invoice(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse text-based invoice(s) from extracted PDF text.

        Args:
            text: Raw text containing invoice(s)

        Returns:
            List of invoice records
        """
        if self.claude:
            return self._parse_with_claude(text)
        return self._parse_with_regex(text)

    def parse_image_invoice(
        self,
        image_path: Path,
        page_num: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        OCR and parse a scanned invoice image.

        Args:
            image_path: Path to invoice image
            page_num: Source page number for reference

        Returns:
            Invoice record
        """
        if not self.claude:
            raise RuntimeError("Claude client required for OCR")

        logger.info(f"OCR processing: {image_path}")

        # Use Claude's multimodal capability for OCR
        ocr_result = self.claude.ocr_image_raw(
            image_path,
            context="scanned vendor invoice or receipt"
        )

        # Parse the OCR text into structured data
        invoice = self._extract_invoice_fields(ocr_result)
        invoice['source_page'] = page_num
        invoice['source_image'] = str(image_path)
        invoice['ocr_text'] = ocr_result

        return invoice

    def _parse_with_regex(self, text: str) -> List[Dict[str, Any]]:
        """Parse invoices using regex patterns."""
        invoices = []

        # Split text into potential invoice blocks
        # Look for "Invoice" headers
        invoice_blocks = re.split(r'(?=Invoice\s*ID\s*:)', text, flags=re.IGNORECASE)

        for block in invoice_blocks:
            if not block.strip() or len(block) < 50:
                continue

            invoice = self._extract_invoice_fields(block)
            if invoice.get('invoice_id') or invoice.get('vendor'):
                invoices.append(invoice)

        logger.info(f"Parsed {len(invoices)} invoices with regex")
        return invoices

    def _extract_invoice_fields(self, text: str) -> Dict[str, Any]:
        """Extract common invoice fields from text."""
        invoice = {
            'invoice_id': '',
            'invoice_date': '',
            'vendor': '',
            'description': '',
            'amount': 0.0,
            'line_items': [],
            'ocr_confidence': 'medium',
            'notes': ''
        }

        # Invoice ID
        id_match = re.search(r'Invoice\s*(?:ID|#|Number)\s*:?\s*(\S+)', text, re.IGNORECASE)
        if id_match:
            invoice['invoice_id'] = id_match.group(1).strip()

        # Invoice Date
        date_patterns = [
            r'Invoice\s*Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})',
            r'Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})',
            r'(\d{1,2}/\d{1,2}/\d{4})',
        ]
        for pattern in date_patterns:
            date_match = re.search(pattern, text, re.IGNORECASE)
            if date_match:
                invoice['invoice_date'] = self._parse_date(date_match.group(1))
                break

        # Amount - look for total
        amount_patterns = [
            r'Total\s*(?:Invoice\s*)?(?:Amt|Amount)\s*:?\s*\$?([\d,]+\.?\d*)',
            r'Invoice\s*Amt\s*:?\s*\$?([\d,]+\.?\d*)',
            r'Amount\s*Due\s*:?\s*\$?([\d,]+\.?\d*)',
            r'Total\s*:?\s*\$?([\d,]+\.?\d*)',
        ]
        for pattern in amount_patterns:
            amount_match = re.search(pattern, text, re.IGNORECASE)
            if amount_match:
                invoice['amount'] = self._parse_amount(amount_match.group(1))
                break

        # Vendor - look for company names at top
        vendor_patterns = [
            r'^([A-Z][A-Za-z\s]+(?:LLC|Inc|Corp|Company|Services)?)\s*$',
            r'Bill\s*(?:To|From)\s*:?\s*([A-Za-z][A-Za-z\s,]+)',
        ]
        lines = text.split('\n')[:20]  # Check first 20 lines
        for line in lines:
            for pattern in vendor_patterns:
                vendor_match = re.search(pattern, line.strip())
                if vendor_match:
                    potential_vendor = vendor_match.group(1).strip()
                    if len(potential_vendor) > 3 and not potential_vendor.lower().startswith('invoice'):
                        invoice['vendor'] = potential_vendor
                        break
            if invoice['vendor']:
                break

        # Description - look for description/notes section
        desc_match = re.search(
            r'Description\s*:?\s*(.+?)(?=Notes|Invoice|Total|$)',
            text,
            re.IGNORECASE | re.DOTALL
        )
        if desc_match:
            desc = desc_match.group(1).strip()
            # Clean up and truncate
            desc = re.sub(r'\s+', ' ', desc)[:500]
            invoice['description'] = desc

        return invoice

    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount string to float."""
        if not amount_str:
            return 0.0
        cleaned = re.sub(r'[,\s$]', '', amount_str)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _parse_date(self, date_str: str) -> str:
        """Parse date string to ISO format."""
        if not date_str:
            return ''
        try:
            dt = datetime.strptime(date_str.strip(), '%m/%d/%Y')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            return date_str

    def _parse_with_claude(self, text: str) -> List[Dict[str, Any]]:
        """Parse invoices using Claude for complex documents."""
        schema = """
        Extract ALL invoices from this text. Return a JSON array where each invoice has:
        {
            "invoice_id": "invoice number/ID",
            "invoice_date": "YYYY-MM-DD",
            "vendor": "vendor/company name",
            "description": "what the invoice is for",
            "amount": numeric total amount,
            "line_items": [
                {"description": "item/service", "amount": numeric}
            ],
            "notes": "any relevant notes or special items"
        }

        Be thorough - extract every invoice you find in the text.
        """

        example = """
        [
            {
                "invoice_id": "890931",
                "invoice_date": "2025-10-24",
                "vendor": "Associa OnCall",
                "description": "Gate issue/phone line repair at Park and Pool",
                "amount": 428.68,
                "line_items": [
                    {"description": "Service call", "amount": 428.68}
                ],
                "notes": "Recommended upgrade to cellular"
            }
        ]
        """

        try:
            result = self.claude.parse_text_to_json(text, schema, example)
            if isinstance(result, list):
                logger.info(f"Parsed {len(result)} invoices with Claude")
                return result
            return []
        except Exception as e:
            logger.error(f"Claude parsing failed: {e}")
            return self._parse_with_regex(text)

    def match_invoice_to_disbursement(
        self,
        invoice: Dict[str, Any],
        disbursements: List[Dict[str, Any]],
        tolerance: float = 0.01
    ) -> Optional[Dict[str, Any]]:
        """
        Try to match an invoice to a disbursement record.

        Args:
            invoice: Invoice record
            disbursements: List of disbursement records
            tolerance: Amount matching tolerance

        Returns:
            Matching disbursement record or None
        """
        invoice_amount = invoice.get('amount', 0)
        invoice_vendor = invoice.get('vendor', '').lower()

        for disb in disbursements:
            disb_amount = disb.get('amount', 0)
            disb_vendor = disb.get('vendor', '').lower()

            # Check amount match
            if abs(invoice_amount - disb_amount) <= tolerance:
                # Check vendor similarity
                if invoice_vendor and disb_vendor:
                    # Simple substring match
                    if invoice_vendor in disb_vendor or disb_vendor in invoice_vendor:
                        return disb

                # Amount match alone might be sufficient
                return disb

        return None
