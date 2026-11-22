This project has the following files:
 - README.md - some introduction for users
 - markdown/PROJECT.md - describing project structure, coding conventions
 - markdown/ARCHITECTURE.md - describes architecture
 - markdown/URLS.md - defines server URLs
 - markdown/BUGS.md - list of bugs
 - markdown/TODO.md - todos
 - markdown/FILES.md - directory structure & file list

Order of work:
 - Do not run tests until changes were performed
 - Start with updating .md files if they should be updated (PROJECT, URLS, etc)
 - write unit tests if a case is missing
 - proceed with updating code
 - after implementation double check if there are similar places in code that should be refactored into a function, or if values were hardcoded in two or more places, but should be in one only

If you find additional errors not connected to prompt, context - you don't have to fix them immediately, but can put these into markdown/BUGS.md

## 4. Communication Style (Low-Verbosity Protocol)
- **Terse & Direct:** Strip all conversational filler, greetings, apologies, and closing summaries. Lead immediately with the answer, action, or diff.
- **High-Signal Formatting:** Prefer bullet fragments, file paths, and code blocks over prose paragraphs.
- **Exception for Specs & Interviews:** During `grill me`, `to spec`, and `code review`, prioritize clarity and precision over brevity—never omit edge cases or architectural reasoning just to save tokens.

---
