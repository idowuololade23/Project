from datetime import datetime, timezone

from database import db


class Analysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.String(64), nullable=True, index=True)
    source_url = db.Column(db.String(2048), nullable=True, index=True)
    extraction_method = db.Column(db.String(20), nullable=False, default="static", server_default="static")
    page_title = db.Column(db.String(500), nullable=True)
    content_type = db.Column(db.String(40), nullable=False, index=True)
    confidence = db.Column(db.Float, nullable=False)
    is_review = db.Column(db.Boolean, nullable=False, default=False, index=True)
    extracted_text = db.Column(db.Text, nullable=False)
    summary = db.Column(db.Text, nullable=False)
    strengths = db.Column(db.JSON, nullable=False, default=list)
    weaknesses = db.Column(db.JSON, nullable=False, default=list)
    recommendation = db.Column(db.Text, nullable=False)
    business_insight = db.Column(db.Text, nullable=False)
    topics = db.Column(db.JSON, nullable=False, default=list)
    positive_percent = db.Column(db.Float, nullable=True)
    neutral_percent = db.Column(db.Float, nullable=True)
    negative_percent = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    aspects = db.relationship(
        "AspectMention",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="AspectMention.mention_count.desc()",
    )


class AspectMention(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey("analysis.id"), nullable=False, index=True)
    aspect = db.Column(db.String(100), nullable=False)
    sentiment = db.Column(db.String(10), nullable=False)
    score = db.Column(db.Float, nullable=False)
    mention_count = db.Column(db.Integer, nullable=False, default=1)
    evidence = db.Column(db.JSON, nullable=False, default=list)

    analysis = db.relationship("Analysis", back_populates="aspects")

    def to_dict(self):
        return {
            "aspect": self.aspect,
            "sentiment": self.sentiment,
            "score": self.score,
            "mention_count": self.mention_count,
            "evidence": self.evidence,
        }
