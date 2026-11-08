"""Find the passages of the paper that are most relevant to a question.

This is the "R" in RAG (retrieval-augmented generation), written by hand with no
database, no embeddings and no external search service.

How it works, in three steps:

1. chunk_pages   - cut each page into overlapping pieces of about 1,400 characters.
                   A chunk never spans two pages, which is what lets every answer carry
                   a page number we can actually trust.
2. build_index   - score how important each word is, using TF-IDF. A word that appears
                   in only a few chunks (like "transformer") is a strong clue. A word in
                   nearly every chunk (like "model") is a weak one.
3. retrieve_chunks - compare the question against every chunk and return the best few.

Honest limitation worth understanding: this matches WORDS, not MEANING. If a question
says "conclude" and the paper only ever says "conclusion", plain word matching scores
zero. Embeddings would solve that properly, at the cost of a large dependency. This
prototype stays dependency-free and closes the worst of the gap with three small, plain
rules in retrieve_chunks:

  - RELATED_PAPER_WORDS bridges question words to the words papers actually use
    ("conclude" also searches for "conclusion", "finding" and "result").
  - OVERVIEW_PHRASES sends whole-paper questions to the abstract, because words like
    "topic" never appear in a paper at all.
  - A second attempt at a lower score accepts weaker matches, but ONLY when nothing
    scored well and only for chunks that already shared words with the question.

question_names_something_absent is the guard on the last two: a question naming a
subject the paper never mentions keeps the strict rules and still returns nothing.
"""

import math
import re
from collections import Counter

# Roughly how many characters go in one chunk. Big enough to hold a full argument,
# small enough that four chunks still fit comfortably in an AI request.
CHUNK_CHARACTERS = 1_400

# Each chunk repeats this many characters of the previous one, so a sentence that falls
# on a chunk boundary still appears whole in one of them.
OVERLAP_CHARACTERS = 220

# The most passages we ever send to the AI, which keeps requests small and cheap.
MAX_RETRIEVED_CHUNKS = 4

# A chunk scoring below this is treated as not relevant. Raising it returns fewer but
# more certain passages; lowering it returns more passages of lower quality. Note that
# broad questions ("what methodology was used?") often score just under this value,
# which is why they can come back with no results at all.
MIN_SIMILARITY = 0.12

# At least this share of the question's meaningful words must appear in a chunk. This
# stops a chunk from being chosen because it happened to match one common word.
MIN_QUERY_COVERAGE = 0.25

# The lower score used only as a second attempt, when nothing reached MIN_SIMILARITY.
# Broad questions such as "what methodology did the authors use?" match the right
# passages but score low, because their words are common across the whole paper. On a
# real 15-page paper the best methodology passage scored 0.0935, just under the 0.12
# threshold, so the question used to return nothing at all. This floor rescues that case.
FALLBACK_MIN_SIMILARITY = 0.05

# The second attempt returns fewer passages than a confident match would, because these
# are weaker matches and we do not want to fill the AI's evidence with guesses.
FALLBACK_MAX_CHUNKS = 3

# How many opening chunks answer a question about the paper as a whole. A paper states
# its topic and its problem in the title, abstract and introduction, which are here.
OVERVIEW_CHUNKS = 3

# Words too common to help us find anything. Removing them means "What is the main topic
# of this paper?" is searched as just "main topic". Note this includes words like
# "paper" and "research", because almost every chunk of a research paper contains them.
STOP_WORDS = set("""a an and are as at be been being but by can could did do does doing
for from had has have how i if in into is it its me my of on or our please should so
than that the their them then there these they this those to us was we were what when
where which who why will with would you your about also explain tell give describe
paper papers document documents research study studies uploaded supplied according""".split())

# Finds runs of letters and digits, ignoring punctuation and underscores.
WORD_PATTERN = re.compile(r"[^\W_]+")

# A blank line, or the space after a sentence-ending ".", "!" or "?". These are the
# natural places to cut text so a chunk does not end mid-sentence.
SENTENCE_OR_PARAGRAPH_BREAK = re.compile(r"\n\s*\n|(?<=[.!?])\s+")

# Same idea, but checked in the other order when we look inside the overlap region.
BREAK_INSIDE_OVERLAP = re.compile(r"(?<=[.!?])\s+|\n\s*\n")

# Matches questions that are only asking for the paper's title.
TITLE_QUESTION = re.compile(
    r"(?:(?:what is|what's|give me|tell me) )?(?:the )?(?:(?:paper|document|pdf) )?"
    r"title(?: of (?:this|the|my) (?:research paper|paper|document|pdf|study))?"
)

# Matches "what is X" style questions, so we can treat X as the thing being defined.
DEFINITION_QUESTION = re.compile(r"(?:what is|what are|what's|define|meaning of) (.+)")

# Questions about the paper as a whole, rather than about something inside it.
#
# These need their own handling because the words that make them meaningful to a person
# ("topic", "about") never appear in a research paper, so word matching scores zero no
# matter how well the paper answers the question. Every phrase mentions the paper or the
# document, which keeps unrelated questions from matching by accident.
OVERVIEW_PHRASES = (
    "main topic", "overall topic", "research problem",
    "this paper about", "the paper about", "this document about", "this study about",
    "problem does this paper", "problem does the paper", "problem this paper",
    "what is this paper", "what does this paper study",
    "what does this paper investigate", "what does this paper propose",
    "summarize this paper", "summarise this paper",
)

# Words people use when asking about research, mapped to the words papers really use.
#
# Someone asks "what do the authors conclude?" but the paper says "Conclusion" and
# "findings". It never says "conclude". TF-IDF compares words, not meaning, so without
# this bridge the question matches nothing. Each value is written in the singular form
# that tokenize() produces, so the added words can match a chunk's words directly.
RELATED_PAPER_WORDS = {
    "topic": ["abstract", "introduction"],
    "overview": ["abstract", "introduction"],
    "summary": ["abstract", "introduction"],
    "problem": ["problem", "challenge", "limitation", "motivation"],
    "address": ["problem", "challenge", "motivation"],
    "challenge": ["problem", "challenge", "limitation"],
    "motivation": ["motivation", "problem", "introduction"],
    "goal": ["objective", "aim", "goal"],
    "objective": ["objective", "aim", "goal"],
    "method": ["method", "approach", "experiment", "training", "architecture"],
    "approach": ["method", "approach", "experiment"],
    "experiment": ["experiment", "method", "evaluation"],
    "conclude": ["conclusion", "finding", "result"],
    "conclusion": ["conclusion", "finding", "result"],
    "finding": ["finding", "result", "conclusion"],
    "result": ["result", "finding", "performance"],
    "contribution": ["contribution", "propose", "novel"],
    "limitation": ["limitation", "future", "work"],
}

# Other general research words that are normal in a question but may be missing from a
# paper. Listed so that a question built only from general words is still recognised as
# a question about the paper, rather than as a question about an unrelated subject.
EXTRA_GENERIC_WORDS = {
    "author", "use", "main", "key", "overall", "purpose", "aim", "propose",
    "present", "investigate", "novelty", "significance", "train", "do",
    # Words about the document's structure rather than its subject, so that a question
    # like "what does page 6 describe?" is still treated as a question about the paper.
    "page", "section", "table", "figure",
}

# Every word that counts as "general research vocabulary" rather than a subject word.
GENERIC_RESEARCH_WORDS = set(RELATED_PAPER_WORDS) | EXTRA_GENERIC_WORDS


def tokenize(text: str) -> list[str]:
    """Split text into the meaningful words we will actually compare.

    Three things happen here:
    1. Everything is lowercased, so "Attention" and "attention" match.
    2. Stop words and single letters are dropped.
    3. Simple plurals are reduced to singular ("methods" -> "method"), so a question
       about "methods" still matches a paper that says "method".
    """
    words = []

    for word in WORD_PATTERN.findall(text.casefold()):
        if word in STOP_WORDS or len(word) < 2:
            continue

        # "studies" -> "study". Only for longer words, so we do not mangle short ones.
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        # "models" -> "model", but leave "class", "status" and "analysis" alone, where
        # the trailing "s" is part of the word rather than a plural.
        elif len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]

        # The two spellings are used interchangeably in papers, so treat them as one.
        if word == "methodology":
            word = "method"

        words.append(word)

    return words


def find_chunk_end(text: str, start: int) -> int:
    """Decide where the chunk starting at `start` should end.

    We aim for CHUNK_CHARACTERS, then move the end backwards to the nearest natural
    break so the chunk does not stop in the middle of a sentence. We only accept a break
    in the second half of the chunk, because cutting at the very first sentence would
    produce tiny, useless chunks.
    """
    furthest_end = min(start + CHUNK_CHARACTERS, len(text))

    # The last chunk of the page simply ends at the end of the text.
    if furthest_end >= len(text):
        return len(text)

    window = text[start:furthest_end]
    halfway = CHUNK_CHARACTERS // 2

    # Prefer the LAST sentence or paragraph break in the second half of the window,
    # which keeps the chunk as full as possible while still ending cleanly.
    break_positions = [
        match.end() for match in SENTENCE_OR_PARAGRAPH_BREAK.finditer(window)
        if match.end() >= halfway
    ]
    if break_positions:
        return start + break_positions[-1]

    # No sentence break available, so fall back to the last space: ending between two
    # words is still better than ending inside one.
    last_space = window.rfind(" ")
    if last_space >= halfway:
        return start + last_space

    # Unbroken text, such as a long table or formula. Accept the hard cut.
    return furthest_end


def find_next_chunk_start(text: str, start: int, end: int) -> int:
    """Decide where the next chunk should begin, so that it overlaps this one.

    The next chunk starts OVERLAP_CHARACTERS before the current end, then we nudge it
    forward to a clean boundary so the repeated text begins at a sentence or at least at
    a whole word.
    """
    # max(start + 1, ...) guarantees forward progress, so the loop can never get stuck.
    next_start = max(start + 1, end - OVERLAP_CHARACTERS)
    overlap_region = text[next_start:end]

    # Best case: start the overlap at a sentence boundary inside that region.
    sentence_break = BREAK_INSIDE_OVERLAP.search(overlap_region)
    if sentence_break and next_start + sentence_break.end() < end:
        return next_start + sentence_break.end()

    # Otherwise, if we would start in the middle of a word, skip to the next space.
    if next_start > 0 and not text[next_start - 1].isspace():
        next_space = re.search(r"\s+", overlap_region)
        if next_space:
            return next_start + next_space.end()

    return next_start


def chunk_pages(pages: list[dict]) -> list[dict]:
    """Cut every page into overlapping chunks, keeping each chunk on a single page.

    Input:  pages  - [{"page_number": 1, "text": "..."}, ...] from PDF extraction.
    Output: chunks - [{"chunk_id", "page_number", "text", "start", "end"}, ...]

    Chunking per page rather than across the whole document is the reason citations are
    reliable: every chunk belongs to exactly one page, so its page number is a fact
    rather than an estimate.
    """
    chunks = []

    for page in pages:
        # Collapse runs of spaces and tabs, which PDF extraction produces a lot of.
        # Newlines are kept, because they tell us where paragraphs end.
        text = re.sub(r"[ \t]+", " ", page["text"]).strip()

        start = 0
        while start < len(text):
            end = find_chunk_end(text, start)
            excerpt = text[start:end].strip()

            if excerpt:
                chunks.append({
                    "chunk_id": f"chunk-{len(chunks) + 1}",
                    "page_number": page["page_number"],
                    "text": excerpt,
                    "start": start,
                    "end": end,
                })

            # Reached the end of this page.
            if end == len(text):
                break

            next_start = find_next_chunk_start(text, start, end)
            start = min(next_start, end)

    return chunks


def normalized_weights(counts: Counter, idf: dict, unseen_idf: float) -> dict:
    """Turn word counts into a comparable set of weights (one TF-IDF vector).

    Two things happen:
    1. Each word's weight is how often it appears, damped by a logarithm so a word used
       20 times is not considered 20 times more important than one used once, multiplied
       by how rare the word is across the document (its IDF).
    2. The weights are scaled so the whole vector has length 1. This is what makes a
       long chunk and a short chunk comparable; without it, longer chunks would always
       look more relevant simply for containing more words.
    """
    weights = {}
    for word, count in counts.items():
        term_frequency = 1 + math.log(count)
        word_rarity = idf.get(word, unseen_idf)
        weights[word] = term_frequency * word_rarity

    # Vector length, i.e. the square root of the sum of the squared weights.
    vector_length = math.sqrt(sum(weight * weight for weight in weights.values()))
    if vector_length:
        for word in weights:
            weights[word] /= vector_length

    return weights


def build_index(pages: list[dict]) -> dict:
    """Build the search index for one document. Called once per uploaded PDF.

    Returns a dict holding the chunks, the rarity score (IDF) of every word, and one
    pre-computed weight vector per chunk. Building this once means every later question
    only has to score the question itself.
    """
    chunks = chunk_pages(pages)

    # Count the words in each chunk, and count how many chunks contain each word.
    word_counts_per_chunk = []
    chunks_containing_word = Counter()
    for chunk in chunks:
        words_in_chunk = Counter(tokenize(chunk["text"]))
        word_counts_per_chunk.append(words_in_chunk)
        chunks_containing_word.update(words_in_chunk.keys())

    # IDF: how rare, and therefore how informative, each word is. A word in few chunks
    # gets a high score; a word in almost every chunk gets a score near 1.
    idf = {}
    for word, chunk_count in chunks_containing_word.items():
        idf[word] = math.log((1 + len(chunks)) / (1 + chunk_count)) + 1

    # The score for a question word that is not in the document at all. It is set to the
    # minimum rather than the maximum on purpose: a word the paper never uses should
    # weaken the match, but giving it the highest possible rarity would let one unknown
    # word dominate the score and drown out the words that did match.
    unseen_idf = 1.0

    chunk_vectors = []
    for words_in_chunk in word_counts_per_chunk:
        chunk_vectors.append(normalized_weights(words_in_chunk, idf, unseen_idf))

    return {
        "chunks": chunks,
        "idf": idf,
        "unseen_idf": unseen_idf,
        "vectors": chunk_vectors,
    }


def similarity_score(query_weights: dict, chunk_vector: dict) -> float:
    """Measure how similar a question is to a chunk (cosine similarity).

    Because both vectors were scaled to length 1 in normalized_weights, multiplying the
    shared words together and adding up the results gives a score between 0 and 1,
    where 1 would mean an identical mix of words.
    """
    score = 0.0
    for word, weight in query_weights.items():
        score += weight * chunk_vector.get(word, 0)
    return score


def asks_for_paper_overview(normalized_question: str) -> bool:
    """Say whether the question is about the paper as a whole.

    Input:  a lowercased question with its spacing tidied up.
    Output: True for questions like "what is the main topic of this paper?".

    Used to send those questions straight to the paper's opening chunks, because the
    abstract is where a paper states both its topic and the problem it tackles.
    """
    for phrase in OVERVIEW_PHRASES:
        if phrase in normalized_question:
            return True
    return False


def question_names_something_absent(question_words: Counter, index: dict) -> bool:
    """Say whether the question mentions a subject the paper never talks about.

    Input:  the question's meaningful words, and the search index.
    Output: True if any subject word in the question is missing from the paper.

    This is the safety check for the two relaxations below. "Method for baking
    croissants" shares the general word "method" with a machine-learning paper, so
    without this check a stretched search could return a methods passage for it. General
    research words are ignored here, which is what lets "what do the authors conclude?"
    still be treated as a real question about the paper.
    """
    for word in question_words:
        if word in GENERIC_RESEARCH_WORDS:
            continue
        if word in index["idf"]:
            continue
        # A subject word the paper never uses, so the question is about something else.
        return True
    return False


def add_related_words(question_words: Counter) -> Counter:
    """Add the words a paper would really use for each research word in the question.

    Input:  the question's meaningful words.
    Output: a new Counter with related words added; the original is left unchanged.

    Added words get a count of 1, so they act as extra hints without outweighing the
    words the user actually typed.
    """
    expanded_words = Counter(question_words)

    for word in list(question_words):
        for related_word in RELATED_PAPER_WORDS.get(word, []):
            if related_word not in expanded_words:
                expanded_words[related_word] = 1

    return expanded_words


def find_matching_chunks(index: dict, question_words: Counter,
                         query_weights: dict) -> list[tuple]:
    """Score every chunk that shares enough words with the question.

    Input:  the index, the question's words, and the question's weight vector.
    Output: a list of (score, chunk) pairs for chunks that passed the word checks.

    The two word checks below are the real protection against irrelevant results. A
    chunk that fails them is never scored, which is why an unrelated question returns
    nothing even if some chunk would have scored highly.
    """
    matching_chunks = []

    for chunk, chunk_vector in zip(index["chunks"], index["vectors"]):
        matched_words = question_words.keys() & chunk_vector.keys()

        # Require at least two matching words, or one if the question only has one.
        if len(matched_words) < min(2, len(question_words)):
            continue

        # Require a reasonable share of the question's words to be present.
        if len(matched_words) / len(question_words) < MIN_QUERY_COVERAGE:
            continue

        matching_chunks.append((similarity_score(query_weights, chunk_vector), chunk))

    return matching_chunks


def select_best_chunks(scored_chunks: list[tuple], limit: int) -> list[dict]:
    """Sort chunks by score, drop repeats, and return at most `limit` of them.

    Input:  a list of (score, chunk) pairs, and how many to keep.
    Output: the chosen chunks, best first.
    """
    # Sort by score only. The explicit key matters: without it, Python would compare the
    # chunk dictionaries whenever two scores tie, and raise a TypeError.
    scored_chunks.sort(key=lambda scored: scored[0], reverse=True)

    # Overlapping chunks can contain the same text, so skip duplicates to avoid sending
    # the AI the same passage twice.
    selected_chunks = []
    already_selected_text = set()
    for score, chunk in scored_chunks:
        if chunk["text"] in already_selected_text:
            continue
        selected_chunks.append(chunk)
        already_selected_text.add(chunk["text"])
        if len(selected_chunks) == limit:
            break

    return selected_chunks


def retrieve_chunks(index: dict, question: str) -> list[dict]:
    """Return up to four chunks that best match the question, best first.

    Input:  the index built for one document, and the user's question.
    Output: the chosen chunks, or an empty list when nothing is relevant enough.

    An empty list is a meaningful answer, not a failure: the caller then tells the user
    there is not enough evidence rather than letting the AI guess.

    The search happens in four steps, stopping at the first one that works:
      1. A title question returns the first chunk.
      2. A question about the whole paper returns the opening chunks.
      3. The normal search returns chunks scoring at least MIN_SIMILARITY.
      4. If step 3 found nothing, a second attempt accepts weaker but still
         word-matched chunks above FALLBACK_MIN_SIMILARITY.
    """
    normalized_question = " ".join(question.casefold().split()).rstrip("?.!")

    # Step 1: "what is the title of this paper?". A title sits at the very start of a
    # paper and the word "title" almost never appears in the body text, so word matching
    # would score zero. Returning the first chunk is a deliberate shortcut.
    if TITLE_QUESTION.fullmatch(normalized_question):
        return index["chunks"][:1]

    # Step 2: "what is the main topic of this paper?" for the same reason. The words that
    # make the question meaningful are not in the paper, but the abstract answers it.
    if asks_for_paper_overview(normalized_question):
        return index["chunks"][:OVERVIEW_CHUNKS]

    # For "what is X?", search for X alone rather than the whole sentence.
    definition_match = DEFINITION_QUESTION.match(normalized_question)
    if definition_match:
        question_words = Counter(tokenize(definition_match[1]))
    else:
        question_words = Counter(tokenize(question))

    # Nothing left after removing stop words, e.g. "what is it about?".
    if not question_words:
        return []

    # A definition question about a single term is special: that term may appear all
    # over the paper, which makes its rarity score low and its similarity score low too.
    # We still want to show those chunks, so the score threshold is skipped.
    asks_for_one_definition = definition_match is not None and len(question_words) == 1

    # Only broaden the search for questions that are really about this paper. If the
    # question names a subject the paper never mentions, we keep the strict rules so the
    # question honestly returns nothing instead of reaching an AI provider.
    question_is_about_this_paper = not question_names_something_absent(question_words, index)
    if question_is_about_this_paper:
        question_words = add_related_words(question_words)

    query_weights = normalized_weights(question_words, index["idf"], index["unseen_idf"])
    matching_chunks = find_matching_chunks(index, question_words, query_weights)

    # Step 3: the normal search. Keep chunks we are confident about.
    confident_chunks = []
    for score, chunk in matching_chunks:
        if asks_for_one_definition or score >= MIN_SIMILARITY:
            confident_chunks.append((score, chunk))

    if confident_chunks:
        return select_best_chunks(confident_chunks, MAX_RETRIEVED_CHUNKS)

    # Step 4: the second attempt. Only chunks that already passed the word checks are
    # considered, so this lowers the score bar without lowering the relevance bar.
    if not question_is_about_this_paper:
        return []

    weaker_chunks = []
    for score, chunk in matching_chunks:
        if score >= FALLBACK_MIN_SIMILARITY:
            weaker_chunks.append((score, chunk))

    return select_best_chunks(weaker_chunks, FALLBACK_MAX_CHUNKS)
