def build_review_analytics(aspects):
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for aspect in aspects:
        sentiment = aspect["sentiment"]
        counts[sentiment] += aspect["mention_count"]
    total = sum(counts.values())
    percentages = {
        f"{sentiment}_percent": round(count / total * 100) if total else 0
        for sentiment, count in counts.items()
    }
    strengths = [
        aspect["aspect"] for aspect in sorted(
            (item for item in aspects if item["sentiment"] == "positive"),
            key=lambda item: (-item["mention_count"], -item["score"]),
        )[:5]
    ]
    weaknesses = [
        aspect["aspect"] for aspect in sorted(
            (item for item in aspects if item["sentiment"] == "negative"),
            key=lambda item: (-item["mention_count"], item["score"]),
        )[:5]
    ]
    return {
        **percentages,
        "total_mentions": total,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "top_aspects": sorted(aspects, key=lambda item: (-item["mention_count"], item["aspect"]))[:8],
    }
