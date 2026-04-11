User: how does the scanner detect chatlog files?
Assistant: It looks for three patterns: speaker labels at line starts, `### ` headers, or `---` section dividers. Any one with three or more occurrences triggers detection.
User: what counts as a speaker label?
Assistant: A line starting with a capitalized identifier (1-16 chars), a colon, and a space. Like `User:`, `Assistant:`, or `DM:`.
User: and what does it actually extract?
Assistant: Turn count, speaker labels, section markers, character stats, reference tokens (@mentions, [[wiki links]], code fences, URLs), top capitalized tokens, and a vocabulary size estimate.
User: thanks for the explanation
Assistant: anytime, happy to help.
