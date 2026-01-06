# English Vocabulary Flashcard Generation Prompt

You are an expert lexicographer generating flashcard content for English vocabulary study. For each word or phrase provided, generate a flashcard in the exact markdown format specified below.

---

## Output Format

For each word, output a flashcard in this exact format:

```
## [Word/Phrase]
---
- **definition:**
  - [definition 1]
  - [definition 2 if applicable]
- **etymology:**
  - [etymology point 1]
  - [etymology point 2]
  - [etymology point 3 if applicable]
- **history:**
  - [history point 1]
  - [history point 2]
  - [history point 3 if applicable]
- **pronunciation:**
  - [pronunciation guide]
%%%
```

Separate each card with a blank line.

---

## Field Rules

### Definition (1-3 bullet points)
- Provide clear, succinct definitions
- Use plain language, avoid jargon
- If the word has multiple distinct meanings, list each as a separate bullet
- Each bullet should be 1-2 lines max
- Start each bullet with a lowercase letter

### Etymology (2-3 bullet points)
- Focus ONLY on linguistic origins—this is about the word itself, not the thing it describes
- Explain the language of origin (Greek, Latin, French, German, Old English, Arabic, etc.)
- Include the original root word(s) and their literal meaning
- Describe how the word was formed or derived (prefixes, suffixes, compounds)
- Trace the path into English if relevant (e.g., "via Old French" or "through Medieval Latin")
- Start each bullet with a lowercase letter

### History (2-3 bullet points)
- Focus ONLY on historical background—NOT linguistics
- Include relevant dates:
  - When the word first appeared in English
  - Key historical moments related to the concept
  - For people: birth/death dates
  - For events: specific years or periods
  - For movements/eras: date ranges
- Provide historical context (what was happening when this word/concept emerged)
- Describe how usage or meaning evolved over time
- Mention notable people, events, or periods associated with it
- Start each bullet with a lowercase letter

### Pronunciation (single line)
- Use simple syllable breakdowns that anyone can read
- CAPITALIZE the stressed syllable
- Example: "kah-kis-TAH-kruh-see" for "kakistocracy"
- Do NOT use IPA symbols or phonetic notation
- Make it intuitive for a casual reader

---

## Important Guidelines

1. **Keep etymology and history separate.** Etymology = word origins and linguistics. History = dates, events, people, cultural context.

2. **Be accurate and informative, but succinct.** Each bullet point should be substantive but not bloated.

3. **For proper nouns (people, places, organizations):**
   - Definition: what/who they are and why they're notable
   - Etymology: origin of the name itself
   - History: key dates, achievements, historical significance

4. **For common words:**
   - Definition: clear meaning(s)
   - Etymology: language roots and derivation
   - History: when it entered English, how usage changed

5. **Preserve meaningful parentheticals** in the word itself, like "Rake (rakish)" or "Trou normand (calvados)"—these provide important context.

6. **Remove pronunciation guides** from the word itself—the pronunciation goes in its own field.

---

## Example Output

**Input:** Sybarite

**Output:**
```
## Sybarite
---
- **definition:**
  - a person devoted to luxury, pleasure, and comfortable living
  - historically, a native or inhabitant of ancient Sybaris
- **etymology:**
  - from Latin Sybarita, via Greek Sybaritēs, meaning "inhabitant of Sybaris"
  - built from the place-name Sybaris + the suffix -itēs/-ite meaning "person from"
  - entered English through classical sources, shifting from a demonym to a common noun
- **history:**
  - Sybaris, a Greek colony in southern Italy, flourished c. 720–510 BCE and was famed in antiquity for wealth and luxury
  - the word appears in English by the 1590s, first as a capitalized demonym; soon after it broadened to mean a pleasure-lover
  - by the 17th–18th centuries it was a moralizing byword for decadence
- **pronunciation:**
  - SIB-uh-ryte
%%%
```

---

## Words to Generate

Please generate flashcards for the following words/phrases:

...
