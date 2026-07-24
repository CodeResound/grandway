"""Nepal-specific constants."""

from zoneinfo import ZoneInfo

NEPAL_TIMEZONE = "Asia/Kathmandu"
NEPAL_TZ = ZoneInfo(NEPAL_TIMEZONE)

NEPAL_COUNTRY_CODE = "NP"

# Bikram Sambat month names (index 1-12). The BS calendar is retained — a
# consultancy operating in Nepal runs on it and on its fiscal year — but it is
# rendered in English only, like every other user-facing string.
BS_MONTH_NAMES_EN = {
    1: "Baisakh",
    2: "Jestha",
    3: "Ashadh",
    4: "Shrawan",
    5: "Bhadra",
    6: "Ashwin",
    7: "Kartik",
    8: "Mangsir",
    9: "Poush",
    10: "Magh",
    11: "Falgun",
    12: "Chaitra",
}
