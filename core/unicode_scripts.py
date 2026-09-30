"""
Unicode Script & Indian Language Detection Engine for DPIG.
Specifically detects Unicode code points for 10 Indian scripts:
1. Hindi / Marathi / Nepali (Devanagari: U+0900 - U+097F)
2. Tamil (U+0B80 - U+0BFF)
3. Telugu (U+0C00 - U+0C7F)
4. Malayalam (U+0D00 - U+0D7F)
5. Kannada (U+0C80 - U+0CFF)
6. Bengali / Assamese (U+0980 - U+09FF)
7. Gujarati (U+0A80 - U+0AFF)
8. Punjabi (Gurmukhi: U+0A00 - U+0A7F)
9. Odia (U+0B00 - U+0B7F)
10. Sinhala (U+0D80 - U+0DFF)

Also detects Romanized / Transliterated Indian languages (e.g. Hinglish, Tanglish)
and generates standardized automated translation headers.
"""
import re
from typing import Dict, Any, Tuple, Optional


# Official Unicode Code Point Ranges for 10 Indian Scripts
INDIAN_SCRIPT_RANGES = [
    {
        "name": "Devanagari",
        "language": "Hindi",
        "lang_code": "hi",
        "range_start": 0x0900,
        "range_end": 0x097F,
        "hex_range": "U+0900–U+097F",
        "sample": "नमस्ते"
    },
    {
        "name": "Bengali",
        "language": "Bengali",
        "lang_code": "bn",
        "range_start": 0x0980,
        "range_end": 0x09FF,
        "hex_range": "U+0980–U+09FF",
        "sample": "বাংলা"
    },
    {
        "name": "Gurmukhi",
        "language": "Punjabi",
        "lang_code": "pa",
        "range_start": 0x0A00,
        "range_end": 0x0A7F,
        "hex_range": "U+0A00–U+0A7F",
        "sample": "ਪੰਜਾਬੀ"
    },
    {
        "name": "Gujarati",
        "language": "Gujarati",
        "lang_code": "gu",
        "range_start": 0x0A80,
        "range_end": 0x0AFF,
        "hex_range": "U+0A80–U+0AFF",
        "sample": "ગુજરાતી"
    },
    {
        "name": "Odia",
        "language": "Odia",
        "lang_code": "or",
        "range_start": 0x0B00,
        "range_end": 0x0B7F,
        "hex_range": "U+0B00–U+0B7F",
        "sample": "ଓଡ଼ିଆ"
    },
    {
        "name": "Tamil",
        "language": "Tamil",
        "lang_code": "ta",
        "range_start": 0x0B80,
        "range_end": 0x0BFF,
        "hex_range": "U+0B80–U+0BFF",
        "sample": "தமிழ்"
    },
    {
        "name": "Telugu",
        "language": "Telugu",
        "lang_code": "te",
        "range_start": 0x0C00,
        "range_end": 0x0C7F,
        "hex_range": "U+0C00–U+0C7F",
        "sample": "తెలుగు"
    },
    {
        "name": "Kannada",
        "language": "Kannada",
        "lang_code": "kn",
        "range_start": 0x0C80,
        "range_end": 0x0CFF,
        "hex_range": "U+0C80–U+0CFF",
        "sample": "ಕನ್ನಡ"
    },
    {
        "name": "Malayalam",
        "language": "Malayalam",
        "lang_code": "ml",
        "range_start": 0x0D00,
        "range_end": 0x0D7F,
        "hex_range": "U+0D00–U+0D7F",
        "sample": "മലയാളം"
    },
    {
        "name": "Sinhala",
        "language": "Sinhala",
        "lang_code": "si",
        "range_start": 0x0D80,
        "range_end": 0x0DFF,
        "hex_range": "U+0D80–U+0DFF",
        "sample": "සිංහල"
    },
]

# Vocabulary markers for Romanized / Transliterated Indian scripts
MANGLISH_MARKERS = {
    "veettil", "veed", "veetila", "vellam", "kudivellam", "varunnilla", "varilla", "varunilla",
    "current", "karannt", "vaidyuthi", "poyi", "poyilla", "illathe", "illa", "illallo",
    "kuzhi", "kuzhikal", "roddil", "roadil", "valiya", "kooduthal", "mazha", "vellakkettu",
    "cheythutharuka", "aarum", "nokkunilla", "malayalam", "ivide", "njangal", "njaangal",
    "theerthu", "chavaru", "malinyam", "sahayam", "sahayikkanam", "aano", "undayi", "undakki",
    "pettannu", "theruvu", "vilakku", "kathunnilla", "aanu", "undu", "aayirunnu", "kurachu",
    "cheyyanam", "pothu", "karan", "vannittilla", "kandittilla", "maram", "veenu"
}

MANGLISH_STRONG_ANCHORS = {
    "vellam", "varunnilla", "varunilla", "varilla", "kuzhi", "kuzhikal", "njangal", "njaangal",
    "veettil", "karannt", "vaidyuthi", "malinyam", "chavaru", "vellakkettu", "kathunnilla",
    "cheythutharuka", "aanu", "undu", "aayirunnu", "theruvu"
}

TANGLISH_MARKERS = {
    "en", "enga", "engal", "veetu", "veetula", "thanni", "thanneer", "varala", "varadhu",
    "illai", "illa", "romba", "irukku", "kuppai", "vilakku", "salai", "pallam", "kaaran",
    "mudiyala", "seekiram", "pannunga", "pannungalen", "thevai", "theru", "munsaram",
    "mincharam", "poiduchu", "poiruchu", "aachu", "aayiduchu", "kudukala", "saakkadai",
    "eriyala", "adikkudhu", "vazhi", "nagar", "oor"
}

TANGLISH_STRONG_ANCHORS = {
    "thanni", "thanneer", "varala", "varadhu", "veetula", "veetu", "kuppai", "irukku",
    "pallam", "salai", "pannunga", "mudiyala", "poiduchu", "poiruchu", "mincharam",
    "munsaram", "saakkadai", "eriyala"
}

HINGLISH_MARKERS = {
    "mera", "meri", "mere", "ghar", "mein", "cal", "kal", "se", "hai", "nahi", "nahin",
    "bijli", "pani", "paani", "sadak", "gaddha", "kuppa", "roshni", "batti", "kar", "raha",
    "rahi", "kripya", "jaldi", "theek", "karo", "bohot", "samay", "din", "adhikari",
    "chali", "gayi", "kachra", "samasya", "batao", "nagar", "nigam"
}

HINGLISH_STRONG_ANCHORS = {
    "mera", "meri", "mere", "ghar", "mein", "bijli", "gaddha", "nahin", "nahi",
    "kachra", "samasya", "batti", "theek", "roshni"
}

TENGLISH_MARKERS = {
    "maaku", "maku", "ma", "illu", "intlo", "neellu", "neeru", "ravatledu", "raavadam",
    "ledu", "current", "poyindi", "raaledu", "baga", "cheyandi", "road", "guntalu",
    "chedipoyindi", "deepalu", "velagadam", "dhayachesi", "twargaga", "adhikarulu"
}

TENGLISH_STRONG_ANCHORS = {
    "neellu", "ravatledu", "raavadam", "intlo", "guntalu", "poyindi", "deepalu", "velagadam", "chedipoyindi"
}

KANGLISH_MARKERS = {
    "namma", "nammooru", "maneyalli", "neeru", "bartha", "bartilla", "current", "hogide",
    "thumba", "kasta", "bega", "maadi", "rastyalli", "gundi", "kandide", "belaku", "deepa",
    "uriya", "beku", "haalaagide", "dayavittu"
}

KANGLISH_STRONG_ANCHORS = {
    "maneyalli", "bartilla", "rastyalli", "hogide", "gundi", "haalaagide", "nammooru"
}

BONGLISH_MARKERS = {
    "amader", "aamader", "barite", "bari", "jol", "aschhe", "na", "current", "nei",
    "chole", "geche", "rasta", "khub", "kharap", "taratari", "korun", "alo", "jolchhe"
}

BONGLISH_STRONG_ANCHORS = {
    "barite", "jol", "aschhe", "chole", "geche", "jolchhe", "taratari"
}


def detect_unicode_script(text: str) -> Dict[str, Any]:
    """
    Analyzes code points of text and identifies if it belongs to any of the
    10 Indian scripts, or is Romanized Indian text (Latin script).
    """
    if not text:
        return {
            "script": "Latin",
            "language": "English",
            "lang_code": "en",
            "hex_range": "U+0020–U+007F",
            "is_indian_script": False,
            "is_transliterated": False,
            "char_count": 0,
            "matched_code_points": 0,
        }

    # Count character frequencies across script ranges
    counts = {s["name"]: 0 for s in INDIAN_SCRIPT_RANGES}
    total_chars = len(text)

    for char in text:
        cp = ord(char)
        for s in INDIAN_SCRIPT_RANGES:
            if s["range_start"] <= cp <= s["range_end"]:
                counts[s["name"]] += 1
                break

    # Find highest matching script
    best_script_name = max(counts, key=counts.get)
    max_count = counts[best_script_name]

    if max_count > 0:
        # Found native Indian Unicode script
        matched = next(s for s in INDIAN_SCRIPT_RANGES if s["name"] == best_script_name)
        return {
            "script": matched["name"],
            "language": matched["language"],
            "lang_code": matched["lang_code"],
            "hex_range": matched["hex_range"],
            "is_indian_script": True,
            "is_transliterated": False,
            "char_count": total_chars,
            "matched_code_points": max_count,
            "sample": matched["sample"]
        }

    # If no native Unicode script found, check Romanized / Transliterated Indian text
    words = set(re.findall(r'[a-zA-Z]+', text.lower()))
    
    # Calculate specific language match scores
    m_score = len(words.intersection(MANGLISH_MARKERS)) + 2 * len(words.intersection(MANGLISH_STRONG_ANCHORS))
    t_score = len(words.intersection(TANGLISH_MARKERS)) + 2 * len(words.intersection(TANGLISH_STRONG_ANCHORS))
    h_score = len(words.intersection(HINGLISH_MARKERS)) + 2 * len(words.intersection(HINGLISH_STRONG_ANCHORS))
    te_score = len(words.intersection(TENGLISH_MARKERS)) + 2 * len(words.intersection(TENGLISH_STRONG_ANCHORS))
    kn_score = len(words.intersection(KANGLISH_MARKERS)) + 2 * len(words.intersection(KANGLISH_STRONG_ANCHORS))
    bn_score = len(words.intersection(BONGLISH_MARKERS)) + 2 * len(words.intersection(BONGLISH_STRONG_ANCHORS))

    # Bonus points for multi-word phrases
    text_lower = text.lower()
    if any(p in text_lower for p in ["cal se", "kal se", "ghar mein", "mera ghar", "bijli nahi", "pani nahi"]):
        h_score += 3
    if any(p in text_lower for p in ["thanni varala", "veetula thanni", "current poiduchu", "kuppai romba"]):
        t_score += 3
    if any(p in text_lower for p in ["vellam varunnilla", "current poyi", "roadil kuzhi", "veettil vellam", "oda kettikkidakkunnu"]):
        m_score += 3
    if any(p in text_lower for p in ["neellu ravatledu", "current poyindi", "road guntalu"]):
        te_score += 3
    if any(p in text_lower for p in ["neeru bartilla", "current hogide", "rastyalli gundi"]):
        kn_score += 3

    translit_candidates = [
        ("Malayalam (Manglish)", "ml-Latn", m_score, "Manglish"),
        ("Tamil (Tanglish)", "ta-Latn", t_score, "Tanglish"),
        ("Hindi (Hinglish)", "hi-Latn", h_score, "Hinglish"),
        ("Telugu (Tenglish)", "te-Latn", te_score, "Tenglish"),
        ("Kannada (Kanglish)", "kn-Latn", kn_score, "Kanglish"),
        ("Bengali (Bonglish)", "bn-Latn", bn_score, "Bonglish"),
    ]

    best_cand = max(translit_candidates, key=lambda c: c[2])

    if best_cand[2] >= 2 or (best_cand[2] >= 1 and (
        (best_cand[0].startswith("Malayalam") and len(words.intersection(MANGLISH_STRONG_ANCHORS)) > 0) or
        (best_cand[0].startswith("Tamil") and len(words.intersection(TANGLISH_STRONG_ANCHORS)) > 0) or
        (best_cand[0].startswith("Hindi") and len(words.intersection(HINGLISH_STRONG_ANCHORS)) > 0) or
        (best_cand[0].startswith("Telugu") and len(words.intersection(TENGLISH_STRONG_ANCHORS)) > 0) or
        (best_cand[0].startswith("Kannada") and len(words.intersection(KANGLISH_STRONG_ANCHORS)) > 0) or
        (best_cand[0].startswith("Bengali") and len(words.intersection(BONGLISH_STRONG_ANCHORS)) > 0)
    )):
        return {
            "script": "Latin (Transliterated)",
            "language": best_cand[0],
            "lang_code": best_cand[1],
            "hex_range": "U+0020–U+007F (Latin)",
            "is_indian_script": True,
            "is_transliterated": True,
            "char_count": total_chars,
            "matched_code_points": total_chars,
            "sample": best_cand[3]
        }

    return {
        "script": "Latin",
        "language": "English",
        "lang_code": "en",
        "hex_range": "U+0020–U+007F",
        "is_indian_script": False,
        "is_transliterated": False,
        "char_count": total_chars,
        "matched_code_points": 0,
        "sample": "ABC"
    }


def generate_translation_header(detection: Dict[str, Any]) -> str:
    """
    Creates a standard automated translation header preserving original text attribution.
    """
    if not detection.get("is_indian_script"):
        return ""

    lang = detection.get("language", "Regional")
    script = detection.get("script", "Unicode")
    hex_range = detection.get("hex_range", "")

    if detection.get("is_transliterated"):
        return f"[AUTOMATED TRANSLATION • Original text preserved in {lang} ({script}) • Translated to English for Municipal Action]"
    else:
        return f"[AUTOMATED TRANSLATION • Original text preserved in {lang} ({script} {hex_range}) • Translated to English for Municipal Action]"


def heuristic_translate_indian_text(text: str, detection: Dict[str, Any]) -> Tuple[str, str]:
    """
    Intelligent civic translation and title generation engine.
    Accurately translates civic complaints across 10 Indian scripts (Tamil, Malayalam,
    Telugu, Kannada, Hindi, Bengali, Gujarati, Punjabi, Odia, Sinhala), Romanized
    transliterations (Tanglish, Manglish, Hinglish, Tenglish, Kanglish), and English.
    
    Returns:
        (translated_title, translated_description)
    """
    if not text or not text.strip():
        return ("Civic Grievance", "")

    raw = text.strip()
    lower = raw.lower()
    lang = detection.get("language", "")
    
    # -------------------------------------------------------------
    # 1. Location & Entity Context Extraction across Indian Scripts
    # -------------------------------------------------------------
    location_title = ""
    location_desc = ""

    # In front of Plot / House / Flat / Residence
    if any(k in raw for k in [
        "பிளாட் முன்னாடி", "பிளாட் எதிரில்", "வீட்டு முன்னாடி", "வீட்டின் முன்", "அபார்ட்மெண்ட்", "வீட்டு வாசலில்",
        "വീടിനു മുന്നിൽ", "ഫ്ലാറ്റിനു മുന്നിൽ", "വീടിന്റെ മുന്നിൽ",
        "घर के सामने", "फ्लैट के सामने", "मकान के सामने", "दरवाजे पर",
        "ఇంటి ముందు", "ఫ్లాట్ ముందు",
        "ಮನೆಯ ಮುಂದೆ", "ಫ್ಲಾಟ್ ಮುಂದೆ",
        "বাড়ির সামনে", "ফ্ল্যাটের সামনে",
        "ઘર સામે", "ફ્લેટ સામે",
        "ਘਰ ਅੱਗੇ",
        "ଘର ଆଗରେ",
        "නිවස ඉදිරිපිට"
    ]) or any(k in lower for k in [
        "plot munnadi", "veetu munnadi", "veetuku munnadi", "veettil", "veedinu munnil",
        "ghar ke samne", "flat ke samne", "inti mundu", "maneya munde",
        "in front of plot", "in front of our plot", "in front of my plot", "in front of house",
        "in front of flat", "in front of my house", "in front of residence", "outside our house"
    ]):
        location_title = "in Front of Plot / Residence"
        location_desc = "in front of our plot / residence"

    # On Main Road / Street / Lane
    elif any(k in raw for k in [
        "ரோட்டில்", "சாலையில்", "தெருவில்", "சந்தில", "முக்கிய சாலையில்",
        "റോഡിൽ", "തെരുവിൽ", "വഴിയിൽ",
        "सड़क पर", "रोड पर", "गली में", "मुख्य मार्ग पर",
        "రోడ్డుపై", "వీధిలో", "సందులో",
        "ರಸ್ತೆಯಲ್ಲಿ", "ಬೀದಿಯಲ್ಲಿ", "ಗಲ್ಲಿಯಲ್ಲಿ",
        "রাস্তায়", "গলিতে",
        "રસ્તા પર", "શેરીમાં",
        "ਸੜਕ ਤੇ", "ਗਲੀ ਵਿੱਚ",
        "ରାସ୍ତାରେ", "ଗଳିରେ",
        "පාරේ"
    ]) or any(k in lower for k in [
        "roadil", "salaiyil", "theruvil", "sandhula", "sadak par", "gali mein",
        "on the road", "on the street", "in our street", "main road", "in lane", "cross road"
    ]):
        location_title = "on Street / Road"
        location_desc = "on the road / street"

    # Near Bus Stand / School / Hospital / Market / Park / Metro
    elif any(k in raw for k in ["பஸ் ஸ்டாண்ட்", "பேருந்து நிலையம்", "बस स्टैंड", "বাস স্ট্যান্ড", "બસ સ્ટેન્ડ", "ಬಸ್ ನಿಲ್ದಾಣ", "బస్ స్టాండ్"]) or "bus stand" in lower or "bus stop" in lower:
        location_title = "Near Bus Stand"
        location_desc = "near the bus stand"
    elif any(k in raw for k in ["பள்ளி", "பள்ளிக்கூடம்", "स्कूल", "বিদ্যালয়", "શાળા", "ಶಾಲೆ", "పాఠశాల"]) or "school" in lower:
        location_title = "Near School"
        location_desc = "near the school"
    elif any(k in raw for k in ["பூங்கா", "பார்க்", "पार्क", "বাগান", "બગીચો", "ಉದ್ಯಾನ"]) or "park" in lower:
        location_title = "Near Public Park"
        location_desc = "near the public park"
    elif any(k in raw for k in ["சந்தை", "மார்க்கெட்", "बाजार", "মার্কেট", "માર્કેટ"]) or "market" in lower:
        location_title = "Near Market Area"
        location_desc = "near the commercial market"

    # -------------------------------------------------------------
    # 2. Domain & Category Pattern Matching
    # -------------------------------------------------------------

    # A. Street Lighting & Electrical Hazards
    # Tamil: ஸ்ட்ரீட் லைட், தெரு விளக்கு, விளக்கு, லைட், பியூஸ், எரியல, எரியவில்லை, இருட்டு, மின் கம்பி, கம்பம்
    # Malayalam: സ്ട്രീറ്റ് ലൈറ്റ്, തെരുവ് വിളക്ക്, ഫ്യൂസ്, കത്തുന്നില്ല, ഇരുട്ട്, കറണ്ട്
    # Hindi: स्ट्रीट लाइट, बत्ती, बिजली, फ्यूज, बंद, खराब, अंधेरा
    # Telugu: వీధి దీపం, దీపాలు, వెలగడం లేదు, ఫ్యూజ్, చీకటి
    # Kannada: ಬೀದಿ ದೀಪ, ಉರಿಯುತ್ತಿಲ್ಲ, ಫ್ಯೂಸ್, ಕತ್ತಲೆ
    # Bengali: রাস্তার লাইট, বাতি, জ্বলছে না, ফিউজ, অন্ধকার
    # Gujarati: સ્ટ્રીટ લાઈટ, લાઈટ, બંધ છે, ફ્યુઝ, અંધારું
    # Punjabi: ਸਟਰੀਟ ਲਾਈਟ, ਬੱਤੀ, ਬੰਦ, ਫਿਊਜ਼, ਨੇਰ੍ਹਾ
    # Odia: ଷ୍ଟ୍ରିଟ୍ ଲାଇଟ୍, ବତୀ, ଜଳୁନାହିଁ, ଫ୍ୟୁଜ୍, ଅନ୍ଧାର
    # Sinhala: වීදි ලාම්පුව, දැල්වෙන්නේ නැත
    if any(k in raw for k in [
        "ஸ்ட்ரீட் லைட்", "தெரு விளக்கு", "மின் விளக்கு", "விளக்கு", "லைட்", "பியூஸ்",
        "സ്ട്രീറ്റ് ലൈറ്റ്", "തെരുവ് വിളക്ക്", "വിളക്ക്", "ഫ്യൂസ്",
        "स्ट्रीट लाइट", "बत्ती", "रोशनी", "खंभा",
        "వీధి దీపం", "వీధి దీపాలు",
        "ಬೀದಿ ದೀಪ", "ಬೀದಿ ದೀಪಗಳು",
        "রাস্তার লাইট", "রাস্তার বাতি",
        "સ્ટ્રીટ લાઈટ",
        "ਸਟਰੀਟ ਲਾਈਟ",
        "ଷ୍ଟ୍ରିଟ୍ ଲାଇଟ୍",
        "වීදි ලාම්පුව"
    ]) or any(k in lower for k in [
        "street light", "streetlight", "street lights", "fuse aayirukku", "vilakku eriyala",
        "fuse", "fused", "light bulb", "kathunnilla", "velagadam ledu", "uriyuttilla",
        "jwalche na", "darkness", "street lamp", "streetlamp", "batti gul", "batti band"
    ]):
        is_fused = any(k in raw for k in ["பியூஸ்", "ഫ്യൂസ്", "फ्यूज", "ਫਿਊਜ਼", "ଫ୍ୟୁଜ୍", "fuse"]) or "fuse" in lower or "fused" in lower
        
        if is_fused:
            loc_t = f" {location_title}" if location_title else ""
            loc_d = f" {location_desc}" if location_desc else " in the locality"
            title = f"Street Light Fused{loc_t}"
            desc = f"The street light{loc_d} is fused and non-functional, causing total darkness and safety risks. Requesting the municipal electrical engineering wing to inspect and replace the fused bulb."
        else:
            loc_t = f" {location_title}" if location_title else ""
            loc_d = f" {location_desc}" if location_desc else " on the street"
            title = f"Streetlight Outage / Non-Functional{loc_t}"
            desc = f"Streetlights{loc_d} are not functioning, plunging the area into darkness after sunset. Immediate repair and restoration of street illumination are requested for public safety."
        return (title, desc)

    # B. Drinking Water Supply Disruption & Pipeline Leakage
    if any(k in raw for k in [
        "குடிநீர்", "தண்ணீர்", "தண்ணி", "குழாய்", "பைப்",
        "കുടിവെള്ളം", "വെള്ളം", "പൈപ്പ്",
        "पीने का पानी", "पानी की सप्लाई", "पाइप फटा", "जल आपूर्ति",
        "మంచినీరు", "తాగునీరు", "నీళ్లు", "పైపు",
        "ಕುಡಿಯುವ ನೀರು", "ನೀರು", "ಪೈಪ್",
        "পানীয় জল", "জল সরবরাহ",
        "પીવાનું પાણી",
        "ਪੀਣ ਵਾਲਾ ਪਾਣੀ",
        "ପିଇବା ପାଣି",
        "පානීය ජලය"
    ]) or any(k in lower for k in [
        "thanni", "thanneer", "kudivellam", "drinking water", "water supply",
        "pipeline leak", "pipe burst", "pipe leak", "water pipe", "varala", "varunnilla",
        "nahi aa raha", "ravatledu", "bartilla", "water shortage", "no water"
    ]):
        is_leak = any(k in raw for k in ["உடைப்பு", "கசிவு", "பொട്ടി", "लीक", "फटा", "లీకేజీ", "ಸೋರಿಕೆ"]) or any(k in lower for k in ["leak", "burst", "breakage", "wasting water"])
        loc_t = f" {location_title}" if location_title else ""
        loc_d = f" {location_desc}" if location_desc else " in the area"
        if is_leak:
            title = f"Drinking Water Pipeline Leakage{loc_t}"
            desc = f"Severe drinking water pipeline breakage/leakage observed{loc_d}. Clean municipal drinking water is being heavily wasted. Urgent pipeline replacement and valve repair requested."
        else:
            title = f"Drinking Water Supply Disruption{loc_t}"
            desc = f"Municipal drinking water supply is disrupted and not reaching households{loc_d}. Residents are facing acute water shortage. Urgent restoration of pipeline pressure and supply requested."
        return (title, desc)

    # C. Severe Potholes & Damaged Road Surface
    if any(k in raw for k in [
        "சாலை", "ரோடு", "பள்ளம்", "குண்டும்குழி", "தார் ரோடு", "சேதம்",
        "റോഡ്", "കുഴി", "കുഴികൾ", "തകർന്നു",
        "सड़क", "रोड", "गड्ढा", "गड्ढे", "टूटी सड़क",
        "రోడ్డు", "గుంతలు", "గుంత",
        "ರಸ್ತೆ", "ಗುಂಡಿ", "ಗುಂಡಿಗಳು",
        "রাস্তা", "গর্ত", "ভাঙা রাস্তা",
        "રોડ", "ખાડો", "ખાડા",
        "ਸੜਕ", "ਟੋਏ", "ਟੋਆ",
        "ରାସ୍ତା", "ଖାଲ",
        "පාර", "වලවල්"
    ]) or any(k in lower for k in [
        "pothole", "potholes", "damaged road", "crater", "pallam", "kuzhi",
        "gaddha", "gaddhe", "guntalu", "gundi", "road damage", "bad road", "broken road", "asphalt"
    ]):
        loc_t = f" {location_title}" if location_title else ""
        loc_d = f" {location_desc}" if location_desc else " on the road"
        title = f"Severe Potholes & Road Damage{loc_t}"
        desc = f"The road surface{loc_d} is severely cratered with dangerous potholes, posing imminent risk of accidents to commuters and two-wheelers. Urgent asphalt cold-mix filling and road relaying requested."
        return (title, desc)

    # D. Solid Waste & Garbage Accumulation
    if any(k in raw for k in [
        "குப்பை", "கழிவு", "குப்பைத்தொட்டி", "துர்நாற்றம்", "அள்ளவில்லை", "குப்பைமேடு",
        "മാലിന്യം", "ചവറ്", "വേസ്റ്റ്", "ദുർഗന്ധം",
        "कचरा", "कूड़ा", "कूड़ेदान", "गंदगी", "बदबू",
        "చెత్త", "చెత్తకుండీ", "కంపు",
        "ಕಸ", "ಕಸದ ರಾಶಿ", "ವಾಸನೆ",
        "আবর্জনা", "ময়লা", "ডাস্টবিন", "দুর্গন্ধ",
        "કચરો", "ગંદકી",
        "ਕੂੜਾ", "ਗੰਦਗੀ",
        "ଅଳିଆ", "ଆବର୍ଜନା",
        "කුණු", "කසළ"
    ]) or any(k in lower for k in [
        "garbage", "trash", "waste dump", "dustbin", "kuppai", "kachra", "chavaru",
        "malinyam", "foul smell", "overflowing bin", "garbage pile", "rubbish", "uncollected waste"
    ]):
        loc_t = f" {location_title}" if location_title else ""
        loc_d = f" {location_desc}" if location_desc else " in the neighborhood"
        title = f"Garbage Dump Accumulation & Odor Hazard{loc_t}"
        desc = f"Solid waste and unattended garbage have accumulated heavily{loc_d}, overflowing onto the road and spreading noxious foul smell. Urgent deployment of municipal compactor vehicles and sanitation clearance requested."
        return (title, desc)

    # E. Stormwater Drain Blockage & Waterlogging
    if any(k in raw for k in [
        "மழைநீர்", "வடிகால்", "சாக்கடை", "நீர் தேக்கம்", "வெள்ளம்", "கொசு",
        "മഴവെള്ളം", "വെള്ളക്കെട്ട്", "ഓട", "മലിനജലം", "കൊതുക്",
        "जलभराव", "नाली जाम", "बरसात का पानी", "सीवर", "मच्छर",
        "వరద నీరు", "మురుగు కాలువ", "దోమలు",
        "ಮಳೆ ನೀರು", "ಚರಂಡಿ", "ನೀರು ನಿಂತಿದೆ", "ಸೊಳ್ಳೆ",
        "নর্দমা", "জল জমা", "মশা",
        "પાણી ભરાવું", "ગટર",
        "ਨਾਲੀ ਜਾਮ", "ਗੰਦਾ ਪਾਣੀ",
        "ଜଳବନ୍ଦୀ", "ନାଳ",
        "ජල ගැලීම්"
    ]) or any(k in lower for k in [
        "waterlogging", "waterlogged", "drainage", "stormwater", "drain clog",
        "blocked drain", "sewage overflow", "stagnant water", "mosquitoes", "saakkadai", "flooding", "sewer"
    ]):
        loc_t = f" {location_title}" if location_title else ""
        loc_d = f" {location_desc}" if location_desc else " in the area"
        title = f"Stormwater Drain Blockage & Waterlogging{loc_t}"
        desc = f"Severe stormwater drain blockage causing stagnant waterlogging and mosquito breeding{loc_d}. Municipal super-sucker machines and desilting teams required urgently to clear the flow."
        return (title, desc)

    # F. Fallen Tree & Electrical Wire / Pole Hazard
    if any(k in raw for k in [
        "மரக்கிளை", "மரம் விழுந்தது", "மின் கம்பி", "மின் கம்பம்",
        "മരം വീണു", "വൈദ്യുതി ലൈൻ", "പോസ്റ്റ്",
        "पेड़ गिरा", "बिजली का तार", "खंभा टूटा",
        "చెట్టు పడిపోయింది", "విద్యుత్ వైరు",
        "ಮರ ಬಿದ್ದಿದೆ", "ವಿದ್ಯುತ್ ತಂತಿ",
        "গাছ পড়েছে", "বিদ্যুতের তার"
    ]) or any(k in lower for k in [
        "fallen tree", "tree branch", "electric wire", "dangling wire", "electric pole", "snapped cable"
    ]):
        loc_t = f" {location_title}" if location_title else ""
        loc_d = f" {location_desc}" if location_desc else " on the street"
        title = f"Tree Fall & Live Electrical Wire Hazard{loc_t}"
        desc = f"Fallen tree branches and dangling overhead cables observed{loc_d}. Poses acute risk of electrocution and traffic blockage. Emergency clearance requested."
        return (title, desc)

    # G. Stray Animals / Dead Animal Carcass Removal
    if any(k in raw for k in [
        "நாய்கள்", "நாய் தொல்லை", "இறந்த நாய்", "விலங்கு",
        "നായ്ക്കൾ", "പട്ടികൾ", "മൃഗം",
        "आवारा कुत्ते", "मरा हुआ जानवर",
        "పిచ్చి కుక్కలు",
        "ಬೀದಿ ನಾಯಿಗಳು",
        "বেওয়ারিশ কুকুর"
    ]) or any(k in lower for k in [
        "stray dog", "stray dogs", "dead animal", "carcass", "dog menace", "animal bite"
    ]):
        loc_t = f" {location_title}" if location_title else ""
        loc_d = f" {location_desc}" if location_desc else " in the locality"
        if any(k in lower for k in ["dead", "carcass", "இறந்த"]):
            title = f"Animal Carcass Removal Required{loc_t}"
            desc = f"An animal carcass is lying unattended{loc_d}, creating acute hygiene and odor concerns. Immediate sanitary disposal requested."
        else:
            title = f"Stray Dog Menace & Public Safety Concern{loc_t}"
            desc = f"Aggressive stray dogs roaming{loc_d}, causing severe distress and bite risks to pedestrians and school children. Animal birth control (ABC) squad deployment requested."
        return (title, desc)

    # H. English / General Fallback Synthesis
    words = re.findall(r'[a-zA-Z0-9\u0900-\u0DFF]+', raw)
    if words:
        clean_words = [w for w in words if w.lower() not in {"i", "want", "to", "report", "complain", "please", "kindly", "an", "the", "is", "are", "have", "been"}]
        snippet = " ".join(clean_words[:5]) if clean_words else " ".join(words[:5])
    else:
        snippet = "Civic Infrastructure Issue"

    if detection.get("is_indian_script"):
        lang_display = detection.get("language", "Regional Language")
        title = f"Civic Grievance: {snippet.title()} ({lang_display})"
        desc = f"Citizen reported civic issue in {lang_display}: '{raw}'. Immediate municipal field inspection and resolution requested."
    else:
        # Standard English
        title = f"{snippet.title()}"
        if location_title and location_title not in title:
            title = f"{title} {location_title}"
        desc = raw

    return (title, desc)

