"""Nepal-specific constants."""

from zoneinfo import ZoneInfo

NEPAL_TIMEZONE = "Asia/Kathmandu"
NEPAL_TZ = ZoneInfo(NEPAL_TIMEZONE)

NEPAL_COUNTRY_CODE = "NP"

# ISO 639-1 language codes used throughout the system
LANG_NEPALI = "ne"
LANG_ENGLISH = "en"
LANG_MIXED = "mixed"

# Bikram Sambat month names (index 1-12)
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

BS_MONTH_NAMES_NP = {
    1: "बैशाख",
    2: "जेठ",
    3: "असार",
    4: "श्रावण",
    5: "भाद्र",
    6: "असोज",
    7: "कार्तिक",
    8: "मंसिर",
    9: "पुष",
    10: "माघ",
    11: "फागुन",
    12: "चैत",
}

# Devanagari digits for display (index 0-9)
DEVANAGARI_DIGITS = "०१२३४५६७८९"
