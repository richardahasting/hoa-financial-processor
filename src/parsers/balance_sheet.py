"""Parser for Balance Sheet reports."""

import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BalanceSheetParser:
    """Parse Balance Sheet report text into structured data."""

    def __init__(self, claude_client=None):
        """
        Initialize parser.

        Args:
            claude_client: Optional ClaudeClient for AI-assisted parsing
        """
        self.claude = claude_client

    def parse(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse balance sheet text into structured records.

        Args:
            text: Raw text from balance sheet report

        Returns:
            List of account records
        """
        if self.claude:
            return self._parse_with_claude(text)
        return self._parse_with_regex(text)

    def _parse_with_regex(self, text: str) -> List[Dict[str, Any]]:
        """Parse using regex patterns."""
        records = []
        current_category = None
        current_subcategory = None

        # Pattern for account lines with numbers
        # e.g., "1001 - PPB #3118 Builder Bond    21,398.80    21,394.40    4.40"
        account_pattern = re.compile(
            r'^\s*(\d{4})\s*-\s*(.+?)\s+'
            r'(-?[\d,]+\.?\d*)\s+'
            r'(-?[\d,]+\.?\d*)\s+'
            r'(-?[\d,]+\.?\d*)?\s*$'
        )

        # Pattern for category headers
        category_pattern = re.compile(r'^\s*(Assets|Liabilities|Owners\' Equity)\s*$', re.IGNORECASE)

        # Pattern for subcategory (e.g., "Operating Funds", "Reserve Funds")
        subcategory_pattern = re.compile(r'^\s{2,10}([A-Z][a-zA-Z\s]+)\s*$')

        # Pattern for total lines
        total_pattern = re.compile(r'^\s*Total\s+', re.IGNORECASE)

        for line in text.split('\n'):
            # Skip empty lines and page markers
            if not line.strip() or 'Printed by' in line or 'Page ' in line:
                continue

            # Check for main category
            cat_match = category_pattern.match(line)
            if cat_match:
                current_category = cat_match.group(1)
                continue

            # Check for subcategory
            sub_match = subcategory_pattern.match(line)
            if sub_match and not total_pattern.match(line):
                potential_sub = sub_match.group(1).strip()
                # Avoid picking up account names as subcategories
                if not re.match(r'^\d{4}', potential_sub):
                    current_subcategory = potential_sub
                continue

            # Check for account line
            acct_match = account_pattern.match(line)
            if acct_match:
                try:
                    current = self._parse_amount(acct_match.group(3))
                    prior = self._parse_amount(acct_match.group(4))
                    change = self._parse_amount(acct_match.group(5)) if acct_match.group(5) else current - prior

                    records.append({
                        'account_code': acct_match.group(1),
                        'account_name': acct_match.group(2).strip(),
                        'category': current_category or 'Unknown',
                        'subcategory': current_subcategory or 'Unknown',
                        'current_balance': current,
                        'prior_balance': prior,
                        'change': change
                    })
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not parse line: {line} - {e}")

        logger.info(f"Parsed {len(records)} balance sheet records with regex")
        return records

    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount string to float."""
        if not amount_str:
            return 0.0
        # Handle parentheses for negative numbers
        negative = '(' in amount_str or amount_str.strip().startswith('-')
        cleaned = re.sub(r'[(),\s$]', '', amount_str)
        value = float(cleaned) if cleaned else 0.0
        return -value if negative and value > 0 else value

    def _parse_with_claude(self, text: str) -> List[Dict[str, Any]]:
        """Parse using Claude for complex or malformed reports."""
        schema = """
        Return a JSON array of account records. Each record should have:
        {
            "account_code": "4-digit account code",
            "account_name": "account description",
            "category": "Assets, Liabilities, or Owners' Equity",
            "subcategory": "e.g., Operating Funds, Reserve Funds, Accounts Payable",
            "current_balance": numeric (negative for credits/liabilities shown in parens),
            "prior_balance": numeric,
            "change": numeric (current - prior)
        }
        """

        example = """
        [
            {
                "account_code": "1001",
                "account_name": "PPB #3118 Builder Bond",
                "category": "Assets",
                "subcategory": "Operating Funds",
                "current_balance": 21398.80,
                "prior_balance": 21394.40,
                "change": 4.40
            }
        ]
        """

        try:
            result = self.claude.parse_text_to_json(text, schema, example)
            if isinstance(result, list):
                logger.info(f"Parsed {len(result)} balance sheet records with Claude")
                return result
            return []
        except Exception as e:
            logger.error(f"Claude parsing failed: {e}")
            # Fall back to regex
            return self._parse_with_regex(text)

    def extract_totals(self, text: str) -> Dict[str, float]:
        """
        Extract total amounts from balance sheet.

        Returns:
            Dictionary with total_assets, total_liabilities, etc.
        """
        totals = {}

        patterns = {
            'total_assets': r'Total\s+Assets\s+(-?[\d,]+\.?\d*)',
            'total_liabilities': r'Total\s+Liabilities\s+(-?[\d,]+\.?\d*)',
            'total_equity': r'Total\s+(?:Owners\'?\s+)?Equity\s+(-?[\d,]+\.?\d*)',
            'net_income': r'Net\s+Income\s*/?\s*\(?\s*Loss\s*\)?\s+(-?[\d,]+\.?\d*)',
            'operating_funds': r'Total\s+Operating\s+Funds\s+(-?[\d,]+\.?\d*)',
            'reserve_funds': r'Total\s+Reserve\s+Funds\s+(-?[\d,]+\.?\d*)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                totals[key] = self._parse_amount(match.group(1))

        return totals
