"""Parser for Bank Reconciliation reports."""

import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BankReconciliationParser:
    """Parse Bank Reconciliation report text into structured data."""

    def __init__(self, claude_client=None):
        """
        Initialize parser.

        Args:
            claude_client: Optional ClaudeClient for AI-assisted parsing
        """
        self.claude = claude_client

    def parse(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse bank reconciliation text into structured records.

        Args:
            text: Raw text from bank reconciliation report

        Returns:
            List of reconciliation records (one per account)
        """
        if self.claude:
            return self._parse_with_claude(text)
        return self._parse_with_regex(text)

    def _parse_with_regex(self, text: str) -> List[Dict[str, Any]]:
        """Parse using regex patterns."""
        records = []

        # Split by account sections
        # Pattern: "Account: XXXX -- Name -- Type"
        account_pattern = re.compile(
            r'Account:\s*(\d{4})\s*--\s*(.+?)\s*--\s*(\w+)',
            re.IGNORECASE
        )

        # Split text into pages/sections
        pages = re.split(r'Page \d+ of \d+', text)

        for page in pages:
            if not page.strip():
                continue

            # Find account info
            acct_match = account_pattern.search(page)
            if not acct_match:
                continue

            account_code = acct_match.group(1)
            account_name = acct_match.group(2).strip()
            account_type = acct_match.group(3).strip()

            # Extract balances
            bank_balance = self._extract_amount(page, r'Balance per Bank:\s*([\d,.-]+)')
            gl_balance = self._extract_amount(page, r'Ending balance General Ledger:\s*([\d,.-]+)')
            difference = self._extract_amount(page, r'Difference:\s*([\d,.-]+)')

            # Extract outstanding items
            outstanding_deposits = self._extract_outstanding_items(page, 'deposits')
            outstanding_checks = self._extract_outstanding_items(page, 'checks')

            # Calculate totals
            total_deposits = self._extract_amount(
                page, r'Total deposits and outstanding debits:\s*([\d,.-]+)'
            )
            total_checks = self._extract_amount(
                page, r'Total outstanding checks:\s*\(?([\d,.-]+)\)?'
            )

            records.append({
                'account_code': account_code,
                'account_name': account_name,
                'account_type': account_type,
                'balance_per_bank': bank_balance,
                'outstanding_deposits': outstanding_deposits,
                'total_outstanding_deposits': total_deposits,
                'outstanding_checks': outstanding_checks,
                'total_outstanding_checks': total_checks,
                'ending_balance_gl': gl_balance,
                'difference': difference,
                'is_reconciled': abs(difference) < 0.01 if difference is not None else None
            })

        logger.info(f"Parsed {len(records)} bank reconciliation records with regex")
        return records

    def _extract_amount(self, text: str, pattern: str) -> Optional[float]:
        """Extract a single amount using pattern."""
        match = re.search(pattern, text)
        if match:
            return self._parse_amount(match.group(1))
        return None

    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount string to float."""
        if not amount_str:
            return 0.0
        # Handle parentheses for negative numbers
        negative = '(' in amount_str or amount_str.strip().startswith('-')
        cleaned = re.sub(r'[(),\s$]', '', amount_str)
        value = float(cleaned) if cleaned else 0.0
        return -value if negative and value > 0 else value

    def _extract_outstanding_items(self, text: str, item_type: str) -> List[Dict[str, Any]]:
        """Extract outstanding deposit or check items."""
        items = []

        if item_type == 'deposits':
            # Find section between "Plus deposits" and "Total deposits"
            section_match = re.search(
                r'Plus deposits and outstanding debits:(.*?)Total deposits',
                text, re.DOTALL | re.IGNORECASE
            )
        else:  # checks
            # Find section between "Less outstanding checks" and "Total outstanding checks"
            section_match = re.search(
                r'Less outstanding checks:(.*?)Total outstanding checks',
                text, re.DOTALL | re.IGNORECASE
            )

        if not section_match:
            return items

        section = section_match.group(1)

        # Skip "No outstanding" messages
        if 'No outstanding' in section:
            return items

        # Pattern for outstanding items:
        # Batch    Date       Description            Reference        Amount
        item_pattern = re.compile(
            r'(\d+)\s+(\d{2}/\d{2}/\d{4})\s+(.+?)\s{2,}(\S+)\s+([\d,.-]+)'
        )

        for match in item_pattern.finditer(section):
            items.append({
                'batch': match.group(1),
                'date': match.group(2),
                'description': match.group(3).strip(),
                'reference': match.group(4),
                'amount': self._parse_amount(match.group(5))
            })

        return items

    def _parse_with_claude(self, text: str) -> List[Dict[str, Any]]:
        """Parse using Claude for complex reports."""
        schema = """
        Return a JSON array of bank reconciliation records. Each record should have:
        {
            "account_code": "4-digit account code",
            "account_name": "account name",
            "account_type": "Operating or Reserves",
            "balance_per_bank": numeric,
            "outstanding_deposits": [
                {"batch": "batch#", "date": "MM/DD/YYYY", "description": "desc", "reference": "ref", "amount": numeric}
            ],
            "total_outstanding_deposits": numeric,
            "outstanding_checks": [
                {"batch": "batch#", "date": "MM/DD/YYYY", "description": "payee", "reference": "check#", "amount": numeric (negative)}
            ],
            "total_outstanding_checks": numeric (negative),
            "ending_balance_gl": numeric,
            "difference": numeric (should be 0 if reconciled),
            "is_reconciled": boolean
        }
        """

        example = """
        [
            {
                "account_code": "1011",
                "account_name": "HAR OPER #1137",
                "account_type": "Operating",
                "balance_per_bank": 3522.75,
                "outstanding_deposits": [
                    {"batch": "3977008", "date": "10/31/2025", "description": "check 1002", "reference": "10/25", "amount": 5500.00}
                ],
                "total_outstanding_deposits": 12300.00,
                "outstanding_checks": [
                    {"batch": "3975807", "date": "11/26/2025", "description": "Pedernales Electric", "reference": "Check No 00300447", "amount": -57.97}
                ],
                "total_outstanding_checks": -410.50,
                "ending_balance_gl": 15412.25,
                "difference": 0.00,
                "is_reconciled": true
            }
        ]
        """

        try:
            result = self.claude.parse_text_to_json(text, schema, example)
            if isinstance(result, list):
                logger.info(f"Parsed {len(result)} bank reconciliation records with Claude")
                return result
            return []
        except Exception as e:
            logger.error(f"Claude parsing failed: {e}")
            return self._parse_with_regex(text)
