"""S-Index (DataRank) — data-sharing influence metric for scholarly works.

DataRank is a Personalized PageRank variant where the personalization vector
is proportional to direct data-sharing evidence.  A paper's score reflects
both its own data-sharing activity and the data-sharing activity of the
research it enables.
"""

from doi_metadata.sindex.datarank import compute_datarank_corpus
from doi_metadata.sindex.endowment import compute_endowment
from doi_metadata.sindex.models import DataRankResult, PaperEndowment

__all__ = [
    "compute_datarank_corpus",
    "compute_endowment",
    "DataRankResult",
    "PaperEndowment",
]
