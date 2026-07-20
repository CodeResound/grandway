"""
Bikram Sambat (BS) ↔ Gregorian (AD) calendar utilities.

Design rules:
- PostgreSQL always stores Gregorian UTC. BS is always a derived projection.
- All conversions go through `nepalidate` from the `nepali` package.
- BS dates are never stored as primary values anywhere in the system.
- The fiscal year in Nepal runs Shrawan 1 (BS month 4) to Ashadh end (BS month 3
  of the next year), aligned to the BS calendar.
"""

from __future__ import annotations

from datetime import date, datetime

from nepali.datetime import nepalidate

from core.nepal.constants import (
    BS_MONTH_NAMES_EN,
    BS_MONTH_NAMES_NP,
    DEVANAGARI_DIGITS,
    NEPAL_TZ,
)


class BsDate:
    """Lightweight container for a Bikram Sambat date with display helpers."""

    def __init__(self, year: int, month: int, day: int) -> None:
        self.year = year
        self.month = month
        self.day = day

    @property
    def month_name_en(self) -> str:
        return BS_MONTH_NAMES_EN[self.month]

    @property
    def month_name_np(self) -> str:
        return BS_MONTH_NAMES_NP[self.month]

    @property
    def display_en(self) -> str:
        return f"{self.year} {self.month_name_en} {self.day}"

    @property
    def display_np(self) -> str:
        year_np = "".join(DEVANAGARI_DIGITS[int(d)] for d in str(self.year))
        day_np = "".join(DEVANAGARI_DIGITS[int(d)] for d in str(self.day))
        return f"{year_np} {self.month_name_np} {day_np}"

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "month_name_en": self.month_name_en,
            "month_name_np": self.month_name_np,
            "display_en": self.display_en,
            "display_np": self.display_np,
        }

    def to_date(self) -> date:
        return nepalidate(self.year, self.month, self.day).to_date()

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    def __repr__(self) -> str:
        return f"BsDate({self.year}, {self.month}, {self.day})"


def to_bs(dt: datetime | date) -> BsDate:
    """Convert a Gregorian datetime (UTC or naive) or date to a BsDate.

    For datetimes, localizes to NPT first so the BS date reflects what the
    calendar shows in Nepal — not the UTC calendar day.
    """
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            local_dt = dt.astimezone(NEPAL_TZ)
        else:
            local_dt = dt.replace(tzinfo=NEPAL_TZ)
        d = local_dt.date()
    else:
        d = dt
    nd = nepalidate.from_date(d)
    return BsDate(nd.year, nd.month, nd.day)


def to_gregorian(year: int, month: int, day: int) -> date:
    """Convert a Bikram Sambat date to a Gregorian date."""
    return nepalidate(year, month, day).to_date()


def parse_bs_string(bs_str: str) -> BsDate:
    """Parse a BS date string in YYYY-MM-DD format.

    Raises ValueError for invalid format or out-of-range values.
    """
    try:
        parts = bs_str.strip().split("-")
        if len(parts) != 3:
            raise ValueError
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid BS date format: '{bs_str}'. Expected YYYY-MM-DD.") from exc

    if not (1 <= month <= 12):
        raise ValueError(f"BS month must be 1-12, got {month}.")
    if not (1 <= day <= 32):
        raise ValueError(f"BS day out of range: {day}.")

    return BsDate(year, month, day)


def bs_string_to_gregorian(bs_str: str) -> date:
    """Parse a BS date string and return the equivalent Gregorian date."""
    bs = parse_bs_string(bs_str)
    return to_gregorian(bs.year, bs.month, bs.day)


def fiscal_year_label(bs: BsDate) -> str:
    """Return the Nepal fiscal year label for a BS date.

    Fiscal year runs Shrawan (month 4) to Ashadh (month 3 of next year).
    Example: BS 2082-01-01 (Baisakh, in FY end) → "2081/82"
             BS 2082-04-01 (Shrawan, FY start) → "2082/83"
    """
    if bs.month >= 4:
        start = bs.year
    else:
        start = bs.year - 1
    end_short = (start + 1) % 100
    return f"{start}/{end_short:02d}"


def fiscal_year_gregorian_range(fy_label: str) -> tuple[date, date]:
    """Return the Gregorian (start, end) date range for a Nepal fiscal year label.

    Fiscal year starts Shrawan 1 and ends Ashadh last day.
    The exact end day of Ashadh varies by year — we use day 31 as the safe
    upper bound (Ashadh is always 31 or 32 days).
    """
    try:
        parts = fy_label.strip().split("/")
        if len(parts) != 2:
            raise ValueError
        start_bs_year = int(parts[0])
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid fiscal year format: '{fy_label}'. Expected 'YYYY/YY'.") from exc

    end_bs_year = start_bs_year + 1
    fy_start = to_gregorian(start_bs_year, 4, 1)

    # Ashadh (month 3) of the end year — use day 31 as upper bound
    try:
        fy_end = to_gregorian(end_bs_year, 3, 31)
    except Exception:
        fy_end = to_gregorian(end_bs_year, 3, 30)

    return fy_start, fy_end


def nepal_today() -> date:
    """Return today's date in Nepal Standard Time (for date-only comparisons)."""
    from datetime import datetime

    return datetime.now(tz=NEPAL_TZ).date()
