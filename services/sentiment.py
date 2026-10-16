import re
from collections import defaultdict


ASPECTS = {
    "battery": ("battery", "battery life", "charge", "charging"),
    "price": ("price", "cost", "expensive", "affordable", "value", "overpriced"),
    "quality": ("quality", "build", "material", "durability", "durable"),
    "performance": ("performance", "speed", "fast", "slow", "responsive"),
    "design": ("design", "look", "appearance", "style", "beautiful"),
    "camera": ("camera", "photo", "picture", "video quality"),
    "display": ("display", "screen", "resolution", "brightness"),
    "delivery": ("delivery", "shipping", "arrived", "packaging"),
    "customer service": ("customer service", "support", "staff", "representative", "help desk"),
    "food": ("food", "meal", "menu", "taste", "flavor", "portion"),
    "cleanliness": ("cleanliness", "clean", "hygiene", "room was spotless"),
    "comfort": ("comfort", "comfortable", "bed", "seating", "ergonomic"),
    "location": ("location", "located", "neighborhood", "accessibility"),
    "usability": ("usability", "easy to use", "intuitive", "interface", "user-friendly"),
    "features": ("feature", "functionality", "options", "capability"),
    "reliability": ("reliability", "reliable", "crash", "bug", "broke", "failure"),
    "staff": ("staff", "team", "employees", "waiter", "reception"),
    "booking": ("booking", "reservation", "check-in", "check in"),
    "sound": ("sound", "audio", "speaker", "volume", "noise"),
}
POSITIVE = {
    "amazing": 2, "awesome": 2, "best": 2, "excellent": 2, "fantastic": 2, "great": 2,
    "love": 2, "perfect": 2, "wonderful": 2, "good": 1, "happy": 1, "helpful": 1,
    "impressive": 2, "recommend": 1, "satisfied": 2, "smooth": 1, "beautiful": 1,
    "comfortable": 1, "clean": 1, "delicious": 2, "easy": 1, "fast": 1, "friendly": 1,
    "reliable": 1, "worth": 1, "durable": 1, "responsive": 1, "sharp": 1,
    "quickly": 1, "helpful": 1, "welcoming": 1, "tasty": 1, "quiet": 1,
}
NEGATIVE = {
    "awful": -2, "bad": -1, "boring": -1, "broken": -2, "disappointing": -2,
    "disappointed": -2, "expensive": -1, "hate": -2, "horrible": -2, "poor": -1,
    "terrible": -2, "unusable": -2, "waste": -2, "worst": -2, "slow": -1,
    "difficult": -1, "hard": -1, "late": -1, "rude": -2, "dirty": -2, "noisy": -1,
    "unreliable": -2, "overpriced": -2, "faulty": -2, "crash": -2, "crashes": -2,
    "high": -1, "uncomfortable": -2, "stale": -1, "cold": -1, "long": -1,
    "unhelpful": -1, "flimsy": -2, "unresponsive": -2,
}
NEGATORS = {"not", "never", "no", "isn't", "wasn't", "aren't", "didn't", "don't", "hardly"}
INTENSIFIERS = {"very": 1.5, "really": 1.4, "extremely": 2, "incredibly": 1.8, "too": 1.4}


def _sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _sentiment_score(sentence):
    words = re.findall(r"[a-z']+", sentence.lower())
    score = 0.0
    for index, word in enumerate(words):
        value = POSITIVE.get(word, NEGATIVE.get(word, 0))
        if not value:
            continue
        window = words[max(0, index - 3):index]
        if any(negator in window for negator in NEGATORS):
            value *= -1
        multiplier = next((INTENSIFIERS[token] for token in reversed(window) if token in INTENSIFIERS), 1)
        score += value * multiplier
    return score


def analyze_aspects(text):
    collected = defaultdict(lambda: {"scores": [], "evidence": []})
    for sentence in _sentences(text):
        lower = sentence.lower()
        clauses = [
            clause.strip()
            for clause in re.split(r"\b(?:but|whereas|while)\b|,\s*and\b|\band\b", lower)
            if clause.strip()
        ]
        for aspect, aliases in ASPECTS.items():
            aspect_clauses = [
                clause for clause in clauses
                if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", clause) for alias in aliases)
            ]
            score = sum(_sentiment_score(clause) for clause in aspect_clauses)
            if not aspect_clauses:
                continue
            item = collected[aspect]
            item["scores"].append(score)
            if len(item["evidence"]) < 3:
                item["evidence"].append(sentence[:300])
    results = []
    for aspect, item in collected.items():
        score = sum(item["scores"]) / len(item["scores"])
        sentiment = "positive" if score > 0.25 else "negative" if score < -0.25 else "neutral"
        results.append({
            "aspect": aspect,
            "sentiment": sentiment,
            "score": round(max(-1, min(1, score / 4)), 2),
            "mention_count": len(item["scores"]),
            "evidence": item["evidence"],
        })
    return sorted(results, key=lambda item: (-item["mention_count"], item["aspect"]))
