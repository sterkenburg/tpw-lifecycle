# Python security source builds

The normal Docker build reconstructs the Python runtime and application from
source, preserving the production package versions in requirements-runtime.txt.
The local tpw-lifecycle distribution is installed without dependency resolution.
SHA-pinned official Brotli sources rebuild Pillow's actual private decoder/common
libraries under their existing SONAMEs. Actual version, valid/malformed decode,
image controls and both CA stores are checked during every build with python -I.
Unrecognized private-library versions fail closed and need a reviewed update.
Only application/config/jobs and build inputs enter the allowlisted build context.

Cloud Build builds a unique image, pushes it, reads its immutable digest, and
updates only tpw-lifecycle-daily's image configuration. It never executes the job
or changes runtime environment, scheduler, CPU or email-dry-run settings. The
normal job command override remains python jobs/daily_pipeline.py; the image's
API/dashboard defaults are preserved for local use.

For this integration, merge with [skip ci] to honor the existing main-trigger
hold. Release the independently tested AMD64 image by immutable digest, compare
job settings and last execution before/after, and confirm no matching automatic
Cloud Build ran. Keep the previous secure image digest for rollback. Subsequent
normal Cloud Builds use these source security gates before a job image update.
