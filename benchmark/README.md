# Benchmark Pipeline

Continuous, self-expanding benchmark dataset for the DOI metadata aggregation system. Starts with ~350 curated seed DOIs, then automatically grows to 10K+ by discovering new DOIs from author profiles, citation graphs, and top-cited queries.

## Quick Start

```bash
# Dry run — load seeds, show queue stats, don't fetch
python -m benchmark.pipeline --dry-run

# Fetch 5 DOIs (quick smoke test)
python -m benchmark.pipeline --max-total 5 --no-expand

# Fetch 1K DOIs (~1 hour)
python -m benchmark.pipeline --max-total 1000

# Overnight run — expand to 10K
python -m benchmark.pipeline --max-total 10000 --expand

# Unlimited — continuous until queue empty or killed
python -m benchmark.pipeline --expand

# Check progress anytime
python -m benchmark.pipeline --status
```

## Architecture

```
corpus.yaml (350 seed DOIs)
       │
       ▼
   queue.db (SQLite)     ←──── expanders discover new DOIs
   pending → in_progress → done
       │
       ▼
   orchestrator.lookup(doi)  →  results/{hash}.json
       │
       ▼
   expanders (every N DOIs):
     • top_cited.py      — OpenAlex top-cited papers → Tier 4
     • author_works.py   — researcher complete works → Tier 5
     • citation_graph.py — references from results   → Tier 4
```

**Key properties:**
- **Checkpoint everything** — kill and restart anytime, picks up from queue.db
- **Never re-fetch** — DOIs in `done` status are skipped
- **Priority ordering** — Tier 1 > 2 > 3 > 4 > 5 (seeds first)
- **Self-expanding** — expanders discover new DOIs automatically
- **Deduplication** — unique constraint on DOI, no duplicates

## Tier Structure

| Tier | Description | Source | Priority | Count |
|------|------------|--------|----------|-------|
| 1 | Edge cases (retracted, old, special chars, etc.) | corpus.yaml | 1 | ~38 |
| 2 | Landmark papers (genomics, cancer, AI/ML, etc.) | corpus.yaml | 3 | ~170 |
| 3 | Researcher key DOIs + ORCID profiles | corpus.yaml | 2 | ~90 |
| 4 | Top-cited papers + citation graph | auto-expanded | 8-9 | unlimited |
| 5 | Author complete works | auto-expanded | 9 | unlimited |

## CLI Options

```
--max-total N          Stop after N DOIs fetched (0 = unlimited)
--max-hours H          Stop after H hours (0 = unlimited)
--concurrency C        Parallel DOI fetches (default: 3)
--expand / --no-expand Enable/disable auto-expansion (default: enabled)
--expand-interval N    Run expanders every N completed DOIs (default: 50)
--tiers 1,2,3          Which seed tiers to load (default: "1,2,3")
--dry-run              Load seeds, show queue stats, don't fetch
--status               Show current queue.db stats and exit
--results-dir DIR      Where to write JSON results
```

## Corpus Categories

### Tier 2 Landmark Papers
- **Genomics & Population** — Human Genome, gnomAD, 1000 Genomes, UK Biobank, HapMap, TOPMed, FinnGen
- **Cancer Genomics** — TCGA Pan-Cancer, ICGC/PCAWG, COSMIC, CCLE, DepMap, CPTAC, GENIE
- **Functional Genomics** — ENCODE, GTEx, Roadmap Epigenomics, FANTOM5, Human Cell Atlas, CRISPR
- **Structural Biology** — AlphaFold2, UniProt, PDB, ESMFold, RoseTTAFold, ColabFold
- **Clinical Data** — MIMIC-III/IV/CXR, CheXpert, eICU, fastMRI, ISIC
- **Methods & Tools** — BWA, samtools, BLAST, STAR, GATK, DESeq2, Seurat, Scanpy, Nextflow
- **AI/ML** — Transformers, BERT, GPT-3, ResNet, GAN, ImageNet, U-Net, XGBoost
- **Data Ethics & Policy** — FAIR Principles, s-index, Toronto Statement, replication crisis
- **Physics & Cross-discipline** — Higgs boson, gravitational waves, black hole image

### Tier 3 Researchers (~45 profiles)
Researchers with ORCIDs whose complete works are auto-fetched by the author_works expander:
- **Cancer genomics**: Kuan-Lin Huang, Li Ding, Matthew Meyerson, Elaine Mardis
- **Genomics**: Eric Lander, Mark Daly, Daniel MacArthur, Ewan Birney, Stacey Gabriel
- **FAIR & Open Science**: Barend Mons, Mark Wilkinson, Michel Dumontier, Susanna-Assunta Sansone, Scott Edmunds, Phil Bourne
- **Bibliometrics**: John Ioannidis, Lutz Bornmann, Ludo Waltman, Vincent Lariviere
- **NIH Leaders**: Josh Gordon, Eric Green, Francis Collins, Michael Lauer
- **AI/ML**: Demis Hassabis, Yoshua Bengio, Yann LeCun, Jennifer Doudna
- **Single Cell & Functional**: Aviv Regev, Fabian Theis, Heng Li, Pardis Sabeti

## Validation & Reporting

```bash
# Validate results
python -m benchmark.validation

# Generate text report
python -m benchmark.report

# Generate markdown report
python -m benchmark.report --format markdown --output report.md
```

## File Layout

```
benchmark/
├── corpus.yaml              # Master seed registry (~350 DOIs + ~45 ORCIDs)
├── pipeline.py              # Continuous runner with SQLite queue
├── queue.db                 # SQLite work queue (auto-created)
├── expanders/
│   ├── top_cited.py         # OpenAlex top-cited discovery
│   ├── author_works.py      # ORCID → all DOIs via OpenAlex
│   └── citation_graph.py    # Extract references from results
├── results/                 # One JSON per DOI (sha256 hash filename)
├── validation.py            # Result verification
├── report.py                # Corpus-wide analytics
└── README.md
```

## How It Grows

| Phase | What happens | Corpus size | Time |
|-------|-------------|-------------|------|
| Start | Load corpus.yaml seeds | ~350 DOIs | instant |
| Hour 1 | Fetch seeds + first expansion | ~1,000 DOIs | ~1 hr |
| Overnight | author_works + top_cited expanders | 5,000–10,000 | 8-12 hrs |
| Days 2-3 | citation_graph expander | 25,000–50,000 | continuous |

## Adding Seeds

Edit `corpus.yaml` to add new DOIs or researchers. The pipeline loads seeds idempotently — existing DOIs are skipped (INSERT OR IGNORE).
