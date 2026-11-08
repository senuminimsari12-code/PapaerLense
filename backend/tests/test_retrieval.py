import pytest

from collections import Counter

from backend.retrieval import (
    CHUNK_CHARACTERS, add_related_words, asks_for_paper_overview, build_index, chunk_pages,
    question_names_something_absent, retrieve_chunks, tokenize,
)


@pytest.mark.parametrize("pages", [[], [{"page_number": 1, "text": ""}], [{"page_number": 1, "text": " \n  "}]])
def test_empty_pages_create_no_chunks_or_matches(pages):
    index = build_index(pages)
    assert index["chunks"] == []
    assert retrieve_chunks(index, "classifier accuracy") == []


def test_chunks_preserve_original_page_numbers_and_do_not_mutate_source():
    pages = [{"page_number": 1, "text": ""}, {"page_number": 2, "text": "First research result."},
             {"page_number": 8, "text": "Later original conclusion."}]
    chunks = chunk_pages(pages)
    assert [chunk["page_number"] for chunk in chunks] == [2, 8]
    assert len({chunk["chunk_id"] for chunk in chunks}) == 2
    assert pages[0]["text"] == ""
    assert pages[1]["text"] == "First research result."


def test_long_page_uses_bounded_overlapping_sentence_chunks():
    sentences = [f"Experiment number {number} measures classifier accuracy on its dataset." for number in range(160)]
    text = " ".join(sentences)
    chunks = chunk_pages([{"page_number": 4, "text": text}])
    assert len(chunks) > 2
    assert all(len(chunk["text"]) <= CHUNK_CHARACTERS for chunk in chunks)
    assert all(chunk["page_number"] == 4 for chunk in chunks)
    assert all(chunk["text"].endswith(".") for chunk in chunks)
    assert all(any(sentence in chunk["text"] for chunk in chunks) for sentence in sentences)
    assert all(chunks[i + 1]["start"] < chunks[i]["end"] for i in range(len(chunks) - 1))


def test_pathological_unbroken_text_still_progresses_without_gaps():
    text = "x" * 8_000
    chunks = chunk_pages([{"page_number": 1, "text": text}])
    assert 1 < len(chunks) < 20
    assert chunks[0]["start"] == 0
    assert chunks[-1]["end"] == len(text)
    assert all(chunks[i]["start"] < chunks[i + 1]["start"] <= chunks[i]["end"] for i in range(len(chunks) - 1))


def test_tokenization_preserves_technical_terms_and_normalizes_simple_plurals():
    assert tokenize("What METHODS and datasets does the paper use for BLEU scores?") == ["method", "dataset", "use", "bleu", "score"]
    assert tokenize("methodology analysis classifiers") == ["method", "analysis", "classifier"]


def test_retrieval_ranks_relevant_page_and_preserves_source():
    index = build_index([
        {"page_number": 1, "text": "Volcanic eruptions release lava and ash through vents."},
        {"page_number": 5, "text": "The image classifier achieved 93 percent accuracy on the test dataset."},
        {"page_number": 7, "text": "The authors thank their colleagues for support."},
    ])
    chunks = retrieve_chunks(index, "What accuracy does the classifier achieve?")
    assert chunks[0]["page_number"] == 5
    assert "93 percent accuracy" in chunks[0]["text"]
    assert len(chunks) == 1


def test_short_single_chunk_paper_can_be_retrieved():
    index = build_index([{"page_number": 1, "text": "Classifier accuracy is 93 percent."}])
    assert retrieve_chunks(index, "classifier accuracy")[0]["page_number"] == 1


@pytest.mark.parametrize("question", ["What is cuteness?", "Define cuteness", "Meaning of cuteness"])
def test_single_term_definitions_retrieve_exact_matches_below_similarity_threshold(question):
    background = " ".join(f"term{i}" for i in range(100))
    index = build_index([
        {"page_number": 1, "text": f"Cuteness is an impression shaped by infant features. {background}"},
        {"page_number": 2, "text": f"Cuteness can elicit care. {background}"},
        {"page_number": 3, "text": background},
    ])
    assert {chunk["page_number"] for chunk in retrieve_chunks(index, question)} == {1, 2}
    assert retrieve_chunks(index, "What is a car?") == []


@pytest.mark.parametrize("question", ["How do I bake sourdough bread?", "the and what is it", "???", "method for baking croissants"])
def test_unrelated_or_meaningless_questions_have_no_matches(question):
    index = build_index([{"page_number": 1, "text": "Our method measures classifier accuracy on image datasets."}])
    assert retrieve_chunks(index, question) == []


def test_retrieval_returns_at_most_four_distinct_passages():
    pages = [{"page_number": number, "text": f"Experiment {number} measures classifier accuracy with dataset number {number}."} for number in range(1, 15)]
    chunks = retrieve_chunks(build_index(pages), "classifier accuracy dataset")
    assert len(chunks) == 4
    assert len({chunk["text"] for chunk in chunks}) == 4


def test_duplicate_headers_do_not_fill_all_context_slots():
    index = build_index([{"page_number": number, "text": "Classifier accuracy measurement."} for number in range(1, 6)])
    assert len(retrieve_chunks(index, "classifier accuracy")) == 1


def test_many_pages_can_find_relevant_passage_near_end():
    pages = [{"page_number": number, "text": f"General experiment notes for section number {number}."} for number in range(1, 200)]
    pages.append({"page_number": 200, "text": "The zeolite catalyst achieves a conversion efficiency of 87 percent."})
    matches = retrieve_chunks(build_index(pages), "zeolite catalyst conversion efficiency")
    assert matches[0]["page_number"] == 200


# ---------------------------------------------------------------------------
# Bug 1 regression: broad research questions used to retrieve nothing at all.
#
# A realistic paper is needed here. The old failures only appear once a document is
# long enough for common words such as "method" and "model" to lose their rarity
# value, which is exactly when the similarity score drops below the threshold.
# ---------------------------------------------------------------------------

RESEARCH_PAPER = [
    {"page_number": 1, "text": """Deep Residual Learning for Soil Moisture Estimation
    R. Mendez and L. Farrow, University of Example
    Abstract. Estimating soil moisture from satellite radar imagery is difficult because
    backscatter depends on surface roughness and vegetation cover. We propose a residual
    convolutional network that predicts volumetric soil moisture directly from Sentinel-1
    imagery. The network reaches a root mean square error of 0.031, improving on a linear
    baseline of 0.058 across four hundred field sites.
    1 Introduction
    Accurate soil moisture maps support drought monitoring and irrigation planning.
    Physical retrieval models must be calibrated separately for every site, which limits
    their use at continental scale. That limitation is the motivation for a learned
    approach that generalises across sites without per-site calibration."""},
    {"page_number": 2, "text": """2 Related Work
    Earlier studies applied random forests and support vector regression to radar
    backscatter values. Those studies treat every pixel independently and therefore
    ignore the spatial context that surrounds a measurement. Other work has combined
    optical reflectance with radar, but optical imagery is blocked by cloud cover for
    much of the growing season in temperate regions."""},
    {"page_number": 3, "text": """3 Method
    Our approach is a residual convolutional network with eight residual blocks and a
    linear output layer. Each block applies two convolutions with batch normalisation.
    The architecture takes a patch of Sentinel-1 backscatter together with a terrain
    slope raster. We train the network using the Adam optimizer with a learning rate of
    0.001 and a batch size of 64 patches. The experiment design splits four hundred field
    sites into training, validation and test groups so that no site appears twice. Our
    evaluation protocol repeats every experiment with five random seeds."""},
    {"page_number": 4, "text": """4 Results
    The network attains a root mean square error of 0.031 on held out sites, compared
    with 0.058 for the linear baseline and 0.042 for the random forest. Performance is
    strongest on bare soil and weakest under dense vegetation, where the error rises to
    0.049. Table 2 reports the result for each land cover class. The improvement over the
    baseline is consistent across all five random seeds."""},
    {"page_number": 5, "text": """5 Conclusion
    We conclude that a residual convolutional network can estimate soil moisture from
    radar imagery without per-site calibration. Our findings show that spatial context
    contributes more to the result than additional optical bands. Limitations include the
    restricted geographic coverage of the training sites and the absence of measurements
    under frozen soil conditions. Future work should evaluate transfer to other radar
    sensors and extend the evaluation to a full annual cycle."""},
]


def research_index():
    return build_index(RESEARCH_PAPER)


@pytest.mark.parametrize("question", [
    "What is the main topic of this paper?",
    "What is this paper about?",
    "What research problem does this paper address?",
    "What methodology did the authors use?",
    "What methodology did the authors use to train the model?",
    "What do the authors conclude?",
    "What are the key results?",
])
def test_broad_research_questions_now_retrieve_supporting_passages(question):
    chunks = retrieve_chunks(research_index(), question)
    assert chunks, f"no passages retrieved for {question!r}"
    assert len(chunks) <= 4
    # Page numbers must still belong to the real document.
    assert all(1 <= chunk["page_number"] <= 5 for chunk in chunks)


@pytest.mark.parametrize("question,expected_page", [
    ("What is a residual convolutional network?", 3),
    ("What root mean square error did the network attain on held out sites?", 4),
    ("Which optimizer and learning rate were used for training?", 3),
])
def test_specific_questions_still_rank_the_correct_page_first(question, expected_page):
    chunks = retrieve_chunks(research_index(), question)
    assert chunks
    assert chunks[0]["page_number"] == expected_page


@pytest.mark.parametrize("question", [
    "How do I bake sourdough bread?",
    "What is the weather like in Paris today?",
    "Who won the 2018 football world cup?",
    "How do I fix my car engine?",
    "method for baking croissants",
    "What is the best recipe for pizza dough?",
])
def test_unrelated_questions_still_retrieve_nothing_from_a_real_paper(question):
    # The honest insufficient-evidence path must survive the broader retrieval, so that
    # an unrelated question never reaches an AI provider.
    assert retrieve_chunks(research_index(), question) == []


def test_broadened_retrieval_never_exceeds_the_passage_limit():
    # The relaxed second attempt must stay conservative, not flood the AI with guesses.
    for question in ["What do the authors conclude?", "What methodology did the authors use?"]:
        assert len(retrieve_chunks(research_index(), question)) <= 3


def test_question_naming_an_absent_subject_keeps_the_strict_rules():
    index = research_index()
    # "method" is a general research word that the paper does use, but "croissant" is a
    # subject the paper never mentions, so the relaxations must stay switched off.
    assert question_names_something_absent(Counter(tokenize("method for baking croissants")), index)
    assert not question_names_something_absent(Counter(tokenize("What do the authors conclude?")), index)


def test_related_words_are_added_without_changing_the_original_question():
    original = Counter(tokenize("What do the authors conclude?"))
    expanded = add_related_words(original)
    assert "conclusion" in expanded and "finding" in expanded
    assert "conclusion" not in original, "the caller's Counter must not be modified"


@pytest.mark.parametrize("question,expected", [
    ("What is the main topic of this paper?", True),
    ("What research problem does this paper address?", True),
    ("What is this paper about?", True),
    ("What is scaled dot-product attention?", False),
    ("How do I bake sourdough bread?", False),
])
def test_overview_questions_are_recognised_without_matching_unrelated_ones(question, expected):
    normalized = " ".join(question.casefold().split()).rstrip("?.!")
    assert asks_for_paper_overview(normalized) is expected
