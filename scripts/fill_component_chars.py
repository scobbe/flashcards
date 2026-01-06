#!/usr/bin/env python3
"""Fill in missing component character info using provided dictionary."""

import re
import sys
from pathlib import Path

# Character dictionary from user-provided data
CHAR_DICT = {
    "㫃": ("㫃", "㫃", "yǎn", "sunlight"),
    "丌": ("丌", "丌", "jī", "pedestal"),
    "不": ("不", "不", "bù", "not"),
    "丝": ("丝", "絲", "sī", "silk"),
    "丨": ("丨", "丨", "gǔn", "line"),
    "丶": ("丶", "丶", "zhǔ", "dot"),
    "主": ("主", "主", "zhǔ", "master"),
    "乂": ("乂", "乂", "yì", "to cut"),
    "久": ("久", "久", "jiǔ", "long time"),
    "之": ("之", "之", "zhī", "of"),
    "乍": ("乍", "乍", "zhà", "suddenly"),
    "亻": ("亻", "亻", "rén", "person radical"),
    "仌": ("仌", "仌", "bīng", "ice"),
    "仓": ("仓", "倉", "cāng", "storehouse"),
    "保": ("保", "保", "bǎo", "protect"),
    "倉": ("倉", "倉", "cāng", "granary"),
    "儿": ("儿", "兒", "ér", "child"),
    "光": ("光", "光", "guāng", "light"),
    "兌": ("兌", "兌", "duì", "exchange"),
    "兑": ("兑", "兌", "duì", "exchange"),
    "兒": ("兒", "兒", "ér", "child"),
    "凡": ("凡", "凡", "fán", "ordinary"),
    "刀": ("刀", "刀", "dāo", "knife"),
    "刁": ("刁", "刁", "diāo", "tricky"),
    "勺": ("勺", "勺", "sháo", "spoon"),
    "匸": ("匸", "匸", "xì", "box radical"),
    "十": ("十", "十", "shí", "ten"),
    "卜": ("卜", "卜", "bǔ", "divine"),
    "卩": ("卩", "卩", "jié", "seal radical"),
    "卪": ("卪", "卪", "jié", "seal variant"),
    "厶": ("厶", "厶", "sī", "private"),
    "反": ("反", "反", "fǎn", "oppose"),
    "口": ("口", "口", "kǒu", "mouth"),
    "召": ("召", "召", "zhào", "summon"),
    "叶": ("叶", "葉", "yè", "leaf"),
    "向": ("向", "向", "xiàng", "toward"),
    "囗": ("囗", "囗", "wéi", "enclosure"),
    "圆": ("圆", "圓", "yuán", "round"),
    "圓": ("圓", "圓", "yuán", "circle"),
    "土": ("土", "土", "tǔ", "earth"),
    "堇": ("堇", "堇", "jǐn", "clay"),
    "夕": ("夕", "夕", "xī", "evening"),
    "夬": ("夬", "夬", "guài", "decide"),
    "央": ("央", "央", "yāng", "center"),
    "奂": ("奂", "奐", "huàn", "change"),
    "奐": ("奐", "奐", "huàn", "abundant"),
    "官": ("官", "官", "guān", "official"),
    "寺": ("寺", "寺", "sì", "temple"),
    "山": ("山", "山", "shān", "mountain"),
    "巾": ("巾", "巾", "jīn", "cloth"),
    "庐": ("庐", "廬", "lú", "hut"),
    "廬": ("廬", "廬", "lú", "cottage"),
    "弋": ("弋", "弋", "yì", "to shoot"),
    "彡": ("彡", "彡", "shān", "hair radical"),
    "惟": ("惟", "惟", "wéi", "only"),
    "戶": ("戶", "戶", "hù", "door"),
    "户": ("户", "戶", "hù", "household"),
    "手": ("手", "手", "shǒu", "hand"),
    "攵": ("攵", "攵", "pū", "strike radical"),
    "斥": ("斥", "斥", "chì", "repel"),
    "斧": ("斧", "斧", "fǔ", "axe"),
    "方": ("方", "方", "fāng", "square"),
    "晶": ("晶", "晶", "jīng", "bright"),
    "月": ("月", "月", "yuè", "moon"),
    "有": ("有", "有", "yǒu", "have"),
    "木": ("木", "木", "mù", "wood"),
    "朿": ("朿", "朿", "cì", "thorn"),
    "杵": ("杵", "杵", "chǔ", "pestle"),
    "枣": ("枣", "棗", "zǎo", "jujube"),
    "桶": ("桶", "桶", "tǒng", "barrel"),
    "棗": ("棗", "棗", "zǎo", "jujube"),
    "欠": ("欠", "欠", "qiàn", "lack"),
    "殹": ("殹", "殹", "yì", "medical"),
    "沙": ("沙", "沙", "shā", "sand"),
    "火": ("火", "火", "huǒ", "fire"),
    "灬": ("灬", "灬", "huǒ", "fire radical"),
    "牛": ("牛", "牛", "niú", "ox"),
    "玉": ("玉", "玉", "yù", "jade"),
    "王": ("王", "王", "wáng", "king"),
    "珏": ("珏", "珏", "jué", "two jades"),
    "甲": ("甲", "甲", "jiǎ", "armor"),
    "白": ("白", "白", "bái", "white"),
    "眼": ("眼", "眼", "yǎn", "eye"),
    "矛": ("矛", "矛", "máo", "spear"),
    "矢": ("矢", "矢", "shǐ", "arrow"),
    "箕": ("箕", "箕", "jī", "winnowing basket"),
    "糸": ("糸", "糸", "mì", "silk radical"),
    "糹": ("糹", "糹", "mì", "silk radical"),
    "絲": ("絲", "絲", "sī", "silk"),
    "網": ("網", "網", "wǎng", "net"),
    "网": ("网", "網", "wǎng", "net"),
    "翅": ("翅", "翅", "chì", "wing"),
    "而": ("而", "而", "ér", "and"),
    "耎": ("耎", "耎", "ruǎn", "soft"),
    "肉": ("肉", "肉", "ròu", "meat"),
    "至": ("至", "至", "zhì", "arrive"),
    "舌": ("舌", "舌", "shé", "tongue"),
    "舟": ("舟", "舟", "zhōu", "boat"),
    "艮": ("艮", "艮", "gèn", "stopping"),
    "艸": ("艸", "艸", "cǎo", "grass radical"),
    "荄": ("荄", "荄", "gāi", "root"),
    "葉": ("葉", "葉", "yè", "leaf"),
    "行": ("行", "行", "xíng", "go"),
    "見": ("見", "見", "jiàn", "see"),
    "言": ("言", "言", "yán", "speech"),
    "豕": ("豕", "豕", "shǐ", "pig"),
    "貝": ("貝", "貝", "bèi", "shell"),
    "車": ("車", "車", "chē", "vehicle"),
    "车": ("车", "車", "chē", "car"),
    "辶": ("辶", "辶", "chuò", "walk radical"),
    "違": ("違", "違", "wéi", "violate"),
    "酉": ("酉", "酉", "yǒu", "wine"),
    "酋": ("酋", "酋", "qiú", "chief"),
    "金": ("金", "金", "jīn", "metal"),
    "釒": ("釒", "釒", "jīn", "metal radical"),
    "針": ("針", "針", "zhēn", "needle"),
    "针": ("针", "針", "zhēn", "needle"),
    "雨": ("雨", "雨", "yǔ", "rain"),
    "韋": ("韋", "韋", "wéi", "tanned leather"),
    "韦": ("韦", "韋", "wéi", "leather"),
    "食": ("食", "食", "shí", "eat"),
    "首": ("首", "首", "shǒu", "head"),
    "鬼": ("鬼", "鬼", "guǐ", "ghost"),
    "鸛": ("鸛", "鸛", "guàn", "stork"),
    "鹳": ("鹳", "鸛", "guàn", "stork"),
    "鼎": ("鼎", "鼎", "dǐng", "tripod cauldron"),
    "鼓": ("鼓", "鼓", "gǔ", "drum"),
    "龜": ("龜", "龜", "guī", "turtle"),
    "龟": ("龟", "龜", "guī", "turtle"),
    "𠂇": ("𠂇", "𠂇", "piě", "slash radical"),
    "𠬝": ("𠬝", "𠬝", "zhuō", "strike"),
    "𠯑": ("𠯑", "𠯑", "kǒu", "mouth variant"),
}


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    lines = content.split('\n')
    result = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Fix component characters missing info
        if "- **component characters:**" in line:
            result.append(line)
            i += 1
            # Process component character items
            while i < len(lines):
                item_line = lines[i]
                # Check if we've left the component characters section
                if item_line.strip().startswith("- **") and "component characters" not in item_line:
                    break
                if item_line.strip() == "%%%":
                    break
                if not item_line.strip():
                    result.append(item_line)
                    i += 1
                    continue
                    
                if not item_line.strip().startswith("- "):
                    result.append(item_line)
                    i += 1
                    continue
                
                item = item_line.strip()[2:]  # Remove "- "
                indent = len(item_line) - len(item_line.lstrip())
                pad = " " * indent
                
                # Check if already hierarchical (next line is more indented with "- ")
                if i + 1 < len(lines) and lines[i + 1].strip().startswith("- ") and len(lines[i + 1]) - len(lines[i + 1].lstrip()) > indent:
                    result.append(item_line)
                    i += 1
                    continue
                
                # Check if item already has parenthetical info
                if re.match(r'^.+\s+\([^)]+\)$', item):
                    # Parse existing format: Chinese (pinyin, "english")
                    match = re.match(r'^(.+?)\s+\(([^,]+),\s*"([^"]+)"\)$', item)
                    if match:
                        chinese_part = match.group(1)
                        pinyin_part = match.group(2).strip()
                        english_part = match.group(3).strip()
                        result.append(f"{pad}- {chinese_part}")
                        result.append(f"{pad}  - {pinyin_part}")
                        result.append(f"{pad}  - {english_part}")
                        i += 1
                        continue
                
                # Item is just a character - look up info from dictionary
                char = item.strip()
                if char in CHAR_DICT:
                    simp, trad, pin, eng = CHAR_DICT[char]
                    if trad and trad != simp:
                        result.append(f"{pad}- {simp}({trad})")
                    else:
                        result.append(f"{pad}- {simp}")
                    if pin:
                        result.append(f"{pad}  - {pin}")
                    if eng:
                        result.append(f"{pad}  - {eng}")
                    i += 1
                    continue
                
                # No lookup found, keep as-is
                result.append(item_line)
                i += 1
            continue
        
        result.append(line)
        i += 1
    
    new_content = '\n'.join(result)
    
    if new_content != original:
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fill in missing component character info')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--path', type=str, default='/Users/scobbe/src/flashcards/output')
    args = parser.parse_args()
    
    output_path = Path(args.path)
    if not output_path.exists():
        print(f"Error: {output_path} does not exist")
        sys.exit(1)
    
    md_files = [p for p in output_path.rglob('*.md') if not p.name.startswith('-')]
    
    modified_count = 0
    for md_file in md_files:
        if migrate_file(md_file, dry_run=args.dry_run):
            modified_count += 1
            action = "Would modify" if args.dry_run else "Modified"
            print(f"{action}: {md_file}")
    
    print(f"\n{'Would modify' if args.dry_run else 'Modified'} {modified_count} files out of {len(md_files)} total")
    
    if not args.dry_run and modified_count > 0:
        print("\nRegenerating combined -output.md files...")
        for out_dir in output_path.rglob('output'):
            if not out_dir.is_dir():
                continue
            
            md_files_in_dir = sorted([p for p in out_dir.glob('*.md') if not p.name.startswith('-')])
            if not md_files_in_dir:
                continue
            
            output_md = out_dir / '-output.md'
            parts = []
            for p in md_files_in_dir:
                try:
                    parts.append(p.read_text(encoding='utf-8', errors='ignore'))
                except Exception:
                    pass
            
            if parts:
                combined = '\n\n'.join(parts) + '\n'
                output_md.write_text(combined, encoding='utf-8')
        
        print("Done regenerating combined files")


if __name__ == '__main__':
    main()

