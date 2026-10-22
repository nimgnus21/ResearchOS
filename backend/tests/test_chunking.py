"""4. Chunking and metadata preservation."""
from app.services.chunking import chunk_pages
from app.services.parsing import ParsedPage, parse_document


def _long_page(n=40, page=1):
    sents = [f"这是第{page}页的第{i}句，描述轴承温度与振动数据的变化情况。" for i in range(n)]
    return ParsedPage(page_number=page, text="".join(sents[: n // 2]) + "\n\n" + "".join(sents[n // 2 :]))


def test_chunks_respect_target_and_overlap():
    page = _long_page()
    chunks = chunk_pages([page], target_chars=200, overlap_chars=60)
    assert len(chunks) > 3
    for c in chunks:
        assert len(c.text) <= 200
        assert c.text == page.text[c.char_start : c.char_end]  # exact, traceable offsets
    overlaps = [b.char_start < a.char_end for a, b in zip(chunks, chunks[1:])]
    assert sum(overlaps) >= len(overlaps) // 2, "most consecutive chunks should overlap"
    covered = set()
    for c in chunks:
        covered.update(range(c.char_start, c.char_end))
    non_space = {i for i, ch in enumerate(page.text) if not ch.isspace()}
    assert non_space <= covered, "no text may be lost between chunks"


def test_chunks_never_cross_pages():
    pages = [_long_page(page=1), _long_page(page=2), _long_page(page=3)]
    chunks = chunk_pages(pages, target_chars=250, overlap_chars=50)
    for c in chunks:
        assert f"这是第{c.page_number}页" in c.text
        other = {1, 2, 3} - {c.page_number}
        assert all(f"这是第{o}页" not in c.text for o in other)


def test_heading_starts_new_chunk_and_section_inherits():
    text = "# 原因\n\n" + "润滑脂劣化导致温升。" * 15 + "\n\n# 建议\n\n每 500 小时补脂一次。"
    page = ParsedPage(1, text, headings=[(0, "原因"), (text.index("# 建议"), "建议")])
    chunks = chunk_pages([page], target_chars=200, overlap_chars=40)
    last = chunks[-1]
    assert last.section_title == "建议" and last.text.startswith("# 建议")
    assert chunks[0].section_title == "原因"
    # next page with no headings inherits the last section
    nxt = chunk_pages([page, ParsedPage(2, "续页内容。")], 200, 40)[-1]
    assert nxt.page_number == 2 and nxt.section_title == "建议"


def test_line_numbers_for_text_files(corpus_dir):
    raw = (corpus_dir / "maintenance_team_memo.md").read_text(encoding="utf-8")
    doc = parse_document("md", raw.encode())
    chunks = chunk_pages(doc.pages, 120, 30, track_lines=True)
    lines = raw.split("\n")
    for c in chunks:
        first = c.text.split("\n")[0]
        assert lines[c.line_start - 1].startswith(first[:10])
    target = next(c for c in chunks if "B-2207" in c.text)
    assert any("B-2207" in lines[i - 1] for i in range(target.line_start, target.line_end + 1))


def test_pathological_long_sentence_is_split():
    page = ParsedPage(1, "无标点长句" * 400)
    chunks = chunk_pages([page], target_chars=300, overlap_chars=50)
    assert all(len(c.text) <= 300 for c in chunks)
    assert "".join(page.text[c.char_start:c.char_end] for c in chunks).count("无标点长句") >= 390
