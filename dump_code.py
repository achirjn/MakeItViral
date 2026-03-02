import os

files = [
    "module2\\context.py",
    "module2\\logging_config.py",
    "module2\\config.py",
    "module2\\cleanup.py",
    "module2\\job_fetcher.py",
    "module2\\remote_inference.py",
    "module2\\planner.py",
    "module2\\engagement_lifecycle.py",
    "module2\\engagement_updater.py",
    "module2\\extractors\\base.py",
    "module2\\extractors\\registry.py",
    "module2\\extractors\\video_fetcher.py",
    "module2\\extractors\\video_probe.py",
    "module2\\extractors\\frame_sampler.py",
    "module2\\extractors\\motion.py",
    "module2\\extractors\\audio.py",
    "module2\\extractors\\ocr.py",
    "module2\\extractors\\hook.py",
    "module2\\extractors\\llm_hook.py",
    "module2\\extractors\\transcript.py",
    "module2\\extractors\\embedding.py",
    "module2\\extractors\\visual_embedding.py",
    "module2\\projections\\engine.py",
    "module2\\projections\\neighbor_similarity.py",
    "module2\\worker.py",
    "module2\\persistence.py",
    "db\\module2_schema.sql",
    "db\\module2_models.py",
    "db\\migrations\\003_dataset_hardening.sql",
    "db\\migrations\\004_pgvector_hardening.sql",
    "db\\migrations\\005_clip_embedding_addition.sql",
    "db\\migrations\\006_engagement_lifecycle.sql",
    "db\\migrations\\007_retry_cap.sql",
    "docs\\engagement_lifecycle_system.md",
    "colab_inference_server.py",
]

base = "d:\\MakeItViral"
out_path = os.path.join(base, "module2_codebase_dump.txt")

with open(out_path, "w", encoding="utf-8") as out:
    out.write("MODULE 2 - FULL CODEBASE DUMP\n")
    out.write("=" * 80 + "\n\n")
    for f in files:
        full = os.path.join(base, f)
        if not os.path.isfile(full):
            out.write("=" * 80 + "\n")
            out.write(f + " (FILE NOT FOUND)\n")
            out.write("=" * 80 + "\n\n")
            continue
        with open(full, encoding="utf-8") as fh:
            content = fh.read()
        out.write("=" * 80 + "\n")
        out.write(f + "\n")
        out.write("=" * 80 + "\n\n")
        out.write(content)
        out.write("\n\n")

print("Done. Written to " + out_path)
