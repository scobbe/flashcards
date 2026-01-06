#!/usr/bin/env python3
"""Manually fix cards by adding etymology explanations.

This script analyzes each card's character breakdown and generates
etymology explanations based on the semantic logic of character combinations.

No API calls - uses embedded logic to generate etymologies.

Usage:
    python scripts/fix_etymology_manually.py [--dry-run]
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.common.utils import is_cjk_char

# Common characters with pinyin and meaning for etymology enrichment
CHAR_INFO = {
    # Radicals and common components
    "口": ("kǒu", "mouth"),
    "阿": ("ā", "prefix"),
    "厄": ("è", "distress"),
    "女": ("nǚ", "woman"),
    "子": ("zǐ", "child"),
    "日": ("rì", "sun"),
    "月": ("yuè", "moon"),
    "水": ("shuǐ", "water"),
    "火": ("huǒ", "fire"),
    "木": ("mù", "wood"),
    "金": ("jīn", "metal"),
    "土": ("tǔ", "earth"),
    "山": ("shān", "mountain"),
    "人": ("rén", "person"),
    "心": ("xīn", "heart"),
    "手": ("shǒu", "hand"),
    "足": ("zú", "foot"),
    "目": ("mù", "eye"),
    "耳": ("ěr", "ear"),
    "言": ("yán", "speech"),
    "食": ("shí", "food"),
    "衣": ("yī", "clothing"),
    "門": ("mén", "door"),
    "门": ("mén", "door"),
    "車": ("chē", "vehicle"),
    "车": ("chē", "vehicle"),
    "馬": ("mǎ", "horse"),
    "马": ("mǎ", "horse"),
    "鳥": ("niǎo", "bird"),
    "鸟": ("niǎo", "bird"),
    "魚": ("yú", "fish"),
    "鱼": ("yú", "fish"),
    "艮": ("gěn", "stopping"),
    "貝": ("bèi", "shell"),
    "贝": ("bèi", "shell"),
    "彳": ("chì", "step"),
    "示": ("shì", "show"),
    "礻": ("shì", "spirit"),
    "糸": ("mì", "silk"),
    "纟": ("sī", "silk"),
    "竹": ("zhú", "bamboo"),
    "米": ("mǐ", "rice"),
    "羊": ("yáng", "sheep"),
    "牛": ("niú", "ox"),
    "犬": ("quǎn", "dog"),
    "虫": ("chóng", "insect"),
    "石": ("shí", "stone"),
    "田": ("tián", "field"),
    "皿": ("mǐn", "dish"),
    "刀": ("dāo", "knife"),
    "力": ("lì", "power"),
    "又": ("yòu", "again"),
    "工": ("gōng", "work"),
    "己": ("jǐ", "self"),
    "巾": ("jīn", "cloth"),
    "广": ("guǎng", "wide"),
    "廴": ("yǐn", "stride"),
    "弓": ("gōng", "bow"),
    "寸": ("cùn", "inch"),
    "小": ("xiǎo", "small"),
    "大": ("dà", "big"),
    "尸": ("shī", "corpse"),
    "囗": ("wéi", "enclosure"),
    "士": ("shì", "scholar"),
    "夕": ("xī", "evening"),
    "止": ("zhǐ", "stop"),
    "攵": ("pū", "strike"),
    "文": ("wén", "writing"),
    "方": ("fāng", "square"),
    "白": ("bái", "white"),
    "立": ("lì", "stand"),
    "穴": ("xué", "cave"),
    "肉": ("ròu", "meat"),
    "舌": ("shé", "tongue"),
    "辛": ("xīn", "bitter"),
    "酉": ("yǒu", "wine"),
    "雨": ("yǔ", "rain"),
    "青": ("qīng", "blue-green"),
    "非": ("fēi", "not"),
    "革": ("gé", "leather"),
    "骨": ("gǔ", "bone"),
    "高": ("gāo", "tall"),
    "鬼": ("guǐ", "ghost"),
    "音": ("yīn", "sound"),
    "頁": ("yè", "page"),
    "页": ("yè", "page"),
    "風": ("fēng", "wind"),
    "风": ("fēng", "wind"),
    "飛": ("fēi", "fly"),
    "飞": ("fēi", "fly"),
    "黑": ("hēi", "black"),
    "齒": ("chǐ", "tooth"),
    "齿": ("chǐ", "tooth"),
    "亠": ("tóu", "lid"),
    "冫": ("bīng", "ice"),
    "冖": ("mì", "cover"),
    "几": ("jī", "table"),
    "凵": ("qǔ", "receptacle"),
    "勹": ("bāo", "wrap"),
    "匕": ("bǐ", "spoon"),
    "匚": ("fāng", "box"),
    "卜": ("bǔ", "divination"),
    "厂": ("chǎng", "cliff"),
    "厶": ("sī", "private"),
    "夂": ("zhǐ", "go"),
    "夊": ("suī", "go slowly"),
    "宀": ("mián", "roof"),
    "爿": ("pán", "split wood"),
    "丬": ("pán", "split wood"),
    "片": ("piàn", "slice"),
    "牙": ("yá", "tooth"),
    "瓜": ("guā", "melon"),
    "甘": ("gān", "sweet"),
    "生": ("shēng", "life"),
    "用": ("yòng", "use"),
    "疒": ("nè", "sickness"),
    "癶": ("bō", "footsteps"),
    "皮": ("pí", "skin"),
    "矛": ("máo", "spear"),
    "矢": ("shǐ", "arrow"),
    "禾": ("hé", "grain"),
    "老": ("lǎo", "old"),
    "而": ("ér", "and"),
    "耒": ("lěi", "plow"),
    "聿": ("yù", "brush"),
    "臣": ("chén", "minister"),
    "自": ("zì", "self"),
    "至": ("zhì", "arrive"),
    "臼": ("jiù", "mortar"),
    "舛": ("chuǎn", "oppose"),
    "舟": ("zhōu", "boat"),
    "艸": ("cǎo", "grass"),
    "血": ("xuè", "blood"),
    "行": ("xíng", "go"),
    "見": ("jiàn", "see"),
    "见": ("jiàn", "see"),
    "角": ("jiǎo", "horn"),
    "谷": ("gǔ", "valley"),
    "豆": ("dòu", "bean"),
    "豕": ("shǐ", "pig"),
    "豸": ("zhì", "beast"),
    "貝": ("bèi", "shell"),
    "赤": ("chì", "red"),
    "走": ("zǒu", "walk"),
    "身": ("shēn", "body"),
    "辰": ("chén", "time"),
    "邑": ("yì", "city"),
    "長": ("cháng", "long"),
    "长": ("cháng", "long"),
    "阜": ("fù", "mound"),
    "隶": ("lì", "slave"),
    "隹": ("zhuī", "short-tailed bird"),
    "面": ("miàn", "face"),
    "韋": ("wéi", "leather"),
    "韭": ("jiǔ", "leek"),
    "首": ("shǒu", "head"),
    "香": ("xiāng", "fragrant"),
    "鼓": ("gǔ", "drum"),
    "鼠": ("shǔ", "rat"),
    "鼻": ("bí", "nose"),
    "亦": ("yì", "also"),
    "交": ("jiāo", "exchange"),
    "京": ("jīng", "capital"),
    "令": ("lìng", "order"),
    "兆": ("zhào", "omen"),
    "共": ("gòng", "together"),
    "包": ("bāo", "wrap"),
    "半": ("bàn", "half"),
    "卑": ("bēi", "low"),
    "占": ("zhàn", "occupy"),
    "召": ("zhào", "summon"),
    "可": ("kě", "can"),
    "台": ("tái", "platform"),
    "同": ("tóng", "same"),
    "向": ("xiàng", "toward"),
    "吾": ("wú", "I"),
    "周": ("zhōu", "circle"),
    "品": ("pǐn", "product"),
    "員": ("yuán", "member"),
    "员": ("yuán", "member"),
    "唐": ("táng", "Tang"),
    "善": ("shàn", "good"),
    "喜": ("xǐ", "joy"),
    "单": ("dān", "single"),
    "單": ("dān", "single"),
    "严": ("yán", "strict"),
    "嚴": ("yán", "strict"),
    "圣": ("shèng", "holy"),
    "聖": ("shèng", "holy"),
    "帝": ("dì", "emperor"),
    "并": ("bìng", "combine"),
    "業": ("yè", "business"),
    "业": ("yè", "business"),
    "東": ("dōng", "east"),
    "东": ("dōng", "east"),
    "各": ("gè", "each"),
    "正": ("zhèng", "correct"),
    "某": ("mǒu", "certain"),
    "次": ("cì", "time"),
    "殳": ("shū", "weapon"),
    "比": ("bǐ", "compare"),
    "民": ("mín", "people"),
    "氏": ("shì", "clan"),
    "气": ("qì", "air"),
    "氣": ("qì", "air"),
    "求": ("qiú", "seek"),
    "汇": ("huì", "gather"),
    "池": ("chí", "pool"),
    "没": ("méi", "not have"),
    "法": ("fǎ", "law"),
    "洋": ("yáng", "ocean"),
    "深": ("shēn", "deep"),
    "清": ("qīng", "clear"),
    "满": ("mǎn", "full"),
    "滿": ("mǎn", "full"),
    "然": ("rán", "thus"),
    "无": ("wú", "without"),
    "無": ("wú", "without"),
    "王": ("wáng", "king"),
    "玉": ("yù", "jade"),
    "甚": ("shèn", "very"),
    "由": ("yóu", "from"),
    "申": ("shēn", "extend"),
    "男": ("nán", "male"),
    "畜": ("chù", "livestock"),
    "番": ("fān", "foreign"),
    "畏": ("wèi", "fear"),
    "真": ("zhēn", "true"),
    "眞": ("zhēn", "true"),
    "秋": ("qiū", "autumn"),
    "穀": ("gǔ", "grain"),
    "空": ("kōng", "empty"),
    "等": ("děng", "wait"),
    "節": ("jié", "festival"),
    "节": ("jié", "festival"),
    "約": ("yuē", "约"),
    "约": ("yuē", "约"),
    "羽": ("yǔ", "feather"),
    "翼": ("yì", "wing"),
    "能": ("néng", "able"),
    "背": ("bèi", "back"),
    "胃": ("wèi", "stomach"),
    "般": ("bān", "sort"),
    "良": ("liáng", "good"),
    "色": ("sè", "color"),
    "草": ("cǎo", "grass"),
    "華": ("huá", "Chinese"),
    "华": ("huá", "Chinese"),
    "虎": ("hǔ", "tiger"),
    "西": ("xī", "west"),
    "要": ("yào", "want"),
    "許": ("xǔ", "permit"),
    "许": ("xǔ", "permit"),
    "谷": ("gǔ", "valley"),
    "象": ("xiàng", "elephant"),
    "負": ("fù", "bear"),
    "负": ("fù", "bear"),
    "農": ("nóng", "agriculture"),
    "农": ("nóng", "agriculture"),
    "近": ("jìn", "near"),
    "進": ("jìn", "advance"),
    "进": ("jìn", "advance"),
    "連": ("lián", "connect"),
    "连": ("lián", "connect"),
    "道": ("dào", "way"),
    "里": ("lǐ", "mile"),
    "量": ("liàng", "quantity"),
    "關": ("guān", "close"),
    "关": ("guān", "close"),
    "青": ("qīng", "green"),
    "靜": ("jìng", "quiet"),
    "静": ("jìng", "quiet"),
    "頭": ("tóu", "head"),
    "头": ("tóu", "head"),
    "題": ("tí", "topic"),
    "题": ("tí", "topic"),
    "顯": ("xiǎn", "show"),
    "显": ("xiǎn", "show"),
    "馬": ("mǎ", "horse"),
    "体": ("tǐ", "body"),
    "體": ("tǐ", "body"),
}


def enrich_etymology_with_pinyin(etymology: str) -> str:
    """Add pinyin and meaning to character references in etymology that are missing them.
    
    Transforms patterns like:
    - 口 ("mouth") -> 口 (kǒu, "mouth")  
    - 口 + phonetic 阿 -> 口 (kǒu, "mouth") + phonetic 阿 (ā, "prefix")
    """
    if not etymology:
        return etymology
    
    result = etymology
    
    # Find all CJK characters that might need enrichment
    # Pattern: character followed by optional space and ( or + or end
    for char in CHAR_INFO:
        if char not in result:
            continue
        
        pinyin, meaning = CHAR_INFO[char]
        
        # Pattern 1: char ("meaning") without pinyin -> char (pinyin, "meaning")
        pattern1 = re.compile(rf'{re.escape(char)}\s*\("([^"]+)"\)')
        if pattern1.search(result):
            result = pattern1.sub(rf'{char} ({pinyin}, "\1")', result)
            continue
        
        # Pattern 2: char followed by space and + or . (phonetic component without any info)
        # e.g., "phonetic 阿 ." or "phonetic 阿 +"
        pattern2 = re.compile(rf'(phonetic\s+){re.escape(char)}(\s*[.+])')
        if pattern2.search(result):
            result = pattern2.sub(rf'\g<1>{char} ({pinyin}, "{meaning}")\2', result)
            continue
        
        # Pattern 3: "semantic 口" without parentheses
        pattern3 = re.compile(rf'(semantic\s+){re.escape(char)}(\s+[^(])')
        if pattern3.search(result):
            result = pattern3.sub(rf'\g<1>{char} ({pinyin}, "{meaning}")\2', result)
    
    return result


def parse_card(content: str) -> Dict:
    """Parse a card's content into structured data."""
    result = {
        "headword": "",
        "headword_trad": "",
        "pinyin": "",
        "definition": "",
        "characters": [],  # List of (char, trad, pinyin, english)
        "has_etymology": False,
        "etymology": "",
        "examples": [],
        "raw_lines": content.split("\n"),
    }
    
    lines = content.split("\n")
    
    # Parse headword
    for line in lines:
        if line.startswith("## "):
            hw = line[3:].strip()
            # Check for traditional in parens
            match = re.match(r'^([^(]+)\(([^)]+)\)$', hw)
            if match:
                result["headword"] = match.group(1).strip()
                result["headword_trad"] = match.group(2).strip()
            else:
                result["headword"] = hw
                result["headword_trad"] = ""
            break
    
    # Parse pinyin
    for line in lines:
        if "**pinyin:**" in line:
            result["pinyin"] = line.split("**pinyin:**")[1].strip()
            break
    
    # Parse definition
    for line in lines:
        if "**definition:**" in line:
            result["definition"] = line.split("**definition:**")[1].strip()
            break
    
    # Check for etymology
    result["has_etymology"] = any("**etymology:**" in line for line in lines)
    
    # Parse characters section
    # Format is:
    #   - 华(華)
    #     - huá
    #     - Chinese
    in_chars = False
    current_char = None
    char_data = []
    sub_items = []
    saved_last = False
    
    for i, line in enumerate(lines):
        if "**characters:**" in line:
            in_chars = True
            continue
        if in_chars:
            # Check for end of characters section
            if line.startswith("- **") and "characters" not in line:
                # Save last character
                if current_char and len(sub_items) >= 2:
                    current_char["pinyin"] = sub_items[0]
                    current_char["english"] = sub_items[1] if len(sub_items) > 1 else ""
                    char_data.append(current_char)
                    saved_last = True
                in_chars = False
                current_char = None
                continue
            
            # Character line (2 spaces, dash, space)
            if line.startswith("  - ") and not line.startswith("    "):
                # Save previous character
                if current_char and len(sub_items) >= 2:
                    current_char["pinyin"] = sub_items[0]
                    current_char["english"] = sub_items[1] if len(sub_items) > 1 else ""
                    char_data.append(current_char)
                
                # Start new character
                sub_items = []
                char_text = line[4:].strip()
                # Parse char(trad) format
                match = re.match(r'^([^(]+)\(([^)]+)\)$', char_text)
                if match:
                    current_char = {"char": match.group(1).strip(), "trad": match.group(2).strip(), "pinyin": "", "english": ""}
                else:
                    current_char = {"char": char_text, "trad": "", "pinyin": "", "english": ""}
            
            # Sub-item line (4 spaces, dash, space)
            elif line.startswith("    - ") and current_char:
                text = line[6:].strip()
                sub_items.append(text)
    
    # Save last character if not already saved
    if current_char and len(sub_items) >= 2 and not saved_last:
        current_char["pinyin"] = sub_items[0]
        current_char["english"] = sub_items[1] if len(sub_items) > 1 else ""
        char_data.append(current_char)
    
    result["characters"] = char_data
    return result


def format_char_reference(char: str, trad: str, pinyin: str, english: str) -> str:
    """Format a character reference with proper format.
    
    Format: simplified(traditional) (pinyin, "meaning") or simplified (pinyin, "meaning")
    """
    # Get primary meaning (before first semicolon, take first comma-separated item)
    primary = english.split(";")[0].split(",")[0].strip()
    
    if trad and trad != char:
        return f'{char}({trad}) ({pinyin}, "{primary}")'
    else:
        return f'{char} ({pinyin}, "{primary}")'


def generate_multi_char_etymology_openai(
    headword: str, 
    headword_trad: str, 
    pinyin: str, 
    definition: str, 
    characters: List[Dict]
) -> str:
    """Use OpenAI to generate insightful etymology for multi-character words."""
    from lib.common.openai import OpenAIClient
    
    # Build character context
    char_info = []
    for c in characters:
        char = c.get("char", "")
        trad = c.get("trad", "")
        char_pinyin = c.get("pinyin", "")
        eng = c.get("english", "")
        if char:
            if trad and trad != char:
                char_info.append(f"{char}({trad}) [{char_pinyin}]: {eng}")
            else:
                char_info.append(f"{char} [{char_pinyin}]: {eng}")
    
    char_context = "\n".join(char_info)
    
    system = """You are an expert in Chinese etymology and word formation.
For this multi-character word, explain WHY these characters together create this meaning.

Provide REAL INSIGHT - not just "combines X with Y". Explain:
- The semantic logic or metaphor behind the combination
- Historical or cultural context if relevant
- Why this particular combination makes sense

Return JSON: {"etymology": "Your insightful 1-2 sentence explanation..."}

CRITICAL RULES:
- When referencing a character, ALWAYS use format: 字(傳統) (pīnyīn, "meaning") or 字 (pīnyīn, "meaning") if traditional is same
- Example: 星 (xīng, "star") and 期 (qī, "period") together reference the seven-day cycle named after celestial bodies.
- Be concise but insightful - explain the WHY, not just the WHAT
- Do NOT start with "Combines..." or "The word..." - jump straight into the insight"""

    user = f"""Word: {headword}"""
    if headword_trad and headword_trad != headword:
        user += f" (traditional: {headword_trad})"
    user += f"""
Pinyin: {pinyin}
Meaning: {definition}

Component characters:
{char_context}"""

    try:
        client = OpenAIClient()
        data = client.complete_json(system, user)
        etymology = str(data.get("etymology", "")).strip()
        if etymology:
            # Ensure it ends with a period
            if not etymology.endswith('.'):
                etymology += '.'
            return etymology
    except Exception as e:
        print(f"    [warn] OpenAI etymology failed for {headword}: {e}")
    
    return ""


def generate_etymology(headword: str, headword_trad: str, pinyin: str, definition: str, characters: List[Dict]) -> str:
    """Generate etymology explanation based on character meanings.
    
    Uses format: simplified(traditional) (pinyin, "meaning") for character references.
    """
    # Count CJK characters in headword
    cjk_count = sum(1 for ch in headword if is_cjk_char(ch))
    
    # Single character - generate etymology based on character structure
    if cjk_count == 1:
        return generate_single_char_etymology(headword, headword_trad, pinyin, definition)
    
    # Multi-character word - use OpenAI for insightful etymology
    if characters:
        openai_etym = generate_multi_char_etymology_openai(
            headword, headword_trad, pinyin, definition, characters
        )
        if openai_etym:
            return openai_etym
    
    # Fallback if no characters or OpenAI failed
    return ""


def fetch_wiktionary_etymology(char: str) -> str:
    """Fetch etymology/glyph origin from Wiktionary for a character."""
    from lib.output.html import fetch_wiktionary_html_status, sanitize_html
    import re
    
    html, status = fetch_wiktionary_html_status(char)
    if status != 200 or not html:
        return ""
    
    # Parse and extract etymology
    parsed = sanitize_html(html)
    
    etymology_text = ""
    
    # Try to find Glyph origin section - look for "Phono-semantic compound" or similar patterns
    # These patterns indicate actual etymology content
    patterns = [
        # Phono-semantic compound explanation
        r'Phono-semantic compound[^.]+\.',
        # Ideogrammic compound
        r'Ideogrammic compound[^.]+\.',
        # Pictogram
        r'Pictogram[^.]+\.',
        # From X
        r'From [^.]+\.',
        # Semantic X + phonetic Y
        r'semantic [^+]+ \+ phonetic [^.]+\.',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, parsed, re.IGNORECASE)
        if match:
            etymology_text = match.group(0).strip()
            break
    
    # If no specific pattern found, try to get the Glyph origin section
    if not etymology_text:
        glyph_match = re.search(r'Glyph origin:\s*(.+?)(?=Etymology:|Definitions:|Pronunciation:|Chinese content:|$)', parsed, re.DOTALL)
        if glyph_match:
            content = glyph_match.group(1).strip()
            # Look for the most informative part (usually starts with Phono-, Ideo-, Picto-, From)
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    etymology_text = match.group(0).strip()
                    break
    
    # Try to extract phonetic series info if still nothing
    if not etymology_text:
        # Look for "phonetic series" which lists related characters
        phonetic_match = re.search(r'phonetic series\s*\(\s*([^\)]+)\s*\)', parsed, re.IGNORECASE)
        if phonetic_match:
            phonetic_char = phonetic_match.group(1).strip()
            # Check if this character has 口 (mouth) radical - common for interjections
            if '口' in parsed[:500]:
                etymology_text = f"Phono-semantic compound: semantic 口 (\"mouth\") + phonetic {phonetic_char}"
    
    # Clean up the text
    if etymology_text:
        # Remove OC pronunciation notations like (OC *qreːɡ)
        etymology_text = re.sub(r'\s*\(\s*OC\s+\*[^)]+\)', '', etymology_text)
        # Remove wiki markup artifacts
        etymology_text = re.sub(r'\[\d+\]', '', etymology_text)
        # Remove citation references like (Pulleyblank, 1995)
        etymology_text = re.sub(r'\s*\([^)]*\d{4}[^)]*\)', '', etymology_text)
        # Clean up Chinese form notation
        etymology_text = re.sub(r'\s*\(\s*形聲\s*/\s*形声[^)]*\)', '', etymology_text)
        etymology_text = re.sub(r'\s*\(\s*會意\s*/\s*会意[^)]*\)', '', etymology_text)
        etymology_text = re.sub(r'\s*\(\s*象形[^)]*\)', '', etymology_text)
        # Clean whitespace
        etymology_text = re.sub(r'\s+', ' ', etymology_text).strip()
        # Normalize curly quotes to straight quotes (U+201C left, U+201D right)
        etymology_text = etymology_text.replace('\u201c', '"').replace('\u201d', '"')
        # Format quotes properly: ( " X " ) -> ("X")
        etymology_text = re.sub(r'\(\s*"\s*', '("', etymology_text)
        etymology_text = re.sub(r'\s*"\s*\)', '")', etymology_text)
        # Clean up any remaining spacing issues around parens
        etymology_text = re.sub(r'\s+\(', ' (', etymology_text)
        etymology_text = re.sub(r'\(\s+', '(', etymology_text)
        etymology_text = re.sub(r'\s+\)', ')', etymology_text)
        # Clean up trailing spaces before period
        etymology_text = re.sub(r'\s+\.', '.', etymology_text)
        # Ensure proper capitalization
        if etymology_text and etymology_text[0].islower():
            etymology_text = etymology_text[0].upper() + etymology_text[1:]
        # Remove trailing period if present, we'll add our own
        etymology_text = etymology_text.rstrip('.')
        # Add period at end
        if etymology_text and not etymology_text.endswith('.'):
            etymology_text += '.'
    
    # Enrich with pinyin and meanings for referenced characters
    etymology_text = enrich_etymology_with_pinyin(etymology_text)
    
    return etymology_text


def generate_single_char_etymology(char: str, trad: str, pinyin: str, definition: str) -> str:
    """Generate etymology for a single character by fetching from Wiktionary."""
    # Try to fetch from Wiktionary
    wiki_etym = fetch_wiktionary_etymology(char)
    if wiki_etym:
        return wiki_etym
    
    # If traditional is different, try that too
    if trad and trad != char:
        wiki_etym = fetch_wiktionary_etymology(trad)
        if wiki_etym:
            return wiki_etym
    
    # Fallback - generic description
    trad_part = f"({trad})" if trad and trad != char else ""
    return f"A character{trad_part} meaning {definition.lower().rstrip('.')}."


def fix_card(content: str, force_refix: bool = False) -> Tuple[str, bool]:
    """Fix a card by adding or updating etymology.
    
    Args:
        content: Card markdown content
        force_refix: If True, re-fetch etymology even if card already has one
    
    Returns (new_content, was_modified).
    """
    card = parse_card(content)
    
    # Skip if already has etymology (unless force_refix)
    if card["has_etymology"] and not force_refix:
        return content, False
    
    # Generate etymology
    etymology = generate_etymology(
        card["headword"], 
        card["headword_trad"], 
        card["pinyin"], 
        card["definition"], 
        card["characters"]
    )
    
    if not etymology:
        return content, False
    
    # Insert etymology in the right place
    lines = content.split("\n")
    
    # If force_refix, remove existing etymology line first
    if force_refix:
        lines = [line for line in lines if "**etymology:**" not in line]
    
    new_lines = []
    inserted = False
    
    # Check if card has characters section
    has_chars_section = any("**characters:**" in line for line in lines)
    
    if has_chars_section:
        # Insert after characters section, before examples
        in_chars = False
        for i, line in enumerate(lines):
            new_lines.append(line)
            
            if "**characters:**" in line:
                in_chars = True
            elif in_chars and line.startswith("- **") and "characters" not in line:
                # Found next section after characters - insert etymology before it
                new_lines.insert(-1, f"- **etymology:** {etymology}")
                inserted = True
                in_chars = False
    else:
        # No characters section - insert after definition, before examples
        for i, line in enumerate(lines):
            new_lines.append(line)
            
            if "**definition:**" in line and not inserted:
                # Check if next line is indented (multi-line definition)
                next_idx = i + 1
                while next_idx < len(lines) and lines[next_idx].startswith("  - "):
                    next_idx += 1
                # We're past the definition, but we already appended this line
                # So we add etymology right after this line
                if next_idx == i + 1:
                    # Single line definition - insert right after
                    new_lines.append(f"- **etymology:** {etymology}")
                    inserted = True
            elif "**examples:**" in line and not inserted:
                # Insert before examples if we haven't yet
                new_lines.insert(-1, f"- **etymology:** {etymology}")
                inserted = True
    
    if not inserted:
        return content, False
    
    return "\n".join(new_lines), True


def process_directory(output_dir: Path, dry_run: bool = False, force_refix: bool = False) -> Tuple[int, int]:
    """Process all cards in a directory.
    
    Returns (total_cards, cards_fixed).
    """
    total = 0
    fixed = 0
    
    for md_file in sorted(output_dir.glob("*.md")):
        if md_file.name.startswith("-"):
            continue
        
        total += 1
        content = md_file.read_text(encoding="utf-8")
        new_content, was_fixed = fix_card(content, force_refix=force_refix)
        
        if was_fixed:
            fixed += 1
            if not dry_run:
                md_file.write_text(new_content, encoding="utf-8")
            print(f"  ✓ Fixed: {md_file.name}")
    
    return total, fixed


def main():
    dry_run = "--dry-run" in sys.argv
    force_refix = "--force" in sys.argv
    
    project_root = Path(__file__).parent.parent
    output_root = project_root / "output"
    
    mode_str = ""
    if dry_run:
        mode_str = "[DRY RUN] "
    if force_refix:
        mode_str += "[FORCE REFIX] "
    
    print(f"{mode_str}Fixing cards with missing etymology...")
    print("=" * 60)
    
    total_cards = 0
    total_fixed = 0
    
    # Find all Chinese output directories
    for output_dir in sorted(output_root.rglob("output")):
        if not output_dir.is_dir():
            continue
        
        # Skip English directories
        if "english" in str(output_dir):
            continue
        
        # Check if has .md files
        md_files = [f for f in output_dir.glob("*.md") if not f.name.startswith("-")]
        if not md_files:
            continue
        
        rel_path = output_dir.relative_to(project_root)
        print(f"\n📁 {rel_path}")
        
        cards, fixed = process_directory(output_dir, dry_run=dry_run, force_refix=force_refix)
        total_cards += cards
        total_fixed += fixed
        
        if fixed == 0:
            print("  (no fixes needed)")
    
    print("\n" + "=" * 60)
    print(f"{mode_str}COMPLETE")
    print(f"Total cards: {total_cards}")
    print(f"Cards fixed: {total_fixed}")


if __name__ == "__main__":
    main()

