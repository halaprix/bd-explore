"""Constants and defaults for bd-explore."""

VERSION = "0.1.0"
SCHEMA_VERSION = "1"

DEFAULT_BUDGET_CHARS = 24_000
MIN_BUDGET_CHARS = 100
DEFAULT_SEEDS = 5

DEP_KINDS = {
    "parent-child",
    "discovered-from",
    "blocks",
    "blocked-by",
    "related",
    "relates-to",
    "supersedes",
}

FILTER_KEYS = {"status", "type", "priority", "epic", "id"}
