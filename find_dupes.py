#!/usr/bin/env python3
"""Find and fix generalized duplicate English patterns in flashcard files."""

import os
import re
from pathlib import Path

def fix_duplicate_english(text):
    """Fix all duplicate English patterns."""
    original = text

    # Pattern: English text followed by (same English text)
    # e.g., "In classical texts it was often written as "艸"(In classical texts it was often written as "艸"),while"
    # The key insight: the English part before ( should match the English part inside ()

    # Generalized pattern: detect when text before ( matches text inside ()
    # Look for: "some text"(same text), or some text(same text).

    def fix_english_duplicates(line):
        """Fix a single line."""
        # Pattern: capture English text that's duplicated in parentheses
        # Match: text(text) where text contains mostly English

        # Find all (text) patterns and check if preceding text matches
        result = []
        i = 0
        while i < len(line):
            # Look for opening paren
            if line[i] == '(':
                # Find matching close paren
                depth = 1
                j = i + 1
                while j < len(line) and depth > 0:
                    if line[j] == '(':
                        depth += 1
                    elif line[j] == ')':
                        depth -= 1
                    j += 1

                if depth == 0:
                    inside = line[i+1:j-1]

                    # Check if this looks like duplicated English (contains "In " at start)
                    if inside.startswith('In ') and len(inside) > 10:
                        # Look back to find where the duplicate starts
                        # The pattern before ( should end with something matching inside
                        lookback = line[max(0, i-len(inside)-10):i]

                        # Extract English-only for comparison
                        def get_english_skeleton(s):
                            return re.sub(r'[^\x00-\x7F]+', '', s).strip()

                        inside_eng = get_english_skeleton(inside)
                        lookback_eng = get_english_skeleton(lookback)

                        # Check if lookback ends with inside
                        if lookback_eng.endswith(inside_eng) or inside_eng in lookback_eng:
                            # This is a duplicate - skip the parenthetical
                            result.append(line[len(result) and sum(len(r) for r in result) or 0:i])
                            i = j
                            continue

                result.append(line[i])
                i += 1
            else:
                result.append(line[i])
                i += 1

        return ''.join(result)

    # Apply specific known patterns first

    # Pattern 1: "In classical texts it was often written as "X"(In classical texts...)
    text = re.sub(
        r'(In classical texts it was often written as "[^"]+")(\(In classical texts it was often written as "[^"]+"\)),',
        r'\1,',
        text
    )

    # Pattern 2: "In dictionaries, X also serves as a radical(X also serves as a radical),"
    text = re.sub(
        r'(In dictionaries,)([^(]+)(also serves as a radical)\(\2\3\),',
        r'\1 \2\3,',
        text
    )

    # Pattern 3: "In characters like X(In characters like X),"
    text = re.sub(
        r'(In characters like [^(]+)\(In characters like [^)]+\),',
        r'\1,',
        text
    )

    # Pattern 4: Generic "In X text(In X text)" where X is any phrase
    # This catches: "In oracle script, X represents Y(X represents Y)."
    text = re.sub(
        r'(In [a-z]+ [a-z]+,?\s*)([^(]+)\(\2\)',
        r'\1\2',
        text
    )

    return text, text != original

def fix_file(filepath):
    """Fix duplicate patterns in a file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        fixed_content, changed = fix_duplicate_english(content)

        if changed:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(fixed_content)
            return True
        return False
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False

def main():
    import sys

    base_dirs = [
        '/Users/scobbe/src/flashcards/output/chinese/general/daily/12-26-25/output',
        '/Users/scobbe/src/flashcards/output/chinese/general/daily/12-27-25/output',
        '/Users/scobbe/src/flashcards/output/chinese/general/common/10000-phrases/chunks/chunk-001/output',
    ]

    files_fixed = 0
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
        for filename in os.listdir(base_dir):
            if filename.endswith('.md'):
                filepath = os.path.join(base_dir, filename)
                if fix_file(filepath):
                    files_fixed += 1
                    print(f"Fixed: {filepath}")
    print(f"\nTotal files fixed: {files_fixed}")
