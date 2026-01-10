"""Parser for Accounts Receivable / Delinquency and Prepaid reports."""

import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class AccountsReceivableParser:
    """Parse Delinquency and Prepaid Report into structured data."""

    def __init__(self, claude_client=None):
        """
        Initialize parser.

        Args:
            claude_client: Optional ClaudeClient for AI-assisted parsing
        """
        self.claude = claude_client

    def parse(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse accounts receivable text into structured records.

        Args:
            text: Raw text from delinquency/prepaid report

        Returns:
            List of account records with aging information
        """
        if self.claude:
            return self._parse_with_claude(text)
        return self._parse_with_regex(text)

    def _parse_with_regex(self, text: str) -> List[Dict[str, Any]]:
        """Parse using regex patterns."""
        records = []

        # Determine which section we're in
        current_section = None

        # Pattern for account lines
        # Account Id      Name                 Address              Legal   30 day  31-60   61-90  91-120  120+   Total
        account_pattern = re.compile(
            r'^(\d{5}-\d{4})\s+'  # Account ID (XXXXX-XXXX)
            r'(.+?)\s{2,}'        # Name
            r'(\d+\s+\w+.+?)\s{2,}'  # Address
            r'(-?[\d,.]+)\s+'     # 30 day
            r'(-?[\d,.]+)\s+'     # 31-60 day
            r'(-?[\d,.]+)\s+'     # 61-90 day
            r'(-?[\d,.]+)\s+'     # 91-120 day
            r'(-?[\d,.]+)\s+'     # 120+ day
            r'(-?[\d,.]+)'        # Total Balance
        )

        # Simpler pattern that's more flexible with spacing
        simple_pattern = re.compile(
            r'^(\d{5}-\d{4})\s+(.+?)(?:\s{2,}|\t)(.+?)(?:\s{2,}|\t)\s*'
            r'(-?[\d,]+\.?\d*)\s+(-?[\d,]+\.?\d*)\s+(-?[\d,]+\.?\d*)\s+'
            r'(-?[\d,]+\.?\d*)\s+(-?[\d,]+\.?\d*)\s+(-?[\d,]+\.?\d*)\s*$'
        )

        lines = text.split('\n')
        for i, line in enumerate(lines):
            # Track section
            if 'Outstanding Balances' in line:
                current_section = 'delinquent'
                continue
            elif 'Prepaid Balances' in line:
                current_section = 'prepaid'
                continue

            # Skip headers, totals, and empty lines
            if not line.strip() or 'Account Id' in line or 'Total Accounts' in line:
                continue
            if 'Outstanding Balance:' in line or 'Prepaid Balance:' in line:
                continue
            if 'Percentage' in line or 'Balance:' in line:
                continue

            # Try to match account line
            match = simple_pattern.match(line)
            if not match:
                # Try more flexible parsing
                parts = line.split()
                if len(parts) >= 8 and re.match(r'\d{5}-\d{4}', parts[0]):
                    try:
                        # Account ID is first
                        account_id = parts[0]
                        # Last 6 items are the amounts
                        amounts = parts[-6:]
                        # Everything in between is name + address
                        name_addr = ' '.join(parts[1:-6])

                        # Try to split name and address
                        # Usually address starts with a number
                        name_match = re.match(r'^(.+?)\s+(\d+\s+.+)$', name_addr)
                        if name_match:
                            name = name_match.group(1)
                            address = name_match.group(2)
                        else:
                            name = name_addr
                            address = ''

                        records.append({
                            'account_id': account_id,
                            'name': name.strip(),
                            'address': address.strip(),
                            'section': current_section or 'unknown',
                            'day_30': self._parse_amount(amounts[0]),
                            'day_31_60': self._parse_amount(amounts[1]),
                            'day_61_90': self._parse_amount(amounts[2]),
                            'day_91_120': self._parse_amount(amounts[3]),
                            'day_120_plus': self._parse_amount(amounts[4]),
                            'total_balance': self._parse_amount(amounts[5])
                        })
                    except (IndexError, ValueError) as e:
                        logger.debug(f"Could not parse line: {line} - {e}")
                continue

            # Process regex match
            records.append({
                'account_id': match.group(1),
                'name': match.group(2).strip(),
                'address': match.group(3).strip(),
                'section': current_section or 'unknown',
                'day_30': self._parse_amount(match.group(4)),
                'day_31_60': self._parse_amount(match.group(5)),
                'day_61_90': self._parse_amount(match.group(6)),
                'day_91_120': self._parse_amount(match.group(7)),
                'day_120_plus': self._parse_amount(match.group(8)),
                'total_balance': self._parse_amount(match.group(9))
            })

        logger.info(f"Parsed {len(records)} accounts receivable records with regex")
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
        """Parse using Claude for complex reports."""
        schema = """
        Return a JSON array of accounts receivable records. Each record should have:
        {
            "account_id": "XXXXX-XXXX format",
            "name": "owner/member name",
            "address": "property address",
            "section": "delinquent or prepaid",
            "day_30": numeric (current month),
            "day_31_60": numeric,
            "day_61_90": numeric,
            "day_91_120": numeric,
            "day_120_plus": numeric (oldest),
            "total_balance": numeric (positive for owed, negative for prepaid/credit)
        }

        Include both Outstanding Balances (delinquent) and Prepaid Balances sections.
        """

        example = """
        [
            {
                "account_id": "00339-2087",
                "name": "Brad S. Rose",
                "address": "1202 Brads Flight",
                "section": "delinquent",
                "day_30": 71.01,
                "day_31_60": 235.80,
                "day_61_90": 40.59,
                "day_91_120": 40.38,
                "day_120_plus": 4069.35,
                "total_balance": 4457.13
            },
            {
                "account_id": "00329-4570",
                "name": "Jeff Epstein",
                "address": "1126 Brads Flight",
                "section": "prepaid",
                "day_30": 0.00,
                "day_31_60": 0.00,
                "day_61_90": 0.00,
                "day_91_120": 0.00,
                "day_120_plus": -1403.60,
                "total_balance": -1403.60
            }
        ]
        """

        try:
            result = self.claude.parse_text_to_json(text, schema, example)
            if isinstance(result, list):
                logger.info(f"Parsed {len(result)} accounts receivable records with Claude")
                return result
            return []
        except Exception as e:
            logger.error(f"Claude parsing failed: {e}")
            return self._parse_with_regex(text)

    def get_summary(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate summary statistics from parsed records.

        Returns:
            Dictionary with totals and counts by section
        """
        summary = {
            'delinquent_count': 0,
            'delinquent_total': 0.0,
            'prepaid_count': 0,
            'prepaid_total': 0.0,
            'net_balance': 0.0
        }

        for record in records:
            if record.get('section') == 'delinquent':
                summary['delinquent_count'] += 1
                summary['delinquent_total'] += record.get('total_balance', 0)
            elif record.get('section') == 'prepaid':
                summary['prepaid_count'] += 1
                summary['prepaid_total'] += record.get('total_balance', 0)

        summary['net_balance'] = summary['delinquent_total'] + summary['prepaid_total']
        return summary
