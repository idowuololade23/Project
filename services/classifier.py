import re


PAGE_TYPES = {
    "bible_commentary": (
        "bible commentary", "scripture", "biblical", "gospel", "psalm", "exegesis",
        "book of genesis", "new testament", "old testament", "chapter and verse",
    ),
    "research_article": (
        "research article", "abstract", "methodology", "literature review", "doi",
        "peer-reviewed", "peer reviewed", "study participants", "research findings",
        "statistical analysis", "journal of",
    ),
    "news_article": (
        "breaking news", "news report", "news article", "correspondent", "newsroom",
        "reported on", "according to officials", "press conference", "published on",
    ),
    "discussion_forum": (
        "discussion forum", "forum thread", "reply to this post", "replies",
        "community discussion", "asked:", "question from", "answers",
    ),
    "service_review": (
        "service review", "customer service", "hotel review", "restaurant review",
        "guest review", "booking experience", "stay at the hotel", "dining experience",
        "staff were", "service was",
    ),
    "product_review": (
        "product review", "verified purchase", "pros and cons", "product rating",
        "bought this product", "review of the", "worth the price", "star review",
        "unboxing review",
    ),
    "blog_post": (
        "personal blog", "blog post", "in this post", "on my blog", "subscribe to my",
        "my travel diary", "today i want to", "welcome back to my",
    ),
}

_PATTERNS = {
    page_type: tuple(
        (term, re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)"))
        for term in terms
    )
    for page_type, terms in PAGE_TYPES.items()
}
_SERVICE_CONTEXT = re.compile(
    r"(?<!\w)(?:hotel|restaurant|hospital|clinic|salon|airline|"
    r"customer service|support team|staff|waiter|reception)(?!\w)"
)
_REVIEW_EVIDENCE = re.compile(
    r"(?<!\w)(?:reviews?|ratings?|stars?|recommend(?:ed|ation)?|"
    r"purchase|bought|disappointed|love|loved|hate|hated|pros|cons|"
    r"worth it|customer service|experience|excellent|great|good|poor|"
    r"terrible|friendly|delicious|slow|high|expensive|overpriced|"
    r"comfortable|clean|reliable|amazing|perfect|awful|bad)(?!\w)"
)
_CONTRAST = re.compile(r"(?<!\w)(?:but|however|though|although)(?!\w)")


def _score_page_type(page_type, title, text):
    patterns = _PATTERNS[page_type]
    title_score = sum(
        min(len(pattern.findall(title)), 3) * (3 if " " in term else 1.5)
        for term, pattern in patterns
    )
    body_score = sum(
        min(len(pattern.findall(text)), 8) * (2 if " " in term else 1)
        for term, pattern in patterns
    )
    return title_score + body_score


def classify_content(text, title=""):
    title = title or ""
    text = text or ""
    normalized_title = title.casefold()
    normalized_text = text.casefold()
    scores = {
        page_type: _score_page_type(page_type, normalized_title, normalized_text)
        for page_type in PAGE_TYPES
    }
    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    review_matches = len(_REVIEW_EVIDENCE.findall(normalized_title)) * 2
    review_matches += min(len(_REVIEW_EVIDENCE.findall(normalized_text)), 20)
    service_context = bool(_SERVICE_CONTEXT.search(f"{normalized_title} {normalized_text}"))
    review_evidence = review_matches >= 2 or (
        review_matches >= 1
        and (
            service_context
            or bool(_CONTRAST.search(f"{normalized_title} {normalized_text}"))
        )
    )
    review_type = "service_review" if service_context else "product_review"

    if best_score == 0:
        if review_evidence:
            content_type = review_type
            confidence = min(0.85, 0.53 + review_matches * 0.035)
        else:
            content_type = "blog_post"
            confidence = 0.35
    elif best_type in {"product_review", "service_review"}:
        if review_evidence:
            content_type = review_type if service_context else best_type
            confidence = min(0.94, 0.58 + best_score / (best_score + 12) * 0.32)
        else:
            content_type = "blog_post"
            confidence = 0.35
    elif best_type == "discussion_forum" and review_matches >= 2:
        content_type = review_type
        confidence = min(0.9, 0.55 + best_score / (best_score + 14) * 0.3)
    elif best_score >= 1:
        content_type = best_type
        confidence = min(0.94, 0.55 + best_score / (best_score + 12) * 0.35)
    elif review_evidence:
        content_type = review_type
        confidence = min(0.85, 0.53 + review_matches * 0.035)
    else:
        content_type = "blog_post"
        confidence = 0.35

    return {
        "content_type": content_type,
        "confidence": round(confidence, 2),
        "is_review": content_type in {"product_review", "service_review"},
    }
