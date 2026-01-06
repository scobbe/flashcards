#!/usr/bin/env python3
"""Fix contemporary usage format from character-by-character to full phrase.

From: 六边(邊)形 (liù biān xíng, "hexagon")
To:   六边形(六邊形): liù biān xíng; hexagon

Converts inline character-by-character traditional to full phrase format.
"""

import re
import sys
from pathlib import Path

# Simplified to Traditional character mapping
SIMP_TO_TRAD = {
    '们': '們', '着': '著', '说': '說', '话': '話', '吗': '嗎', '饭': '飯',
    '听': '聽', '请': '請', '这': '這', '个': '個', '问': '問', '题': '題',
    '国': '國', '学': '學', '书': '書', '红': '紅', '专': '專', '车': '車',
    '马': '馬', '鸟': '鳥', '鱼': '魚', '龙': '龍', '风': '風', '云': '雲',
    '电': '電', '见': '見', '观': '觀', '门': '門', '开': '開', '关': '關',
    '头': '頭', '发': '發', '体': '體', '语': '語', '读': '讀', '写': '寫',
    '认': '認', '识': '識', '词': '詞', '记': '記', '讲': '講', '论': '論',
    '谈': '談', '设': '設', '计': '計', '许': '許', '诉': '訴', '让': '讓',
    '该': '該', '谁': '誰', '调': '調', '课': '課', '谢': '謝', '进': '進',
    '远': '遠', '运': '運', '过': '過', '还': '還', '边': '邊', '达': '達',
    '选': '選', '连': '連', '对': '對', '时': '時', '将': '將', '导': '導',
    '岁': '歲', '当': '當', '录': '錄', '钟': '鐘', '钱': '錢', '铁': '鐵',
    '银': '銀', '错': '錯', '锁': '鎖', '长': '長', '间': '間', '闻': '聞',
    '阳': '陽', '阴': '陰', '队': '隊', '难': '難', '面': '麵', '页': '頁',
    '须': '須', '飞': '飛', '馆': '館', '验': '驗', '惊': '驚', '鸡': '雞',
    '齐': '齊', '亲': '親', '觉': '覺', '览': '覽', '贝': '貝', '负': '負',
    '贵': '貴', '买': '買', '卖': '賣', '资': '資', '赵': '趙', '赶': '趕',
    '级': '級', '纪': '紀', '纸': '紙', '纯': '純', '纳': '納', '纲': '綱',
    '纷': '紛', '纹': '紋', '纺': '紡', '纽': '紐', '线': '線', '练': '練',
    '组': '組', '细': '細', '织': '織', '终': '終', '绍': '紹', '经': '經',
    '结': '結', '绕': '繞', '绘': '繪', '给': '給', '络': '絡', '绝': '絕',
    '统': '統', '丝': '絲', '继': '繼', '绩': '績', '绪': '緒', '续': '續',
    '维': '維', '绵': '綿', '综': '綜', '缓': '緩', '编': '編', '缘': '緣',
    '缠': '纏', '缩': '縮', '缴': '繳', '红': '紅', '纯': '純', '纱': '紗',
    '纲': '綱', '纳': '納', '纵': '縱', '纷': '紛', '纸': '紙', '纹': '紋',
    '纺': '紡', '纽': '紐', '线': '線', '练': '練', '组': '組', '绅': '紳',
    '细': '細', '织': '織', '终': '終', '绊': '絆', '绍': '紹', '绎': '繹',
    '经': '經', '绑': '綁', '绒': '絨', '结': '結', '绕': '繞', '绘': '繪',
    '给': '給', '绚': '絢', '络': '絡', '绝': '絕', '绞': '絞', '统': '統',
    '绢': '絹', '绣': '繡', '绥': '綏', '继': '繼', '绩': '績', '绪': '緒',
    '续': '續', '绮': '綺', '绰': '綽', '绳': '繩', '维': '維', '绵': '綿',
    '综': '綜', '绷': '繃', '绸': '綢', '绻': '綣', '绽': '綻', '绾': '綰',
    '绿': '綠', '缀': '綴', '缄': '緘', '缅': '緬', '缆': '纜', '缇': '緹',
    '缈': '緲', '缉': '緝', '缊': '縕', '缋': '繢', '缌': '緦', '缍': '縋',
    '缎': '緞', '缏': '緶', '缑': '緱', '缒': '縋', '缓': '緩', '缔': '締',
    '缕': '縷', '编': '編', '缗': '緡', '缘': '緣', '缙': '縉', '缚': '縛',
    '缛': '縟', '缜': '縝', '缝': '縫', '缞': '縗', '缟': '縞', '缠': '纏',
    '缡': '縭', '缢': '縊', '缣': '縑', '缤': '繽', '缥': '縹', '缦': '縵',
    '缧': '縲', '缨': '纓', '缩': '縮', '缪': '繆', '缫': '繅', '缬': '纈',
    '缭': '繚', '缮': '繕', '缯': '繒', '缰': '韁', '缱': '繾', '缲': '繰',
    '缳': '繯', '缴': '繳', '缵': '纘', '庐': '廬', '敌': '敵', '标': '標',
    '志': '誌', '样': '樣', '板': '闆', '节': '節', '杂': '雜', '乐': '樂',
}


def simp_to_trad(text: str) -> str:
    """Convert simplified text to traditional using character mapping."""
    result = []
    for char in text:
        result.append(SIMP_TO_TRAD.get(char, char))
    return ''.join(result)


def convert_inline_to_full_phrase(line: str) -> str:
    """Convert inline character-by-character traditional to full phrase format.
    
    From: 六边(邊)形 (liù biān xíng, "hexagon")
    To:   六边形(六邊形): liù biān xíng; hexagon
    """
    # Pattern: text with inline (trad) + space + (pinyin, "english")
    # e.g., "六边(邊)形 (liù biān xíng, \"hexagon\")"
    
    # Check if it already has colon format (already migrated)
    if re.match(r'^[^(]+\([^)]+\):\s', line) or ': ' in line and '; ' in line:
        # Already in new format, skip
        return line
    
    # Pattern for old format: Chinese(with inline trad) (pinyin, "english")
    match = re.match(r'^(.+?)\s+\(([^,]+),\s*"([^"]+)"\)$', line)
    if not match:
        return line
    
    chinese_part = match.group(1)  # e.g., "六边(邊)形"
    pinyin = match.group(2).strip()  # e.g., "liù biān xíng"
    english = match.group(3).strip()  # e.g., "hexagon"
    
    # Extract simplified by removing inline (trad) annotations
    # e.g., "六边(邊)形" -> "六边形"
    simplified = re.sub(r'\([^)]+\)', '', chinese_part)
    
    # Build traditional version
    traditional = simp_to_trad(simplified)
    
    # If traditional differs from simplified, show both
    if traditional != simplified:
        return f"{simplified}({traditional}): {pinyin}; {english}"
    else:
        return f"{simplified}: {pinyin}; {english}"


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    lines = content.split('\n')
    result = []
    
    in_contemporary = False
    
    for line in lines:
        # Track contemporary usage section
        if line.strip() == "- **contemporary usage:**":
            in_contemporary = True
            result.append(line)
            continue
        elif line.strip().startswith("- **") and "contemporary usage" not in line:
            in_contemporary = False
        
        # Convert contemporary usage items
        if in_contemporary and line.startswith("  - "):
            item = line[4:]  # Remove "  - "
            new_item = convert_inline_to_full_phrase(item)
            if new_item != item:
                line = f"  - {new_item}"
        
        result.append(line)
    
    new_content = '\n'.join(result)
    
    if new_content != original:
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fix contemporary usage format')
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

