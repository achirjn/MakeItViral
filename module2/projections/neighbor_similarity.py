from sqlalchemy import text

from module2.logging_config import get_logger


logger = get_logger("projection.neighbor")

MIN_NEIGHBOR_POOL = 1000


def fetch_embedding_neighbors(session, reel_id, embedding_vector, k=5):
    """
    Retrieve k nearest neighbors using pgvector cosine similarity.
    Returns list of dicts with similarity and engagement metrics.

    Cold-start safe: returns [] if embedding pool < MIN_NEIGHBOR_POOL.
    """

    if embedding_vector is None:
        return []

    # Cold-start guard: skip if insufficient embedding pool
    try:
        count_result = session.execute(text("SELECT COUNT(*) FROM reel_embeddings"))
        pool_size = count_result.scalar() or 0
    except Exception:  # noqa: BLE001
        pool_size = 0

    if pool_size < MIN_NEIGHBOR_POOL:
        logger.info(
            "similarity_skipped_cold_start pool_size=%d min_required=%d",
            pool_size,
            MIN_NEIGHBOR_POOL,
            extra={"reel_id": reel_id},
        )
        return []

    logger.debug(
        "neighbor_query_started k=%d pool_size=%d",
        k,
        pool_size,
        extra={"reel_id": reel_id},
    )

    try:
        query = text(
            """
            SELECT
                r.id,
                1 - (e.embedding <=> :embedding) AS similarity,
                r.views,
                r.likes,
                r.comments
            FROM reel_embeddings e
            JOIN reels r ON r.id = e.reel_id
            WHERE r.id != :reel_id
            ORDER BY e.embedding <=> :embedding
            LIMIT :k
            """
        )

        result = session.execute(
            query,
            {
                "embedding": embedding_vector,
                "reel_id": reel_id,
                "k": k,
            },
        )

        neighbors = []
        for row in result:
            neighbors.append(
                {
                    "similarity": float(row.similarity or 0.0),
                    "views": row.views or 0,
                    "likes": row.likes or 0,
                    "comments": row.comments or 0,
                }
            )

        avg_sim = (
            sum(n["similarity"] for n in neighbors) / len(neighbors)
            if neighbors
            else 0.0
        )
        logger.debug(
            "neighbor_count=%d avg_similarity=%.4f",
            len(neighbors),
            avg_sim,
            extra={"reel_id": reel_id},
        )

        return neighbors

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "similarity_query_failed error=%s",
            str(exc)[:80],
            extra={"reel_id": reel_id},
        )
        # failure isolated — trend intelligence optional
        return []
