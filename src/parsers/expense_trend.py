"""Parser for Income and Expense Trend Reports (monthly breakdown)."""

import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ExpenseTrendParser:
    """Parse Income and Expense Trend Report into structured data."""

    def __init__(self, claude_client=None):
        """
        Initialize parser.

        Args:
            claude_client: Optional ClaudeClient for AI-assisted parsing
        """
        self.claude = claude_client

    def parse(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse expense trend text into structured records.

        Args:
            text: Raw text from expense trend report

        Returns:
            List of line item records with monthly breakdown
        """
        if self.claude:
            return self._parse_with_claude(text)
        return self._parse_with_regex(text)

    def _parse_with_regex(self, text: str) -> List[Dict[str, Any]]:
        """Parse using regex patterns."""
        records = []
        current_section = None  # Income or Expense category
        current_category = None

        # Pattern for account lines with monthly amounts
        # Account Code - Name   Jan  Feb  Mar  Apr  May  Jun  Jul  Aug  Sep  Oct  Nov  Dec  FullYear  Budget
        account_pattern = re.compile(
            r'^\s*(\d{4})\s*-\s*(.+?)\s+'
            r'(-?[\d,().]+)\s+'  # Jan
            r'(-?[\d,().]+)\s+'  # Feb
            r'(-?[\d,().]+)\s+'  # Mar
            r'(-?[\d,().]+)\s+'  # Apr
            r'(-?[\d,().]+)\s+'  # May
            r'(-?[\d,().]+)\s+'  # Jun
            r'(-?[\d,().]+)\s+'  # Jul
            r'(-?[\d,().]+)\s+'  # Aug
            r'(-?[\d,().]+)\s+'  # Sep
            r'(-?[\d,().]+)\s+'  # Oct
            r'(-?[\d,().]+)\s+'  # Nov
            r'(-?[\d,().]*)\s*'  # Dec (might be empty/budget)
            r'(-?[\d,().]+)\s+'  # Full Year Actual
            r'(-?[\d,().]+)\s*$'  # Total Budget
        )

        # Simpler pattern - just grab account and try to parse amounts
        simple_pattern = re.compile(
            r'^\s*(\d{4})\s*-\s*([A-Za-z].*?)\s{2,}'
        )

        for line in text.split('\n'):
            # Skip empty lines and headers
            if not line.strip() or 'Printed by' in line or 'Page ' in line:
                continue

            # Track categories
            stripped = line.strip()

            # Check for category headers (lines without account codes)
            if (stripped and
                not stripped[0].isdigit() and
                not stripped.startswith('Total') and
                not stripped.startswith('Account') and
                not any(month in stripped for month in ['Jan', 'Feb', 'Mar', 'Actual', 'Budget']) and
                len(stripped) < 40):
                current_category = stripped
                continue

            # Try to match account line
            simple_match = simple_pattern.match(line)
            if simple_match:
                account_code = simple_match.group(1)
                account_name = simple_match.group(2).strip()

                # Extract all numbers from the rest of the line
                rest_of_line = line[simple_match.end():]
                amounts = re.findall(r'-?[\d,]+\.?\d*|\([\d,]+\.?\d*\)', rest_of_line)

                if len(amounts) >= 12:
                    try:
                        record = {
                            'account_code': account_code,
                            'account_name': account_name,
                            'category': current_category or 'Unknown',
                            'is_total': False,
                            'jan': self._parse_amount(amounts[0]) if len(amounts) > 0 else 0,
                            'feb': self._parse_amount(amounts[1]) if len(amounts) > 1 else 0,
                            'mar': self._parse_amount(amounts[2]) if len(amounts) > 2 else 0,
                            'apr': self._parse_amount(amounts[3]) if len(amounts) > 3 else 0,
                            'may': self._parse_amount(amounts[4]) if len(amounts) > 4 else 0,
                            'jun': self._parse_amount(amounts[5]) if len(amounts) > 5 else 0,
                            'jul': self._parse_amount(amounts[6]) if len(amounts) > 6 else 0,
                            'aug': self._parse_amount(amounts[7]) if len(amounts) > 7 else 0,
                            'sep': self._parse_amount(amounts[8]) if len(amounts) > 8 else 0,
                            'oct': self._parse_amount(amounts[9]) if len(amounts) > 9 else 0,
                            'nov': self._parse_amount(amounts[10]) if len(amounts) > 10 else 0,
                            'full_year_actual': self._parse_amount(amounts[-2]) if len(amounts) > 1 else 0,
                            'total_budget': self._parse_amount(amounts[-1]) if len(amounts) > 0 else 0,
                        }
                        records.append(record)
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Could not parse line: {line} - {e}")

            # Check for Total lines
            if stripped.startswith('Total '):
                total_match = re.match(r'Total\s+(.+?)\s{2,}', stripped)
                if total_match:
                    category_name = total_match.group(1).strip()
                    amounts = re.findall(r'-?[\d,]+\.?\d*|\([\d,]+\.?\d*\)', line)

                    if len(amounts) >= 2:
                        records.append({
                            'account_code': '',
                            'account_name': f'Total {category_name}',
                            'category': category_name,
                            'is_total': True,
                            'jan': self._parse_amount(amounts[0]) if len(amounts) > 0 else 0,
                            'feb': self._parse_amount(amounts[1]) if len(amounts) > 1 else 0,
                            'mar': self._parse_amount(amounts[2]) if len(amounts) > 2 else 0,
                            'apr': self._parse_amount(amounts[3]) if len(amounts) > 3 else 0,
                            'may': self._parse_amount(amounts[4]) if len(amounts) > 4 else 0,
                            'jun': self._parse_amount(amounts[5]) if len(amounts) > 5 else 0,
                            'jul': self._parse_amount(amounts[6]) if len(amounts) > 6 else 0,
                            'aug': self._parse_amount(amounts[7]) if len(amounts) > 7 else 0,
                            'sep': self._parse_amount(amounts[8]) if len(amounts) > 8 else 0,
                            'oct': self._parse_amount(amounts[9]) if len(amounts) > 9 else 0,
                            'nov': self._parse_amount(amounts[10]) if len(amounts) > 10 else 0,
                            'full_year_actual': self._parse_amount(amounts[-2]) if len(amounts) > 1 else 0,
                            'total_budget': self._parse_amount(amounts[-1]) if len(amounts) > 0 else 0,
                        })

        logger.info(f"Parsed {len(records)} expense trend records with regex")
        return records

    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount string to float."""
        if not amount_str:
            return 0.0
        # Handle parentheses for negative numbers
        negative = '(' in amount_str
        cleaned = re.sub(r'[(),\s$]', '', amount_str)
        value = float(cleaned) if cleaned else 0.0
        return -value if negative else value

    def _parse_with_claude(self, text: str) -> List[Dict[str, Any]]:
        """Parse using Claude for complex reports."""
        schema = """
        Return a JSON array of expense trend line items. Each record should have:
        {
            "account_code": "4-digit account code (empty for totals)",
            "account_name": "account name",
            "category": "expense category (Administrative, Utilities, etc.)",
            "is_total": boolean (true for Total lines),
            "jan": numeric (January actual),
            "feb": numeric (February actual),
            "mar": numeric (March actual),
            "apr": numeric (April actual),
            "may": numeric (May actual),
            "jun": numeric (June actual),
            "jul": numeric (July actual),
            "aug": numeric (August actual),
            "sep": numeric (September actual),
            "oct": numeric (October actual),
            "nov": numeric (November actual),
            "full_year_actual": numeric (sum of all months),
            "total_budget": numeric (annual budget)
        }

        Parse ALL line items including individual accounts AND totals.
        Numbers in parentheses are negative.
        """

        example = """
        [
            {
                "account_code": "5000",
                "account_name": "Administrative Supplies",
                "category": "Administrative",
                "is_total": false,
                "jan": 20.00,
                "feb": 0.00,
                "mar": 72.00,
                "apr": 63.00,
                "may": 188.00,
                "jun": 79.00,
                "jul": 242.00,
                "aug": 0.00,
                "sep": 70.00,
                "oct": 0.00,
                "nov": 342.00,
                "full_year_actual": 1076.00,
                "total_budget": 1100.00
            },
            {
                "account_code": "",
                "account_name": "Total Administrative",
                "category": "Administrative",
                "is_total": true,
                "jan": 107.00,
                "feb": 0.00,
                "mar": 407.00,
                "apr": 406.00,
                "may": 414.00,
                "jun": 313.00,
                "jul": 862.00,
                "aug": 0.00,
                "sep": 160.00,
                "oct": 0.00,
                "nov": 912.00,
                "full_year_actual": 3582.00,
                "total_budget": 2150.00
            }
        ]
        """

        try:
            result = self.claude.parse_text_to_json(text, schema, example)
            if isinstance(result, list):
                logger.info(f"Parsed {len(result)} expense trend records with Claude")
                return result
            return []
        except Exception as e:
            logger.error(f"Claude parsing failed: {e}")
            return self._parse_with_regex(text)

    def get_summary(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate summary comparing actuals to budget.

        Returns:
            Dictionary with total actuals, budget, and variance by category
        """
        summary = {
            'total_actual': 0.0,
            'total_budget': 0.0,
            'variance': 0.0,
            'categories': {}
        }

        for record in records:
            if record.get('is_total') and 'Total Income' not in record.get('account_name', ''):
                category = record.get('category', 'Unknown')
                actual = record.get('full_year_actual', 0)
                budget = record.get('total_budget', 0)

                summary['categories'][category] = {
                    'actual': actual,
                    'budget': budget,
                    'variance': budget - actual
                }

        # Calculate totals from Total Income and Total Expense if present
        for record in records:
            name = record.get('account_name', '').lower()
            if 'total income' in name:
                summary['total_income'] = record.get('full_year_actual', 0)
            elif 'total expense' in name or 'total operating expense' in name:
                summary['total_expense'] = record.get('full_year_actual', 0)
                summary['total_budget'] = record.get('total_budget', 0)

        return summary
