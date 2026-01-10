"""Parser for Check Disbursement reports."""

import re
from typing import List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DisbursementsParser:
    """Parse Check Disbursement reports into structured data."""

    def __init__(self, claude_client=None):
        """
        Initialize parser.

        Args:
            claude_client: Optional ClaudeClient for AI-assisted parsing
        """
        self.claude = claude_client

    def parse(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse disbursement text into structured records.

        Args:
            text: Raw text from disbursement report

        Returns:
            List of transaction records
        """
        if self.claude:
            return self._parse_with_claude(text)
        return self._parse_with_regex(text)

    def _parse_with_regex(self, text: str) -> List[Dict[str, Any]]:
        """Parse using regex patterns."""
        records = []
        current_vendor = None
        current_check = None
        current_check_date = None
        current_check_amount = None

        # Pattern for vendor header
        # e.g., "Associa Hill Country (11810) - The Enclave at Canyon Lake"
        vendor_pattern = re.compile(r'^([A-Za-z][^(]+)\s*\(\d+\)')

        # Pattern for check line
        # e.g., "Bank: Harmony Bank Operating      Check Number: 00200284        Check Date: 11/03/2025   Check Amount: 805.00"
        check_pattern = re.compile(
            r'Check\s+Number:\s*(\d+)\s+'
            r'Check\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})\s+'
            r'Check\s+Amount:\s*([\d,]+\.?\d*)'
        )

        # Pattern for transaction line
        # e.g., "123 - 7040 - Management Fees    11/01/2025   Management Fee    805.00"
        trans_pattern = re.compile(
            r'^\s*(\d+)\s*-\s*(\d+)\s*-\s*([^0-9]+?)\s+'
            r'(\d{1,2}/\d{1,2}/\d{4})\s+'
            r'(.+?)\s+'
            r'(-?[\d,]+\.?\d*)$'
        )

        # Simplified pattern for lines with just account and amount
        simple_trans_pattern = re.compile(
            r'^\s*\d+\s*-\s*(\d+)\s*-\s*(.+?)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(.+?)\s+([\d,]+\.?\d*)\s*$'
        )

        for line in text.split('\n'):
            line = line.rstrip()

            # Skip empty lines and page markers
            if not line.strip() or 'Printed by' in line or 'Page ' in line:
                continue

            # Check for vendor
            vendor_match = vendor_pattern.match(line)
            if vendor_match:
                current_vendor = vendor_match.group(1).strip()
                continue

            # Check for check header
            check_match = check_pattern.search(line)
            if check_match:
                current_check = check_match.group(1)
                current_check_date = self._parse_date(check_match.group(2))
                current_check_amount = self._parse_amount(check_match.group(3))
                continue

            # Try to match transaction line
            trans_match = trans_pattern.match(line)
            if not trans_match:
                trans_match = simple_trans_pattern.match(line)

            if trans_match:
                try:
                    # Handle both pattern formats
                    if len(trans_match.groups()) == 6:
                        dept, account, account_name, date, desc, amount = trans_match.groups()
                    else:
                        account = trans_match.group(1)
                        account_name = trans_match.group(2).strip()
                        date = trans_match.group(3)
                        desc = trans_match.group(4).strip()
                        amount = trans_match.group(5)

                    records.append({
                        'check_number': current_check or '',
                        'check_date': current_check_date or '',
                        'check_amount': current_check_amount or 0,
                        'vendor': current_vendor or 'Unknown',
                        'account_code': account.strip(),
                        'account_name': account_name.strip(),
                        'trans_date': self._parse_date(date),
                        'description': desc.strip(),
                        'amount': self._parse_amount(amount),
                        'category': ''  # Will be filled by categorization
                    })
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not parse transaction line: {line} - {e}")

        logger.info(f"Parsed {len(records)} disbursement records with regex")
        return records

    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount string to float."""
        if not amount_str:
            return 0.0
        cleaned = re.sub(r'[,\s$]', '', amount_str)
        return float(cleaned) if cleaned else 0.0

    def _parse_date(self, date_str: str) -> str:
        """Parse date string to ISO format."""
        if not date_str:
            return ''
        try:
            # Try MM/DD/YYYY
            dt = datetime.strptime(date_str.strip(), '%m/%d/%Y')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            return date_str

    def _parse_with_claude(self, text: str) -> List[Dict[str, Any]]:
        """Parse using Claude for complex reports."""
        schema = """
        Return a JSON array of transaction records from this check disbursement report.
        Each record should have:
        {
            "check_number": "check number",
            "check_date": "YYYY-MM-DD",
            "vendor": "vendor name",
            "account_code": "GL account code (4 digits)",
            "account_name": "account description",
            "description": "transaction description/memo",
            "amount": numeric amount
        }

        Parse ALL transaction lines, not just the first few.
        """

        example = """
        [
            {
                "check_number": "00200284",
                "check_date": "2025-11-03",
                "vendor": "Associa Hill Country",
                "account_code": "7040",
                "account_name": "Management Fees",
                "description": "Management Fee",
                "amount": 805.00
            }
        ]
        """

        try:
            result = self.claude.parse_text_to_json(text, schema, example)
            if isinstance(result, list):
                logger.info(f"Parsed {len(result)} disbursement records with Claude")
                return result
            return []
        except Exception as e:
            logger.error(f"Claude parsing failed: {e}")
            return self._parse_with_regex(text)

    def summarize_by_vendor(self, records: List[Dict[str, Any]]) -> Dict[str, float]:
        """Summarize total spending by vendor."""
        vendor_totals = {}
        for rec in records:
            vendor = rec.get('vendor', 'Unknown')
            amount = rec.get('amount', 0)
            vendor_totals[vendor] = vendor_totals.get(vendor, 0) + amount
        return dict(sorted(vendor_totals.items(), key=lambda x: -x[1]))

    def summarize_by_account(self, records: List[Dict[str, Any]]) -> Dict[str, float]:
        """Summarize total spending by account."""
        account_totals = {}
        for rec in records:
            key = f"{rec.get('account_code', '')} - {rec.get('account_name', '')}"
            amount = rec.get('amount', 0)
            account_totals[key] = account_totals.get(key, 0) + amount
        return dict(sorted(account_totals.items(), key=lambda x: -x[1]))
