#!/usr/bin/env python3
"""Add traditional parentheticals to ALL clauses, even when identical.

From: 我们坐着工作(我們坐著工作)，效率反而更高。
To:   我们坐着工作(我們坐著工作)，效率反而更高(效率反而更高)。
"""

import re
import sys
from pathlib import Path

# Simplified to Traditional character mapping (common differences)
SIMP_TO_TRAD = {
    '们': '們', '着': '著', '说': '說', '话': '話', '吗': '嗎', '饭': '飯',
    '听': '聽', '请': '請', '这': '這', '个': '個', '问': '問', '题': '題',
    '国': '國', '学': '學', '书': '書', '红': '紅', '专': '專', '车': '車',
    '马': '馬', '鸟': '鳥', '鱼': '魚', '龙': '龍', '风': '風', '云': '雲',
    '电': '電', '见': '見', '观': '觀', '门': '門', '开': '開', '关': '關',
    '头': '頭', '发': '發', '体': '體', '语': '語', '读': '讀', '写': '寫',
    '认': '認', '识': '識', '词': '詞', '记': '記', '讲': '講', '论': '論',
    '谈': '談', '设': '設', '计': '計', '许': '許', '诉': '訴', '让': '讓',
    '该': '該', '说': '說', '谁': '誰', '调': '調', '课': '課', '请': '請',
    '谢': '謝', '进': '進', '远': '遠', '运': '運', '过': '過', '还': '還',
    '边': '邊', '达': '達', '选': '選', '道': '道', '通': '通', '连': '連',
    '对': '對', '时': '時', '将': '將', '导': '導', '岁': '歲', '当': '當',
    '录': '錄', '钟': '鐘', '钱': '錢', '铁': '鐵', '银': '銀', '错': '錯',
    '锁': '鎖', '长': '長', '门': '門', '间': '間', '闻': '聞', '阳': '陽',
    '阴': '陰', '队': '隊', '难': '難', '面': '麵', '页': '頁', '须': '須',
    '飞': '飛', '饭': '飯', '馆': '館', '验': '驗', '惊': '驚', '鸡': '雞',
    '齐': '齊', '亲': '親', '觉': '覺', '览': '覽', '贝': '貝', '负': '負',
    '贵': '貴', '买': '買', '卖': '賣', '资': '資', '赵': '趙', '赶': '趕',
    '起': '起', '趋': '趨', '越': '越', '跃': '躍', '踊': '踴', '蹄': '蹄',
    '躯': '軀', '车': '車', '轨': '軌', '转': '轉', '轮': '輪', '软': '軟',
    '轻': '輕', '较': '較', '载': '載', '辆': '輛', '辈': '輩', '辑': '輯',
    '输': '輸', '辞': '辭', '农': '農', '迁': '遷', '迟': '遲', '过': '過',
    '迈': '邁', '达': '達', '违': '違', '适': '適', '选': '選', '逊': '遜',
    '递': '遞', '遗': '遺', '邮': '郵', '释': '釋', '里': '裡', '针': '針',
    '钓': '釣', '钢': '鋼', '钥': '鑰', '铜': '銅', '铃': '鈴', '铅': '鉛',
    '银': '銀', '销': '銷', '锋': '鋒', '锐': '銳', '锅': '鍋', '锦': '錦',
    '镇': '鎮', '镜': '鏡', '闪': '閃', '闭': '閉', '问': '問', '闯': '闖',
    '闲': '閒', '间': '間', '闷': '悶', '闹': '鬧', '阁': '閣', '阅': '閱',
    '阔': '闊', '阙': '闕', '阵': '陣', '阶': '階', '际': '際', '陆': '陸',
    '险': '險', '随': '隨', '隐': '隱', '隶': '隸', '难': '難', '雾': '霧',
    '霁': '霽', '灵': '靈', '静': '靜', '靠': '靠', '韧': '韌', '韩': '韓',
    '顶': '頂', '顷': '頃', '项': '項', '顺': '順', '须': '須', '顽': '頑',
    '顾': '顧', '颁': '頒', '颂': '頌', '预': '預', '颅': '顱', '领': '領',
    '颇': '頗', '频': '頻', '颓': '頹', '颖': '穎', '颗': '顆', '题': '題',
    '颜': '顏', '额': '額', '颠': '顛', '颤': '顫', '风': '風', '飘': '飄',
    '饥': '飢', '饭': '飯', '饮': '飲', '饰': '飾', '饱': '飽', '饶': '饒',
    '饺': '餃', '饼': '餅', '馅': '餡', '馆': '館', '馈': '饋', '馋': '饞',
    '首': '首', '香': '香', '马': '馬', '驰': '馳', '驱': '驅', '驳': '駁',
    '驴': '驢', '驶': '駛', '驻': '駐', '驼': '駝', '驾': '駕', '骂': '罵',
    '骄': '驕', '骆': '駱', '骇': '駭', '验': '驗', '骏': '駿', '骑': '騎',
    '骗': '騙', '骚': '騷', '骤': '驟', '骨': '骨', '髓': '髓', '高': '高',
    '鬼': '鬼', '魂': '魂', '魄': '魄', '魏': '魏', '魔': '魔', '鱼': '魚',
    '鲁': '魯', '鲜': '鮮', '鲤': '鯉', '鲨': '鯊', '鳄': '鱷', '鸟': '鳥',
    '鸡': '雞', '鸣': '鳴', '鸥': '鷗', '鸦': '鴉', '鸭': '鴨', '鸳': '鴛',
    '鸵': '鴕', '鸽': '鴿', '鸿': '鴻', '鹅': '鵝', '鹉': '鵡', '鹊': '鵲',
    '鹏': '鵬', '鹤': '鶴', '鹦': '鸚', '鹰': '鷹', '鹿': '鹿', '麦': '麥',
    '麻': '麻', '黄': '黃', '黎': '黎', '黑': '黑', '默': '默', '鼓': '鼓',
    '鼠': '鼠', '鼻': '鼻', '齿': '齒', '龄': '齡', '龙': '龍', '龟': '龜',
}


def simp_to_trad(text: str) -> str:
    """Convert simplified text to traditional using character mapping."""
    result = []
    for char in text:
        result.append(SIMP_TO_TRAD.get(char, char))
    return ''.join(result)


def split_by_clause_punct(text: str) -> list:
    """Split text by Chinese clause punctuation, keeping the punctuation."""
    pattern = r'([，、；,;])'
    parts = re.split(pattern, text)
    
    result = []
    i = 0
    while i < len(parts):
        if i + 1 < len(parts) and re.match(r'^[，、；,;]$', parts[i + 1]):
            result.append((parts[i], parts[i + 1]))
            i += 2
        else:
            result.append((parts[i], ''))
            i += 1
    return result


def add_all_clause_trad(chinese: str) -> str:
    """Add traditional parentheticals to ALL clauses.
    
    If already has some parentheticals (partial), expand to all.
    If already has full sentence parenthetical, split by clause.
    """
    # Check if it has ending punctuation
    ending_punct = ''
    if chinese and chinese[-1] in '。？！.?!':
        ending_punct = chinese[-1]
        text = chinese[:-1]
    else:
        text = chinese
    
    # Check if it's already in full-sentence format: text(trad)
    full_match = re.match(r'^(.+?)\((.+?)\)$', text)
    if full_match:
        # Full sentence format - split and add to each clause
        simplified_full = full_match.group(1)
        traditional_full = full_match.group(2)
        
        simp_parts = split_by_clause_punct(simplified_full)
        trad_parts = split_by_clause_punct(traditional_full)
        
        if len(simp_parts) == len(trad_parts):
            result = []
            for (simp_text, simp_punct), (trad_text, _) in zip(simp_parts, trad_parts):
                result.append(f"{simp_text}({trad_text}){simp_punct}")
            return ''.join(result) + ending_punct
        return chinese
    
    # Check if it's already in partial clause format: text(trad)，text。
    # Count existing parentheticals vs clauses
    clause_pattern = r'([^，、；,;]+)(\([^)]+\))?([，、；,;])?'
    
    # Split by clause punctuation first
    parts = split_by_clause_punct(text)
    
    result = []
    for clause_text, punct in parts:
        if not clause_text.strip():
            continue
            
        # Check if this clause already has a parenthetical
        paren_match = re.match(r'^(.+?)\((.+?)\)$', clause_text)
        if paren_match:
            # Already has parenthetical, keep it
            result.append(f"{clause_text}{punct}")
        else:
            # No parenthetical, add traditional
            trad = simp_to_trad(clause_text)
            result.append(f"{clause_text}({trad}){punct}")
    
    return ''.join(result) + ending_punct


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    lines = content.split('\n')
    result = []
    
    in_examples = False
    
    for i, line in enumerate(lines):
        if line.strip() == "- **examples:**":
            in_examples = True
            result.append(line)
            continue
        elif line.strip().startswith("- **") and "examples" not in line:
            in_examples = False
        
        # Check for Chinese example lines (first line of hierarchical example)
        if in_examples and line.startswith("  - ") and not line.startswith("  - **"):
            chinese = line[4:]
            
            # Check if next line is indented (hierarchical format)
            if i + 1 < len(lines) and lines[i + 1].startswith("    - "):
                # Check if it needs migration (has clauses without full parentheticals)
                clauses = split_by_clause_punct(chinese.rstrip('。？！.?!'))
                needs_migration = False
                for clause_text, _ in clauses:
                    if clause_text.strip() and not re.search(r'\([^)]+\)$', clause_text):
                        needs_migration = True
                        break
                
                if needs_migration:
                    new_chinese = add_all_clause_trad(chinese)
                    if new_chinese != chinese:
                        line = f"  - {new_chinese}"
        
        result.append(line)
    
    new_content = '\n'.join(result)
    
    if new_content != original:
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Add traditional parentheticals to all clauses')
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

