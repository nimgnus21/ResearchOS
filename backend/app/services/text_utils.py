"""Tokenization shared by keyword indexing, query parsing and the offline hash embedder.

PostgreSQL's 'simple' text-search parser does not segment Chinese, so we pre-tokenize in
Python and store a space-joined token string (`search_text`) that Postgres indexes as-is:

* Latin/digit runs -> lowercase words with light plural stripping.
* CJK runs -> split at common function words, then character bigrams (unigram for 1-char runs).
"""
import re
import unicodedata

_CJK = r"㐀-䶿一-鿿豈-﫿"
_TOKEN_RE = re.compile(rf"[{_CJK}]+|[a-z0-9]+(?:\.[0-9]+)?")

# Multi-character question / filler phrases removed before bigramming.
CJK_STOP_PHRASES = [
    "为什么", "怎么样", "是否", "什么", "哪些", "哪个", "哪里", "如何", "怎样", "怎么", "多少",
    "请问", "根据", "资料", "文档", "当前", "这些", "那些", "这个", "那个", "关于", "以及",
    "其中", "可以", "进行", "一个", "我们", "他们", "提到", "说明", "认为",
    # task words that describe the request rather than its content
    "比较", "对比", "解释", "说法", "观点", "总结", "描述", "区别", "异同",
]
# Single characters that act as word boundaries.
CJK_STOP_CHARS = set("的了吗呢是和与及或在对被把将也都而并吧啊呀之其")

EN_STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "were", "be",
    "been", "by", "with", "as", "at", "it", "its", "this", "that", "these", "those", "from", "what",
    "which", "who", "whom", "how", "why", "when", "where", "do", "does", "did", "according", "documents",
    "document", "about", "there", "their", "they", "can", "could", "should", "would", "will", "has",
    "have", "had", "not", "no", "any", "all", "than", "then", "into", "also", "between",
}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss") and not word[-2].isdigit():
        return word[:-1]
    return word


def _cjk_tokens(run: str) -> list[str]:
    for phrase in CJK_STOP_PHRASES:
        run = run.replace(phrase, " ")
    segments: list[str] = []
    buf = []
    for ch in run:
        if ch == " " or ch in CJK_STOP_CHARS:
            if buf:
                segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        segments.append("".join(buf))
    out: list[str] = []
    for seg in segments:
        if len(seg) == 1:
            out.append(seg)
        else:
            out.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return out


def tokenize(text: str) -> list[str]:
    text = normalize(text).lower()
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if re.match(rf"[{_CJK}]", tok):
            tokens.extend(_cjk_tokens(tok))
        else:
            tokens.append(_stem(tok))
    return tokens


def content_terms(text: str) -> list[str]:
    """Unique query terms that carry meaning (stopwords and lone CJK characters removed)."""
    seen: dict[str, None] = {}
    for tok in tokenize(text):
        if tok in EN_STOPWORDS:
            continue
        if len(tok) == 1 and re.match(rf"[{_CJK}]", tok):
            continue
        if len(tok) == 1 and tok.isalpha():
            continue
        seen.setdefault(tok, None)
    return list(seen)


def is_cjk(tok: str) -> bool:
    return bool(re.match(rf"[{_CJK}]", tok))


def boundary_bigrams(text: str, present: set[str]) -> set[str]:
    """CJK bigrams that straddle a word boundary: absent from the corpus, and overlapping a
    neighbouring bigram that IS a corpus term (e.g. 故障|障时|时轴|轴承 -> 障时, 时轴).
    They are segmentation noise; the inner bigrams of a genuinely unknown word are kept."""
    seq = tokenize(text)
    out = set()
    for i, b in enumerate(seq):
        if not (len(b) == 2 and is_cjk(b) and b not in present):
            continue
        a = seq[i - 1] if i > 0 else ""
        c = seq[i + 1] if i + 1 < len(seq) else ""
        left = len(a) == 2 and a in present and a[1] == b[0]
        right = len(c) == 2 and c in present and b[1] == c[0]
        if left or right:
            out.add(b)
    return out


def search_text(text: str) -> str:
    return " ".join(tokenize(text))


def tsquery_or(terms: list[str]) -> str:
    """Build an OR tsquery string; tokens only contain [a-z0-9.] or CJK so they are safe."""
    safe = [t.replace("'", "") for t in terms if t]
    return " | ".join(f"'{t}'" for t in safe)


def compact(text: str) -> str:
    """Whitespace-insensitive form used when verifying quotes against source text."""
    return re.sub(r"\s+", "", normalize(text)).lower()
