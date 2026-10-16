import re
from collections import Counter
from math import sqrt

from services.sentiment import ASPECTS, _sentences


STOP_WORDS = set("""
a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further
had has have having he her here hers herself him himself his how i if in into is it its
itself me more most my myself nor of off on once only or other our ours ourselves out over
own same she should so some such than that the their theirs them themselves then there these
they this those through to too under until up very was we were what when where which while
who whom why will with would you your yours yourself yourselves
""".split())

WORD_PATTERN = re.compile(r"[a-z][a-z'-]{2,}")
SUMMARY_SENTENCE_LIMIT = 3
SUMMARY_MAX_LENGTH = 900


def _tokens(text):
    return [
        word for word in WORD_PATTERN.findall(text.lower())
        if word not in STOP_WORDS
    ]


def _topics(text):
    words = WORD_PATTERN.findall(text.lower())
    counts = Counter(word for word in words if word not in STOP_WORDS)
    for aspect, aliases in ASPECTS.items():
        phrase_count = sum(
            len(re.findall(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text.lower()))
            for alias in aliases
            if " " in alias
        )
        if phrase_count:
            counts[aspect] += phrase_count * 2
    return [word for word, _ in counts.most_common(6)]


def _extract_summary(text):
    sentences = _sentences(text)
    candidates = []
    for index, sentence in enumerate(sentences):
        tokens = _tokens(sentence)
        if len(tokens) < 4:
            continue
        candidates.append((index, sentence, tokens))

    if not candidates:
        return ""

    frequency = Counter(token for _, _, tokens in candidates for token in set(tokens))
    ranked = []
    for index, sentence, tokens in candidates:
        score = sum(frequency[token] for token in set(tokens)) / sqrt(len(set(tokens)))
        if index == 0:
            score *= 1.15
        ranked.append((score, index, sentence, set(tokens)))

    selected = []
    remaining = ranked[:]
    while remaining and len(selected) < SUMMARY_SENTENCE_LIMIT:
        best = max(
            remaining,
            key=lambda item: (
                item[0] - max(
                    (
                        len(item[3] & picked[3]) / max(len(item[3] | picked[3]), 1)
                        for picked in selected
                    ),
                    default=0,
                ) * item[0] * 0.7,
                -item[1],
            ),
        )
        selected.append(best)
        remaining.remove(best)

    summary = " ".join(item[2] for item in sorted(selected, key=lambda item: item[1]))
    return summary[:SUMMARY_MAX_LENGTH]


def summarize_content(text, aspects, review_mode):
    summary = _extract_summary(text) or text[:300]
    topics = _topics(text)
    if review_mode:
        positive = [item["aspect"] for item in aspects if item["sentiment"] == "positive"]
        negative = [item["aspect"] for item in aspects if item["sentiment"] == "negative"]
        strengths = positive[:5]
        weaknesses = negative[:5]
        recommendation = (
            "Consider this option if its reported strengths match your priorities."
            if positive and not negative else
            "Compare the reported strengths and drawbacks against your needs before deciding."
            if positive else
            "Review additional independent feedback before making a decision."
        )
        insight = (
            f"Feedback most often highlights {', '.join(strengths[:3]) or 'no clear strengths'}"
            f"{'; concerns include ' + ', '.join(weaknesses[:3]) if weaknesses else ''}."
        )
        return {
            "executive_summary": summary,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendation": recommendation,
            "business_insight": insight,
            "topics": topics,
        }
    return {
        "executive_summary": summary,
        "strengths": [],
        "weaknesses": [],
        "recommendation": "Use the summary and topics as a starting point, then consult the full source for context.",
        "business_insight": "This page was treated as informational content; review sentiment metrics are not applicable.",
        "topics": topics,
    }
