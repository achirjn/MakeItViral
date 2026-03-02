# Module 2 Complete Documentation Index

## Overview
This document provides a comprehensive index of all Module 2 documentation files. Each document contains line-by-line explanations of the codebase to ensure complete understanding and prevent surprises in production.

---

## Documentation Files

### 1. Core Worker System
**File**: `docs/module2_worker_detailed.md`
**Content**: Complete line-by-line documentation of the worker system
- `run_once()`: Main processing function with transaction management
- `execute_extractor_dag()`: DAG execution with dependency resolution
- `run_extractor_with_logging()`: Extractor execution wrapper
- Error handling, cooldown logic, and resource management
- Integration patterns and failure scenarios

### 2. Extractor Framework and Implementations
**File**: `docs/module2_extractors_detailed.md`
**Content**: Detailed documentation of all extractors
- BaseExtractor abstract class and ExtractorResult dataclass
- VideoFetcherExtractor: yt-dlp integration with authentication
- VideoProbeExtractor: ffprobe metadata extraction
- FrameSamplerExtractor: ffmpeg frame extraction
- Common patterns, dependency resolution, and error handling

### 3. Context Management and Cleanup
**File**: `docs/module2_context_cleanup_detailed.md`
**Content**: Complete documentation of state management
- ExtractionContext dataclass with all fields and lifecycle
- Temporary directory creation and management
- Remote inference result storage fields
- Cleanup system with file removal and error handling
- Resource isolation and security considerations

### 4. Projection Engine and Remote Inference
**File**: `docs/module2_projections_inference_detailed.md`
**Content**: Detailed explanation of scoring and ML systems
- Projection engine: heuristic scoring, LLM fusion, confidence calculation
- Remote inference client: HTTP calls, retries, validation
- RemoteInferenceExtractor: centralized ML processing
- Score formulas, normalization, and integration patterns

### 5. Scheduler and Job Fetcher
**File**: `docs/module2_scheduler_jobfetcher_detailed.md`
**Content**: Complete job distribution system documentation
- Scheduler: PENDING → READY_FOR_PROCESSING transitions
- Job fetcher: Row-level locking and claim logic
- Priority calculations, batch processing, and race condition handling
- Performance tuning and monitoring considerations

### 6. Persistence Layer and Database Models
**File**: `docs/module2_persistence_database_detailed.md`
**Content**: Comprehensive database and persistence documentation
- Database models: Creator, Reel, and all feature tables
- Persistence layer: Upsert logic, transaction management
- Schema design, indexes, and migration strategy
- Performance optimization and error handling

---

## How to Use This Documentation

### For New Team Members
1. Start with `module2_worker_detailed.md` to understand the main processing flow
2. Read `module2_context_cleanup_detailed.md` to understand state management
3. Review `module2_extractors_detailed.md` to understand individual processing steps
4. Study `module2_projections_inference_detailed.md` to understand scoring logic
5. Read `module2_scheduler_jobfetcher_detailed.md` to understand job distribution
6. Review `module2_persistence_database_detailed.md` to understand data storage

### For Debugging Production Issues
1. **Worker crashes**: Check `module2_worker_detailed.md` for error handling patterns
2. **Extractor failures**: Review `module2_extractors_detailed.md` for specific extractor logic
3. **Resource leaks**: Check `module2_context_cleanup_detailed.md` for cleanup procedures
4. **Scoring issues**: Review `module2_projections_inference_detailed.md` for calculation logic
5. **Job distribution problems**: Check `module2_scheduler_jobfetcher_detailed.md`
6. **Database issues**: Review `module2_persistence_database_detailed.md`

### For System Modifications
1. **Adding new extractors**: Follow patterns in `module2_extractors_detailed.md`
2. **Modifying scoring logic**: Update formulas in `module2_projections_inference_detailed.md`
3. **Changing database schema**: Follow patterns in `module2_persistence_database_detailed.md`
4. **Updating job flow**: Modify worker logic in `module2_worker_detailed.md`

---

## Key Cross-Cutting Concepts

### 1. Error Handling Strategy
- **Critical failures**: Abort entire job (video download, probe)
- **Non-critical failures**: Log and continue (OCR, LLM hook)
- **Transaction management**: Rollback on any error, commit only on success
- **Resource cleanup**: Guaranteed cleanup in finally blocks

### 2. State Management
- **ExtractionContext**: Central state container for each job
- **Temporary isolation**: Each job gets unique temporary directory
- **Result storage**: All extractor results stored in context.intermediate_outputs
- **Cleanup**: Automatic removal of all temporary files

### 3. Dependency Resolution
- **DAG execution**: Topological sorting ensures correct order
- **Parallel execution**: Independent extractors run concurrently
- **Failure propagation**: Failed dependencies cause downstream skipping
- **Critical path**: Essential extractors must succeed

### 4. Performance Optimization
- **Batch processing**: Database operations in batches
- **Async I/O**: Non-blocking operations for external calls
- **Connection pooling**: Efficient database connection management
- **Indexing strategy**: Optimized database queries

### 5. Monitoring and Observability
- **Structured logging**: All logs include reel_id context
- **Performance metrics**: Duration, counts, and success rates
- **Health checks**: System status and backlog monitoring
- **Error tracking**: Detailed error logging with context

---

## Common Production Scenarios

### 1. Normal Processing Flow
```
Scheduler → Job Fetcher → Worker → Extractors → Projections → Persistence → Cleanup
```

### 2. Error Recovery Flow
```
Error Detection → Transaction Rollback → Cleanup → Error Logging → Retry/Skip
```

### 3. Resource Management Flow
```
Context Creation → Temporary Directory → File Operations → Cleanup → Directory Removal
```

### 4. Database Interaction Flow
```
Session Creation → Operations → Commit/Rollback → Session Closure
```

---

## Configuration and Tuning

### 1. Performance Tuning
- **Batch sizes**: Adjust based on database capacity
- **Timeouts**: Configure based on network latency
- **Retry logic**: Exponential backoff for resilience
- **Connection pooling**: Optimize for concurrent load

### 2. Feature Flags
- **Remote inference**: Enable/disable external ML services
- **LLM integration**: Control OpenAI API usage
- **Heavy extractors**: Skip resource-intensive operations
- **Debug logging**: Enable detailed tracing

### 3. Environment Variables
- **Database URL**: Connection configuration
- **Remote inference URL**: ML service endpoint
- **OpenAI API key**: LLM service authentication
- **Log level**: Control verbosity

---

## Security Considerations

### 1. Data Protection
- **No sensitive data in logs**: Only metadata and counts
- **Temporary file security**: Isolated directories with permissions
- **Database access**: Principle of least privilege
- **API security**: Authentication and rate limiting

### 2. Input Validation
- **Parameter validation**: All inputs validated before processing
- **SQL injection prevention**: Parameterized queries only
- **File validation**: Check file types and sizes
- **URL validation**: Verify external resource URLs

### 3. Resource Limits
- **File size limits**: Prevent disk space exhaustion
- **Processing timeouts**: Prevent hanging operations
- **Memory limits**: Control resource usage
- **Rate limiting**: Prevent abuse of external services

---

## Troubleshooting Guide

### 1. Common Issues and Solutions

#### Worker Not Processing Jobs
- **Check**: Scheduler status and reel counts
- **Verify**: Database connectivity and indexes
- **Action**: Run scheduler manually, check logs

#### Extractor Failures
- **Check**: External dependencies (yt-dlp, ffmpeg)
- **Verify**: File permissions and disk space
- **Action**: Update dependencies, check error logs

#### Remote Inference Timeouts
- **Check**: Network connectivity to inference service
- **Verify**: Service availability and response times
- **Action**: Increase timeouts, check service health

#### Database Performance Issues
- **Check**: Query performance and indexes
- **Verify**: Connection pool configuration
- **Action**: Add indexes, tune pool settings

### 2. Log Analysis Patterns

#### Success Patterns
```
job_claimed → dag_started → projections_computed → persistence_success → job_completed
```

#### Failure Patterns
```
extractor_failed → rollback_triggered → cleanup_completed
```

#### Performance Patterns
```
extractor_success (duration_s=X.XXX) → persistence_success
```

---

## Future Enhancements

### 1. Scalability Improvements
- **Horizontal scaling**: Multiple worker instances
- **Queue management**: Redis/RabbitMQ for job distribution
- **Load balancing**: Intelligent job assignment
- **Caching**: Redis for frequently accessed data

### 2. Feature Enhancements
- **Additional extractors**: More ML models and analysis
- **Real-time processing**: Streaming analysis capabilities
- **Advanced projections**: More sophisticated scoring algorithms
- **Export capabilities**: Data export and reporting

### 3. Operational Improvements
- **Health monitoring**: Comprehensive system health checks
- **Automated recovery**: Self-healing capabilities
- **Performance tuning**: Automatic optimization based on metrics
- **Security enhancements**: Additional security layers

---

This documentation set provides complete understanding of the Module 2 codebase. Each file contains detailed line-by-line explanations to ensure you know exactly what is happening at every step, preventing surprises in production environments.
