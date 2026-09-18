"""Seed three practical starter blog posts."""

from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision = "20260918_0012"
down_revision = "20260918_0011"
branch_labels = None
depends_on = None


POSTS = [
    {
        "id": UUID("6a3a9242-3be7-4dd3-b7cf-79d3e0a8f201"),
        "slug": "five-questions-to-ask-your-sales-data",
        "content": {
            "title": "Five questions to ask your sales data every month",
            "excerpt": "A practical monthly review that helps small teams find changes in revenue, customers, products, and regions before they become expensive surprises.",
            "author": "Tatparya team",
            "cover_image": None,
            "cover_alt": None,
            "sections": [
                {
                    "heading": "Start with the change, not the total",
                    "body": "A total tells you where the business finished. A comparison tells you what changed. Begin by comparing revenue with the previous month and the same period last year. Then check whether the change came from more orders, higher order values, or a different mix of products.\n\nThis first question gives the rest of the review a clear direction instead of turning it into a search through every available metric.",
                },
                {
                    "heading": "Find where performance moved",
                    "body": "Compare regions, products, customer groups, and sales channels. Look for the areas that contributed most to growth and the areas that lost momentum. A small percentage decline in a large region may matter more than a large percentage decline in a very small one.\n\nAsk for both the amount and percentage contribution so the comparison stays in context.",
                },
                {
                    "heading": "Check whether growth is healthy",
                    "body": "Revenue can rise while profitability weakens. Review discounts, units sold, and marketing spend beside revenue. If sales increased only after much deeper discounts or substantially higher spending, the result may be less valuable than it first appears.\n\nTreat relationships as signals to investigate. They do not automatically prove that one activity caused another.",
                },
                {
                    "heading": "Finish with a decision",
                    "body": "A useful monthly review should end with a small number of actions. Protect the strongest segment, investigate the weakest meaningful area, and define one experiment for the next period. Assign an owner and a date for reviewing the result.\n\nThis turns analysis into an operating habit instead of another report that is read once and forgotten.",
                },
            ],
        },
    },
    {
        "id": UUID("5067bd22-e995-437f-a691-f024f0e8e202"),
        "slug": "choose-the-right-chart-for-business-data",
        "content": {
            "title": "How to choose a chart your team can understand",
            "excerpt": "Use the question and the shape of the data—not decoration—to select a visual that makes the business answer easier to see.",
            "author": "Tatparya team",
            "cover_image": None,
            "cover_alt": None,
            "sections": [
                {
                    "heading": "Begin with the business question",
                    "body": "The best chart is the one that answers the question with the least effort. Before choosing a visual, decide whether you need to compare categories, follow a change over time, show contribution to a total, or understand the relationship between two measures.\n\nIf the question is unclear, adding more visual detail rarely helps.",
                },
                {
                    "heading": "Use bars for clear comparisons",
                    "body": "Bar charts work well when comparing products, branches, customer groups, or regions. Sort the values when ranking matters and keep category labels readable. Horizontal bars are often better for long names, while vertical bars work well for a smaller set of short labels.",
                },
                {
                    "heading": "Use lines for changes over time",
                    "body": "Line charts help people see direction, turning points, and unusual periods. Keep dates in chronological order and avoid adding too many lines to the same chart. If several categories must be compared, highlight the most important series and reduce visual emphasis on the rest.",
                },
                {
                    "heading": "Use part-to-whole visuals selectively",
                    "body": "A pie or donut chart can explain contribution when there are only a few categories and they form a meaningful total. When there are many categories or values are close together, a sorted bar chart will usually be easier to compare.\n\nAlways include labels or a clear legend, and make sure the same numbers appear in the report and the on-screen chart.",
                },
            ],
        },
    },
    {
        "id": UUID("90c84f62-6ea2-40cb-bfe7-31cbfdb25303"),
        "slug": "turn-analysis-into-business-action",
        "content": {
            "title": "From analysis to action: a simple decision framework",
            "excerpt": "A straightforward way to turn findings into focused recommendations, responsible experiments, and measurable next steps.",
            "author": "Tatparya team",
            "cover_image": None,
            "cover_alt": None,
            "sections": [
                {
                    "heading": "Separate evidence from explanation",
                    "body": "Start by writing down what the data directly shows: which measure changed, by how much, during which period, and in which business area. Keep possible explanations separate until they are supported by additional evidence.\n\nThis distinction prevents a plausible story from being mistaken for a verified cause.",
                },
                {
                    "heading": "Prioritize by value and confidence",
                    "body": "Not every finding deserves immediate action. Estimate the value of responding, the confidence you have in the evidence, and the effort required. High-value findings supported by reliable data should move first. Low-confidence findings may need a smaller investigation before a wider decision.",
                },
                {
                    "heading": "Turn recommendations into tests",
                    "body": "A recommendation becomes useful when it names the action, the intended outcome, the responsible owner, and the review date. When the cause is uncertain, use a controlled and reversible experiment. For example, test a promotion in one comparable customer group before extending it to every customer.",
                },
                {
                    "heading": "Measure the result consistently",
                    "body": "Choose the success measure before starting the action. Record the baseline, the time window, and any important constraints. Review the result using the same definition each time.\n\nIf the expected improvement does not appear, keep the learning. A well-measured unsuccessful test is more valuable than an unmeasured change that only appears successful.",
                },
            ],
        },
    },
]


def upgrade():
    content_entries = sa.table(
        "content_entries",
        sa.column("id", sa.Uuid()),
        sa.column("content_type", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("status", sa.String()),
        sa.column("content", sa.JSON()),
        sa.column("updated_by", sa.Uuid()),
    )
    op.bulk_insert(
        content_entries,
        [
            {
                "id": post["id"],
                "content_type": "blog",
                "slug": post["slug"],
                "status": "published",
                "content": post["content"],
                "updated_by": None,
            }
            for post in POSTS
        ],
    )


def downgrade():
    op.execute(
        sa.text(
            "DELETE FROM content_entries WHERE content_type = 'blog' "
            "AND slug IN ('five-questions-to-ask-your-sales-data', "
            "'choose-the-right-chart-for-business-data', "
            "'turn-analysis-into-business-action')"
        )
    )
